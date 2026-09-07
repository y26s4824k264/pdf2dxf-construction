from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

import ezdxf

from pdf2dxf_stable.engine.drawing_profile import (
    ConstructionProfileAnalyzerV15,
    canonical_layer_map,
)
from pdf2dxf_stable.engine.geometry.construction import (
    ConstructionGraphicsKernelV15,
    ConstructionKernelConfigV15,
)


@dataclass(slots=True)
class PipelineConfigV15:
    output_units: Literal["paper_mm", "pdf_pt", "model_mm"] = "paper_mm"
    dxf_version: str = "R2018"
    layer_mode: Literal["preserve", "discipline_prefix", "canonical"] = "preserve"
    include_native_dimensions: bool = False
    core_appid: str = "PDF2DXF15"
    construction_appid: str = "PDF2DXF15C"
    add_construction_xdata: bool = False
    clip_paths: bool = True
    emit_splines: bool = True
    emit_hatches: bool = True
    include_native_text: bool = True
    include_hidden_text: bool = True
    recover_outline_text: bool = True
    outline_text_policy: Literal["keep", "off_layer", "drop"] = "off_layer"
    include_images: bool = True
    include_shadings: bool = True
    clip_images: bool = True
    compact_dense_patterns: bool = True


@dataclass(slots=True)
class PipelineResultV15:
    source_pdf: str
    page_index: int
    output_dxf: str
    profile: dict[str, Any]
    kernel_stats: dict[str, Any]
    dimension: dict[str, Any] | None
    layer_mode: str
    output_units: str
    elapsed_seconds: float
    warnings: list[str] = field(default_factory=list)

    def to_dict(self):
        return asdict(self)

    def save(self, p):
        Path(p).write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )


class ConstructionPDF2DXFV15:
    def __init__(self, config: PipelineConfigV15 | None = None):
        self.config = config or PipelineConfigV15()
        if self.config.include_native_dimensions:
            raise ValueError(
                "include_native_dimensions was removed; use persisted-DXF scale "
                "calibration after base conversion"
            )
        self.profiler = ConstructionProfileAnalyzerV15()

    def _core(self):
        c = self.config
        return ConstructionKernelConfigV15(
            units="paper_mm",
            dxf_version=c.dxf_version,
            clip_paths=c.clip_paths,
            emit_splines=c.emit_splines,
            emit_hatches=c.emit_hatches,
            include_native_text=c.include_native_text,
            include_hidden_text=c.include_hidden_text,
            recover_outline_text=c.recover_outline_text,
            outline_text_policy=c.outline_text_policy,
            include_images=c.include_images,
            include_shadings=c.include_shadings,
            clip_images=c.clip_images,
            appid=c.core_appid,
            compact_dense_patterns=c.compact_dense_patterns,
        )

    @staticmethod
    def _prefix(d):
        return {
            "architecture": "A",
            "structure": "S",
            "electrical": "E",
            "plumbing": "P",
            "fire": "F",
            "hvac": "M",
            "civil_site": "C",
            "landscape": "L",
            "interior": "I",
            "general": "G",
        }.get(d, "G")

    def _layers(self, path, profile):
        c = self.config
        if c.layer_mode == "preserve" and not c.add_construction_xdata:
            return {}
        doc = ezdxf.readfile(str(path))
        by = {r.original_name: r for r in profile.layers}
        canon = canonical_layer_map(profile)
        ren = {}
        if c.add_construction_xdata and c.construction_appid not in doc.appids:
            doc.appids.add(c.construction_appid)
        if c.layer_mode != "preserve":
            for r in profile.layers:
                old = r.original_name
                if not old or old not in doc.layers:
                    continue
                new = (
                    canon[old]
                    if c.layer_mode == "canonical"
                    else (
                        self._prefix(r.discipline)
                        + "__"
                        + old.replace("|", "_").replace("/", "_").replace("\\", "_")
                    )[:240]
                )
                base = new
                n = 2
                while new in doc.layers and new != old:
                    new = f"{base[:230]}_{n:02d}"
                    n += 1
                doc.layers.get(old).rename(new)
                ren[old] = new
        reverse = {v: k for k, v in ren.items()}
        if c.add_construction_xdata:
            for e in doc.modelspace():
                layer = str(getattr(e.dxf, "layer", "") or "")
                orig = reverse.get(layer, layer)
                r = by.get(orig)
                disc, role, can = (
                    (r.discipline, r.role, r.canonical_name)
                    if r
                    else self.profiler.classify_layer(orig)
                )
                e.set_xdata(
                    c.construction_appid,
                    [
                        (1000, profile.primary_discipline),
                        (1000, profile.sheet_kind),
                        (1000, disc),
                        (1000, role),
                        (1000, can),
                        (1000, orig),
                    ],
                )
        doc.saveas(str(path))
        return ren

    def convert_page(self, pdf, page_index, output_dxf, manifest_path=None):
        from pdf2dxf_stable.drawings import cached_document

        with cached_document(pdf, page_index, Path(output_dxf).parent) as cached:
            return self._convert_page(cached, page_index, output_dxf, manifest_path)

    def _convert_page(self, pdf, page_index, output_dxf, manifest_path=None):
        t = time.perf_counter()
        c = self.config
        out = Path(output_dxf)
        out.parent.mkdir(parents=True, exist_ok=True)
        profile = self.profiler.analyze(pdf, page_index)
        ks = ConstructionGraphicsKernelV15(self._core()).convert_page(
            pdf, page_index, out
        )
        warnings = list(ks.warnings) + list(profile.warnings)
        if c.output_units != "paper_mm":
            warnings.append(
                "non-paper units require reliable dimensions; paper_mm retained"
            )
        ren = self._layers(out, profile)
        res = PipelineResultV15(
            str(getattr(pdf, "name", "")),
            page_index,
            str(out),
            profile.to_dict(),
            ks.to_dict(),
            None,
            c.layer_mode,
            "paper_mm",
            time.perf_counter() - t,
            warnings,
        )
        res.profile["layer_rename_map"] = ren
        if manifest_path:
            res.save(manifest_path)
        return res
