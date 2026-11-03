"""Real embedded fonts with missing PDF ToUnicode maps, without OCR fixtures."""

import ezdxf
import fitz
from fontTools.ttLib import TTFont

from pdf2dxf_stable.engine.geometry.native_text import extract_text_runs
from pdf2dxf_stable.engine.pipeline import ConstructionPDF2DXFV15
from pdf2dxf_stable.validation import validate_dxf
from test_font_catalog import _write_font


def missing_mapping_pdf(tmp_path, text="中文国图", *, alias=False):
    font = _write_font(tmp_path / "fixture.ttf", alias_for_tu=alias)
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_font(fontname="Fixture", fontfile=str(font))
    page.insert_text((30, 50), text, fontname="Fixture")
    for row in page.get_fonts():
        pdf.xref_set_key(row[0], "ToUnicode", "null")
    data = pdf.tobytes()
    pdf.close()
    return fitz.open(stream=data, filetype="pdf")


def test_missing_tounicode_uses_unique_embedded_cmap_and_keeps_geometry(tmp_path):
    with missing_mapping_pdf(tmp_path) as pdf:
        page = pdf[0]
        original = page.get_texttrace()[0]
        assert any(item[0] == 0xFFFD for item in original["chars"])
        runs = extract_text_runs(page)
        assert "".join(run.text for run in runs) == "中文国图"
        assert [c.origin for c in runs[0].chars] == [tuple(c[2]) for c in original["chars"]]
        assert [c.bbox for c in runs[0].chars] == [tuple(c[3]) for c in original["chars"]]
        assert "embedded-cmap" in runs[0].source


def test_ambiguous_gid_is_not_published_as_arbitrary_unicode(tmp_path):
    with missing_mapping_pdf(tmp_path, alias=True) as pdf:
        runs = extract_text_runs(pdf[0])
        assert "".join(run.text for run in runs) == "中文国\ufffd"


def test_cached_conversion_persists_verified_unicode_not_glyph_numbers(tmp_path):
    output = tmp_path / "text.dxf"
    with missing_mapping_pdf(tmp_path) as pdf:
        ConstructionPDF2DXFV15().convert_page(pdf, 0, output)
    doc = ezdxf.readfile(output)
    texts = list(doc.modelspace().query("TEXT"))
    assert "".join(e.dxf.text for e in texts) == "中文国图"
    assert all(doc.styles.get(e.dxf.style).dxf.font == "simsun.ttf" for e in texts)
    assert all(any("embedded-cmap" in str(t.value) for t in e.get_xdata("PDF2DXF15")) for e in texts)


def test_cmap_does_not_override_a_valid_explicit_pdf_mapping(tmp_path):
    with missing_mapping_pdf(tmp_path) as pdf:
        original = pdf[0]
        traces = original.get_texttrace()
        chars = list(traces[0]["chars"])
        chars[0] = (ord("另"), *chars[0][1:])
        traces[0]["chars"] = tuple(chars)

        class Page:
            cropbox = original.cropbox
            parent = pdf

            def get_fonts(self, *args, **kwargs):
                return original.get_fonts(*args, **kwargs)

            def get_text(self, *args, **kwargs):
                return original.get_text(*args, **kwargs)

            def get_texttrace(self):
                return traces

        assert extract_text_runs(Page())[0].text.startswith("另")


def test_same_named_different_fonts_must_agree_on_glyph_labels(tmp_path):
    other = _write_font(tmp_path / "other.ttf")
    with TTFont(other) as font:
        for table in font["cmap"].tables:
            if table.isUnicode():
                table.cmap[ord("中")] = "uni6587"
                table.cmap[ord("文")] = "uni4E2D"
        font.save(other)
    with missing_mapping_pdf(tmp_path) as pdf:
        page = pdf[0]
        original = page.get_fonts()[0]

        class Document:
            def extract_font(self, xref):
                return pdf.extract_font(xref) if xref == original[0] else (
                    original[3], "ttf", "Type0", other.read_bytes()
                )

        class Page:
            cropbox = page.cropbox
            parent = Document()

            def get_fonts(self, **kwargs):
                return [original, (999, *original[1:])]

            def get_texttrace(self):
                return page.get_texttrace()

            def get_text(self, *args, **kwargs):
                return page.get_text(*args, **kwargs)

        assert extract_text_runs(Page())[0].text == "\ufffd\ufffd国图"


def test_unresolved_native_unicode_is_not_qualified_as_complete_graphics(tmp_path):
    output = tmp_path / "unknown.dxf"
    with missing_mapping_pdf(tmp_path, alias=True) as pdf:
        stats = ConstructionPDF2DXFV15().convert_page(pdf, 0, output)
    result = validate_dxf(output, profile="universal", backend_payload=stats.to_dict())
    assert not result["geometry_valid"]
    assert "SOURCE_GRAPHICS_INCOMPLETE" in {e["code"] for e in result["errors"]}
