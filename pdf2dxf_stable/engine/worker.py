"""Short-lived worker stages for base conversion and persisted-DXF text recovery."""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import fitz

from pdf2dxf_stable.engine.pipeline import ConstructionPDF2DXFV15, PipelineConfigV15


def run_base(
    pdf_path: Path, page_index: int, output_dxf: Path, result_json: Path
) -> dict:
    started = time.perf_counter()
    pdf = fitz.open(pdf_path)
    try:
        result = ConstructionPDF2DXFV15(
            PipelineConfigV15(
                output_units="paper_mm",
                layer_mode="preserve",
                compact_dense_patterns=True,
            )
        ).convert_page(pdf, page_index, output_dxf, output_dxf.with_suffix(".v15.json"))
    finally:
        pdf.close()
    payload = result.to_dict()
    payload["isolated_stage"] = "base_conversion"
    payload["worker_elapsed_seconds"] = time.perf_counter() - started
    result_json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return payload


def run_outline_text(
    dxf_path: Path,
    page_index: int,
    result_json: Path,
    *,
    mode: str,
    original_policy: str,
    font_catalog_paths: tuple[str, ...] | list[str] = (),
) -> dict:
    started = time.perf_counter()
    from pdf2dxf_stable.engine.text.outline_text import recover_outline_text

    payload = recover_outline_text(
        dxf_path,
        page_index,
        mode=mode,
        policy=original_policy,
        font_catalog_paths=font_catalog_paths,
    )
    payload["isolated_stage"] = "persisted_dxf_outline_text"
    payload["worker_elapsed_seconds"] = time.perf_counter() - started
    result_json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Internal PDF2DXF worker")
    subparsers = parser.add_subparsers(dest="stage", required=True)

    base = subparsers.add_parser("base")
    base.add_argument("pdf")
    base.add_argument("--page", type=int, required=True)
    base.add_argument("--output-dxf", required=True)
    base.add_argument("--result-json", required=True)

    outline = subparsers.add_parser("outline-text")
    outline.add_argument("dxf")
    outline.add_argument("--page", type=int, required=True)
    outline.add_argument("--result-json", required=True)
    outline.add_argument("--mode", choices=("auto", "required"), required=True)
    outline.add_argument(
        "--original-policy",
        choices=("keep", "off_layer", "drop"),
        default="off_layer",
    )
    outline.add_argument("--font-catalog", action="append", default=[])

    args = parser.parse_args(argv)
    if args.stage == "base":
        payload = run_base(
            Path(args.pdf),
            args.page,
            Path(args.output_dxf),
            Path(args.result_json),
        )
    else:
        payload = run_outline_text(
            Path(args.dxf),
            args.page,
            Path(args.result_json),
            mode=args.mode,
            original_policy=args.original_policy,
            font_catalog_paths=args.font_catalog,
        )
    # Logs can be redirected to a legacy Windows code page. The UTF-8 JSON
    # artifact above retains readable Unicode; escaped log JSON is lossless.
    print(json.dumps(payload, ensure_ascii=True), flush=True)
    return 0


if __name__ == "__main__":
    os._exit(int(main()))
