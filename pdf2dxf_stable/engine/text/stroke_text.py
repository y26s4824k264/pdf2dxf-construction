"""Match complete SHX stroke glyphs in saved DXF, without pixels or fonts."""

from collections import defaultdict
from dataclasses import replace

import numpy as np

from .vector_text import _adjacent, _candidate_group, _placement
from .vector_catalog import _join_stroke_paths, _normalise, _stroke_paths_agree

MAX_ROW_GLYPHS = 96


def _painted_stroke(entity):
    if not entity.has_xdata("PDF2DXF_STROKE"):
        return False
    return any(
        t.code == 1000 and t.value == "paint"
        for t in entity.get_xdata("PDF2DXF_STROKE")
    )


def _whole_source(group, source_entities):
    present = {a.entity.dxf.handle for a in group}
    return all(
        e.dxf.handle in present or _painted_stroke(e)
        for e in source_entities[group[0].source_ref]
    )


def _row_model(row, catalog, proofs, *, spaced=False):
    # One affine placement for the whole row prevents accumulated per-glyph
    # scale noise. Uniform tracking is fitted only for separately emitted,
    # independently locked four-label rows; no missing text is inferred.
    x, y, observed_x, observed_y = [], [], [], []
    advance = 0.0
    if spaced and len({m.char for m in row}) < 4:
        return None
    for position, match in enumerate(row):
        _, index, _, _ = proofs[match.start, match.end, match.char][catalog.catalog_id]
        x0, y0, x1, y1, step = map(float, catalog.arrays["metrics.npy"][index])
        x.extend(
            ((1, advance + x0, position), (1, advance + x1, position))
            if spaced
            else ((1, advance + x0), (1, advance + x1))
        )
        y.extend(((1, y0), (1, y1)))
        observed_x.extend((match.low[0], match.high[0]))
        observed_y.extend((match.low[1], match.high[1]))
        advance += step
    x, y = np.asarray(x), np.asarray(y)
    a = np.linalg.lstsq(x, observed_x, rcond=None)[0]
    b = np.linalg.lstsq(y, observed_y, rcond=None)[0]
    if not 0 < b[1] or not 0.2 <= a[1] / b[1] <= 3:
        return None
    if spaced and not 0.05 * b[1] <= a[2] <= b[1]:
        return None
    pitch = min(m.font_vector_grid_pitch or 0 for m in row)
    limit = max(0.006 * b[1], np.sqrt(2) * pitch)
    if (
        max(np.max(np.abs(x @ a - observed_x)), np.max(np.abs(y @ b - observed_y)))
        > limit
    ):
        return None
    return tuple(map(float, (*a, *b)))


def _coherent(row, catalog, proofs):
    return _row_model(row, catalog, proofs) is not None


def _whole_cell(match, atoms, catalog, proofs):
    em, width, origin, baseline, advance = _placement(match, catalog, proofs)
    # A neighbouring stroke in the same font cell is an omitted part, not text.
    for i in (match.start - 1, match.end):
        if not 0 <= i < len(atoms):
            continue
        atom = atoms[i]
        if atom.entity.dxftype() == "HATCH" or atom.layer != match.atoms[0].layer:
            continue
        ref = (
            match.atoms[0].source_ref if i < match.start else match.atoms[-1].source_ref
        )
        if atom.source_ref[:2] != ref[:2] or abs(atom.source_ref[2] - ref[2]) > 1:
            continue
        center = (atom.low + atom.high) * 0.5
        if (
            origin < center[0] < origin + advance
            and baseline - 0.2 * em < center[1] < baseline + 1.2 * em
        ):
            return False
    return True


def _anchored_single(match, row, catalog, proofs, groups, whole):
    """Confirm a separated glyph from a real local row, without labelling gaps."""
    if len({m.char for m in row}) < 4:
        return None
    if match.atoms[0].layer != row[0].atoms[0].layer:
        return None
    ref = match.atoms[0].source_ref
    if ref[:2] != row[0].atoms[0].source_ref[:2]:
        return None
    first, last = row[0].atoms[0].source_ref[2], row[-1].atoms[-1].source_ref[2]
    if match.atoms[-1].source_ref[2] < first:
        lo, hi = match.atoms[-1].source_ref[2], first
        left, right = match, row[0]
    elif ref[2] > last:
        lo, hi = last, ref[2]
        left, right = row[-1], match
    else:
        return None
    if not 1 < hi - lo <= 64:
        return None
    model = _row_model(row, catalog, proofs)
    if model is None:
        return None
    _, index, _, _ = proofs[match.start, match.end, match.char][catalog.catalog_id]
    x0, y0, x1, y1, advance = map(float, catalog.arrays["metrics.npy"][index])
    origin = (match.low[0] + match.high[0] - (x0 + x1) * model[1]) * 0.5
    expected = np.array(
        [
            origin + x0 * model[1],
            model[2] + y0 * model[3],
            origin + x1 * model[1],
            model[2] + y1 * model[3],
        ]
    )
    pitch = min(
        match.font_vector_grid_pitch or 0, *(m.font_vector_grid_pitch or 0 for m in row)
    )
    limit = max(0.006 * model[3], np.sqrt(2) * pitch)
    error = float(np.max(np.abs(expected - (*match.low, *match.high))))
    gap_lo, gap_hi = left.high[0], right.low[0]
    if error > limit or not 0 < gap_hi - gap_lo <= 3 * advance * model[1]:
        return None
    # Every intervening source paint must survive completely, on the same
    # layer and inside the visible gap. Missing/unsupported paints cannot act
    # as punctuation evidence. Their Unicode and spacing are never invented.
    for seq in range(lo + 1, hi):
        key = (*ref[:2], seq)
        if not whole.get(key, False) or not groups.get(key):
            return None
        for atom in groups[key]:
            if (
                atom.layer != match.atoms[0].layer
                or atom.low[0] < gap_lo - limit
                or atom.high[0] > gap_hi + limit
                or atom.low[1] < model[2] - 0.3 * model[3]
                or atom.high[1] > model[2] + 1.2 * model[3]
            ):
                return None
    layout = (
        model[3],
        model[1] / model[3],
        float(origin),
        model[2],
        advance * model[1],
    )
    return layout, {
        "catalog_id": catalog.catalog_id,
        "text": match.char,
        "anchor_text": "".join(m.char for m in row),
        "source_span": [lo, hi],
        "layout": list(layout),
        "maximum_layout_residual": error,
        "layout_error_limit": float(limit),
        "unlabelled_separator_paints": hi - lo - 1,
    }


def _separate_locations(a, b):
    return any(a.high[i] <= b.low[i] or b.high[i] <= a.low[i] for i in (0, 1))


def _repeat_candidates(matches, deferred, atoms):
    """Use only independent, already confirmed glyphs; never feed back new ones."""
    prototypes = defaultdict(list)
    for match in matches:
        if match.template.admission != "shx_stroke_boundary_layout_consensus":
            continue
        for cid in match.font_catalog_ids:
            bucket = prototypes[cid, match.char]
            if len(bucket) >= 8 or any(
                not _separate_locations(match, ref) for ref, _ in bucket
            ):
                continue
            normal, _, _ = _normalise(
                _join_stroke_paths([p for a in match.atoms for p in a.paths])
            )
            bucket.append((match, normal))
    used = {i for m in matches for i in range(m.start, m.end)}
    added, evidence = [], []
    for match, proof in deferred:
        if any(i in used for i in range(match.start, match.end)):
            continue
        normal, _, extent = _normalise(
            _join_stroke_paths([p for a in match.atoms for p in a.paths])
        )
        admitted = {}
        supports = []
        for cid in match.font_catalog_ids:
            catalog = proof[cid][0]
            if not _whole_cell(
                match, atoms, catalog, {(match.start, match.end, match.char): proof}
            ):
                continue
            votes = [
                ref
                for ref, paths in prototypes[cid, match.char]
                if _separate_locations(match, ref)
                and _stroke_paths_agree(
                    normal, paths, extent[0] / extent[1], match.font_vector_error_limit
                )
            ]
            if len(votes) < 2:
                continue
            admitted[cid] = proof[cid]
            supports.append(
                {
                    "catalog_id": cid,
                    "reference_source_handles": [
                        [a.entity.dxf.handle for a in ref.atoms] for ref in votes
                    ],
                    "reference_source_spans": [
                        [ref.atoms[0].source_ref[2], ref.atoms[-1].source_ref[2]]
                        for ref in votes
                    ],
                }
            )
        if not admitted:
            continue
        candidate = replace(
            match,
            font_catalog_ids=tuple(sorted(admitted)),
            font_vector_error=max(p[2] for p in admitted.values()),
        )
        added.append((candidate, admitted))
        evidence.append(
            {
                "text": match.char,
                "source_handles": [a.entity.dxf.handle for a in match.atoms],
                "source_span": [
                    match.atoms[0].source_ref[2],
                    match.atoms[-1].source_ref[2],
                ],
                "boundary_error": candidate.font_vector_error,
                "error_limit": match.font_vector_error_limit,
                "method": "independent_preconfirmed_path_bijection",
                "supports": supports,
                "span_key": [match.start, match.end, match.char],
            }
        )
    return added, evidence


def _admit_isolated(matches, singletons, proofs, atoms, references, metrics):
    """Confirm complete isolated Han from two earlier occurrences, not neighbours."""
    from .font_catalog import is_han_character

    locked = {row["catalog_id"] for row in metrics["font_vector_evidence"]}
    used = {i for m in matches for i in range(m.start, m.end)}
    pending = []
    for cid in locked:
        for match in singletons[cid]:
            if (
                not is_han_character(match.char)
                or not match.font_vector_grid_pitch
                or len(locked.intersection(match.font_catalog_ids)) != 1
                or any(i in used for i in range(match.start, match.end))
            ):
                continue
            proof = proofs[match.start, match.end, match.char]
            pending.append(
                (replace(match, font_catalog_ids=(cid,)), {cid: proof[cid]})
            )
    evidence = []
    added = []
    for candidate, proof in pending:
        # A source-order cap can be filled by a different printed size or pen
        # partition. Prioritise comparable ink height, never Unicode scores;
        # the same eight-independent-reference cap and geometry budget remain.
        seeds = sorted(
            (
                m for m in references
                if m.char == candidate.char
                and m.atoms[0].source_ref[:2] == candidate.atoms[0].source_ref[:2]
            ),
            key=lambda m: abs(np.log(m.height / candidate.height)),
        )
        supported, details = _repeat_candidates(seeds, [(candidate, proof)], atoms)
        for (match, proof), detail in zip(supported, details):
            catalog = next(iter(proof.values()))[0]
            layout = _placement(match, catalog, proofs)
            if layout is None or not 0.2 <= layout[1] <= 3:
                continue
            added.append(
                replace(
                    match,
                    font_vector_layout=layout,
                    template=replace(
                        match.template,
                        support_locations=min(
                            len(s["reference_source_spans"]) for s in detail["supports"]
                        ),
                        admission="shx_stroke_isolated_repeat_consensus",
                    ),
                )
            )
            evidence.append(
                {
                    **{k: v for k, v in detail.items() if k != "span_key"},
                    "grid_pitch": match.font_vector_grid_pitch,
                    "layout": list(layout),
                    "source_layer": match.atoms[0].layer,
                    "reference_policy": "previous_strict_rows_same_source_page",
                    "reference_selection": "nearest_ink_height_before_independent_cap",
                }
            )
    metrics["font_stroke_isolated_glyph_matches"] = len(added)
    metrics["font_stroke_isolated_evidence"] = evidence[:200]
    result = sorted([*matches, *added], key=lambda m: m.start)
    metrics["font_stroke_glyph_matches"] = metrics["font_vector_glyph_matches"] = len(result)
    return result


def _spaced_matches(matches, candidates, proofs, atoms, catalogs, locked):
    """Measure real uniform tracking, retaining each glyph as separate TEXT."""
    used = {i for m in matches for i in range(m.start, m.end)}
    proposals = []
    for catalog in catalogs:
        if catalog.catalog_id not in locked:
            continue
        spans = [
            m
            for m in candidates
            if catalog.catalog_id in m.font_catalog_ids
            and not any(i in used for i in range(m.start, m.end))
            and _whole_cell(m, atoms, catalog, proofs)
        ]
        starts = defaultdict(list)
        for i, m in enumerate(spans):
            starts[m.start].append(i)
        forward, backward = defaultdict(list), defaultdict(list)
        for i, a in enumerate(spans):
            for j in starts.get(a.end, []):
                if _adjacent(a, spans[j], catalog, proofs, spaced=True):
                    forward[i].append(j)
                    backward[j].append(i)
        for i in range(len(spans)):
            if backward[i]:
                continue
            indices = [i]
            while len(forward[indices[-1]]) == 1:
                j = forward[indices[-1]][0]
                if len(backward[j]) != 1 or len(indices) >= MAX_ROW_GLYPHS:
                    break
                indices.append(j)
            if forward[indices[-1]]:
                continue
            row = [spans[j] for j in indices]
            model = _row_model(row, catalog, proofs, spaced=True)
            if model is not None:
                proposals.append((catalog, row, model))
    additions = {}
    evidence = []
    for i, (catalog, row, model) in enumerate(proposals):
        keys = {(m.start, m.end, m.char) for m in row}
        if any(
            any(a.start < b.end and b.start < a.end for a in row for b in other)
            and keys != {(m.start, m.end, m.char) for m in other}
            for j, (_, other, _) in enumerate(proposals)
            if i != j
        ):
            continue
        advance = 0.0
        for position, m in enumerate(row):
            index = proofs[m.start, m.end, m.char][catalog.catalog_id][1]
            step = float(catalog.arrays["metrics.npy"][index, 4])
            layout = (
                model[4],
                model[1] / model[4],
                model[0] + advance * model[1] + position * model[2],
                model[3],
                step * model[1],
            )
            advance += step
            additions.setdefault(
                (m.start, m.end, m.char),
                replace(
                    m,
                    font_catalog_ids=(catalog.catalog_id,),
                    font_vector_layout=layout,
                    template=replace(
                        m.template, admission="shx_stroke_spaced_row_consensus"
                    ),
                ),
            )
        if len(evidence) < 200:
            evidence.append(
                {
                    "text": "".join(m.char for m in row),
                    "catalog_id": catalog.catalog_id,
                    "tracking_dxf_units": model[2],
                    "layout_model": list(model),
                    "distinct_han": len({m.char for m in row}),
                    "source_spans": [
                        [m.atoms[0].source_ref[2], m.atoms[-1].source_ref[2]]
                        for m in row
                    ],
                    "output_policy": "separate_TEXT_preserving_observed_ink_bounds",
                }
            )
    return list(additions.values()), evidence


def recover_stroke_matches(
    atoms, source_entities, catalogs, occupied, entries, *, paper_mm, _prepared=None
):
    metrics = {
        "font_stroke_windows_scanned": 0,
        "font_stroke_geometry_policy": "complete_ink_network_v1",
        "font_stroke_candidate_glyphs": 0,
        "font_stroke_cell_fragments_rejected": 0,
        "font_stroke_conflicting_rows_rejected": 0,
        "font_stroke_glyph_matches": 0,
        "font_stroke_anchored_single_glyphs": 0,
        "font_stroke_single_anchor_evidence": [],
        "font_stroke_deferred_candidate_glyphs": 0,
        "font_stroke_repeat_glyph_matches": 0,
        "font_stroke_repeat_evidence": [],
        "font_stroke_spaced_glyph_matches": 0,
        "font_stroke_spaced_row_evidence": [],
        "font_stroke_isolated_glyph_matches": 0,
        "font_stroke_isolated_evidence": [],
        "font_vector_glyph_matches": 0,
        "font_vector_candidate_glyphs": 0,
        "font_vector_ambiguous_glyphs": 0,
        "font_vector_locked_catalogs": 0,
        "font_vector_evidence": [],
    }
    maximum_source = min(
        128, 2 * max(int(c.font["max_source_paths"]) for c in catalogs)
    )
    groups = defaultdict(list)
    for atom in atoms:
        if atom.entity.dxftype() != "HATCH":
            groups[atom.source_ref].append(atom)
    whole = {
        ref: _whole_source(group, source_entities) for ref, group in groups.items()
    }
    candidates, proofs, deferred = [], {}, []
    if _prepared is not None:
        candidates, proofs, scan_metrics = _prepared
        metrics.update(scan_metrics)
    for start, first in enumerate(atoms if _prepared is None else []):
        if first.entity.dxftype() == "HATCH":
            break
        if (
            start in occupied
            or not whole[first.source_ref]
            or (start and atoms[start - 1].source_ref == first.source_ref)
        ):
            continue
        lo = first.low.copy()
        hi = first.high.copy()
        previous = first.source_ref
        for end in range(start, min(len(atoms), start + maximum_source)):
            atom = atoms[end]
            if (
                atom.entity.dxftype() == "HATCH"
                or end in occupied
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
            lo = np.minimum(lo, atom.low)
            hi = np.maximum(hi, atom.high)
            if max(hi - lo) > 12:
                break
            if end + 1 < len(atoms) and atoms[end + 1].source_ref == atom.source_ref:
                continue
            metrics["font_stroke_windows_scanned"] += 1
            result = _candidate_group(
                atoms[start : end + 1],
                catalogs,
                metrics,
                paper_mm=paper_mm,
                deferred=deferred,
            )
            if result is None:
                continue
            match, evidence = result
            candidates.append(match)
            proofs[match.start, match.end, match.char] = evidence
    metrics["font_stroke_candidate_glyphs"] = metrics[
        "font_vector_candidate_glyphs"
    ] = len(candidates)
    rows = []
    singletons = defaultdict(list)
    for catalog in catalogs:
        spans = [m for m in candidates if catalog.catalog_id in m.font_catalog_ids]
        complete = [m for m in spans if _whole_cell(m, atoms, catalog, proofs)]
        metrics["font_stroke_cell_fragments_rejected"] += len(spans) - len(complete)
        spans = complete
        starts = defaultdict(list)
        for i, m in enumerate(spans):
            starts[m.start].append(i)
        forward = defaultdict(list)
        backward = defaultdict(list)
        for i, a in enumerate(spans):
            for j in starts.get(a.end, []):
                if _adjacent(a, spans[j], catalog, proofs):
                    forward[i].append(j)
                    backward[j].append(i)
        for i, match in enumerate(spans):
            if (
                not forward[i]
                and not backward[i]
                and not any(
                    other is not match
                    and other.start < match.end
                    and match.start < other.end
                    for other in spans
                )
            ):
                singletons[catalog.catalog_id].append(match)
        for i in range(len(spans)):
            if backward[i]:
                continue
            indices = [i]
            while len(forward[indices[-1]]) == 1:
                j = forward[indices[-1]][0]
                if len(backward[j]) != 1 or len(indices) >= MAX_ROW_GLYPHS:
                    break
                indices.append(j)
            if forward[indices[-1]]:
                continue
            row = [spans[j] for j in indices]
            if len({m.char for m in row}) < 2 or not _coherent(row, catalog, proofs):
                continue
            if not all(_whole_cell(m, atoms, catalog, proofs) for m in row):
                metrics["font_stroke_cell_fragments_rejected"] += 1
                continue
            rows.append((catalog, row))
    # Competing coherent interpretations are rejected across all supplied fonts.
    rejected = set()
    by_start = sorted(range(len(rows)), key=lambda i: rows[i][1][0].start)
    for pos, i in enumerate(by_start):
        a = rows[i][1]
        ak = {(m.start, m.end, m.char) for m in a}
        for j in by_start[pos + 1 :]:
            b = rows[j][1]
            if b[0].start >= a[-1].end:
                break
            bk = {(m.start, m.end, m.char) for m in b}
            overlap_a = {
                key for key in ak if any(x < key[1] and key[0] < y for x, y, _ in bk)
            }
            overlap_b = {
                key for key in bk if any(x < key[1] and key[0] < y for x, y, _ in ak)
            }
            if overlap_a != overlap_b:
                rejected.update((i, j))
    metrics["font_stroke_conflicting_rows_rejected"] = len(rejected)
    admitted = {}
    for catalog in catalogs:
        available = [
            r for i, (c, r) in enumerate(rows) if i not in rejected and c is catalog
        ]
        strong = [r for r in available if len({m.char for m in r}) >= 5]
        if len(strong) < 2:
            continue
        metrics["font_vector_locked_catalogs"] += 1
        evidence = {
            "catalog_id": catalog.catalog_id,
            "method": "shx_stroke_boundary_layout_consensus",
            "stroke_geometry_policy": "complete_ink_network_v1",
            "network_topology_error_multipliers": [1, 2],
            "strong_rows": len(strong),
            "runs": ["".join(m.char for m in r) for r in strong[:10]],
            "maximum_boundary_error": max(
                m.font_vector_error for r in available for m in r
            ),
        }
        metrics["font_vector_evidence"].append(evidence)
        for entry in entries:
            if entry.get("catalog_id") == catalog.catalog_id:
                entry.update(
                    status="locked",
                    locked=True,
                    lock_method=evidence["method"],
                    vector_consensus=evidence,
                )
        for row in available:
            model = _row_model(row, catalog, proofs)
            offset = 0.0
            for match in row:
                _, index, _, _ = proofs[match.start, match.end, match.char][
                    catalog.catalog_id
                ]
                advance = float(catalog.arrays["metrics.npy"][index, 4])
                layout = (
                    model[3],
                    model[1] / model[3],
                    model[0] + offset * model[1],
                    model[2],
                    advance * model[1],
                )
                offset += advance
                admitted.setdefault(
                    (match.start, match.end, match.char),
                    replace(
                        match,
                        font_catalog_ids=(catalog.catalog_id,),
                        font_vector_layout=layout,
                        font_vector_error=proofs[match.start, match.end, match.char][
                            catalog.catalog_id
                        ][2],
                        template=replace(
                            match.template,
                            support_locations=len(strong),
                            admission=evidence["method"],
                        ),
                    ),
                )
        for match in singletons[catalog.catalog_id]:
            anchored = [
                result
                for row in available
                if (
                    result := _anchored_single(
                        match, row, catalog, proofs, groups, whole
                    )
                )
                is not None
            ]
            if not anchored:
                continue
            layout, proof = min(
                anchored, key=lambda result: result[1]["maximum_layout_residual"]
            )
            if any(
                max(abs(a - b) for a, b in zip(layout, other))
                > proof["layout_error_limit"]
                for other, _ in anchored
            ):
                continue
            admitted[match.start, match.end, match.char] = replace(
                match,
                font_catalog_ids=(catalog.catalog_id,),
                font_vector_layout=layout,
                template=replace(
                    match.template,
                    support_locations=len(strong),
                    admission="shx_stroke_row_anchor_consensus",
                ),
            )
            metrics["font_stroke_anchored_single_glyphs"] += 1
            if len(metrics["font_stroke_single_anchor_evidence"]) < 200:
                metrics["font_stroke_single_anchor_evidence"].append(proof)

    matches = sorted(admitted.values(), key=lambda m: m.start)
    if _prepared is None and deferred:
        metrics["font_stroke_deferred_candidate_glyphs"] = len(deferred)
        added, repeat_evidence = _repeat_candidates(matches, deferred, atoms)
        if added:
            retry_proofs = dict(proofs)
            for m, proof in added:
                retry_proofs[m.start, m.end, m.char] = proof
            scan_metrics = {
                key: metrics[key]
                for key in (
                    "font_stroke_windows_scanned",
                    "font_vector_ambiguous_glyphs",
                    "font_stroke_deferred_candidate_glyphs",
                )
            }
            retry, retry_metrics = recover_stroke_matches(
                atoms,
                source_entities,
                catalogs,
                occupied,
                entries,
                paper_mm=paper_mm,
                _prepared=(
                    [*candidates, *(m for m, _ in added)],
                    retry_proofs,
                    scan_metrics,
                ),
            )
            keys = {tuple(e["span_key"]) for e in repeat_evidence}
            accepted_keys = {(m.start, m.end, m.char) for m in retry} & keys
            retry = [
                replace(
                    m,
                    template=replace(
                        m.template,
                        admission="shx_stroke_repeat_boundary_layout_consensus",
                    ),
                )
                if (m.start, m.end, m.char) in accepted_keys
                and m.template.admission == "shx_stroke_boundary_layout_consensus"
                else m
                for m in retry
            ]
            retry_metrics["font_stroke_repeat_glyph_matches"] = len(accepted_keys)
            retry_metrics["font_stroke_repeat_evidence"] = [
                {k: v for k, v in e.items() if k != "span_key"}
                for e in repeat_evidence
                if tuple(e["span_key"]) in accepted_keys
            ][:200]
            # Only the original strict rows may seed isolated characters;
            # neither this retry's new glyphs nor single anchors may bootstrap.
            retry = _admit_isolated(
                retry, singletons, proofs, atoms, matches, retry_metrics
            )
            return retry, retry_metrics
    spaced, spacing_evidence = _spaced_matches(
        matches,
        candidates,
        proofs,
        atoms,
        catalogs,
        {r["catalog_id"] for r in metrics["font_vector_evidence"]},
    )
    matches = sorted([*matches, *spaced], key=lambda m: m.start)
    metrics["font_stroke_spaced_glyph_matches"] = len(spaced)
    metrics["font_stroke_spaced_row_evidence"] = spacing_evidence
    metrics["font_stroke_glyph_matches"] = metrics["font_vector_glyph_matches"] = len(
        matches
    )
    if _prepared is None:
        matches = _admit_isolated(matches, singletons, proofs, atoms, matches, metrics)
    return matches, metrics
