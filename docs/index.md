# nastran2stl documentation

**nastran2stl** converts Nastran bulk-data (`BDF`/`NAS`/`DAT`) meshes into
STL files and, optionally, into faceted STEP solid models.  It runs as a
command line tool, as a Tkinter desktop application, as a Windows executable,
and as an importable, dependency-free Python library.

This is the documentation hub.  The project overview and a condensed quick
start live in the top-level [`README.md`](../README.md); the pages below cover
each topic in depth.

## Suggested reading order

1. **[Installation](installation.md)** — what you need and how to run the
   first conversion.
2. **[Command line usage](usage-cli.md)** — every switch with realistic
   examples.
3. **[GUI usage](usage-gui.md)** — the desktop converter, including the three
   solid/STEP options.
4. **[Formats and parsing](formats-and-parsing.md)** — which cards and field
   formats are understood and how triangles are produced.
5. **[Solids and STEP](solids-and-step.md)** — shell extrusion, watertight
   volume solids and faceted STEP export.
6. **[Library API](library-api.md)** — embed the converter in your own tool.
7. **[Architecture](architecture.md)** — how the package is built.
8. **[Building on Windows](building-windows.md)** — reproduce the EXE.
9. **[Testing](testing.md)** — run and extend the test suite.
10. **[Troubleshooting](troubleshooting.md)**, **[Limitations](limitations.md)**,
    **[FAQ](faq.md)** and **[Changelog](changelog.md)** for reference.

## What the tool does

- Reads ASCII Nastran `BDF`/`NAS`/`DAT` files with all three field formats
  (small field, large field, free field), continuation lines, `$` comments and
  nested `INCLUDE` files.
- Triangulates shell elements (`CTRIA3/6`, `CQUAD4/8/9`) and extracts the outer
  skin of volume elements (`CTETRA`, `CHEXA`, `CPENTA`, `CPYRAM`).
- Applies `CORD2R/C/S` rectangular, cylindrical and spherical coordinate
  systems, including nested references.
- Converts units between metres, centimetres, millimetres, micrometres,
  nanometres, inches, feet and mils.
- Writes one binary or ASCII STL per property ID (PID) plus an optional
  combined STL and a JSON manifest.
- **Optionally** extrudes shells into closed thin solids using the `PSHELL`
  thickness `T`, with a fallback thickness.
- **Optionally** treats watertight volume-element boundaries as solids.
- **Optionally** writes faceted STEP files through an installed FreeCAD.
- Provides a Tkinter converter window and a lightweight 3D preview, both
  without OpenGL or third-party GUI toolkits.

## What the tool does *not* do

- It is not a solver and does not read result files (`OP2`, `F06`, `PCH`).
- It is not a full-featured Nastran pre/post-processor.  It focuses on the
  geometric subset needed to obtain correct triangle and solid geometry.
- It does not heal meshes or recreate smooth NURBS surfaces.  STEP output is
  faceted by design.

## Requirements at a glance

| Component | Requirement |
| --- | --- |
| Python | 3.9 or newer (developed and tested on CPython 3.11.5) |
| Third-party Python packages | **none** for STL, viewer and GUI |
| GUI | Tkinter (bundled with the standard Windows/macOS installers) |
| STEP export | An installed FreeCAD (`FreeCADCmd.exe`); optional |
| Standalone EXE | PyInstaller (build-time only) |

See [installation.md](installation.md) for the details.

## Quick links

- Repository files: [`README.md`](../README.md), [`pyproject.toml`](../pyproject.toml)
- Contributing guide: [`CONTRIBUTING.md`](../CONTRIBUTING.md)
- Import feasibility assessment for FreeCAD_OpenEMS_GUI:
  [`NASTRAN_IMPORT_ASSESSMENT_EN.md`](../NASTRAN_IMPORT_ASSESSMENT_EN.md)
- Windows build script: [`build_exe.ps1`](../build_exe.ps1)
