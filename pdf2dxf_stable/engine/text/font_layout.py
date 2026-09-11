"""Resolve internal stroke conflicts using persisted font layout measurements.

This is an additional proof for horizontal, uniformly scaled Han rows. It
never reads a PDF/font, assigns an ambiguous whole-glyph label, or bridges a
source gap. Legacy catalogs simply cannot supply this proof.
"""

from __future__ import annotations

from collections import defaultdict
from bisect import bisect_left
from dataclasses import dataclass, replace
from itertools import accumulate
from typing import TYPE_CHECKING, Any
import unicodedata

from .font_catalog import is_han_character

if TYPE_CHECKING:
    from .font_catalog import FontGlyphCatalog
    from .outline_text import GlyphMatch, OutlineAtom, _FontScanContext

# Bounds from flattened DXF curves may differ slightly from exact font extrema.
LAYOUT_TOLERANCE_EM = 0.01
MAX_LAYOUT_ROW_GLYPHS = 96


@dataclass(frozen=True)
class _Placement:
    match: GlyphMatch
    em: float
    origin: float
    baseline: float
    advance: float


def _placement(match: GlyphMatch, catalog: FontGlyphCatalog) -> _Placement | None:
    digests = {
        bytes.fromhex(digest)
        for cid, digest, _ in match.font_match_evidence
        if cid == catalog.catalog_id
    }
    placements = set()
    for template in catalog.templates_by_label.get(match.char, ()):
        metrics = template.layout_metrics
        if metrics is None or not digests.intersection(template.match_digests):
            continue
        x0, y0, x1, y1, advance = metrics
        if advance <= 0:
            continue
        width, height = match.high[0] - match.low[0], match.height
        # Estimate scale on the longer font axis, then check both ink extents.
        em = width / (x1 - x0) if x1 - x0 >= y1 - y0 else height / (y1 - y0)
        if (
            em <= 0
            or max(abs(width / em - (x1 - x0)), abs(height / em - (y1 - y0)))
            > LAYOUT_TOLERANCE_EM
        ):
            continue
        placements.add(
            (em, match.low[0] - x0 * em, match.low[1] - y0 * em, advance * em)
        )
    if len(placements) != 1:
        return None
    return _Placement(match, *placements.pop())


def _adjacent(left: _Placement, right: _Placement) -> bool:
    from .outline_text import MAX_SOURCE_SEQUENCE_GAP

    a, b = left.match, right.match
    if a.end != b.start or a.atoms[-1].layer != b.atoms[0].layer:
        return False
    aa, bb = a.atoms[-1], b.atoms[0]
    if (
        aa.source_ref[:2] != bb.source_ref[:2]
        or not 0 <= bb.source_ref[2] - aa.source_ref[2] <= MAX_SOURCE_SEQUENCE_GAP
        or (aa.entity.dxftype() == "HATCH") != (bb.entity.dxftype() == "HATCH")
    ):
        return False
    em = min(left.em, right.em)
    return (
        max(
            abs(left.em - right.em),
            abs(left.baseline - right.baseline),
            abs(right.origin - left.origin - left.advance),
        )
        <= LAYOUT_TOLERANCE_EM * em
    )


def resolve_font_layout_rows(
    atoms: list[OutlineAtom],
    catalogs: list[FontGlyphCatalog],
    candidates: list[GlyphMatch],
    context: _FontScanContext | None,
) -> tuple[list[GlyphMatch], dict[str, Any]]:
    from .outline_text import (
        _font_fragment_evidence,
        _font_window_evidence,
        _has_small_han_row,
    )

    metrics: dict[str, Any] = {
        "font_layout_matches": 0,
        "font_layout_evidence": [],
        "font_layout_evidence_truncated": 0,
    }
    if context is None:
        return [], metrics
    existing = {(m.start, m.end, m.char) for m in candidates}
    missing = {
        (m.start, m.end, m.char)
        for m in context.matches
        if is_han_character(m.char) and (m.start, m.end, m.char) not in existing
    }
    if not missing:
        return [], metrics
    windows_by_start = sorted(
        (*context.matches, *context.conflicts), key=lambda w: w.start
    )
    window_starts = [w.start for w in windows_by_start]
    window_ends = list(accumulate((w.end for w in windows_by_start), max))

    def overlapping(parent):
        index = bisect_left(window_starts, parent.end) - 1
        result = []
        while index >= 0 and window_ends[index] > parent.start:
            w = windows_by_start[index]
            if w is not parent and w.end > parent.start:
                result.append(w)
            index -= 1
        return sorted(result, key=lambda w: (w.start, w.end))

    restored = {}
    for catalog in catalogs:
        placements = [
            p
            for m in context.matches
            if is_han_character(m.char)
            and catalog.catalog_id in m.font_catalog_ids
            and (p := _placement(m, catalog)) is not None
        ]
        starts = defaultdict(list)
        for i, placement in enumerate(placements):
            starts[placement.match.start].append(i)
        forward, backward = defaultdict(list), defaultdict(list)
        for i, left in enumerate(placements):
            for j in starts.get(left.match.end, ()):
                if _adjacent(left, placements[j]):
                    forward[i].append(j)
                    backward[j].append(i)
        for i in range(len(placements)):
            if backward[i]:
                continue
            indices = [i]
            while len(forward[indices[-1]]) == 1:
                j = forward[indices[-1]][0]
                if len(backward[j]) != 1 or len(indices) >= MAX_LAYOUT_ROW_GLYPHS:
                    break
                indices.append(j)
            # Branching alternatives and unbounded rows require other proofs.
            if forward[indices[-1]] or len(indices) < 3:
                continue
            row = [placements[j] for j in indices]
            if len({p.match.char for p in row}) < 3:
                continue
            row_keys = {(p.match.start, p.match.end, p.match.char) for p in row}
            if not row_keys.intersection(missing) or not row_keys.intersection(
                existing
            ):
                continue
            # Bound total drift too; pairwise tolerances must not accumulate.
            first = row[0]
            if any(
                max(abs(p.em - first.em), abs(p.baseline - first.baseline))
                > LAYOUT_TOLERANCE_EM * first.em
                for p in row
            ):
                continue
            proofs = []
            valid = True
            for placement in row:
                parent = placement.match
                competitors = overlapping(parent)
                windows = [_font_window_evidence(w, atoms) for w in competitors]
                if len(windows) > 32 or _has_small_han_row(windows):
                    valid = False
                    break
                for w in windows:
                    a, b = w["span"]
                    box = w["bbox"]
                    if not (
                        parent.start <= a < b <= parent.end
                        and (a, b) != (parent.start, parent.end)
                        and parent.low[0] <= box[0] <= box[2] <= parent.high[0]
                        and parent.low[1] <= box[1] <= box[3] <= parent.high[1]
                    ):
                        valid = False
                        break
                    # Whole letters/digits and arbitrary Han are never absorbed.
                    # The Han/Bopomofo/stroke aliases below must all describe a
                    # physically thin horizontal stroke at this row's em scale.
                    line_labels = {"一", "ㄧ"}
                    labels = w["labels"]
                    if not all(
                        unicodedata.category(ch).startswith("P")
                        or ch in line_labels
                        or 0x31C0 <= ord(ch) <= 0x31EF
                        for ch in labels
                    ):
                        valid = False
                        break
                    non_punctuation = any(
                        not unicodedata.category(ch).startswith("P") for ch in labels
                    )
                    if non_punctuation and (
                        box[3] - box[1] > 0.16 * placement.em
                        or box[2] - box[0] < 3 * (box[3] - box[1])
                    ):
                        valid = False
                        break
                    if not non_punctuation and box[3] - box[1] >= 0.70 * placement.em:
                        valid = False
                        break
                if not valid:
                    break
                proofs.append(
                    {
                        **_font_fragment_evidence(parent),
                        "em": placement.em,
                        "origin_x": placement.origin,
                        "baseline_y": placement.baseline,
                        "advance": placement.advance,
                        "conflicts": windows,
                    }
                )
            if not valid:
                continue
            for p in row:
                m = p.match
                key = (m.start, m.end, m.char)
                if key in missing:
                    restored.setdefault(
                        key,
                        replace(
                            m,
                            font_catalog_ids=(catalog.catalog_id,),
                            font_match_evidence=tuple(
                                e
                                for e in m.font_match_evidence
                                if e[0] == catalog.catalog_id
                            ),
                        ),
                    )
            if len(metrics["font_layout_evidence"]) < 32:
                metrics["font_layout_evidence"].append(
                    {
                        "stage": "persisted_font_layout_consensus",
                        "catalog_id": catalog.catalog_id,
                        "text": "".join(p.match.char for p in row),
                        "maximum_error_em": LAYOUT_TOLERANCE_EM,
                        "glyphs": proofs,
                    }
                )
            else:
                metrics["font_layout_evidence_truncated"] += 1
    metrics["font_layout_matches"] = len(restored)
    return sorted(restored.values(), key=lambda m: m.start), metrics
