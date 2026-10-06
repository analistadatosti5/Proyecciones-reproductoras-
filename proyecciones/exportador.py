"""Generación del Excel de resultado.

Usa xlsxwriter en modo de memoria constante (las filas se escriben en orden y
se liberan), por lo que el consumo de memoria no crece con el tamaño de la
proyección. Se escribe primero un archivo temporal y solo al final se
reemplaza el destino, para no dejar archivos a medio escribir.

Hojas: BD_LOTE y VALIDACIONES. La hoja TABLERO (tabla dinámica) la agrega
después tabla_dinamica.py usando Excel.
"""

import os
from collections.abc import Sequence
from pathlib import Path

import pandas as pd
import xlsxwriter
from xlsxwriter.exceptions import XlsxWriterException
from xlsxwriter.utility import xl_col_to_name

from . import config
from .modelos import ErrorExportacion, Mensaje, Nivel

_EPOCA_EXCEL = pd.Timestamp("1899-12-30")  # día 0 del calendario de Excel

# Formato numérico y ancho por columna de la hoja BD_LOTE
_FORMATOS_BASE = {
    "FECHA": "dd/mm/yyyy",
    "FECHA ENCASETAMIENTO": "dd/mm/yyyy",
    "AVES+2%": "#,##0.00",
    "SALDO H": "#,##0.00",
    "PROY ALIM H/AVE": "#,##0.00",
    "ALIM H": "#,##0.00",
    "MORTALIDAD H": "0.00%",
    "CONSUMO ACUM": "#,##0",
}
_ANCHOS_BASE = {"FECHA": 12, "FECHA ENCASETAMIENTO": 14, "TIPO ALIMENTO": 40, "GRANJA": 26, "LÍNEA": 10}


class _Estilos:
    """Formatos reutilizables del libro (xlsxwriter exige crearlos una sola vez)."""

    def __init__(self, libro: xlsxwriter.Workbook):
        self._libro = libro
        self._numericos: dict[str, object] = {}
        self.encabezado = libro.add_format(
            {"bold": True, "font_color": "#FFFFFF", "bg_color": "#1F4E78", "border": 1, "text_wrap": True,
             "valign": "vcenter"}
        )

    def numero(self, formato: str | None):
        if formato is None:
            return None
        if formato not in self._numericos:
            self._numericos[formato] = self._libro.add_format({"num_format": formato})
        return self._numericos[formato]


def exportar(ruta: Path, base: pd.DataFrame, mensajes: Sequence[Mensaje]) -> None:
    """Escribe el libro de resultado en `ruta`."""
    ruta = Path(ruta)
    temporal = ruta.with_name(f"{ruta.stem}.tmp{ruta.suffix}")
    libro = xlsxwriter.Workbook(str(temporal), {"constant_memory": True, "nan_inf_to_errors": True})
    try:
        estilos = _Estilos(libro)
        _escribir_base(libro, estilos, base)
        _escribir_validaciones(libro, estilos, mensajes)
        libro.close()
        os.replace(temporal, ruta)
    except PermissionError as exc:
        raise ErrorExportacion(
            f"No se pudo guardar '{ruta.name}'. Si el archivo está abierto en Excel, ciérrelo e intente de nuevo."
        ) from exc
    except (OSError, XlsxWriterException) as exc:
        raise ErrorExportacion(f"No se pudo generar el Excel '{ruta.name}': {exc}") from exc
    finally:
        if not libro.fileclosed:  # falló a mitad de escritura: se cierra para liberar temporales
            try:
                libro.close()
            except (OSError, XlsxWriterException):
                pass
        temporal.unlink(missing_ok=True)


def _valores_excel(serie: pd.Series) -> list:
    """Fechas -> número de serie de Excel (el formato de la columna las muestra como fecha)."""
    if pd.api.types.is_datetime64_any_dtype(serie):
        return (serie - _EPOCA_EXCEL).dt.days.tolist()
    return serie.tolist()


def _escribir_base(libro: xlsxwriter.Workbook, estilos: _Estilos, base: pd.DataFrame) -> None:
    hoja = libro.add_worksheet(config.HOJA_BASE)
    columnas = list(base.columns)
    # En modo de memoria constante los formatos de columna se definen antes de escribir filas.
    for j, columna in enumerate(columnas):
        ancho = _ANCHOS_BASE.get(columna, max(9, len(columna) + 2))
        hoja.set_column(j, j, ancho, estilos.numero(_FORMATOS_BASE.get(columna)))

    hoja.write_row(0, 0, columnas, estilos.encabezado)
    valores = [_valores_excel(base[c]) for c in columnas]
    for i, fila in enumerate(zip(*valores), start=1):
        hoja.write_row(i, 0, fila)

    ultima_fila, ultima_columna = len(base), len(columnas) - 1
    hoja.freeze_panes(1, 0)
    hoja.autofilter(0, 0, ultima_fila, ultima_columna)
    # Nombre definido para crear tablas dinámicas sobre toda la base.
    libro.define_name(
        config.NOMBRE_RANGO_BASE,
        f"='{config.HOJA_BASE}'!$A$1:${xl_col_to_name(ultima_columna)}${ultima_fila + 1}",
    )


def _escribir_validaciones(libro: xlsxwriter.Workbook, estilos: _Estilos, mensajes: Sequence[Mensaje]) -> None:
    hoja = libro.add_worksheet(config.HOJA_VALIDACIONES)
    encabezados = ["NIVEL", "ORIGEN", "FILA INSUMO", "LOTE", "DETALLE"]
    for j, ancho in enumerate([14, 15, 12, 30, 140]):
        hoja.set_column(j, j, ancho)
    hoja.write_row(0, 0, encabezados, estilos.encabezado)

    orden = {Nivel.ERROR: 0, Nivel.ADVERTENCIA: 1, Nivel.INFO: 2}
    ordenados = sorted(mensajes, key=lambda m: orden[m.nivel])
    if not ordenados:
        hoja.write(1, 0, "Sin observaciones")
    for i, m in enumerate(ordenados, start=1):
        hoja.write_row(i, 0, [m.nivel.value, m.origen, m.fila or "", m.lote or "", m.detalle])
    hoja.autofilter(0, 0, max(len(ordenados), 1), len(encabezados) - 1)
