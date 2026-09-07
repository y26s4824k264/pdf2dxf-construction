import ezdxf

from pdf2dxf_stable.profiles import emit_legacy_r12, emit_universal


def test_dedup_inside_blocks_preserves_separate_placements_and_definitions(tmp_path):
    doc = ezdxf.new("R2007")
    block = doc.blocks.new("DRAWING")
    first = block.add_text("100", dxfattribs={"insert": (10, 20), "height": 2})
    duplicate = block.add_text("100", dxfattribs={"insert": (10, 20), "height": 2})
    other = doc.blocks.new("OTHER").add_text(
        "100", dxfattribs={"insert": (10, 20), "height": 2}
    )
    for name, point in (
        ("DRAWING", (0, 0)),
        ("DRAWING", (100, 0)),
        ("OTHER", (200, 0)),
    ):
        doc.modelspace().add_blockref(name, point)
    source, output, legacy = [
        tmp_path / n for n in ("source.dxf", "out.dxf", "r12.dxf")
    ]
    doc.saveas(source)
    report = emit_universal(source, output, seed="block-text")
    assert report.downgraded.get("DUPLICATE_TEXT_HIDDEN") == 1
    final = ezdxf.readfile(output)
    assert final.entitydb[duplicate.dxf.handle].dxf.layer == "PDF_TEXT_DUPLICATE_HIDDEN"
    for handle in (first.dxf.handle, other.dxf.handle):
        assert final.entitydb[handle].dxf.layer == "0"
    assert len(final.modelspace().query("INSERT")) == 3
    emit_legacy_r12(output, legacy, seed="block-text-r12")
    texts = list(ezdxf.readfile(legacy).modelspace().query("TEXT"))
    visible = [e for e in texts if e.dxf.layer == "0"]
    assert [e.dxf.insert.x for e in visible] == [10, 110, 210]
    assert len(texts) == 5  # Both hidden copies are preserved in their placements.
