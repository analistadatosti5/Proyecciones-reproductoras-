"""Configuración central: parámetros de negocio, columnas y valores por defecto.

Las credenciales y los servidores NO se definen aquí: se leen del archivo .env
(ver .env.example). Cualquier regla de negocio que pueda cambiar se ajusta en
este archivo y no en el código de cálculo.
"""

import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Rutas
# ---------------------------------------------------------------------------
# En el ejecutable (PyInstaller) __file__ está en una carpeta temporal que se borra
# al cerrar: el .env y la carpeta logs se buscan junto al .exe.
if getattr(sys, "frozen", False):
    RAIZ_PROYECTO = Path(sys.executable).resolve().parent
else:
    RAIZ_PROYECTO = Path(__file__).resolve().parent.parent
ARCHIVO_ENV = RAIZ_PROYECTO / ".env"
# El ejecutable puede llevar un .env adentro (PyInstaller --add-data); se usa si no hay uno junto al .exe.
ARCHIVO_ENV_INTERNO = Path(getattr(sys, "_MEIPASS", RAIZ_PROYECTO)) / ".env"
CARPETA_LOGS = RAIZ_PROYECTO / "logs"
ARCHIVO_LOG = CARPETA_LOGS / "proyecciones.log"

# ---------------------------------------------------------------------------
# Parámetros de la proyección
# ---------------------------------------------------------------------------
SEMANA_FINAL_DEFECTO = 64  # 64 semanas x 7 = 448 días, desde el día 1
SEMANA_FINAL_MAXIMA = 100  # tope de la interfaz; la cobertura real se valida contra el estándar
DIAS_POR_SEMANA = 7

PORCENTAJE_MACHOS = 0.15  # machos pedido = hembras pedido x 15 %
PORCENTAJE_ADICIONAL = 0.02  # aves adicionales que regala la casa genética (+2 %)

# Cómo se obtiene MORTALIDAD H (fracción acumulada desde el día 1) a partir del estándar:
#   "acumulado_bd": usa accumulated_mortality_percentage. La BD reinicia ese acumulado
#                   al iniciar producción (día 176), así que se le suma lo acumulado
#                   hasta el reinicio para obtener un acumulado continuo.
#   "suma_diaria":  suma día a día mortality_percentage. Ese valor viene redondeado a
#                   2 decimales en la BD y sobreestima la mortalidad (~1,4 puntos en ROSSAP
#                   hembra a la semana 64).
METODO_MORTALIDAD = "acumulado_bd"
METODOS_MORTALIDAD = ("acumulado_bd", "suma_diaria")

# ---------------------------------------------------------------------------
# Estándares (avi_granjas: core.standard_header / core.standard_data)
# ---------------------------------------------------------------------------
CLASE_LOTE_REPRODUCTORAS = "R"  # batch_class: siempre 'R' para reproductoras
RAZAS_PERMITIDAS = ("ROSSAP", "COBB M")  # razas habilitadas en esta versión (insumo)
# Estándar de las líneas y sexos que tienen más de uno en standard_header (lotes reales).
# ROSS hembra: 002 (normal) y 005 (sobrepeso); en Granjas_BI casi todos los lotes usan 002.
ESTANDAR_PREFERIDO = {("ROSS", "H"): "002"}
SEXO_HEMBRA = "H"
SEXO_MACHO = "M"
ETAPAS = {"L": "LEVANTE", "P": "PRODUCCIÓN"}  # traducción de standard_data.stage

# ---------------------------------------------------------------------------
# Granjas y regiones (analitica: public.mnl_broiler_breeder_farms)
# ---------------------------------------------------------------------------
REGION_OCCIDENTE = "BUGA"  # todas las granjas de la sociedad OCCIDENTE, sin importar la zona
# Granjas de ORIENTE: CENTRO si su zona está en ZONAS_REGION_CENTRO; si no, REGION_POR_DEFECTO.
ZONAS_REGION_CENTRO = frozenset({"ZONA 6 REPRODUCTORAS"})  # zone_name en mayúsculas
REGION_CENTRO = "CENTRO"
REGION_POR_DEFECTO = "SANTANDER"  # las demás granjas de ORIENTE
CLASE_GRANJA_REPRODUCTORAS = "R"  # flock_class esperado
ESTADO_GRANJA_ACTIVA = "A"

# ---------------------------------------------------------------------------
# Sociedades: se genera un archivo de resultado por cada una
# ---------------------------------------------------------------------------
SOCIEDADES = {"ORIENTE": "1000", "OCCIDENTE": "2000"}  # nombre -> código; también es el orden de los archivos
SOCIEDAD_OCCIDENTE = "OCCIDENTE"
SOCIEDAD_POR_DEFECTO = "ORIENTE"  # granjas de cualquier otro regional, o sin regional
# regional_code (mnl_broiler_breeder_farms) de Occidente. Las reproductoras del Valle
# están en 1GV; 1GB agrupa las granjas de engorde de esa misma región.
REGIONALES_OCCIDENTE = frozenset({"1GB", "1GV"})

# ---------------------------------------------------------------------------
# Datos reales de los lotes (Granjas_BI, SQL Server)
# ---------------------------------------------------------------------------
# Los días con registros en DiaReproductora reemplazan a los proyectados; los demás se
# proyectan desde el último saldo real con la mortalidad y el consumo del estándar.
PATRON_GRANJA_REPRODUCTORAS = "R%"  # EncasetamientoCabecera.Granja (las granjas E... son de engorde)
DIAS_HISTORIA_REALES = 600  # se consideran los encasetamientos de los últimos N días
DIAS_LOTE_ACTIVO = 7  # lote activo: tiene registros en los últimos N días hasta la fecha de corte
# Fecha de corte: último día con carga completa. Un día está incompleto si tiene menos de esta
# fracción de las cabeceras con registros de la mediana de los DIAS_REFERENCIA_CARGA días anteriores.
FRACCION_DIA_COMPLETO = 0.9
DIAS_REFERENCIA_CARGA = 7
DIAS_TOLERANCIA_ENCASETAMIENTO = 30  # se advierte si la fecha real difiere más de N días de la del insumo
TIPO_DATO_REAL = "REAL"
TIPO_DATO_PROYECTADO = "PROYECTADO"
# Día sin registro del lote antes de su último registro (un día suelto, un período largo o los días
# anteriores al primer registro): no se proyecta (consumo 0).
TIPO_DATO_SIN_REGISTRO = "SIN REGISTRO"

# ---------------------------------------------------------------------------
# Archivo de insumo
# ---------------------------------------------------------------------------
COLUMNAS_INSUMO = ("LOTE", "FECHA ENCASETAMIENTO", "CENTRO GRANJA", "NUCLEO", "RAZA", "HEMBRAS PEDIDO")
EXTENSIONES_INSUMO = (".xlsx", ".xlsm")
ANIO_MINIMO_ENCASETAMIENTO = 2000
ANIO_MAXIMO_ENCASETAMIENTO = 2100

# ---------------------------------------------------------------------------
# Archivo de resultado
# ---------------------------------------------------------------------------
COLUMNAS_RESULTADO = (
    "LOTE",
    "SEMANA",
    "EDAD DIA",
    "SEXO",
    "FECHA",
    "FECHA ENCASETAMIENTO",
    "LÍNEA",
    "AVES+2%",
    "SALDO H",
    "PROY ALIM H/AVE",
    "ALIM H",
    "MORTALIDAD H",
    "SEMANA AÑO",
    "TIPO ALIMENTO",
    "REGION",
    "ETAPA",
    "CONSUMO ACUM",
    "GRANJA",
    "SOCIEDAD",
    "TIPO DATO",  # REAL (Granjas_BI), SIN REGISTRO o PROYECTADO
)
HOJA_BASE = "BD_LOTE"
HOJA_VALIDACIONES = "VALIDACIONES"
NOMBRE_RANGO_BASE = "DATOS_PROYECCION"  # nombre definido: origen de las tablas dinámicas
MAX_FILAS_EXCEL = 1_048_575  # filas de datos disponibles en una hoja (sin encabezado)
MENSAJES_MAXIMOS_EN_PANTALLA = 200  # el resto se consulta en la hoja VALIDACIONES

# Tabla dinámica (hoja TABLERO, equivalente a la que se entrega a la Dirección de Reproductoras).
# Filas: año y mes de TABLA_DINAMICA_FECHA; columnas: TABLA_DINAMICA_COLUMNAS; valor: suma de TABLA_DINAMICA_VALOR.
HOJA_TABLA_DINAMICA = "TABLERO"
NOMBRE_TABLA_DINAMICA = "TD_CONSUMO_ALIMENTO"
TABLA_DINAMICA_FILTROS = ("LÍNEA", "REGION", "GRANJA", "LOTE", "TIPO DATO")
TABLA_DINAMICA_FECHA = "FECHA"
TABLA_DINAMICA_COLUMNAS = "TIPO ALIMENTO"
TABLA_DINAMICA_VALOR = "ALIM H"  # kg proyectados (el TABLERO anterior sumaba CONSUMO ACUM, g acumulados por ave)

# ---------------------------------------------------------------------------
# Base de datos
# ---------------------------------------------------------------------------
# Prefijo de las variables de entorno de cada base (ver .env.example)
BD_ESTANDARES = "AVI_GRANJAS"
BD_MATERIALES = "COMMERCIAL_BI"
BD_GRANJAS = "ANALITICA"
BD_REALES = "GRANJAS_BI"  # SQL Server
PUERTO_BD_DEFECTO = 5432
PUERTO_SQL_SERVER_DEFECTO = 1433
# Controladores ODBC en orden de preferencia; "SQL Server" viene con Windows.
# Se puede forzar uno con la variable GRANJAS_BI_DRIVER del .env.
CONTROLADORES_SQL_SERVER = ("ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server", "SQL Server")
TIEMPO_CONEXION_S = 10
TIEMPO_MAXIMO_CONSULTA_MS = 120_000
NOMBRE_APLICACION_BD = "proyeccion_consumo_reproductoras"
