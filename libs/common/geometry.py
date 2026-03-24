from __future__ import annotations

from math import hypot
from typing import Iterable


Point = tuple[float, float]
Polygon = list[Point]


def point_in_polygon(point: Point, polygon: Polygon) -> bool:
    x, y = point
    inside = False
    for index in range(len(polygon)):
        x1, y1 = polygon[index]
        x2, y2 = polygon[(index + 1) % len(polygon)]
        intersects = ((y1 > y) != (y2 > y)) and (
            x < (x2 - x1) * (y - y1) / ((y2 - y1) or 1e-9) + x1
        )
        if intersects:
            inside = not inside
    return inside


def side_of_line(point: Point, line: Iterable[Point]) -> float:
    (x1, y1), (x2, y2) = list(line)
    px, py = point
    return (x2 - x1) * (py - y1) - (y2 - y1) * (px - x1)


def point_distance(a: Point, b: Point) -> float:
    return hypot(a[0] - b[0], a[1] - b[1])


def line_distance(point: Point, line: Iterable[Point]) -> float:
    (x1, y1), (x2, y2) = list(line)
    numerator = abs(side_of_line(point, line))
    denominator = hypot(x2 - x1, y2 - y1) or 1e-9
    return numerator / denominator


def _orientation(a: Point, b: Point, c: Point) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _on_segment(a: Point, b: Point, c: Point, epsilon: float = 1e-9) -> bool:
    return (
        min(a[0], c[0]) - epsilon <= b[0] <= max(a[0], c[0]) + epsilon
        and min(a[1], c[1]) - epsilon <= b[1] <= max(a[1], c[1]) + epsilon
    )


def segments_intersect(a1: Point, a2: Point, b1: Point, b2: Point, epsilon: float = 1e-9) -> bool:
    o1 = _orientation(a1, a2, b1)
    o2 = _orientation(a1, a2, b2)
    o3 = _orientation(b1, b2, a1)
    o4 = _orientation(b1, b2, a2)

    if (o1 > epsilon and o2 < -epsilon or o1 < -epsilon and o2 > epsilon) and (
        o3 > epsilon and o4 < -epsilon or o3 < -epsilon and o4 > epsilon
    ):
        return True

    if abs(o1) <= epsilon and _on_segment(a1, b1, a2, epsilon):
        return True
    if abs(o2) <= epsilon and _on_segment(a1, b2, a2, epsilon):
        return True
    if abs(o3) <= epsilon and _on_segment(b1, a1, b2, epsilon):
        return True
    if abs(o4) <= epsilon and _on_segment(b1, a2, b2, epsilon):
        return True
    return False


def crossed_line(
    previous: Point,
    current: Point,
    line: Iterable[Point],
    min_motion_distance: float = 0.0,
    min_side_distance: float = 0.0,
) -> bool:
    line_points = list(line)
    if len(line_points) != 2:
        return False
    previous_side = side_of_line(previous, line)
    current_side = side_of_line(current, line)
    if point_distance(previous, current) < min_motion_distance:
        return False
    if line_distance(previous, line) < min_side_distance or line_distance(current, line) < min_side_distance:
        return False
    if previous_side * current_side >= 0:
        return False
    return segments_intersect(previous, current, line_points[0], line_points[1])
