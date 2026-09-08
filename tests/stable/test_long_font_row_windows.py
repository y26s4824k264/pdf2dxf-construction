"""Long exact font rows retain bounded, independent local ambiguity evidence."""

import ezdxf
import pytest

from pdf2dxf_stable.engine.text import outline_text as o
from test_han_fragment_consensus import (
    fixture as han_fixture,
    original_entities,
    recovered,
)
from test_latin_row_recheck import fixture as latin_fixture
from test_multifont_row_recheck import mixed_fixture


def fixture(tmp_path, monkeypatch, stage, text, fill=False):
    if stage == "han_candidate":
        path, catalog = han_fixture(tmp_path, monkeypatch, text=text, fill=fill)
        return path, [catalog]
    if stage == "han_recheck":
        return mixed_fixture(tmp_path, monkeypatch, text=text, fill=fill)
    return latin_fixture(tmp_path, monkeypatch, text=text, fill=fill)


@pytest.mark.parametrize("stage", ["han_candidate", "han_recheck", "latin_recheck"])
@pytest.mark.parametrize("length", [97, 193])
@pytest.mark.parametrize("position", ["start", "middle", "end"])
@pytest.mark.parametrize("fill", [False, True])
def test_long_row_restores_parent_with_nearby_original_anchors(
    tmp_path, monkeypatch, stage, length, position, fill
):
    alphabet, parent = ("ABCD", "i") if stage == "latin_recheck" else ("国文中", "图")
    body = (alphabet * length)[: length - 1]
    index = {"start": 0, "middle": length // 2, "end": length - 1}[position]
    text = body[:index] + parent + body[index:]
    path, catalogs = fixture(tmp_path, monkeypatch, stage, text, fill)
    before = original_entities(path)
    report = o.recover_outline_text(path, mode="required", font_catalog_paths=catalogs)
    assert recovered(path) == text, (stage, length, position, report)
    assert original_entities(path) == before
    assert all(2 <= len(r["text"]) <= 96 for r in report["accepted"])
    evidence_key = (
        "font_han_fragment_evidence"
        if stage == "han_candidate"
        else "font_row_recheck_evidence"
    )
    assert report[evidence_key]
    for proof in report[evidence_key]:
        assert proof["row_window"]["glyph_count"] <= 96
        start, end = proof["row_window"]["span"]
        assert start <= proof["parent"]["span"][0] < proof["parent"]["span"][1] <= end
        assert all(
            start <= a["span"][0] < a["span"][1] <= end for a in proof["anchors"]
        )
    assert (
        o.recover_outline_text(path, mode="required", font_catalog_paths=catalogs)[
            "emitted_text_entities"
        ]
        == 0
    )


@pytest.mark.parametrize("stage", ["han_candidate", "han_recheck", "latin_recheck"])
@pytest.mark.parametrize("length", [96, 97, 193])
@pytest.mark.parametrize("fill", [False, True])
def test_far_anchor_cannot_be_borrowed_beyond_local_window(
    tmp_path, monkeypatch, stage, length, fill
):
    anchors, repeat, parent = {
        "han_candidate": ("国文", "文", "图"),
        "han_recheck": ("国文中", "中", "图"),
        "latin_recheck": ("ABCD", "B", "i"),
    }[stage]
    text = anchors + repeat * (length - len(anchors) - 1) + parent
    path, catalogs = fixture(tmp_path, monkeypatch, stage, text, fill)
    before = original_entities(path)
    o.recover_outline_text(path, mode="required", font_catalog_paths=catalogs)
    assert (parent in recovered(path)) == (length == 96)
    assert original_entities(path) == before


@pytest.mark.parametrize("stage", ["han_recheck", "latin_recheck"])
@pytest.mark.parametrize("break_kind", ["sequence", "layer", "position"])
def test_long_row_does_not_cross_source_or_geometry_breaks(
    tmp_path, monkeypatch, stage, break_kind
):
    alphabet, parent = ("ABCD", "i") if stage == "latin_recheck" else ("国文中", "图")
    text = (alphabet * 193)[:192] + parent
    path, catalogs = fixture(tmp_path, monkeypatch, stage, text)
    doc = ezdxf.readfile(path)
    # Fixtures draw the final glyph last, with two or five original contours.
    last_count = 2 if stage == "latin_recheck" else 5
    for entity in list(doc.modelspace())[-last_count:]:
        if break_kind == "sequence":
            tags = list(entity.get_xdata("PDF2DXF15"))
            tags[2] = (tags[2].code, tags[2].value + 1000)
            entity.set_xdata("PDF2DXF15", tags)
        elif break_kind == "layer":
            entity.dxf.layer = "OTHER"
        else:
            entity.translate(0, 20, 0)
    doc.saveas(path)
    o.recover_outline_text(path, mode="required", font_catalog_paths=catalogs)
    assert parent not in recovered(path)
