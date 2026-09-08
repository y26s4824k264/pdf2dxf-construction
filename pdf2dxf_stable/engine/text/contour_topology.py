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
