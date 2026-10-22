"""End-to-end conversion, manifest, naming and CLI tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nastran2stl import (
    NastranError,
    convert,
    is_watertight,
    load_names,
    sanitize_name,
    unit_factor,
)
from nastran2stl.cli import main

FIXTURES = Path(__file__).parent / "fixtures"


def _shell_without_thickness(tmp_path: Path) -> Path:
    source = tmp_path / "no_thickness.bdf"
    source.write_text(
        "\n".join(
            [
                "BEGIN BULK",
                "GRID           1       0     0.0     0.0     0.0",
                "GRID           2       0     1.0     0.0     0.0",
                "GRID           3       0     0.0     1.0     0.0",
                "PSHELL       100       1     0.0       1",
                "CTRIA3       200     100       1       2       3",
                "ENDDATA",
            ]
        )
        + "\n",
        encoding="ascii",
    )
    return source


def test_convert_writes_split_and_combined(tmp_path):
    result = convert(FIXTURES / "small_field.bdf", tmp_path)
    assert len(result.objects) == 1
    obj = result.objects[0]
    assert obj.pid == 100
    assert obj.kind == "PSHELL"
    assert len(obj.triangles) == 3
    assert result.triangle_count == 3
    assert obj.stl_path is not None and obj.stl_path.exists()
    assert result.combined_path is not None and result.combined_path.exists()
    assert result.combined_path.stat().st_size == 80 + 4 + 50 * 3
    assert result.manifest_path is not None and result.manifest_path.exists()
    assert result.bounds[1] == pytest.approx((10.0, 10.0, 0.0))


def test_manifest_contents(tmp_path):
    result = convert(FIXTURES / "small_field.bdf", tmp_path, names={100: "enclosure"})
    payload = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert payload["format"] == "nastran2stl/1"
    assert payload["scale"] == 1.0
    assert payload["source_units"] == "mm"
    assert payload["output_units"] == "mm"
    assert payload["objects"][0]["pid"] == 100
    assert payload["objects"][0]["name"] == "enclosure"
    assert payload["objects"][0]["triangles"] == 3
    assert payload["bounds"][0] == [0.0, 0.0, 0.0]


def test_custom_name_is_sanitized(tmp_path):
    result = convert(
        FIXTURES / "small_field.bdf", tmp_path, names={100: "my enclosure/1"}
    )
    assert result.objects[0].stl_path.name == "small_field_pid100_my_enclosure_1.stl"


def test_units_are_scaled(tmp_path):
    result = convert(
        FIXTURES / "units.bdf",
        tmp_path,
        unit_in="in",
        unit_out="mm",
        split=False,
    )
    assert result.scale == pytest.approx(25.4)
    assert result.objects[0].stl_path is None
    assert result.combined_path is not None
    assert result.bounds[1] == pytest.approx((25.4, 25.4, 0.0))
    payload = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert payload["scale"] == pytest.approx(25.4)


def test_explicit_scale_overrides_units(tmp_path):
    result = convert(FIXTURES / "units.bdf", tmp_path, scale=2.0, combined=False)
    assert result.bounds[1] == pytest.approx((2.0, 2.0, 0.0))


def test_split_only_and_combined_only(tmp_path):
    split_only = convert(FIXTURES / "small_field.bdf", tmp_path / "a", combined=False)
    assert split_only.combined_path is None
    assert split_only.objects[0].stl_path is not None

    combined_only = convert(FIXTURES / "small_field.bdf", tmp_path / "b", split=False)
    assert combined_only.objects[0].stl_path is None
    assert combined_only.combined_path is not None


def test_at_least_one_output_is_required(tmp_path):
    with pytest.raises(ValueError):
        convert(FIXTURES / "small_field.bdf", tmp_path, split=False, combined=False)


def test_manifest_can_be_disabled(tmp_path):
    result = convert(FIXTURES / "small_field.bdf", tmp_path, manifest=False)
    assert result.manifest_path is None


def test_solid_conversion(tmp_path):
    result = convert(FIXTURES / "solids.bdf", tmp_path, solids="boundary")
    assert len(result.objects) == 1
    assert result.objects[0].pid == 500
    assert result.triangle_count == 20


def test_shell_solid_uses_pshell_thickness(tmp_path):
    result = convert(FIXTURES / "units.bdf", tmp_path, shell_solid=True)
    obj = result.objects[0]

    assert obj.solid
    assert obj.thickness == pytest.approx(1.5)
    assert len(obj.triangles) == 8
    assert is_watertight(obj.triangles)
    assert result.stats["shell_extrusions"] == 1
    assert result.stats["solids_written"] == 1

    payload = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert payload["objects"][0]["solid"] is True
    assert payload["objects"][0]["thickness"] == pytest.approx(1.5)
    assert payload["objects"][0]["step"] is None


def test_shell_solid_fallback_is_scaled(tmp_path):
    source = _shell_without_thickness(tmp_path)
    result = convert(
        source,
        tmp_path / "out",
        unit_in="in",
        unit_out="mm",
        shell_solid=True,
        shell_thickness=0.1,
    )
    obj = result.objects[0]

    assert obj.thickness == pytest.approx(2.54)
    assert obj.solid
    assert result.bounds is not None
    assert result.bounds[1][2] - result.bounds[0][2] == pytest.approx(2.54)


def test_shell_solid_requires_a_thickness(tmp_path):
    source = _shell_without_thickness(tmp_path)
    with pytest.raises(NastranError, match="fallback shell thickness"):
        convert(source, tmp_path / "out", shell_solid=True)


def test_solid_elements_are_marked_as_solids(tmp_path):
    result = convert(
        FIXTURES / "solids_pids.bdf",
        tmp_path,
        solid_elements=True,
    )

    assert result.objects
    assert all(obj.solid for obj in result.objects)
    payload = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert all(item["solid"] is True for item in payload["objects"])


def test_open_solid_boundary_is_not_marked_as_solid(tmp_path):
    result = convert(
        FIXTURES / "solids.bdf",
        tmp_path,
        solids="faces",
        solid_elements=True,
    )

    assert result.objects
    assert not any(obj.solid for obj in result.objects)
    assert any("not watertight" in warning for warning in result.warnings)


def test_warnings_are_reported(tmp_path):
    result = convert(FIXTURES / "degenerate.bdf", tmp_path)
    assert any("undefined GRID" in warning for warning in result.warnings)
    payload = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert payload["warnings"]


def test_invalid_unit_raises():
    with pytest.raises(NastranError):
        unit_factor("furlong")


def test_sanitize_name():
    assert sanitize_name("my enclosure/1") == "my_enclosure_1"
    assert sanitize_name("") == "mesh"
    assert sanitize_name("CON") == "_CON"
    assert sanitize_name("a" * 200).__len__() == 80


def test_load_names(tmp_path):
    assert load_names(FIXTURES / "names.json") == {100: "enclosure", 500: "block"}
    bad = tmp_path / "bad.json"
    bad.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(NastranError):
        load_names(bad)


def test_cli_writes_files(tmp_path, capsys):
    code = main(
        [
            str(FIXTURES / "small_field.bdf"),
            "-o",
            str(tmp_path),
            "--no-manifest",
        ]
    )
    assert code == 0
    output = capsys.readouterr()
    assert "1 object(s)" in output.out
    assert "3 triangles" in output.out
    assert (tmp_path / "small_field_all.stl").exists()
    assert (tmp_path / "small_field_pid100.stl").exists()


def test_cli_names_and_ascii(tmp_path):
    code = main(
        [
            str(FIXTURES / "small_field.bdf"),
            "-o",
            str(tmp_path),
            "--names",
            str(FIXTURES / "names.json"),
            "--ascii",
            "--no-combined",
        ]
    )
    assert code == 0
    path = tmp_path / "small_field_pid100_enclosure.stl"
    assert path.exists()
    assert path.read_text(encoding="ascii").startswith("solid enclosure")


def test_cli_shell_solid(tmp_path, capsys):
    code = main(
        [
            str(FIXTURES / "units.bdf"),
            "-o",
            str(tmp_path),
            "--shell-solid",
            "--no-manifest",
        ]
    )
    assert code == 0
    output = capsys.readouterr()
    assert "solid" in output.out
    assert (tmp_path / "units_pid100.stl").exists()


def test_cli_step_failure_does_not_remove_stl(tmp_path, capsys):
    code = main(
        [
            str(FIXTURES / "units.bdf"),
            "-o",
            str(tmp_path),
            "--step",
            "--freecad",
            str(tmp_path / "missing-FreeCADCmd.exe"),
            "--no-manifest",
        ]
    )
    assert code == 0
    assert (tmp_path / "units_pid100.stl").exists()
    assert not (tmp_path / "units_pid100.step").exists()
    assert "FreeCADCmd" in capsys.readouterr().err


def test_cli_no_geometry(tmp_path, capsys):
    code = main([str(FIXTURES / "no_geometry.bdf"), "-o", str(tmp_path)])
    assert code == 2
    assert "no supported" in capsys.readouterr().err


def test_cli_missing_file(tmp_path):
    code = main([str(tmp_path / "missing.bdf"), "-o", str(tmp_path)])
    assert code == 1
