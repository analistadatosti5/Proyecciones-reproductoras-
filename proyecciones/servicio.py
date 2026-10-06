"""Orquestación del proceso completo, independiente de la interfaz gráfica.

    1. Validar parámetros.
    2. Leer y validar el insumo.
    3. Consultar los datos reales en Granjas_BI y unir sus lotes con los del insumo.
    4. Consultar las bases PostgreSQL (una consulta por tabla para todos los lotes).
    5. Validar los lotes contra la información de las bases.
    6. Si no hay errores: calcular la proyección y, por cada sociedad con registros,
       exportar su Excel y agregarle la tabla dinámica (hoja TABLERO) con Excel.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pandas as pd

from . import config, exportador, insumo, proyeccion, reales, repositorio, tabla_dinamica, validaciones
from .modelos import (
    DatosReferencia,
    ErrorExportacion,
    ErrorProyeccion,
    LotesReales,
    Mensaje,
    Nivel,
    ParametrosProyeccion,
)

log = logging.getLogger(__name__)

Informar = Callable[[str], None]


def _sin_informe(_: str) -> None:
    """Callback por defecto cuando no hay interfaz que muestre el avance."""


@dataclass
class ResultadoProceso:
    mensajes: list[Mensaje] = field(default_factory=list)
    archivos: dict[str, Path] = field(default_factory=dict)  # sociedad -> archivo generado
    lotes: int = 0
    lotes_por_sociedad: dict[str, int] = field(default_factory=dict)
    filas: int = 0
    consumo_total_kg: float = 0.0

    @property
    def errores(self) -> list[Mensaje]:
        return [m for m in self.mensajes if m.nivel == Nivel.ERROR]

    @property
    def advertencias(self) -> list[Mensaje]:
        return [m for m in self.mensajes if m.nivel == Nivel.ADVERTENCIA]

    @property
    def exitoso(self) -> bool:
        return not self.errores


@dataclass
class _Preparacion:
    lotes: pd.DataFrame  # lotes del insumo y de Granjas_BI (columna REAL)
    sociedades: pd.Series  # sociedad de cada lote según su granja actual, alineada con `lotes`
    referencia: DatosReferencia | None
    mapa_estandar: dict[tuple[str, str], str]  # (raza, sexo) -> estándar de los lotes del insumo
    lote_sexo_reales: pd.DataFrame  # proyeccion.COLUMNAS_LOTE_SEXO de los lotes de Granjas_BI
    reales: LotesReales | None
    resultado: ResultadoProceso


def ruta_por_sociedad(ruta_salida: Path, sociedad: str) -> Path:
    """Archivo de una sociedad: el nombre elegido con la sociedad al final (..._ORIENTE.xlsx)."""
    ruta_salida = Path(ruta_salida)
    return ruta_salida.with_name(f"{ruta_salida.stem}_{sociedad}{ruta_salida.suffix}")


def validar_insumo(
    ruta_insumo: Path, parametros: ParametrosProyeccion, informar: Informar = _sin_informe, hoy: date | None = None
) -> ResultadoProceso:
    """Ejecuta todas las validaciones sin generar el Excel de resultado."""
    resultado = _preparar(Path(ruta_insumo), parametros, informar, hoy or date.today()).resultado
    informar("Validación terminada.")
    return resultado


def generar_proyeccion(
    ruta_insumo: Path,
    ruta_salida: Path,
    parametros: ParametrosProyeccion,
    informar: Informar = _sin_informe,
    hoy: date | None = None,
) -> ResultadoProceso:
    """Valida, calcula la proyección y genera un Excel por sociedad (ver ruta_por_sociedad).

    Si hay errores no genera ningún archivo.
    """
    ruta_insumo = Path(ruta_insumo)
    rutas = {sociedad: ruta_por_sociedad(ruta_salida, sociedad) for sociedad in config.SOCIEDADES}
    if any(ruta_insumo.resolve() == ruta.resolve() for ruta in rutas.values()):
        raise ErrorProyeccion("El archivo de resultado no puede ser el mismo archivo de insumo.")

    preparacion = _preparar(ruta_insumo, parametros, informar, hoy or date.today())
    resultado = preparacion.resultado
    if not resultado.exitoso:
        informar("Se encontraron errores: no se generó la proyección.")
        return resultado

    informar(f"Calculando la proyección de {len(preparacion.lotes)} lotes...")
    del_insumo = preparacion.lotes[~preparacion.lotes["REAL"]]
    partes = [
        parte
        for parte in (
            proyeccion.lote_sexo_insumo(del_insumo, preparacion.mapa_estandar, parametros),
            preparacion.lote_sexo_reales,
        )
        if not parte.empty  # concat con un DataFrame vacío cambiaría los tipos de las columnas
    ]
    lote_sexo = pd.concat(partes, ignore_index=True)
    base = proyeccion.construir_proyeccion(
        lote_sexo, preparacion.referencia, parametros, preparacion.reales.diario if preparacion.reales else None
    )
    resultado.filas = len(base)
    resultado.consumo_total_kg = float(base["ALIM H"].sum())
    resultado.lotes_por_sociedad = {
        s: int(base.loc[base["SOCIEDAD"] == s, "LOTE"].nunique()) for s in config.SOCIEDADES if (base["SOCIEDAD"] == s).any()
    }

    mensajes = list(resultado.mensajes)  # los avisos de un archivo no van en la hoja del otro
    for sociedad in resultado.lotes_por_sociedad:
        parte = base[base["SOCIEDAD"] == sociedad].reset_index(drop=True)
        _generar_sociedad(preparacion, sociedad, parte, rutas[sociedad], mensajes, informar)
    return resultado


def _generar_sociedad(
    preparacion: _Preparacion,
    sociedad: str,
    base: pd.DataFrame,
    ruta: Path,
    mensajes: list[Mensaje],
    informar: Informar,
) -> None:
    """Exporta la proyección de una sociedad y le agrega la tabla dinámica."""
    resultado = preparacion.resultado
    informar(
        f"Sociedad {sociedad} ({config.SOCIEDADES[sociedad]}): {base['LOTE'].nunique()} lotes. "
        f"Escribiendo el Excel ({len(base):,} registros). Puede tardar unos segundos..."
    )
    exportador.exportar(
        ruta, base, mensajes_de_sociedad(mensajes, preparacion.lotes, preparacion.sociedades, sociedad)
    )

    informar(f"Creando la tabla dinámica (hoja {config.HOJA_TABLA_DINAMICA}) con Excel...")
    try:
        tabla_dinamica.agregar_tabla_dinamica(ruta)
    except ErrorExportacion as exc:
        # La base ya quedó guardada: se entrega sin la tabla dinámica y se avisa.
        log.warning("Tabla dinámica no creada en %s: %s", ruta.name, exc)
        resultado.mensajes.append(
            Mensaje(
                Nivel.ADVERTENCIA,
                "Tabla dinámica",
                f"{exc} El archivo {ruta.name} se generó sin la hoja {config.HOJA_TABLA_DINAMICA}.",
            )
        )
    resultado.archivos[sociedad] = ruta
    log.info("Proyección generada: %s (%s registros)", ruta, len(base))
    informar(f"Archivo generado: {ruta}")


def mensajes_de_sociedad(
    mensajes: list[Mensaje], lotes: pd.DataFrame, sociedades: pd.Series, sociedad: str
) -> list[Mensaje]:
    """Mensajes para la hoja VALIDACIONES de una sociedad: los generales y los de sus lotes.

    Se omiten los que se refieren solo a lotes de otra sociedad (por fila del insumo o por lote).
    """
    ajenos = lotes[sociedades != sociedad]
    filas_ajenas = {int(fila) for fila in ajenos["FILA"].dropna()}
    lotes_ajenos = set(ajenos["LOTE"].astype(str))

    def es_ajeno(mensaje: Mensaje) -> bool:
        if mensaje.fila is not None:
            return mensaje.fila in filas_ajenas
        return bool(mensaje.lote) and set(mensaje.lote.split(", ")) <= lotes_ajenos

    return [m for m in mensajes if not es_ajeno(m)]


def _preparar(ruta_insumo: Path, parametros: ParametrosProyeccion, informar: Informar, hoy: date) -> _Preparacion:
    """Pasos comunes a validar y generar: lectura, consultas y validaciones."""
    _validar_parametros(parametros)

    informar(f"Leyendo el insumo '{ruta_insumo.name}'...")
    lotes_insumo, mensajes = insumo.leer_insumo(ruta_insumo)
    resultado = ResultadoProceso(mensajes=mensajes, lotes=len(lotes_insumo))
    informar(f"Lotes del insumo con datos válidos: {len(lotes_insumo)}.")
    if lotes_insumo.empty:
        return _Preparacion(lotes_insumo.assign(REAL=False), pd.Series(dtype=object), None, {}, pd.DataFrame(), None, resultado)

    informar("Consultando los datos reales en Granjas_BI (SQL Server)...")
    datos_reales = repositorio.cargar_datos_reales(lotes_insumo["LOTE"].tolist(), hoy)
    lotes_reales = reales.consolidar(datos_reales)
    resultado.mensajes.extend(lotes_reales.mensajes)
    lotes, mensajes_union = reales.combinar_lotes(lotes_insumo, lotes_reales)
    resultado.mensajes.extend(mensajes_union)
    resultado.lotes = len(lotes)
    if datos_reales.fecha_corte is not None:
        informar(
            f"Datos reales hasta el {datos_reales.fecha_corte:%d/%m/%Y}: {len(lotes_reales.lotes)} lotes "
            f"({int((lotes['REAL'] & lotes['FILA'].notna()).sum())} del insumo)."
        )

    # Todas las granjas en que han estado los lotes (en los reales, también las anteriores).
    granjas_lote = lotes[["LOTE", "CENTRO GRANJA", "NUCLEO", "REAL"]]
    if not lotes_reales.granjas.empty:
        granjas_lote = pd.concat([granjas_lote, lotes_reales.granjas.assign(REAL=True)], ignore_index=True)
    granjas_lote = granjas_lote.drop_duplicates(["LOTE", "CENTRO GRANJA", "NUCLEO"])

    informar("Consultando estándares, materiales y granjas en las bases de datos...")
    referencia = repositorio.cargar_datos_referencia(
        razas=sorted(lotes["RAZA"].dropna().unique()),
        codigos_granja=sorted(granjas_lote["CENTRO GRANJA"].dropna().unique()),
        dias=parametros.dias,
        codigos_estandar=sorted(lotes_reales.lote_sexo["CODIGO DETALLE"].dropna().unique()),
    )
    sociedades = proyeccion.sociedad_por_lote(lotes, referencia.granjas)
    conteo = sociedades.value_counts()
    resultado.lotes_por_sociedad = {s: int(conteo[s]) for s in config.SOCIEDADES if s in conteo}
    informar(
        "Lotes por sociedad: " + (", ".join(f"{s} {n}" for s, n in resultado.lotes_por_sociedad.items()) or "ninguno")
        + "."
    )

    resultado.mensajes.extend(_validar_tamano(resultado.lotes_por_sociedad, parametros.dias))
    mapa_estandar, mensajes_estandar = validaciones.resolver_estandares(lotes[~lotes["REAL"]], referencia.encabezados)
    resultado.mensajes.extend(mensajes_estandar)
    lote_sexo_reales = pd.DataFrame(columns=[*proyeccion.COLUMNAS_LOTE_SEXO, "CODIGO DETALLE"])
    if not lotes_reales.lote_sexo.empty:
        lote_sexo_reales = lotes_reales.lote_sexo.merge(
            lotes.loc[lotes["REAL"], ["LOTE", "FECHA ENCASETAMIENTO", "CENTRO GRANJA", "NUCLEO", "RAZA"]], on="LOTE"
        )
        lote_sexo_reales["CODIGO ESTANDAR"], mensajes_reales = validaciones.resolver_estandares_reales(
            lote_sexo_reales, referencia.encabezados
        )
        resultado.mensajes.extend(mensajes_reales)
    codigos = [*mapa_estandar.values(), *lote_sexo_reales["CODIGO ESTANDAR"].dropna()]
    resultado.mensajes.extend(validaciones.validar_contra_bd(granjas_lote, referencia, codigos, parametros.dias))
    informar(f"Validación: {len(resultado.errores)} errores, {len(resultado.advertencias)} advertencias.")
    return _Preparacion(
        lotes,
        sociedades,
        referencia,
        mapa_estandar,
        lote_sexo_reales[proyeccion.COLUMNAS_LOTE_SEXO],
        lotes_reales,
        resultado,
    )


def _validar_tamano(lotes_por_sociedad: dict[str, int], dias: int) -> list[Mensaje]:
    """La proyección de cada sociedad va en su propio archivo y debe caber en una hoja de Excel."""
    mensajes = []
    for sociedad, cantidad in lotes_por_sociedad.items():
        filas = cantidad * 2 * dias
        if filas > config.MAX_FILAS_EXCEL:
            mensajes.append(
                Mensaje(
                    Nivel.ERROR,
                    "Parámetros",
                    f"La proyección de {sociedad} tendría {filas:,} registros y una hoja de Excel admite "
                    f"{config.MAX_FILAS_EXCEL:,}. Reduzca la cantidad de lotes o la semana final.",
                )
            )
    return mensajes


def _validar_parametros(parametros: ParametrosProyeccion) -> None:
    if not isinstance(parametros.semana_final, int) or not 1 <= parametros.semana_final <= config.SEMANA_FINAL_MAXIMA:
        raise ErrorProyeccion(
            f"La semana final debe ser un número entero entre 1 y {config.SEMANA_FINAL_MAXIMA}."
        )
    for nombre, valor in (("machos", parametros.porcentaje_machos), ("adicional", parametros.porcentaje_adicional)):
        if not 0 <= valor <= 1:
            raise ErrorProyeccion(f"El porcentaje de {nombre} debe estar entre 0 y 1 (valor: {valor}).")
    if parametros.metodo_mortalidad not in config.METODOS_MORTALIDAD:
        raise ErrorProyeccion(
            f"Método de mortalidad '{parametros.metodo_mortalidad}' no válido. Opciones: {config.METODOS_MORTALIDAD}"
        )
