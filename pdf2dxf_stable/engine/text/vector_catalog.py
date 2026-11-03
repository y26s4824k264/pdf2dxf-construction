"""Persist vector font geometry; runtime matching never opens fonts or PDFs."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import zipfile
import zlib

import numpy as np
from scipy.spatial import cKDTree
from shapely import distance, hausdorff_distance, points as shapely_points
from shapely.geometry import MultiLineString, Polygon

from ...paths import protect_inputs
from ..geometry.fill import filled_geometry
from . import font_catalog as fc

SCHEMA = "pdf2dxf.vector_font_catalog.v1"
MAX_ROWS = 200_000
MAX_POINTS = 20_000_000
MAX_PATHS = 2_000_000
MAX_GLYPH_POINTS = 8192
# Error is a fraction of observed ink height, not a drawing/engineering scale.
MAX_BOUNDARY_ERROR = 0.006
MAX_GRID_BOUNDARY_ERROR = 0.02
MAX_CANDIDATES = 128
GRID = shapely_points(
    np.array([(x, y) for y in np.linspace(0, 1, 6) for x in np.linspace(0, 1, 6)])
)
ARRAY_DTYPES = {
    "points.npy": np.dtype("<f4"),
    "path_offsets.npy": np.dtype("<u4"),
    "glyph_offsets.npy": np.dtype("<u4"),
    "codepoints.npy": np.dtype("<u4"),
    "metrics.npy": np.dtype("<f4"),
    "aspects.npy": np.dtype("<f4"),
    "descriptors.npy": np.dtype("<f4"),
}


def _normalise(paths):
    all_points = np.vstack(paths)
    low, high = all_points.min(0), all_points.max(0)
    extent = high - low
    if not np.isfinite(all_points).all() or min(extent) <= 1e-9:
        raise ValueError("vector glyph has no finite two-dimensional ink bounds")
    return (
        tuple(np.asarray((p - low) / extent, dtype="<f4") for p in paths),
        low,
        extent,
    )


def _descriptor(paths):
    return np.asarray(distance(GRID, MultiLineString(paths)), dtype="<f4")


def _topology(paths):
    polygons = [Polygon(p) for p in paths]
    if any(not p.is_valid or p.area <= 0 for p in polygons):
        return None
    depths = []
    for i, p in enumerate(polygons):
        depth = 0
        for j, other in enumerate(polygons):
            if i == j:
                continue
            if p.boundary.intersects(other.boundary):
                return None
            depth += other.area > p.area and other.covers(p)
        depths.append(depth)
    return tuple(sorted(depths))


def _polygon_parts(geometry):
    if isinstance(geometry, Polygon):
        yield geometry
    elif hasattr(geometry, "geoms"):
        for part in geometry.geoms:
            yield from _polygon_parts(part)


def _filled_paths(paths):
    """Canonical filled boundaries, retaining the font's outer/hole winding."""
    return tuple(
        np.asarray(r.coords, dtype=np.float64)
        for p in _polygon_parts(filled_geometry(paths))
        for r in (p.exterior, *p.interiors)
    )


def _join_stroke_paths(paths):
    """Join exact consecutive pen endpoints, preserving every undirected edge."""
    joined = []
    for path in paths:
        path = np.asarray(path)
        if not joined:
            joined.append(np.asarray(path))
            continue
        previous = joined[-1]
        if np.array_equal(previous[-1], path[0]):
            joined[-1] = np.vstack((previous, path[1:]))
        elif np.array_equal(previous[-1], path[-1]):
            joined[-1] = np.vstack((previous, path[-2::-1]))
        elif np.array_equal(previous[0], path[-1]):
            joined[-1] = np.vstack((path, previous[1:]))
        elif np.array_equal(previous[0], path[0]):
            joined[-1] = np.vstack((path[::-1], previous[1:]))
        else:
            joined.append(path)
    return tuple(joined)


def _stroke_network_topology(envelope):
    """Connected components and holes of a vector uncertainty envelope."""
    parts = tuple(_polygon_parts(envelope))
    holes = tuple(sorted(len(p.interiors) for p in parts))
    if not parts or len(parts) + sum(holes) > 512:
        return None
    return holes


def _stroke_paths_agree(observed, expected, aspect, limit):
    """Retain the strict per-path proof when printer noise changes envelope topology."""
    from scipy.optimize import linear_sum_assignment
    from shapely.geometry import LineString

    if len(observed) != len(expected):
        return False
    a = [p * [aspect, 1] for p in observed]
    b = [p * [aspect, 1] for p in expected]
    costs = np.ones((len(a), len(b)))
    for i, p in enumerate(a):
        closed = np.array_equal(p[0], p[-1])
        for j, q in enumerate(b):
            if closed != np.array_equal(q[0], q[-1]):
                continue
            if (
                not closed
                and min(
                    max(np.linalg.norm(p[0] - q[0]), np.linalg.norm(p[-1] - q[-1])),
                    max(np.linalg.norm(p[0] - q[-1]), np.linalg.norm(p[-1] - q[0])),
                )
                > limit
            ):
                continue
            x, y = LineString(p), LineString(q)
            if (
                float(hausdorff_distance(x, y, densify=0.25)) <= limit
                and x.buffer(limit, quad_segs=8).covers(y)
                and y.buffer(limit, quad_segs=8).covers(x)
            ):
                costs[i, j] = 0
    rows, cols = linear_sum_assignment(costs)
    return bool(np.all(costs[rows, cols] == 0))


@dataclass(slots=True)
class VectorFontCatalog:
    path: Path
    catalog_id: str
    font: dict
    manifest: dict
    arrays: dict
    _indices: dict = field(default_factory=dict)
    _topologies: dict = field(default_factory=dict)
    _stroke_paths: dict = field(default_factory=dict)
    _path_counts: np.ndarray | None = None

    def paths(self, row):
        if row in self._stroke_paths:
            return self._stroke_paths[row]
        a = self.arrays
        first, end = a["glyph_offsets.npy"][row : row + 2]
        paths = tuple(
            a["points.npy"][a["path_offsets.npy"][i] : a["path_offsets.npy"][i + 1]]
            for i in range(int(first), int(end))
        )
        if self.manifest["outline_policy"] == "open_stroke_paths_v1":
            # rc42 archives retain their verified original arrays and identity.
            # Matching uses the same exact endpoint normalisation on both sides.
            paths = _join_stroke_paths(paths)
            self._stroke_paths[row] = paths
        return paths

    def path_counts(self):
        if self._path_counts is None:
            self._path_counts = (
                np.array(
                    [
                        len(self.paths(i))
                        for i in range(len(self.arrays["codepoints.npy"]))
                    ]
                )
                if self.manifest["outline_policy"] == "open_stroke_paths_v1"
                else np.diff(self.arrays["glyph_offsets.npy"])
            )
        return self._path_counts

    def candidates(self, paths, *, max_error=MAX_BOUNDARY_ERROR, deferred=None):
        """Return every label inside the geometric budget, or reject ambiguity.

        Distance-to-outline samples are Lipschitz under Hausdorff distance.
        An L-infinity radius query therefore cannot omit an admissible rival;
        unlike top-k retrieval it does not turn a hidden tie into a decision.
        """
        if not 0 < max_error <= MAX_GRID_BOUNDARY_ERROR:
            raise ValueError("invalid vector boundary error budget")
        stroke = self.manifest["outline_policy"] == "open_stroke_paths_v1"
        paths = _join_stroke_paths(paths) if stroke else paths
        normal, _, extent = _normalise(paths)
        topology = () if stroke else _topology(normal)
        if topology is None:
            return []
        # Pen partitions are not glyph identity. Search all stroke rows so a
        # different path count cannot conceal a competing Unicode label.
        key = "stroke_network" if stroke else len(paths)
        if key not in self._indices:
            rows = (
                np.arange(len(self.arrays["codepoints.npy"]))
                if stroke
                else np.flatnonzero(self.path_counts() == len(paths))
            )
            self._indices[key] = (rows, cKDTree(self.arrays["descriptors.npy"][rows]))
        rows, tree = self._indices[key]
        if not len(rows):
            return []
        aspect = float(extent[0] / extent[1])
        radius = max_error / min(aspect, 1.0) + 2e-6
        nearby = tree.query_ball_point(_descriptor(normal), radius, p=np.inf, eps=0)
        if len(nearby) > MAX_CANDIDATES:
            return None  # Never truncate away a competing label.
        observed = MultiLineString([p * [aspect, 1] for p in normal])
        observed_buffer = None
        observed_wide_topology = None
        result = []
        for position in nearby:
            row = int(rows[position])
            template_aspect = float(self.arrays["aspects.npy"][row])
            width_factor = aspect / template_aspect
            if not 0.2 <= width_factor <= 3:
                continue
            if not stroke:
                if row not in self._topologies:
                    self._topologies[row] = _topology(self.paths(row))
                if self._topologies[row] != topology:
                    continue
            expected = MultiLineString([p * [aspect, 1] for p in self.paths(row)])
            error = float(hausdorff_distance(observed, expected, densify=0.25))
            if not np.isfinite(error) or error > max_error:
                continue
            # Discrete Hausdorff alone can miss an error between vertices.
            # Inscribed buffers require coverage of both complete polylines.
            expected_buffer = expected.buffer(max_error, quad_segs=8)
            if not expected_buffer.covers(observed):
                continue
            if observed_buffer is None:
                observed_buffer = observed.buffer(max_error, quad_segs=8)
            if not observed_buffer.covers(expected):
                continue
            cp = int(self.arrays["codepoints.npy"][row])
            prediction = (fc._canonical_catalog_character(cp), row, error, width_factor)
            if stroke and not _stroke_paths_agree(
                normal, self.paths(row), aspect, max_error
            ):
                topology = _stroke_network_topology(observed_buffer)
                if topology is None or topology != _stroke_network_topology(
                    expected_buffer
                ):
                    if deferred is not None:
                        deferred.append(prediction)
                    continue
                if observed_wide_topology is None:
                    observed_wide_topology = _stroke_network_topology(
                        observed.buffer(2 * max_error, quad_segs=8)
                    )
                if (
                    observed_wide_topology is None
                    or observed_wide_topology
                    != _stroke_network_topology(
                        expected.buffer(2 * max_error, quad_segs=8)
                    )
                ):
                    if deferred is not None:
                        deferred.append(prediction)
                    continue
            result.append(prediction)
        return result

    def entry(self):
        return {
            "path": str(self.path),
            "catalog_id": self.catalog_id,
            "status": "loaded",
            "font": self.font,
            "schema": SCHEMA,
            "outline_policy": self.manifest["outline_policy"],
            "templates": len(self.arrays["codepoints.npy"]),
            "vector_boundary_error_limit": MAX_BOUNDARY_ERROR,
            "stroke_geometry_policy": (
                "complete_ink_network_v1"
                if self.manifest["outline_policy"] == "open_stroke_paths_v1"
                else None
            ),
        }


def build_vector_font_catalog(
    font_path, output, *, face_index=0, codepoints=None, progress=None
):
    """Build Han templates from Unicode cmap labels and actual vector outlines."""
    from fontTools.ttLib import TTFont
    from fontTools.pens.recordingPen import DecomposingRecordingPen

    source = Path(font_path).expanduser().resolve()
    target = Path(output).expanduser().resolve()
    protect_inputs(target, [source])
    if target.suffix.lower() != ".p2dvec":
        raise ValueError("vector font catalogs must end in .p2dvec")
    faces = fc._font_face_count(source)
    if type(face_index) is not int or not 0 <= face_index < faces:
        raise ValueError("invalid font face index")
    coords, path_offsets, glyph_offsets = [], [0], [0]
    cps, metrics, aspects, descriptors = [], [], [], []
    skipped = 0
    with TTFont(
        source,
        fontNumber=face_index,
        lazy=False,
        recalcBBoxes=False,
        recalcTimestamp=False,
    ) as font:
        metadata = fc._font_metadata(font, source, face_index, faces)
        cmap = font.getBestCmap() or {}
        requested = sorted(set(cmap if codepoints is None else map(int, codepoints)))
        requested = [
            cp
            for cp in requested
            if cp in cmap and 0 <= cp <= 0x10FFFF and fc.is_han_character(chr(cp))
        ]
        gs = font.getGlyphSet()
        for done, cp in enumerate(requested, 1):
            pen = DecomposingRecordingPen(gs)
            gs[cmap[cp]].draw(pen)
            raw = fc._glyph_paths(pen, gs, metadata["units_per_em"] / 1024)
            variants = [_filled_paths(raw)] if raw else []
            admitted = False
            for paths in variants:
                if (
                    not paths
                    or len(paths) > fc.MAX_CONTOURS
                    or sum(map(len, paths)) > MAX_GLYPH_POINTS
                ):
                    continue
                if any(len(p) < 4 or not np.array_equal(p[0], p[-1]) for p in paths):
                    continue
                try:
                    normal, low, extent = _normalise(paths)
                except ValueError:
                    continue
                next_points = path_offsets[-1] + sum(map(len, normal))
                if (
                    len(cps) >= MAX_ROWS
                    or next_points > MAX_POINTS
                    or len(path_offsets) - 1 + len(normal) > MAX_PATHS
                ):
                    raise fc.FontCatalogError(
                        "vector font catalog exceeds geometry limits"
                    )
                for p in normal:
                    coords.append(p)
                    path_offsets.append(path_offsets[-1] + len(p))
                glyph_offsets.append(len(path_offsets) - 1)
                cps.append(cp)
                em = metadata["units_per_em"]
                metrics.append(
                    (
                        *low / em,
                        *(low + extent) / em,
                        float(font["hmtx"][cmap[cp]][0]) / em,
                    )
                )
                aspects.append(float(extent[0] / extent[1]))
                descriptors.append(_descriptor(normal))
                admitted = True
            skipped += not admitted
            if progress:
                progress(done, len(requested))
    if not cps:
        raise fc.FontCatalogError("font has no drawable Han vector templates")
    arrays = {
        "points.npy": np.vstack(coords).astype("<f4"),
        "path_offsets.npy": np.asarray(path_offsets, dtype="<u4"),
        "glyph_offsets.npy": np.asarray(glyph_offsets, dtype="<u4"),
        "codepoints.npy": np.asarray(cps, dtype="<u4"),
        "metrics.npy": np.asarray(metrics, dtype="<f4"),
        "aspects.npy": np.asarray(aspects, dtype="<f4"),
        "descriptors.npy": np.asarray(descriptors, dtype="<f4"),
    }
    return _write_vector_arrays(target, metadata, arrays, skipped)


def _write_vector_arrays(
    target, metadata, arrays, skipped, *, outline_policy="nonzero_filled_boundaries_v1"
):
    cps = arrays["codepoints.npy"]
    face_index = metadata["face_index"]
    policy_key = outline_policy if outline_policy == "open_stroke_paths_v1" else ""
    payloads = {name: fc._npy_bytes(a) for name, a in arrays.items()}
    digest = fc._dataset_digest(arrays)
    identity = hashlib.sha256(
        (SCHEMA + metadata["sha256"] + str(face_index) + policy_key + digest).encode()
    ).hexdigest()[:24]
    manifest = {
        "schema": SCHEMA,
        "catalog_id": identity,
        "font": metadata,
        "runtime_input": "persisted_dxf_only",
        "runtime_font_access": False,
        "runtime_pdf_access": False,
        "runtime_ocr": False,
        "unicode_label_normalization": "NFKC_single_codepoint",
        "outline_policy": outline_policy,
        "curve_tolerance_divisor": 1024,
        "template_set_sha256": digest,
        "rows": len(cps),
        "paths": len(arrays["path_offsets.npy"]) - 1,
        "points": len(arrays["points.npy"]),
        "mapped_codepoints": len(set(cps)),
        "skipped_codepoints": skipped,
        "arrays": {
            n: {
                "shape": list(arrays[n].shape),
                "bytes": len(p),
                "sha256": hashlib.sha256(p).hexdigest(),
            }
            for n, p in payloads.items()
        },
    }
    fc._write_catalog_archive(target, manifest, payloads)
    return {**manifest, "path": str(target), "sha256": fc._sha256_path(target)}


def load_vector_font_catalog(path):
    """Read bounded numeric arrays and verify the descriptor index completely."""
    path = Path(path).expanduser().resolve()
    try:
        with zipfile.ZipFile(path) as z:
            if len(z.namelist()) != 8 or set(z.namelist()) != {
                "manifest.json",
                *ARRAY_DTYPES,
            }:
                raise ValueError("unexpected vector catalog archive members")
            if z.getinfo("manifest.json").file_size > 128_000:
                raise ValueError("vector catalog manifest is too large")
            m = json.loads(z.read("manifest.json"))
            if (
                m.get("schema") != SCHEMA
                or m.get("outline_policy")
                not in {"nonzero_filled_boundaries_v1", "open_stroke_paths_v1"}
                or m.get("runtime_input") != "persisted_dxf_only"
                or any(
                    m.get(k) is not False
                    for k in (
                        "runtime_font_access",
                        "runtime_pdf_access",
                        "runtime_ocr",
                    )
                )
            ):
                raise ValueError("unsupported vector catalog contract")
            stroke = m["outline_policy"] == "open_stroke_paths_v1"
            n, paths, points = (m.get(k) for k in ("rows", "paths", "points"))
            if any(type(v) is not int for v in (n, paths, points)) or not (
                0 < n <= MAX_ROWS
                and n <= paths <= MAX_PATHS
                and paths * (2 if stroke else 4) <= points <= MAX_POINTS
            ):
                raise ValueError("invalid vector catalog counts")
            shapes = {
                "points.npy": (points, 2),
                "path_offsets.npy": (paths + 1,),
                "glyph_offsets.npy": (n + 1,),
                "codepoints.npy": (n,),
                "metrics.npy": (n, 5),
                "aspects.npy": (n,),
                "descriptors.npy": (n, 36),
            }
            a = {}
            for name, dtype in ARRAY_DTYPES.items():
                spec = m["arrays"][name]
                info = z.getinfo(name)
                if info.file_size > int(np.prod(shapes[name])) * dtype.itemsize + 4096:
                    raise ValueError("vector catalog array exceeds declared limits")
                data = z.read(name)
                if (
                    len(data) != spec["bytes"]
                    or hashlib.sha256(data).hexdigest() != spec["sha256"]
                ):
                    raise ValueError("vector catalog array digest mismatch")
                a[name] = fc._load_npy(data, shapes[name], dtype)
        font = m["font"]
        if (
            not isinstance(font, dict)
            or not fc._is_lower_hex(font.get("sha256"), 64)
            or type(font.get("face_index")) is not int
            or type(font.get("face_count")) is not int
            or not 0 <= font["face_index"] < font["face_count"]
            or type(font.get("units_per_em")) is not int
            or not 16 <= font["units_per_em"] <= 16384
        ):
            raise ValueError("invalid vector font provenance")
        if stroke and (
            font.get("source_format") != "AutoCAD-86 bigfont 1.0"
            or font.get("source_encoding") != "gbk"
            or font.get("unicode_mapping") != "strict_gbk_roundtrip"
            or font.get("path_join_policy")
            not in {
                "exact_sequential_endpoint_v1",
                "exact_sequential_undirected_endpoint_v2",
            }
        ):
            raise ValueError("unsupported stroke font encoding contract")
        digest = fc._dataset_digest(a)
        identity = hashlib.sha256(
            (
                SCHEMA
                + font["sha256"]
                + str(font["face_index"])
                + ("open_stroke_paths_v1" if stroke else "")
                + digest
            ).encode()
        ).hexdigest()[:24]
        if (
            digest != m["template_set_sha256"]
            or identity != m["catalog_id"]
            or not fc._is_lower_hex(font["sha256"], 64)
        ):
            raise ValueError("vector catalog identity mismatch")
        po, go = a["path_offsets.npy"], a["glyph_offsets.npy"]
        if stroke and (
            type(font.get("max_source_paths")) is not int
            or not int(np.max(np.diff(go.astype("i8"))))
            <= font["max_source_paths"]
            <= fc.MAX_CONTOURS
            or font["face_index"] != 0
            or font["face_count"] != 1
        ):
            raise ValueError("invalid stroke source path limits")
        if (
            po[0] != 0
            or po[-1] != points
            or go[0] != 0
            or go[-1] != paths
            or np.any(np.diff(po.astype("i8")) < (2 if stroke else 4))
            or np.any(np.diff(go.astype("i8")) < 1)
            or np.any(np.diff(go.astype("i8")) > fc.MAX_CONTOURS)
        ):
            raise ValueError("invalid vector catalog geometry offsets")
        if any(
            not np.isfinite(a[k]).all()
            for k in ("points.npy", "metrics.npy", "aspects.npy", "descriptors.npy")
        ):
            raise ValueError("nonfinite vector catalog geometry")
        if (
            np.any(a["points.npy"] < 0)
            or np.any(a["points.npy"] > 1)
            or np.any(a["aspects.npy"] <= 0)
        ):
            raise ValueError("vector catalog geometry is out of bounds")
        cps = a["codepoints.npy"]
        if any(not fc.is_han_character(chr(int(cp))) for cp in cps) or np.any(
            cps[1:] < cps[:-1]
        ):
            raise ValueError("invalid vector catalog Unicode labels")
        _, repetitions = np.unique(cps, return_counts=True)
        metrics = a["metrics.npy"]
        if (
            np.any(repetitions > 1)
            or np.any(np.abs(metrics) > 16)
            or np.any(metrics[:, 2] <= metrics[:, 0])
            or np.any(metrics[:, 3] <= metrics[:, 1])
            or np.any(metrics[:, 4] < 0)
            or not np.allclose(
                a["aspects.npy"],
                (metrics[:, 2] - metrics[:, 0]) / (metrics[:, 3] - metrics[:, 1]),
                atol=1e-5,
                rtol=1e-5,
            )
        ):
            raise ValueError("invalid vector catalog layout metrics")
        catalog = VectorFontCatalog(path, identity, font, m, a)
        for i in range(n):
            rings = catalog.paths(i)
            if sum(map(len, rings)) > MAX_GLYPH_POINTS or any(
                not np.array_equal(p[0], p[-1]) for p in rings if not stroke
            ):
                raise ValueError("unclosed or oversized vector glyph")
            bounds = np.vstack(rings)
            if not np.allclose(bounds.min(0), 0, atol=1e-6) or not np.allclose(
                bounds.max(0), 1, atol=1e-6
            ):
                raise ValueError("vector glyph is not normalised")
            if not np.allclose(
                _descriptor(rings), a["descriptors.npy"][i], atol=1e-6, rtol=0
            ):
                raise ValueError("vector catalog search descriptor mismatch")
        return catalog
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        zipfile.BadZipFile,
        RuntimeError,
        zlib.error,
        OverflowError,
    ) as e:
        raise fc.FontCatalogError(f"invalid vector font catalog: {e}") from e
