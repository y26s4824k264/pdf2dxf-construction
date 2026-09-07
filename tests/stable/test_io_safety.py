import json
import os

import fitz
import pytest

from pdf2dxf_stable.batch import _collect, _destination, run_batch, run_regression
from pdf2dxf_stable.cli import main
from pdf2dxf_stable.core import Converter
from pdf2dxf_stable.request import ConversionRequest


@pytest.mark.parametrize("allow, expected", [(False, 5), (True, 2)])
def test_batch_quality_degradation_is_not_success(
    tmp_path, monkeypatch, allow, expected
):
    monkeypatch.setattr(
        "pdf2dxf_stable.batch.run_batch",
        lambda *args: {"count": 1, "ok": 0, "failed": 0, "degraded": 1},
    )
    args = ["batch", "input.pdf", "-o", str(tmp_path)]
    if allow:
        args.append("--allow-quality-degradation")
    assert main(args) == expected


@pytest.mark.parametrize(
    "content", ["null", '"input.pdf"', "{}", "[]", '{"files": [null]}']
)
def test_invalid_or_empty_manifest_is_rejected(tmp_path, content):
    manifest = tmp_path / "inputs.json"
    manifest.write_text(content)
    with pytest.raises(ValueError, match="manifest|PDF"):
        _collect(manifest)


def test_manifest_duplicates_are_processed_once(tmp_path):
    source = tmp_path / "input.pdf"
    source.touch()
    manifest = tmp_path / "inputs.json"
    manifest.write_text(json.dumps(["input.pdf", "./input.pdf", str(source)]))
    assert _collect(manifest) == [source]


def test_batch_summary_cannot_overwrite_manifest(tmp_path):
    source = tmp_path / "input.pdf"
    source.touch()
    manifest = tmp_path / "batch_summary.json"
    original = '["input.pdf"]'
    manifest.write_text(original)
    with pytest.raises(ValueError, match="overwrite"):
        run_batch(manifest, tmp_path, ConversionRequest())
    assert manifest.read_text() == original


@pytest.mark.parametrize("runner", [run_batch, run_regression])
def test_batch_item_output_directory_error_is_reported(tmp_path, runner):
    source = tmp_path / "input.pdf"
    source.touch()
    out = tmp_path / "output"
    parent = out if runner is run_batch else out / "run_1"
    parent.mkdir(parents=True)
    _destination(source, parent).parent.write_text("this is a file, not a directory")
    result = runner(source, out, ConversionRequest())
    assert result["failed"] == 1
    assert result["count"] == 1


def test_cli_json_cannot_overwrite_catalog_through_hardlink(tmp_path):
    catalog = tmp_path / "font.p2dfont"
    catalog.write_bytes(b"catalog must survive")
    alias = tmp_path / "result.json"
    os.link(catalog, alias)
    with pytest.raises(SystemExit) as error:
        main(
            [
                "convert",
                "missing.pdf",
                "-o",
                str(tmp_path / "out.dxf"),
                "--outline-chinese",
                "required",
                "--outline-font-catalog",
                str(catalog),
                "--json",
                str(alias),
            ]
        )
    assert error.value.code == 2
    assert catalog.read_bytes() == b"catalog must survive"


@pytest.mark.parametrize(
    "name, pages, extra",
    [
        ("out_p001.dxf", 2, []),
        ("out.r12.dxf", 1, ["--emit-r12"]),
    ],
)
def test_cli_json_cannot_replace_generated_dxf(tmp_path, name, pages, extra):
    source = tmp_path / "input.pdf"
    with fitz.open() as doc:
        for _ in range(pages):
            doc.new_page().draw_line((10, 20), (100, 20))
        doc.save(source)
    destination = tmp_path / name
    with pytest.raises(SystemExit) as error:
        main(
            [
                "convert",
                str(source),
                "-o",
                str(tmp_path / "out.dxf"),
                "--json",
                str(destination),
                *extra,
            ]
        )
    assert error.value.code == 2
    # Rejection may happen before conversion, but must never replace DXF with JSON.
    if destination.exists():
        import ezdxf

        assert len(ezdxf.readfile(destination).modelspace()) > 0


@pytest.mark.parametrize("suffix", [".dxf", ".report.json", ".dxf.lock"])
def test_converter_protects_input_catalog_from_every_initial_output(tmp_path, suffix):
    catalog = tmp_path / ("out" + suffix)
    catalog.write_bytes(b"source catalog")
    with pytest.raises(ValueError, match="overwrite"):
        Converter().convert(
            "missing.pdf",
            tmp_path / "out.dxf",
            ConversionRequest(
                outline_chinese="required", outline_font_catalogs=[str(catalog)]
            ),
        )
    assert catalog.read_bytes() == b"source catalog"


@pytest.mark.parametrize("pages", ["0", "-1", "a", "1,", "1-1000000000"])
def test_cli_rejects_invalid_page_selection_without_traceback(tmp_path, pages, capsys):
    with pytest.raises(SystemExit) as error:
        main(
            [
                "convert",
                "missing.pdf",
                "-o",
                str(tmp_path / "out.dxf"),
                "--pages",
                pages,
            ]
        )
    assert error.value.code == 2
    assert "Traceback" not in capsys.readouterr().err
