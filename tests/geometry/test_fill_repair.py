"""Repaired fill collections must retain their actual two-dimensional regions."""

import pytest
from shapely.geometry import Polygon, box
from shapely.validation import make_valid

from pdf2dxf_stable.engine.geometry.base import KernelStats, rings_to_fill_geometry

# A 4x4 square, plus a retraced spike with no fill area.
SPIKE = [(0, 0), (4, 0), (4, 4), (2, 4), (2, 6), (2, 4), (0, 4), (0, 0)]
HOLE = [(1, 1), (1, 3), (3, 3), (3, 1), (1, 1)]


@pytest.mark.parametrize("even_odd", [False, True])
@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("hole", [False, True])
def test_repaired_collection_preserves_fill_and_hole(even_odd, reverse, hole):
    rings = [SPIKE, HOLE] if hole else [SPIKE]
    if reverse:
        rings = [list(reversed(ring)) for ring in rings]
    assert make_valid(Polygon(rings[0])).geom_type == "GeometryCollection"
    expected = box(0, 0, 4, 4)
    if hole:
        expected = expected.difference(box(1, 1, 3, 3))
    stats = KernelStats()
    result = rings_to_fill_geometry(rings, even_odd, stats)
    assert result.equals(expected)
    assert result.area == (12 if hole else 16)
    assert stats.invalid_geometries_repaired == 1


@pytest.mark.parametrize("even_odd", [False, True])
def test_collection_retains_every_polygon_component(even_odd):
    # Two 2x2 squares connected by a retraced, zero-area segment.
    ring = [
        (0, 0),
        (2, 0),
        (2, 2),
        (0, 2),
        (0, 0),
        (4, 0),
        (6, 0),
        (6, 2),
        (4, 2),
        (4, 0),
        (0, 0),
    ]
    repaired = make_valid(Polygon(ring))
    assert repaired.geom_type == "GeometryCollection"
    expected = box(0, 0, 2, 2).union(box(4, 0, 6, 2))
    assert rings_to_fill_geometry([ring], even_odd).equals(expected)


def test_zero_area_collection_does_not_invent_fill():
    ring = [(0, 0), (2, 0), (0, 0), (0, 2), (0, 0)]
    assert rings_to_fill_geometry([ring], True).is_empty


@pytest.mark.parametrize("even_odd", [False, True])
@pytest.mark.parametrize("stroke", [False, True])
def test_pdf_fill_repair_reaches_saved_hatch_without_losing_stroke(
    tmp_path, even_odd, stroke
):
    import ezdxf
    import fitz
    from pdf2dxf_stable.engine.geometry.base import (
        GenericGraphicsKernelV14,
        KernelConfig,
    )

    with fitz.open() as pdf:
        page = pdf.new_page(width=100, height=100)
        shape = page.new_shape()
        for ring in (SPIKE, HOLE):
            shape.draw_polyline([(20 + 10 * x, 20 + 10 * y) for x, y in ring])
        shape.finish(
            fill=(0, 0, 0),
            color=(0, 0, 0) if stroke else None,
            even_odd=even_odd,
            closePath=True,
        )
        shape.commit()
        path = tmp_path / "fill.dxf"
        kernel = GenericGraphicsKernelV14(
            KernelConfig(
                units="pdf_pt", include_page_boundary=False, include_native_text=False
            )
        )
        kernel.convert_page(pdf, 0, path)
    doc = ezdxf.readfile(path)
    (hatch,) = doc.modelspace().query("HATCH")
    boundaries = [[(v[0], v[1]) for v in ring.vertices] for ring in hatch.paths]
    actual = Polygon(boundaries[0], boundaries[1:])
    assert actual.equals(box(20, 40, 60, 80).difference(box(30, 50, 50, 70)))
    assert hatch.has_xdata("PDF2DXF14")
    polylines = list(doc.modelspace().query("LWPOLYLINE"))
    if stroke:
        # The retraced spike has no fill, but is still a visible stroked path.
        assert any((40, 20) in list(e.get_points("xy")) for e in polylines)
    else:
        assert polylines == []
    assert not doc.audit().errors


@pytest.mark.parametrize("even_odd", [False, True])
def test_repaired_clip_keeps_polygon_and_hole_instead_of_scissor(even_odd):
    from pdf2dxf_stable.engine.geometry.base import clip_state_from_record, KernelConfig

    record = dict(
        type="clip",
        even_odd=even_odd,
        closePath=True,
        scissor=(-1, -1, 7, 7),
        items=[("l", a, b) for ring in (SPIKE, HOLE) for a, b in zip(ring, ring[1:])],
    )
    clip = clip_state_from_record(record, KernelConfig(), KernelStats())
    assert clip is not None
    assert clip.geometry.equals(box(0, 0, 4, 4).difference(box(1, 1, 3, 3)))
    assert clip.bounds == (0, 0, 4, 4)
    assert not clip.is_rectangle
