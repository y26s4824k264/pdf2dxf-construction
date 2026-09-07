import json

import ezdxf
import pytest
from test_contracts import pdf_file

from pdf2dxf_stable.cli import main
from pdf2dxf_stable.core import Converter
from pdf2dxf_stable.determinism import sha256
from pdf2dxf_stable.request import ConversionRequest


def saved_manual_output(tmp_path):
    path = tmp_path / "drawing.dxf"
    doc = ezdxf.new("R2007")
    doc.header["$INSUNITS"] = 6
    doc.modelspace().add_line((0, 0), (1, 0))
    doc.modelspace().add_linear_dim(
        base=(0, 0.1), p1=(0, 0), p2=(1, 0), text="1000"
    ).render()
    doc.saveas(path)
    report = {
        "artifacts": [{"kind": "dxf", "path": str(path), "sha256": sha256(path)}],
        "pages": [
            {
                "page": 1,
                "request": ConversionRequest(
                    scale_mode="manual", manual_scale=100, units="m"
                ).model_dump(),
                "backend": {},
                "universal_validation": {"path": str(path)},
            }
        ],
    }
    path.with_suffix(".report.json").write_text(json.dumps(report))
    return path


def test_validate_cli_reopens_saved_output_with_its_request_and_report(
    tmp_path, capsys
):
    path = saved_manual_output(tmp_path)
    assert main(["validate", str(path)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["model_ready"]
    assert result["output_units"] == "m"
    assert result["scale_status"] == "user_confirmed"


def test_validate_cli_detects_change_outside_dimension_evidence(tmp_path, capsys):
    path = saved_manual_output(tmp_path)
    doc = ezdxf.readfile(path)
    next(iter(doc.modelspace().query("LINE"))).dxf.end = (2, 0, 0)
    doc.saveas(path)
    assert main(["validate", str(path)]) == 5
    result = json.loads(capsys.readouterr().out)
    assert any(e["code"] == "ARTIFACT_HASH_MISMATCH" for e in result["errors"])


def test_cli_json_cannot_overwrite_input_or_dxf(tmp_path):
    path = saved_manual_output(tmp_path)
    before = path.read_bytes()
    with pytest.raises(SystemExit) as error:
        main(["validate", str(path), "--json", str(path)])
    assert error.value.code == 2
    assert path.read_bytes() == before


def test_cli_writing_default_report_keeps_report_hash_valid(tmp_path, capsys):
    source = pdf_file(tmp_path / "source.pdf")
    output = tmp_path / "result.dxf"
    report = output.with_suffix(".report.json")
    main(
        [
            "convert",
            str(source),
            "-o",
            str(output),
            "--scale-mode",
            "manual",
            "--manual-scale",
            "100",
            "--no-path-text",
            "--json",
            str(report),
        ]
    )
    result = json.loads(capsys.readouterr().out)
    artifact = next(a for a in result["artifacts"] if a["kind"] == "report")
    assert sha256(report) == artifact["sha256"]


@pytest.mark.parametrize("case", ["source", "report", "wrong_suffix"])
def test_converter_rejects_paths_that_overwrite_input_or_ignore_target(tmp_path, case):
    target = tmp_path / "output.dxf"
    source = (
        target
        if case == "source"
        else target.with_suffix(".report.json")
        if case == "report"
        else tmp_path / "source.pdf"
    )
    pdf_file(source)
    original = source.read_bytes()
    if case == "wrong_suffix":
        target = tmp_path / "output.pdf"
    with pytest.raises(ValueError):
        Converter().convert(
            source, target, ConversionRequest(recover_pure_path_text=False)
        )
    assert source.read_bytes() == original
