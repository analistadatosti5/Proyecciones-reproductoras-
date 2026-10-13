"""Datos reales de los lotes (Granjas_BI): consolidación por lote, sexo y día.

En Granjas_BI cada etapa de un lote en una granja es una cabecera (EncasetamientoCabecera):
levante (L) y producción (P). Si el lote cambia de granja durante el levante hay dos
cabeceras de levante: origen (Clase O) y destino (Clase D). EncasetamientoDetalle trae las
aves encasetadas en cada cabecera y DiaReproductora un registro por cabecera, galpón,
división, sexo y día (las consultas ya suman galpones y divisiones).

Por cabecera y sexo:
    AVES+2%       aves encasetadas en la etapa: EncasetamientoDetalle.Cantidad si coincide con
                  DiaReproductora.avesEncasetadas del primer día; si no, Cantidad - MortalidadTrans
    SALDO H       AVES+2% - acumulado de (selección + mortalidad + mortalidad de transporte +
                  vendidas + sacrificio) + acumulado de (agregadas - transferidas)
    MORTALIDAD H  acumulado de (selección + mortalidad) / AVES+2%
    ALIM H        consumo (kg)

Los días en que dos cabeceras del lote tienen registros (traslado entre granjas) toman el
saldo, la granja y la etapa de la más reciente y suman el consumo de ambas.

Los días sin registro del lote hasta su último registro no se proyectan: un día suelto, un
período largo (también los días sin carga de ninguna granja) o los días anteriores al primer
registro. Quedan con TIPO DATO = SIN REGISTRO, consumo 0 y el saldo del registro anterior (antes
del primero, las aves encasetadas).

El módulo no accede a bases de datos: recibe DataFrames (ver repositorio.cargar_datos_reales).
"""

import numpy as np
import pandas as pd

from . import config
from .modelos import DatosReales, LotesReales, Mensaje, Nivel

ORIGEN = "Granjas_BI"
SEXOS = (config.SEXO_HEMBRA, config.SEXO_MACHO)
COLUMNAS_LOTES = ["LOTE", "FECHA ENCASETAMIENTO", "CENTRO GRANJA", "NUCLEO", "RAZA"]
COLUMNAS_LOTE_SEXO = ["LOTE", "SEXO", "AVES+2%", "CODIGO DETALLE"]
COLUMNAS_DIARIO = [
    "LOTE",
    "SEXO",
    "EDAD DIA",
    "FECHA",
    "SEMANA",
    "LÍNEA",
    "AVES+2%",
    "SALDO H",
    "ALIM H",
    "MORTALIDAD H",
    "ETAPA",
    "CENTRO GRANJA",
    "NUCLEO",
    "TIPO DATO",  # REAL o SIN REGISTRO
]
# Salidas de aves de cada día; las agregadas menos las transferidas se suman al saldo.
_SALIDAS = ["seleccion", "mortalidad", "mortalidad_transporte", "aves_vendidas", "aves_sacrificio"]


# ---------------------------------------------------------------------------
# Selección de días y lotes (las usa repositorio antes de pedir los registros diarios)
# ---------------------------------------------------------------------------
def fecha_corte(carga: pd.DataFrame) -> pd.Timestamp | None:
    """Último día con carga completa en DiaReproductora (None si no hay registros).

    `carga`: fecha y cabeceras de reproductoras con registros ese día. Se descartan los
    últimos días con menos de FRACCION_DIA_COMPLETO x la mediana de los
    DIAS_REFERENCIA_CARGA días anteriores (Granjas_BI carga los registros con rezago).
    """
    serie = carga.set_index("fecha")["cabeceras"].sort_index()
    serie = serie[serie > 0]
    for i in range(len(serie) - 1, -1, -1):
        anteriores = serie.iloc[max(0, i - config.DIAS_REFERENCIA_CARGA) : i]
        if anteriores.empty or serie.iloc[i] >= config.FRACCION_DIA_COMPLETO * anteriores.median():
            return serie.index[i]
    return None


def lotes_a_incluir(cabeceras: pd.DataFrame, corte: pd.Timestamp, lotes_insumo: list[int]) -> list[int]:
    """Lotes activos (con registros en los últimos DIAS_LOTE_ACTIVO días hasta el corte) y los del insumo."""
    desde = corte - pd.Timedelta(days=config.DIAS_LOTE_ACTIVO - 1)
    activos = set(cabeceras.loc[cabeceras["ultimo_registro"] >= desde, "lote"])
    del_insumo = set(cabeceras["lote"]) & {int(lote) for lote in lotes_insumo}
    return sorted(activos | del_insumo)


# ---------------------------------------------------------------------------
# Consolidación
# ---------------------------------------------------------------------------
def consolidar(datos: DatosReales) -> LotesReales:
    """Datos reales por lote: estado actual, aves del día 1 y registros diarios."""
    if datos.fecha_corte is None:
        return _vacio(
            [Mensaje(Nivel.ADVERTENCIA, ORIGEN, "Granjas_BI no tiene registros diarios de reproductoras; todo se proyecta.")]
        )
    cabeceras = _cabeceras_por_sexo(datos.cabeceras)
    if cabeceras.empty:
        return _vacio([_mensaje_corte(datos)])

    mensajes: list[Mensaje] = []
    dias, aves = _dias_por_cabecera(datos.dias, cabeceras, mensajes)
    diario = _diario_por_lote(dias, mensajes)
    lotes, lote_sexo = _lotes(cabeceras, aves, diario)
    diario = _con_dias_sin_registro(diario, mensajes)
    granjas = (
        cabeceras[["lote", "granja", "nucleo"]]
        .drop_duplicates()
        .rename(columns={"lote": "LOTE", "granja": "CENTRO GRANJA", "nucleo": "NUCLEO"})
        .reset_index(drop=True)
    )
    mensajes = [_mensaje_corte(datos), *_mensajes_sin_carga(datos, lotes), *mensajes]
    return LotesReales(lotes=lotes, lote_sexo=lote_sexo, diario=diario, granjas=granjas, mensajes=mensajes)


def _vacio(mensajes: list[Mensaje]) -> LotesReales:
    return LotesReales(
        lotes=pd.DataFrame(columns=COLUMNAS_LOTES),
        lote_sexo=pd.DataFrame(columns=COLUMNAS_LOTE_SEXO),
        diario=pd.DataFrame(columns=COLUMNAS_DIARIO),
        granjas=pd.DataFrame(columns=["LOTE", "CENTRO GRANJA", "NUCLEO"]),
        mensajes=mensajes,
    )


def _cabeceras_por_sexo(cabeceras: pd.DataFrame) -> pd.DataFrame:
    """Una fila por cabecera y sexo. La raza y el estándar son los del detalle con más aves."""
    if cabeceras.empty:
        return pd.DataFrame()
    c = cabeceras[cabeceras["sexo"].isin(SEXOS)].sort_values("cantidad", ascending=False, kind="stable")
    c = c.groupby(["id_encaseta", "sexo"], as_index=False).agg(
        lote=("lote", "first"),
        granja=("granja", "first"),
        nucleo=("nucleo", "first"),
        etapa=("etapa", "first"),
        raza=("raza", "first"),
        codigo=("codigo_estandar", "first"),
        fecha_ingreso=("fecha_ingreso", "min"),
        cantidad=("cantidad", "sum"),
        mortalidad_transporte=("mortalidad_transporte", "sum"),
        primer_registro=("primer_registro", "min"),
    )
    # Cabeceras sin aves ni registros diarios (p. ej. R999/R000 con cantidad 0) no son etapas del lote.
    aves = c.groupby("id_encaseta")["cantidad"].transform("sum")
    registros = c.groupby("id_encaseta")["primer_registro"].transform("count")
    c = c[(aves > 0) | (registros > 0)].copy()
    # Inicio de la etapa: ordena las cabeceras del lote (la más reciente es la de mayor inicio).
    c["inicio"] = c["fecha_ingreso"].fillna(c["primer_registro"]).groupby(c["id_encaseta"]).transform("min")
    return c.reset_index(drop=True)


def _dias_por_cabecera(
    dias: pd.DataFrame, cabeceras: pd.DataFrame, mensajes: list[Mensaje]
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Registros diarios por cabecera y sexo con saldo y mortalidad acumulada de la etapa."""
    claves = ["id_encaseta", "sexo"]
    if dias.empty:
        aves = cabeceras[claves].assign(aves=cabeceras["cantidad"])
        return pd.DataFrame(), aves
    d = dias[dias["sexo"].isin(SEXOS)].merge(
        cabeceras[[*claves, "lote", "granja", "nucleo", "inicio"]], on=claves, how="inner"
    )
    d = d.sort_values([*claves, "fecha"], ignore_index=True)
    aves = _aves_por_etapa(d, cabeceras, mensajes)
    d = d.merge(aves, on=claves, how="left")

    grupos = [d["id_encaseta"], d["sexo"]]
    salidas = d[_SALIDAS].sum(axis=1) - d["aves_agregadas"] + d["aves_transferidas"]
    d["saldo"] = d["aves"] - salidas.groupby(grupos).cumsum()
    mortalidad = (d["seleccion"] + d["mortalidad"]).groupby(grupos).cumsum()
    d["mortalidad_acumulada"] = (mortalidad / d["aves"].where(d["aves"] > 0)).fillna(0.0)

    negativos = d["saldo"] < 0
    if negativos.any():
        mensajes.append(
            Mensaje(
                Nivel.ADVERTENCIA,
                ORIGEN,
                f"En {int(negativos.sum())} registros diarios las salidas acumuladas superan las aves encasetadas "
                "de la etapa; el saldo de esos días se deja en 0.",
                lote=_lista(d.loc[negativos, "lote"]),
            )
        )
        d["saldo"] = d["saldo"].clip(lower=0)
    return d, aves


def _aves_por_etapa(d: pd.DataFrame, cabeceras: pd.DataFrame, mensajes: list[Mensaje]) -> pd.DataFrame:
    """Aves encasetadas en cada cabecera y sexo: Cantidad del detalle validada con el primer día."""
    claves = ["id_encaseta", "sexo"]
    primer_dia = d.groupby(claves, as_index=False).first()[[*claves, "fecha", "aves_encasetadas"]]
    a = cabeceras.merge(primer_dia, on=claves, how="left")
    sin_registros = a["aves_encasetadas"].isna()
    coincide = a["cantidad"] == a["aves_encasetadas"]
    sin_detalle = (a["cantidad"] == 0) & ~sin_registros
    # Regla de negocio: si no coinciden, las aves encasetadas son Cantidad - MortalidadTrans.
    a["aves"] = np.where(sin_registros | coincide, a["cantidad"], a["cantidad"] - a["mortalidad_transporte"])
    a.loc[sin_detalle, "aves"] = a.loc[sin_detalle, "aves_encasetadas"]

    for fila in a[~(sin_registros | coincide | sin_detalle)].itertuples():
        mensajes.append(
            Mensaje(
                Nivel.ADVERTENCIA,
                ORIGEN,
                f"Etapa {fila.etapa} en {fila.granja}, sexo {fila.sexo}: EncasetamientoDetalle tiene "
                f"{fila.cantidad:,.0f} aves y DiaReproductora {fila.aves_encasetadas:,.0f} el primer día "
                f"({fila.fecha:%d/%m/%Y}); se usa Cantidad - MortalidadTrans = {fila.aves:,.0f}.",
                lote=str(fila.lote),
            )
        )
    return a[[*claves, "aves"]]


def _diario_por_lote(d: pd.DataFrame, mensajes: list[Mensaje]) -> pd.DataFrame:
    """Un registro por lote, sexo y día: la cabecera más reciente del día y el consumo de todas."""
    if d.empty:
        return pd.DataFrame(columns=COLUMNAS_DIARIO)
    claves = ["lote", "sexo", "fecha"]
    consumo = d.groupby(claves, as_index=False)["consumo"].sum().rename(columns={"consumo": "consumo_lote"})
    actual = d.sort_values([*claves, "inicio", "id_encaseta"]).groupby(claves).tail(1)
    actual = actual.merge(consumo, on=claves, how="left").sort_values(["lote", "sexo", "edad", "fecha"])

    # La misma edad en dos fechas sería un error de captura: se deja la fecha más reciente.
    repetidas = actual.duplicated(["lote", "sexo", "edad"], keep="last")
    if repetidas.any():
        mensajes.append(
            Mensaje(
                Nivel.ADVERTENCIA,
                ORIGEN,
                f"{int(repetidas.sum())} registros diarios repiten la edad de otro día del mismo lote y sexo; "
                "se usa el de fecha más reciente.",
                lote=_lista(actual.loc[repetidas, "lote"]),
            )
        )
        actual = actual[~repetidas]

    return pd.DataFrame(
        {
            "LOTE": actual["lote"],
            "SEXO": actual["sexo"],
            "EDAD DIA": actual["edad"],
            "FECHA": actual["fecha"],
            "SEMANA": actual["semana"],
            "LÍNEA": actual["linea"],
            "AVES+2%": actual["aves"],
            "SALDO H": actual["saldo"],
            "ALIM H": actual["consumo_lote"],
            "MORTALIDAD H": actual["mortalidad_acumulada"],
            "ETAPA": actual["etapa"],
            "CENTRO GRANJA": actual["granja"],
            "NUCLEO": actual["nucleo"],
            "TIPO DATO": config.TIPO_DATO_REAL,
        }
    ).sort_values(["LOTE", "SEXO", "EDAD DIA"], ignore_index=True)


def _con_dias_sin_registro(diario: pd.DataFrame, mensajes: list[Mensaje]) -> pd.DataFrame:
    """Agrega los días sin registro de cada lote y sexo hasta su último registro (TIPO DATO = SIN REGISTRO).

    No se proyectan y toman consumo 0. Los días entre dos registros llevan el saldo, la mortalidad,
    la etapa y la granja del registro anterior; los anteriores al primer registro, las aves
    encasetadas (sin mortalidad) y la etapa y la granja del primer registro.
    """
    if diario.empty:
        return diario
    diario = diario.sort_values(["LOTE", "SEXO", "EDAD DIA"], ignore_index=True)
    siguiente = diario.groupby(["LOTE", "SEXO"])["EDAD DIA"].shift(-1)
    entre = _desplazados(diario, (siguiente - diario["EDAD DIA"] - 1).fillna(0).clip(lower=0), 1)
    primero = diario.drop_duplicates(["LOTE", "SEXO"])
    antes = _desplazados(primero, (primero["EDAD DIA"] - 1).clip(lower=0), -1)  # hay registros con edad 0
    antes = antes.assign(**{"SALDO H": antes["AVES+2%"], "MORTALIDAD H": 0.0})
    huecos = pd.concat([antes, entre], ignore_index=True)
    if huecos.empty:
        return diario
    huecos = huecos.assign(
        **{
            "SEMANA": (huecos["EDAD DIA"] - 1) // config.DIAS_POR_SEMANA + 1,
            "ALIM H": 0.0,
            "TIPO DATO": config.TIPO_DATO_SIN_REGISTRO,
        }
    )
    mensajes.append(
        Mensaje(
            Nivel.INFO,
            ORIGEN,
            f"{len(huecos)} días de lote y sexo no tienen registro en Granjas_BI antes del último registro del "
            f"lote y no se proyectan: quedan con consumo 0 (TIPO DATO = {config.TIPO_DATO_SIN_REGISTRO}).",
            lote=_lista(huecos["LOTE"]),
        )
    )
    if not antes.empty:
        inicio = primero[primero["EDAD DIA"] > 1].sort_values("EDAD DIA").drop_duplicates("LOTE").sort_values("LOTE")
        lotes = "; ".join(
            f"{lote} ({fecha:%d/%m/%Y}, día {edad})"
            for lote, fecha, edad in zip(inicio["LOTE"], inicio["FECHA"], inicio["EDAD DIA"])
        )
        mensajes.append(
            Mensaje(
                Nivel.ADVERTENCIA,
                ORIGEN,
                f"Lotes sin registros desde el encasetamiento (primer registro: fecha y día de edad): {lotes}. "
                f"Los días anteriores quedan como {config.TIPO_DATO_SIN_REGISTRO} con las aves encasetadas.",
                lote=_lista(inicio["LOTE"]),
            )
        )
    return pd.concat([diario, huecos], ignore_index=True).sort_values(["LOTE", "SEXO", "EDAD DIA"], ignore_index=True)


def _desplazados(registros: pd.DataFrame, veces: pd.Series, sentido: int) -> pd.DataFrame:
    """Copia cada registro `veces` veces corriendo la edad y la fecha 1, 2, ... días hacia adelante (1) o atrás (-1)."""
    copias = registros.loc[registros.index.repeat(veces.astype("int64"))]
    dias = (copias.groupby(level=0).cumcount().to_numpy() + 1) * sentido
    return copias.assign(
        **{"EDAD DIA": copias["EDAD DIA"].to_numpy() + dias, "FECHA": copias["FECHA"] + pd.to_timedelta(dias, unit="D")}
    )


def _lotes(cabeceras: pd.DataFrame, aves: pd.DataFrame, diario: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Estado actual de cada lote (granja, núcleo y línea de la etapa más reciente) y aves del día 1."""
    c = cabeceras.merge(aves, on=["id_encaseta", "sexo"], how="left")
    c["aves"] = c["aves"].fillna(c["cantidad"])  # etapas sin registros diarios
    c = c.sort_values(["lote", "inicio", "id_encaseta"], ignore_index=True)

    actual = c.groupby("lote").tail(1).set_index("lote")
    lotes = pd.DataFrame({"LOTE": actual.index, "CENTRO GRANJA": actual["granja"], "NUCLEO": actual["nucleo"]})
    # Día 1: el que dan los registros diarios (FECHA - EDAD DIA + 1); sin registros, el primer ingreso.
    lotes["FECHA ENCASETAMIENTO"] = lotes["LOTE"].map(c.groupby("lote")["inicio"].min())
    lotes["RAZA"] = lotes["LOTE"].map(c.groupby("lote")["raza"].last())
    if not diario.empty:
        dia1 = (diario["FECHA"] - pd.to_timedelta(diario["EDAD DIA"] - 1, unit="D")).groupby(diario["LOTE"]).agg(
            lambda fechas: fechas.mode().iloc[0]
        )
        lotes["FECHA ENCASETAMIENTO"] = lotes["LOTE"].map(dia1).fillna(lotes["FECHA ENCASETAMIENTO"])
        linea = diario.sort_values("FECHA").groupby("LOTE")["LÍNEA"].last()
        lotes["RAZA"] = lotes["LOTE"].map(linea).fillna(lotes["RAZA"])
    lotes = lotes[COLUMNAS_LOTES].reset_index(drop=True)

    # Aves del día 1: las de la primera etapa; estándar del detalle: el de la etapa más reciente.
    por_sexo = c.groupby(["lote", "sexo"]).agg(aves=("aves", "first"), codigo=("codigo", "last"))
    indice = pd.MultiIndex.from_product([lotes["LOTE"], SEXOS], names=["LOTE", "SEXO"])
    lote_sexo = por_sexo.reindex(indice).reset_index()
    lote_sexo = lote_sexo.rename(columns={"aves": "AVES+2%", "codigo": "CODIGO DETALLE"})
    lote_sexo["AVES+2%"] = lote_sexo["AVES+2%"].fillna(0.0)
    return lotes, lote_sexo[COLUMNAS_LOTE_SEXO]


def _mensaje_corte(datos: DatosReales) -> Mensaje:
    corte = datos.fecha_corte
    carga = datos.carga.sort_values("fecha")
    habitual = carga.loc[carga["fecha"] <= corte, "cabeceras"].tail(config.DIAS_REFERENCIA_CARGA).median()
    texto = (
        f"Datos reales de Granjas_BI hasta el {corte:%d/%m/%Y} (último día con carga completa); "
        "los días siguientes se proyectan desde el último saldo real."
    )
    incompletos = carga[carga["fecha"] > corte]
    if not incompletos.empty:
        dias = ", ".join(f"{f:%d/%m/%Y} ({n})" for f, n in zip(incompletos["fecha"], incompletos["cabeceras"]))
        texto += f" Días con carga incompleta que no se usan (cabeceras con registros, de ~{habitual:.0f}): {dias}."
    return Mensaje(Nivel.INFO, ORIGEN, texto)


def _mensajes_sin_carga(datos: DatosReales, lotes: pd.DataFrame) -> list[Mensaje]:
    """Días sin ningún registro de reproductoras desde el encasetamiento del lote más antiguo."""
    if lotes.empty or datos.carga.empty:
        return []
    desde = max(lotes["FECHA ENCASETAMIENTO"].min(), datos.carga["fecha"].min())
    con_carga = set(datos.carga.loc[datos.carga["cabeceras"] > 0, "fecha"])
    faltantes = [f for f in pd.date_range(desde, datos.fecha_corte, freq="D") if f not in con_carga]
    if not faltantes:
        return []
    rangos, inicio, anterior = [], faltantes[0], faltantes[0]
    for fecha in [*faltantes[1:], None]:
        if fecha is not None and fecha - anterior == pd.Timedelta(days=1):
            anterior = fecha
            continue
        rangos.append(f"{inicio:%d/%m/%Y}" if inicio == anterior else f"{inicio:%d/%m/%Y} a {anterior:%d/%m/%Y}")
        inicio = anterior = fecha
    return [
        Mensaje(
            Nivel.INFO,
            ORIGEN,
            f"Granjas_BI no tiene registros de reproductoras en {len(faltantes)} días ({'; '.join(rangos)}). "
            f"En los lotes con registros antes y después quedan como {config.TIPO_DATO_SIN_REGISTRO} (consumo 0).",
        )
    ]


# ---------------------------------------------------------------------------
# Unión con el insumo
# ---------------------------------------------------------------------------
def combinar_lotes(lotes_insumo: pd.DataFrame, reales: LotesReales) -> tuple[pd.DataFrame, list[Mensaje]]:
    """Lotes a proyectar: los del insumo más los de Granjas_BI (columna REAL).

    Si un lote del insumo ya existe en Granjas_BI se usan sus datos reales (fecha, granja,
    núcleo, línea y aves) en lugar de los del insumo.
    """
    de_bd = reales.lotes
    en_bd = lotes_insumo["LOTE"].isin(de_bd["LOTE"])
    por_lote = de_bd.set_index("LOTE")
    mensajes = [_mensaje_lote_existente(fila, por_lote.loc[fila["LOTE"]]) for _, fila in lotes_insumo[en_bd].iterrows()]

    filas = lotes_insumo.drop_duplicates("LOTE").set_index("LOTE")["FILA"]
    partes = [lotes_insumo[~en_bd].assign(REAL=False)]
    if not de_bd.empty:  # concat con un DataFrame vacío cambiaría los tipos de las columnas
        partes.append(de_bd.assign(FILA=de_bd["LOTE"].map(filas), REAL=True))
    lotes = pd.concat(partes, ignore_index=True)
    lotes["FILA"] = lotes["FILA"].astype("Int64")  # vacía para los lotes que no están en el insumo
    lotes["REAL"] = lotes["REAL"].astype(bool)
    lotes = lotes[["FILA", *config.COLUMNAS_INSUMO, "REAL"]].sort_values("LOTE", ignore_index=True)

    if not de_bd.empty:
        del_insumo = int(en_bd.sum())
        mensajes.insert(
            0,
            Mensaje(
                Nivel.INFO,
                ORIGEN,
                f"{len(de_bd)} lotes con datos reales: {del_insumo} del insumo y {len(de_bd) - del_insumo} "
                "activos que no están en el insumo.",
            ),
        )
    return lotes, mensajes


def _mensaje_lote_existente(insumo: pd.Series, real: pd.Series) -> Mensaje:
    diferencias = []
    dias = abs((real["FECHA ENCASETAMIENTO"] - insumo["FECHA ENCASETAMIENTO"]).days)
    if dias:
        diferencias.append(f"fecha {insumo['FECHA ENCASETAMIENTO']:%d/%m/%Y}")
    for columna, nombre in (("CENTRO GRANJA", "granja"), ("NUCLEO", "núcleo"), ("RAZA", "raza")):
        if insumo[columna] != real[columna]:
            diferencias.append(f"{nombre} {insumo[columna]}")
    importante = dias > config.DIAS_TOLERANCIA_ENCASETAMIENTO or insumo["RAZA"] != real["RAZA"]
    texto = (
        f"El lote ya está encasetado en Granjas_BI ({real['CENTRO GRANJA']} núcleo {real['NUCLEO']}, "
        f"{real['RAZA']}, día 1 el {real['FECHA ENCASETAMIENTO']:%d/%m/%Y}): se usan sus datos reales"
    )
    if diferencias:
        texto += f" (en el insumo: {', '.join(diferencias)})"
    return Mensaje(Nivel.ADVERTENCIA if importante else Nivel.INFO, ORIGEN, texto + ".", int(insumo["FILA"]), str(insumo["LOTE"]))


def _lista(lotes: pd.Series) -> str:
    return ", ".join(str(lote) for lote in sorted(set(lotes)))
