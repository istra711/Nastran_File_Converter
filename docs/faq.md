# Frequently asked questions

## General

### What exactly does the converter produce?

Binary or ASCII **STL** files (one per PID plus a combined file), a **JSON
manifest**, and optionally faceted **STEP** files.  Shell extrusion and
watertight volume detection determine whether STEP gets a real solid or a
surface.

### Which Python versions are supported?

Python **3.9 or newer**.  It is developed and tested on CPython 3.11.5.

### Are there any third-party dependencies?

No.  STL, the GUI and the viewer use only the standard library.  STEP export
uses an **external** FreeCAD installation, not a Python package.

### Can I use it commercially?

The repository currently ships **without a license file**, which by default means
"all rights reserved".  Add a license if you want to grant others usage rights;
choose one appropriate to your intent.

## Usage

### How do I convert a whole folder?

```bat
for %f in (parts\*.bdf) do python -m nastran2stl "%f" -o out --weld-tol 1e-6
```

Or loop in PowerShell / your build system.  Each file is converted
independently.

### How do I name the objects?

Nastran property cards have no name field.  Provide a JSON map:

```json
{ "100": "enclosure", "500": "block" }
```

```bat
python -m nastran2stl model.bdf -o out --names names.json
```

### Why is one STL file produced per PID?

Because PIDs usually correspond to regions/parts and materials in an EM or CAD
model.  The combined STL is also written unless you pass `--no-combined`.

### How do I merge duplicated nodes on solid interfaces?

Use `--weld-tol` with a small tolerance in source units:

```bat
python -m nastran2stl model.bdf -o out --weld-tol 1e-6 --solid-elements --step
```

### The model is in inches.  What do I do?

```bat
python -m nastran2stl model.bdf -o out --unit in --out-unit mm
```

## Solids and STEP

### What is the difference between option 1 and option 2?

- **Option 1** (`--shell-solid`) gives shells a thickness and produces a closed
  thin **solid mesh**; it changes the STL geometry.
- **Option 2** (`--solid-elements`) checks whether a volume-element boundary is
  watertight and marks it as a solid **for STEP**; it does not change the STL.

They are independent and can be combined.

### Do I need FreeCAD for shells to become solids?

No.  Option 1 alone already produces a closed STL.  FreeCAD is only needed to
**write STEP** (option 3).

### Why is my STEP file a surface, not a solid?

The mesh is not watertight, or `--solids faces` kept internal faces.  Use
`--solids boundary` (default) and `--weld-tol` when nodes are duplicated.  See
[troubleshooting.md](troubleshooting.md#step-contains-a-surface-instead-of-a-solid).

### Is the STEP geometry smooth?

No.  It is a **faceted B-rep** of triangles.  This keeps the conversion exact
and fast; smooth NURBS surfaces would require surface fitting, which is out of
scope.

### Where does it look for FreeCAD?

`FREECAD_CMD`, then `PATH`, then `%ProgramFiles%\FreeCAD*\bin` (and the
`Program Files (x86)` equivalent), then Linux/macOS standard folders.  Override
with `--freecad` or `freecad_cmd=`.

### Is FreeCAD bundled with the EXE?

No.  The EXE and ZIP contain only the converter.  STEP uses whatever FreeCAD is
installed on the machine.

## Library

### Can I get triangles without writing files?

Yes:

```python
from nastran2stl import read_bdf

for part in read_bdf("model.bdf").parts(scale=25.4):
    for tri in part.triangles:
        ...  # flat 9-tuple
```

### Can I embed it in another application?

Yes.  It is dependency-free and layered.  See
[library-api.md](library-api.md) and
[`NASTRAN_IMPORT_ASSESSMENT_EN.md`](../NASTRAN_IMPORT_ASSESSMENT_EN.md).

## Troubleshooting

### It says "no supported shell/solid geometry".  Why?

The file has no recognised geometry, or the geometry is in an `INCLUDE` that
could not be found, or all elements reference missing grids.  Check the
manifest statistics.

### Coordinates are off by 25.4 / 1000.

You mixed up `--unit` and `--out-unit`.  `--unit` describes the BDF, `--out-unit`
the STL.  STEP is always millimetres.

### The EXE is flagged by antivirus.

Use the Onedir ZIP instead of a one-file build.  One-file executables are
frequently quarantined heuristically.

### More help

See [troubleshooting.md](troubleshooting.md) and
[limitations.md](limitations.md).
