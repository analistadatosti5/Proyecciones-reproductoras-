"""Conexiones a PostgreSQL y a SQL Server (Granjas_BI).

Servidores, bases, usuario y clave se leen del archivo .env (nunca del código).
Para cada base se usan las variables <PREFIJO>_HOST y <PREFIJO>_DB; el usuario y
la clave son DB_USER / DB_PASSWORD, salvo que existan <PREFIJO>_USER /
<PREFIJO>_PASSWORD para esa base en particular.
"""

import functools
import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

import psycopg
import pyodbc
from dotenv import load_dotenv

from . import config
from .modelos import ErrorBaseDatos, ErrorConfiguracion


@dataclass(frozen=True)
class ConfiguracionBD:
    host: str
    puerto: int
    base: str
    usuario: str
    clave: str = field(repr=False)  # nunca se imprime ni se registra

    def descripcion(self) -> str:
        return f"{self.base} ({self.host}:{self.puerto})"


@functools.cache
def _cargar_env() -> None:
    """Carga el .env una sola vez. Las variables ya definidas en el sistema tienen prioridad.

    Se usa el .env junto al .exe (o al proyecto) y, si no existe, el que va dentro del ejecutable.
    """
    archivo = config.ARCHIVO_ENV if config.ARCHIVO_ENV.is_file() else config.ARCHIVO_ENV_INTERNO
    load_dotenv(archivo, override=False)


def configuracion_bd(
    prefijo: str, puerto_defecto: int = config.PUERTO_BD_DEFECTO, puerto_comun: bool = True
) -> ConfiguracionBD:
    """Arma la configuración de conexión de una base a partir de las variables de entorno.

    `puerto_comun=False` ignora DB_PORT (es el puerto de PostgreSQL, no sirve para SQL Server).
    """
    _cargar_env()
    variables = {
        "host": (f"{prefijo}_HOST",),
        "base": (f"{prefijo}_DB",),
        "usuario": (f"{prefijo}_USER", "DB_USER"),
        "clave": (f"{prefijo}_PASSWORD", "DB_PASSWORD"),
        "puerto": (f"{prefijo}_PORT", "DB_PORT") if puerto_comun else (f"{prefijo}_PORT",),
    }
    valores = {clave: next((os.getenv(n) for n in nombres if os.getenv(n)), None) for clave, nombres in variables.items()}

    faltantes = [variables[c][-1] for c in ("host", "base", "usuario", "clave") if not valores[c]]
    if faltantes:
        raise ErrorConfiguracion(
            f"Faltan variables en el archivo {config.ARCHIVO_ENV.name}: {', '.join(faltantes)}. "
            "Use .env.example como plantilla."
        )
    try:
        puerto = int(valores["puerto"] or puerto_defecto)
    except ValueError as exc:
        raise ErrorConfiguracion(f"El puerto configurado para {prefijo} no es un número: {valores['puerto']!r}") from exc

    return ConfiguracionBD(valores["host"], puerto, valores["base"], valores["usuario"], valores["clave"])


@contextmanager
def conectar(prefijo: str) -> Iterator[psycopg.Connection]:
    """Abre una conexión de solo lectura a la base indicada y la cierra al terminar."""
    cfg = configuracion_bd(prefijo)
    try:
        conexion = psycopg.connect(
            host=cfg.host,
            port=cfg.puerto,
            dbname=cfg.base,
            user=cfg.usuario,
            password=cfg.clave,
            connect_timeout=config.TIEMPO_CONEXION_S,
            application_name=config.NOMBRE_APLICACION_BD,
            options=f"-c statement_timeout={config.TIEMPO_MAXIMO_CONSULTA_MS}",
        )
    except psycopg.Error as exc:
        # psycopg repite el mensaje por cada intento de conexión: basta con el último.
        detalle = str(exc).strip().splitlines()[-1] if str(exc).strip() else type(exc).__name__
        raise ErrorBaseDatos(f"No fue posible conectar a {cfg.descripcion()}: {detalle}") from exc
    try:
        conexion.read_only = True  # la aplicación solo consulta
        yield conexion
    finally:
        conexion.close()


@contextmanager
def conectar_sql_server(prefijo: str) -> Iterator[pyodbc.Connection]:
    """Abre una conexión de solo lectura a una base SQL Server (ODBC) y la cierra al terminar."""
    cfg = configuracion_bd(prefijo, config.PUERTO_SQL_SERVER_DEFECTO, puerto_comun=False)
    controlador = _controlador_sql_server(prefijo)
    partes = [
        f"DRIVER={{{controlador}}}",
        f"SERVER={cfg.host},{cfg.puerto}",
        f"DATABASE={cfg.base}",
        f"UID={cfg.usuario}",
        f"PWD={{{cfg.clave.replace('}', '}}')}}}",  # entre llaves: la clave puede tener ; = % * +
        f"APP={config.NOMBRE_APLICACION_BD}",
        "ApplicationIntent=ReadOnly",
    ]
    if "18" in controlador:  # el controlador 18 cifra por defecto y exige un certificado válido
        partes.append("TrustServerCertificate=yes")
    try:
        conexion = pyodbc.connect(";".join(partes), timeout=config.TIEMPO_CONEXION_S, readonly=True)
    except pyodbc.Error as exc:
        raise ErrorBaseDatos(f"No fue posible conectar a {cfg.descripcion()}: {mensaje_odbc(exc)}") from exc
    try:
        conexion.timeout = config.TIEMPO_MAXIMO_CONSULTA_MS // 1000  # tiempo máximo por consulta (s)
        yield conexion
    finally:
        conexion.close()


def _controlador_sql_server(prefijo: str) -> str:
    """Primer controlador ODBC de SQL Server instalado (o el indicado en <PREFIJO>_DRIVER)."""
    instalados = set(pyodbc.drivers())
    preferido = os.getenv(f"{prefijo}_DRIVER")
    candidatos = ((preferido,) if preferido else ()) + config.CONTROLADORES_SQL_SERVER
    for controlador in candidatos:
        if controlador in instalados:
            return controlador
    raise ErrorConfiguracion(
        "No hay un controlador ODBC para SQL Server instalado. Instale 'ODBC Driver 17 for SQL Server' "
        f"o indique uno en la variable {prefijo}_DRIVER del archivo {config.ARCHIVO_ENV.name}."
    )


def mensaje_odbc(error: pyodbc.Error) -> str:
    """Texto legible de un error ODBC, sin los prefijos [Microsoft][ODBC Driver ...] ni los códigos."""
    texto = str(error.args[-1]) if error.args else type(error).__name__
    texto = texto.split("; [")[0]  # el controlador encadena varios mensajes: basta con el primero
    texto = re.sub(r"\[[^\]]*\]", "", texto)  # [Microsoft][ODBC Driver 17 for SQL Server][SQL Server]
    texto = re.sub(r"\s*\(\d+\)(\s*\(SQL\w+\))?\s*$", "", texto)  # (18456) (SQLDriverConnect)
    return texto.strip() or type(error).__name__
