"""Saved text styles must cover all characters of a source font, in any order."""

import ezdxf
import fitz
import pytest

from pdf2dxf_stable.engine.geometry.base import GenericGraphicsKernelV14
from pdf2dxf_stable.engine.geometry.construction import ConstructionGraphicsKernelV15
from pdf2dxf_stable.engine.pipeline import ConstructionPDF2DXFV15


@pytest.mark.parametrize(
    "kernel_type",
    [GenericGraphicsKernelV14, ConstructionGraphicsKernelV15, ConstructionPDF2DXFV15],
)
@pytest.mark.parametrize("phrases", [("ABC中文",), ("ABC", "中文"), ("中文", "ABC")])
def test_mixed_source_font_keeps_han_capable_style(tmp_path, kernel_type, phrases):
    output = tmp_path / "mixed.dxf"
    with fitz.open() as pdf:
        page = pdf.new_page()
        for index, phrase in enumerate(phrases):
            page.insert_text((30, 50 + index * 30), phrase, fontname="china-s")
        kernel_type().convert_page(pdf, 0, output)
    document = ezdxf.readfile(output)
    texts = list(document.modelspace().query("TEXT"))
    assert "".join(entity.dxf.text for entity in texts) == "".join(phrases)
    assert {document.styles.get(entity.dxf.style).dxf.font for entity in texts} == {
        "simsun.ttf"
    }


def test_latin_only_source_keeps_latin_style(tmp_path):
    output = tmp_path / "latin.dxf"
    with fitz.open() as pdf:
        page = pdf.new_page()
        page.insert_text((30, 50), "ABC123")
        ConstructionPDF2DXFV15().convert_page(pdf, 0, output)
    document = ezdxf.readfile(output)
    texts = list(document.modelspace().query("TEXT"))
    assert "".join(entity.dxf.text for entity in texts) == "ABC123"
    assert {document.styles.get(entity.dxf.style).dxf.font for entity in texts} == {
        "Arial.ttf"
    }
