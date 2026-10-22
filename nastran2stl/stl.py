"""STL writers (binary and ASCII) using only the Python standard library."""

from __future__ import annotations

import math
import struct
from pathlib import Path
from typing import Iterable, Sequence

Triangle = Sequence[float]

_PACK = struct.Struct("<12fH")


def _as_flat(triangle: Sequence) -> Sequence[float]:
    """Accept either nine floats or three (x, y, z) points."""
    if len(triangle) == 9 and not isinstance(triangle[0], (list, tuple)):
        # Fast path: ``BdfModel.parts`` already produces flat 9-tuples.
        return triangle
    if len(triangle) == 3:
        return (
            float(triangle[0][0]), float(triangle[0][1]), float(triangle[0][2]),
            float(triangle[1][0]), float(triangle[1][1]), float(triangle[1][2]),
            float(triangle[2][0]), float(triangle[2][1]), float(triangle[2][2]),
        )
    raise ValueError(
        "a triangle must be nine numbers or three (x, y, z) points"
    )


def triangle_normal(triangle: Triangle) -> tuple[float, float, float]:
    flat = _as_flat(triangle)
    ux = flat[3] - flat[0]
    uy = flat[4] - flat[1]
    uz = flat[5] - flat[2]
    vx = flat[6] - flat[0]
    vy = flat[7] - flat[1]
    vz = flat[8] - flat[2]
    nx = uy * vz - uz * vy
    ny = uz * vx - ux * vz
    nz = ux * vy - uy * vx
    length = math.sqrt(nx * nx + ny * ny + nz * nz)
    if length <= 0.0 or not math.isfinite(length):
        return (0.0, 0.0, 0.0)
    return (nx / length, ny / length, nz / length)


def write_binary_stl(
    path: str | Path,
    triangles: Iterable[Triangle],
    *,
    name: str = "mesh",
) -> Path:
    """Write a binary STL.  Returns the written path."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        count = len(triangles)  # type: ignore[arg-type]
    except TypeError:
        triangles = list(triangles)  # type: ignore[assignment]
        count = len(triangles)  # type: ignore[arg-type]
    header_text = f"Nastran2STL {name}".encode("ascii", errors="replace")[:80]
    # Write in chunks so that very large meshes do not require a second
    # 50-bytes-per-triangle buffer in memory.
    chunk_triangles = 8192
    buffer = bytearray(50 * min(count, chunk_triangles) or 50)
    with path.open("wb") as handle:
        handle.write(header_text.ljust(80, b" "))
        handle.write(struct.pack("<I", count))
        offset = 0
        pack_into = _PACK.pack_into
        for triangle in triangles:  # type: ignore[union-attr]
            flat = _as_flat(triangle)
            nx, ny, nz = triangle_normal(flat)
            if offset + 50 > len(buffer):
                handle.write(buffer[:offset])
                offset = 0
            pack_into(
                buffer,
                offset,
                nx, ny, nz,
                flat[0], flat[1], flat[2],
                flat[3], flat[4], flat[5],
                flat[6], flat[7], flat[8],
                0,
            )
            offset += 50
        if offset:
            handle.write(buffer[:offset])
    return path


def write_ascii_stl(
    path: str | Path,
    triangles: Iterable[Triangle],
    *,
    name: str = "mesh",
) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    safe_name = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in name) or "mesh"
    with path.open("w", encoding="ascii", errors="replace", newline="\n") as handle:
        handle.write(f"solid {safe_name}\n")
        for triangle in triangles:
            flat = _as_flat(triangle)
            nx, ny, nz = triangle_normal(flat)
            handle.write(f"  facet normal {nx:.10g} {ny:.10g} {nz:.10g}\n")
            handle.write("    outer loop\n")
            for index in (0, 3, 6):
                handle.write(
                    f"      vertex {flat[index]:.10g} {flat[index + 1]:.10g} "
                    f"{flat[index + 2]:.10g}\n"
                )
            handle.write("    endloop\n")
            handle.write("  endfacet\n")
        handle.write(f"endsolid {safe_name}\n")
    return path


def write_stl(
    path: str | Path,
    triangles: Iterable[Triangle],
    *,
    name: str = "mesh",
    ascii: bool = False,
) -> Path:
    """Write triangles to STL, binary by default."""
    if ascii:
        return write_ascii_stl(path, triangles, name=name)
    return write_binary_stl(path, triangles, name=name)
