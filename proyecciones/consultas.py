"""Consultas SQL de la aplicación (único lugar donde se escribe SQL).

PostgreSQL (psycopg) usa parámetros con nombre (%(nombre)s) y SQL Server (pyodbc)
parámetros posicionales (?); en ambos casos se envían por separado: nunca se
concatenan valores al texto de la consulta. Cada consulta trae de una sola vez lo
necesario para todos los lotes (no una consulta por lote o por día).
"""

# avi_granjas -----------------------------------------------------------------

# Estándar de cada raza y sexo (se espera exactamente uno por combinación), más los
# estándares que Granjas_BI asigna a los lotes reales (EncasetamientoDetalle.CodEstandar).
ENCABEZADOS_ESTANDAR = """
SELECT rtrim(standard_code)     AS standard_code,
       upper(trim(breed))       AS breed,
       upper(trim(sex))         AS sex,
       trim(description)        AS description
FROM core.standard_header
WHERE batch_class = %(clase)s
  AND ((upper(trim(breed)) = ANY(%(razas)s) AND upper(trim(sex)) = ANY(%(sexos)s))
       OR rtrim(standard_code) = ANY(%(codigos)s))
ORDER BY standard_code
"""

# Valores diarios del estándar (age = día de edad). Usa el índice (standard_code, age, ...).
# Nota: no usar el signo de porcentaje en el texto SQL (psycopg lo toma como parámetro).
DATOS_ESTANDAR = """
SELECT rtrim(standard_code)              AS standard_code,
       age,
       week_number,
       bird_consumption,                 -- g/ave/día         -> PROY ALIM H/AVE
       accumulated_bird_consumption,     -- g/ave acumulado   -> CONSUMO ACUM
       rtrim(feed_type)                  AS feed_type,        -- código de material -> TIPO ALIMENTO
       mortality_percentage,             -- porcentaje diario
       accumulated_mortality_percentage, -- porcentaje acumulado (se reinicia al iniciar producción)
       rtrim(stage)                      AS stage             -- L / P -> ETAPA
FROM core.standard_data
WHERE batch_class = %(clase)s
  AND standard_code = ANY(%(codigos)s)
  AND age BETWEEN 1 AND %(dias)s
ORDER BY standard_code, age
"""

# commercial_bi -----------------------------------------------------------------

# Nombre de los alimentos. materials.code es entero ('05670' -> 5670).
MATERIALES = """
SELECT code, trim(name) AS name
FROM public.materials
WHERE code = ANY(%(codigos)s)
"""

# analitica ---------------------------------------------------------------------

# Nombre, zona (para la región), regional (para la sociedad) y estado de las granjas del insumo.
GRANJAS = """
SELECT trim(farm_code)     AS farm_code,
       trim(farm_name)     AS farm_name,
       upper(trim(zone_name)) AS zone_name,
       upper(trim(regional_code)) AS regional_code,
       flock_class,
       status
FROM public.mnl_broiler_breeder_farms
WHERE trim(farm_code) = ANY(%(codigos)s)
"""

# Núcleos registrados por granja (para validar el NUCLEO del insumo).
NUCLEOS = """
SELECT DISTINCT trim(farm_code) AS farm_code,
                trim(nucleus)   AS nucleus
FROM public.mnl_broiler_breeder_house_details
WHERE trim(farm_code) = ANY(%(codigos)s)
"""

# Granjas_BI (SQL Server) -------------------------------------------------------
# Las listas se envían como un texto separado por comas que separa STRING_SPLIT.
# Las cabeceras de reproductoras son las de granjas R (patrón como parámetro: sin el
# signo de porcentaje en el texto); las de granjas E son de engorde.

# Cabeceras de reproductoras con registros en cada día: para la fecha de corte y los días sin carga.
CARGA_DIARIA_REALES = """
SELECT r.fecha, COUNT(DISTINCT r.idEncaseta) AS cabeceras
FROM dbo.DiaReproductora r
JOIN dbo.EncasetamientoCabecera c ON c.Id = r.idEncaseta
WHERE c.Granja LIKE ? AND r.fecha >= ? AND r.fecha < ?
GROUP BY r.fecha
"""

# Etapas (cabeceras) de los lotes de reproductoras encasetados desde una fecha, por sexo y
# estándar, con su primer y último día registrado en DiaReproductora hasta la fecha de corte.
CABECERAS_REALES = """
SELECT c.Id                  AS id_encaseta,
       c.Lote                AS lote,
       rtrim(c.Granja)       AS granja,
       rtrim(c.Nucleo)       AS nucleo,
       rtrim(c.Etapa)        AS etapa,
       rtrim(d.Sexo)         AS sexo,
       rtrim(d.Raza)         AS raza,
       rtrim(d.CodEstandar)  AS codigo_estandar,
       MIN(d.FechaIngreso)   AS fecha_ingreso,
       SUM(d.Cantidad)       AS cantidad,
       SUM(d.MortalidadTrans) AS mortalidad_transporte,
       MIN(r.primer_dia)     AS primer_registro,
       MAX(r.ultimo_dia)     AS ultimo_registro
FROM dbo.EncasetamientoCabecera c
JOIN dbo.EncasetamientoDetalle d ON d.IdEncaseta = c.Id
LEFT JOIN (
    SELECT idEncaseta, MIN(fecha) AS primer_dia, MAX(fecha) AS ultimo_dia
    FROM dbo.DiaReproductora
    WHERE fecha >= ? AND fecha <= ?
    GROUP BY idEncaseta
) r ON r.idEncaseta = c.Id
WHERE c.Granja LIKE ?
  AND rtrim(c.Etapa) IN ('L', 'P')
  AND d.FechaIngreso >= ?
  AND ISNULL(d.Anulado, '') <> 'X'
GROUP BY c.Id, c.Lote, c.Granja, c.Nucleo, c.Etapa, d.Sexo, d.Raza, d.CodEstandar
"""

# Registros diarios por cabecera, día y sexo (suma de galpones y divisiones) hasta la fecha de corte.
DIAS_REALES = """
SELECT r.idEncaseta                 AS id_encaseta,
       r.fecha,
       rtrim(r.sexo)                AS sexo,
       MIN(r.edadDias)              AS edad,
       MIN(r.edadSemanas)           AS semana,
       MIN(rtrim(r.lineaGenetica))  AS linea,
       MIN(rtrim(r.etapa))          AS etapa,
       SUM(r.avesEncasetadas)       AS aves_encasetadas,
       SUM(r.seleccion)             AS seleccion,
       SUM(r.mortalidad)            AS mortalidad,
       SUM(r.mortalidadTransporte)  AS mortalidad_transporte,
       SUM(r.avesVendidas)          AS aves_vendidas,
       SUM(r.avesSacrificio)        AS aves_sacrificio,
       SUM(r.avesAgregadas)         AS aves_agregadas,
       SUM(r.avesTransferidas)      AS aves_transferidas,
       SUM(r.consumo)               AS consumo            -- kg
FROM dbo.DiaReproductora r
WHERE r.idEncaseta IN (SELECT CAST(value AS int) FROM STRING_SPLIT(?, ','))
  AND r.fecha <= ?
GROUP BY r.idEncaseta, r.fecha, rtrim(r.sexo)
"""
