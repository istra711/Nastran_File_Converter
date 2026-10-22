"""BDF reader tests: field formats, includes, elements, coordinates."""

from __future__ import annotations

from pathlib import Path

import pytest

from nastran2stl import NastranError, NoGeometryError, convert, read_bdf
from nastran2stl.bdf import parse_float, parse_int

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_float_handles_implicit_exponents():
    assert parse_float("1.5") == pytest.approx(1.5)
    assert parse_float("1.5-3") == pytest.approx(1.5e-3)
    assert parse_float("-2.0+4") == pytest.approx(-2.0e4)
    assert parse_float("1.0D-3") == pytest.approx(1.0e-3)
    assert parse_float("") is None
    assert parse_float("not-a-number") is None
    assert parse_float("nan") is None
    assert parse_float("inf") is None
    assert parse_float("1e999") is None


def test_parse_int_falls_back_to_float():
    assert parse_int("12") == 12
    assert parse_int("12.0") == 12
    assert parse_int("") == 0
    assert parse_int("x", default=7) == 7


@pytest.mark.parametrize("name", ["small_field.bdf", "large_field.bdf", "free_field.bdf"])
def test_field_formats_are_equivalent(name):
    model = read_bdf(FIXTURES / name)
    assert set(model.nodes) == {1, 2, 3, 4, 5}
    assert len(model.elements) == 2
    assert model.elements[0].kind == "CTRIA3"
    assert model.elements[0].nodes == (1, 2, 3)
    assert model.elements[1].kind == "CQUAD4"
    assert model.elements[1].nodes == (1, 2, 3, 4)
    assert model.properties[100].kind == "PSHELL"
    assert model.properties[100].thickness == pytest.approx(1.5)
    assert model.nodes[3] == pytest.approx((10.0, 10.0, 0.0))
    assert model.warnings == []


def test_free_field_continuation_is_not_shifted():
    model = read_bdf(FIXTURES / "free_field.bdf")
    assert model.elements[0].nodes == (1, 2, 3)


def test_tab_separated_free_field(tmp_path):
    source = tmp_path / "tabs.bdf"
    source.write_text(
        "BEGIN BULK\n"
        "GRID\t1\t\t0\t0\t0\n"
        "GRID\t2\t\t1\t0\t0\n"
        "GRID\t3\t\t0\t1\t0\n"
        "PSHELL\t100\t1\t1.5\n"
        "CTRIA3\t200\t100\t1\t2\t3\n"
        "ENDDATA\n",
        encoding="ascii",
    )
    model = read_bdf(source)
    assert len(model.elements) == 1
    assert model.elements[0].nodes == (1, 2, 3)
    assert len(model.parts()[0].triangles) == 1


def test_mixed_small_and_large_field_cards(tmp_path):
    def large(card, fields, per_line=4):
        name = card + "*"
        lines = [f"{name:<8}" + "".join(f"{value:>16}" for value in fields[:per_line])]
        rest = fields[per_line:]
        while rest:
            chunk, rest = rest[:per_line], rest[per_line:]
            lines.append("*" + " " * 7 + "".join(f"{value:>16}" for value in chunk))
        return "\n".join(lines)

    source = tmp_path / "mixed.bdf"
    source.write_text(
        "BEGIN BULK\n"
        + large("GRID", [1, 0, 0.0, 0.0, 0.0])
        + "\nGRID           2       0     1.0     0.0     0.0\n"
        + "GRID           3       0     0.0     1.0     0.0\n"
        + "PSHELL       100       1     1.5       1\n"
        + "CTRIA3       200     100       1       2       3\n"
        + "ENDDATA\n",
        encoding="ascii",
    )
    model = read_bdf(source)
    assert set(model.nodes) == {1, 2, 3}
    assert len(model.elements) == 1
    assert len(model.parts()[0].triangles) == 1


def test_nested_include():
    model = read_bdf(FIXTURES / "include" / "main.bdf")
    assert set(model.nodes) == {1, 2, 3}
    assert len(model.elements) == 1
    assert model.stats["includes"] == 2
    assert model.warnings == []


def test_missing_include_warns_but_keeps_geometry():
    model = read_bdf(FIXTURES / "include" / "missing.bdf")
    assert model.stats["includes_missing"] == 1
    assert len(model.elements) == 1
    assert any("INCLUDE not found" in warning for warning in model.warnings)


def test_quads_are_split_into_two_triangles():
    model = read_bdf(FIXTURES / "small_field.bdf")
    part = model.parts()[0]
    assert len(part.triangles) == 3  # CTRIA3 + CQUAD4 -> 1 + 2


def test_shortest_diagonal_for_non_planar_quad():
    model = read_bdf(FIXTURES / "quad.bdf")
    shortest = model.parts(quad_split="shortest")[0].triangles
    fixed = model.parts(quad_split="fixed")[0].triangles
    # In the shortest variant the diagonal runs 1-3, so node 1 (10, 0, 0)
    # and node 3 (0, 1, 5) share no triangle with both 0-2 endpoints.
    def has_both(triangles, first, second):
        for triangle in triangles:
            points = [triangle[index:index + 3] for index in (0, 3, 6)]
            if any(all(abs(a - b) < 1e-9 for a, b in zip(point, first)) for point in points) and any(
                all(abs(a - b) < 1e-9 for a, b in zip(point, second)) for point in points
            ):
                return True
        return False

    p0 = (0.0, 0.0, 0.0)
    p2 = (10.0, 10.0, 0.0)
    assert not has_both(shortest, p0, p2)
    assert has_both(fixed, p0, p2)


def test_two_hexes_share_one_face_in_boundary_mode():
    model = read_bdf(FIXTURES / "solids.bdf")
    parts = model.parts(solids="boundary")
    assert len(parts) == 1
    assert parts[0].kind == "PSOLID"
    assert len(parts[0].triangles) == 20  # 10 outer quads -> 20 triangles
    low, high = parts[0].bounds()
    assert low == pytest.approx((0.0, 0.0, 0.0))
    assert high == pytest.approx((20.0, 10.0, 10.0))
    assert model.stats["solid_faces_internal"] == 2


def test_solids_are_skinned_per_pid():
    model = read_bdf(FIXTURES / "solids_pids.bdf")
    parts = model.parts(solids="boundary")
    assert {part.pid for part in parts} == {500, 501}
    assert sum(len(part.triangles) for part in parts) == 24  # both cubes closed


def test_solids_faces_mode_keeps_every_face():
    model = read_bdf(FIXTURES / "solids.bdf")
    parts = model.parts(solids="faces")
    assert sum(len(part.triangles) for part in parts) == 24


def test_solids_can_be_skipped():
    model = read_bdf(FIXTURES / "solids.bdf")
    assert model.parts(solids="skip") == []


def test_weld_tol_removes_duplicate_node_faces():
    model = read_bdf(FIXTURES / "solids_split_nodes.bdf")
    assert sum(len(part.triangles) for part in model.parts(weld_tol=0.0)) == 24
    assert sum(len(part.triangles) for part in model.parts(weld_tol=1e-6)) == 20


def test_cord2r_transforms_grid_coordinates():
    model = read_bdf(FIXTURES / "coords_r.bdf")
    assert model.nodes[1] == pytest.approx((1.0, 3.0, -2.0))
    assert model.nodes[2] == pytest.approx((2.0, 3.0, -2.0))
    assert model.nodes[3] == pytest.approx((1.0, 3.0, -3.0))


def test_cord2c_transforms_grid_coordinates():
    model = read_bdf(FIXTURES / "coords_c.bdf")
    assert model.nodes[1] == pytest.approx((0.0, 2.0, 3.0), abs=1e-12)
    assert model.nodes[2] == pytest.approx((2.0, 0.0, 3.0))
    assert model.nodes[3] == pytest.approx((0.0, 0.0, 0.0))


def test_cord2s_transforms_grid_coordinates():
    model = read_bdf(FIXTURES / "coords_s.bdf")
    assert model.nodes[1] == pytest.approx((0.0, 2.0, 0.0), abs=1e-12)
    assert model.nodes[2] == pytest.approx((2.0, 0.0, 0.0), abs=1e-12)
    assert model.nodes[3] == pytest.approx((0.0, 0.0, 2.0), abs=1e-12)


def test_cord2r_with_parent_rid():
    model = read_bdf(FIXTURES / "coords_rid.bdf")
    assert model.nodes[1] == pytest.approx((1.0, 0.0, 0.0))
    assert model.nodes[2] == pytest.approx((2.0, 0.0, 0.0))
    assert model.nodes[3] == pytest.approx((1.0, 1.0, 0.0))


def test_degenerate_and_missing_nodes_warn():
    model = read_bdf(FIXTURES / "degenerate.bdf")
    parts = model.parts()
    assert sum(len(part.triangles) for part in parts) == 1
    assert model.stats["elements_missing_nodes"] == 1
    assert model.stats["triangles_degenerate"] == 1
    assert any("undefined GRID" in warning for warning in model.warnings)
    assert any("degenerate" in warning for warning in model.warnings)


def test_midside_nodes_are_linearised():
    model = read_bdf(FIXTURES / "midside.bdf")
    assert len(model.parts()[0].triangles) == 1
    assert model.stats["midside_nodes_ignored"] == 1
    assert any("linearised" in warning for warning in model.warnings)


def test_scale_is_applied():
    model = read_bdf(FIXTURES / "units.bdf")
    part = model.parts(scale=25.4)[0]
    low, high = part.bounds()
    assert high == pytest.approx((25.4, 25.4, 0.0))


def test_part_element_counts_distinguish_shells_and_solids():
    shell_part = read_bdf(FIXTURES / "units.bdf").parts()[0]
    assert shell_part.shell_count == 1
    assert shell_part.solid_count == 0
    assert shell_part.is_shell
    assert not shell_part.is_solid

    solid_part = read_bdf(FIXTURES / "solids.bdf").parts()[0]
    assert solid_part.shell_count == 0
    assert solid_part.solid_count == 2
    assert solid_part.is_solid
    assert not solid_part.is_shell


def test_no_geometry_raises(tmp_path):
    with pytest.raises(NoGeometryError):
        convert(FIXTURES / "no_geometry.bdf", tmp_path)


def test_unknown_card_is_counted(tmp_path):
    source = tmp_path / "unknown.bdf"
    source.write_text(
        "\n".join(
            [
                "BEGIN BULK",
                "GRID,1,,0.0,0.0,0.0",
                "GRID,2,,1.0,0.0,0.0",
                "GRID,3,,0.0,1.0,0.0",
                "PSHELL,100,1,1.5",
                "FOOBAR,1,2,3",
                "CTRIA3,200,100,1,2,3",
                "ENDDATA",
            ]
        )
        + "\n",
        encoding="ascii",
    )
    model = read_bdf(source)
    assert model.unsupported["FOOBAR"] == 1
    assert len(model.parts()[0].triangles) == 1


def test_missing_file_raises():
    with pytest.raises(NastranError):
        read_bdf(FIXTURES / "does_not_exist.bdf")
