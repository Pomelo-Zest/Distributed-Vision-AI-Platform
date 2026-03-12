from __future__ import annotations

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


def crossed_line(previous: Point, current: Point, line: Iterable[Point]) -> bool:
    previous_side = side_of_line(previous, line)
    current_side = side_of_line(current, line)
    return previous_side == 0 or current_side == 0 or previous_side * current_side < 0

