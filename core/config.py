"""Centralized configuration dataclass and Pydantic validation for Vision Bot v2."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional, Tuple
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CONFIG_FILE = Path("widget_config.json")

Region = Tuple[int, int, int, int]


class BotConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Operating mode
    mode: str = Field(default="auto")                # "auto" | "vision" | "playwright"


    # Target
    url: str = Field(default="")                       # Used in playwright mode

    # Ollama / AI
    # `model` se conserva como alias de compatibilidad para `reason_model`.
    model: str = Field(default="deepseek-r1:8b", min_length=1, max_length=120)
    ollama_host: str = Field(default="http://localhost:11434", min_length=1, max_length=300)
    vision_model: str = Field(default="qwen2.5-vl", min_length=1, max_length=120)
    reason_model: str = Field(default="deepseek-r1:8b", min_length=1, max_length=120)
    confidence_threshold: float = Field(default=0.70, ge=0.0, le=1.0)
    max_think_ms: int = Field(default=5000, ge=0)
    vision_enabled: bool = Field(default=True)
    log_reasoning: bool = Field(default=False)

    # Manual authentication wait (Playwright mode)
    wait_for_manual_auth: bool = Field(default=True)
    manual_auth_timeout_sec: int = Field(default=300, ge=0)
    manual_auth_poll_sec: float = Field(default=1.0, ge=0.1, le=60.0)

    # OCR (vision mode)
    lang: str = Field(default="spa+eng", min_length=1, max_length=80)
    psm: int = Field(default=6, ge=0, le=13)
    no_preprocess: bool = False
    region: Optional[tuple[int, int, int, int]] = None

    # Click behaviour
    click: bool = True
    confirm: bool = False
    i_am_authorized: bool = True
    min_click_score: float = Field(default=0.58, ge=0.0, le=1.0)

    # Loop timing
    interval: float = Field(default=3.0, ge=0.2, le=3600.0)

    # Multi-page settings
    max_pages: int = Field(default=50, ge=1)
    auto_next: bool = True
    next_wait_sec: float = Field(default=2.0, ge=0.0, le=60.0)

    # Playwright settings
    pw_timeout_ms: int = Field(default=60000, ge=0)
    pw_headless: bool = False           # False = browser visible

    # Tesseract path (vision mode)
    tesseract_cmd: str = Field(default=r"C:\Program Files\Tesseract-OCR\tesseract.exe", max_length=500)

    # Scroll behaviour
    auto_scroll: bool = False
    scroll_amount: int = Field(default=-300, ge=-10000, le=10000)
    scroll_delay: float = Field(default=1.0, ge=0.0, le=60.0)

    @field_validator("model", "vision_model", "reason_model", "ollama_host", "lang", "tesseract_cmd", "url", mode="before")
    @classmethod
    def _strip_text(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = value.strip()
            if value == "llama3.1":
                return "deepseek-r1:8b"
        return value

    @field_validator("ollama_host")
    @classmethod
    def _ensure_http(cls, value: str) -> str:
        if not value.startswith(("http://", "https://")):
            value = "http://" + value
        return value.rstrip("/")

    @model_validator(mode="after")
    def _validate_region(self) -> "BotConfig":
        if self.region is None:
            return self

        _x, _y, width, height = self.region
        if width <= 0 or height <= 0:
            raise ValueError("region debe tener ancho y alto mayores que cero")

        return self

    @model_validator(mode="after")
    def _sync_reason_model(self) -> "BotConfig":
        if self.model and self.reason_model != self.model:
            self.reason_model = self.model
        return self

    def save(self) -> None:
        """Persist config to JSON file."""
        try:
            data = self.model_dump(mode="json")
            with open(CONFIG_FILE, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=4, ensure_ascii=False)
        except Exception as exc:  # pragma: no cover
            print(f"[CONFIG] Error al guardar: {exc}")

    @classmethod
    def load(cls) -> "BotConfig":
        """Load config from JSON file, falling back to defaults."""
        if not CONFIG_FILE.exists():
            return cls()
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            # Only keep keys that exist in the model fields
            valid_keys = set(cls.model_fields.keys())
            filtered = {k: v for k, v in data.items() if k in valid_keys}
            return cls.model_validate(filtered)
        except Exception as exc:  # pragma: no cover
            print(f"[CONFIG] Error al cargar, usando defaults: {exc}")
            return cls()

    def ensure_http(self) -> str:
        """Return ollama_host guaranteed to have http:// prefix."""
        host = self.ollama_host.strip()
        if not host.startswith(("http://", "https://")):
            host = "http://" + host
        return host.rstrip("/")


class BotConfigUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Optional[str] = None
    url: Optional[str] = None
    model: Optional[str] = Field(default=None, min_length=1, max_length=120)
    ollama_host: Optional[str] = Field(default=None, min_length=1, max_length=300)
    vision_model: Optional[str] = Field(default=None, min_length=1, max_length=120)
    reason_model: Optional[str] = Field(default=None, min_length=1, max_length=120)
    confidence_threshold: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    max_think_ms: Optional[int] = Field(default=None, ge=0)
    vision_enabled: Optional[bool] = None
    log_reasoning: Optional[bool] = None
    wait_for_manual_auth: Optional[bool] = None
    manual_auth_timeout_sec: Optional[int] = Field(default=None, ge=0)
    manual_auth_poll_sec: Optional[float] = Field(default=None, ge=0.1, le=60.0)
    lang: Optional[str] = Field(default=None, min_length=1, max_length=80)
    psm: Optional[int] = Field(default=None, ge=0, le=13)
    region: Optional[tuple[int, int, int, int]] = None
    no_preprocess: Optional[bool] = None
    click: Optional[bool] = None
    confirm: Optional[bool] = None
    i_am_authorized: Optional[bool] = None
    min_click_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    interval: Optional[float] = Field(default=None, ge=0.2, le=3600.0)
    tesseract_cmd: Optional[str] = Field(default=None, max_length=500)
    auto_scroll: Optional[bool] = None
    scroll_amount: Optional[int] = Field(default=None, ge=-10000, le=10000)
    scroll_delay: Optional[float] = Field(default=None, ge=0.0, le=60.0)

    # Multi-page settings
    max_pages: Optional[int] = Field(default=None, ge=1)
    auto_next: Optional[bool] = None
    next_wait_sec: Optional[float] = Field(default=None, ge=0.0, le=60.0)

    # Playwright settings
    pw_timeout_ms: Optional[int] = Field(default=None, ge=0)
    pw_headless: Optional[bool] = None

    @field_validator("model", "vision_model", "reason_model", "ollama_host", "lang", "tesseract_cmd", "url", mode="before")
    @classmethod
    def _strip_text(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = value.strip()
            if value == "llama3.1":
                return "deepseek-r1:8b"
        return value

    @field_validator("ollama_host")
    @classmethod
    def _ensure_http(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.startswith(("http://", "https://")):
            value = "http://" + value
        return value.rstrip("/")

    @model_validator(mode="after")
    def _validate_region(self) -> "BotConfigUpdate":
        if self.region is None:
            return self

        _x, _y, width, height = self.region
        if width <= 0 or height <= 0:
            raise ValueError("region debe tener ancho y alto mayores que cero")

        return self

    @model_validator(mode="after")
    def _sync_reason_model(self) -> "BotConfigUpdate":
        if self.model and self.reason_model is None:
            self.reason_model = self.model
        return self


def default_config_dict() -> dict[str, Any]:
    return BotConfig().model_dump(mode="json")


def merge_config(current: dict[str, Any], update: BotConfigUpdate) -> dict[str, Any]:
    values = update.model_dump(exclude_unset=True, mode="json")
    return BotConfig.model_validate({**current, **values}).model_dump(mode="json")
