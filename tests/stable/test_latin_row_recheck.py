"""An exact Latin glyph can contain a foreign font's punctuation contour."""

import ezdxf
import pytest

from pdf2dxf_stable.engine.text import outline_text as o
from pdf2dxf_stable.engine.text.font_catalog import (
    build_font_catalog,
    extract_font_glyph_paths,
)
from test_font_catalog import SHAPES, _write_font, _write_outline_dxf
from test_han_fragment_consensus import original_entities, recovered

STEM = ((400, 0), (500, 0), (500, 580), (400, 580))
DOT = ((400, 760), (500, 760), (500, 880), (400, 880))


def fixture(
    tmp_path,
    monkeypatch,
    *,
    text="ABCDi",
    fill=False,
    reverse=False,
    alias="–",
    full_alias=False,
    tall=False,
    ambiguous_punctuation=False,
):
    shapes = dict(zip("ABCD", (SHAPES[ch] for ch in "国文中图")))
    stem = ((400, 0), (500, 0), (500, 900), (400, 900)) if tall else STEM
    shapes["i"] = (stem, DOT)
    for ch in list(SHAPES):
        monkeypatch.delitem(SHAPES, ch)
    for ch, paths in shapes.items():
        monkeypatch.setitem(SHAPES, ch, paths)
    font = _write_font(tmp_path / "letters.ttf")
    primary = tmp_path / "letters.p2dfont"
    build_font_catalog(font, primary, charset="all")
    glyphs = {ch: extract_font_glyph_paths(font, ch) for ch in set(text)}
    path = _write_outline_dxf(tmp_path / "drawing.dxf", glyphs, text=text)
    font.unlink()
    for ch in list(SHAPES):
        monkeypatch.delitem(SHAPES, ch)
    monkeypatch.setitem(SHAPES, alias, (stem,))
    if ambiguous_punctuation:
        monkeypatch.setitem(SHAPES, "_", (stem,))
    if full_alias:
        monkeypatch.setitem(SHAPES, "j", shapes["i"])
    font = _write_font(tmp_path / "other.ttf")
    foreign = tmp_path / "other.p2dfont"
    build_font_catalog(font, foreign, charset="all")
    font.unlink()
    if fill:
        doc = ezdxf.readfile(path)
        for entity in list(doc.modelspace()):
            hatch = doc.modelspace().add_hatch(dxfattribs={"layer": entity.dxf.layer})
            hatch.paths.add_polyline_path(list(entity.get_points("xy")), is_closed=True)
            hatch.set_xdata("PDF2DXF15", list(entity.get_xdata("PDF2DXF15")))
            doc.modelspace().delete_entity(entity)
        doc.saveas(path)
    catalogs = [primary, foreign]
    return path, catalogs[::-1] if reverse else catalogs


@pytest.mark.parametrize("fill", [False, True])
@pytest.mark.parametrize("reverse", [False, True])
def test_foreign_punctuation_does_not_hide_verified_latin_parent(
    tmp_path, monkeypatch, fill, reverse
):
    path, catalogs = fixture(tmp_path, monkeypatch, fill=fill, reverse=reverse)
    before = original_entities(path)
    report = o.recover_outline_text(path, mode="required", font_catalog_paths=catalogs)
    assert recovered(path) == "ABCDi", report
    assert original_entities(path) == before
    assert report["font_row_recheck_matches"] == 1
    (proof,) = report["font_row_recheck_evidence"]
    assert proof["script"] == "latin" and proof["parent"]["char"] == "i"
    assert len({a["char"].lower() for a in proof["anchors"]}) == 4
    assert proof["conflicts"][0]["labels"] == ["–"]
    assert proof["fragment_height_reference"] == "parent_height"
    assert (
        o.recover_outline_text(path, mode="required", font_catalog_paths=catalogs)[
            "emitted_text_entities"
        ]
        == 0
    )


@pytest.mark.parametrize("alias", ["I", "0", "一", "|"])
def test_foreign_letter_digit_han_and_symbol_remain_competing_text(
    tmp_path, monkeypatch, alias
):
    path, catalogs = fixture(tmp_path, monkeypatch, alias=alias)
    report = o.recover_outline_text(path, mode="required", font_catalog_paths=catalogs)
    assert "i" not in recovered(path)
    assert report["font_row_recheck_matches"] == 0


@pytest.mark.parametrize("text", ["ABCi", "ABABi", "Ai"])
def test_latin_recheck_requires_four_distinct_existing_anchors(
    tmp_path, monkeypatch, text
):
    path, catalogs = fixture(tmp_path, monkeypatch, text=text)
    o.recover_outline_text(path, mode="required", font_catalog_paths=catalogs)
    assert "i" not in recovered(path)


@pytest.mark.parametrize("option", ["full_alias", "tall"])
def test_complete_label_and_full_height_conflicts_remain_ambiguous(
    tmp_path, monkeypatch, option
):
    path, catalogs = fixture(tmp_path, monkeypatch, **{option: True})
    o.recover_outline_text(path, mode="required", font_catalog_paths=catalogs)
    assert "i" not in recovered(path)


@pytest.mark.parametrize("break_kind", ["sequence", "position", "layer"])
def test_latin_font_lock_requires_continuous_local_row(
    tmp_path, monkeypatch, break_kind
):
    path, catalogs = fixture(tmp_path, monkeypatch)
    doc = ezdxf.readfile(path)
    for entity in list(doc.modelspace())[-2:]:
        if break_kind == "sequence":
            tags = list(entity.get_xdata("PDF2DXF15"))
            tags[2] = (1070, tags[2].value + 100)
            entity.set_xdata("PDF2DXF15", tags)
        elif break_kind == "position":
            entity.translate(0, 20, 0)
        else:
            entity.dxf.layer = "OTHER"
    doc.saveas(path)
    report = o.recover_outline_text(path, mode="required", font_catalog_paths=catalogs)
    assert report["font_catalogs"]["locked"] == 1
    assert "i" not in recovered(path)


def test_same_span_punctuation_disagreement_does_not_choose_a_fragment_label(
    tmp_path, monkeypatch
):
    path, catalogs = fixture(tmp_path, monkeypatch, ambiguous_punctuation=True)
    report = o.recover_outline_text(path, mode="required", font_catalog_paths=catalogs)
    assert recovered(path) == "ABCDi"
    # This parent is already accepted by the original scan because its only
    # child window is ambiguous; the new recheck need not republish it.
    assert report["font_row_recheck_matches"] == 0
