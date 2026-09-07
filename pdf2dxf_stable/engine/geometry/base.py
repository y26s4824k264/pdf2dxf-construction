from __future__ import annotations

"""Generic PDF vector graphics -> DXF kernel v1.4.

The module deliberately treats PDF coordinates as observations and preserves
geometry without applying architecture-specific semantics.  It uses PyMuPDF's
extended drawing stream to retain OCG layer names and clipping scopes, emits
native DXF primitives where confidence is high, and falls back to polylines
when exact primitive clipping is not practical.
"""

from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any, Iterable, Iterator, Literal, Sequence
import hashlib
import json
import math
import os
import re
import time

import cv2
import ezdxf
from ezdxf.enums import TextEntityAlignment
import fitz
import numpy as np
from shapely.geometry import (
    GeometryCollection,
    LineString,
    MultiLineString,
    MultiPolygon,
    Point,
    Polygon,
    box,
)
from shapely.ops import unary_union
from shapely.validation import make_valid

from pdf2dxf_stable.engine.geometry.native_text import (
    TextRecoveryConfig,
    TextRecoveryDiagnostics,
    TextRunObservation,
    extract_text_runs,
    match_outline_records,
)
from pdf2dxf_stable.engine.geometry.media import (
    MediaConfig,
    enumerate_media_occurrences,
    clip_polygon_to_image_pixels,
    extract_image_pixmap,
    render_image_mask_paints,
    render_shading_fallback,
)


INVALID_DXF_LAYER = re.compile(r'[<>/\\":;?*|=]')
POINT_EPS = 1e-5
TAU = math.tau


@dataclass(slots=True)
class KernelConfig:
    units: Literal["paper_mm", "pdf_pt"] = "paper_mm"
    dxf_version: str = "R2018"
    apply_page_rotation: bool = True
    include_page_boundary: bool = True

    # Geometry fidelity.
    preserve_layers: bool = True
    use_style_layers_when_missing: bool = True
    clip_paths: bool = True
    emit_splines: bool = True
    detect_circles: bool = True
    detect_ellipses: bool = True
    detect_arcs: bool = True
    emit_hatches: bool = True
    emit_fill_boundary: bool = False
    preserve_stroke_for_fill_stroke: bool = True
    curve_flatten_tolerance_pt: float = 0.12
    primitive_fit_rel_tol: float = 0.004
    ellipse_fit_rel_tol: float = 0.010
    min_entity_length_pt: float = 0.003
    min_fill_area_pt2: float = 1e-5

    # Text. Invisible search text can be promoted to visible editable text
    # when it conservatively matches vector outline glyphs.
    include_native_text: bool = True
    include_hidden_text: bool = True
    hidden_text_layer: str = "PDF_HIDDEN_TEXT"
    native_text_style: str = "PDF_NATIVE_TEXT"
    cjk_font: str = "simsun.ttf"
    latin_font: str = "Arial.ttf"
    native_text_height_factor: float = 0.86
    recovered_text_height_factor: float = 1.0
    recover_outline_text: bool = True
    outline_text_policy: Literal["keep", "off_layer", "drop"] = "off_layer"
    unmatched_recovered_text_visible: bool = False
    recovered_text_layer: str = "PDF_RECOVERED_TEXT"
    unmatched_recovered_text_layer: str = "PDF_RECOVERED_TEXT_UNMATCHED"
    outline_original_layer: str = "PDF_OUTLINE_TEXT_ORIGINAL"
    outline_min_match_confidence: float = 0.74

    # Images and PDF shadings are sidecar PNGs referenced by DXF IMAGE.
    # Non-rectangular PDF image clips become native IMAGE boundaries.
    include_images: bool = True
    include_shadings: bool = True
    image_subdir: str = "images"
    shading_subdir: str = "shadings"
    clip_images: bool = True
    max_image_clip_vertices: int = 192
    shading_render_scale: float = 2.0
    skip_unclipped_full_page_shading: bool = True

    # Metadata and performance.
    add_xdata: bool = True
    appid: str = "PDF2DXF14"
    max_layer_name: int = 220
    max_curve_samples: int = 96
    verbose: bool = False


@dataclass(slots=True)
class KernelStats:
    source_pdf: str = ""
    page_index: int = 0
    page_rotation: int = 0
    unit_mode: str = ""
    geometry_scale: float = 1.0
    input_draw_records: int = 0
    input_clip_records: int = 0
    input_group_records: int = 0
    input_stroke_records: int = 0
    input_fill_records: int = 0
    input_fill_stroke_records: int = 0
    source_subpaths: int = 0
    clipped_records: int = 0
    clipped_fallback_polylines: int = 0
    clip_rejected_records: int = 0
    line_entities: int = 0
    polyline_entities: int = 0
    spline_entities: int = 0
    circle_entities: int = 0
    arc_entities: int = 0
    ellipse_entities: int = 0
    elliptical_arc_entities: int = 0
    hatch_entities: int = 0
    hatch_holes: int = 0
    native_text_entities: int = 0
    hidden_text_entities: int = 0
    text_runs: int = 0
    hidden_text_runs: int = 0
    hidden_search_chars: int = 0
    outline_matched_runs: int = 0
    outline_unmatched_runs: int = 0
    recovered_text_entities: int = 0
    recovered_text_runs: int = 0
    unmatched_recovered_text_entities: int = 0
    matched_outline_records: int = 0
    outline_records_relayered: int = 0
    outline_records_dropped: int = 0
    image_entities: int = 0
    image_files: int = 0
    clipped_image_entities: int = 0
    image_clip_vertices: int = 0
    shading_entities: int = 0
    shading_files: int = 0
    outside_page_media_skipped: int = 0
    skipped_full_page_shadings: int = 0
    malformed_paths: int = 0
    invalid_geometries_repaired: int = 0
    zero_length_entities_skipped: int = 0
    layers: int = 0
    output_entities: int = 0
    output_bytes: int = 0
    elapsed_seconds: float = 0.0
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class LineSeg:
    p0: tuple[float, float]
    p1: tuple[float, float]


@dataclass(slots=True)
class CubicSeg:
    p0: tuple[float, float]
    c1: tuple[float, float]
    c2: tuple[float, float]
    p1: tuple[float, float]


Segment = LineSeg | CubicSeg


@dataclass(slots=True)
class PathChain:
    segments: list[Segment]
    closed: bool = False

    @property
    def start(self) -> tuple[float, float]:
        return self.segments[0].p0

    @property
    def end(self) -> tuple[float, float]:
        return self.segments[-1].p1

    @property
    def all_lines(self) -> bool:
        return all(isinstance(s, LineSeg) for s in self.segments)

    @property
    def all_cubics(self) -> bool:
        return all(isinstance(s, CubicSeg) for s in self.segments)


@dataclass(slots=True)
class ClipState:
    geometry: Polygon | MultiPolygon
    bounds: tuple[float, float, float, float]
    is_rectangle: bool


class PageTransform:
    """Unrotated PDF coordinates -> upright DXF coordinates."""

    def __init__(self, page: fitz.Page, config: KernelConfig):
        self.page = page
        self.config = config
        self.scale = 25.4 / 72.0 if config.units == "paper_mm" else 1.0
        if config.apply_page_rotation:
            self.matrix = page.rotation_matrix
            self.display_width = float(page.rect.width)
            self.display_height = float(page.rect.height)
        else:
            self.matrix = fitz.Matrix(1, 0, 0, 1, 0, 0)
            self.display_width = float(page.cropbox.width)
            self.display_height = float(page.cropbox.height)

    def point(self, p: Sequence[float]) -> tuple[float, float]:
        q = fitz.Point(float(p[0]), float(p[1])) * self.matrix
        return float(q.x) * self.scale, (self.display_height - float(q.y)) * self.scale

    def points(self, pts: Iterable[Sequence[float]]) -> list[tuple[float, float]]:
        return [self.point(p) for p in pts]

    def angle_from_pdf_vector(self, v: Sequence[float]) -> float:
        p0 = self.point((0.0, 0.0))
        p1 = self.point((float(v[0]), float(v[1])))
        return math.degrees(math.atan2(p1[1] - p0[1], p1[0] - p0[0])) % 360.0

    @property
    def width(self) -> float:
        return self.display_width * self.scale

    @property
    def height(self) -> float:
        return self.display_height * self.scale


class LayerManager:
    def __init__(self, doc: ezdxf.document.Drawing, config: KernelConfig):
        self.doc = doc
        self.config = config
        self.mapping: dict[str, str] = {}

    def sanitize(self, name: str | None, fallback: str = "PDF") -> str:
        raw = (name or fallback).strip() or fallback
        if raw in self.mapping:
            return self.mapping[raw]
        value = INVALID_DXF_LAYER.sub("_", raw).replace("\n", "_").replace("\r", "_")
        value = re.sub(r"\s+", " ", value).strip()
        if len(value) > self.config.max_layer_name:
            digest = hashlib.blake2b(raw.encode("utf-8"), digest_size=4).hexdigest()
            value = value[: self.config.max_layer_name - 9] + "_" + digest
        existing = set(self.mapping.values())
        if value in existing:
            digest = hashlib.blake2b(raw.encode("utf-8"), digest_size=4).hexdigest()
            value = value[: self.config.max_layer_name - 9] + "_" + digest
        self.mapping[raw] = value
        if value not in self.doc.layers:
            self.doc.layers.add(name=value)
        return value

    def off(self, name: str) -> None:
        try:
            self.doc.layers.get(name).off()
        except Exception:
            pass

    def style_layer(self, drawing: dict[str, Any], kind: str) -> str:
        if self.config.preserve_layers and drawing.get("layer"):
            return self.sanitize(str(drawing["layer"]), f"PDF_{kind}")
        if not self.config.use_style_layers_when_missing:
            return self.sanitize(f"PDF_{kind}")
        color = drawing.get("color") if kind == "STROKE" else drawing.get("fill")
        rgb = color_to_rgb(color)
        ctext = "NONE" if rgb is None else "".join(f"{c:02X}" for c in rgb)
        if kind == "STROKE":
            width = float(drawing.get("width", 0.0) or 0.0)
            raw = f"PDF_STROKE_{ctext}_W{int(round(width * 1000)):04d}"
        else:
            raw = f"PDF_FILL_{ctext}"
        return self.sanitize(raw, f"PDF_{kind}")


class LinetypeManager:
    def __init__(self, doc: ezdxf.document.Drawing, scale: float):
        self.doc = doc
        self.scale = scale
        self.cache: dict[str, str] = {}

    def get(self, dash_spec: str | None) -> str | None:
        if not dash_spec or dash_spec.strip() in ("[] 0", "[]0"):
            return None
        if dash_spec in self.cache:
            return self.cache[dash_spec]
        m = re.search(r"\[([^]]*)\]", dash_spec)
        if not m:
            return None
        try:
            vals = [float(x) * self.scale for x in m.group(1).replace(",", " ").split()]
        except ValueError:
            return None
        if not vals or sum(abs(x) for x in vals) <= 1e-9:
            return None
        pattern: list[float] = [sum(abs(x) for x in vals)]
        for i, v in enumerate(vals):
            pattern.append(abs(v) if i % 2 == 0 else -abs(v))
        digest = (
            hashlib.blake2b(dash_spec.encode("utf-8"), digest_size=4)
            .hexdigest()
            .upper()
        )
        name = f"PDF_DASH_{digest}"
        try:
            if name not in self.doc.linetypes:
                self.doc.linetypes.add(name, pattern=pattern, description=dash_spec)
            self.cache[dash_spec] = name
            return name
        except Exception:
            return None


def color_to_rgb(value: Any) -> tuple[int, int, int] | None:
    if value is None:
        return None
    try:
        a = list(value)
        if len(a) == 1:
            g = int(round(max(0.0, min(1.0, float(a[0]))) * 255))
            return g, g, g
        if len(a) >= 3:
            return tuple(int(round(max(0.0, min(1.0, float(x))) * 255)) for x in a[:3])  # type: ignore[return-value]
    except Exception:
        return None
    return None


def dist(a: Sequence[float], b: Sequence[float]) -> float:
    return math.hypot(float(a[0]) - float(b[0]), float(a[1]) - float(b[1]))


def points_close(a: Sequence[float], b: Sequence[float], eps: float = 1e-3) -> bool:
    return dist(a, b) <= eps


def cubic_point(seg: CubicSeg, t: float) -> tuple[float, float]:
    mt = 1.0 - t
    p0 = np.asarray(seg.p0, dtype=float)
    c1 = np.asarray(seg.c1, dtype=float)
    c2 = np.asarray(seg.c2, dtype=float)
    p1 = np.asarray(seg.p1, dtype=float)
    q = mt**3 * p0 + 3 * mt**2 * t * c1 + 3 * mt * t**2 * c2 + t**3 * p1
    return float(q[0]), float(q[1])


def cubic_flatness(seg: CubicSeg) -> float:
    p0 = np.asarray(seg.p0, dtype=float)
    p1 = np.asarray(seg.p1, dtype=float)
    v = p1 - p0
    n = np.linalg.norm(v)
    if n <= 1e-12:
        return max(
            np.linalg.norm(np.asarray(seg.c1) - p0),
            np.linalg.norm(np.asarray(seg.c2) - p0),
        )
    # NumPy 2.5 removed two-component input to cross(). The scalar 2D
    # determinant is the same signed area and does not depend on that API.
    c1, c2 = np.asarray(seg.c1) - p0, np.asarray(seg.c2) - p0
    return max(
        abs((v[0] * c1[1] - v[1] * c1[0]) / n),
        abs((v[0] * c2[1] - v[1] * c2[0]) / n),
    )


def flatten_cubic(
    seg: CubicSeg, tolerance: float, max_samples: int = 96
) -> list[tuple[float, float]]:
    flat = cubic_flatness(seg)
    n = int(
        max(
            4,
            min(
                max_samples,
                math.ceil(2.0 + math.sqrt(max(flat, 0.0) / max(tolerance, 1e-4)) * 5.0),
            ),
        )
    )
    return [cubic_point(seg, i / (n - 1)) for i in range(n)]


def flatten_chain(
    chain: PathChain, tolerance: float, max_samples: int = 96
) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for seg in chain.segments:
        pts = (
            [seg.p0, seg.p1]
            if isinstance(seg, LineSeg)
            else flatten_cubic(seg, tolerance, max_samples)
        )
        if out and points_close(out[-1], pts[0], 1e-6):
            out.extend(pts[1:])
        else:
            out.extend(pts)
    if chain.closed and out and not points_close(out[0], out[-1], 1e-6):
        out.append(out[0])
    return out


def parse_drawing_chains(
    drawing: dict[str, Any], stats: KernelStats | None = None
) -> list[PathChain]:
    chains: list[PathChain] = []
    current: list[Segment] = []

    def flush(closed: bool = False) -> None:
        nonlocal current
        if current:
            chains.append(PathChain(current, closed=closed))
        current = []

    for item in drawing.get("items", []):
        try:
            kind = item[0]
            if kind == "l":
                p0 = (float(item[1][0]), float(item[1][1]))
                p1 = (float(item[2][0]), float(item[2][1]))
                if current and not points_close(current[-1].p1, p0):
                    flush(False)
                current.append(LineSeg(p0, p1))
            elif kind == "c":
                p0 = (float(item[1][0]), float(item[1][1]))
                c1 = (float(item[2][0]), float(item[2][1]))
                c2 = (float(item[3][0]), float(item[3][1]))
                p1 = (float(item[4][0]), float(item[4][1]))
                if current and not points_close(current[-1].p1, p0):
                    flush(False)
                current.append(CubicSeg(p0, c1, c2, p1))
            elif kind == "re":
                flush(False)
                r = item[1]
                x0, y0, x1, y1 = map(float, (r[0], r[1], r[2], r[3]))
                pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
                segs = [LineSeg(pts[i], pts[(i + 1) % 4]) for i in range(4)]
                chains.append(PathChain(segs, closed=True))
            elif kind == "qu":
                flush(False)
                q = item[1]
                raw = [(float(p[0]), float(p[1])) for p in q]
                if len(raw) == 4:
                    pts = [raw[0], raw[1], raw[3], raw[2]]
                    segs = [LineSeg(pts[i], pts[(i + 1) % 4]) for i in range(4)]
                    chains.append(PathChain(segs, closed=True))
            else:
                if stats is not None:
                    stats.warnings.append(f"unsupported drawing item: {kind}")
        except Exception:
            if stats is not None:
                stats.malformed_paths += 1
    flush(bool(drawing.get("closePath", False)))
    # A fill implicitly closes all subpaths.
    if "f" in str(drawing.get("type", "")):
        for chain in chains:
            chain.closed = True
    if stats is not None:
        stats.source_subpaths += len(chains)
    return chains


def signed_ring_area(coords: Sequence[Sequence[float]]) -> float:
    if len(coords) < 3:
        return 0.0
    return 0.5 * sum(
        float(coords[i][0]) * float(coords[(i + 1) % len(coords)][1])
        - float(coords[(i + 1) % len(coords)][0]) * float(coords[i][1])
        for i in range(len(coords))
    )


def rings_to_fill_geometry(
    rings: list[list[tuple[float, float]]],
    even_odd: bool,
    stats: KernelStats | None = None,
):
    polygons: list[tuple[Polygon, float]] = []
    for ring in rings:
        if len(ring) < 4:
            continue
        if not points_close(ring[0], ring[-1], 1e-6):
            ring = list(ring) + [ring[0]]
        try:
            p = Polygon(ring)
            if not p.is_valid:
                p = make_valid(p)
                if stats is not None:
                    stats.invalid_geometries_repaired += 1
            if isinstance(p, Polygon) and not p.is_empty and p.area > 1e-10:
                polygons.append((p, signed_ring_area(ring)))
            elif isinstance(p, MultiPolygon):
                polygons.extend(
                    (g, signed_ring_area(list(g.exterior.coords)))
                    for g in p.geoms
                    if g.area > 1e-10
                )
            elif isinstance(p, GeometryCollection):
                # A retraced spike may repair to polygons plus zero-area lines.
                # Keep every polygon; a mixed collection is not an empty fill.
                # Repair may reverse GEOS ring orientation, so retain the source
                # ring's sign for the existing non-zero winding classification.
                source_area = signed_ring_area(ring)
                polygons.extend(
                    (g, source_area)
                    for g in geometry_parts(p)
                    if isinstance(g, Polygon) and g.area > 1e-10
                )
        except Exception:
            if stats is not None:
                stats.malformed_paths += 1
    if not polygons:
        return GeometryCollection()
    if even_odd:
        geom = GeometryCollection()
        for p, _ in sorted(polygons, key=lambda z: z[0].area, reverse=True):
            geom = p if geom.is_empty else geom.symmetric_difference(p)
        return make_valid(geom)
    # Non-zero winding approximation: use the largest ring orientation as the
    # exterior orientation and subtract rings of the opposite orientation.
    largest = max(polygons, key=lambda z: z[0].area)
    outer_sign = 1.0 if largest[1] >= 0 else -1.0
    positive = [p for p, a in polygons if (1.0 if a >= 0 else -1.0) == outer_sign]
    negative = [p for p, a in polygons if (1.0 if a >= 0 else -1.0) != outer_sign]
    geom = unary_union(positive)
    if negative:
        geom = geom.difference(unary_union(negative))
    return make_valid(geom)


def drawing_fill_geometry(
    drawing: dict[str, Any], config: KernelConfig, stats: KernelStats | None = None
):
    chains = parse_drawing_chains(drawing, None)
    rings = [
        flatten_chain(c, config.curve_flatten_tolerance_pt, config.max_curve_samples)
        for c in chains
        if c.closed
    ]
    return rings_to_fill_geometry(rings, bool(drawing.get("even_odd", False)), stats)


def clip_state_from_record(
    record: dict[str, Any], config: KernelConfig, stats: KernelStats
) -> ClipState | None:
    # Clip paths are closed by PDF semantics even when PyMuPDF reports
    # closePath=False (common for circles represented by four cubics).
    clip_record = dict(record)
    clip_record["type"] = "f"
    clip_record["closePath"] = True
    geom = drawing_fill_geometry(clip_record, config, stats)
    scissor = record.get("scissor")
    if (geom is None or geom.is_empty) and scissor:
        geom = box(*map(float, scissor))
    elif scissor:
        try:
            geom = geom.intersection(box(*map(float, scissor)))
        except Exception:
            pass
    if geom is None or geom.is_empty:
        return None
    if not isinstance(geom, (Polygon, MultiPolygon)):
        geom = make_valid(geom)
        if not isinstance(geom, (Polygon, MultiPolygon)):
            return None
    b = tuple(map(float, geom.bounds))
    rect = box(*b)
    is_rect = abs(float(geom.area) - float(rect.area)) <= max(
        1e-6, float(rect.area) * 1e-8
    )
    return ClipState(geom, b, is_rect)


def fit_circle(points: np.ndarray) -> tuple[float, float, float, float] | None:
    if len(points) < 3:
        return None
    x = points[:, 0]
    y = points[:, 1]
    A = np.column_stack([2 * x, 2 * y, np.ones_like(x)])
    b = x * x + y * y
    try:
        sol, *_ = np.linalg.lstsq(A, b, rcond=None)
    except np.linalg.LinAlgError:
        return None
    cx, cy, c = map(float, sol)
    r2 = c + cx * cx + cy * cy
    if r2 <= 0:
        return None
    r = math.sqrt(r2)
    radial = np.hypot(x - cx, y - cy)
    rel = float(np.sqrt(np.mean((radial - r) ** 2)) / max(r, 1e-9))
    return cx, cy, r, rel


def fit_ellipse(
    points: np.ndarray,
) -> tuple[float, float, float, float, float, float] | None:
    if len(points) < 8:
        return None
    try:
        (cx, cy), (w, h), angle = cv2.fitEllipse(
            points.astype(np.float32).reshape(-1, 1, 2)
        )
    except Exception:
        return None
    if w <= 1e-8 or h <= 1e-8:
        return None
    if w >= h:
        major, minor, theta = w * 0.5, h * 0.5, math.radians(angle)
    else:
        major, minor, theta = h * 0.5, w * 0.5, math.radians(angle + 90.0)
    ct, st = math.cos(theta), math.sin(theta)
    qx = (points[:, 0] - cx) * ct + (points[:, 1] - cy) * st
    qy = -(points[:, 0] - cx) * st + (points[:, 1] - cy) * ct
    rho = np.sqrt((qx / major) ** 2 + (qy / minor) ** 2)
    rel = float(np.sqrt(np.mean((rho - 1.0) ** 2)))
    return float(cx), float(cy), float(major), float(minor), float(theta), rel


def is_full_closed_sample(points: np.ndarray) -> bool:
    if len(points) < 8:
        return False
    return np.linalg.norm(points[0] - points[-1]) <= max(
        1e-6, np.ptp(points[:, 0]) * 1e-4, np.ptp(points[:, 1]) * 1e-4
    )


def unwrap_angles(values: np.ndarray) -> np.ndarray:
    return np.unwrap(values)


def geometry_parts(geom: Any) -> Iterator[Any]:
    if geom is None or geom.is_empty:
        return
    if isinstance(geom, (Polygon, LineString)):
        yield geom
    elif isinstance(geom, (MultiPolygon, MultiLineString, GeometryCollection)):
        for g in geom.geoms:
            yield from geometry_parts(g)


class GenericGraphicsKernelV14:
    def __init__(self, config: KernelConfig | None = None):
        self.config = config or KernelConfig()

    def _entity_attrs(
        self,
        layer: str,
        drawing: dict[str, Any],
        ltypes: LinetypeManager,
        stroke: bool = True,
    ) -> dict[str, Any]:
        attrs: dict[str, Any] = {"layer": layer}
        if stroke:
            lt = ltypes.get(drawing.get("dashes"))
            if lt:
                attrs["linetype"] = lt
            width_pt = float(drawing.get("width", 0.0) or 0.0)
            lw = int(max(0, min(211, round(width_pt * 25.4 / 72.0 * 100.0))))
            if lw > 0:
                attrs["lineweight"] = lw
        return attrs

    def _decorate(
        self,
        entity: Any,
        drawing: dict[str, Any],
        page_index: int,
        seqno: int,
        method: str,
        opacity: float | None = None,
    ) -> None:
        if drawing.get("_v14_outline_original"):
            method = "outline_text_original:" + method
        rgb = color_to_rgb(
            drawing.get("color")
            if not method.endswith("hatch")
            else drawing.get("fill")
        )
        if rgb is not None:
            try:
                entity.rgb = rgb
            except Exception:
                pass
        if opacity is not None and opacity < 0.999:
            try:
                entity.transparency = max(0.0, min(1.0, 1.0 - float(opacity)))
            except Exception:
                pass
        if self.config.add_xdata:
            try:
                entity.set_xdata(
                    self.config.appid,
                    [
                        (1000, method),
                        (1070, int(page_index)),
                        (1070, int(seqno)),
                        (1000, str(drawing.get("type", ""))),
                    ],
                )
            except Exception:
                pass

    def _emit_line_string(
        self,
        msp: Any,
        coords: Sequence[Sequence[float]],
        attrs: dict[str, Any],
        drawing: dict[str, Any],
        stats: KernelStats,
        page_index: int,
        seqno: int,
        method: str,
        closed: bool = False,
    ) -> int:
        pts = [(float(p[0]), float(p[1])) for p in coords]
        if len(pts) < 2:
            return 0
        if closed and points_close(pts[0], pts[-1], 1e-8):
            pts = pts[:-1]
        length = sum(dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))
        if length <= self.config.min_entity_length_pt * (
            25.4 / 72.0 if self.config.units == "paper_mm" else 1.0
        ):
            stats.zero_length_entities_skipped += 1
            return 0
        if len(pts) == 2 and not closed:
            e = msp.add_line(pts[0], pts[1], dxfattribs=attrs)
            stats.line_entities += 1
        else:
            e = msp.add_lwpolyline(pts, close=closed, dxfattribs=attrs)
            stats.polyline_entities += 1
        self._decorate(
            e,
            drawing,
            page_index,
            seqno,
            method,
            float(drawing.get("stroke_opacity", 1.0) or 1.0),
        )
        return 1

    def _emit_hatch_polygon(
        self,
        msp: Any,
        poly: Polygon,
        layer: str,
        drawing: dict[str, Any],
        stats: KernelStats,
        page_index: int,
        seqno: int,
    ) -> int:
        if poly.area <= self.config.min_fill_area_pt2 * (
            (25.4 / 72.0) ** 2 if self.config.units == "paper_mm" else 1.0
        ):
            return 0
        h = msp.add_hatch(dxfattribs={"layer": layer})
        try:
            h.set_solid_fill(color=7, style=1)
        except Exception:
            pass
        ext = [(float(x), float(y)) for x, y in poly.exterior.coords]
        h.paths.add_polyline_path(ext, is_closed=True, flags=1)
        for ring in poly.interiors:
            h.paths.add_polyline_path(
                [(float(x), float(y)) for x, y in ring.coords], is_closed=True, flags=16
            )
            stats.hatch_holes += 1
        self._decorate(
            h,
            drawing,
            page_index,
            seqno,
            "hatch",
            float(drawing.get("fill_opacity", 1.0) or 1.0),
        )
        stats.hatch_entities += 1
        if self.config.emit_fill_boundary:
            battrs = {"layer": layer}
            self._emit_line_string(
                msp,
                ext,
                battrs,
                drawing,
                stats,
                page_index,
                seqno,
                "fill_boundary",
                closed=True,
            )
            for ring in poly.interiors:
                self._emit_line_string(
                    msp,
                    list(ring.coords),
                    battrs,
                    drawing,
                    stats,
                    page_index,
                    seqno,
                    "fill_hole_boundary",
                    closed=True,
                )
        return 1

    def _emit_closed_curve_primitive(
        self,
        msp: Any,
        chain: PathChain,
        transform: PageTransform,
        layer: str,
        attrs: dict[str, Any],
        drawing: dict[str, Any],
        stats: KernelStats,
        page_index: int,
        seqno: int,
    ) -> bool:
        if not chain.closed or not any(isinstance(s, CubicSeg) for s in chain.segments):
            return False
        sample_pdf = flatten_chain(
            chain, self.config.curve_flatten_tolerance_pt, self.config.max_curve_samples
        )
        sample = np.asarray(transform.points(sample_pdf), dtype=float)
        if len(sample) < 8 or not is_full_closed_sample(sample):
            return False
        span = max(float(np.ptp(sample[:, 0])), float(np.ptp(sample[:, 1])), 1e-9)
        if self.config.detect_circles:
            fit = fit_circle(sample[:-1])
            if fit is not None:
                cx, cy, radius, rel = fit
                if rel <= self.config.primitive_fit_rel_tol and radius > 1e-8:
                    e = msp.add_circle((cx, cy), radius, dxfattribs=attrs)
                    self._decorate(
                        e,
                        drawing,
                        page_index,
                        seqno,
                        "circle",
                        float(drawing.get("stroke_opacity", 1.0) or 1.0),
                    )
                    stats.circle_entities += 1
                    return True
        if self.config.detect_ellipses:
            fit_e = fit_ellipse(sample[:-1])
            if fit_e is not None:
                cx, cy, major, minor, theta, rel = fit_e
                if (
                    rel <= self.config.ellipse_fit_rel_tol
                    and major > 1e-8
                    and minor / major >= 1e-4
                ):
                    axis = (major * math.cos(theta), major * math.sin(theta))
                    e = msp.add_ellipse(
                        (cx, cy), major_axis=axis, ratio=minor / major, dxfattribs=attrs
                    )
                    self._decorate(
                        e,
                        drawing,
                        page_index,
                        seqno,
                        "ellipse",
                        float(drawing.get("stroke_opacity", 1.0) or 1.0),
                    )
                    stats.ellipse_entities += 1
                    return True
        return False

    def _emit_open_ellipse_arc_if_possible(
        self,
        msp: Any,
        chain: PathChain,
        transform: PageTransform,
        attrs: dict[str, Any],
        drawing: dict[str, Any],
        stats: KernelStats,
        page_index: int,
        seqno: int,
    ) -> bool:
        if chain.closed or not chain.all_cubics or not self.config.detect_ellipses:
            return False
        sample = np.asarray(
            transform.points(
                flatten_chain(
                    chain,
                    self.config.curve_flatten_tolerance_pt,
                    self.config.max_curve_samples,
                )
            ),
            dtype=float,
        )
        if len(sample) < 8:
            return False
        fit = fit_ellipse(sample)
        if fit is None:
            return False
        cx, cy, major, minor, theta, rel = fit
        if (
            rel > self.config.ellipse_fit_rel_tol
            or major <= 1e-8
            or minor / major < 1e-4
        ):
            return False
        ct, st = math.cos(theta), math.sin(theta)
        qx = (sample[:, 0] - cx) * ct + (sample[:, 1] - cy) * st
        qy = -(sample[:, 0] - cx) * st + (sample[:, 1] - cy) * ct
        params = np.unwrap(np.arctan2(qy / minor, qx / major))
        delta = float(params[-1] - params[0])
        if abs(delta) < math.radians(2.0) or abs(delta) > TAU * 0.995:
            return False
        if delta > 0:
            start, end = float(params[0]), float(params[-1])
        else:
            start, end = float(params[-1]), float(params[0])
        while end <= start:
            end += TAU
        axis = (major * math.cos(theta), major * math.sin(theta))
        try:
            e = msp.add_ellipse(
                (cx, cy),
                major_axis=axis,
                ratio=minor / major,
                start_param=start,
                end_param=end,
                dxfattribs=attrs,
            )
        except Exception:
            return False
        self._decorate(
            e,
            drawing,
            page_index,
            seqno,
            "ellipse_arc",
            float(drawing.get("stroke_opacity", 1.0) or 1.0),
        )
        stats.elliptical_arc_entities += 1
        return True

    def _emit_open_arc_if_possible(
        self,
        msp: Any,
        chain: PathChain,
        transform: PageTransform,
        attrs: dict[str, Any],
        drawing: dict[str, Any],
        stats: KernelStats,
        page_index: int,
        seqno: int,
    ) -> bool:
        if chain.closed or not chain.all_cubics or not self.config.detect_arcs:
            return False
        sample = np.asarray(
            transform.points(
                flatten_chain(
                    chain,
                    self.config.curve_flatten_tolerance_pt,
                    self.config.max_curve_samples,
                )
            ),
            dtype=float,
        )
        if len(sample) < 6:
            return False
        fit = fit_circle(sample)
        if fit is None:
            return False
        cx, cy, r, rel = fit
        if rel > self.config.primitive_fit_rel_tol or r <= 1e-8:
            return False
        ang = unwrap_angles(np.arctan2(sample[:, 1] - cy, sample[:, 0] - cx))
        delta = float(ang[-1] - ang[0])
        if abs(delta) < math.radians(2.0) or abs(delta) > TAU * 0.995:
            return False
        if delta > 0:
            start, end = math.degrees(ang[0]) % 360.0, math.degrees(ang[-1]) % 360.0
        else:
            start, end = math.degrees(ang[-1]) % 360.0, math.degrees(ang[0]) % 360.0
        e = msp.add_arc((cx, cy), r, start, end, dxfattribs=attrs)
        self._decorate(
            e,
            drawing,
            page_index,
            seqno,
            "arc",
            float(drawing.get("stroke_opacity", 1.0) or 1.0),
        )
        stats.arc_entities += 1
        return True

    def _emit_native_chain(
        self,
        msp: Any,
        chain: PathChain,
        transform: PageTransform,
        attrs: dict[str, Any],
        drawing: dict[str, Any],
        stats: KernelStats,
        page_index: int,
        seqno: int,
    ) -> int:
        if not chain.segments:
            return 0
        if self._emit_closed_curve_primitive(
            msp,
            chain,
            transform,
            attrs.get("layer", "0"),
            attrs,
            drawing,
            stats,
            page_index,
            seqno,
        ):
            return 1
        if self._emit_open_ellipse_arc_if_possible(
            msp, chain, transform, attrs, drawing, stats, page_index, seqno
        ):
            return 1
        if self._emit_open_arc_if_possible(
            msp, chain, transform, attrs, drawing, stats, page_index, seqno
        ):
            return 1
        if chain.all_lines:
            pts = [chain.segments[0].p0] + [s.p1 for s in chain.segments]
            return self._emit_line_string(
                msp,
                transform.points(pts),
                attrs,
                drawing,
                stats,
                page_index,
                seqno,
                "line_or_polyline",
                closed=chain.closed,
            )
        count = 0
        # Mixed line / cubic path: preserve each exact cubic as a degree-3 SPLINE and
        # aggregate adjacent line segments as polylines.
        line_run: list[tuple[float, float]] = []

        def flush_lines() -> None:
            nonlocal count, line_run
            if len(line_run) >= 2:
                count += self._emit_line_string(
                    msp,
                    transform.points(line_run),
                    attrs,
                    drawing,
                    stats,
                    page_index,
                    seqno,
                    "mixed_path_line",
                    closed=False,
                )
            line_run = []

        for seg in chain.segments:
            if isinstance(seg, LineSeg):
                if not line_run:
                    line_run = [seg.p0, seg.p1]
                elif points_close(line_run[-1], seg.p0):
                    line_run.append(seg.p1)
                else:
                    flush_lines()
                    line_run = [seg.p0, seg.p1]
            else:
                flush_lines()
                cps = transform.points([seg.p0, seg.c1, seg.c2, seg.p1])
                if self.config.emit_splines:
                    try:
                        e = msp.add_open_spline(
                            cps,
                            degree=3,
                            knots=[0, 0, 0, 0, 1, 1, 1, 1],
                            dxfattribs=attrs,
                        )
                        self._decorate(
                            e,
                            drawing,
                            page_index,
                            seqno,
                            "cubic_spline",
                            float(drawing.get("stroke_opacity", 1.0) or 1.0),
                        )
                        stats.spline_entities += 1
                        count += 1
                    except Exception:
                        pts = transform.points(
                            flatten_cubic(
                                seg,
                                self.config.curve_flatten_tolerance_pt,
                                self.config.max_curve_samples,
                            )
                        )
                        count += self._emit_line_string(
                            msp,
                            pts,
                            attrs,
                            drawing,
                            stats,
                            page_index,
                            seqno,
                            "cubic_fallback_polyline",
                        )
                else:
                    pts = transform.points(
                        flatten_cubic(
                            seg,
                            self.config.curve_flatten_tolerance_pt,
                            self.config.max_curve_samples,
                        )
                    )
                    count += self._emit_line_string(
                        msp,
                        pts,
                        attrs,
                        drawing,
                        stats,
                        page_index,
                        seqno,
                        "cubic_polyline",
                    )
        flush_lines()
        if (
            chain.closed
            and count
            and isinstance(chain.segments[-1], LineSeg)
            and not points_close(chain.end, chain.start)
        ):
            count += self._emit_line_string(
                msp,
                transform.points([chain.end, chain.start]),
                attrs,
                drawing,
                stats,
                page_index,
                seqno,
                "close_segment",
            )
        return count

    def _effective_clip(
        self,
        active: dict[int, ClipState],
        drawing_level: int,
        cache: dict[tuple[int, tuple[tuple[int, int], ...]], ClipState | None],
        version_map: dict[int, int],
    ) -> ClipState | None:
        levels = sorted(k for k in active if k < drawing_level)
        if not levels:
            return None
        key = (drawing_level, tuple((k, version_map.get(k, 0)) for k in levels))
        if key in cache:
            return cache[key]
        states = [active[k] for k in levels]
        geom = states[0].geometry
        for state in states[1:]:
            geom = geom.intersection(state.geometry)
            if geom.is_empty:
                break
        if geom.is_empty or not isinstance(geom, (Polygon, MultiPolygon)):
            cache[key] = None
            return None
        b = tuple(map(float, geom.bounds))
        rect = box(*b)
        result = ClipState(
            geom,
            b,
            abs(float(geom.area) - float(rect.area))
            <= max(1e-6, float(rect.area) * 1e-8),
        )
        cache[key] = result
        return result

    def _record_inside_rect_clip(
        self, drawing: dict[str, Any], clip: ClipState
    ) -> bool:
        r = drawing.get("rect")
        if not r:
            return False
        x0, y0, x1, y1 = map(float, r)
        a0, b0, a1, b1 = clip.bounds
        return (
            x0 >= a0 - 1e-6 and y0 >= b0 - 1e-6 and x1 <= a1 + 1e-6 and y1 <= b1 + 1e-6
        )

    def _emit_clipped_stroke(
        self,
        msp: Any,
        chains: list[PathChain],
        clip: ClipState,
        transform: PageTransform,
        attrs: dict[str, Any],
        drawing: dict[str, Any],
        stats: KernelStats,
        page_index: int,
        seqno: int,
    ) -> int:
        count = 0
        for chain in chains:
            pts = flatten_chain(
                chain,
                self.config.curve_flatten_tolerance_pt,
                self.config.max_curve_samples,
            )
            if len(pts) < 2:
                continue
            try:
                ls = LineString(pts)
                inter = ls.intersection(clip.geometry)
            except Exception:
                continue
            for part in geometry_parts(inter):
                if isinstance(part, LineString):
                    coords = transform.points(part.coords)
                    count += self._emit_line_string(
                        msp,
                        coords,
                        attrs,
                        drawing,
                        stats,
                        page_index,
                        seqno,
                        "clipped_polyline",
                        closed=False,
                    )
                    if count:
                        stats.clipped_fallback_polylines += 1
        return count

    def _emit_fill(
        self,
        msp: Any,
        drawing: dict[str, Any],
        clip: ClipState | None,
        transform: PageTransform,
        layer: str,
        stats: KernelStats,
        page_index: int,
        seqno: int,
    ) -> int:
        geom = drawing_fill_geometry(drawing, self.config, stats)
        if geom is None or geom.is_empty:
            return 0
        if clip is not None:
            try:
                geom = geom.intersection(clip.geometry)
            except Exception:
                return 0
            if geom.is_empty:
                stats.clip_rejected_records += 1
                return 0
        # Transform polygon rings pointwise.  The page transform is affine, so this
        # preserves topology and ring nesting.
        count = 0
        for part in geometry_parts(geom):
            if not isinstance(part, Polygon):
                continue
            ext = transform.points(part.exterior.coords)
            holes = [transform.points(r.coords) for r in part.interiors]
            try:
                poly = Polygon(ext, holes)
                if not poly.is_valid:
                    poly = make_valid(poly)
                    stats.invalid_geometries_repaired += 1
                for p in geometry_parts(poly):
                    if isinstance(p, Polygon):
                        count += self._emit_hatch_polygon(
                            msp, p, layer, drawing, stats, page_index, seqno
                        )
            except Exception:
                stats.malformed_paths += 1
        return count

    def _add_text_runs(
        self,
        page: fitz.Page,
        doc: ezdxf.document.Drawing,
        msp: Any,
        transform: PageTransform,
        layers: LayerManager,
        stats: KernelStats,
        page_index: int,
        runs: list[TextRunObservation],
        matches: dict[int, Any],
    ) -> None:
        if not self.config.include_native_text:
            return

        style_cache: dict[tuple[str, str], str] = {}

        def style_for(font: str, category: str, char: str) -> str:
            key = (font, category)
            if key in style_cache:
                return style_cache[key]
            clean = re.sub(r"[^A-Za-z0-9_]", "_", font)[:55] or "PDF"
            style_name = layers.sanitize(
                f"STYLE_{category}_{clean}", self.config.native_text_style
            )
            # DXF styles reference font file names; no font bytes are distributed.
            fallback_font = (
                self.config.cjk_font
                if any(ord(c) > 255 for c in char)
                else self.config.latin_font
            )
            try:
                if style_name not in doc.styles:
                    doc.styles.add(style_name, font=fallback_font)
            except Exception:
                pass
            style_cache[key] = style_name
            return style_name

        def emit_char(
            run: TextRunObservation,
            char: Any,
            *,
            layer: str,
            method: str,
            visible: bool,
            confidence: float | None,
        ) -> None:
            text = str(char.text)
            if not text or text.isspace() or text == "\ufffd":
                return
            if not visible:
                layers.off(layer)
            pos = transform.point(char.origin)
            rotation = transform.angle_from_pdf_vector(run.direction)
            factor = (
                self.config.recovered_text_height_factor
                if method.startswith("recovered")
                else self.config.native_text_height_factor
            )
            height = max(float(run.size) * transform.scale * factor, 1e-5)
            category = (
                "REC"
                if method.startswith("recovered")
                else ("HID" if not visible else "VIS")
            )
            # Per-character width factor uses the observed PDF glyph cell along the
            # text baseline. Each character keeps its original origin, so tracking
            # remains exact even when the target CAD substitutes another font.
            dx, dy = map(float, run.direction)
            n = math.hypot(dx, dy) or 1.0
            ux, uy = dx / n, dy / n
            corners = [
                (char.bbox[0], char.bbox[1]),
                (char.bbox[2], char.bbox[1]),
                (char.bbox[2], char.bbox[3]),
                (char.bbox[0], char.bbox[3]),
            ]
            proj = [x * ux + y * uy for x, y in corners]
            observed_along = max(proj) - min(proj)
            nominal_ratio = 1.0 if ord(text[0]) > 255 else 0.60
            width_factor = max(
                0.25,
                min(4.0, observed_along / max(float(run.size) * nominal_ratio, 1e-6)),
            )
            try:
                e = msp.add_text(
                    text,
                    dxfattribs={
                        "layer": layer,
                        "style": style_for(run.font, category, text),
                        "height": height,
                        "rotation": rotation,
                        "width": width_factor,
                    },
                )
                # PDF origin is the text baseline origin; LEFT is baseline-left in DXF.
                e.set_placement(pos, align=TextEntityAlignment.LEFT)
                if run.rgb is not None:
                    e.rgb = run.rgb
                if run.opacity < 0.999:
                    e.transparency = max(0.0, min(1.0, 1.0 - run.opacity))
                if self.config.add_xdata:
                    payload = [
                        (1000, method),
                        (1070, page_index),
                        (1070, int(run.seqno)),
                        (1000, run.font),
                        (1000, run.layer or ""),
                        (1000, run.source),
                    ]
                    if confidence is not None:
                        payload.append((1040, float(confidence)))
                    e.set_xdata(self.config.appid, payload)
                if method == "native_text":
                    stats.native_text_entities += 1
                elif method == "hidden_native_text":
                    stats.hidden_text_entities += 1
                elif method == "recovered_outline_text":
                    stats.recovered_text_entities += 1
                elif method == "recovered_search_text_unmatched":
                    stats.unmatched_recovered_text_entities += 1
            except Exception as exc:
                stats.warnings.append(f"text emit failed: {exc}")

        for run in runs:
            if not run.hidden:
                layer = layers.sanitize(run.layer, "PDF_NATIVE_TEXT")
                for char in run.chars:
                    emit_char(
                        run,
                        char,
                        layer=layer,
                        method="native_text",
                        visible=True,
                        confidence=None,
                    )
                continue

            match = matches.get(run.index)
            if self.config.recover_outline_text and match is not None:
                layer = layers.sanitize(
                    self.config.recovered_text_layer, self.config.recovered_text_layer
                )
                for char in run.chars:
                    emit_char(
                        run,
                        char,
                        layer=layer,
                        method="recovered_outline_text",
                        visible=True,
                        confidence=float(match.confidence),
                    )
                stats.recovered_text_runs += 1
                continue

            if (
                self.config.recover_outline_text
                and self.config.unmatched_recovered_text_visible
            ):
                layer = layers.sanitize(
                    self.config.unmatched_recovered_text_layer,
                    self.config.unmatched_recovered_text_layer,
                )
                for char in run.chars:
                    emit_char(
                        run,
                        char,
                        layer=layer,
                        method="recovered_search_text_unmatched",
                        visible=True,
                        confidence=None,
                    )
                continue

            if self.config.include_hidden_text:
                layer = layers.sanitize(
                    self.config.hidden_text_layer, self.config.hidden_text_layer
                )
                for char in run.chars:
                    emit_char(
                        run,
                        char,
                        layer=layer,
                        method="hidden_native_text",
                        visible=False,
                        confidence=None,
                    )

    def _build_media_clip_map(
        self, drawings: list[dict[str, Any]], stats: KernelStats
    ) -> dict[int, ClipState]:
        """Map bboxlog sequence numbers of immediately following media to clips.

        In common PDF streams a clip path is painted/declared immediately before
        an image or shading. PyMuPDF omits images from get_cdrawings(), but its
        drawing seqno shares the page bboxlog sequence, which lets us bind the
        next fill-image/fill-shade occurrence conservatively.
        """
        result: dict[int, ClipState] = {}
        last_seqno: int | None = None
        pending: ClipState | None = None
        for record in drawings:
            typ = str(record.get("type", ""))
            if typ == "clip":
                state = clip_state_from_record(record, self.config, stats)
                if state is not None:
                    if pending is None:
                        pending = state
                    else:
                        try:
                            geom = pending.geometry.intersection(state.geometry)
                            if not geom.is_empty and isinstance(
                                geom, (Polygon, MultiPolygon)
                            ):
                                b = tuple(map(float, geom.bounds))
                                rect = box(*b)
                                pending = ClipState(
                                    geom,
                                    b,
                                    abs(float(geom.area) - float(rect.area))
                                    <= max(1e-6, float(rect.area) * 1e-8),
                                )
                        except Exception:
                            pending = state
                    if last_seqno is not None:
                        result[last_seqno + 1] = pending
                continue
            seq = record.get("seqno")
            if seq is not None:
                last_seqno = int(seq)
                # A normal drawing after the pending clip means the next media slot
                # has passed; keep only exact next-sequence bindings.
                if pending is not None and last_seqno not in result:
                    pending = None
        return result

    def _add_images(
        self,
        pdf: fitz.Document,
        page: fitz.Page,
        doc: ezdxf.document.Drawing,
        msp: Any,
        transform: PageTransform,
        layers: LayerManager,
        stats: KernelStats,
        page_index: int,
        output_path: Path,
        media_clips: dict[int, ClipState],
    ) -> None:
        if not self.config.include_images and not self.config.include_shadings:
            return
        try:
            infos = page.get_image_info(xrefs=True, hashes=True)
        except Exception as exc:
            stats.warnings.append(f"image enumeration failed: {exc}")
            return
        if not infos:
            return

        occurrences = enumerate_media_occurrences(page, infos)
        image_dir = output_path.parent / self.config.image_subdir
        shade_dir = output_path.parent / self.config.shading_subdir
        image_dir.mkdir(parents=True, exist_ok=True)
        shade_dir.mkdir(parents=True, exist_ok=True)
        defs: dict[tuple[Any, str], Any] = {}
        extracted: dict[tuple[Any, str], tuple[Path, int, int]] = {}
        soft_masks: dict[int, int] = {}
        try:
            soft_masks = {
                int(row[0]): int(row[1])
                for row in page.get_images(full=True)
                if len(row) >= 2 and int(row[0]) > 0 and int(row[1]) > 0
            }
        except Exception as exc:
            stats.warnings.append(f"image soft mask enumeration failed: {exc}")
        mask_paints = {}
        if any(int(info.get("colorspace", -1)) == 0 for info in infos):
            try:
                rows = render_image_mask_paints(
                    page, infos, image_dir, f"p{page_index + 1:03d}"
                )
                mask_paints = {
                    index: paint
                    for index, paint in zip(
                        (
                            i
                            for i, info in enumerate(infos)
                            if int(info.get("colorspace", -1)) == 0
                        ),
                        rows,
                        strict=True,
                    )
                }
            except Exception as exc:
                stats.warnings.append(f"image mask rendering failed: {exc}")

        for index, info in enumerate(infos):
            occurrence = occurrences[index] if index < len(occurrences) else None
            kind = (
                occurrence.kind
                if occurrence is not None
                else (
                    "fill-shade" if int(info.get("xref", 0) or 0) == 0 else "fill-image"
                )
            )
            seqno = occurrence.seqno if occurrence is not None else -1
            clip = media_clips.get(seqno)
            xref = int(info.get("xref", 0) or 0)
            digest = info.get("digest") or xref or index
            mask_paint = mask_paints.get(index)
            digest_bytes = digest if isinstance(digest, bytes) else str(digest).encode()
            name_hash = hashlib.blake2b(
                digest_bytes + f"/{seqno}/{kind}".encode(), digest_size=7
            ).hexdigest()

            is_shading = kind == "fill-shade"
            if is_shading and not self.config.include_shadings:
                continue
            if not is_shading and not self.config.include_images:
                continue

            bbox = tuple(map(float, info.get("bbox", (0, 0, 0, 0))))
            if (fitz.Rect(*bbox) & page.rect).is_empty:
                stats.outside_page_media_skipped += 1
                continue
            page_area = max(float(page.cropbox.width * page.cropbox.height), 1.0)
            bbox_area = max(0.0, bbox[2] - bbox[0]) * max(0.0, bbox[3] - bbox[1])
            if (
                is_shading
                and self.config.skip_unclipped_full_page_shading
                and clip is None
                and bbox_area / page_area > 0.95
            ):
                stats.skipped_full_page_shadings += 1
                stats.warnings.append(
                    f"unclipped full-page shading skipped at bboxlog seqno {seqno}"
                )
                continue

            cache_key = (
                digest if isinstance(digest, (bytes, int)) else str(digest),
                f"{kind}:mask:{mask_paint.index}"
                if mask_paint is not None
                else (kind if xref > 0 else f"{kind}:{seqno}"),
            )
            if cache_key not in extracted:
                if mask_paint is not None:
                    img_path = mask_paint.path
                    width, height = mask_paint.width, mask_paint.height
                    extracted[cache_key] = (img_path, width, height)
                    stats.image_files += 1
                elif is_shading or xref <= 0:
                    target_dir = shade_dir if is_shading else image_dir
                    img_path = target_dir / f"p{page_index + 1:03d}_{name_hash}.png"
                    try:
                        clip_geom = clip.geometry if clip is not None else None
                        width, height = render_shading_fallback(
                            page,
                            bbox,
                            img_path,
                            clip_geometry=clip_geom,
                            scale=self.config.shading_render_scale,
                        )
                        extracted[cache_key] = (img_path, int(width), int(height))
                        if is_shading:
                            stats.shading_files += 1
                        else:
                            stats.image_files += 1
                    except Exception as exc:
                        stats.warnings.append(
                            f"raster fallback failed seqno={seqno}: {exc}"
                        )
                        continue
                else:
                    img_path = image_dir / f"p{page_index + 1:03d}_{name_hash}.png"
                    try:
                        soft_mask_xref = soft_masks.get(xref, 0)
                        if info.get("has-mask") and not soft_mask_xref:
                            soft_mask_xref = int(
                                pdf.extract_image(xref).get("smask", 0) or 0
                            )
                        pix = extract_image_pixmap(pdf, xref, soft_mask_xref)
                        pix.save(str(img_path))
                        extracted[cache_key] = (
                            img_path,
                            int(info.get("width", pix.width) or pix.width),
                            int(info.get("height", pix.height) or pix.height),
                        )
                        stats.image_files += 1
                    except Exception as exc:
                        stats.warnings.append(
                            f"image extract failed xref={xref}: {exc}"
                        )
                        continue

            img_path, width, height = extracted[cache_key]
            def_key = (cache_key, str(img_path))
            if def_key not in defs:
                rel = os.path.relpath(img_path, output_path.parent)
                defs[def_key] = doc.add_image_def(
                    filename=rel, size_in_pixel=(width, height)
                )

            matrix = info.get("transform")
            if not matrix or len(matrix) != 6:
                continue
            a, b, c, d, e0, f0 = map(float, matrix)
            p00 = transform.point((e0, f0))
            p10 = transform.point((e0 + a, f0 + b))
            p01 = transform.point((e0 + c, f0 + d))
            raw_layer = (
                occurrence.layer
                if occurrence is not None and occurrence.layer
                else ("PDF_SHADING" if is_shading else "PDF_IMAGES")
            )
            layer = layers.sanitize(
                raw_layer, "PDF_SHADING" if is_shading else "PDF_IMAGES"
            )
            try:
                entity = msp.add_image(
                    defs[def_key],
                    insert=p01,
                    size_in_units=(1, 1),
                    rotation=0.0,
                    dxfattribs={"layer": layer},
                )
                entity.dxf.insert = (p01[0], p01[1], 0.0)
                entity.dxf.u_pixel = (
                    (p10[0] - p00[0]) / max(width, 1),
                    (p10[1] - p00[1]) / max(width, 1),
                    0.0,
                )
                entity.dxf.v_pixel = (
                    (p00[0] - p01[0]) / max(height, 1),
                    (p00[1] - p01[1]) / max(height, 1),
                    0.0,
                )
                entity.dxf.image_size = (float(width), float(height), 0.0)
                if self.config.clip_images and clip is not None:
                    boundary = clip_polygon_to_image_pixels(
                        info, clip.geometry, self.config.max_image_clip_vertices
                    )
                    if boundary is not None:
                        entity.set_boundary_path(boundary)
                        stats.clipped_image_entities += 1
                        stats.image_clip_vertices += max(0, len(boundary) - 1)
                if self.config.add_xdata:
                    entity.set_xdata(
                        self.config.appid,
                        [
                            (
                                1000,
                                "shading_raster_fallback" if is_shading else "image",
                            ),
                            (1070, page_index),
                            (1070, xref),
                            (1070, seqno),
                        ],
                    )
                if is_shading:
                    stats.shading_entities += 1
                else:
                    stats.image_entities += 1
            except Exception as exc:
                stats.warnings.append(f"image placement failed xref={xref}: {exc}")

    def convert_page(
        self, pdf: fitz.Document, page_index: int, output_path: str | Path
    ) -> KernelStats:
        started = time.perf_counter()
        page = pdf[page_index]
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        stats = KernelStats(
            source_pdf=str(getattr(pdf, "name", "")),
            page_index=page_index,
            page_rotation=int(page.rotation),
            unit_mode=self.config.units,
        )
        transform = PageTransform(page, self.config)
        stats.geometry_scale = transform.scale
        doc = ezdxf.new(self.config.dxf_version, setup=True)
        doc.header["$INSUNITS"] = 4 if self.config.units == "paper_mm" else 0
        if self.config.add_xdata and self.config.appid not in doc.appids:
            doc.appids.add(self.config.appid)
        msp = doc.modelspace()
        layers = LayerManager(doc, self.config)
        ltypes = LinetypeManager(doc, transform.scale)

        if self.config.include_page_boundary:
            layer = layers.sanitize("PDF_PAGE")
            e = msp.add_lwpolyline(
                [
                    (0, 0),
                    (transform.width, 0),
                    (transform.width, transform.height),
                    (0, transform.height),
                ],
                close=True,
                dxfattribs={"layer": layer},
            )
            if self.config.add_xdata:
                e.set_xdata(
                    self.config.appid, [(1000, "page_boundary"), (1070, page_index)]
                )

        try:
            drawings = page.get_cdrawings(extended=True)
        except TypeError:
            drawings = page.get_cdrawings()
        stats.input_draw_records = len(drawings)

        # Extract text before graphics emission so invisible search text can be
        # matched to its visible outline paths. This is reversible: matched paths
        # are moved to an OFF layer by default, not deleted.
        text_diag = TextRecoveryDiagnostics()
        text_runs: list[TextRunObservation] = []
        matches: dict[int, Any] = {}
        matched_outline_indices: set[int] = set()
        if self.config.include_native_text:
            text_runs = extract_text_runs(page, text_diag)
            stats.text_runs = len(text_runs)
            stats.hidden_text_runs = text_diag.hidden_runs
            stats.hidden_search_chars = text_diag.hidden_chars
            stats.warnings.extend(text_diag.warnings)
            if self.config.recover_outline_text:
                recovery_cfg = TextRecoveryConfig(
                    recover_hidden_search_text=True,
                    unmatched_text_visible=self.config.unmatched_recovered_text_visible,
                    recovered_text_layer=self.config.recovered_text_layer,
                    unmatched_text_layer=self.config.unmatched_recovered_text_layer,
                    outline_original_layer=self.config.outline_original_layer,
                    outline_policy=self.config.outline_text_policy,
                    min_match_confidence=self.config.outline_min_match_confidence,
                )
                matches, matched_outline_indices = match_outline_records(
                    text_runs, drawings, recovery_cfg, text_diag
                )
                stats.outline_matched_runs = text_diag.matched_runs
                stats.outline_unmatched_runs = text_diag.unmatched_runs
                stats.matched_outline_records = len(matched_outline_indices)

        media_clips = (
            self._build_media_clip_map(drawings, stats)
            if self.config.clip_images
            else {}
        )
        outline_layer = ""
        if matched_outline_indices and self.config.outline_text_policy == "off_layer":
            outline_layer = layers.sanitize(
                self.config.outline_original_layer, self.config.outline_original_layer
            )
            layers.off(outline_layer)

        active_clips: dict[int, ClipState] = {}
        clip_versions: dict[int, int] = {}
        clip_cache: dict[tuple[int, tuple[tuple[int, int], ...]], ClipState | None] = {}
        version_counter = 0

        for record_index, source_record in enumerate(drawings):
            record = source_record
            is_outline = record_index in matched_outline_indices
            if is_outline:
                if self.config.outline_text_policy == "drop":
                    stats.outline_records_dropped += 1
                    continue
                if self.config.outline_text_policy == "off_layer":
                    record = dict(source_record)
                    record["_v14_outline_original"] = True
                    stats.outline_records_relayered += 1

            typ = str(record.get("type", ""))
            level = int(record.get("level", 0) or 0)
            if typ == "group":
                stats.input_group_records += 1
                continue
            if typ == "clip":
                stats.input_clip_records += 1
                for k in [k for k in active_clips if k >= level]:
                    active_clips.pop(k, None)
                    clip_versions.pop(k, None)
                state = clip_state_from_record(record, self.config, stats)
                if state is not None:
                    active_clips[level] = state
                    version_counter += 1
                    clip_versions[level] = version_counter
                    clip_cache.clear()
                continue
            if typ == "s":
                stats.input_stroke_records += 1
            elif typ == "f":
                stats.input_fill_records += 1
            elif typ == "fs":
                stats.input_fill_stroke_records += 1
            else:
                continue
            seqno = int(record.get("seqno", -1) or -1)
            clip = (
                self._effective_clip(active_clips, level, clip_cache, clip_versions)
                if self.config.clip_paths
                else None
            )
            if (
                clip is not None
                and clip.is_rectangle
                and self._record_inside_rect_clip(record, clip)
            ):
                clip = None
            elif clip is not None:
                stats.clipped_records += 1

            forced_layer = (
                outline_layer
                if is_outline and self.config.outline_text_policy == "off_layer"
                else None
            )
            if "f" in typ and self.config.emit_hatches:
                fill_layer = forced_layer or layers.style_layer(record, "FILL")
                self._emit_fill(
                    msp, record, clip, transform, fill_layer, stats, page_index, seqno
                )

            if "s" in typ and (
                typ == "s" or self.config.preserve_stroke_for_fill_stroke
            ):
                chains = parse_drawing_chains(record, stats)
                stroke_layer = forced_layer or layers.style_layer(record, "STROKE")
                attrs = self._entity_attrs(stroke_layer, record, ltypes, stroke=True)
                if clip is None:
                    for chain in chains:
                        self._emit_native_chain(
                            msp,
                            chain,
                            transform,
                            attrs,
                            record,
                            stats,
                            page_index,
                            seqno,
                        )
                else:
                    fully_inside = False
                    try:
                        r = record.get("rect")
                        if r:
                            fully_inside = clip.geometry.covers(box(*map(float, r)))
                    except Exception:
                        fully_inside = False
                    if fully_inside:
                        for chain in chains:
                            self._emit_native_chain(
                                msp,
                                chain,
                                transform,
                                attrs,
                                record,
                                stats,
                                page_index,
                                seqno,
                            )
                    else:
                        emitted = self._emit_clipped_stroke(
                            msp,
                            chains,
                            clip,
                            transform,
                            attrs,
                            record,
                            stats,
                            page_index,
                            seqno,
                        )
                        if emitted == 0:
                            stats.clip_rejected_records += 1

        self._add_text_runs(
            page, doc, msp, transform, layers, stats, page_index, text_runs, matches
        )
        self._add_images(
            pdf,
            page,
            doc,
            msp,
            transform,
            layers,
            stats,
            page_index,
            output_path,
            media_clips,
        )

        try:
            doc.header["$EXTMIN"] = (0.0, 0.0, 0.0)
            doc.header["$EXTMAX"] = (transform.width, transform.height, 0.0)
        except Exception:
            pass
        doc.saveas(output_path)
        stats.layers = len(doc.layers)
        stats.output_entities = len(msp)
        stats.output_bytes = output_path.stat().st_size
        stats.elapsed_seconds = time.perf_counter() - started
        return stats


def save_stats(path: str | Path, stats: KernelStats) -> None:
    Path(path).write_text(
        json.dumps(stats.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )


__all__ = [
    "KernelConfig",
    "KernelStats",
    "PageTransform",
    "GenericGraphicsKernelV14",
    "save_stats",
]
