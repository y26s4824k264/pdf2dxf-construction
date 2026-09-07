from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ConversionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile: Literal["universal", "legacy-r12"] = "universal"
    emit_r12: bool = False
    pages: list[int] | Literal["all"] = "all"
    mode: Literal["auto", "sheet", "blocks"] = "auto"
    units: Literal["auto", "mm", "cm", "m", "inch"] = "auto"
    scale_mode: Literal["auto", "page", "manual", "declared"] = "auto"
    manual_scale: float | None = None
    text_mode: Literal["editable", "outline", "hybrid"] = "editable"
    curve_mode: Literal["native", "compatible", "polyline"] = "compatible"
    fill_mode: Literal["hatch", "solid", "boundary"] = "hatch"
    memory_limit_mb: int = Field(default=2560, ge=256)
    temp_disk_limit_mb: int = Field(default=20480, ge=1024)
    workers: int = Field(default=2, ge=1, le=16)
    timeout_seconds: int = Field(default=1800, ge=30)
    allow_partial: bool = True
    deterministic: bool = True
    strict_validation: bool = True
    recover_pure_path_text: bool = True
    outline_chinese: Literal["off", "auto", "required"] = "off"
    outline_font_catalogs: list[str] = Field(default_factory=list, max_length=32)
    path_text_policy: Literal["keep", "off_layer", "drop"] = "off_layer"
    dimension_p95_limit: float = Field(default=0.002, gt=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def _manual(self):
        if self.scale_mode == "manual" and (
            self.manual_scale is None or self.manual_scale <= 0
        ):
            raise ValueError("manual_scale must be positive when scale_mode=manual")
        if self.manual_scale is not None and (
            not math.isfinite(self.manual_scale) or self.manual_scale <= 0
        ):
            raise ValueError("manual_scale must be finite and positive")
        if self.manual_scale is not None and self.scale_mode != "manual":
            raise ValueError("manual_scale requires scale_mode=manual")
        if self.pages != "all" and (not self.pages or any(n <= 0 for n in self.pages)):
            raise ValueError("pages must contain positive 1-based page numbers")
        if self.text_mode == "outline":
            raise ValueError(
                "text_mode=outline is not implemented; use editable or hybrid"
            )
        if self.curve_mode != "compatible":
            raise ValueError("only curve_mode=compatible is implemented")
        if self.fill_mode != "hatch":
            raise ValueError("only fill_mode=hatch is implemented")
        normalized_catalogs: list[str] = []
        for value in self.outline_font_catalogs:
            normalized = value.strip()
            if not normalized or len(normalized) > 4096:
                raise ValueError("outline_font_catalogs contains an invalid path")
            if normalized not in normalized_catalogs:
                normalized_catalogs.append(normalized)
        self.outline_font_catalogs = normalized_catalogs
        if self.outline_font_catalogs and self.outline_chinese == "off":
            raise ValueError(
                "outline_font_catalogs requires outline_chinese=auto or required"
            )
        return self


@dataclass(slots=True)
class ConversionArtifact:
    kind: str
    path: str
    sha256: str | None = None
    size_bytes: int | None = None


@dataclass(slots=True)
class ConversionResult:
    status: Literal["ok", "degraded", "failed"]
    source: str
    artifacts: list[ConversionArtifact]
    pages: list[dict[str, Any]]
    warnings: list[dict[str, Any]]
    errors: list[dict[str, Any]]
    report_path: str | None = None
    schema: str = "pdf2dxf.stable.result.v2"
    input_validation: dict[str, Any] | None = None

    def to_dict(self):
        return asdict(self)
