"""Build and load persisted Unicode glyph catalogs from outline fonts.

Font files are read only by :func:`build_font_catalog`.  Conversion-time
matching loads the resulting archive and continues to consume persisted DXF
entities only.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import os
import string
import struct
import tempfile
import unicodedata
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from itertools import groupby
from pathlib import Path
from typing import Any, Callable, Iterable

import numpy as np
from fontTools.pens.basePen import BasePen

from ...paths import protect_inputs
from ..curve_sampling import cubic_sample_count

FONT_CATALOG_SCHEMA = "pdf2dxf.font_glyph_catalog.v2"
FONT_CATALOG_VERSION = "2"
LEGACY_FONT_CATALOG_SCHEMA = "pdf2dxf.font_glyph_catalog.v1"
FONT_CATALOG_SUFFIX = ".p2dfont"
UNICODE_CJK_VERSION = "17.0"
MASK_SIZE = 56
MASK_BYTES = math.ceil(MASK_SIZE * MASK_SIZE / 8)
FONT_CATALOG_RASTER_DECIMALS = 4
FONT_OUTLINE_POLICY = "raw_and_noncollinear_fill_v1"
LEGACY_FONT_OUTLINE_POLICY = "raw_contours_v1"
MAX_TEMPLATES = 200_000
MAX_VARIANTS = 32
MAX_CONTOURS = 128
# Preserve the legacy variants and include converter sampling at common PDF
# font sizes. A 20 pt em / 0.12 pt curve tolerance is 166.666..., not 166:
# rounding that ratio can change the number of samples in individual curves.
DEFAULT_TOLERANCE_DIVISORS = tuple(
    sorted(
        {
            32,
            64,
            128,
            256,
            1024,
            *(size / 0.12 for size in (8, 9, 10, 12, 14, 16, 18, 20, 24, 28, 32, 36)),
        }
    )
)

# Unicode Han ranges through Extension J, plus Chinese punctuation, radicals,
# strokes, Bopomofo, CJK symbols and printable ASCII used on drawings.
CHINESE_RANGES = (
    (0x0021, 0x007E),
    (0x2E80, 0x303F),
    (0x3100, 0x312F),
    (0x31A0, 0x31BF),
    (0x31C0, 0x31EF),
    (0x3200, 0x33FF),
    (0x3400, 0x4DBF),
    (0x4E00, 0x9FFF),
    (0xF900, 0xFAFF),
    (0xFE10, 0xFE1F),
    (0xFE30, 0xFE4F),
    (0xFE50, 0xFE6F),
    (0xFF01, 0xFF65),
    (0xFFE0, 0xFFE6),
    (0x16FE0, 0x16FFF),
    (0x20000, 0x2A6DF),
    (0x2A700, 0x2B73F),
    (0x2B740, 0x2B81F),
    (0x2B820, 0x2CEAF),
    (0x2CEB0, 0x2EBEF),
    (0x2EBF0, 0x2EE5F),
    (0x2F800, 0x2FA1F),
    (0x30000, 0x3134F),
    (0x31350, 0x323AF),
    (0x323B0, 0x3347F),
)
CHARSET_RANGES = {"chinese": CHINESE_RANGES, "english": ((0x0021, 0x007E),)}
HAN_RANGES = (
    (0x3400, 0x4DBF),
    (0x4E00, 0x9FFF),
    (0xF900, 0xFAFF),
    (0x20000, 0x2A6DF),
    (0x2A700, 0x2B73F),
    (0x2B740, 0x2B81F),
    (0x2B820, 0x2CEAF),
    (0x2CEB0, 0x2EBEF),
    (0x2EBF0, 0x2EE5F),
    (0x2F800, 0x2FA1F),
    (0x30000, 0x3134F),
    (0x31350, 0x323AF),
    (0x323B0, 0x3347F),
)
ARRAY_NAMES = (
    "aspect_ratios.npy",
    "canonical_masks.npy",
    "closed_counts.npy",
    "codepoints.npy",
    "entity_counts.npy",
    "variant_digests.npy",
)


class FontCatalogError(RuntimeError):
    """Raised when a font catalog cannot be built or verified."""


@dataclass(frozen=True, slots=True)
class FontGlyphTemplate:
    char: str
    codepoint: int
    entity_count: int
    closed_count: int
    aspect_ratio: float
    canonical_mask: bytes
    match_digests: tuple[bytes, ...]

    @property
    def match_keys(self) -> tuple[tuple[int, int, bytes], ...]:
        return tuple(
            (self.entity_count, self.closed_count, digest)
            for digest in self.match_digests
        )


@dataclass(slots=True)
class FontGlyphCatalog:
    path: Path
    schema: str
    catalog_id: str
    font: dict[str, Any]
    charset: str
    unicode_cjk_version: str
    template_set_sha256: str
    raster_round_decimals: int
    outline_policy: str
    tolerance_divisors: tuple[float, ...]
    templates: tuple[FontGlyphTemplate, ...]
    by_char: dict[str, FontGlyphTemplate]
    templates_by_label: dict[str, tuple[FontGlyphTemplate, ...]]
    lookup: dict[tuple[int, int, bytes], tuple[str, ...]]
    structures: dict[tuple[int, int], tuple[float, float]]
    lengths: frozenset[int]
    characters: frozenset[str]
    recognition_characters: frozenset[str]
    normalized_alias_mappings: int
    ambiguous_keys: int
    fully_ambiguous_characters: int

    def matching_characters(
        self, key: tuple[int, int, bytes], aspect_ratio: float
    ) -> tuple[str, ...]:
        # Thin outlines can rasterize identically despite different proportions
        # (e.g. lowercase l and |). Check each actual cmap template, including
        # NFKC aliases, rather than a combined aspect envelope across the font.
        return tuple(
            char
            for char in self.lookup.get(key, ())
            if any(
                0.90 <= aspect_ratio / template.aspect_ratio <= 1.10
                and key in template.match_keys
                for template in self.templates_by_label[char]
            )
        )


def _in_ranges(codepoint: int, ranges: tuple[tuple[int, int], ...]) -> bool:
    return any(start <= codepoint <= end for start, end in ranges)


def _is_lower_hex(value: Any, length: int) -> bool:
    return (
        isinstance(value, str)
        and len(value) == length
        and all(character in "0123456789abcdef" for character in value)
    )


def is_han_character(value: str) -> bool:
    return len(value) == 1 and _in_ranges(ord(value), HAN_RANGES)


def _canonical_catalog_character(codepoint: int) -> str:
    char = chr(codepoint)
    normalized = unicodedata.normalize("NFKC", char)
    return normalized if len(normalized) == 1 else char


def font_mask_digest(packed_mask: bytes, entity_count: int, closed_count: int) -> bytes:
    """Hash a normalized mask and topology without polyline sample counts."""
    if len(packed_mask) != MASK_BYTES:
        raise ValueError("invalid normalized glyph mask size")
    if not 0 < entity_count <= MAX_CONTOURS or not 0 <= closed_count <= entity_count:
        raise ValueError("invalid glyph topology")
    payload = packed_mask + struct.pack("<HH", entity_count, closed_count)
    return hashlib.blake2b(payload, digest_size=16).digest()


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _font_name(font: Any, name_id: int) -> str:
    table = font.get("name")
    if table is None:
        return ""
    candidates: list[tuple[int, int, int, str]] = []
    for record in table.names:
        if record.nameID != name_id:
            continue
        try:
            value = record.toUnicode().strip()
        except Exception:  # noqa: BLE001
            continue
        if value:
            language_rank = 0 if record.langID in (0x0409, 0) else 1
            candidates.append(
                (language_rank, record.platformID, record.platEncID, value)
            )
    return min(candidates)[-1] if candidates else ""


def _font_metadata(font: Any, path: Path, face_index: int, face_count: int) -> dict:
    head = font.get("head")
    units_per_em = int(getattr(head, "unitsPerEm", 0) or 0)
    if not 16 <= units_per_em <= 16384:
        raise FontCatalogError("font has an invalid units-per-em value")
    return {
        "source_file": path.name,
        "sha256": _sha256_path(path),
        "face_index": face_index,
        "face_count": face_count,
        "family": _font_name(font, 1),
        "subfamily": _font_name(font, 2),
        "full_name": _font_name(font, 4),
        "postscript_name": _font_name(font, 6),
        "version": _font_name(font, 5),
        "copyright": _font_name(font, 0),
        "license": _font_name(font, 13),
        "license_url": _font_name(font, 14),
        "units_per_em": units_per_em,
    }


def _font_face_count(path: Path) -> int:
    from fontTools.ttLib import TTCollection

    with path.open("rb") as stream:
        is_collection = stream.read(4) == b"ttcf"
    if not is_collection:
        return 1
    collection = TTCollection(str(path), lazy=True)
    try:
        return len(collection.fonts)
    finally:
        collection.close()


def list_font_faces(font_path: str | Path) -> list[dict[str, Any]]:
    """Return deterministic face metadata for a TTF, OTF, TTC or OTC file."""
    from fontTools.ttLib import TTFont

    path = Path(font_path).expanduser().resolve()
    if not path.is_file():
        raise FontCatalogError(f"font file does not exist: {path}")
    count = _font_face_count(path)
    faces: list[dict[str, Any]] = []
    for face_index in range(count):
        font = TTFont(
            str(path),
            fontNumber=face_index,
            lazy=True,
            recalcBBoxes=False,
            recalcTimestamp=False,
        )
        try:
            metadata = _font_metadata(font, path, face_index, count)
            cmap = font.getBestCmap() or {}
            metadata["mapped_codepoints"] = len(cmap)
            metadata["mapped_han_codepoints"] = sum(
                _in_ranges(int(codepoint), HAN_RANGES) for codepoint in cmap
            )
            faces.append(metadata)
        finally:
            font.close()
    return faces


def _cubic_flatness(
    p0: tuple[float, float],
    c1: tuple[float, float],
    c2: tuple[float, float],
    p1: tuple[float, float],
) -> float:
    start = np.asarray(p0, dtype=np.float64)
    end = np.asarray(p1, dtype=np.float64)
    vector = end - start
    length = float(np.linalg.norm(vector))
    if length <= 1e-12:
        return max(
            float(np.linalg.norm(np.asarray(c1, dtype=np.float64) - start)),
            float(np.linalg.norm(np.asarray(c2, dtype=np.float64) - start)),
        )
    first = np.asarray(c1, dtype=np.float64) - start
    second = np.asarray(c2, dtype=np.float64) - start
    return max(
        abs(float(vector[0] * first[1] - vector[1] * first[0])) / length,
        abs(float(vector[0] * second[1] - vector[1] * second[0])) / length,
    )


def _flatten_cubic(
    p0: tuple[float, float],
    c1: tuple[float, float],
    c2: tuple[float, float],
    p1: tuple[float, float],
    tolerance: float,
    max_samples: int = 96,
) -> list[tuple[float, float]]:
    flatness = _cubic_flatness(p0, c1, c2, p1)
    samples = cubic_sample_count(flatness, tolerance, max_samples)
    values = []
    for index in range(samples):
        t = index / (samples - 1)
        mt = 1.0 - t
        x = mt**3 * p0[0] + 3 * mt**2 * t * c1[0] + 3 * mt * t**2 * c2[0] + t**3 * p1[0]
        y = mt**3 * p0[1] + 3 * mt**2 * t * c1[1] + 3 * mt * t**2 * c2[1] + t**3 * p1[1]
        values.append((float(x), float(y)))
    return values


def _same_point(left: tuple[float, float], right: tuple[float, float]) -> bool:
    return math.dist(left, right) <= 1e-9


class _FlattenPen(BasePen):
    """FontTools segment pen that emits converter-compatible polylines."""

    def __init__(self, glyph_set: Any, tolerance: float):
        super().__init__(glyph_set)
        self.tolerance = float(tolerance)
        self.paths: list[np.ndarray] = []
        self._current: list[tuple[float, float]] = []

    def _flush(self, *, close: bool) -> None:
        if (
            close
            and self._current
            and not _same_point(self._current[0], self._current[-1])
        ):
            self._current.append(self._current[0])
        compact: list[tuple[float, float]] = []
        for point in self._current:
            if not compact or not _same_point(compact[-1], point):
                compact.append(point)
        if len(compact) >= 2:
            self.paths.append(np.asarray(compact, dtype=np.float64))
        self._current = []

    def _moveTo(self, point) -> None:  # noqa: N802
        if self._current:
            self._flush(close=False)
        self._current = [(float(point[0]), float(point[1]))]

    def _lineTo(self, point) -> None:  # noqa: N802
        self._current.append((float(point[0]), float(point[1])))

    def _curveToOne(self, control1, control2, end) -> None:  # noqa: N802
        start = tuple(map(float, self._getCurrentPoint()))
        points = _flatten_cubic(
            start,
            tuple(map(float, control1)),
            tuple(map(float, control2)),
            tuple(map(float, end)),
            self.tolerance,
        )
        self._current.extend(points[1:])

    def _closePath(self) -> None:  # noqa: N802
        self._flush(close=True)

    def _endPath(self) -> None:  # noqa: N802
        self._flush(close=False)


def _glyph_paths(recording: Any, glyph_set: Any, tolerance: float) -> list[np.ndarray]:
    pen = _FlattenPen(glyph_set, tolerance)
    recording.replay(pen)
    if pen._current:
        pen._flush(close=False)
    return pen.paths


def _has_font_fill(path: np.ndarray) -> bool:
    """Exclude only exactly collinear closed contours, which have no font ink.

    Do not use signed area: a self-intersecting contour can have cancelling
    signed areas and still contain filled regions. No size tolerance is used,
    so thin real contours remain part of the template's topology.
    """
    if len(path) < 3 or not np.array_equal(path[0], path[-1]):
        return True
    offsets = path[1:-1] - path[0]
    direction = offsets[np.argmax(np.sum(offsets * offsets, axis=1))]
    return bool(np.any(offsets[:, 0] * direction[1] != offsets[:, 1] * direction[0]))


def _glyph_variant_row(signatures: list[Any]) -> tuple[Any, ...]:
    if not signatures or any(signature is None for signature in signatures):
        raise ValueError("glyph has no two-dimensional outline")
    canonical = signatures[-1]
    if (
        canonical.entity_count > MAX_CONTOURS
        or canonical.closed_count != canonical.entity_count
        or any(
            item.entity_count != canonical.entity_count
            or item.closed_count != canonical.closed_count
            for item in signatures
        )
    ):
        raise ValueError("glyph topology is unsupported")
    return (
        canonical.entity_count,
        canonical.closed_count,
        canonical.aspect_ratio,
        bytes.fromhex(canonical.mask_hex),
        tuple(
            font_mask_digest(
                bytes.fromhex(item.mask_hex), item.entity_count, item.closed_count
            )
            for item in signatures
        ),
    )


def extract_font_glyph_paths(
    font_path: str | Path,
    char: str,
    *,
    face_index: int = 0,
    tolerance_divisor: int = 1024,
) -> tuple[np.ndarray, ...]:
    """Extract one glyph as normalized-source polylines for tests and audits."""
    from fontTools.pens.recordingPen import DecomposingRecordingPen
    from fontTools.ttLib import TTFont

    if len(char) != 1:
        raise ValueError("char must contain exactly one Unicode character")
    path = Path(font_path).expanduser().resolve()
    count = _font_face_count(path)
    if not 0 <= face_index < count:
        raise FontCatalogError(
            f"font face index {face_index} is outside 0..{count - 1}"
        )
    font = TTFont(
        str(path),
        fontNumber=face_index,
        lazy=False,
        recalcBBoxes=False,
        recalcTimestamp=False,
    )
    try:
        cmap = font.getBestCmap() or {}
        glyph_name = cmap.get(ord(char))
        if glyph_name is None:
            return ()
        glyph_set = font.getGlyphSet()
        recording = DecomposingRecordingPen(glyph_set)
        glyph_set[glyph_name].draw(recording)
        units_per_em = int(font["head"].unitsPerEm)
        return tuple(
            _glyph_paths(
                recording,
                glyph_set,
                units_per_em / max(int(tolerance_divisor), 1),
            )
        )
    finally:
        font.close()


def _npy_bytes(array: np.ndarray) -> bytes:
    stream = io.BytesIO()
    np.save(stream, np.ascontiguousarray(array), allow_pickle=False)
    return stream.getvalue()


def _dataset_digest(arrays: dict[str, np.ndarray]) -> str:
    digest = hashlib.sha256()
    for name in sorted(arrays):
        array = np.ascontiguousarray(arrays[name])
        digest.update(name.encode("ascii"))
        digest.update(array.dtype.str.encode("ascii"))
        digest.update(json.dumps(array.shape, separators=(",", ":")).encode("ascii"))
        digest.update(array.tobytes())
    return digest.hexdigest()


def _catalog_identifier(
    font_sha256: str,
    face_index: int,
    template_set_sha256: str,
    *,
    schema: str = FONT_CATALOG_SCHEMA,
) -> str:
    payload = (
        font_sha256
        + f":{face_index}:"
        + template_set_sha256
        + f":{schema}:NFKC_single_codepoint:"
        + UNICODE_CJK_VERSION
        + json.dumps(CHINESE_RANGES, separators=(",", ":"))
    )
    return hashlib.sha256(payload.encode("ascii")).hexdigest()[:24]


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    info.create_system = 3
    return info


def _write_catalog_archive(
    output: Path, manifest: dict[str, Any], array_payloads: dict[str, bytes]
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{output.name}.", suffix=".tmp", dir=output.parent
    )
    os.close(descriptor)
    try:
        with zipfile.ZipFile(
            temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
        ) as archive:
            archive.writestr(
                _zip_info("manifest.json"),
                json.dumps(
                    manifest,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8"),
            )
            for name in sorted(array_payloads):
                archive.writestr(_zip_info(name), array_payloads[name])
        os.replace(temporary, output)
    finally:
        Path(temporary).unlink(missing_ok=True)


def build_font_catalog(
    font_path: str | Path,
    output: str | Path,
    *,
    face_index: int = 0,
    charset: str = "chinese",
    codepoints: Iterable[int] | None = None,
    tolerance_divisors: Iterable[float] = DEFAULT_TOLERANCE_DIVISORS,
    progress: Callable[[int, int], None] | None = None,
) -> dict[str, Any]:
    """Persist every drawable requested Unicode mapping from one font face."""
    from fontTools.pens.recordingPen import DecomposingRecordingPen
    from fontTools.ttLib import TTFont

    if charset not in {*CHARSET_RANGES, "all"}:
        raise ValueError("charset must be chinese, english or all")
    source = Path(font_path).expanduser().resolve()
    destination = Path(output).expanduser().resolve()
    if not source.is_file():
        raise FontCatalogError(f"font file does not exist: {source}")
    protect_inputs(destination, [source])
    if destination.suffix.lower() != FONT_CATALOG_SUFFIX:
        raise FontCatalogError("font catalog output must end in .p2dfont")
    face_count = _font_face_count(source)
    if not 0 <= face_index < face_count:
        raise FontCatalogError(
            f"font face index {face_index} is outside 0..{face_count - 1}"
        )
    divisors = tuple(sorted({float(value) for value in tolerance_divisors}))
    if (
        not divisors
        or len(divisors) > MAX_VARIANTS
        or not all(math.isfinite(value) for value in divisors)
        or divisors[0] < 8
        or divisors[-1] > 8192
    ):
        raise ValueError("invalid font outline tolerance divisors")

    font = TTFont(
        str(source),
        fontNumber=face_index,
        lazy=False,
        recalcBBoxes=False,
        recalcTimestamp=False,
    )
    try:
        metadata = _font_metadata(font, source, face_index, face_count)
        units_per_em = int(metadata["units_per_em"])
        cmap = font.getBestCmap() or {}
        if codepoints is None:
            requested = [
                int(value)
                for value in cmap
                if charset == "all" or _in_ranges(int(value), CHARSET_RANGES[charset])
            ]
            catalog_charset = charset
        else:
            requested = [int(value) for value in codepoints if int(value) in cmap]
            catalog_charset = "explicit"
        requested = sorted(
            {
                value
                for value in requested
                if 0 <= value <= 0x10FFFF and not 0xD800 <= value <= 0xDFFF
            }
        )
        if len(requested) > MAX_TEMPLATES:
            raise FontCatalogError("font catalog exceeds the template safety limit")
        glyph_set = font.getGlyphSet()
        cache: dict[str, list[tuple[Any, ...]] | None] = {}
        skip_reasons: dict[str, str] = {}
        fill_skip_reasons: dict[str, str] = {}
        skipped_fill_variants: list[dict[str, Any]] = []
        skipped_mappings: list[dict[str, Any]] = []
        rows: list[tuple[int, int, int, float, bytes, tuple[bytes, ...]]] = []
        skipped = 0
        for index, codepoint in enumerate(requested):
            glyph_name = cmap[codepoint]
            cached = cache.get(glyph_name)
            if glyph_name not in cache:
                try:
                    recording = DecomposingRecordingPen(glyph_set)
                    glyph_set[glyph_name].draw(recording)
                    signatures = []
                    fill_signatures = []
                    has_empty_contours = False
                    from .outline_text import fingerprint_paths

                    for divisor in divisors:
                        paths = _glyph_paths(
                            recording, glyph_set, units_per_em / divisor
                        )
                        signature = fingerprint_paths(
                            paths,
                            raster_round_decimals=FONT_CATALOG_RASTER_DECIMALS,
                        )
                        signatures.append(signature)
                        filled_paths = [path for path in paths if _has_font_fill(path)]
                        has_empty_contours |= len(filled_paths) != len(paths)
                        fill_signatures.append(
                            fingerprint_paths(
                                filled_paths,
                                raster_round_decimals=FONT_CATALOG_RASTER_DECIMALS,
                            )
                            if len(filled_paths) != len(paths)
                            else signature
                        )
                    # The primary representation remains the original stroke
                    # topology. An additional fill representation must not replace it.
                    cached = [_glyph_variant_row(signatures)]
                    if has_empty_contours:
                        try:
                            alternate = _glyph_variant_row(fill_signatures)
                            if alternate[0] < cached[0][0]:
                                cached.append(alternate)
                            else:
                                raise ValueError(
                                    "fill topology did not remove a contour"
                                )
                        except ValueError as exc:
                            fill_skip_reasons[glyph_name] = str(exc)
                except Exception as exc:  # noqa: BLE001 - individual glyph boundary
                    cached = None
                    skip_reasons[glyph_name] = f"{type(exc).__name__}: {exc}"[:240]
                cache[glyph_name] = cached
            if cached is None:
                skipped += 1
                skipped_mappings.append(
                    {"codepoint": codepoint, "reason": skip_reasons[glyph_name]}
                )
                if progress is not None:
                    progress(index + 1, len(requested))
                continue
            rows.extend((codepoint, *variant) for variant in cached)
            if glyph_name in fill_skip_reasons:
                skipped_fill_variants.append(
                    {"codepoint": codepoint, "reason": fill_skip_reasons[glyph_name]}
                )
            if progress is not None:
                progress(index + 1, len(requested))
    finally:
        font.close()

    if not rows:
        raise FontCatalogError("font has no drawable characters in the requested set")
    count = len(rows)
    mapped_count = len({row[0] for row in rows})
    codepoint_array = np.asarray([row[0] for row in rows], dtype="<u4")
    entity_array = np.asarray([row[1] for row in rows], dtype="<u2")
    closed_array = np.asarray([row[2] for row in rows], dtype="<u2")
    aspect_array = np.asarray([row[3] for row in rows], dtype="<f4")
    mask_array = np.frombuffer(
        b"".join(row[4] for row in rows), dtype=np.uint8
    ).reshape(count, MASK_BYTES)
    digest_array = np.frombuffer(
        b"".join(digest for row in rows for digest in row[5]), dtype=np.uint8
    ).reshape(count, len(divisors), 16)
    arrays = {
        "aspect_ratios.npy": aspect_array,
        "canonical_masks.npy": mask_array,
        "closed_counts.npy": closed_array,
        "codepoints.npy": codepoint_array,
        "entity_counts.npy": entity_array,
        "variant_digests.npy": digest_array,
    }
    template_set_sha256 = _dataset_digest(arrays)
    catalog_id = _catalog_identifier(
        metadata["sha256"], face_index, template_set_sha256
    )
    collision_map: dict[tuple[int, int, bytes], set[str]] = defaultdict(set)
    canonical_characters = {_canonical_catalog_character(row[0]) for row in rows}
    for row in rows:
        for digest in set(row[5]):
            collision_map[(row[1], row[2], digest)].add(
                _canonical_catalog_character(row[0])
            )
    ambiguous_keys = sum(len(values) > 1 for values in collision_map.values())
    fully_ambiguous_characters = sum(
        all(
            len(collision_map[(row[1], row[2], digest)]) > 1
            for row in variants
            for digest in set(row[5])
        )
        for _, variants in groupby(rows, key=lambda row: row[0])
    )
    array_payloads = {name: _npy_bytes(value) for name, value in arrays.items()}
    manifest = {
        "schema": FONT_CATALOG_SCHEMA,
        "catalog_version": FONT_CATALOG_VERSION,
        "catalog_id": catalog_id,
        "runtime_input": "persisted_dxf_only",
        "runtime_font_access": False,
        "runtime_pdf_access": False,
        "runtime_ocr": False,
        "unicode_label_normalization": "NFKC_single_codepoint",
        "builder_input": "ttf_otf_ttc_otc_outline_font",
        "unicode_cjk_version": UNICODE_CJK_VERSION,
        "charset": catalog_charset,
        "unicode_ranges": [list(value) for value in CHARSET_RANGES[catalog_charset]]
        if catalog_charset in CHARSET_RANGES
        else None,
        "mask_size": MASK_SIZE,
        "raster_round_decimals": FONT_CATALOG_RASTER_DECIMALS,
        "outline_policy": FONT_OUTLINE_POLICY,
        "tolerance_divisors": list(divisors),
        "font": metadata,
        "requested_mapped_codepoints": len(requested),
        "template_count": count,
        "mapped_codepoint_count": mapped_count,
        "fill_variant_count": count - mapped_count,
        "representation_order": "raw_then_fill",
        "recognition_character_count": len(canonical_characters),
        "normalized_alias_mappings": mapped_count - len(canonical_characters),
        "han_template_count": sum(
            _in_ranges(int(value), HAN_RANGES) for value in set(codepoint_array)
        ),
        "skipped_non_outline_mappings": skipped,
        "ambiguous_geometry_keys": ambiguous_keys,
        "fully_ambiguous_characters": fully_ambiguous_characters,
        "template_set_sha256": template_set_sha256,
        "arrays": {
            name: {
                "sha256": hashlib.sha256(payload).hexdigest(),
                "size_bytes": len(payload),
            }
            for name, payload in sorted(array_payloads.items())
        },
    }
    _write_catalog_archive(destination, manifest, array_payloads)
    return {
        **manifest,
        "path": str(destination),
        "size_bytes": destination.stat().st_size,
        "sha256": _sha256_path(destination),
        # Build diagnostics stay outside the bounded runtime manifest.
        "skipped_mappings": skipped_mappings,
        "skipped_fill_variants": skipped_fill_variants,
    }


def _load_npy(payload: bytes, shape: tuple[int, ...], dtype: np.dtype) -> np.ndarray:
    """Validate the small header and exact byte count before constructing an array."""
    stream = io.BytesIO(payload)
    version = np.lib.format.read_magic(stream)
    if version == (1, 0):
        actual_shape, fortran, actual_dtype = np.lib.format.read_array_header_1_0(
            stream, max_header_size=4096
        )
    elif version == (2, 0):
        actual_shape, fortran, actual_dtype = np.lib.format.read_array_header_2_0(
            stream, max_header_size=4096
        )
    else:
        raise FontCatalogError("font catalog array has an unsupported NPY version")
    if actual_shape != shape or actual_dtype != dtype or fortran:
        raise FontCatalogError("font catalog array shape or type mismatch")
    size = math.prod(shape) * dtype.itemsize
    if len(payload) - stream.tell() != size:
        raise FontCatalogError("font catalog array payload length mismatch")
    return np.frombuffer(payload, dtype=dtype, offset=stream.tell()).reshape(shape)


def load_font_catalog(path: str | Path) -> FontGlyphCatalog:
    """Load and fully verify a persisted font catalog without opening the font."""
    try:
        return _load_font_catalog(path)
    except FontCatalogError:
        raise
    except (
        ValueError,
        TypeError,
        KeyError,
        OverflowError,
        EOFError,
        OSError,
        zipfile.BadZipFile,
        RuntimeError,
    ) as exc:
        raise FontCatalogError(f"invalid font catalog: {exc}") from exc


def _load_font_catalog(path: str | Path) -> FontGlyphCatalog:
    source = Path(path).expanduser().resolve()
    with zipfile.ZipFile(source, "r") as archive:
        members = archive.namelist()
        names = set(members)
        expected = {"manifest.json", *ARRAY_NAMES}
        if len(members) != len(expected) or names != expected:
            raise FontCatalogError("font catalog contains an unexpected file set")
        manifest_info = archive.getinfo("manifest.json")
        if manifest_info.file_size > 1024 * 1024:
            raise FontCatalogError("font catalog manifest is too large")
        manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
        if not isinstance(manifest, dict):
            raise FontCatalogError("font catalog manifest must be an object")
        integer_fields = (
            "mask_size",
            "raster_round_decimals",
            "template_count",
            "ambiguous_geometry_keys",
            "fully_ambiguous_characters",
            "recognition_character_count",
            "normalized_alias_mappings",
            "requested_mapped_codepoints",
            "skipped_non_outline_mappings",
            "han_template_count",
        )
        if any(
            type(manifest.get(key)) is not int or manifest[key] < 0
            for key in integer_fields
        ):
            raise FontCatalogError("font catalog counts must be nonnegative integers")
        if (
            (manifest.get("schema"), manifest.get("catalog_version"))
            not in (
                (FONT_CATALOG_SCHEMA, FONT_CATALOG_VERSION),
                (LEGACY_FONT_CATALOG_SCHEMA, "1"),
            )
            or manifest.get("runtime_input") != "persisted_dxf_only"
            or manifest.get("runtime_font_access") is not False
            or manifest.get("runtime_pdf_access") is not False
            or manifest.get("runtime_ocr") is not False
            or manifest.get("unicode_label_normalization") != "NFKC_single_codepoint"
            or manifest.get("unicode_cjk_version") != UNICODE_CJK_VERSION
            or (
                manifest.get("outline_policy") != FONT_OUTLINE_POLICY
                or manifest.get("representation_order") != "raw_then_fill"
            )
            and manifest.get("schema") == FONT_CATALOG_SCHEMA
            or manifest.get("outline_policy", LEGACY_FONT_OUTLINE_POLICY)
            != LEGACY_FONT_OUTLINE_POLICY
            and manifest.get("schema") == LEGACY_FONT_CATALOG_SCHEMA
            or int(manifest.get("mask_size", 0)) != MASK_SIZE
            or int(manifest.get("raster_round_decimals", -1))
            != FONT_CATALOG_RASTER_DECIMALS
        ):
            raise FontCatalogError("font catalog has an unsupported runtime contract")
        is_v2 = manifest["schema"] == FONT_CATALOG_SCHEMA
        count = int(manifest.get("template_count", 0))
        raw_divisors = manifest.get("tolerance_divisors")
        if not isinstance(raw_divisors, list) or any(
            type(value) not in (int, float)
            or not math.isfinite(value)
            or not 8 <= value <= 8192
            for value in raw_divisors
        ):
            raise FontCatalogError("font catalog tolerance divisors are invalid")
        divisors = tuple(raw_divisors)
        charset = manifest.get("charset")
        expected_ranges = (
            [list(value) for value in CHARSET_RANGES[charset]]
            if charset in CHARSET_RANGES
            else None
        )
        if (
            not 0 < count <= MAX_TEMPLATES * (2 if is_v2 else 1)
            or not divisors
            or len(divisors) > MAX_VARIANTS
            or tuple(sorted(set(divisors))) != divisors
            or charset not in {*CHARSET_RANGES, "all", "explicit"}
            or manifest.get("unicode_ranges") != expected_ranges
        ):
            raise FontCatalogError("font catalog dimensions are invalid")
        expected_shapes = {
            "aspect_ratios.npy": (count,),
            "canonical_masks.npy": (count, MASK_BYTES),
            "closed_counts.npy": (count,),
            "codepoints.npy": (count,),
            "entity_counts.npy": (count,),
            "variant_digests.npy": (count, len(divisors), 16),
        }
        expected_dtypes = {
            "aspect_ratios.npy": np.dtype("<f4"),
            "canonical_masks.npy": np.dtype("u1"),
            "closed_counts.npy": np.dtype("<u2"),
            "codepoints.npy": np.dtype("<u4"),
            "entity_counts.npy": np.dtype("<u2"),
            "variant_digests.npy": np.dtype("u1"),
        }
        arrays = {}
        declared_arrays = manifest.get("arrays")
        if not isinstance(declared_arrays, dict) or set(declared_arrays) != set(
            ARRAY_NAMES
        ):
            raise FontCatalogError("font catalog array manifest is invalid")
        for name in ARRAY_NAMES:
            info = archive.getinfo(name)
            declared = declared_arrays[name]
            if (
                not isinstance(declared, dict)
                or type(declared.get("size_bytes")) is not int
                or info.file_size != declared["size_bytes"]
                or info.file_size
                > (
                    math.prod(expected_shapes[name]) * expected_dtypes[name].itemsize
                    + 4096
                )
            ):
                raise FontCatalogError(f"font catalog array size mismatch: {name}")
            payload = archive.read(name)
            if hashlib.sha256(payload).hexdigest() != declared.get("sha256"):
                raise FontCatalogError(f"font catalog array hash mismatch: {name}")
            arrays[name] = _load_npy(
                payload, expected_shapes[name], expected_dtypes[name]
            )
    if _dataset_digest(arrays) != manifest.get("template_set_sha256"):
        raise FontCatalogError("font catalog template set hash mismatch")

    codepoints = arrays["codepoints.npy"]
    entities = arrays["entity_counts.npy"]
    closed = arrays["closed_counts.npy"]
    aspects = arrays["aspect_ratios.npy"]
    masks = arrays["canonical_masks.npy"]
    digests = arrays["variant_digests.npy"]
    unique_codepoints, repetitions = np.unique(codepoints, return_counts=True)
    duplicates = np.flatnonzero(codepoints[1:] == codepoints[:-1])
    if (
        not bool(np.all(codepoints[1:] >= codepoints[:-1]))
        or len(unique_codepoints) > MAX_TEMPLATES
        or bool(np.any(repetitions > (2 if is_v2 else 1)))
        or is_v2
        and (
            bool(np.any(entities[duplicates + 1] >= entities[duplicates]))
            or bool(np.any(closed != entities))
            or type(manifest.get("mapped_codepoint_count")) is not int
            or manifest["mapped_codepoint_count"] != len(unique_codepoints)
            or type(manifest.get("fill_variant_count")) is not int
            or manifest["fill_variant_count"] != len(duplicates)
        )
    ):
        raise FontCatalogError("font catalog glyph representations are invalid")
    if (
        bool(np.any(codepoints > 0x10FFFF))
        or bool(np.any((codepoints >= 0xD800) & (codepoints <= 0xDFFF)))
        or bool(np.any(entities == 0))
        or bool(np.any(entities > MAX_CONTOURS))
        or bool(np.any(closed > entities))
        or not bool(np.all(np.isfinite(aspects)))
        or bool(np.any(aspects <= 0))
    ):
        raise FontCatalogError("font catalog contains invalid glyph rows")

    templates: list[FontGlyphTemplate] = []
    lookup: dict[tuple[int, int, bytes], tuple[str, ...]] = {}
    ambiguous_labels: dict[tuple[int, int, bytes], set[str]] = {}
    structures_lists: dict[tuple[int, int], list[float]] = defaultdict(list)
    digest_row = struct.Struct("16s" * len(divisors))
    for index in range(count):
        entity_count = int(entities[index])
        closed_count = int(closed[index])
        canonical_mask = bytes(masks[index])
        match_digests = tuple(
            dict.fromkeys(digest_row.unpack(digests[index].tobytes()))
        )
        canonical_digest = font_mask_digest(canonical_mask, entity_count, closed_count)
        if canonical_digest not in match_digests:
            raise FontCatalogError("font catalog canonical mask is not a match variant")
        codepoint = int(codepoints[index])
        char = chr(codepoint)
        canonical_char = _canonical_catalog_character(codepoint)
        template = FontGlyphTemplate(
            char=char,
            codepoint=codepoint,
            entity_count=entity_count,
            closed_count=closed_count,
            aspect_ratio=float(aspects[index]),
            canonical_mask=canonical_mask,
            match_digests=match_digests,
        )
        templates.append(template)
        structures_lists[(entity_count, closed_count)].append(template.aspect_ratio)
        # Most keys have one label. Share its immutable tuple across this glyph's
        # variants instead of allocating a temporary set for every geometry key.
        single_label = (canonical_char,)
        for digest in match_digests:
            key = (entity_count, closed_count, digest)
            labels = lookup.get(key)
            if labels is None:
                lookup[key] = single_label
            elif canonical_char != labels[0]:
                # Accumulate collisions in a set and sort once, even when many
                # cmap aliases share a geometry. Avoid quadratic tuple copying.
                conflicts = ambiguous_labels.get(key)
                if conflicts is None:
                    ambiguous_labels[key] = {labels[0], canonical_char}
                else:
                    conflicts.add(canonical_char)
    for key, labels in ambiguous_labels.items():
        lookup[key] = tuple(sorted(labels, key=ord))
    ambiguous_keys = sum(len(values) > 1 for values in lookup.values())
    if ambiguous_keys != int(manifest.get("ambiguous_geometry_keys", -1)):
        raise FontCatalogError("font catalog ambiguity count mismatch")
    fully_ambiguous_characters = sum(
        all(
            len(lookup[(template.entity_count, template.closed_count, digest)]) > 1
            for template in variants
            for digest in template.match_digests
        )
        for _, variants in groupby(templates, key=lambda template: template.codepoint)
    )
    if fully_ambiguous_characters != int(
        manifest.get("fully_ambiguous_characters", -1)
    ):
        raise FontCatalogError("font catalog ambiguous character count mismatch")
    recognition_characters = frozenset(
        _canonical_catalog_character(template.codepoint) for template in templates
    )
    normalized_alias_mappings = len(unique_codepoints) - len(recognition_characters)
    if len(recognition_characters) != int(
        manifest.get("recognition_character_count", -1)
    ) or normalized_alias_mappings != int(
        manifest.get("normalized_alias_mappings", -1)
    ):
        raise FontCatalogError("font catalog normalized character count mismatch")
    catalog_id = str(manifest.get("catalog_id", ""))
    font = manifest.get("font")
    if (
        not _is_lower_hex(catalog_id, 24)
        or not isinstance(font, dict)
        or not _is_lower_hex(font.get("sha256"), 64)
        or not isinstance(font.get("face_index"), int)
        or not isinstance(font.get("face_count"), int)
        or not 0 <= font["face_index"] < font["face_count"]
        or not isinstance(font.get("units_per_em"), int)
        or not 16 <= font["units_per_em"] <= 16384
        or not isinstance(font.get("source_file"), str)
        or not font["source_file"]
    ):
        raise FontCatalogError("font catalog provenance is invalid")
    if catalog_id != _catalog_identifier(
        font["sha256"],
        font["face_index"],
        str(manifest["template_set_sha256"]),
        schema=manifest["schema"],
    ):
        raise FontCatalogError("font catalog identity mismatch")
    requested_count = manifest.get("requested_mapped_codepoints")
    skipped_count = manifest.get("skipped_non_outline_mappings")
    han_count = sum(_in_ranges(int(value), HAN_RANGES) for value in unique_codepoints)
    if (
        not isinstance(requested_count, int)
        or not isinstance(skipped_count, int)
        or requested_count != len(unique_codepoints) + skipped_count
        or han_count != int(manifest.get("han_template_count", -1))
    ):
        raise FontCatalogError("font catalog coverage counts are invalid")
    by_char: dict[str, FontGlyphTemplate] = {}
    templates_by_label: dict[str, list[FontGlyphTemplate]] = defaultdict(list)
    for template in templates:
        by_char.setdefault(template.char, template)
        templates_by_label[_canonical_catalog_character(template.codepoint)].append(
            template
        )
    for template in templates:
        canonical_char = _canonical_catalog_character(template.codepoint)
        if canonical_char not in by_char or (
            template.char == canonical_char
            and by_char[canonical_char].char != canonical_char
        ):
            by_char[canonical_char] = template
    return FontGlyphCatalog(
        path=source,
        schema=manifest["schema"],
        catalog_id=catalog_id,
        font=dict(font),
        charset=str(charset),
        unicode_cjk_version=str(manifest["unicode_cjk_version"]),
        template_set_sha256=str(manifest["template_set_sha256"]),
        raster_round_decimals=FONT_CATALOG_RASTER_DECIMALS,
        outline_policy=manifest.get("outline_policy", LEGACY_FONT_OUTLINE_POLICY),
        tolerance_divisors=divisors,
        templates=tuple(templates),
        by_char=by_char,
        templates_by_label={
            key: tuple(values) for key, values in templates_by_label.items()
        },
        lookup=lookup,
        structures={
            key: (min(values), max(values)) for key, values in structures_lists.items()
        },
        lengths=frozenset(int(value) for value in entities),
        characters=frozenset(template.char for template in templates),
        recognition_characters=recognition_characters,
        normalized_alias_mappings=normalized_alias_mappings,
        ambiguous_keys=ambiguous_keys,
        fully_ambiguous_characters=fully_ambiguous_characters,
    )


def inspect_font_catalog(path: str | Path) -> dict[str, Any]:
    return describe_font_catalog(load_font_catalog(path))


def describe_font_catalog(catalog: FontGlyphCatalog) -> dict[str, Any]:
    """Describe a verified catalog without constructing a second lookup index."""
    return {
        "schema": catalog.schema,
        "path": str(catalog.path),
        "sha256": _sha256_path(catalog.path),
        "size_bytes": catalog.path.stat().st_size,
        "catalog_id": catalog.catalog_id,
        "font": catalog.font,
        "charset": catalog.charset,
        "unicode_cjk_version": catalog.unicode_cjk_version,
        "template_set_sha256": catalog.template_set_sha256,
        "templates": len(catalog.templates),
        "mapped_codepoints": len(catalog.characters),
        "fill_variants": len(catalog.templates) - len(catalog.characters),
        "han_characters": sum(is_han_character(value) for value in catalog.characters),
        "characters": len(catalog.characters),
        "recognition_characters": len(catalog.recognition_characters),
        "english_letters": {
            "uppercase": "".join(
                ch for ch in string.ascii_uppercase if ch in catalog.characters
            ),
            "lowercase": "".join(
                ch for ch in string.ascii_lowercase if ch in catalog.characters
            ),
            "missing": "".join(
                ch for ch in string.ascii_letters if ch not in catalog.characters
            ),
            "mapped_count": len(set(string.ascii_letters) & catalog.characters),
        },
        "han_range_coverage": [
            {
                "first": f"U+{start:04X}",
                "last": f"U+{end:04X}",
                "mapped_count": sum(
                    start <= ord(ch) <= end for ch in catalog.characters
                ),
            }
            for start, end in HAN_RANGES
        ],
        "normalized_alias_mappings": catalog.normalized_alias_mappings,
        "tolerance_divisors": list(catalog.tolerance_divisors),
        "raster_round_decimals": catalog.raster_round_decimals,
        "outline_policy": catalog.outline_policy,
        "ambiguous_geometry_keys": catalog.ambiguous_keys,
        "fully_ambiguous_characters": catalog.fully_ambiguous_characters,
        "runtime_input": "persisted_dxf_only",
        "runtime_font_access": False,
        "runtime_pdf_access": False,
        "ocr_enabled": False,
    }
