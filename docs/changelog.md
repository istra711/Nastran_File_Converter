# Changelog

All notable changes to this project are documented here.  The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions use
[Semantic Versioning](https://semver.org/).

## [0.2.0] — 2026-10-22

The "solids and STEP" release.

### Added

- **Shell extrusion (option 1).**  `extrude_shell_triangles()` thickens shell
  PIDs by their `PSHELL` thickness `T`, using a fallback thickness when `T` is
  missing or zero.  The original surface becomes the mid-plane; top, bottom and
  boundary side triangles form a closed mesh.
- **Watertight volume solids (option 2).**  `is_watertight()` checks that every
  edge is shared by exactly two triangles so that a volume-element boundary can
  be exported as a STEP solid.
- **Faceted STEP export (option 3)** through an installed FreeCAD.  New module
  `nastran2stl/step.py` with `find_freecad_cmd()`, `write_step_files()`,
  `StepItem`, `StepResult` and `StepError`.  Closed meshes become
  `MANIFOLD_SOLID_BREP` bodies; open meshes remain shells.
- **CLI options** `--shell-solid`, `--shell-thickness`, `--solid-elements`,
  `--step` and `--freecad`, plus extended console output (solid flags, STEP
  files, extrusions).
- **GUI options** as independent checkboxes.  Options 1 and 2 are selectable
  independently; a fallback-thickness field, a STEP option, a FreeCAD status
  line and a **Hilfe** dialog were added.
- **Library API** for the new features: `extrude_shell_triangles`,
  `is_watertight`, `SolidError`, `StepItem`, `StepResult`, `StepError`,
  `find_freecad_cmd`, `write_step_files`.
- `MeshPart.shell_count`, `MeshPart.solid_count`, `MeshPart.is_shell` and
  `MeshPart.is_solid`.
- Manifest fields `solid`, `thickness`, `step`, `combined_step`,
  `step_warnings` and extended statistics (`objects_written`,
  `triangles_written`, `shell_extrusions`, `solids_written`,
  `step_files_written`).
- Solid/STEP warnings for missing thickness, open boundaries, closed shell
  input, mixed PIDs and FreeCAD failures.
- Tests `test_solid.py` and `test_step.py`, plus expanded coverage in
  `test_convert.py`, `test_converter_gui.py` and `test_bdf.py` (**96 tests**).
- Full English documentation in `docs/`.

### Changed

- STEP files are always written in millimetres; the exporter applies a `×1000`
  factor when the STL output unit is not `mm`.
- `requires-python` raised to `>=3.9`, consistent with module-level PEP 585
  generics.
- Package metadata: keywords, classifiers and author.
- README restructured with a documentation index.

### Fixed

- STEP export uses `out.exportStep(path)` instead of `Part.export([shape], path)`,
  which could produce empty files.
- GUI layout: removed a checkbox/label overlap in the solid option row and set a
  minimum window size so the row never clips.

## [0.1.0] — initial baseline

The original STL converter.

### Added

- Dependency-free BDF/NAS/DAT reader: small field, large field and free field,
  continuation lines, `$` comments, `BEGIN BULK`/`ENDDATA`, nested `INCLUDE`.
- Shells (`CTRIA3/6`, `CQUAD4/8/9`) and volume elements (`CTETRA`, `CHEXA`,
  `CPENTA`, `CPYRAM`) triangulated per PID; solid outer-skin extraction.
- `CORD2R/C/S` coordinate systems, including nested references.
- Unit conversion between `m`, `cm`, `mm`, `um`, `nm`, `in`, `ft` and `mil`.
- Binary and ASCII STL writers; per-PID and combined output; JSON manifest.
- CLI, Tkinter converter GUI and a dependency-free 3D preview.
- PyInstaller Onedir build script producing `NastranConverter.exe` and a
  portable ZIP.

[0.2.0]: https://github.com/istra711/Nastran_File_Converter/releases/tag/v0.2.0
[0.1.0]: https://github.com/istra711/Nastran_File_Converter/releases
