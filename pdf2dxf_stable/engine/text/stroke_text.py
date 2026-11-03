"""Match complete SHX stroke glyphs in saved DXF, without pixels or fonts."""

from collections import defaultdict
from dataclasses import replace

import numpy as np

from .vector_text import _adjacent, _candidate_group, _placement
from .vector_catalog import _join_stroke_paths

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


def _row_model(row, catalog, proofs):
    # One affine placement for the whole row prevents accumulated per-glyph
    # scale noise. Fit all ink bounds, without adding tracking or missing text.
    x, y, observed_x, observed_y = [], [], [], []
    advance = 0.0
    for match in row:
        _, index, _, _ = proofs[match.start, match.end, match.char][catalog.catalog_id]
        x0, y0, x1, y1, step = map(float, catalog.arrays["metrics.npy"][index])
        x.extend(((1, advance + x0), (1, advance + x1)))
        y.extend(((1, y0), (1, y1)))
        observed_x.extend((match.low[0], match.high[0]))
        observed_y.extend((match.low[1], match.high[1]))
        advance += step
    x, y = np.asarray(x), np.asarray(y)
    a = np.linalg.lstsq(x, observed_x, rcond=None)[0]
    b = np.linalg.lstsq(y, observed_y, rcond=None)[0]
    if not 0 < b[1] or not 0.2 <= a[1] / b[1] <= 3:
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


def recover_stroke_matches(
    atoms, source_entities, catalogs, occupied, entries, *, paper_mm
):
    metrics = {
        "font_stroke_windows_scanned": 0,
        "font_stroke_candidate_glyphs": 0,
        "font_stroke_cell_fragments_rejected": 0,
        "font_stroke_conflicting_rows_rejected": 0,
        "font_stroke_glyph_matches": 0,
        "font_vector_glyph_matches": 0,
        "font_vector_candidate_glyphs": 0,
        "font_vector_ambiguous_glyphs": 0,
        "font_vector_locked_catalogs": 0,
        "font_vector_evidence": [],
    }
    counts = {int(n) for c in catalogs for n in np.diff(c.arrays["glyph_offsets.npy"])}
    maximum = max(counts)
    maximum_source = min(
        128, max(int(c.font.get("max_source_paths", maximum * 2)) for c in catalogs)
    )
    groups = defaultdict(list)
    for atom in atoms:
        if atom.entity.dxftype() != "HATCH":
            groups[atom.source_ref].append(atom)
    whole = {
        ref: _whole_source(group, source_entities) for ref, group in groups.items()
    }
    candidates = []
    proofs = {}
    for start, first in enumerate(atoms):
        if first.entity.dxftype() == "HATCH":
            break
        if (
            start in occupied
            or not whole[first.source_ref]
            or (start and atoms[start - 1].source_ref == first.source_ref)
        ):
            continue
        paths = []
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
            paths.extend(atom.paths)
            lo = np.minimum(lo, atom.low)
            hi = np.maximum(hi, atom.high)
            joined_count = len(_join_stroke_paths(paths))
            if joined_count > maximum or max(hi - lo) > 12:
                break
            if joined_count not in counts or (
                end + 1 < len(atoms) and atoms[end + 1].source_ref == atom.source_ref
            ):
                continue
            metrics["font_stroke_windows_scanned"] += 1
            result = _candidate_group(
                atoms[start : end + 1], catalogs, metrics, paper_mm=paper_mm
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

    matches = sorted(admitted.values(), key=lambda m: m.start)
    metrics["font_stroke_glyph_matches"] = metrics["font_vector_glyph_matches"] = len(
        matches
    )
    return matches, metrics
