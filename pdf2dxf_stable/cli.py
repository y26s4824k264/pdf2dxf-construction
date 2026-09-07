from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from zipfile import BadZipFile

from .core import Converter, _write_json
from .paths import protect_inputs, result_paths, same_path
from .request import ConversionRequest
from .saved_validation import validate_saved_output
from .version import __version__


def _pages(value):
    if value.strip().lower() in {"all", "*"}:
        return "all"
    out = set()
    if len(value) > 100_000:
        raise argparse.ArgumentTypeError("page selection is too long; use 'all'")
    for token in value.split(","):
        token = token.strip()
        if not re.fullmatch(r"[1-9][0-9]*(?:-[1-9][0-9]*)?", token):
            raise argparse.ArgumentTypeError(
                "pages must be positive numbers or ranges (1,3-5)"
            )
        if "-" in token:
            a, b = map(int, token.split("-", 1))
        else:
            a = b = int(token)
        if max(a, b) > 100_000 or len(out) + abs(b - a) + 1 > 100_000:
            raise argparse.ArgumentTypeError(
                "explicit pages are limited to 100000; use 'all'"
            )
        out.update(range(min(a, b), max(a, b) + 1))
    return sorted(out)


def _add_batch_conversion_options(parser):
    parser.add_argument(
        "--scale-mode",
        choices=("auto", "page", "manual", "declared"),
        default="auto",
    )
    parser.add_argument("--manual-scale", type=float)
    parser.add_argument(
        "--outline-chinese",
        choices=("off", "auto", "required"),
        default="off",
        help="recover audited outline glyphs from the persisted DXF; no OCR",
    )
    parser.add_argument(
        "--outline-font-catalog",
        action="append",
        default=[],
        help="persisted .p2dfont catalog; repeat for multiple font faces",
    )
    parser.add_argument("--no-path-text", action="store_true")
    parser.add_argument(
        "--path-text-policy", choices=("keep", "off_layer", "drop"), default="off_layer"
    )
    parser.add_argument("--no-strict-validation", action="store_true")
    parser.add_argument("--memory-limit-mb", type=int, default=2560)
    parser.add_argument("--temp-disk-limit-mb", type=int, default=20480)
    parser.add_argument("--timeout-seconds", type=int, default=1800)


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="pdf2dxf",
        description=f"PDF2DXF Construction v{__version__} stable interface",
    )
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="command", required=True)
    c = sub.add_parser("convert")
    c.add_argument("input")
    c.add_argument("-o", "--output", required=True)
    c.add_argument(
        "--profile", choices=("universal", "legacy-r12"), default="universal"
    )
    c.add_argument("--emit-r12", action="store_true")
    c.add_argument("--pages", type=_pages, default="all")
    c.add_argument("--mode", choices=("auto", "sheet", "blocks"), default="auto")
    c.add_argument("--workers", type=int, default=2)
    c.add_argument("--memory-limit-mb", type=int, default=2560)
    c.add_argument("--temp-disk-limit-mb", type=int, default=20480)
    c.add_argument("--timeout-seconds", type=int, default=1800)
    c.add_argument("--no-path-text", action="store_true")
    c.add_argument("--no-deterministic", action="store_true")
    c.add_argument("--allow-quality-degradation", action="store_true")
    c.add_argument("--json")
    c.add_argument("--units", choices=("auto", "mm", "cm", "m", "inch"), default="auto")
    c.add_argument(
        "--scale-mode",
        choices=("auto", "page", "manual", "declared"),
        default="auto",
    )
    c.add_argument("--manual-scale", type=float)
    c.add_argument(
        "--path-text-policy", choices=("keep", "off_layer", "drop"), default="off_layer"
    )
    c.add_argument(
        "--outline-chinese",
        choices=("off", "auto", "required"),
        default="off",
        help="recover audited outline glyphs from the persisted DXF; no OCR",
    )
    c.add_argument(
        "--outline-font-catalog",
        action="append",
        default=[],
        help="persisted .p2dfont catalog; repeat for multiple font faces",
    )
    c.add_argument("--no-strict-validation", action="store_true")
    v = sub.add_parser("validate")
    v.add_argument("dxf")
    v.add_argument(
        "--profile", choices=("universal", "legacy-r12"), default="universal"
    )
    v.add_argument("--json")
    v.add_argument(
        "--report", help="conversion report; defaults to the adjacent .report.json"
    )
    i = sub.add_parser("inspect")
    i.add_argument("input")
    i.add_argument("--json")
    b = sub.add_parser("batch")
    b.add_argument("source")
    b.add_argument("-o", "--output", required=True)
    b.add_argument(
        "--profile", choices=("universal", "legacy-r12"), default="universal"
    )
    b.add_argument("--emit-r12", action="store_true")
    b.add_argument("--workers", type=int, default=2)
    b.add_argument("--allow-quality-degradation", action="store_true")
    _add_batch_conversion_options(b)
    b.add_argument("--json")
    r = sub.add_parser("regress")
    r.add_argument("source")
    r.add_argument("-o", "--output", required=True)
    r.add_argument(
        "--profile", choices=("universal", "legacy-r12"), default="universal"
    )
    r.add_argument("--emit-r12", action="store_true")
    r.add_argument("--workers", type=int, default=2)
    _add_batch_conversion_options(r)
    r.add_argument("--json")
    font_catalog = sub.add_parser(
        "font-catalog",
        help="build persisted full-Unicode outline templates from a font",
    )
    font_commands = font_catalog.add_subparsers(
        dest="font_catalog_command", required=True
    )
    font_faces = font_commands.add_parser("faces")
    font_faces.add_argument("font")
    font_faces.add_argument("--json")
    font_build = font_commands.add_parser("build")
    font_build.add_argument("font")
    font_build.add_argument("-o", "--output", required=True)
    font_build.add_argument("--face-index", type=int, default=0)
    font_build.add_argument("--charset", choices=("chinese", "all"), default="chinese")
    font_build.add_argument("--json")
    font_inspect = font_commands.add_parser("inspect")
    font_inspect.add_argument("catalog")
    font_inspect.add_argument("--json")
    a = p.parse_args(argv)
    from .engine.text.font_catalog import FontCatalogError
    from fontTools.ttLib import TTLibError

    try:
        return _execute(a)
    except KeyboardInterrupt:
        print("pdf2dxf: cancelled", file=sys.stderr)
        return 130
    except (ValueError, OSError, BadZipFile, FontCatalogError, TTLibError) as exc:
        p.error(str(exc))


def _execute(a):
    if getattr(a, "json", None):
        protected = [
            getattr(a, key, None) for key in ("input", "source", "dxf", "report")
        ]
        protected.extend(getattr(a, "outline_font_catalog", ()))
        if a.command == "convert":
            protected.append(a.output)
        elif a.command == "font-catalog":
            protected.extend(
                getattr(a, key, None) for key in ("font", "catalog", "output")
            )
        protect_inputs(a.json, protected)
    if a.command == "font-catalog":
        from .engine.text.font_catalog import (
            build_font_catalog,
            inspect_font_catalog,
            list_font_faces,
        )

        if a.font_catalog_command == "faces":
            o = {"font": str(Path(a.font)), "faces": list_font_faces(a.font)}
        elif a.font_catalog_command == "build":
            o = build_font_catalog(
                a.font,
                a.output,
                face_index=a.face_index,
                charset=a.charset,
            )
        else:
            o = inspect_font_catalog(a.catalog)
        code = 0
    elif a.command in {"batch", "regress"}:
        from .batch import run_batch, run_regression

        req = ConversionRequest(
            profile=a.profile,
            emit_r12=a.emit_r12,
            workers=a.workers,
            scale_mode=a.scale_mode,
            manual_scale=a.manual_scale,
            outline_chinese=a.outline_chinese,
            outline_font_catalogs=a.outline_font_catalog,
            recover_pure_path_text=not a.no_path_text,
            path_text_policy=a.path_text_policy,
            strict_validation=not a.no_strict_validation,
            memory_limit_mb=a.memory_limit_mb,
            temp_disk_limit_mb=a.temp_disk_limit_mb,
            timeout_seconds=a.timeout_seconds,
        )
        o = (
            run_batch(a.source, a.output, req)
            if a.command == "batch"
            else run_regression(a.source, a.output, req)
        )
        code = 0 if int(o.get("failed", 0)) == 0 else 5
        if code == 0 and int(o.get("degraded", 0)):
            code = 2 if a.allow_quality_degradation else 5
    elif a.command == "inspect":
        import fitz

        with fitz.open(a.input) as d:
            if not d.is_pdf:
                raise ValueError("NOT_PDF: input is not a PDF document")
            if d.needs_pass:
                raise ValueError("PASSWORD_REQUIRED: unlock the PDF before inspection")
            o = {
                "path": str(Path(a.input)),
                "page_count": d.page_count,
                "pages": [
                    {
                        "page": n + 1,
                        "width_pt": d[n].rect.width,
                        "height_pt": d[n].rect.height,
                        "rotation": d[n].rotation,
                    }
                    for n in range(d.page_count)
                ],
            }
        code = 0
    elif a.command == "validate":
        o = validate_saved_output(a.dxf, profile=a.profile, report_path=a.report)
        code = 0 if o["valid"] and not o["warnings"] else 5
    else:
        req = ConversionRequest(
            units=a.units,
            scale_mode=a.scale_mode,
            manual_scale=a.manual_scale,
            path_text_policy=a.path_text_policy,
            outline_chinese=a.outline_chinese,
            outline_font_catalogs=a.outline_font_catalog,
            strict_validation=not a.no_strict_validation,
            profile=a.profile,
            emit_r12=a.emit_r12,
            pages=a.pages,
            mode=a.mode,
            workers=a.workers,
            memory_limit_mb=a.memory_limit_mb,
            temp_disk_limit_mb=a.temp_disk_limit_mb,
            timeout_seconds=a.timeout_seconds,
            recover_pure_path_text=not a.no_path_text,
            deterministic=not a.no_deterministic,
        )
        result = Converter().convert(a.input, a.output, req)
        o = result.to_dict()
        code = (
            0
            if result.status == "ok"
            else (
                2 if result.status == "degraded" and a.allow_quality_degradation else 5
            )
        )
    own_report = bool(
        a.command == "convert"
        and a.json
        and o.get("report_path")
        and same_path(a.json, o["report_path"])
    )
    if a.json and not own_report:
        protect_inputs(a.json, result_paths(o))
    text = json.dumps(o, ensure_ascii=False, indent=2)
    print(text)
    if getattr(a, "json", None):
        dest = Path(a.json).expanduser().resolve()
        # Converter already wrote this report without its own hash. Rewriting
        # the returned result here would create a stale self-referential hash.
        if not own_report:
            dest.parent.mkdir(parents=True, exist_ok=True)
            _write_json(dest, o)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
