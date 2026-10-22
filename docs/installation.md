# Installation

## Requirements

| Component | Requirement |
| --- | --- |
| Python | **3.9 or newer**.  Developed and tested on CPython 3.11.5 (Windows 10). |
| Runtime dependencies | **None.**  The package imports only the Python standard library. |
| Optional GUI | Tkinter.  Bundled with the official Python installers on Windows and macOS.  On Linux install `python3-tk`. |
| Optional STEP export | A local FreeCAD installation providing `FreeCADCmd.exe` (tested with FreeCAD 0.19). |
| Optional Windows build | PyInstaller (only needed to produce the standalone EXE). |

There is intentionally **no** dependency on NumPy, meshio, pyNastran, VTK or
Qt.  That keeps the package small, easy to vendor, and safe to freeze into an
executable.

## Getting the code

Clone the repository:

```bat
git clone https://github.com/istra711/Nastran_File_Converter.git
cd Nastran_File_Converter
```

Or download and unpack the source ZIP from GitHub.

## Running without installing

The package is importable straight from the project folder, so no
installation is required for a first test:

```bat
python -m nastran2stl tests\fixtures\small_field.bdf -o out
```

This writes:

```
out\small_field_pid100.stl        one STL per property ID
out\small_field_all.stl           all objects in one STL
out\small_field_nastran2stl.json  manifest with units, bounds and warnings
```

## Installing the package

An editable install adds a `nastran2stl` console command:

```bat
pip install -e .
nastran2stl model.bdf -o out
```

To install the optional test dependencies:

```bat
pip install -e ".[test]"
python -m pytest -q
```

## Verifying the installation

```bat
python -m nastran2stl --version
python -m nastran2stl --help
python -m pytest -q
```

The test suite must report **96 passed** on a clean checkout.  STEP tests that
need FreeCAD are skipped automatically when no `FreeCADCmd` is present.

## The GUI

Start the converter window directly from the source tree:

```bat
python -m nastran2stl.converter_gui
python -m nastran2stl.converter_gui tests\fixtures\solids_pids.bdf
```

After an editable install the GUI is also available as a module of the
installed package.  See [usage-gui.md](usage-gui.md).

## The 3D viewer

```bat
python -m nastran2stl.viewer model.bdf
python -m nastran2stl.viewer model.bdf --wireframe --solids boundary
```

See [usage-gui.md](usage-gui.md#3d-viewer) for controls.

## Setting up FreeCAD for STEP export

STEP output is optional.  Everything else works without FreeCAD.  To enable
STEP:

1. Install FreeCAD from <https://www.freecad.org/downloads.php>.
2. Make sure `FreeCADCmd.exe` is reachable.  The converter searches, in order:
   1. the `FREECAD_CMD` environment variable,
   2. `FreeCADCmd.exe`, `FreeCADCmd` or `freecadcmd` on `PATH`,
   3. `%ProgramFiles%\FreeCAD*\bin\FreeCADCmd.exe` and the
      `Program Files (x86)` equivalent,
   4. on Linux/macOS, `/usr/bin`, `/usr/local/bin` and `/opt`.

A typical Windows location is:

```
C:\Program Files\FreeCAD 0.19\bin\FreeCADCmd.exe
```

Provide an explicit path when auto-detection fails:

```bat
set FREECAD_CMD=C:\Program Files\FreeCAD 0.19\bin\FreeCADCmd.exe
```

or per run:

```bat
python -m nastran2stl model.bdf -o out --step --freecad "C:\Program Files\FreeCAD 0.19\bin\FreeCADCmd.exe"
```

The GUI displays a status line that shows whether FreeCAD was found and where.

> **Note:** FreeCAD is never bundled.  FreeCAD is **not** included in the EXE,
> the portable ZIP, or the Python package.  STEP export always calls the
> FreeCAD installation already on the machine.  Without FreeCAD the converter
> still writes STL and the manifest, and reports a clear warning.

## The standalone Windows executable

If you only want to run the converter on Windows without Python, use the
portable build from the GitHub releases page:

1. Download `NastranConverter-win64.zip`.
2. Unpack it anywhere.
3. Run `NastranConverter.exe`.

The ZIP is self-contained except for the optional FreeCAD dependency.  To
build it yourself, see [building-windows.md](building-windows.md).

## Uninstalling

```bat
pip uninstall nastran2stl
```

Then delete the cloned folder.  The converter writes nothing outside the
output folders you choose.
