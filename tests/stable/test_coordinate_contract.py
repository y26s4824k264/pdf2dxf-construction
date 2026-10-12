"""Paper millimetres must not be confused with confirmed model millimetres."""

import ezdxf
import fitz
import pytest

from pdf2dxf_stable import Converter, ConversionRequest
from pdf2dxf_stable.coordinates import COORDINATE_APPID


@pytest.mark.parametrize(
    "scale_mode,scale,expected",
    [
        ("page", None, ("paper", 0)),
        ("auto", None, ("unknown", 0)),
        ("manual", 100, ("user_confirmed", 1)),
    ],
)
def test_saved_entities_carry_actual_validation_decision(
    tmp_path, scale_mode, scale, expected
):
    source = tmp_path / "plan.pdf"
    with fitz.open() as pdf:
        page = pdf.new_page()
        page.draw_rect((20, 20, 200, 200))
        pdf.save(source)
    result = Converter().convert(
        source,
        tmp_path / "plan.dxf",
        ConversionRequest(
            scale_mode=scale_mode,
            manual_scale=scale,
            emit_r12=True,
            workers=1,
        ),
    )
    assert result.status != "failed", result.errors
    for artifact in result.artifacts:
        if artifact.kind != "dxf":
            continue
        doc = ezdxf.readfile(artifact.path)
        assert not doc.audit().has_errors
        ready = expected[1] if not artifact.path.endswith(".r12.dxf") else 0
        for entity in doc.modelspace():
            values = [t.value for t in entity.get_xdata(COORDINATE_APPID)]
            assert values == ["v1", expected[0], ready, "mm", 0]


def test_native_character_run_evidence_survives_public_conversion(tmp_path):
    import hashlib

    source = tmp_path / "text.pdf"
    with fitz.open() as pdf:
        page = pdf.new_page()
        page.insert_text((20, 40), "9.355")
        pdf.save(source)
    result = Converter().convert(
        source, tmp_path / "text.dxf", ConversionRequest(workers=1)
    )
    assert result.status != "failed", result.errors
    document = ezdxf.readfile(next(a.path for a in result.artifacts if a.kind == "dxf"))
    text = list(document.modelspace().query("TEXT"))
    assert "".join(e.dxf.text for e in text) == "9.355"
    for i, e in enumerate(text):
        tags = [t.value for t in e.get_xdata("DRAWING_TEXT_RUN")]
        assert tags == ["v1", "0:0", i, 5, hashlib.sha256(b"9.355").hexdigest()]
