"""Pruebas de lectura y validación del insumo (insumo.py)."""

from datetime import datetime

import openpyxl
import pandas as pd
import pytest

from proyecciones.insumo import leer_insumo, normalizar_encabezado
from proyecciones.modelos import ErrorInsumo, Nivel

ENCABEZADOS = ["LOTE", "FECHA ENCASETAMIENTO", "CENTRO GRANJA", "Núcleo", "raza", "HEMBRAS PEDIDO", ""]


def _crear_excel(ruta, filas, encabezados=ENCABEZADOS):
    libro = openpyxl.Workbook()
    hoja = libro.active
    hoja.append(encabezados)
    for fila in filas:
        hoja.append(fila)
    libro.save(ruta)
    return ruta


def test_lee_y_normaliza_valores(tmp_path):
    ruta = _crear_excel(
        tmp_path / "insumo.xlsx",
        [
            [1071, datetime(2026, 9, 16), "r001", 1, "ROSSAP", 35300, "*nota que se ignora"],
            [1072, datetime(2026, 11, 18, 21, 7, 12), "R006", " 2 - 3 ", "cobb m", 33400],
            [None, None, None, None, None, None],  # fila vacía: se ignora
        ],
    )
    lotes, mensajes = leer_insumo(ruta)
    assert lotes["LOTE"].tolist() == [1071, 1072]
    assert lotes["CENTRO GRANJA"].tolist() == ["R001", "R006"]
    assert lotes["NUCLEO"].tolist() == ["1", "2-3"]
    assert lotes["RAZA"].tolist() == ["ROSSAP", "COBB M"]
    assert lotes["FECHA ENCASETAMIENTO"].iloc[1] == pd.Timestamp("2026-11-18")  # se descarta la hora
    assert [m.nivel for m in mensajes] == [Nivel.INFO]  # aviso de fechas que traían hora


def test_faltan_columnas(tmp_path):
    ruta = _crear_excel(tmp_path / "insumo.xlsx", [[1071, datetime(2026, 9, 16)]], ["LOTE", "FECHA ENCASETAMIENTO"])
    with pytest.raises(ErrorInsumo, match="CENTRO GRANJA"):
        leer_insumo(ruta)


def test_errores_por_fila(tmp_path):
    ruta = _crear_excel(
        tmp_path / "insumo.xlsx",
        [
            [1071, datetime(2026, 9, 16), "R001", 1, "HUBBARD", 35300],  # fila 2: raza no permitida
            [1072, "no es fecha", "R001", 1, "ROSSAP", 35300],  # fila 3: fecha inválida
            [1073, datetime(2026, 9, 16), "R001", "1/2", "ROSSAP", -5],  # fila 4: núcleo y hembras
            [1074, datetime(2026, 9, 16), "R001", 1, "ROSSAP", 1000],  # fila 5
            [1074, datetime(2026, 9, 17), "R002", 1, "ROSSAP", 1000],  # fila 6: lote repetido
        ],
    )
    lotes, mensajes = leer_insumo(ruta)
    errores = {(m.fila, m.detalle.split()[0]) for m in mensajes if m.nivel == Nivel.ERROR}
    assert {(2, "RAZA"), (3, "FECHA"), (4, "NUCLEO"), (4, "HEMBRAS"), (5, "LOTE"), (6, "LOTE")} <= errores
    assert lotes["LOTE"].tolist() == [1074, 1074]  # solo quedan las filas con formato válido


def test_archivo_inexistente(tmp_path):
    with pytest.raises(ErrorInsumo, match="No existe"):
        leer_insumo(tmp_path / "no_existe.xlsx")


def test_normalizar_encabezado():
    assert normalizar_encabezado("  Núcleo ") == "NUCLEO"
    assert normalizar_encabezado("fecha   encasetamiento") == "FECHA ENCASETAMIENTO"
