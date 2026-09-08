"""Half-enclosed parts need exact labels, disjoint geometry and independent anchors."""

import ezdxf
import numpy as np
import pytest

from pdf2dxf_stable.engine.text import outline_text as o
from pdf2dxf_stable.engine.text.contour_topology import half_enclosure_evidence
from pdf2dxf_stable.engine.text.font_catalog import (
    build_font_catalog,
    extract_font_glyph_paths,
)
from test_font_catalog import SHAPES, _write_font, _write_outline_dxf
from test_han_fragment_consensus import original_entities, recovered

WRAPPER = ((40, 40), (860, 40), (860, 100), (140, 100), (140, 700), (40, 700))
CORE = ((450, 250), (650, 450), (450, 860), (250, 450))


def fixture(
    tmp_path,
    monkeypatch,
    *,
    text="文中国建",
    fill=False,
    alias=True,
    canonical=True,
    canonical_shape=None,
    alias_shape=None,
    core=CORE,
    wrapper=WRAPPER,
    whole_alias=False,
):
    monkeypatch.setitem(SHAPES, "建", (wrapper, core))
    monkeypatch.setitem(SHAPES, "廴", (canonical_shape or wrapper,))
    if not canonical:
        monkeypatch.delitem(SHAPES, "廴")
    if alias:
        monkeypatch.setitem(SHAPES, "⼵", (alias_shape or wrapper,))
    if whole_alias:
        monkeypatch.setitem(SHAPES, "回", (wrapper, core))
    font = _write_font(tmp_path / "font.ttf")
    catalog = tmp_path / "font.p2dfont"
    build_font_catalog(font, catalog)
    glyphs = {ch: extract_font_glyph_paths(font, ch) for ch in set(text)}
    path = _write_outline_dxf(tmp_path / "drawing.dxf", glyphs, text=text)
    if fill:
        doc = ezdxf.readfile(path)
        for e in list(doc.modelspace()):
            hatch = doc.modelspace().add_hatch(dxfattribs={"layer": e.dxf.layer})
            hatch.paths.add_polyline_path(list(e.get_points("xy")), is_closed=True)
            hatch.set_xdata("PDF2DXF15", list(e.get_xdata("PDF2DXF15")))
            doc.modelspace().delete_entity(e)
        doc.saveas(path)
    font.unlink()
    return path, catalog


@pytest.mark.parametrize("fill", [False, True])
@pytest.mark.parametrize("position", ["start", "middle", "end"])
@pytest.mark.parametrize("alias", [False, True])
def test_half_enclosed_whole_glyph_recovers_without_changing_source(
    tmp_path, monkeypatch, fill, position, alias
):
    text = {"start": "建文中国", "middle": "文中国建文中国", "end": "文中国建"}[
        position
    ]
    path, catalog = fixture(tmp_path, monkeypatch, text=text, fill=fill, alias=alias)
    before = original_entities(path)
    report = o.recover_outline_text(path, mode="required", font_catalog_paths=[catalog])
    assert recovered(path) == text
    assert original_entities(path) == before
    assert report["font_enclosed_radical_half_matches"] == 1
    (proof,) = report["font_enclosed_radical_evidence"]
    assert proof["parent"]["char"] == "建" and proof["radical_codepoint"] == "U+2F35"
    assert {a["char"] for a in proof["anchors"]} == set("文中国")
    assert proof["geometry_evidence"]["open_side"] == "max_y"
    assert proof["geometry_evidence"]["radical_disjoint_from_all_remaining_polygons"]
    assert (
        o.recover_outline_text(path, mode="required", font_catalog_paths=[catalog])[
            "emitted_text_entities"
        ]
        == 0
    )


@pytest.mark.parametrize("text", ["建", "文建", "文中建", "文文文建", "文中国廴"])
def test_half_enclosure_cannot_supply_its_own_anchors_or_replace_standalone_radical(
    tmp_path, monkeypatch, text
):
    path, catalog = fixture(tmp_path, monkeypatch, text=text)
    o.recover_outline_text(path, mode="required", font_catalog_paths=[catalog])
    assert "建" not in recovered(path)


@pytest.mark.parametrize("canonical_matches", [False, True])
def test_actual_canonical_radical_outline_is_verified_independently_of_compatibility_form(
    tmp_path, monkeypatch, canonical_matches
):
    different = ((80, 200), (850, 200), (570, 770))
    path, catalog = fixture(
        tmp_path,
        monkeypatch,
        canonical_shape=WRAPPER if canonical_matches else different,
        alias_shape=different if canonical_matches else WRAPPER,
    )
    report = o.recover_outline_text(path, mode="required", font_catalog_paths=[catalog])
    assert recovered(path) == ("文中国建" if canonical_matches else "文中国")
    if canonical_matches:
        (proof,) = report["font_enclosed_radical_evidence"]
        assert proof["radical_outline_codepoint"] == "U+5EF4"
        assert proof["radical_codepoint"] == "U+2F35"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"canonical": False},
        {"whole_alias": True},
        {"core": ((450, 250), (650, 450), (450, 650), (250, 450))},
        {"core": tuple((x, y + 700) for x, y in CORE)},
        {"core": ((-20, 250), (650, 450), (450, 860), (250, 450))},
        {"core": ((140, 250), (650, 450), (450, 860), (140, 450))},
        {"core": ((120, 250), (650, 450), (450, 860), (120, 450))},
    ],
)
def test_no_label_or_no_interlocking_topology_keeps_geometry(
    tmp_path, monkeypatch, kwargs
):
    path, catalog = fixture(tmp_path, monkeypatch, **kwargs)
    before = original_entities(path)
    o.recover_outline_text(path, mode="required", font_catalog_paths=[catalog])
    assert "建" not in recovered(path)
    assert original_entities(path) == before


@pytest.mark.parametrize("label", ["口", "A"])
@pytest.mark.parametrize("reverse", [False, True])
def test_foreign_radical_alias_still_blocks_half_enclosure(
    tmp_path, monkeypatch, label, reverse
):
    path, catalog = fixture(tmp_path, monkeypatch)
    with monkeypatch.context() as other:
        for char in list(SHAPES):
            other.delitem(SHAPES, char)
        other.setitem(SHAPES, label, (WRAPPER,))
        font = _write_font(tmp_path / "other.ttf")
        foreign = tmp_path / "other.p2dfont"
        build_font_catalog(font, foreign)
        font.unlink()
    catalogs = [catalog, foreign]
    o.recover_outline_text(
        path,
        mode="required",
        font_catalog_paths=catalogs[::-1] if reverse else catalogs,
    )
    assert "建" not in recovered(path)


@pytest.mark.parametrize("kind", ["layer", "source", "vertical"])
def test_half_enclosure_respects_source_row_boundaries(tmp_path, monkeypatch, kind):
    path, catalog = fixture(tmp_path, monkeypatch)
    doc = ezdxf.readfile(path)
    for e in list(doc.modelspace())[-2:]:
        if kind == "layer":
            e.dxf.layer = "OTHER"
        elif kind == "source":
            tags = list(e.get_xdata("PDF2DXF15"))
            tags[2] = (1070, tags[2].value + 100)
            e.set_xdata("PDF2DXF15", tags)
        else:
            e.translate(0, 20, 0)
    doc.saveas(path)
    o.recover_outline_text(path, mode="required", font_catalog_paths=[catalog])
    assert "建" not in recovered(path)


def closed(points):
    return np.array([*points, points[0]], dtype=float)


@pytest.mark.parametrize("rotation", [0, 1, 2, 3])
@pytest.mark.parametrize("reverse", [False, True])
def test_half_enclosure_is_invariant_under_axis_rotation_and_winding(rotation, reverse):
    matrix = np.linalg.matrix_power(np.array([[0, -1], [1, 0]]), rotation)
    ring, core = (closed(points) @ matrix for points in (WRAPPER, CORE))
    if reverse:
        ring, core = ring[::-1], core[::-1]
    before = [p.copy() for p in (ring, core)]
    proof = half_enclosure_evidence([ring], [core])
    assert proof is not None and proof["minimum_part_distance"] > 0
    assert all(np.array_equal(a, b) for a, b in zip(before, (ring, core)))


@pytest.mark.parametrize(
    "scale,offset", [(0.001, (10, -20)), (1, (0, 0)), (1000, (-100, 200))]
)
def test_half_enclosure_preserves_uniform_scale_and_translation(scale, offset):
    ring, core = (closed(points) * scale + offset for points in (WRAPPER, CORE))
    proof = half_enclosure_evidence([ring], [core])
    assert proof is not None
    reference = half_enclosure_evidence([closed(WRAPPER)], [closed(CORE)])
    assert proof["convex_hull_intersection_area"] == pytest.approx(
        reference["convex_hull_intersection_area"] * scale**2
    )


@pytest.mark.parametrize(
    "rings,parts",
    [
        ([], [closed(CORE)]),
        ([closed(WRAPPER)], []),
        ([closed(WRAPPER)] * 2, [closed(CORE)]),
        ([closed(WRAPPER)[:-1]], [closed(CORE)]),
        ([closed(WRAPPER)], [closed(CORE)[:-1]]),
        ([closed(WRAPPER)], [np.full((4, 2), np.nan)]),
        ([np.full((4, 2), np.inf)], [closed(CORE)]),
        ([np.ones((4, 3))], [closed(CORE)]),
        ([closed([(0, 0), (1, 1), (2, 2)])], [closed(CORE)]),
        ([closed(WRAPPER)], [closed([(0, 0), (1, 1), (2, 2)])]),
        ([closed(WRAPPER)], [closed([(250, 250), (650, 860), (250, 860), (650, 250)])]),
        # A part's polygon contains the radical even though its boundary is disjoint.
        ([closed(WRAPPER)], [closed([(0, 0), (900, 0), (900, 900), (0, 900)])]),
        # One otherwise qualifying part cannot excuse a second touching/crossing part.
        (
            [closed(WRAPPER)],
            [closed(CORE), closed([(100, 150), (180, 150), (180, 200), (100, 200)])],
        ),
    ],
)
def test_invalid_or_touching_full_geometry_has_no_half_enclosure_evidence(rings, parts):
    assert half_enclosure_evidence(rings, parts) is None


def add_closed_glyph(monkeypatch):
    from test_enclosed_radical_consensus import CORE as CLOSED_CORE, RING

    monkeypatch.setitem(SHAPES, "图", (*RING, CLOSED_CORE))
    monkeypatch.setitem(SHAPES, "囗", RING)
    monkeypatch.setitem(SHAPES, "⼞", RING)


@pytest.mark.parametrize("text", ["文中国图建", "文中国建图"])
@pytest.mark.parametrize("fill", [False, True])
def test_independently_verified_radical_can_connect_the_next_proof(
    tmp_path, monkeypatch, text, fill
):
    add_closed_glyph(monkeypatch)
    path, catalog = fixture(tmp_path, monkeypatch, text=text, fill=fill)
    before = original_entities(path)
    report = o.recover_outline_text(path, mode="required", font_catalog_paths=[catalog])
    assert recovered(path) == text
    assert original_entities(path) == before
    proofs = report["font_enclosed_radical_evidence"]
    assert [p["dependency_round"] for p in proofs] == [1, 2]
    assert [p["parent"]["char"] for p in proofs] == list(text[-2:])
    assert [b["char"] for b in proofs[1]["verified_bridges"]] == [text[-2]]
    assert proofs[1]["verified_bridges"][0]["verified_catalog_ids"] == [
        proofs[0]["catalog_id"]
    ]
    assert all({a["char"] for a in p["anchors"]} == set("文中国") for p in proofs)


def test_local_candidates_cannot_bootstrap_each_other_with_a_remote_font_lock(
    tmp_path, monkeypatch
):
    add_closed_glyph(monkeypatch)
    path, catalog = fixture(tmp_path, monkeypatch, text="文中国文中图建")
    doc = ezdxf.readfile(path)
    for e in list(doc.modelspace())[sum(len(SHAPES[ch]) for ch in "文中国") :]:
        e.translate(0, 20, 0)
    doc.saveas(path)
    report = o.recover_outline_text(path, mode="required", font_catalog_paths=[catalog])
    assert report["font_catalogs"]["locked"] == 1
    assert recovered(path) == "文中国文中"
    assert report["font_enclosed_radical_matches"] == 0


def test_confirmed_chain_still_requires_original_anchors_inside_96_glyph_window(
    tmp_path, monkeypatch
):
    path, catalog = fixture(tmp_path, monkeypatch, text="文中国" + "建" * 94)
    before = original_entities(path)
    report = o.recover_outline_text(path, mode="required", font_catalog_paths=[catalog])
    assert recovered(path) == "文中国" + "建" * 93
    assert original_entities(path) == before
    assert report["font_enclosed_radical_matches"] == 93
    assert report["font_enclosed_radical_rounds"] == 93
    assert report["font_enclosed_radical_evidence_truncated"] == 61
    assert report["font_enclosed_radical_rejection_counts"] == {
        "insufficient_independent_local_row_anchors": 1
    }


def test_an_ordinary_han_component_cannot_claim_radical_identity(tmp_path, monkeypatch):
    monkeypatch.setitem(SHAPES, "甲", (WRAPPER,))
    path, catalog = fixture(tmp_path, monkeypatch, canonical=False, alias=False)
    o.recover_outline_text(path, mode="required", font_catalog_paths=[catalog])
    assert recovered(path) == "文中国"


def test_a_bridge_keeps_the_font_that_actually_proved_its_radical(
    tmp_path, monkeypatch
):
    from test_enclosed_radical_consensus import RING

    add_closed_glyph(monkeypatch)
    monkeypatch.delitem(SHAPES, "⼞")
    path, primary = fixture(tmp_path, monkeypatch, text="文中国建图")
    with monkeypatch.context() as other:
        # Both fonts contain the same exact whole glyphs. Only the first can
        # prove 建's canonical radical; only the second can prove 图's counter.
        other.delitem(SHAPES, "廴")
        other.setitem(SHAPES, "⼞", RING)
        font = _write_font(tmp_path / "other.ttf")
        secondary = tmp_path / "other.p2dfont"
        build_font_catalog(font, secondary)
        font.unlink()
    report = o.recover_outline_text(
        path, mode="required", font_catalog_paths=[primary, secondary]
    )
    assert report["font_catalogs"]["locked"] == 2
    assert recovered(path) == "文中国建"
