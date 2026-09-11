"""Recover audited outlined text from a persisted DXF.

The matcher only reads DXF entities.  A glyph is publishable when its
translation/scale-normalized geometry and topology exactly match a catalog
template with auditable label evidence.  Unknown or ambiguous outlines remain
geometry.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
import math
import os
import re
import tempfile
from bisect import bisect_left
from collections import defaultdict
from dataclasses import dataclass, field, replace
from itertools import accumulate
from pathlib import Path
from typing import Any

import cv2
import ezdxf
import numpy as np
from ezdxf import bbox as dxf_bbox
from ezdxf.enums import TextEntityAlignment

from .contour_topology import half_enclosure_evidence, strictly_encloses_paths
from .font_catalog import (
    FONT_CATALOG_RASTER_DECIMALS,
    MAX_CONTOURS,
    FontGlyphCatalog,
    _has_font_fill,
    font_mask_digest,
    is_han_character,
    load_font_catalog,
)

CATALOG = Path(__file__).with_name("assets") / "chinese_glyph_templates.json"
CATALOG_SCHEMA = "pdf2dxf.outline_glyph_catalog.v1"
REPORT_SCHEMA = "pdf2dxf.outline_text.v3"
MASK_SIZE = 56
MIN_GLYPH_ASPECT = 0.05
MAX_GLYPH_ASPECT = 20.0
MAX_SOURCE_SEQUENCE_GAP = 4
MIN_HAN_RUN_SIZE_RATIO = 0.72
MIN_FONT_LOCK_DISTINCT_HAN = 3
MIN_FONT_LOCK_DISTINCT_LATIN = 4
MAX_OUTLINE_POINTS_PER_ATOM = 4096
RECOVERY_KEY_PRECISION = 6
MAX_RECOVERED_TEXT_GLYPHS = 96
KANGXI_RADICAL_CODEPOINTS = {
    unicodedata.normalize("NFKC", chr(codepoint)): codepoint
    for codepoint in range(0x2F00, 0x2FD6)
}
TEXT_LAYER = "PDF_TEXT_RECOVERED_NOOCR"
BACKUP_LAYER = "PDF_OUTLINE_BACKUP"
APPID = "PDF2DXF_GLYPH"
TEXT_STYLE = "PDF2DXF_CJK_VECTOR"
TEXT_FONT = "simsun.ttc"
SOURCE_APPIDS = ("PDF2DXF15", "PDF2DXF14")
SCALE_TEXT = re.compile(r"^1:(?:0*[1-9]\d*)(?:\.\d+)?$")


def _is_english_letter(char: str) -> bool:
    return len(char) == 1 and ("A" <= char <= "Z" or "a" <= char <= "z")


class GlyphCatalogUnavailable(RuntimeError):
    """Raised when the persisted-DXF glyph catalog cannot be trusted."""


@dataclass(frozen=True, slots=True)
class GeometrySignature:
    fingerprint: str
    entity_count: int
    closed_count: int
    point_counts: tuple[int, ...]
    aspect_ratio: float
    mask_hex: str


@dataclass(frozen=True, slots=True)
class GlyphTemplate:
    id: str
    char: str
    fingerprint: str
    entity_count: int
    closed_count: int
    point_counts: tuple[int, ...]
    aspect_ratio: float
    support_locations: int
    support_documents: int
    admission: str

    @property
    def structural_key(self) -> tuple[int, int, tuple[int, ...]]:
        return self.entity_count, self.closed_count, self.point_counts


@dataclass(slots=True)
class GlyphCatalog:
    path: Path
    version: str
    template_set_sha256: str
    templates: tuple[GlyphTemplate, ...]
    lookup: dict[tuple[int, int, tuple[int, ...], str], GlyphTemplate]
    structures: dict[tuple[int, int, tuple[int, ...]], tuple[GlyphTemplate, ...]]
    lengths: frozenset[int]
    characters: frozenset[str]


@dataclass(slots=True)
class OutlineAtom:
    sequence_index: int
    modelspace_index: int
    entity: Any
    paths: tuple[np.ndarray, ...]
    low: np.ndarray
    high: np.ndarray
    layer: str
    point_counts: tuple[int, ...]
    closed_count: int
    source_ref: tuple[str, int, int]


@dataclass(frozen=True, slots=True)
class GlyphMatch:
    start: int
    end: int
    char: str
    low: tuple[float, float]
    high: tuple[float, float]
    atoms: tuple[OutlineAtom, ...]
    template: GlyphTemplate
    font_catalog_ids: tuple[str, ...] = ()
    font_raster_round_decimals: int | None = None
    font_match_evidence: tuple[tuple[str, str, int], ...] = ()

    @property
    def height(self) -> float:
        return self.high[1] - self.low[1]


@dataclass(frozen=True, slots=True)
class FontCatalogLock:
    catalog: FontGlyphCatalog
    exact_anchor_occurrences: int
    exact_anchor_characters: tuple[str, ...]
    method: str
    evidence_texts: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _FontConflict:
    start: int
    end: int
    low: tuple[float, float]
    high: tuple[float, float]
    # Catalog, label, exact fingerprint, raster precision; no label is chosen.
    predictions: tuple[tuple[str, str, str, int], ...]


@dataclass(slots=True)
class _FontScanContext:
    matches: tuple[GlyphMatch, ...] = ()
    conflicts: list[_FontConflict] = field(default_factory=list)
    han_parent_spans: set[tuple[int, int]] = field(default_factory=set)


def _is_hex(value: str, size: int) -> bool:
    return len(value) == size and all(ch in "0123456789abcdef" for ch in value)


def _validate_label_evidence(
    evidence: Any, char: str, *, minimum_documents: int
) -> None:
    if not isinstance(evidence, list) or not evidence:
        raise ValueError("glyph template has no label evidence")
    source_hashes: set[str] = set()
    for item in evidence:
        if not isinstance(item, dict):
            raise TypeError("invalid glyph label evidence row")
        source_sha256 = str(item.get("source_sha256", ""))
        label = item.get("label")
        char_index = item.get("char_index")
        if (
            not _is_hex(source_sha256, 64)
            or not isinstance(label, str)
            or not isinstance(char_index, int)
            or not 0 <= char_index < len(label)
            or label[char_index] != char
        ):
            raise ValueError("glyph label evidence does not identify its character")
        source_hashes.add(source_sha256)
    if len(source_hashes) < minimum_documents:
        raise ValueError("glyph label evidence lacks independent source documents")


def _mask_digest(
    mask: np.ndarray,
    entity_count: int,
    closed_count: int,
    point_counts: tuple[int, ...],
) -> str:
    payload = (
        np.asarray(mask, dtype=np.uint8).tobytes()
        + bytes((min(entity_count, 255), min(closed_count, 255)))
        + np.asarray(point_counts, dtype="<u2").tobytes()
    )
    return hashlib.blake2b(payload, digest_size=16).hexdigest()


def fingerprint_paths(
    paths: list[np.ndarray] | tuple[np.ndarray, ...],
    *,
    raster_round_decimals: int | None = None,
) -> GeometrySignature | None:
    """Return a deterministic, translation/uniform-scale invariant signature."""
    if not paths:
        return None
    normalized_paths: list[np.ndarray] = []
    for raw in paths:
        path = np.asarray(raw, dtype=np.float64)
        if path.ndim != 2 or path.shape[1] != 2 or len(path) < 2:
            return None
        if not np.isfinite(path).all():
            return None
        normalized_paths.append(path)
    points = np.vstack(normalized_paths)
    low, high = points.min(axis=0), points.max(axis=0)
    extent = high - low
    scale = float(extent.max())
    if scale <= 1e-8 or float(extent.min()) <= 1e-8:
        return None
    offset = (
        np.array([MASK_SIZE - 1, MASK_SIZE - 1]) - extent / scale * (MASK_SIZE - 7)
    ) / 2
    mask = np.zeros((MASK_SIZE, MASK_SIZE), dtype=np.uint8)
    point_counts: list[int] = []
    closed_count = 0
    for path in normalized_paths:
        normalized = (path - low) / scale * (MASK_SIZE - 7) + offset
        if raster_round_decimals is not None:
            normalized = np.round(normalized, decimals=raster_round_decimals)
        raster = np.rint(normalized).astype(np.int32)
        cv2.polylines(mask, [raster], False, 1, 1)
        point_counts.append(len(path))
        closed_count += int(
            len(path) >= 3 and np.linalg.norm(path[0] - path[-1]) < 1e-5 * scale
        )
    counts = tuple(sorted(point_counts))
    packed = np.packbits(mask.reshape(-1), bitorder="little").tobytes().hex()
    return GeometrySignature(
        fingerprint=_mask_digest(mask, len(normalized_paths), closed_count, counts),
        entity_count=len(normalized_paths),
        closed_count=closed_count,
        point_counts=counts,
        aspect_ratio=float(extent[0] / max(extent[1], 1e-9)),
        mask_hex=packed,
    )


def _validate_template_mask(row: dict[str, Any], signature: GeometrySignature) -> None:
    packed = bytes.fromhex(signature.mask_hex)
    expected_size = math.ceil(MASK_SIZE * MASK_SIZE / 8)
    if len(packed) != expected_size:
        raise ValueError("invalid packed glyph mask size")
    mask = np.unpackbits(np.frombuffer(packed, dtype=np.uint8), bitorder="little")[
        : MASK_SIZE * MASK_SIZE
    ].reshape(MASK_SIZE, MASK_SIZE)
    digest = _mask_digest(
        mask,
        signature.entity_count,
        signature.closed_count,
        signature.point_counts,
    )
    if digest != signature.fingerprint or digest != str(row.get("fingerprint", "")):
        raise ValueError("glyph mask and fingerprint disagree")


def load_catalog(path: str | Path = CATALOG) -> GlyphCatalog:
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != CATALOG_SCHEMA:
        raise ValueError("unsupported outlined-text glyph catalog")
    if (
        data.get("runtime_input") != "persisted_dxf_only"
        or data.get("runtime_ocr") is not False
    ):
        raise ValueError("glyph catalog has an unsafe runtime contract")
    raw_templates = data.get("templates")
    if not isinstance(raw_templates, list) or not raw_templates:
        raise ValueError("outlined-text glyph catalog is empty")
    canonical = json.dumps(
        raw_templates, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    template_set_sha256 = hashlib.sha256(canonical).hexdigest()
    if data.get("template_set_sha256") != template_set_sha256:
        raise ValueError("glyph template set hash mismatch")

    templates: list[GlyphTemplate] = []
    lookup: dict[tuple[int, int, tuple[int, ...], str], GlyphTemplate] = {}
    ids: set[str] = set()
    for row in raw_templates:
        if not isinstance(row, dict):
            raise TypeError("invalid glyph template row")
        char = str(row.get("char", ""))
        template_id = str(row.get("id", ""))
        fingerprint = str(row.get("fingerprint", ""))
        point_counts = tuple(int(value) for value in row.get("point_counts", ()))
        entity_count = int(row.get("entity_count", 0))
        closed_count = int(row.get("closed_count", -1))
        aspect_ratio = float(row.get("aspect_ratio", 0))
        support_locations = int(row.get("support_locations", 0))
        support_documents = int(row.get("support_documents", 0))
        admission = str(row.get("admission", ""))
        evidence = row.get("label_evidence")
        if (
            len(char) != 1
            or not template_id
            or template_id in ids
            or not _is_hex(fingerprint, 32)
            or entity_count != len(point_counts)
            or entity_count <= 0
            or closed_count < 0
            or closed_count > entity_count
            or any(value < 2 or value > 65535 for value in point_counts)
            or not math.isfinite(aspect_ratio)
            or aspect_ratio <= 0
        ):
            raise ValueError(f"invalid glyph template: {template_id or '<missing>'}")
        if admission == "repeated_document_consensus":
            if support_locations < 2 or support_documents < 2:
                raise ValueError(
                    f"glyph lacks repeated-document support: {template_id}"
                )
            _validate_label_evidence(evidence, char, minimum_documents=2)
        elif admission == "reviewed_scale_with_independent_engineering_catalog":
            scale_labels = row.get("scale_labels") or []
            independent = row.get("independent_label_evidence") or []
            if (
                char not in "0123456789:"
                or not scale_labels
                or any(
                    SCALE_TEXT.fullmatch(str(label)) is None for label in scale_labels
                )
                or not independent
                or any(
                    not _is_hex(str(item.get("source_sha256", "")), 64)
                    for item in independent
                )
            ):
                raise ValueError(f"invalid reviewed-scale template: {template_id}")
            _validate_label_evidence(evidence, char, minimum_documents=1)
        else:
            raise ValueError(f"unsupported glyph admission method: {admission}")
        signature = GeometrySignature(
            fingerprint=fingerprint,
            entity_count=entity_count,
            closed_count=closed_count,
            point_counts=point_counts,
            aspect_ratio=aspect_ratio,
            mask_hex=str(row.get("mask_hex", "")),
        )
        _validate_template_mask(row, signature)
        template = GlyphTemplate(
            id=template_id,
            char=char,
            fingerprint=fingerprint,
            entity_count=entity_count,
            closed_count=closed_count,
            point_counts=point_counts,
            aspect_ratio=aspect_ratio,
            support_locations=support_locations,
            support_documents=support_documents,
            admission=admission,
        )
        key = (*template.structural_key, fingerprint)
        if key in lookup:
            raise ValueError("duplicate or ambiguous glyph fingerprint in catalog")
        lookup[key] = template
        templates.append(template)
        ids.add(template_id)
    structures: dict[tuple[int, int, tuple[int, ...]], list[GlyphTemplate]] = (
        defaultdict(list)
    )
    for template in templates:
        structures[template.structural_key].append(template)
    return GlyphCatalog(
        path=path,
        version=str(data.get("catalog_version", "")),
        template_set_sha256=template_set_sha256,
        templates=tuple(templates),
        lookup=lookup,
        structures={key: tuple(value) for key, value in structures.items()},
        lengths=frozenset(template.entity_count for template in templates),
        characters=frozenset(template.char for template in templates),
    )


def _entity_paths(entity: Any, *, include_fill: bool = False) -> tuple[np.ndarray, ...]:
    if entity.dxftype() == "LINE":
        return (
            np.asarray(
                [tuple(entity.dxf.start)[:2], tuple(entity.dxf.end)[:2]],
                dtype=np.float64,
            ),
        )
    if entity.dxftype() == "LWPOLYLINE" and not entity.has_arc:
        points = np.asarray(list(entity.get_points("xy")), dtype=np.float64)
        if entity.closed and len(points):
            points = np.vstack((points, points[0]))
        return (points,) if len(points) >= 2 else ()
    if include_fill and entity.dxftype() == "HATCH" and entity.dxf.solid_fill:
        if (
            tuple(entity.dxf.extrusion) != (0.0, 0.0, 1.0)
            or tuple(entity.dxf.elevation) != (0.0, 0.0, 0.0)
            or not 0 < len(entity.paths) <= MAX_CONTOURS
        ):
            return ()
        paths = []
        point_count = 0
        for boundary in entity.paths:
            # Read persisted, closed polygon boundaries only; do not alter the
            # hatch or guess unsupported curved/nonplanar boundary geometry.
            if (
                not hasattr(boundary, "vertices")
                or not boundary.is_closed
                or boundary.has_bulge()
            ):
                return ()
            point_count += len(boundary.vertices) + 1
            if point_count > MAX_OUTLINE_POINTS_PER_ATOM:
                return ()
            points = np.asarray(
                [point[:2] for point in boundary.vertices], dtype=np.float64
            )
            if len(points) < 3:
                return ()
            if not np.array_equal(points[0], points[-1]):
                points = np.vstack((points, points[0]))
            paths.append(points)
        return tuple(paths)
    return ()


def _source_ref(entity: Any, page_index: int) -> tuple[str, int, int] | None:
    for appid in SOURCE_APPIDS:
        if not entity.has_xdata(appid):
            continue
        values = [
            int(value)
            for code, value in entity.get_xdata(appid)
            if code in (1070, 1071)
        ]
        if len(values) >= 2 and values[0] == page_index:
            return appid, values[0], values[1]
    return None


def _collect_atoms(
    doc: Any, page_index: int, *, include_fills: bool = False
) -> tuple[list[OutlineAtom], dict[tuple[str, int, int], list[Any]], dict[str, int]]:
    atoms: list[OutlineAtom] = []
    source_entities: dict[tuple[str, int, int], list[Any]] = defaultdict(list)
    stats = {
        "source_mapped_entities": 0,
        "candidate_outline_entities": 0,
        "unsupported_outline_entities": 0,
        "existing_recovered_text_entities": 0,
        "candidate_fill_entities": 0,
    }
    stroke_sources = set()
    if include_fills:
        for entity in doc.modelspace():
            if entity.dxftype() in {
                "LINE",
                "LWPOLYLINE",
                "POLYLINE",
                "SPLINE",
                "ARC",
                "CIRCLE",
                "ELLIPSE",
            }:
                source_ref = _source_ref(entity, page_index)
                if source_ref is not None:
                    stroke_sources.add(source_ref)
    for modelspace_index, entity in enumerate(doc.modelspace()):
        layer = str(entity.dxf.get("layer", ""))
        if (
            entity.dxftype() == "TEXT"
            and layer == TEXT_LAYER
            and entity.has_xdata(APPID)
        ):
            stats["existing_recovered_text_entities"] += 1
        source_ref = _source_ref(entity, page_index)
        if source_ref is not None:
            stats["source_mapped_entities"] += 1
            source_entities[source_ref].append(entity)
        if layer in {"PDF_PAGE", TEXT_LAYER, BACKUP_LAYER, "PDF_DIMENSION_EVIDENCE"}:
            continue
        is_fill = entity.dxftype() == "HATCH"
        if is_fill and source_ref in stroke_sources:
            continue
        paths = _entity_paths(entity, include_fill=include_fills)
        if not paths:
            continue
        if source_ref is None:
            stats["unsupported_outline_entities"] += 1
            continue
        points = np.vstack(paths)
        if not np.isfinite(points).all():
            stats["unsupported_outline_entities"] += 1
            continue
        low, high = points.min(axis=0), points.max(axis=0)
        extent = high - low
        if (
            float(extent.max()) < 0.02
            or float(extent.max()) > 12.0
            or sum(len(path) for path in paths) > MAX_OUTLINE_POINTS_PER_ATOM
        ):
            continue
        scale = max(float(extent.max()), 1e-9)
        closed_count = sum(
            int(len(path) >= 3 and np.linalg.norm(path[0] - path[-1]) < 1e-5 * scale)
            for path in paths
        )
        atoms.append(
            OutlineAtom(
                sequence_index=len(atoms),
                modelspace_index=modelspace_index,
                entity=entity,
                paths=paths,
                low=low,
                high=high,
                layer=layer,
                point_counts=tuple(len(path) for path in paths),
                closed_count=closed_count,
                source_ref=source_ref,
            )
        )
        stats["candidate_outline_entities"] += 1
        stats["candidate_fill_entities"] += int(is_fill)
    # Fill operations may occur between separate stroke operations without
    # sharing their seqno. Keep each representation's source order intact so
    # new fill candidates cannot split previously verified stroke glyphs/runs.
    atoms.sort(key=lambda atom: atom.entity.dxftype() == "HATCH")
    for index, atom in enumerate(atoms):
        atom.sequence_index = index
    return atoms, source_entities, stats


def _scan_matches(
    atoms: list[OutlineAtom], catalog: GlyphCatalog
) -> tuple[list[GlyphMatch], dict[str, int]]:
    matches: list[GlyphMatch] = []
    metrics = {
        "structural_candidate_windows": 0,
        "fingerprints_computed": 0,
        "exact_glyph_matches": 0,
    }
    max_length = max(catalog.lengths)
    for start, first in enumerate(atoms):
        if first.entity.dxftype() == "HATCH":
            continue  # Reviewed built-in templates describe stroke contours.
        paths: list[np.ndarray] = []
        point_counts: list[int] = []
        closed_count = 0
        low, high = first.low.copy(), first.high.copy()
        previous_source_sequence = first.source_ref[2]
        for end in range(start, min(len(atoms), start + max_length)):
            atom = atoms[end]
            if atom.entity.dxftype() == "HATCH":
                break
            if end > start and (
                atom.layer != first.layer
                or atom.source_ref[:2] != first.source_ref[:2]
                or atom.source_ref[2] < previous_source_sequence
                or atom.source_ref[2] - previous_source_sequence
                > MAX_SOURCE_SEQUENCE_GAP
            ):
                break
            previous_source_sequence = atom.source_ref[2]
            paths.extend(atom.paths)
            point_counts.extend(atom.point_counts)
            closed_count += atom.closed_count
            low = np.minimum(low, atom.low)
            high = np.maximum(high, atom.high)
            entity_count = len(paths)
            if entity_count > max_length:
                break
            if entity_count not in catalog.lengths:
                continue
            structural_key = (
                entity_count,
                closed_count,
                tuple(sorted(point_counts)),
            )
            candidates = catalog.structures.get(structural_key)
            if not candidates:
                continue
            metrics["structural_candidate_windows"] += 1
            extent = high - low
            if float(extent.max()) > 12.0 or float(extent.min()) < 0.04:
                continue
            aspect_ratio = float(extent[0] / max(extent[1], 1e-9))
            if not MIN_GLYPH_ASPECT <= aspect_ratio <= MAX_GLYPH_ASPECT:
                continue
            if not any(
                0.90 <= aspect_ratio / max(template.aspect_ratio, 1e-9) <= 1.10
                for template in candidates
            ):
                continue
            signature = fingerprint_paths(paths)
            metrics["fingerprints_computed"] += 1
            if signature is None:
                continue
            template = catalog.lookup.get((*structural_key, signature.fingerprint))
            if template is None:
                continue
            matches.append(
                GlyphMatch(
                    start=start,
                    end=end + 1,
                    char=template.char,
                    low=(float(low[0]), float(low[1])),
                    high=(float(high[0]), float(high[1])),
                    atoms=tuple(atoms[start : end + 1]),
                    template=template,
                )
            )
    metrics["exact_glyph_matches"] = len(matches)
    return matches, metrics


def _font_signature_key(
    signature: GeometrySignature,
) -> tuple[int, int, bytes]:
    return (
        signature.entity_count,
        signature.closed_count,
        font_mask_digest(
            bytes.fromhex(signature.mask_hex),
            signature.entity_count,
            signature.closed_count,
        ),
    )


def _font_fingerprint_paths(
    paths: list[np.ndarray] | tuple[np.ndarray, ...],
) -> GeometrySignature | None:
    # DXF serialization can move a mathematically exact half-pixel by a few
    # ulps or PDF numeric serialization.  Font catalogs quantize the 56-pixel
    # raster coordinate at 1e-4 pixel solely to stabilize that boundary; the
    # built-in audited catalog keeps its v1 digest.
    return fingerprint_paths(paths, raster_round_decimals=FONT_CATALOG_RASTER_DECIMALS)


def _font_fingerprint_variants(
    paths: list[np.ndarray], signature: GeometrySignature
) -> list[tuple[GeometrySignature, int]]:
    """Resolve only subpixel numeric serialization at integer rounding ties.

    PDF coordinate serialization can move normalized vertices by a few 1e-4
    pixels. Rounding to 3/4/5 decimals bounds the affected vertices to within
    0.0005 of a half-pixel boundary. Every resulting mask must still match a
    persisted catalog digest and topology exactly; callers must reject label
    conflicts across *all* variants, including the original four-decimal mask.
    This changes neither saved geometry nor the built-in audited fingerprint.
    """
    variants = [(signature, FONT_CATALOG_RASTER_DECIMALS)]
    seen = {signature.mask_hex}
    for decimals in (3, 5):
        candidate = fingerprint_paths(paths, raster_round_decimals=decimals)
        if candidate is not None and candidate.mask_hex not in seen:
            seen.add(candidate.mask_hex)
            variants.append((candidate, decimals))
    return variants


def _load_font_catalogs(
    paths: tuple[str | Path, ...], mode: str
) -> tuple[list[FontGlyphCatalog], list[dict[str, Any]]]:
    catalogs: list[FontGlyphCatalog] = []
    entries: list[dict[str, Any]] = []
    seen_paths: set[Path] = set()
    seen_ids: set[str] = set()
    for raw_path in paths:
        path = Path(raw_path).expanduser().resolve()
        if path in seen_paths:
            continue
        seen_paths.add(path)
        try:
            catalog = load_font_catalog(path)
        except Exception as exc:  # noqa: BLE001 - external catalog boundary
            if mode == "required":
                raise GlyphCatalogUnavailable(
                    f"OUTLINE_TEXT_FONT_CATALOG_UNAVAILABLE: {path}"
                ) from exc
            entries.append(
                {
                    "path": str(path),
                    "status": "unavailable",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            continue
        if catalog.catalog_id in seen_ids:
            entries.append(
                {
                    "path": str(path),
                    "status": "duplicate",
                    "catalog_id": catalog.catalog_id,
                }
            )
            continue
        seen_ids.add(catalog.catalog_id)
        catalogs.append(catalog)
        entries.append(
            {
                "path": str(catalog.path),
                "status": "loaded",
                "catalog_id": catalog.catalog_id,
                "font": catalog.font,
                "charset": catalog.charset,
                "unicode_cjk_version": catalog.unicode_cjk_version,
                "template_set_sha256": catalog.template_set_sha256,
                "outline_policy": catalog.outline_policy,
                "templates": len(catalog.templates),
                "characters": len(catalog.characters),
                "recognition_characters": len(catalog.recognition_characters),
                "normalized_alias_mappings": catalog.normalized_alias_mappings,
                "han_characters": sum(
                    is_han_character(char) for char in catalog.characters
                ),
                "ambiguous_geometry_keys": catalog.ambiguous_keys,
                "fully_ambiguous_characters": catalog.fully_ambiguous_characters,
                "tolerance_divisors": list(catalog.tolerance_divisors),
                "raster_round_decimals": catalog.raster_round_decimals,
            }
        )
    return catalogs, entries


def _lock_font_catalogs(
    catalogs: list[FontGlyphCatalog],
    audited_matches: list[GlyphMatch],
    entries: list[dict[str, Any]],
) -> tuple[list[FontCatalogLock], dict[str, list[GlyphMatch]]]:
    entry_by_id = {
        str(entry.get("catalog_id")): entry
        for entry in entries
        if entry.get("catalog_id")
    }
    locked: list[FontCatalogLock] = []
    matching_anchors: dict[str, list[GlyphMatch]] = defaultdict(list)
    signatures: list[tuple[GlyphMatch, GeometrySignature]] = []
    for match in audited_matches:
        if not is_han_character(match.char):
            continue
        signature = _font_fingerprint_paths(
            [path for atom in match.atoms for path in atom.paths]
        )
        if signature is not None:
            signatures.append((match, signature))
    for catalog in catalogs:
        comparable = 0
        exact_occurrences = 0
        exact_characters: set[str] = set()
        for match, signature in signatures:
            template = catalog.by_char.get(match.char)
            if template is None:
                continue
            comparable += 1
            label = unicodedata.normalize("NFKC", match.char)
            if len(label) != 1:
                label = match.char
            if label in catalog.matching_characters(
                _font_signature_key(signature), signature.aspect_ratio
            ):
                exact_occurrences += 1
                exact_characters.add(match.char)
                matching_anchors[catalog.catalog_id].append(
                    replace(match, font_catalog_ids=(catalog.catalog_id,))
                )
        is_locked = len(exact_characters) >= MIN_FONT_LOCK_DISTINCT_HAN
        entry = entry_by_id[catalog.catalog_id]
        entry.update(
            {
                "comparable_audited_han_occurrences": comparable,
                "exact_anchor_occurrences": exact_occurrences,
                "exact_anchor_characters": sorted(exact_characters, key=ord),
                "minimum_distinct_han_anchors": MIN_FONT_LOCK_DISTINCT_HAN,
                "minimum_distinct_latin_letters": MIN_FONT_LOCK_DISTINCT_LATIN,
                "locked": is_locked,
                "lock_method": "audited_han_anchors" if is_locked else None,
                "lock_reason": (
                    "distinct_audited_han_exact_masks"
                    if is_locked
                    else "insufficient_audited_anchors_or_adjacent_cmap_consensus"
                ),
            }
        )
        entry["status"] = "locked" if is_locked else "not_locked"
        if is_locked:
            locked.append(
                FontCatalogLock(
                    catalog=catalog,
                    exact_anchor_occurrences=exact_occurrences,
                    exact_anchor_characters=tuple(sorted(exact_characters, key=ord)),
                    method="audited_han_anchors",
                )
            )
    return locked, matching_anchors


def _scan_font_catalog_matches(
    atoms: list[OutlineAtom],
    locks: list[FontCatalogLock],
    occupied_indices: set[int],
    *,
    context: _FontScanContext | None = None,
) -> tuple[list[GlyphMatch], dict[str, Any]]:
    metrics = {
        "font_structural_candidate_windows": 0,
        "font_fingerprints_computed": 0,
        "font_catalog_candidate_matches": 0,
        "font_exact_glyph_matches": 0,
        "font_ambiguous_geometry_matches": 0,
        "font_ambiguous_overlap_rejections": 0,
        "font_overlapping_matches_rejected": 0,
        "font_contained_punctuation_suppressed": 0,
        "font_contained_fill_variants_suppressed": 0,
        "font_han_fragment_resolved_candidates": 0,
        "font_contained_han_fragments_suppressed": 0,
        "font_han_fragment_evidence": [],
        "font_han_fragment_evidence_truncated": 0,
        "font_numeric_variant_masks": 0,
    }
    if not locks:
        return [], metrics
    lengths = frozenset(length for lock in locks for length in lock.catalog.lengths)
    structures: dict[tuple[int, int], tuple[float, float]] = {}
    for lock in locks:
        for key, bounds in lock.catalog.structures.items():
            if key not in structures:
                structures[key] = bounds
            else:
                current = structures[key]
                structures[key] = (
                    min(current[0], bounds[0]),
                    max(current[1], bounds[1]),
                )
    max_length = max(lengths)
    lock_by_id = {lock.catalog.catalog_id: lock for lock in locks}
    matches: list[GlyphMatch] = []
    ambiguous_spans: list[tuple[int, int]] = []
    for start, first in enumerate(atoms):
        if start in occupied_indices:
            continue
        paths: list[np.ndarray] = []
        point_counts: list[int] = []
        closed_count = 0
        low, high = first.low.copy(), first.high.copy()
        previous_source_sequence = first.source_ref[2]
        for end in range(start, min(len(atoms), start + max_length)):
            if end in occupied_indices:
                break
            atom = atoms[end]
            if (atom.entity.dxftype() == "HATCH") != (
                first.entity.dxftype() == "HATCH"
            ):
                break
            if end > start and (
                atom.layer != first.layer
                or atom.source_ref[:2] != first.source_ref[:2]
                or atom.source_ref[2] < previous_source_sequence
                or atom.source_ref[2] - previous_source_sequence
                > MAX_SOURCE_SEQUENCE_GAP
            ):
                break
            previous_source_sequence = atom.source_ref[2]
            paths.extend(atom.paths)
            point_counts.extend(atom.point_counts)
            closed_count += atom.closed_count
            low = np.minimum(low, atom.low)
            high = np.maximum(high, atom.high)
            entity_count = len(paths)
            if entity_count > max_length:
                break
            if entity_count not in lengths:
                continue
            structure = (entity_count, closed_count)
            aspect_bounds = structures.get(structure)
            if aspect_bounds is None:
                continue
            metrics["font_structural_candidate_windows"] += 1
            extent = high - low
            if float(extent.max()) > 12.0 or float(extent.min()) < 0.04:
                continue
            aspect_ratio = float(extent[0] / max(extent[1], 1e-9))
            if not MIN_GLYPH_ASPECT <= aspect_ratio <= MAX_GLYPH_ASPECT:
                continue
            if not (aspect_bounds[0] * 0.90 <= aspect_ratio <= aspect_bounds[1] * 1.10):
                continue
            signature = _font_fingerprint_paths(paths)
            metrics["font_fingerprints_computed"] += 1
            if signature is None:
                continue
            variants = _font_fingerprint_variants(paths, signature)
            metrics["font_numeric_variant_masks"] += len(variants) - 1
            predictions: list[tuple[str, str, GeometrySignature, int]] = []
            for variant, decimals in variants:
                key = _font_signature_key(variant)
                for lock in locks:
                    for value in lock.catalog.matching_characters(
                        key, variant.aspect_ratio
                    ):
                        predictions.append(
                            (lock.catalog.catalog_id, value, variant, decimals)
                        )
            characters = {value for _, value, _, _ in predictions}
            if not predictions:
                continue
            if len(characters) != 1:
                ambiguous_spans.append((start, end + 1))
                if context is not None:
                    context.conflicts.append(
                        _FontConflict(
                            start,
                            end + 1,
                            tuple(low),
                            tuple(high),
                            tuple(
                                sorted(
                                    {
                                        (
                                            cid,
                                            label,
                                            _font_signature_key(sig)[2].hex(),
                                            decimals,
                                        )
                                        for cid, label, sig, decimals in predictions
                                    }
                                )
                            ),
                        )
                    )
                metrics["font_ambiguous_geometry_matches"] += 1
                continue
            char = characters.pop()
            catalog_ids = tuple(sorted({value for value, _, _, _ in predictions}))
            evidence_by_catalog: dict[str, tuple[GeometrySignature, int]] = {}
            for catalog_id, _, variant, decimals in predictions:
                evidence_by_catalog.setdefault(catalog_id, (variant, decimals))
            signature, raster_decimals = evidence_by_catalog[catalog_ids[0]]
            key = _font_signature_key(signature)
            support_locations = max(
                1,
                min(
                    lock_by_id[value].exact_anchor_occurrences for value in catalog_ids
                ),
            )
            template = GlyphTemplate(
                id=f"font-{catalog_ids[0]}-u{ord(char):04x}",
                char=char,
                fingerprint=key[2].hex(),
                entity_count=signature.entity_count,
                closed_count=signature.closed_count,
                point_counts=signature.point_counts,
                aspect_ratio=signature.aspect_ratio,
                support_locations=support_locations,
                support_documents=1,
                admission="font_catalog_exact_candidate",
            )
            matches.append(
                GlyphMatch(
                    start=start,
                    end=end + 1,
                    char=char,
                    low=(float(low[0]), float(low[1])),
                    high=(float(high[0]), float(high[1])),
                    atoms=tuple(atoms[start : end + 1]),
                    template=template,
                    font_catalog_ids=catalog_ids,
                    font_raster_round_decimals=raster_decimals,
                    font_match_evidence=tuple(
                        (
                            catalog_id,
                            _font_signature_key(evidence_by_catalog[catalog_id][0])[
                                2
                            ].hex(),
                            evidence_by_catalog[catalog_id][1],
                        )
                        for catalog_id in catalog_ids
                    ),
                )
            )

    # A complete exact letter/Han glyph may contain a contour identical to a
    # dash or another punctuation glyph (including vertical compatibility
    # forms). Such a strict subset is part of the complete glyph, not competing
    # text. The same-label raw/fill subset below keeps the complete raw glyph.
    # Equal windows and partial overlaps remain ambiguous. A separate Han
    # pass below considers only undersized children in an anchored source row.
    # Font/run consensus is still required.
    # Multi-label windows remain competing geometry even though they cannot
    # create a GlyphMatch. Otherwise adding a conflicting catalog can remove
    # a child from the overlap check and incorrectly admit its whole parent.
    # Prefix maxima handle nested/crossing spans; half-open endpoints allow
    # adjacent glyphs. Avoid scanning every ambiguous span for every match.
    ambiguous_spans.sort()
    ambiguous_starts = [start for start, _ in ambiguous_spans]
    ambiguous_ends = list(accumulate((end for _, end in ambiguous_spans), max))
    rejected: set[int] = set()
    for index, match in enumerate(matches):
        preceding = bisect_left(ambiguous_starts, match.end) - 1
        if preceding >= 0 and ambiguous_ends[preceding] > match.start:
            rejected.add(index)
    metrics["font_ambiguous_overlap_rejections"] = len(rejected)
    contained_punctuation: set[int] = set()
    contained_fill_variants: set[int] = set()
    ordered = sorted(enumerate(matches), key=lambda item: (item[1].start, item[1].end))
    active: list[tuple[int, GlyphMatch]] = []
    for index, match in ordered:
        active = [item for item in active if item[1].end > match.start]
        for other_index, other in active:
            if other.end > match.start and match.end > other.start:
                subset = None
                fill_subset = None
                for child_index, child, parent in (
                    (index, match, other),
                    (other_index, other, match),
                ):
                    # Both windows already match exact catalog representations.
                    # Retain the complete raw glyph when its same-label subset
                    # omits only closed collinear paths. Do not filter DXF paths.
                    if (
                        child.char == parent.char
                        and parent.start <= child.start
                        and child.end <= parent.end
                        and (parent.start, parent.end) != (child.start, child.end)
                        and set(child.font_catalog_ids) & set(parent.font_catalog_ids)
                        and all(
                            not _has_font_fill(path)
                            for offset, atom in enumerate(parent.atoms, parent.start)
                            if not child.start <= offset < child.end
                            for path in atom.paths
                        )
                    ):
                        fill_subset = child_index
                        break
                    if (
                        unicodedata.category(child.char).startswith("P")
                        and (
                            _is_english_letter(parent.char)
                            or is_han_character(parent.char)
                        )
                        and parent.start <= child.start
                        and child.end <= parent.end
                        and (parent.start, parent.end) != (child.start, child.end)
                        and set(child.font_catalog_ids) & set(parent.font_catalog_ids)
                        and all(
                            parent.low[axis] <= child.low[axis]
                            and child.high[axis] <= parent.high[axis]
                            for axis in (0, 1)
                        )
                    ):
                        subset = child_index
                        break
                if fill_subset is not None:
                    contained_fill_variants.add(fill_subset)
                    continue
                if subset is not None:
                    contained_punctuation.add(subset)
                    continue
                rejected.add(index)
                rejected.add(other_index)
        active.append((index, match))
    promoted, han_fragments, evidence = _resolve_contained_han_fragments(
        matches,
        rejected,
        contained_punctuation | contained_fill_variants,
        ambiguous_spans,
    )
    rejected.difference_update(promoted | han_fragments)
    metrics["font_han_fragment_resolved_candidates"] = len(promoted)
    metrics["font_contained_han_fragments_suppressed"] = len(han_fragments)
    metrics["font_han_fragment_evidence"] = evidence[:32]
    metrics["font_han_fragment_evidence_truncated"] = len(promoted) - len(evidence)
    excluded = (
        rejected | contained_punctuation | contained_fill_variants | han_fragments
    )
    accepted = [match for index, match in enumerate(matches) if index not in excluded]
    metrics["font_catalog_candidate_matches"] = len(accepted)
    metrics["font_overlapping_matches_rejected"] = len(rejected)
    metrics["font_contained_punctuation_suppressed"] = len(contained_punctuation)
    metrics["font_contained_fill_variants_suppressed"] = len(contained_fill_variants)
    if context is not None:
        context.matches = tuple(matches)
        context.han_parent_spans = {
            (matches[i].start, matches[i].end) for i in promoted
        }
    return accepted, metrics


def _font_row_window_bounds(length: int, position: int) -> tuple[int, int]:
    """Keep the complete short row, or at most 96 glyphs around a long-row parent."""
    start = max(
        0,
        min(
            position - (MAX_RECOVERED_TEXT_GLYPHS - 1) // 2,
            length - MAX_RECOVERED_TEXT_GLYPHS,
        ),
    )
    return start, min(length, start + MAX_RECOVERED_TEXT_GLYPHS)


def _resolve_contained_han_fragments(
    matches: list[GlyphMatch],
    rejected: set[int],
    ignored: set[int],
    ambiguous_spans: list[tuple[int, int]],
) -> tuple[set[int], set[int], list[dict[str, Any]]]:
    """Resolve only undersized Han fragments in a complete, anchored source row.

    The whole glyph must exactly cover its overlap component. Two uncontested
    Han anchors and the parent must provide three distinct labels in one font.
    A fragment at the anchors' scale, a separate small-text run, or any other
    complete interpretation keeps the component ambiguous.
    """
    ordered = sorted(
        ((index, match) for index, match in enumerate(matches) if index not in ignored),
        key=lambda item: (item[1].start, item[1].end),
    )
    components: list[list[tuple[int, GlyphMatch]]] = []
    component: list[tuple[int, GlyphMatch]] = []
    end = -1
    for item in ordered:
        if component and item[1].start >= end:
            components.append(component)
            component = []
            end = -1
        component.append(item)
        end = max(end, item[1].end)
    if component:
        components.append(component)

    roots: list[tuple[int, GlyphMatch]] = []
    proposals: dict[int, tuple[list[tuple[int, GlyphMatch]], set[str]]] = {}
    for component in components:
        if len(component) == 1:
            index, match = component[0]
            if index not in rejected and not any(
                match.start < high and low < match.end for low, high in ambiguous_spans
            ):
                roots.append((index, match))
            continue
        # Bounded evidence review; dense/complex components remain ambiguous.
        if len(component) > 32:
            continue
        index, parent = max(component, key=lambda item: item[1].end - item[1].start)
        if not is_han_character(parent.char):
            continue
        children = [(i, match) for i, match in component if i != index]
        if any(
            not is_han_character(child.char)
            or not parent.start <= child.start < child.end <= parent.end
            or (parent.start, parent.end) == (child.start, child.end)
            or not all(
                parent.low[axis] <= child.low[axis]
                and child.high[axis] <= parent.high[axis]
                for axis in (0, 1)
            )
            for _, child in children
        ) or any(
            parent.start < high and low < parent.end for low, high in ambiguous_spans
        ):
            continue
        shared = set(parent.font_catalog_ids)
        for _, child in children:
            shared.intersection_update(child.font_catalog_ids)
        if not shared:
            continue
        # A real line of small characters is an alternative interpretation.
        if any(
            _publishable_text("".join(match.char for match in run), font_locked=True)[0]
            for run in _group_runs([child for _, child in children])
        ):
            continue
        roots.append((index, parent))
        proposals[index] = children, shared

    if not proposals:
        return set(), set(), []

    promoted: set[int] = set()
    suppressed: set[int] = set()
    evidence: list[dict[str, Any]] = []
    for font in sorted({font for _, match in roots for font in match.font_catalog_ids}):
        runs: list[list[tuple[int, GlyphMatch]]] = []
        run: list[tuple[int, GlyphMatch]] = []
        for index, match in roots:
            if not is_han_character(match.char) or font not in match.font_catalog_ids:
                if run:
                    runs.append(run)
                    run = []
                continue
            if run:
                left = run[-1][1]
                a, b = left.atoms[-1].source_ref, match.atoms[0].source_ref
                if (
                    not _run_neighbors(left, match)
                    or a[:2] != b[:2]
                    or not 0 <= b[2] - a[2] <= MAX_SOURCE_SEQUENCE_GAP
                ):
                    runs.append(run)
                    run = []
            run.append((index, match))
        if run:
            runs.append(run)
        for run in runs:
            if len(run) < 3:
                continue
            for position, (index, parent) in enumerate(run):
                if index not in proposals or index in promoted:
                    continue
                start, stop = _font_row_window_bounds(len(run), position)
                window = run[start:stop]
                anchors = [match for i, match in window if i not in proposals]
                if len(anchors) < 2:
                    continue
                minimum_height = min(match.height for match in anchors)
                children, shared = proposals[index]
                if (
                    font not in shared
                    or len({parent.char, *(a.char for a in anchors)}) < 3
                ):
                    continue
                if any(
                    child.height >= MIN_HAN_RUN_SIZE_RATIO * minimum_height
                    for _, child in children
                ):
                    continue
                promoted.add(index)
                suppressed.update(i for i, _ in children)
                if len(evidence) >= 32:
                    continue
                # Include the smallest anchor plus enough distinct labels to
                # reproduce the decision, using at most three anchor records.
                proof_anchors: list[GlyphMatch] = []
                labels = {parent.char}
                for anchor in sorted(anchors, key=lambda a: (a.height, a.start)):
                    if not proof_anchors or anchor.char not in labels:
                        proof_anchors.append(anchor)
                        labels.add(anchor.char)
                    if len(labels) >= 3:
                        break
                evidence.append(
                    {
                        "stage": "font_candidate_scan",
                        "catalog_id": font,
                        "parent": _font_fragment_evidence(parent),
                        "fragments": [
                            _font_fragment_evidence(child) for _, child in children
                        ],
                        "anchors": [
                            _font_fragment_evidence(anchor) for anchor in proof_anchors
                        ],
                        "minimum_anchor_height": minimum_height,
                        "maximum_fragment_height_ratio": max(
                            child.height for _, child in children
                        )
                        / minimum_height,
                        "required_height_ratio_below": MIN_HAN_RUN_SIZE_RATIO,
                        **(
                            {
                                "row_window": {
                                    "glyph_count": len(window),
                                    "span": [window[0][1].start, window[-1][1].end],
                                }
                            }
                            if len(run) > MAX_RECOVERED_TEXT_GLYPHS
                            else {}
                        ),
                    }
                )
    return promoted, suppressed, evidence


def _font_fragment_evidence(match: GlyphMatch) -> dict[str, Any]:
    return {
        "char": match.char,
        "span": [match.start, match.end],
        "bbox": [*match.low, *match.high],
        "source_handles": [atom.entity.dxf.handle for atom in match.atoms],
        "fingerprints_by_catalog": [list(item) for item in match.font_match_evidence],
    }


def _complete_font_catalog_locks(
    catalogs: list[FontGlyphCatalog],
    anchor_locks: list[FontCatalogLock],
    matching_anchors: dict[str, list[GlyphMatch]],
    font_candidates: list[GlyphMatch],
    entries: list[dict[str, Any]],
) -> list[FontCatalogLock]:
    locks = {lock.catalog.catalog_id: lock for lock in anchor_locks}
    entry_by_id = {
        str(entry.get("catalog_id")): entry
        for entry in entries
        if entry.get("catalog_id")
    }
    for catalog in catalogs:
        if catalog.catalog_id in locks:
            continue
        catalog_matches = [
            *matching_anchors.get(catalog.catalog_id, ()),
            *(
                match
                for match in font_candidates
                if catalog.catalog_id in match.font_catalog_ids
            ),
        ]
        qualifying_runs: list[dict[str, Any]] = []
        for run in _group_runs(sorted(catalog_matches, key=lambda match: match.start)):
            han = [match.char for match in run if is_han_character(match.char)]
            distinct_han = sorted(set(han), key=ord)
            latin = [match.char for match in run if _is_english_letter(match.char)]
            han_consensus = len(distinct_han) >= MIN_FONT_LOCK_DISTINCT_HAN
            latin_consensus = (
                len({ch.lower() for ch in latin}) >= MIN_FONT_LOCK_DISTINCT_LATIN
            )
            if not han_consensus and not latin_consensus:
                continue
            text = "".join(match.char for match in run)
            qualifying_runs.append(
                {
                    "text": text[:96],
                    "glyphs": len(run),
                    "distinct_han_characters": distinct_han[:32],
                    "distinct_latin_characters": sorted(set(latin)),
                    "consensus_script": "han" if han_consensus else "latin",
                }
            )
        if not qualifying_runs:
            continue
        evidence_characters = sorted(
            {
                char
                for run in qualifying_runs
                for char in (
                    *run["distinct_han_characters"],
                    *run["distinct_latin_characters"],
                )
            },
            key=ord,
        )
        evidence_occurrences = max(int(run["glyphs"]) for run in qualifying_runs)
        method = (
            "font_cmap_run_consensus"
            if any(run["consensus_script"] == "han" for run in qualifying_runs)
            else "font_cmap_latin_run_consensus"
        )
        locks[catalog.catalog_id] = FontCatalogLock(
            catalog=catalog,
            exact_anchor_occurrences=evidence_occurrences,
            exact_anchor_characters=tuple(evidence_characters),
            method=method,
            evidence_texts=tuple(run["text"] for run in qualifying_runs[:5]),
        )
        entry = entry_by_id[catalog.catalog_id]
        entry.update(
            {
                "status": "locked",
                "locked": True,
                "lock_method": method,
                "lock_reason": (
                    "distinct_adjacent_han_exact_font_cmap_masks"
                    if method == "font_cmap_run_consensus"
                    else "distinct_adjacent_latin_exact_font_cmap_masks"
                ),
                "self_lock_evidence": qualifying_runs[:5],
            }
        )
    return [locks[key] for key in sorted(locks)]


def _font_window_evidence(
    window: GlyphMatch | _FontConflict, atoms: list[OutlineAtom]
) -> dict[str, Any]:
    predictions = (
        tuple(
            (cid, window.char, digest, decimals)
            for cid, digest, decimals in window.font_match_evidence
        )
        if isinstance(window, GlyphMatch)
        else window.predictions
    )
    return {
        "span": [window.start, window.end],
        "bbox": [*window.low, *window.high],
        "source_handles": [
            a.entity.dxf.handle for a in atoms[window.start : window.end]
        ],
        "labels": sorted({p[1] for p in predictions}),
        "predictions": [list(p) for p in predictions],
    }


def _has_small_han_row(windows: list[dict[str, Any]]) -> bool:
    """Keep even a possible independent two-Han row; source gaps do not excuse it."""
    han = [w for w in windows if any(is_han_character(ch) for ch in w["labels"])]
    for index, left in enumerate(han):
        for right in han[index + 1 :]:
            if (
                left["span"][0] < right["span"][1]
                and right["span"][0] < left["span"][1]
            ):
                continue
            a, b = sorted((left["bbox"], right["bbox"]), key=lambda box: box[0])
            height = max(a[3] - a[1], b[3] - b[1], 0.01)
            if (
                min(a[3] - a[1], b[3] - b[1]) / height >= MIN_HAN_RUN_SIZE_RATIO
                and abs((a[1] + a[3] - b[1] - b[3]) / 2) <= 0.35 * height
                and -0.12 * height <= b[0] - a[2] <= 0.90 * height
            ):
                return True
    return False


def _recheck_locked_font_rows(
    atoms: list[OutlineAtom],
    locks: list[FontCatalogLock],
    candidates: list[GlyphMatch],
    context: _FontScanContext | None,
    occupied_indices: set[int],
) -> tuple[list[GlyphMatch], dict[str, Any]]:
    """Recheck an exact glyph without discarding other fonts' evidence.

    The selected font must already be locked by the all-font scan. A local Han
    row needs three distinct globally unambiguous anchors plus the existing
    single-font Han-fragment decision. A Latin row needs four distinct letters
    and permits only strictly shorter internal punctuation. All original
    competing windows remain checked, including other fonts' predictions.
    """
    metrics: dict[str, Any] = {
        "font_row_recheck_scans": 0,
        "font_row_recheck_matches": 0,
        "font_row_recheck_evidence": [],
        "font_row_recheck_evidence_truncated": 0,
    }
    if context is None or not locks:
        return [], metrics

    def key(match: GlyphMatch) -> tuple[int, int, str]:
        return match.start, match.end, match.char

    existing = {key(m): m for m in candidates}
    missing = {
        key(m): m
        for m in context.matches
        if (is_han_character(m.char) or _is_english_letter(m.char))
        and key(m) not in existing
    }
    restored: dict[tuple[int, int, str], GlyphMatch] = {}
    for lock in locks:
        font = lock.catalog.catalog_id
        if not any(font in m.font_catalog_ids for m in missing.values()):
            continue
        local_context = _FontScanContext()
        local, _ = _scan_font_catalog_matches(
            atoms, [lock], occupied_indices, context=local_context
        )
        metrics["font_row_recheck_scans"] += 1
        for run in _group_runs(local):
            han_row = all(is_han_character(m.char) for m in run)
            latin_row = all(_is_english_letter(m.char) for m in run)
            required_anchors = (
                MIN_FONT_LOCK_DISTINCT_HAN if han_row else MIN_FONT_LOCK_DISTINCT_LATIN
            )
            if not (han_row or latin_row) or len(run) < required_anchors + 1:
                continue
            if any(
                a.atoms[-1].source_ref[:2] != b.atoms[0].source_ref[:2]
                or not 0
                <= b.atoms[0].source_ref[2] - a.atoms[-1].source_ref[2]
                <= MAX_SOURCE_SEQUENCE_GAP
                for a, b in zip(run, run[1:])
            ):
                continue
            for position, parent in enumerate(run):
                if key(parent) not in missing or key(parent) in restored:
                    continue
                start, stop = _font_row_window_bounds(len(run), position)
                window = run[start:stop]
                anchors = [
                    m
                    for m in window
                    if key(m) in existing
                    and font in existing[key(m)].font_catalog_ids
                    and not any(
                        m.start < c.end and c.start < m.end for c in context.conflicts
                    )
                ]
                if (
                    len({m.char.lower() if latin_row else m.char for m in anchors})
                    < required_anchors
                ):
                    continue
                minimum_height = min(m.height for m in anchors)
                reference_height = minimum_height if han_row else parent.height
                maximum_ratio = MIN_HAN_RUN_SIZE_RATIO if han_row else 1.0
                competitors: list[GlyphMatch | _FontConflict] = [
                    m
                    for m in context.matches
                    if key(m) != key(parent)
                    and m.start < parent.end
                    and parent.start < m.end
                ]
                competitors.extend(
                    c
                    for c in context.conflicts
                    if c.start < parent.end and parent.start < c.end
                )
                if (
                    not competitors
                    or len(competitors) > 32
                    or any(
                        not parent.start <= c.start < c.end <= parent.end
                        or (c.start, c.end) == (parent.start, parent.end)
                        or c.high[1] - c.low[1] >= maximum_ratio * reference_height
                        or not all(
                            parent.low[axis] <= c.low[axis]
                            and c.high[axis] <= parent.high[axis]
                            for axis in (0, 1)
                        )
                        for c in competitors
                    )
                ):
                    continue
                windows = [_font_window_evidence(c, atoms) for c in competitors]
                punctuation_only = all(
                    all(
                        unicodedata.category(ch).startswith("P")
                        for ch in window["labels"]
                    )
                    for window in windows
                )
                # A locally unambiguous whole Han glyph can also be blocked
                # solely by another font's small punctuation. It needs the
                # same independent row anchors and strict subset/size checks;
                # a Han-fragment proof is only relevant to Han competitors.
                if (
                    han_row
                    and (parent.start, parent.end) not in local_context.han_parent_spans
                    and not punctuation_only
                ):
                    continue
                valid = True
                for window in windows:
                    if latin_row:
                        if not all(
                            unicodedata.category(ch).startswith("P")
                            for ch in window["labels"]
                        ):
                            valid = False
                            break
                        continue
                    han = {ch for ch in window["labels"] if is_han_character(ch)}
                    if (
                        len(han) > 1
                        or any(
                            not (
                                is_han_character(ch)
                                or unicodedata.category(ch).startswith("P")
                                or 0x31C0 <= ord(ch) <= 0x31EF
                            )
                            for ch in window["labels"]
                        )
                        or any(
                            not any(
                                cid == font and label == ch
                                for cid, label, _, _ in window["predictions"]
                            )
                            for ch in han
                        )
                    ):
                        valid = False
                        break
                if not valid or _has_small_han_row(windows):
                    continue
                restored[key(parent)] = parent
                if len(metrics["font_row_recheck_evidence"]) >= 32:
                    continue
                proof_anchors: dict[str, GlyphMatch] = {}
                for anchor in sorted(anchors, key=lambda m: (m.height, m.start)):
                    label = anchor.char.lower() if latin_row else anchor.char
                    proof_anchors.setdefault(label, anchor)
                    if len(proof_anchors) == required_anchors:
                        break
                metrics["font_row_recheck_evidence"].append(
                    {
                        "stage": "locked_font_row_recheck",
                        "script": "han" if han_row else "latin",
                        "catalog_id": font,
                        "parent": _font_fragment_evidence(parent),
                        "anchors": [
                            _font_fragment_evidence(a) for a in proof_anchors.values()
                        ],
                        "conflicts": windows,
                        "conflict_kind": "contained_punctuation_only"
                        if punctuation_only
                        else "contained_han_fragments",
                        "minimum_anchor_height": minimum_height,
                        "fragment_height_reference": "minimum_anchor_height"
                        if han_row
                        else "parent_height",
                        "fragment_height_reference_value": reference_height,
                        "required_fragment_height_ratio_below": maximum_ratio,
                        **(
                            {
                                "row_window": {
                                    "glyph_count": stop - start,
                                    "span": [run[start].start, run[stop - 1].end],
                                }
                            }
                            if len(run) > MAX_RECOVERED_TEXT_GLYPHS
                            else {}
                        ),
                    }
                )
    metrics["font_row_recheck_matches"] = len(restored)
    metrics["font_row_recheck_evidence_truncated"] = len(restored) - len(
        metrics["font_row_recheck_evidence"]
    )
    return sorted(restored.values(), key=lambda m: m.start), metrics


def _font_row_neighborhood(
    parent: GlyphMatch,
    font: str,
    members: list[GlyphMatch],
    starts: list[int],
    anchor_spans: set[tuple[int, int]],
) -> tuple[list[GlyphMatch], list[GlyphMatch]]:
    """Find three independent anchors along at most 96 adjacent source glyphs.

    Grow a local window in both directions, stopping at every unverified gap,
    source/layer change or incompatible neighbor. Long rows need not fit inside
    one TEXT entity. Already verified glyphs may connect the window but only
    original uncontested matches can supply its anchors.
    """
    position = bisect_left(starts, parent.start)
    indices = [position - 1, position]
    frontiers = [parent, parent]
    active = [True, True]
    row = [parent]
    anchors: dict[str, GlyphMatch] = {}
    while any(active) and len(row) < MAX_RECOVERED_TEXT_GLYPHS:
        for side in (0, 1):
            if not active[side]:
                continue
            index = indices[side]
            if not 0 <= index < len(members):
                active[side] = False
                continue
            match = members[index]
            left, right = (
                (match, frontiers[side]) if side == 0 else (frontiers[side], match)
            )
            a, b = left.atoms[-1].source_ref, right.atoms[0].source_ref
            if (
                not is_han_character(match.char)
                or font not in match.font_catalog_ids
                or not _run_neighbors(left, right)
                or a[:2] != b[:2]
                or not 0 <= b[2] - a[2] <= MAX_SOURCE_SEQUENCE_GAP
            ):
                active[side] = False
                continue
            row.append(match)
            frontiers[side] = match
            indices[side] += -1 if side == 0 else 1
            if (match.start, match.end) in anchor_spans:
                anchors.setdefault(match.char, match)
            if (
                len(anchors) == MIN_FONT_LOCK_DISTINCT_HAN
                or len(row) == MAX_RECOVERED_TEXT_GLYPHS
            ):
                return sorted(row, key=lambda m: m.start), sorted(
                    anchors.values(), key=lambda m: m.start
                )
    return sorted(row, key=lambda m: m.start), sorted(
        anchors.values(), key=lambda m: m.start
    )


def _restore_enclosed_radicals(
    locks: list[FontCatalogLock],
    candidates: list[GlyphMatch],
    context: _FontScanContext | None,
    *,
    verified_bridges: list[GlyphMatch] | tuple[GlyphMatch, ...] = (),
) -> tuple[list[GlyphMatch], dict[str, Any]]:
    """Resolve a single enclosing or half-enclosing radical after a font lock.

    Both complete glyph and radical must already have unique exact matches.
    Every overlap, including hidden multi-label windows, participates. Three
    uncontested distinct Han anchors in the same source row are required;
    these proposals can never create their own font lock or act as anchors.
    """
    metrics: dict[str, Any] = {
        "font_enclosed_radical_matches": 0,
        "font_enclosed_radical_half_matches": 0,
        "font_enclosed_radical_rounds": 0,
        "font_enclosed_radical_bridge_matches": 0,
        "font_enclosed_radical_evidence": [],
        "font_enclosed_radical_evidence_truncated": 0,
        "font_enclosed_radical_rejection_counts": {},
        "font_enclosed_radical_rejections": [],
        "font_enclosed_radical_rejections_truncated": 0,
    }
    if context is None or not locks:
        return [], metrics
    existing = {(m.start, m.end) for m in candidates}
    bridges = {(m.start, m.end): m for m in verified_bridges}
    members = sorted(
        {(m.start, m.end): m for m in [*candidates, *verified_bridges]}.values(),
        key=lambda m: m.start,
    )
    member_starts = [m.start for m in members]
    components: list[list[GlyphMatch | _FontConflict]] = []
    end = -1
    for window in sorted(
        [*context.matches, *context.conflicts], key=lambda m: (m.start, m.end)
    ):
        if not components or window.start >= end:
            components.append([])
        components[-1].append(window)
        end = max(end, window.end)
    uncontested = {
        (c[0].start, c[0].end)
        for c in components
        if len(c) == 1 and isinstance(c[0], GlyphMatch)
    }
    anchor_spans = uncontested & existing

    def reject(parent: GlyphMatch, radical: GlyphMatch, reason: str) -> None:
        counts = metrics["font_enclosed_radical_rejection_counts"]
        counts[reason] = counts.get(reason, 0) + 1
        if len(metrics["font_enclosed_radical_rejections"]) < 32:
            metrics["font_enclosed_radical_rejections"].append(
                {
                    "status": "unconfirmed_geometry_retained",
                    "reason": reason,
                    "parent_candidate": _font_fragment_evidence(parent),
                    "radical_candidate": _font_fragment_evidence(radical),
                }
            )
        else:
            metrics["font_enclosed_radical_rejections_truncated"] += 1

    proposals: list[tuple[GlyphMatch, GlyphMatch, int, dict[str, object] | None]] = []
    for component in components:
        # More than one alternative, or a hidden ambiguous window, needs a
        # different proof. Do not absorb arbitrary small text or punctuation.
        if len(component) != 2 or not all(isinstance(m, GlyphMatch) for m in component):
            continue
        parent, radical = sorted(component, key=lambda m: m.start - m.end)
        if (
            (parent.start, parent.end) in existing
            or (parent.start, parent.end) in bridges
            or not is_han_character(parent.char)
            or not is_han_character(radical.char)
            or not parent.start <= radical.start < radical.end <= parent.end
            or (parent.start, parent.end) == (radical.start, radical.end)
        ):
            continue
        rings = [path for atom in radical.atoms for path in atom.paths]
        remaining = [
            path
            for index, atom in enumerate(parent.atoms, parent.start)
            if not radical.start <= index < radical.end
            for path in atom.paths
        ]
        closed_enclosure = strictly_encloses_paths(rings, remaining)
        half_enclosure = (
            None if closed_enclosure else half_enclosure_evidence(rings, remaining)
        )
        if not closed_enclosure and half_enclosure is None:
            reject(parent, radical, "not_a_strict_closed_enclosure")
            continue
        proposals.append((parent, radical, len(rings), half_enclosure))

    restored: dict[tuple[int, int], GlyphMatch] = {}
    rejections: dict[tuple[int, int], tuple[GlyphMatch, GlyphMatch, str]] = {}
    verified_for_bridging: dict[tuple[int, int], GlyphMatch] = {}
    # Each round sees only independently proved earlier results. New glyphs
    # never supply anchors and cannot bootstrap one another within a round.
    # Even a long chain must reach three ORIGINAL anchors within 96 neighbors.
    for round_index in range(MAX_RECOVERED_TEXT_GLYPHS):
        previous_count = len(restored)
        for parent, radical, ring_count, half_enclosure in proposals:
            if (parent.start, parent.end) in restored:
                continue
            closed_enclosure = half_enclosure is None
            rejection = (
                "no_matching_radical_alias_in_locked_font"
                if closed_enclosure
                else "no_matching_canonical_radical_in_locked_font"
            )
            for lock in locks:
                font = lock.catalog.catalog_id
                if (
                    font not in parent.font_catalog_ids
                    or font not in radical.font_catalog_ids
                ):
                    continue
                digests = {
                    bytes.fromhex(digest)
                    for cid, digest, _ in radical.font_match_evidence
                    if cid == font
                }
                radical_codepoint = KANGXI_RADICAL_CODEPOINTS.get(radical.char)
                if half_enclosure is not None and radical_codepoint is None:
                    continue
                # Compatibility radicals may use a different drawing from their
                # canonical Han form. The open-side proof validates the actual
                # canonical cmap outline; Unicode supplies its radical identity.
                # Closed counters retain their existing exact alias-geometry check.
                aliases = [
                    t
                    for t in lock.catalog.templates_by_label.get(radical.char, ())
                    if (
                        0x2F00 <= t.codepoint <= 0x2FD5
                        if closed_enclosure
                        else t.codepoint == ord(radical.char)
                    )
                    and t.entity_count == t.closed_count == ring_count
                    and 0.90 <= radical.template.aspect_ratio / t.aspect_ratio <= 1.10
                    and digests.intersection(t.match_digests)
                ]
                if not aliases:
                    continue
                # Verified earlier stages may connect a row, never supply anchors.
                # Only results proved in earlier rounds enter the member list.
                row, anchors = _font_row_neighborhood(
                    parent, font, members, member_starts, anchor_spans
                )
                if len(anchors) < MIN_FONT_LOCK_DISTINCT_HAN:
                    rejection = "insufficient_independent_local_row_anchors"
                    continue
                restored[parent.start, parent.end] = parent
                # A globally shared whole-glyph match does not transfer the
                # radical proof to a font that did not establish it.
                verified_for_bridging[parent.start, parent.end] = replace(
                    parent, font_catalog_ids=(font,)
                )
                metrics["font_enclosed_radical_half_matches"] += (
                    half_enclosure is not None
                )
                used_bridges = [m for m in row if (m.start, m.end) in bridges]
                metrics["font_enclosed_radical_bridge_matches"] += bool(used_bridges)
                if len(metrics["font_enclosed_radical_evidence"]) < 32:
                    metrics["font_enclosed_radical_evidence"].append(
                        {
                            "stage": "locked_font_enclosed_radical_recheck",
                            "dependency_round": round_index + 1,
                            "catalog_id": font,
                            "parent": _font_fragment_evidence(parent),
                            "radical": _font_fragment_evidence(radical),
                            "radical_codepoint": f"U+{min(t.codepoint for t in aliases) if closed_enclosure else radical_codepoint:04X}",
                            "anchors": [_font_fragment_evidence(a) for a in anchors],
                            "verified_bridges": [
                                {
                                    **_font_fragment_evidence(m),
                                    "verified_catalog_ids": list(m.font_catalog_ids),
                                }
                                for m in used_bridges
                            ],
                            "row_path": [_font_fragment_evidence(m) for m in row],
                            "topology": (
                                "two_nested_rings_strictly_contain_all_remaining_paths"
                                if closed_enclosure
                                else "disjoint_parts_interleave_across_one_open_side"
                            ),
                            **(
                                {
                                    "geometry_evidence": half_enclosure,
                                    "radical_outline_codepoint": f"U+{ord(radical.char):04X}",
                                    "radical_identity": "unicode_nfkc_kangxi_to_canonical_han",
                                }
                                if half_enclosure is not None
                                else {}
                            ),
                        }
                    )
                break
            else:
                rejections[parent.start, parent.end] = (parent, radical, rejection)
        if len(restored) == previous_count:
            break
        metrics["font_enclosed_radical_rounds"] = round_index + 1
        bridges.update(verified_for_bridging)
        members = sorted(
            {(m.start, m.end): m for m in [*candidates, *bridges.values()]}.values(),
            key=lambda m: m.start,
        )
        member_starts = [m.start for m in members]
    for span, (parent, radical, reason) in rejections.items():
        if span not in restored:
            reject(parent, radical, reason)
    metrics["font_enclosed_radical_matches"] = len(restored)
    metrics["font_enclosed_radical_evidence_truncated"] = len(restored) - len(
        metrics["font_enclosed_radical_evidence"]
    )
    return sorted(restored.values(), key=lambda m: m.start), metrics


def _finalize_font_matches(
    candidates: list[GlyphMatch], locks: list[FontCatalogLock]
) -> list[GlyphMatch]:
    lock_by_id = {lock.catalog.catalog_id: lock for lock in locks}
    finalized: list[GlyphMatch] = []
    for match in candidates:
        catalog_ids = tuple(
            value for value in match.font_catalog_ids if value in lock_by_id
        )
        if not catalog_ids:
            continue
        methods = {lock_by_id[value].method for value in catalog_ids}
        admission = (
            "font_cmap_run_consensus_exact"
            if methods & {"font_cmap_run_consensus", "font_cmap_latin_run_consensus"}
            else "audited_anchor_locked_font_catalog_exact"
        )
        support_locations = min(
            lock_by_id[value].exact_anchor_occurrences for value in catalog_ids
        )
        template = replace(
            match.template,
            support_locations=support_locations,
            admission=admission,
        )
        evidence = tuple(
            item for item in match.font_match_evidence if item[0] in catalog_ids
        )
        raster_decimals = match.font_raster_round_decimals
        if evidence:
            catalog_id, fingerprint, raster_decimals = evidence[0]
            template = replace(
                template,
                id=f"font-{catalog_id}-u{ord(match.char):04x}",
                fingerprint=fingerprint,
            )
        finalized.append(
            replace(
                match,
                template=template,
                font_catalog_ids=tuple(sorted(catalog_ids)),
                font_raster_round_decimals=raster_decimals,
                font_match_evidence=evidence,
            )
        )
    return finalized


def _select_non_overlapping(matches: list[GlyphMatch]) -> tuple[list[GlyphMatch], int]:
    selected: list[GlyphMatch] = []
    used: set[int] = set()
    ranked = sorted(
        matches,
        key=lambda match: (
            -match.template.support_documents,
            -match.template.support_locations,
            -(match.end - match.start),
            match.start,
            match.template.id,
        ),
    )
    for match in ranked:
        indices = set(range(match.start, match.end))
        if indices.intersection(used):
            continue
        used.update(indices)
        selected.append(match)
    selected.sort(key=lambda match: match.start)
    return selected, len(matches) - len(selected)


def _run_neighbors(left: GlyphMatch, right: GlyphMatch) -> bool:
    if right.start != left.end or right.atoms[0].layer != left.atoms[0].layer:
        return False
    if (left.atoms[0].entity.dxftype() == "HATCH") != (
        right.atoms[0].entity.dxftype() == "HATCH"
    ):
        return False
    left_height, right_height = left.height, right.height
    height = max(left_height, right_height, 0.01)
    center_delta = abs((right.low[1] + right.high[1] - left.low[1] - left.high[1]) / 2)
    gap = right.low[0] - left.high[0]
    relative_size = min(left_height, right_height) / max(
        left_height, right_height, 1e-9
    )
    punctuation = left.char in ":-" or right.char in ":-"
    same_font_latin = bool(
        set(left.font_catalog_ids) & set(right.font_catalog_ids)
    ) and (_is_english_letter(left.char) or _is_english_letter(right.char))
    size_ok = relative_size >= (
        0.03 if punctuation else 0.45 if same_font_latin else MIN_HAN_RUN_SIZE_RATIO
    )
    return (
        right.low[0] >= left.low[0] - 0.10 * height
        and center_delta <= 0.35 * height
        and -0.12 * height <= gap <= 0.90 * height
        and size_ok
    )


def _group_runs(matches: list[GlyphMatch]) -> list[list[GlyphMatch]]:
    groups: list[list[GlyphMatch]] = []
    current: list[GlyphMatch] = []
    for match in matches:
        if current and _run_neighbors(current[-1], match):
            current.append(match)
            continue
        if current:
            groups.append(current)
        current = [match]
    if current:
        groups.append(current)
    return groups


def _publishable_text(text: str, *, font_locked: bool = False) -> tuple[bool, str]:
    if not text or len(text) > MAX_RECOVERED_TEXT_GLYPHS:
        return False, "unsupported_text_length"
    if SCALE_TEXT.fullmatch(text):
        return True, "reviewed_scale_token"
    han_count = sum(is_han_character(char) or char == "〇" for char in text)
    if han_count >= 2:
        return True, "multiple_han_glyphs"
    if font_locked and han_count + sum(_is_english_letter(char) for char in text) >= 2:
        return True, "locked_font_letter_run"
    return False, "insufficient_text_run_consensus"


def _split_long_text_run(run: list[GlyphMatch]) -> list[list[GlyphMatch]]:
    """Bound TEXT payloads after matching, without discarding an exact long row.

    Every segment still needs its own publication consensus. Move a final
    one-glyph remainder into a two-glyph tail; never invent a missing neighbor
    or cross the original run boundary. Glyphs retain their own source atoms.
    """
    if len(run) <= MAX_RECOVERED_TEXT_GLYPHS:
        return [run]
    segments: list[list[GlyphMatch]] = []
    start = 0
    while len(run) - start > MAX_RECOVERED_TEXT_GLYPHS:
        end = start + MAX_RECOVERED_TEXT_GLYPHS
        if len(run) - end == 1:
            end -= 1
        segments.append(run[start:end])
        start = end
    segments.append(run[start:])
    return segments


def _run_geometry(
    run: list[GlyphMatch],
) -> tuple[str, np.ndarray, np.ndarray, float]:
    text = "".join(match.char for match in run)
    low = np.min(np.asarray([match.low for match in run]), axis=0)
    high = np.max(np.asarray([match.high for match in run]), axis=0)
    height = float(np.median([match.height for match in run]))
    return text, low, high, height


def _recovery_key(
    low: np.ndarray, high: np.ndarray
) -> tuple[float, float, float, float]:
    return tuple(round(float(value), RECOVERY_KEY_PRECISION) for value in (*low, *high))


def _existing_recovery_keys(
    doc: Any, page_index: int
) -> set[tuple[float, float, float, float]]:
    keys: set[tuple[float, float, float, float]] = set()
    for entity in doc.modelspace().query(f'TEXT[layer=="{TEXT_LAYER}"]'):
        if not entity.has_xdata(APPID):
            continue
        tags = list(entity.get_xdata(APPID))
        pages = [int(value) for code, value in tags if code in (1070, 1071)]
        bounds = [float(value) for code, value in tags if code == 1040]
        if not pages or pages[0] != page_index or len(bounds) < 4:
            continue
        low = np.asarray(bounds[:2], dtype=np.float64)
        high = np.asarray(bounds[2:4], dtype=np.float64)
        keys.add(_recovery_key(low, high))
    return keys


def _entity_bounds(entity: Any) -> tuple[float, float, float, float] | None:
    try:
        bounds = dxf_bbox.extents([entity], fast=True)
        values = (
            float(bounds.extmin.x),
            float(bounds.extmin.y),
            float(bounds.extmax.x),
            float(bounds.extmax.y),
        )
    except Exception:  # noqa: BLE001
        return None
    return values if all(math.isfinite(value) for value in values) else None


def _related_fill_entities(
    run: list[GlyphMatch], source_entities: dict[tuple[str, int, int], list[Any]]
) -> list[Any]:
    related: list[Any] = []
    seen = {str(atom.entity.dxf.handle) for match in run for atom in match.atoms}
    for match in run:
        height = max(match.height, 0.01)
        pad = max(0.02, 0.15 * height)
        expanded = (
            match.low[0] - pad,
            match.low[1] - pad,
            match.high[0] + pad,
            match.high[1] + pad,
        )
        for source_ref in {atom.source_ref for atom in match.atoms}:
            for entity in source_entities.get(source_ref, ()):  # source-mapped only
                if entity.dxftype() not in {"HATCH", "SOLID", "TRACE"}:
                    continue
                handle = str(entity.dxf.handle)
                if handle in seen:
                    continue
                bounds = _entity_bounds(entity)
                if bounds is None:
                    continue
                if (
                    bounds[0] >= expanded[0]
                    and bounds[1] >= expanded[1]
                    and bounds[2] <= expanded[2]
                    and bounds[3] <= expanded[3]
                ):
                    related.append(entity)
                    seen.add(handle)
    return related


def _base_report(mode: str, policy: str) -> dict[str, Any]:
    return {
        "schema": REPORT_SCHEMA,
        "long_text_runs_split": 0,
        "long_text_segments": 0,
        "status": "disabled" if mode == "off" else "pending",
        "mode": mode,
        "policy": policy,
        "engine": {
            "name": "persisted_dxf_topology_template_consensus",
            "runtime_input": "persisted_dxf_only",
            "runtime_pdf_access": False,
            "runtime_font_access": False,
            "ocr_enabled": False,
            "match": "exact_normalized_mask_and_topology_with_locked_font_catalogs",
        },
        "catalog": None,
        "font_catalogs": {
            "requested": 0,
            "loaded": 0,
            "locked": 0,
            "minimum_distinct_han_anchors": MIN_FONT_LOCK_DISTINCT_HAN,
            "minimum_distinct_latin_letters": MIN_FONT_LOCK_DISTINCT_LATIN,
            "entries": [],
        },
        "source_mapped_entities": 0,
        "candidate_outline_entities": 0,
        "candidate_fill_entities": 0,
        "unsupported_outline_entities": 0,
        "structural_candidate_windows": 0,
        "fingerprints_computed": 0,
        "exact_glyph_matches": 0,
        "font_structural_candidate_windows": 0,
        "font_fingerprints_computed": 0,
        "font_catalog_candidate_matches": 0,
        "font_exact_glyph_matches": 0,
        "font_ambiguous_geometry_matches": 0,
        "font_ambiguous_overlap_rejections": 0,
        "font_overlapping_matches_rejected": 0,
        "selected_glyph_matches": 0,
        "font_contained_punctuation_suppressed": 0,
        "font_contained_fill_variants_suppressed": 0,
        "font_han_fragment_resolved_candidates": 0,
        "font_contained_han_fragments_suppressed": 0,
        "font_han_fragment_evidence": [],
        "font_han_fragment_evidence_truncated": 0,
        "font_row_recheck_scans": 0,
        "font_row_recheck_matches": 0,
        "font_row_recheck_evidence": [],
        "font_row_recheck_evidence_truncated": 0,
        "font_enclosed_radical_matches": 0,
        "font_enclosed_radical_half_matches": 0,
        "font_enclosed_radical_rounds": 0,
        "font_enclosed_radical_bridge_matches": 0,
        "font_enclosed_radical_evidence": [],
        "font_enclosed_radical_evidence_truncated": 0,
        "font_enclosed_radical_rejection_counts": {},
        "font_enclosed_radical_rejections": [],
        "font_enclosed_radical_rejections_truncated": 0,
        "font_numeric_variant_masks": 0,
        "font_numeric_stabilized_matches": 0,
        "overlapping_glyph_matches_rejected": 0,
        "unpublished_glyph_matches": 0,
        "rejected_runs": [],
        "accepted": [],
        "emitted_text_entities": 0,
        "suppressed_source_entities": 0,
        "suppressed_outline_entities": 0,
        "suppressed_fill_entities": 0,
        "existing_recovered_text_entities": 0,
        "already_recovered_runs": 0,
        "original_geometry_preserved": True,
    }


def recover_outline_text(
    dxf_path: str | Path,
    page_index: int = 0,
    *,
    mode: str = "auto",
    policy: str = "off_layer",
    catalog_path: str | Path = CATALOG,
    font_catalog_paths: tuple[str | Path, ...] | list[str | Path] = (),
) -> dict[str, Any]:
    """Convert exact, evidence-backed DXF outline runs to editable TEXT."""
    if mode not in {"off", "auto", "required"}:
        raise ValueError(f"unsupported outline Chinese mode: {mode}")
    if policy not in {"keep", "off_layer", "drop"}:
        raise ValueError(f"unsupported outline policy: {policy}")
    if page_index < 0:
        raise ValueError("page_index must be non-negative")
    report = _base_report(mode, policy)
    requested_font_catalogs = tuple(font_catalog_paths)
    report["font_catalogs"]["requested"] = len(requested_font_catalogs)
    if mode == "off":
        return report
    dxf_path = Path(dxf_path)
    try:
        catalog = load_catalog(catalog_path)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        if mode == "required":
            raise GlyphCatalogUnavailable(
                "OUTLINE_TEXT_GLYPH_CATALOG_UNAVAILABLE"
            ) from exc
        report.update(status="unavailable", error=f"{type(exc).__name__}: {exc}")
        return report
    report["catalog"] = {
        "path": str(catalog.path),
        "version": catalog.version,
        "template_set_sha256": catalog.template_set_sha256,
        "templates": len(catalog.templates),
        "characters": len(catalog.characters),
    }
    font_catalogs, font_catalog_entries = _load_font_catalogs(
        requested_font_catalogs, mode
    )
    report["font_catalogs"].update(
        loaded=len(font_catalogs), entries=font_catalog_entries
    )

    doc = ezdxf.readfile(dxf_path)
    atoms, source_entities, atom_stats = _collect_atoms(
        doc, page_index, include_fills=bool(font_catalogs)
    )
    report.update(atom_stats)
    matches, scan_metrics = _scan_matches(atoms, catalog)
    report.update(scan_metrics)
    selected, overlap_rejected = _select_non_overlapping(matches)
    anchor_locks, matching_anchors = _lock_font_catalogs(
        font_catalogs, selected, font_catalog_entries
    )
    anchor_lock_by_id = {lock.catalog.catalog_id: lock for lock in anchor_locks}
    scan_context = [
        anchor_lock_by_id.get(catalog.catalog_id)
        or FontCatalogLock(
            catalog=catalog,
            exact_anchor_occurrences=len(matching_anchors.get(catalog.catalog_id, ())),
            exact_anchor_characters=tuple(
                sorted(
                    {
                        match.char
                        for match in matching_anchors.get(catalog.catalog_id, ())
                    },
                    key=ord,
                )
            ),
            method="candidate",
        )
        for catalog in font_catalogs
    ]
    occupied_indices = {
        index for match in selected for index in range(match.start, match.end)
    }
    font_scan = _FontScanContext() if font_catalogs else None
    font_candidates, font_metrics = _scan_font_catalog_matches(
        atoms, scan_context, occupied_indices, context=font_scan
    )
    report.update(font_metrics)
    locks = _complete_font_catalog_locks(
        font_catalogs,
        anchor_locks,
        matching_anchors,
        font_candidates,
        font_catalog_entries,
    )
    report["font_catalogs"]["locked"] = len(locks)
    restored, recheck_metrics = _recheck_locked_font_rows(
        atoms, locks, font_candidates,
        font_scan if len(font_catalogs) > 1 else None, occupied_indices
    )
    enclosed, enclosure_metrics = _restore_enclosed_radicals(
        locks, font_candidates, font_scan, verified_bridges=restored
    )
    font_candidates = sorted(
        {(m.start, m.end, m.char): m for m in [*font_candidates, *restored, *enclosed]}.values(),
        key=lambda m: m.start,
    )
    from .font_layout import resolve_font_layout_rows

    layout_matches, layout_metrics = resolve_font_layout_rows(
        atoms, font_catalogs, font_candidates, font_scan
    )
    if layout_matches:
        font_candidates = sorted([*font_candidates, *layout_matches], key=lambda m: m.start)
        locks = _complete_font_catalog_locks(
            font_catalogs, locks, matching_anchors, font_candidates, font_catalog_entries
        )
        report["font_catalogs"]["locked"] = len(locks)
    report.update(layout_metrics)
    report.update(recheck_metrics)
    report.update(enclosure_metrics)
    report["font_catalog_candidate_matches"] = len(font_candidates)
    del font_scan
    font_matches = _finalize_font_matches(font_candidates, locks)
    report["font_exact_glyph_matches"] = len(font_matches)
    report["font_numeric_stabilized_matches"] = sum(
        match.font_raster_round_decimals in (3, 5) for match in font_matches
    )
    selected = sorted([*selected, *font_matches], key=lambda match: match.start)
    report["selected_glyph_matches"] = len(selected)
    report["overlapping_glyph_matches_rejected"] = overlap_rejected
    runs = []
    for run in _group_runs(selected):
        segments = _split_long_text_run(run)
        if len(segments) > 1:
            report["long_text_runs_split"] += 1
            report["long_text_segments"] += len(segments)
        runs.extend(segments)
    accepted_runs: list[list[GlyphMatch]] = []
    for run in runs:
        text = "".join(match.char for match in run)
        latin_matches = [match for match in run if _is_english_letter(match.char)]
        publishable, reason = _publishable_text(
            text,
            font_locked=bool(latin_matches)
            and all(match.font_catalog_ids for match in latin_matches),
        )
        if publishable:
            accepted_runs.append(run)
        elif len(report["rejected_runs"]) < 100:
            report["rejected_runs"].append(
                {
                    "text": text,
                    "reason": reason,
                    "template_ids": [match.template.id for match in run],
                }
            )
    report["unpublished_glyph_matches"] = len(selected) - sum(
        len(run) for run in accepted_runs
    )
    existing_keys = _existing_recovery_keys(doc, page_index)
    pending_runs: list[list[GlyphMatch]] = []
    for run in accepted_runs:
        _, low, high, _ = _run_geometry(run)
        if _recovery_key(low, high) in existing_keys:
            report["already_recovered_runs"] += 1
        else:
            pending_runs.append(run)
    accepted_runs = pending_runs
    if not accepted_runs:
        report["status"] = "ok"
        return report

    for name in (TEXT_LAYER, BACKUP_LAYER):
        if name not in doc.layers:
            doc.layers.new(name)
    doc.layers.get(BACKUP_LAYER).off()
    if APPID not in doc.appids:
        doc.appids.add(APPID)
    if TEXT_STYLE not in doc.styles:
        doc.styles.new(TEXT_STYLE, dxfattribs={"font": TEXT_FONT})

    suppressed = 0
    suppressed_fills = 0
    used_handles: set[str] = set()
    for run in accepted_runs:
        text_value, low, high, height = _run_geometry(run)
        run_font_catalog_ids = sorted(
            {catalog_id for match in run for catalog_id in match.font_catalog_ids}
        )
        match_method = (
            "locked_font_catalog_exact_mask_and_topology"
            if run_font_catalog_ids
            else "exact_normalized_mask_and_topology"
        )
        start, end = (float(low[0]), float(low[1])), (float(high[0]), float(low[1]))
        text = doc.modelspace().add_text(
            text_value,
            dxfattribs={"height": height, "layer": TEXT_LAYER, "style": TEXT_STYLE},
        )
        text.set_placement(start, end, align=TextEntityAlignment.FIT)
        text.set_xdata(
            APPID,
            [
                (1000, "dxf_topology_template_consensus"),
                (1070, int(page_index)),
                (1000, text_value[:240]),
                (1000, catalog.version[:240]),
                *((1040, float(value)) for value in (*low, *high)),
                *((1000, match.template.id[:240]) for match in run),
            ],
        )
        outlines = [atom.entity for match in run for atom in match.atoms]
        fills = _related_fill_entities(run, source_entities)
        entities = [*outlines, *fills]
        source_handles = [str(entity.dxf.handle) for entity in entities]
        if policy != "keep":
            for entity in entities:
                handle = str(entity.dxf.handle)
                if handle in used_handles:
                    continue
                used_handles.add(handle)
                if policy == "drop":
                    doc.modelspace().delete_entity(entity)
                else:
                    original_layer = str(entity.dxf.layer)
                    entity.set_xdata(
                        APPID,
                        [
                            (1000, "outline_text_original"),
                            (1000, original_layer[:240]),
                            (1000, str(text.dxf.handle)),
                        ],
                    )
                    entity.dxf.layer = BACKUP_LAYER
                suppressed += 1
                suppressed_fills += int(entity.dxftype() in {"HATCH", "SOLID", "TRACE"})
        report["accepted"].append(
            {
                "text": text_value,
                "bbox_dxf": [float(value) for value in (*low, *high)],
                "height": height,
                "match_method": match_method,
                "template_ids": [match.template.id for match in run],
                "template_fingerprints": [match.template.fingerprint for match in run],
                "font_catalog_ids": run_font_catalog_ids,
                "font_raster_round_decimals": [
                    match.font_raster_round_decimals for match in run
                ],
                "admission_methods": sorted(
                    {match.template.admission for match in run}
                ),
                "minimum_support_locations": min(
                    match.template.support_locations for match in run
                ),
                "minimum_support_documents": min(
                    match.template.support_documents for match in run
                ),
                "source_handles": source_handles,
                "source_seqnos": sorted(
                    {
                        match_atom.source_ref[2]
                        for match in run
                        for match_atom in match.atoms
                    }
                ),
                "matched_outline_entities": len(outlines),
                "related_fill_entities": len(fills),
                "text_handle": str(text.dxf.handle),
            }
        )

    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{dxf_path.stem}.outline-text-",
        suffix=dxf_path.suffix,
        dir=dxf_path.parent,
    )
    os.close(descriptor)
    Path(temporary).unlink(missing_ok=True)
    try:
        doc.saveas(temporary)
        os.replace(temporary, dxf_path)
    finally:
        Path(temporary).unlink(missing_ok=True)
    report.update(
        status="ok",
        emitted_text_entities=len(accepted_runs),
        suppressed_source_entities=suppressed,
        suppressed_outline_entities=suppressed - suppressed_fills,
        suppressed_fill_entities=suppressed_fills,
        original_geometry_preserved=policy != "drop",
    )
    return report
