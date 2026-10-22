# Nastran mesh import — feasibility and effort assessment

*Status: assessment only, no code changes. Written 2026-10-22; code references
verified against `FreeCAD_OpenEMS_GUI`.*

## Short answer

Importing objects from a Nastran mesh file is feasible and fits the existing
import architecture well, but the effort depends heavily on what the file
contains:

| Scope | Effort (1 developer familiar with the code base) |
|---|---|
| **A) Surface mesh** (`CTRIA3`/`CQUAD4`), one object per property ID, unit dialog, material assignment | **4–5 working days** (parser alone 2–3) |
| **B) As A, plus shells to closed volumes** (sheet thickness, offset, mesh healing) | **+1–3 days** if PEC sheets can use the existing `conducting_sheet` material (½-day spike first); **+2–4 days** if real extrusion/healing is required (≈ 1–1.5 weeks total) |
| **C) Volume mesh** (`CTETRA`/`CHEXA`) used physically | **+1–2 weeks**, benefit questionable |
| **D) Full format support** (`MAT8`/`MAT9`/`PCOMP`, `CORD2R`, `RBE2/3`, `INCLUDE`, `OP2`, performance) | **3–6 weeks** |

## Why it fits the existing code

The import pipeline already does exactly what a Nastran surface mesh needs:

- `app/ui/main_window.py` → `_on_import()` and `_import_geometry_path()` read a
  file, write one triangle array (`.npy`) per object and create a
  `GeometryFile` entry in the project.
- `app/csxcad_builder/triangle_mesh.py` → `add_triangle_mesh()` turns those
  triangles into either an **axis-aligned box** (`CSPrimBox`, exact metal edges)
  or an **STL polyhedron** (`PolyhedronReader`). This is the same path used
  today for STEP/STL/OBJ. The box path only triggers for **closed** axis-aligned
  solids — it verifies the enclosed volume — so a single flat shell does not
  become a box.
- The Geometry tab assigns a material and role per imported object
  (`assignments`), and the Mesh Viewer shows the objects, materials, ports and
  the domain.
- The material system already knows zero-thickness PEC surfaces
  (`conducting_sheet` → `csx.AddConductingSheet`, see `app/models/project.py`
  and `app/csxcad_builder/builder.py`), so single-layer shells do not
  necessarily have to be extruded. Whether `AddConductingSheet` works on a
  `PolyhedronReader` primitive must be verified first (see stage B).

So a Nastran import only has to produce **BDF → triangles per PID** and feed
them into that path. No solver or meshing code is required.

Where the change would plug in:

| Layer | File | Change |
|---|---|---|
| Parser | new `app/freecad_io/nastran.py` | read BDF cards, return triangles + PIDs + units |
| Import dispatch | `app/ui/main_window.py` (`_on_import`, `_import_geometry_path`) | accept `*.bdf *.nas` (`*.dat` only if explicitly wanted — very generic extension), call the parser, write `.npy` per PID (the builder writes the STL on demand) |
| Options | new import dialog (drawing unit incl. `in`/`cm`, merge tolerance, PID filter, shell handling) | user decisions before the objects are created; show a bounding-box preview |
| Materials | Geometry tab / `assignments` | map PID/`PSHELL`/`MAT1` to a project material, default PEC for metal; `conducting_sheet` for single-layer PEC shells (to verify) |
| Builder | `app/csxcad_builder/triangle_mesh.py` | unchanged (triangles in, box or polyhedron out) |

## What a Nastran file contains — and what is missing

Contained: `BEGIN BULK`/`ENDDATA`, `GRID` (including the `CP`/`CD`
coordinate-system fields), `CTRIA3`/`CQUAD4` (shells, quads possibly
non-planar), `CTETRA`/`CHEXA` (solids), `PSHELL`/`PSOLID`/`PCOMP`, `MAT1`,
coordinate systems, `INCLUDE` (possibly nested), `$` comments, three field
formats (8-character small field, 16-character "large field" with `*`
continuation, free field with commas or tabs) and continuation lines.

Missing or not directly usable:

- **Units** are not stored in the file (mm, m, cm and inch are all common) — the
  user must choose. The app scales geometry through `project.mesh.drawing_unit`
  (`unit_to_meters()`), but the UI only offers `mm`, `um` and `m`, while
  `GeometryFile.unit` is hard-coded to `"mm"` and never evaluated. Inch and cm
  models therefore need either `in`/`cm` in the drawing-unit list or a scaling
  step during import. The dialog should show the resulting bounding box as a
  sanity check.
- **Electromagnetic material data is absent**: `MAT1` provides Young's modulus,
  Poisson ratio and density. openEMS needs `eps_r`, `tan_d` and `kappa`.
  Consequently: `PSHELL`/`MAT1` → PEC (sheet metal) or map to an existing
  project material. The project's `conducting_sheet` material is the natural
  target for single-layer metal shells.
- **Closed volumes**: `PolyhedronReader` is the only path openEMS really
  simulates; an in-memory `AddPolyhedron` is reported as an "Unused primitive"
  and ignored (see `app/csxcad_builder/triangle_mesh.py`). Dielectric sheets
  need a closed volume, i.e. extrusion or a real thickness. For PEC shells a
  `conducting_sheet` may suffice — verify this with a small test before
  planning stage B.
- **Flat shells are not boxes**: the automatic box conversion verifies the
  enclosed volume, so only *closed* axis-aligned solids become a `CSPrimBox`; a
  single flat plate becomes an open STL (or, better, a `conducting_sheet`).
- **Coordinate systems**: `GRID` entries with `CP`/`CD` ≠ 0 (or references to
  `CORD2R`) would silently produce wrong geometry. At minimum the parser must
  warn and skip or transform them.

## The stages in detail

### A) Surface import (MVP, 4–5 days)

- Parser: `BEGIN BULK`/`ENDDATA`, `GRID` (warn on `CP`/`CD` ≠ 0), `CTRIA3`,
  `CQUAD4` (→ two triangles; non-planar quads are an accepted approximation),
  `PSHELL`, `MAT1`, `INCLUDE` (also nested, relative to the including file),
  `$` comments, small/large/free field (comma or tab), `*` continuation lines —
  roughly 400–600 lines, **2–3 days** including fixtures. Elements without a
  defined PID go into a fallback bucket.
- GUI: add `*.bdf *.nas` to the import dialog, an options dialog (drawing unit
  aligned with `project.mesh.drawing_unit` incl. `in`/`cm`, merge tolerance,
  property filter, "shells as PEC/conducting_sheet") with a bounding-box
  preview, and a log summary (nodes, elements, skipped cards, free edges,
  bounding box). Group objects by PID, named from `PSHELL`; sanitise names for
  files and ensure they are unique across imports (the same file stem from
  different folders currently collides in `work/imported/<stem>`).
- Project: one object per PID with material assignment, exactly like imported
  CAD objects (1 day).
- Result: sheet metal parts and enclosures become simulation-ready metal or
  dielectric objects. **Closed** axis-aligned solids automatically become exact
  boxes; flat shells need a thickness/`conducting_sheet` decision.

### B) Shells to volumes (+1–3 days, or +2–4 days without the sheet shortcut)

- **First a half-day spike**: import one flat PEC shell as a
  `conducting_sheet` + `PolyhedronReader` and check whether openEMS actually
  simulates it. If yes, most sheet-metal models need no extrusion at all and
  this stage shrinks to the dielectric/multi-layer cases.
- Otherwise: read the thickness `T` from `PSHELL`, offset the surface by ±T/2,
  close the rim → a closed polyhedron.
- Mesh healing: merge duplicate nodes, detect free edges / T-junctions, drop
  degenerate triangles, orient normals.
- This is the genuinely tricky part; offsetting can fail on strongly curved or
  badly connected meshes.

### C) Volume mesh (+1–2 weeks)

openEMS is an FDTD solver on a Cartesian grid — tetrahedra/hexahedra cannot be
mapped 1:1. Three options:

1. **Voxelise onto the FDTD grid** (material per cell) → thousands of boxes,
   staircase edges, slow CSX; usually worse than the existing boxes.
2. **Extract the outer skin per material region** → effectively stage A; almost
   always the sensible choice.
3. **One polyhedron per element** → correct, but practically unusable at 10⁵
   elements.

Recommendation: implement "volume import" as **region extraction**, not as
element-by-element transfer.

### D) Full support (weeks)

`MAT8`/`MAT9`/`PCOMP` (layups), `CORD2R`/`CP` (coordinate systems), `RBE2`/`RBE3`,
`SPC`, `SET`, subcases, `OP2` (binary, separate format), and 1 M+ elements with
a progress bar.

## Typical pitfalls that drive the effort

1. **Units** — wrong guess means a factor of 1000 in the model; a dialog with a
   bounding-box preview is mandatory.
2. **Material mapping** — mechanical cards carry no EM values; a default
   proposal is needed (PEC for metal PIDs, otherwise project materials).
3. **Mesh quality** — crash/structural meshes are often not watertight and have
   duplicate nodes and free edges.
4. **Object flood** — a BDF easily contains hundreds of PIDs (screws, gaskets);
   without filters/multi-select the project becomes unmanageable.
5. **Priorities** — openEMS needs an overlap hierarchy that Nastran does not
   provide.
6. **Performance** — large meshes slow down STL creation and openEMS meshing.
   `write_binary_stl()` currently packs one triangle at a time in a Python loop
   (`app/csxcad_builder/triangle_mesh.py`); vectorise it before handling 10⁵+
   triangles, and plan for progress reporting and cancellation.
7. **Naming and paths** — PID/`PSHELL` names become file names and primitive/
   assignment keys; sanitise them and keep them unique, both within one file and
   across re-imports.

## Proposed MVP scope

- ASCII BDF only: `BEGIN BULK`/`ENDDATA`, `GRID`, `CTRIA3`, `CQUAD4`,
  `PSHELL`, `MAT1`, `INCLUDE`, `$` comments, small/large/free field, `*`
  continuation lines. Warn on `GRID` `CP`/`CD` ≠ 0.
- Unit selection aligned with `project.mesh.drawing_unit` (default: the project
  unit; add `in`/`cm` or scale on import) with bounding-box preview.
- One object per PID, named `<PID> <PSHELL name>` (sanitised, unique), triangles
  stored as `.npy` in the existing `work/imported/<stem>` folder; the builder
  writes the STL on demand.
- Closed axis-aligned solids → exact box; everything else → STL polyhedron;
  flat PEC shells → `conducting_sheet` if the spike confirms it.
- Material/role assignment through the existing Geometry tab; default PEC for
  sheet-metal properties.
- Log: nodes, elements, skipped cards, free-edge count, bounding box.

Out of scope for the MVP: volume elements, layups, coordinate systems (beyond
the warning), binary OP2, automatic extrusion of curved shells.

## Test plan (for the implementation)

- Fixtures: tiny hand-written BDF files covering short field, large field, free
  field, `*` continuation lines, `INCLUDE` (also nested), quads (→ 2 triangles),
  `BEGIN BULK`/`ENDDATA`, comments and elements with an undefined PID.
- Unit scaling: same model in mm/m/cm/inch must produce identical geometry in
  metres.
- PID grouping, unique/sanitised object names (two files with the same stem)
  and material defaulting.
- Degenerate/duplicate nodes, an open shell and `CP` ≠ 0 (must warn, not crash).
- Box detection: a closed box becomes a `CSPrimBox`, a single flat plate does
  **not**.
- End-to-end: import → mesh → Mesh Viewer shows the object with the expected
  bounding box; build CSX without "Unused primitive" warnings.
- If the sheet spike succeeds: PEC shell as `conducting_sheet`, verify it is
  actually simulated (not silently ignored).

## Workaround available today (no development)

Because the GUI already imports STL/OBJ, a converter is enough:

- **meshio** (pure Python, `pip install meshio`): `meshio convert model.bdf model.stl`
  (depending on the version) or a short script. Works for **surface meshes
  only**; `CTETRA`/`CHEXA` cannot be written to STL.
- **pyNastran** (comprehensive, also reads `OP2`): extract the shell elements
  and write an STL with a short script (no one-liner).
- **Gmsh**: can open BDF surface meshes and export STL. It **cannot** derive a
  STEP (BREP) file from a shell mesh, so the STEP route is not available for
  Nastran input.

Then use **Import Geometry…** as usual. This costs no development time, but the
user has to do the intermediate step manually and loses the PID/material
mapping (it has to be recreated in the Geometry tab).
