import pytest
from shapely.geometry import Point, Polygon

from pdf2dxf_stable.engine.geometry.base import rings_to_fill_geometry


def square(a, b):
    return [(a, a), (b, a), (b, b), (a, b), (a, a)]


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("even_odd", [False, True])
def test_nested_hole_retains_ink_island(reverse, even_odd):
    rings = [square(0, 10), square(2, 8)[::-1], square(4, 6)]
    if reverse:
        rings = [r[::-1] for r in rings]
    actual = rings_to_fill_geometry(rings, even_odd)
    assert actual.area == pytest.approx(68)
    assert actual.covers(Point(5, 5))
    assert not actual.covers(Point(3, 3))
    assert actual.is_valid


@pytest.mark.parametrize("opposite", [False, True])
@pytest.mark.parametrize("even_odd", [False, True])
def test_overlapping_paths_use_total_winding(opposite, even_odd):
    first = square(0, 4)
    second = [(x + 2, y) for x, y in first]
    if opposite:
        second = second[::-1]
    actual = rings_to_fill_geometry([first, second], even_odd)
    assert actual.area == pytest.approx(16 if opposite or even_odd else 24)
    assert actual.covers(Point(3, 2)) is (not opposite and not even_odd)
    assert actual.covers(Point(5, 2))


def test_retraced_spike_and_self_crossing_remain_filled():
    spike = [(0, 0), (4, 0), (4, 4), (2, 4), (2, 6), (2, 4), (0, 4), (0, 0)]
    assert rings_to_fill_geometry([spike], False).area == pytest.approx(16)
    crossing = [(0, 0), (4, 4), (0, 4), (4, 0), (0, 0)]
    assert rings_to_fill_geometry([crossing], False).area == pytest.approx(8)


def test_disjoint_opposite_winding_is_still_ink():
    first = square(0, 2)
    second = square(4, 6)[::-1]
    result = rings_to_fill_geometry([first, second], False)
    assert result.equals(Polygon(first).union(Polygon(second)))


@pytest.mark.parametrize("construction", [False, True])
def test_pdf_nested_ink_survives_persisted_dxf(tmp_path, construction):
    import ezdxf
    import fitz
    from pdf2dxf_stable.engine.geometry.base import GenericGraphicsKernelV14
    from pdf2dxf_stable.engine.geometry.construction import (
        ConstructionGraphicsKernelV15,
    )

    kernel = (
        ConstructionGraphicsKernelV15() if construction else GenericGraphicsKernelV14()
    )
    path = tmp_path / "nested.dxf"
    with fitz.open() as pdf:
        page = pdf.new_page(width=100, height=100)
        page.draw_line((0, 0), (1, 1))
        pdf.update_stream(
            page.get_contents()[0],
            (
                b"q 0 g 10 10 80 80 re "
                b"25 25 m 25 75 l 75 75 l 75 25 l h "
                b"40 40 20 20 re f Q"
            ),
        )
        kernel.convert_page(pdf, 0, path)
    saved = ezdxf.readfile(path)
    hatches = list(saved.modelspace().query("HATCH"))
    assert len(hatches) == 2
    assert sum(len(h.paths) for h in hatches) == 3
    assert not saved.audit().errors
