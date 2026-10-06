"""Punto de entrada de la aplicación.

Uso:  python main.py
"""

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

from proyecciones import config
from proyecciones.gui import iniciar


def _manejador(carpeta: Path) -> RotatingFileHandler:
    carpeta.mkdir(parents=True, exist_ok=True)
    return RotatingFileHandler(carpeta / config.ARCHIVO_LOG.name, maxBytes=1_000_000, backupCount=3, encoding="utf-8")


def configurar_registro() -> None:
    """Registra eventos y errores inesperados en logs/proyecciones.log (archivo rotativo).

    Si la carpeta del programa no permite escribir (p. ej. Archivos de programa), usa la del usuario.
    """
    try:
        manejador = _manejador(config.CARPETA_LOGS)
    except OSError:
        config.CARPETA_LOGS = Path(os.getenv("LOCALAPPDATA", Path.home())) / "ProyeccionesReproductoras" / "logs"
        config.ARCHIVO_LOG = config.CARPETA_LOGS / config.ARCHIVO_LOG.name
        manejador = _manejador(config.CARPETA_LOGS)
    logging.basicConfig(
        level=logging.INFO,
        handlers=[manejador],
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


if __name__ == "__main__":
    configurar_registro()
    iniciar()
