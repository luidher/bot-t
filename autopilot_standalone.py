"""
autopilot_standalone.py — Interfaz standalone para el Autopilot DB.

Modo de uso:
    python autopilot_standalone.py

Flujo:
    1. El usuario ingresa la URL del cuestionario.
    2. Clic en "Abrir Navegador" → lanza Chromium visible.
    3. El usuario hace login manualmente en el navegador.
    4. Clic en "Iniciar Autopilot" → el bot responde automáticamente.
    5. El log muestra actividad en tiempo real.

No requiere PyQt5 ni el widget principal.
"""
from __future__ import annotations

import queue
import sys
import threading
import tkinter as tk
from tkinter import font as tkfont
from tkinter import scrolledtext, ttk
from pathlib import Path

# ── Asegurar que 'core' sea importable desde cualquier CWD ────────────────
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.browser import BotBrowser
from core.autopilot_runner import AutopilotRunner


# ---------------------------------------------------------------------------
# Paleta de colores
# ---------------------------------------------------------------------------
COLORS = {
    "bg":           "#0f1117",
    "surface":      "#1a1d27",
    "surface2":     "#23263a",
    "accent":       "#6c63ff",
    "accent_dark":  "#4e46cc",
    "accent_stop":  "#e05260",
    "accent_stop2": "#b03040",
    "text":         "#e8eaf6",
    "text_muted":   "#8b8fa8",
    "success":      "#4ade80",
    "warning":      "#facc15",
    "error":        "#f87171",
    "info":         "#93c5fd",
    "border":       "#2d3055",
}

LOG_LEVEL_COLORS = {
    "SUCCESS": COLORS["success"],
    "WARNING": COLORS["warning"],
    "ERROR":   COLORS["error"],
    "INFO":    COLORS["info"],
    "DEBUG":   COLORS["text_muted"],
}


# ---------------------------------------------------------------------------
# Aplicación principal
# ---------------------------------------------------------------------------

class AutopilotApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Autopilot DB — Standalone")
        self.root.configure(bg=COLORS["bg"])
        # Allow a smaller minimum size for a more compact UI
        self.root.minsize(640, 480)
        self.root.resizable(True, True)

        # Estado interno
        self._browser: BotBrowser | None = None
        self._runner: AutopilotRunner | None = None
        self._runner_thread: threading.Thread | None = None
        self._browser_cmd_queue: queue.Queue | None = None
        self._closing = False
        self._log_queue: queue.Queue = queue.Queue()
        self._stats: dict = {}
        self._var_browser_type = tk.StringVar(value="chromium")

        # Fuentes
        # Slightly smaller fonts for a compact layout
        self._font_title  = tkfont.Font(family="Segoe UI", size=13, weight="bold")
        self._font_label  = tkfont.Font(family="Segoe UI", size=9)
        self._font_small  = tkfont.Font(family="Segoe UI", size=8)
        self._font_log    = tkfont.Font(family="Consolas", size=8)
        self._font_btn    = tkfont.Font(family="Segoe UI", size=9, weight="bold")
        self._font_stats  = tkfont.Font(family="Segoe UI", size=8)

        self._build_ui()
        self._poll_log_queue()

    # ------------------------------------------------------------------
    # Construcción de la UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        # ── Header ───────────────────────────────────────────────────────
        # Reduced header padding for compactness
        header = tk.Frame(self.root, bg=COLORS["surface"], pady=10, padx=12)
        header.pack(fill="x", side="top")

        tk.Label(
            header, text="🤖  Autopilot DB",
            font=self._font_title,
            bg=COLORS["surface"], fg=COLORS["text"],
        ).pack(side="left")

        self._lbl_status = tk.Label(
            header, text="● Inactivo",
            font=self._font_small,
            bg=COLORS["surface"], fg=COLORS["text_muted"],
        )
        self._lbl_status.pack(side="right", padx=10)

        # ── Separador ────────────────────────────────────────────────────
        tk.Frame(self.root, bg=COLORS["border"], height=1).pack(fill="x")

        # ── Panel de configuración ────────────────────────────────────────
        cfg_frame = tk.Frame(self.root, bg=COLORS["surface2"], padx=20, pady=14)
        cfg_frame.pack(fill="x", padx=0, pady=0)

        # URL
        tk.Label(
            cfg_frame, text="URL del cuestionario:",
            font=self._font_label, bg=COLORS["surface2"], fg=COLORS["text_muted"],
        ).grid(row=0, column=0, sticky="w", padx=(0, 10))

        self._var_url = tk.StringVar(value="https://")
        self._entry_url = tk.Entry(
            cfg_frame, textvariable=self._var_url,
            font=self._font_label,
            bg=COLORS["surface"], fg=COLORS["text"],
            insertbackground=COLORS["text"],
            relief="flat", bd=6,
            width=45,
        )
        self._entry_url.grid(row=0, column=1, sticky="ew", padx=(0, 12))
        cfg_frame.columnconfigure(1, weight=1)

        # Botón Abrir Navegador
        self._btn_open = tk.Button(
            cfg_frame, text="🌐  Abrir Navegador",
            font=self._font_btn,
            bg=COLORS["accent"], fg="white",
            activebackground=COLORS["accent_dark"], activeforeground="white",
            relief="flat", bd=0, padx=12, pady=5,
            cursor="hand2",
            command=self._on_open_browser,
        )
        self._btn_open.grid(row=0, column=2, padx=(0, 8))

        # Botón Elegir Navegador
        self._btn_select = tk.Button(
            cfg_frame, text="⚙️  Elegir navegador",
            font=self._font_btn,
            bg=COLORS["surface"], fg=COLORS["text"],
            activebackground=COLORS["surface2"], activeforeground=COLORS["text"],
            relief="flat", bd=0, padx=12, pady=5,
            cursor="hand2",
            command=self._show_browser_menu,
        )
        self._btn_select.grid(row=0, column=3, padx=(0, 8))

        # ── Fila de botones de control ────────────────────────────────────
        btn_frame = tk.Frame(self.root, bg=COLORS["bg"], padx=20, pady=12)
        btn_frame.pack(fill="x")

        self._btn_start = tk.Button(
            btn_frame, text="▶  Iniciar Autopilot",
            font=self._font_btn,
            bg=COLORS["accent"], fg="white",
            activebackground=COLORS["accent_dark"], activeforeground="white",
            relief="flat", bd=0, padx=18, pady=8,
            cursor="hand2",
            state="disabled",
            command=self._on_start,
        )
        self._btn_start.pack(side="left", padx=(0, 10))

        self._btn_stop = tk.Button(
            btn_frame, text="⏹  Detener",
            font=self._font_btn,
            bg=COLORS["accent_stop"], fg="white",
            activebackground=COLORS["accent_stop2"], activeforeground="white",
            relief="flat", bd=0, padx=14, pady=8,
            cursor="hand2",
            state="disabled",
            command=self._on_stop,
        )
        self._btn_stop.pack(side="left", padx=(0, 10))

        self._btn_clear = tk.Button(
            btn_frame, text="🗑  Limpiar log",
            font=self._font_small,
            bg=COLORS["surface2"], fg=COLORS["text_muted"],
            activebackground=COLORS["surface"], activeforeground=COLORS["text"],
            relief="flat", bd=0, padx=10, pady=8,
            cursor="hand2",
            command=self._clear_log,
        )
        self._btn_clear.pack(side="right")

        # ── Panel de estadísticas ─────────────────────────────────────────
        stats_outer = tk.Frame(self.root, bg=COLORS["bg"], padx=20)
        stats_outer.pack(fill="x")

        stats_frame = tk.Frame(stats_outer, bg=COLORS["surface"], padx=16, pady=8)
        stats_frame.pack(fill="x")

        self._stat_vars = {
            "total_registros_db":    tk.StringVar(value="0"),
            "respondidas_desde_db":  tk.StringVar(value="0"),
            "respondidas_al_azar":   tk.StringVar(value="0"),
            "nuevas_guardadas":      tk.StringVar(value="0"),
            "hojas_completadas":     tk.StringVar(value="0"),
        }
        labels = {
            "total_registros_db":    "📦 Total en BD",
            "respondidas_desde_db":  "✅ Desde BD",
            "respondidas_al_azar":   "🎲 Al azar",
            "nuevas_guardadas":      "💾 Guardadas",
            "hojas_completadas":     "📄 Hojas",
        }

        for col, (key, label) in enumerate(labels.items()):
            cell = tk.Frame(stats_frame, bg=COLORS["surface"])
            cell.grid(row=0, column=col, padx=12, pady=4, sticky="ew")
            stats_frame.columnconfigure(col, weight=1)

            tk.Label(
                cell, text=label,
                font=self._font_stats,
                bg=COLORS["surface"], fg=COLORS["text_muted"],
            ).pack()
            tk.Label(
                cell, textvariable=self._stat_vars[key],
                font=tkfont.Font(family="Segoe UI", size=14, weight="bold"),
                bg=COLORS["surface"], fg=COLORS["accent"],
            ).pack()

        # ── Área de log ───────────────────────────────────────────────────
        tk.Frame(self.root, bg=COLORS["border"], height=1).pack(fill="x", pady=(8, 0))

        log_frame = tk.Frame(self.root, bg=COLORS["bg"])
        log_frame.pack(fill="both", expand=True, padx=20, pady=(8, 16))

        tk.Label(
            log_frame, text="Actividad",
            font=self._font_small,
            bg=COLORS["bg"], fg=COLORS["text_muted"],
        ).pack(anchor="w", pady=(0, 4))

        self._log_area = scrolledtext.ScrolledText(
            log_frame,
            font=self._font_log,
            bg=COLORS["surface"], fg=COLORS["text"],
            insertbackground=COLORS["text"],
            relief="flat", bd=0,
            state="disabled",
            wrap="word",
        )
        self._log_area.pack(fill="both", expand=True)

        # Configurar tags de color por nivel
        for level, color in LOG_LEVEL_COLORS.items():
            self._log_area.tag_config(level, foreground=color)
        self._log_area.tag_config("TIMESTAMP", foreground=COLORS["text_muted"])

    # ------------------------------------------------------------------
    # Handlers de botones
    # ------------------------------------------------------------------

    def _show_browser_menu(self) -> None:
        menu = tk.Menu(self.root, tearoff=0, bg=COLORS["surface"], fg=COLORS["text"], activebackground=COLORS["accent"], activeforeground="white")
        
        menu.add_radiobutton(
            label="Chromium (Predeterminado)",
            variable=self._var_browser_type,
            value="chromium",
            command=self._on_browser_type_changed
        )
        menu.add_radiobutton(
            label="Google Chrome",
            variable=self._var_browser_type,
            value="chrome",
            command=self._on_browser_type_changed
        )
        menu.add_radiobutton(
            label="Firefox",
            variable=self._var_browser_type,
            value="firefox",
            command=self._on_browser_type_changed
        )
        menu.add_radiobutton(
            label="Microsoft Edge",
            variable=self._var_browser_type,
            value="msedge",
            command=self._on_browser_type_changed
        )
        
        x = self._btn_select.winfo_rootx()
        y = self._btn_select.winfo_rooty() + self._btn_select.winfo_height()
        menu.post(x, y)

    def _on_browser_type_changed(self) -> None:
        browser_names = {
            "chromium": "Chromium",
            "chrome": "Chrome",
            "firefox": "Firefox",
            "msedge": "Edge"
        }
        selected = self._var_browser_type.get()
        name = browser_names.get(selected, "Chromium")
        self._btn_select.config(text=f"Elegir navegador ({name})")
        self._append_log(f"Navegador seleccionado: {name}", "INFO")

    def _on_open_browser(self) -> None:
        url = self._var_url.get().strip()
        if not url or url == "https://":
            self._append_log("Por favor ingresa una URL válida.", "WARNING")
            return
        if self._runner_thread and self._runner_thread.is_alive():
            self._append_log("Ya hay un navegador abierto para esta sesión.", "WARNING")
            return

        self._btn_open.config(state="disabled", text="Abriendo...")
        self._btn_select.config(state="disabled")
        self._set_status("Abriendo navegador...", COLORS["warning"])
        self._browser_cmd_queue = queue.Queue()
        self._closing = False

        self._runner_thread = threading.Thread(
            target=self._browser_worker,
            args=(url, self._browser_cmd_queue),
            daemon=True,
        )
        self._runner_thread.start()

    def _browser_worker(self, url: str, cmd_queue: queue.Queue) -> None:
        """
        Mantiene Playwright, el navegador y el Autopilot en el mismo thread.

        Playwright sync no permite crear el browser en un thread y reutilizar
        page/context desde otro; hacerlo produce errores tipo:
        "cannot switch to a different thread".
        """
        browser: BotBrowser | None = None
        try:
            browser = BotBrowser(headless=False, browser_type=self._var_browser_type.get())
            browser.open(url, timeout_ms=120000)
            self._browser = browser
            self._log_queue.put(("INFO", "Navegador abierto. Haz login y luego presiona 'Iniciar Autopilot'."))
            self._ui_after(self._on_browser_ready)

            while True:
                cmd = cmd_queue.get()
                if cmd == "run":
                    self._run_autopilot_in_browser_thread(browser)
                elif cmd == "close":
                    break

        except Exception as exc:
            err_msg = str(exc)
            if "executable" in err_msg.lower() or "playwright install" in err_msg.lower():
                err_msg += "\nTip: Asegúrate de tener instalado el navegador seleccionado o ejecuta 'playwright install <nombre_navegador>'."
            self._log_queue.put(("ERROR", f"Error al abrir el navegador: {err_msg}"))
            self._ui_after(lambda: (
                self._btn_open.config(state="normal", text="🌐  Abrir Navegador"),
                self._btn_select.config(state="normal"),
                self._set_status("Error al abrir", COLORS["error"]),
            ))
        finally:
            if browser:
                try:
                    browser.close()
                except Exception:
                    pass
            self._browser = None
            self._runner = None
            self._browser_cmd_queue = None

    def _run_autopilot_in_browser_thread(self, browser: BotBrowser) -> None:
        import time as _time
        if not self._runner:
            self._runner = AutopilotRunner(
                url="",  # El browser ya está abierto y posicionado
                log_callback=lambda msg, lvl: self._log_queue.put((lvl, msg)),
                stats_callback=lambda stats: self._ui_after(lambda: self._update_stats(stats)),
                keep_browser_open=True,
                browser=browser,
            )
        _backoff = 2  # segundos iniciales de espera ante error
        while True:
            try:
                self._runner.run()
            except Exception as exc:
                self._log_queue.put(("ERROR", f"Error crítico en Autopilot: {exc}"))
            # Si el usuario detuvo el bot (stop() fue llamado), salir definitivamente
            if self._closing or not (self._runner and self._runner._running):
                break
            # Auto-reanudación: el bot se detuvo por error, reintentar automáticamente
            self._log_queue.put(("WARNING", f"Autopilot detenido inesperadamente. Reanudando en {_backoff}s..."))
            _time.sleep(_backoff)
            _backoff = min(_backoff * 2, 60)
            # Restablecer _running para el próximo intento
            if self._runner:
                self._runner._running = True
        self._runner = None
        self._ui_after(self._on_runner_finished)

    def _on_browser_ready(self) -> None:
        self._btn_open.config(state="disabled", text="Navegador abierto")
        self._btn_select.config(state="disabled")
        self._btn_start.config(state="normal")
        self._set_status("Navegador listo — haz login y presiona Iniciar", COLORS["success"])

    def _on_start(self) -> None:
        if self._runner:
            self._append_log("El Autopilot ya está en ejecución.", "WARNING")
            return
        if not self._browser or not self._browser_cmd_queue:
            self._append_log("Primero abre el navegador y navega al cuestionario.", "WARNING")
            return

        self._btn_start.config(state="disabled")
        self._btn_stop.config(state="normal")
        self._btn_open.config(state="disabled")
        self._btn_select.config(state="disabled")
        self._set_status("● Ejecutando...", COLORS["accent"])

        self._browser_cmd_queue.put("run")

    def _on_stop(self) -> None:
        if self._runner:
            self._runner.stop()
            self._append_log("Deteniendo Autopilot...", "WARNING")
        self._btn_stop.config(state="disabled")

    def _on_runner_finished(self) -> None:
        self._btn_start.config(state="normal")
        self._btn_stop.config(state="disabled")
        if self._browser and self._browser_cmd_queue:
            self._btn_open.config(state="disabled", text="Navegador abierto")
            self._btn_select.config(state="disabled")
        else:
            self._btn_open.config(state="normal", text="🌐  Abrir Navegador")
            self._btn_select.config(state="normal")
        self._set_status("● Inactivo", COLORS["text_muted"])

    # ------------------------------------------------------------------
    # Helpers de UI
    # ------------------------------------------------------------------

    def _set_status(self, text: str, color: str = COLORS["text_muted"]) -> None:
        self._lbl_status.config(text=text, fg=color)

    def _append_log(self, msg: str, level: str = "INFO") -> None:
        import datetime
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self._log_area.config(state="normal")
        self._log_area.insert("end", f"[{ts}] ", "TIMESTAMP")
        self._log_area.insert("end", f"{msg}\n", level)
        self._log_area.see("end")
        self._log_area.config(state="disabled")

    def _clear_log(self) -> None:
        self._log_area.config(state="normal")
        self._log_area.delete("1.0", "end")
        self._log_area.config(state="disabled")

    def _update_stats(self, stats: dict) -> None:
        for key, var in self._stat_vars.items():
            if key in stats:
                var.set(str(stats[key]))

    def _poll_log_queue(self) -> None:
        """Lee mensajes del queue de log y los muestra en la UI."""
        try:
            while True:
                level, msg = self._log_queue.get_nowait()
                self._append_log(msg, level)
        except queue.Empty:
            pass
        self.root.after(80, self._poll_log_queue)

    def _ui_after(self, callback) -> None:
        if self._closing:
            return
        try:
            self.root.after(0, callback)
        except tk.TclError:
            pass

    # ------------------------------------------------------------------
    # Cierre limpio
    # ------------------------------------------------------------------

    def _on_close(self) -> None:
        self._closing = True
        if self._runner:
            self._runner.stop()
        if self._browser_cmd_queue:
            try:
                self._browser_cmd_queue.put("close")
            except Exception:
                pass
        self.root.destroy()


# ---------------------------------------------------------------------------
# Punto de entrada
# ---------------------------------------------------------------------------

def main() -> None:
    # Enable High-DPI awareness on Windows before creating the Tk root
    if sys.platform.startswith("win"):
        try:
            import ctypes
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(1)
            except Exception:
                try:
                    ctypes.windll.user32.SetProcessDPIAware()
                except Exception:
                    pass
        except Exception:
            pass

    root = tk.Tk()
    app = AutopilotApp(root)
    root.protocol("WM_DELETE_WINDOW", app._on_close)

    # Centrar ventana en pantalla
    root.update_idletasks()
    # Use a smaller default geometry for a compact window
    w, h = 760, 540
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    root.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")

    root.mainloop()


if __name__ == "__main__":
    main()
