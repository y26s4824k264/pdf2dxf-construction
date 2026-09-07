import json
import subprocess
from pathlib import Path

import fitz
from PIL import Image

from pdf2dxf_stable import Converter, ConversionRequest
from pdf2dxf_stable.repair import _can_open, recover_pdf


def test_non_pdf_document_is_not_accepted_as_pdf(tmp_path):
    source = tmp_path / "image.pdf"
    Image.new("RGB", (20, 20)).save(source, format="PNG")
    ok, reason = _can_open(source)
    assert not ok and "NOT_PDF" in reason


def test_encrypted_pdf_has_explicit_password_error(tmp_path):
    source = tmp_path / "locked.pdf"
    with fitz.open() as doc:
        doc.new_page()
        doc.save(
            source,
            encryption=fitz.PDF_ENCRYPT_AES_256,
            owner_pw="owner",
            user_pw="reader",
        )
    ok, reason = _can_open(source)
    assert not ok and "PASSWORD_REQUIRED" in reason


def test_repair_timeout_does_not_skip_next_available_tool(tmp_path, monkeypatch):
    from pdf2dxf_stable import repair

    source = tmp_path / "broken.pdf"
    source.write_bytes(b"broken")
    attempted = []

    def run(command, **kwargs):
        attempted.append(command[0])
        if command[0] == "qpdf":
            raise subprocess.TimeoutExpired(command, 300)
        with fitz.open() as doc:
            doc.new_page()
            doc.save(command[-1])
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(repair.shutil, "which", lambda name: name)
    monkeypatch.setattr(repair.subprocess, "run", run)
    result = recover_pdf(source, tmp_path / "repair")
    assert result.repaired and result.selected
    assert attempted == ["qpdf", "mutool"]
    assert "TIMEOUT" in result.attempts[1].message


def test_preflight_resource_failure_is_persisted_without_running_page(
    tmp_path, monkeypatch
):
    from pdf2dxf_stable import core
    from pdf2dxf_stable.supervision import ProcessOutcome

    commands = []

    def limited(command, **kwargs):
        commands.append(command)
        assert kwargs["memory_mb"] == 256
        assert kwargs["timeout"] == 30
        return ProcessOutcome(-9, "MEMORY_LIMIT", 300 * 1024**2, 0.1)

    monkeypatch.setattr(core, "run_supervised", limited)
    result = Converter().convert(
        tmp_path / "input.pdf",
        tmp_path / "output.dxf",
        ConversionRequest(memory_limit_mb=256, timeout_seconds=30),
    )
    assert len(commands) == 1 and "pdf2dxf_stable.preflight" in commands[0]
    report = json.loads(Path(result.report_path).read_text())
    assert result.status == "failed" and not result.pages
    assert report["input_validation"]["resources"]["reason"] == "MEMORY_LIMIT"


def test_successful_conversion_records_preflight_evidence(tmp_path):
    source = tmp_path / "source.pdf"
    with fitz.open() as doc:
        doc.new_page().draw_line((10, 10), (30, 30))
        doc.save(source)
    result = Converter().convert(source, tmp_path / "result.dxf", ConversionRequest())
    report = json.loads(Path(result.report_path).read_text())
    assert report["input_validation"]["repair"]["repaired"] is False
    assert report["input_validation"]["selected_pages"] == [0]
    assert report["input_validation"]["resources"]["returncode"] == 0


def test_cli_json_preserves_chinese_with_redirected_legacy_encoding(tmp_path):
    import os
    import sys

    source = tmp_path / "中文图纸.pdf"
    destination = tmp_path / "检查结果.json"
    with fitz.open() as doc:
        doc.new_page()
        doc.save(source)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pdf2dxf_stable.cli",
            "inspect",
            str(source),
            "--json",
            str(destination),
        ],
        env=dict(os.environ, PYTHONIOENCODING="cp1252"),
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr.decode(
        "ascii", errors="backslashreplace"
    )
    assert json.loads(result.stdout)["path"] == str(source)
    assert json.loads(destination.read_text(encoding="utf-8"))["path"] == str(source)
