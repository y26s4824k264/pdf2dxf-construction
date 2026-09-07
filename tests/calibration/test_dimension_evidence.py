import itertools
import json
from copy import deepcopy
from pathlib import Path

import ezdxf
import pytest

from pdf2dxf_stable.engine.calibration.evidence import (
    _chains,
    analyze_dimensions,
    calibrate_paper_dxf,
)
from pdf2dxf_stable.engine.text.dxf_text import CATALOG, load_catalog, read_tokens
from pdf2dxf_stable.profiles import emit_universal
from pdf2dxf_stable.request import ConversionRequest
from pdf2dxf_stable.validation import validate_dxf


def add_dimension(doc, p0, p1, label, axis=0, shortened=True):
    layer = "DIMS"
    if layer not in doc.layers:
        doc.layers.new(layer)
    cross = p0[1 - axis]
    for point in (p0, p1):
        a, b = list(point), list(point)
        a[1 - axis] -= 5
        b[1 - axis] += 1
        doc.modelspace().add_line(a, b, dxfattribs={"layer": layer})
        if shortened:
            a, b = list(point), list(point)
            a[axis] -= 0.5
            b[axis] += 0.5
            doc.modelspace().add_lwpolyline([a, point, b], dxfattribs={"layer": layer})
    a, b = list(p0), list(p1)
    if shortened:
        a[axis] += 0.3
        b[axis] -= 0.3
    doc.modelspace().add_line(a, b, dxfattribs={"layer": layer})
    text = str(label)
    h = 2
    start = (p0[axis] + p1[axis]) / 2 - 0.6 * h * len(text) / 2
    insert = (start, cross + 0.4) if axis == 0 else (cross - 0.4, start)
    doc.modelspace().add_text(
        text, dxfattribs={"height": h, "insert": insert, "rotation": axis * 90}
    )


def fixture(scales=(100, 100), bad=False):
    d = ezdxf.new("R2007")
    d.header["$INSUNITS"] = 4
    for axis, scale in enumerate(scales):
        points = [20, 40, 70, 120]
        cross = 10 if axis == 0 else 180
        for i, (a, b) in enumerate(itertools.pairwise(points)):
            p0, p1 = ((a, cross), (b, cross)) if axis == 0 else ((cross, a), (cross, b))
            label = round((b - a) * scale)
            if bad and i == 1:
                label *= 2
            add_dimension(d, p0, p1, label, axis)
        cross -= 8 if axis == 0 else -8
        p0, p1 = (
            ((20, cross), (120, cross)) if axis == 0 else ((cross, 20), (cross, 120))
        )
        add_dimension(d, p0, p1, round(100 * scale), axis)
    return d


def test_dimensions_bind_extensions_instead_of_shortened_dimension_line():
    r = analyze_dimensions(fixture(), recover=False)
    assert r["status"] == "confirmed", r["reasons"]
    assert r["scale"] == pytest.approx(100)
    assert r["holdout_count"] >= 2
    assert all(a["observed_scale"] == pytest.approx(100) for a in r["anchors"])
    assert any(c["passed"] and c["total_mm"] == 10000 for c in r["chains"])


@pytest.mark.parametrize("scales,bad", [((100, 200), False), ((100, 100), True)])
def test_conflicting_scale_or_wrong_dimension_is_refused(scales, bad):
    r = analyze_dimensions(fixture(scales, bad), recover=False)
    assert r["status"] == "unconfirmed"
    assert not r["model_output"]


def test_title_alone_never_sets_engineering_scale():
    d = ezdxf.new("R2007")
    d.modelspace().add_text("1:100", dxfattribs={"height": 2})
    d.modelspace().add_text("1 : 100", dxfattribs={"height": 2})
    r = analyze_dimensions(d, recover=False)
    assert r["scale"] is None
    assert r["title_scales"] == ["1:100"]
    assert not r["model_output"]


def test_material_mix_ratio_is_not_a_title_scale():
    doc = ezdxf.new("R2007")
    doc.modelspace().add_text("20厚1:2.5水泥砂浆", dxfattribs={"height": 2})
    report = analyze_dimensions(doc, recover=False)
    assert report["title_scales"] == []


def test_declared_scale_keeps_detected_table_content_in_paper_space(tmp_path):
    source = tmp_path / "table-paper.dxf"
    output = tmp_path / "table-output.dxf"
    doc = ezdxf.new("R2007")
    doc.modelspace().add_text("门窗表", dxfattribs={"height": 3})
    doc.modelspace().add_text("1:90", dxfattribs={"height": 3})
    doc.saveas(source)

    report = calibrate_paper_dxf(
        source,
        output,
        mode="blocks",
        recover=False,
        allow_declared_scale=True,
    )

    assert report["sheet_text_markers"] == ["门窗表"]
    assert report["title_scales"] == ["1:90"]
    assert report["status"] == "unconfirmed"
    assert "sheet_content_requires_paper_space" in report["reasons"]
    assert not report["applied"]


def test_declared_title_scale_is_uniformly_applied_but_remains_unconfirmed(tmp_path):
    paper, model, output = [
        tmp_path / name for name in ("paper.dxf", "model.dxf", "final.dxf")
    ]
    doc = ezdxf.new("R2007")
    line = doc.modelspace().add_line((10, 20), (20, 20))
    handle = line.dxf.handle
    doc.modelspace().add_text("1:80", dxfattribs={"height": 2, "insert": (30, 10)})
    doc.saveas(paper)

    evidence = calibrate_paper_dxf(
        paper,
        model,
        recover=False,
        allow_declared_scale=True,
    )
    scaled = ezdxf.readfile(model)
    assert evidence["status"] == "declared_approximate"
    assert evidence["scale_source"] == "single_title_scale"
    assert evidence["scale"] == pytest.approx(80)
    assert evidence["applied"] and not evidence["engineering_scale_confirmed"]
    assert scaled.entitydb[handle].dxf.start.x == pytest.approx(800)
    assert scaled.entitydb[handle].dxf.end.x == pytest.approx(1600)

    request = ConversionRequest(scale_mode="declared")
    emit_universal(model, output, seed="declared-scale", request=request)
    checked = validate_dxf(
        output,
        profile="universal",
        backend_payload={"dimension_evidence": evidence},
        request=request,
    )
    assert checked["geometry_valid"] and checked["valid"]
    assert checked["scale_status"] == "declared_approximate"
    assert not checked["engineering_scale_confirmed"]
    assert not checked["model_ready"]
    assert any(
        row["code"] == "ENGINEERING_SCALE_APPROXIMATE" for row in checked["warnings"]
    )


def test_declared_scale_refuses_multiple_title_scales(tmp_path):
    paper, output = tmp_path / "paper.dxf", tmp_path / "out.dxf"
    doc = ezdxf.new("R2007")
    doc.modelspace().add_line((0, 0), (10, 0))
    for index, value in enumerate(("1:50", "1:100")):
        doc.modelspace().add_text(
            value, dxfattribs={"height": 2, "insert": (0, index * 5)}
        )
    doc.saveas(paper)
    evidence = calibrate_paper_dxf(
        paper,
        output,
        recover=False,
        allow_declared_scale=True,
    )
    assert evidence["status"] == "unconfirmed"
    assert not evidence["applied"]
    assert "multiple_declared_view_scales" in evidence["reasons"]


@pytest.mark.parametrize(
    "units,factor", [("mm", 100), ("m", 0.1), ("inch", 100 / 25.4)]
)
def test_written_dimensions_and_units_are_independently_measured(
    tmp_path, units, factor
):
    paper, model, output = [
        tmp_path / n for n in ("paper.dxf", "model.dxf", "final.dxf")
    ]
    d = fixture()
    original = d.modelspace().add_line((0, 250), (10, 250))
    handle = original.dxf.handle
    d.saveas(paper)
    evidence = calibrate_paper_dxf(paper, model, recover=False)
    request = ConversionRequest(units=units)
    emit_universal(model, output, seed="evidence", request=request)
    final = ezdxf.readfile(output)
    assert final.entitydb[handle].dxf.end.x == pytest.approx(10 * factor)
    result = validate_dxf(
        output,
        profile="universal",
        backend_payload={"dimension_evidence": evidence},
        request=request,
    )
    assert result["scale_status"] == "calibrated"
    assert result["model_ready"], result
    assert result["dimension_count_checked"] == 8
    assert result["dimension_relative_error_p95"] < 1e-10
    # Re-reading changed geometry must invalidate a previously valid report.
    dim = next(iter(final.modelspace().query("DIMENSION")))
    dim.dxf.defpoint3 = dim.dxf.defpoint3 + (1e4, 0, 0)
    final.saveas(output)
    assert not validate_dxf(
        output,
        profile="universal",
        backend_payload={"dimension_evidence": evidence},
        request=request,
    )["model_ready"]


def test_single_axis_and_manual_page_mode_do_not_claim_auto_calibration(tmp_path):
    d = fixture()
    entities = list(d.modelspace())
    for e in entities:
        if e.dxftype() == "TEXT" and e.dxf.rotation == 90:
            d.modelspace().delete_entity(e)
    assert analyze_dimensions(d, recover=False)["status"] == "unconfirmed"
    paper, output = tmp_path / "paper.dxf", tmp_path / "out.dxf"
    fixture().saveas(paper)
    report = calibrate_paper_dxf(paper, output, mode="sheet", recover=False)
    assert report["status"] == "confirmed" and not report["applied"]
    assert report["paper_mm_preserved"]


def test_catalog_has_real_digit_shapes_and_label_provenance():
    assert set("0123456789") <= {r[0] for r in load_catalog()}
    data = json.loads(CATALOG.read_text())
    assert all(
        len(t["source_sha256"]) == 64 and t["label_evidence"] and t["paths"]
        for t in data["templates"]
    )


def test_window_id_prefix_and_unrecognized_strokes_cannot_become_dimensions():
    data = json.loads(CATALOG.read_text())
    shapes = {
        t["char"]: t["paths"] for t in data["templates"] if t["source"] == "superos.shx"
    }
    d = ezdxf.new("R2007")
    for i, ch in enumerate("C1564"):
        for path in shapes[ch]:
            d.modelspace().add_lwpolyline([(x / 10 + i * 2, y / 10) for x, y in path])
    tokens, stats = read_tokens(d)
    assert not any(t.text == "1564" for t in tokens)
    assert stats["accepted_tokens"] == 0


def test_multiple_title_scales_refuse_global_scaling():
    doc = fixture()
    for i, text in enumerate(("1:100", "1:50")):
        doc.modelspace().add_text(
            text, dxfattribs={"height": 2, "insert": (300, i * 5)}
        )
    report = analyze_dimensions(doc, recover=False)
    assert report["status"] == "unconfirmed"
    assert "multiple_declared_view_scales" in report["reasons"]


def test_block_export_and_intentional_paper_units(tmp_path):
    paper, model, output = [
        tmp_path / n for n in ("paper.dxf", "model.dxf", "final.dxf")
    ]
    fixture().saveas(paper)
    evidence = calibrate_paper_dxf(paper, model, mode="blocks", recover=False)
    doc = ezdxf.readfile(model)
    assert len(doc.modelspace().query("INSERT")) == 1
    assert len(doc.blocks.get("PDF2DXF_MODEL").query("DIMENSION")) == 8
    emit_universal(model, output, seed="blocks")
    checked = validate_dxf(
        output,
        profile="universal",
        backend_payload={"dimension_evidence": evidence},
        request=ConversionRequest(),
    )
    assert checked["model_ready"], checked
    evidence = calibrate_paper_dxf(paper, model, mode="sheet", recover=False)
    request = ConversionRequest(scale_mode="page")
    emit_universal(model, output, seed="page", request=request)
    checked = validate_dxf(
        output,
        profile="universal",
        backend_payload={"dimension_evidence": evidence},
        request=request,
    )
    assert checked["geometry_valid"] and checked["scale_status"] == "paper"
    assert not checked["model_ready"]


@pytest.mark.parametrize("angle", [90, 180, 270])
def test_rotated_native_dimensions_keep_two_axis_evidence(angle):
    import math

    from ezdxf import transform
    from ezdxf.math import Matrix44

    doc = fixture()
    transform.inplace(doc.modelspace(), Matrix44.z_rotate(math.radians(angle)))
    evidence = analyze_dimensions(doc, recover=False)
    assert evidence["status"] == "confirmed", evidence["reasons"]
    assert evidence["scale"] == pytest.approx(100)


@pytest.mark.parametrize("origin", [(0, 0), (500, 500), (-2000, 1200)])
def test_character_grouping_survives_small_height_differences(origin):
    doc = ezdxf.new("R2007")
    for i, char in enumerate("24050"):
        doc.modelspace().add_text(
            char,
            dxfattribs={
                "height": 2 + (i % 2) * 0.002,
                "insert": (origin[0] + i * 1.5, origin[1]),
            },
        )
    tokens, _ = read_tokens(doc, recover=False)
    assert [t.text for t in tokens] == ["24050"]


def test_character_grouping_keeps_prefix_across_height_bucket_boundary():
    doc = ezdxf.new("R2007")
    for i, char in enumerate("C1564"):
        doc.modelspace().add_text(
            char,
            dxfattribs={
                "height": 2.01 if char == "C" else 2,
                "insert": (500 + i * 1.5, 500),
            },
        )
    tokens, _ = read_tokens(doc, recover=False)
    assert [t.text for t in tokens] == ["C1564"]


def test_repeated_dimension_spans_do_not_leak_into_holdout():
    doc = fixture()
    # The same two projected endpoints annotated at another chain level are
    # repeated evidence, even though their DXF handles and baselines differ.
    for y in (0, -10, -20):
        add_dimension(doc, (20, y), (40, y), 2000)
    report = analyze_dimensions(doc, recover=False)
    assert report["status"] == "confirmed", report["reasons"]
    roles = {}
    for anchor in report["anchors"]:
        axis = 0 if anchor["axis"] == "x" else 1
        key = (axis, anchor["p0"][axis], anchor["p1"][axis])
        roles.setdefault(key, set()).add(anchor["role"])
    assert all(not {"fit", "holdout"} <= values for values in roles.values())


@pytest.mark.parametrize("damage", ["missing_dimension", "all_fit", "false_chain"])
def test_validation_rechecks_evidence_instead_of_trusting_summary(tmp_path, damage):
    paper, output = tmp_path / "paper.dxf", tmp_path / "out.dxf"
    fixture().saveas(paper)
    evidence = deepcopy(calibrate_paper_dxf(paper, output, recover=False))
    if damage == "missing_dimension":
        doc = ezdxf.readfile(output)
        doc.modelspace().delete_entity(next(iter(doc.modelspace().query("DIMENSION"))))
        doc.saveas(output)
    elif damage == "all_fit":
        for a in evidence["anchors"]:
            a["role"] = "fit"
    else:
        for chain in evidence["chains"]:
            chain["parts"] = [chain["total"], chain["total"]]
    checked = validate_dxf(
        output,
        profile="universal",
        backend_payload={"dimension_evidence": evidence},
        request=ConversionRequest(),
    )
    assert not checked["model_ready"], checked


def test_crossing_dimension_stroke_does_not_consume_last_zero():
    source = json.loads(
        (Path(__file__).parent / "fixtures/crossing_dimension_label.json").read_text()
    )
    doc = ezdxf.new("R2007")
    for e in source["entities"]:
        for path in e["paths"]:
            doc.modelspace().add_lwpolyline(path, dxfattribs={"layer": e["layer"]})
    tokens, _ = read_tokens(doc)
    assert any(
        t.text == source["expected_text"] and t.angle == source["angle"] for t in tokens
    )
    assert not any(t.text == "2405" for t in tokens)


def test_conflicting_repeated_label_is_kept_out_of_scale_fit():
    doc = fixture()
    add_dimension(doc, (20, -10), (40, -10), 2001)
    report = analyze_dimensions(doc, recover=False)
    assert report["status"] == "confirmed", report["reasons"]
    repeated = [
        a
        for a in report["anchors"]
        if a["axis"] == "x" and a["p0"][0] == 20 and a["p1"][0] == 40
    ]
    assert {a["role"] for a in repeated} == {"check_only"}
    assert all(
        a["fit_exclusion"] == "conflicting_repeated_span_labels" for a in repeated
    )


def test_text_deduplication_requires_same_real_position_and_height(tmp_path):
    doc = ezdxf.new("R2007")
    handles = []
    for xy, height in [((10, 10), 1), ((20, 20), 2), ((10, 10), 2)]:
        text = doc.modelspace().add_text(
            "A", dxfattribs={"insert": xy, "height": height}
        )
        handles.append(text.dxf.handle)
    source, output = tmp_path / "source.dxf", tmp_path / "output.dxf"
    doc.saveas(source)
    emit_universal(source, output, seed="native-text-preservation")
    final = ezdxf.readfile(output)
    assert all(
        final.entitydb[h].dxf.layer != "PDF_TEXT_DUPLICATE_HIDDEN" for h in handles
    )


@pytest.mark.parametrize("separate_parts", [True, False])
def test_dimensions_on_unrelated_baselines_cannot_confirm_scale(separate_parts):
    doc = ezdxf.new("R2007")
    for axis in (0, 1):
        for i, (a, b) in enumerate(((20, 40), (40, 70), (70, 120), (20, 120))):
            cross = (10 + i * 200) if separate_parts else (610 if i == 3 else 10)
            p0, p1 = ((a, cross), (b, cross)) if axis == 0 else ((cross, a), (cross, b))
            add_dimension(doc, p0, p1, (b - a) * 100, axis)
    report = analyze_dimensions(doc, recover=False)
    assert report["status"] == "unconfirmed"
    assert "dimension_chain_not_confirmed" in report["reasons"]


def test_validation_rejects_projected_chain_from_unrelated_baselines():
    from pdf2dxf_stable.validation import _confirmed_dimension_evidence

    report = analyze_dimensions(fixture(), recover=False)
    assert _confirmed_dimension_evidence(report, 0.002)
    for i, a in enumerate(report["anchors"]):
        cross_axis = 1 if a["axis"] == "x" else 0
        for p in (a["p0"], a["p1"]):
            p[cross_axis] += i * 200
    assert not _confirmed_dimension_evidence(report, 0.002)


def test_overlapping_complete_chains_are_ambiguous_even_when_sums_agree():
    doc = ezdxf.new("R2007")
    for a, b in ((0, 60), (60, 100), (0, 40), (40, 100)):
        add_dimension(doc, (a, 10), (b, 10), (b - a) * 100)
    add_dimension(doc, (0, 2), (100, 2), 10000)
    report = analyze_dimensions(doc, recover=False)
    chains = _chains(report["anchors"])
    assert not any(c["passed"] and c["total_mm"] == 10000 for c in chains)


@pytest.mark.parametrize(
    "text,value",
    [("1m", 1000), ("2.5m", 2500), ("0.5m", 500), (".5m", 500), ("5cm", 50)],
)
def test_small_dimensions_with_explicit_units_are_converted(tmp_path, text, value):
    doc = fixture()
    add_dimension(doc, (20, -40), (20 + value / 100, -40), text, shortened=False)
    report = analyze_dimensions(doc, recover=False)
    matches = [a for a in report["anchors"] if a["text"] == text]
    assert len(matches) == 1
    assert matches[0]["label_mm"] == value
    assert matches[0]["observed_scale"] == pytest.approx(100)
    assert matches[0]["label_unit_source"] == "explicit"
    paper, output = tmp_path / "paper.dxf", tmp_path / "model.dxf"
    doc.saveas(paper)
    evidence = calibrate_paper_dxf(paper, output, recover=False)
    anchor = next(a for a in evidence["anchors"] if a["text"] == text)
    final = ezdxf.readfile(output)
    assert final.entitydb[
        anchor["output_dimension_handle"]
    ].get_measurement() == pytest.approx(value)


@pytest.mark.parametrize("text", ["0m", "0.0cm", "5", ".5", "C1m", "-1m", "1e3m"])
def test_small_or_nonpositive_numbers_without_clear_dimension_units_are_ignored(text):
    doc = fixture()
    add_dimension(doc, (20, -40), (40, -40), text)
    assert not any(
        a["text"] == text for a in analyze_dimensions(doc, recover=False)["anchors"]
    )


def test_real_plumbing_chain_has_seventeen_local_parts():
    source = json.loads(
        (Path(__file__).parent / "fixtures/local_dimension_chain.json").read_text()
    )
    chains = _chains(source["anchors"])
    match = next(c for c in chains if c["total"] == source["total_id"])
    assert match["passed"]
    assert len(match["parts"]) == 17
    assert match["parts_sum_mm"] == match["total_mm"] == 94175
    assert match["level_separation_paper_mm"] == pytest.approx(8.000975884331638)


def test_dimension_chain_cannot_cross_layers_or_pass_incomplete_search(monkeypatch):
    from pdf2dxf_stable.engine.calibration import chains

    anchors = analyze_dimensions(fixture(), recover=False)["anchors"]
    for a in anchors:
        a["dimension_layer"] = a["id"]
    assert not any(c["passed"] for c in _chains(anchors))
    for a in anchors:
        a["dimension_layer"] = "DIMS"
    monkeypatch.setattr(chains, "MAX_SEARCH_STEPS", 2)
    result = _chains(anchors)
    assert result and not any(c["passed"] for c in result)
    assert all(c["reason"] == "search_limit" for c in result)


def test_total_dimension_can_use_separate_grid_annotation_layer():
    anchors = analyze_dimensions(fixture(), recover=False)["anchors"]
    for a in anchors:
        if a["label_mm"] == 10000:
            a["dimension_layer"] = "GRID_TOTAL"
    assert sum(c["passed"] for c in _chains(anchors)) == 2
