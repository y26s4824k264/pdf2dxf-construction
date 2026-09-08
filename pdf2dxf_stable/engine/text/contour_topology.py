"""Read-only predicates for evidence-backed outline disambiguation."""

from collections.abc import Sequence

import numpy as np
from shapely import contains_properly
from shapely.errors import GEOSException
from shapely.geometry import MultiLineString, Polygon


def strictly_encloses_paths(
    rings: Sequence[np.ndarray], remaining: Sequence[np.ndarray]
) -> bool:
    """Require two simple nested rings enclosing every remaining full path.

    No tolerance, buffering, polygon repair or source geometry mutation is
    allowed. Checking only a bounding box or sampled vertices misses edges
    crossing a concave boundary. Ring order and winding are immaterial here;
    the caller must separately prove the glyph and radical's catalog labels.
    """
    if len(rings) != 2 or not remaining:
        return False
    for path in (*rings, *remaining):
        if (
            path.ndim != 2
            or path.shape[1] != 2
            or len(path) < 4
            or not np.isfinite(path).all()
            or not np.array_equal(path[0], path[-1])
        ):
            return False
    try:
        outer, inner = sorted((Polygon(path) for path in rings), key=lambda p: -p.area)
        return bool(
            outer.is_valid
            and inner.is_valid
            and inner.area > 0
            and contains_properly(outer, inner)
            and contains_properly(inner, MultiLineString(remaining))
        )
    except GEOSException:
        return False


def half_enclosure_evidence(
    rings: Sequence[np.ndarray], remaining: Sequence[np.ndarray]
) -> dict[str, object] | None:
    """Verify disjoint parts interleaving across exactly one open bbox side.

    The radical is one simple closed outline, not a closed counter. All other
    contours must form valid polygons disjoint from it, including boundaries.
    Their combined bounds extend beyond exactly one radical bound and are
    strictly inside the other three. The two convex hull interiors must overlap
    without either containing the other: separate adjacent characters fail.

    This only supplies spatial evidence. Exact whole-glyph and radical labels,
    a canonical radical cmap outline, an independent font lock and row anchors are still
    required by the caller. No source path is changed, repaired or approximated.
    """
    if len(rings) != 1 or not remaining:
        return None
    for path in (*rings, *remaining):
        if (
            path.ndim != 2
            or path.shape[1] != 2
            or len(path) < 4
            or not np.isfinite(path).all()
            or not np.array_equal(path[0], path[-1])
        ):
            return None
    try:
        radical = Polygon(rings[0])
        parts = [Polygon(path) for path in remaining]
        if (
            not radical.is_valid
            or radical.area <= 0
            or any(
                not p.is_valid or p.area <= 0 or not radical.disjoint(p) for p in parts
            )
        ):
            return None
        radical_hull = radical.convex_hull
        remaining_hull = MultiLineString(remaining).convex_hull
        if not radical_hull.overlaps(remaining_hull):
            return None
        a, b = radical.bounds, remaining_hull.bounds
        margins = (b[0] - a[0], b[1] - a[1], a[2] - b[2], a[3] - b[3])
        if sum(value < 0 for value in margins) != 1 or any(
            value == 0 for value in margins
        ):
            return None
        return {
            "open_side": ("min_x", "min_y", "max_x", "max_y")[
                next(i for i, value in enumerate(margins) if value < 0)
            ],
            "radical_bbox": list(a),
            "remaining_bbox": list(b),
            "radical_disjoint_from_all_remaining_polygons": True,
            "minimum_part_distance": min(radical.distance(p) for p in parts),
            "convex_hulls_overlap_without_containment": True,
            "convex_hull_intersection_area": radical_hull.intersection(
                remaining_hull
            ).area,
        }
    except GEOSException:
        return None
