# Command line usage

The CLI is the workhorse of the package.  Run it either as a module or through
the installed console script:

```bat
python -m nastran2stl INPUT.bdf [INPUT2.bdf ...] [options]
nastran2stl INPUT.bdf [options]      :: after `pip install -e .`
```

Multiple input files are allowed; each is converted independently.

```bat
python -m nastran2stl part_a.bdf part_b.bdf -o out
```

## Synopsis

```
nastran2stl [-h] [-o DIR] [--unit UNIT] [--out-unit UNIT]
            [--scale SCALE] [--no-split] [--no-combined] [--ascii]
            [--solids {boundary,faces,skip}]
            [--quad-split {shortest,fixed}] [--weld-tol TOL]
            [--names JSON] [--no-manifest] [--shell-solid]
            [--shell-thickness T] [--solid-elements] [--step]
            [--freecad PATH] [--view] [--view-only] [--wireframe] [-q]
            [--version]
            [BDF ...]
```

## Options

### Input and output

| Option | Default | Description |
| --- | --- | --- |
| `BDF ...` | — | One or more `.bdf`/`.nas`/`.dat` files.  May be omitted with `--view`/`--view-only` to pick a file in a dialog. |
| `-o`, `--out DIR` | input folder | Output directory.  Created if it does not exist. |
| `--no-split` | off | Do not write one STL per PID. |
| `--no-combined` | off | Do not write the combined STL. |
| `--ascii` | off | Write ASCII STL instead of binary STL. |
| `--no-manifest` | off | Do not write the JSON manifest. |
| `-q`, `--quiet` | off | Suppress the per-file summary. |

At least one of the per-PID or combined output must stay enabled; using both
`--no-split` and `--no-combined` is an error.

> When `--no-split` is combined with `--step`, the converter creates temporary
> per-PID STL files internally so that FreeCAD can still build one solid per
> PID.  The temporary files are deleted afterwards and are not part of the
> output.

### Units and scale

| Option | Default | Description |
| --- | --- | --- |
| `--unit UNIT` | `mm` | Unit of the Nastran coordinates in the BDF file. |
| `--out-unit UNIT` | `mm` | Unit of the STL coordinates. |
| `--scale FACTOR` | — | Explicit scale factor; overrides `--unit`/`--out-unit`. |

Supported unit names: `m`, `meter`, `metre`, `cm`, `mm`, `millimeter`,
`millimetre`, `um`, `µm`, `micron`, `nm`, `in`, `inch`, `ft`, `mil`.

The applied scale is `unit_in / unit_out`.  Converting inches to millimetres
therefore uses a factor of 25.4, exactly as expected:

```bat
:: source is in inches, output in millimetres
python -m nastran2stl model.bdf -o out --unit in --out-unit mm
```

STEP is always written in millimetres regardless of `--out-unit`.  See
[solids-and-step.md](solids-and-step.md#units).

### Geometry

| Option | Default | Description |
| --- | --- | --- |
| `--solids {boundary,faces,skip}` | `boundary` | How volume elements are handled.  `boundary` extracts the outer skin per PID and removes shared internal faces; `faces` emits every element face; `skip` ignores volume elements entirely. |
| `--quad-split {shortest,fixed}` | `shortest` | Split quadrilaterals along the shortest diagonal, or along the fixed 1–3 diagonal. |
| `--weld-tol TOL` | `0` | Merge coincident solid faces by rounding coordinates to `TOL` (in source units).  `0` merges only genuinely shared node IDs.  Useful when the mesh duplicates nodes on element interfaces. |
| `--names JSON` | — | JSON file mapping PID to a display/file name, e.g. `{"100": "enclosure"}`. |

```bat
:: only shells, ignore volume elements
python -m nastran2stl model.bdf -o out --solids skip

:: every solid element face instead of the outer skin
python -m nastran2stl model.bdf -o out --solids faces

:: merge duplicated nodes on solid interfaces (tolerance in source units)
python -m nastran2stl model.bdf -o out --weld-tol 1e-6

:: readable ASCII STL, no combined file
python -m nastran2stl model.bdf -o out --ascii --no-combined
```

### Solids and STEP

| Option | Default | Description |
| --- | --- | --- |
| `--shell-solid` | off | Extrude shell elements by their `PSHELL` thickness `T` and write closed thin-solid STL meshes. |
| `--shell-thickness T` | — | Fallback thickness **in input units** when `T` is missing or zero.  Required only if some shell has no usable `T`. |
| `--solid-elements` | off | Mark watertight volume-element boundaries as solids for STEP.  Open boundaries stay surfaces. |
| `--step` | off | Also write faceted STEP files through FreeCAD. |
| `--freecad PATH` | auto-detect | Explicit path to `FreeCADCmd.exe` for `--step`. |

```bat
:: extrude shells by PSHELL T (fallback 1.0 for shells without T)
python -m nastran2stl model.bdf -o out --shell-solid --shell-thickness 1.0

:: write faceted STEP files with FreeCAD; treat closed volume skins as solids
python -m nastran2stl model.bdf -o out --solid-elements --step

:: STEP with an explicit FreeCADCmd path
python -m nastran2stl model.bdf -o out --step --freecad "C:\Program Files\FreeCAD 0.19\bin\FreeCADCmd.exe"
```

Options 1 (`--shell-solid`) and 2 (`--solid-elements`) are independent and can
be combined.  `--step` is orthogonal and controls whether STEP files are
written at all.  See [solids-and-step.md](solids-and-step.md) for the full
semantics.

### Viewing

| Option | Description |
| --- | --- |
| `--view` | Convert first, then open the result in the 3D viewer. |
| `--view-only` | Open the viewer without writing any files. |
| `--wireframe` | Start the viewer in wireframe mode. |
| `--version` | Print the version and exit. |
| `-h`, `--help` | Print the full help text and exit. |

```bat
:: inspect the mesh without writing STL files
python -m nastran2stl model.bdf --view-only

:: convert and then open the result in the 3D viewer
python -m nastran2stl model.bdf -o out --view

:: choose a file in a dialog and only view it
python -m nastran2stl --view-only
```

`--view` and `--view-only` are mutually exclusive.

## Output files

For an input `model.bdf` the converter writes into the output folder:

| File | When | Contents |
| --- | --- | --- |
| `<stem>_pid<PID>.stl` | `--split` (default) | Triangles for one property ID. |
| `<stem>_pid<PID>_<name>.stl` | `--split` and a name is known | Same, with the name from `--names`. |
| `<stem>_all.stl` | `--combined` (default) | All objects merged. |
| `<stem>_nastran2stl.json` | `--manifest` (default) | Manifest (see below). |
| `<stem>_pid<PID>.step` | `--step --split` | Faceted STEP per PID. |
| `<stem>_all.step` | `--step --combined` | Combined STEP compound. |

`<stem>` is the sanitised input file stem.

### JSON manifest

```json
{
  "format": "nastran2stl/1",
  "source": "model.bdf",
  "source_units": "mm",
  "output_units": "mm",
  "scale": 1.0,
  "bounds": [[0.0, 0.0, 0.0], [10.0, 10.0, 10.0]],
  "combined_stl": "out/model_all.stl",
  "combined_step": null,
  "stats": { "nodes_read": 42, "elements_read": 12 },
  "warnings": [],
  "step_warnings": [],
  "unsupported_cards": { "CBAR": 3 },
  "objects": [
    {
      "pid": 100,
      "name": "PSHELL 100",
      "kind": "PSHELL",
      "elements": 8,
      "triangles": 16,
      "stl": "out/model_pid100.stl",
      "step": null,
      "solid": false,
      "thickness": null,
      "bounds": [[0.0, 0.0, 0.0], [10.0, 10.0, 10.0]]
    }
  ]
}
```

The manifest is designed to be consumed by downstream tools that need to know
what was written, in which units, and with which warnings.

## Console summary

A normal run prints a summary to stdout; warnings go to stderr:

```
model.bdf: 2 object(s), 24 triangles, unit mm -> mm (scale 1)
  PID 100    PSHELL   'PSHELL 100': 16 tri -> out\model_pid100.stl
    bounds [0, 0, 0] .. [10, 10, 10]
  PID 500    PSOLID   'PSOLID 500' [solid]: 8 tri -> out\model_pid500.stl
    bounds [0, 0, 0] .. [20, 20, 20]
  combined: out\model_all.stl
  manifest: out\model_nastran2stl.json
  nodes: 42, elements: 12
  STEP files: 2
```

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Success (possibly with warnings). |
| `1` | At least one input failed (I/O error, invalid option, viewer error, …). |
| `2` | Every input was readable but contained no usable geometry. |

`argparse` also returns `2` for usage errors such as unknown options.

## Names file

`names.json` maps a PID to a name.  Values may be plain strings or objects with
a `name` field:

```json
{
  "100": "enclosure",
  "500": { "name": "block" }
}
```

```bat
python -m nastran2stl model.bdf -o out --names names.json
```

Names are sanitised for the file system (invalid characters become `_`,
reserved Windows names such as `CON` are escaped) and are used as the STL
`solid` name in ASCII output.

## Recipes

```bat
:: 1) plain STL, one file per PID plus a combined file
python -m nastran2stl model.bdf -o out

:: 2) thin solids from shells, fallback thickness 0.8 mm, then STEP
python -m nastran2stl model.bdf -o out ^
    --shell-solid --shell-thickness 0.8 --solid-elements --step

:: 3) inches to millimetres, ASCII, no combined file, quiet
python -m nastran2stl model.bdf -o out ^
    --unit in --out-unit mm --ascii --no-combined -q

:: 4) batch convert many files, welding duplicated nodes
for %f in (parts\*.bdf) do python -m nastran2stl "%f" -o out --weld-tol 1e-6
```

On PowerShell use the backtick `` ` `` for line continuation and
`Get-ChildItem` instead of `for %f`.
