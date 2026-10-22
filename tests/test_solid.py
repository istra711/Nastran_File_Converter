"""Tests for shell extrusion and watertight mesh detection."""

from __future__ import annotations

import math

import pytest

from nastran2stl.solid import SolidError, extrude_shell_triangles, is_watertight


def _z_range(triangles):
    values = [triangle[index] for triangle in triangles for index in (2, 5, 8)]
    return min(values), max(values)


def test_extrude_single_triangle_is_closed():
    triangles = [(0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0)]

    result = extrude_shell_triangles(triangles, 2.0)

    assert len(result) == 8
    assert is_watertight(result)
    assert _z_range(result) == pytest.approx((-1.0, 1.0))


def test_extrude_open_quad_has_side_walls():
    triangles = [
        (0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0),
        (1.0, 0.0, 0.0, 1.0, 1.0, 0.0, 0.0, 1.0, 0.0),
    ]

    result = extrude_shell_triangles(triangles, 1.0)

    assert len(result) == 12
    assert is_watertight(result)


def test_watertight_detects_open_and_closed_meshes():
    triangle = [(0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0)]
    assert not is_watertight(triangle)
    assert is_watertight(extrude_shell_triangles(triangle, 1.0))


@pytest.mark.parametrize("thickness", [0.0, -1.0, math.inf, math.nan])
def test_extrude_rejects_invalid_thickness(thickness):
    triangle = [(0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0)]
    with pytest.raises(SolidError):
        extrude_shell_triangles(triangle, thickness)


def test_extrude_empty_mesh():
    assert extrude_shell_triangles([], 1.0) == []
