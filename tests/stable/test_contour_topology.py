"""Whole edges, rather than vertex samples, must fit a valid enclosure."""

import itertools

import numpy as np
import pytest
from fontTools.pens.pointInsidePen import PointInsidePen

from pdf2dxf_stable.engine.text.contour_topology import strictly_encloses_paths


def path(points):
    return np.array([*points, points[0]], dtype=float)


OUTER = path([(0, 0), (10, 0), (10, 10), (0, 10)])
INNER = path([(1, 1), (9, 1), (9, 9), (1, 9)])
CORE = path([(2, 2), (8, 2), (8, 8), (2, 8)])


@pytest.mark.parametrize("swap,reverse", list(itertools.product([False, True], repeat=2)))
def test_order_and_winding_do_not_change_topological_evidence(swap, reverse):
    rings = [OUTER.copy(), INNER.copy()]
    if swap:
        rings.reverse()
    if reverse:
        rings = [ring[::-1] for ring in rings]
    before = [r.copy() for r in rings]
    assert strictly_encloses_paths(rings, [CORE])
    assert all(np.array_equal(a, b) for a, b in zip(before, rings))


def test_concave_hole_rejects_crossing_edge_even_when_every_vertex_is_inside():
    inner = path([(1, 1), (9, 1), (9, 4), (4, 4), (4, 9), (1, 9)])
    core = path([(2, 8), (8, 2), (2, 2)])
    # Independent font-pen ray casting shows why point-only checks are unsafe.
    for point in core:
        pen = PointInsidePen(None, tuple(point), evenOdd=True)
        pen.moveTo(tuple(inner[0]))
        for vertex in inner[1:]:
            pen.lineTo(tuple(vertex))
        pen.closePath()
        assert pen.getResult()
    assert not strictly_encloses_paths([OUTER, inner], [core])


@pytest.mark.parametrize(
    "rings,remaining",
    [
        ([OUTER, INNER], []),
        ([OUTER], [CORE]),
        ([OUTER, INNER, CORE], [CORE]),
        ([OUTER, INNER], [CORE + (1, 0)]),  # Touches inner boundary.
        ([OUTER, INNER], [CORE + (2, 0)]),  # Crosses inner boundary.
        ([OUTER, INNER + (1, 0)], [CORE]),  # Rings touch.
        ([OUTER, INNER + (20, 0)], [CORE]),
        ([OUTER, path([(1, 1), (9, 9), (1, 9), (9, 1)])], [CORE]),
        ([OUTER, path([(1, 1), (2, 2), (3, 3)])], [CORE]),
        ([OUTER[:-1], INNER], [CORE]),
        ([OUTER, INNER], [CORE[:-1]]),
        ([OUTER, INNER], [np.array([[np.nan, 2]] * 4)]),
    ],
)
def test_unproven_topology_fails_closed(rings, remaining):
    assert not strictly_encloses_paths(rings, remaining)
