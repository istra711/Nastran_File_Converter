# nastran2stl — standalone Nastran BDF → STL/STEP converter

[![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)
[![Dependencies](https://img.shields.io/badge/runtime%20dependencies-none-brightgreen.svg)](pyproject.toml)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey.svg)](#requirements)
[![Tests](https://img.shields.io/badge/tests-96%20passing-brightgreen.svg)](#tests)
[![Version](https://img.shields.io/badge/version-0.2.0-blue.svg)](docs/changelog.md)

A small, **dependency-free** Python package that turns Nastran bulk-data
(`BDF`/`NAS`/`DAT`) meshes into STL files and optionally into faceted STEP
files.  It can extrude shells into closed thin solids and turn watertight
volume-element boundaries into STEP solids through an installed FreeCAD.  It is
designed both as a command line tool and as a library that can later be plugged
into **VisualOpenEMS / FreeCAD_OpenEMS_GUI**.

Because it uses only the Python standard library, it is easy to embed, vendor,
audit, and freeze into a single Windows executable.

## Documentation

The full manual lives in [`docs/`](docs/index.md).  This README is the quick
overview; the linked pages go into depth.

| Page | Contents |
| --- | --- |
| [docs/index.md](docs/index.md) | Documentation hub and suggested reading order |
| [docs/installation.md](docs/installation.md) | Requirements, installation, first conversion, FreeCAD setup |
| [docs/usage-cli.md](docs/usage-cli.md) | Complete command line reference with examples |
| [docs/usage-gui.md](docs/usage-gui.md) | Window walkthrough, options 1/2/3, log, viewer |
| [docs/formats-and-parsing.md](docs/formats-and-parsing.md) | Supported cards, field formats, coordinate systems, triangulation |
| [docs/solids-and-step.md](docs/solids-and-step.md) | Shell extrusion, watertight solids, faceted STEP, FreeCAD |
| [docs/library-api.md](docs/library-api.md) | Public Python API with worked examples |
| [docs/architecture.md](docs/architecture.md) | Module map, data flow and design decisions |
| [docs/building-windows.md](docs/building-windows.md) | Reproducing the standalone Windows EXE |
| [docs/testing.md](docs/testing.md) | Test suite, fixtures and how to run them |
| [docs/troubleshooting.md](docs/troubleshooting.md) | Symptoms, causes and fixes |
| [docs/limitations.md](docs/limitations.md) | Known limitations and non-goals |
| [docs/faq.md](docs/faq.md) | Frequently asked questions |
| [docs/changelog.md](docs/changelog.md) | Version history |
| [CONTRIBUTING.md](CONTRIBUTING.md) | How to contribute |

## Table of contents

- [Features](#features)
- [Quick start](#quick-start)
- [GUI converter](#gui-converter)
- [Solids and STEP](#solids-and-step)
- [3D viewer](#3d-viewer)
- [Windows EXE](#windows-exe)
- [Library / plugin API](#library--plugin-api)
- [Behaviour and limitations](#behaviour-and-limitations)
- [Tests](#tests)
- [Layout](#layout)

## Features

- ASCII BDF/NAS input (`.bdf`, `.nas`, `.dat`).
- All three Nastran field formats: 8-character small field, 16-character large
  field (`GRID*`), and free field (commas, tabs).
- Continuation lines, `$` comments, `BEGIN BULK`/`ENDDATA`, nested `INCLUDE`
  files (paths relative to the including file).
- Shells: `CTRIA3`, `CTRIA6`, `CQUAD4`, `CQUAD8`, `CQUAD9`
  (higher-order elements are linearised; quads are split along the shortest
  diagonal).
- Solids: `CTETRA`, `CHEXA`, `CPENTA`, `CPYRAM` — exported as the **outer
  skin per PID** by default (shared internal faces removed).
- `GRID` coordinate systems: `CORD2R`, `CORD2C`, `CORD2S` (including nested
  RID references).  `CD` is ignored because STL carries no coordinate system.
- Unit conversion between `m`, `cm`, `mm`, `um`, `nm`, `in`, `ft`, `mil`.
- One STL per property ID (PID), an optional combined STL, and a JSON manifest
  with bounds, triangle counts and warnings.
- Optional shell extrusion by `PSHELL` thickness `T`, with a fallback
  thickness when `T` is missing or zero.  The original surface becomes the
  mid-plane; top, bottom and boundary side triangles form a closed mesh.
- Optional STEP export through an installed `FreeCADCmd.exe`.  Closed meshes
  are written as faceted `Part.Solid` bodies; open meshes remain surfaces.
- Optional solid treatment for watertight `CTETRA`/`CHEXA`/`CPENTA`/`CPYRAM`
  boundaries.  Open boundaries are detected and reported.
- Binary STL by default, ASCII on request.
- Tkinter converter window with visible output folder, conversion log,
  solid/STEP options and an "open output folder" action.
- Built-in GUI help for solids, STEP and manual FreeCAD conversion.
- Interactive 3D preview with Tkinter (rotate, pan, zoom, wireframe, per-PID
  visibility); no OpenGL or third-party GUI toolkit required.
- No Python third-party dependencies — no numpy, no meshio, no pyNastran.
  STEP is optional and uses an external FreeCAD installation.

## Quick start

No installation is required; run the package from this folder:

```bat
cd Nastran_File_Converter

python -m nastran2stl tests\fixtures\small_field.bdf -o out
```

Optionally install it (also provides a `nastran2stl` console command):

```bat
pip install -e .
nastran2stl model.bdf -o out
```

Output:

```
out\small_field_pid100.stl              one STL per PID
out\small_field_all.stl                 everything in one STL
out\small_field_nastran2stl.json        manifest (units, bounds, warnings)
out\small_field_pid100.step             optional STEP (with --step)
out\small_field_all.step                optional combined STEP
```

Common options:

```bat
:: source is in inches, output in millimetres
python -m nastran2stl model.bdf -o out --unit in --out-unit mm

:: only shells, ignore volume elements
python -m nastran2stl model.bdf -o out --solids skip

:: every solid element face instead of the outer skin
python -m nastran2stl model.bdf -o out --solids faces

:: merge duplicated nodes on solid interfaces (tolerance in source units)
python -m nastran2stl model.bdf -o out --weld-tol 1e-6

:: readable ASCII STL, no combined file
python -m nastran2stl model.bdf -o out --ascii --no-combined

:: names for PIDs (Nastran PSHELL cards have no name field)
python -m nastran2stl model.bdf -o out --names names.json

:: extrude shells by PSHELL T (fallback 1.0 for shells without T)
python -m nastran2stl model.bdf -o out --shell-solid --shell-thickness 1.0

:: write faceted STEP files with FreeCAD; treat closed volume skins as solids
python -m nastran2stl model.bdf -o out --solid-elements --step

:: STEP with an explicit FreeCADCmd path
python -m nastran2stl model.bdf -o out --step --freecad "C:\Program Files\FreeCAD 0.19\bin\FreeCADCmd.exe"

:: inspect the mesh without writing STL files
python -m nastran2stl model.bdf --view-only

:: convert and then open the result in the 3D viewer
python -m nastran2stl model.bdf -o out --view
```

`names.json`:

```json
{
  "100": "enclosure",
  "500": { "name": "block" }
}
```

Run `python -m nastran2stl --help` for all options.

## GUI converter

The converter window is the main standalone application.  Start it with an
optional BDF path:

```bat
python -m nastran2stl.converter_gui
python -m nastran2stl.converter_gui tests\fixtures\solids_pids.bdf
```

The window contains the input file, the output folder, unit and solids options,
the per-PID/combined output switches, the solid/STEP options, a conversion log
and a **3D anzeigen** button.  The two solid modes are independent:

- **Shells extrudieren (PSHELL T)** — option 1; uses `PSHELL` `T`.  If `T`
  is missing or zero, the value in **Ersatzdicke** is used (in the input
  unit).  The STL becomes a closed thin solid even without FreeCAD.
- **Volumenelemente als Solid (STEP)** — option 2; marks watertight volume
  boundaries as solids for STEP.  Open boundaries stay surfaces.
- **STEP zusätzlich (FreeCAD)** — writes `.step` files next to the STL files.
  FreeCADCmd is auto-detected; the status line shows whether it was found.
- **Hilfe** — explains the options and the manual FreeCAD workflow.

The default output folder is:

```
<input folder>\<input stem>_stl
```

After conversion the full output path is shown in the log and in a confirmation
dialog.  **Ausgabeordner öffnen** opens the folder in Explorer.  The 3D viewer
opens in a separate window and can also be used before converting.

## Solids and STEP

An STL file always stores triangles; a closed STL is still a triangle shell,
not a CAD solid.  The converter therefore offers three solid-related paths:

1. **Shell extrusion (option 1).**  Each shell PID is thickened by `PSHELL`
   `T`.  If `T` is missing or zero, `--shell-thickness` / the GUI fallback is
   used.  The fallback is interpreted in the input unit and is scaled like all
   other coordinates.  The result is a watertight triangle mesh with the
   original surface at its mid-plane.
2. **Volume-element solids (option 2).**  The outer skin of a volume PID is
   checked for watertightness.  If every edge is shared by exactly two
   triangles, STEP gets a solid; otherwise the STEP file keeps the surface and
   the manifest/log reports a warning.  This option does not change the STL
   geometry, because the STL already contains the boundary skin.
3. **STEP and FreeCAD (option 3).**  STEP output requires a local FreeCAD
   installation.  The converter looks for `FreeCADCmd.exe` in `FREECAD_CMD`,
   `PATH` and the usual `C:\Program Files\FreeCAD*\bin` folders.  A specific
   executable can be given with `--freecad`; the GUI status line shows the
   auto-detected path.  FreeCAD is **not** bundled into the EXE.

The STEP result is faceted B-rep geometry: triangle faces, not smooth NURBS
cylinders or freeform surfaces.  Closed meshes become `MANIFOLD_SOLID_BREP`
bodies; open meshes become shells.  STEP is always written in millimetres, so
coordinates are converted when the STL output unit is not `mm`.  A FreeCAD
failure never deletes already written STL files; it becomes a warning in the
result and in the manifest.

Manual conversion in FreeCAD:

1. Import the STL (`File > Import`).
2. `Part > Create shape from mesh`.
3. `Part > Convert to solid` if the mesh is closed.
4. `File > Export > STEP`.

## 3D viewer

The viewer is a small software renderer built on Tkinter.  It is independent of
OpenGL, numpy and the Qt/FreeCAD application and can be launched directly:

```bat
:: open the file dialog and choose a BDF
python -m nastran2stl.viewer

:: open a file directly
python -m nastran2stl.viewer model.bdf
python -m nastran2stl.viewer model.bdf --wireframe --solids boundary
```

Or from the normal CLI:

```bat
:: choose a file in the dialog, only view it, write nothing
python -m nastran2stl --view-only

:: only view, do not write anything
python -m nastran2stl model.bdf --view-only

:: write STL/manifest first, then show the model
python -m nastran2stl model.bdf -o out --view
```

If no input path is given to `python -m nastran2stl.viewer` or to the CLI
together with `--view-only`/`--view`, a small dialog with a path field and a
native **Browse** button opens.  Cancelling the dialog exits without error.

Controls:

| Input | Action |
| --- | --- |
| Left-drag | Rotate/orbit |
| Shift+left-drag or middle-drag | Pan |
| Mouse wheel | Zoom |
| `W` | Toggle wireframe |
| `F` | Fit model to window |
| `R` | Reset camera |
| `T` | Top view |
| `Esc` | Close window |
| Checkboxes in the sidebar | Show/hide individual PIDs |

Each PID gets a stable colour.  The window title shows the triangle count, and
`--wireframe` starts in wireframe mode.  Very large meshes are decimated while
dragging and rendered at full detail after the mouse button is released.

Tkinter is part of the standard Windows Python distribution.  On Linux install
it with the distribution package (for example `python3-tk`); on systems without
a graphical display, `--view-only` and `--view` report a clear error.  The
headless part of the viewer (`Scene`, `Camera`) can still be imported and used.

## Windows EXE

Build the standalone converter with PyInstaller (already installed in this
environment):

```bat
.\build_exe.ps1
```

Result:

```
dist\NastranConverter\NastranConverter.exe   converter window (needs _internal nearby)
dist\NastranConverter-win64.zip              portable distribution of the folder
```

The EXE opens the converter window.  A BDF path can be passed on the command
line or dragged onto the EXE; the input and default output folder are then
prefilled.  STEP export still uses the installed FreeCADCmd; FreeCAD is not
included in the EXE or ZIP.  The Onedir build is used because PyInstaller
one-file executables are frequently quarantined by antivirus heuristics.  For
a one-file build (when the local scanner allows it):

```bat
python -m PyInstaller --noconfirm --clean --onefile --windowed --name NastranConverter --paths . NastranConverter.py
```

`NastranConverter.py` is only the GUI entry point and can also be started with
`python NastranConverter.py`.  `NastranViewer.py` remains available as a
viewer-only entry point.

## Library / plugin API

```python
from nastran2stl import read_bdf, convert, write_binary_stl

model = read_bdf("model.bdf")

for part in model.parts(solids="boundary"):
    print(part.pid, part.name, part.kind, len(part.triangles))
    print("bounds:", part.bounds())
    # part.triangles is a list of flat (ax, ay, az, bx, by, bz, cx, cy, cz)

result = convert("model.bdf", "out", unit_in="mm", unit_out="mm")
for obj in result.objects:
    print(obj.pid, obj.name, obj.stl_path)
print(result.bounds, result.warnings, result.stats)

# Optional solids and STEP:
result = convert(
    "model.bdf",
    "out",
    shell_solid=True,          # extrude shells by PSHELL T
    shell_thickness=1.0,       # fallback in input units
    solid_elements=True,       # mark watertight volume skins as solids
    step=True,                 # write faceted STEP through FreeCAD
)
for obj in result.objects:
    print(obj.pid, "solid:", obj.solid, "thickness:", obj.thickness)
    print("  STL:", obj.stl_path)
    print("  STEP:", obj.step_path)
print("combined STEP:", result.combined_step_path)
print("STEP warnings:", result.step_warnings)
```

`FreeCADCmd.exe` can be selected explicitly with
`convert(..., freecad_cmd=r"C:\Program Files\FreeCAD 0.19\bin\FreeCADCmd.exe")`.
If FreeCAD is missing, the STL/manifest are still written and the STEP problem
is returned in `result.step_warnings`.

To open the viewer from Python:

```python
from nastran2stl import convert, read_bdf, show_model

model = read_bdf("model.bdf")
show_model(model)                       # blocks until the window is closed
show_model(model, wireframe=True)       # optional start mode

# Reuse triangles from a conversion:
result = convert("model.bdf", "out")
show_model(result.model, result.objects)
```

`show_scene()` accepts an already prepared `Scene`; `show_file()` combines
reading and showing.  `block=False` returns the `ViewerWindow` so an existing
Tk application can keep control of its main loop.  For a standalone file
picker, use:

```python
from nastran2stl import ask_for_bdf, show_file

path = ask_for_bdf()          # None if the user cancels
if path is not None:
    show_file(path)
```

### Using it from FreeCAD_OpenEMS_GUI

The converter has no Qt, FreeCAD or openEMS imports, so it can be vendored or
installed next to the application and called from the import path:

```python
import numpy as np
from nastran2stl import read_bdf

model = read_bdf(path)
for part in model.parts(scale=scale, solids="boundary"):
    triangles = np.asarray(part.triangles, dtype=float).reshape(-1, 3, 3)
    np.save(obj_dir / f"{part.name}.npy", triangles)
```

The existing `add_triangle_mesh()` builder writes the STL on demand and already
handles axis-aligned closed boxes, so no changes to the CSX builder are needed.
Set `scale` so that the STL coordinates match `project.mesh.drawing_unit`
(`project.mesh.unit_to_meters()`); `GeometryFile.unit` is currently not
evaluated by the application.

A combined STL can also be imported manually with **Import Geometry…**.

## Behaviour and limitations

- **Sources are ASCII BDF only.** Binary `OP2` is a different format and is not
  supported.
- **PSHELL has no name.** Nastran property cards store only the PID; use
  `--names` to give objects meaningful names.
- **Shells are surfaces by default.** Without `--shell-solid` they are written
  as open triangle meshes; openEMS needs either a thickness (`PSHELL` `T`) or a
  `conducting_sheet` material.  With `--shell-solid`, shells are extruded into
  closed thin meshes.  No geometric offsetting or mesh healing is attempted.
- **Solid skin is per PID.** Internal faces between elements of the same PID
  are removed.  Faces between different PIDs remain, so every PID stays a
  closed region.  If the mesh has duplicated nodes instead of shared node IDs,
  use `--weld-tol` to remove the internal faces.  Watertightness is checked by
  edge counts; duplicated or non-manifold geometry can therefore prevent STEP
  solid creation.
- **STEP is faceted.** It is a B-rep made of triangle faces, not smooth NURBS
  geometry.  STEP export needs FreeCADCmd; without it, only STL is written.
- **Higher-order elements** (`CTRIA6`, `CQUAD8`, `CQUAD9`, 10-node tets,
  20-node hexes) are linearised using their corner nodes.  A warning is added.
- **`CORD1R/C/S`** (coordinate systems defined by grid points) are not
  supported.  `GRID` entries referring to an undefined system keep their raw
  coordinates and are reported as warnings.
- **Unsupported cards** (bars, beams, rigid elements, masses, loads, …) are
  ignored; the manifest lists unknown card names with counts.
- Free-field blank-delimited data (spaces without commas) is not detected as
  free field; use commas or tabs.

## Tests

```bat
python -m pytest -q
```

The test suite covers all field formats, nested includes, coordinate systems,
quads, solid skin extraction, duplicate-node welding, unit scaling, STL layout,
manifest content, naming, the CLI, the viewer's camera/scene math, the
converter GUI's path/result formatting, shell extrusion, watertight detection,
solid metadata and STEP export.  STEP tests are skipped when FreeCADCmd is not
installed; the no-FreeCAD fallback is always tested.  GUI windows are not opened
by the tests; the CLI viewer hooks are tested with a stub.

## Layout

```
nastran2stl/
    __init__.py      public API
    bdf.py           tokenizer, parser, coordinate systems, triangulation
    stl.py           binary and ASCII STL writers
    solid.py         shell extrusion and watertightness helpers
    step.py          optional FreeCAD STEP export
    convert.py       file conversion, naming, manifest
    converter_gui.py Tkinter converter window
    viewer.py        dependency-free Tkinter 3D preview
    cli.py           command line interface
    __main__.py      python -m nastran2stl
NastranConverter.py  converter EXE entry point
NastranViewer.py     viewer-only entry point
build_exe.ps1        PyInstaller build script
docs/                full English manual
CONTRIBUTING.md      contribution guide
pyproject.toml       packaging metadata
pytest.ini           pytest configuration
tests/
    fixtures/        small hand-written BDF files
    test_bdf.py
    test_stl.py
    test_solid.py
    test_step.py
    test_convert.py
    test_converter_gui.py
    test_viewer.py
```

## Contributing

Bug reports, feature requests and pull requests are welcome.  Please read
[`CONTRIBUTING.md`](CONTRIBUTING.md) first.  In short:

- keep the package **dependency-free** (standard library only),
- keep the layered API intact,
- run `python -m pytest -q` before opening a pull request,
- document user-facing changes in the README, the `docs/` pages and the
  [changelog](docs/changelog.md).

## License

This repository currently does **not** include a license file.  Without one,
the default is "all rights reserved": others may view and fork the code on
GitHub, but reuse and redistribution are not granted.  If you intend to allow
reuse, add a license (for example MIT or Apache-2.0) and reference it here.

## Acknowledgements

- [FreeCAD](https://www.freecad.org/) provides the optional STEP export.
- [openEMS](https://www.openems.de/) and FreeCAD_OpenEMS_GUI motivated the
  triangle-array API.
- [pyNastran](https://pynastran-git.readthedocs.io/) was a useful reference for
  Nastran card semantics.
