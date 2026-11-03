"""Bounded vector comparison of complete saved-DXF fill operations."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
import hashlib

import numpy as np

from .vector_catalog import (
    MAX_BOUNDARY_ERROR,
    MAX_GRID_BOUNDARY_ERROR,
    VectorFontCatalog,
)


def _printer_grid(points, *, paper_mm, minimum_vertices=12):
    """Admit a printer grid only when every saved vertex supports its lattice."""
    if not paper_mm or len(points) < minimum_vertices:
        return 0.0
    if minimum_vertices < 12 and len(np.unique(points, axis=0)) < minimum_vertices:
        return 0.0
    if any(len(np.unique(points[:, axis])) < 4 for axis in (0, 1)):
        return 0.0
    pitch = 25.4 / 600
    lattice = (points - points[0]) / pitch
    return pitch if np.max(np.abs(lattice - np.rint(lattice))) <= 0.003 else 0.0


def recover_vector_matches(
    atoms,
    source_entities,
    catalogs: list[VectorFontCatalog],
    occupied,
    entries,
    *,
    paper_mm=False,
):
    metrics = {
        "font_vector_candidate_glyphs": 0,
        "font_vector_glyph_matches": 0,
        "font_vector_ambiguous_glyphs": 0,
        "font_vector_locked_catalogs": 0,
        "font_vector_evidence": [],
        "font_vector_boundary_error_limit": MAX_BOUNDARY_ERROR,
        "font_vector_grid_error_cap": MAX_GRID_BOUNDARY_ERROR,
    }
    if not catalogs:
        return [], metrics
    fill_catalogs = [
        c
        for c in catalogs
        if c.manifest["outline_policy"] == "nonzero_filled_boundaries_v1"
    ]
    stroke_catalogs = [
        c for c in catalogs if c.manifest["outline_policy"] == "open_stroke_paths_v1"
    ]
    groups = defaultdict(list)
    for atom in atoms:
        if atom.entity.dxftype() == "HATCH":
            groups[atom.source_ref].append(atom)
    candidates = []
    proofs = {}
    for ref, group in groups.items():
        indices = [a.sequence_index for a in group]
        if any(i in occupied for i in indices) or indices != list(
            range(indices[0], indices[-1] + 1)
        ):
            continue
        # Never recognise a surviving fragment of a larger/unsupported paint.
        if {a.entity.dxf.handle for a in group} != {
            e.dxf.handle for e in source_entities[ref]
        }:
            continue
        if len({a.layer for a in group}) != 1:
            continue
        result = _candidate_group(group, fill_catalogs, metrics, paper_mm=paper_mm)
        if result is None:
            continue
        match, proof = result
        candidates.append(match)
        proofs[match.start, match.end, match.char] = proof
    metrics["font_vector_candidate_glyphs"] = len(candidates)

    admitted = {}
    for catalog in fill_catalogs:
        # Independent adjacent rows are required; a lone drawing symbol or a
        # single short phrase cannot bootstrap this geometric fallback.
        spans = [m for m in candidates if catalog.catalog_id in m.font_catalog_ids]
        runs, current = [], []
        for match in spans:
            if current and not _adjacent(current[-1], match, catalog, proofs):
                runs.append(current)
                current = []
            current.append(match)
        if current:
            runs.append(current)
        qualifying = [r for r in runs if len({m.char for m in r}) >= 5]
        if len(qualifying) < 2:
            continue
        metrics["font_vector_locked_catalogs"] += 1
        evidence = {
            "catalog_id": catalog.catalog_id,
            "method": "font_vector_boundary_run_consensus",
            "runs": ["".join(m.char for m in r)[:96] for r in qualifying[:10]],
            "maximum_boundary_error": max(
                m.font_vector_error for r in qualifying for m in r
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
        for run in qualifying:
            for match in run:
                admitted[match.start] = replace(
                    match,
                    template=replace(
                        match.template,
                        support_locations=len(qualifying),
                        admission="font_vector_boundary_run_consensus",
                    ),
                )
    matches = sorted(admitted.values(), key=lambda m: m.start)
    metrics["font_vector_glyph_matches"] = len(matches)
    if stroke_catalogs:
        from .stroke_text import recover_stroke_matches

        stroke_matches, stroke_metrics = recover_stroke_matches(
            atoms,
            source_entities,
            stroke_catalogs,
            occupied,
            entries,
            paper_mm=paper_mm,
        )
        matches = sorted([*matches, *stroke_matches], key=lambda m: m.start)
        for key, value in stroke_metrics.items():
            if (
                key in metrics
                and isinstance(value, (int, float))
                and not isinstance(value, bool)
            ):
                metrics[key] += value
            elif key == "font_vector_evidence":
                metrics[key].extend(value)
            else:
                metrics[key] = value
    return matches, metrics


def _adjacent(a, b, catalog, proofs, *, spaced=False):
    if a.end != b.start or a.atoms[-1].layer != b.atoms[0].layer:
        return False
    aa, bb = a.atoms[-1].source_ref, b.atoms[0].source_ref
    if aa[:2] != bb[:2] or bb[2] - aa[2] != 1:
        return False

    x, y = _placement(a, catalog, proofs), _placement(b, catalog, proofs)
    if x is None or y is None:
        return False
    em = min(x[0], y[0])
    pitch = min(a.font_vector_grid_pitch or 0, b.font_vector_grid_pitch or 0)
    return (
        abs(x[0] - y[0]) <= max(0.02 * em, 2 * pitch)
        and abs(x[1] - y[1])
        <= max(
            0.03, min(0.1, 2 * pitch / min(a.high[0] - a.low[0], b.high[0] - b.low[0]))
        )
        * min(x[1], y[1])
        and abs(x[3] - y[3]) <= max(0.015 * em, 2 * pitch)
        and (
            0.05 * em <= y[2] - x[2] - x[4] <= em
            if spaced
            else abs(y[2] - x[2] - x[4]) <= max(0.025 * em, 2 * pitch)
        )
    )


def _candidate_group(group, catalogs, metrics, *, paper_mm, deferred=None):
    from .outline_text import GlyphMatch, GlyphTemplate

    indices = [a.sequence_index for a in group]
    paths = [p for a in group for p in a.paths]
    if not paths or len(paths) > 128 or sum(map(len, paths)) > 8192:
        return None
    points = np.vstack(paths)
    low, high = points.min(0), points.max(0)
    extent = high - low
    if not 0.08 <= extent.min() or extent.max() > 12:
        return None
    stroke_catalogs = all(
        c.manifest["outline_policy"] == "open_stroke_paths_v1" for c in catalogs
    )
    pitch = _printer_grid(
        points, paper_mm=paper_mm, minimum_vertices=8 if stroke_catalogs else 12
    )
    # Independent pixel errors in X/Y require an Euclidean diagonal budget.
    grid_factor = (
        np.sqrt(2.0)
        if all(c.manifest["outline_policy"] == "open_stroke_paths_v1" for c in catalogs)
        else 1.0
    )
    error_limit = (
        max(
            MAX_BOUNDARY_ERROR,
            min(
                MAX_GRID_BOUNDARY_ERROR, grid_factor * pitch / float(extent[1]) + 0.001
            ),
        )
        if pitch
        else MAX_BOUNDARY_ERROR
    )
    predictions = []
    weak_predictions = []
    allow_deferred = deferred is not None and stroke_catalogs and bool(pitch)
    overloaded = False
    for catalog in catalogs:
        weak = []
        result = (
            catalog.candidates(paths, max_error=error_limit, deferred=weak)
            if allow_deferred
            else catalog.candidates(paths, max_error=error_limit)
        )
        if result is None:
            overloaded = True
            break
        predictions.extend((catalog, *r) for r in result)
        weak_predictions.extend((catalog, *r) for r in weak)
    labels = {p[1] for p in predictions}
    if overloaded or len(labels) > 1:
        metrics["font_vector_ambiguous_glyphs"] += 1
        return None
    pending = False
    if not labels:
        weak_labels = {p[1] for p in weak_predictions}
        if not allow_deferred or len(weak_labels) != 1:
            if len(weak_labels) > 1:
                metrics["font_vector_ambiguous_glyphs"] += 1
            return None
        predictions, labels, pending = weak_predictions, weak_labels, True
    char = labels.pop()
    by_catalog = {}
    for catalog, _, row, error, width in predictions:
        old = by_catalog.get(catalog.catalog_id)
        if old is None or error < old[2]:
            by_catalog[catalog.catalog_id] = (catalog, row, error, width)
    ids = tuple(sorted(by_catalog))
    vector_digest = hashlib.sha256(
        b"".join(p.astype("<f4").tobytes() for p in paths)
    ).hexdigest()
    match = GlyphMatch(
        start=indices[0],
        end=indices[-1] + 1,
        char=char,
        low=tuple(map(float, low)),
        high=tuple(map(float, high)),
        atoms=tuple(group),
        template=GlyphTemplate(
            id=f"vector-{ids[0]}-u{ord(char):04x}",
            char=char,
            fingerprint=vector_digest,
            entity_count=len(paths),
            closed_count=sum(int(np.array_equal(p[0], p[-1])) for p in paths),
            point_counts=tuple(sorted(map(len, paths))),
            aspect_ratio=float(extent[0] / extent[1]),
            support_locations=1,
            support_documents=1,
            admission="font_vector_boundary_candidate",
        ),
        font_catalog_ids=ids,
        font_vector_error=max(v[2] for v in by_catalog.values()),
        font_vector_error_limit=error_limit,
        font_vector_grid_pitch=pitch or None,
    )
    if pending:
        deferred.append((match, by_catalog))
        return None
    return match, by_catalog


def _placement(m, catalog, proofs):
    _, row, _, width = proofs[m.start, m.end, m.char][catalog.catalog_id]
    x0, y0, x1, y1, advance = catalog.arrays["metrics.npy"][row]
    if y1 <= y0 or advance <= 0:
        return None
    em = m.height / float(y1 - y0)
    return tuple(
        map(
            float,
            (
                em,
                width,
                m.low[0] - x0 * em * width,
                m.low[1] - y0 * em,
                advance * em * width,
            ),
        )
    )
