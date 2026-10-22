# Solids and STEP

STL always stores triangles.  Even a closed STL is, for FreeCAD, a triangle
shell and not yet a CAD volume body.  This page explains the three
solid-related paths offered by the converter and the exact conditions under
which a STEP file contains a real (faceted) solid.

## Overview

| # | Name | GUI | CLI | Library | Affects |
| --- | --- | --- | --- | --- | --- |
| 1 | Shell extrusion | **Shells extrudieren (PSHELL T)** | `--shell-solid` | `shell_solid=True` | STL geometry (and STEP) |
| 2 | Volume-element solids | **Volumenelemente als Solid (STEP)** | `--solid-elements` | `solid_elements=True` | STEP metadata only |
| 3 | STEP export | **STEP zusätzlich (FreeCAD)** | `--step` | `step=True` | Whether `.step` files are written |

Options 1 and 2 are **independent** and can be combined.  Option 3 is
orthogonal: it decides whether STEP is produced at all.  Without option 3, only
STL and the manifest are written.

A decision matrix for a single PID:

| PID content | Option 1 | Option 2 | STEP result (with option 3) |
| --- | --- | --- | --- |
| Shells | off | off | Surface shell |
| Shells | **on** | off | Faceted **solid** (closed thin body) |
| Watertight volume skin | off | **on** | Faceted **solid** |
| Watertight volume skin | off | off | Surface shell |
| Open volume skin | off | **on** | Surface shell + warning |
| Open volume skin | off | off | Surface shell |
| Mixed shell + volume | any | any | Warning; treated as before |

## Option 1 — Extrude shells (PSHELL T)

Each shell PID is thickened into a closed thin solid.  The wall thickness comes
from the `PSHELL` card's `T` field (field 3).  If `T` is blank, zero or not
finite, the fallback thickness is used.

- The fallback is given in the **input unit** (`--shell-thickness` / GUI
  **Ersatzdicke**) and is scaled with every other coordinate.
- If no positive thickness is available at all, conversion stops with a clear
  error rather than guessing.

### Algorithm

The implementation is in
[`nastran2stl/solid.py`](../nastran2stl/solid.py) (`extrude_shell_triangles`):

1. Vertices are deduplicated by coordinate (rounded to 1e-10).
2. Each face normal is accumulated per vertex, and the averaged vertex normal
   is normalised.  A fallback normal is used when averages cancel out.
3. The original surface becomes the **mid-plane**.  Top vertices are offset by
   `+t/2` and bottom vertices by `-t/2` along their normal.
4. Top faces reuse the original winding; bottom faces are reversed.
5. For every **boundary edge** (an edge used by exactly one triangle), two side
   triangles connect top and bottom, so the boundary is closed.

The result is a closed triangle mesh.  It is validated by the same
watertightness test used by option 2.  Because the original surface is the
mid-plane, the outer and inner surfaces sit at ±`t/2`; there is no coupling to
`PSHELL` offset (`Z0`) or non-structural mass.

### Special cases

- **Closed input surface.**  If the incoming shell mesh is already closed,
  extruding it produces an inner and an outer shell; a warning is emitted
  because this is usually not intended.
- **Mixed PID.**  If a PID contains both shell and volume elements, shells in
  that PID are **not** extruded; a warning is emitted instead.
- **Degenerate faces.**  Faces that cannot be offset are reported by the normal
  accumulation fallback; the whole mesh is still produced.

> No geometric offsetting, shell-offset handling or mesh healing is attempted.
> Option 1 is a robust "give the surface a thickness" operation, not a
> reconstruction of the original CAD geometry.

## Option 2 — Watertight volume solids

Volume elements (`CTETRA`, `CHEXA`, `CPENTA`, `CPYRAM`) are exported as the
outer skin per PID by default.  Option 2 checks whether that skin is
**watertight** and, if so, marks the object as a solid for STEP.

Watertightness (`is_watertight`) is defined as:

> Every mesh edge is shared by **exactly two** triangles.

Edges are matched by rounded vertex coordinates (10 decimal places).  A single
free edge, a fold with three faces on an edge, or a disconnected component
makes the test fail.

- **Watertight** → STEP receives a solid.
- **Open** → STEP receives a surface; the manifest, the log and
  `result.step_warnings` record a warning.

Option 2 does **not** change the STL geometry: the STL already contains the
boundary skin, so the triangles are identical.  It only changes how the STEP
writer treats them.

Common reasons a volume skin is not watertight:

- duplicated nodes at element interfaces instead of shared node IDs
  (use `--weld-tol`),
- `--solids faces` (internal faces are included by design),
- a genuinely open or non-manifold mesh,
- overlapping or degenerate elements.

## Option 3 — STEP export through FreeCAD

The STL files are handed to an installed FreeCAD in a worker subprocess.  The
converter itself stays small and dependency-free; FreeCAD provides the
OpenCascade B-rep and STEP writer.

### Finding FreeCAD

`nastran2stl.step.find_freecad_cmd()` searches, in order:

1. the `FREECAD_CMD` environment variable (quotes and `~` are handled),
2. `FreeCADCmd.exe`, `FreeCADCmd` or `freecadcmd` on `PATH`,
3. `%ProgramFiles%\FreeCAD*\bin\FreeCADCmd.exe` (and `Program Files (x86)`),
4. `/usr/bin`, `/usr/local/bin`, `/opt` (Linux/macOS).

An explicit executable can be passed with `--freecad` / `freecad_cmd=...`.
The GUI shows whether FreeCAD was found and which version folder was used.

> FreeCAD is **not** bundled with the package, the EXE or the portable ZIP.
> STEP export always uses the FreeCAD installation present on the machine.

### What the FreeCAD script does

For each STL the subprocess:

1. loads the mesh (`Mesh.Mesh`) and builds a shape
   (`Part.Shape.makeShapeFromMesh`) with a tolerance derived from the
   bounding-box diagonal,
2. if a solid is requested (`StepItem.solid`), checks that all shells are
   closed and converts them with `Part.Solid`; valid solids become a
   `Part.makeCompound`,
3. applies the unit scale,
4. writes the STEP file (`exportStep`) and verifies that the file is non-empty.

The per-item status is one of:

| Status | Meaning |
| --- | --- |
| `solid` | A valid faceted solid was written. |
| `shell` | A surface was written (no solid requested). |
| `open_shell` | A solid was requested but the mesh is not closed; a surface was written. |
| `shell_invalid_solid` | The shell is closed but `Part.Solid` rejected it; a surface was written. |
| `error` | The mesh could not be processed; the item is reported. |

### Per-PID and combined STEP

- With per-PID output enabled, each STL becomes `<stem>_pid<PID>.step`.
- The combined STL becomes `<stem>_all.step`, a compound of all successful
  shapes.
- With `--no-split`, temporary per-PID STL files are created internally so that
  FreeCAD can still produce one solid per PID; the temporary files are removed
  afterwards.

### Failure behaviour

STEP problems never destroy the STL output:

- If FreeCAD is missing, `write_step_files` raises `StepError`; the message is
  captured in `result.step_warnings`, STL and the manifest remain valid.
- If an individual item fails, only that item is affected; the remaining items
  and the combined file are still attempted.
- The subprocess runs with `CREATE_NO_WINDOW` on Windows and a 600-second
  timeout.

### Units

FreeCAD writes STEP in **millimetres**.  STL coordinates use `--out-unit`, so
before export the shapes are scaled by:

```
step_scale = unit_factor(unit_out) * 1000
```

For example, with `--out-unit m` the STL is in metres, and the STEP writer
multiplies the shapes by `1 · 1000 = 1000` to reach millimetres.  With
`--out-unit mm` the factor is 1.

### Faceted geometry

The STEP result is a **faceted B-rep**: triangle faces, not smooth NURBS
cylinders or freeform surfaces.  Closed meshes become `MANIFOLD_SOLID_BREP`
bodies; open meshes become shells.  This is a deliberate trade-off: it keeps the
conversion exact, lossless and fast, and avoids unreliable surface fitting.  If
you need smooth CAD geometry, use the STEP file as a reference and remodel, or
apply a mesh-to-NURBS tool.

## Watertightness reference

```python
from nastran2stl import is_watertight, extrude_shell_triangles

closed = is_watertight(part.triangles)
thick = extrude_shell_triangles(part.triangles, thickness=1.0)
assert is_watertight(thick)
```

`extrude_shell_triangles` raises `SolidError` when the thickness is not a
positive finite number or a triangle is malformed.  `is_watertight` returns
`False` (never raises) for malformed input.

## Manual conversion in FreeCAD

Option 1 without STEP already gives a closed STL, which some tools can use
directly.  To get a STEP solid by hand:

1. Import the STL (`File > Import`).
2. `Part > Create shape from mesh`.
3. `Part > Convert to solid` when the shell is closed.
4. `File > Export > STEP`.

The same workflow is described in the GUI **Hilfe** dialog.

## Warning reference

STEP and solid warnings are returned in `ConversionResult.step_warnings` and
prefixed with `STEP:` in `ConversionResult.warnings` and the manifest.  Typical
messages (translated from the built-in German wording):

| Situation | Message |
| --- | --- |
| FreeCAD not found | "FreeCADCmd.exe was not found. STEP needs a FreeCAD installation (or the `FREECAD_CMD` environment variable)." |
| STL missing | "STL file not found: …" |
| Subprocess failed | "FreeCADCmd could not be executed: …" |
| No result file | "FreeCADCmd did not write STEP results." |
| Per-item error | "…: STEP failed (…)" |
| Open mesh | "…: mesh is not closed; STEP contains a surface, not a solid." |
| Closed but rejected | "…: closed shell could not be converted into a valid solid; STEP contains a surface." |
| Combined failure | "Combined STEP file failed (…)" |

Solid-geometry warnings (from `convert`) include:

| Situation | Message |
| --- | --- |
| Missing thickness | "PID n: PSHELL thickness is missing or zero; enter a fallback shell thickness." |
| Extrusion not watertight | "PID n: extruded shell is not watertight; STEP may contain a surface instead of a solid." |
| Closed shell input | "PID n: shell mesh is closed; extrusion creates an inner and an outer shell." |
| Mixed PID | "PID n: mixes shell and volume elements; shells were not extruded." |
| Open volume skin | "PID n: volume boundary is not watertight; STEP will contain a surface instead of a solid." |
