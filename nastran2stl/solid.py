"""Helpers for turning surface triangle meshes into closed thin solids."""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Iterable

Point = tuple[float, float, float]
Triangle = tuple[float, ...]


class SolidError(ValueError):
    """Raised when a triangle mesh cannot be thickened."""


def _point(triangle: Triangle, index: int) -> Point:
    base = 3 * index
    return (
        float(triangle[base]),
        float(triangle[base + 1]),
        float(triangle[base + 2]),
    )


def _sub(a: Point, b: Point) -> Point:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _add(a: Point, b: Point) -> Point:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _scale(a: Point, factor: float) -> Point:
    return (a[0] * factor, a[1] * factor, a[2] * factor)


def _cross(a: Point, b: Point) -> Point:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _length(a: Point) -> float:
    return math.sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2])


def _normalize(a: Point) -> Point:
    length = _length(a)
    if length <= 1e-18:
        return (0.0, 0.0, 0.0)
    return (a[0] / length, a[1] / length, a[2] / length)


def _triangle_normal(triangle: Triangle) -> Point:
    a, b, c = _point(triangle, 0), _point(triangle, 1), _point(triangle, 2)
    return _cross(_sub(b, a), _sub(c, a))


def _vertex_key(point: Point) -> tuple[float, float, float]:
    # STL triangles share exact coordinates when they come from shared GRID
    # nodes.  Rounding only protects against harmless floating point noise.
    return (
        round(point[0], 10),
        round(point[1], 10),
        round(point[2], 10),
    )


def is_watertight(triangles: Iterable[Triangle]) -> bool:
    """Return True when every mesh edge is shared by exactly two triangles."""
    counts: dict[tuple[tuple[float, float, float], tuple[float, float, float]], int] = (
        defaultdict(int)
    )
    for triangle in triangles:
        if len(triangle) < 9:
            return False
        points = [_point(triangle, index) for index in range(3)]
        keys = [_vertex_key(point) for point in points]
        for start, end in ((0, 1), (1, 2), (2, 0)):
            a, b = keys[start], keys[end]
            edge = (a, b) if a <= b else (b, a)
            counts[edge] += 1
    return bool(counts) and all(count == 2 for count in counts.values())


def extrude_shell_triangles(
    triangles: Iterable[Triangle],
    thickness: float,
) -> list[Triangle]:
    """Thicken an open triangle surface into a closed triangle mesh.

    The original surface becomes the mid-plane.  Vertices are offset along
    averaged vertex normals by ``thickness / 2``; side walls are added along
    boundary edges.  The result is suitable for STL and for a faceted STEP
    solid.
    """
    if not math.isfinite(thickness) or thickness <= 0.0:
        raise SolidError("thickness must be a positive, finite number")

    source = [tuple(float(value) for value in triangle) for triangle in triangles]
    if not source:
        return []

    points: dict[tuple[float, float, float], Point] = {}
    normals: dict[tuple[float, float, float], Point] = defaultdict(
        lambda: (0.0, 0.0, 0.0)
    )
    fallback_normals: dict[tuple[float, float, float], Point] = {}
    triangles_by_key: list[tuple[tuple[float, float, float], ...]] = []

    for triangle in source:
        if len(triangle) < 9:
            raise SolidError("triangles must contain three 3D points")
        triangle_points = [_point(triangle, index) for index in range(3)]
        keys = tuple(_vertex_key(point) for point in triangle_points)
        for key, point in zip(keys, triangle_points):
            points.setdefault(key, point)
        normal = _triangle_normal(triangle)
        for key in keys:
            normals[key] = _add(normals[key], normal)
            fallback_normals.setdefault(key, normal)
        triangles_by_key.append(keys)

    vertex_normals: dict[tuple[float, float, float], Point] = {}
    for key in points:
        normal = _normalize(normals[key])
        if _length(normal) <= 1e-18:
            normal = _normalize(fallback_normals.get(key, (0.0, 0.0, 1.0)))
        if _length(normal) <= 1e-18:
            normal = (0.0, 0.0, 1.0)
        vertex_normals[key] = normal

    half = thickness * 0.5
    top = {
        key: _add(point, _scale(vertex_normals[key], half))
        for key, point in points.items()
    }
    bottom = {
        key: _add(point, _scale(vertex_normals[key], -half))
        for key, point in points.items()
    }

    result: list[Triangle] = []
    for keys in triangles_by_key:
        a, b, c = keys
        result.append((*top[a], *top[b], *top[c]))
        result.append((*bottom[c], *bottom[b], *bottom[a]))

    edge_counts: dict[
        tuple[tuple[float, float, float], tuple[float, float, float]], int
    ] = defaultdict(int)
    edge_directions: dict[
        tuple[tuple[float, float, float], tuple[float, float, float]],
        tuple[tuple[float, float, float], tuple[float, float, float]],
    ] = {}
    for keys in triangles_by_key:
        for start, end in ((0, 1), (1, 2), (2, 0)):
            a, b = keys[start], keys[end]
            canonical = (a, b) if a <= b else (b, a)
            edge_counts[canonical] += 1
            edge_directions.setdefault(canonical, (a, b))

    for edge, count in edge_counts.items():
        if count != 1:
            continue
        a, b = edge_directions[edge]
        result.append((*top[a], *bottom[a], *bottom[b]))
        result.append((*top[a], *bottom[b], *top[b]))

    return result


__all__ = [
    "SolidError",
    "extrude_shell_triangles",
    "is_watertight",
]
