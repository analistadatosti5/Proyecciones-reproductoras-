"""Pruebas de las validaciones contra datos de referencia (validaciones.py)."""

import pandas as pd

from proyecciones import config
from proyecciones.modelos import Nivel
from proyecciones.validaciones import resolver_estandares, resolver_estandares_reales, validar_contra_bd


def test_resolver_estandares_exige_uno_por_raza_y_sexo():
    encabezados = pd.DataFrame(
        {
            "standard_code": ["006", "007", "010", "011"],
            "breed": ["ROSSAP", "ROSSAP", "COBB M", "COBB M"],
            "sex": ["H", "M", "H", "H"],
            "description": ["", "", "", ""],
        }
    )
    mapa, mensajes = resolver_estandares(pd.DataFrame({"RAZA": ["ROSSAP", "COBB M"]}), encabezados)
    assert mapa == {("ROSSAP", "H"): "006", ("ROSSAP", "M"): "007"}
    detalles = [m.detalle for m in mensajes if m.nivel == Nivel.ERROR]
    assert any("Hay 2 estándares para raza COBB M, sexo H" in d for d in detalles)
    assert any("No existe estándar" in d and "raza COBB M, sexo M" in d for d in detalles)


def test_sin_observaciones_con_datos_consistentes(lotes, referencia, mapa_estandar):
    assert validar_contra_bd(lotes, referencia, list(mapa_estandar.values()), dias=14) == []


def test_granja_inexistente_y_nucleo_no_registrado(lotes, referencia, mapa_estandar):
    lotes = lotes.assign(**{"CENTRO GRANJA": ["R001", "R999"], "NUCLEO": ["2", "1"]})
    mensajes = validar_contra_bd(lotes, referencia, list(mapa_estandar.values()), dias=14)
    assert any(m.nivel == Nivel.ERROR and "R999 no existe" in m.detalle for m in mensajes)
    assert any(m.nivel == Nivel.ADVERTENCIA and "núcleo 2 de la granja R001" in m.detalle for m in mensajes)


def test_granja_sin_zona_sin_regional_e_inactiva(lotes, referencia, mapa_estandar):
    referencia.granjas.loc[0, ["zone_name", "regional_code", "status"]] = [None, None, "I"]
    mensajes = validar_contra_bd(lotes, referencia, list(mapa_estandar.values()), dias=14)
    detalles = [m.detalle for m in mensajes if m.nivel == Nivel.ADVERTENCIA]
    assert any("inactiva" in d for d in detalles)
    assert any("no tiene zona" in d for d in detalles)
    assert any("no tiene regional; se asigna a la sociedad ORIENTE" in d for d in detalles)


def test_estandar_sin_cobertura_para_la_semana_final(lotes, referencia, mapa_estandar):
    mensajes = validar_contra_bd(lotes, referencia, list(mapa_estandar.values()), dias=21)  # el estándar cubre 14 días
    assert sum(m.nivel == Nivel.ERROR and "no tiene datos" in m.detalle for m in mensajes) == 2


def test_lotes_reales_no_validan_nucleo(lotes, referencia, mapa_estandar):
    lotes = lotes.assign(NUCLEO=["5-6", "9"], REAL=[True, False])
    mensajes = validar_contra_bd(lotes, referencia, list(mapa_estandar.values()), dias=14)
    assert [m.lote for m in mensajes if "núcleo" in m.detalle] == ["1072"]


def test_estandar_de_lotes_reales_por_linea_o_por_detalle(monkeypatch):
    encabezados = pd.DataFrame(
        {
            "standard_code": ["002", "005", "004", "006", "012"],
            "breed": ["ROSS", "ROSS", "ROSS", "ROSSAP", "ROSSAPN"],
            "sex": ["H", "H", "M", "H", "H"],
        }
    )
    lote_sexo = pd.DataFrame(
        {
            "LOTE": [1, 1, 2, 3, 4, 5],
            "SEXO": ["H", "M", "H", "H", "H", "H"],
            "RAZA": ["ROSS", "ROSS", "ROSSAP", "ROSS", "XX", "ROSS"],
            "CODIGO DETALLE": ["005", "004", "012", "006", "012", None],
        }
    )
    codigos, mensajes = resolver_estandares_reales(lote_sexo, encabezados)
    # ROSS H tiene dos estándares: decide el del detalle si es uno de ellos (005) y si no, el preferido (002).
    # ROSSAP H tiene uno solo: se usa aunque el detalle diga otro. La línea XX no tiene estándar: el del detalle.
    assert codigos.tolist() == ["005", "004", "006", "002", "012", "002"]
    assert mensajes == []

    monkeypatch.setattr(config, "ESTANDAR_PREFERIDO", {})
    codigos, mensajes = resolver_estandares_reales(lote_sexo, encabezados)
    assert pd.isna(codigos[3]) and pd.isna(codigos[5])
    assert [m.lote for m in mensajes] == ["3", "5"] and all(m.nivel == Nivel.ERROR for m in mensajes)
    assert "hay 2 (002, 005)" in mensajes[0].detalle


def test_consumo_acumulado_inconsistente(lotes, referencia, mapa_estandar):
    referencia.estandar.loc[referencia.estandar["standard_code"] == "007", "accumulated_bird_consumption"] += 50
    mensajes = validar_contra_bd(lotes, referencia, list(mapa_estandar.values()), dias=14)
    assert len(mensajes) == 1
    assert mensajes[0].nivel == Nivel.ADVERTENCIA
    assert mensajes[0].detalle.startswith("Estándar 007:")
