from __future__ import annotations

"""Conservative Unicode recovery for outline/search-text PDFs.

Many CAD PDFs paint visible glyphs as vector paths and add an invisible Unicode
text layer for copy/search. This module uses that invisible text as semantic
metadata, but only suppresses the matching vector outlines when spatial,
optional-content-layer, and paint-order evidence agree.
"""

from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence
import math

import fitz
import numpy as np
from shapely.geometry import box
from shapely.strtree import STRtree


@dataclass(slots=True)
class TextCharObservation:
    text: str
    bbox: tuple[float, float, float, float]
    origin: tuple[float, float]


@dataclass(slots=True)
class TextRunObservation:
    text: str
    chars: list[TextCharObservation]
    bbox: tuple[float, float, float, float]
    direction: tuple[float, float]
    size: float
    font: str
    rgb: tuple[int, int, int] | None
    opacity: float
    hidden: bool
    layer: str
    seqno: int
    source: str
    index: int

    @property
    def nonspace_chars(self) -> list[TextCharObservation]:
        return [
            c
            for c in self.chars
            if c.text and not c.text.isspace() and c.text != "\ufffd"
        ]


@dataclass(slots=True)
class OutlineRecord:
    record_index: int
    seqno: int
    layer: str
    typ: str
    bbox: tuple[float, float, float, float]
    item_count: int


@dataclass(slots=True)
class OutlineMatch:
    run_index: int
    record_indices: list[int]
    record_seqnos: list[int]
    confidence: float
    char_coverage: float
    layer_score: float
    sequence_score: float
    bbox_score: float


@dataclass(slots=True)
class TextRecoveryConfig:
    recover_hidden_search_text: bool = True
    matched_text_visible: bool = True
    unmatched_text_visible: bool = False
    recovered_text_layer: str = "PDF_RECOVERED_TEXT"
    unmatched_text_layer: str = "PDF_RECOVERED_TEXT_UNMATCHED"
    outline_original_layer: str = "PDF_OUTLINE_TEXT_ORIGINAL"
    outline_policy: str = "off_layer"  # keep | off_layer | drop
    min_match_confidence: float = 0.74
    min_char_coverage: float = 0.58
    bbox_expand_factor: float = 0.12
    bbox_expand_min_pt: float = 0.30
    max_candidate_extent_factor: float = 2.25
    max_candidate_area_factor: float = 3.0
    max_sequence_span: int = 768
    max_candidates_per_run: int = 4096
    allow_stroke_only_candidates: bool = True


@dataclass(slots=True)
class TextRecoveryDiagnostics:
    trace_sane: bool = False
    texttrace_runs: int = 0
    rawdict_runs: int = 0
    hidden_runs: int = 0
    hidden_chars: int = 0
    matched_runs: int = 0
    unmatched_runs: int = 0
    matched_outline_records: int = 0
    warnings: list[str] = field(default_factory=list)


def _rgb_from_trace(value: Any) -> tuple[int, int, int] | None:
    if value is None:
        return None
    try:
        vals = list(value)
    except Exception:
        return None
    if len(vals) == 1:
        g = int(round(max(0.0, min(1.0, float(vals[0]))) * 255))
        return g, g, g
    if len(vals) >= 3:
        return tuple(int(round(max(0.0, min(1.0, float(x))) * 255)) for x in vals[:3])  # type: ignore[return-value]
    return None


def _union_bbox(
    chars: Iterable[TextCharObservation], fallback: Sequence[float]
) -> tuple[float, float, float, float]:
    rows = list(chars)
    if not rows:
        return tuple(map(float, fallback))  # type: ignore[return-value]
    return (
        min(c.bbox[0] for c in rows),
        min(c.bbox[1] for c in rows),
        max(c.bbox[2] for c in rows),
        max(c.bbox[3] for c in rows),
    )


def _trace_sanity(page: fitz.Page, traces: list[dict[str, Any]]) -> bool:
    w, h = float(page.cropbox.width), float(page.cropbox.height)
    inside = total = 0
    for tr in traces:
        for row in tr.get("chars", []):
            try:
                b = row[3]
                cx = (float(b[0]) + float(b[2])) * 0.5
                cy = (float(b[1]) + float(b[3])) * 0.5
            except Exception:
                continue
            total += 1
            if -0.05 * w <= cx <= 1.05 * w and -0.05 * h <= cy <= 1.05 * h:
                inside += 1
    return total > 0 and inside / total >= 0.95


def _build_trace_runs(traces: list[dict[str, Any]]) -> list[TextRunObservation]:
    rows: list[TextRunObservation] = []
    for index, tr in enumerate(traces):
        chars: list[TextCharObservation] = []
        for item in tr.get("chars", []):
            try:
                code = int(item[0])
                text = chr(code) if 0 <= code <= 0x10FFFF else "\ufffd"
                origin = (float(item[2][0]), float(item[2][1]))
                bbox = tuple(map(float, item[3]))
            except Exception:
                continue
            chars.append(TextCharObservation(text=text, bbox=bbox, origin=origin))
        text = "".join(c.text for c in chars)
        if not text:
            continue
        rows.append(
            TextRunObservation(
                text=text,
                chars=chars,
                bbox=_union_bbox(chars, tr.get("bbox", (0, 0, 0, 0))),
                direction=tuple(map(float, tr.get("dir", (1.0, 0.0)))),
                size=float(tr.get("size", 1.0) or 1.0),
                font=str(tr.get("font", "") or "PDF"),
                rgb=_rgb_from_trace(tr.get("color")),
                opacity=float(tr.get("opacity", 1.0) or 1.0),
                hidden=int(tr.get("type", 0) or 0) == 3,
                layer=str(tr.get("layer", "") or ""),
                seqno=int(tr.get("seqno", -1) if tr.get("seqno") is not None else -1),
                source="texttrace",
                index=index,
            )
        )
    return rows


def _run_key(text: str, font: str) -> tuple[str, str]:
    return text.replace("\x00", "").replace("\ufffd", ""), font.split("+")[-1]


def _build_rawdict_runs(
    page: fitz.Page, trace_runs: list[TextRunObservation]
) -> list[TextRunObservation]:
    try:
        raw = page.get_text("rawdict")
    except Exception:
        return []
    lookup: dict[tuple[str, str], list[TextRunObservation]] = {}
    for tr in trace_runs:
        lookup.setdefault(_run_key(tr.text, tr.font), []).append(tr)
    used: set[int] = set()
    rows: list[TextRunObservation] = []
    out_index = 0
    for block in raw.get("blocks", []):
        if int(block.get("type", 0)) != 0:
            continue
        for line in block.get("lines", []):
            direction = tuple(map(float, line.get("dir", (1.0, 0.0))))
            for span in line.get("spans", []):
                chars: list[TextCharObservation] = []
                for item in span.get("chars", []):
                    text = str(item.get("c", ""))
                    try:
                        bbox = tuple(
                            map(float, item.get("bbox", span.get("bbox", (0, 0, 0, 0))))
                        )
                        origin = tuple(
                            map(float, item.get("origin", (bbox[0], bbox[3])))
                        )
                    except Exception:
                        continue
                    chars.append(
                        TextCharObservation(text=text, bbox=bbox, origin=origin)
                    )
                text = "".join(c.text for c in chars)
                if not text:
                    continue
                font = str(span.get("font", "") or "PDF")
                borrowed: TextRunObservation | None = None
                for candidate in lookup.get(_run_key(text, font), []):
                    if candidate.index not in used:
                        borrowed = candidate
                        used.add(candidate.index)
                        break
                alpha = int(span.get("alpha", 255) or 0)
                color_int = int(span.get("color", 0) or 0)
                rgb = ((color_int >> 16) & 255, (color_int >> 8) & 255, color_int & 255)
                rows.append(
                    TextRunObservation(
                        text=text,
                        chars=chars,
                        bbox=_union_bbox(chars, span.get("bbox", (0, 0, 0, 0))),
                        direction=direction,
                        size=float(span.get("size", 1.0) or 1.0),
                        font=font,
                        rgb=rgb,
                        opacity=max(0.0, min(1.0, alpha / 255.0)),
                        hidden=alpha <= 4,
                        layer=borrowed.layer if borrowed is not None else "",
                        seqno=borrowed.seqno if borrowed is not None else -1,
                        source="rawdict+trace" if borrowed is not None else "rawdict",
                        index=out_index,
                    )
                )
                out_index += 1
    return rows


def _repair_trace_unicode(page, runs, diagnostics):
    """Use a second native PDF decoding only at an identical font/origin.

    Some embedded fonts decode as U+FFFD in texttrace but expose Unicode in
    rawdict. Keep trace geometry/layer/visibility. Reject ambiguous positions.
    """
    if not any(char.text == "\ufffd" for run in runs for char in run.chars):
        return
    try:
        raw = page.get_text("rawdict")
    except Exception:
        return

    def key(font, origin):
        return (
            font.split("+")[-1],
            round(float(origin[0]), 4),
            round(float(origin[1]), 4),
        )

    candidates = {}
    for block in raw.get("blocks", []):
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                for char in span.get("chars", []):
                    text = char.get("c", "")
                    if text and "\ufffd" not in text and char.get("origin") is not None:
                        candidates.setdefault(
                            key(span.get("font", ""), char["origin"]), set()
                        ).add(text)
    recovered = 0
    for run in runs:
        for char in run.chars:
            if char.text != "\ufffd":
                continue
            values = candidates.get(key(run.font, char.origin), set())
            if len(values) == 1:
                char.text = next(iter(values))
                recovered += 1
        run.text = "".join(char.text for char in run.chars)
    if recovered:
        diagnostics.warnings.append(
            f"native rawdict Unicode matched {recovered} texttrace replacement characters at identical font/origin"
        )


def extract_text_runs(
    page: fitz.Page, diagnostics: TextRecoveryDiagnostics | None = None
) -> list[TextRunObservation]:
    diagnostics = diagnostics or TextRecoveryDiagnostics()
    try:
        traces = list(page.get_texttrace())
    except Exception as exc:
        traces = []
        diagnostics.warnings.append(f"get_texttrace failed: {exc}")
    trace_runs = _build_trace_runs(traces)
    _repair_trace_unicode(page, trace_runs, diagnostics)
    diagnostics.texttrace_runs = len(trace_runs)
    diagnostics.trace_sane = _trace_sanity(page, traces)
    if diagnostics.trace_sane:
        runs = trace_runs
    else:
        runs = _build_rawdict_runs(page, trace_runs)
        diagnostics.rawdict_runs = len(runs)
        if traces:
            diagnostics.warnings.append(
                "texttrace coordinates inconsistent with CropBox; rawdict positions used"
            )
    diagnostics.hidden_runs = sum(r.hidden for r in runs)
    diagnostics.hidden_chars = sum(len(r.nonspace_chars) for r in runs if r.hidden)
    return runs


class OutlineRecordIndex:
    def __init__(self, drawings: list[dict[str, Any]]):
        self.records: list[OutlineRecord] = []
        geoms = []
        for i, d in enumerate(drawings):
            typ = str(d.get("type", ""))
            if typ not in {"f", "fs", "s"}:
                continue
            r = d.get("rect")
            if not r:
                continue
            try:
                bbox = tuple(map(float, r))
            except Exception:
                continue
            if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
                continue
            self.records.append(
                OutlineRecord(
                    record_index=i,
                    seqno=int(d.get("seqno", -1) if d.get("seqno") is not None else -1),
                    layer=str(d.get("layer", "") or ""),
                    typ=typ,
                    bbox=bbox,
                    item_count=len(d.get("items", [])),
                )
            )
            geoms.append(box(*bbox))
        self.tree = STRtree(geoms) if geoms else None

    def query(self, bbox: Sequence[float]) -> list[OutlineRecord]:
        if self.tree is None:
            return []
        return [self.records[int(i)] for i in self.tree.query(box(*map(float, bbox)))]


def _bbox_intersection_area(a: Sequence[float], b: Sequence[float]) -> float:
    w = max(0.0, min(float(a[2]), float(b[2])) - max(float(a[0]), float(b[0])))
    h = max(0.0, min(float(a[3]), float(b[3])) - max(float(a[1]), float(b[1])))
    return w * h


def _bbox_area(a: Sequence[float]) -> float:
    return max(0.0, float(a[2]) - float(a[0])) * max(0.0, float(a[3]) - float(a[1]))


def _center_inside(inner: Sequence[float], outer: Sequence[float]) -> bool:
    cx = (float(inner[0]) + float(inner[2])) * 0.5
    cy = (float(inner[1]) + float(inner[3])) * 0.5
    return float(outer[0]) <= cx <= float(outer[2]) and float(outer[1]) <= cy <= float(
        outer[3]
    )


def match_outline_records(
    runs: list[TextRunObservation],
    drawings: list[dict[str, Any]],
    config: TextRecoveryConfig | None = None,
    diagnostics: TextRecoveryDiagnostics | None = None,
) -> tuple[dict[int, OutlineMatch], set[int]]:
    config = config or TextRecoveryConfig()
    diagnostics = diagnostics or TextRecoveryDiagnostics()
    if not any(run.hidden and run.nonspace_chars for run in runs):
        return {}, set()
    index = OutlineRecordIndex(drawings)
    matches: dict[int, OutlineMatch] = {}
    matched_record_indices: set[int] = set()

    for run in runs:
        if not run.hidden or not run.nonspace_chars:
            continue
        x0, y0, x1, y1 = run.bbox
        width = max(x1 - x0, 1e-6)
        height = max(y1 - y0, 1e-6)
        expand = max(
            config.bbox_expand_min_pt, max(width, height) * config.bbox_expand_factor
        )
        query_bbox = (x0 - expand, y0 - expand, x1 + expand, y1 + expand)
        raw_candidates = index.query(query_bbox)
        if len(raw_candidates) > config.max_candidates_per_run:
            diagnostics.warnings.append(
                f"outline query too broad for run {run.index}: {len(raw_candidates)}"
            )
            continue
        candidates: list[OutlineRecord] = []
        for rec in raw_candidates:
            rw = rec.bbox[2] - rec.bbox[0]
            rh = rec.bbox[3] - rec.bbox[1]
            if (
                max(rw, rh)
                > max(width, height) * config.max_candidate_extent_factor + expand
            ):
                continue
            if (
                _bbox_area(rec.bbox)
                > max(_bbox_area(run.bbox), 1e-6) * config.max_candidate_area_factor
            ):
                continue
            if (
                not _center_inside(rec.bbox, query_bbox)
                and _bbox_intersection_area(rec.bbox, query_bbox) <= 0
            ):
                continue
            if rec.typ == "s" and (
                not config.allow_stroke_only_candidates or rec.item_count <= 1
            ):
                continue
            if run.layer and rec.layer and rec.layer != run.layer:
                continue
            if (
                run.seqno >= 0
                and rec.seqno >= 0
                and run.seqno - rec.seqno > config.max_sequence_span * 4
            ):
                continue
            candidates.append(rec)
        if not candidates:
            continue

        covered = 0
        for ch in run.nonspace_chars:
            hit = False
            for rec in candidates:
                ia = _bbox_intersection_area(ch.bbox, rec.bbox)
                if (
                    ia > 0
                    or _center_inside(rec.bbox, ch.bbox)
                    or _center_inside(ch.bbox, rec.bbox)
                ):
                    hit = True
                    break
            covered += int(hit)
        char_coverage = covered / max(len(run.nonspace_chars), 1)
        layer_score = float(
            np.mean(
                [
                    1.0
                    if (not run.layer or not r.layer or r.layer == run.layer)
                    else 0.0
                    for r in candidates
                ]
            )
        )
        if run.seqno >= 0:
            good = 0.0
            for rec in candidates:
                if rec.seqno < 0:
                    good += 0.5
                else:
                    gap = run.seqno - rec.seqno
                    if 0 < gap <= config.max_sequence_span:
                        good += 1.0
                    elif abs(gap) <= config.max_sequence_span * 2:
                        good += 0.35
            sequence_score = good / max(len(candidates), 1)
        else:
            sequence_score = 0.5
        cb = _union_bbox(run.nonspace_chars, run.bbox)
        ub = (
            min(r.bbox[0] for r in candidates),
            min(r.bbox[1] for r in candidates),
            max(r.bbox[2] for r in candidates),
            max(r.bbox[3] for r in candidates),
        )
        bbox_score = max(
            0.0, min(1.0, _bbox_intersection_area(cb, ub) / max(_bbox_area(cb), 1e-6))
        )
        ratio = len(candidates) / max(len(run.nonspace_chars), 1)
        count_score = (
            1.0
            if 0.45 <= ratio <= 8.0
            else max(0.0, 1.0 - abs(math.log(max(ratio, 1e-6) / 1.5)) / 4.0)
        )
        confidence = (
            0.45 * char_coverage
            + 0.20 * layer_score
            + 0.15 * sequence_score
            + 0.12 * bbox_score
            + 0.08 * count_score
        )
        if (
            char_coverage < config.min_char_coverage
            or confidence < config.min_match_confidence
        ):
            continue
        record_indices = sorted({r.record_index for r in candidates})
        record_seqnos = sorted({r.seqno for r in candidates if r.seqno >= 0})
        matches[run.index] = OutlineMatch(
            run_index=run.index,
            record_indices=record_indices,
            record_seqnos=record_seqnos,
            confidence=float(confidence),
            char_coverage=float(char_coverage),
            layer_score=float(layer_score),
            sequence_score=float(sequence_score),
            bbox_score=float(bbox_score),
        )
        matched_record_indices.update(record_indices)

    diagnostics.matched_runs = len(matches)
    diagnostics.unmatched_runs = sum(
        1 for r in runs if r.hidden and r.nonspace_chars and r.index not in matches
    )
    diagnostics.matched_outline_records = len(matched_record_indices)
    return matches, matched_record_indices


__all__ = [
    "TextCharObservation",
    "TextRunObservation",
    "OutlineMatch",
    "TextRecoveryConfig",
    "TextRecoveryDiagnostics",
    "extract_text_runs",
    "match_outline_records",
]
