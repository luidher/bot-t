"""PyQt5 Floating Widget for Vision Bot v2."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any, Optional

from PyQt5.QtCore import Qt, QPoint, pyqtSignal, pyqtSlot
from PyQt5.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QComboBox,
    QTextEdit,
    QFrame,
    QGraphicsDropShadowEffect
)
from PyQt5.QtGui import QColor, QCursor, QPainter, QPen, QBrush, QFont

from core.config import BotConfig, BotConfigUpdate
from core.runner import BotRunner, BotRunnerThread
from core.autopilot_runner import AutopilotRunnerThread


class RegionSelector(QWidget):
    """Fullscreen overlay for drawing and selecting screen region with crosshair cursor."""
    region_selected = pyqtSignal(int, int, int, int)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setCursor(Qt.CrossCursor)

        # Full screen geometry
        desktop = QApplication.desktop()
        self.setGeometry(desktop.geometry())

        self.start_point = QPoint()
        self.end_point = QPoint()
        self.is_drawing = False

    def paintEvent(self, event: Any) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # Dark overlay
        overlay_color = QColor(0, 0, 0, 140)
        painter.fillRect(self.rect(), overlay_color)

        if self.is_drawing:
            # Selected region
            x1 = min(self.start_point.x(), self.end_point.x())
            y1 = min(self.start_point.y(), self.end_point.y())
            w = abs(self.start_point.x() - self.end_point.x())
            h = abs(self.start_point.y() - self.end_point.y())
            
            # Clear selected region from overlay
            painter.setCompositionMode(QPainter.CompositionMode_Clear)
            painter.fillRect(x1, y1, w, h, QBrush(Qt.transparent))

            # Draw border around region
            painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
            pen = QPen(QColor("#8E2DE2"), 2, Qt.DashLine)
            painter.setPen(pen)
            painter.drawRect(x1, y1, w, h)

    def mousePressEvent(self, event: Any) -> None:
        if event.button() == Qt.LeftButton:
            self.start_point = event.pos()
            self.end_point = event.pos()
            self.is_drawing = True
            self.update()

    def mouseMoveEvent(self, event: Any) -> None:
        if self.is_drawing:
            self.end_point = event.pos()
            self.update()

    def mouseReleaseEvent(self, event: Any) -> None:
        if event.button() == Qt.LeftButton and self.is_drawing:
            self.is_drawing = False
            x1 = min(self.start_point.x(), self.end_point.x())
            y1 = min(self.start_point.y(), self.end_point.y())
            w = abs(self.start_point.x() - self.end_point.x())
            h = abs(self.start_point.y() - self.end_point.y())

            # Emit region if size is non-trivial
            if w > 10 and h > 10:
                self.region_selected.emit(x1, y1, w, h)
            self.close()

    def keyPressEvent(self, event: Any) -> None:
        if event.key() == Qt.Key_Escape:
            self.close()


class VisionBotWidget(QWidget):
    """Obsidian dark-themed premium floating widget to control the bot."""

    def __init__(self) -> None:
        super().__init__()
        self.drag_position = QPoint()
        self.runner = BotRunner()
        self.runner_thread: Optional[BotRunnerThread] = None
        self.autopilot_thread: Optional[AutopilotRunnerThread] = None

        self.init_ui()
        self.load_config_to_ui()
        self.check_system_status()

    def init_ui(self) -> None:
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        # Smaller default size to keep the widget compact
        self.resize(360, 560)

        # Style sheet (Obsidian glassmorphism, nice buttons)
        self.setStyleSheet("""
            QWidget#MainFrame {
                background-color: #121216;
                border: 1px solid #282830;
                border-radius: 12px;
            }
            QLabel {
                color: #B3B3C2;
                font-family: 'Segoe UI', sans-serif;
                font-size: 11px;
            }
            QLabel#TitleLabel {
                color: #FFFFFF;
                font-size: 13px;
                font-weight: bold;
            }
            QLineEdit {
                background-color: #1A1A22;
                border: 1px solid #2D2D38;
                border-radius: 6px;
                color: #FFFFFF;
                padding: 6px 10px;
                font-family: 'Segoe UI', sans-serif;
                font-size: 11px;
            }
            QLineEdit:focus {
                border: 1px solid #8E2DE2;
            }
            QComboBox {
                background-color: #1A1A22;
                border: 1px solid #2D2D38;
                border-radius: 6px;
                color: #FFFFFF;
                padding: 4px 10px;
                font-family: 'Segoe UI', sans-serif;
                font-size: 11px;
            }
            QComboBox::drop-down {
                border: 0px;
            }
            QComboBox QAbstractItemView {
                background-color: #1A1A22;
                border: 1px solid #2D2D38;
                color: #FFFFFF;
                selection-background-color: #8E2DE2;
            }
            QPushButton {
                background-color: #20202A;
                border: 1px solid #2D2D38;
                border-radius: 6px;
                color: #E2E2E9;
                padding: 6px 12px;
                font-family: 'Segoe UI', sans-serif;
                font-weight: bold;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #2D2D3B;
                border: 1px solid #3E3E52;
            }
            QPushButton#BtnStart {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #11998e, stop:1 #38ef7d);
                color: #FFFFFF;
                border: 0px;
            }
            QPushButton#BtnStart:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #12a89d, stop:1 #45f085);
            }
            QPushButton#BtnPause {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #f7971e, stop:1 #ffd200);
                color: #121216;
                border: 0px;
            }
            QPushButton#BtnPause:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #faa32b, stop:1 #ffd71a);
            }
            QPushButton#BtnStop {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #ff007f, stop:1 #ff416c);
                color: #FFFFFF;
                border: 0px;
            }
            QPushButton#BtnStop:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #ff1a8c, stop:1 #ff577b);
            }
            QTextEdit#LogPanel {
                background-color: #0A0A0C;
                border: 1px solid #1E1E24;
                border-radius: 8px;
                color: #D2D2DC;
                font-family: 'Consolas', monospace;
                font-size: 10px;
            }
            QFrame#TitleLine {
                background-color: #202028;
                max-height: 1px;
            }
            QFrame#DBStatsFrame {
                background-color: #10101A;
                border: 1px solid #1E2A1E;
                border-radius: 8px;
            }
            QPushButton#BtnAutopilot {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #4776E6, stop:1 #8E54E9);
                color: #FFFFFF;
                border: 0px;
            }
            QPushButton#BtnAutopilot:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #5585f5, stop:1 #9e65f7);
            }
        """)

        # Main Layout
        self.main_container = QWidget(self)
        self.main_container.setObjectName("MainFrame")
        
        # Shadow effect
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(20)
        shadow.setColor(QColor(0, 0, 0, 160))
        shadow.setOffset(0, 5)
        self.main_container.setGraphicsEffect(shadow)

        layout = QVBoxLayout(self.main_container)
        # Slightly reduced margins for a more compact layout
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(10)

        # Custom Title Bar
        title_layout = QHBoxLayout()
        self.title_lbl = QLabel("👁  Vision Bot v2", self)
        self.title_lbl.setObjectName("TitleLabel")
        
        self.btn_min = QPushButton("－", self)
        self.btn_min.setFixedSize(22, 22)
        self.btn_min.setStyleSheet("QPushButton { border: 0px; font-size: 12px; } QPushButton:hover { background-color: #202028; }")
        self.btn_min.clicked.connect(self.showMinimized)

        self.btn_close = QPushButton("×", self)
        self.btn_close.setFixedSize(22, 22)
        self.btn_close.setStyleSheet("QPushButton { border: 0px; font-size: 14px; } QPushButton:hover { background-color: #9C0E26; color: white; }")
        self.btn_close.clicked.connect(self.close)

        title_layout.addWidget(self.title_lbl)
        title_layout.addStretch()
        title_layout.addWidget(self.btn_min)
        title_layout.addWidget(self.btn_close)
        layout.addLayout(title_layout)

        # Divider line
        line = QFrame(self)
        line.setObjectName("TitleLine")
        layout.addWidget(line)

        # Mode Selector Row
        mode_layout = QHBoxLayout()
        mode_lbl = QLabel("Modo de trabajo:", self)
        self.cb_mode = QComboBox(self)
        self.cb_mode.addItems(["Modo Automático", "Modo Visión", "Modo Playwright", "Modo Autopilot DB"])
        self.cb_mode.currentTextChanged.connect(self.on_mode_changed)
        mode_layout.addWidget(mode_lbl)
        mode_layout.addWidget(self.cb_mode)
        layout.addLayout(mode_layout)

        # URL Input Row (Playwright mode only)
        self.url_widget = QWidget(self)
        url_layout = QVBoxLayout(self.url_widget)
        url_layout.setContentsMargins(0, 0, 0, 0)
        url_layout.setSpacing(4)
        url_lbl = QLabel("URL del Formulario:", self)
        self.txt_url = QLineEdit(self)
        self.txt_url.setPlaceholderText("https://example.com/formulario")
        url_layout.addWidget(url_lbl)
        url_layout.addWidget(self.txt_url)
        layout.addWidget(self.url_widget)

        # Region Row (Vision mode only)
        self.region_widget = QWidget(self)
        region_layout = QHBoxLayout(self.region_widget)
        region_layout.setContentsMargins(0, 0, 0, 0)
        self.lbl_region_status = QLabel("Región: Completa", self)
        self.btn_select_region = QPushButton("📷 Selec. Región", self)
        self.btn_select_region.clicked.connect(self.start_region_selector)
        region_layout.addWidget(self.lbl_region_status)
        region_layout.addStretch()
        region_layout.addWidget(self.btn_select_region)
        layout.addWidget(self.region_widget)

        # Actions Buttons Row
        actions_layout = QHBoxLayout()
        self.btn_start = QPushButton("▶ Iniciar", self)
        self.btn_start.setObjectName("BtnStart")
        self.btn_start.clicked.connect(self.start_bot)

        self.btn_pause = QPushButton("⏸ Pausar", self)
        self.btn_pause.setObjectName("BtnPause")
        self.btn_pause.setEnabled(False)
        self.btn_pause.clicked.connect(self.toggle_pause)

        self.btn_stop = QPushButton("■ Detener", self)
        self.btn_stop.setObjectName("BtnStop")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_bot)

        actions_layout.addWidget(self.btn_start)
        actions_layout.addWidget(self.btn_pause)
        actions_layout.addWidget(self.btn_stop)
        layout.addLayout(actions_layout)

        # ── DB Stats Panel (visible sólo en Modo Autopilot DB) ──────────
        self.db_stats_frame = QFrame(self)
        self.db_stats_frame.setObjectName("DBStatsFrame")
        db_stats_layout = QVBoxLayout(self.db_stats_frame)
        db_stats_layout.setContentsMargins(10, 8, 10, 8)
        db_stats_layout.setSpacing(4)

        db_title = QLabel("📦  Base de Datos Autopilot", self)
        db_title.setStyleSheet("color: #8E54E9; font-weight: bold; font-size: 11px;")

        self.lbl_db_total      = QLabel("Total en BD: 0", self)
        self.lbl_db_hits       = QLabel("Desde BD: 0", self)
        self.lbl_db_azar       = QLabel("Al azar: 0", self)
        self.lbl_db_guardadas  = QLabel("Nuevas guardadas: 0", self)
        self.lbl_db_hojas      = QLabel("Hojas completadas: 0", self)

        for lbl in (self.lbl_db_total, self.lbl_db_hits,
                    self.lbl_db_azar, self.lbl_db_guardadas, self.lbl_db_hojas):
            lbl.setStyleSheet("color: #9A9AB0; font-size: 10px;")

        db_stats_layout.addWidget(db_title)
        db_stats_layout.addWidget(self.lbl_db_total)
        db_stats_layout.addWidget(self.lbl_db_hits)
        db_stats_layout.addWidget(self.lbl_db_azar)
        db_stats_layout.addWidget(self.lbl_db_guardadas)
        db_stats_layout.addWidget(self.lbl_db_hojas)

        layout.addWidget(self.db_stats_frame)
        self.db_stats_frame.hide()   # oculto hasta que se seleccione el modo

        # Real-time Log Panel
        log_lbl = QLabel("Registros de Eventos:", self)
        self.log_panel = QTextEdit(self)
        self.log_panel.setObjectName("LogPanel")
        self.log_panel.setReadOnly(True)
        layout.addWidget(log_lbl)
        layout.addWidget(self.log_panel)

        # AI result details
        details_frame = QFrame(self)
        details_frame.setObjectName("DetailsFrame")
        details_frame.setStyleSheet("""
            QFrame#DetailsFrame {
                background-color: #17171D;
                border: 1px solid #282830;
                border-radius: 8px;
            }
        """)
        details_layout = QVBoxLayout(details_frame)
        details_layout.setContentsMargins(10, 8, 10, 8)
        details_layout.setSpacing(5)

        details_title = QLabel("Detalle IA", self)
        details_title.setStyleSheet("color: #FFFFFF; font-weight: bold;")
        self.lbl_model_detail = QLabel("Modelo: -", self)
        self.lbl_confidence_detail = QLabel("Confianza: -", self)
        self.lbl_qwen_detail = QLabel("Qwen: -", self)

        details_layout.addWidget(details_title)
        details_layout.addWidget(self.lbl_model_detail)
        details_layout.addWidget(self.lbl_confidence_detail)
        details_layout.addWidget(self.lbl_qwen_detail)
        layout.addWidget(details_frame)

        # Bottom Bar: Status Indicators & Diagnostics
        bottom_layout = QHBoxLayout()
        self.lbl_status = QLabel("● Inactivo", self)
        self.lbl_status.setStyleSheet("color: #7A7A8A; font-weight: bold;")
        
        self.lbl_ollama_status = QLabel("Ollama: ●", self)
        self.lbl_ollama_status.setStyleSheet("color: #FF416C; font-weight: bold;")
        self.lbl_ollama_status.setToolTip("Estado de conexión a Ollama local.")

        self.lbl_tess_status = QLabel("Tesseract: ●", self)
        self.lbl_tess_status.setStyleSheet("color: #FF416C; font-weight: bold;")
        self.lbl_tess_status.setToolTip("Verifica si Tesseract-OCR está instalado en la ruta.")

        self.lbl_db_status = QLabel("DB: ●", self)
        self.lbl_db_status.setStyleSheet("color: #7A7A8A; font-weight: bold;")
        self.lbl_db_status.setToolTip("Base de datos Autopilot (autopilot_respuestas.db).")
        self.lbl_db_status.hide()   # sólo visible en Modo Autopilot DB

        bottom_layout.addWidget(self.lbl_status)
        bottom_layout.addStretch()
        bottom_layout.addWidget(self.lbl_db_status)
        bottom_layout.addWidget(self.lbl_ollama_status)
        bottom_layout.addWidget(self.lbl_tess_status)
        layout.addLayout(bottom_layout)

        # Set main layout inside frame container
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(self.main_container)

    def load_config_to_ui(self) -> None:
        """Load persistent config values into UI fields."""
        config = BotConfig.load()
        if config.mode == "auto":
            self.cb_mode.setCurrentIndex(0)
            self.url_widget.show()
            self.region_widget.show()
            self.db_stats_frame.hide()
            self.lbl_db_status.hide()
        elif config.mode == "playwright":
            self.cb_mode.setCurrentIndex(2)
            self.url_widget.show()
            self.region_widget.hide()
            self.db_stats_frame.hide()
            self.lbl_db_status.hide()
        elif config.mode == "autopilot_db":
            self.cb_mode.setCurrentIndex(3)
            self.url_widget.show()
            self.region_widget.hide()
            self.db_stats_frame.show()
            self.lbl_db_status.show()
            self._refresh_db_indicator()
        else:  # vision
            self.cb_mode.setCurrentIndex(1)
            self.url_widget.hide()
            self.region_widget.show()
            self.db_stats_frame.hide()
            self.lbl_db_status.hide()

        self.txt_url.setText(config.url)
        
        if config.region:
            rx, ry, rw, rh = config.region
            self.lbl_region_status.setText(f"Región: {rw}x{rh} en ({rx},{ry})")
        else:
            self.lbl_region_status.setText("Región: Completa")

        self.update_ai_details(
            model_used=config.reason_model,
            confidence=None,
            qwen_activated=False,
            threshold=config.confidence_threshold,
            reason="Sin resultado todavia.",
        )

    def save_ui_to_config(self) -> BotConfig:
        """Save UI fields back into persistent configuration."""
        config = BotConfig.load()
        idx = self.cb_mode.currentIndex()
        if idx == 0:
            config.mode = "auto"
        elif idx == 2:
            config.mode = "playwright"
        elif idx == 3:
            config.mode = "autopilot_db"
        else:
            config.mode = "vision"
        config.url = self.txt_url.text().strip()
        config.save()
        
        # Apply configuration back to runner (only for non-autopilot modes)
        if config.mode != "autopilot_db":
            self.runner.update_config(BotConfigUpdate(
                mode=config.mode,
                url=config.url
            ))
        return config

    def check_system_status(self) -> None:
        """Query system status from runner and color dots accordingly."""
        status = self.runner.get_system_status()
        
        # Ollama Dot
        if status.get("ollama_available"):
            self.lbl_ollama_status.setStyleSheet("color: #00F260; font-weight: bold;")
            models = status.get("ollama_models", [])
            model_info = ", ".join(models) if models else "No models found"
            reason_state = "OK" if status.get("reason_model_available") else "No encontrado"
            vision_state = "OK" if status.get("vision_model_available") else "No encontrado"
            self.lbl_ollama_status.setToolTip(
                f"Ollama Conectado. Modelos: {model_info}\n"
                f"Reason: {self.runner.config.get('reason_model')} ({reason_state})\n"
                f"Qwen: {self.runner.config.get('vision_model')} ({vision_state})"
            )
        else:
            self.lbl_ollama_status.setStyleSheet("color: #FF416C; font-weight: bold;")
            self.lbl_ollama_status.setToolTip("Ollama desconectado. ¿Está corriendo en el puerto 11434?")

        # Tesseract Dot
        if status.get("tesseract_available"):
            self.lbl_tess_status.setStyleSheet("color: #00F260; font-weight: bold;")
            self.lbl_tess_status.setToolTip("Tesseract OCR Encontrado.")
        else:
            self.lbl_tess_status.setStyleSheet("color: #FF416C; font-weight: bold;")
            self.lbl_tess_status.setToolTip(f"No se encontró Tesseract en: {self.runner.config.get('tesseract_cmd')}")

        self.update_ai_details(
            model_used=self.runner.config.get("reason_model", "-"),
            confidence=None,
            qwen_activated=False,
            threshold=self.runner.config.get("confidence_threshold", 0.70),
            reason="Esperando resultado de la pipeline.",
        )

    def update_ai_details(
        self,
        model_used: str,
        confidence: float | None,
        qwen_activated: bool,
        threshold: float,
        reason: str,
    ) -> None:
        """Refresh model, confidence, and Qwen diagnostics."""
        self.lbl_model_detail.setText(f"Modelo: {model_used or '-'}")

        if confidence is None:
            self.lbl_confidence_detail.setText(f"Confianza: - (umbral {threshold:.0%})")
            self.lbl_confidence_detail.setStyleSheet("color: #B3B3C2;")
        else:
            confidence_text = f"{confidence:.0%}"
            self.lbl_confidence_detail.setText(f"Confianza: {confidence_text} (umbral {threshold:.0%})")
            color = "#00F260" if confidence >= threshold else "#f7971e"
            self.lbl_confidence_detail.setStyleSheet(f"color: {color}; font-weight: bold;")

        qwen_text = "activo" if qwen_activated else "omitido"
        qwen_color = "#00F260" if qwen_activated else "#7A7A8A"
        self.lbl_qwen_detail.setText(f"Qwen: {qwen_text}")
        self.lbl_qwen_detail.setStyleSheet(f"color: {qwen_color}; font-weight: bold;")

        tooltip = reason or "Sin razonamiento disponible."
        self.lbl_model_detail.setToolTip(tooltip)
        self.lbl_confidence_detail.setToolTip(tooltip)
        self.lbl_qwen_detail.setToolTip(tooltip)

    def on_mode_changed(self, mode_text: str) -> None:
        if mode_text == "Modo Automático":
            self.url_widget.show()
            self.region_widget.show()
            self.db_stats_frame.hide()
            self.lbl_db_status.hide()
        elif mode_text == "Modo Playwright":
            self.url_widget.show()
            self.region_widget.hide()
            self.db_stats_frame.hide()
            self.lbl_db_status.hide()
        elif mode_text == "Modo Autopilot DB":
            self.url_widget.show()
            self.region_widget.hide()
            self.db_stats_frame.show()
            self.lbl_db_status.show()
            self._refresh_db_indicator()
        else:  # Modo Visión
            self.url_widget.hide()
            self.region_widget.show()
            self.db_stats_frame.hide()
            self.lbl_db_status.hide()
        self.save_ui_to_config()

    def start_region_selector(self) -> None:
        self.hide()  # Hide main window during capture
        time.sleep(0.3)
        self.selector = RegionSelector()
        self.selector.region_selected.connect(self.on_region_selected)
        self.selector.show()

    def on_region_selected(self, x: int, y: int, w: int, h: int) -> None:
        self.lbl_region_status.setText(f"Región: {w}x{h} en ({x},{y})")
        # Save to configuration
        config = BotConfig.load()
        config.region = (x, y, w, h)
        config.save()
        
        # Update runner configuration
        self.runner.update_config(BotConfigUpdate(region=(x, y, w, h)))
        self.show()  # Re-show main window

    # Draggable Frameless Window
    def mousePressEvent(self, event: Any) -> None:
        if event.button() == Qt.LeftButton:
            self.drag_position = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event: Any) -> None:
        if event.buttons() == Qt.LeftButton:
            self.move(event.globalPos() - self.drag_position)
            event.accept()

    # Bot Control Slots
    def start_bot(self) -> None:
        # Save settings first
        config = self.save_ui_to_config()

        # ── Modo Autopilot DB ──────────────────────────────────────────
        if config.mode == "autopilot_db":
            url = config.url.strip()
            if not url:
                self.append_log("ERROR: Configura la URL antes de iniciar el Autopilot DB.", "ERROR")
                return
            self.btn_start.setEnabled(False)
            self.btn_pause.setEnabled(True)
            self.btn_stop.setEnabled(True)
            self.cb_mode.setEnabled(False)
            self.txt_url.setEnabled(False)
            self.btn_select_region.setEnabled(False)

            self.autopilot_thread = AutopilotRunnerThread(
                url=url,
                bot_config=self.runner.config,
                keep_browser_open=True,
            )
            self.autopilot_thread.log_signal.connect(self.on_runner_log)
            self.autopilot_thread.status_signal.connect(self.on_runner_status)
            self.autopilot_thread.db_stats_signal.connect(self.on_db_stats)
            self.autopilot_thread.start()
            return

        # ── Modos Automático / Visión / Playwright ─────────────────────
        # Check dependencies before starting
        status = self.runner.get_system_status()
        if config.mode == "vision" and not status.get("tesseract_available"):
            self.append_log("ERROR: Tesseract OCR no está disponible. No se puede iniciar.", "ERROR")
            return
        if not status.get("ollama_available"):
            self.append_log("ERROR: Servidor Ollama no está disponible. No se puede iniciar.", "ERROR")
            return
        if not status.get("reason_model_available"):
            self.append_log(
                f"ERROR: Modelo de razonamiento no encontrado: {self.runner.config.get('reason_model')}",
                "ERROR",
            )
            return
        if self.runner.config.get("vision_enabled", True) and not status.get("vision_model_available"):
            self.append_log(
                f"WARNING: Qwen no encontrado: {self.runner.config.get('vision_model')}. La pipeline seguira sin analisis visual.",
                "WARNING",
            )

        self.btn_start.setEnabled(False)
        self.btn_pause.setEnabled(True)
        self.btn_stop.setEnabled(True)
        self.cb_mode.setEnabled(False)
        self.txt_url.setEnabled(False)
        self.btn_select_region.setEnabled(False)

        # Threaded run
        self.runner_thread = BotRunnerThread(self.runner)
        self.runner_thread.log_signal.connect(self.on_runner_log)
        self.runner_thread.status_signal.connect(self.on_runner_status)
        self.runner_thread.result_signal.connect(self.on_runner_result)
        self.runner_thread.start()

    def toggle_pause(self) -> None:
        # Autopilot DB thread
        if self.autopilot_thread and self.autopilot_thread.isRunning():
            if self.btn_pause.text().startswith("⏸"):
                self.autopilot_thread.pause()
                self.btn_pause.setText("▶ Reanudar")
            else:
                self.autopilot_thread.resume()
                self.btn_pause.setText("⏸ Pausar")
            return

        # Modos existentes
        if not self.runner.loop_active:
            return
        
        if self.runner.paused:
            self.runner.resume_loop()
            self.btn_pause.setText("⏸ Pausar")
        else:
            self.runner.pause_loop()
            self.btn_pause.setText("▶ Reanudar")

    def stop_bot(self) -> None:
        # Detener Autopilot DB si está activo
        if self.autopilot_thread and self.autopilot_thread.isRunning():
            self.autopilot_thread.stop()
            self.autopilot_thread.wait(3000)
            self.autopilot_thread = None

        # Detener runner normal si está activo
        if self.runner_thread:
            self.runner.stop_loop()
            self.runner_thread.wait()
            self.runner_thread = None

        self.btn_start.setEnabled(True)
        self.btn_pause.setEnabled(False)
        self.btn_pause.setText("⏸ Pausar")
        self.btn_stop.setEnabled(False)
        self.cb_mode.setEnabled(True)
        self.txt_url.setEnabled(True)
        self.btn_select_region.setEnabled(True)

    # Thread Signal Handlers
    @pyqtSlot(str, str)
    def on_runner_log(self, message: str, level: str) -> None:
        self.append_log(message, level)

    @pyqtSlot(str)
    def on_runner_status(self, status: str) -> None:
        if status == "running":
            self.lbl_status.setText("● Ejecutando")
            self.lbl_status.setStyleSheet("color: #00F260; font-weight: bold;")
        elif status == "paused":
            self.lbl_status.setText("● Pausado")
            self.lbl_status.setStyleSheet("color: #f7971e; font-weight: bold;")
        else:
            self.lbl_status.setText("● Inactivo")
            self.lbl_status.setStyleSheet("color: #7A7A8A; font-weight: bold;")
            self.btn_start.setEnabled(True)
            self.btn_pause.setEnabled(False)
            self.btn_pause.setText("⏸ Pausar")
            self.btn_stop.setEnabled(False)
            self.cb_mode.setEnabled(True)
            self.txt_url.setEnabled(True)
            self.btn_select_region.setEnabled(True)

    @pyqtSlot(dict)
    def on_runner_result(self, result: dict) -> None:
        answer = result.get("answer", {})
        confidence = answer.get("confidence")
        try:
            confidence_value = float(confidence) if confidence is not None else None
        except (TypeError, ValueError):
            confidence_value = None

        reason = str(answer.get("reason") or "")
        self.update_ai_details(
            model_used=str(result.get("model_used") or self.runner.config.get("reason_model", "-")),
            confidence=confidence_value,
            qwen_activated=bool(result.get("qwen_activated")),
            threshold=float(result.get("confidence_threshold") or self.runner.config.get("confidence_threshold", 0.70)),
            reason=reason,
        )

    # ------------------------------------------------------------------
    # Autopilot DB slots
    # ------------------------------------------------------------------

    @pyqtSlot(dict)
    def on_db_stats(self, stats: dict) -> None:
        """Actualiza el panel de estadísticas de BD en tiempo real."""
        total = stats.get("total_registros_db", 0)
        hits  = stats.get("respondidas_desde_db", 0)
        azar  = stats.get("respondidas_al_azar", 0)
        saved = stats.get("nuevas_guardadas", 0)
        hojas = stats.get("hojas_completadas", 0)

        self.lbl_db_total.setText(f"Total en BD: {total:,}")
        self.lbl_db_hits.setText(f"Desde BD: {hits}")
        self.lbl_db_azar.setText(f"Al azar: {azar}")
        self.lbl_db_guardadas.setText(f"Nuevas guardadas: {saved}")
        self.lbl_db_hojas.setText(f"Hojas completadas: {hojas}")

        # Colorear stats
        self.lbl_db_hits.setStyleSheet("color: #00F260; font-size: 10px;" if hits > 0 else "color: #9A9AB0; font-size: 10px;")
        self.lbl_db_azar.setStyleSheet("color: #f7971e; font-size: 10px;" if azar > 0 else "color: #9A9AB0; font-size: 10px;")
        self.lbl_db_guardadas.setStyleSheet("color: #8E54E9; font-size: 10px;" if saved > 0 else "color: #9A9AB0; font-size: 10px;")

        # Actualizar indicador de BD
        if total > 0:
            self.lbl_db_status.setStyleSheet("color: #00F260; font-weight: bold;")
            self.lbl_db_status.setToolTip(f"BD Autopilot activa. {total:,} preguntas guardadas.")
        else:
            self.lbl_db_status.setStyleSheet("color: #f7971e; font-weight: bold;")
            self.lbl_db_status.setToolTip("BD Autopilot vacía. Aprenderá en esta sesión.")

    def _refresh_db_indicator(self) -> None:
        """Consulta la BD para actualizar el indicador sin iniciar el bot."""
        try:
            from core.db_manager import DBManager
            db = DBManager()
            total = db.contar_registros()
            db.close()
            if total > 0:
                self.lbl_db_status.setStyleSheet("color: #00F260; font-weight: bold;")
                self.lbl_db_status.setToolTip(f"BD Autopilot activa. {total:,} preguntas guardadas.")
                self.lbl_db_total.setText(f"Total en BD: {total:,}")
            else:
                self.lbl_db_status.setStyleSheet("color: #f7971e; font-weight: bold;")
                self.lbl_db_status.setToolTip("BD Autopilot vacía. Aprenderá en esta sesión.")
                self.lbl_db_total.setText("Total en BD: 0")
        except Exception:
            self.lbl_db_status.setStyleSheet("color: #7A7A8A; font-weight: bold;")

    # ------------------------------------------------------------------
    # Log
    # ------------------------------------------------------------------

    def append_log(self, message: str, level: str = "INFO") -> None:
        color = "#D2D2DC"
        if level == "SUCCESS":
            color = "#00F260"
        elif level == "WARNING":
            color = "#f7971e"
        elif level == "ERROR":
            color = "#FF416C"

        timestamp = time.strftime("%H:%M:%S")
        self.log_panel.append(
            f'<font color="#6A6A7A">[{timestamp}]</font> '
            f'<font color="{color}">[{level}] {message}</font>'
        )


if __name__ == "__main__":
    # Enable High-DPI scaling and make the process DPI-aware on Windows
    try:
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    except Exception:
        pass

    if sys.platform.startswith("win"):
        try:
            import ctypes
            # Prefer SetProcessDpiAwareness if available, fallback to SetProcessDPIAware
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(1)
            except Exception:
                try:
                    ctypes.windll.user32.SetProcessDPIAware()
                except Exception:
                    pass
        except Exception:
            pass

    app = QApplication(sys.argv)
    widget = VisionBotWidget()
    widget.show()
    sys.exit(app.exec_())
