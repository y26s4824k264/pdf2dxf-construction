from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from pathlib import Path


def _find_backend():
    import pdf2dxf_stable.engine.pdf as module

    return module, module.convert_pdf_page


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("source")
    p.add_argument("--page", type=int, required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--result-json", required=True)
    p.add_argument("--mode", default="blocks")
    p.add_argument("--memory-limit-mb", type=int, default=2560)
    p.add_argument("--recover-path-text", action="store_true")
    p.add_argument("--request-json")
    a = p.parse_args(argv)
    from .request import ConversionRequest

    request = (
        ConversionRequest.model_validate_json(
            Path(a.request_json).read_text(encoding="utf-8")
        )
        if a.request_json
        else ConversionRequest(recover_pure_path_text=a.recover_path_text)
    )
    try:
        module, fn = _find_backend()
        kwargs = {
            "pdf_path": Path(a.source),
            "page_index": a.page,
            "output": Path(a.output),
            "mode": a.mode,
            "dimension_p95_limit": request.dimension_p95_limit,
            "recover_pure_path_text": a.recover_path_text,
            "path_text_policy": request.path_text_policy,
            "outline_chinese": request.outline_chinese,
            "outline_font_catalogs": [
                str(Path(value).expanduser().resolve())
                for value in request.outline_font_catalogs
            ],
            "allow_declared_scale": request.scale_mode == "declared",
            "keep_paper_dxf": True,
        }
        missing = []
        from .capabilities import glyph_capability

        capability = glyph_capability()
        if kwargs.get("recover_pure_path_text") and not capability["available"]:
            kwargs["recover_pure_path_text"] = False
            missing = capability["missing"]
        result = fn(**kwargs)
        if missing:
            result["path_text"] = {
                "status": "unavailable",
                "code": "GLYPH_ASSETS_MISSING",
                "missing": missing,
                "original_geometry_preserved": True,
            }

        payload = {
            "ok": True,
            "backend_module": module.__name__,
            "backend_function": fn.__name__,
            "result": result,
        }
        Path(a.result_json).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        return 0
    # This process boundary must serialize every backend failure for the parent.
    except Exception as exc:  # noqa: BLE001
        payload = {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        }
        Path(a.result_json).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return 3


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(int(code))
