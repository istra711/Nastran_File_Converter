"""Viewer math and CLI integration tests (no window is opened)."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from nastran2stl import Camera, NastranError, Scene, ViewerError, read_bdf
from nastran2stl.cli import main
from nastran2stl.viewer import _face_intensity, _shade_color
from nastran2stl.viewer import main as viewer_main

FIXTURES = Path(__file__).parent / "fixtures"


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def test_scene_from_mesh_parts():
    model = read_bdf(FIXTURES / "small_field.bdf")
    scene = Scene.from_parts(model.parts())

    assert scene.triangle_count == 3
    assert len(scene.parts) == 1
    assert scene.parts[0].pid == 100
    assert scene.parts[0].color.startswith("#")
    assert scene.bounds == ((0.0, 0.0, 0.0), (10.0, 10.0, 0.0))
    assert scene.center == pytest.approx((5.0, 5.0, 0.0))
    assert scene.radius == pytest.approx(math.sqrt(50.0))


def test_scene_from_duck_typed_objects():
    class Part:
        pid = 7
        name = "object"
        triangles = [(0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0)]

    scene = Scene.from_parts([Part()])
    assert scene.triangle_count == 1
    assert scene.parts[0].name == "object"
    assert scene.radius > 0


def test_scene_requires_geometry():
    with pytest.raises(ViewerError):
        Scene.from_parts([])


def test_camera_basis_is_orthonormal():
    camera = Camera(yaw=37.0, pitch=23.0, distance=10.0)
    right, up, forward = camera.basis()

    for vector in (right, up, forward):
        assert _dot(vector, vector) == pytest.approx(1.0, abs=1e-12)
    assert _dot(right, up) == pytest.approx(0.0, abs=1e-12)
    assert _dot(right, forward) == pytest.approx(0.0, abs=1e-12)
    assert _dot(up, forward) == pytest.approx(0.0, abs=1e-12)


def test_camera_position_is_behind_target():
    camera = Camera(yaw=0.0, pitch=0.0, distance=10.0)
    right, up, forward = camera.basis()
    position = camera.position()
    assert position == pytest.approx((10.0, 0.0, 0.0))
    assert _dot(position, forward) == pytest.approx(-10.0)
    assert _dot(right, right) == pytest.approx(1.0)
    assert _dot(up, up) == pytest.approx(1.0)


def test_project_center_to_viewport_center():
    camera = Camera()
    camera.fit((1.0, 2.0, 3.0), 10.0)
    projected = camera.project((1.0, 2.0, 3.0), 800, 600)
    assert projected is not None
    assert projected[0] == pytest.approx(400.0)
    assert projected[1] == pytest.approx(300.0)
    assert projected[2] == pytest.approx(camera.distance)


def test_fit_keeps_bounding_box_on_screen():
    camera = Camera()
    camera.fit((0.0, 0.0, 0.0), math.sqrt(75.0))
    for x in (-5.0, 5.0):
        for y in (-5.0, 5.0):
            for z in (-5.0, 5.0):
                point = (x, y, z)
                projected = camera.project(point, 640, 480)
                assert projected is not None
                assert 0.0 <= projected[0] <= 640.0
                assert 0.0 <= projected[1] <= 480.0


def test_face_lighting_is_two_sided():
    upright = (0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0)
    flipped = (0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 1.0, 0.0, 0.0)
    assert _face_intensity(upright) > 0.5
    assert _face_intensity(flipped) == pytest.approx(_face_intensity(upright))
    assert _face_intensity((0.0,) * 9) == 0.0


def test_shade_color_returns_darker_hex():
    dark = _shade_color("#808080", 0)
    bright = _shade_color("#808080", 20)
    assert dark.startswith("#") and len(dark) == 7
    assert bright.startswith("#") and len(bright) == 7
    assert int(dark[1:3], 16) < int(bright[1:3], 16)


def test_zoom_and_pan_are_bounded():
    camera = Camera()
    camera.fit((0.0, 0.0, 0.0), 10.0)
    start = camera.target

    camera.zoom(1e9)
    assert camera.distance == pytest.approx(camera.max_distance)
    camera.zoom(1e-9)
    assert camera.distance == pytest.approx(camera.min_distance)

    camera.distance = 10.0
    camera.pan(10.0, -5.0, 800, 600)
    assert camera.target != start


def test_viewer_main_without_input_opens_dialog(monkeypatch):
    calls = {}

    def fake_ask(**kwargs):
        calls["ask"] = kwargs
        return FIXTURES / "small_field.bdf"

    def fake_show(model, parts=None, **kwargs):
        calls["model"] = model
        calls["parts"] = list(parts or [])

    monkeypatch.setattr("nastran2stl.viewer.ask_for_bdf", fake_ask)
    monkeypatch.setattr("nastran2stl.viewer.show_model", fake_show)

    assert viewer_main([]) == 0
    assert calls["ask"] == {}
    assert [part.pid for part in calls["parts"]] == [100]


def test_viewer_main_reports_read_errors(monkeypatch):
    messages = []

    def fail_read(*_args, **_kwargs):
        raise NastranError("bad input")

    monkeypatch.setattr("nastran2stl.viewer.read_bdf", fail_read)
    monkeypatch.setattr(
        "nastran2stl.viewer._report_error",
        lambda message: messages.append(message),
    )

    assert viewer_main([str(FIXTURES / "small_field.bdf")]) == 1
    assert messages == ["bad input"]


def test_viewer_main_cancel_returns_zero(monkeypatch):
    calls = []
    monkeypatch.setattr("nastran2stl.viewer.ask_for_bdf", lambda **_kwargs: None)
    monkeypatch.setattr(
        "nastran2stl.viewer.show_model",
        lambda *_args, **_kwargs: calls.append(True),
    )
    assert viewer_main([]) == 0
    assert calls == []


def test_cli_view_only_without_input_opens_dialog(monkeypatch):
    calls = {}

    def fake_show(model, parts=None, **kwargs):
        calls["parts"] = list(parts or [])

    monkeypatch.setattr(
        "nastran2stl.cli.ask_for_bdf",
        lambda: FIXTURES / "small_field.bdf",
    )
    monkeypatch.setattr("nastran2stl.cli.show_model", fake_show)

    assert main(["--view-only", "-q"]) == 0
    assert [part.pid for part in calls["parts"]] == [100]


def test_cli_without_input_requires_view(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main([])
    assert excinfo.value.code == 2
    assert "BDF file is required" in capsys.readouterr().err


def test_cli_view_only_opens_viewer_without_writing(monkeypatch, tmp_path):
    calls = {}

    def fake_show(model, parts=None, **kwargs):
        calls["model"] = model
        calls["parts"] = list(parts or [])
        calls["wireframe"] = kwargs.get("wireframe")

    monkeypatch.setattr("nastran2stl.cli.show_model", fake_show)
    code = main(
        [
            str(FIXTURES / "small_field.bdf"),
            "--view-only",
            "--wireframe",
            "-o",
            str(tmp_path),
        ]
    )

    assert code == 0
    assert [part.pid for part in calls["parts"]] == [100]
    assert calls["wireframe"] is True
    assert not list(tmp_path.iterdir())


def test_cli_view_opens_viewer_after_conversion(monkeypatch, tmp_path):
    calls = {}

    def fake_show(model, parts=None, **kwargs):
        calls["model"] = model
        calls["parts"] = list(parts or [])

    monkeypatch.setattr("nastran2stl.cli.show_model", fake_show)
    code = main(
        [
            str(FIXTURES / "small_field.bdf"),
            "-o",
            str(tmp_path),
            "--view",
        ]
    )

    assert code == 0
    assert calls["parts"][0].pid == 100
    assert len(calls["parts"][0].triangles) == 3
    assert (tmp_path / "small_field_all.stl").exists()


def test_cli_view_only_reports_viewer_error(monkeypatch):
    def fake_show(*_args, **_kwargs):
        raise ViewerError("no display")

    monkeypatch.setattr("nastran2stl.cli.show_model", fake_show)
    code = main([str(FIXTURES / "small_field.bdf"), "--view-only", "-q"])
    assert code == 1


def test_view_flags_are_mutually_exclusive(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main([str(FIXTURES / "small_field.bdf"), "--view", "--view-only"])
    assert excinfo.value.code == 2
    assert "mutually exclusive" in capsys.readouterr().err
