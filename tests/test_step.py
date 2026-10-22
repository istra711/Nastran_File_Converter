"""Optional FreeCAD/STEP tests.

These tests are skipped when FreeCADCmd is not installed.  The STL tests in
``test_convert.py`` cover the no-FreeCAD fallback.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from nastran2stl.convert import convert
from nastran2stl.step import StepError, StepItem, find_freecad_cmd, write_step_files

FIXTURES = Path(__file__).parent / "fixtures"
FREECAD = find_freecad_cmd()
requires_freecad = pytest.mark.skipif(
    FREECAD is None, reason="FreeCADCmd is not installed"
)


def test_find_freecad_cmd_is_an_executable():
    if FREECAD is None:
        pytest.skip("FreeCADCmd is not installed")
    assert FREECAD.is_file()


@requires_freecad
def test_write_step_files_creates_solid(tmp_path):
    result = convert(
        FIXTURES / "solids_pids.bdf",
        tmp_path,
        solid_elements=True,
        step=False,
    )
    items = [
        StepItem(
            stl_path=obj.stl_path,
            step_path=obj.stl_path.with_suffix(".step"),
            solid=obj.solid,
            label=f"PID {obj.pid}",
        )
        for obj in result.objects
        if obj.stl_path is not None
    ]

    step_result = write_step_files(items, freecad_cmd=FREECAD)

    assert len(step_result.paths) == 2
    assert not step_result.warnings
    assert all(
        "MANIFOLD_SOLID_BREP" in path.read_text(encoding="utf-8", errors="replace")
        for path in step_result.paths
    )


@requires_freecad
def test_convert_writes_per_pid_and_combined_step(tmp_path):
    result = convert(
        FIXTURES / "solids_pids.bdf",
        tmp_path,
        solid_elements=True,
        step=True,
        freecad_cmd=FREECAD,
    )

    assert result.step_warnings == []
    assert [obj.step_path for obj in result.objects if obj.step_path] != []
    assert result.combined_step_path is not None
    assert result.combined_step_path.is_file()
    combined = result.combined_step_path.read_text(encoding="utf-8", errors="replace")
    assert combined.count("MANIFOLD_SOLID_BREP") == 2
    assert result.stats["step_files_written"] == 3


@requires_freecad
def test_shell_extrusion_writes_solid_step(tmp_path):
    result = convert(
        FIXTURES / "units.bdf",
        tmp_path,
        shell_solid=True,
        step=True,
        freecad_cmd=FREECAD,
    )

    obj = result.objects[0]
    assert obj.solid
    assert obj.step_path is not None
    text = obj.step_path.read_text(encoding="utf-8", errors="replace")
    assert "MANIFOLD_SOLID_BREP" in text


def test_missing_freecad_keeps_stl_files(tmp_path):
    result = convert(
        FIXTURES / "units.bdf",
        tmp_path,
        step=True,
        freecad_cmd=tmp_path / "missing-FreeCADCmd.exe",
    )

    assert result.objects[0].stl_path is not None
    assert result.objects[0].stl_path.exists()
    assert result.combined_step_path is None
    assert result.step_warnings
    assert any("STEP:" in warning for warning in result.warnings)


def test_missing_freecad_raises_from_writer(tmp_path):
    result = convert(FIXTURES / "units.bdf", tmp_path, step=False)
    item = StepItem(
        stl_path=result.objects[0].stl_path,
        step_path=tmp_path / "out.step",
        solid=True,
    )
    with pytest.raises(StepError):
        write_step_files([item], freecad_cmd=tmp_path / "missing-FreeCADCmd.exe")
