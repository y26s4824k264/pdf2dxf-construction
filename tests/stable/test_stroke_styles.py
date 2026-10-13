"""Read back painted areas; expected values come from elementary geometry."""

import math

import ezdxf
import fitz
import pytest
from shapely.geometry import Polygon

from pdf2dxf_stable.engine.geometry.base import GenericGraphicsKernelV14
from pdf2dxf_stable.engine.geometry.construction import ConstructionGraphicsKernelV15


@pytest.fixture(params=[GenericGraphicsKernelV14, ConstructionGraphicsKernelV15])
def kernel(request):
    return request.param()


def convert(tmp_path, kernel, content):
    with fitz.open() as pdf:
        page = pdf.new_page(width=100, height=100)
        page.draw_line((0, 0), (1, 1))
        pdf.update_stream(page.get_contents()[0], content)
        path = tmp_path / "stroke.dxf"
        kernel.convert_page(pdf, 0, path)
    return ezdxf.readfile(path)


def area(doc):
    value = 0
    for entity in doc.modelspace().query("HATCH"):
        if not entity.has_xdata("PDF2DXF_STROKE"):
            continue
        for ring in entity.paths:
            value += (1 if ring.path_type_flags & 1 else -1) * Polygon(
                [(p[0], p[1]) for p in ring.vertices]
            ).area
    return value / (25.4 / 72) ** 2


@pytest.mark.parametrize("cap,expected", [(0, 400), (1, 400 + 25 * math.pi), (2, 500)])
def test_all_line_caps_have_real_paint(tmp_path, kernel, cap, expected):
    doc = convert(tmp_path, kernel, f"10 w {cap} J 20 50 m 60 50 l S".encode())
    assert area(doc) == pytest.approx(expected, abs=0.15)


@pytest.mark.parametrize(
    "join,limit,expected",
    [(0, 10, 800), (0, 1, 787.5), (1, 10, 775 + 25 * math.pi / 4), (2, 10, 787.5)],
)
def test_joins_and_pdf_miter_fallback(tmp_path, kernel, join, limit, expected):
    doc = convert(
        tmp_path,
        kernel,
        f"10 w 0 J {join} j {limit} M 20 20 m 60 20 l 60 60 l S".encode(),
    )
    assert area(doc) == pytest.approx(expected, abs=0.15)


def test_clip_applies_to_painted_width_not_centerline(tmp_path, kernel):
    doc = convert(
        tmp_path, kernel, b"q 20 50 40 50 re W n 10 w 1 J 20 50 m 60 50 l S Q"
    )
    assert area(doc) == pytest.approx(200, abs=0.15)


def test_anisotropic_transform_preserves_stroke_space(tmp_path, kernel):
    doc = convert(tmp_path, kernel, b"q 2 0 0 1 0 0 cm 10 w 2 J 10 50 m 30 50 l S Q")
    assert area(doc) == pytest.approx(600, abs=0.15)


def test_centerline_and_cubic_survive_without_double_paint(tmp_path, kernel):
    doc = convert(tmp_path, kernel, b"5 w 1 J 20 20 m 30 40 50 40 60 20 c S")
    splines = list(doc.modelspace().query("SPLINE"))
    assert splines
    assert all(e.has_xdata("PDF2DXF_STROKE") and e.transparency == 1 for e in splines)
    assert all(not e.dxf.invisible for e in splines)
    assert area(doc) > 200


def test_dash_intervals_use_original_affine_space(tmp_path, kernel):
    doc = convert(
        tmp_path, kernel, b"q 2 0 0 1 0 0 cm 4 w 0 J [10 5] 0 d 10 50 m 40 50 l S Q"
    )
    # Two 10-unit painted intervals, enlarged twice in X, each 4 units wide.
    assert area(doc) == pytest.approx(160, abs=0.1)
    lines = list(doc.modelspace().query("LINE"))
    scale = 25.4 / 72
    assert sorted(
        (round(e.dxf.start.x / scale), round(e.dxf.end.x / scale)) for e in lines
    ) == [(20, 40), (50, 70)]


def test_closed_dash_seam_is_joined(tmp_path, kernel):
    doc = convert(
        tmp_path,
        kernel,
        b"10 w 0 J 0 j [100 10] 10 d 20 20 m 50 20 l 50 50 l 20 50 l h S",
    )
    # The closing seam is painted on both sides: its outer miter corner survives.
    hatches = list(doc.modelspace().query("HATCH"))
    scale = 25.4 / 72
    points = [
        (x / scale, y / scale)
        for e in hatches
        for ring in e.paths
        for x, y, *_ in ring.vertices
    ]
    assert any(abs(x - 15) < 1e-6 and abs(y - 15) < 1e-6 for x, y in points)
