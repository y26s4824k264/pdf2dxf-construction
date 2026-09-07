"""Local, unambiguous dimension chains on persisted paper-mm geometry."""

import math

ENDPOINT_TOLERANCE = 0.07
MAX_LEVEL_TEXT_HEIGHTS = 12
# Real basement/grid chains contain 17-24 parts. Keep a finite traversal budget
# without truncating those ordinary chains at the former twelve-part cutoff.
MAX_CHAIN_PARTS = 64
MAX_SEARCH_STEPS = 2000


def _find_chain(parts, start, end, axis):
    """Find up to two geometric solutions; never select one by its label sum."""
    solutions = []
    remaining = MAX_SEARCH_STEPS
    exhausted = False
    parts = sorted(parts, key=lambda a: (a["p0"][axis], a["p1"][axis], a["id"]))

    def follow(position, path):
        nonlocal remaining, exhausted
        if remaining <= 0:
            exhausted = True
            return
        remaining -= 1
        if abs(position - end) < ENDPOINT_TOLERANCE and len(path) >= 2:
            solutions.append(path)
            return
        following = [
            p
            for p in parts
            if abs(p["p0"][axis] - position) < ENDPOINT_TOLERANCE
            and p["p1"][axis] > position + ENDPOINT_TOLERANCE
        ]
        if len(path) >= MAX_CHAIN_PARTS:
            exhausted |= bool(following)
            return
        for part in following:
            follow(part["p1"][axis], [*path, part])
            if len(solutions) >= 2 or exhausted:
                return

    follow(start, [])
    return solutions, exhausted


def find_chains(anchors):
    """Parts share a layer and baseline; the total must be a nearby chain level.

    Twelve text heights is a conservative locality cap, not a guessed viewport
    boundary. More distant levels require review even when projected sums agree.
    """
    anchors = [
        a
        for a in anchors
        if a["axis"] in ("x", "y")
        and all(
            math.isfinite(v)
            for v in (*a["p0"], *a["p1"], a["label_mm"], a["text_height"])
        )
        and a["label_mm"] > 0
        and a["text_height"] > 0
        and abs(
            a["p1"][1 if a["axis"] == "x" else 0]
            - a["p0"][1 if a["axis"] == "x" else 0]
        )
        < ENDPOINT_TOLERANCE
    ]
    chains = []
    for total in anchors:
        axis = 0 if total["axis"] == "x" else 1
        start, end = total["p0"][axis], total["p1"][axis]
        cross = total["p0"][1 - axis]
        parts = [
            a
            for a in anchors
            if a["axis"] == total["axis"]
            and 0 < a["p1"][axis] - a["p0"][axis] < (end - start) * 0.95
            and a["p0"][axis] >= start - ENDPOINT_TOLERANCE
            and a["p1"][axis] <= end + ENDPOINT_TOLERANCE
            and abs(a["p1"][1 - axis] - a["p0"][1 - axis]) < ENDPOINT_TOLERANCE
            and abs(a["p0"][1 - axis] - cross)
            <= MAX_LEVEL_TEXT_HEIGHTS * max(a["text_height"], total["text_height"])
        ]
        groups = []
        for part in sorted(
            parts,
            key=lambda a: (a.get("dimension_layer", ""), a["p0"][1 - axis], a["id"]),
        ):
            if (
                not groups
                or part.get("dimension_layer") != groups[-1][0].get("dimension_layer")
                or part["p0"][1 - axis] - groups[-1][0]["p0"][1 - axis]
                >= ENDPOINT_TOLERANCE
            ):
                groups.append([])
            groups[-1].append(part)
        for group in groups:
            solutions, exhausted = _find_chain(group, start, end, axis)
            if not solutions and not exhausted:
                continue
            unique = len(solutions) == 1 and not exhausted
            found = solutions[0] if unique else []
            value = sum(a["label_mm"] for a in found)
            error = (
                abs(value - total["label_mm"]) / total["label_mm"] if unique else None
            )
            chains.append(
                {
                    "total": total["id"],
                    "parts": [a["id"] for a in found],
                    "total_mm": total["label_mm"],
                    "parts_sum_mm": value if unique else None,
                    "relative_error": error,
                    "passed": unique and error <= 0.002,
                    "reason": "search_limit"
                    if exhausted
                    else "ambiguous_geometry"
                    if not unique
                    else "closed"
                    if error <= 0.002
                    else "label_sum_mismatch",
                    "part_baseline_paper_mm": group[0]["p0"][1 - axis],
                    "part_layer": group[0].get("dimension_layer"),
                    "total_layer": total.get("dimension_layer"),
                    "level_separation_paper_mm": abs(cross - group[0]["p0"][1 - axis]),
                }
            )
    return chains
