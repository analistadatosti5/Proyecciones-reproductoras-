"""Interfaz gráfica (Tkinter): selección del insumo, parámetros y ejecución.

El trabajo pesado (consultas y cálculo) corre en un hilo aparte para que la
ventana no se congele; el hilo se comunica con la interfaz mediante una cola.
"""

import logging
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from . import __version__, config, servicio
from .modelos import ErrorProyeccion, Mensaje, Nivel, ParametrosProyeccion

log = logging.getLogger(__name__)

TITULO = "Proyección de consumo de alimento - Reproductoras"
_ORDEN_NIVEL = {Nivel.ERROR: 0, Nivel.ADVERTENCIA: 1, Nivel.INFO: 2}


class Aplicacion(ttk.Frame):
    """Ventana principal."""

    def __init__(self, raiz: tk.Tk):
        super().__init__(raiz, padding=12)
        self.raiz = raiz
        self._cola: queue.Queue = queue.Queue()
        self._ruta_insumo = tk.StringVar()
        self._semana_final = tk.StringVar(value=str(config.SEMANA_FINAL_DEFECTO))
        self._texto_dias = tk.StringVar()
        self._botones: list[ttk.Button] = []
        self._construir()
        self._semana_final.trace_add("write", lambda *_: self._actualizar_dias())
        self._actualizar_dias()
        self.after(100, self._atender_cola)

    # ------------------------------------------------------------------ diseño
    def _construir(self) -> None:
        self.grid(row=0, column=0, sticky="nsew")
        self.raiz.columnconfigure(0, weight=1)
        self.raiz.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(4, weight=1)
        gris = "#555555"

        ttk.Label(self, text=TITULO, font=("Segoe UI", 13, "bold")).grid(row=0, column=0, sticky="w", pady=(0, 10))

        archivo = ttk.LabelFrame(self, text="1. Archivo de insumo", padding=8)
        archivo.grid(row=1, column=0, sticky="ew")
        archivo.columnconfigure(0, weight=1)
        ttk.Entry(archivo, textvariable=self._ruta_insumo, state="readonly").grid(
            row=0, column=0, sticky="ew", padx=(0, 6)
        )
        self._boton(archivo, "Examinar...", self._seleccionar_insumo).grid(row=0, column=1)
        ttk.Label(
            archivo, text="Columnas requeridas: " + ", ".join(config.COLUMNAS_INSUMO), foreground=gris
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))

        parametros = ttk.LabelFrame(self, text="2. Parámetros", padding=8)
        parametros.grid(row=2, column=0, sticky="ew", pady=8)
        parametros.columnconfigure(3, weight=1)  # el espacio sobrante va a la derecha
        ttk.Label(parametros, text="Semana final de proyección:").grid(row=0, column=0, sticky="w")
        ttk.Spinbox(
            parametros, from_=1, to=config.SEMANA_FINAL_MAXIMA, textvariable=self._semana_final, width=6
        ).grid(row=0, column=1, padx=6)
        ttk.Label(parametros, textvariable=self._texto_dias).grid(row=0, column=2, sticky="w")
        ttk.Label(
            parametros,
            text=(
                f"Machos: {config.PORCENTAJE_MACHOS:.0%} de las hembras pedido.  "
                f"Aves adicionales: {config.PORCENTAJE_ADICIONAL:.0%}."
            ),
            foreground=gris,
        ).grid(row=1, column=0, columnspan=4, sticky="w", pady=(6, 0))

        acciones = ttk.Frame(self)
        acciones.grid(row=3, column=0, sticky="ew")
        self._boton(acciones, "Validar insumo", self._validar).pack(side="left")
        self._boton(acciones, "Generar proyección", self._generar).pack(side="left", padx=6)
        self._progreso = ttk.Progressbar(acciones, mode="determinate", length=220)
        self._progreso.pack(side="right")

        self._registro = ScrolledText(self, height=18, wrap="word", state="disabled", font=("Consolas", 9))
        self._registro.grid(row=4, column=0, sticky="nsew", pady=(8, 0))
        for etiqueta, color in (("ERROR", "#C00000"), ("ADVERTENCIA", "#B45F06"), ("OK", "#2E7D32")):
            self._registro.tag_configure(etiqueta, foreground=color)

    def _boton(self, padre: tk.Misc, texto: str, accion) -> ttk.Button:
        boton = ttk.Button(padre, text=texto, command=accion)
        self._botones.append(boton)
        return boton

    # ------------------------------------------------------------------ acciones
    def _seleccionar_insumo(self) -> None:
        ruta = filedialog.askopenfilename(
            title="Seleccionar archivo de insumo",
            filetypes=[("Libros de Excel", "*.xlsx *.xlsm"), ("Todos los archivos", "*.*")],
        )
        if ruta:
            self._ruta_insumo.set(ruta)

    def _validar(self) -> None:
        parametros = self._parametros()
        if parametros:
            self._iniciar(servicio.validar_insumo, Path(self._ruta_insumo.get()), parametros)

    def _generar(self) -> None:
        parametros = self._parametros()
        if not parametros:
            return
        insumo = Path(self._ruta_insumo.get())
        ruta_salida = filedialog.asksaveasfilename(
            title="Guardar proyección como (se agrega el nombre de la sociedad a cada archivo)",
            defaultextension=".xlsx",
            filetypes=[("Libro de Excel", "*.xlsx")],
            initialdir=str(insumo.parent),
            initialfile=(
                f"Proyeccion_Consumo_Reproductoras_S{parametros.semana_final}_{datetime.now():%Y%m%d_%H%M}.xlsx"
            ),
            confirmoverwrite=False,  # el archivo elegido no se crea: se revisan los de cada sociedad
        )
        if not ruta_salida:
            return
        rutas = [servicio.ruta_por_sociedad(Path(ruta_salida), sociedad) for sociedad in config.SOCIEDADES]
        existentes = [ruta.name for ruta in rutas if ruta.exists()]
        if existentes and not messagebox.askyesno(
            TITULO, "Ya existen estos archivos:\n" + "\n".join(existentes) + "\n\n¿Desea reemplazarlos?"
        ):
            return
        self._iniciar(servicio.generar_proyeccion, insumo, Path(ruta_salida), parametros)

    def _parametros(self) -> ParametrosProyeccion | None:
        """Parámetros de la interfaz, o None (con aviso) si no son válidos."""
        if not self._ruta_insumo.get():
            messagebox.showwarning(TITULO, "Seleccione primero el archivo de insumo.")
            return None
        semana = self._leer_semana()
        if semana is None:
            messagebox.showwarning(
                TITULO, f"La semana final debe ser un número entero entre 1 y {config.SEMANA_FINAL_MAXIMA}."
            )
            return None
        return ParametrosProyeccion(semana_final=semana)

    def _leer_semana(self) -> int | None:
        texto = self._semana_final.get().strip()
        if not texto.isdigit() or not 1 <= int(texto) <= config.SEMANA_FINAL_MAXIMA:
            return None
        return int(texto)

    def _actualizar_dias(self) -> None:
        semana = self._leer_semana()
        dias = semana * config.DIAS_POR_SEMANA if semana else None
        self._texto_dias.set(f"= {dias} días por lote y sexo (día 1 al {dias})" if dias else "valor no válido")

    # ------------------------------------------------------------------ ejecución en segundo plano
    def _iniciar(self, tarea, *argumentos) -> None:
        self._escribir("-" * 90)
        for boton in self._botones:
            boton.state(["disabled"])
        self._progreso.configure(mode="indeterminate")
        self._progreso.start(12)
        threading.Thread(target=self._trabajar, args=(tarea, argumentos), daemon=True).start()

    def _trabajar(self, tarea, argumentos) -> None:
        """Se ejecuta en el hilo secundario: nunca toca widgets, solo escribe en la cola."""
        try:
            resultado = tarea(*argumentos, informar=lambda texto: self._cola.put(("avance", texto)))
            self._cola.put(("fin", resultado))
        except ErrorProyeccion as exc:
            log.warning("Proceso detenido: %s", exc)
            self._cola.put(("error", str(exc)))
        except Exception:
            log.exception("Error inesperado")
            self._cola.put(("error", f"Ocurrió un error inesperado. El detalle quedó en {config.ARCHIVO_LOG}"))

    def _atender_cola(self) -> None:
        try:
            while True:
                tipo, dato = self._cola.get_nowait()
                if tipo == "avance":
                    self._escribir(dato)
                elif tipo == "fin":
                    self._terminar()
                    self._mostrar_resultado(dato)
                elif tipo == "error":
                    self._terminar()
                    self._escribir(dato, "ERROR")
                    messagebox.showerror(TITULO, dato)
        except queue.Empty:
            pass
        self.after(100, self._atender_cola)

    def _terminar(self) -> None:
        self._progreso.stop()
        self._progreso.configure(mode="determinate", value=0)  # barra vacía mientras no hay proceso
        for boton in self._botones:
            boton.state(["!disabled"])

    # ------------------------------------------------------------------ resultados
    def _mostrar_resultado(self, resultado: servicio.ResultadoProceso) -> None:
        mensajes = sorted(resultado.mensajes, key=lambda m: _ORDEN_NIVEL[m.nivel])
        limite = config.MENSAJES_MAXIMOS_EN_PANTALLA
        for mensaje in mensajes[:limite]:
            self._escribir(_formatear(mensaje), mensaje.nivel.value)
        if len(mensajes) > limite:
            self._escribir(f"... y {len(mensajes) - limite} mensajes más (ver hoja {config.HOJA_VALIDACIONES}).")

        if not resultado.exitoso:
            texto = f"Se encontraron {len(resultado.errores)} errores. Corrija el insumo e intente de nuevo."
            self._escribir(texto, "ERROR")
            messagebox.showerror(TITULO, texto)
        elif resultado.archivos:
            self._escribir(
                f"Proyección generada: {resultado.lotes} lotes ({_texto_sociedades(resultado)}), "
                f"{resultado.filas:,} registros, {resultado.consumo_total_kg:,.0f} kg de alimento en total.",
                "OK",
            )
            rutas = list(resultado.archivos.values())
            pregunta = "¿Desea abrir el archivo?" if len(rutas) == 1 else "¿Desea abrir los archivos?"
            if messagebox.askyesno(
                TITULO, "Proyección generada:\n" + "\n".join(str(r) for r in rutas) + f"\n\n{pregunta}"
            ):
                for ruta in rutas:
                    _abrir_archivo(ruta)
        else:
            self._escribir(
                f"Validación exitosa: {resultado.lotes} lotes listos para proyectar ({_texto_sociedades(resultado)}; "
                f"{len(resultado.advertencias)} advertencias).",
                "OK",
            )

    def _escribir(self, texto: str, etiqueta: str | None = None) -> None:
        self._registro.configure(state="normal")
        self._registro.insert("end", texto + "\n", etiqueta or ())
        self._registro.see("end")
        self._registro.configure(state="disabled")


def _texto_sociedades(resultado: servicio.ResultadoProceso) -> str:
    """'ORIENTE 196, OCCIDENTE 4'"""
    return ", ".join(f"{sociedad} {lotes}" for sociedad, lotes in resultado.lotes_por_sociedad.items())


def _formatear(mensaje: Mensaje) -> str:
    ubicacion = []
    if mensaje.fila:
        ubicacion.append(f"fila {mensaje.fila}")
    if mensaje.lote:
        ubicacion.append(f"{'lotes' if ',' in mensaje.lote else 'lote'} {mensaje.lote}")
    prefijo = f"[{mensaje.nivel.value}] " + (f"({'; '.join(ubicacion)}) " if ubicacion else "")
    return prefijo + mensaje.detalle


def _abrir_archivo(ruta: Path) -> None:
    try:
        if sys.platform == "win32":
            os.startfile(ruta)  # abre el archivo con la aplicación predeterminada (Excel)
        else:
            subprocess.run(["open" if sys.platform == "darwin" else "xdg-open", str(ruta)], check=False)
    except OSError as exc:
        messagebox.showwarning(TITULO, f"No se pudo abrir el archivo: {exc}")


def iniciar() -> None:
    """Crea la ventana principal y arranca el ciclo de eventos."""
    if sys.platform == "win32":
        try:  # texto nítido en pantallas con escalado
            import ctypes

            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    raiz = tk.Tk()
    raiz.title(f"{TITULO}  v{__version__}")
    raiz.minsize(780, 540)
    Aplicacion(raiz)
    raiz.mainloop()
