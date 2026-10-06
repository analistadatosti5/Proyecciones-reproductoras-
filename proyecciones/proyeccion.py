"""Lógica de negocio: construye la base diaria equivalente a BD_LOTE.

Un registro por lote, sexo y día de edad (1 .. semana_final x 7). Los días con datos
reales en Granjas_BI (ver reales.py) los toman tal cual; los demás se proyectan:

    AVES+2%          aves del día 1. Lotes del insumo: H = hembras pedido x (1 + % adicional),
                     M = hembras pedido x % machos x (1 + % adicional). Lotes reales: las
                     encasetadas; después de un día real, las de su etapa.
    FECHA            fecha de encasetamiento + edad - 1 (el día 1 es el mismo día del encasetamiento)
    SALDO H          AVES+2% x (1 - m), con m la mortalidad acumulada del estándar (fracción,
                     desde el día 1). Después de un día real a: SALDO real(a) x (1 - m) / (1 - m(a)).
    MORTALIDAD H     m. Después de un día real a: MORTALIDAD real(a) + (SALDO(a) - SALDO H) / AVES+2%
    PROY ALIM H/AVE  consumo diario del estándar (g/ave/día); en los días reales, ALIM H / SALDO H
    ALIM H           SALDO H x PROY ALIM H/AVE / 1000 (kg/día)
    SEMANA AÑO       equivalente a WEEKNUM(FECHA; 2) de Excel
    SOCIEDAD         según el regional de la granja del registro

El módulo no accede a bases de datos ni a archivos: recibe DataFrames.
"""

import numpy as np
import pandas as pd

from . import config
from .modelos import DatosReferencia, ParametrosProyeccion
from .repositorio import codigo_material

# Un registro por lote y sexo: entrada de construir_proyeccion.
COLUMNAS_LOTE_SEXO = [
    "LOTE",
    "SEXO",
    "FECHA ENCASETAMIENTO",
    "CENTRO GRANJA",
    "NUCLEO",
    "RAZA",
    "AVES+2%",
    "CODIGO ESTANDAR",
]
# Columnas de los registros reales (reales.COLUMNAS_DIARIO) con su tipo, para unirlas aunque no haya.
_TIPOS_REALES = {
    "LOTE": "int64",
    "SEXO": "object",
    "EDAD DIA": "int64",
    "FECHA": "datetime64[ns]",
    "SEMANA": "int64",
    "LÍNEA": "object",
    "AVES+2%": "float64",
    "SALDO H": "float64",
    "ALIM H": "float64",
    "MORTALIDAD H": "float64",
    "ETAPA": "object",
    "CENTRO GRANJA": "object",
    "NUCLEO": "object",
}
_CLAVES = ["LOTE", "SEXO", "EDAD DIA"]


def lote_sexo_insumo(
    lotes: pd.DataFrame, mapa_estandar: dict[tuple[str, str], str], parametros: ParametrosProyeccion
) -> pd.DataFrame:
    """Un registro por lote del insumo y sexo, con las aves iniciales y el estándar."""
    hembras = lotes.assign(SEXO=config.SEXO_HEMBRA, FACTOR=1.0)
    machos = lotes.assign(SEXO=config.SEXO_MACHO, FACTOR=parametros.porcentaje_machos)
    lote_sexo = pd.concat([hembras, machos], ignore_index=True)
    lote_sexo["AVES+2%"] = (
        lote_sexo["HEMBRAS PEDIDO"] * lote_sexo["FACTOR"] * (1 + parametros.porcentaje_adicional)
    )
    lote_sexo["CODIGO ESTANDAR"] = [mapa_estandar[(r, s)] for r, s in zip(lote_sexo["RAZA"], lote_sexo["SEXO"])]
    return lote_sexo[COLUMNAS_LOTE_SEXO]


def construir_proyeccion(
    lote_sexo: pd.DataFrame,
    referencia: DatosReferencia,
    parametros: ParametrosProyeccion,
    reales: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Devuelve la proyección diaria con las columnas de config.COLUMNAS_RESULTADO.

    `lote_sexo`: un registro por lote y sexo (COLUMNAS_LOTE_SEXO) con las aves del día 1.
    `reales`: registros reales por lote, sexo y día (reales.COLUMNAS_DIARIO). Reemplazan a los
    proyectados y los días siguientes se proyectan desde el último saldo real.
    """
    dias = parametros.dias
    lote_sexo = lote_sexo[COLUMNAS_LOTE_SEXO].reset_index(drop=True)

    # 1) Expansión: un registro por cada día de edad.
    base = lote_sexo.loc[lote_sexo.index.repeat(dias)].reset_index(drop=True)
    base["EDAD DIA"] = np.tile(np.arange(1, dias + 1, dtype="int64"), len(lote_sexo))
    base["SEMANA"] = (base["EDAD DIA"] - 1) // config.DIAS_POR_SEMANA + 1
    base["FECHA"] = base["FECHA ENCASETAMIENTO"] + pd.to_timedelta(base["EDAD DIA"] - 1, unit="D")

    # 2) Valores del estándar para cada día de edad.
    base = base.merge(
        preparar_estandar(referencia, parametros.metodo_mortalidad),
        how="left",
        left_on=["CODIGO ESTANDAR", "EDAD DIA"],
        right_on=["standard_code", "age"],
        validate="many_to_one",
    )

    # 3) Días reales (columnas "REAL ...").
    base = _unir_reales(base, reales).sort_values(_CLAVES, ignore_index=True)
    es_real = base["REAL SALDO H"].notna()
    por_lote_sexo = [base["LOTE"], base["SEXO"]]

    def arrastrar(serie: pd.Series) -> pd.Series:
        """Último valor no vacío hasta cada día, dentro del lote y sexo."""
        return serie.groupby(por_lote_sexo).ffill()

    # 4) Proyección desde el último día real (o desde el día 1 si aún no hay ninguno).
    m = base["MORTALIDAD EST"]
    saldo_ancla = arrastrar(base["REAL SALDO H"])
    hay_real_antes = saldo_ancla.notna()
    saldo_ancla = saldo_ancla.fillna(base["AVES+2%"])
    mortalidad_ancla = arrastrar(m.where(es_real)).fillna(0.0)
    aves = arrastrar(base["REAL AVES+2%"]).fillna(base["AVES+2%"])
    saldo = saldo_ancla * (1 - m) / (1 - mortalidad_ancla)
    # Después de un día real: su mortalidad más las muertes proyectadas desde ese día
    # (las ventas y los traslados bajan el saldo, pero no son mortalidad).
    mortalidad_real = arrastrar(base["REAL MORTALIDAD H"])
    mortalidad = pd.Series(
        np.where(hay_real_antes, mortalidad_real + (saldo_ancla - saldo) / aves.where(aves > 0), m), index=base.index
    )

    base["SALDO H"] = base["REAL SALDO H"].where(es_real, saldo)
    base["AVES+2%"] = base["REAL AVES+2%"].where(es_real, aves)
    base["MORTALIDAD H"] = base["REAL MORTALIDAD H"].where(es_real, mortalidad.fillna(0.0))
    alimento_real = (base["REAL ALIM H"] * 1000 / base["REAL SALDO H"].where(base["REAL SALDO H"] > 0)).fillna(0.0)
    base["PROY ALIM H/AVE"] = alimento_real.where(es_real, base["PROY EST"])
    base["ALIM H"] = base["REAL ALIM H"].where(es_real, base["SALDO H"] * base["PROY ALIM H/AVE"] / 1000)  # g -> kg
    # Lotes con días reales: consumo acumulado por ave de lo real y lo proyectado; sin días reales, el del estándar.
    tiene_real = es_real.groupby(por_lote_sexo).transform("any")
    base["CONSUMO ACUM"] = base["PROY ALIM H/AVE"].groupby(por_lote_sexo).cumsum().where(tiene_real, base["CONSUMO ACUM EST"])

    base["FECHA"] = base["REAL FECHA"].where(es_real, base["FECHA"])
    base["SEMANA"] = base["REAL SEMANA"].where(es_real, base["SEMANA"]).astype("int64")
    base["LÍNEA"] = base["REAL LÍNEA"].where(es_real, base["RAZA"])
    etapa = base["REAL ETAPA"].where(es_real, base["ETAPA EST"])
    base["ETAPA"] = etapa.map(config.ETAPAS).fillna(etapa)
    base["CENTRO GRANJA"] = base["REAL CENTRO GRANJA"].where(es_real, base["CENTRO GRANJA"])
    base["NUCLEO"] = base["REAL NUCLEO"].where(es_real, base["NUCLEO"])
    base["TIPO DATO"] = np.where(es_real, config.TIPO_DATO_REAL, config.TIPO_DATO_PROYECTADO)
    base["SEMANA AÑO"] = semana_anio_excel(base["FECHA"])

    # 5) Granja, región y sociedad del registro (en los días reales, la granja de ese día).
    base = base.merge(
        granjas_con_region(referencia.granjas),
        how="left",
        left_on="CENTRO GRANJA",
        right_on="farm_code",
        validate="many_to_one",
    )
    base["GRANJA"] = base["farm_name"].fillna(base["CENTRO GRANJA"]) + " " + base["NUCLEO"]
    return base[list(config.COLUMNAS_RESULTADO)]


def _unir_reales(base: pd.DataFrame, reales: pd.DataFrame | None) -> pd.DataFrame:
    """Agrega a la base las columnas de los registros reales con el prefijo "REAL "."""
    if reales is None or reales.empty:
        reales = pd.DataFrame({c: pd.Series(dtype=t) for c, t in _TIPOS_REALES.items()})
    reales = reales[list(_TIPOS_REALES)].astype({c: _TIPOS_REALES[c] for c in _CLAVES})
    reales = reales.rename(columns={c: f"REAL {c}" for c in reales.columns if c not in _CLAVES})
    return base.merge(reales, how="left", on=_CLAVES, validate="one_to_one")


def preparar_estandar(referencia: DatosReferencia, metodo_mortalidad: str) -> pd.DataFrame:
    """Valores diarios del estándar (columnas "... EST" y TIPO ALIMENTO)."""
    estandar = referencia.estandar.sort_values(["standard_code", "age"], ignore_index=True)
    return pd.DataFrame(
        {
            "standard_code": estandar["standard_code"],
            "age": estandar["age"],
            "MORTALIDAD EST": mortalidad_acumulada(estandar, metodo_mortalidad),
            "PROY EST": estandar["bird_consumption"],
            "CONSUMO ACUM EST": estandar["accumulated_bird_consumption"],
            "TIPO ALIMENTO": [nombre_alimento(c, referencia.materiales) for c in estandar["feed_type"]],
            "ETAPA EST": estandar["stage"],
        }
    )


def mortalidad_acumulada(estandar: pd.DataFrame, metodo: str) -> pd.Series:
    """Mortalidad acumulada desde el día 1 como fracción (0.0012 = 0,12 %), por estándar.

    `estandar` debe venir ordenado por standard_code y age.
    """
    por_estandar = estandar["standard_code"]
    if metodo == "suma_diaria":
        return (estandar["mortality_percentage"] / 100).groupby(por_estandar).cumsum()
    if metodo == "acumulado_bd":
        acumulado = estandar["accumulated_mortality_percentage"] / 100
        anterior = acumulado.groupby(por_estandar).shift(1)
        # La BD reinicia el acumulado al iniciar producción: se suma lo acumulado hasta el reinicio.
        reinicio = acumulado < anterior
        compensacion = anterior.where(reinicio, 0.0).groupby(por_estandar).cumsum()
        return acumulado + compensacion
    raise ValueError(f"Método de mortalidad no soportado: {metodo!r}. Opciones: {config.METODOS_MORTALIDAD}")


def nombre_alimento(feed_type: str, materiales: dict[int, str]) -> str:
    """Nombre del material; si no existe en materials se devuelve el código."""
    codigo = codigo_material(feed_type)
    return materiales.get(codigo, f"{feed_type} (SIN NOMBRE EN MATERIALS)")


def _sociedad(regional_code: pd.Series) -> np.ndarray:
    regional = regional_code.fillna("").str.strip().str.upper()
    return np.where(regional.isin(config.REGIONALES_OCCIDENTE), config.SOCIEDAD_OCCIDENTE, config.SOCIEDAD_POR_DEFECTO)


def granjas_con_region(granjas: pd.DataFrame) -> pd.DataFrame:
    """farm_code, farm_name, REGION según la zona de la granja y SOCIEDAD según su regional."""
    zona = granjas["zone_name"].fillna("").str.strip().str.upper()
    return pd.DataFrame(
        {
            "farm_code": granjas["farm_code"],
            "farm_name": granjas["farm_name"],
            "REGION": np.where(zona.isin(config.ZONAS_REGION_CENTRO), config.REGION_CENTRO, config.REGION_POR_DEFECTO),
            "SOCIEDAD": _sociedad(granjas["regional_code"]),
        }
    ).drop_duplicates("farm_code")


def sociedad_por_lote(lotes: pd.DataFrame, granjas: pd.DataFrame) -> pd.Series:
    """Sociedad de cada lote (alineada con `lotes`) según el regional_code de su granja actual.

    Queda vacía (NaN) para los lotes cuya granja no existe en la base, que ya son un ERROR.
    """
    granjas = granjas.drop_duplicates("farm_code")
    sociedad = pd.Series(_sociedad(granjas["regional_code"]), index=granjas["farm_code"].to_numpy())
    return lotes["CENTRO GRANJA"].map(sociedad).rename("SOCIEDAD")


def semana_anio_excel(fechas: pd.Series) -> pd.Series:
    """Equivalente a WEEKNUM(fecha; 2) de Excel.

    Las semanas inician el lunes y la semana 1 es la que contiene el 1 de enero
    (no es la semana ISO).
    """
    fechas = pd.to_datetime(fechas).dt.normalize()
    primero_enero = fechas - pd.to_timedelta(fechas.dt.dayofyear - 1, unit="D")
    lunes_semana_1 = primero_enero - pd.to_timedelta(primero_enero.dt.weekday, unit="D")
    return ((fechas - lunes_semana_1).dt.days // 7 + 1).astype("int64")
