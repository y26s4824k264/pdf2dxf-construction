from __future__ import annotations
import gc
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any
import ezdxf
from .determinism import canonicalize_ascii_dxf
from .dimension_instances import insert_placements
from .options import output_unit_info


@dataclass(slots=True)
class ProfileReport:
    profile: str
    input_dxf: str
    output_dxf: str
    source_entities: int = 0
    output_entities: int = 0
    downgraded: dict[str, int] = field(default_factory=dict)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    audit_errors: int = 0
    audit_fixes: int = 0
    acadver: str = ""
    curve_tolerance_output_units: float | None = None

    def to_dict(self):
        return asdict(self)


def _layer_attrs(e):
    a = {"layer": str(getattr(e.dxf, "layer", "0") or "0")}
    try:
        a["color"] = int(e.dxf.color)
    except Exception:
        pass
    try:
        a["linetype"] = str(e.dxf.linetype)
    except Exception:
        pass
    return a


def _flatten_points(e, tol=0.05):
    try:
        return [
            (float(p.x), float(p.y)) for p in e.flattening(distance=tol, segments=8)
        ]
    except TypeError:
        try:
            return [(float(p.x), float(p.y)) for p in e.flattening(tol)]
        except Exception:
            return []
    except Exception:
        return []


def _add_polyline_r12(target, points, attrs, closed=False):
    if len(points) < 2:
        return 0
    try:
        target.add_polyline2d(points, dxfattribs=attrs, close=bool(closed))
        return 1
    except TypeError:
        try:
            p = target.add_polyline2d(points, dxfattribs=attrs)
            if closed:
                p.close(True)
            return 1
        except Exception:
            return 0
    except Exception:
        return 0


def _emit_virtual(entity, target, report, depth):
    if depth > 32:
        report.warnings.append(
            {
                "code": "R12_RECURSION_LIMIT",
                "handle": str(getattr(entity.dxf, "handle", "") or ""),
            }
        )
        return 0
    count = 0
    try:
        placements = (
            insert_placements(entity) if entity.dxftype() == "INSERT" else (entity,)
        )
        for placement in placements:
            for row in placement.virtual_entities():
                count += _emit_r12(row, target, report, depth + 1)
    except Exception as exc:
        report.warnings.append(
            {
                "code": "R12_EXPANSION_FAILED",
                "handle": entity.dxf.handle,
                "message": str(exc),
                "emitted_entities": count,
            }
        )
    return count


def _emit_hatch_boundaries(e, target, report):
    from ezdxf.path import from_hatch

    count = 0
    for path in from_hatch(e):
        points = [
            (float(v.x), float(v.y))
            for v in path.flattening(report.curve_tolerance_output_units or 0.05)
        ]
        count += _add_polyline_r12(target, points, _layer_attrs(e), True)
    report.downgraded["HATCH_BOUNDARY"] = report.downgraded.get("HATCH_BOUNDARY", 0) + 1
    return count


def _emit_r12(e, target, report, depth=0):
    typ = e.dxftype()
    attrs = _layer_attrs(e)
    try:
        if typ == "LINE":
            target.add_line(e.dxf.start, e.dxf.end, dxfattribs=attrs)
            return 1
        if typ == "POINT":
            target.add_point(e.dxf.location, dxfattribs=attrs)
            return 1
        if typ == "CIRCLE":
            target.add_circle(e.dxf.center, float(e.dxf.radius), dxfattribs=attrs)
            return 1
        if typ == "ARC":
            target.add_arc(
                e.dxf.center,
                float(e.dxf.radius),
                float(e.dxf.start_angle),
                float(e.dxf.end_angle),
                dxfattribs=attrs,
            )
            return 1
        if typ == "TEXT":
            a = dict(attrs)
            a.update(
                {
                    "style": str(getattr(e.dxf, "style", "Standard")),
                    "width": float(getattr(e.dxf, "width", 1.0)),
                    "height": max(float(getattr(e.dxf, "height", 2.5) or 2.5), 1e-6),
                    "rotation": float(getattr(e.dxf, "rotation", 0.0) or 0.0),
                }
            )
            for key in (
                "halign",
                "valign",
                "align_point",
                "oblique",
                "text_generation_flag",
                "extrusion",
                "thickness",
            ):
                if e.dxf.hasattr(key):
                    a[key] = e.dxf.get(key)
            target.add_text(str(e.dxf.text), dxfattribs={**a, "insert": e.dxf.insert})
            return 1
        if typ == "MTEXT":
            from ezdxf.addons.mtxpl import MTextExplode
            from ezdxf.layouts import VirtualLayout
            from .r12_fonts import ensure_r12_fonts

            if ensure_r12_fonts() and not any(
                item.get("code") == "R12_FONT_METRICS_FALLBACK" for item in report.warnings
            ):
                report.warnings.append({
                    "code": "R12_FONT_METRICS_FALLBACK",
                    "message": "No system fonts; R12 text layout uses Matplotlib's bundled metrics. Verify appearance against the source font.",
                })

            # Keep attachment, wrapping, local line spacing and text direction.
            # Stage the result so an error cannot leave a partially emitted label.
            # The normal R12 path also converts any generated modern entities.
            layout = VirtualLayout()
            with MTextExplode(layout, doc=target.doc) as exploder:
                exploder.explode(e, destroy=False)
            n = sum(_emit_r12(part, target, report, depth + 1) for part in layout)
            report.downgraded["MTEXT_TO_TEXT"] = (
                report.downgraded.get("MTEXT_TO_TEXT", 0) + 1
            )
            return n
        if typ in {"SOLID", "TRACE", "3DFACE"}:
            pts = [getattr(e.dxf, f"vtx{i}") for i in range(4)]
            if typ == "3DFACE":
                target.add_3dface(pts, dxfattribs=attrs)
            else:
                target.add_solid(pts, dxfattribs=attrs)
            return 1
        if typ in {"LWPOLYLINE", "POLYLINE"}:
            n = _emit_virtual(e, target, report, depth)
            if n:
                return n
            pts = []
            try:
                pts = [
                    (float(v.dxf.location.x), float(v.dxf.location.y))
                    for v in e.vertices
                ]
            except Exception:
                try:
                    pts = [(float(x), float(y)) for x, y, *_ in e.get_points()]
                except Exception:
                    pts = []
            report.downgraded[typ + "_TO_POLYLINE"] = (
                report.downgraded.get(typ + "_TO_POLYLINE", 0) + 1
            )
            return _add_polyline_r12(
                target, pts, attrs, bool(getattr(e, "is_closed", False))
            )
        if typ in {"ELLIPSE", "SPLINE"}:
            pts = _flatten_points(e, report.curve_tolerance_output_units or 0.05)
            report.downgraded[typ + "_TO_POLYLINE"] = (
                report.downgraded.get(typ + "_TO_POLYLINE", 0) + 1
            )
            return _add_polyline_r12(target, pts, attrs, False)
        if typ == "HATCH":
            return _emit_hatch_boundaries(e, target, report)
        if typ in {"INSERT", "DIMENSION", "LEADER", "MLINE"}:
            n = _emit_virtual(e, target, report, depth)
            report.downgraded[typ + "_EXPLODED"] = (
                report.downgraded.get(typ + "_EXPLODED", 0) + 1
            )
            if n:
                return n
        if typ == "IMAGE":
            pts = []
            try:
                pts = [(float(p.x), float(p.y)) for p in e.boundary_path_wcs()]
            except Exception:
                pass
            report.downgraded["IMAGE_BOUNDARY"] = (
                report.downgraded.get("IMAGE_BOUNDARY", 0) + 1
            )
            return _add_polyline_r12(target, pts, attrs, True)
    except Exception as exc:
        report.warnings.append(
            {
                "code": "R12_ENTITY_EXCEPTION",
                "type": typ,
                "handle": str(getattr(e.dxf, "handle", "") or ""),
                "message": str(exc),
            }
        )
    # No silent drop: emit a point at a representative location and report it.
    pos = None
    for name in ("insert", "location", "center", "start"):
        try:
            pos = getattr(e.dxf, name)
            break
        except Exception:
            pass
    if pos is None:
        pos = (0, 0, 0)
    try:
        target.add_point(pos, dxfattribs=attrs)
        n = 1
    except Exception:
        n = 0
    report.warnings.append(
        {
            "code": "R12_UNSUPPORTED_ENTITY_WITNESS",
            "type": typ,
            "handle": str(getattr(e.dxf, "handle", "") or ""),
            "witness_added": bool(n),
        }
    )
    report.downgraded["UNSUPPORTED_WITNESS"] = (
        report.downgraded.get("UNSUPPORTED_WITNESS", 0) + 1
    )
    return n


def _prepare_layers(src, dst):
    for name in ("linetypes", "styles", "layers"):
        source_table, target_table = getattr(src, name), getattr(dst, name)
        for entry in source_table:
            attrs = entry.dxfattribs()
            attrs.pop("handle", None)
            attrs.pop("owner", None)
            key = attrs.pop("name")
            if key in target_table:
                target_table.get(key).update_dxf_attribs(attrs)
            else:
                # new() accepts signed layer colors, unlike layers.add().
                copied = target_table.new(key, dxfattribs=attrs)
                if name == "linetypes":
                    copied.pattern_tags = entry.pattern_tags
    dst.header["$INSUNITS"] = src.header.get("$INSUNITS", 0)
    if "PDF2DXF_STABLE" not in dst.appids:
        dst.appids.add("PDF2DXF_STABLE")
    dst.layers.get("0").set_xdata(
        "PDF2DXF_STABLE",
        [(1000, "INSUNITS"), (1070, int(src.header.get("$INSUNITS", 0)))],
    )


def _dedup_text(doc):
    hidden = "PDF_TEXT_DUPLICATE_HIDDEN"
    if hidden not in doc.layers:
        try:
            doc.layers.add(hidden, color=8)
        except Exception:
            pass
    moved = 0
    # Blocks include model/paper layouts and ordinary definitions. Compare only
    # within each definition: separate INSERT placements must remain separate.
    for layout in doc.blocks:
        seen = {}
        for e in layout:
            if e.dxftype() not in {"TEXT", "MTEXT"}:
                continue
            text = e.text if e.dxftype() == "MTEXT" else str(e.dxf.text)
            if not text.strip():
                continue
            # Only identical entities may be hidden. Normalizing absolute
            # positions by each text's height collides for distant labels, e.g.
            # (10, 10, h=1) and (20, 20, h=2). Keep raw formatting, placement,
            # font, layer, height and all other rendering attributes intact.
            key = (
                e.dxftype(),
                text,
                tuple(
                    (k, repr(v))
                    for k, v in sorted(e.dxf.all_existing_dxf_attribs().items())
                    if k not in {"handle", "owner"}
                ),
            )
            if key in seen:
                try:
                    e.dxf.layer = hidden
                    moved += 1
                except Exception:
                    pass
            else:
                seen[key] = e
    try:
        doc.layers.get(hidden).off()
        doc.layers.get(hidden).freeze()
    except Exception:
        pass
    return moved


def emit_universal(
    input_dxf, output_dxf, *, seed, deterministic=True, resource_root=None, request=None
):
    input_dxf, output_dxf = Path(input_dxf), Path(output_dxf)
    doc = ezdxf.readfile(input_dxf)
    report = ProfileReport("universal", str(input_dxf), str(output_dxf))
    report.source_entities = sum(1 for _ in doc.entitydb.values())
    from .resources import relocate_images
    from .options import apply_output_options

    _, missing = relocate_images(doc, input_dxf, output_dxf, resource_root)
    report.warnings.extend(missing)
    if request is not None:
        apply_output_options(doc, request)
    moved = _dedup_text(doc)
    if moved:
        report.downgraded["DUPLICATE_TEXT_HIDDEN"] = moved
    doc.dxfversion = "AC1021"
    # Stable header metadata. Byte canonicalizer repeats this after serialization.
    doc.header["$TDCREATE"] = 2451544.5
    doc.header["$TDUPDATE"] = 2451544.5
    output_dxf.parent.mkdir(parents=True, exist_ok=True)
    audit = doc.audit()
    report.audit_errors = len(audit.errors)
    report.audit_fixes = len(audit.fixes)
    report.acadver = doc.dxfversion
    report.output_entities = sum(1 for _ in doc.entitydb.values())
    doc.saveas(output_dxf, fmt="asc")
    if deterministic:
        canonicalize_ascii_dxf(output_dxf, seed=seed)
    del audit, doc
    gc.collect()
    # page_worker independently reopens the serialized DXF in validate_dxf().
    return report


def emit_legacy_r12(input_dxf, output_dxf, *, seed, deterministic=True):
    input_dxf, output_dxf = Path(input_dxf), Path(output_dxf)
    src = ezdxf.readfile(input_dxf)
    dst = ezdxf.new("R12", setup=True)
    report = ProfileReport("legacy-r12", str(input_dxf), str(output_dxf))
    report.curve_tolerance_output_units = 0.05 / output_unit_info(src)[1]
    _prepare_layers(src, dst)
    target = dst.modelspace()
    source_entities = list(src.modelspace())
    report.source_entities = len(source_entities)
    for e in source_entities:
        report.output_entities += _emit_r12(e, target, report, 0)
    dst.header["$TDCREATE"] = 2451544.5
    dst.header["$TDUPDATE"] = 2451544.5
    output_dxf.parent.mkdir(parents=True, exist_ok=True)
    dst.saveas(output_dxf, fmt="asc")
    if deterministic:
        canonicalize_ascii_dxf(output_dxf, seed=seed)
    check = ezdxf.readfile(output_dxf)
    audit = check.audit()
    report.audit_errors = len(audit.errors)
    report.audit_fixes = len(audit.fixes)
    report.acadver = check.dxfversion
    gc.collect()
    return report
