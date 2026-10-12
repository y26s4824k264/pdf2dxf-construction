"""Clip dash-cap paint while retaining exact circle arcs in HATCH boundaries."""

from __future__ import annotations

from dataclasses import dataclass
import math

from shapely.affinity import affine_transform
from shapely.geometry import Point, Polygon, box
from shapely.geometry.polygon import orient


@dataclass(frozen=True)
class Edge:
    start: tuple[float, float]
    end: tuple[float, float]
    # Counterclockwise unit-circle parameters; None denotes a straight edge.
    angles: tuple[float, float] | None = None


def _polygons(geometry):
    if geometry.is_empty:
        return
    if isinstance(geometry, Polygon):
        yield orient(geometry, sign=1)
    elif hasattr(geometry, "geoms"):
        for part in geometry.geoms:
            yield from _polygons(part)


def _rings(geometry):
    for polygon in _polygons(geometry):
        yield polygon.exterior
        yield from polygon.interiors


def _circle_point(angle):
    return math.cos(angle), math.sin(angle)


def _circle_edges(clip):
    """Intersect a unit disk and polygon boundaries analytically."""
    edges, angles = [], []
    for ring in _rings(clip):
        points = list(ring.coords)
        for a, b in zip(points, points[1:]):
            dx, dy = b[0] - a[0], b[1] - a[1]
            squared = dx * dx + dy * dy
            if squared == 0:
                continue
            middle = -(a[0] * dx + a[1] * dy) / squared
            nearest = a[0] + middle * dx, a[1] + middle * dy
            height = 1 - nearest[0] ** 2 - nearest[1] ** 2
            cuts = [(0.0, tuple(a)), (1.0, tuple(b))]
            if height >= -1e-14:
                delta = math.sqrt(max(0, height) / squared)
                for t in (middle - delta, middle + delta):
                    if -1e-12 <= t <= 1 + 1e-12:
                        t = min(1.0, max(0.0, t))
                        angle = math.atan2(a[1] + t * dy, a[0] + t * dx) % math.tau
                        angles.append(angle)
                        cuts.append((t, _circle_point(angle)))
            cuts.sort(key=lambda cut: cut[0])
            for (ta, start), (tb, end) in zip(cuts, cuts[1:]):
                if tb - ta <= 1e-12:
                    continue
                t = (ta + tb) / 2
                if (a[0] + t * dx) ** 2 + (a[1] + t * dy) ** 2 < 1:
                    edges.append(Edge(start, end))
    ordered = []
    for angle in sorted(angles):
        if not ordered or angle - ordered[-1] > 1e-10:
            ordered.append(angle)
    if len(ordered) > 1 and ordered[0] + math.tau - ordered[-1] <= 1e-10:
        ordered.pop()
    if not ordered:
        ordered = [0.0]
    for a, b in zip(ordered, ordered[1:] + [ordered[0] + math.tau]):
        if clip.covers(Point(_circle_point((a + b) / 2))):
            edges.append(Edge(_circle_point(a), _circle_point(b), (a, b)))
    return edges


def _loops(edges):
    """Join analytic endpoints without rounding the emitted coordinates."""
    tolerance = 1e-9
    buckets = {}

    def key(point):
        return tuple(math.floor(v / tolerance) for v in point)

    for index, edge in enumerate(edges):
        buckets.setdefault(key(edge.start), set()).add(index)
    remaining = set(range(len(edges)))
    while remaining:
        index = min(remaining)
        first = edges[index].start
        loop = []
        while True:
            remaining.remove(index)
            edge = edges[index]
            loop.append(edge)
            if math.dist(edge.end, first) <= tolerance:
                break
            x, y = key(edge.end)
            candidates = [
                i
                for dx in (-1, 0, 1)
                for dy in (-1, 0, 1)
                for i in buckets.get((x + dx, y + dy), ())
                if i in remaining and math.dist(edges[i].start, edge.end) <= tolerance
            ]
            if len(candidates) != 1:
                raise ValueError("PDF_DASH_DOT_CLIP_TOPOLOGY_UNCONFIRMED")
            index = candidates[0]
        yield loop


def add_dot_paths(hatch, center, radius, cap, angle, clip=None):
    """Add native boundaries in drawing coordinates; return the boundary count."""
    x, y = center
    if clip is not None:
        # Normalization and a bounding square keep the quadratic well-conditioned.
        clip = affine_transform(
            clip, [1 / radius, 0, 0, 1 / radius, -x / radius, -y / radius]
        )
        clip = clip.intersection(box(-2, -2, 2, 2))
        if clip.is_empty:
            return 0

    def world(point):
        return x + radius * point[0], y + radius * point[1]

    if cap == 2:
        u, v = math.cos(angle), math.sin(angle)
        square = Polygon(
            [
                (a * u - b * v, a * v + b * u)
                for a, b in ((-1, -1), (1, -1), (1, 1), (-1, 1))
            ]
        )
        geometry = square if clip is None else square.intersection(clip)
        count = 0
        for polygon in _polygons(geometry):
            for index, ring in enumerate((polygon.exterior, *polygon.interiors)):
                hatch.paths.add_polyline_path(
                    [world(p) for p in ring.coords],
                    is_closed=True,
                    flags=1 if index == 0 else 0,
                )
                count += 1
        return count

    if clip is None or clip.covers(box(-1, -1, 1, 1)):
        hatch.paths.add_edge_path().add_arc(center, radius, 0, 360)
        return 1
    count = 0
    for loop in _loops(_circle_edges(clip)):
        area = (
            sum(
                edge.angles[1] - edge.angles[0]
                if edge.angles is not None
                else edge.start[0] * edge.end[1] - edge.start[1] * edge.end[0]
                for edge in loop
            )
            / 2
        )
        if abs(area) <= 1e-14:
            continue
        path = hatch.paths.add_edge_path(flags=1 if area > 0 else 0)
        for edge in loop:
            if edge.angles is None:
                path.add_line(world(edge.start), world(edge.end))
            else:
                path.add_arc(center, radius, *map(math.degrees, edge.angles))
        count += 1
    return count
