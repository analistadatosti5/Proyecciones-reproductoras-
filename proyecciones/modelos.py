"""Estructuras de datos compartidas y excepciones de la aplicación."""

from dataclasses import dataclass
from enum import Enum

import pandas as pd

from . import config


# ---------------------------------------------------------------------------
# Excepciones: su mensaje está pensado para mostrarse tal cual al usuario.
# ---------------------------------------------------------------------------
class ErrorProyeccion(Exception):
    """Error controlado de la aplicación."""


class ErrorConfiguracion(ErrorProyeccion):
    """Falta o es inválida una variable del archivo .env."""


class ErrorInsumo(ErrorProyeccion):
    """El archivo de insumo no se puede leer o no tiene la estructura esperada."""


class ErrorBaseDatos(ErrorProyeccion):
    """Falló la conexión o una consulta a la base de datos."""


class ErrorExportacion(ErrorProyeccion):
    """No fue posible escribir el Excel de resultado."""


# ---------------------------------------------------------------------------
# Mensajes de validación
# ---------------------------------------------------------------------------
class Nivel(str, Enum):
    ERROR = "ERROR"  # impide generar la proyección
    ADVERTENCIA = "ADVERTENCIA"  # se genera, pero conviene revisar
    INFO = "INFO"  # informativo


@dataclass(frozen=True)
class Mensaje:
    nivel: Nivel
    origen: str
    detalle: str
    fila: int | None = None  # fila del Excel de insumo (la 1 es el encabezado)
    lote: str | None = None


# ---------------------------------------------------------------------------
# Parámetros y datos de referencia
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ParametrosProyeccion:
    semana_final: int = config.SEMANA_FINAL_DEFECTO
    porcentaje_machos: float = config.PORCENTAJE_MACHOS
    porcentaje_adicional: float = config.PORCENTAJE_ADICIONAL
    metodo_mortalidad: str = config.METODO_MORTALIDAD

    @property
    def dias(self) -> int:
        """Días a proyectar: desde el día 1 hasta semana_final x 7."""
        return self.semana_final * config.DIAS_POR_SEMANA


@dataclass
class DatosReferencia:
    """Información consultada en las bases de datos, con tipos ya normalizados."""

    encabezados: pd.DataFrame  # standard_code, breed, sex, description
    estandar: pd.DataFrame  # standard_code, age, bird_consumption, ... (un registro por día)
    materiales: dict[int, str]  # código de material -> nombre
    granjas: pd.DataFrame  # farm_code, farm_name, zone_name, regional_code, flock_class, status
    nucleos: pd.DataFrame  # farm_code, nucleus


@dataclass
class DatosReales:
    """Información de Granjas_BI (SQL Server) con tipos ya normalizados."""

    fecha_corte: pd.Timestamp | None  # último día con carga completa; lo posterior se proyecta
    carga: pd.DataFrame  # fecha, cabeceras: cabeceras de reproductoras con registros por día
    cabeceras: pd.DataFrame  # id_encaseta, lote, granja, nucleo, etapa, sexo, raza, codigo_estandar,
    #                          fecha_ingreso, cantidad, mortalidad_transporte, primer_registro, ultimo_registro
    dias: pd.DataFrame  # id_encaseta, fecha, sexo, edad, semana, linea, etapa y sumas del día (ver consultas.DIAS_REALES)

    @classmethod
    def vacios(cls) -> "DatosReales":
        return cls(None, pd.DataFrame(columns=["fecha", "cabeceras"]), pd.DataFrame(), pd.DataFrame())


@dataclass
class LotesReales:
    """Datos reales consolidados por lote (ver reales.consolidar)."""

    lotes: pd.DataFrame  # LOTE, FECHA ENCASETAMIENTO, CENTRO GRANJA, NUCLEO, RAZA (granja y línea actuales)
    lote_sexo: pd.DataFrame  # LOTE, SEXO, AVES+2% (aves encasetadas el día 1), CODIGO DETALLE
    diario: pd.DataFrame  # LOTE, SEXO, EDAD DIA, FECHA, SEMANA, LÍNEA, AVES+2%, SALDO H, ALIM H,
    #                       MORTALIDAD H, ETAPA, CENTRO GRANJA, NUCLEO (un registro por día con datos)
    granjas: pd.DataFrame  # LOTE, CENTRO GRANJA, NUCLEO: todas las granjas en que ha estado el lote
    mensajes: list[Mensaje]
