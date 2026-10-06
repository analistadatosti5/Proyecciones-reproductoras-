"""Lectura y validación del Excel de insumo (lotes a proyectar).

Columnas requeridas: LOTE, FECHA ENCASETAMIENTO, CENTRO GRANJA, NUCLEO, RAZA,
HEMBRAS PEDIDO. Los encabezados se comparan sin tildes, sin distinguir
mayúsculas y sin espacios repetidos. Las demás columnas se ignoran.
"""

import numbers
import re
import unicodedata
from datetime import date
from pathlib import Path

import pandas as pd

from . import config
from .modelos import ErrorInsumo, Mensaje, Nivel

ORIGEN = "Insumo"
_PATRON_NUCLEO = re.compile(r"^\d+(-\d+)*$")  # 1, 2-3, 3-2-6


def leer_insumo(ruta: Path) -> tuple[pd.DataFrame, list[Mensaje]]:
    """Lee el insumo y valida cada fila.

    Devuelve las filas válidas (con tipos normalizados) y los mensajes de
    validación. Lanza ErrorInsumo si el archivo no se puede leer, si faltan
    columnas o si no contiene lotes.
    """
    hoja, datos = _leer_hoja_con_columnas(Path(ruta))
    mensajes: list[Mensaje] = []
    registros: list[dict] = []
    fechas_con_hora = 0

    for indice, fila in datos.iterrows():
        numero_fila = indice + 2  # +1 por el encabezado y +1 porque Excel cuenta desde 1
        if all(_vacio(fila[c]) for c in config.COLUMNAS_INSUMO):
            continue

        registro, errores, tenia_hora = _validar_fila(fila)
        fechas_con_hora += tenia_hora
        lote = str(registro["LOTE"]) if registro["LOTE"] is not None else _texto_original(fila["LOTE"])
        if errores:
            mensajes.extend(Mensaje(Nivel.ERROR, ORIGEN, e, numero_fila, lote) for e in errores)
            continue
        if not float(registro["HEMBRAS PEDIDO"]).is_integer():
            mensajes.append(
                Mensaje(Nivel.ADVERTENCIA, ORIGEN, "HEMBRAS PEDIDO tiene decimales.", numero_fila, lote)
            )
        registros.append({"FILA": numero_fila, **registro})

    if not registros and not mensajes:
        raise ErrorInsumo(f"La hoja '{hoja}' no contiene lotes para proyectar.")

    lotes = pd.DataFrame(registros, columns=["FILA", *config.COLUMNAS_INSUMO])
    mensajes.extend(_validar_lotes_duplicados(lotes))
    if fechas_con_hora:
        mensajes.append(
            Mensaje(
                Nivel.INFO,
                ORIGEN,
                f"{fechas_con_hora} fechas de encasetamiento traían hora; se usa solo la fecha.",
            )
        )
    lotes["FECHA ENCASETAMIENTO"] = pd.to_datetime(lotes["FECHA ENCASETAMIENTO"])
    lotes["HEMBRAS PEDIDO"] = lotes["HEMBRAS PEDIDO"].astype(float)
    return lotes, mensajes


# ---------------------------------------------------------------------------
# Lectura
# ---------------------------------------------------------------------------
def normalizar_encabezado(texto: object) -> str:
    """'  Núcleo ' -> 'NUCLEO' (mayúsculas, sin tildes, sin espacios repetidos)."""
    texto = unicodedata.normalize("NFKD", str(texto))
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return " ".join(texto.upper().split())


def _leer_hoja_con_columnas(ruta: Path) -> tuple[str, pd.DataFrame]:
    """Devuelve la primera hoja que contenga todas las columnas requeridas."""
    if not ruta.is_file():
        raise ErrorInsumo(f"No existe el archivo: {ruta}")
    if ruta.suffix.lower() not in config.EXTENSIONES_INSUMO:
        raise ErrorInsumo(f"El insumo debe ser un Excel ({', '.join(config.EXTENSIONES_INSUMO)}): {ruta.name}")
    try:
        hojas = pd.read_excel(ruta, sheet_name=None, dtype=object)
    except PermissionError as exc:
        raise ErrorInsumo(f"No se pudo abrir '{ruta.name}': el archivo está bloqueado por otro programa.") from exc
    except Exception as exc:  # el archivo está dañado o no es un Excel válido
        raise ErrorInsumo(f"No se pudo leer '{ruta.name}' como Excel: {exc}") from exc

    faltantes_por_hoja = {}
    for nombre, datos in hojas.items():
        renombrar = {}
        for columna in datos.columns:
            canonica = normalizar_encabezado(columna)
            if canonica in config.COLUMNAS_INSUMO and canonica not in renombrar.values():
                renombrar[columna] = canonica
        faltantes = [c for c in config.COLUMNAS_INSUMO if c not in renombrar.values()]
        if not faltantes:
            return nombre, datos.rename(columns=renombrar)[list(config.COLUMNAS_INSUMO)]
        faltantes_por_hoja[nombre] = faltantes

    detalle = "; ".join(f"hoja '{h}': faltan {', '.join(f)}" for h, f in faltantes_por_hoja.items())
    raise ErrorInsumo(
        f"El archivo no tiene las columnas requeridas ({', '.join(config.COLUMNAS_INSUMO)}). {detalle}."
    )


# ---------------------------------------------------------------------------
# Validación por fila
# ---------------------------------------------------------------------------
def _validar_fila(fila: pd.Series) -> tuple[dict, list[str], bool]:
    """Convierte los valores de una fila. Devuelve (registro, errores, fecha_tenia_hora)."""
    errores = []

    lote = _a_entero(fila["LOTE"])
    if lote is None or lote <= 0:
        errores.append(f"LOTE debe ser un número entero positivo (valor: {_texto_original(fila['LOTE'])}).")

    fecha, tenia_hora = _a_fecha(fila["FECHA ENCASETAMIENTO"])
    if fecha is None:
        errores.append(
            f"FECHA ENCASETAMIENTO no es una fecha válida (valor: {_texto_original(fila['FECHA ENCASETAMIENTO'])})."
        )
    elif not config.ANIO_MINIMO_ENCASETAMIENTO <= fecha.year <= config.ANIO_MAXIMO_ENCASETAMIENTO:
        errores.append(f"FECHA ENCASETAMIENTO fuera de rango: {fecha:%d/%m/%Y}.")

    granja = _a_texto(fila["CENTRO GRANJA"])
    if granja is None:
        errores.append("CENTRO GRANJA está vacío.")

    nucleo = _a_nucleo(fila["NUCLEO"])
    if nucleo is None:
        errores.append(
            f"NUCLEO inválido (valor: {_texto_original(fila['NUCLEO'])}); se esperan números o grupos como 2-3."
        )

    raza = _a_texto(fila["RAZA"])
    if raza is None:
        errores.append("RAZA está vacía.")
    elif raza not in config.RAZAS_PERMITIDAS:
        errores.append(f"RAZA '{raza}' no permitida. Razas válidas: {', '.join(config.RAZAS_PERMITIDAS)}.")

    hembras = _a_numero(fila["HEMBRAS PEDIDO"])
    if hembras is None or hembras <= 0:
        errores.append(
            f"HEMBRAS PEDIDO debe ser un número mayor que cero (valor: {_texto_original(fila['HEMBRAS PEDIDO'])})."
        )

    registro = {
        "LOTE": lote,
        "FECHA ENCASETAMIENTO": fecha,
        "CENTRO GRANJA": granja,
        "NUCLEO": nucleo,
        "RAZA": raza,
        "HEMBRAS PEDIDO": hembras,
    }
    return registro, errores, tenia_hora


def _validar_lotes_duplicados(lotes: pd.DataFrame) -> list[Mensaje]:
    """Cada LOTE debe aparecer una sola vez (identifica el lote en la proyección)."""
    duplicados = lotes[lotes["LOTE"].duplicated(keep=False)]
    return [
        Mensaje(Nivel.ERROR, ORIGEN, "LOTE repetido en el insumo.", int(fila), str(lote))
        for fila, lote in zip(duplicados["FILA"], duplicados["LOTE"])
    ]


# ---------------------------------------------------------------------------
# Conversión de valores
# ---------------------------------------------------------------------------
def _vacio(valor: object) -> bool:
    if isinstance(valor, str):
        return not valor.strip()
    return valor is None or bool(pd.isna(valor))


def _texto_original(valor: object) -> str:
    return "vacío" if _vacio(valor) else repr(valor)


def _a_entero(valor: object) -> int | None:
    if _vacio(valor) or isinstance(valor, bool):
        return None
    if isinstance(valor, numbers.Integral):
        return int(valor)
    if isinstance(valor, numbers.Real):
        return int(valor) if float(valor).is_integer() else None
    texto = str(valor).strip()
    return int(texto) if texto.isdigit() else None


def _a_numero(valor: object) -> float | None:
    """Acepta números de Excel o texto con dígitos sin separadores de miles."""
    if _vacio(valor) or isinstance(valor, bool):
        return None
    if isinstance(valor, numbers.Real):
        return float(valor)
    texto = str(valor).strip()
    return float(texto) if re.fullmatch(r"\d+(\.\d+)?", texto) else None


def _a_fecha(valor: object) -> tuple[pd.Timestamp | None, bool]:
    """Devuelve (fecha sin hora, indicador de si traía hora)."""
    if _vacio(valor):
        return None, False
    if isinstance(valor, date):  # incluye datetime y pd.Timestamp
        marca = pd.Timestamp(valor)
    elif isinstance(valor, str):
        marca = pd.to_datetime(valor.strip(), dayfirst=True, errors="coerce")
        if pd.isna(marca):
            return None, False
    else:
        return None, False
    fecha = marca.normalize()
    return fecha, marca != fecha


def _a_texto(valor: object) -> str | None:
    """Texto en mayúsculas y sin espacios repetidos (1.0 -> '1')."""
    if _vacio(valor):
        return None
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    return " ".join(str(valor).upper().split())


def _a_nucleo(valor: object) -> str | None:
    """1, '1', 1.0 -> '1';  ' 2 - 3 ' -> '2-3'. None si no tiene el formato esperado."""
    texto = _a_texto(valor)
    if texto is None:
        return None
    texto = re.sub(r"\s*-\s*", "-", texto)
    return texto if _PATRON_NUCLEO.match(texto) else None
