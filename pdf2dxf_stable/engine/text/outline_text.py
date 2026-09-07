"""Recover audited outlined text from a persisted DXF.

The matcher only reads DXF entities.  A glyph is publishable when its
translation/scale-normalized geometry and topology exactly match a catalog
template with auditable label evidence.  Unknown or ambiguous outlines remain
geometry.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from collections import defaultdict
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import cv2
import ezdxf
import numpy as np
from ezdxf import bbox as dxf_bbox
from ezdxf.enums import TextEntityAlignment

from .font_catalog import (
    FONT_CATALOG_RASTER_DECIMALS,
    FontGlyphCatalog,
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
MIN_FONT_LOCK_DISTINCT_HAN = 3
MAX_OUTLINE_POINTS_PER_ATOM = 4096
RECOVERY_KEY_PRECISION = 6
TEXT_LAYER = "PDF_TEXT_RECOVERED_NOOCR"
BACKUP_LAYER = "PDF_OUTLINE_BACKUP"
APPID = "PDF2DXF_GLYPH"
TEXT_STYLE = "PDF2DXF_CJK_VECTOR"
TEXT_FONT = "simsun.ttc"
SOURCE_APPIDS = ("PDF2DXF15", "PDF2DXF14")
SCALE_TEXT = re.compile(r"^1:(?:0*[1-9]\d*)(?:\.\d+)?$")
HAN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


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


def _entity_paths(entity: Any) -> tuple[np.ndarray, ...]:
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
    doc: Any, page_index: int
) -> tuple[list[OutlineAtom], dict[tuple[str, int, int], list[Any]], dict[str, int]]:
    atoms: list[OutlineAtom] = []
    source_entities: dict[tuple[str, int, int], list[Any]] = defaultdict(list)
    stats = {
        "source_mapped_entities": 0,
        "candidate_outline_entities": 0,
        "unsupported_outline_entities": 0,
        "existing_recovered_text_entities": 0,
    }
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
        paths = _entity_paths(entity)
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
        paths: list[np.ndarray] = []
        point_counts: list[int] = []
        closed_count = 0
        low, high = first.low.copy(), first.high.copy()
        previous_source_sequence = first.source_ref[2]
        for end in range(start, min(len(atoms), start + max_length)):
            atom = atoms[end]
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
            entity_count = end - start + 1
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
    return fingerprint_paths(
        paths, raster_round_decimals=FONT_CATALOG_RASTER_DECIMALS
    )


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
            if _font_signature_key(signature) in template.match_keys:
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
                "locked": is_locked,
                "lock_method": "audited_han_anchors" if is_locked else None,
                "lock_reason": (
                    "distinct_audited_han_exact_masks"
                    if is_locked
                    else "insufficient_distinct_audited_han_exact_masks"
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
) -> tuple[list[GlyphMatch], dict[str, int]]:
    metrics = {
        "font_structural_candidate_windows": 0,
        "font_fingerprints_computed": 0,
        "font_catalog_candidate_matches": 0,
        "font_exact_glyph_matches": 0,
        "font_ambiguous_geometry_matches": 0,
        "font_overlapping_matches_rejected": 0,
    }
    if not locks:
        return [], metrics
    lengths = frozenset(
        length for lock in locks for length in lock.catalog.lengths
    )
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
            entity_count = end - start + 1
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
            if not (
                aspect_bounds[0] * 0.90
                <= aspect_ratio
                <= aspect_bounds[1] * 1.10
            ):
                continue
            signature = _font_fingerprint_paths(paths)
            metrics["font_fingerprints_computed"] += 1
            if signature is None:
                continue
            key = _font_signature_key(signature)
            predictions: list[tuple[str, str]] = []
            ambiguous = False
            for lock in locks:
                values = lock.catalog.lookup.get(key)
                if not values:
                    continue
                if len(values) != 1:
                    ambiguous = True
                    continue
                predictions.append((lock.catalog.catalog_id, values[0]))
            if ambiguous:
                metrics["font_ambiguous_geometry_matches"] += 1
                continue
            characters = {value for _, value in predictions}
            if not predictions:
                continue
            if len(characters) != 1:
                metrics["font_ambiguous_geometry_matches"] += 1
                continue
            char = characters.pop()
            catalog_ids = tuple(sorted({value for value, _ in predictions}))
            support_locations = max(
                1,
                min(
                    lock_by_id[value].exact_anchor_occurrences
                    for value in catalog_ids
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
                )
            )

    # Full Unicode catalogs can contain alternative segmentations whose masks
    # are individually valid.  Reject every overlapping alternative instead of
    # choosing one by score or character frequency.
    rejected: set[int] = set()
    ordered = sorted(enumerate(matches), key=lambda item: (item[1].start, item[1].end))
    active: list[tuple[int, GlyphMatch]] = []
    for index, match in ordered:
        active = [item for item in active if item[1].end > match.start]
        for other_index, other in active:
            if other.end > match.start and match.end > other.start:
                rejected.add(index)
                rejected.add(other_index)
        active.append((index, match))
    accepted = [match for index, match in enumerate(matches) if index not in rejected]
    metrics["font_catalog_candidate_matches"] = len(accepted)
    metrics["font_overlapping_matches_rejected"] = len(rejected)
    return accepted, metrics


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
            if len(distinct_han) < MIN_FONT_LOCK_DISTINCT_HAN:
                continue
            text = "".join(match.char for match in run)
            qualifying_runs.append(
                {
                    "text": text[:96],
                    "glyphs": len(run),
                    "distinct_han_characters": distinct_han[:32],
                }
            )
        if not qualifying_runs:
            continue
        evidence_characters = sorted(
            {
                char
                for run in qualifying_runs
                for char in run["distinct_han_characters"]
            },
            key=ord,
        )
        evidence_occurrences = max(
            int(run["glyphs"]) for run in qualifying_runs
        )
        locks[catalog.catalog_id] = FontCatalogLock(
            catalog=catalog,
            exact_anchor_occurrences=evidence_occurrences,
            exact_anchor_characters=tuple(evidence_characters),
            method="font_cmap_run_consensus",
            evidence_texts=tuple(run["text"] for run in qualifying_runs[:5]),
        )
        entry = entry_by_id[catalog.catalog_id]
        entry.update(
            {
                "status": "locked",
                "locked": True,
                "lock_method": "font_cmap_run_consensus",
                "lock_reason": "distinct_adjacent_han_exact_font_cmap_masks",
                "self_lock_evidence": qualifying_runs[:5],
            }
        )
    return [locks[key] for key in sorted(locks)]


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
            if "font_cmap_run_consensus" in methods
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
        finalized.append(
            replace(
                match,
                template=template,
                font_catalog_ids=tuple(sorted(catalog_ids)),
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
    left_height, right_height = left.height, right.height
    height = max(left_height, right_height, 0.01)
    center_delta = abs((right.low[1] + right.high[1] - left.low[1] - left.high[1]) / 2)
    gap = right.low[0] - left.high[0]
    relative_size = min(left_height, right_height) / max(
        left_height, right_height, 1e-9
    )
    punctuation = left.char in ":-" or right.char in ":-"
    size_ok = relative_size >= (0.03 if punctuation else 0.72)
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


def _publishable_text(text: str) -> tuple[bool, str]:
    if not text or len(text) > 96:
        return False, "unsupported_text_length"
    if SCALE_TEXT.fullmatch(text):
        return True, "reviewed_scale_token"
    if len(HAN.findall(text)) >= 2:
        return True, "multiple_han_glyphs"
    return False, "insufficient_text_run_consensus"


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
    return tuple(
        round(float(value), RECOVERY_KEY_PRECISION) for value in (*low, *high)
    )


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
    seen: set[str] = set()
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
            "entries": [],
        },
        "source_mapped_entities": 0,
        "candidate_outline_entities": 0,
        "unsupported_outline_entities": 0,
        "structural_candidate_windows": 0,
        "fingerprints_computed": 0,
        "exact_glyph_matches": 0,
        "font_structural_candidate_windows": 0,
        "font_fingerprints_computed": 0,
        "font_catalog_candidate_matches": 0,
        "font_exact_glyph_matches": 0,
        "font_ambiguous_geometry_matches": 0,
        "font_overlapping_matches_rejected": 0,
        "selected_glyph_matches": 0,
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
    atoms, source_entities, atom_stats = _collect_atoms(doc, page_index)
    report.update(atom_stats)
    matches, scan_metrics = _scan_matches(atoms, catalog)
    report.update(scan_metrics)
    selected, overlap_rejected = _select_non_overlapping(matches)
    anchor_locks, matching_anchors = _lock_font_catalogs(
        font_catalogs, selected, font_catalog_entries
    )
    anchor_lock_by_id = {
        lock.catalog.catalog_id: lock for lock in anchor_locks
    }
    scan_context = [
        anchor_lock_by_id.get(catalog.catalog_id)
        or FontCatalogLock(
            catalog=catalog,
            exact_anchor_occurrences=len(
                matching_anchors.get(catalog.catalog_id, ())
            ),
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
    font_candidates, font_metrics = _scan_font_catalog_matches(
        atoms, scan_context, occupied_indices
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
    font_matches = _finalize_font_matches(font_candidates, locks)
    report["font_exact_glyph_matches"] = len(font_matches)
    selected = sorted([*selected, *font_matches], key=lambda match: match.start)
    report["selected_glyph_matches"] = len(selected)
    report["overlapping_glyph_matches_rejected"] = overlap_rejected
    runs = _group_runs(selected)
    accepted_runs: list[list[GlyphMatch]] = []
    for run in runs:
        text = "".join(match.char for match in run)
        publishable, reason = _publishable_text(text)
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
            {
                catalog_id
                for match in run
                for catalog_id in match.font_catalog_ids
            }
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
