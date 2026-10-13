"""Pruebas de la consolidación de datos reales de Granjas_BI (reales.py)."""

import pandas as pd
import pytest

from proyecciones import reales
from proyecciones.modelos import DatosReales, Nivel

DIA1 = pd.Timestamp("2026-01-01")
_SUMAS = [
    "aves_encasetadas",
    "seleccion",
    "mortalidad",
    "mortalidad_transporte",
    "aves_vendidas",
    "aves_sacrificio",
    "aves_agregadas",
    "aves_transferidas",
    "consumo",
]


def _cabecera(id_encaseta, lote, granja, nucleo, etapa, sexo, cantidad, ingreso, primer=None, ultimo=None, **otros):
    return {
        "id_encaseta": id_encaseta,
        "lote": lote,
        "granja": granja,
        "nucleo": nucleo,
        "etapa": etapa,
        "sexo": sexo,
        "raza": "ROSS",
        "codigo_estandar": "002" if sexo == "H" else "004",
        "fecha_ingreso": pd.Timestamp(ingreso),
        "cantidad": float(cantidad),
        "mortalidad_transporte": 0.0,
        "primer_registro": pd.Timestamp(primer) if primer else pd.NaT,
        "ultimo_registro": pd.Timestamp(ultimo) if ultimo else pd.NaT,
        **otros,
    }


def _dia(id_encaseta, sexo, edad, aves, **valores):
    fila = {
        "id_encaseta": id_encaseta,
        "fecha": DIA1 + pd.Timedelta(days=edad - 1),
        "sexo": sexo,
        "edad": edad,
        "semana": (edad - 1) // 7 + 1,
        "linea": "ROSS",
        "etapa": "L",
        **{c: 0.0 for c in _SUMAS},
        "consumo": 10.0,
    }
    fila.update(aves_encasetadas=float(aves), **{k: float(v) for k, v in valores.items()})
    return fila


@pytest.fixture
def datos() -> DatosReales:
    """Lote 500: levante en R010 (días 1-4) y traslado a R011 (días 4-6, el día 4 en ambas).
    Lote 501: encasetado sin registros diarios. Cabecera 3: R999 sin aves (se descarta)."""
    cabeceras = pd.DataFrame(
        [
            _cabecera(1, 500, "R010", "1", "L", "H", 1000, "2026-01-01", "2026-01-01", "2026-01-04"),
            _cabecera(1, 500, "R010", "1", "L", "M", 100, "2026-01-01", "2026-01-01", "2026-01-04"),
            _cabecera(2, 500, "R011", "2", "L", "H", 980, "2026-01-04", "2026-01-04", "2026-01-06", mortalidad_transporte=10.0),
            _cabecera(2, 500, "R011", "2", "L", "M", 95, "2026-01-04", "2026-01-04", "2026-01-06"),
            _cabecera(3, 500, "R999", "1", "P", "H", 0, "2026-01-02"),
            _cabecera(4, 501, "R021", "1", "L", "H", 500, "2026-01-03"),
            _cabecera(4, 501, "R021", "1", "L", "M", 50, "2026-01-03"),
        ]
    )
    dias = pd.DataFrame(
        [
            _dia(1, "H", 1, 1000, mortalidad=3, mortalidad_transporte=5),
            _dia(1, "H", 2, 1000, mortalidad=2, seleccion=1),
            _dia(1, "H", 3, 1000, mortalidad=1),
            _dia(1, "H", 4, 1000, mortalidad=1),
            # Primer día de R011: avesEncasetadas (970) no coincide con Cantidad (980) -> 980 - 10 de transporte.
            _dia(2, "H", 4, 970, mortalidad=2, consumo=8),
            _dia(2, "H", 5, 970, mortalidad=1),
            _dia(2, "H", 6, 970, aves_vendidas=100),
            _dia(1, "M", 1, 100),
            _dia(1, "M", 2, 100, aves_agregadas=10),
            _dia(1, "M", 3, 100, aves_transferidas=4),
            _dia(1, "M", 4, 100),
            _dia(2, "M", 4, 95),
            _dia(2, "M", 5, 95),
            _dia(2, "M", 6, 95),
        ]
    )
    carga = pd.DataFrame(
        {"fecha": pd.date_range(DIA1, periods=7, freq="D"), "cabeceras": [10, 10, 10, 10, 10, 10, 2]}
    )
    return DatosReales(fecha_corte=pd.Timestamp("2026-01-06"), carga=carga, cabeceras=cabeceras, dias=dias)


def test_fecha_corte_descarta_los_ultimos_dias_incompletos():
    fechas = pd.date_range("2026-09-20", periods=11, freq="D")
    carga = pd.DataFrame({"fecha": fechas, "cabeceras": [72, 61, 72, 73, 72, 72, 73, 73, 73, 62, 3]})
    assert reales.fecha_corte(carga) == pd.Timestamp("2026-09-28")  # 62 de ~72 y 3: incompletos
    assert reales.fecha_corte(carga.iloc[:2]) == pd.Timestamp("2026-09-20")  # el primer día no tiene referencia
    assert reales.fecha_corte(carga.iloc[:0]) is None


def test_lotes_activos_y_del_insumo(datos):
    corte = pd.Timestamp("2026-01-06")
    assert reales.lotes_a_incluir(datos.cabeceras, corte, [999]) == [500]  # 501 no tiene registros
    assert reales.lotes_a_incluir(datos.cabeceras, corte, [501, 999]) == [500, 501]
    assert reales.lotes_a_incluir(datos.cabeceras, corte + pd.Timedelta(days=30), []) == []


def test_saldo_con_balance_completo_por_etapa(datos):
    diario = reales.consolidar(datos).diario.set_index(["LOTE", "SEXO", "EDAD DIA"])
    # R010: 1000 - (3 + 5 de transporte) = 992; luego - 3 (mortalidad + selección) y - 1.
    assert diario.loc[(500, "H", 1), "SALDO H"] == 992
    assert diario.loc[(500, "H", 3), "SALDO H"] == 988
    assert diario.loc[(500, "H", 3), "MORTALIDAD H"] == pytest.approx((3 + 3 + 1) / 1000)  # sin transporte
    # Machos: + 10 agregadas el día 2, - 4 transferidas el día 3.
    assert diario.loc[(500, "M", 2), "SALDO H"] == 110
    assert diario.loc[(500, "M", 3), "SALDO H"] == 106


def test_dia_de_traslado_usa_la_etapa_mas_reciente_y_suma_el_consumo(datos):
    lotes_reales = reales.consolidar(datos)
    dia4 = lotes_reales.diario.set_index(["LOTE", "SEXO", "EDAD DIA"]).loc[(500, "H", 4)]
    assert dia4["CENTRO GRANJA"] == "R011" and dia4["NUCLEO"] == "2"
    assert dia4["AVES+2%"] == 970  # 980 - 10: no coincidía con avesEncasetadas
    assert dia4["SALDO H"] == 968
    assert dia4["ALIM H"] == 18  # 10 en R010 + 8 en R011
    dia6 = lotes_reales.diario.set_index(["LOTE", "SEXO", "EDAD DIA"]).loc[(500, "H", 6)]
    assert dia6["SALDO H"] == 867  # 100 vendidas
    avisos = [m for m in lotes_reales.mensajes if m.nivel == Nivel.ADVERTENCIA]
    assert len(avisos) == 1 and avisos[0].lote == "500" and "Cantidad - MortalidadTrans = 970" in avisos[0].detalle


def test_estado_actual_y_aves_del_dia_1(datos):
    lotes_reales = reales.consolidar(datos)
    lotes = lotes_reales.lotes.set_index("LOTE")
    assert lotes.loc[500, "CENTRO GRANJA"] == "R011"  # la R999 sin aves se descarta
    assert lotes.loc[500, "FECHA ENCASETAMIENTO"] == DIA1
    assert lotes.loc[500, "RAZA"] == "ROSS"
    assert lotes.loc[501, "FECHA ENCASETAMIENTO"] == pd.Timestamp("2026-01-03")  # sin registros: el ingreso
    aves = lotes_reales.lote_sexo.set_index(["LOTE", "SEXO"])
    assert aves.loc[(500, "H"), "AVES+2%"] == 1000 and aves.loc[(500, "M"), "AVES+2%"] == 100
    assert aves.loc[(501, "H"), "CODIGO DETALLE"] == "002"
    assert set(lotes_reales.granjas["CENTRO GRANJA"]) == {"R010", "R011", "R021"}


def test_mensajes_de_corte_y_dias_sin_carga(datos):
    datos.carga = datos.carga[datos.carga["fecha"] != pd.Timestamp("2026-01-03")]
    detalles = [m.detalle for m in reales.consolidar(datos).mensajes if m.nivel == Nivel.INFO]
    assert any("hasta el 06/01/2026" in d and "07/01/2026 (2)" in d for d in detalles)
    assert any("en 1 días (03/01/2026)" in d for d in detalles)


def test_dias_sin_registro_entre_registros_quedan_con_consumo_0(datos):
    # Hembras sin registro el día 5; machos sin registro los días 2 y 3 (el 3 sin carga de ninguna granja).
    sin_dia = ((datos.dias["id_encaseta"] == 2) & (datos.dias["sexo"] == "H") & (datos.dias["edad"] == 5)) | (
        (datos.dias["sexo"] == "M") & datos.dias["edad"].isin([2, 3])
    )
    datos.dias = datos.dias[~sin_dia]
    datos.carga = datos.carga[datos.carga["fecha"] != pd.Timestamp("2026-01-03")]
    lotes_reales = reales.consolidar(datos)
    diario = lotes_reales.diario.set_index(["LOTE", "SEXO", "EDAD DIA"])

    dia5 = diario.loc[(500, "H", 5)]
    assert dia5["TIPO DATO"] == "SIN REGISTRO" and dia5["ALIM H"] == 0
    assert dia5["FECHA"] == pd.Timestamp("2026-01-05") and dia5["SEMANA"] == 1
    assert dia5["SALDO H"] == diario.loc[(500, "H", 4), "SALDO H"] and dia5["CENTRO GRANJA"] == "R011"
    machos = diario.loc[(500, "M")]
    assert machos.loc[[2, 3], "TIPO DATO"].tolist() == ["SIN REGISTRO", "SIN REGISTRO"]
    assert machos.loc[3, "FECHA"] == pd.Timestamp("2026-01-03") and machos.loc[3, "SALDO H"] == machos.loc[1, "SALDO H"]
    assert (diario.drop(index=[(500, "H", 5), (500, "M", 2), (500, "M", 3)])["TIPO DATO"] == "REAL").all()
    aviso = next(m for m in lotes_reales.mensajes if m.detalle.startswith("3 días"))
    assert aviso.nivel == Nivel.INFO and aviso.lote == "500"


def test_dias_antes_del_primer_registro_quedan_sin_registro(datos):
    # Machos sin registros los días 1 y 2: el primer registro es el día 3.
    datos.dias = datos.dias[~((datos.dias["sexo"] == "M") & datos.dias["edad"].isin([1, 2]))]
    lotes_reales = reales.consolidar(datos)
    machos = lotes_reales.diario.set_index(["LOTE", "SEXO", "EDAD DIA"]).loc[(500, "M")]

    assert machos.loc[[1, 2], "TIPO DATO"].tolist() == ["SIN REGISTRO", "SIN REGISTRO"]
    assert machos.loc[1, "FECHA"] == DIA1 and machos.loc[2, "FECHA"] == DIA1 + pd.Timedelta(days=1)
    assert machos.loc[1, "SALDO H"] == 100 and machos.loc[1, "MORTALIDAD H"] == 0  # aves encasetadas
    assert machos.loc[1, "ALIM H"] == 0 and machos.loc[1, "CENTRO GRANJA"] == "R010"
    assert machos.loc[3, "TIPO DATO"] == "REAL"
    aviso = next(m for m in lotes_reales.mensajes if "desde el encasetamiento" in m.detalle)
    assert aviso.nivel == Nivel.ADVERTENCIA and aviso.lote == "500" and "500 (03/01/2026, día 3)" in aviso.detalle


def test_sin_datos_reales_todo_se_proyecta():
    lotes_reales = reales.consolidar(DatosReales.vacios())
    assert lotes_reales.lotes.empty and lotes_reales.diario.empty
    assert lotes_reales.mensajes[0].nivel == Nivel.ADVERTENCIA


def test_combinar_lotes_usa_los_datos_reales_del_lote_existente(datos, lotes):
    lotes_reales = reales.consolidar(datos)
    insumo = lotes.assign(LOTE=[500, 1072])  # el 500 ya existe en Granjas_BI
    combinados, mensajes = reales.combinar_lotes(insumo, lotes_reales)
    assert combinados["LOTE"].tolist() == [500, 501, 1072]
    assert combinados["REAL"].tolist() == [True, True, False]
    assert combinados["FILA"].tolist()[0] == 2 and pd.isna(combinados["FILA"].iloc[1])
    fila = combinados.set_index("LOTE").loc[500]
    assert fila["CENTRO GRANJA"] == "R011" and fila["RAZA"] == "ROSS"
    aviso = next(m for m in mensajes if m.lote == "500")
    # La raza del insumo (ROSSAP) difiere de la real (ROSS): advertencia.
    assert aviso.nivel == Nivel.ADVERTENCIA and "raza ROSSAP" in aviso.detalle
    assert mensajes[0].detalle.startswith("2 lotes con datos reales: 1 del insumo y 1 activos")
