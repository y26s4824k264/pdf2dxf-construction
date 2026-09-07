"""Bounded, deterministic stroke recognition on persisted DXF entities.

Templates carry their label provenance. Shape matches are candidates until a
complete token and independent dimension geometry agree; unmatched paths survive.
No PDF reader, image OCR, font download, or language model is used here.
"""

import json
import pickle
import re
import tempfile
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from scipy.ndimage import distance_transform_edt
from shapely.geometry import LineString, Point, box
from shapely.strtree import STRtree

CATALOG = Path(__file__).with_name("assets") / "engineering_glyphs.json"
SIZE = 48
_MAX_MATCH_SCORE = 0.028
_MIN_MATCH_MARGIN = 0.009


@dataclass
class Token:
    text: str
    bbox: list[float]
    angle: int
    handles: list[str]
    method: str
    height: float
    distance: float = 0.0

    def to_dict(self):
        return asdict(self)


def entity_paths(entity):
    kind = entity.dxftype()
    if kind == "LINE":
        return [np.array([tuple(entity.dxf.start)[:2], tuple(entity.dxf.end)[:2]])]
    if kind == "LWPOLYLINE" and not entity.has_arc:
        points = np.asarray(entity.get_points("xy"))
        if entity.closed and len(points):
            points = np.vstack([points, points[0]])
        return [points]
    return []


def mask_paths(paths):
    points = np.vstack(paths)
    low, high = points.min(0), points.max(0)
    extent = high - low
    if extent.max() <= 0:
        return None
    mask = np.zeros((SIZE, SIZE), np.uint8)
    for path in paths:
        q = (path - low) / np.maximum(extent, extent.max() * 0.02)
        q = np.rint(2 + q * (SIZE - 5)).astype(np.int32)
        cv2.polylines(mask, [q], False, 1, 1)
    return mask.astype(bool)


@lru_cache(maxsize=1)
def load_catalog():
    data = json.loads(CATALOG.read_text())
    if data.get("schema") != "pdf2dxf.glyph_catalog.v1":
        raise ValueError("Unsupported glyph catalog")
    rows = []
    for item in data["templates"]:
        paths = [np.asarray(p, dtype=float) for p in item["paths"]]
        if not item.get("label_evidence") or not item.get("source_sha256"):
            raise ValueError("Glyph label provenance is missing")
        if len(item["char"]) != 1 or not all(np.isfinite(p).all() for p in paths):
            raise ValueError("Invalid glyph template")
        mask = mask_paths(paths)
        if mask is None or not mask.any():
            raise ValueError("Empty glyph template")
        extent = np.ptp(np.vstack(paths), axis=0)
        rows.append((item["char"], mask, distance_transform_edt(~mask), extent))
    if not set("0123456789").issubset({row[0] for row in rows}):
        raise ValueError("Incomplete engineering digit catalog")
    return rows


def match_paths(paths, alphabet):
    mask = mask_paths(paths)
    if mask is None:
        return None
    extent = np.ptp(np.vstack(paths), axis=0)
    if extent[1] <= 0:
        return None
    ratio = extent[0] / extent[1]
    return _match_mask(mask.tobytes(), round(float(ratio), 2), alphabet)


@lru_cache(maxsize=8192)
def _match_mask(packed, ratio, alphabet):
    mask = np.frombuffer(packed, dtype=bool).reshape(SIZE, SIZE)
    dt = distance_transform_edt(~mask)
    scores = {}
    for char, target, target_dt, target_extent in load_catalog():
        if char not in alphabet:
            continue
        target_ratio = target_extent[0] / max(target_extent[1], 1e-9)
        if not 0.45 <= ratio / max(target_ratio, 0.01) <= 1.9:
            continue
        forward, backward = target_dt[mask], dt[target]
        score = float((forward.mean() + backward.mean()) / (2 * (SIZE - 5)))
        # Such a candidate can neither win nor make an accepted match ambiguous.
        # Keep a small arithmetic slack at the boundary before skipping quantiles.
        if score > _MAX_MATCH_SCORE + _MIN_MATCH_MARGIN + 1e-12:
            continue
        tail = float(
            max(np.quantile(forward, 0.95), np.quantile(backward, 0.95)) / (SIZE - 5)
        )
        if tail > 0.085:
            continue
        scores[char] = min(scores.get(char, 1), score)
    ranked = sorted(scores.items(), key=lambda row: row[1])
    if not ranked or ranked[0][1] > _MAX_MATCH_SCORE:
        return None
    if len(ranked) > 1 and ranked[1][1] - ranked[0][1] < _MIN_MATCH_MARGIN:
        return None
    return ranked[0]


def stroke_components(doc):
    """Spatial index keeps grouping local; large architectural paths stay intact."""
    geometries, rows = [], []
    for entity in doc.modelspace():
        if entity.dxf.layer in (
            "PDF_PAGE",
            "PDF_OUTLINE_BACKUP",
            "PDF_TEXT_RECOVERED_NOOCR",
        ):
            continue
        paths = entity_paths(entity)
        if not paths or not 2 <= sum(len(p) for p in paths) <= 200:
            continue
        points = np.vstack(paths)
        extent = np.ptp(points, axis=0)
        if not 0.15 <= extent.max() <= 12:
            continue
        geometry = LineString(points)
        if geometry.length <= 0.05:
            continue
        geometries.append(geometry)
        rows.append((entity.dxf.handle, entity.dxf.layer, paths))
    if not rows:
        return
    tree = STRtree(geometries)
    parents = list(range(len(rows)))

    def root(index):
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    for i, geom in enumerate(geometries):
        for j in tree.query(geom, predicate="dwithin", distance=0.012):
            if j > i and rows[i][1] == rows[j][1]:
                sizes = [
                    max(g.bounds[2] - g.bounds[0], g.bounds[3] - g.bounds[1])
                    for g in (geom, geometries[j])
                ]
                if max(sizes) > 3 * min(sizes):
                    # A long dimension/leader passing through a small closed
                    # glyph is a crossing, not a stroke connection. Genuine
                    # T-junctions still join when an open path ends there.
                    connected = any(
                        Point(endpoint).distance(other) <= 0.012
                        for paths, other in (
                            (rows[i][2], geometries[j]),
                            (rows[j][2], geom),
                        )
                        for path in paths
                        if not np.allclose(path[0], path[-1], rtol=0, atol=0.012)
                        for endpoint in (path[0], path[-1])
                    )
                    if not connected:
                        continue
                parents[root(int(j))] = root(i)
    groups = {}
    for i, row in enumerate(rows):
        groups.setdefault(root(i), []).append(row)
    # The recognition caller accumulates tokens as this generator yields. Drop
    # the connectivity index first, then release each consumed group, so a dense
    # sheet does not retain both complete geometry and recognition structures.
    parents.clear()
    del tree, geometries, rows
    for key in list(groups):
        group = groups.pop(key)
        paths = [path for _, _, parts in group for path in parts]
        points = np.vstack(paths)
        low, high = points.min(0), points.max(0)
        if len(points) > 240 or (high - low).max() > 12:
            continue
        yield paths, [r[0] for r in group], [*low, *high]


def _rotate(points, angle):
    # Local baseline coordinates: x follows text, y points above the baseline.
    if angle == 0:
        return points
    if angle == 90:
        return np.column_stack([points[:, 1], -points[:, 0]])
    if angle == 180:
        return -points
    return np.column_stack([-points[:, 1], points[:, 0]])


def _word_groups(group):
    """Break a consistently spaced row at a substantially larger word gap."""
    word, gaps = [], []
    for item in group:
        row = item[1]
        if word:
            prev = word[-1][1]
            height = min(row["box"][3] - row["box"][1], prev["box"][3] - prev["box"][1])
            gap = max(0, row["box"][0] - prev["box"][2]) / height
            # Require a preceding sequence, so a prefix is never discarded from
            # the first digit merely because their shapes have different widths.
            if len(word) >= 3 and gap > 0.45 and gap > 3 * float(np.median(gaps)):
                yield word
                word, gaps = [], []
            else:
                gaps.append(gap)
        word.append(item)
    if word:
        yield word


def _group_characters(characters, method, *, numeric_only=False):
    result = []
    # Compare actual neighbors, never baseline/height buckets: rounding that
    # quotient splits a word differently when it moves away from the origin.
    for angle in (0, 90, 180, 270):
        rows = sorted(
            (
                r
                for r in characters
                if r["angle"] == angle and r["box"][3] > r["box"][1]
            ),
            key=lambda r: (r["box"][0], r["box"][1], r["handles"]),
        )
        if not rows:
            continue
        tree = STRtree([box(*r["box"]) for r in rows])
        following = {}
        for i, row in enumerate(rows):
            x0, y0, x1, y1 = row["box"]
            h = y1 - y0
            for j in tree.query(
                box(x1 - 0.05 * h, y0 - 0.25 * h, x1 + 0.95 * h, y1 + 0.25 * h)
            ):
                j = int(j)
                if j <= i:
                    continue
                a, b, _, d = rows[j]["box"]
                size = min(h, d - b)
                gap = a - x1
                if not (
                    0.8 <= (d - b) / h <= 1.25
                    and a > x0
                    and -0.05 * size <= gap <= 0.95 * size
                    and abs(b - y0) <= 0.2 * size
                ):
                    continue
                score = (max(0, gap) / size, abs(b - y0) / size)
                following.setdefault(i, []).append((score, j))
        # Branching/overlapping strokes are ambiguous. Keep the entire connected
        # context as unknown, rather than publishing a plausible numeric suffix.
        parents = list(range(len(rows)))

        def root(i, parents=parents):
            while parents[i] != i:
                parents[i] = parents[parents[i]]
                i = parents[i]
            return i

        ambiguous, incoming = set(), {}
        for i, candidates in following.items():
            candidates.sort()
            best = candidates[0]
            for score, j in candidates:
                if score[0] > best[0][0] + 0.05:
                    continue
                parents[root(j)] = root(i)
                incoming.setdefault(j, []).append(i)
                if j != best[1]:
                    ambiguous.update((i, j, best[1]))
        # Two predecessors reaching the same glyph also invalidate that chain.
        for j, linked in incoming.items():
            if len(linked) > 1:
                ambiguous.update([j, *linked])
        groups = {}
        for i, row in enumerate(rows):
            groups.setdefault(root(i), []).append((i, row))
        for group in (
            word for row_group in groups.values() for word in _word_groups(row_group)
        ):
            chain = [r for _, r in group]
            text = "".join(r["char"] for r in chain)
            if any(i in ambiguous for i, _ in group):
                text = "?" + text
            if numeric_only and not re.fullmatch(r"[1-9]\d{2,5}", text):
                continue
            boxes = np.array([r["world"] for r in chain])
            result.append(
                Token(
                    text,
                    [*boxes[:, :2].min(0), *boxes[:, 2:].max(0)],
                    angle,
                    [handle for r in chain for handle in r["handles"]],
                    method,
                    float(np.median([r["box"][3] - r["box"][1] for r in chain])),
                    max(r.get("distance", 0) for r in chain),
                )
            )
    return result


def read_tokens(doc, recover=True, *, spool_dir=None):
    native = []
    for entity in doc.modelspace().query("TEXT MTEXT"):
        if (
            entity.dxf.layer == "PDF_TEXT_RECOVERED_NOOCR"
            and not entity.has_xdata("PDF2DXF_GLYPH")
        ):
            continue
        text = entity.dxf.text if entity.dxftype() == "TEXT" else entity.plain_text()
        text = text.strip()
        height = float(
            entity.dxf.height if entity.dxftype() == "TEXT" else entity.dxf.char_height
        )
        angle = round(float(entity.dxf.get("rotation", 0))) % 360
        if angle not in (0, 90, 180, 270) or not text or height <= 0:
            continue
        xy = np.array(tuple(entity.dxf.insert)[:2])
        local = _rotate(xy.reshape(1, 2), angle)[0]
        width = height * 0.6 * len(text) * float(entity.dxf.get("width", 1))
        box = [*local, local[0] + width, local[1] + height]
        corners = _rotate(
            np.array([[box[0], box[1]], [box[2], box[3]]]), (-angle) % 360
        )
        world = [*corners.min(0), *corners.max(0)]
        native.append(
            {
                "char": text,
                "box": box,
                "world": world,
                "angle": angle,
                "handles": [entity.dxf.handle],
            }
        )
    native_tokens = _group_characters(native, "native_dxf_text")
    candidates = []
    if recover:
        # Replay only our own temporary stream. Connectivity is built
        # once; each orientation can then release its character graph before the
        # next one. Retaining four graphs plus every rejected Token exhausted the
        # page budget on large basement sheets.
        # Keep the file visible inside the page work directory so existing disk
        # supervision includes it. It is deleted when this context closes.
        with tempfile.NamedTemporaryFile(dir=spool_dir, suffix=".glyph-spool") as spool:
            for component in stroke_components(doc):
                pickle.dump(component, spool, protocol=5)
            for angle in (0, 90, 180, 270):
                characters = []
                spool.seek(0)
                while True:
                    try:
                        paths, handles, bbox = pickle.load(spool)
                    except EOFError:
                        break
                    rotated = [_rotate(p, angle) for p in paths]
                    points = np.vstack(rotated)
                    low, high = points.min(0), points.max(0)
                    if high[1] - low[1] < 0.4:
                        continue
                    match = match_paths(rotated, "0123456789")
                    if match is None:
                        match = match_paths(
                            rotated,
                            "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz.+-/:()[]%",
                        )
                    # Unknown neighbors must still block partial numeric tokens.
                    characters.append(
                        {
                            "char": match[0] if match else "?",
                            "distance": match[1] if match else 1.0,
                            "box": [*low, *high],
                            "world": bbox,
                            "angle": angle,
                            "handles": handles,
                        }
                    )
                candidates.extend(
                    _group_characters(
                        characters, "verified_vector_template", numeric_only=True
                    )
                )
                del characters
    return native_tokens + candidates, {
        "status": "available" if recover else "disabled",
        "catalog_templates": len(load_catalog()) if recover else 0,
        "candidate_tokens": len(candidates),
        "accepted_tokens": 0,
        "native_tokens": len(native_tokens),
        "scope": "dimension digits; other unmatched outlines remain geometry",
        "ocr_enabled": False,
    }
