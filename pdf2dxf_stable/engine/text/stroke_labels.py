"""Confirm repeated complex labels without globally locking a short-row font."""

from collections import defaultdict
from dataclasses import replace

import numpy as np

from .vector_catalog import _join_stroke_paths, _normalise, _stroke_paths_agree
from .vector_text import _placement


def _neighbours(a, b, catalog, proofs):
    if a.end != b.start or a.atoms[0].layer != b.atoms[0].layer:
        return False
    x, y = a.atoms[-1].source_ref, b.atoms[0].source_ref
    if x[:2] != y[:2] or y[2] - x[2] != 1:
        return False
    aa, bb = _placement(a, catalog, proofs), _placement(b, catalog, proofs)
    em = min(aa[0], bb[0])
    pitch = min(a.font_vector_grid_pitch, b.font_vector_grid_pitch)
    return (
        abs(aa[0] - bb[0]) <= max(0.02 * em, 2 * pitch)
        and abs(aa[1] - bb[1])
        <= max(
            0.03, min(0.1, 2 * pitch / min(a.high[0] - a.low[0], b.high[0] - b.low[0]))
        )
        * min(aa[1], bb[1])
        and abs(aa[3] - bb[3]) <= max(0.015 * em, 2 * pitch)
        and 0 <= b.low[0] - a.high[0] <= 0.5 * em
    )


def admit_repeated_labels(matches, candidates, proofs, atoms, catalogs, metrics):
    from .font_catalog import is_han_character
    from .stroke_text import _whole_cell

    used = {i for m in matches for i in range(m.start, m.end)}
    groups = defaultdict(list)
    normals = {}
    for catalog in catalogs:
        complete = [
            m
            for m in candidates
            if catalog.catalog_id in m.font_catalog_ids
            and m.font_vector_grid_pitch
            and is_han_character(m.char)
            and not any(i in used for i in range(m.start, m.end))
            and _whole_cell(m, atoms, catalog, proofs)
        ]
        # Do not resolve competing segmentations by choosing a preferred row.
        spans = [
            m
            for m in complete
            if not any(
                n is not m and m.start < n.end and n.start < m.end for n in complete
            )
        ]
        starts = defaultdict(list)
        for i, m in enumerate(spans):
            starts[m.start].append(i)
        forward, backward = defaultdict(list), defaultdict(list)
        for i, m in enumerate(spans):
            for j in starts[m.end]:
                if _neighbours(m, spans[j], catalog, proofs):
                    forward[i].append(j)
                    backward[j].append(i)
        for i in range(len(spans)):
            if backward[i]:
                continue
            indices = [i]
            while len(forward[indices[-1]]) == 1 and len(indices) < 8:
                j = forward[indices[-1]][0]
                if len(backward[j]) != 1:
                    break
                indices.append(j)
            if forward[indices[-1]]:
                continue
            row = [spans[j] for j in indices]
            if len({m.char for m in row}) < 2 or not any(
                len(
                    catalog.paths(proofs[m.start, m.end, m.char][catalog.catalog_id][1])
                )
                >= 8
                and len(_join_stroke_paths([p for a in m.atoms for p in a.paths])) >= 8
                for m in row
            ):
                continue
            low = np.min([m.low for m in row], axis=0)
            high = np.max([m.high for m in row], axis=0)
            em, width, *_ = _placement(row[0], catalog, proofs)
            scale = np.array([em * width, em, em * width, em])
            boxes = (
                np.array([(*m.low, *m.high) for m in row]) - np.tile(low, 2)
            ) / scale
            key = (
                catalog.catalog_id,
                row[0].atoms[0].source_ref[:2],
                "".join(m.char for m in row),
            )
            groups[key].append((catalog, row, low, high, boxes, scale))
    additions, evidence = {}, []
    for group in groups.values():
        if not 4 <= len(group) <= 64:
            continue
        for catalog, row, low, high, boxes, scale in group:
            pitch = min(m.font_vector_grid_pitch for m in row)
            limit = max(0.006 * scale[1], np.sqrt(2) * pitch)
            supports, locations, residuals = [], [(low, high)], []
            for _, ref, rlow, rhigh, rboxes, _ in group:
                if any(
                    not np.any((high_ <= rlow) | (rhigh <= low_))
                    for low_, high_ in locations
                ):
                    continue
                error = float(np.max(np.abs(boxes - rboxes) * scale))
                if error > limit:
                    continue
                agree = True
                pair_limits = []
                for m, other in zip(row, ref):
                    for glyph in (m, other):
                        key = glyph.start, glyph.end
                        if key not in normals:
                            normals[key] = _normalise(
                                _join_stroke_paths(
                                    [p for a in glyph.atoms for p in a.paths]
                                )
                            )[0]
                    aspect = (m.high[0] - m.low[0]) / m.height
                    other_aspect = (other.high[0] - other.low[0]) / other.height
                    # Both observations already pass the unchanged font bound.
                    # Their mutual displacement includes both independently
                    # verified uncertainties, after the reference X rescaling.
                    pair_limit = (
                        m.font_vector_error_limit
                        + other.font_vector_error_limit
                        * max(1.0, aspect / other_aspect)
                        + 2e-6
                    )
                    pair_limits.append(float(pair_limit))
                    if not _stroke_paths_agree(
                        normals[m.start, m.end],
                        normals[other.start, other.end],
                        aspect,
                        pair_limit,
                    ):
                        agree = False
                        break
                if not agree:
                    continue
                locations.append((rlow, rhigh))
                supports.append(
                    {
                        "source_span": [
                            ref[0].atoms[0].source_ref[2],
                            ref[-1].atoms[-1].source_ref[2],
                        ],
                        "source_handles": [
                            a.entity.dxf.handle for m in ref for a in m.atoms
                        ],
                        "glyph_pair_error_limits": pair_limits,
                    }
                )
                residuals.append(error)
                if len(supports) == 3:
                    break
            if len(supports) < 3:
                continue
            for m in row:
                additions.setdefault(
                    (m.start, m.end),
                    replace(
                        m,
                        font_catalog_ids=(catalog.catalog_id,),
                        font_vector_layout=_placement(m, catalog, proofs),
                        template=replace(
                            m.template,
                            support_locations=4,
                            admission="shx_stroke_repeated_label_consensus",
                        ),
                    ),
                )
            evidence.append(
                {
                    "text": "".join(m.char for m in row),
                    "catalog_id": catalog.catalog_id,
                    "source_span": [
                        row[0].atoms[0].source_ref[2],
                        row[-1].atoms[-1].source_ref[2],
                    ],
                    "source_handles": [
                        a.entity.dxf.handle for m in row for a in m.atoms
                    ],
                    "bbox_dxf": [*map(float, low), *map(float, high)],
                    "supports": supports,
                    "maximum_layout_residual": max(residuals),
                    "layout_error_limit": float(limit),
                    "glyph_error_limits": [m.font_vector_error_limit for m in row],
                    "font_globally_locked": False,
                }
            )
    metrics["font_stroke_repeated_label_glyph_matches"] = len(additions)
    metrics["font_stroke_repeated_label_evidence"] = evidence[:200]
    result = sorted([*matches, *additions.values()], key=lambda m: m.start)
    metrics["font_stroke_glyph_matches"] = metrics["font_vector_glyph_matches"] = len(
        result
    )
    return result
