# GUI usage

The desktop converter is the easiest way to use the tool.  It is a thin
[Tkinter](https://docs.python.org/3/library/tkinter.html) layer around
`nastran2stl.convert`: it collects the options, runs the conversion in a worker
thread and displays the written files.

> The GUI labels are in **German**.  This page lists each control with its
> English meaning.  The CLI and the library API are language-neutral.

## Starting the GUI

```bat
:: empty window, pick a file inside the app
python -m nastran2stl.converter_gui

:: prefill the input file
python -m nastran2stl.converter_gui tests\fixtures\solids_pids.bdf
```

With the standalone build, just run `NastranConverter.exe`.  You can also drag a
BDF file onto the EXE; the input and the default output folder are then
prefilled.  A path passed on the command line behaves the same way.

## Window layout

```
┌ Nastran BDF → STL/STEP ──────────────────────────────────────────────┐
│ Nastran BDF → STL/STEP                                               │
│ Shells und Solids als STL oder facettierte STEP-Dateien exportieren   │
│ <status line>                                                         │
│ ┌ Eingabedatei (BDF/NAS/DAT): [..............] [Durchsuchen…]        │
│ │ Ausgabeordner:              [..............] [Durchsuchen…]        │
│ │ Standard: <Ordner der BDF>\<Dateiname>_stl. …                       │
│ └ Einheit Eingabe [mm▾]  Einheit STL [mm▾]  Solids [boundary▾]       │
│   ☑ STL pro PID  ☑ Kombinierte STL  ☐ ASCII-STL  ☑ JSON-Manifest    │
│   ☐ Nach dem Konvertieren 3D anzeigen   ☐ Ausgabeordner öffnen       │
│ ┌ Volumenkörper:                                                      │
│ │ ☐ Shells extrudieren (PSHELL T)   Ersatzdicke: [ ] (Eingabeeinheit)│
│ │ ☐ Volumenelemente als Solid (STEP)              [Hilfe]            │
│ │ ☐ STEP zusätzlich (FreeCAD)   FreeCAD gefunden (FreeCAD 0.19)      │
│ └ [Konvertieren] [3D anzeigen] [Ausgabeordner öffnen]                │
│ Protokoll                                                            │
│ ┌──────────────────────────────────────────────────────────────────┐ │
│ │ conversion log …                                                 │ │
│ └──────────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────┘
```

## Input and output

| Control | Meaning |
| --- | --- |
| **Eingabedatei (BDF/NAS/DAT)** | The `.bdf`/`.nas`/`.dat` file to convert.  **Durchsuchen…** opens a file dialog. |
| **Ausgabeordner** | Target folder.  Defaults to `<input folder>\<input stem>_stl`.  **Durchsuchen…** opens a folder dialog. |

The default output folder is shown in the field automatically once an input
file is chosen.  Editing the field keeps your value; the automatic behaviour is
disabled as soon as you type.

## Units and geometry mode

| Control | Meaning |
| --- | --- |
| **Einheit Eingabe** | Unit of the coordinates in the BDF file (default `mm`). |
| **Einheit STL** | Unit of the STL output (default `mm`). |
| **Solids** | `boundary` = outer skin per PID (default), `faces` = every element face, `skip` = ignore volume elements. |

## Output switches

| Control | Meaning |
| --- | --- |
| **STL pro PID** | Write one STL per property ID (default on). |
| **Kombinierte STL** | Also write one merged STL (default on). |
| **ASCII-STL** | Write ASCII instead of binary STL. |
| **JSON-Manifest** | Write the `<stem>_nastran2stl.json` manifest (default on). |
| **Nach dem Konvertieren 3D anzeigen** | Open the 3D viewer when conversion finishes. |
| **Ausgabeordner öffnen** | Open the output folder in the file manager when conversion finishes. |

At least one of **STL pro PID** and **Kombinierte STL** must be enabled; the
GUI reports an error dialog otherwise.

## Solid and STEP options

This is the **Volumenkörper** (solid bodies) section.  The three options map to
the CLI switches and to the library parameters.

| Control | CLI equivalent | Meaning |
| --- | --- | --- |
| **Shells extrudieren (PSHELL T)** | `--shell-solid` | Option 1.  Thicken each shell PID by its `PSHELL` thickness `T`, producing a closed thin solid. |
| **Ersatzdicke** | `--shell-thickness T` | Fallback thickness **in the input unit** when `T` is missing or zero.  Only evaluated when option 1 is enabled.  Commas are accepted as decimal separators. |
| **(Eingabeeinheit)** | — | Reminder that the fallback thickness uses the input unit, not the STL unit. |
| **Volumenelemente als Solid (STEP)** | `--solid-elements` | Option 2.  Mark watertight volume-element boundaries as solids for STEP. |
| **STEP zusätzlich (FreeCAD)** | `--step` | Option 3.  Write faceted `.step` files next to the STL files. |
| **FreeCAD …** status | — | Shows whether `FreeCADCmd` was found (and the version folder) or explains how to provide it. |
| **Hilfe** | — | Opens the **Hilfe: Solid und STEP** dialog with the option descriptions and the manual FreeCAD workflow. |

The three options are **independent**:

- Option 1 changes the STL geometry (closed mesh) and can produce a STEP solid
  even without option 2.
- Option 2 only affects STEP metadata; the STL stays the outer skin.
- Option 3 decides whether STEP files are written at all.  Without FreeCAD,
  STL is still written and a note appears in the log.

See [solids-and-step.md](solids-and-step.md) for the exact semantics.

## Actions

| Button | Meaning |
| --- | --- |
| **Konvertieren** | Validate the inputs and start the conversion.  The button is disabled while a job runs. |
| **3D anzeigen** | Open the current input in the 3D viewer, or the last conversion result if one exists. |
| **Ausgabeordner öffnen** | Open the last output folder.  Disabled until a conversion has finished. |

## Conversion log

The **Protokoll** panel receives a timestamped log: the chosen source and
output folder, the options, every written file, bounds, warnings and any STEP
warnings.  When the run finishes, a confirmation dialog shows the output folder
and a short summary, and the folder button becomes active.

## Validation

Before conversion the GUI checks that:

- the input file exists and is a file,
- the output path is a directory (or can be created),
- at least one STL output is enabled,
- both units are known,
- the solids mode is valid,
- the fallback thickness is a positive finite number when shell extrusion is
  enabled and a value was entered.

Validation errors are shown in an error dialog and never start a thread.

## 3D viewer

The viewer is shared with the CLI (`--view` / `--view-only`).  It is a small
software renderer built on a plain Tkinter `Canvas`; it needs no OpenGL, no
NumPy and no Qt.

```bat
:: open the file dialog and choose a BDF
python -m nastran2stl.viewer

:: open a file directly
python -m nastran2stl.viewer model.bdf
python -m nastran2stl.viewer model.bdf --wireframe --solids boundary
```

Controls:

| Input | Action |
| --- | --- |
| Left-drag | Rotate / orbit |
| Shift+left-drag or middle-drag | Pan |
| Mouse wheel | Zoom |
| `W` | Toggle wireframe |
| `F` | Fit model to window |
| `R` | Reset camera |
| `T` | Top view |
| `Esc` | Close window |
| Sidebar checkboxes | Show or hide individual PIDs |

Each PID gets a stable colour from a fixed palette, so the same model always
looks the same.  The window title shows the triangle count.  Very large meshes
are decimated while dragging and rendered at full detail after the mouse button
is released.

On systems without a graphical display, `--view`, `--view-only` and the viewer
entry points report a clear error; the headless geometry API (`Scene`,
`Camera`) can still be imported.  On Linux, install Tkinter with your package
manager (for example `python3-tk`).
