import ezdxf
import pytest
from test_block_validation import block_output, checked

from pdf2dxf_stable.profiles import emit_legacy_r12
from pdf2dxf_stable.request import ConversionRequest
from pdf2dxf_stable.validation import validate_dxf


def test_r12_without_measurable_dimensions_is_not_model_ready(tmp_path):
    output, evidence, request = block_output(tmp_path)
    legacy = tmp_path / "legacy.dxf"
    emit_legacy_r12(output, legacy, seed="proof")
    result = validate_dxf(
        legacy,
        profile="legacy-r12",
        backend_payload={"dimension_evidence": evidence},
        request=request,
    )
    assert result["dimension_count_checked"] == 0
    assert not result["model_ready"]


@pytest.mark.parametrize(
    "entity_role,damage",
    [("extension", "delete"), ("extension", "move"), ("text", "change")],
)
def test_visible_source_entities_are_checked_as_well_as_hidden_dimensions(
    tmp_path, entity_role, damage
):
    output, evidence, request = block_output(tmp_path)
    doc = ezdxf.readfile(output)
    anchor = evidence["anchors"][0]
    handle = (
        anchor["extension_handles"][0]
        if entity_role == "extension"
        else anchor["text_handles"][0]
    )
    entity = doc.entitydb[handle]
    if damage == "delete":
        entity.get_layout().delete_entity(entity)
    elif damage == "move":
        entity.translate(1000, 0, 0)
    else:
        entity.dxf.text = "99999"
    doc.saveas(output)
    result = checked(output, evidence, request)
    assert not result["model_ready"]


def test_evidence_without_any_persisted_dimensions_does_not_confirm_output(tmp_path):
    output, evidence, request = block_output(tmp_path)
    doc = ezdxf.readfile(output)
    for anchor in evidence["anchors"]:
        entity = doc.entitydb[anchor.pop("output_dimension_handle")]
        entity.get_layout().delete_entity(entity)
    doc.saveas(output)
    assert not checked(output, evidence, request)["model_ready"]


def test_infinite_dimension_limit_is_rejected():
    with pytest.raises(ValueError):
        ConversionRequest(dimension_p95_limit=float("inf"))


def test_removing_source_snapshot_cannot_hide_changed_geometry(tmp_path):
    output, evidence, request = block_output(tmp_path)
    anchor = evidence["anchors"][0]
    evidence["source_entities"].pop(anchor["extension_handles"][0])
    assert not checked(output, evidence, request)["model_ready"]


def test_legacy_trust_summary_is_not_independent_scale_evidence(tmp_path):
    output, _evidence, _request = block_output(tmp_path)
    summary = {
        "accepted_viewport_ids": ["A"],
        "trust": {
            "A": {
                "allowed_by_policy": True,
                "two_axis_support": True,
                "grade": "A",
                "residual_p95": 0,
            }
        },
    }
    result = validate_dxf(output, profile="universal", backend_payload=summary)
    assert not result["model_ready"]
    assert not result["engineering_scale_confirmed"]


def test_manual_scale_does_not_make_empty_dxf_model_ready(tmp_path):
    path = tmp_path / "empty.dxf"
    ezdxf.new("R2007").saveas(path)
    result = validate_dxf(
        path,
        profile="universal",
        request=ConversionRequest(scale_mode="manual", manual_scale=100),
    )
    assert not result["model_ready"]
    assert any(e["code"] == "MODELSPACE_EMPTY" for e in result["errors"])


@pytest.mark.parametrize("limit", [float("nan"), float("inf"), 0, -1])
def test_validator_rejects_invalid_limit_before_reading_geometry(tmp_path, limit):
    output, _evidence, _request = block_output(tmp_path)
    with pytest.raises(ValueError):
        validate_dxf(output, profile="universal", dimension_p95_limit=limit)
