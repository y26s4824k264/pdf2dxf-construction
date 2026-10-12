"""PDF dash state and exact sub-curves for phase-sensitive strokes.

DXF simple linetypes have no dash-phase field. Materialize painted intervals
before clipping, retaining cubic control points rather than flattening curves.
"""

from __future__ import annotations

import math
import re

MAX_DASH_INTERVALS = 100_000


def parse_dash(spec):
    if not spec:
        return (), 0.0
    match = re.fullmatch(r"\s*\[([^]]*)\]\s*([^\s]+)\s*", str(spec))
    if match is None:
        raise ValueError("PDF_DASH_INVALID")
    values = tuple(float(v) for v in match[1].replace(",", " ").split())
    phase = float(match[2])
    if (
        not math.isfinite(phase)
        or phase < 0
        or any(not math.isfinite(v) or v < 0 for v in values)
    ):
        raise ValueError("PDF_DASH_INVALID")
    if not values:
        return (), 0.0
    if not sum(values) > 0:
        raise ValueError("PDF_DASH_INVALID")
    if len(values) % 2:
        values *= 2
    return values, phase % sum(values)


def _lerp(a, b, t):
    return tuple(x + (y - x) * t for x, y in zip(a, b))


def _split(seg, t):
    a, b, c = (
        _lerp(x, y, t)
        for x, y in ((seg.p0, seg.c1), (seg.c1, seg.c2), (seg.c2, seg.p1))
    )
    d, e = _lerp(a, b, t), _lerp(b, c, t)
    point = _lerp(d, e, t)
    return type(seg)(seg.p0, a, d, point), type(seg)(point, e, c, seg.p1)


def _length(seg, t=1.0):
    if not hasattr(seg, "c1"):
        return math.dist(seg.p0, seg.p1) * t
    from scipy.integrate import quad

    points = (seg.p0, seg.c1, seg.c2, seg.p1)

    def speed(u):
        weights = ((1 - u) ** 2, 2 * (1 - u) * u, u * u)
        return math.hypot(
            *(
                sum(
                    3 * weights[i] * (points[i + 1][axis] - points[i][axis])
                    for i in range(3)
                )
                for axis in (0, 1)
            )
        )

    length, error = quad(speed, 0, t, epsabs=1e-7, epsrel=1e-10, limit=64)
    if not math.isfinite(length) or error > 1e-5:
        raise ValueError("PDF_DASH_CURVE_LENGTH_UNCONFIRMED")
    return length


def _portion(seg, start, end, length):
    if not hasattr(seg, "c1"):
        return type(seg)(
            _lerp(seg.p0, seg.p1, start / length), _lerp(seg.p0, seg.p1, end / length)
        )
    from scipy.optimize import brentq

    def parameter(distance):
        if distance <= 1e-10:
            return 0.0
        if distance >= length - 1e-10:
            return 1.0
        return brentq(lambda t: _length(seg, t) - distance, 0, 1, xtol=1e-12)

    a, b = parameter(start), parameter(end)
    left = _split(seg, b)[0] if b < 1 else seg
    return _split(left, a / b)[1] if a > 0 else left


def dashed_chains(chains, values, phase):
    from .base import LineSeg, PathChain

    count = 0
    for chain in chains:
        segments = list(chain.segments)
        if chain.closed and segments and math.dist(chain.end, chain.start) > 1e-10:
            segments.append(LineSeg(chain.end, chain.start))
        index, offset = 0, phase
        while offset > 0 and offset >= values[index]:
            offset -= values[index]
            index = (index + 1) % len(values)
            if offset == 0:
                break
        remaining = values[index] - offset
        run = []
        for seg in segments:
            length = _length(seg)
            if length <= 1e-10:
                continue
            position = 0.0
            while position < length - 1e-10:
                if remaining <= 1e-10:
                    if run:
                        yield PathChain(run)
                        run = []
                    # A zero-length on interval is a PDF line-cap dot.
                    if values[index] == 0 and index % 2 == 0:
                        point = _portion(seg, position, position, length).p0
                        end = _portion(
                            seg, position, min(length, position + 1e-5), length
                        ).p1
                        yield PathChain(
                            [LineSeg(point, point)],
                            dot_direction=(end[0] - point[0], end[1] - point[1]),
                        )
                    index = (index + 1) % len(values)
                    remaining = values[index]
                    count += 1
                    if count > MAX_DASH_INTERVALS:
                        raise ValueError("PDF_DASH_INTERVAL_LIMIT")
                    continue
                step = min(remaining, length - position)
                if index % 2 == 0:
                    run.append(_portion(seg, position, position + step, length))
                position += step
                remaining -= step
        if run:
            yield PathChain(run)
        # A round/square dot exactly at an open path's endpoint is still paint.
        if segments and not chain.closed and remaining <= 1e-10:
            index = (index + 1) % len(values)
            while values[index] == 0:
                if index % 2 == 0:
                    point = segments[-1].p1
                    previous = getattr(segments[-1], "c2", segments[-1].p0)
                    yield PathChain(
                        [LineSeg(point, point)],
                        dot_direction=(point[0] - previous[0], point[1] - previous[1]),
                    )
                index = (index + 1) % len(values)
