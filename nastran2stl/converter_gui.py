"""Tkinter file converter for Nastran BDF meshes.

The GUI is intentionally a thin layer around :func:`nastran2stl.convert`: it
collects a source file and an output folder, runs the conversion in a worker
thread, and shows the written files.  STL is always written; shell extrusion
and STEP export (through FreeCAD) are optional.  The 3D viewer is available
from the same window, but conversion is the primary action.

The module can be started directly::

    python -m nastran2stl.converter_gui model.bdf
"""

from __future__ import annotations

import math
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

from .bdf import NastranError, NoGeometryError, read_bdf
from .convert import ConversionResult, convert, unit_factor
from .step import find_freecad_cmd
from .viewer import ViewerError, show_model

# Match the viewer's dark palette so both windows look like one application.
BACKGROUND = "#1b1c22"
PANEL = "#262832"
PANEL_HOVER = "#343645"
FOREGROUND = "#d8dae2"
MUTED = "#8b8f9e"
ACCENT = "#3a6ea5"
ACCENT_HOVER = "#4b82ba"
DANGER = "#a84b4b"
LOG_BACKGROUND = "#111217"
BORDER = "#3b3d4a"

UNITS = ("mm", "cm", "m", "in", "um", "nm", "ft", "mil")
SOLIDS_CHOICES = ("boundary", "faces", "skip")
_FILE_TYPES = (
    ("Nastran-Dateien", "*.bdf *.nas *.dat"),
    ("BDF", "*.bdf"),
    ("NAS", "*.nas"),
    ("DAT", "*.dat"),
    ("Alle Dateien", "*.*"),
)

HELP_TEXT = """STL, STEP und Solids

STL enthält immer Dreiecke. Auch eine geschlossene STL-Hülle ist für
FreeCAD zunächst eine Mesh-Oberfläche und noch kein CAD-Volumenkörper.

Option 1: Shells zu Solid extrudieren
  • Verwendet die PSHELL-Dicke T als Wanddicke.
  • Die ursprüngliche Oberfläche wird zur Mittelebene; oben, unten und an
    den freien Rändern entstehen geschlossene Dreiecksflächen.
  • Fehlt T oder ist T = 0, wird die Ersatzdicke verwendet. Die Ersatzdicke
    wird in der Einheit der Eingabedatei eingegeben.
  • Das Ergebnis ist eine geschlossene STL-Hülle. Mit STEP kann FreeCAD
    daraus einen facettierten Solid machen.

Option 2: Volumenelemente als Solid
  • Gilt für CHEXA, CTETRA, CPENTA und CPYRAM.
  • Die Außenhaut wird nur dann als Solid markiert, wenn sie wasserdicht
    ist. Bei offenen oder nicht zusammenhängenden Netzen bleibt STEP eine
    Fläche; im Protokoll erscheint ein Hinweis.
  • Diese Option wirkt sich auf STEP aus. Die STL-Ausgabe bleibt die
    bekannte Außenhaut.

Option 3: STEP und FreeCAD
  • Benötigt FreeCADCmd.exe. Das Programm sucht FreeCAD automatisch; ein
    abweichender Pfad kann über die Umgebungsvariable FREECAD_CMD oder in
    der Kommandozeile mit --freecad angegeben werden.
  • STEP wird als facettierte B-Rep-Geometrie geschrieben: Dreiecksflächen,
    keine glatten NURBS-Zylinder oder Freiformflächen.
  • Bei einem Fehler bleiben bereits geschriebene STL-Dateien erhalten.

Manuell in FreeCAD
  1. STL importieren.
  2. Part > Create shape from mesh (Form aus Mesh erzeugen).
  3. Part > Convert to solid (In Solid umwandeln), wenn die Hülle
     geschlossen ist.
  4. Für STEP: Datei > Exportieren > STEP.

Ohne FreeCAD lassen sich STL-Dateien weiterhin erzeugen. Option 1 kann
geschlossene STL-Hüllen auch ohne FreeCAD schreiben; Option 2 und STEP
benötigen FreeCAD für echte Solid-Dateien.
"""


def default_output_dir(source: str | Path) -> Path:
    """Return the visible default output folder for a BDF file."""
    path = Path(source).expanduser()
    return path.parent / f"{path.stem}_stl"


def result_output_dir(result: ConversionResult) -> Path | None:
    """Find the folder containing a conversion result's files."""
    if result.combined_path is not None:
        return result.combined_path.parent
    for obj in result.objects:
        if obj.stl_path is not None:
            return obj.stl_path.parent
    if result.manifest_path is not None:
        return result.manifest_path.parent
    return None


def _clean_path_text(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1]
    return value.strip()


def _format_bounds(bounds: tuple[tuple[float, ...], tuple[float, ...]] | None) -> str:
    if bounds is None:
        return "-"
    low, high = bounds
    size = tuple(high[i] - low[i] for i in range(3))
    return (
        f"min=({low[0]:g}, {low[1]:g}, {low[2]:g}) "
        f"max=({high[0]:g}, {high[1]:g}, {high[2]:g}) "
        f"size=({size[0]:g}, {size[1]:g}, {size[2]:g})"
    )


def format_result(result: ConversionResult, output_dir: Path | None = None) -> str:
    """Format a conversion result as readable text for the log."""
    output_dir = output_dir or result_output_dir(result)
    lines = [
        f"Quelle: {result.source}",
        f"Ausgabeordner: {output_dir if output_dir is not None else '-'}",
        (
            f"{len(result.objects)} Objekt(e), {result.triangle_count} Dreiecke, "
            f"Einheit {result.unit_in} -> {result.unit_out} "
            f"(Faktor {result.scale:g})"
        ),
    ]
    for obj in result.objects:
        target = str(obj.stl_path) if obj.stl_path is not None else "(nicht geschrieben)"
        flags = []
        if obj.solid:
            flags.append("Solid")
        if obj.thickness is not None:
            flags.append(f"Dicke {obj.thickness:g}")
        suffix = f" [{' / '.join(flags)}]" if flags else ""
        lines.append(
            f"  PID {obj.pid} [{obj.kind}] {obj.name}{suffix}: "
            f"{len(obj.triangles)} Dreiecke -> {target}"
        )
        if obj.step_path is not None:
            lines.append(f"    STEP: {obj.step_path}")
    if result.combined_path is not None:
        lines.append(f"  Kombiniert: {result.combined_path}")
    if result.combined_step_path is not None:
        lines.append(f"  Kombiniert STEP: {result.combined_step_path}")
    if result.manifest_path is not None:
        lines.append(f"  Manifest: {result.manifest_path}")
    lines.append(f"  Bounds: {_format_bounds(result.bounds)}")
    if result.warnings:
        lines.append(f"  Warnungen ({len(result.warnings)}):")
        for warning in result.warnings[:8]:
            lines.append(f"    {warning}")
        if len(result.warnings) > 8:
            lines.append(f"    ... {len(result.warnings) - 8} weitere")
    return "\n".join(lines)


class ConverterWindow:
    """Tkinter window for converting BDF files to STL and optional STEP."""

    def __init__(self, root, *, initial_file: str | Path | None = None) -> None:
        try:
            import tkinter as tk
            from tkinter import ttk
        except ImportError as exc:  # pragma: no cover
            raise ViewerError("Tkinter is not available") from exc

        self.tk = tk
        self.ttk = ttk
        self.root = root
        self.root.title("Nastran BDF → STL/STEP Konverter")
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        width = min(1040, max(820, screen_width - 120))
        height = min(840, max(660, screen_height - 160))
        self.root.geometry(f"{width}x{height}")
        self.root.minsize(min(900, width), min(620, height))
        self.root.configure(bg=BACKGROUND)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        self.input_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.unit_in_var = tk.StringVar(value="mm")
        self.unit_out_var = tk.StringVar(value="mm")
        self.solids_var = tk.StringVar(value="boundary")
        self.ascii_var = tk.BooleanVar(value=False)
        self.split_var = tk.BooleanVar(value=True)
        self.combined_var = tk.BooleanVar(value=True)
        self.manifest_var = tk.BooleanVar(value=True)
        self.view_after_var = tk.BooleanVar(value=False)
        self.open_after_var = tk.BooleanVar(value=True)
        self.shell_solid_var = tk.BooleanVar(value=False)
        self.solid_elements_var = tk.BooleanVar(value=False)
        self.step_var = tk.BooleanVar(value=False)
        self.thickness_var = tk.StringVar(value="")
        self._freecad_cmd = find_freecad_cmd()
        self.status_var = tk.StringVar(value="Bereit. Bitte eine BDF-Datei wählen.")

        self._output_auto = True
        self._running = False
        self._closed = False
        self._poll_id: str | None = None
        self._queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._last_result: ConversionResult | None = None
        self._last_output_dir: Path | None = None
        self._log_lines = 0

        self._build_ui()
        if initial_file is not None:
            self.set_input(initial_file)
        self.root.after(50, self._focus_input)

    # ------------------------------------------------------------------ UI

    def _button(self, parent, text: str, command, *, primary: bool = False):
        tk = self.tk
        background = ACCENT if primary else PANEL_HOVER
        active = ACCENT_HOVER if primary else BORDER
        return tk.Button(
            parent,
            text=text,
            command=command,
            bg=background,
            fg=FOREGROUND,
            activebackground=active,
            activeforeground=FOREGROUND,
            relief="flat",
            bd=0,
            padx=14,
            pady=7,
            cursor="hand2",
            disabledforeground=MUTED,
        )

    def _build_ui(self) -> None:
        tk = self.tk

        header = tk.Frame(self.root, bg=BACKGROUND, padx=18, pady=14)
        header.pack(fill="x")
        tk.Label(
            header,
            text="Nastran BDF → STL/STEP",
            bg=BACKGROUND,
            fg=FOREGROUND,
            font=("Segoe UI", 18, "bold"),
            anchor="w",
        ).pack(fill="x")
        tk.Label(
            header,
            text="Shells und Solids als STL oder facettierte STEP-Dateien exportieren",
            bg=BACKGROUND,
            fg=MUTED,
            anchor="w",
        ).pack(fill="x", pady=(2, 0))

        status = tk.Label(
            self.root,
            textvariable=self.status_var,
            bg=PANEL,
            fg=MUTED,
            anchor="w",
            padx=12,
            pady=5,
        )
        status.pack(side="bottom", fill="x")

        files = tk.Frame(
            self.root, bg=PANEL, padx=14, pady=12, highlightthickness=1,
            highlightbackground=BORDER,
        )
        files.pack(fill="x", padx=18, pady=(0, 10))
        files.columnconfigure(1, weight=1)

        tk.Label(files, text="Eingabedatei (BDF/NAS/DAT):", bg=PANEL, fg=FOREGROUND).grid(
            row=0, column=0, sticky="w", pady=4
        )
        self.input_entry = tk.Entry(
            files,
            textvariable=self.input_var,
            bg=LOG_BACKGROUND,
            fg=FOREGROUND,
            insertbackground=FOREGROUND,
            relief="flat",
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=ACCENT,
        )
        self.input_entry.grid(row=0, column=1, sticky="ew", padx=8, pady=4, ipady=4)
        self.input_entry.bind("<Return>", lambda _event: self.start_conversion())
        self._button(files, "Durchsuchen…", self.browse_input).grid(
            row=0, column=2, sticky="ew", pady=4
        )

        tk.Label(files, text="Ausgabeordner:", bg=PANEL, fg=FOREGROUND).grid(
            row=1, column=0, sticky="w", pady=4
        )
        self.output_entry = tk.Entry(
            files,
            textvariable=self.output_var,
            bg=LOG_BACKGROUND,
            fg=FOREGROUND,
            insertbackground=FOREGROUND,
            relief="flat",
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=ACCENT,
        )
        self.output_entry.grid(row=1, column=1, sticky="ew", padx=8, pady=4, ipady=4)
        self.output_entry.bind("<KeyRelease>", self._output_edited)
        self.output_entry.bind("<Return>", lambda _event: self.start_conversion())
        self._button(files, "Durchsuchen…", self.browse_output).grid(
            row=1, column=2, sticky="ew", pady=4
        )
        tk.Label(
            files,
            text="Standard: <Ordner der BDF>\\<Dateiname>_stl. "
            "Die STL-Dateien werden dort neu angelegt.",
            bg=PANEL,
            fg=MUTED,
            anchor="w",
        ).grid(row=2, column=1, columnspan=2, sticky="w", padx=8)

        options = tk.Frame(
            self.root, bg=PANEL, padx=14, pady=12, highlightthickness=1,
            highlightbackground=BORDER,
        )
        options.pack(fill="x", padx=18, pady=(0, 10))
        options.columnconfigure(5, weight=1)

        tk.Label(options, text="Einheit Eingabe:", bg=PANEL, fg=FOREGROUND).grid(
            row=0, column=0, sticky="w", padx=(0, 6), pady=3
        )
        self._combo(options, self.unit_in_var, UNITS, width=7).grid(
            row=0, column=1, sticky="w", padx=(0, 18), pady=3
        )
        tk.Label(options, text="Einheit STL:", bg=PANEL, fg=FOREGROUND).grid(
            row=0, column=2, sticky="w", padx=(0, 6), pady=3
        )
        self._combo(options, self.unit_out_var, UNITS, width=7).grid(
            row=0, column=3, sticky="w", padx=(0, 18), pady=3
        )
        tk.Label(options, text="Solids:", bg=PANEL, fg=FOREGROUND).grid(
            row=0, column=4, sticky="w", padx=(0, 6), pady=3
        )
        self._combo(options, self.solids_var, SOLIDS_CHOICES, width=10).grid(
            row=0, column=5, sticky="w", pady=3
        )

        checks = tk.Frame(options, bg=PANEL)
        checks.grid(row=1, column=0, columnspan=6, sticky="w", pady=(8, 0))
        self._check(checks, "STL pro PID", self.split_var).pack(side="left", padx=(0, 16))
        self._check(checks, "Kombinierte STL", self.combined_var).pack(
            side="left", padx=(0, 16)
        )
        self._check(checks, "ASCII-STL", self.ascii_var).pack(side="left", padx=(0, 16))
        self._check(checks, "JSON-Manifest", self.manifest_var).pack(
            side="left", padx=(0, 16)
        )
        self._check(checks, "Nach dem Konvertieren 3D anzeigen", self.view_after_var).pack(
            side="left", padx=(0, 16)
        )
        self._check(
            checks, "Ausgabeordner öffnen", self.open_after_var
        ).pack(side="left")

        solid = tk.Frame(
            self.root, bg=PANEL, padx=14, pady=10, highlightthickness=1,
            highlightbackground=BORDER,
        )
        solid.pack(fill="x", padx=18, pady=(0, 10))
        solid.columnconfigure(6, weight=1)

        tk.Label(solid, text="Volumenkörper:", bg=PANEL, fg=FOREGROUND).grid(
            row=0, column=0, sticky="w", padx=(0, 8)
        )
        self._check(
            solid, "Shells extrudieren (PSHELL T)", self.shell_solid_var
        ).grid(row=0, column=1, sticky="w")
        tk.Label(solid, text="Ersatzdicke:", bg=PANEL, fg=FOREGROUND).grid(
            row=0, column=2, sticky="w", padx=(14, 5)
        )
        self.thickness_entry = tk.Entry(
            solid,
            textvariable=self.thickness_var,
            width=8,
            bg=LOG_BACKGROUND,
            fg=FOREGROUND,
            insertbackground=FOREGROUND,
            relief="flat",
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=ACCENT,
        )
        self.thickness_entry.grid(row=0, column=3, sticky="w", ipady=3)
        tk.Label(solid, text="(Eingabeeinheit)", bg=PANEL, fg=MUTED).grid(
            row=0, column=4, sticky="w", padx=(5, 14)
        )
        self._check(
            solid, "Volumenelemente als Solid (STEP)", self.solid_elements_var
        ).grid(row=0, column=5, sticky="w")
        self._check(
            solid, "STEP zusätzlich (FreeCAD)", self.step_var
        ).grid(row=1, column=1, sticky="w", pady=(5, 0))

        if self._freecad_cmd is not None:
            version = self._freecad_cmd.parent.parent.name
            freecad_text = f"FreeCAD gefunden ({version})"
        else:
            freecad_text = (
                "FreeCAD: nicht gefunden – STEP ist nicht verfügbar "
                "(FREECAD_CMD setzen oder FreeCAD installieren)."
            )
        tk.Label(solid, text=freecad_text, bg=PANEL, fg=MUTED, anchor="w").grid(
            row=1, column=2, columnspan=5, sticky="w", padx=(5, 0), pady=(5, 0)
        )
        self.help_button = self._button(solid, "Hilfe", self.show_help)
        self.help_button.grid(row=0, column=7, rowspan=2, sticky="e", padx=(12, 0))

        actions = tk.Frame(self.root, bg=BACKGROUND, padx=18)
        actions.pack(fill="x", pady=(0, 10))
        self.convert_button = self._button(
            actions, "Konvertieren", self.start_conversion, primary=True
        )
        self.convert_button.pack(side="left")
        self.view_button = self._button(actions, "3D anzeigen", self.show_view)
        self.view_button.pack(side="left", padx=(8, 0))
        self.open_button = self._button(
            actions, "Ausgabeordner öffnen", self.open_output
        )
        self.open_button.pack(side="left", padx=(8, 0))
        self.open_button.configure(state="disabled")

        log_frame = tk.Frame(self.root, bg=BACKGROUND, padx=18, pady=0)
        log_frame.pack(fill="both", expand=True, pady=(0, 12))
        tk.Label(
            log_frame, text="Protokoll", bg=BACKGROUND, fg=FOREGROUND, anchor="w"
        ).pack(fill="x", pady=(0, 4))
        text_frame = tk.Frame(log_frame, bg=BACKGROUND)
        text_frame.pack(fill="both", expand=True)
        self.log = tk.Text(
            text_frame,
            bg=LOG_BACKGROUND,
            fg=FOREGROUND,
            insertbackground=FOREGROUND,
            selectbackground=ACCENT,
            selectforeground=FOREGROUND,
            relief="flat",
            highlightthickness=1,
            highlightbackground=BORDER,
            wrap="word",
            padx=8,
            pady=6,
            state="disabled",
        )
        scrollbar = tk.Scrollbar(
            text_frame, command=self.log.yview, bg=PANEL, troughcolor=LOG_BACKGROUND,
            activebackground=PANEL_HOVER, relief="flat",
        )
        self.log.configure(yscrollcommand=scrollbar.set)
        self.log.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self._append_log(
            "Bereit. Wähle eine BDF-Datei, prüfe den Ausgabeordner und "
            "klicke auf „Konvertieren“."
        )

    def _combo(self, parent, variable, values, *, width: int):
        combo = self.ttk.Combobox(
            parent,
            textvariable=variable,
            values=values,
            state="readonly",
            width=width,
        )
        return combo

    def _check(self, parent, text: str, variable):
        tk = self.tk
        return tk.Checkbutton(
            parent,
            text=text,
            variable=variable,
            bg=PANEL,
            fg=FOREGROUND,
            activebackground=PANEL,
            activeforeground=FOREGROUND,
            selectcolor=LOG_BACKGROUND,
            anchor="w",
            bd=0,
            highlightthickness=0,
        )

    # --------------------------------------------------------------- input

    def _focus_input(self) -> None:
        if not self._closed:
            self.input_entry.focus_set()

    def _dialog_directory(self) -> str:
        current = _clean_path_text(self.input_var.get())
        if current:
            path = Path(current).expanduser()
            if path.parent.is_dir():
                return str(path.parent)
        return str(Path.home())

    def _output_edited(self, _event=None) -> None:
        self._output_auto = False

    def browse_input(self) -> Path | None:
        from tkinter import filedialog, messagebox

        try:
            selected = filedialog.askopenfilename(
                parent=self.root,
                title="Nastran-Datei auswählen",
                initialdir=self._dialog_directory(),
                filetypes=_FILE_TYPES,
            )
        except Exception as exc:  # pragma: no cover - dialog failures
            messagebox.showerror("Datei auswählen", str(exc), parent=self.root)
            return None
        if not selected:
            return None
        path = Path(selected)
        self.set_input(path)
        return path

    def set_input(self, path: str | Path) -> None:
        path = Path(path).expanduser()
        self.input_var.set(str(path))
        if self._output_auto or not self.output_var.get().strip():
            self.output_var.set(str(default_output_dir(path)))
            self._output_auto = True
        self.status_var.set(f"Eingabe: {path.name}")

    def browse_output(self) -> Path | None:
        from tkinter import filedialog, messagebox

        current = _clean_path_text(self.output_var.get())
        initial = current or self._dialog_directory()
        try:
            selected = filedialog.askdirectory(
                parent=self.root,
                title="Ausgabeordner auswählen",
                initialdir=initial,
                mustexist=False,
            )
        except Exception as exc:  # pragma: no cover - dialog failures
            messagebox.showerror("Ausgabeordner", str(exc), parent=self.root)
            return None
        if not selected:
            return None
        path = Path(selected)
        self.output_var.set(str(path))
        self._output_auto = False
        return path

    # ---------------------------------------------------------- conversion

    def _collect_job(self) -> dict[str, Any]:
        source_text = _clean_path_text(self.input_var.get())
        if not source_text:
            raise ValueError("Bitte eine Eingabedatei wählen.")
        source = Path(source_text).expanduser()
        if not source.is_file():
            raise ValueError(f"Eingabedatei nicht gefunden:\n{source}")

        output_text = _clean_path_text(self.output_var.get())
        output_dir = (
            Path(output_text).expanduser() if output_text else default_output_dir(source)
        )
        if output_dir.exists() and not output_dir.is_dir():
            raise ValueError(f"Der Ausgabepfad ist kein Ordner:\n{output_dir}")

        if not self.split_var.get() and not self.combined_var.get():
            raise ValueError(
                "Mindestens eine STL-Ausgabe muss aktiv sein:\n"
                "„STL pro PID“ oder „Kombinierte STL“."
            )

        unit_in = self.unit_in_var.get()
        unit_out = self.unit_out_var.get()
        unit_factor(unit_in)
        unit_factor(unit_out)
        solids = self.solids_var.get()
        if solids not in SOLIDS_CHOICES:
            raise ValueError(f"Unbekannter Solids-Modus: {solids}")

        shell_solid = bool(self.shell_solid_var.get())
        thickness_text = self.thickness_var.get().strip().replace(",", ".")
        shell_thickness: float | None = None
        if shell_solid and thickness_text:
            try:
                shell_thickness = float(thickness_text)
            except ValueError as exc:
                raise ValueError(
                    "Die Ersatzdicke muss eine Zahl in der Eingabeeinheit sein."
                ) from exc
            if not math.isfinite(shell_thickness) or shell_thickness <= 0.0:
                raise ValueError("Die Ersatzdicke muss größer als 0 sein.")

        return {
            "source": source,
            "out_dir": output_dir,
            "unit_in": unit_in,
            "unit_out": unit_out,
            "split": bool(self.split_var.get()),
            "combined": bool(self.combined_var.get()),
            "ascii_stl": bool(self.ascii_var.get()),
            "solids": solids,
            "manifest": bool(self.manifest_var.get()),
            "shell_solid": shell_solid,
            "shell_thickness": shell_thickness,
            "solid_elements": bool(self.solid_elements_var.get()),
            "step": bool(self.step_var.get()),
        }

    def start_conversion(self) -> None:
        if self._running:
            return
        from tkinter import messagebox

        try:
            job = self._collect_job()
        except (NastranError, ValueError, OSError) as exc:
            messagebox.showerror("Eingabe prüfen", str(exc), parent=self.root)
            return

        self._running = True
        self._last_result = None
        self._last_output_dir = job["out_dir"]
        if not self.output_var.get().strip():
            self.output_var.set(str(job["out_dir"]))
            self._output_auto = True
        self.convert_button.configure(state="disabled")
        self.view_button.configure(state="disabled")
        self.open_button.configure(state="disabled")
        self.status_var.set("Konvertiere…")
        self._append_log("")
        self._append_log(f"=== Konvertierung: {job['source']} ===")
        self._append_log(f"Ausgabeordner: {job['out_dir']}")
        if job["step"] and self._freecad_cmd is None:
            self._append_log(
                "Hinweis: FreeCADCmd wurde nicht gefunden; STEP wird übersprungen."
            )
        if job["solid_elements"] and not job["step"]:
            self._append_log(
                "Hinweis: „Volumenelemente als Solid“ wirkt nur mit STEP; "
                "die STL-Ausgabe bleibt eine Oberfläche."
            )
        self._append_log("Läuft…")

        thread = threading.Thread(
            target=self._run_conversion, args=(job,), name="nastran2stl-convert",
            daemon=True,
        )
        thread.start()
        self._schedule_poll()

    def _run_conversion(self, job: dict[str, Any]) -> None:
        try:
            result = convert(
                job["source"],
                job["out_dir"],
                unit_in=job["unit_in"],
                unit_out=job["unit_out"],
                split=job["split"],
                combined=job["combined"],
                ascii_stl=job["ascii_stl"],
                solids=job["solids"],
                manifest=job["manifest"],
                shell_solid=job["shell_solid"],
                shell_thickness=job["shell_thickness"],
                solid_elements=job["solid_elements"],
                step=job["step"],
            )
        except Exception as exc:  # noqa: BLE001 - report all conversion errors
            self._queue.put(("error", exc))
        else:
            self._queue.put(("ok", result))

    def _schedule_poll(self) -> None:
        if self._closed or self._poll_id is not None:
            return
        self._poll_id = self.root.after(100, self._poll_queue)

    def _poll_queue(self) -> None:
        self._poll_id = None
        if self._closed:
            return
        try:
            kind, payload = self._queue.get_nowait()
        except queue.Empty:
            if self._running:
                self._schedule_poll()
            return

        self._running = False
        self.convert_button.configure(state="normal")
        self.view_button.configure(state="normal")
        if kind == "ok":
            self._finish(payload)
        else:
            self._fail(payload)
        if self._running:
            self._schedule_poll()

    def _finish(self, result: ConversionResult) -> None:
        from tkinter import messagebox

        self._last_result = result
        output_dir = result_output_dir(result) or self._last_output_dir
        self._last_output_dir = output_dir
        self._append_log(format_result(result, output_dir))
        stl_files = sum(1 for obj in result.objects if obj.stl_path is not None)
        if result.combined_path is not None:
            stl_files += 1
        step_files = sum(1 for obj in result.objects if obj.step_path is not None)
        if result.combined_step_path is not None:
            step_files += 1
        if output_dir is not None:
            self.open_button.configure(state="normal")
            self.status_var.set(
                f"Fertig: {result.triangle_count} Dreiecke, "
                f"{stl_files} STL, {step_files} STEP in {output_dir}"
            )
        else:
            self.status_var.set(
                f"Fertig: {result.triangle_count} Dreiecke geschrieben."
            )
        self._append_log("")
        summary = (
            f"{result.triangle_count} Dreiecke in {stl_files} STL-Datei(en) "
            f"und {step_files} STEP-Datei(en) geschrieben.\n\n"
            f"Ausgabeordner:\n{output_dir if output_dir else '-'}"
        )
        if result.step_warnings:
            hints = "\n".join(result.step_warnings[:5])
            if len(result.step_warnings) > 5:
                hints += f"\n... {len(result.step_warnings) - 5} weitere"
            summary += f"\n\nSTEP-Hinweise:\n{hints}"
        messagebox.showinfo(
            "Konvertierung abgeschlossen",
            summary,
            parent=self.root,
        )
        if self.open_after_var.get() and output_dir is not None:
            self._open_folder(output_dir)
        if self.view_after_var.get():
            self.show_view()

    def _fail(self, error: Exception) -> None:
        from tkinter import messagebox

        self.status_var.set("Fehler bei der Konvertierung.")
        self._append_log(f"FEHLER: {error}")
        messagebox.showerror(
            "Konvertierung fehlgeschlagen", str(error), parent=self.root
        )

    # -------------------------------------------------------------- actions

    def show_help(self) -> None:
        """Show the built-in explanation for solids, STEP and FreeCAD."""
        tk = self.tk
        window = tk.Toplevel(self.root)
        window.title("Hilfe: Solid und STEP")
        window.configure(bg=BACKGROUND)
        window.geometry("760x600")
        window.transient(self.root)
        window.columnconfigure(0, weight=1)
        window.rowconfigure(0, weight=1)

        text = tk.Text(
            window,
            bg=LOG_BACKGROUND,
            fg=FOREGROUND,
            insertbackground=FOREGROUND,
            selectbackground=ACCENT,
            selectforeground=FOREGROUND,
            relief="flat",
            wrap="word",
            padx=14,
            pady=12,
        )
        text.grid(row=0, column=0, sticky="nsew", padx=14, pady=(14, 8))
        text.insert("1.0", HELP_TEXT)
        text.configure(state="disabled")

        scrollbar = tk.Scrollbar(
            window,
            command=text.yview,
            bg=PANEL,
            troughcolor=LOG_BACKGROUND,
            activebackground=PANEL_HOVER,
            relief="flat",
        )
        scrollbar.grid(row=0, column=1, sticky="ns", pady=(14, 8))
        text.configure(yscrollcommand=scrollbar.set)

        self._button(window, "Schließen", window.destroy).grid(
            row=1, column=0, columnspan=2, sticky="e", padx=14, pady=(0, 12)
        )

    def show_view(self) -> None:
        from tkinter import messagebox

        try:
            if self._last_result is not None:
                result = self._last_result
                show_model(
                    result.model,
                    result.objects,
                    title=result.source.name,
                    parent=self.root,
                    block=False,
                )
                return

            source_text = _clean_path_text(self.input_var.get())
            if not source_text:
                raise ValueError("Bitte zuerst eine Eingabedatei wählen.")
            source = Path(source_text).expanduser()
            if not source.is_file():
                raise ValueError(f"Eingabedatei nicht gefunden:\n{source}")
            model = read_bdf(source)
            parts = model.parts(solids=self.solids_var.get())
            if not parts:
                raise NoGeometryError(
                    f"{source.name}: keine unterstützte Shell-/Solid-Geometrie"
                )
            show_model(
                model,
                parts,
                title=source.name,
                parent=self.root,
                block=False,
            )
        except (NastranError, ViewerError, ValueError, OSError) as exc:
            messagebox.showerror("3D-Ansicht", str(exc), parent=self.root)

    def open_output(self) -> None:
        from tkinter import messagebox

        output_dir = self._last_output_dir
        if output_dir is None:
            text = _clean_path_text(self.output_var.get())
            if text:
                output_dir = Path(text).expanduser()
        if output_dir is None or not output_dir.is_dir():
            messagebox.showinfo(
                "Ausgabeordner",
                "Es wurde noch kein Ausgabeordner angelegt.\n"
                "Bitte zuerst konvertieren.",
                parent=self.root,
            )
            return
        self._open_folder(output_dir)

    def _open_folder(self, folder: Path) -> None:
        from tkinter import messagebox

        try:
            if sys.platform.startswith("win"):
                os.startfile(str(folder))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(folder)])
            else:
                subprocess.Popen(["xdg-open", str(folder)])
        except OSError as exc:
            messagebox.showerror(
                "Ausgabeordner öffnen",
                f"Ordner konnte nicht geöffnet werden:\n{folder}\n\n{exc}",
                parent=self.root,
            )

    def _append_log(self, text: str) -> None:
        if self._closed:
            return
        self.log.configure(state="normal")
        if text:
            self.log.insert("end", text + "\n")
            self._log_lines += 1
        self.log.see("end")
        self.log.configure(state="disabled")

    def close(self) -> None:
        from tkinter import messagebox

        if self._running and not messagebox.askyesno(
            "Konvertierung läuft",
            "Die Konvertierung läuft noch. Fenster trotzdem schließen?",
            parent=self.root,
        ):
            return
        self._closed = True
        if self._poll_id is not None:
            try:
                self.root.after_cancel(self._poll_id)
            except Exception:
                pass
            self._poll_id = None
        self.root.destroy()


def main(argv: list[str] | None = None) -> int:
    """Start the converter GUI; an optional BDF path is used as input."""
    try:
        import tkinter as tk
    except ImportError:
        print("error: Tkinter is not available", file=sys.stderr)
        return 1

    arguments = list(sys.argv[1:] if argv is None else argv)
    initial_file: Path | None = None
    for argument in arguments:
        if argument.startswith("-"):
            continue
        candidate = Path(argument).expanduser()
        if candidate.is_file():
            initial_file = candidate
            break

    try:
        root = tk.Tk()
    except tk.TclError as exc:
        print(f"error: cannot open a window: {exc}", file=sys.stderr)
        return 1

    ConverterWindow(root, initial_file=initial_file)
    root.mainloop()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
