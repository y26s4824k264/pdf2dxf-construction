"""Dimension-label/extension-line evidence and conservative paper-mm calibration."""

import itertools
import math
import re
import statistics
from collections import defaultdict
from pathlib import Path

import numpy as np
from shapely.geometry import LineString, box
from shapely.strtree import STRtree

from pdf2dxf_stable.engine.calibration.chains import find_chains as _chains
from pdf2dxf_stable.engine.text.dxf_text import _rotate, entity_paths, read_tokens

NUMBER = re.compile(
    r"^((?:0|[1-9]\d{0,5})(?:\.\d+)?|\.\d+)\s*(mm|cm|m)?$", re.IGNORECASE
)
SHEET_TEXT_MARKERS = ("目录", "做法表", "门窗表", "建筑设计说明")


def _sheet_text_marker(text):
    compact = re.sub(r"\s+", "", text)
    return next((marker for marker in SHEET_TEXT_MARKERS if marker in compact), None)


def _p95(values):
    return sorted(values)[max(0, math.ceil(0.95 * len(values)) - 1)] if values else None


class LineIndex:
    def __init__(self, doc):
        self.rows, shapes, self.markers = [], [], defaultdict(list)
        for e in doc.modelspace():
            if e.dxf.layer in (
                "PDF_PAGE",
                "PDF_OUTLINE_BACKUP",
                "PDF_TEXT_RECOVERED_NOOCR",
            ):
                continue
            paths = entity_paths(e)
            for path in paths:
                if len(path) == 3:
                    delta = np.ptp(path, axis=0)
                    axis = int(delta[1] > delta[0])
                    if delta[1 - axis] < 0.005 and 0.05 < delta[axis] < 4:
                        self.markers[axis].append((path[1], e.dxf.layer, e.dxf.handle))
                for a, b in itertools.pairwise(path):
                    delta = np.abs(b - a)
                    axis = int(delta[1] > delta[0])
                    if delta[axis] < 0.5 or delta[1 - axis] > 0.01:
                        continue
                    lo, hi = sorted((float(a[axis]), float(b[axis])))
                    cross = float((a[1 - axis] + b[1 - axis]) / 2)
                    self.rows.append(
                        {
                            "axis": axis,
                            "lo": lo,
                            "hi": hi,
                            "cross": cross,
                            "handle": e.dxf.handle,
                            "layer": e.dxf.layer,
                        }
                    )
                    shapes.append(LineString([a, b]))
        self.tree = STRtree(shapes)
        self.marker_trees = {}
        from shapely.geometry import Point

        for axis, markers in self.markers.items():
            self.marker_trees[axis] = STRtree([Point(row[0]) for row in markers])

    def query(self, bounds, axis):
        return [
            self.rows[int(i)]
            for i in self.tree.query(box(*bounds))
            if self.rows[int(i)]["axis"] == axis
        ]

    def endpoint(self, line, end, height):
        axis, cross = line["axis"], line["cross"]
        xy = [end, cross] if axis == 0 else [cross, end]
        bounds = [xy[0] - height, xy[1] - height, xy[0] + height, xy[1] + height]
        markers = []
        if axis in self.marker_trees:
            for i in self.marker_trees[axis].query(box(*bounds)):
                point, layer, handle = self.markers[axis][int(i)]
                if layer == line["layer"] and abs(point[1 - axis] - cross) < 0.025:
                    markers.append((point[axis], handle))
        candidates = []
        for other in self.query(bounds, 1 - axis):
            if (
                other["layer"] != line["layer"]
                or not other["lo"] + 0.01 < cross < other["hi"] - 0.01
            ):
                continue
            delta = abs(other["cross"] - end)
            marker = next(
                (h for x, h in markers if abs(x - other["cross"]) < 0.025), None
            )
            if marker or delta < 0.06 * height:
                candidates.append((0 if marker else 1, delta, other, marker))
        candidates.sort(key=lambda r: r[:2])
        if not candidates:
            return None
        best = candidates[0]
        if any(
            r[0] == best[0]
            and abs(r[1] - best[1]) < 0.03 * height
            and abs(r[2]["cross"] - best[2]["cross"]) > 0.04
            for r in candidates[1:]
        ):
            return None
        return best[2]["cross"], best[2]["handle"], best[3]


def bind_dimensions(doc, tokens):
    index = LineIndex(doc)
    anchors, rejected = [], []
    for token in tokens:
        match = NUMBER.fullmatch(token.text)
        if not match or (
            not match[2] and not re.fullmatch(r"[1-9]\d{1,5}(?:\.\d+)?", match[1])
        ):
            continue
        label = (
            float(match[1])
            * {None: 1, "mm": 1, "cm": 10, "m": 1000}[
                match[2].lower() if match[2] else None
            ]
        )
        if not math.isfinite(label) or label <= 0:
            continue
        # Unitless architectural dimensions are conventionally mm; retain this
        # convention explicitly. A conflicting sheet unit declaration vetoes auto.
        axis = (token.angle // 90) % 2
        x0, y0, x1, y1 = token.bbox
        local = _rotate(np.array([[x0, y0], [x1, y1]]), token.angle)
        low = local.min(0)
        center = (token.bbox[axis] + token.bbox[axis + 2]) / 2
        h = token.height
        bounds = [x0 - 2 * h, y0 - 2 * h, x1 + 2 * h, y1 + 2 * h]
        candidates = []
        for line in index.query(bounds, axis):
            cross = line["cross"] * (1, -1, -1, 1)[token.angle // 90]
            offset = low[1] - cross
            if not -0.1 * h <= offset <= 1.8 * h:
                continue
            if not line["lo"] - 0.5 * h < center < line["hi"] + 0.5 * h:
                continue
            ends = [index.endpoint(line, line[key], h) for key in ("lo", "hi")]
            if any(end is None for end in ends):
                continue
            a, b = sorted(ends)
            span = b[0] - a[0]
            if span < 0.5 or abs(center - (a[0] + b[0]) / 2) > max(
                0.7 * h, 0.08 * span
            ):
                continue
            ratio = label / span
            if not 0.01 <= ratio <= 10000:
                continue
            score = abs(offset) / h + abs(center - (a[0] + b[0]) / 2) / max(span, h)
            candidates.append((score, line, a, b, span, ratio))
        candidates.sort(key=lambda c: c[0])
        if not candidates:
            rejected.append(
                {
                    "text": token.text,
                    "handles": token.handles,
                    "reason": "no unambiguous dimension line and extension endpoints",
                }
            )
            continue
        best = candidates[0]
        if (
            len(candidates) > 1
            and candidates[1][0] - best[0] < 0.15
            and abs(candidates[1][-1] / best[-1] - 1) > 0.002
        ):
            rejected.append(
                {
                    "text": token.text,
                    "handles": token.handles,
                    "reason": "ambiguous dimension span",
                }
            )
            continue
        _, line, a, b, span, ratio = best
        p0, p1 = (
            ([a[0], line["cross"]], [b[0], line["cross"]])
            if axis == 0
            else ([line["cross"], a[0]], [line["cross"], b[0]])
        )
        anchors.append(
            {
                "id": f"dim-{len(anchors) + 1}",
                "text": token.text,
                "label_mm": label,
                "label_unit_source": "explicit"
                if match[2]
                else "architectural_mm_convention",
                "axis": "x" if axis == 0 else "y",
                "p0": p0,
                "p1": p1,
                "paper_length_mm": span,
                "observed_scale": ratio,
                "text_handles": token.handles,
                "dimension_line_handle": line["handle"],
                "dimension_layer": line["layer"],
                "extension_handles": [a[1], b[1]],
                "marker_handles": [a[2], b[2]],
                "text_method": token.method,
                "text_bbox": token.bbox,
                "text_height": h,
                "text_angle": token.angle,
                "template_distance": token.distance,
                "status": "candidate",
            }
        )
    # Native labels have precedence over any co-located recovered candidate.
    unique, conflicts = {}, set()
    for a in sorted(anchors, key=lambda a: a["text_method"] != "native_dxf_text"):
        key = (a["axis"], *(round(v, 2) for p in (a["p0"], a["p1"]) for v in p))
        if key in unique and unique[key]["label_mm"] != a["label_mm"]:
            if (
                unique[key]["text_method"] == "native_dxf_text"
                and a["text_method"] != "native_dxf_text"
            ):
                continue
            conflicts.add(key)
            rejected.append(
                {
                    "text": a["text"],
                    "handles": a["text_handles"],
                    "reason": "conflicting labels or reading orientations on the same span",
                }
            )
        unique.setdefault(key, a)
    for key in conflicts:
        unique.pop(key, None)
    return list(unique.values()), rejected


def analyze_dimensions(doc, *, recover=True, limit=0.002, spool_dir=None):
    if not math.isfinite(limit) or limit <= 0:
        raise ValueError("dimension limit must be finite and positive")
    tokens, text_stats = read_tokens(doc, recover, spool_dir=spool_dir)
    anchors, rejected = bind_dimensions(doc, tokens)
    sheet_text_markers = sorted(
        {
            marker
            for token in tokens
            if (marker := _sheet_text_marker(token.text)) is not None
        }
    )
    report = {
        "schema": "pdf2dxf.dimension_evidence.v1",
        "status": "unconfirmed",
        "anchors": anchors,
        "unbound_labels": rejected,
        "path_text": text_stats,
        "chains": [],
        "scale": None,
        "title_scales": sorted(
            {
                token.text.replace(" ", "")
                for token in tokens
                if re.fullmatch(r"1\s*:\s*[1-9]\d*(?:\.\d+)?", token.text)
            }
        ),
        "sheet_text_markers": sheet_text_markers,
        "reasons": [],
        "paper_mm_preserved": True,
        "model_output": False,
    }
    # Short spans amplify PDF coordinate rounding. They remain in the independent
    # output checks, but never determine the global conversion factor.
    report["minimum_fit_span_paper_mm"] = 15.0
    span_groups = []
    for a in sorted(
        anchors,
        key=lambda a: (
            a["text_method"] != "native_dxf_text",
            a["template_distance"],
            a["id"],
        ),
    ):
        if a["paper_length_mm"] < 15 or a["label_mm"] < 500:
            continue
        axis = 0 if a["axis"] == "x" else 1
        duplicate = next(
            (
                group
                for group in span_groups
                if group[0]["axis"] == a["axis"]
                and all(
                    abs(a[key][axis] - group[0][key][axis]) <= 0.025
                    for key in ("p0", "p1")
                )
            ),
            None,
        )
        if duplicate:
            duplicate.append(a)
        else:
            span_groups.append([a])
    usable = []
    report["conflicting_repeated_spans"] = []
    for group in span_groups:
        if len({a["label_mm"] for a in group}) > 1:
            report["conflicting_repeated_spans"].append([a["id"] for a in group])
            for a in group:
                a["fit_exclusion"] = "conflicting_repeated_span_labels"
            continue
        usable.append(group[0])
        for a in group[1:]:
            a["duplicate_of"] = group[0]["id"]
    report["independent_fit_candidates"] = len(usable)
    report["duplicate_span_count"] = sum("duplicate_of" in a for a in anchors)
    groups = []
    for a in sorted(usable, key=lambda a: a["observed_scale"]):
        if (
            groups
            and abs(
                a["observed_scale"]
                / statistics.median(x["observed_scale"] for x in groups[-1])
                - 1
            )
            < 0.02
        ):
            groups[-1].append(a)
        else:
            groups.append([a])
    supported = [g for g in groups if len(g) >= 3]
    report["scale_groups"] = [
        {
            "scale": statistics.median(a["observed_scale"] for a in g),
            "anchors": [a["id"] for a in g],
        }
        for g in groups
    ]
    declared = {float(text.split(":")[-1]) for text in report["title_scales"]}
    if len(declared) > 1:
        report["reasons"].append("multiple_declared_view_scales")
        return report
    if len(supported) != 1:
        report["reasons"].append(
            "multiple_scale_groups"
            if len(supported) > 1
            else "insufficient_dimension_evidence"
        )
        return report
    group = supported[0]
    if len(usable) - len(group) > max(1, len(usable) * 0.1):
        report["reasons"].append("conflicting_dimension_evidence")
        return report
    fit, holdout = [], []
    for axis in ("x", "y"):
        rows = sorted(
            [a for a in group if a["axis"] == axis], key=lambda a: (a["p0"], a["p1"])
        )
        distinct = {
            (round(a["paper_length_mm"], 1), round(a["p0"][0 if axis == "x" else 1], 1))
            for a in rows
        }
        if len(rows) < 3 or len(distinct) < 3:
            report["reasons"].append("insufficient_independent_two_axis_evidence")
            return report
        holdout.extend(rows[::3])
        fit.extend(a for i, a in enumerate(rows) if i % 3)
    factor = sum(a["paper_length_mm"] * a["label_mm"] for a in fit) / sum(
        a["paper_length_mm"] ** 2 for a in fit
    )
    axis_scales = {
        axis: sum(
            a["paper_length_mm"] * a["label_mm"] for a in fit if a["axis"] == axis
        )
        / sum(a["paper_length_mm"] ** 2 for a in fit if a["axis"] == axis)
        for axis in ("x", "y")
    }
    for a in anchors:
        a["converted_length_mm"] = a["paper_length_mm"] * factor
        a["error_mm"] = a["converted_length_mm"] - a["label_mm"]
        a["relative_error"] = abs(a["error_mm"]) / a["label_mm"]
        a["role"] = "holdout" if a in holdout else "fit" if a in fit else "check_only"
        a["status"] = "accepted" if a["relative_error"] <= limit else "review"
    report["chains"] = _chains([a for a in anchors if a["relative_error"] <= 0.02])
    report.update(
        scale=factor,
        axis_scales=axis_scales,
        fit_p95=_p95([a["relative_error"] for a in fit]),
        holdout_p95=_p95([a["relative_error"] for a in holdout]),
        fit_count=len(fit),
        holdout_count=len(holdout),
    )
    if abs(axis_scales["x"] / axis_scales["y"] - 1) > limit:
        report["reasons"].append("axis_scale_conflict")
    if max(report["fit_p95"], report["holdout_p95"]) > limit:
        report["reasons"].append("dimension_residual_exceeded")
    if not any(c["passed"] for c in report["chains"]):
        report["reasons"].append("dimension_chain_not_confirmed")
    # Unit declarations take precedence over the conventional unitless-mm rule.
    if any(
        re.search(
            r"单位.*(?:厘米|米|cm)|dimensions.*(?:centimet|metres)",
            t.text,
            re.IGNORECASE,
        )
        and not re.search(r"毫米|millimet", t.text, re.IGNORECASE)
        for t in tokens
    ):
        report["reasons"].append("drawing_unit_requires_confirmation")
    if not report["reasons"]:
        report.update(status="confirmed", paper_mm_preserved=False, model_output=True)
    return report


def calibrate_paper_dxf(
    source,
    output,
    *,
    mode="auto",
    recover=True,
    policy="off_layer",
    limit=0.002,
    allow_declared_scale=False,
):
    """Write real model units only after independent horizontal/vertical checks."""
    import ezdxf
    from ezdxf import transform
    from ezdxf.enums import TextEntityAlignment
    from ezdxf.math import Matrix44

    from pdf2dxf_stable.determinism import sha256

    doc = ezdxf.readfile(source)
    report = analyze_dimensions(
        doc, recover=recover, limit=limit, spool_dir=Path(output).parent
    )
    report["source_paper_dxf_sha256"] = sha256(source)
    report["source_coordinate_units"] = "paper_mm"
    confirmed = report["status"] == "confirmed"
    declared = sorted(
        {float(text.split(":")[-1]) for text in report.get("title_scales", [])}
    )
    unsafe_reasons = {
        "multiple_declared_view_scales",
        "multiple_scale_groups",
        "conflicting_dimension_evidence",
        "axis_scale_conflict",
        "dimension_residual_exceeded",
        "drawing_unit_requires_confirmation",
    }
    dimension_conflict = any(
        abs(float(group["scale"]) / declared[0] - 1) > 0.05
        for group in report.get("scale_groups", [])
        if declared and len(group.get("anchors", [])) >= 2
    )
    report["declared_scale_conflicts_dimension_evidence"] = dimension_conflict
    if dimension_conflict and not confirmed:
        report["reasons"].append("declared_scale_conflicts_dimensions")
    approximate = (
        allow_declared_scale
        and not confirmed
        and mode != "sheet"
        and len(declared) == 1
        and not report["sheet_text_markers"]
        and not unsafe_reasons.intersection(report["reasons"])
        and not dimension_conflict
    )
    if (
        allow_declared_scale
        and not confirmed
        and mode != "sheet"
        and declared
        and report["sheet_text_markers"]
    ):
        report["reasons"].append("sheet_content_requires_paper_space")
    if approximate:
        report.update(
            status="declared_approximate",
            scale=declared[0],
            scale_source="single_title_scale",
            engineering_scale_confirmed=False,
        )
    elif confirmed:
        report.update(
            scale_source="independent_dimension_evidence",
            engineering_scale_confirmed=True,
        )
    else:
        report["engineering_scale_confirmed"] = False
    apply_scale = (confirmed or approximate) and mode != "sheet"
    report["applied"] = apply_scale
    report["paper_mm_preserved"] = not apply_scale
    report["model_output"] = apply_scale
    appid = "PDF2DXF_EVIDENCE"
    if appid not in doc.appids:
        doc.appids.add(appid)
    for name in (
        "PDF_TEXT_RECOVERED_NOOCR",
        "PDF_OUTLINE_BACKUP",
        "PDF_DIMENSION_EVIDENCE",
    ):
        if name not in doc.layers:
            doc.layers.new(name)
    doc.layers.get("PDF_OUTLINE_BACKUP").off()
    doc.layers.get("PDF_DIMENSION_EVIDENCE").off()
    chain_ids = {
        key
        for chain in report["chains"]
        if chain["passed"]
        for key in [chain["total"], *chain["parts"]]
    }
    written, seen = 0, set()
    for anchor in report["anchors"]:
        # Geometry residual and label recovery are separate facts. A label in a
        # closed dimension chain can be correct even when PDF rounding is coarse.
        label_confirmed = confirmed and (
            anchor.get("relative_error", 1) <= limit
            or (anchor["id"] in chain_ids and anchor.get("relative_error", 1) <= 0.02)
        )
        anchor["label_status"] = (
            "native"
            if anchor["text_method"] == "native_dxf_text"
            else "confirmed"
            if label_confirmed
            else "review"
        )
        if not confirmed:
            continue
        if anchor["text_method"] == "verified_vector_template" and label_confirmed:
            handles = anchor["text_handles"]
            if not any(handle in seen for handle in handles):
                seen.update(handles)
                x0, y0, x1, y1 = anchor["text_bbox"]
                a, b = {
                    0: ((x0, y0), (x1, y0)),
                    90: ((x1, y0), (x1, y1)),
                    180: ((x1, y1), (x0, y1)),
                    270: ((x0, y1), (x0, y0)),
                }[anchor["text_angle"]]
                text = doc.modelspace().add_text(
                    anchor["text"],
                    dxfattribs={
                        "height": anchor["text_height"],
                        "layer": "PDF_TEXT_RECOVERED_NOOCR",
                    },
                )
                text.set_placement(a, b, align=TextEntityAlignment.FIT)
                text.set_xdata(
                    appid,
                    [
                        (1000, "verified_dimension_label"),
                        (1000, anchor["id"]),
                        *((1000, h) for h in handles),
                    ],
                )
                anchor["recovered_text_handle"] = text.dxf.handle
                written += 1
                for handle in handles:
                    entity = doc.entitydb.get(handle)
                    if entity is None:
                        continue
                    if policy == "drop":
                        doc.modelspace().delete_entity(entity)
                    elif policy == "off_layer":
                        entity.set_xdata(
                            appid, [(1000, "original_layer"), (1000, entity.dxf.layer)]
                        )
                        entity.dxf.layer = "PDF_OUTLINE_BACKUP"
        # Store independently measurable evidence, including residuals. The
        # original dimension strokes remain the visible rendering of the source.
        if anchor["text_method"] == "native_dxf_text" or label_confirmed:
            # Reject a misbound annotation; it must agree with this scale mode.
            if anchor.get("relative_error", 1) > 0.05:
                anchor["status"] = "review"
                continue
            dim = doc.modelspace().add_linear_dim(
                base=anchor["p0"],
                p1=anchor["p0"],
                p2=anchor["p1"],
                angle=0 if anchor["axis"] == "x" else 90,
                text=str(anchor["label_mm"]),
                dimstyle="Standard",
                dxfattribs={"layer": "PDF_DIMENSION_EVIDENCE"},
                override={
                    "dimtxt": anchor["text_height"],
                    "dimasz": anchor["text_height"] * 0.25,
                },
            )
            dim.render()
            dim.dimension.set_xdata(
                appid,
                [
                    (1000, anchor["id"]),
                    (1040, anchor["label_mm"]),
                    *(
                        (1000, h)
                        for h in anchor["text_handles"] + anchor["extension_handles"]
                    ),
                ],
            )
            anchor["output_dimension_handle"] = dim.dimension.dxf.handle
    report["path_text"]["accepted_tokens"] = written
    from .source_entities import capture_sources

    report["source_entities"] = capture_sources(doc, report["anchors"])
    report["source_entity_coordinate_units"] = "paper_mm"
    if apply_scale:
        failures = list(
            transform.inplace(doc.modelspace(), Matrix44.scale(report["scale"]))
        )
        if failures:
            raise ValueError("CALIBRATION_TRANSFORM_FAILED: " + str(failures[:3]))
        for key in ("$EXTMIN", "$EXTMAX"):
            if key in doc.header:
                doc.header[key] = tuple(
                    float(v) * report["scale"] for v in doc.header[key]
                )
        if mode == "blocks":
            name = "PDF2DXF_MODEL"
            while name in doc.blocks:
                name += "_"
            block = doc.blocks.new(name)
            for entity in list(doc.modelspace()):
                doc.modelspace().move_to_layout(entity, block)
            doc.modelspace().add_blockref(name, (0, 0))
    doc.header["$INSUNITS"] = 4
    doc.layers.get("0").set_xdata(
        appid,
        [
            (1000, "paper_to_model_mm"),
            (1040, report["scale"] if apply_scale else 1.0),
            (1000, "dimension_evidence"),
            (1000, report["status"]),
            (1000, "source_paper_mm"),
        ],
    )
    doc.saveas(output)
    return report
