# Architecture

This page explains how the package is organised and why.  It is aimed at
contributors and at anyone embedding `nastran2stl` into another application.

## Design goals

1. **Zero runtime dependencies.**  Only the Python standard library is used.
   This keeps the package small, easy to vendor, audit and freeze, and makes it
   suitable for embedding in CAD/CAE applications.
2. **Correct geometry first.**  The reader prefers faithful triangles over
   clever surface reconstruction.  STEP output is intentionally faceted.
3. **Optional heavy features.**  STEP needs FreeCAD, which is detected and
   called in a subprocess.  Everything else works without it.
4. **Layered API.**  A low-level parser (`read_bdf`) and a high-level file
   converter (`convert`) cover both integration styles.
5. **One behaviour, three front ends.**  The CLI, the GUI and the library all
   call the same `convert()` and share the same semantics.

## Module map

```
nastran2stl/
    __init__.py       public API, lazy viewer imports, __version__
    bdf.py            tokenizer, parser, coordinate systems, triangulation
    stl.py            binary and ASCII STL writers
    solid.py          shell extrusion and watertightness helpers
    step.py           optional FreeCAD STEP export (subprocess)
    convert.py        file conversion, naming, manifest, plugin result
    cli.py            command line interface
    converter_gui.py  Tkinter converter window
    viewer.py         dependency-free Tkinter 3D preview
    __main__.py       `python -m nastran2stl`
NastranConverter.py   GUI/EXE entry point
NastranViewer.py      viewer-only entry point
build_exe.ps1         PyInstaller Onedir build + ZIP
pytest.ini            pytest configuration
pyproject.toml        packaging metadata
docs/                 this manual
tests/                test suite and BDF fixtures
```

## Data flow

```
BDF file
   │  _iter_source      (comments, BEGIN BULK, ENDDATA, INCLUDE expansion)
   ▼
line stream ──► _iter_cards ──► Card(name, fields, source, lineno)
   │                              │
   │                              ├─ GRID          → raw_nodes (+ CP)
   │                              ├─ shell/solid   → Element
   │                              ├─ property card → Property
   │                              └─ CORD2*        → CoordSystem
   ▼
read_bdf ──► BdfModel(nodes, elements, properties, coordsystems,
                       warnings, stats, unsupported)
   │
   │  BdfModel.parts(scale, quad_split, solids, weld_tol, names)
   ▼
MeshPart list (triangles per PID)
   │
   │  convert(...)
   ├─ option 1: extrude_shell_triangles  → closed thin solid
   ├─ option 2: is_watertight            → solid flag for STEP
   ├─ write_stl                          → per-PID / combined STL
   ├─ option 3: write_step_files         → FreeCAD subprocess → STEP
   └─ _write_manifest                    → JSON manifest
   ▼
ConversionResult(source, model, objects, paths, warnings, stats, ...)
```

## Layer responsibilities

### `bdf.py` — parsing and triangulation

- **Tokenizer.**  `_iter_source` expands includes and strips comments; `_iter_cards`
  assembles cards and continuation lines across the three field formats.
- **Numeric parsing.**  `parse_float` / `parse_int` handle implicit exponents and
  invalid fields.
- **Coordinate systems.**  `_resolve_cs` resolves `RID` chains with cycle
  detection; `_apply_cs` transforms rectangular/cylindrical/spherical nodes.
- **Model.**  `BdfModel` stores nodes, elements, properties, systems, statistics
  and warnings.
- **Triangulation.**  `parts()` groups elements by PID, triangulates shells and
  quads, and extracts solid boundaries with `_boundary_triangles`.
- **Robustness.**  Degenerate triangles are dropped with a scale-independent
  test; missing nodes and incomplete elements are counted and warned about.

### `stl.py` — output

Two writers (`write_binary_stl`, `write_ascii_stl`) behind `write_stl`.  The
binary writer streams in 50-byte records using `struct`, avoiding a second full
copy of large meshes.

### `solid.py` — shells to solids

`extrude_shell_triangles` builds averaged vertex normals and offsets the
original surface to a mid-plane, closing boundary edges.  `is_watertight`
implements the "every edge shared by exactly two triangles" test.  The module
has no knowledge of BDF; it works on plain triangle tuples.

### `step.py` — FreeCAD bridge

- `find_freecad_cmd` performs detection.
- `write_step_files` serialises a small job description, writes a Python script
  and runs `FreeCADCmd` in a subprocess (`CREATE_NO_WINDOW`, 600 s timeout),
  then parses the JSON result the script writes.
- The FreeCAD script uses `Mesh.Mesh` + `makeShapeFromMesh` and, for solids,
  `Part.Solid`.  It verifies non-empty output.

This isolation means FreeCAD version differences, crashes and hangs cannot take
down the converter process.

### `convert.py` — orchestration

- Validates parameters.
- Calls `read_bdf` and `parts`.
- Applies options 1 and 2 per PID, collecting warnings.
- Writes STL files with de-duplicated names.
- Drives STEP export (including temporary per-PID STLs when `--no-split`).
- Computes overall bounds and extended statistics.
- Writes the JSON manifest.
- Returns a `ConversionResult` rich enough for a plugin.

### `cli.py`, `converter_gui.py`, `viewer.py` — front ends

- `cli.py` is a thin `argparse` wrapper with a human-readable summary and
  warning output on stderr.
- `converter_gui.py` runs `convert()` in a worker thread and communicates with
  the Tk main loop through a `queue.Queue`.
- `viewer.py` is a self-contained software renderer (projection + painter's
  algorithm) on a Tk `Canvas`.

## Design decisions

| Decision | Rationale |
| --- | --- |
| Standard library only | Portability, auditability, tiny footprint, easy vendoring/freezing. |
| STEP via external FreeCAD | Avoids shipping a huge CAD kernel and keeps licensing simple. |
| Faceted STEP | Exact, lossless and fast; avoids unreliable NURBS fitting. |
| Solid skin **per PID** | Keeps each object a closed region, which matches how STL files are consumed. |
| Binary STL by default | Smaller files; ASCII available for inspection. |
| Onedir PyInstaller build | One-file executables are frequently quarantined by antivirus heuristics. |
| Lazy viewer import | `import nastran2stl` stays free of GUI code and avoids runpy warnings. |
| De-duplicated warnings | Keeps logs usable on large, messy meshes. |

## Threading and processes

- The GUI runs `convert()` in a daemon worker thread and polls a queue from the
  Tk main loop.  Only the worker touches the converter.
- STEP export spawns `FreeCADCmd` as a separate process.  The converter never
  imports FreeCAD modules.
- The viewer runs entirely on the Tk main loop.

## Error model

- Recoverable issues become **warnings** (missing includes, unsupported cards,
  undefined coordinate systems, non-watertight STEP, …).
- Fatal issues raise typed exceptions: `NastranError` /
  `NoGeometryError` (parsing, missing thickness), `SolidError`
  (geometry helpers), `StepError` (STEP), `ViewerError` (display).
- The CLI maps these to exit codes `1` (failure) and `2` (no geometry).

## Extending the parser

To add an element type:

1. Add the card name to `KNOWN_CARDS`.
2. Describe its corner nodes: `SHELL_TRI`, `SHELL_QUAD` or `SOLID_CORNERS`.
3. For volume elements, add a `SOLID_FACES` entry listing the local faces.
4. The tokenizer, triangulation, boundary extraction, extrusion and STEP paths
   then work unchanged.

Unsupported cards are automatically counted and surfaced in the manifest, so
partial support is safe.
