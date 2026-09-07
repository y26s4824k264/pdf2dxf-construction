import ezdxf
import pytest
from ezdxf.enums import TextEntityAlignment

from pdf2dxf_stable.profiles import emit_legacy_r12


@pytest.mark.parametrize(
    "align",
    [
        TextEntityAlignment.FIT,
        TextEntityAlignment.ALIGNED,
        TextEntityAlignment.MIDDLE_CENTER,
    ],
)
def test_r12_keeps_text_alignment_and_second_point(tmp_path, align):
    doc = ezdxf.new("R2007")
    entity = doc.modelspace().add_text("24050", dxfattribs={"height": 2})
    entity.set_placement((10, 20), (70, 90), align=align)
    source, output = tmp_path / "source.dxf", tmp_path / "r12.dxf"
    doc.saveas(source)
    emit_legacy_r12(source, output, seed="r12-placement")
    final = next(iter(ezdxf.readfile(output).modelspace().query("TEXT")))
    alignment, first, second = final.get_placement()
    assert alignment == align
    assert first.isclose((10, 20, 0))
    if align in (TextEntityAlignment.FIT, TextEntityAlignment.ALIGNED):
        assert second.isclose((70, 90, 0))


def test_r12_keeps_transformed_text_placement_and_slant(tmp_path):
    doc = ezdxf.new("R2007")
    block = doc.blocks.new("LABEL")
    text = block.add_text(
        "24050", dxfattribs={"height": 2, "oblique": 15, "text_generation_flag": 2}
    )
    text.set_placement((10, 20), (70, 20), align=TextEntityAlignment.FIT)
    insert = doc.modelspace().add_blockref(
        "LABEL", (100, 200), dxfattribs={"rotation": 30, "xscale": 2, "yscale": 2}
    )
    expected = next(iter(insert.virtual_entities()))
    source, output = tmp_path / "source.dxf", tmp_path / "r12.dxf"
    doc.saveas(source)
    emit_legacy_r12(source, output, seed="r12-transformed")
    final = next(iter(ezdxf.readfile(output).modelspace().query("TEXT")))
    for key in ("insert", "align_point"):
        assert final.dxf.get(key).isclose(expected.dxf.get(key))
    for key in ("height", "oblique", "text_generation_flag", "halign"):
        assert final.dxf.get(key) == pytest.approx(expected.dxf.get(key))


@pytest.mark.parametrize("rotation", [0, 90])
def test_r12_multiline_text_respects_attachment_and_rotated_line_spacing(
    tmp_path, rotation
):
    doc = ezdxf.new("R2007")
    doc.modelspace().add_mtext(
        "ONE\\PTWO",
        dxfattribs={
            "insert": (100, 200),
            "char_height": 2,
            "width": 20,
            "attachment_point": 9,
            "rotation": rotation,
        },
    )
    source, output = tmp_path / "source.dxf", tmp_path / "r12.dxf"
    doc.saveas(source)
    report = emit_legacy_r12(source, output, seed="r12-multiline")
    assert all(w["code"] == "R12_FONT_METRICS_FALLBACK" for w in report.warnings)
    final = ezdxf.readfile(output)
    texts = {e.dxf.text: e for e in final.modelspace().query("TEXT")}
    assert set(texts) == {"ONE", "TWO"}
    first, second = texts["ONE"].dxf.insert, texts["TWO"].dxf.insert
    assert texts["ONE"].dxf.rotation == pytest.approx(rotation)
    if rotation == 90:
        assert second.x > first.x
        assert first.y < 200 and second.y < 200
    else:
        assert first.y > second.y
        assert first.x < 100 and second.x < 100


def test_r12_no_system_fonts_keeps_text_and_reports_metric_substitution(
    tmp_path, monkeypatch
):
    from ezdxf.fonts import fonts
    from ezdxf.fonts.font_manager import FontManager

    monkeypatch.setattr(fonts, "font_manager", FontManager())
    doc = ezdxf.new("R2007")
    doc.modelspace().add_mtext("ONE\\PTWO", dxfattribs={"char_height": 2})
    source, output = tmp_path / "source.dxf", tmp_path / "r12.dxf"
    doc.saveas(source)
    report = emit_legacy_r12(source, output, seed="no-system-fonts")
    assert {e.dxf.text for e in ezdxf.readfile(output).modelspace().query("TEXT")} == {
        "ONE",
        "TWO",
    }
    assert any(w["code"] == "R12_FONT_METRICS_FALLBACK" for w in report.warnings)
    assert all(w["code"] == "R12_FONT_METRICS_FALLBACK" for w in report.warnings)
