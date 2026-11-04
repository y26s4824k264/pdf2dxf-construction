"""Verify quarter-turned Han against independent, earlier upright glyphs."""

from collections import defaultdict
from dataclasses import replace
import hashlib

import numpy as np
from scipy.spatial import cKDTree

from .font_catalog import _canonical_catalog_character, is_han_character
from .vector_catalog import MAX_GRID_BOUNDARY_ERROR, _descriptor, _normalise
from .vector_text import _adjacent, _candidate_group, _placement, _printer_grid


def _turn(points, angle):
    if angle == 90:
        return np.column_stack((-points[:, 1], points[:, 0]))
    if angle == 180:
        return -points
    if angle == 270:
        return np.column_stack((points[:, 1], -points[:, 0]))
    raise ValueError("Only nonzero quarter turns are supported")


def _bounds(low, high, angle):
    points = _turn(np.array([low, high]), angle)
    return points.min(0), points.max(0)


def _unique_orientation(match, angle, atoms, catalogs):
    """Short labels cannot use row layout to disambiguate a quarter turn.

    Search every supplied stroke font in all four orientations, including
    unseeded labels and topology-deferred rivals. Independent references may
    confirm geometry, but must never hide a different orientation or Unicode.
    """
    interpretations = set()
    for turn in (0, 90, 180, 270):
        group = []
        for atom in atoms[match.start : match.end]:
            paths = tuple(
                _turn(p, 360 - turn) if turn else p for p in atom.paths
            )
            points = np.vstack(paths)
            group.append(
                replace(atom, paths=paths, low=points.min(0), high=points.max(0))
            )
        pending = []
        metrics = {"font_vector_ambiguous_glyphs": 0}
        result = _candidate_group(
            group, catalogs, metrics,
            paper_mm=True, deferred=pending, reject_deferred_rivals=True,
        )
        # An ambiguous orientation is not evidence that there is no rival.
        # _candidate_group increments the metric before rejecting its labels.
        if metrics["font_vector_ambiguous_glyphs"]:
            return False
        if result is not None:
            pending.append(result)
        interpretations.update((turn, m.char) for m, _ in pending)
    return interpretations == {(angle, match.char)}


def recover_rotated_strokes(
    atoms, source_entities, catalogs, matches, occupied, *, paper_mm
):
    from .stroke_text import _coherent, _repeat_candidates, _whole_cell, _whole_source

    metrics = {
        "font_stroke_rotated_windows_scanned": 0,
        "font_stroke_rotated_glyph_matches": 0,
        "font_stroke_rotated_short_glyph_matches": 0,
        "font_stroke_rotated_row_evidence": [],
    }
    # No labels from single anchors, repeats or this pass may become references.
    seeds = [
        m
        for m in matches
        if m.template.admission == "shx_stroke_boundary_layout_consensus"
    ]
    if not seeds or not paper_mm:
        return [], metrics
    locked = {cid for m in seeds for cid in m.font_catalog_ids}
    reference_labels = defaultdict(set)
    for m in seeds:
        for cid in m.font_catalog_ids:
            reference_labels[cid].add(m.char)
    descriptors = [
        c.arrays["descriptors.npy"][i]
        for c in catalogs
        for i, cp in enumerate(c.arrays["codepoints.npy"])
        if _canonical_catalog_character(int(cp)) in reference_labels[c.catalog_id]
    ]
    if not descriptors:
        return [], metrics
    reference_tree = cKDTree(descriptors)
    used = occupied | {i for m in matches for i in range(m.start, m.end)}
    groups = defaultdict(list)
    for atom in atoms:
        if atom.entity.dxftype() != "HATCH":
            groups[atom.source_ref].append(atom)
    whole = {
        ref: _whole_source(group, source_entities) for ref, group in groups.items()
    }
    maximum = min(128, 2 * max(int(c.font["max_source_paths"]) for c in catalogs))
    proposals = []
    for angle in (90, 180, 270):
        local = []
        for atom in atoms:
            paths = tuple(_turn(p, 360 - angle) for p in atom.paths)
            points = np.vstack(paths)
            local.append(
                replace(atom, paths=paths, low=points.min(0), high=points.max(0))
            )
        candidates, proofs = [], {}
        scan_metrics = {"font_vector_ambiguous_glyphs": 0}
        for start, first in enumerate(local):
            if first.entity.dxftype() == "HATCH":
                break
            if (
                start in used
                or not whole[first.source_ref]
                or (start and local[start - 1].source_ref == first.source_ref)
            ):
                continue
            low, high, previous = first.low.copy(), first.high.copy(), first.source_ref
            for end in range(start, min(len(local), start + maximum)):
                atom = local[end]
                if (
                    atom.entity.dxftype() == "HATCH"
                    or end in used
                    or atom.layer != first.layer
                    or not whole.get(atom.source_ref, False)
                ):
                    break
                if (
                    atom.source_ref[:2] != previous[:2]
                    or not 0 <= atom.source_ref[2] - previous[2] <= 1
                ):
                    break
                previous = atom.source_ref
                low, high = np.minimum(low, atom.low), np.maximum(high, atom.high)
                if max(high - low) > 12:
                    break
                if (
                    end + 1 < len(local)
                    and local[end + 1].source_ref == atom.source_ref
                ):
                    continue
                metrics["font_stroke_rotated_windows_scanned"] += 1
                paths = [p for a in local[start : end + 1] for p in a.paths]
                if (
                    len(paths) > 128
                    or sum(map(len, paths)) > 8192
                    or min(high - low) < 0.08
                ):
                    continue
                points = np.vstack(paths)
                if not _printer_grid(points, paper_mm=paper_mm, minimum_vertices=8):
                    continue
                normal, _, extent = _normalise(paths)
                aspect = float(extent[0] / extent[1])
                # Same complete radius bound as the full catalog search. This
                # only skips windows unable to match any earlier known label;
                # all supplied fonts still take part in the final ambiguity check.
                radius = MAX_GRID_BOUNDARY_ERROR / min(aspect, 1.0) + 2e-6
                if not reference_tree.query_ball_point(
                    _descriptor(normal), radius, p=np.inf, eps=0
                ):
                    continue
                pending = []
                result = _candidate_group(
                    local[start : end + 1],
                    catalogs,
                    scan_metrics,
                    paper_mm=paper_mm,
                    deferred=pending,
                )
                found = [result] if result is not None else pending
                for m, proof in found:
                    if (
                        not is_han_character(m.char)
                        or not m.font_vector_grid_pitch
                        or len(locked.intersection(m.font_catalog_ids)) != 1
                    ):
                        continue
                    references = sorted(
                        (
                            s
                            for s in seeds
                            if s.char == m.char
                            and s.atoms[0].source_ref[:2] == m.atoms[0].source_ref[:2]
                        ),
                        key=lambda s: abs(np.log(s.height / m.height)),
                    )
                    # Bounds rotate to compare physical locations; reference ink
                    # stays upright for the existing path-bijection verifier.
                    refs = [
                        replace(s, low=tuple(lo), high=tuple(hi))
                        for s in references
                        for lo, hi in [_bounds(s.low, s.high, 360 - angle)]
                    ]
                    supported, evidence = _repeat_candidates(refs, [(m, proof)], local)
                    if not supported:
                        continue
                    m, proof = supported[0]
                    if len(proof) != 1:
                        continue
                    candidates.append(m)
                    proofs[m.start, m.end, m.char] = proof
                    scan_metrics[m.start, m.end, m.char] = evidence[0]
        for catalog in catalogs:
            if catalog.catalog_id not in locked:
                continue
            spans = [
                m
                for m in candidates
                if catalog.catalog_id in m.font_catalog_ids
                and _whole_cell(m, local, catalog, proofs)
            ]
            starts = defaultdict(list)
            for i, m in enumerate(spans):
                starts[m.start].append(i)
            forward, backward = defaultdict(list), defaultdict(list)
            for i, m in enumerate(spans):
                for j in starts[m.end]:
                    if _adjacent(m, spans[j], catalog, proofs):
                        forward[i].append(j)
                        backward[j].append(i)
            for i in range(len(spans)):
                if backward[i]:
                    continue
                indices = [i]
                while len(forward[indices[-1]]) == 1 and len(indices) < 96:
                    j = forward[indices[-1]][0]
                    if len(backward[j]) != 1:
                        break
                    indices.append(j)
                if forward[indices[-1]]:
                    continue
                row = [spans[j] for j in indices]
                if not _coherent(row, catalog, proofs):
                    continue
                short = len({m.char for m in row}) < 3
                if short:
                    if len(row) > 2 or len({m.char for m in row}) != len(row):
                        continue
                    if len(row) == 1 and any(
                        other is not row[0]
                        and other.start <= row[0].end
                        and row[0].start <= other.end
                        for other in candidates
                    ):
                        # Do not turn a failed neighbouring row or competing
                        # partition into apparently isolated characters.
                        continue
                    if not all(
                        _unique_orientation(m, angle, atoms, catalogs) for m in row
                    ):
                        continue
                # At least one complex glyph is needed in addition to the
                # independent references for a multi-character row. A truly
                # isolated glyph instead needs a unique full-font orientation.
                if len(row) > 1 and not any(
                    len(
                        catalog.paths(
                            proofs[m.start, m.end, m.char][catalog.catalog_id][1]
                        )
                    )
                    >= 8
                    for m in row
                ):
                    continue
                proposal = []
                for m in row:
                    original = tuple(atoms[m.start : m.end])
                    low = np.min([a.low for a in original], axis=0)
                    high = np.max([a.high for a in original], axis=0)
                    digest = hashlib.sha256(
                        b"".join(
                            p.astype("<f4").tobytes() for a in original for p in a.paths
                        )
                    ).hexdigest()
                    proposal.append(
                        replace(
                            m,
                            low=tuple(low),
                            high=tuple(high),
                            atoms=original,
                            font_vector_layout=_placement(m, catalog, proofs),
                            font_vector_rotation=angle,
                            template=replace(
                                m.template,
                                fingerprint=digest,
                                support_locations=2,
                                admission="shx_stroke_rotated_reference_consensus",
                            ),
                        )
                    )
                proposals.append(
                    (
                        proposal,
                        {
                            "text": "".join(m.char for m in row),
                            "rotation": angle,
                            "catalog_id": catalog.catalog_id,
                            "source_layer": row[0].atoms[0].layer,
                            "source_spans": [
                                [m.atoms[0].source_ref[2], m.atoms[-1].source_ref[2]]
                                for m in row
                            ],
                            "glyph_reference_evidence": [
                                scan_metrics[m.start, m.end, m.char] for m in row
                            ],
                            "reference_policy": "earlier_strict_upright_rows_same_page",
                            "orientation_policy": (
                                "all_supplied_fonts_all_quarter_turns_unique"
                                if short else "three_label_row_layout"
                            ),
                            "output_policy": "separate_TEXT_preserving_ink_bounds_and_rotation",
                        },
                    )
                )
    additions = []
    for i, (row, evidence) in enumerate(proposals):
        if any(
            any(a.start < b.end and b.start < a.end for a in row for b in other)
            for j, (other, _) in enumerate(proposals)
            if i != j
        ):
            continue
        additions.extend(row)
        if evidence["orientation_policy"] == "all_supplied_fonts_all_quarter_turns_unique":
            metrics["font_stroke_rotated_short_glyph_matches"] += len(row)
        metrics["font_stroke_rotated_row_evidence"].append(evidence)
    metrics["font_stroke_rotated_glyph_matches"] = len(additions)
    return additions, metrics
