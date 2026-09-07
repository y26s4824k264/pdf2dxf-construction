from __future__ import annotations

import hashlib
import io
import json
import math
import zipfile
from pathlib import Path

import ezdxf
import fitz
import numpy as np
import pytest
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

from pdf2dxf_stable.engine.text import outline_text
from pdf2dxf_stable.engine.text.font_catalog import (
    FONT_CATALOG_SCHEMA,
    FontCatalogError,
    build_font_catalog,
    extract_font_glyph_paths,
    inspect_font_catalog,
    is_han_character,
    list_font_faces,
    load_font_catalog,
)
from pdf2dxf_stable.cli import main as cli_main
from pdf2dxf_stable.core import Converter
from pdf2dxf_stable.request import ConversionRequest

DENSE_CONTOUR = tuple(
    (
        int(round(450 + 190 * math.cos(2 * math.pi * index / 240))),
        int(round(360 + 190 * math.sin(2 * math.pi * index / 240))),
    )
    for index in range(240)
)


SHAPES = {
    "中": (
        ((80, 80), (820, 80), (820, 820), (80, 820)),
        ((420, 0), (480, 0), (480, 900), (420, 900)),
    ),
    "文": (
        ((80, 720), (820, 720), (820, 790), (80, 790)),
        ((420, 790), (480, 790), (480, 900), (420, 900)),
        DENSE_CONTOUR,
    ),
    "国": (
        ((50, 50), (850, 50), (850, 850), (50, 850)),
        ((180, 180), (720, 180), (720, 720), (180, 720)),
        ((390, 300), (510, 300), (510, 600), (390, 600)),
    ),
    "图": (
        ((40, 40), (860, 40), (860, 860), (40, 860)),
        ((450, 180), (700, 450), (450, 720), (200, 450)),
        ((420, 420), (480, 420), (480, 480), (420, 480)),
    ),
}


def _glyph(contours):
    pen = TTGlyphPen(None)
    for contour in contours:
        pen.moveTo(contour[0])
        for point in contour[1:]:
            pen.lineTo(point)
        pen.closePath()
    return pen.glyph()


def _write_font(path: Path, *, alias_for_tu: bool = False) -> Path:
    glyph_order = [".notdef", *(f"uni{ord(char):04X}" for char in SHAPES)]
    builder = FontBuilder(1000, isTTF=True)
    builder.setupGlyphOrder(glyph_order)
    character_map = {ord(char): f"uni{ord(char):04X}" for char in SHAPES}
    if alias_for_tu:
        character_map[ord("回")] = f"uni{ord('图'):04X}"
    builder.setupCharacterMap(character_map)
    glyphs = {".notdef": _glyph(())}
    glyphs.update(
        {f"uni{ord(char):04X}": _glyph(contours) for char, contours in SHAPES.items()}
    )
    builder.setupGlyf(glyphs)
    builder.setupHorizontalMetrics({name: (1000, 0) for name in glyph_order})
    builder.setupHorizontalHeader(ascent=900, descent=-100)
    builder.setupNameTable(
        {
            "familyName": "PDF2DXF Test CJK",
            "styleName": "Regular",
            "uniqueFontIdentifier": "PDF2DXF-Test-CJK-Regular",
            "fullName": "PDF2DXF Test CJK Regular",
            "psName": "PDF2DXF-Test-CJK-Regular",
        }
    )
    builder.setupOS2(
        sTypoAscender=900,
        sTypoDescender=-100,
        usWinAscent=900,
        usWinDescent=100,
    )
    builder.setupPost()
    builder.setupMaxp()
    builder.save(path)
    return path


def _write_audited_catalog(path: Path, glyphs: dict[str, tuple[np.ndarray, ...]]):
    templates = []
    for char in "中文国":
        signature = outline_text.fingerprint_paths(glyphs[char])
        assert signature is not None
        templates.append(
            {
                "id": f"anchor-{ord(char):04x}",
                "char": char,
                "fingerprint": signature.fingerprint,
                "entity_count": signature.entity_count,
                "closed_count": signature.closed_count,
                "point_counts": list(signature.point_counts),
                "aspect_ratio": signature.aspect_ratio,
                "mask_hex": signature.mask_hex,
                "support_locations": 2,
                "support_documents": 2,
                "label_evidence": [
                    {"source_sha256": "a" * 64, "label": char, "char_index": 0},
                    {"source_sha256": "b" * 64, "label": char, "char_index": 0},
                ],
                "admission": "repeated_document_consensus",
            }
        )
    templates.sort(key=lambda row: row["id"])
    canonical = json.dumps(
        templates, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    payload = {
        "schema": outline_text.CATALOG_SCHEMA,
        "catalog_version": "font-lock-test",
        "runtime_input": "persisted_dxf_only",
        "runtime_ocr": False,
        "template_set_sha256": hashlib.sha256(canonical).hexdigest(),
        "templates": templates,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _write_outline_dxf(
    path: Path,
    glyphs: dict[str, tuple[np.ndarray, ...]],
    *,
    text: str = "中文国图",
) -> Path:
    document = ezdxf.new("R2007")
    document.layers.new("OUTLINE_TEXT")
    document.appids.add("PDF2DXF15")
    sequence = 10
    cursor = 0.0
    for char in text:
        points = np.vstack(glyphs[char])
        low, high = points.min(axis=0), points.max(axis=0)
        scale = 0.0051
        for contour in glyphs[char]:
            transformed = (contour - low) * scale + np.asarray((cursor, 2.0))
            entity = document.modelspace().add_lwpolyline(
                transformed[:-1],
                close=True,
                dxfattribs={"layer": "OUTLINE_TEXT"},
            )
            entity.set_xdata(
                "PDF2DXF15",
                [
                    (1000, "line_or_polyline"),
                    (1070, 0),
                    (1070, sequence),
                    (1000, "s"),
                ],
            )
            sequence += 1
        cursor += float(high[0] - low[0]) * scale + 0.45
    document.saveas(path)
    return path


def _write_outline_pdf(
    path: Path,
    glyphs: dict[str, tuple[np.ndarray, ...]],
    *,
    text: str = "中文国图",
) -> Path:
    with fitz.open() as document:
        page = document.new_page(width=300, height=100)
        cursor = 20.0
        for char in text:
            points = np.vstack(glyphs[char])
            low, high = points.min(axis=0), points.max(axis=0)
            scale = 0.03
            for contour in glyphs[char]:
                pdf_points = [
                    fitz.Point(
                        cursor + (float(x) - low[0]) * scale,
                        70.0 - (float(y) - low[1]) * scale,
                    )
                    for x, y in contour[:-1]
                ]
                shape = page.new_shape()
                shape.draw_polyline(pdf_points)
                shape.finish(color=(0, 0, 0), width=0.5, closePath=True)
                shape.commit()
            cursor += float(high[0] - low[0]) * scale + 3.0
        document.save(path)
    return path


def test_build_is_deterministic_and_covers_every_mapped_chinese_character(tmp_path):
    font = _write_font(tmp_path / "test-cjk.ttf")
    first = tmp_path / "first.p2dfont"
    second = tmp_path / "second.p2dfont"

    first_report = build_font_catalog(font, first)
    build_font_catalog(font, second)
    loaded = load_font_catalog(first)
    inspected = inspect_font_catalog(first)

    assert first.read_bytes() == second.read_bytes()
    assert first_report["schema"] == FONT_CATALOG_SCHEMA
    assert first_report["template_count"] == len(SHAPES)
    assert first_report["han_template_count"] == len(SHAPES)
    assert loaded.characters == frozenset(SHAPES)
    assert inspected["runtime_input"] == "persisted_dxf_only"
    assert inspected["runtime_font_access"] is False
    assert inspected["runtime_pdf_access"] is False
    assert inspected["ocr_enabled"] is False
    assert inspected["unicode_cjk_version"] == "17.0"
    assert list_font_faces(font)[0]["mapped_han_codepoints"] == len(SHAPES)
    assert is_han_character(chr(0x323B0))
    assert is_han_character(chr(0x3347F))
    assert not is_han_character(chr(0x33480))


def test_tampered_persisted_catalog_is_rejected(tmp_path):
    font = _write_font(tmp_path / "test-cjk.ttf")
    catalog = tmp_path / "test-cjk.p2dfont"
    tampered = tmp_path / "tampered.p2dfont"
    build_font_catalog(font, catalog)

    with zipfile.ZipFile(catalog, "r") as source:
        payloads = {name: source.read(name) for name in source.namelist()}
    changed = bytearray(payloads["variant_digests.npy"])
    changed[-1] ^= 1
    payloads["variant_digests.npy"] = bytes(changed)
    with zipfile.ZipFile(tampered, "w") as target:
        for name, payload in payloads.items():
            target.writestr(name, payload)

    with pytest.raises(FontCatalogError, match="array hash mismatch"):
        load_font_catalog(tampered)


@pytest.mark.parametrize("change", ["list", "float_count", "zero_divisor", "negative_skipped"])
def test_malformed_catalog_manifest_has_controlled_error(tmp_path, change):
    font = _write_font(tmp_path / "test.ttf")
    catalog = tmp_path / "test.p2dfont"
    build_font_catalog(font, catalog)
    with zipfile.ZipFile(catalog) as archive:
        payloads = {name: archive.read(name) for name in archive.namelist()}
    manifest = json.loads(payloads["manifest.json"])
    if change == "list":
        manifest = []
    elif change == "float_count":
        manifest["template_count"] = float(manifest["template_count"])
    elif change == "zero_divisor":
        manifest["tolerance_divisors"] = [0]
    else:
        manifest["skipped_non_outline_mappings"] = -1
        manifest["requested_mapped_codepoints"] -= 1
    payloads["manifest.json"] = json.dumps(manifest).encode()
    with zipfile.ZipFile(catalog, "w") as archive:
        for name, data in payloads.items():
            archive.writestr(name, data)
    with pytest.raises(FontCatalogError):
        load_font_catalog(catalog)
    with pytest.raises(SystemExit) as error:
        cli_main(["font-catalog", "inspect", str(catalog)])
    assert error.value.code == 2


@pytest.mark.parametrize("shape, tail", [((10**12,), b""), ((4,), b""), ((4,), b"\0" * 32)])
def test_catalog_rejects_npy_shape_and_length_before_loading(tmp_path, monkeypatch, shape, tail):
    font = _write_font(tmp_path / "test.ttf")
    catalog = tmp_path / "test.p2dfont"
    build_font_catalog(font, catalog)
    with zipfile.ZipFile(catalog) as archive:
        payloads = {name: archive.read(name) for name in archive.namelist()}
    stream = io.BytesIO()
    np.lib.format.write_array_header_1_0(stream, {
        "shape": shape, "fortran_order": False, "descr": "<f4",
    })
    payloads["aspect_ratios.npy"] = data = stream.getvalue() + tail
    manifest = json.loads(payloads["manifest.json"])
    manifest["arrays"]["aspect_ratios.npy"] = {
        "size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
    }
    payloads["manifest.json"] = json.dumps(manifest).encode()
    with zipfile.ZipFile(catalog, "w") as archive:
        for name, data in payloads.items():
            archive.writestr(name, data)

    def unsafe_load(*args, **kwargs):
        pytest.fail("an unchecked NPY header reached numpy.load")

    monkeypatch.setattr(np, "load", unsafe_load)
    with pytest.raises(FontCatalogError, match="shape or type|payload length"):
        load_font_catalog(catalog)


def test_tampered_catalog_identity_is_rejected(tmp_path):
    font = _write_font(tmp_path / "test-cjk.ttf")
    catalog = tmp_path / "test-cjk.p2dfont"
    tampered = tmp_path / "tampered-identity.p2dfont"
    build_font_catalog(font, catalog)

    with zipfile.ZipFile(catalog, "r") as source:
        payloads = {name: source.read(name) for name in source.namelist()}
    manifest = json.loads(payloads["manifest.json"])
    manifest["catalog_id"] = "0" * 24
    payloads["manifest.json"] = json.dumps(
        manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    with zipfile.ZipFile(tampered, "w") as target:
        for name, payload in payloads.items():
            target.writestr(name, payload)

    with pytest.raises(FontCatalogError, match="identity mismatch"):
        load_font_catalog(tampered)


def test_duplicate_catalog_member_is_rejected(tmp_path):
    font = _write_font(tmp_path / "test-cjk.ttf")
    catalog = tmp_path / "test-cjk.p2dfont"
    duplicated = tmp_path / "duplicated-member.p2dfont"
    build_font_catalog(font, catalog)

    with zipfile.ZipFile(catalog, "r") as source:
        payloads = [(name, source.read(name)) for name in source.namelist()]
    manifest_payload = dict(payloads)["manifest.json"]
    with zipfile.ZipFile(duplicated, "w") as target:
        for name, payload in payloads:
            target.writestr(name, payload)
        with pytest.warns(UserWarning, match="Duplicate name"):
            target.writestr("manifest.json", manifest_payload)

    with pytest.raises(FontCatalogError, match="unexpected file set"):
        load_font_catalog(duplicated)


def test_three_audited_han_anchors_lock_font_and_decode_unknown_from_dxf(tmp_path):
    font = _write_font(tmp_path / "test-cjk.ttf")
    font_catalog = tmp_path / "test-cjk.p2dfont"
    build_font_catalog(font, font_catalog)
    glyphs = {
        char: extract_font_glyph_paths(font, char) for char in SHAPES
    }
    audited_catalog = _write_audited_catalog(
        tmp_path / "audited.json", glyphs
    )
    dxf = _write_outline_dxf(tmp_path / "outline.dxf", glyphs)

    # Runtime proof: after persistence, recognition no longer needs the font.
    font.unlink()
    report = outline_text.recover_outline_text(
        dxf,
        mode="required",
        policy="keep",
        catalog_path=audited_catalog,
        font_catalog_paths=[font_catalog],
    )

    result = ezdxf.readfile(dxf)
    recovered = list(
        result.modelspace().query("TEXT[layer=='PDF_TEXT_RECOVERED_NOOCR']")
    )
    assert report["status"] == "ok"
    assert report["font_catalogs"]["loaded"] == 1
    assert report["font_catalogs"]["locked"] == 1
    entry = report["font_catalogs"]["entries"][0]
    assert entry["exact_anchor_characters"] == ["中", "国", "文"]
    assert entry["locked"] is True
    assert report["font_exact_glyph_matches"] == 1
    assert report["accepted"][0]["text"] == "中文国图"
    assert report["accepted"][0]["font_catalog_ids"] == [entry["catalog_id"]]
    assert [entity.dxf.text for entity in recovered] == ["中文国图"]


def test_arbitrary_font_self_locks_from_three_unique_adjacent_han(tmp_path):
    font = _write_font(tmp_path / "unseen-font.ttf")
    font_catalog = tmp_path / "unseen-font.p2dfont"
    build_font_catalog(font, font_catalog)
    glyphs = {
        char: extract_font_glyph_paths(font, char) for char in SHAPES
    }
    dxf = _write_outline_dxf(tmp_path / "unseen-font.dxf", glyphs)
    font.unlink()

    report = outline_text.recover_outline_text(
        dxf,
        mode="required",
        policy="keep",
        font_catalog_paths=[font_catalog],
    )

    assert report["exact_glyph_matches"] == 0
    assert report["font_catalogs"]["locked"] == 1
    entry = report["font_catalogs"]["entries"][0]
    assert entry["lock_method"] == "font_cmap_run_consensus"
    assert entry["self_lock_evidence"][0]["text"] == "中文国图"
    assert report["font_exact_glyph_matches"] == 4
    assert report["accepted"][0]["text"] == "中文国图"


@pytest.mark.parametrize("stdio_encoding", [None, "cp1252"])
def test_arbitrary_font_recovers_complete_run_through_pdf_to_dxf(
    tmp_path, monkeypatch, stdio_encoding
):
    if stdio_encoding:
        monkeypatch.setenv("PYTHONIOENCODING", stdio_encoding)
    tmp_path = tmp_path / "中文图纸"
    tmp_path.mkdir()
    font = _write_font(tmp_path / "pdf-font.ttf")
    font_catalog = tmp_path / "pdf-font.p2dfont"
    build_font_catalog(font, font_catalog)
    glyphs = {
        char: extract_font_glyph_paths(font, char) for char in SHAPES
    }
    source = _write_outline_pdf(tmp_path / "outline.pdf", glyphs)
    font.unlink()

    output = tmp_path / "outline.dxf"
    result = Converter().convert(
        source,
        output,
        ConversionRequest(
            outline_chinese="required",
            outline_font_catalogs=[str(font_catalog)],
            recover_pure_path_text=False,
            strict_validation=False,
        ),
    )

    assert result.status == "degraded", result.to_dict()
    outline_report = result.pages[0]["backend"]["result"]["outline_chinese"]
    assert outline_report["font_catalogs"]["locked"] == 1
    assert outline_report["font_exact_glyph_matches"] == 4
    assert [row["text"] for row in outline_report["accepted"]] == ["中文国图"]
    document = ezdxf.readfile(output)
    assert [
        entity.dxf.text
        for entity in document.query("TEXT[layer=='PDF_TEXT_RECOVERED_NOOCR']")
    ] == ["中文国图"]


def test_two_unseen_han_are_insufficient_to_self_lock_font(tmp_path):
    font = _write_font(tmp_path / "unseen-font.ttf")
    font_catalog = tmp_path / "unseen-font.p2dfont"
    build_font_catalog(font, font_catalog)
    glyphs = {
        char: extract_font_glyph_paths(font, char) for char in SHAPES
    }
    dxf = _write_outline_dxf(tmp_path / "two-han.dxf", glyphs, text="中文")

    before = dxf.read_bytes()
    report = outline_text.recover_outline_text(
        dxf,
        mode="required",
        font_catalog_paths=[font_catalog],
    )

    assert report["font_catalog_candidate_matches"] == 2
    assert report["font_catalogs"]["locked"] == 0
    assert report["font_exact_glyph_matches"] == 0
    assert report["emitted_text_entities"] == 0
    assert dxf.read_bytes() == before


def test_same_geometry_mapped_to_two_characters_is_not_published(tmp_path):
    font = _write_font(tmp_path / "alias-font.ttf", alias_for_tu=True)
    font_catalog = tmp_path / "alias-font.p2dfont"
    built = build_font_catalog(font, font_catalog)
    glyphs = {
        char: extract_font_glyph_paths(font, char) for char in SHAPES
    }
    dxf = _write_outline_dxf(tmp_path / "alias-font.dxf", glyphs)

    report = outline_text.recover_outline_text(
        dxf,
        mode="required",
        policy="keep",
        font_catalog_paths=[font_catalog],
    )

    assert built["ambiguous_geometry_keys"] > 0
    assert built["fully_ambiguous_characters"] == 2
    assert report["font_catalogs"]["locked"] == 1
    assert report["font_ambiguous_geometry_matches"] >= 1
    assert report["font_exact_glyph_matches"] == 3
    assert [row["text"] for row in report["accepted"]] == ["中文国"]


def test_font_catalog_cli_builds_and_inspects_catalog(tmp_path, capsys):
    font = _write_font(tmp_path / "test-cjk.ttf")
    catalog = tmp_path / "test-cjk.p2dfont"

    assert (
        cli_main(
            [
                "font-catalog",
                "build",
                str(font),
                "--output",
                str(catalog),
            ]
        )
        == 0
    )
    built = json.loads(capsys.readouterr().out)
    assert built["template_count"] == len(SHAPES)

    assert cli_main(["font-catalog", "inspect", str(catalog)]) == 0
    inspected = json.loads(capsys.readouterr().out)
    assert inspected["catalog_id"] == built["catalog_id"]
