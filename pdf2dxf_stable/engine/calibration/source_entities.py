"""Compact source geometry evidence for dimensions and their visible labels."""

import math

from ezdxf.math import Matrix44

_ATTRS = {
    "LINE": ("start", "end", "extrusion", "thickness"),
    "LWPOLYLINE": ("elevation", "extrusion", "const_width", "flags"),
    "POLYLINE": ("elevation", "extrusion", "flags"),
    "CIRCLE": ("center", "radius", "extrusion"),
    "ARC": ("center", "radius", "extrusion", "start_angle", "end_angle"),
    "ELLIPSE": (
        "center",
        "major_axis",
        "extrusion",
        "ratio",
        "start_param",
        "end_param",
    ),
    "SPLINE": ("degree", "flags"),
    "TEXT": (
        "text",
        "height",
        "width",
        "rotation",
        "oblique",
        "text_generation_flag",
        "extrusion",
    ),
    "MTEXT": (
        "insert",
        "char_height",
        "width",
        "attachment_point",
        "text_direction",
        "extrusion",
        "line_spacing_style",
        "line_spacing_factor",
    ),
}


def _plain(value):
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return [_plain(v) for v in value]


def entity_state(entity):
    kind = entity.dxftype()
    if kind not in _ATTRS:
        raise ValueError(f"unsupported calibration source entity: {kind}")
    attrs = {key: _plain(getattr(entity.dxf, key)) for key in _ATTRS[kind]}
    for key in ("rotation", "start_angle", "end_angle"):
        if key in attrs:
            angle = attrs[key] % 360
            attrs[key] = 0.0 if math.isclose(angle, 360, abs_tol=1e-8) else angle
    if kind == "TEXT":
        alignment, first, second = entity.get_placement()
        attrs["placement"] = [alignment.name, _plain(first), _plain(second)]
    elif kind == "LWPOLYLINE":
        attrs["vertices"] = _plain(entity.get_points("xyseb"))
    elif kind == "POLYLINE":
        attrs["vertices"] = [
            [_plain(v.dxf.location), v.dxf.bulge, v.dxf.start_width, v.dxf.end_width]
            for v in entity.vertices
        ]
    elif kind == "SPLINE":
        for key in ("control_points", "fit_points", "knots", "weights"):
            attrs[key] = _plain(getattr(entity, key))
    elif kind == "MTEXT":
        attrs["text"] = entity.text
        # MTEXT can store a rotation or a direction vector; normalize that choice.
        attrs["text_direction"] = list(entity.ucs().ux)
    return {"type": kind, "attributes": attrs}


def required_source_handles(anchors):
    handles = set()
    for anchor in anchors:
        if not anchor.get("output_dimension_handle"):
            continue
        handles.add(anchor["dimension_line_handle"])
        handles.update(anchor["extension_handles"])
        if anchor.get("recovered_text_handle"):
            handles.add(anchor["recovered_text_handle"])
        elif anchor["text_method"] == "native_dxf_text":
            handles.update(anchor["text_handles"])
    return handles


def capture_sources(doc, anchors):
    return {
        handle: entity_state(doc.entitydb[handle])
        for handle in sorted(required_source_handles(anchors))
    }


def _equal(a, b):
    if isinstance(a, dict):
        return (
            isinstance(b, dict)
            and a.keys() == b.keys()
            and all(_equal(v, b[k]) for k, v in a.items())
        )
    if isinstance(a, list):
        return (
            isinstance(b, list)
            and len(a) == len(b)
            and all(_equal(x, y) for x, y in zip(a, b))
        )
    if isinstance(a, (float, int)):
        return (
            isinstance(b, (float, int))
            and math.isfinite(a)
            and math.isfinite(b)
            and math.isclose(a, b, rel_tol=1e-10, abs_tol=1e-6)
        )
    return a == b


def check_sources(instances, evidence, mm_per_unit):
    snapshots = evidence.get("source_entities")
    if (
        not snapshots
        or evidence.get("source_entity_coordinate_units") != "paper_mm"
        or not required_source_handles(evidence.get("anchors", [])).issubset(snapshots)
    ):
        return [{"code": "CALIBRATION_SOURCE_EVIDENCE_UNAVAILABLE"}]
    errors = []
    # Compare in original paper coordinates so unit changes do not change the
    # comparison tolerance or the representation of arcs, widths and text.
    to_paper = Matrix44.scale(mm_per_unit / evidence["scale"])
    for handle, state in snapshots.items():
        rows = instances.get(handle, [])
        if not rows or not rows[0].entity.is_alive:
            errors.append({"code": "CALIBRATION_SOURCE_MISSING", "handle": handle})
            continue
        if len(rows) != 1:
            errors.append(
                {
                    "code": "CALIBRATION_SOURCE_MULTIPLE_PLACEMENTS",
                    "handle": handle,
                    "count": len(rows),
                }
            )
            continue
        try:
            copy = rows[0].entity.copy()
            copy.transform(rows[0].matrix @ to_paper)
            if not _equal(state, entity_state(copy)):
                errors.append({"code": "CALIBRATION_SOURCE_MISMATCH", "handle": handle})
        except (TypeError, ValueError, ArithmeticError, NotImplementedError) as exc:
            errors.append(
                {
                    "code": "CALIBRATION_SOURCE_UNMEASURABLE",
                    "handle": handle,
                    "message": str(exc),
                }
            )
    return errors
