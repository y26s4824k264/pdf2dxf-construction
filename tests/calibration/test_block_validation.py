import ezdxf
import pytest
from test_dimension_evidence import fixture

from pdf2dxf_stable.engine.calibration.evidence import calibrate_paper_dxf
from pdf2dxf_stable.profiles import emit_universal
from pdf2dxf_stable.request import ConversionRequest
from pdf2dxf_stable.validation import validate_dxf


def block_output(tmp_path, units="mm", nested=False):
    paper, model, output = [tmp_path / n for n in ("paper.dxf", "model.dxf", "out.dxf")]
    fixture().saveas(paper)
    evidence = calibrate_paper_dxf(paper, model, mode="blocks", recover=False)
    if nested:
        doc = ezdxf.readfile(model)
        original = next(iter(doc.modelspace().query("INSERT")))
        wrapper = doc.blocks.new("WRAPPER", base_point=(50, 70))
        doc.modelspace().move_to_layout(original, wrapper)
        original.dxf.insert = (50, 70, 0)
        doc.modelspace().add_blockref("WRAPPER", (0, 0))
        doc.saveas(model)
    request = ConversionRequest(mode="blocks", units=units)
    emit_universal(model, output, seed="block-validation", request=request)
    return output, evidence, request


def checked(output, evidence, request):
    return validate_dxf(
        output,
        profile="universal",
        backend_payload={"dimension_evidence": evidence},
        request=request,
    )


@pytest.mark.parametrize("units", ["mm", "cm", "m", "inch"])
@pytest.mark.parametrize("nested", [False, True])
def test_block_measurements_use_final_coordinates(tmp_path, units, nested):
    output, evidence, request = block_output(tmp_path, units, nested)
    result = checked(output, evidence, request)
    assert result["model_ready"], result["errors"]
    assert result["dimension_count_checked"] == 8
    assert result["dimension_relative_error_p95"] < 1e-10


@pytest.mark.parametrize(
    "damage", ["delete", "move", "elevation", "rotate", "scale", "duplicate", "array"]
)
def test_altered_block_reference_cannot_pass_source_evidence(tmp_path, damage):
    output, evidence, request = block_output(tmp_path)
    doc = ezdxf.readfile(output)
    insert = next(iter(doc.modelspace().query("INSERT")))
    if damage == "delete":
        doc.modelspace().delete_entity(insert)
    elif damage == "move":
        insert.dxf.insert = (100, 200, 0)
    elif damage == "elevation":
        insert.dxf.insert = (0, 0, 100)
    elif damage == "rotate":
        insert.dxf.rotation = 90
    elif damage == "scale":
        insert.dxf.xscale = 2
    elif damage == "array":
        insert.dxf.column_count = 2
        insert.dxf.column_spacing = 50000
    else:
        doc.modelspace().add_blockref(insert.dxf.name, (0, 0))
    doc.saveas(output)
    assert not checked(output, evidence, request)["model_ready"]


def test_unreferenced_block_dimensions_do_not_count_as_output(tmp_path):
    output, evidence, request = block_output(tmp_path)
    doc = ezdxf.readfile(output)
    unused = doc.blocks.new("UNUSED")
    unused.add_linear_dim(base=(0, 1), p1=(0, 0), p2=(50, 0), text="100").render()
    doc.saveas(output)
    result = checked(output, evidence, request)
    assert result["model_ready"], result["errors"]
    assert result["dimension_count_checked"] == 8


def test_cyclic_block_reference_is_reported_without_recursion(tmp_path):
    output, evidence, request = block_output(tmp_path)
    doc = ezdxf.readfile(output)
    block = doc.blocks.new("CYCLE")
    block.add_blockref("CYCLE", (0, 0))
    doc.modelspace().add_blockref("CYCLE", (0, 0))
    doc.saveas(output)
    result = checked(output, evidence, request)
    assert not result["model_ready"]
    assert any(e["code"] == "BLOCK_REFERENCE_CYCLE" for e in result["errors"])


def test_nested_array_measurement_is_bounded_and_counts_placements(
    tmp_path, monkeypatch
):
    from pdf2dxf_stable import dimension_instances

    output, evidence, request = block_output(tmp_path, units="m", nested=True)
    doc = ezdxf.readfile(output)
    insert = next(iter(doc.modelspace().query("INSERT")))
    insert.dxf.column_count = 3
    insert.dxf.column_spacing = 50
    doc.saveas(output)
    result = checked(output, evidence, request)
    assert result["dimension_count_checked"] == 24
    assert result["dimension_relative_error_p95"] < 1e-10
    assert not result["model_ready"]
    monkeypatch.setattr(dimension_instances, "MAX_INSTANCES", 10)
    result = checked(output, evidence, request)
    assert not result["model_ready"]
    assert any(e["code"] == "BLOCK_INSTANCE_LIMIT" for e in result["errors"])


def test_angular_measurement_does_not_convert_degrees_to_millimetres(tmp_path):
    output, evidence, request = block_output(tmp_path, units="m")
    doc = ezdxf.readfile(output)
    doc.modelspace().add_angular_dim_3p(
        base=(5, 5), center=(0, 0), p1=(10, 0), p2=(0, 10), text="90"
    ).render()
    doc.saveas(output)
    result = checked(output, evidence, request)
    assert result["model_ready"], result["errors"]
    assert result["dimension_count_checked"] == 9


def test_nonfinite_dimension_cannot_be_silently_skipped(tmp_path):
    output, evidence, request = block_output(tmp_path)
    doc = ezdxf.readfile(output)
    dimension = doc.modelspace().add_linear_dim(
        base=(0, 2), p1=(0, 0), p2=(100, 0), text="100"
    )
    dimension.render()
    dimension.dimension.dxf.defpoint3 = (float("nan"), 0, 0)
    doc.saveas(output)
    result = checked(output, evidence, request)
    assert not result["model_ready"]
    assert any(e["code"] == "DIMENSION_MEASUREMENT_INVALID" for e in result["errors"])
