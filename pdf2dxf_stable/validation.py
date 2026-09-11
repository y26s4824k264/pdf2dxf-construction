from __future__ import annotations

import itertools
import math
import re
import statistics
from pathlib import Path

import ezdxf

from .dimension_instances import collect_dimensions
from .options import output_unit_info

_NUM = re.compile(r"[-+]?\d+(?:\.\d+)?")


def _walk_values(obj, key):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == key:
                yield v
            yield from _walk_values(v, key)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_values(v, key)


def _dimension_errors(doc, instances):
    mm_per_unit = output_unit_info(doc)[1]
    out, errors = [], []
    for instance in instances:
        e = instance.entity
        try:
            m = _NUM.findall(str(e.dxf.text))
            if not m and e.has_xdata("PDF2DXF20"):
                tags = list(e.get_xdata("PDF2DXF20"))
                for index, (code, value) in enumerate(tags):
                    if (
                        code == 1000
                        and value == "associative_short_dimension_dimlfac_v20"
                    ):
                        m = [str(tags[index + 1][1])]
                        break
            if not m:
                continue
            label = abs(float(m[0]))
            if label == 0:
                continue
            # Angular measurements are degrees, independent of INSUNITS.
            factor = 1.0 if e.dimtype in (2, 5) else mm_per_unit
            measurement = abs(float(instance.measurement())) * factor
            if not math.isfinite(label) or not math.isfinite(measurement):
                raise ValueError("non-finite dimension measurement or label")
            out.append(abs(measurement - label) / label)
        except (TypeError, ValueError, ArithmeticError, IndexError) as exc:
            errors.append(
                {
                    "code": "DIMENSION_MEASUREMENT_INVALID",
                    "handle": e.dxf.handle,
                    "insert_handles": instance.insert_handles,
                    "message": str(exc),
                }
            )
    return out, errors


def _p95(values):
    if not values:
        return None
    s = sorted(values)
    return s[min(len(s) - 1, max(0, math.ceil(0.95 * len(s)) - 1))]


def _confirmed_dimension_evidence(evidence, limit):
    """Recompute the calibration gate from anchors, not cached pass flags."""
    try:
        scale = float(evidence["scale"])
        if not math.isfinite(scale) or scale <= 0:
            return False
        anchors = {a["id"]: a for a in evidence["anchors"]}
        if len(anchors) != len(evidence["anchors"]):
            return False
        checked = [a for a in anchors.values() if a.get("role") in ("fit", "holdout")]
        for role in ("fit", "holdout"):
            rows = [a for a in checked if a["role"] == role]
            if {a["axis"] for a in rows} != {"x", "y"}:
                return False
            residuals = []
            for a in rows:
                axis = 0 if a["axis"] == "x" else 1
                length = a["p1"][axis] - a["p0"][axis]
                if (
                    length <= 0
                    or a["label_mm"] <= 0
                    or not math.isclose(length, a["paper_length_mm"], abs_tol=1e-7)
                ):
                    return False
                residuals.append(abs(length * scale / a["label_mm"] - 1))
            if not all(math.isfinite(v) for v in residuals) or _p95(residuals) > limit:
                return False
        for i, a in enumerate(checked):
            axis = 0 if a["axis"] == "x" else 1
            for b in checked[i + 1 :]:
                if a["axis"] == b["axis"] and all(
                    abs(a[k][axis] - b[k][axis]) <= 0.025 for k in ("p0", "p1")
                ):
                    return False
        axis_scales = {}
        for axis in ("x", "y"):
            rows = [a for a in checked if a["axis"] == axis]
            if len(rows) < 3:
                return False
            fit = [a for a in rows if a["role"] == "fit"]
            axis_scales[axis] = sum(
                a["paper_length_mm"] * a["label_mm"] for a in fit
            ) / sum(a["paper_length_mm"] ** 2 for a in fit)
        if abs(axis_scales["x"] / axis_scales["y"] - 1) > limit:
            return False
        from pdf2dxf_stable.engine.calibration.chains import find_chains

        # Rebuild local geometric solutions, including competing branches. Cached
        # "passed" flags and sums cannot establish spatial chain membership.
        rebuilt = find_chains(
            [
                a
                for a in anchors.values()
                if a["label_mm"] > 0
                and abs(a["paper_length_mm"] * scale / a["label_mm"] - 1) <= 0.02
            ]
        )
        signatures = {(c["total"], tuple(c["parts"])) for c in rebuilt if c["passed"]}
        for chain in evidence["chains"]:
            if (chain["total"], tuple(chain["parts"])) not in signatures:
                continue
            total = anchors[chain["total"]]
            keys = chain["parts"]
            if len(keys) < 2 or len(set(keys)) != len(keys) or total["id"] in keys:
                continue
            parts = [anchors[key] for key in keys]
            axis = 0 if total["axis"] == "x" else 1
            if any(p["axis"] != total["axis"] for p in parts):
                continue
            ends = [
                (total["p0"][axis], parts[0]["p0"][axis]),
                (parts[-1]["p1"][axis], total["p1"][axis]),
            ]
            ends.extend(
                (a["p1"][axis], b["p0"][axis]) for a, b in itertools.pairwise(parts)
            )
            if (
                all(abs(a - b) < 0.07 for a, b in ends)
                and total["label_mm"] > 0
                and all(
                    p["label_mm"] > 0 and p["p1"][axis] > p["p0"][axis] for p in parts
                )
                and abs(sum(p["label_mm"] for p in parts) / total["label_mm"] - 1)
                <= 0.002
            ):
                return True
    except (KeyError, TypeError, ValueError, ZeroDivisionError, IndexError):
        pass
    return False


def _calibration_entity_errors(doc, evidence, instances):
    """Every recorded output dimension must survive and retain its endpoints."""
    mm_per_unit = output_unit_info(doc)[1]
    errors = []
    by_handle = {}
    for instance in instances:
        by_handle.setdefault(instance.entity.dxf.handle, []).append(instance)
    for a in evidence.get("anchors", []):
        handle = a.get("output_dimension_handle")
        if not handle:
            continue
        placements = by_handle.get(handle, [])
        if not placements:
            errors.append(
                {
                    "code": "CALIBRATION_DIMENSION_MISSING",
                    "handle": handle,
                    "anchor": a["id"],
                }
            )
            continue
        if len(placements) != 1:
            errors.append(
                {
                    "code": "CALIBRATION_DIMENSION_MULTIPLE_PLACEMENTS",
                    "handle": handle,
                    "anchor": a["id"],
                    "count": len(placements),
                }
            )
            continue
        instance = placements[0]
        entity = instance.entity
        try:
            label_matches = float(entity.dxf.text) == a["label_mm"]
        except (TypeError, ValueError):
            label_matches = False
        if not label_matches:
            errors.append(
                {
                    "code": "CALIBRATION_LABEL_MISMATCH",
                    "handle": handle,
                    "anchor": a["id"],
                }
            )
        for key, point in (("p0", entity.dxf.defpoint2), ("p1", entity.dxf.defpoint3)):
            point = instance.matrix.transform(point)
            if any(
                not math.isclose(
                    point[i] * mm_per_unit,
                    (a[key][i] if i < len(a[key]) else 0) * evidence["scale"],
                    rel_tol=1e-9,
                    abs_tol=1e-5,
                )
                for i in (0, 1, 2)
            ):
                errors.append(
                    {
                        "code": "CALIBRATION_GEOMETRY_MISMATCH",
                        "handle": handle,
                        "anchor": a["id"],
                        "insert_handles": instance.insert_handles,
                    }
                )
                break
    return errors


def validate_dxf(
    path,
    *,
    profile,
    backend_payload=None,
    dimension_p95_limit=0.002,
    allow_paper_space=False,
    request=None,
):
    if not math.isfinite(dimension_p95_limit) or dimension_p95_limit <= 0:
        raise ValueError("dimension_p95_limit must be finite and positive")
    path = Path(path)
    doc = ezdxf.readfile(path)
    evidence_rows = [
        value
        for value in _walk_values(backend_payload or {}, "dimension_evidence")
        if isinstance(value, dict) and value.get("applied") is True
    ]
    source_handles = {
        handle
        for evidence in evidence_rows
        for handle in evidence.get("source_entities", {})
    }
    instances, source_instances, errors = collect_dimensions(doc, source_handles)
    if not any(doc.modelspace()):
        errors.append({"code": "MODELSPACE_EMPTY"})
    audit = doc.audit()
    warnings = []
    expected = "AC1021" if profile == "universal" else "AC1009"
    if doc.dxfversion != expected:
        errors.append(
            {
                "code": "DXF_VERSION_MISMATCH",
                "expected": expected,
                "actual": doc.dxfversion,
            }
        )
    paper_requested = request is not None and (
        request.scale_mode == "page"
        or (request.mode == "sheet" and request.scale_mode == "auto")
    )
    dims, measurement_errors = (
        ([], []) if paper_requested else _dimension_errors(doc, instances)
    )
    errors.extend(measurement_errors)
    p95 = _p95(dims)
    if p95 is not None and p95 > dimension_p95_limit:
        errors.append(
            {
                "code": "DIMENSION_P95_EXCEEDED",
                "actual": p95,
                "limit": dimension_p95_limit,
            }
        )
    if audit.errors:
        errors.append({"code": "EZDXF_AUDIT_ERRORS", "count": len(audit.errors)})
    if profile == "universal":
        for evidence in evidence_rows:
            if (
                isinstance(evidence, dict)
                and evidence.get("applied") is True
                and _confirmed_dimension_evidence(evidence, dimension_p95_limit)
            ):
                errors.extend(_calibration_entity_errors(doc, evidence, instances))
                from .engine.calibration.source_entities import check_sources

                errors.extend(
                    check_sources(source_instances, evidence, output_unit_info(doc)[1])
                )
    fatal = sum(
        int(v or 0)
        for v in _walk_values(backend_payload or {}, "fatal_failure_count")
        if isinstance(v, (int, float))
    )
    silent = sum(
        int(v or 0)
        for v in _walk_values(backend_payload or {}, "silent_drop_count")
        if isinstance(v, (int, float))
    )
    fallback_dimensions = 0
    if fatal:
        for entity in doc.entitydb.values():
            for appid in ("PDF2DXF20", "PDF2DXF18", "PDF2DXF19"):
                try:
                    tags = entity.get_xdata(appid)
                    if any(
                        int(code) == 1000 and "dimension_editable_" in str(value)
                        for code, value in tags
                    ):
                        fallback_dimensions += 1
                        break
                except ezdxf.DXFValueError:
                    continue
    if fatal and fallback_dimensions < fatal:
        errors.append(
            {
                "code": "FATAL_TRANSFORM_FAILURE",
                "count": fatal,
                "resolved_fallbacks": fallback_dimensions,
            }
        )
    elif fatal:
        warnings.append(
            {
                "code": "DIMENSION_TRANSFORM_DEGRADED_BUT_PRESERVED",
                "count": fatal,
                "fallback_entities": fallback_dimensions,
            }
        )
    if silent:
        errors.append({"code": "SILENT_DROP", "count": silent})

    # Detect an explicit model-space refusal, not merely a paper_dxf artifact path.
    def _detect_paper_fallback(value):
        if isinstance(value, dict):
            schema = str(value.get("schema", "")).lower()
            reason = str(value.get("reason", "")).lower()
            if (
                "paper_fallback" in schema
                or value.get("paper_mm_preserved") is True
                or value.get("model_output") is False
            ):
                return True
            if ("skipped" in schema and ("sheet mode" not in reason)) or any(
                t in reason
                for t in (
                    "no accepted",
                    "paper-mm fallback",
                    "paper_mm fallback",
                    "scale refused",
                    "refuse_multi",
                )
            ):
                return True
            if (
                value.get("paper_space_fallback") is True
                or value.get("model_space_generated") is False
            ):
                return True
            views = value.get("viewports")
            outputs = (
                value.get("outputs") if isinstance(value.get("outputs"), dict) else {}
            )
            model_output = bool(
                outputs.get("blocks")
                or outputs.get("split")
                or outputs.get("model_dxf")
            )
            if (
                isinstance(views, list)
                and views
                and not model_output
                and not any(
                    str(v.get("status", "")).lower() == "accepted"
                    for v in views
                    if isinstance(v, dict)
                )
            ):
                return True
            return any(_detect_paper_fallback(v) for v in value.values())
        if isinstance(value, list):
            return any(_detect_paper_fallback(v) for v in value)
        return False

    paper_fallback = _detect_paper_fallback(backend_payload or {})

    strict = request.strict_validation if request is not None else True
    manual = request is not None and request.scale_mode == "manual"
    intentional_paper = allow_paper_space or (
        request is not None and request.scale_mode == "page"
    )

    def confirmed_calibration(value):
        if isinstance(value, dict):
            evidence = value.get("dimension_evidence")
            if (
                isinstance(evidence, dict)
                and evidence.get("status") == "confirmed"
                and evidence.get("applied") is True
            ):
                return _confirmed_dimension_evidence(evidence, dimension_p95_limit)
            return any(confirmed_calibration(v) for v in value.values())
        if isinstance(value, list):
            return any(confirmed_calibration(v) for v in value)
        return False

    calibrated = not paper_fallback and confirmed_calibration(backend_payload or {})

    def declared_approximation(value):
        if isinstance(value, dict):
            evidence = value.get("dimension_evidence")
            if (
                isinstance(evidence, dict)
                and evidence.get("status") == "declared_approximate"
                and evidence.get("applied") is True
                and evidence.get("scale_source") == "single_title_scale"
            ):
                return True
            return any(declared_approximation(item) for item in value.values())
        if isinstance(value, list):
            return any(declared_approximation(item) for item in value)
        return False

    approximate = not paper_fallback and declared_approximation(backend_payload or {})
    geometry_valid = not errors
    scale_status = (
        "user_confirmed"
        if manual
        else (
            "paper"
            if intentional_paper
            else (
                "calibrated"
                if calibrated
                else ("declared_approximate" if approximate else "unknown")
            )
        )
    )
    scale_confirmed = scale_status in ("user_confirmed", "calibrated")
    if approximate:
        warnings.append(
            {
                "code": "ENGINEERING_SCALE_APPROXIMATE",
                "reason": "uniform scale comes from one detected title ratio and requires review",
            }
        )
    elif not scale_confirmed:
        issue = {
            "code": "PAPER_SPACE_OUTPUT"
            if intentional_paper
            else "ENGINEERING_SCALE_UNCONFIRMED"
        }
        (warnings if intentional_paper or not strict else errors).append(issue)
    if not dims:
        warnings.append(
            {
                "code": "DIMENSION_VALIDATION_UNAVAILABLE",
                "reason": "no independently checkable dimension labels",
            }
        )
    if profile == "legacy-r12":
        warnings.append({"code": "R12_COMPATIBILITY_OUTPUT_REQUIRES_REVIEW"})
    missing_images = []
    for image in doc.objects.query("IMAGEDEF"):
        resource = Path(str(image.dxf.filename).replace("\\", "/"))
        if not resource.is_absolute():
            resource = path.parent / resource
        if not resource.is_file():
            missing_images.append(str(image.dxf.filename))
    if missing_images:
        errors.append({"code": "IMAGE_RESOURCE_MISSING", "filenames": missing_images})
        geometry_valid = False
    backend = backend_payload or {}
    for value in _walk_values(backend, "path_text"):
        if isinstance(value, dict) and (
            value.get("error") or value.get("status") == "unavailable"
        ):
            warnings.append({"code": "PATH_TEXT_UNAVAILABLE", "detail": value})
    for value in _walk_values(backend, "outline_chinese"):
        if isinstance(value, dict) and value.get("status") == "unavailable":
            warnings.append(
                {"code": "OUTLINE_CHINESE_CATALOG_UNAVAILABLE", "detail": value}
            )
    seen_backend_warnings = set()
    for value in _walk_values(backend, "warnings"):
        if value:
            marker = repr(value)
            if marker in seen_backend_warnings:
                continue
            seen_backend_warnings.add(marker)
            warnings.append({"code": "BACKEND_WARNINGS", "detail": value})
            if any(
                token in str(value).lower()
                for token in (
                    "image extract failed",
                    "image mask rendering failed",
                    "image placement failed",
                    "image clipping failed",
                    "image soft mask enumeration failed",
                    "raster fallback failed",
                    "shading render failed",
                )
            ):
                errors.append({"code": "SOURCE_GRAPHICS_INCOMPLETE", "detail": value})
                geometry_valid = False
    if audit.fixes:
        warnings.append({"code": "EZDXF_AUDIT_FIXES", "count": len(audit.fixes)})
    return {
        "schema": "pdf2dxf.stable.validation.v2",
        "path": str(path),
        "profile": profile,
        "acadver": doc.dxfversion,
        "audit_errors": len(audit.errors),
        "audit_fixes": len(audit.fixes),
        "dimension_count_checked": len(dims),
        "dimension_validation_status": "checked" if dims else "unavailable",
        "dimension_relative_error_median": statistics.median(dims) if dims else None,
        "dimension_relative_error_p95": p95,
        "fatal_failure_count": fatal,
        "resolved_dimension_fallbacks": fallback_dimensions,
        "silent_drop_count": silent,
        "paper_space_fallback": paper_fallback,
        "geometry_valid": geometry_valid,
        "scale_status": scale_status,
        "engineering_scale_confirmed": scale_confirmed,
        "model_ready": geometry_valid
        and scale_confirmed
        and not errors
        and (manual or bool(dims))
        and profile == "universal",
        "output_units": output_unit_info(doc)[0],
        "source_mapping": "backend source/page provenance retained; entity XDATA retained where supplied",
        "errors": errors,
        "warnings": warnings,
        "valid": not errors,
    }
