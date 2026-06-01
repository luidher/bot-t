from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class BotConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str = Field(default="llama3.1", min_length=1, max_length=120)
    ollama_host: str = Field(default="http://localhost:11434", min_length=1, max_length=300)
    lang: str = Field(default="spa+eng", min_length=1, max_length=80)
    psm: int = Field(default=6, ge=0, le=13)
    region: tuple[int, int, int, int] | None = None
    no_preprocess: bool = False
    click: bool = True
    confirm: bool = False
    i_am_authorized: bool = True
    min_click_score: float = Field(default=0.58, ge=0.0, le=1.0)
    interval: float = Field(default=3.0, ge=0.2, le=3600.0)
    tesseract_cmd: str = Field(default=r"C:\Program Files\Tesseract-OCR\tesseract.exe", max_length=500)
    auto_scroll: bool = False
    scroll_amount: int = Field(default=-300, ge=-10000, le=10000)
    scroll_delay: float = Field(default=1.0, ge=0.0, le=60.0)

    @field_validator("model", "ollama_host", "lang", "tesseract_cmd", mode="before")
    @classmethod
    def _strip_text(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

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


class BotConfigUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str | None = Field(default=None, min_length=1, max_length=120)
    ollama_host: str | None = Field(default=None, min_length=1, max_length=300)
    lang: str | None = Field(default=None, min_length=1, max_length=80)
    psm: int | None = Field(default=None, ge=0, le=13)
    region: tuple[int, int, int, int] | None = None
    no_preprocess: bool | None = None
    click: bool | None = None
    confirm: bool | None = None
    i_am_authorized: bool | None = None
    min_click_score: float | None = Field(default=None, ge=0.0, le=1.0)
    interval: float | None = Field(default=None, ge=0.2, le=3600.0)
    tesseract_cmd: str | None = Field(default=None, max_length=500)
    auto_scroll: bool | None = None
    scroll_amount: int | None = Field(default=None, ge=-10000, le=10000)
    scroll_delay: float | None = Field(default=None, ge=0.0, le=60.0)

    @field_validator("model", "ollama_host", "lang", "tesseract_cmd", mode="before")
    @classmethod
    def _strip_text(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

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


def default_config_dict() -> dict[str, Any]:
    return BotConfig().model_dump(mode="json")


def merge_config(current: dict[str, Any], update: BotConfigUpdate) -> dict[str, Any]:
    values = update.model_dump(exclude_unset=True, mode="json")
    return BotConfig.model_validate({**current, **values}).model_dump(mode="json")
