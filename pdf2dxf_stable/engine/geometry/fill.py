"""Resolve filled paths by their actual winding, including nested islands."""

from __future__ import annotations

import numpy as np
from shapely.geometry import GeometryCollection, LineString, Polygon
from shapely.ops import polygonize, unary_union


def filled_geometry(rings, even_odd=False, stats=None):
    paths = []
    for ring in rings:
        try:
            p = np.asarray(ring, dtype=np.float64)
            if p.ndim != 2 or p.shape[1] != 2 or not np.isfinite(p).all():
                raise ValueError("invalid fill coordinates")
            if len(p) < 3:
                continue
            if not np.array_equal(p[0], p[-1]):
                p = np.vstack((p, p[0]))
            shape = Polygon(p)
            if not shape.is_valid and stats is not None:
                stats.invalid_geometries_repaired += 1
            paths.append(p)
        except (TypeError, ValueError):
            if stats is not None:
                stats.malformed_paths += 1
    if not paths:
        return GeometryCollection()
    # The common single simple ring needs no planar arrangement.
    if len(paths) == 1:
        shape = Polygon(paths[0])
        if shape.is_valid:
            return shape
    starts = np.vstack([p[:-1] for p in paths])
    ends = np.vstack([p[1:] for p in paths])
    faces = polygonize(unary_union([LineString(p) for p in paths]))
    kept = []
    for face in faces:
        point = face.representative_point()
        x, y = point.x, point.y
        cross = (ends[:, 0] - starts[:, 0]) * (y - starts[:, 1]) - (
            x - starts[:, 0]
        ) * (ends[:, 1] - starts[:, 1])
        winding = int(
            np.count_nonzero((starts[:, 1] <= y) & (y < ends[:, 1]) & (cross > 0))
            - np.count_nonzero((ends[:, 1] <= y) & (y < starts[:, 1]) & (cross < 0))
        )
        if (winding % 2 != 0) if even_odd else (winding != 0):
            kept.append(face)
    return unary_union(kept)
