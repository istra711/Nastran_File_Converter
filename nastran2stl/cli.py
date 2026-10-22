"""Command line interface for nastran2stl."""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .bdf import NastranError, NoGeometryError, read_bdf
from .convert import ConversionResult, convert, load_names, unit_factor
from .viewer import ViewerError, ask_for_bdf, show_model


def _bounds_text(bounds) -> str:
    if not bounds:
        return "n/a"
    low, high = bounds
    return (
        "[" + ", ".join(f"{value:.6g}" for value in low) + "] .. ["
        + ", ".join(f"{value:.6g}" for value in high) + "]"
    )


def _print_result(result: ConversionResult) -> None:
    print(
        f"{result.source.name}: {len(result.objects)} object(s), "
        f"{result.triangle_count} triangles, unit {result.unit_in} -> "
        f"{result.unit_out} (scale {result.scale:g})"
    )
    for obj in result.objects:
        target = str(obj.stl_path) if obj.stl_path else "(not written)"
        flags = []
        if obj.solid:
            flags.append("solid")
        if obj.thickness is not None:
            flags.append(f"t={obj.thickness:g}")
        suffix = f" [{', '.join(flags)}]" if flags else ""
        print(
            f"  PID {obj.pid:<6d} {obj.kind:<8s} {obj.name!r}{suffix}: "
            f"{len(obj.triangles)} tri -> {target}"
        )
        if obj.bounds:
            print(f"    bounds {_bounds_text(obj.bounds)}")
        if obj.step_path:
            print(f"    step: {obj.step_path}")
    if result.combined_path:
        print(f"  combined: {result.combined_path}")
    if result.combined_step_path:
        print(f"  combined STEP: {result.combined_step_path}")
    if result.manifest_path:
        print(f"  manifest: {result.manifest_path}")
    print(f"  nodes: {result.stats.get('nodes_read', 0)}, "
          f"elements: {result.stats.get('elements_read', 0)}")
    if result.stats.get("shell_extrusions"):
        print(f"  extruded shell PIDs: {result.stats['shell_extrusions']}")
    if result.stats.get("step_files_written"):
        print(f"  STEP files: {result.stats['step_files_written']}")
    if result.model.unsupported:
        top = ", ".join(
            f"{name} ({count})"
            for name, count in result.model.unsupported.most_common(8)
        )
        print(f"  ignored/unsupported cards: {top}")
    if result.model.stats.get("solid_faces_internal"):
        print(
            "  solid faces removed as internal: "
            f"{result.model.stats['solid_faces_internal']}"
        )
    if result.warnings:
        print(f"  warnings: {len(result.warnings)}", file=sys.stderr)
        for warning in result.warnings[:20]:
            print(f"    {warning}", file=sys.stderr)
        if len(result.warnings) > 20:
            print(
                f"    ... {len(result.warnings) - 20} more warning(s)",
                file=sys.stderr,
            )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nastran2stl",
        description=(
            "Convert Nastran BDF shell/solid meshes to STL, one file per PID "
            "plus an optional combined file; optionally extrude shells or "
            "write faceted STEP solids through FreeCAD."
        ),
    )
    parser.add_argument(
        "inputs", nargs="*", metavar="BDF",
        help=(
            "input .bdf/.nas/.dat file(s); omit with --view or --view-only "
            "to choose one in a dialog"
        ),
    )
    parser.add_argument(
        "-o", "--out", metavar="DIR",
        help="output directory (default: directory of each input file)",
    )
    parser.add_argument(
        "--unit", default="mm", metavar="UNIT",
        help="unit of the Nastran coordinates (mm, cm, m, in, um, nm, ft; default: mm)",
    )
    parser.add_argument(
        "--out-unit", default="mm", metavar="UNIT",
        help="unit of the STL coordinates (default: mm)",
    )
    parser.add_argument(
        "--scale", type=float, default=None,
        help="explicit scale factor, overrides --unit/--out-unit",
    )
    parser.add_argument(
        "--no-split", action="store_true",
        help="do not write one STL per PID",
    )
    parser.add_argument(
        "--no-combined", action="store_true",
        help="do not write the combined STL",
    )
    parser.add_argument(
        "--ascii", action="store_true",
        help="write ASCII STL instead of binary STL",
    )
    parser.add_argument(
        "--solids", choices=("boundary", "faces", "skip"), default="boundary",
        help=(
            "volume elements: boundary = outer skin per PID (default), "
            "faces = every element face, skip = ignore"
        ),
    )
    parser.add_argument(
        "--quad-split", choices=("shortest", "fixed"), default="shortest",
        help="triangulate quads along the shortest diagonal (default) or fixed 1-3",
    )
    parser.add_argument(
        "--weld-tol", type=float, default=0.0, metavar="TOL",
        help=(
            "merge coincident solid faces by rounding coordinates to TOL "
            "(source units); 0 = only shared node ids (default)"
        ),
    )
    parser.add_argument(
        "--names", metavar="JSON",
        help="JSON file mapping PID -> object name, e.g. {\"100\": \"enclosure\"}",
    )
    parser.add_argument(
        "--no-manifest", action="store_true",
        help="do not write the <stem>_nastran2stl.json manifest",
    )
    parser.add_argument(
        "--shell-solid", action="store_true",
        help=(
            "extrude shells by their PSHELL thickness and write closed "
            "thin-solid STL meshes"
        ),
    )
    parser.add_argument(
        "--shell-thickness", type=float, metavar="T",
        help=(
            "fallback shell thickness in input units when PSHELL T is "
            "missing or zero (used with --shell-solid)"
        ),
    )
    parser.add_argument(
        "--solid-elements", action="store_true",
        help=(
            "mark watertight volume-element boundaries as solids for STEP; "
            "open boundaries remain surfaces"
        ),
    )
    parser.add_argument(
        "--step", action="store_true",
        help=(
            "also write faceted STEP files through FreeCADCmd (auto-detected "
            "or set FREECAD_CMD / --freecad)"
        ),
    )
    parser.add_argument(
        "--freecad", metavar="PATH",
        help="path to FreeCADCmd.exe for --step",
    )
    parser.add_argument(
        "--view", action="store_true",
        help="open the 3D viewer after writing the STL files",
    )
    parser.add_argument(
        "--view-only", action="store_true",
        help="open the 3D viewer without writing any files",
    )
    parser.add_argument(
        "--wireframe", action="store_true",
        help="start the 3D viewer in wireframe mode",
    )
    parser.add_argument(
        "-q", "--quiet", action="store_true",
        help="suppress the per-file summary",
    )
    parser.add_argument("--version", action="version", version=__version__)
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        names = load_names(args.names) if args.names else {}
    except NastranError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.view and args.view_only:
        parser.error("--view and --view-only are mutually exclusive")

    if not args.inputs:
        if not (args.view or args.view_only):
            parser.error(
                "a BDF file is required; use --view-only without a file to "
                "open the file dialog"
            )
        try:
            selected = ask_for_bdf()
        except ViewerError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        if selected is None:
            return 0
        args.inputs = [str(selected)]

    failures = 0
    empty = 0
    for source in args.inputs:
        if args.view_only:
            try:
                model = read_bdf(source)
                scale = (
                    args.scale
                    if args.scale is not None
                    else unit_factor(args.unit) / unit_factor(args.out_unit)
                )
                parts = model.parts(
                    scale=scale,
                    quad_split=args.quad_split,
                    solids=args.solids,
                    weld_tol=args.weld_tol,
                    names=names,
                )
                if not parts or not any(part.triangles for part in parts):
                    raise NoGeometryError(
                        f"{model.source.name}: no supported shell/solid geometry "
                        "with valid nodes"
                    )
                if not args.quiet:
                    triangles = sum(len(part.triangles) for part in parts)
                    print(
                        f"{model.source.name}: {len(parts)} object(s), "
                        f"{triangles} triangles — opening 3D viewer"
                    )
                show_model(
                    model,
                    parts,
                    title=model.source.name,
                    wireframe=args.wireframe,
                )
            except NoGeometryError as exc:
                print(f"error: {exc}", file=sys.stderr)
                empty += 1
                continue
            except (NastranError, ViewerError, ValueError, OSError) as exc:
                print(f"error: {exc}", file=sys.stderr)
                failures += 1
                continue
            continue

        try:
            result = convert(
                source,
                args.out,
                unit_in=args.unit,
                unit_out=args.out_unit,
                scale=args.scale,
                split=not args.no_split,
                combined=not args.no_combined,
                ascii_stl=args.ascii,
                solids=args.solids,
                quad_split=args.quad_split,
                weld_tol=args.weld_tol,
                names=names,
                manifest=not args.no_manifest,
                shell_solid=args.shell_solid,
                shell_thickness=args.shell_thickness,
                solid_elements=args.solid_elements,
                step=args.step,
                freecad_cmd=args.freecad,
            )
        except NoGeometryError as exc:
            print(f"error: {exc}", file=sys.stderr)
            empty += 1
            continue
        except (NastranError, ValueError, OSError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            failures += 1
            continue
        if not args.quiet:
            _print_result(result)
        if args.view:
            try:
                show_model(
                    result.model,
                    result.objects,
                    title=result.source.name,
                    wireframe=args.wireframe,
                )
            except ViewerError as exc:
                print(f"error: {exc}", file=sys.stderr)
                failures += 1
    if failures:
        return 1
    if empty and empty == len(args.inputs):
        return 2
    return 0
