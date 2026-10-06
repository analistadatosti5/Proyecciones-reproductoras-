"""Pruebas de tabla_dinamica.py que no requieren Excel."""

import pytest

from proyecciones import tabla_dinamica
from proyecciones.modelos import ErrorExportacion


def test_sin_pywin32_informa_como_instalarlo(monkeypatch, tmp_path):
    monkeypatch.setattr(tabla_dinamica, "pythoncom", None)
    with pytest.raises(ErrorExportacion, match="pywin32"):
        tabla_dinamica.agregar_tabla_dinamica(tmp_path / "proyeccion.xlsx")
