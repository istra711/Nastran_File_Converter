# Formats and parsing

This page describes what the reader understands, how it tokenises the file, and
how shells and solids become triangles.  The implementation lives in
[`nastran2stl/bdf.py`](../nastran2stl/bdf.py).

## Input files

| Extension | Treated as |
| --- | --- |
| `.bdf` | Nastran bulk data |
| `.nas` | Nastran bulk data |
| `.dat` | Nastran bulk data |

Only **ASCII** bulk-data files are read.  Binary result files (`OP2`) and
punch/`F06` output are different formats and are **not** supported.  The file is
opened as UTF-8 with a BOM fallback and `errors="replace"`, so stray non-ASCII
bytes do not abort the read.

## Field formats

Nastran bulk data can be written in three field layouts.  All three are
detected per card, and files may mix them freely:

### Small field (8 characters)

The card name occupies columns 1–8; eight data fields follow, each eight
characters wide.

```
GRID           1       0.      0.      0.      0
```

### Large field (16 characters)

A card name ending in `*` marks the large field.  Data fields are sixteen
characters wide.  Continuation lines also use 16-character fields.

```
GRID*    1               0.              0.
*        0.              0.
```

### Free field

Data fields separated by commas (and, as a non-standard convenience, tabs).
A trailing comma is treated as a separator, not as an empty field.

```
GRID,1,0.0,0.0,0.0
```

> Free-field data separated only by **spaces** (no commas or tabs) is not
> detected as free field.  Use commas or tabs, which is what Nastran itself
> writes.

### Continuation lines

A line is treated as a continuation of the previous card when its first field is
blank, starts with `+`, or is a short non-card token.  Continuation IDs inside
an alphabetic token (for example `+A`) are also handled.  A token ending in `*`
always starts a new large-field card.

## File structure

- `$` comments and blank lines are skipped.
- `BEGIN BULK` is skipped; `ENDDATA` ends the file.
- `INCLUDE` directives are expanded recursively:
  - relative paths are resolved against the including file,
  - matching is attempted case-insensitively on case-sensitive file systems,
  - nesting is limited to 16 levels,
  - cycles and repeated files are detected and reported once,
  - missing includes become warnings and are counted (`includes_missing`).

## Supported cards

### Geometry

| Card | Nodes (corners) | Handling |
| --- | --- | --- |
| `GRID` | — | Node coordinates; `CP` selects a coordinate system. |
| `CTRIA3` | 3 | Triangle. |
| `CTRIA6` | 3 | Triangle, midside nodes ignored (linearised). |
| `CQUAD4` | 4 | Split into two triangles. |
| `CQUAD8` | 4 | Quad, midside nodes ignored. |
| `CQUAD9` | 4 | Quad, midside nodes ignored. |
| `CTETRA` | 4 | Volume element; faces triangulated. |
| `CHEXA` | 8 | Volume element; faces triangulated. |
| `CPENTA` | 6 | Volume element; faces triangulated. |
| `CPYRAM` | 5 | Volume element; faces triangulated. |
| 10-node tets / 20-node hexes | corner nodes | Linearised; midside nodes ignored. |

### Properties

Property cards are stored so the shell thickness can be recovered:

```
PSHELL, PSOLID, PCOMP, PCOMPG, PBAR, PBARL, PBEAM, PBEAML,
PROD, PSHEAR, PSPRING, PDAMP, PMASS, PLPLANE, PPLANE, PGAP,
PBUSH, PBUSH1D, PELAS, PVISC
```

Only `PSHELL` field 3 (`T`) is interpreted geometrically; it is the shell
thickness used by option 1 (shell extrusion).  A `PSHELL` with `T` blank or
zero falls back to the explicit fallback thickness.

### Coordinate systems

| Card | Kind | Supported |
| --- | --- | --- |
| `CORD2R` | Rectangular | Yes |
| `CORD2C` | Cylindrical | Yes |
| `CORD2S` | Spherical | Yes |
| `CORD1R/C/S` | Defined by grid points | No (reported once as unsupported) |

A `GRID` `CP` field selects the coordinate system of the node.  `CORD2` cards
may reference a parent (`RID`), forming a chain; the reader resolves the chain
with cycle detection.  `CD` (the output coordinate system of a grid) is
**ignored**, because STL carries no coordinate-system information.

### Intentionally ignored cards

Cards that never contribute geometry are counted as ignored rather than
reported as unsupported.  This includes `MAT1/2/8/9/10`, tables, loads (`FORCE`,
`MOMENT`, `PLOAD4`, …), `SPC*`, `RBE1/2/3`, `CBAR`/`CBEAM`/`CROD`/`CONROD`,
`CONM2`, `SET`, `PARAM`, `EIGRL`/`EIGB`, `SUBCASE`, `TITLE`, `MPC`,
`TEMPERATURE`, `DISP`, `DLOAD`, `TSTEP`, `FREQ`, `NLPCI`, `NLPARM`, and control
cards.

### Unsupported cards

Anything else is counted in `model.unsupported` and listed in the manifest as
`unsupported_cards`, for example:

```json
"unsupported_cards": { "CBAR": 3, "RBE2": 1 }
```

## Number parsing

Nastran permits compact numbers and Fortran-style exponents.  The reader:

- converts `D`/`d` exponents to `E`,
- accepts implicit exponents such as `1.2-3` (interpreted as `1.2e-3`),
- rejects non-finite values (treated as missing),
- returns a default when a field is blank or invalid.

## Triangulation

### Shells

- Triangles are emitted directly.
- Quads are split into two triangles along:
  - the **shortest diagonal** (default, `--quad-split shortest`), or
  - the fixed 1–3 diagonal (`--quad-split fixed`).

### Volume elements

Two modes are available (`--solids`):

- **`boundary` (default)** — the outer skin per PID.  Each element face is
  oriented outwards (away from the element centroid) using a Newell normal,
  then faces are grouped by their node set.  A face that occurs exactly once is
  a boundary face; faces shared by two or more elements are internal and are
  removed.  This usually yields a closed shell that can become a STEP solid.
- **`faces`** — every element face is emitted, including internal ones.  Useful
  for debugging or for tools that want the raw face soup, but the result is
  generally not watertight.
- **`skip`** — volume elements are ignored; only shells are exported.

Because faces are grouped **per PID**, an interface between two different PIDs
keeps its faces, so every PID remains a closed region on its own.

### Welding duplicated nodes

Some meshes store identical coordinates under different node IDs at element
interfaces.  In that case internal faces are not recognised as shared and the
boundary stays open.  `--weld-tol TOL` rounds coordinates to `TOL` (in source
units) before grouping faces, which removes those internal faces.  With
`TOL = 0` only genuinely shared node IDs are merged.

### Degeneracy

Zero-area or collinear triangles are discarded.  The test is scale-independent,
so legitimately tiny geometry (metres or nanometres) is not rejected:

```
area² ≤ 1e-24 · max_edge² · max_edge²  →  discarded and counted
```

The count appears in the manifest as `triangles_degenerate`.

## Units

Coordinates are scaled by `unit_in / unit_out`.  The following names are
accepted (case-insensitively):

| Name(s) | Metres per unit |
| --- | --- |
| `m`, `meter`, `metre` | 1 |
| `cm` | 1e-2 |
| `mm`, `millimeter`, `millimetre` | 1e-3 |
| `um`, `µm`, `micron` | 1e-6 |
| `nm` | 1e-9 |
| `in`, `inch` | 0.0254 |
| `ft` | 0.3048 |
| `mil` | 2.54e-5 |

An explicit `--scale` overrides the unit conversion entirely.  STEP export
always writes millimetres, so the exporter applies an additional factor when
`--out-unit` is not `mm` (see [solids-and-step.md](solids-and-step.md#units)).

## Statistics and warnings

`read_bdf()` returns a `BdfModel` carrying a `stats` counter.  Useful keys:

| Key | Meaning |
| --- | --- |
| `grid_cards` | `GRID` cards seen |
| `grids_invalid` | Grids with bad coordinates or IDs |
| `grids_duplicate` | Duplicate node IDs (last definition wins) |
| `elements_read` | Geometry elements stored |
| `elements_invalid` | Elements with bad IDs or too few nodes |
| `properties_read` | Property cards stored |
| `coordsystems_read` | `CORD2*` systems stored |
| `nodes_untransformed` | Grids using an undefined coordinate system |
| `midside_nodes_ignored` | Higher-order elements linearised |
| `includes`, `includes_missing` | `INCLUDE` handling |
| `cards_ignored` | Non-geometric cards skipped |
| `nodes_read` | Final node count |
| `elements_missing_nodes` | Elements referencing undefined grids |
| `elements_incomplete` | Elements with too few nodes |
| `triangles_degenerate` | Discarded degenerate triangles |
| `solid_faces_internal` | Internal faces removed by boundary extraction |

`convert()` adds `objects_written`, `triangles_written`, `shell_extrusions`,
`solids_written` and `step_files_written`.

Warnings are de-duplicated by key and capped (200 messages, then a single
"further warnings suppressed" entry).  They are returned in `model.warnings`
and written to the manifest.
