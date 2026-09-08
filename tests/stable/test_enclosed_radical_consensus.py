"""A locked font may disambiguate a complete glyph from its enclosing radical."""

import ezdxf
import pytest

from pdf2dxf_stable.engine.text import outline_text as o
from pdf2dxf_stable.engine.text.font_catalog import (
    build_font_catalog,
    extract_font_glyph_paths,
)
from test_font_catalog import SHAPES, _write_font, _write_outline_dxf
from test_han_fragment_consensus import original_entities, recovered

RING = (
    ((40, 40), (860, 40), (860, 860), (40, 860)),
    ((125, 140), (125, 760), (755, 760), (755, 140)),
)
CORE = ((450, 250), (650, 450), (450, 650), (250, 450))


def fixture(
    tmp_path,
    monkeypatch,
    *,
    text="文中国图",
    fill=False,
    alias=True,
    whole_alias=False,
    ring=RING,
    core=CORE,
):
    monkeypatch.setitem(SHAPES, "图", (*ring, core))
    monkeypatch.setitem(SHAPES, "囗", ring)
    if alias:
        monkeypatch.setitem(SHAPES, "⼞", ring)
    font = _write_font(tmp_path / "font.ttf", alias_for_tu=whole_alias)
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


@pytest.mark.parametrize("fill", [False, True])
def test_enclosed_radical_recovers_whole_glyph_after_independent_lock(
    tmp_path, monkeypatch, fill
):
    path, catalog = fixture(tmp_path, monkeypatch, fill=fill)
    before = original_entities(path)
    report = o.recover_outline_text(path, mode="required", font_catalog_paths=[catalog])
    assert recovered(path) == "文中国图", report
    assert original_entities(path) == before
    assert report["font_enclosed_radical_matches"] == 1
    (proof,) = report["font_enclosed_radical_evidence"]
    assert proof["parent"]["char"] == "图"
    assert proof["radical"]["char"] == "囗"
    assert proof["radical_codepoint"] == "U+2F1E"
    assert len({a["char"] for a in proof["anchors"]}) == 3
    assert proof["topology"] == "two_nested_rings_strictly_contain_all_remaining_paths"
    again = o.recover_outline_text(path, mode="required", font_catalog_paths=[catalog])
    assert again["emitted_text_entities"] == 0


@pytest.mark.parametrize("text", ["图", "文图", "文中图", "文文文图", "文中国囗"])
def test_radical_cannot_supply_its_own_lock_or_replace_standalone_text(
    tmp_path, monkeypatch, text
):
    path, catalog = fixture(tmp_path, monkeypatch, text=text)
    o.recover_outline_text(path, mode="required", font_catalog_paths=[catalog])
    assert "图" not in recovered(path)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"alias": False},
        {"whole_alias": True},
        {"core": ((125, 250), (600, 450), (400, 650))},
        {"core": ((110, 250), (600, 450), (400, 650))},
        {"ring": (RING[0],)},
    ],
)
def test_unproven_or_ambiguous_enclosure_remains_geometry(
    tmp_path, monkeypatch, kwargs
):
    path, catalog = fixture(tmp_path, monkeypatch, **kwargs)
    before = original_entities(path)
    o.recover_outline_text(path, mode="required", font_catalog_paths=[catalog])
    assert "图" not in recovered(path)
    assert original_entities(path) == before


@pytest.mark.parametrize("kind", ["vertical", "source_sequence"])
def test_enclosure_requires_anchors_in_same_source_row(tmp_path, monkeypatch, kind):
    path, catalog = fixture(tmp_path, monkeypatch)
    doc = ezdxf.readfile(path)
    for entity in list(doc.modelspace())[-3:]:
        if kind == "vertical":
            entity.translate(0, 20, 0)
        else:
            tags = list(entity.get_xdata("PDF2DXF15"))
            tags[2] = (1070, tags[2].value + 100)
            entity.set_xdata("PDF2DXF15", tags)
    doc.saveas(path)
    o.recover_outline_text(path, mode="required", font_catalog_paths=[catalog])
    assert "图" not in recovered(path)


@pytest.mark.parametrize("label", ["回", "口", "A"])
def test_foreign_catalog_conflicting_window_is_never_silenced(
    tmp_path, monkeypatch, label
):
    path, catalog = fixture(tmp_path, monkeypatch)
    for char in list(SHAPES):
        monkeypatch.delitem(SHAPES, char)
    monkeypatch.setitem(SHAPES, label, RING)
    other_font = _write_font(tmp_path / "other.ttf")
    other_catalog = tmp_path / "other.p2dfont"
    build_font_catalog(other_font, other_catalog)
    other_font.unlink()
    for catalogs in ([catalog, other_catalog], [other_catalog, catalog]):
        report = o.recover_outline_text(
            path, mode="required", font_catalog_paths=catalogs
        )
        assert "图" not in recovered(path)
        assert report["font_enclosed_radical_matches"] == 0


def test_radical_alias_must_have_same_geometry_in_the_locked_font(
    tmp_path, monkeypatch
):
    monkeypatch.setitem(SHAPES, "⼞", SHAPES["文"])
    path, catalog = fixture(tmp_path, monkeypatch, alias=False)
    report = o.recover_outline_text(path, mode="required", font_catalog_paths=[catalog])
    assert "图" not in recovered(path)
    assert report["font_enclosed_radical_matches"] == 0


def test_another_font_cannot_supply_the_radical_alias(tmp_path, monkeypatch):
    path, catalog = fixture(tmp_path, monkeypatch, alias=False)
    for char in list(SHAPES):
        monkeypatch.delitem(SHAPES, char)
    monkeypatch.setitem(SHAPES, "⼞", RING)
    other_font = _write_font(tmp_path / "other.ttf")
    other_catalog = tmp_path / "other.p2dfont"
    build_font_catalog(other_font, other_catalog)
    other_font.unlink()
    report = o.recover_outline_text(
        path, mode="required", font_catalog_paths=[catalog, other_catalog]
    )
    assert "图" not in recovered(path)
    assert report["font_enclosed_radical_matches"] == 0
