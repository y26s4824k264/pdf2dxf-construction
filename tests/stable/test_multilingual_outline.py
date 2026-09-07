"""Real outline fonts and Unicode cmap fixtures exercise saved DXF text recovery."""

from pathlib import Path
import io
import string
import unicodedata

import ezdxf
import fitz
import matplotlib
import pytest
from fontTools.ttLib import TTFont
from fontTools.ttLib.tables._c_m_a_p import CmapSubtable
from fontTools.pens.reportLabPen import ReportLabPen
from reportlab.graphics.shapes import Drawing, Group
from reportlab.graphics import renderPDF

from pdf2dxf_stable.engine.text.font_catalog import (
    DEFAULT_TOLERANCE_DIVISORS,
    build_font_catalog,
    extract_font_glyph_paths,
    inspect_font_catalog,
    load_font_catalog,
)
from pdf2dxf_stable.engine.text.outline_text import recover_outline_text
from pdf2dxf_stable.core import Converter
from pdf2dxf_stable.request import ConversionRequest
from pdf2dxf_stable.cli import main as cli_main
from test_font_catalog import (
    _write_font,
    _write_outline_dxf,
    _write_audited_catalog,
    _glyph,
    SHAPES,
)


@pytest.fixture
def latin_font(tmp_path):
    source = Path(matplotlib.get_data_path()) / "fonts/ttf/DejaVuSans.ttf"
    target = tmp_path / "latin.ttf"
    target.write_bytes(source.read_bytes())
    return target


def _saved_text(path):
    doc = ezdxf.readfile(path)
    return [
        e.dxf.text
        for e in doc.modelspace().query("TEXT[layer=='PDF_TEXT_RECOVERED_NOOCR']")
    ]


@pytest.mark.parametrize(
    "text",
    [
        string.ascii_uppercase,
        string.ascii_lowercase,
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz",
    ],
)
def test_all_52_english_letters_recover_without_han_anchors(tmp_path, latin_font, text):
    catalog = tmp_path / "latin.p2dfont"
    build_font_catalog(latin_font, catalog)
    glyphs = {ch: extract_font_glyph_paths(latin_font, ch) for ch in text}
    dxf = _write_outline_dxf(tmp_path / "letters.dxf", glyphs, text=text)
    latin_font.unlink()
    report = recover_outline_text(dxf, mode="required", font_catalog_paths=[catalog])
    assert "".join(_saved_text(dxf)) == text, report
    assert report["font_catalogs"]["locked"] == 1
    assert report["font_exact_glyph_matches"] == len(text)
    assert report["engine"]["ocr_enabled"] is False


@pytest.mark.parametrize(
    "base",
    [
        0x3400,
        0x4E00,
        0xF900,
        0x20000,
        0x2A700,
        0x2B740,
        0x2B820,
        0x2CEB0,
        0x2EBF0,
        0x2F800,
        0x30000,
        0x31350,
        0x323B0,
    ],
)
@pytest.mark.parametrize("pipeline", ["dxf", "pdf"])
def test_han_in_every_unified_extension_reaches_saved_text(tmp_path, base, pipeline):
    font_path = _write_font(tmp_path / "cjk.ttf")
    text = "".join(chr(base + i) for i in range(3))
    with TTFont(io.BytesIO(font_path.read_bytes())) as font:
        table = CmapSubtable.newSubtable(12)
        table.platformID, table.platEncID, table.language = 3, 10, 0
        table.cmap = {base + i: f"uni{ord(ch):04X}" for i, ch in enumerate("中文国")}
        font["cmap"].tables = [table]
        font.save(font_path)
    catalog = tmp_path / "cjk.p2dfont"
    build_font_catalog(font_path, catalog)
    dxf = tmp_path / "han.dxf"
    if pipeline == "dxf":
        glyphs = {ch: extract_font_glyph_paths(font_path, ch) for ch in text}
        _write_outline_dxf(dxf, glyphs, text=text)
    else:
        source = _baseline_pdf(font_path, tmp_path / "han.pdf", text)
    font_path.unlink()
    if pipeline == "dxf":
        report = recover_outline_text(
            dxf, mode="required", font_catalog_paths=[catalog]
        )
    else:
        result = Converter().convert(
            source,
            dxf,
            ConversionRequest(
                outline_chinese="required",
                outline_font_catalogs=[str(catalog)],
                recover_pure_path_text=False,
                strict_validation=False,
            ),
        )
        report = result.to_dict()
        assert result.status == "degraded", report
    assert _saved_text(dxf) == [unicodedata.normalize("NFKC", text)], report


@pytest.mark.parametrize("text", ["AAA", "ABC", "AaBb", "ll", "123456"])
def test_short_or_repeated_latin_and_digits_cannot_lock_font(
    tmp_path, latin_font, text
):
    catalog = tmp_path / "latin.p2dfont"
    build_font_catalog(latin_font, catalog)
    glyphs = {ch: extract_font_glyph_paths(latin_font, ch) for ch in text}
    dxf = _write_outline_dxf(tmp_path / "short.dxf", glyphs, text=text)
    before = dxf.read_bytes()
    report = recover_outline_text(dxf, mode="required", font_catalog_paths=[catalog])
    assert report["font_catalogs"]["locked"] == 0
    assert dxf.read_bytes() == before


def test_catalog_inspection_reports_all_english_letter_coverage(tmp_path, latin_font):
    catalog = tmp_path / "latin.p2dfont"
    build_font_catalog(latin_font, catalog)
    coverage = inspect_font_catalog(catalog)["english_letters"]
    assert coverage["uppercase"] == string.ascii_uppercase
    assert coverage["lowercase"] == string.ascii_lowercase
    assert coverage["missing"] == ""
    assert coverage["mapped_count"] == 52


@pytest.mark.parametrize(
    "divisors", [(32, 64, 128, 256, 1024), DEFAULT_TOLERANCE_DIVISORS]
)
def test_legacy_and_fractional_sampling_catalogs_round_trip(tmp_path, divisors):
    font = _write_font(tmp_path / "font.ttf")
    catalog = tmp_path / "font.p2dfont"
    build_font_catalog(font, catalog, tolerance_divisors=divisors)
    assert load_font_catalog(catalog).tolerance_divisors == divisors


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_sampling_is_rejected_before_catalog_is_written(tmp_path, value):
    font = _write_font(tmp_path / "font.ttf")
    catalog = tmp_path / "font.p2dfont"
    with pytest.raises(ValueError, match="tolerance divisors"):
        build_font_catalog(font, catalog, tolerance_divisors=[32, value])
    assert not catalog.exists()


@pytest.mark.parametrize("policy", ["off_layer", "keep"])
def test_filled_glyph_sources_are_preserved_and_recovery_is_idempotent(
    tmp_path, policy
):
    font = _write_font(tmp_path / "font.ttf")
    catalog = tmp_path / "font.p2dfont"
    build_font_catalog(font, catalog)
    dxf = tmp_path / "filled.dxf"
    glyphs = {ch: extract_font_glyph_paths(font, ch) for ch in "中文国图"}
    _write_outline_dxf(dxf, glyphs)
    doc = ezdxf.readfile(dxf)
    for outline in list(doc.modelspace().query("LWPOLYLINE")):
        hatch = doc.modelspace().add_hatch()
        hatch.paths.add_polyline_path(list(outline.get_points("xy")), is_closed=True)
        hatch.set_xdata("PDF2DXF15", outline.get_xdata("PDF2DXF15"))
        doc.modelspace().delete_entity(outline)
    originals = {
        h.dxf.handle: list(h.paths[0].vertices) for h in doc.modelspace().query("HATCH")
    }
    doc.saveas(dxf)
    report = recover_outline_text(
        dxf, mode="required", policy=policy, font_catalog_paths=[catalog]
    )
    assert _saved_text(dxf) == ["中文国图"], report
    saved = ezdxf.readfile(dxf)
    for handle, vertices in originals.items():
        assert list(saved.entitydb[handle].paths[0].vertices) == vertices
        assert saved.entitydb[handle].dxf.layer == (
            "PDF_OUTLINE_BACKUP" if policy == "off_layer" else "0"
        )
    before = dxf.read_bytes()
    recover_outline_text(
        dxf, mode="required", policy=policy, font_catalog_paths=[catalog]
    )
    assert dxf.read_bytes() == before


@pytest.mark.parametrize("unsupported", ["extrusion", "elevation", "bulge", "open"])
def test_unsupported_fill_geometry_stays_unmodified(tmp_path, unsupported):
    font = _write_font(tmp_path / "font.ttf")
    catalog = tmp_path / "font.p2dfont"
    build_font_catalog(font, catalog)
    glyphs = {ch: extract_font_glyph_paths(font, ch) for ch in "中文国图"}
    dxf = _write_outline_dxf(tmp_path / "unsupported.dxf", glyphs)
    doc = ezdxf.readfile(dxf)
    for outline in list(doc.modelspace().query("LWPOLYLINE")):
        hatch = doc.modelspace().add_hatch()
        vertices = list(outline.get_points("xy"))
        if unsupported == "bulge":
            vertices = [(x, y, 1) for x, y in vertices]
        hatch.paths.add_polyline_path(vertices, is_closed=unsupported != "open")
        if unsupported == "extrusion":
            hatch.dxf.extrusion = (0, 1, 0)
        elif unsupported == "elevation":
            hatch.dxf.elevation = (0, 0, 1)
        hatch.set_xdata("PDF2DXF15", outline.get_xdata("PDF2DXF15"))
        doc.modelspace().delete_entity(outline)
    doc.saveas(dxf)
    before = dxf.read_bytes()
    report = recover_outline_text(dxf, mode="required", font_catalog_paths=[catalog])
    assert report["emitted_text_entities"] == 0
    assert dxf.read_bytes() == before


def test_interleaved_fill_operations_do_not_split_verified_stroke_text(tmp_path):
    font = _write_font(tmp_path / "font.ttf")
    catalog = tmp_path / "font.p2dfont"
    build_font_catalog(font, catalog)
    glyphs = {ch: extract_font_glyph_paths(font, ch) for ch in "中文国图"}
    audited = _write_audited_catalog(tmp_path / "audited.json", glyphs)
    dxf = _write_outline_dxf(tmp_path / "interleaved.dxf", glyphs)
    doc = ezdxf.readfile(dxf)
    outlines = list(doc.modelspace())
    for index, outline in enumerate(outlines):
        doc.modelspace().unlink_entity(outline)
        doc.modelspace().add_entity(outline)
        outline.set_xdata("PDF2DXF15", [(1070, 0), (1070, index * 2)])
        hatch = doc.modelspace().add_hatch()
        hatch.paths.add_polyline_path([(10, 5), (11, 5), (10.2, 5.3)], is_closed=True)
        hatch.set_xdata("PDF2DXF15", [(1070, 0), (1070, index * 2 + 1)])
    doc.saveas(dxf)
    report = recover_outline_text(
        dxf, mode="required", catalog_path=audited, font_catalog_paths=[catalog]
    )
    assert _saved_text(dxf) == ["中文国图"], report
    assert report["exact_glyph_matches"] == 3
    assert report["font_exact_glyph_matches"] == 1
    assert len(ezdxf.readfile(dxf).modelspace().query("HATCH[layer=='0']")) == len(
        outlines
    )


def _baseline_pdf(font_path, path, text):
    """Keep real font advances, ascenders and descenders, not equal-height boxes."""
    with TTFont(font_path) as font:
        cmap = font.getBestCmap()
        advances = {ch: font["hmtx"][cmap[ord(ch)]][0] for ch in text}
        scale = 20 / font["head"].unitsPerEm
    with fitz.open() as doc:
        page = doc.new_page(
            width=max(300, sum(advances.values()) * scale + 60), height=100
        )
        cursor = 20.0
        for ch in text:
            for contour in extract_font_glyph_paths(font_path, ch):
                shape = page.new_shape()
                shape.draw_polyline(
                    [
                        fitz.Point(cursor + x * scale, 60 - y * scale)
                        for x, y in contour[:-1]
                    ]
                )
                shape.finish(color=(0, 0, 0), closePath=True)
                shape.commit()
            cursor += advances[ch] * scale
        doc.save(path)
    return path


def _bezier_pdf(font_path, path, text):
    with TTFont(font_path) as font:
        glyph_set = font.getGlyphSet()
        cmap = font.getBestCmap()
        scale = 20 / font["head"].unitsPerEm
        cursor = 20.0
        drawing = Drawing(1000, 100)
        for ch in text:
            pen = ReportLabPen(glyph_set)
            glyph_set[cmap[ord(ch)]].draw(pen)
            pen.path.strokeColor = None
            group = Group(pen.path)
            group.transform = (scale, 0, 0, scale, cursor, 40)
            drawing.add(group)
            cursor += font["hmtx"][cmap[ord(ch)]][0] * scale
        renderPDF.drawToFile(drawing, str(path))
    return path


@pytest.mark.parametrize(
    "name", ["DejaVuSans.ttf", "DejaVuSerif.ttf", "DejaVuSansMono.ttf"]
)
@pytest.mark.parametrize("curves", [False, True])
def test_real_pdf_all_52_letters_keep_case_and_baseline(tmp_path, name, curves):
    font = tmp_path / name
    font.write_bytes(
        (Path(matplotlib.get_data_path()) / "fonts/ttf" / name).read_bytes()
    )
    text = string.ascii_uppercase + string.ascii_lowercase
    catalog = tmp_path / "latin.p2dfont"
    build_font_catalog(font, catalog)
    source = (_bezier_pdf if curves else _baseline_pdf)(
        font, tmp_path / "letters.pdf", text
    )
    font.unlink()
    output = tmp_path / "letters.dxf"
    result = Converter().convert(
        source,
        output,
        ConversionRequest(
            outline_chinese="required",
            outline_font_catalogs=[str(catalog)],
            recover_pure_path_text=False,
            strict_validation=False,
        ),
    )
    assert result.status == "degraded", result.to_dict()
    assert _saved_text(output) == [text], result.to_dict()
    report = result.pages[0]["backend"]["result"]["outline_chinese"]
    assert report["font_exact_glyph_matches"] == 52


def test_mixed_chinese_english_and_ideographic_zero(tmp_path, latin_font):
    with TTFont(io.BytesIO(latin_font.read_bytes())) as font:
        for ch, contours in {
            **SHAPES,
            "〇": (((50, 0), (950, 0), (900, 850), (100, 850)),),
        }.items():
            name = f"uni{ord(ch):04X}"
            font["glyf"][name] = _glyph(contours)
            font["hmtx"][name] = (1000, 0)
            for table in font["cmap"].tables:
                if table.isUnicode():
                    table.cmap[ord(ch)] = name
        font.save(latin_font)
    text = "Floor中文国图Abcd〇"
    catalog = tmp_path / "mixed.p2dfont"
    build_font_catalog(latin_font, catalog)
    source = _baseline_pdf(latin_font, tmp_path / "mixed.pdf", text)
    latin_font.unlink()
    output = tmp_path / "mixed.dxf"
    result = Converter().convert(
        source,
        output,
        ConversionRequest(
            outline_chinese="required",
            outline_font_catalogs=[str(catalog)],
            recover_pure_path_text=False,
            strict_validation=False,
        ),
    )
    assert result.status == "degraded", result.to_dict()
    assert _saved_text(output) == [text], result.to_dict()


def test_english_charset_is_available_from_cli(tmp_path, latin_font, capsys):
    catalog = tmp_path / "english.p2dfont"
    assert (
        cli_main(
            [
                "font-catalog",
                "build",
                str(latin_font),
                "--charset",
                "english",
                "-o",
                str(catalog),
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert inspect_font_catalog(catalog)["english_letters"]["mapped_count"] == 52
