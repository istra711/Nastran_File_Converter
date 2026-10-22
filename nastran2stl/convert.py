"""High-level BDF -> STL conversion (files, manifest, plugin-friendly result)."""

from __future__ import annotations

import json
import math
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .bdf import (
    BdfModel,
    NastranError,
    NoGeometryError,
    UNIT_TO_METRES,
    read_bdf,
    triangle_bounds,
)
from .solid import SolidError, extrude_shell_triangles, is_watertight
from .step import StepError, StepItem, write_step_files
from .stl import write_stl

_MANIFEST_FORMAT = "nastran2stl/1"
_INVALID_NAME = re.compile(r"[^A-Za-z0-9._-]+")
_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


@dataclass
class ConvertedObject:
    pid: int
    name: str
    kind: str
    triangles: list[tuple[float, ...]]
    element_count: int
    stl_path: Path | None = None
    bounds: tuple[tuple[float, float, float], tuple[float, float, float]] | None = None
    solid: bool = False
    thickness: float | None = None
    step_path: Path | None = None


@dataclass
class ConversionResult:
    source: Path
    model: BdfModel
    objects: list[ConvertedObject]
    combined_path: Path | None
    manifest_path: Path | None
    warnings: list[str]
    stats: dict[str, Any]
    bounds: tuple[tuple[float, float, float], tuple[float, float, float]] | None
    scale: float
    unit_in: str
    unit_out: str
    combined_step_path: Path | None = None
    step_warnings: list[str] = field(default_factory=list)

    @property
    def triangle_count(self) -> int:
        return sum(len(obj.triangles) for obj in self.objects)


def sanitize_name(text: object, *, fallback: str = "mesh", limit: int = 80) -> str:
    """Make a string safe for file names on Windows and POSIX."""
    value = _INVALID_NAME.sub("_", str(text)).strip(" ._-")
    if not value:
        value = fallback
    if value.upper() in _WINDOWS_RESERVED:
        value = f"_{value}"
    return value[:limit]


def unit_factor(name: str) -> float:
    key = str(name).strip().lower()
    if key not in UNIT_TO_METRES:
        supported = ", ".join(sorted(set(UNIT_TO_METRES)))
        raise NastranError(f"unknown unit {name!r}; supported: {supported}")
    return UNIT_TO_METRES[key]


def load_names(path: str | Path) -> dict[int, str]:
    """Load a JSON map ``{"100": "enclosure"}`` (values may be objects)."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise NastranError(f"cannot read names file {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise NastranError("names JSON must be an object mapping PID -> name")
    result: dict[int, str] = {}
    for key, value in data.items():
        try:
            pid = int(key)
        except (TypeError, ValueError):
            continue
        if isinstance(value, dict):
            value = value.get("name")
        if value is not None and str(value).strip():
            result[pid] = str(value).strip()
    return result


def _part_element_counts(part) -> tuple[int, int]:
    """Return ``(shell_count, solid_count)`` for a mesh part.

    Older/external ``MeshPart`` instances may not carry the counters.  In that
    case the property card is a good fallback.
    """
    if part.shell_count or part.solid_count:
        return part.shell_count, part.solid_count
    if part.kind == "PSOLID":
        return 0, part.element_count
    return part.element_count, 0


def _write_manifest(
    path: Path,
    *,
    source: Path,
    model: BdfModel,
    objects: list[ConvertedObject],
    combined_path: Path | None,
    combined_step_path: Path | None,
    scale: float,
    unit_in: str,
    unit_out: str,
    bounds: tuple[tuple[float, float, float], tuple[float, float, float]] | None,
    warnings: list[str],
    step_warnings: list[str],
) -> None:
    payload = {
        "format": _MANIFEST_FORMAT,
        "source": str(source),
        "source_units": unit_in,
        "output_units": unit_out,
        "scale": scale,
        "bounds": [list(bounds[0]), list(bounds[1])] if bounds else None,
        "combined_stl": str(combined_path) if combined_path else None,
        "combined_step": str(combined_step_path) if combined_step_path else None,
        "stats": dict(model.stats),
        "warnings": list(warnings),
        "step_warnings": list(step_warnings),
        "unsupported_cards": dict(model.unsupported.most_common()),
        "objects": [
            {
                "pid": obj.pid,
                "name": obj.name,
                "kind": obj.kind,
                "elements": obj.element_count,
                "triangles": len(obj.triangles),
                "stl": str(obj.stl_path) if obj.stl_path else None,
                "step": str(obj.step_path) if obj.step_path else None,
                "solid": obj.solid,
                "thickness": obj.thickness,
                "bounds": [list(obj.bounds[0]), list(obj.bounds[1])] if obj.bounds else None,
            }
            for obj in objects
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def convert(
    source: str | Path,
    out_dir: str | Path | None = None,
    *,
    unit_in: str = "mm",
    unit_out: str = "mm",
    scale: float | None = None,
    split: bool = True,
    combined: bool = True,
    ascii_stl: bool = False,
    solids: str = "boundary",
    quad_split: str = "shortest",
    weld_tol: float = 0.0,
    names: dict[int, str] | None = None,
    manifest: bool = True,
    shell_solid: bool = False,
    shell_thickness: float | None = None,
    solid_elements: bool = False,
    step: bool = False,
    freecad_cmd: str | Path | None = None,
) -> ConversionResult:
    """Convert one BDF/NAS file to STL files (and optional STEP files).

    Parameters
    ----------
    source:
        Input file (BDF/NAS/DAT).
    out_dir:
        Target folder; defaults to the folder of the input file.
    unit_in, unit_out:
        Units of the Nastran coordinates and of the STL output.  The scale
        factor is ``unit_in / unit_out`` (e.g. ``in`` -> ``mm`` gives 25.4).
    scale:
        Optional factor that overrides the unit conversion.
    split, combined:
        Write one STL per PID and/or one combined STL.
    solids:
        ``boundary`` = outer skin per PID, ``faces`` = every volume element
        face, ``skip`` = ignore volume elements.
    weld_tol:
        Tolerance (in source units) for merging duplicated nodes when the
        solid boundary is extracted.  ``0`` = only genuinely shared node ids.
    shell_solid:
        Extrude shell elements by their ``PSHELL`` thickness.  The original
        surface becomes the mid-plane and the STL becomes a closed thin solid.
    shell_thickness:
        Fallback thickness in source units when a shell has no positive
        ``PSHELL`` thickness.  It is scaled with the other coordinates.
    solid_elements:
        Treat watertight volume-element boundaries as solids for STEP.  Open
        boundaries stay surfaces and are reported as a warning.
    step:
        Also write faceted STEP files through an installed FreeCADCmd.  A
        missing or failing FreeCAD does not remove the STL files; the problem
        is reported in :attr:`ConversionResult.step_warnings`.
    freecad_cmd:
        Explicit path to ``FreeCADCmd.exe``; otherwise auto-detected.
    """
    if not split and not combined:
        raise ValueError("at least one of split/combined must be enabled")
    if scale is None:
        factor_in = unit_factor(unit_in)
        factor_out = unit_factor(unit_out)
        scale = factor_in / factor_out
    if not math.isfinite(scale) or scale <= 0.0:
        raise ValueError("scale must be a positive, finite number")
    if not math.isfinite(weld_tol) or weld_tol < 0.0:
        raise ValueError("weld_tol must be a finite, non-negative number")
    if solids not in {"boundary", "faces", "skip"}:
        raise ValueError("solids must be 'boundary', 'faces' or 'skip'")
    if quad_split not in {"shortest", "fixed"}:
        raise ValueError("quad_split must be 'shortest' or 'fixed'")
    if shell_thickness is not None and (
        not math.isfinite(shell_thickness) or shell_thickness <= 0.0
    ):
        raise ValueError("shell_thickness must be a positive, finite number")

    source = Path(source)
    model = read_bdf(source)
    name_map = {int(key): str(value) for key, value in (names or {}).items()}
    parts = model.parts(
        scale=scale,
        quad_split=quad_split,
        solids=solids,
        weld_tol=weld_tol,
        names=name_map,
    )
    if not parts:
        raise NoGeometryError(
            f"{source.name}: no supported shell/solid geometry with valid nodes"
        )

    out_path = Path(out_dir) if out_dir is not None else source.parent
    out_path.mkdir(parents=True, exist_ok=True)
    stem = sanitize_name(source.stem, fallback="model")

    warnings = list(model.warnings)
    objects: list[ConvertedObject] = []
    used_names: set[str] = set()
    combined_triangles: list[tuple[float, ...]] = []
    extrusions = 0
    for part in parts:
        shell_count, solid_count = _part_element_counts(part)
        triangles = list(part.triangles)
        is_solid = False
        output_thickness: float | None = None

        if shell_solid and shell_count and solid_count:
            warnings.append(
                f"PID {part.pid}: mixes shell and volume elements; "
                "shells were not extruded."
            )
        elif shell_solid and shell_count:
            property_def = model.properties.get(part.pid)
            source_thickness = property_def.thickness if property_def else None
            if source_thickness is None or not math.isfinite(source_thickness) or source_thickness <= 0:
                source_thickness = shell_thickness
            if source_thickness is None:
                raise NastranError(
                    f"PID {part.pid}: PSHELL thickness is missing or zero; "
                    "enter a fallback shell thickness."
                )
            output_thickness = source_thickness * scale
            try:
                triangles = extrude_shell_triangles(part.triangles, output_thickness)
            except SolidError as exc:
                raise NastranError(
                    f"PID {part.pid}: cannot extrude shell elements: {exc}"
                ) from exc
            if not triangles:
                raise NastranError(f"PID {part.pid}: shell extrusion produced no triangles")
            is_solid = is_watertight(triangles)
            extrusions += 1
            if not is_solid:
                warnings.append(
                    f"PID {part.pid}: extruded shell is not watertight; "
                    "STEP may contain a surface instead of a solid."
                )
            elif is_watertight(part.triangles):
                warnings.append(
                    f"PID {part.pid}: shell mesh is closed; extrusion creates "
                    "an inner and an outer shell."
                )

        if solid_elements and shell_count and solid_count:
            warnings.append(
                f"PID {part.pid}: mixes shell and volume elements; "
                "the volume boundary was not marked as a solid."
            )
        elif solid_elements and solid_count:
            if is_watertight(part.triangles):
                is_solid = True
            else:
                warnings.append(
                    f"PID {part.pid}: volume boundary is not watertight; "
                    "STEP will contain a surface instead of a solid."
                )

        suffix = ""
        if part.pid in name_map:
            suffix = "_" + sanitize_name(part.name, fallback="object")
        base = f"{stem}_pid{part.pid}{suffix}"
        candidate = base
        counter = 2
        while candidate.lower() in used_names:
            candidate = f"{base}_{counter}"
            counter += 1
        used_names.add(candidate.lower())
        stl_path: Path | None = None
        if split:
            stl_path = write_stl(
                out_path / f"{candidate}.stl",
                triangles,
                name=part.name,
                ascii=ascii_stl,
            )
        obj = ConvertedObject(
            pid=part.pid,
            name=part.name,
            kind=part.kind,
            triangles=triangles,
            element_count=part.element_count,
            stl_path=stl_path,
            bounds=triangle_bounds(triangles),
            solid=is_solid,
            thickness=output_thickness,
        )
        objects.append(obj)
        combined_triangles.extend(triangles)

    combined_path: Path | None = None
    if combined:
        combined_path = write_stl(
            out_path / f"{stem}_all.stl",
            combined_triangles,
            name=f"{stem}_all",
            ascii=ascii_stl,
        )

    combined_step_path: Path | None = None
    step_warnings: list[str] = []
    if step:
        # FreeCAD writes STEP in millimetres.  STL coordinates use unit_out,
        # so scale them for the STEP writer when unit_out is not mm.
        step_scale = unit_factor(unit_out) * 1000.0
        temporary: tempfile.TemporaryDirectory[str] | None = None
        try:
            if split:
                step_items = [
                    StepItem(
                        stl_path=obj.stl_path,
                        step_path=obj.stl_path.with_suffix(".step"),
                        solid=obj.solid,
                        label=f"PID {obj.pid}",
                    )
                    for obj in objects
                    if obj.stl_path is not None
                ]
                combined_step_target = (
                    combined_path.with_suffix(".step") if combined_path is not None else None
                )
            else:
                # With split disabled there is no per-PID STL.  Build
                # temporary per-PID STLs so FreeCAD can create one solid per
                # PID and combine them properly.
                temporary = tempfile.TemporaryDirectory(
                    prefix="nastran2stl_step_shapes_"
                )
                temp_dir = Path(temporary.name)
                step_items = []
                for obj in objects:
                    temp_stl = temp_dir / f"pid{obj.pid}.stl"
                    write_stl(temp_stl, obj.triangles, name=obj.name, ascii=False)
                    step_items.append(
                        StepItem(
                            stl_path=temp_stl,
                            step_path=None,
                            solid=obj.solid,
                            label=f"PID {obj.pid}",
                        )
                    )
                combined_step_target = (
                    combined_path.with_suffix(".step") if combined_path is not None else None
                )

            try:
                step_result = write_step_files(
                    step_items,
                    combined_path=combined_step_target,
                    freecad_cmd=freecad_cmd,
                    scale=step_scale,
                )
            except StepError as exc:
                step_warnings.append(str(exc))
            else:
                step_warnings.extend(step_result.warnings)
                if split:
                    written_objects = [obj for obj in objects if obj.stl_path is not None]
                    for obj, entry in zip(written_objects, step_result.statuses):
                        step_text = entry.get("step")
                        if step_text:
                            candidate = Path(step_text)
                            if candidate.is_file():
                                obj.step_path = candidate
                combined_step_path = step_result.combined_path
        finally:
            if temporary is not None:
                temporary.cleanup()
        for message in step_warnings:
            warnings.append(f"STEP: {message}")

    overall_bounds = triangle_bounds(combined_triangles)
    stats = dict(model.stats)
    stats["objects_written"] = len(objects)
    stats["triangles_written"] = len(combined_triangles)
    stats["shell_extrusions"] = extrusions
    stats["solids_written"] = sum(1 for obj in objects if obj.solid)
    stats["step_files_written"] = sum(
        1 for obj in objects if obj.step_path is not None
    ) + (1 if combined_step_path is not None else 0)

    manifest_path: Path | None = None
    if manifest:
        manifest_path = out_path / f"{stem}_nastran2stl.json"
        _write_manifest(
            manifest_path,
            source=source,
            model=model,
            objects=objects,
            combined_path=combined_path,
            combined_step_path=combined_step_path,
            scale=scale,
            unit_in=unit_in,
            unit_out=unit_out,
            bounds=overall_bounds,
            warnings=warnings,
            step_warnings=step_warnings,
        )

    return ConversionResult(
        source=source,
        model=model,
        objects=objects,
        combined_path=combined_path,
        manifest_path=manifest_path,
        warnings=warnings,
        stats=stats,
        bounds=overall_bounds,
        scale=scale,
        unit_in=unit_in,
        unit_out=unit_out,
        combined_step_path=combined_step_path,
        step_warnings=step_warnings,
    )
