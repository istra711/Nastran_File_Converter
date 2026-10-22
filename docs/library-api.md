# Library API

The package is designed to be embedded.  Everything public is re-exported from
the top-level `nastran2stl` package:

```python
import nastran2stl
print(nastran2stl.__version__)
```

The viewer helpers are imported lazily, so `import nastran2stl` never imports
Tkinter.  Nothing here needs a third-party package.

## Reading a BDF

### `read_bdf(path) -> BdfModel`

Parse a BDF/NAS/DAT file, including nested `INCLUDE` files.

```python
from nastran2stl import read_bdf

model = read_bdf("model.bdf")
print(model.source)         # pathlib.Path
print(len(model.nodes))     # node count
print(len(model.elements))  # geometry element count
print(model.warnings)       # list[str]
print(dict(model.stats))    # Counter of parse statistics
print(model.unsupported.most_common())
```

Raises `NastranError` when the file cannot be read.

### `BdfModel`

| Attribute | Type | Meaning |
| --- | --- | --- |
| `source` | `Path` | Input path |
| `nodes` | `dict[int, (x, y, z)]` | Grid coordinates after coordinate-system transformation |
| `elements` | `list[Element]` | Geometry elements |
| `properties` | `dict[int, Property]` | Property cards by PID |
| `coordsystems` | `dict[int, CoordSystem]` | `CORD2*` systems by CID |
| `warnings` | `list[str]` | De-duplicated warnings |
| `stats` | `Counter` | Parse statistics |
| `unsupported` | `Counter` | Unsupported card counts |

### `BdfModel.parts(...) -> list[MeshPart]`

Turn the model into triangles grouped by PID.

```python
def parts(
    self,
    *,
    scale: float = 1.0,
    quad_split: str = "shortest",   # or "fixed"
    solids: str = "boundary",       # or "faces" / "skip"
    weld_tol: float = 0.0,
    names: dict[int, str] | None = None,
) -> list[MeshPart]: ...
```

```python
for part in model.parts(scale=25.4, solids="boundary"):
    print(part.pid, part.name, part.kind)
    print("  elements:", part.element_count, "shells:", part.shell_count,
          "solids:", part.solid_count)
    print("  triangles:", len(part.triangles))
    print("  bounds:", part.bounds())
```

### `Element`

| Field | Type | Meaning |
| --- | --- | --- |
| `eid` | `int` | Element ID |
| `pid` | `int` | Property ID |
| `kind` | `str` | Card name, e.g. `CTRIA3` |
| `nodes` | `tuple[int, ...]` | Corner node IDs |

### `Property`

| Field | Type | Meaning |
| --- | --- | --- |
| `pid` | `int` | Property ID |
| `kind` | `str` | Card name, e.g. `PSHELL` |
| `fields` | `tuple[str, ...]` | Raw tokens |
| `thickness` | `float \| None` | `PSHELL` `T` (field 3), else `None` |

### `MeshPart`

| Field | Type | Meaning |
| --- | --- | --- |
| `pid` | `int` | Property ID |
| `name` | `str` | Display/file name |
| `kind` | `str` | Property card name or `UNKNOWN` |
| `triangles` | `list[tuple[float, ...]]` | Flat 9-tuples `(ax, ay, az, bx, by, bz, cx, cy, cz)` |
| `element_count` | `int` | Elements contributing triangles |
| `shell_count`, `solid_count` | `int` | Element counts by category |
| `is_shell`, `is_solid` | `bool` | Category helpers |
| `bounds()` | `(low, high) \| None` | Axis-aligned bounding box |

### `triangle_bounds(triangles) -> (low, high) | None`

Compute an axis-aligned bounding box from a triangle sequence.

## Converting to files

### `convert(...) -> ConversionResult`

```python
def convert(
    source,
    out_dir=None,
    *,
    unit_in="mm",
    unit_out="mm",
    scale=None,
    split=True,
    combined=True,
    ascii_stl=False,
    solids="boundary",
    quad_split="shortest",
    weld_tol=0.0,
    names=None,
    manifest=True,
    shell_solid=False,
    shell_thickness=None,
    solid_elements=False,
    step=False,
    freecad_cmd=None,
) -> ConversionResult: ...
```

```python
from nastran2stl import convert

result = convert("model.bdf", "out")
print(result.triangle_count, result.bounds, result.scale)
for obj in result.objects:
    print(obj.pid, obj.name, obj.stl_path)

result = convert(
    "model.bdf",
    "out",
    shell_solid=True,       # option 1: extrude shells by PSHELL T
    shell_thickness=1.0,    # fallback in input units
    solid_elements=True,    # option 2: watertight volume skins become solids
    step=True,              # option 3: write faceted STEP through FreeCAD
    freecad_cmd=r"C:\Program Files\FreeCAD 0.19\bin\FreeCADCmd.exe",
)
for obj in result.objects:
    print(obj.pid, "solid:", obj.solid, "thickness:", obj.thickness)
    print("  STL:", obj.stl_path, " STEP:", obj.step_path)
print("combined STEP:", result.combined_step_path)
print("STEP warnings:", result.step_warnings)
```

Parameters mirror the CLI.  See [usage-cli.md](usage-cli.md) for the meaning of
each option.  `convert` raises:

- `ValueError` for invalid parameters (bad unit, non-positive scale, both
  `split` and `combined` disabled, …),
- `NoGeometryError` when the file has no usable geometry,
- `NastranError` for a missing `PSHELL` thickness or a failed extrusion.

A missing FreeCAD does **not** raise; the problem is reported in
`result.step_warnings` and the STL files remain valid.

### `ConversionResult`

| Field | Type | Meaning |
| --- | --- | --- |
| `source` | `Path` | Input file |
| `model` | `BdfModel` | Parsed model |
| `objects` | `list[ConvertedObject]` | One entry per PID |
| `combined_path` | `Path \| None` | Combined STL |
| `manifest_path` | `Path \| None` | JSON manifest |
| `combined_step_path` | `Path \| None` | Combined STEP |
| `warnings` | `list[str]` | All warnings (solid + STEP, prefixed) |
| `step_warnings` | `list[str]` | STEP-only warnings |
| `stats` | `dict` | Extended statistics |
| `bounds` | `(low, high) \| None` | Overall bounding box |
| `scale` | `float` | Applied unit scale |
| `unit_in`, `unit_out` | `str` | Units |
| `triangle_count` | `int` | Property: total triangles |

### `ConvertedObject`

| Field | Type | Meaning |
| --- | --- | --- |
| `pid` | `int` | Property ID |
| `name` | `str` | Display name |
| `kind` | `str` | Property card name |
| `triangles` | `list` | Triangles actually written (after extrusion) |
| `element_count` | `int` | Source element count |
| `stl_path` | `Path \| None` | Per-PID STL, if written |
| `step_path` | `Path \| None` | Per-PID STEP, if written |
| `solid` | `bool` | Marked as solid for STEP |
| `thickness` | `float \| None` | Applied shell thickness (output units) |
| `bounds` | `(low, high) \| None` | Bounding box |

## Helper functions

### `unit_factor(name) -> float`

Return metres per unit; raises `NastranError` for unknown names.

```python
from nastran2stl import unit_factor
unit_factor("in")   # 0.0254
```

### `sanitize_name(text, *, fallback="mesh", limit=80) -> str`

Make a string safe for file names on Windows and POSIX.  Windows reserved names
are escaped.

### `load_names(path) -> dict[int, str]`

Load a PID → name JSON map (values may be strings or objects with a `name`
field).

## STL writers

```python
from nastran2stl import write_stl, write_binary_stl, write_ascii_stl

write_stl("out/mesh.stl", triangles, name="mesh", ascii=False)
write_binary_stl("out/mesh.stl", triangles, name="mesh")
write_ascii_stl("out/mesh.stl", triangles, name="mesh")
```

`triangles` may be flat 9-tuples or three `(x, y, z)` points per triangle.  All
three functions return the written `Path` and create parent folders.

## Solid helpers

```python
from nastran2stl import extrude_shell_triangles, is_watertight, SolidError

closed = is_watertight(triangles)
thick = extrude_shell_triangles(triangles, thickness=1.0)
```

See [solids-and-step.md](solids-and-step.md).

## STEP helpers

```python
from nastran2stl import (
    StepItem, StepResult, StepError, find_freecad_cmd, write_step_files,
)

cmd = find_freecad_cmd()          # Path | None

items = [
    StepItem(
        stl_path=Path("out/model_pid100.stl"),
        step_path=Path("out/model_pid100.step"),
        solid=True,
        label="PID 100",
    )
]
result: StepResult = write_step_files(
    items,
    combined_path=Path("out/model_all.step"),
    freecad_cmd=cmd,
    scale=1.0,
)
print(result.paths, result.combined_path, result.warnings, result.freecad_cmd)
```

`StepItem.solid` requests a solid; `scale` is applied before export.  Raises
`StepError` when FreeCAD is missing, cannot be executed, or writes no result.

## Viewer helpers

Imported lazily from `nastran2stl`:

```python
from nastran2stl import read_bdf, show_model, show_scene, show_file, ask_for_bdf

model = read_bdf("model.bdf")
show_model(model)                       # blocks until the window is closed
show_model(model, wireframe=True)

result = convert("model.bdf", "out")
show_model(result.model, result.objects)

scene = ...                             # a prepared Scene
show_scene(scene)

path = ask_for_bdf()                    # None if the user cancels
if path is not None:
    show_file(path)
```

`show_model(..., block=False)` returns the `ViewerWindow` so an existing Tk
application keeps control of the main loop.  `Scene` and `Camera` are headless
and can be used without a display.

## Exceptions

| Exception | Base | Raised by |
| --- | --- | --- |
| `NastranError` | `Exception` | Parsing, unit and conversion errors |
| `NoGeometryError` | `NastranError` | Files without usable geometry |
| `SolidError` | `ValueError` | Invalid thickness or malformed triangles |
| `StepError` | `RuntimeError` | STEP export problems |
| `ViewerError` | `Exception` | The 3D window cannot be opened |

## Embedding example (FreeCAD_OpenEMS_GUI)

The converter is a good fit for an existing import pipeline because it can feed
triangle arrays directly:

```python
import numpy as np
from nastran2stl import read_bdf

model = read_bdf(path)
for part in model.parts(scale=scale, solids="boundary"):
    triangles = np.asarray(part.triangles, dtype=float).reshape(-1, 3, 3)
    np.save(obj_dir / f"{part.name}.npy", triangles)
```

Set `scale` so the STL coordinates match the project's drawing unit.  See
[`NASTRAN_IMPORT_ASSESSMENT_EN.md`](../NASTRAN_IMPORT_ASSESSMENT_EN.md) for the
full integration assessment.
