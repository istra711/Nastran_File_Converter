"""Optional STEP export through an installed FreeCAD/OpenCascade.

STL stores triangle surfaces.  FreeCAD can build a faceted B-rep shape from
those triangles and, when the mesh is closed, turn it into a real (but still
faceted) solid.  This module runs ``FreeCADCmd.exe`` in a subprocess so the
converter itself stays small and dependency-free.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class StepError(RuntimeError):
    """Raised when STEP export cannot be started or completed."""


@dataclass
class StepItem:
    """One STL file to convert into a STEP file.

    ``step_path`` may be ``None`` when the shape is only needed for a combined
    STEP compound.
    """

    stl_path: Path
    step_path: Path | None = None
    solid: bool = False
    label: str = ""


@dataclass
class StepResult:
    paths: list[Path] = field(default_factory=list)
    combined_path: Path | None = None
    warnings: list[str] = field(default_factory=list)
    statuses: list[dict[str, Any]] = field(default_factory=list)
    freecad_cmd: Path | None = None


def find_freecad_cmd() -> Path | None:
    """Find ``FreeCADCmd`` (or return ``None`` when FreeCAD is unavailable)."""
    env = os.environ.get("FREECAD_CMD", "").strip().strip('"')
    if env:
        candidate = Path(env).expanduser()
        if candidate.is_file():
            return candidate

    for name in ("FreeCADCmd.exe", "FreeCADCmd", "freecadcmd"):
        found = shutil.which(name)
        if found:
            return Path(found)

    roots: list[Path] = []
    for variable in ("ProgramFiles", "ProgramFiles(x86)"):
        value = os.environ.get(variable)
        if value:
            roots.append(Path(value))
    if os.name != "nt":
        roots.extend((Path("/usr/bin"), Path("/usr/local/bin"), Path("/opt")))

    candidates: list[Path] = []
    for root in roots:
        candidates.extend(root.glob("FreeCAD*/bin/FreeCADCmd.exe"))
        candidates.extend(root.glob("FreeCAD*/bin/FreeCADCmd"))
        candidates.extend(root.glob("freecad*/bin/FreeCADCmd"))
    for candidate in sorted(candidates, reverse=True):
        if candidate.is_file():
            return candidate
    return None


_SCRIPT_TEMPLATE = r'''
import json
import os
import Mesh
import Part

CONFIG = __CONFIG__

result = {"items": [], "combined": None}
shapes = []

for item in CONFIG["items"]:
    entry = {
        "label": item.get("label", ""),
        "stl": item.get("stl"),
        "step": item.get("step"),
        "status": "error",
        "message": "",
        "solid": False,
    }
    try:
        mesh = Mesh.Mesh(item["stl"])
        shape = Part.Shape()
        diagonal = getattr(mesh.BoundBox, "DiagonalLength", 0.0)
        tolerance = max(1e-9, min(0.1, diagonal * 1e-6)) if diagonal > 0 else 1e-6
        shape.makeShapeFromMesh(mesh.Topology, tolerance)

        out = shape
        status = "shell"
        if item.get("solid"):
            shells = list(shape.Shells)
            if shells and all(shell.isClosed() for shell in shells):
                solids = []
                for shell in shells:
                    try:
                        candidate = Part.Solid(shell)
                        if candidate.isValid():
                            solids.append(candidate)
                    except Exception:
                        pass
                if len(solids) == len(shells):
                    out = solids[0] if len(solids) == 1 else Part.makeCompound(solids)
                    status = "solid"
                else:
                    status = "shell_invalid_solid"
            else:
                status = "open_shell"

        geometry_scale = CONFIG.get("scale", 1.0)
        if geometry_scale != 1.0:
            out.scale(geometry_scale)

        if item.get("step"):
            out.exportStep(item["step"])
            if not os.path.isfile(item["step"]) or os.path.getsize(item["step"]) == 0:
                raise RuntimeError("FreeCAD did not write " + item["step"])

        entry["status"] = status
        entry["solid"] = status == "solid"
        shapes.append(out)
    except Exception as exc:
        entry["message"] = str(exc)
    result["items"].append(entry)

combined = CONFIG.get("combined")
if combined and shapes:
    try:
        out = shapes[0] if len(shapes) == 1 else Part.makeCompound(shapes)
        out.exportStep(combined)
        if not os.path.isfile(combined) or os.path.getsize(combined) == 0:
            raise RuntimeError("FreeCAD did not write " + combined)
        result["combined"] = {"step": combined, "status": "ok"}
    except Exception as exc:
        result["combined"] = {"step": combined, "status": "error", "message": str(exc)}

with open(CONFIG["result"], "w", encoding="utf-8") as handle:
    json.dump(result, handle)
'''


def write_step_files(
    items: list[StepItem],
    *,
    combined_path: Path | None = None,
    freecad_cmd: str | Path | None = None,
    timeout: float = 600.0,
    scale: float = 1.0,
) -> StepResult:
    """Convert STL files to faceted STEP files using FreeCADCmd.

    Closed meshes are converted to solids when ``StepItem.solid`` is true.
    Open surfaces are exported as shells.  ``combined_path`` writes a compound
    of all successfully created shapes.  ``scale`` is applied before export;
    STEP itself is written in millimetres by FreeCAD.
    """
    if not items:
        return StepResult(combined_path=None, freecad_cmd=None)
    if not math.isfinite(scale) or scale <= 0.0:
        raise StepError("STEP scale must be a positive, finite number")

    command = (
        Path(freecad_cmd).expanduser()
        if freecad_cmd is not None
        else find_freecad_cmd()
    )
    if command is None or not command.is_file():
        raise StepError(
            "FreeCADCmd.exe wurde nicht gefunden. STEP benötigt eine "
            "FreeCAD-Installation (oder die Umgebungsvariable FREECAD_CMD)."
        )

    for item in items:
        if not item.stl_path.is_file():
            raise StepError(f"STL-Datei nicht gefunden: {item.stl_path}")
        if item.step_path is not None:
            item.step_path.parent.mkdir(parents=True, exist_ok=True)
    if combined_path is not None:
        combined_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="nastran2stl_step_") as temp_name:
        temp = Path(temp_name)
        script_path = temp / "write_step.py"
        result_path = temp / "result.json"
        config = {
            "items": [
                {
                    "stl": str(item.stl_path),
                    "step": str(item.step_path) if item.step_path is not None else None,
                    "solid": bool(item.solid),
                    "label": item.label,
                }
                for item in items
            ],
            "combined": str(combined_path) if combined_path is not None else None,
            "result": str(result_path),
            "scale": float(scale),
        }
        script_path.write_text(
            _SCRIPT_TEMPLATE.replace("__CONFIG__", repr(config)),
            encoding="utf-8",
        )

        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            completed = subprocess.run(
                [str(command), str(script_path)],
                capture_output=True,
                text=True,
                timeout=timeout,
                creationflags=creation_flags,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise StepError(f"FreeCADCmd konnte nicht ausgeführt werden: {exc}") from exc

        if not result_path.is_file():
            details = (completed.stderr or completed.stdout or "").strip()
            if len(details) > 1200:
                details = details[-1200:]
            raise StepError(
                "FreeCADCmd hat keine STEP-Ergebnisse geschrieben."
                + (f"\n\n{details}" if details else "")
            )
        try:
            payload = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise StepError(f"FreeCAD-Ergebnis konnte nicht gelesen werden: {exc}") from exc

    warnings: list[str] = []
    paths: list[Path] = []
    statuses: list[dict[str, Any]] = []
    for entry, item in zip(payload.get("items", []), items):
        status = str(entry.get("status", "error"))
        statuses.append(entry)
        step_text = entry.get("step")
        if step_text:
            step_file = Path(step_text)
            if step_file.is_file():
                paths.append(step_file)
            else:
                warnings.append(f"{item.label}: STEP-Datei wurde nicht geschrieben.")
        if status == "error":
            message = str(entry.get("message", "")).strip()
            warnings.append(f"{item.label}: STEP fehlgeschlagen" + (f" ({message})" if message else ""))
        elif status == "open_shell":
            warnings.append(
                f"{item.label}: Netz ist nicht geschlossen; STEP enthält eine Fläche, "
                "keinen Solid."
            )
        elif status == "shell_invalid_solid":
            warnings.append(
                f"{item.label}: geschlossene Hülle konnte nicht in einen gültigen "
                "Solid umgewandelt werden; STEP enthält eine Fläche."
            )

    combined_step: Path | None = None
    combined_entry = payload.get("combined")
    if combined_entry:
        if combined_entry.get("status") == "ok" and combined_entry.get("step"):
            candidate = Path(combined_entry["step"])
            if candidate.is_file():
                combined_step = candidate
            else:
                warnings.append("Kombinierte STEP-Datei wurde nicht geschrieben.")
        elif combined_entry.get("status") == "error":
            message = str(combined_entry.get("message", "")).strip()
            warnings.append(
                "Kombinierte STEP-Datei fehlgeschlagen"
                + (f" ({message})" if message else "")
            )

    return StepResult(
        paths=paths,
        combined_path=combined_step,
        warnings=warnings,
        statuses=statuses,
        freecad_cmd=command,
    )


__all__ = [
    "StepError",
    "StepItem",
    "StepResult",
    "find_freecad_cmd",
    "write_step_files",
]
