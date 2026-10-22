# Testing

The suite uses [pytest](https://docs.pytest.org/) and runs in a couple of
seconds.  It has **96 tests** and needs no third-party runtime package.

## Running the tests

```bat
python -m pytest -q
```

Expected result on a clean checkout:

```
96 passed
```

Install the test extra if pytest is missing:

```bat
pip install -e ".[test]"
```

Configuration lives in [`pytest.ini`](../pytest.ini): the test path is `tests`
and `.git`, `__pycache__` and `_scratch` are not searched.

## Test layout

| File | Focus |
| --- | --- |
| `test_bdf.py` | Tokenizer, field formats, includes, coordinate systems, units, quads, solid skin, welding, warnings |
| `test_stl.py` | Binary and ASCII STL layout, headers, triangle counts |
| `test_solid.py` | Shell extrusion, watertightness, `SolidError` |
| `test_step.py` | FreeCAD detection, STEP writing, missing-FreeCAD fallback |
| `test_convert.py` | End-to-end conversion, manifest, naming, CLI |
| `test_converter_gui.py` | GUI path/result formatting, option parsing, help text |
| `test_viewer.py` | Camera/scene math and CLI viewer hooks (stubbed) |

`conftest.py` holds shared fixtures and path helpers.

## Fixtures

Hand-written BDF files live in `tests/fixtures/`:

| Fixture | Purpose |
| --- | --- |
| `small_field.bdf` | Small-field triangle shell |
| `large_field.bdf` | Large-field (`GRID*`) variant |
| `free_field.bdf` | Comma/tab free field |
| `quad.bdf` | Quad splitting (`shortest`/`fixed`) |
| `coords_r.bdf`, `coords_c.bdf`, `coords_s.bdf` | Rectangular/cylindrical/spherical systems |
| `coords_rid.bdf` | Nested coordinate-system references |
| `units.bdf` | Clean shell suitable for extrusion tests |
| `midside.bdf` | Higher-order elements (linearised) |
| `degenerate.bdf` | Zero-area triangles |
| `solids.bdf` | Two adjacent `CHEXA` in one PID |
| `solids_pids.bdf` | Two closed boxes with different PIDs |
| `solids_split_nodes.bdf` | Duplicated nodes on solid interfaces (welding) |
| `no_geometry.bdf` | Readable but without usable geometry |
| `include/` | Nested `INCLUDE` files, including a missing target |
| `names.json` | PID → name map |

The fixtures are deliberately tiny so failures are easy to inspect.

## FreeCAD-dependent tests

STEP tests need a working `FreeCADCmd`.  They are **skipped** automatically when
FreeCAD is not installed, and the no-FreeCAD fallback
(`StepError` → warning, STL preserved) is always tested.  This means the suite
is green on machines without FreeCAD, while still exercising the real export
path where FreeCAD is available.

To force a particular executable:

```bat
set FREECAD_CMD=C:\Program Files\FreeCAD 0.19\bin\FreeCADCmd.exe
python -m pytest -q tests\test_step.py
```

## GUI tests

GUI tests do **not** open windows.  They test pure functions such as
`format_result`, `default_output_dir`, `result_output_dir`, option parsing in
`_collect_job` (where practical) and the content of `HELP_TEXT`.  This keeps the
suite headless-friendly.

To smoke-test the window manually:

```bat
python -m nastran2stl.converter_gui tests\fixtures\solids_pids.bdf
```

## Writing new tests

- Put fixtures in `tests/fixtures/` and keep them minimal.
- Prefer asserting on geometry (triangle counts, bounds, watertightness) over
  exact float strings.
- Use `tmp_path` for output directories.
- Guard FreeCAD usage with the existing skip helper so the suite still passes
  without FreeCAD.
- When adding an element type, add a small BDF fixture and a triangulation
  assertion.

## Continuous integration

The suite is designed to run on any CPython 3.9+ platform without extra
services or secrets.  A minimal CI job is:

```yaml
python -m pip install -e ".[test]"
python -m pytest -q
```

STEP tests simply skip where FreeCAD is absent.
