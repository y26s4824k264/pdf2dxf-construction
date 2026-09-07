"""Revalidate a published DXF with its page request and conversion evidence."""

import json
import re
from pathlib import Path

from .determinism import sha256
from .request import ConversionRequest
from .validation import validate_dxf


def _name(value):
    return Path(str(value).replace("\\", "/")).name


def _report_path(path):
    stem = path.stem.removesuffix(".r12")
    candidates = [
        path.with_suffix(".report.json"),
        path.with_name(stem + ".report.json"),
    ]
    candidates.append(path.with_name(re.sub(r"_p\d+$", "", stem) + ".report.json"))
    return next((p for p in candidates if p.is_file()), None)


def validate_saved_output(path, *, profile="universal", report_path=None):
    path = Path(path)
    report = Path(report_path) if report_path is not None else _report_path(path)
    backend, request, expected, problem = None, None, None, None
    if report is not None:
        try:
            data = json.loads(report.read_text(encoding="utf-8"))
            artifacts = [
                a
                for a in data["artifacts"]
                if a.get("kind") == "dxf" and _name(a.get("path")) == path.name
            ]
            pages = [
                page
                for page in data["pages"]
                if any(
                    _name(page.get(key, {}).get("path")) == path.name
                    for key in ("universal_validation", "r12_validation")
                    if isinstance(page.get(key), dict)
                )
            ]
            if len(artifacts) != 1 or len(pages) != 1:
                raise ValueError(
                    "report must identify exactly one matching DXF and page"
                )
            expected = artifacts[0].get("sha256")
            if not isinstance(expected, str) or not re.fullmatch(
                r"[0-9a-f]{64}", expected
            ):
                raise ValueError("report is missing the output SHA256")
            backend = pages[0].get("backend", {})
            if "request" in pages[0]:
                request = ConversionRequest.model_validate(pages[0]["request"])
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            backend, request = None, None
            problem = {"code": "CONVERSION_REPORT_INVALID", "message": str(exc)}
    result = validate_dxf(
        path,
        profile=profile,
        backend_payload=backend,
        request=request,
        dimension_p95_limit=request.dimension_p95_limit
        if request is not None
        else 0.002,
        allow_paper_space=request is not None and request.mode == "sheet",
    )
    if report is not None:
        result["conversion_report"] = str(report)
        if problem is None:
            actual = sha256(path)
            result["artifact_sha256"] = actual
            if actual != expected:
                problem = {
                    "code": "ARTIFACT_HASH_MISMATCH",
                    "expected": expected,
                    "actual": actual,
                }
        if problem is not None:
            result["errors"].append(problem)
            result["valid"] = result["model_ready"] = False
    return result
