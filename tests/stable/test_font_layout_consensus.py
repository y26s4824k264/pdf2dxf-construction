"""Font-em measurements add proof without relabeling whole-glyph ambiguity."""

import json
import zipfile

import ezdxf
import numpy as np
import pytest

from pdf2dxf_stable.engine.text import outline_text as o
from pdf2dxf_stable.engine.text.font_catalog import (
    FONT_LAYOUT_POLICY,
    FontCatalogError,
    _catalog_identifier,
    _dataset_digest,
    _npy_bytes,
    build_font_catalog,
    extract_font_glyph_paths,
    load_font_catalog,
)
from test_font_catalog import SHAPES, _write_font
from test_han_fragment_consensus import original_entities, recovered

STROKE = ((180, 90), (720, 90), (720, 125), (180, 125))


def layout_fixture(
    tmp_path, monkeypatch, *, text="国中图", fill=False, alias="一", full_alias=False
):
    for ch in "中图":
        monkeypatch.setitem(SHAPES, ch, (*SHAPES[ch], STROKE))
    font = _write_font(tmp_path / "parent.ttf", alias_for_tu=full_alias)
    primary = tmp_path / "parent.p2dfont"
    build_font_catalog(font, primary)
    doc = ezdxf.new("R2007")
    doc.layers.new("OUTLINE_TEXT")
    doc.appids.add("PDF2DXF15")
    for position, ch in enumerate(text):
        for contour in extract_font_glyph_paths(font, ch):
            points = contour * 0.0051 + np.asarray((position * 5.1, 2.0))
            if fill:
                entity = doc.modelspace().add_hatch(
                    dxfattribs={"layer": "OUTLINE_TEXT"}
                )
                entity.paths.add_polyline_path(points[:-1], is_closed=True)
            else:
                entity = doc.modelspace().add_lwpolyline(
                    points[:-1], close=True, dxfattribs={"layer": "OUTLINE_TEXT"}
                )
            entity.set_xdata(
                "PDF2DXF15",
                [
                    (1000, "line_or_polyline"),
                    (1070, 0),
                    (1070, position + 10),
                    (1000, "f" if fill else "s"),
                ],
            )
    target = tmp_path / "drawing.dxf"
    doc.saveas(target)
    with monkeypatch.context() as other:
        for ch in list(SHAPES):
            other.delitem(SHAPES, ch)
        for ch in ("_", "-", alias):
            other.setitem(SHAPES, ch, (STROKE,))
        foreign_font = _write_font(tmp_path / "foreign.ttf")
        foreign = tmp_path / "foreign.p2dfont"
        build_font_catalog(foreign_font, foreign)
    font.unlink()
    foreign_font.unlink()
    return target, [primary, foreign]


@pytest.mark.parametrize("fill", [False, True])
@pytest.mark.parametrize("reverse", [False, True])
def test_one_uncontested_anchor_plus_three_distinct_measured_whole_glyphs(
    tmp_path, monkeypatch, fill, reverse
):
    path, catalogs = layout_fixture(tmp_path, monkeypatch, fill=fill)
    original = original_entities(path)
    report = o.recover_outline_text(
        path,
        mode="required",
        font_catalog_paths=catalogs[::-1] if reverse else catalogs,
    )
    assert recovered(path) == "国中图"
    assert report["font_layout_matches"] == 2
    (proof,) = report["font_layout_evidence"]
    assert proof["text"] == "国中图"
    assert [p["em"] for p in proof["glyphs"]] == pytest.approx([5.1] * 3, abs=1e-6)
    assert [p["baseline_y"] for p in proof["glyphs"]] == pytest.approx(
        [2.0] * 3, abs=1e-6
    )
    assert original_entities(path) == original
    assert not ezdxf.readfile(path).audit().errors
    assert (
        o.recover_outline_text(path, font_catalog_paths=catalogs)[
            "emitted_text_entities"
        ]
        == 0
    )


@pytest.mark.parametrize(
    "option",
    [
        "short",
        "duplicate",
        "baseline",
        "advance",
        "scale",
        "source",
        "layer",
        "full_alias",
        "letter",
        "digit",
        "foreign_han",
    ],
)
def test_layout_never_supplies_missing_or_conflicting_evidence(
    tmp_path, monkeypatch, option
):
    text = (
        "国图" if option == "short" else "国国图" if option == "duplicate" else "国中图"
    )
    alias = {"letter": "I", "digit": "0", "foreign_han": "二"}.get(option, "一")
    path, catalogs = layout_fixture(
        tmp_path, monkeypatch, text=text, alias=alias, full_alias=option == "full_alias"
    )
    doc = ezdxf.readfile(path)
    for e in doc.modelspace():
        tags = list(e.get_xdata("PDF2DXF15"))
        if tags[2].value != 12:
            continue
        if option == "baseline":
            e.translate(0, 0.2, 0)
        elif option == "advance":
            e.translate(0.2, 0, 0)
        elif option == "scale":
            e.scale(1.05, 1.05, 1)
        elif option == "source":
            tags[2] = (1070, 1000)
            e.set_xdata("PDF2DXF15", tags)
        elif option == "layer":
            e.dxf.layer = "OTHER"
    doc.saveas(path)
    original = original_entities(path)
    report = o.recover_outline_text(path, font_catalog_paths=catalogs)
    assert "图" not in recovered(path)
    assert report["font_layout_matches"] == 0
    assert original_entities(path) == original


def test_r2_catalog_is_verified_but_cannot_supply_layout_evidence(
    tmp_path, monkeypatch
):
    path, catalogs = layout_fixture(tmp_path, monkeypatch)
    for catalog in catalogs:
        with zipfile.ZipFile(catalog) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            arrays = {
                n: np.load(
                    __import__("io").BytesIO(archive.read(n)), allow_pickle=False
                )
                for n in manifest["arrays"]
                if n != "layout_metrics.npy"
            }
        manifest.update(
            schema="pdf2dxf.font_glyph_catalog.v2",
            catalog_version="2",
            template_set_sha256=_dataset_digest(arrays),
        )
        manifest.pop("layout_policy")
        manifest["arrays"].pop("layout_metrics.npy")
        manifest["catalog_id"] = _catalog_identifier(
            manifest["font"]["sha256"],
            0,
            manifest["template_set_sha256"],
            schema=manifest["schema"],
        )
        with zipfile.ZipFile(catalog, "w") as archive:
            for n, a in arrays.items():
                archive.writestr(n, _npy_bytes(a))
            archive.writestr("manifest.json", json.dumps(manifest))
        assert all(
            t.layout_metrics is None for t in load_font_catalog(catalog).templates
        )
    report = o.recover_outline_text(path, font_catalog_paths=catalogs)
    assert report["font_layout_matches"] == 0
    assert "图" not in recovered(path)


def test_catalog_layout_contract_is_mandatory(tmp_path):
    path = tmp_path / "font.p2dfont"
    build_font_catalog(_write_font(tmp_path / "font.ttf"), path)
    with zipfile.ZipFile(path) as archive:
        payloads = {n: archive.read(n) for n in archive.namelist()}
    manifest = json.loads(payloads["manifest.json"])
    assert manifest.pop("layout_policy") == FONT_LAYOUT_POLICY
    payloads["manifest.json"] = json.dumps(manifest).encode()
    with zipfile.ZipFile(path, "w") as archive:
        for n, payload in payloads.items():
            archive.writestr(n, payload)
    with pytest.raises(FontCatalogError, match="layout contract"):
        load_font_catalog(path)


@pytest.mark.parametrize("filled", [False, True])
def test_layout_ignores_move_only_contours_like_saved_dxf(filled):
    from fontTools.pens.recordingPen import RecordingPen
    from pdf2dxf_stable.engine.text.font_catalog import _glyph_layout_metrics

    pen = RecordingPen()
    pen.moveTo((2000, -2000))
    pen.closePath()
    pen.moveTo((100, 200))
    pen.lineTo((800, 200))
    pen.lineTo((800, 900))
    pen.lineTo((100, 900))
    pen.closePath()
    pen.moveTo((4000, 5000))
    pen.endPath()
    pen.moveTo((-3000, -3000))
    assert _glyph_layout_metrics(pen, {}, 1000, 1000, filled=filled) == (
        0.1,
        0.2,
        0.8,
        0.9,
        1.0,
    )
