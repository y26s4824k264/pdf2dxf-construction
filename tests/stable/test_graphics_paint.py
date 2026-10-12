"""Observe saved DXF paint, independently of converter statistics."""

import math

import ezdxf
import fitz
import pytest

from pdf2dxf_stable.engine.geometry.base import (
    GenericGraphicsKernelV14,
    LinetypeManager,
)
from pdf2dxf_stable.engine.geometry.construction import (
    ConstructionGraphicsKernelV15,
    ConstructionKernelConfigV15,
)


@pytest.fixture(params=[GenericGraphicsKernelV14, ConstructionGraphicsKernelV15])
def kernel(request):
    return request.param()


def converted(tmp_path, kernel, content):
    with fitz.open() as pdf:
        page = pdf.new_page(width=100, height=100)
        page.draw_line((0, 0), (1, 1))
        pdf.update_stream(page.get_contents()[0], content)
        path = tmp_path / "paint.dxf"
        kernel.convert_page(pdf, 0, path)
    return ezdxf.readfile(path)


@pytest.mark.parametrize("opacity", [0.0, 0.5, 1.0])
def test_stroke_and_fill_keep_opacity(tmp_path, kernel, opacity):
    with fitz.open() as pdf:
        page = pdf.new_page(width=100, height=100)
        page.draw_rect(
            (20, 20, 80, 80),
            fill=(0, 0, 0),
            color=(0, 0, 0),
            stroke_opacity=opacity,
            fill_opacity=opacity,
        )
        path = tmp_path / "opacity.dxf"
        kernel.convert_page(pdf, 0, path)
    doc = ezdxf.readfile(path)
    entities = [e for e in doc.modelspace() if e.dxf.layer != "PDF_PAGE"]
    assert {e.dxftype() for e in entities} == {"HATCH", "LWPOLYLINE"}
    for entity in entities:
        assert entity.transparency == pytest.approx(1 - opacity, abs=1 / 255)
        assert bool(entity.dxf.get("invisible", 0)) == (opacity == 0)


def test_dense_fill_strokes_keep_opacity(tmp_path):
    kernel = ConstructionGraphicsKernelV15(
        ConstructionKernelConfigV15(dense_pattern_min_records=1)
    )
    with fitz.open() as pdf:
        oc = pdf.add_ocg("HATCH")
        page = pdf.new_page()
        page.draw_line((20, 20), (80, 20), stroke_opacity=0.5, oc=oc)
        path = tmp_path / "dense.dxf"
        kernel.convert_page(pdf, 0, path)
    lines = list(ezdxf.readfile(path).modelspace().query("LINE"))
    assert lines
    assert all(e.transparency == pytest.approx(0.5, abs=1 / 255) for e in lines)


def test_odd_dash_array_repeats_as_dash_and_gap():
    doc = ezdxf.new()
    name = LinetypeManager(doc, 1).get("[3] 0")
    assert [
        t.value for t in doc.linetypes.get(name).pattern_tags.tags if t.code == 49
    ] == [3, -3]


@pytest.mark.parametrize("clip", [False, True])
def test_nonzero_dash_phase_and_clipping_keep_painted_intervals(tmp_path, kernel, clip):
    content = b"q " + (b"25 0 35 100 re W n " if clip else b"")
    content += b"[10 5] 7 d 20 50 m 60 50 l S Q"
    doc = converted(tmp_path, kernel, content)
    scale = 25.4 / 72
    spans = []
    for e in doc.modelspace().query("LINE"):
        assert e.dxf.get("linetype", "BYLAYER") in ("BYLAYER", "CONTINUOUS")
        spans.append((e.dxf.start.x / scale, e.dxf.end.x / scale))
    expected = [(28, 38), (43, 53), (58, 60)]
    if not clip:
        expected.insert(0, (20, 23))
    assert len(spans) == len(expected)
    for observed, wanted in zip(sorted(spans), expected):
        assert observed == pytest.approx(wanted, abs=1e-5)


def test_dashed_cubic_keeps_exact_curve_segments(tmp_path, kernel):
    from scipy.integrate import quad

    doc = converted(tmp_path, kernel, b"[10 5] 7 d 10 10 m 10 80 80 80 80 10 c S")
    splines = list(doc.modelspace().query("SPLINE"))
    assert len(splines) > 2
    first = splines[0]
    points = [tuple(v)[:2] for v in first.control_points]
    assert len(points) == 4

    def speed(t):
        dx, dy = (
            sum(
                3
                * ((1 - t) ** 2, 2 * (1 - t) * t, t * t)[i]
                * (points[i + 1][axis] - points[i][axis])
                for i in range(3)
            )
            for axis in (0, 1)
        )
        return math.hypot(dx, dy)

    assert quad(speed, 0, 1)[0] == pytest.approx(3 * 25.4 / 72, abs=1e-5)


def test_dash_phase_continues_across_vertices_and_resets_at_subpaths():
    from pdf2dxf_stable.engine.geometry.base import LineSeg, PathChain
    from pdf2dxf_stable.engine.geometry.dashes import dashed_chains

    chains = [
        PathChain([LineSeg((0, 0), (8, 0)), LineSeg((8, 0), (8, 12))]),
        PathChain([LineSeg((30, 0), (50, 0))]),
    ]
    result = list(dashed_chains(chains, (10, 5), 7))
    assert [(c.start, c.end) for c in result] == [
        ((0, 0), (3, 0)),
        ((8, 0), (8, 10)),
        ((30, 0), (33, 0)),
        ((38, 0), (48, 0)),
    ]


@pytest.mark.parametrize(
    "end,expected", [(39, [20, 25, 30, 35]), (40, [20, 25, 30, 35, 40])]
)
def test_zero_length_round_dashes_include_endpoint_dots(
    tmp_path, kernel, end, expected
):
    doc = converted(
        tmp_path, kernel, f"2 w 1 J [0 5] 0 d 20 50 m {end} 50 l S".encode()
    )
    dots = list(doc.modelspace().query("HATCH"))
    assert len(dots) == len(expected)
    assert [
        dot.paths[0].edges[0].center.x / (25.4 / 72) for dot in dots
    ] == pytest.approx(expected)


def test_invisible_paths_are_not_text_candidates():
    from pdf2dxf_stable.engine.text.dxf_text import stroke_components, read_tokens

    doc = ezdxf.new()
    doc.modelspace().add_line((0, 0), (1, 1), dxfattribs={"invisible": 1})
    doc.modelspace().add_text("123", dxfattribs={"invisible": 1})
    assert list(stroke_components(doc)) == []
    assert read_tokens(doc)[0] == []
    from pdf2dxf_stable.engine.calibration.evidence import LineIndex

    assert LineIndex(doc).rows == []
