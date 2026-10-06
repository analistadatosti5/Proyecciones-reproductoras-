"""Datos sintéticos compartidos por las pruebas (no se usa la base de datos)."""

import pandas as pd
import pytest

from proyecciones.modelos import DatosReferencia

DIAS_ESTANDAR = 14  # el estándar sintético cubre 2 semanas


def _estandar(codigo: str, consumo_base: int, alimento_levante: str, alimento_produccion: str) -> list[dict]:
    """Días 1-7 levante y 8-14 producción. Como en la BD real, el acumulado de
    mortalidad se reinicia al iniciar producción (día 8)."""
    filas, consumo_acumulado = [], 0.0
    for edad in range(1, DIAS_ESTANDAR + 1):
        produccion = edad >= 8
        consumo = float(consumo_base + edad)
        consumo_acumulado += consumo
        filas.append(
            {
                "standard_code": codigo,
                "age": edad,
                "week_number": (edad - 1) // 7 + 1,
                "bird_consumption": consumo,
                "accumulated_bird_consumption": consumo_acumulado,
                "feed_type": alimento_produccion if produccion else alimento_levante,
                "mortality_percentage": 0.1,
                "accumulated_mortality_percentage": round(0.1 * (edad - 7 if produccion else edad), 4),
                "stage": "P" if produccion else "L",
            }
        )
    return filas


@pytest.fixture
def referencia() -> DatosReferencia:
    return DatosReferencia(
        encabezados=pd.DataFrame(
            {
                "standard_code": ["006", "007"],
                "breed": ["ROSSAP", "ROSSAP"],
                "sex": ["H", "M"],
                "description": ["HEMBRA REPRODUCTORA ROSSAP", "MACHO REPRODUCTOR ROSSAP"],
            }
        ),
        estandar=pd.DataFrame(
            _estandar("006", 20, "05356", "05492") + _estandar("007", 30, "05356", "05587")
        ),
        materiales={
            5356: "ALIMENTO POLLITA GRANEL",
            5492: "ALIMENTO FASE 1 ROSS HARINA GRANEL",
            5587: "ALIMENTO MACHOS HARINA GRANEL",
        },
        granjas=pd.DataFrame(
            {
                "farm_code": ["R001", "R021"],
                "farm_name": ["AGUILAS", "FILADELFIA"],
                "zone_name": ["ZONA 3 REPRODUCTORAS", "ZONA 6 REPRODUCTORAS"],
                "regional_code": ["1GR", "1GR"],
                "flock_class": ["R", "R"],
                "status": ["A", "A"],
            }
        ),
        nucleos=pd.DataFrame({"farm_code": ["R001", "R021"], "nucleus": ["1", "1"]}),
    )


@pytest.fixture
def lotes() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "FILA": [2, 3],
            "LOTE": [1071, 1072],
            "FECHA ENCASETAMIENTO": pd.to_datetime(["2026-09-16", "2026-12-30"]),
            "CENTRO GRANJA": ["R001", "R021"],
            "NUCLEO": ["1", "1"],
            "RAZA": ["ROSSAP", "ROSSAP"],
            "HEMBRAS PEDIDO": [35300.0, 10000.0],
        }
    )


@pytest.fixture
def mapa_estandar() -> dict[tuple[str, str], str]:
    return {("ROSSAP", "H"): "006", ("ROSSAP", "M"): "007"}
