"""STL writer tests."""

from __future__ import annotations

import struct

import pytest

from nastran2stl import write_ascii_stl, write_binary_stl, write_stl
from nastran2stl.stl import triangle_normal


TRIANGLE = ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0))


def test_triangle_normal():
    assert triangle_normal(TRIANGLE) == pytest.approx((0.0, 0.0, 1.0))
    assert triangle_normal(((0, 0, 0), (0, 0, 0), (0, 0, 0))) == (0.0, 0.0, 0.0)


def test_binary_stl_layout(tmp_path):
    path = write_binary_stl(tmp_path / "tri.stl", [TRIANGLE], name="tri")
    data = path.read_bytes()
    assert len(data) == 80 + 4 + 50
    assert data[:10] == b"Nastran2ST"
    count = struct.unpack("<I", data[80:84])[0]
    assert count == 1
    values = struct.unpack("<12fH", data[84:])
    assert values[0:3] == pytest.approx((0.0, 0.0, 1.0))
    assert values[3:12] == pytest.approx(
        (0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0)
    )
    assert values[12] == 0


def test_flat_and_point_inputs_are_equivalent(tmp_path):
    flat = (0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0)
    first = write_binary_stl(tmp_path / "a.stl", [flat], name="a")
    second = write_binary_stl(tmp_path / "b.stl", [TRIANGLE], name="b")
    assert first.read_bytes()[84:] == second.read_bytes()[84:]


def test_ascii_stl(tmp_path):
    path = write_ascii_stl(tmp_path / "tri.stl", [TRIANGLE], name="tri")
    text = path.read_text(encoding="ascii")
    assert text.startswith("solid tri\n")
    assert text.count("facet normal") == 1
    assert text.count("vertex") == 3
    assert text.strip().endswith("endsolid tri")


def test_write_stl_dispatch(tmp_path):
    binary = write_stl(tmp_path / "b.stl", [TRIANGLE])
    ascii_file = write_stl(tmp_path / "a.stl", [TRIANGLE], ascii=True)
    assert binary.read_bytes()[80:84] == struct.pack("<I", 1)
    assert ascii_file.read_text(encoding="ascii").startswith("solid mesh")


def test_invalid_triangle_raises(tmp_path):
    with pytest.raises(ValueError):
        write_binary_stl(tmp_path / "bad.stl", [(0.0, 0.0)])
