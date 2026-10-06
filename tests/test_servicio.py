"""Pruebas de las funciones puras del orquestador (servicio.py)."""

from pathlib import Path

import pandas as pd

from proyecciones.modelos import Mensaje, Nivel
from proyecciones.servicio import mensajes_de_sociedad, ruta_por_sociedad


def test_ruta_por_sociedad_agrega_la_sociedad_al_final():
    ruta = Path(r"C:\salidas\Proyeccion_S64.xlsx")
    assert ruta_por_sociedad(ruta, "OCCIDENTE") == Path(r"C:\salidas\Proyeccion_S64_OCCIDENTE.xlsx")


def test_cada_sociedad_recibe_sus_mensajes_y_los_generales():
    lotes = pd.DataFrame({"FILA": [2, 3, 4], "LOTE": [1071, 1072, 1073]})
    sociedades = pd.Series(["ORIENTE", "ORIENTE", "OCCIDENTE"])
    general = Mensaje(Nivel.ADVERTENCIA, "Base de datos", "Estándar 009: consumo inconsistente.")
    fila_oriente = Mensaje(Nivel.ADVERTENCIA, "Insumo", "HEMBRAS PEDIDO tiene decimales.", 2, "1071")
    granja_oriente = Mensaje(Nivel.ADVERTENCIA, "Base de datos", "Granja inactiva.", lote="1071, 1072")
    granja_occidente = Mensaje(Nivel.ADVERTENCIA, "Base de datos", "Granja sin zona.", lote="1073")
    mensajes = [general, fila_oriente, granja_oriente, granja_occidente]

    assert mensajes_de_sociedad(mensajes, lotes, sociedades, "ORIENTE") == [general, fila_oriente, granja_oriente]
    assert mensajes_de_sociedad(mensajes, lotes, sociedades, "OCCIDENTE") == [general, granja_occidente]
