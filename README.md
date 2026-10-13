# Proyección de consumo de alimento – Reproductoras

Aplicación de escritorio (Python + Tkinter) que lee el Excel de insumo con los lotes a encasetar y genera, por cada sociedad (ORIENTE y OCCIDENTE), un Excel con la proyección diaria de aves y de consumo de alimento por lote, sexo y día (la base equivalente a `BD_LOTE`) y la tabla dinámica de consumo por tipo de alimento (hoja `TABLERO`).

Además de los lotes del insumo, incluye los lotes de reproductoras activos en Granjas_BI. Los días que ya tienen registro real reemplazan a los proyectados. Los días en que un lote no registró entre dos registros suyos no se proyectan, y los demás se proyectan desde el último saldo real (ver [Datos reales](#datos-reales-granjas_bi)).

Los estándares, los nombres de alimento y las granjas se consultan directamente en PostgreSQL, y los datos reales en SQL Server (Granjas_BI); en el código no hay consumos ni estándares digitados a mano.

## Instalación

Requisitos: Windows, Python 3.10 o superior, Microsoft Excel instalado (crea la tabla dinámica) y acceso de red a los servidores de base de datos (PostgreSQL y SQL Server). Para SQL Server basta el controlador ODBC "SQL Server" que trae Windows; si está instalado "ODBC Driver 17/18 for SQL Server", se usa ese.

```powershell
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env      # luego complete usuario y clave en .env
```

El archivo `.env` guarda servidores y credenciales. Está excluido del repositorio (`.gitignore`) y **nunca** debe copiarse en el código.

## Uso

```powershell
python main.py
```

1. **Examinar...**: seleccione el Excel de insumo.
2. **Semana final de proyección**: por defecto 64 (64 × 7 = 448 días, del día 1 al 448).
3. **Validar insumo** (opcional): revisa el archivo y lo cruza con las bases de datos sin generar resultado.
4. **Generar proyección**: pide dónde guardar el resultado, valida y genera un Excel por sociedad (ver [Sociedades](#sociedades)).

Si hay **errores**, no se genera el archivo y se listan en pantalla con su fila y lote. Las **advertencias** no detienen el proceso y quedan en la hoja `VALIDACIONES`.

## Archivo de insumo

Una fila por lote, con estas columnas (en cualquier orden y en cualquier hoja; se ignoran tildes, mayúsculas y columnas adicionales):

| Columna | Regla |
|---|---|
| LOTE | Entero positivo, sin repetidos |
| FECHA ENCASETAMIENTO | Fecha válida; si trae hora, se descarta |
| CENTRO GRANJA | Código de granja (ej. R001); debe existir en la base de granjas |
| NUCLEO | Número o grupo de números (1, 2-3, 3-2-6) |
| RAZA | ROSSAP o COBB M (`RAZAS_PERMITIDAS` en `config.py`) |
| HEMBRAS PEDIDO | Número mayor que cero, **sin** el 2 % adicional |

## Archivo de resultado

### Sociedades

Se genera un archivo por sociedad, con el nombre elegido y la sociedad al final: `Proyeccion_..._ORIENTE.xlsx` y `Proyeccion_..._OCCIDENTE.xlsx`. Si el insumo no tiene lotes de una sociedad, no se crea su archivo.

| Sociedad | Código | Granjas (`regional_code` en `mnl_broiler_breeder_farms`) |
|---|---|---|
| ORIENTE | 1000 | Todos los demás regionales (hoy las reproductoras están en 1GR) o sin regional |
| OCCIDENTE | 2000 | 1GB y 1GV (`REGIONALES_OCCIDENTE` en `config.py`). Las reproductoras del Valle están en 1GV; 1GB son granjas de engorde |

Los dos archivos tienen la misma estructura y los mismos cálculos. La hoja `VALIDACIONES` de cada uno incluye los mensajes generales y los de sus propios lotes.

### Hojas

| Hoja | Contenido |
|---|---|
| TABLERO | Tabla dinámica: suma de `ALIM H` (kg) con filas por año y mes de la FECHA, columnas por TIPO ALIMENTO y filtros LÍNEA, REGION, GRANJA, LOTE y TIPO DATO |
| BD_LOTE | Un registro por lote × sexo × día. Tiene autofiltro y el nombre definido `DATOS_PROYECCION`, que es el origen de la tabla dinámica |
| VALIDACIONES | Errores, advertencias e información de la ejecución |

La tabla dinámica la crea Microsoft Excel al final del proceso (con pywin32), en una instancia propia que no afecta los libros que el usuario tenga abiertos; toma unos 10 segundos. Si Excel no está disponible, el archivo se entrega sin la hoja `TABLERO` y se muestra una advertencia.

Columnas de `BD_LOTE` en los días proyectados (los días reales se describen en [Datos reales](#datos-reales-granjas_bi)):

| Columna | Cálculo / fuente |
|---|---|
| LOTE, FECHA ENCASETAMIENTO | Insumo (en los lotes de Granjas_BI, el día 1 real) |
| SEMANA | 1 a semana final: `(EDAD DIA - 1) // 7 + 1` |
| EDAD DIA | 1 a semana final × 7 |
| SEXO | H (hembra) y M (macho) |
| FECHA | FECHA ENCASETAMIENTO + EDAD DIA − 1 (el día 1 es el mismo día del encasetamiento) |
| LÍNEA | RAZA del insumo (en los lotes de Granjas_BI, su línea genética) |
| AVES+2% | H: hembras pedido × 1,02 · M: hembras pedido × 0,15 × 1,02 (sin redondeo, como el Excel anterior). En los lotes de Granjas_BI, las aves encasetadas; después de un día real, las de la etapa de ese día |
| MORTALIDAD H | Mortalidad acumulada desde el día 1, en fracción (ver reglas). Después de un día real *a*: MORTALIDAD real(*a*) + (SALDO(*a*) − SALDO H) / AVES+2% (las ventas y traslados no cuentan como mortalidad) |
| SALDO H | AVES+2% − AVES+2% × MORTALIDAD H. Después de un día real *a*: SALDO real(*a*) × (1 − m) / (1 − m(*a*)), con *m* la mortalidad acumulada del estándar |
| PROY ALIM H/AVE | `standard_data.bird_consumption` (g/ave/día) |
| ALIM H | SALDO H × PROY ALIM H/AVE / 1000 (kg/día) |
| SEMANA AÑO | Igual a `WEEKNUM(FECHA; 2)` de Excel: semanas desde el lunes, la semana 1 contiene el 1 de enero |
| TIPO ALIMENTO | `standard_data.feed_type` → `commercial_bi.public.materials.name` |
| REGION | OCCIDENTE: siempre BUGA. ORIENTE: CENTRO si la granja está en `ZONA 6 REPRODUCTORAS`; SANTANDER en los demás casos |
| ETAPA | `standard_data.stage`: L → LEVANTE, P → PRODUCCIÓN |
| CONSUMO ACUM | `standard_data.accumulated_bird_consumption` (g/ave acumulado). En los lotes con días reales: suma de PROY ALIM H/AVE desde el día 1 |
| GRANJA | `farm_name` de la granja + espacio + NUCLEO (ej. AGUILAS 1); en los lotes de Granjas_BI, la granja actual |
| SOCIEDAD | ORIENTE u OCCIDENTE según el regional de la granja del registro (ver [Sociedades](#sociedades)) |
| TIPO DATO | PROYECTADO; REAL en los días con registro en Granjas_BI; SIN REGISTRO en los días en que el lote no registró entre dos registros suyos (ver [Datos reales](#datos-reales-granjas_bi)) |

## Datos reales (Granjas_BI)

Se consultan en SQL Server (base `Granjas_BI`; servidor y credenciales en `.env`) con 3 consultas para todos los lotes:

- `EncasetamientoCabecera`: una cabecera por etapa del lote en una granja: levante (L) y producción (P). Si el lote cambia de granja en el levante hay dos cabeceras de levante: origen (Clase O) y destino (Clase D). Solo se usan las de granjas de reproductoras (código que empieza por R); las granjas E son de engorde. Se descartan las cabeceras sin aves ni registros (por ejemplo R999/R000 con cantidad 0).
- `EncasetamientoDetalle`: aves encasetadas (`Cantidad`), fecha de ingreso y estándar (`CodEstandar`) de cada cabecera y sexo.
- `DiaReproductora`: un registro por cabecera, galpón, división, sexo y día; se suman galpones y divisiones.

**Qué lotes**: los del insumo más los **activos** (con registros en los últimos `DIAS_LOTE_ACTIVO` = 7 días hasta la fecha de corte). Si un lote del insumo ya existe en Granjas_BI se usan sus datos reales (fecha, granja, núcleo, línea y aves) y se informa en `VALIDACIONES`; si su fecha difiere más de 30 días o su línea es otra, queda como advertencia.

**Fecha de corte**: último día con carga completa. Granjas_BI carga los registros con rezago, así que se descartan los últimos días con menos del 90 % de las cabeceras habituales (mediana de los 7 días anteriores). La fecha de corte y los días descartados quedan en `VALIDACIONES`, igual que los días sin ningún registro (por ejemplo, del 11/09/2026 al 06/10/2026 no hay carga).

**Días reales** (TIPO DATO = REAL), por lote, sexo y día:

| Columna | Fuente |
|---|---|
| SEMANA, EDAD DIA, SEXO, FECHA, LÍNEA, ETAPA | `edadSemanas`, `edadDias`, `sexo`, `fecha`, `lineaGenetica`, `etapa` de DiaReproductora |
| AVES+2% | Aves encasetadas en la etapa: `Cantidad` de EncasetamientoDetalle, validada con `avesEncasetadas` del primer día de la etapa en DiaReproductora; si no coinciden, `Cantidad − MortalidadTrans` (con advertencia). En los datos revisados siempre coinciden |
| SALDO H | AVES+2% − acumulado de (selección + mortalidad + mortalidadTransporte + avesVendidas + avesSacrificio) + acumulado de (avesAgregadas − avesTransferidas), dentro de la etapa. Así cuadra exacto con las aves encasetadas en la etapa siguiente |
| MORTALIDAD H | Acumulado de (selección + mortalidad) / AVES+2%, dentro de la etapa |
| ALIM H | `consumo` (kg) |
| PROY ALIM H/AVE | ALIM H × 1000 / SALDO H (g/ave) |
| TIPO ALIMENTO | Estándar por línea genética y sexo, en la edad del registro. Si la línea tiene más de un estándar se usa el `CodEstandar` del lote; si tampoco lo resuelve, `ESTANDAR_PREFERIDO` en `config.py` (ROSS hembra → 002; el 005 es "sobrepeso") |
| REGION, GRANJA, SOCIEDAD | Granja y núcleo de la cabecera de ese día |

El día de un traslado entre granjas, cuando las dos cabeceras tienen registros, se toman el saldo, la granja y la etapa de la más reciente y se suma el consumo de ambas.

**Días sin registro del lote** (TIPO DATO = SIN REGISTRO): los días sin registro del lote hasta su último registro **no se proyectan**, sea un día suelto, un período largo o los días anteriores al primer registro. Quedan con ALIM H = 0. Los días entre dos registros llevan el saldo, la mortalidad, la etapa y la granja del registro anterior. Los anteriores al primer registro llevan las aves encasetadas como saldo, mortalidad 0, y la etapa y la granja del primer registro. En los datos revisados (12/10/2026) hay tres casos:

- Días sueltos del levante (semanas 5 a 24), casi siempre domingo, miércoles o jueves. El registro siguiente trae un consumo normal y las salidas de aves de los dos días.
- Del 11/09/2026 al 06/10/2026 Granjas_BI no tiene carga de ninguna granja; esos días quedan como SIN REGISTRO en todos los lotes con registros antes y después.
- Lotes encasetados durante ese período (241, 242 y 1071), cuyo primer registro es el 07/10/2026; se informan con una advertencia.

Como esos días suman 0, en estos lotes CONSUMO ACUM queda por debajo del consumo real por ave. Los días posteriores al último registro se proyectan desde ese saldo real, con la mortalidad y el consumo del estándar, hasta la semana final.

## Reglas y fuentes de datos

- **Estándar**: en `avi_granjas.core.standard_header` se busca el estándar por raza y sexo, siempre con `batch_class = 'R'`; debe existir exactamente uno por combinación (hoy 006 ROSSAP-H, 007 ROSSAP-M, 008 COBB M-H y 009 COBB M-M). Luego se leen sus valores diarios en `core.standard_data` por `age` (día de edad).
- **Mortalidad** (`METODO_MORTALIDAD` en `config.py`):
  - `acumulado_bd` (por defecto): usa `accumulated_mortality_percentage` / 100. La base reinicia ese acumulado al iniciar producción (día 176); la aplicación le suma lo acumulado en levante para obtener un acumulado continuo desde el día 1, que es lo que requiere la fórmula de SALDO H.
  - `suma_diaria`: suma día a día `mortality_percentage` / 100. Ese valor viene redondeado a 2 decimales y sobreestima la mortalidad (ROSSAP hembra a la semana 64: 12,6 % frente a 11,2 %).
- **Rendimiento**: se hacen 8 consultas en total (5 en PostgreSQL y 3 en Granjas_BI, con todos los lotes a la vez, parametrizadas y en conexiones de solo lectura), no una por lote o por día. La consulta de estándares usa el índice `(standard_code, age, ...)`.

## Validaciones

Errores (detienen la generación):
- Faltan columnas requeridas, o hay valores vacíos o inválidos, lotes repetidos o razas no permitidas.
- La granja no existe en `mnl_broiler_breeder_farms` o no es de reproductoras.
- No hay estándar, o hay más de uno, para una raza y sexo (en los lotes de Granjas_BI, solo si tampoco lo resuelven el estándar del lote ni `ESTANDAR_PREFERIDO`).
- El estándar no cubre todos los días hasta la semana final (hoy llega hasta el día 483, semana 69).
- La proyección de una sociedad superaría el máximo de filas de una hoja de Excel.

Advertencias (se genera igual):
- La granja está inactiva, no tiene zona (solo en ORIENTE; se le asigna SANTANDER) o no tiene regional (se asigna a ORIENTE).
- El núcleo no está registrado en `mnl_broiler_breeder_house_details`.
- El alimento del estándar no existe en `materials` (se muestra el código).
- El consumo acumulado del estándar no coincide con la suma de su consumo diario.
- Granjas_BI: las aves encasetadas del detalle no coinciden con las del primer día; las salidas superan las aves de la etapa (el saldo se deja en 0); un lote del insumo ya encasetado con otra fecha o línea; lotes sin registros desde el encasetamiento (con la fecha y el día de edad de su primer registro).

Información: fecha de corte de los datos reales, días sin carga en Granjas_BI, días sin registro de cada lote (SIN REGISTRO) y lotes del insumo que ya están encasetados.

## Diferencias frente al Excel anterior

| Tema | Excel anterior | Aplicación |
|---|---|---|
| Archivos | Un solo libro con todas las granjas | Un archivo por sociedad (ORIENTE / OCCIDENTE) según el regional de la granja |
| Datos reales | Solo las aves encasetadas reales digitadas en `RECEPCIONES`; todos los días se calculan con el estándar | Los días con registro en Granjas_BI son reales (aves, saldo, consumo); los días sin registro del lote entre dos registros suyos quedan en 0; los demás se proyectan desde el último saldo real |
| Lotes | Los digitados en `RECEPCIONES` | Los del insumo más los activos en Granjas_BI |
| FECHA | FECHA ENCASETAMIENTO + EDAD DIA (el día 1 es el día siguiente al encasetamiento) | FECHA ENCASETAMIENTO + EDAD DIA − 1 (el día 1 es el día del encasetamiento, como en Granjas_BI) |
| Horizonte | 455 días (65 semanas) | Parámetro; por defecto 448 días (64 semanas) |
| Estándar de consumo y alimento | Hoja `CONS PROY` digitada, por semana | `core.standard_data` por día |
| Mortalidad | Hoja `MORT PROY`: 0,03 %/día (H) y 0,055 %/día (M) constantes para todas las líneas | Estándar de la base por línea, sexo y día |
| Nombres de alimento | Cortos (POLLITA, FASE 1 ROSS…) | Nombre del material (ALIMENTO POLLITA GRANEL…) |
| CONSUMO ACUM | Suma de valores semanales que se reinicia en la semana 25 | Acumulado g/ave de la base desde el día 1 |
| Tabla dinámica del TABLERO | Suma **CONSUMO ACUM** (gramos acumulados por ave) | Suma **ALIM H** (kg proyectados); se cambia con `TABLA_DINAMICA_VALOR` en `config.py` |
| Región | Lista manual (R999 = NUEVA, región 0) | OCCIDENTE: BUGA; ORIENTE: zona de la granja en la base (R999 = COMPRA HUEVOS, regional 1GV: BUGA) |
| Granja | Nombre manual (VENT-1-LA VENTA, LIRIOS Y CORRALES) | `farm_name` + núcleo (VENTANITAS 1 1, LOS LIRIOS-EL CORRAL 1) |
| Columnas ID, ID MORT, ID GENÉTICA | Llaves de búsqueda | Eliminadas |

## Estructura del proyecto y dónde modificar

```
main.py                  punto de entrada (interfaz gráfica y registro en logs/)
construir_exe.ps1        genera el ejecutable dist\ProyeccionesReproductoras.exe
proyecciones/
  config.py              parámetros de negocio: % machos, % adicional, semana, razas, regiones, columnas
  modelos.py             estructuras de datos y excepciones
  db.py                  conexiones PostgreSQL (lee .env)
  consultas.py           todo el SQL de la aplicación
  repositorio.py         ejecuta las consultas y devuelve DataFrames
  insumo.py              lectura y validación del Excel de entrada
  reales.py              datos reales de Granjas_BI: fecha de corte, saldo y consolidación por lote y día
  validaciones.py        validaciones contra las bases de datos
  proyeccion.py          lógica de negocio (cálculos de la proyección)
  exportador.py          generación del Excel de salida (hojas BD_LOTE y VALIDACIONES)
  tabla_dinamica.py      hoja TABLERO: tabla dinámica creada con Excel
  servicio.py            orquesta el proceso (independiente de la interfaz)
  gui.py                 interfaz Tkinter
tests/                   pruebas automáticas (no requieren base de datos)
```

- Para cambiar un **porcentaje, la semana por defecto, las razas, la regla de regiones o los regionales de cada sociedad**, edite `config.py`.
- Para cambiar **qué lotes reales se incluyen o cómo se detecta la fecha de corte**, edite `DIAS_LOTE_ACTIVO`, `FRACCION_DIA_COMPLETO` y los demás parámetros de "Datos reales" en `config.py`.
- Para cambiar una **consulta**, edite `consultas.py` (no use el signo de porcentaje en el texto SQL: psycopg lo interpreta como parámetro).
- Para cambiar una **fórmula**, edite `proyeccion.py`.
- Para cambiar los **filtros, las columnas o el valor de la tabla dinámica**, edite `TABLA_DINAMICA_*` en `config.py`.
- Para cambiar **servidores o credenciales**, edite `.env`.

## Pruebas

```powershell
python -m pytest
```
