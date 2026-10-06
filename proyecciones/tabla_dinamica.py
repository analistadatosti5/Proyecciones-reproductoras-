"""Hoja TABLERO: tabla dinámica del consumo proyectado por tipo de alimento.

Replica el TABLERO del Excel anterior: filtros LÍNEA, REGION, GRANJA y LOTE;
filas por año y mes de la FECHA; columnas por TIPO ALIMENTO; valores = suma de
ALIM H. Los campos se configuran en config.py (TABLA_DINAMICA_*).

xlsxwriter y openpyxl no pueden crear tablas dinámicas, por eso el archivo ya
generado se abre con Microsoft Excel (automatización COM con pywin32) y Excel
crea la tabla. Requiere Excel instalado en el equipo.
"""

import gc
from pathlib import Path

from . import config
from .modelos import ErrorExportacion

try:
    import pythoncom
    import win32com.client
except ImportError:  # pywin32 solo existe en Windows
    pythoncom = None

# Constantes del modelo de objetos de Excel
_XL_BASE_DATOS = 1  # xlDatabase: el origen es un rango de celdas
_XL_FILA, _XL_COLUMNA, _XL_FILTRO = 1, 2, 3  # xlRowField, xlColumnField, xlPageField
_XL_SUMA = -4157  # xlSum
_XL_TABULAR = 1  # xlTabularRow
_XL_REPETIR_ETIQUETAS = 2  # xlRepeatLabels
_XL_VERSION = 5  # xlPivotTableVersion15 (Excel 2013 o posterior)
# Periods de Range.Group: segundos, minutos, horas, días, meses, trimestres, años
_MESES_Y_ANIOS = (False, False, False, False, True, False, True)
_ANCHO_COLUMNA_VALORES = 16  # los nombres de alimento son largos: se muestran en varias líneas


def agregar_tabla_dinamica(ruta: Path) -> None:
    """Abre el libro con Excel, agrega la hoja TABLERO con la tabla dinámica y lo guarda."""
    if pythoncom is None:
        raise ErrorExportacion("La tabla dinámica requiere el paquete pywin32 (pip install pywin32).")
    error = None
    pythoncom.CoInitialize()  # necesario: la interfaz ejecuta el proceso en un hilo secundario
    try:
        try:
            # Instancia propia de Excel: no interfiere con los libros que el usuario tenga abiertos.
            excel = win32com.client.DispatchEx("Excel.Application")
        except pythoncom.com_error:
            raise ErrorExportacion(
                "No fue posible iniciar Microsoft Excel; la tabla dinámica requiere Excel instalado."
            ) from None
        try:
            excel.Visible = False
            excel.DisplayAlerts = False
            error = _crear_en_libro(excel, Path(ruta).resolve())
        finally:
            excel.Quit()
            del excel
            gc.collect()  # libera las referencias COM restantes para que el proceso de Excel termine
    finally:
        pythoncom.CoUninitialize()
    if error:
        raise ErrorExportacion(error)


def _crear_en_libro(excel, ruta: Path) -> str | None:
    """Crea la tabla y guarda el libro. Devuelve el error de Excel como texto, o None.

    El error no se relanza aquí para que su traza, que retiene objetos COM, se
    libere antes de cerrar Excel (si no, el proceso de Excel queda abierto).
    """
    libro = None
    try:
        libro = excel.Workbooks.Open(str(ruta))
        _construir_tabla(libro)
        libro.Save()
        return None
    except pythoncom.com_error as exc:
        return f"Excel no pudo crear la tabla dinámica: {_descripcion(exc)}"
    finally:
        if libro is not None:
            libro.Close(False)


def _construir_tabla(libro) -> None:
    hoja = libro.Worksheets.Add(Before=libro.Worksheets(1))  # queda como primera hoja y activa
    hoja.Name = config.HOJA_TABLA_DINAMICA
    cache = libro.PivotCaches().Create(
        SourceType=_XL_BASE_DATOS, SourceData=config.NOMBRE_RANGO_BASE, Version=_XL_VERSION
    )
    tabla = cache.CreatePivotTable(
        TableDestination=hoja.Range("A3"), TableName=config.NOMBRE_TABLA_DINAMICA, DefaultVersion=_XL_VERSION
    )
    tabla.ManualUpdate = True  # no recalcular con cada cambio de diseño
    tabla.RowAxisLayout(_XL_TABULAR)
    for campo in reversed(config.TABLA_DINAMICA_FILTROS):  # Excel ubica cada filtro nuevo arriba de los demás
        tabla.PivotFields(campo).Orientation = _XL_FILTRO
    tabla.PivotFields(config.TABLA_DINAMICA_COLUMNAS).Orientation = _XL_COLUMNA
    fecha = tabla.PivotFields(config.TABLA_DINAMICA_FECHA)
    fecha.Orientation = _XL_FILA
    valor = config.TABLA_DINAMICA_VALOR
    tabla.AddDataField(tabla.PivotFields(valor), f"Suma de {valor}", _XL_SUMA).NumberFormat = "#,##0"
    tabla.ManualUpdate = False
    # Agrupar la fecha por años y meses. By debe enviarse como Empty: si se omite, Excel ignora Periods.
    fecha.DataRange.Cells(1).Group(True, True, pythoncom.Empty, _MESES_Y_ANIOS)
    tabla.RepeatAllLabels(_XL_REPETIR_ETIQUETAS)

    tabla.HasAutoFormat = False  # que Excel no reajuste los anchos al filtrar o actualizar
    tabla.ColumnRange.WrapText = True
    tabla.DataBodyRange.ColumnWidth = _ANCHO_COLUMNA_VALORES


def _descripcion(error) -> str:
    """Texto legible de un error COM: la descripción que da Excel o, si no hay, el mensaje general."""
    info = error.excepinfo
    return (info[2] if info and info[2] else error.strerror) or "error desconocido"
