"""Ambiguous windows must still block overlapping unique glyph interpretations."""

import shutil

import ezdxf
import pytest

from pdf2dxf_stable.engine.text import outline_text as o
from pdf2dxf_stable.engine.text.font_catalog import build_font_catalog
from test_font_catalog import SHAPES, _write_font
from test_han_fragment_consensus import fixture, original_entities, recovered

TALL = ((400, 50), (500, 50), (500, 850), (400, 850))


def ambiguous_fixture(tmp_path, monkeypatch, *, fill=False, alias="二", cross=False):
    if cross:
        monkeypatch.setitem(
            SHAPES, "平", (((40, 40), (760, 80), (630, 780), (260, 710)),)
        )
    path, primary = fixture(
        tmp_path,
        monkeypatch,
        fill=fill,
        fragment=TALL,
        text="国文平中图" if cross else "国文中图",
    )
    if cross:
        doc = ezdxf.readfile(path)
        atoms, _, _ = o._collect_atoms(doc, 0, include_fills=True)
        # Last contour of 中 plus the first contour of 图: a competing window
        # crossing both glyphs, with all original coordinates preserved.
        window = atoms[-5:-3]
        low = tuple(min(atom.low[axis] for atom in window) for axis in (0, 1))
        shapes = tuple(
            tuple(
                ((float(x) - low[0]) * 1000, (float(y) - low[1]) * 1000)
                for x, y in points[:-1]
            )
            for atom in window
            for points in atom.paths
        )
    else:
        shapes = (TALL,)
    with monkeypatch.context() as other:
        for char in list(SHAPES):
            other.delitem(SHAPES, char)
        other.setitem(SHAPES, alias, shapes)
        if cross:
            other.setitem(SHAPES, "三", shapes)
        font = _write_font(tmp_path / "other.ttf")
        secondary = tmp_path / "other.p2dfont"
        build_font_catalog(font, secondary)
        font.unlink()
    return path, primary, secondary


@pytest.mark.parametrize("fill", [False, True])
@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("alias", ["二", "I", "0"])
def test_adding_conflicting_catalog_does_not_publish_rejected_parent(
    tmp_path, monkeypatch, fill, reverse, alias
):
    path, primary, secondary = ambiguous_fixture(
        tmp_path, monkeypatch, fill=fill, alias=alias
    )
    single = tmp_path / "single.dxf"
    shutil.copyfile(path, single)
    o.recover_outline_text(single, mode="required", font_catalog_paths=[primary])
    assert recovered(single) == "国文中"
    before = original_entities(path)
    catalogs = [primary, secondary]
    if reverse:
        catalogs.reverse()
    report = o.recover_outline_text(path, mode="required", font_catalog_paths=catalogs)
    assert report["font_ambiguous_geometry_matches"] >= 1
    assert recovered(path) == "国文中"
    assert original_entities(path) == before
    assert report["font_ambiguous_overlap_rejections"] >= 1
    assert report["font_row_recheck_matches"] == 0
    repeat = o.recover_outline_text(path, mode="required", font_catalog_paths=catalogs)
    assert repeat["emitted_text_entities"] == 0
    assert recovered(path) == "国文中"


@pytest.mark.parametrize("fill", [False, True])
def test_conflict_inside_one_catalog_still_blocks_parent(tmp_path, monkeypatch, fill):
    monkeypatch.setitem(SHAPES, "二", (TALL,))
    path, catalog = fixture(tmp_path, monkeypatch, fill=fill, fragment=TALL)
    before = original_entities(path)
    report = o.recover_outline_text(path, mode="required", font_catalog_paths=[catalog])
    assert report["font_ambiguous_geometry_matches"] >= 1
    assert recovered(path) == "国文中"
    assert original_entities(path) == before
    assert report["font_ambiguous_overlap_rejections"] >= 1


@pytest.mark.parametrize("fill", [False, True])
def test_ambiguous_window_crossing_glyph_boundary_keeps_both_outlines(
    tmp_path, monkeypatch, fill
):
    path, primary, secondary = ambiguous_fixture(
        tmp_path, monkeypatch, fill=fill, cross=True
    )
    before = original_entities(path)
    report = o.recover_outline_text(
        path, mode="required", font_catalog_paths=[primary, secondary]
    )
    assert report["font_ambiguous_geometry_matches"] >= 1
    assert recovered(path) == "国文平"
    assert original_entities(path) == before
    assert report["font_ambiguous_overlap_rejections"] >= 2


@pytest.mark.parametrize("fill", [False, True])
def test_ambiguous_whole_glyph_blocks_its_child_but_not_adjacent_anchors(
    tmp_path, monkeypatch, fill
):
    path, primary = fixture(
        tmp_path, monkeypatch, fill=fill, fragment=TALL, position=0
    )
    parent_shape = SHAPES["图"]
    with monkeypatch.context() as other:
        for char in list(SHAPES):
            other.delitem(SHAPES, char)
        other.setitem(SHAPES, "回", parent_shape)
        font = _write_font(tmp_path / "alias.ttf")
        secondary = tmp_path / "alias.p2dfont"
        build_font_catalog(font, secondary)
        font.unlink()
    before = original_entities(path)
    report = o.recover_outline_text(
        path, mode="required", font_catalog_paths=[primary, secondary]
    )
    assert report["font_ambiguous_geometry_matches"] >= 1
    assert recovered(path) == "国文中"
    assert original_entities(path) == before
    assert report["font_ambiguous_overlap_rejections"] >= 1
