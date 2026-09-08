"""Verified row stages compose without allowing a candidate to prove itself."""

import ezdxf
import pytest

from pdf2dxf_stable.engine.text import outline_text as o
from pdf2dxf_stable.engine.text.font_catalog import build_font_catalog
from test_enclosed_radical_consensus import fixture
from test_font_catalog import SHAPES, _write_font
from test_han_fragment_consensus import FRAGMENT, original_entities, recovered
from test_multifont_row_recheck import DASH

OPEN_RADICAL = ((40, 40), (860, 40), (860, 100), (140, 100), (140, 860), (40, 860))


def bridge_fixture(tmp_path, monkeypatch, *, text="文中国面图", fill=False, alias="_"):
    monkeypatch.setitem(SHAPES, "面", (*SHAPES["图"], DASH, FRAGMENT))
    monkeypatch.setitem(SHAPES, "一", (FRAGMENT,))
    path, primary = fixture(tmp_path, monkeypatch, text=text, fill=fill)
    with monkeypatch.context() as other:
        for ch in list(SHAPES):
            other.delitem(SHAPES, ch)
        other.setitem(SHAPES, alias, (FRAGMENT,))
        other.setitem(SHAPES, "-", (DASH,))
        font = _write_font(tmp_path / "other.ttf")
        catalog = tmp_path / "other.p2dfont"
        build_font_catalog(font, catalog)
        font.unlink()
    return path, [primary, catalog]


@pytest.mark.parametrize("fill", [False, True])
@pytest.mark.parametrize("reverse", [False, True])
def test_verified_glyph_can_connect_anchors_to_enclosed_glyph(
    tmp_path, monkeypatch, fill, reverse
):
    path, catalogs = bridge_fixture(tmp_path, monkeypatch, fill=fill)
    before = original_entities(path)
    report = o.recover_outline_text(
        path,
        mode="required",
        font_catalog_paths=catalogs[::-1] if reverse else catalogs,
    )
    assert recovered(path) == "文中国面图", report
    assert original_entities(path) == before
    assert report["font_row_recheck_matches"] == 1
    assert report["font_enclosed_radical_matches"] == 1
    assert report["font_enclosed_radical_bridge_matches"] == 1
    (proof,) = report["font_enclosed_radical_evidence"]
    assert {a["char"] for a in proof["anchors"]} == set("文中国")
    assert [b["char"] for b in proof["verified_bridges"]] == ["面"]
    assert "".join(m["char"] for m in proof["row_path"]) == "文中国面图"
    assert (
        o.recover_outline_text(path, mode="required", font_catalog_paths=catalogs)[
            "emitted_text_entities"
        ]
        == 0
    )


@pytest.mark.parametrize("alias", ["I", "0", "二"])
def test_unresolved_bridge_cannot_connect_evidence(tmp_path, monkeypatch, alias):
    path, catalogs = bridge_fixture(tmp_path, monkeypatch, alias=alias)
    report = o.recover_outline_text(path, mode="required", font_catalog_paths=catalogs)
    assert recovered(path) == "文中国"
    assert report["font_row_recheck_matches"] == 0
    assert report["font_enclosed_radical_matches"] == 0


@pytest.mark.parametrize("text", ["文中面图", "文文中面图", "面图", "文中图面"])
def test_stages_cannot_supply_each_others_missing_anchors(tmp_path, monkeypatch, text):
    path, catalogs = bridge_fixture(tmp_path, monkeypatch, text=text)
    report = o.recover_outline_text(path, mode="required", font_catalog_paths=catalogs)
    assert "图" not in recovered(path) and "面" not in recovered(path)
    assert report["font_enclosed_radical_matches"] == 0


@pytest.mark.parametrize("length", [96, 97, 193])
@pytest.mark.parametrize("position", ["start", "middle", "end"])
def test_long_row_uses_bounded_local_evidence(tmp_path, monkeypatch, length, position):
    text = ("文中国" * length)[: length - 1]
    index = {"start": 0, "middle": len(text) // 2, "end": len(text)}[position]
    text = text[:index] + "图" + text[index:]
    path, catalog = fixture(tmp_path, monkeypatch, text=text)
    before = original_entities(path)
    report = o.recover_outline_text(path, mode="required", font_catalog_paths=[catalog])
    assert recovered(path) == text, report
    assert original_entities(path) == before
    (proof,) = report["font_enclosed_radical_evidence"]
    assert 4 <= len(proof["row_path"]) <= o.MAX_RECOVERED_TEXT_GLYPHS
    assert len({m["char"] for m in proof["anchors"]}) == 3
    assert all(2 <= len(r["text"]) <= 96 for r in report["accepted"])


@pytest.mark.parametrize("kind", ["source", "layer", "vertical"])
def test_confirmed_bridge_does_not_override_a_broken_boundary(
    tmp_path, monkeypatch, kind
):
    path, catalogs = bridge_fixture(tmp_path, monkeypatch)
    doc = ezdxf.readfile(path)
    for e in list(doc.modelspace())[-3:]:
        if kind == "source":
            tags = list(e.get_xdata("PDF2DXF15"))
            tags[2] = (1070, tags[2].value + 100)
            e.set_xdata("PDF2DXF15", tags)
        elif kind == "layer":
            e.dxf.layer = "OTHER"
        else:
            e.translate(0, 20, 0)
    doc.saveas(path)
    report = o.recover_outline_text(path, mode="required", font_catalog_paths=catalogs)
    assert report["font_row_recheck_matches"] == 1
    assert "图" not in recovered(path)


@pytest.mark.parametrize("repeats,complete", [(93, True), (97, False)])
def test_local_anchor_search_has_a_hard_budget(
    tmp_path, monkeypatch, repeats, complete
):
    text = "国" + "文" * repeats + "中图"
    path, catalog = fixture(tmp_path, monkeypatch, text=text)
    report = o.recover_outline_text(path, mode="required", font_catalog_paths=[catalog])
    assert recovered(path) == (text if complete else text[:-1])
    if complete:
        (proof,) = report["font_enclosed_radical_evidence"]
        assert len(proof["row_path"]) == 96
    else:
        assert report["font_enclosed_radical_rejection_counts"] == {
            "insufficient_independent_local_row_anchors": 1
        }


def test_open_radical_candidate_explains_rejection_without_emitting_text(
    tmp_path, monkeypatch
):
    path, catalog = fixture(tmp_path, monkeypatch, ring=(OPEN_RADICAL,))
    report = o.recover_outline_text(path, mode="required", font_catalog_paths=[catalog])
    assert "图" not in recovered(path)
    (rejection,) = report["font_enclosed_radical_rejections"]
    assert rejection["reason"] == "not_a_strict_closed_enclosure"
    assert rejection["status"] == "unconfirmed_geometry_retained"
    assert rejection["parent_candidate"]["char"] == "图"
    assert rejection["radical_candidate"]["char"] == "囗"
    assert rejection["parent_candidate"]["source_handles"]


@pytest.mark.parametrize("valid", [False, True])
def test_evidence_and_rejections_are_bounded_for_many_rows(
    tmp_path, monkeypatch, valid
):
    from test_enclosed_radical_consensus import RING

    path, catalog = fixture(
        tmp_path, monkeypatch, ring=RING if valid else (OPEN_RADICAL,)
    )
    doc = ezdxf.readfile(path)
    originals = list(doc.modelspace())
    for row in range(1, 35):
        for index, original in enumerate(originals):
            entity = original.copy()
            entity.translate(0, row * 12, 0)
            entity.set_xdata("PDF2DXF15", [(1070, 0), (1070, row * 100 + index + 10)])
            doc.modelspace().add_entity(entity)
    doc.saveas(path)
    report = o.recover_outline_text(path, mode="required", font_catalog_paths=[catalog])
    assert recovered(path) == ("文中国图" if valid else "文中国") * 35
    field = (
        "font_enclosed_radical_evidence"
        if valid
        else "font_enclosed_radical_rejections"
    )
    assert len(report[field]) == 32
    assert report[field + "_truncated"] == 3
    if valid:
        assert report["font_enclosed_radical_matches"] == 35
    else:
        assert report["font_enclosed_radical_rejection_counts"] == {
            "not_a_strict_closed_enclosure": 35
        }


def punctuation_fixture(
    tmp_path, monkeypatch, *, text="文中国面图", fill=False, label="'", tall=False
):
    contour = ((400, 50), (500, 50), (500, 850), (400, 850)) if tall else DASH
    monkeypatch.setitem(SHAPES, "面", (*SHAPES["图"], contour))
    path, primary = fixture(tmp_path, monkeypatch, text=text, fill=fill)
    with monkeypatch.context() as other:
        for ch in list(SHAPES):
            other.delitem(SHAPES, ch)
        other.setitem(SHAPES, label, (contour,))
        font = _write_font(tmp_path / "other.ttf")
        catalog = tmp_path / "other.p2dfont"
        build_font_catalog(font, catalog)
        font.unlink()
    return path, [primary, catalog]


@pytest.mark.parametrize("text", ["文中国面", "文中国面图"])
@pytest.mark.parametrize("fill", [False, True])
def test_pure_punctuation_conflicts_can_be_rechecked_without_han_fragment(
    tmp_path, monkeypatch, text, fill
):
    path, catalogs = punctuation_fixture(tmp_path, monkeypatch, text=text, fill=fill)
    before = original_entities(path)
    report = o.recover_outline_text(path, mode="required", font_catalog_paths=catalogs)
    assert recovered(path) == text, report
    assert original_entities(path) == before
    (proof,) = report["font_row_recheck_evidence"]
    assert proof["parent"]["char"] == "面"
    assert proof["conflict_kind"] == "contained_punctuation_only"
    assert report["font_enclosed_radical_bridge_matches"] == int(text.endswith("图"))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"label": "I"},
        {"label": "0"},
        {"label": "二"},
        {"tall": True},
        {"text": "文中面图"},
        {"text": "文文中面图"},
    ],
)
def test_pure_punctuation_rule_keeps_other_conflicts_and_anchor_requirements(
    tmp_path, monkeypatch, kwargs
):
    path, catalogs = punctuation_fixture(tmp_path, monkeypatch, **kwargs)
    report = o.recover_outline_text(path, mode="required", font_catalog_paths=catalogs)
    assert "面" not in recovered(path) and "图" not in recovered(path)
    assert report["font_row_recheck_matches"] == 0
