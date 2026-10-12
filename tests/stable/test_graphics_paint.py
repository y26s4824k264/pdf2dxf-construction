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


def hatch_area(hatch):
    """Green's theorem on saved LINE/ARC boundaries, without tessellation."""
    area = 0.0
    for path in hatch.paths:
        if hasattr(path, "vertices"):
            points = list(path.vertices)
            area += (
                sum(
                    a[0] * b[1] - b[0] * a[1]
                    for a, b in zip(points, points[1:] + points[:1])
                )
                / 2
            )
            continue
        for edge in path.edges:
            if hasattr(edge, "radius"):
                a, b = map(math.radians, (edge.start_angle, edge.end_angle))
                sweep = (b - a) % math.tau or math.tau
                x, y = edge.center
                r = edge.radius
                area += (
                    r * x * (math.sin(b) - math.sin(a))
                    + r * y * (math.cos(a) - math.cos(b))
                    + r * r * sweep
                ) / 2
            else:
                area += (edge.start.x * edge.end.y - edge.end.x * edge.start.y) / 2
    return area


@pytest.mark.parametrize("cut", [0, 0.5])
def test_clipped_round_dot_preserves_exact_arc_and_area(tmp_path, kernel, cut):
    doc = converted(
        tmp_path,
        kernel,
        f"q {20 + cut} 0 80 100 re W n 2 w 1 J [0 5] 0 d 20 50 m 21 50 l S Q".encode(),
    )
    dots = list(doc.modelspace().query("HATCH"))
    assert len(dots) == 1
    scale = 25.4 / 72
    assert hatch_area(dots[0]) / scale**2 == pytest.approx(
        math.acos(cut) - cut * math.sqrt(1 - cut**2), abs=1e-7
    )
    assert any(hasattr(edge, "radius") for edge in dots[0].paths[0].edges)
    audit = doc.audit()
    assert not audit.has_errors and not audit.has_fixes


def test_clipped_rotated_square_dot_keeps_tangent_and_area(tmp_path, kernel):
    doc = converted(
        tmp_path, kernel, b"q 20 0 80 100 re W n 2 w 2 J [0 5] 0 d 20 50 m 21 51 l S Q"
    )
    dots = list(doc.modelspace().query("HATCH"))
    assert len(dots) == 1
    assert hatch_area(dots[0]) / (25.4 / 72) ** 2 == pytest.approx(2, abs=1e-7)


@pytest.mark.parametrize("nested", [True, False])
def test_empty_clip_cannot_reveal_paint_and_scope_is_restored(tmp_path, kernel, nested):
    clip = b"0 0 10 10 re W n 20 20 10 10 re W n" if nested else b"0 0 0 10 re W n"
    doc = converted(
        tmp_path,
        kernel,
        b"q " + clip + b" 1 5 m 9 5 l S 1 1 8 8 re f Q 40 50 m 50 50 l S",
    )
    entities = [e for e in doc.modelspace() if e.dxf.layer != "PDF_PAGE"]
    assert len(entities) == 1
    assert entities[0].dxftype() == "LINE"
    assert entities[0].dxf.start.x / (25.4 / 72) == pytest.approx(40)


@pytest.mark.parametrize(
    "clip,expected_area,expected_paths",
    [
        ("0 0 100 100 re 19.5 49.5 1 1 re W* n", math.pi - 1, 2),
        (
            "18 0 1.5 100 re 20.5 0 2 100 re W n",
            2 * (math.acos(0.5) - math.sqrt(3) / 4),
            2,
        ),
        ("21 0 70 100 re W n", 0, 0),
        ("0 0 100 100 re 0 0 100 100 re W* n", 0, 0),
    ],
)
def test_dot_clips_keep_holes_disjoint_regions_and_empty_tangency(
    tmp_path, kernel, clip, expected_area, expected_paths
):
    doc = converted(
        tmp_path, kernel, f"q {clip} 2 w 1 J [0 5] 0 d 20 50 m 21 50 l S Q".encode()
    )
    dots = list(doc.modelspace().query("HATCH"))
    assert sum(len(dot.paths) for dot in dots) == expected_paths
    assert sum(hatch_area(dot) for dot in dots) / (25.4 / 72) ** 2 == pytest.approx(
        expected_area, abs=1e-7
    )
    for dot in dots:
        for path in dot.paths:
            edges = path.edges
            for a, b in zip(edges, edges[1:] + edges[:1]):

                def endpoint(edge, end):
                    if not hasattr(edge, "radius"):
                        return tuple(edge.end if end else edge.start)
                    angle = math.radians(edge.end_angle if end else edge.start_angle)
                    return (
                        edge.center.x + edge.radius * math.cos(angle),
                        edge.center.y + edge.radius * math.sin(angle),
                    )

                assert math.dist(endpoint(a, True), endpoint(b, False)) < 1e-9


def test_clip_intersection_keeps_area_when_another_component_only_touches(
    tmp_path, kernel
):
    doc = converted(
        tmp_path,
        kernel,
        b"q 0 0 10 10 re 20 0 10 10 re W n 0 5 20 10 re W n "
        b"1 7 m 9 7 l S 21 7 m 29 7 l S Q",
    )
    lines = list(doc.modelspace().query("LINE"))
    assert len(lines) == 1
    assert lines[0].dxf.start.x / (25.4 / 72) == pytest.approx(1)
    assert lines[0].dxf.end.x / (25.4 / 72) == pytest.approx(9)
