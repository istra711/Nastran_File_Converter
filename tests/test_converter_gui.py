"""Tests for the converter GUI helpers (no window is opened)."""

from __future__ import annotations

from pathlib import Path

from nastran2stl.convert import convert
from nastran2stl.converter_gui import (
    HELP_TEXT,
    default_output_dir,
    format_result,
    result_output_dir,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_default_output_dir_is_beside_input():
    assert default_output_dir("models/part.bdf") == Path("models/part_stl")
    assert default_output_dir("PART.NAS") == Path("PART_stl")


def test_result_output_dir_and_log_text(tmp_path):
    result = convert(FIXTURES / "small_field.bdf", tmp_path)
    output_dir = result_output_dir(result)

    assert output_dir == tmp_path
    text = format_result(result, output_dir)

    assert f"Ausgabeordner: {tmp_path}" in text
    assert "small_field_pid100.stl" in text
    assert "small_field_all.stl" in text
    assert "small_field_nastran2stl.json" in text
    assert "3 Dreiecke" in text
    assert "Einheit mm -> mm" in text


def test_format_result_can_use_combined_path_only(tmp_path):
    result = convert(
        FIXTURES / "small_field.bdf",
        tmp_path,
        split=False,
        combined=True,
    )
    text = format_result(result)

    assert "small_field_all.stl" in text
    assert "(nicht geschrieben)" in text
    assert result_output_dir(result) == tmp_path


def test_format_result_marks_solid_and_thickness(tmp_path):
    result = convert(FIXTURES / "units.bdf", tmp_path, shell_solid=True)
    text = format_result(result)

    assert "[Solid / Dicke 1.5]" in text
    assert "8 Dreiecke" in text


def test_help_explains_solid_and_step_options():
    assert "Option 1" in HELP_TEXT
    assert "Option 2" in HELP_TEXT
    assert "Option 3" in HELP_TEXT
    assert "FreeCADCmd" in HELP_TEXT
    assert "Convert to solid" in HELP_TEXT
