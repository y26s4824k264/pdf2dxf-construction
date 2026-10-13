"""PDF stroke state and bounded paint outlines, independent of DXF lineweight.

Native centerlines remain in the DXF for geometry and dimension evidence. The
paint envelope is a separate HATCH, so caps, joins and clipping do not depend on
a CAD viewer's global lineweight settings. Curves use a declared error bound.
"""

from __future__ import annotations

import math

from shapely.affinity import affine_transform
from shapely.geometry import LineString, Polygon, Point
from shapely.ops import unary_union

from .dashes import dashed_chains, parse_dash

STROKE_APPID = "PDF2DXF_STROKE"
MAX_OUTLINE_VERTICES = 200_000


def _inverse(matrix):
    a, b, c, d, e, f = matrix
    determinant = a * d - b * c
    if not math.isfinite(determinant) or abs(determinant) < 1e-18:
        raise ValueError("PDF_STROKE_TRANSFORM_UNCONFIRMED")
    return (
        d / determinant,
        -b / determinant,
        -c / determinant,
        a / determinant,
        (c * f - d * e) / determinant,
        (b * e - a * f) / determinant,
    )


def _point(point, matrix):
    a, b, c, d, e, f = matrix
    x, y = point
    return a * x + c * y + e, b * x + d * y + f


def attach_stroke_states(page, drawings):
    """Read miter limit and the actual affine stroke space omitted by cdrawings."""
    from fitz import mupdf
    from .base import LineSeg, CubicSeg, PathChain

    class Walker(mupdf.FzPathWalker2):
        def __init__(self, matrix):
            super().__init__()
            self.matrix = matrix
            self.chains = []
            self.current = None
            for name in ("moveto", "lineto", "curveto", "closepath"):
                getattr(self, "use_virtual_" + name)()

        def point(self, x, y):
            m = self.matrix
            return m.a * x + m.c * y + m.e, m.b * x + m.d * y + m.f

        def moveto(self, arg, x, y):
            self.current = self.point(x, y)
            self.chains.append(PathChain([]))

        def lineto(self, arg, x, y):
            end = self.point(x, y)
            self.chains[-1].segments.append(LineSeg(self.current, end))
            self.current = end

        def curveto(self, arg, x1, y1, x2, y2, x3, y3):
            end = self.point(x3, y3)
            self.chains[-1].segments.append(
                CubicSeg(self.current, self.point(x1, y1), self.point(x2, y2), end)
            )
            self.current = end

        def closepath(self, arg):
            chain = self.chains[-1]
            if chain.segments:
                chain.closed = True
                self.current = chain.start

    class Device(mupdf.FzDevice2):
        def __init__(self):
            super().__init__()
            self.use_virtual_stroke_path()
            self.rows = []

        def stroke_path(
            self, ctx, path, state, matrix, colorspace, color, alpha, params
        ):
            walker = Walker(matrix)
            # Match PyMuPDF's native walker ownership/callback convention. The
            # callback argument must be the walker pointer (not a null arg).
            mupdf.fz_walk_path(
                mupdf.FzPath(mupdf.ll_fz_keep_path(path)), walker, walker.m_internal
            )
            self.rows.append(
                {
                    "cap": int(state.start_cap),
                    "join": int(state.linejoin),
                    "miter": float(state.miterlimit),
                    "width": float(state.linewidth),
                    "matrix": (
                        matrix.a,
                        matrix.b,
                        matrix.c,
                        matrix.d,
                        matrix.e,
                        matrix.f,
                    ),
                    "chains": [c for c in walker.chains if c.segments],
                }
            )

    rotation = page.rotation
    device = Device()
    try:
        if rotation:
            page.set_rotation(0)
        mupdf.fz_run_page(page.this, device, mupdf.FzMatrix(), mupdf.FzCookie())
    finally:
        try:
            mupdf.fz_close_device(device)
        finally:
            if rotation:
                page.set_rotation(rotation)
    count = 0

    def annotate(record):
        nonlocal count
        if "s" not in str(record.get("type", "")):
            return
        if count >= len(device.rows):
            raise ValueError("PDF_STROKE_STATE_UNCONFIRMED")
        state = device.rows[count]
        count += 1
        record["_stroke_chains"] = state.pop("chains")
        record["_stroke_state"] = state

    # A spool yields fresh dictionaries on each pass. Updating one pass alone
    # loses state before the geometry emitter reads it; persist that enrichment.
    update = getattr(drawings, "update_records", None)
    if callable(update):
        update(annotate)
    else:
        for record in drawings:
            annotate(record)
    if count != len(device.rows):
        raise ValueError("PDF_STROKE_STATE_UNCONFIRMED")


def painted_chains(chains, drawing):
    from .base import LineSeg, CubicSeg, PathChain

    values, phase = parse_dash(drawing.get("dashes"))
    if not values:
        return list(chains)
    matrix = drawing["_stroke_state"]["matrix"]
    inverse = _inverse(matrix)

    def mapped(chain, mapping):
        def point(p):
            return _point(p, mapping)

        segments = [
            CubicSeg(*map(point, (s.p0, s.c1, s.c2, s.p1)))
            if hasattr(s, "c1")
            else LineSeg(point(s.p0), point(s.p1))
            for s in chain.segments
        ]
        direction = chain.dot_direction
        if direction:
            direction = (
                mapping[0] * direction[0] + mapping[2] * direction[1],
                mapping[1] * direction[0] + mapping[3] * direction[1],
            )
        return PathChain(segments, closed=chain.closed, dot_direction=direction)

    result = []
    for chain in chains:
        chain = mapped(chain, inverse)
        runs = list(dashed_chains([chain], values, phase))
        # The PDF closing seam is a join when paint continues across it.
        if chain.closed and runs:
            if len(runs) == 1 and math.dist(runs[0].start, runs[0].end) <= 1e-9:
                runs[0].closed = True
            elif (
                len(runs) > 1
                and math.dist(runs[-1].end, chain.start) <= 1e-9
                and math.dist(runs[0].start, chain.start) <= 1e-9
                and math.dist(runs[-1].start, runs[-1].end) > 1e-9
                and math.dist(runs[0].start, runs[0].end) > 1e-9
            ):
                runs[0].segments = runs[-1].segments + runs[0].segments
                runs.pop()
        result.extend(mapped(run, matrix) for run in runs)
    return result


def _flatten(chain, inverse, tolerance):
    points = []

    def append(point):
        value = tuple(point)
        if not points or value != points[-1]:
            points.append(value)
        if len(points) > MAX_OUTLINE_VERTICES:
            raise ValueError("PDF_STROKE_OUTLINE_LIMIT")

    def cubic(a, b, c, d, depth=0):
        line = LineString([a, d])

        if max(line.distance(Point(b)), line.distance(Point(c))) <= tolerance:
            append(d)
            return
        if depth >= 24:
            raise ValueError("PDF_STROKE_CURVE_TOLERANCE_UNCONFIRMED")
        ab, bc, cd = (
            tuple((x + y) / 2 for x, y in zip(p, q))
            for p, q in ((a, b), (b, c), (c, d))
        )
        abc, bcd = (
            tuple((x + y) / 2 for x, y in zip(p, q)) for p, q in ((ab, bc), (bc, cd))
        )
        middle = tuple((x + y) / 2 for x, y in zip(abc, bcd))
        cubic(a, ab, abc, middle, depth + 1)
        cubic(middle, bcd, cd, d, depth + 1)

    def local(point):
        return _point(point, inverse)

    # Subdivide in the original stroke space. Native centerline controls survive.
    append(local(chain.start))
    for segment in chain.segments:
        if hasattr(segment, "c1"):
            cubic(*map(local, (segment.p0, segment.c1, segment.c2, segment.p1)))
        else:
            append(local(segment.p1))
    if chain.closed and points and points[-1] != points[0]:
        points.append(points[0])
    return points


def _miter_patches(points, radius, limit, closed):
    count = len(points) - 1
    indices = range(count) if closed else range(1, count)
    for i in indices:
        a, b, c = (
            points[(i - 1) % count],
            points[i],
            points[(i + 1) % count if closed else i + 1],
        )
        first, second = (b[0] - a[0], b[1] - a[1]), (c[0] - b[0], c[1] - b[1])
        la, lb = math.hypot(*first), math.hypot(*second)
        if min(la, lb) <= 1e-12:
            continue
        u, v = (first[0] / la, first[1] / la), (second[0] / lb, second[1] / lb)
        cross = u[0] * v[1] - u[1] * v[0]
        if abs(cross) < 1e-12:
            continue
        sign = -1 if cross > 0 else 1
        p = b[0] - sign * radius * u[1], b[1] + sign * radius * u[0]
        q = b[0] - sign * radius * v[1], b[1] + sign * radius * v[0]
        t = ((q[0] - p[0]) * v[1] - (q[1] - p[1]) * v[0]) / cross
        tip = p[0] + t * u[0], p[1] + t * u[1]
        # PDF falls back to the bevel, rather than clipping the miter at limit.
        if math.dist(tip, b) <= radius * limit * (1 + 1e-12):
            yield Polygon([p, tip, q, b])


def stroke_geometry(chains, drawing, clip):
    state = drawing.get("_stroke_state")
    if state is None:
        raise ValueError("PDF_STROKE_STATE_UNCONFIRMED")
    width = state["width"]
    if width <= 0:
        return None, 0.0
    cap, join, limit = state["cap"], state["join"], state["miter"]
    if cap not in (0, 1, 2) or join not in (0, 1, 2) or not limit > 0:
        raise ValueError("PDF_STROKE_STYLE_UNSUPPORTED")
    matrix = state["matrix"]
    inverse = _inverse(matrix)
    norm = math.sqrt(sum(value**2 for value in matrix[:4]))
    tolerance = min(0.005 / max(norm, 1e-12), width / 200)
    radius = width / 2
    segments = max(8, math.ceil(math.pi / (4 * math.acos(1 - tolerance / radius))))
    if segments > 4096:
        raise ValueError("PDF_STROKE_OUTLINE_LIMIT")
    pieces = []
    for chain in chains:
        points = _flatten(chain, inverse, tolerance)
        if len(points) == 1 and not chain.closed:
            if cap == 1:
                pieces.append(Point(points[0]).buffer(radius, quad_segs=segments))
            elif cap == 2:
                direction = chain.dot_direction or (1, 0)
                dx = inverse[0] * direction[0] + inverse[2] * direction[1]
                dy = inverse[1] * direction[0] + inverse[3] * direction[1]
                angle = math.atan2(dy, dx)
                u, v = math.cos(angle), math.sin(angle)
                x, y = points[0]
                pieces.append(
                    Polygon(
                        [
                            (x + radius * (a * u - b * v), y + radius * (a * v + b * u))
                            for a, b in ((-1, -1), (1, -1), (1, 1), (-1, 1))
                        ]
                    )
                )
            continue
        if len(points) < 2:
            continue
        line = LineString(points)
        shape = line.buffer(
            radius,
            quad_segs=segments,
            cap_style={0: 2, 1: 1, 2: 3}[cap],
            join_style=1 if join == 1 else 3,
        )
        if join == 0:
            patches = list(_miter_patches(points, radius, limit, chain.closed))
            if patches:
                shape = unary_union([shape, *patches])
        pieces.append(shape)
    if not pieces:
        return None, tolerance * norm
    shape = unary_union(pieces)
    shape = affine_transform(
        shape, [matrix[0], matrix[2], matrix[1], matrix[3], matrix[4], matrix[5]]
    )
    if clip is not None:
        shape = shape.intersection(clip.geometry)
    vertices = sum(
        len(p.exterior.coords) + sum(len(r.coords) for r in p.interiors)
        for p in polygons(shape)
    )
    if vertices > MAX_OUTLINE_VERTICES:
        raise ValueError("PDF_STROKE_OUTLINE_LIMIT")
    return shape, 2 * tolerance * norm


def polygons(geometry):
    if geometry is None or geometry.is_empty:
        return
    if isinstance(geometry, Polygon):
        yield geometry
    elif hasattr(geometry, "geoms"):
        for part in geometry.geoms:
            yield from polygons(part)
