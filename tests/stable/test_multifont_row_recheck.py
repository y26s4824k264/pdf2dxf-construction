"""Foreign punctuation cannot hide an exact Han glyph in a verified font row."""

import ezdxf
import pytest

from pdf2dxf_stable.engine.text import outline_text as o
from pdf2dxf_stable.engine.text.font_catalog import build_font_catalog
from test_font_catalog import SHAPES, _write_font
from test_han_fragment_consensus import (
    FRAGMENT,
    fixture,
    original_entities,
    recovered,
)

DASH = ((150, 90), (450, 90), (450, 130), (150, 130))


def mixed_fixture(
    tmp_path,
    monkeypatch,
    *,
    fill=False,
    reverse=False,
    text="国文中图",
    alias="_",
    full_alias=False,
    tall=False,
    foreign_han=False,
    fragment=FRAGMENT,
):
    dash = ((400, 50), (500, 50), (500, 850), (400, 850)) if tall else DASH
    monkeypatch.setitem(SHAPES, "图", (*SHAPES["图"], dash))
    path, primary = fixture(
        tmp_path, monkeypatch, fill=fill, text=text, fragment=fragment
    )
    parent_shape = SHAPES["图"]
    with monkeypatch.context() as other:
        for ch in list(SHAPES):
            other.delitem(SHAPES, ch)
        other.setitem(SHAPES, alias, (fragment,))
        other.setitem(SHAPES, "二" if foreign_han else "-", (dash,))
        if full_alias:
            other.setitem(SHAPES, "回", parent_shape)
        font = _write_font(tmp_path / "other.ttf")
        catalog = tmp_path / "other.p2dfont"
        build_font_catalog(font, catalog)
        font.unlink()
    catalogs = [primary, catalog]
    return path, list(reversed(catalogs)) if reverse else catalogs


@pytest.mark.parametrize("fill", [False, True])
@pytest.mark.parametrize("reverse", [False, True])
def test_recheck_recovers_han_with_foreign_punctuation_conflicts(
    tmp_path, monkeypatch, fill, reverse
):
    path, catalogs = mixed_fixture(tmp_path, monkeypatch, fill=fill, reverse=reverse)
    before = original_entities(path)
    report = o.recover_outline_text(path, mode="required", font_catalog_paths=catalogs)
    assert recovered(path) == "国文中图", report
    assert original_entities(path) == before
    assert report["font_catalogs"]["locked"] == 1
    assert report["font_row_recheck_matches"] == 1
    (evidence,) = report["font_row_recheck_evidence"]
    assert evidence["parent"]["char"] == "图"
    assert len({a["char"] for a in evidence["anchors"]}) >= 3
    assert all(
        c["bbox"][3] - c["bbox"][1] < 0.72 * evidence["minimum_anchor_height"]
        for c in evidence["conflicts"]
    )
    assert (
        o.recover_outline_text(path, mode="required", font_catalog_paths=catalogs)[
            "emitted_text_entities"
        ]
        == 0
    )


@pytest.mark.parametrize("alias", ["I", "0", "二"])
def test_competing_letter_digit_or_han_label_stays_ambiguous(
    tmp_path, monkeypatch, alias
):
    path, catalogs = mixed_fixture(tmp_path, monkeypatch, alias=alias)
    o.recover_outline_text(path, mode="required", font_catalog_paths=catalogs)
    assert "图" not in recovered(path)


@pytest.mark.parametrize("text", ["国中图", "国国文图"])
def test_recheck_requires_three_distinct_uncontested_row_anchors(
    tmp_path, monkeypatch, text
):
    path, catalogs = mixed_fixture(tmp_path, monkeypatch, text=text)
    o.recover_outline_text(path, mode="required", font_catalog_paths=catalogs)
    assert "图" not in recovered(path)


@pytest.mark.parametrize("option", ["full_alias", "tall", "foreign_han"])
def test_complete_labels_large_fragments_and_foreign_han_remain_conflicts(
    tmp_path, monkeypatch, option
):
    path, catalogs = mixed_fixture(tmp_path, monkeypatch, **{option: True})
    o.recover_outline_text(path, mode="required", font_catalog_paths=catalogs)
    assert "图" not in recovered(path)


@pytest.mark.parametrize("break_kind", ["sequence", "position", "layer"])
def test_page_font_lock_does_not_replace_local_row_evidence(
    tmp_path, monkeypatch, break_kind
):
    path, catalogs = mixed_fixture(tmp_path, monkeypatch)
    doc = ezdxf.readfile(path)
    for entity in list(doc.modelspace())[-5:]:
        if break_kind == "sequence":
            tags = list(entity.get_xdata("PDF2DXF15"))
            tags[2] = (1070, tags[2].value + 100)
            entity.set_xdata("PDF2DXF15", tags)
        elif break_kind == "position":
            entity.translate(0, 20, 0)
        else:
            entity.dxf.layer = "OTHER"
    doc.saveas(path)
    o.recover_outline_text(path, mode="required", font_catalog_paths=catalogs)
    assert "图" not in recovered(path)


def test_independent_small_han_row_with_interleaved_sources_is_preserved(
    tmp_path, monkeypatch
):
    left = ((150, 700), (450, 700), (450, 720), (150, 720))
    right = tuple((x + 312, y) for x, y in left)
    spacer = ((90, 210), (120, 290), (140, 200))
    monkeypatch.setitem(SHAPES, "图", (*SHAPES["图"], spacer, right))
    path, catalogs = mixed_fixture(tmp_path, monkeypatch, fragment=left)
    report = o.recover_outline_text(path, mode="required", font_catalog_paths=catalogs)
    assert "图" not in recovered(path)
    assert report["font_row_recheck_scans"] == 1
    assert report["font_row_recheck_matches"] == 0


def test_recheck_evidence_cap_does_not_limit_confirmed_text(tmp_path, monkeypatch):
    path, catalogs = mixed_fixture(tmp_path, monkeypatch)
    doc = ezdxf.readfile(path)
    originals = list(doc.modelspace())
    for row in range(1, 34):
        for index, original in enumerate(originals):
            entity = original.copy()
            entity.translate(0, row * 12, 0)
            entity.set_xdata("PDF2DXF15", [(1070, 0), (1070, row * 100 + index + 10)])
            doc.modelspace().add_entity(entity)
    doc.saveas(path)
    report = o.recover_outline_text(path, mode="required", font_catalog_paths=catalogs)
    assert recovered(path) == "国文中图" * 34
    assert report["font_row_recheck_matches"] == 34
    assert len(report["font_row_recheck_evidence"]) == 32
    assert report["font_row_recheck_evidence_truncated"] == 2
