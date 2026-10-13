"""Validaciones del insumo contra la información consultada en las bases de datos.

ERROR       impide generar la proyección (dato inexistente o ambiguo).
ADVERTENCIA la proyección se genera, pero el dato merece revisión.
"""

import pandas as pd

from . import config
from .modelos import DatosReferencia, Mensaje, Nivel
from .repositorio import codigo_material

ORIGEN = "Base de datos"

# Diferencia (g/ave) a partir de la cual se advierte que el consumo acumulado del
# estándar no coincide con la suma de su consumo diario.
_TOLERANCIA_CONSUMO_G = 1.0


def resolver_estandares(
    lotes: pd.DataFrame, encabezados: pd.DataFrame
) -> tuple[dict[tuple[str, str], str], list[Mensaje]]:
    """Asigna el código de estándar a cada (raza, sexo): debe existir exactamente uno."""
    mapa: dict[tuple[str, str], str] = {}
    mensajes: list[Mensaje] = []
    for raza in sorted(lotes["RAZA"].unique()):
        for sexo in (config.SEXO_HEMBRA, config.SEXO_MACHO):
            filtro = (encabezados["breed"] == raza) & (encabezados["sex"] == sexo)
            codigos = sorted(encabezados.loc[filtro, "standard_code"])
            if len(codigos) == 1:
                mapa[(raza, sexo)] = codigos[0]
            elif not codigos:
                mensajes.append(
                    Mensaje(
                        Nivel.ERROR,
                        ORIGEN,
                        f"No existe estándar en core.standard_header (batch_class "
                        f"'{config.CLASE_LOTE_REPRODUCTORAS}') para raza {raza}, sexo {sexo}.",
                    )
                )
            else:
                mensajes.append(
                    Mensaje(
                        Nivel.ERROR,
                        ORIGEN,
                        f"Hay {len(codigos)} estándares para raza {raza}, sexo {sexo} "
                        f"({', '.join(codigos)}); debe existir uno solo.",
                    )
                )
    return mapa, mensajes


def resolver_estandares_reales(lote_sexo: pd.DataFrame, encabezados: pd.DataFrame) -> tuple[pd.Series, list[Mensaje]]:
    """Estándar de cada lote real y sexo (`lote_sexo`: LOTE, SEXO, RAZA, CODIGO DETALLE).

    Se busca por línea genética y sexo. Si hay varios (p. ej. ROSS hembra: 002 y 005), se usa
    el que Granjas_BI asignó al lote (EncasetamientoDetalle.CodEstandar) si es uno de ellos y,
    si no, el de config.ESTANDAR_PREFERIDO. Si no hay ninguno, también el del lote.
    Devuelve el código alineado con `lote_sexo` (vacío si no se pudo determinar: ERROR).
    """
    codigos = pd.Series(None, index=lote_sexo.index, dtype=object)
    mensajes: list[Mensaje] = []
    sexo_de = dict(zip(encabezados["standard_code"], encabezados["sex"]))
    for (raza, sexo, detalle), grupo in lote_sexo.groupby(["RAZA", "SEXO", "CODIGO DETALLE"], dropna=False):
        candidatos = sorted(encabezados.loc[(encabezados["breed"] == raza) & (encabezados["sex"] == sexo), "standard_code"])
        preferido = config.ESTANDAR_PREFERIDO.get((raza, sexo))
        if len(candidatos) == 1:
            codigos[grupo.index] = candidatos[0]
        elif detalle in candidatos or (not candidatos and sexo_de.get(detalle) == sexo):
            codigos[grupo.index] = detalle
        elif preferido in candidatos:
            codigos[grupo.index] = preferido
        else:
            causa = f"hay {len(candidatos)} ({', '.join(candidatos)})" if candidatos else "no existe ninguno"
            mensajes.append(
                Mensaje(
                    Nivel.ERROR,
                    ORIGEN,
                    f"No se pudo determinar el estándar de la línea {raza}, sexo {sexo}: {causa} en "
                    f"core.standard_header y el estándar del lote en Granjas_BI ({_texto(detalle)}) no lo resuelve.",
                    lote=", ".join(str(lote) for lote in sorted(set(grupo["LOTE"]))),
                )
            )
    return codigos, mensajes


def _texto(valor: object) -> str:
    return "vacío" if valor is None or pd.isna(valor) else str(valor)


def validar_contra_bd(
    lotes: pd.DataFrame, referencia: DatosReferencia, codigos_estandar: list[str], dias: int
) -> list[Mensaje]:
    """Ejecuta todas las validaciones de los lotes contra la información de referencia.

    `lotes`: LOTE, CENTRO GRANJA y NUCLEO, una fila por cada granja del lote; con la columna
    REAL = True en los lotes de Granjas_BI, a los que no se les valida el núcleo.
    """
    codigos = sorted(set(codigos_estandar))
    estandar = referencia.estandar[referencia.estandar["standard_code"].isin(codigos)]
    del_insumo = lotes[~lotes["REAL"]] if "REAL" in lotes else lotes
    return [
        *_validar_granjas(lotes, referencia.granjas),
        *_validar_nucleos(del_insumo, referencia.nucleos, referencia.granjas),
        *_validar_cobertura_estandar(estandar, codigos, dias),
        *_validar_materiales(estandar, referencia.materiales),
        *_validar_etapas(estandar),
        *_validar_consistencia_consumo(estandar),
    ]


def _lotes_de(lotes: pd.DataFrame, filtro: pd.Series) -> str:
    return ", ".join(str(lote) for lote in sorted(set(lotes.loc[filtro, "LOTE"])))


def _validar_granjas(lotes: pd.DataFrame, granjas: pd.DataFrame) -> list[Mensaje]:
    mensajes = [
        Mensaje(Nivel.ERROR, ORIGEN, f"La granja {codigo} está repetida en mnl_broiler_breeder_farms.")
        for codigo in sorted(set(granjas.loc[granjas["farm_code"].duplicated(), "farm_code"]))
    ]
    por_codigo = granjas.drop_duplicates("farm_code").set_index("farm_code")
    for codigo in sorted(lotes["CENTRO GRANJA"].unique()):
        de_la_granja = lotes["CENTRO GRANJA"] == codigo
        lista = _lotes_de(lotes, de_la_granja)
        if codigo not in por_codigo.index:
            mensajes.append(
                Mensaje(
                    Nivel.ERROR,
                    ORIGEN,
                    f"La granja {codigo} no existe en mnl_broiler_breeder_farms.",
                    lote=lista,
                )
            )
            continue
        granja = por_codigo.loc[codigo]
        if granja["flock_class"] != config.CLASE_GRANJA_REPRODUCTORAS:
            mensajes.append(
                Mensaje(
                    Nivel.ERROR,
                    ORIGEN,
                    f"La granja {codigo} ({granja['farm_name']}) no es de reproductoras "
                    f"(flock_class = {granja['flock_class']}).",
                    lote=lista,
                )
            )
        if granja["status"] != config.ESTADO_GRANJA_ACTIVA:
            mensajes.append(
                Mensaje(
                    Nivel.ADVERTENCIA,
                    ORIGEN,
                    f"La granja {codigo} ({granja['farm_name']}) está inactiva (status = {granja['status']}).",
                    lote=lista,
                )
            )
        regional = "" if pd.isna(granja["regional_code"]) else str(granja["regional_code"]).strip().upper()
        de_oriente = regional not in config.REGIONALES_OCCIDENTE  # en Occidente la región no depende de la zona
        if de_oriente and (pd.isna(granja["zone_name"]) or not str(granja["zone_name"]).strip()):
            mensajes.append(
                Mensaje(
                    Nivel.ADVERTENCIA,
                    ORIGEN,
                    f"La granja {codigo} ({granja['farm_name']}) no tiene zona; se asigna región "
                    f"{config.REGION_POR_DEFECTO}.",
                    lote=lista,
                )
            )
        if not regional:
            mensajes.append(
                Mensaje(
                    Nivel.ADVERTENCIA,
                    ORIGEN,
                    f"La granja {codigo} ({granja['farm_name']}) no tiene regional; se asigna a la sociedad "
                    f"{config.SOCIEDAD_POR_DEFECTO}.",
                    lote=lista,
                )
            )
    return mensajes


def _validar_nucleos(lotes: pd.DataFrame, nucleos: pd.DataFrame, granjas: pd.DataFrame) -> list[Mensaje]:
    """El núcleo debería existir en mnl_broiler_breeder_house_details (solo se advierte)."""
    registrados = set(zip(nucleos["farm_code"], nucleos["nucleus"]))
    existentes = set(granjas["farm_code"])
    mensajes = []
    for (codigo, nucleo), grupo in lotes.groupby(["CENTRO GRANJA", "NUCLEO"]):
        if codigo in existentes and (codigo, nucleo) not in registrados:
            lista = ", ".join(str(lote) for lote in grupo["LOTE"])
            conocidos = sorted(n for g, n in registrados if g == codigo)
            mensajes.append(
                Mensaje(
                    Nivel.ADVERTENCIA,
                    ORIGEN,
                    f"El núcleo {nucleo} de la granja {codigo} no está en mnl_broiler_breeder_house_details "
                    f"(núcleos registrados: {', '.join(conocidos) or 'ninguno'}).",
                    lote=lista,
                )
            )
    return mensajes


def _validar_cobertura_estandar(estandar: pd.DataFrame, codigos: list[str], dias: int) -> list[Mensaje]:
    """Cada estándar usado debe tener un registro por cada día de 1 a `dias`, sin repetidos."""
    mensajes = []
    esperados = set(range(1, dias + 1))
    for codigo in codigos:
        edades = estandar.loc[estandar["standard_code"] == codigo, "age"]
        if edades.duplicated().any():
            mensajes.append(Mensaje(Nivel.ERROR, ORIGEN, f"El estándar {codigo} tiene días repetidos."))
        faltantes = sorted(esperados - set(edades))
        if faltantes:
            ultimo = int(edades.max()) if len(edades) else 0
            mensajes.append(
                Mensaje(
                    Nivel.ERROR,
                    ORIGEN,
                    f"El estándar {codigo} no tiene datos para {len(faltantes)} de los {dias} días a proyectar "
                    f"(primer día faltante: {faltantes[0]}; último día disponible: {ultimo}, "
                    f"semana {ultimo // config.DIAS_POR_SEMANA}). Reduzca la semana final.",
                )
            )
    return mensajes


def _validar_materiales(estandar: pd.DataFrame, materiales: dict[int, str]) -> list[Mensaje]:
    mensajes = []
    for (codigo_estandar, feed_type), grupo in estandar.groupby(["standard_code", "feed_type"]):
        codigo = codigo_material(feed_type)
        if codigo is None or codigo not in materiales:
            mensajes.append(
                Mensaje(
                    Nivel.ADVERTENCIA,
                    ORIGEN,
                    f"El alimento '{feed_type}' del estándar {codigo_estandar} (días {grupo['age'].min()} a "
                    f"{grupo['age'].max()}) no existe en commercial_bi.public.materials; se mostrará el código.",
                )
            )
    return mensajes


def _validar_etapas(estandar: pd.DataFrame) -> list[Mensaje]:
    desconocidas = sorted(set(estandar["stage"]) - set(config.ETAPAS))
    return [
        Mensaje(Nivel.ADVERTENCIA, ORIGEN, f"Etapa '{etapa}' del estándar sin traducción en config.ETAPAS.")
        for etapa in desconocidas
    ]


def _validar_consistencia_consumo(estandar: pd.DataFrame) -> list[Mensaje]:
    """Compara accumulated_bird_consumption con la suma de bird_consumption al último día."""
    mensajes = []
    for codigo, datos in estandar.sort_values("age").groupby("standard_code"):
        if datos.empty:
            continue
        suma = datos["bird_consumption"].sum()
        acumulado = datos["accumulated_bird_consumption"].iloc[-1]
        if abs(suma - acumulado) > _TOLERANCIA_CONSUMO_G:
            mensajes.append(
                Mensaje(
                    Nivel.ADVERTENCIA,
                    ORIGEN,
                    f"Estándar {codigo}: al día {datos['age'].iloc[-1]} el consumo acumulado de la BD "
                    f"({acumulado:,.0f} g) no coincide con la suma del consumo diario ({suma:,.0f} g). "
                    "PROY ALIM H/AVE usa bird_consumption y CONSUMO ACUM usa accumulated_bird_consumption.",
                )
            )
    return mensajes
