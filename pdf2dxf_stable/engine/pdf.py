"""PDF page extraction followed by persisted-DXF text and scale analysis."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


def convert_pdf_page(
    pdf_path: str | Path,
    page_index: int,
    output: str | Path,
    *,
    mode: str = "blocks",
    recover_pure_path_text: bool = True,
    dimension_p95_limit: float = 0.002,
    path_text_policy: str = "off_layer",
    outline_chinese: str = "off",
    outline_font_catalogs: tuple[str | Path, ...] | list[str | Path] = (),
    allow_declared_scale: bool = False,
    keep_paper_dxf: bool = True,
) -> dict[str, Any]:
    pdf_path = Path(pdf_path)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    assets = output.parent / f"{output.stem}_assets_v20"
    assets.mkdir(parents=True, exist_ok=True)
    paper_dxf = assets / f"{pdf_path.stem}_p{page_index + 1:03d}_paper_mm_v20.dxf"
    base_json = assets / f"{pdf_path.stem}_p{page_index + 1:03d}_base_worker_v20.json"
    env = dict(os.environ)

    base_cmd = [
        sys.executable,
        "-m",
        "pdf2dxf_stable.engine.worker",
        "base",
        str(pdf_path),
        "--page",
        str(page_index),
        "--output-dxf",
        str(paper_dxf),
        "--result-json",
        str(base_json),
    ]
    base_log = assets / f"{pdf_path.stem}_p{page_index + 1:03d}_base_worker_v20.log"
    with base_log.open("w", encoding="utf-8") as stream:
        proc = subprocess.run(
            base_cmd,
            stdout=subprocess.DEVNULL,
            stderr=stream,
            text=True,
            env=env,
            check=False,
        )
    if proc.returncode != 0:
        raise RuntimeError(
            base_log.read_text(encoding="utf-8", errors="replace")[-4000:]
        )

    if outline_chinese == "off":
        from pdf2dxf_stable.engine.text.outline_text import recover_outline_text

        outline_report = recover_outline_text(
            paper_dxf, page_index, mode="off", policy=path_text_policy
        )
    else:
        outline_json = (
            assets / f"{pdf_path.stem}_p{page_index + 1:03d}_outline_text.json"
        )
        outline_log = (
            assets / f"{pdf_path.stem}_p{page_index + 1:03d}_outline_text.log"
        )
        outline_cmd = [
            sys.executable,
            "-m",
            "pdf2dxf_stable.engine.worker",
            "outline-text",
            str(paper_dxf),
            "--page",
            str(page_index),
            "--result-json",
            str(outline_json),
            "--mode",
            outline_chinese,
            "--original-policy",
            path_text_policy,
        ]
        for catalog_path in outline_font_catalogs:
            outline_cmd.extend(("--font-catalog", str(catalog_path)))
        with outline_log.open("w", encoding="utf-8") as stream:
            proc = subprocess.run(
                outline_cmd,
                stdout=subprocess.DEVNULL,
                stderr=stream,
                text=True,
                env=env,
                check=False,
            )
        if proc.returncode != 0 or not outline_json.is_file():
            raise RuntimeError(
                "OUTLINE_CHINESE_WORKER_FAILED: "
                + outline_log.read_text(encoding="utf-8", errors="replace")[-4000:]
            )
        outline_report = json.loads(outline_json.read_text(encoding="utf-8"))

    from pdf2dxf_stable.engine.calibration.evidence import calibrate_paper_dxf

    evidence = calibrate_paper_dxf(
        paper_dxf,
        output,
        mode=mode,
        recover=recover_pure_path_text,
        policy=path_text_policy,
        limit=dimension_p95_limit,
        allow_declared_scale=allow_declared_scale,
    )
    payload = {
        "schema": "pdf2dxf.dxf_calibration.v1",
        "source_pdf": str(pdf_path),
        "page_index": page_index,
        "paper_dxf": str(paper_dxf),
        "output_dxf": str(output),
        "base_worker": json.loads(base_json.read_text(encoding="utf-8")),
        "path_text": evidence.pop("path_text"),
        "outline_chinese": outline_report,
        "dimension_evidence": evidence,
        "paper_mm_preserved": not evidence["applied"],
        "coverage_gate": {"model_output": evidence["applied"], "silent_drop_count": 0},
        "manifest": str(output.with_suffix(".evidence.json")),
    }
    Path(payload["manifest"]).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if not keep_paper_dxf:
        paper_dxf.unlink()
    return payload
