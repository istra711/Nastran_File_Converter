# Troubleshooting

This page lists common symptoms, their likely causes and fixes.

## "No supported shell/solid geometry with valid nodes"

The file was read but produced no triangles.

- Check that the file contains `CTRIA3/6`, `CQUAD4/8/9`, `CTETRA`, `CHEXA`,
  `CPENTA` or `CPYRAM`.
- Check that the `GRID` cards are actually present; if the geometry is in an
  `INCLUDE` file, verify the path (see below).
- If the model is volume-only and you passed `--solids skip`, volume elements
  are ignored by design.
- Open the manifest/statistics: `elements_missing_nodes` and
  `elements_incomplete` show how many elements were dropped.

Exit code `2` means *every* input had this problem.

## `INCLUDE` files are not found

- Paths are resolved relative to the **including** file, not the current
  directory.
- Matching is case-insensitive against the folder, but the folder itself must
  exist.
- Nesting deeper than 16 levels is ignored.
- Missing includes are warnings, not errors, and are counted as
  `includes_missing`; the conversion continues with what it has.

## Nothing appears in the output folder

- Check the **Ausgabeordner** field or `-o`.  The default is
  `<input folder>\<stem>_stl` in the GUI, or the input folder itself on the CLI.
- Both `--no-split` and `--no-combined` disable all STL output; the CLI rejects
  that combination.
- `--view-only` writes nothing by design.

## STEP is not written

Most often FreeCAD was not found.

> The error message is part of `result.step_warnings` and appears as
> `STEP: …` in the log and manifest.  STL files are still valid.

Fixes:

1. Install FreeCAD.
2. Set `FREECAD_CMD`:

   ```bat
   set FREECAD_CMD=C:\Program Files\FreeCAD 0.19\bin\FreeCADCmd.exe
   ```

3. Or pass `--freecad "C:\...\FreeCADCmd.exe"`.
4. Remember STEP requires `--step` (option 3).

If FreeCAD is found but exits without results, the warning includes the tail of
its output.  Typical causes: a corrupted STL input, an unsupported FreeCAD
build, or a timeout on an extremely large mesh.

## STEP contains a surface instead of a solid

A solid was requested but FreeCAD reported `open_shell` or
`shell_invalid_solid`.

- The mesh is not watertight.  Use `--weld-tol` if the mesh duplicates nodes at
  element interfaces.
- You used `--solids faces`, which keeps internal faces by design.  Use the
  default `--solids boundary`.
- The geometry is genuinely open or non-manifold.
- For shell extrusion (option 1), make sure the fallback thickness is positive
  and the shell mesh is not already closed (a closed input produces an inner and
  outer shell and a warning).

## "PSHELL thickness is missing or zero; enter a fallback shell thickness"

Option 1 was enabled for a shell whose `PSHELL` has no positive `T` and no
fallback was given.

- Pass `--shell-thickness T` (CLI) or fill in **Ersatzdicke** (GUI), or
- set a valid `T` on the `PSHELL` card.

The fallback is interpreted in the **input unit**.

## Coordinates are wrong by a factor

Almost always a unit mismatch.

- `--unit` is the unit of the **BDF**, `--out-unit` the unit of the **STL**.
- The applied scale is `unit_in / unit_out`; it is printed in the summary and in
  the manifest (`scale`).
- STEP is always millimetres; do not expect the STEP numbers to match a
  non-mm STL directly.

## "coordinate system N not defined" or nodes keep raw coordinates

- `CORD1R/C/S` (systems defined by grid points) are not supported.  Use
  `CORD2*`.
- The `CP` field of a `GRID` must reference a defined `CORD2*`.
- Nodes referencing an undefined system keep their raw coordinates and are
  counted as `nodes_untransformed`.

## Quads look wrong

- Try `--quad-split fixed` if the default shortest-diagonal split produces
  unexpected triangulation.
- Strongly non-planar quads are triangulated anyway; a warning is not emitted
  unless triangles are degenerate.

## Higher-order elements lose curvature

`CTRIA6`, `CQUAD8`, `CQUAD9`, 10-node tets and 20-node hexes are linearised
using their corner nodes.  Midside nodes are ignored and the event is counted as
`midside_nodes_ignored`.  This is expected for STL output.

## "further warnings suppressed after 200 entries"

Warnings are capped to keep logs readable.  The manifest still records the
counts.  Fix the root cause (often units, includes or coordinate systems) rather
than raising the cap.

## The GUI does not start

- Tkinter is missing.  On Linux install `python3-tk`; on Windows/macOS reinstall
  Python with Tcl/Tk enabled.
- Headless server: the GUI and viewer need a display.  Use the CLI/library API
  instead; `Scene` and `Camera` remain importable.

## The 3D viewer is slow

Very large meshes are decimated while dragging and rendered fully on release.
Use `--wireframe`, hide PIDs in the sidebar, or inspect the STL in a dedicated
viewer.

## Antivirus flags the EXE

Use the Onedir ZIP from the releases page rather than a one-file executable.
One-file PyInstaller builds are commonly flagged by heuristics.  Building from
source with `build_exe.ps1` is also an option.

## `pip install -e .` fails

- Ensure Python 3.9+ (`python --version`).
- On Windows, a missing compiler is not an issue: the package has no compiled
  extensions.
- If setuptools is old, upgrade it: `python -m pip install -U setuptools`.
