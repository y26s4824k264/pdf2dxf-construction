"""Exact long outline rows must not disappear at the TEXT payload boundary."""

import ezdxf
import numpy as np
import pytest

from pdf2dxf_stable.engine.text import outline_text as o
from pdf2dxf_stable.engine.text.font_catalog import (
    build_font_catalog,
    extract_font_glyph_paths,
)
from test_font_catalog import SHAPES, _write_font, _write_outline_dxf
from test_han_fragment_consensus import original_entities, recovered


def long_fixture(tmp_path, monkeypatch, text, *, fill=False, alias=False):
    shapes = dict(zip("ABCD", (SHAPES[ch] for ch in "国文中图")))
    shapes["𠀀"] = SHAPES["国"]
    shapes["0"] = (((100, 0), (700, 60), (850, 900), (200, 790), (320, 420)),)
    for char, contours in shapes.items():
        monkeypatch.setitem(SHAPES, char, contours)
    # Each fixture maps one alphabet, avoiding artificial cross-script aliases.
    for char in list(SHAPES):
        if char not in text:
            monkeypatch.delitem(SHAPES, char)
    if alias:
        monkeypatch.setitem(SHAPES, "回", SHAPES["图"])
    font = _write_font(tmp_path / "source.ttf")
    catalog = tmp_path / "font.p2dfont"
    build_font_catalog(font, catalog, charset="all")
    glyphs = {ch: extract_font_glyph_paths(font, ch) for ch in set(text)}
    path = _write_outline_dxf(tmp_path / "drawing.dxf", glyphs, text=text)
    font.unlink()
    if fill:
        doc = ezdxf.readfile(path)
        for entity in list(doc.modelspace()):
            hatch = doc.modelspace().add_hatch(dxfattribs={"layer": entity.dxf.layer})
            hatch.paths.add_polyline_path(list(entity.get_points("xy")), is_closed=True)
            hatch.set_xdata("PDF2DXF15", list(entity.get_xdata("PDF2DXF15")))
            doc.modelspace().delete_entity(entity)
        doc.saveas(path)
    return path, catalog


@pytest.mark.parametrize("fill", [False, True])
@pytest.mark.parametrize("size", [96, 97, 192, 193, 289])
@pytest.mark.parametrize("alphabet", ["国文中图", "ABCD"])
def test_long_exact_rows_keep_every_glyph_and_source_position(
    tmp_path, monkeypatch, fill, size, alphabet
):
    expected = (alphabet * 73)[:size]
    path, catalog = long_fixture(tmp_path, monkeypatch, expected, fill=fill)
    before = original_entities(path)
    original = ezdxf.readfile(path)
    atoms, _, _ = o._collect_atoms(original, 0, include_fills=True)
    report = o.recover_outline_text(path, mode="required", font_catalog_paths=[catalog])
    assert recovered(path) == expected
    assert original_entities(path) == before
    assert report["font_catalogs"]["locked"] == 1
    assert report["unpublished_glyph_matches"] == 0
    assert report.get("long_text_runs_split", 0) == int(size > 96)
    assert report.get("long_text_segments", 0) == ((size + 95) // 96 if size > 96 else 0)
    doc = ezdxf.readfile(path)
    assert len(report["accepted"]) == (size + 95) // 96
    used = []
    offset = 0
    for run in report["accepted"]:
        text = run["text"]
        assert 2 <= len(text) <= 96
        assert text == expected[offset : offset + len(text)]
        handles = run["source_handles"]
        assert not set(used) & set(handles)
        used.extend(handles)
        points = np.vstack([p for a in atoms if a.entity.dxf.handle in handles for p in a.paths])
        low, high = points.min(axis=0), points.max(axis=0)
        entity = doc.entitydb[run["text_handle"]]
        assert entity.dxf.text == text
        assert tuple(entity.dxf.insert)[:2] == pytest.approx(low)
        assert tuple(entity.dxf.align_point)[:2] == pytest.approx((high[0], low[1]))
        offset += len(text)
    assert used == [a.entity.dxf.handle for a in atoms]
    again = o.recover_outline_text(path, mode="required", font_catalog_paths=[catalog])
    assert again["emitted_text_entities"] == 0
    assert recovered(path) == expected


def test_supplementary_han_tail_is_not_cut_into_utf16_units(tmp_path, monkeypatch):
    text = ("𠀀文中图" * 25)[:97]
    path, catalog = long_fixture(tmp_path, monkeypatch, text)
    o.recover_outline_text(path, mode="required", font_catalog_paths=[catalog])
    assert recovered(path) == text


@pytest.mark.parametrize("fill", [False, True])
def test_unknown_glyph_between_long_rows_remains_geometry(tmp_path, monkeypatch, fill):
    text = "国文中图" * 49
    path, catalog = long_fixture(tmp_path, monkeypatch, text, fill=fill)
    doc = ezdxf.readfile(path)
    # The first contour of glyph 99: deformation preserves its source identity.
    entity = list(doc.modelspace())[sum(len(SHAPES[ch]) for ch in text[:98])]
    entity.translate(0, 20, 0)
    doc.saveas(path)
    before = original_entities(path)
    report = o.recover_outline_text(path, mode="required", font_catalog_paths=[catalog])
    assert recovered(path) == text[:98] + text[99:]
    assert all(entity.dxf.handle not in run["source_handles"] for run in report["accepted"])
    assert original_entities(path) == before


def test_long_repeated_two_letter_row_cannot_create_a_font_lock(tmp_path, monkeypatch):
    path, catalog = long_fixture(tmp_path, monkeypatch, "AB" * 60)
    report = o.recover_outline_text(path, mode="required", font_catalog_paths=[catalog])
    assert report["font_catalogs"]["locked"] == 0
    assert recovered(path) == ""


def test_long_run_segmentation_does_not_publish_ambiguous_labels(tmp_path, monkeypatch):
    text = "国文中" * 35 + "图" + "国文中" * 35
    path, catalog = long_fixture(tmp_path, monkeypatch, text, alias=True)
    before = original_entities(path)
    report = o.recover_outline_text(path, mode="required", font_catalog_paths=[catalog])
    assert report["font_ambiguous_geometry_matches"] > 0
    assert recovered(path) == text.replace("图", "")
    assert original_entities(path) == before


def test_long_numeric_tail_still_requires_its_own_text_consensus(tmp_path, monkeypatch):
    text = "国文中" * 32 + "0" * 10
    path, catalog = long_fixture(tmp_path, monkeypatch, text)
    report = o.recover_outline_text(path, mode="required", font_catalog_paths=[catalog])
    assert recovered(path) == text[:96]
    assert report["unpublished_glyph_matches"] == 10
    assert report["rejected_runs"][0]["reason"] == "insufficient_text_run_consensus"
