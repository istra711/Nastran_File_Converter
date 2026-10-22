# Limitations and non-goals

Knowing the boundaries of the tool saves time.  This page lists what
`nastran2stl` deliberately does not do.

## Input formats

- **ASCII BDF/NAS/DAT only.**  Binary `OP2`, `F06`/`PCH` output, HDF5 and
  Nastran archive formats are not read.
- **No free-field blank-delimited data.**  Free field must use commas or tabs.
- **No Nastran solver features.**  Loads, constraints, subcases, materials and
  optimization data are ignored (but counted so you can see them).
- **`CORD1R/C/S` unsupported.**  Only `CORD2*` coordinate systems are applied.
- **`CD` is ignored.**  STL carries no coordinate-system information, so the
  grid output system is not honoured.

## Element support

- **Shells and volume corners only.**  Bars, beams, rods, rigid elements,
  springs, dampers, masses, gaps and bushings are not exported as geometry.
- **Higher-order elements are linearised.**  Midside nodes of `CTRIA6`,
  `CQUAD8`, `CQUAD9`, 10-node tets and 20-node hexes are ignored.
- **No mixed-element topology.**  A `PSHELL` is assumed to describe shells and a
  `PSOLID` volume elements; mixed PIDs are reported and not extruded.
- **No `PCOMP` ply geometry.**  Composite layups are not expanded into plies.

## Geometry

- **No mesh healing or repair.**  Duplicated nodes must be welded explicitly
  with `--weld-tol`; self-intersections, cracks and non-manifold edges are not
  fixed.
- **No surface reconstruction.**  Output is always triangles.
- **No `PSHELL` offset (`Z0`) handling.**  Shell extrusion is symmetric about
  the original surface (mid-plane).
- **No thickness tapering.**  A single `PSHELL` `T` applies to the whole PID.
- **Per-PID skinning only.**  Internal faces are removed within one PID;
  interfaces between different PIDs keep their faces so each PID stays closed.
- **Bounding boxes are axis-aligned** and computed from the emitted triangles
  (after scaling and extrusion).

## Output

- **Binary STL by default.**  ASCII is available but much larger.
- **STEP is faceted.**  It is a B-rep of triangles, not smooth NURBS geometry.
  FreeCAD turns closed meshes into `MANIFOLD_SOLID_BREP` entities; open meshes
  stay surfaces.
- **STEP needs FreeCAD.**  It is never bundled and must be installed separately.
- **STEP is always millimetres.**  Non-mm STL output is rescaled on export.
- **No colours, materials or assembly structure.**  STL has none; STEP keeps
  only geometry (and PID labels internally).

## Solids and STEP options

- **Option 1** gives a closed thin solid, not the original CAD wall.  Offset
  direction and precise outer surface are not reconstructed.
- **Option 2** only changes STEP treatment; it never changes STL geometry.
- **Watertightness is an edge-count test.**  It can be fooled by
  self-intersecting but edge-consistent geometry; `Part.Solid` may then reject
  it (`shell_invalid_solid`).
- **No automatic unit detection.**  The unit must be supplied.

## Performance

- **Pure Python.**  The parser and triangulation are fast for typical models but
  are not optimised for multi-million-element meshes.  Binary STL writing is
  streamed to limit memory use.
- **The viewer is a software renderer.**  It is meant for quick inspection, not
  for large-model visualisation.

## Platform

- **GUI/viewer need Tkinter and a display.**  Headless use is via the CLI and
  the library API (`Scene`/`Camera` remain importable).
- **The prebuilt EXE is Windows x64.**  On other platforms install from source.

## Non-goals

- Replacing a full CAE pre/post-processor or a solver.
- Reading or writing Nastran results.
- Producing parametric or feature-based CAD models.
- Repairing broken meshes.
