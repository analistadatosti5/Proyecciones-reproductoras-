"""Acceso a datos: ejecuta las consultas de `consultas.py` y devuelve DataFrames tipados."""

from datetime import date, datetime, time, timedelta

import pandas as pd
import psycopg
import pyodbc

from . import config, consultas, reales
from .db import conectar, conectar_sql_server, mensaje_odbc
from .modelos import DatosReales, DatosReferencia, ErrorBaseDatos

_COLUMNAS_ESTANDAR = [
    "standard_code",
    "age",
    "week_number",
    "bird_consumption",
    "accumulated_bird_consumption",
    "feed_type",
    "mortality_percentage",
    "accumulated_mortality_percentage",
    "stage",
]
_COLUMNAS_NUMERICAS_ESTANDAR = [
    "bird_consumption",
    "accumulated_bird_consumption",
    "mortality_percentage",
    "accumulated_mortality_percentage",
]


def _consultar(conexion: psycopg.Connection, descripcion: str, sql: str, parametros: dict) -> pd.DataFrame:
    """Ejecuta una consulta y devuelve el resultado como DataFrame."""
    try:
        with conexion.cursor() as cursor:
            cursor.execute(sql, parametros)
            columnas = [c.name for c in cursor.description]
            return pd.DataFrame(cursor.fetchall(), columns=columnas)
    except psycopg.Error as exc:
        raise ErrorBaseDatos(f"Falló la consulta de {descripcion}: {str(exc).strip()}") from exc


def codigo_material(feed_type: str) -> int | None:
    """'05670' -> 5670. Devuelve None si el código no es numérico."""
    texto = str(feed_type).strip()
    return int(texto) if texto.isdigit() else None


def cargar_datos_referencia(
    razas: list[str], codigos_granja: list[str], dias: int, codigos_estandar: list[str] | None = None
) -> DatosReferencia:
    """Consulta en las bases PostgreSQL todo lo necesario para proyectar los lotes.

    `codigos_estandar`: estándares que Granjas_BI asigna a los lotes reales, además de los
    que se buscan por raza y sexo.
    """
    with conectar(config.BD_GRANJAS) as conexion:
        parametros = {"codigos": codigos_granja}
        granjas = _consultar(conexion, "granjas", consultas.GRANJAS, parametros)
        nucleos = _consultar(conexion, "núcleos de granja", consultas.NUCLEOS, parametros)

    with conectar(config.BD_ESTANDARES) as conexion:
        encabezados = _consultar(
            conexion,
            "encabezados de estándar",
            consultas.ENCABEZADOS_ESTANDAR,
            {
                "clase": config.CLASE_LOTE_REPRODUCTORAS,
                "razas": razas,
                "sexos": [config.SEXO_HEMBRA, config.SEXO_MACHO],
                "codigos": codigos_estandar or [],
            },
        )
        codigos = encabezados["standard_code"].tolist()
        estandar = pd.DataFrame(columns=_COLUMNAS_ESTANDAR)
        if codigos:
            estandar = _consultar(
                conexion,
                "datos de estándar",
                consultas.DATOS_ESTANDAR,
                {"clase": config.CLASE_LOTE_REPRODUCTORAS, "codigos": codigos, "dias": dias},
            )
    estandar[_COLUMNAS_NUMERICAS_ESTANDAR] = estandar[_COLUMNAS_NUMERICAS_ESTANDAR].astype(float)
    estandar["age"] = estandar["age"].astype(int)

    codigos_alimento = sorted({c for c in map(codigo_material, estandar["feed_type"].unique()) if c is not None})
    materiales: dict[int, str] = {}
    if codigos_alimento:
        with conectar(config.BD_MATERIALES) as conexion:
            filas = _consultar(conexion, "materiales", consultas.MATERIALES, {"codigos": codigos_alimento})
        materiales = dict(zip(filas["code"].astype(int), filas["name"]))

    return DatosReferencia(
        encabezados=encabezados,
        estandar=estandar,
        materiales=materiales,
        granjas=granjas,
        nucleos=nucleos,
    )


# ---------------------------------------------------------------------------
# Granjas_BI (SQL Server): datos reales de los lotes
# ---------------------------------------------------------------------------
_COLUMNAS_DIAS_SUMADAS = [
    "aves_encasetadas",
    "seleccion",
    "mortalidad",
    "mortalidad_transporte",
    "aves_vendidas",
    "aves_sacrificio",
    "aves_agregadas",
    "aves_transferidas",
    "consumo",
]


def _consultar_sql_server(conexion: pyodbc.Connection, descripcion: str, sql: str, parametros: list) -> pd.DataFrame:
    """Ejecuta una consulta en SQL Server y devuelve el resultado como DataFrame."""
    try:
        cursor = conexion.cursor()
        cursor.execute(sql, parametros)
        columnas = [c[0] for c in cursor.description]
        return pd.DataFrame.from_records([tuple(f) for f in cursor.fetchall()], columns=columnas)
    except pyodbc.Error as exc:
        raise ErrorBaseDatos(f"Falló la consulta de {descripcion} en Granjas_BI: {mensaje_odbc(exc)}") from exc


def cargar_datos_reales(lotes_insumo: list[int], hoy: date) -> DatosReales:
    """Consulta en Granjas_BI los lotes de reproductoras activos y los del insumo que ya existen.

    Solo se usan días anteriores a `hoy` y hasta la fecha de corte (último día con carga completa).
    """
    desde = _fecha_sql(hoy - timedelta(days=config.DIAS_HISTORIA_REALES))
    patron = config.PATRON_GRANJA_REPRODUCTORAS
    with conectar_sql_server(config.BD_REALES) as conexion:
        carga = _consultar_sql_server(
            conexion, "carga diaria", consultas.CARGA_DIARIA_REALES, [patron, desde, _fecha_sql(hoy)]
        )
        carga["fecha"] = pd.to_datetime(carga["fecha"])
        carga["cabeceras"] = carga["cabeceras"].astype(int)
        corte = reales.fecha_corte(carga)
        if corte is None:
            return DatosReales.vacios()

        cabeceras = _tipos_cabeceras(
            _consultar_sql_server(
                conexion, "encasetamientos", consultas.CABECERAS_REALES, [desde, _fecha_sql(corte), patron, desde]
            )
        )
        lotes = reales.lotes_a_incluir(cabeceras, corte, lotes_insumo)
        cabeceras = cabeceras[cabeceras["lote"].isin(lotes)].reset_index(drop=True)
        ids = sorted(cabeceras["id_encaseta"].unique())
        dias = pd.DataFrame(columns=["id_encaseta", "fecha", "sexo", "edad", "semana", "linea", "etapa", *_COLUMNAS_DIAS_SUMADAS])
        if ids:
            dias = _consultar_sql_server(
                conexion,
                "registros diarios (DiaReproductora)",
                consultas.DIAS_REALES,
                [",".join(str(i) for i in ids), _fecha_sql(corte)],
            )
    return DatosReales(fecha_corte=corte, carga=carga, cabeceras=cabeceras, dias=_tipos_dias(dias))


def _fecha_sql(fecha: date) -> datetime:
    """Fecha como datetime a medianoche: el controlador ODBC "SQL Server" de Windows no envía parámetros date."""
    return datetime.combine(pd.Timestamp(fecha).date(), time())


def _texto(serie: pd.Series) -> pd.Series:
    return serie.astype("string").str.strip().str.upper().astype(object).where(serie.notna(), None)


def _tipos_cabeceras(cabeceras: pd.DataFrame) -> pd.DataFrame:
    cabeceras = cabeceras.copy()
    for columna in ("granja", "nucleo", "etapa", "sexo", "raza", "codigo_estandar"):
        cabeceras[columna] = _texto(cabeceras[columna])
    for columna in ("fecha_ingreso", "primer_registro", "ultimo_registro"):
        cabeceras[columna] = pd.to_datetime(cabeceras[columna])
    for columna in ("id_encaseta", "lote"):
        cabeceras[columna] = cabeceras[columna].astype("int64")
    for columna in ("cantidad", "mortalidad_transporte"):
        cabeceras[columna] = cabeceras[columna].astype(float).fillna(0.0)
    return cabeceras


def _tipos_dias(dias: pd.DataFrame) -> pd.DataFrame:
    dias = dias.copy()
    dias["fecha"] = pd.to_datetime(dias["fecha"])
    for columna in ("sexo", "linea", "etapa"):
        dias[columna] = _texto(dias[columna])
    for columna in ("id_encaseta", "edad", "semana"):
        dias[columna] = dias[columna].astype("int64")
    for columna in _COLUMNAS_DIAS_SUMADAS:  # consumo llega como Decimal
        dias[columna] = dias[columna].astype(float)
    return dias
