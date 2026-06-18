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
        self.root.minsize(780, 600)
        self.root.resizable(True, True)

        # Estado interno
        self._browser: BotBrowser | None = None
        self._runner: AutopilotRunner | None = None
        self._runner_thread: threading.Thread | None = None
        self._log_queue: queue.Queue = queue.Queue()
        self._stats: dict = {}

        # Fuentes
        self._font_title  = tkfont.Font(family="Segoe UI", size=15, weight="bold")
        self._font_label  = tkfont.Font(family="Segoe UI", size=10)
        self._font_small  = tkfont.Font(family="Segoe UI", size=9)
        self._font_log    = tkfont.Font(family="Consolas", size=9)
        self._font_btn    = tkfont.Font(family="Segoe UI", size=10, weight="bold")
        self._font_stats  = tkfont.Font(family="Segoe UI", size=9)

        self._build_ui()
        self._poll_log_queue()

    # ------------------------------------------------------------------
    # Construcción de la UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        # ── Header ───────────────────────────────────────────────────────
        header = tk.Frame(self.root, bg=COLORS["surface"], pady=14, padx=20)
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
            width=55,
        )
        self._entry_url.grid(row=0, column=1, sticky="ew", padx=(0, 12))
        cfg_frame.columnconfigure(1, weight=1)

        # Botón Abrir Navegador
        self._btn_open = tk.Button(
            cfg_frame, text="🌐  Abrir Navegador",
            font=self._font_btn,
            bg=COLORS["accent"], fg="white",
            activebackground=COLORS["accent_dark"], activeforeground="white",
            relief="flat", bd=0, padx=14, pady=6,
            cursor="hand2",
            command=self._on_open_browser,
        )
        self._btn_open.grid(row=0, column=2, padx=(0, 8))

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
            cell.grid(row=0, column=col, padx=18, pady=4, sticky="ew")
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

    def _on_open_browser(self) -> None:
        url = self._var_url.get().strip()
        if not url or url == "https://":
            self._append_log("Por favor ingresa una URL válida.", "WARNING")
            return

        self._btn_open.config(state="disabled", text="Abriendo...")
        self._set_status("Abriendo navegador...", COLORS["warning"])

        def _open():
            try:
                self._browser = BotBrowser(headless=False)
                self._browser.open(url, timeout_ms=120000)
                self._log_queue.put(("INFO", "Navegador abierto. Haz login y luego presiona 'Iniciar Autopilot'."))
                self.root.after(0, self._on_browser_ready)
            except Exception as exc:
                self._log_queue.put(("ERROR", f"Error al abrir el navegador: {exc}"))
                self.root.after(0, lambda: (
                    self._btn_open.config(state="normal", text="🌐  Abrir Navegador"),
                    self._set_status("Error al abrir", COLORS["error"]),
                ))

        threading.Thread(target=_open, daemon=True).start()

    def _on_browser_ready(self) -> None:
        self._btn_open.config(state="normal", text="🌐  Abrir Navegador")
        self._btn_start.config(state="normal")
        self._set_status("Navegador listo — haz login y presiona Iniciar", COLORS["success"])

    def _on_start(self) -> None:
        if self._runner_thread and self._runner_thread.is_alive():
            self._append_log("El Autopilot ya está en ejecución.", "WARNING")
            return

        self._btn_start.config(state="disabled")
        self._btn_stop.config(state="normal")
        self._btn_open.config(state="disabled")
        self._set_status("● Ejecutando...", COLORS["accent"])

        def _run():
            try:
                self._runner = AutopilotRunner(
                    url="",  # El browser ya está abierto y posicionado
                    log_callback=lambda msg, lvl: self._log_queue.put((lvl, msg)),
                    stats_callback=lambda stats: self.root.after(0, lambda: self._update_stats(stats)),
                    keep_browser_open=True,
                    browser=self._browser,  # Reutilizar el browser ya abierto
                )
                self._runner.run()
            except Exception as exc:
                self._log_queue.put(("ERROR", f"Error crítico en Autopilot: {exc}"))
            finally:
                self.root.after(0, self._on_runner_finished)

        self._runner_thread = threading.Thread(target=_run, daemon=True)
        self._runner_thread.start()

    def _on_stop(self) -> None:
        if self._runner:
            self._runner.stop()
            self._append_log("Deteniendo Autopilot...", "WARNING")
        self._btn_stop.config(state="disabled")

    def _on_runner_finished(self) -> None:
        self._btn_start.config(state="normal")
        self._btn_stop.config(state="disabled")
        self._btn_open.config(state="normal")
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

    # ------------------------------------------------------------------
    # Cierre limpio
    # ------------------------------------------------------------------

    def _on_close(self) -> None:
        if self._runner:
            self._runner.stop()
        if self._browser:
            try:
                self._browser.close()
            except Exception:
                pass
        self.root.destroy()


# ---------------------------------------------------------------------------
# Punto de entrada
# ---------------------------------------------------------------------------

def main() -> None:
    root = tk.Tk()
    app = AutopilotApp(root)
    root.protocol("WM_DELETE_WINDOW", app._on_close)

    # Centrar ventana en pantalla
    root.update_idletasks()
    w, h = 900, 680
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    root.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")

    root.mainloop()


if __name__ == "__main__":
    main()
