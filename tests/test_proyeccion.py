"""Pruebas de la lógica de negocio (proyeccion.py)."""

import pandas as pd
import pytest

from proyecciones import config
from proyecciones.modelos import ParametrosProyeccion
from proyecciones.proyeccion import (
    construir_proyeccion,
    lote_sexo_insumo,
    mortalidad_acumulada,
    semana_anio_excel,
    sociedad_por_lote,
)

PARAMETROS = ParametrosProyeccion(semana_final=2)  # 14 días: lo que cubre el estándar sintético
DIAS = PARAMETROS.dias


@pytest.fixture
def lote_sexo(lotes, mapa_estandar) -> pd.DataFrame:
    return lote_sexo_insumo(lotes, mapa_estandar, PARAMETROS)


@pytest.fixture
def base(lote_sexo, referencia) -> pd.DataFrame:
    return construir_proyeccion(lote_sexo, referencia, PARAMETROS)


def test_estructura_y_cantidad_de_registros(base):
    assert list(base.columns) == list(config.COLUMNAS_RESULTADO)
    assert len(base) == 2 * 2 * DIAS  # lotes x sexos x días
    edades = base.groupby(["LOTE", "SEXO"])["EDAD DIA"].agg(["min", "max"])
    assert (edades["min"] == 1).all() and (edades["max"] == DIAS).all()


def test_aves_iniciales_por_sexo(base):
    indice = base.set_index(["LOTE", "SEXO", "EDAD DIA"])
    assert indice.loc[(1071, "H", 1), "AVES+2%"] == pytest.approx(35300 * 1.02)
    assert indice.loc[(1071, "M", 1), "AVES+2%"] == pytest.approx(35300 * 0.15 * 1.02)


def test_fechas_y_semanas(base):
    indice = base.set_index(["LOTE", "SEXO", "EDAD DIA"])
    assert indice.loc[(1071, "H", 1), "FECHA"] == pd.Timestamp("2026-09-16")  # mismo día del encasetamiento
    assert indice.loc[(1071, "H", 7), "SEMANA"] == 1
    assert indice.loc[(1071, "H", 8), "SEMANA"] == 2
    assert indice.loc[(1072, "H", 2), "FECHA"] == pd.Timestamp("2026-12-31")
    assert indice.loc[(1072, "H", 2), "SEMANA AÑO"] == 53
    assert indice.loc[(1072, "H", 3), "FECHA"] == pd.Timestamp("2027-01-01")
    assert indice.loc[(1072, "H", 3), "SEMANA AÑO"] == 1


def test_saldo_y_alimento(base):
    fila = base.set_index(["LOTE", "SEXO", "EDAD DIA"]).loc[(1071, "H", 9)]
    # Acumulado continuo: 0,7 % al cierre de levante (día 7) + 0,2 % en producción (día 9)
    assert fila["MORTALIDAD H"] == pytest.approx(0.009)
    assert fila["SALDO H"] == pytest.approx(fila["AVES+2%"] - fila["AVES+2%"] * 0.009)
    assert fila["PROY ALIM H/AVE"] == 29  # 20 + edad
    assert fila["ALIM H"] == pytest.approx(fila["SALDO H"] * 29 / 1000)


def test_atributos_desde_bases_de_datos(base):
    indice = base.set_index(["LOTE", "SEXO", "EDAD DIA"])
    assert indice.loc[(1071, "H", 1), "TIPO ALIMENTO"] == "ALIMENTO POLLITA GRANEL"
    assert indice.loc[(1071, "H", 8), "TIPO ALIMENTO"] == "ALIMENTO FASE 1 ROSS HARINA GRANEL"
    assert indice.loc[(1071, "H", 7), "ETAPA"] == "LEVANTE"
    assert indice.loc[(1071, "H", 8), "ETAPA"] == "PRODUCCIÓN"
    assert indice.loc[(1071, "H", 1), "REGION"] == "SANTANDER"
    assert indice.loc[(1072, "M", 1), "REGION"] == "CENTRO"  # ZONA 6 REPRODUCTORAS
    assert indice.loc[(1071, "H", 1), "GRANJA"] == "AGUILAS 1"
    assert indice.loc[(1071, "M", 3), "CONSUMO ACUM"] == 31 + 32 + 33
    assert indice.loc[(1071, "M", 1), "LÍNEA"] == "ROSSAP"
    assert (base["SOCIEDAD"] == "ORIENTE").all()  # regional 1GR
    assert (base["TIPO DATO"] == "PROYECTADO").all()


def _reales(**columnas) -> pd.DataFrame:
    """Registros reales del lote 1071 hembras (reales.COLUMNAS_DIARIO); `columnas` reemplaza los valores."""
    edades = columnas.pop("EDAD DIA")
    n = len(edades)
    datos = {
        "LOTE": [1071] * n,
        "SEXO": ["H"] * n,
        "EDAD DIA": edades,
        "FECHA": [pd.Timestamp("2026-09-15") + pd.Timedelta(days=e) for e in edades],  # día 1 = 16/09/2026
        "SEMANA": [(e - 1) // 7 + 1 for e in edades],
        "LÍNEA": ["ROSSAP"] * n,
        "AVES+2%": [36000.0] * n,
        "ALIM H": [700.0] * n,
        "MORTALIDAD H": [0.01] * n,
        "ETAPA": ["L"] * n,
        "CENTRO GRANJA": ["R021"] * n,
        "NUCLEO": ["2"] * n,
    }
    datos.update(columnas)
    return pd.DataFrame(datos)


def test_dias_reales_reemplazan_a_los_proyectados(lote_sexo, referencia):
    reales = _reales(**{"EDAD DIA": [3, 4], "SALDO H": [35800.0, 35000.0]})
    base = construir_proyeccion(lote_sexo, referencia, PARAMETROS, reales).set_index(["LOTE", "SEXO", "EDAD DIA"])
    dia4 = base.loc[(1071, "H", 4)]
    assert dia4["TIPO DATO"] == "REAL"
    assert dia4["SALDO H"] == 35000 and dia4["ALIM H"] == 700 and dia4["MORTALIDAD H"] == 0.01
    assert dia4["PROY ALIM H/AVE"] == pytest.approx(700 * 1000 / 35000)  # g/ave a partir del consumo real
    assert dia4["GRANJA"] == "FILADELFIA 2" and dia4["REGION"] == "CENTRO"  # granja del registro real
    assert dia4["ETAPA"] == "LEVANTE"
    # Antes del primer día real se proyecta desde las aves iniciales; los machos no tienen reales.
    assert base.loc[(1071, "H", 2), "TIPO DATO"] == "PROYECTADO"
    assert base.loc[(1071, "H", 2), "AVES+2%"] == pytest.approx(35300 * 1.02)
    assert (base.loc[(1071, "M"), "TIPO DATO"] == "PROYECTADO").all()
    assert (base.loc[1072, "TIPO DATO"] == "PROYECTADO").all()


def test_despues_del_ultimo_dia_real_se_proyecta_desde_su_saldo(lote_sexo, referencia):
    reales = _reales(**{"EDAD DIA": [4], "SALDO H": [35000.0]})
    base = construir_proyeccion(lote_sexo, referencia, PARAMETROS, reales).set_index(["LOTE", "SEXO", "EDAD DIA"])
    # Mortalidad del estándar 006 sintético: 0,1 % por día acumulado (día 4: 0,4 %; día 6: 0,6 %).
    dia6 = base.loc[(1071, "H", 6)]
    assert dia6["TIPO DATO"] == "PROYECTADO"
    assert dia6["SALDO H"] == pytest.approx(35000 * (1 - 0.006) / (1 - 0.004))
    assert dia6["AVES+2%"] == 36000  # aves de la etapa del último día real
    # Mortalidad real del día 4 (1 %) más las muertes proyectadas desde entonces; las 1.000 aves que faltan
    # entre AVES+2% y el saldo real (p. ej. vendidas) no cuentan como mortalidad.
    assert dia6["MORTALIDAD H"] == pytest.approx(0.01 + (35000 - dia6["SALDO H"]) / 36000)
    assert dia6["ALIM H"] == pytest.approx(dia6["SALDO H"] * 26 / 1000)  # estándar: 20 + edad g/ave
    assert dia6["GRANJA"] == "AGUILAS 1"  # granja actual del lote
    # Consumo acumulado por ave: proyectado días 1-3, real el 4 y proyectado el 5 y 6.
    assert dia6["CONSUMO ACUM"] == pytest.approx(21 + 22 + 23 + 700 * 1000 / 35000 + 25 + 26)


def test_sociedad_segun_regional_de_la_granja():
    lotes = pd.DataFrame({"CENTRO GRANJA": ["R001", "R501", "E501", "R999", "R000"]}, index=[10, 11, 12, 13, 14])
    granjas = pd.DataFrame(
        {"farm_code": ["R001", "R501", "E501", "R999"], "regional_code": ["1GR", "1GV", " 1gb ", None]}
    )
    sociedades = sociedad_por_lote(lotes, granjas)
    assert sociedades.index.tolist() == [10, 11, 12, 13, 14]  # alineada con los lotes
    # R999 sin regional -> Oriente; R000 no existe en la base -> sin sociedad
    assert sociedades.iloc[:4].tolist() == ["ORIENTE", "OCCIDENTE", "OCCIDENTE", "ORIENTE"]
    assert pd.isna(sociedades.iloc[4])


def test_mortalidad_acumulada_empalma_el_reinicio_de_la_bd():
    estandar = pd.DataFrame(
        {
            "standard_code": ["X"] * 5,
            "age": [1, 2, 3, 4, 5],
            "mortality_percentage": [0.1, 0.1, 0.1, 0.05, 0.05],
            "accumulated_mortality_percentage": [0.1, 0.2, 0.3, 0.05, 0.1],  # reinicio el día 4
        }
    )
    esperado = [0.001, 0.002, 0.003, 0.0035, 0.004]
    assert mortalidad_acumulada(estandar, "acumulado_bd").tolist() == pytest.approx(esperado)
    assert mortalidad_acumulada(estandar, "suma_diaria").tolist() == pytest.approx(esperado)
    with pytest.raises(ValueError):
        mortalidad_acumulada(estandar, "otro")


@pytest.mark.parametrize(
    ("fecha", "semana"),
    [
        ("2026-01-01", 1),  # jueves
        ("2026-01-04", 1),  # domingo: aún semana 1
        ("2026-01-05", 2),  # lunes: inicia semana 2
        ("2026-12-31", 53),
        ("2027-01-01", 1),
        ("2027-01-04", 2),
    ],
)
def test_semana_anio_equivale_a_weeknum_tipo_2(fecha, semana):
    assert semana_anio_excel(pd.Series(pd.to_datetime([fecha]))).iloc[0] == semana
