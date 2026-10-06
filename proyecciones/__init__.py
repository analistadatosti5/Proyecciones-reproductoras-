"""Proyección de consumo de alimento para lotes de reproductoras.

Paquete organizado por responsabilidad:
    config        parámetros de negocio y valores por defecto
    modelos       estructuras de datos compartidas y excepciones
    db            conexiones a PostgreSQL (credenciales desde .env)
    consultas     texto de las consultas SQL
    repositorio   ejecución de consultas -> DataFrames
    insumo        lectura y validación del Excel de entrada
    validaciones  validaciones del insumo contra las bases de datos
    proyeccion    lógica de negocio (construcción de la base diaria)
    exportador    generación del Excel de salida
    servicio      orquestación del proceso completo
    gui           interfaz gráfica (Tkinter)
"""

__version__ = "1.0.0"
