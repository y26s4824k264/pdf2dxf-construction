"""A short Han stroke is not a competing glyph at a verified row's scale."""

import ezdxf
import pytest
from ezdxf.lldxf.tagwriter import TagCollector

from pdf2dxf_stable.engine.text import outline_text as o
from pdf2dxf_stable.engine.text.font_catalog import (
    build_font_catalog,
    extract_font_glyph_paths,
)
from test_font_catalog import SHAPES, _write_font, _write_outline_dxf

FRAGMENT = ((150, 700), (750, 700), (750, 740), (150, 740))


def fixture(
    tmp_path,
    monkeypatch,
    *,
    position=3,
    fill=False,
    text="国文中图",
    fragment=FRAGMENT,
    alias=False,
):
    contours = list(SHAPES["图"])
    contours.insert(position, fragment)
    monkeypatch.setitem(SHAPES, "图", tuple(contours))
    monkeypatch.setitem(SHAPES, "一", (fragment,))
    font = _write_font(tmp_path / "font.ttf", alias_for_tu=alias)
    catalog = tmp_path / "font.p2dfont"
    build_font_catalog(font, catalog)
    glyphs = {ch: extract_font_glyph_paths(font, ch) for ch in set(text)}
    path = _write_outline_dxf(tmp_path / "drawing.dxf", glyphs, text=text)
    if fill:
        doc = ezdxf.readfile(path)
        for outline in list(doc.modelspace()):
            hatch = doc.modelspace().add_hatch(dxfattribs={"layer": outline.dxf.layer})
            hatch.paths.add_polyline_path(
                list(outline.get_points("xy")), is_closed=True
            )
            hatch.set_xdata("PDF2DXF15", list(outline.get_xdata("PDF2DXF15")))
            doc.modelspace().delete_entity(outline)
        doc.saveas(path)
    font.unlink()
    return path, catalog


def recovered(path):
    return "".join(
        e.dxf.text
        for e in ezdxf.readfile(path)
        .modelspace()
        .query(f'TEXT[layer=="{o.TEXT_LAYER}"]')
    )


def original_entities(path):
    doc = ezdxf.readfile(path)
    result = {}
    for entity in doc.modelspace():
        if entity.dxf.layer == o.TEXT_LAYER:
            continue
        if entity.has_xdata(o.APPID):
            entity.dxf.layer = list(entity.get_xdata(o.APPID))[1].value
            entity.discard_xdata(o.APPID)
        result[entity.dxf.handle] = TagCollector.dxftags(entity)
    return result


@pytest.mark.parametrize("position", [0, 1, 3])
@pytest.mark.parametrize("fill", [False, True])
def test_small_han_fragment_does_not_block_complete_exact_row(
    tmp_path, monkeypatch, position, fill
):
    path, catalog = fixture(tmp_path, monkeypatch, position=position, fill=fill)
    before = original_entities(path)
    report = o.recover_outline_text(path, mode="required", font_catalog_paths=[catalog])
    assert recovered(path) == "国文中图", report
    assert original_entities(path) == before
    assert report["font_contained_han_fragments_suppressed"] == 1
    (evidence,) = report["font_han_fragment_evidence"]
    assert evidence["parent"]["char"] == "图"
    assert set(evidence["parent"]["source_handles"]) == set(list(before)[-4:])
    assert [fragment["char"] for fragment in evidence["fragments"]] == ["一"]
    assert len({"图", *(anchor["char"] for anchor in evidence["anchors"])}) >= 3
    assert evidence["maximum_fragment_height_ratio"] == pytest.approx(40 / 730)
    assert report["font_catalogs"]["locked"] == 1
    assert (
        o.recover_outline_text(path, mode="required", font_catalog_paths=[catalog])[
            "emitted_text_entities"
        ]
        == 0
    )


@pytest.mark.parametrize("text", ["图", "国图", "国国图"])
def test_fragment_resolution_requires_two_distinct_uncontested_anchors(
    tmp_path, monkeypatch, text
):
    path, catalog = fixture(tmp_path, monkeypatch, text=text)
    before = original_entities(path)
    o.recover_outline_text(path, mode="required", font_catalog_paths=[catalog])
    assert recovered(path) == ""
    assert original_entities(path) == before


def test_full_height_competing_han_is_not_a_small_fragment(tmp_path, monkeypatch):
    fragment = ((400, 50), (500, 50), (500, 850), (400, 850))
    path, catalog = fixture(tmp_path, monkeypatch, fragment=fragment)
    o.recover_outline_text(path, mode="required", font_catalog_paths=[catalog])
    assert recovered(path) == "国文中"


@pytest.mark.parametrize("break_kind", ["vertical", "source_sequence"])
def test_anchors_outside_continuous_source_row_cannot_resolve_fragment(
    tmp_path, monkeypatch, break_kind
):
    path, catalog = fixture(tmp_path, monkeypatch)
    doc = ezdxf.readfile(path)
    for e in list(doc.modelspace())[-4:]:
        if break_kind == "vertical":
            e.translate(0, 15, 0)
        else:
            tags = list(e.get_xdata("PDF2DXF15"))
            tags[2] = (1070, tags[2].value + 100)
            e.set_xdata("PDF2DXF15", tags)
    doc.saveas(path)
    o.recover_outline_text(path, mode="required", font_catalog_paths=[catalog])
    assert "图" not in recovered(path)


def test_two_small_han_can_be_an_independent_run_inside_a_large_shape(
    tmp_path, monkeypatch
):
    left = ((150, 700), (400, 700), (400, 725), (150, 725))
    right = tuple((x + 262, y) for x, y in left)
    monkeypatch.setitem(SHAPES, "图", (*SHAPES["图"], right))
    path, catalog = fixture(tmp_path, monkeypatch, position=3, fragment=left)
    o.recover_outline_text(path, mode="required", font_catalog_paths=[catalog])
    assert "图" not in recovered(path)


def test_equal_full_glyph_labels_remain_ambiguous(tmp_path, monkeypatch):
    path, catalog = fixture(tmp_path, monkeypatch, alias=True)
    o.recover_outline_text(path, mode="required", font_catalog_paths=[catalog])
    assert "图" not in recovered(path) and "回" not in recovered(path)


def test_competing_fragment_from_another_font_cannot_be_absorbed(tmp_path, monkeypatch):
    contours = (*SHAPES["图"], FRAGMENT)
    monkeypatch.setitem(SHAPES, "图", contours)
    font = _write_font(tmp_path / "parent.ttf")
    parent = tmp_path / "parent.p2dfont"
    build_font_catalog(font, parent)
    glyphs = {ch: extract_font_glyph_paths(font, ch) for ch in "国文中图"}
    path = _write_outline_dxf(tmp_path / "drawing.dxf", glyphs, text="国文中图")
    for ch in list(SHAPES):
        monkeypatch.delitem(SHAPES, ch)
    monkeypatch.setitem(SHAPES, "一", (FRAGMENT,))
    other_font = _write_font(tmp_path / "child.ttf")
    other = tmp_path / "child.p2dfont"
    build_font_catalog(other_font, other)
    font.unlink()
    other_font.unlink()
    o.recover_outline_text(path, mode="required", font_catalog_paths=[parent, other])
    assert "图" not in recovered(path)


def test_ambiguous_anchor_labels_do_not_support_fragment_resolution(
    tmp_path, monkeypatch
):
    monkeypatch.setitem(SHAPES, "回", SHAPES["国"])
    path, catalog = fixture(tmp_path, monkeypatch, text="国中图")
    report = o.recover_outline_text(path, mode="required", font_catalog_paths=[catalog])
    assert "图" not in recovered(path)
    assert report["font_contained_han_fragments_suppressed"] == 0


def test_fragment_evidence_is_bounded_without_dropping_confirmed_rows(
    tmp_path, monkeypatch
):
    path, catalog = fixture(tmp_path, monkeypatch)
    doc = ezdxf.readfile(path)
    originals = list(doc.modelspace())
    for row in range(1, 34):
        for index, original in enumerate(originals):
            entity = original.copy()
            entity.translate(0, row * 12, 0)
            entity.set_xdata("PDF2DXF15", [(1070, 0), (1070, row * 100 + index + 10)])
            doc.modelspace().add_entity(entity)
    doc.saveas(path)
    report = o.recover_outline_text(path, mode="required", font_catalog_paths=[catalog])
    assert recovered(path) == "国文中图" * 34
    assert report["font_han_fragment_resolved_candidates"] == 34
    assert report["font_contained_han_fragments_suppressed"] == 34
    assert len(report["font_han_fragment_evidence"]) == 32
    assert report["font_han_fragment_evidence_truncated"] == 2
