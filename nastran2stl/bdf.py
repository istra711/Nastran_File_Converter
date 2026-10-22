"""Read Nastran BDF files and turn shell/solid elements into triangles.

The reader is deliberately dependency-free (Python standard library only) so
it can run stand-alone or be dropped into the FreeCAD/openEMS application
later.  It supports the three Nastran field formats, continuation lines,
``INCLUDE`` files and the most common shell and solid elements.

Public entry points:

``read_bdf(path)``
    Parse a BDF file and return a :class:`BdfModel`.

``BdfModel.parts(...)``
    Convert the model into one :class:`MeshPart` per property ID (PID).
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Sequence

# ---------------------------------------------------------------------------
# Card / field tables
# ---------------------------------------------------------------------------

#: Cards used to tell a new card apart from a continuation line with an
#: alphabetic continuation ID.  The list does not have to be complete; an
#: unknown card name of three or more characters is also treated as a new card.
KNOWN_CARDS = {
    "GRID", "GRDSET", "CTRIA3", "CTRIA6", "CQUAD4", "CQUAD8", "CQUAD9",
    "CTETRA", "CHEXA", "CPENTA", "CPYRAM", "PSHELL", "PSOLID", "PCOMP",
    "PCOMPG", "PBAR", "PBARL", "PBEAM", "PBEAML", "PROD", "PSHEAR",
    "PSPRING", "PDAMP", "PMASS", "PLPLANE", "PPLANE", "PGAP", "PBUSH",
    "PBUSH1D", "PELAS", "PVISC", "MAT1", "MAT2", "MAT8", "MAT9", "MAT10",
    "CORD1R", "CORD1C", "CORD1S", "CORD2R", "CORD2C", "CORD2S",
    "RBE1", "RBE2", "RBE3", "RBAR", "CBAR", "CBEAM", "CROD", "CONROD",
    "CONM2", "SPC", "SPC1", "SPCD", "LOAD", "FORCE", "MOMENT", "PLOAD4",
    "SET", "SET1", "PARAM", "EIGRL", "EIGB", "SUBCASE", "TITLE", "ECHO",
    "BEGIN", "ENDDATA", "INCLUDE", "MPC", "TEMPERATURE", "DISP",
}

#: Non-geometric cards that are expected in a BDF and intentionally ignored.
IGNORED_CARDS = {
    "BEGIN", "MAT1", "MAT2", "MAT8", "MAT9", "MAT10", "MATT1", "MATT2",
    "MATT8", "MATT9", "TABLEM1", "TABLEM2", "TABLEM3", "TABLEM4",
    "SPC", "SPC1", "SPCD", "LOAD", "FORCE", "MOMENT", "PLOAD4", "PLOAD",
    "RBE1", "RBE2", "RBE3", "RBAR", "CBAR", "CBEAM", "CROD", "CONROD",
    "CONM2", "SET", "SET1", "PARAM", "EIGRL", "EIGB", "SUBCASE", "TITLE",
    "ECHO", "MPC", "TEMPERATURE", "DISP", "OLOAD", "DLOAD", "TSTEP",
    "FREQ", "FREQ1", "FREQ2", "RANDPS", "TABRND1", "TABDMP1", "NLPCI",
    "NLPARM", "DESSUB", "DCONSTR", "DRESP1", "DESOBJ", "ANALYSIS",
    "ENDDATA", "CASE", "METHOD", "SORT", "DMAP", "ASSIGN", "GEOMCHECK",
}

PROPERTY_CARDS = {
    "PSHELL", "PSOLID", "PCOMP", "PCOMPG", "PBAR", "PBARL", "PBEAM",
    "PBEAML", "PROD", "PSHEAR", "PSPRING", "PDAMP", "PMASS", "PLPLANE",
    "PPLANE", "PGAP", "PBUSH", "PBUSH1D", "PELAS", "PVISC",
}

#: Shell cards and their number of *corner* nodes.  Higher-order nodes are
#: ignored (the geometry is linearised), which is fine for an STL surface.
SHELL_TRI = {"CTRIA3": 3, "CTRIA6": 3}
SHELL_QUAD = {"CQUAD4": 4, "CQUAD8": 4, "CQUAD9": 4}

#: Solid cards and their number of corner nodes.
SOLID_CORNERS = {"CTETRA": 4, "CHEXA": 8, "CPENTA": 6, "CPYRAM": 5}

#: Local face index tables (corner nodes only).  Faces are oriented later
#: against the element centroid, so the order here only has to be a valid
#: polygon and must not repeat nodes.
SOLID_FACES = {
    "CTETRA": ((0, 2, 1), (0, 1, 3), (1, 2, 3), (0, 3, 2)),
    "CHEXA": (
        (0, 3, 2, 1), (4, 5, 6, 7),
        (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7),
    ),
    "CPENTA": ((0, 2, 1), (3, 4, 5), (0, 1, 4, 3), (1, 2, 5, 4), (2, 0, 3, 5)),
    "CPYRAM": ((0, 3, 2, 1), (0, 1, 4), (1, 2, 4), (2, 3, 4), (3, 0, 4)),
}

CARD_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
IMPLICIT_EXP_RE = re.compile(r"^([+-]?(?:\d+\.\d*|\.\d+|\d+))([+-]\d+)$")

UNIT_TO_METRES = {
    "m": 1.0,
    "meter": 1.0,
    "metre": 1.0,
    "cm": 1e-2,
    "mm": 1e-3,
    "millimeter": 1e-3,
    "millimetre": 1e-3,
    "um": 1e-6,
    "µm": 1e-6,
    "micron": 1e-6,
    "nm": 1e-9,
    "in": 0.0254,
    "inch": 0.0254,
    "ft": 0.3048,
    "mil": 2.54e-5,
}


class NastranError(Exception):
    """Raised when a BDF file cannot be read."""


class NoGeometryError(NastranError):
    """Raised when a BDF file contains no usable surface geometry."""


# ---------------------------------------------------------------------------
# Card tokenizer
# ---------------------------------------------------------------------------


@dataclass
class Card:
    name: str
    fields: list[str]
    source: Path
    lineno: int


class Warnings:
    """Collects unique warnings plus repetition counts."""

    def __init__(self, limit: int = 200) -> None:
        self.messages: list[str] = []
        self.counts: Counter[object] = Counter()
        self._seen: set[object] = set()
        self.limit = limit

    def once(self, key: object, message: str) -> None:
        self.counts[key] += 1
        if key in self._seen:
            return
        self._seen.add(key)
        if len(self.messages) < self.limit:
            self.messages.append(message)
        elif len(self.messages) == self.limit:
            self.messages.append(
                f"further warnings suppressed after {self.limit} entries"
            )


def parse_float(token: str, default: float | None = None) -> float | None:
    """Parse a Nastran numeric field, including implicit exponents (1.2-3)."""
    text = token.strip().upper()
    if not text:
        return default
    text = text.replace("D", "E")
    try:
        value = float(text)
    except ValueError:
        value = None
    if value is not None:
        return value if math.isfinite(value) else default
    match = IMPLICIT_EXP_RE.match(text)
    if match:
        try:
            value = float(f"{match.group(1)}E{match.group(2)}")
        except ValueError:
            return default
        return value if math.isfinite(value) else default
    return default


def parse_int(token: str, default: int = 0) -> int:
    text = token.strip()
    if not text:
        return default
    try:
        return int(text)
    except ValueError:
        value = parse_float(text)
        if value is None:
            return default
        try:
            return int(value)
        except (ValueError, OverflowError):
            return default


def _split_free(line: str) -> list[str]:
    fields = [part.strip() for part in line.split(",")]
    # A trailing comma is a separator, not an empty field.  Keeping it would
    # shift all values appended from a continuation line by one position.
    if line.rstrip().endswith(",") and fields and fields[-1] == "":
        fields.pop()
    return fields


def _fixed_fields(line: str, width: int, count: int) -> list[str]:
    start = 8
    return [
        line[start + i * width:start + (i + 1) * width].strip()
        for i in range(count)
    ]


def _is_continuation(line: str, fmt: str) -> bool:
    head = line[:8]
    stripped = head.strip()
    if fmt == "free":
        text = line.lstrip()
        return text.startswith("+") or text.startswith(",")
    if not stripped:
        return True
    if line[0] in "+*":
        return True
    # A card name ending in * starts a new large-field card, regardless of the
    # format of the previous card (BDF files may mix small and large fields).
    if stripped.endswith("*"):
        return False
    upper = stripped.upper()
    if upper in KNOWN_CARDS:
        return False
    # Continuation IDs are usually '+' or numeric; a short alphabetic token is
    # far more likely a continuation ID than a new card.
    if len(upper) >= 3 and CARD_NAME_RE.match(upper):
        return False
    return True


def _continuation_fields(line: str, fmt: str) -> list[str]:
    if fmt == "free":
        text = line.strip().replace("\t", ",")
        if text.startswith("+"):
            text = text[1:]
        fields = _split_free(text)
        if fields and fields[0] == "":
            fields = fields[1:]
        return fields
    if fmt == "large":
        return _fixed_fields(line, 16, 4)
    return _fixed_fields(line, 8, 9)


def _start_card(line: str) -> tuple[str, str, list[str]]:
    # Tab-separated free field is not standard but common in exported files.
    if "\t" in line and "," not in line:
        line = line.replace("\t", ",")
    if "," in line:
        fields = _split_free(line)
        name = fields[0].strip().upper() if fields else ""
        return "free", name, fields[1:]
    head = line[:8].strip()
    if head.endswith("*"):
        return "large", head[:-1].upper(), _fixed_fields(line, 16, 4)
    return "small", head.upper(), _fixed_fields(line, 8, 9)


def _trim_trailing(fields: list[str]) -> list[str]:
    while fields and fields[-1] == "":
        fields.pop()
    return fields


def _iter_cards(
    lines: Iterable[tuple[str, Path, int]], warnings: Warnings
) -> Iterator[Card]:
    current: tuple[str, str, list[str], Path, int] | None = None
    for line, source, lineno in lines:
        if current is not None and _is_continuation(line, current[0]):
            current[2].extend(_continuation_fields(line, current[0]))
            continue
        if current is not None:
            yield Card(current[1], _trim_trailing(current[2]), current[3], current[4])
        fmt, name, fields = _start_card(line)
        if not name:
            warnings.once(
                ("blank_card", source.name),
                f"{source.name}:{lineno}: line without a card name ignored",
            )
            current = None
            continue
        current = (fmt, name, list(fields), source, lineno)
    if current is not None:
        yield Card(current[1], _trim_trailing(current[2]), current[3], current[4])


def _include_target(line: str) -> str | None:
    text = line.lstrip()
    match = re.match(r"(?i)^INCLUDE\b(.*)$", text)
    if not match:
        return None
    rest = match.group(1).strip().lstrip("=, \t").strip()
    if not rest:
        return None
    if rest[0] in "'\"":
        end = rest.find(rest[0], 1)
        if end > 1:
            return rest[1:end]
    token = re.split(r"[\s,]+", rest, maxsplit=1)[0]
    return token or None


def _find_case_insensitive(folder: Path, name: str) -> Path | None:
    try:
        target = name.replace("\\", "/").lower()
        for entry in folder.iterdir():
            if entry.name.lower() == target:
                return entry
    except OSError:
        return None
    return None


def _iter_source(
    path: Path,
    *,
    depth: int,
    seen: set[str],
    warnings: Warnings,
    stats: Counter,
) -> Iterator[tuple[str, Path, int]]:
    path = Path(path)
    if depth > 16:
        warnings.once("include_depth", "INCLUDE nesting deeper than 16 ignored")
        return
    key = str(path.resolve()).lower()
    if key in seen:
        warnings.once(
            ("include_cycle", key),
            f"INCLUDE cycle or repeated file skipped: {path.name}",
        )
        return
    seen.add(key)
    try:
        handle = path.open("r", encoding="utf-8-sig", errors="replace")
    except OSError as exc:
        raise NastranError(f"cannot read {path}: {exc}") from exc
    with handle:
        for lineno, raw in enumerate(handle, 1):
            line = raw.rstrip("\r\n")
            text = line.lstrip()
            if not text or text.startswith("$"):
                continue
            if re.match(r"(?i)^BEGIN\s+BULK\b", text):
                continue
            if re.match(r"(?i)^ENDDATA\b", text):
                return
            if re.match(r"(?i)^INCLUDE\b", text):
                target_name = _include_target(line)
                if not target_name:
                    warnings.once(
                        ("include_empty", path.name, lineno),
                        f"{path.name}:{lineno}: INCLUDE without a file name",
                    )
                    continue
                target = Path(target_name).expanduser()
                if not target.is_absolute():
                    target = path.parent / target
                if not target.exists():
                    target = _find_case_insensitive(path.parent, target_name) or target
                if not target.exists():
                    warnings.once(
                        ("include_missing", str(target).lower()),
                        f"INCLUDE not found: {target_name} (from {path.name}:{lineno})",
                    )
                    stats["includes_missing"] += 1
                    continue
                stats["includes"] += 1
                yield from _iter_source(
                    target,
                    depth=depth + 1,
                    seen=seen,
                    warnings=warnings,
                    stats=stats,
                )
                continue
            yield line, path, lineno


# ---------------------------------------------------------------------------
# Coordinate systems
# ---------------------------------------------------------------------------


@dataclass
class CoordSystem:
    cid: int
    kind: str  # R (rectangular), C (cylindrical), S (spherical)
    rid: int
    a: tuple[float, float, float]
    b: tuple[float, float, float]
    c: tuple[float, float, float]


def _sub(a: Sequence[float], b: Sequence[float]) -> tuple[float, float, float]:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _dot(a: Sequence[float], b: Sequence[float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: Sequence[float], b: Sequence[float]) -> tuple[float, float, float]:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _norm(a: Sequence[float]) -> float:
    return math.sqrt(_dot(a, a))


def _scale(a: Sequence[float], factor: float) -> tuple[float, float, float]:
    return (a[0] * factor, a[1] * factor, a[2] * factor)


def _unit(a: Sequence[float]) -> tuple[float, float, float] | None:
    length = _norm(a)
    if length <= 0.0 or not math.isfinite(length):
        return None
    return _scale(a, 1.0 / length)


def _cs_axes(
    a: Sequence[float], b: Sequence[float], c: Sequence[float]
) -> tuple[tuple[float, float, float], ...] | None:
    z_axis = _unit(_sub(b, a))
    if z_axis is None:
        return None
    x_raw = _sub(c, a)
    x_raw = _sub(x_raw, _scale(z_axis, _dot(x_raw, z_axis)))
    x_axis = _unit(x_raw)
    if x_axis is None:
        return None
    y_axis = _cross(z_axis, x_axis)
    return x_axis, y_axis, z_axis


def _resolve_cs(
    cid: int,
    systems: dict[int, CoordSystem],
    cache: dict[int, tuple[tuple[float, float, float], tuple[tuple[float, float, float], ...]]],
    stack: set[int],
    warnings: Warnings,
) -> tuple[tuple[float, float, float], tuple[tuple[float, float, float], ...]] | None:
    if cid in cache:
        return cache[cid]
    system = systems.get(cid)
    if system is None:
        warnings.once(("cs_missing", cid), f"coordinate system {cid} not defined")
        return None
    if cid in stack:
        warnings.once(("cs_cycle", cid), f"coordinate system cycle at CID {cid}")
        return None
    stack.add(cid)
    a, b, c = system.a, system.b, system.c
    if system.rid:
        parent = _resolve_cs(system.rid, systems, cache, stack, warnings)
        if parent is None:
            stack.discard(cid)
            return None
        origin, axes = parent

        def transform(point: Sequence[float]) -> tuple[float, float, float]:
            return (
                origin[0] + axes[0][0] * point[0] + axes[1][0] * point[1] + axes[2][0] * point[2],
                origin[1] + axes[0][1] * point[0] + axes[1][1] * point[1] + axes[2][1] * point[2],
                origin[2] + axes[0][2] * point[0] + axes[1][2] * point[1] + axes[2][2] * point[2],
            )

        a, b, c = transform(a), transform(b), transform(c)
    axes = _cs_axes(a, b, c)
    stack.discard(cid)
    if axes is None:
        warnings.once(
            ("cs_degenerate", cid),
            f"coordinate system {cid} is degenerate (A, B, C collinear)",
        )
        return None
    result = (a, axes)
    cache[cid] = result
    return result


def _apply_cs(
    system: CoordSystem,
    resolved: tuple[tuple[float, float, float], tuple[tuple[float, float, float], ...]],
    xyz: Sequence[float],
) -> tuple[float, float, float]:
    origin, axes = resolved
    x, y, z = xyz
    if system.kind == "C":
        angle = math.radians(y)
        local = (x * math.cos(angle), x * math.sin(angle), z)
    elif system.kind == "S":
        theta = math.radians(y)
        phi = math.radians(z)
        local = (
            x * math.sin(phi) * math.cos(theta),
            x * math.sin(phi) * math.sin(theta),
            x * math.cos(phi),
        )
    else:
        local = (x, y, z)
    return (
        origin[0] + axes[0][0] * local[0] + axes[1][0] * local[1] + axes[2][0] * local[2],
        origin[1] + axes[0][1] * local[0] + axes[1][1] * local[1] + axes[2][1] * local[2],
        origin[2] + axes[0][2] * local[0] + axes[1][2] * local[1] + axes[2][2] * local[2],
    )


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


@dataclass
class Element:
    eid: int
    pid: int
    kind: str
    nodes: tuple[int, ...]


@dataclass
class Property:
    pid: int
    kind: str
    fields: tuple[str, ...]

    @property
    def thickness(self) -> float | None:
        if self.kind == "PSHELL" and len(self.fields) >= 3:
            return parse_float(self.fields[2])
        return None


@dataclass
class MeshPart:
    """Triangles belonging to one property ID."""

    pid: int
    name: str
    kind: str
    triangles: list[tuple[float, ...]]
    element_count: int
    shell_count: int = 0
    solid_count: int = 0

    @property
    def is_shell(self) -> bool:
        """True when the PID contains shell elements only."""
        if self.solid_count:
            return False
        return self.shell_count > 0 or self.kind not in {"PSOLID"}

    @property
    def is_solid(self) -> bool:
        """True when the PID contains volume elements only."""
        if self.shell_count:
            return False
        return self.solid_count > 0 or self.kind == "PSOLID"

    def bounds(
        self,
    ) -> tuple[tuple[float, float, float], tuple[float, float, float]] | None:
        return triangle_bounds(self.triangles)


@dataclass
class BdfModel:
    source: Path
    nodes: dict[int, tuple[float, float, float]]
    elements: list[Element]
    properties: dict[int, Property]
    coordsystems: dict[int, CoordSystem]
    warnings: list[str]
    stats: Counter
    unsupported: Counter

    def _node_coordinates(self, scale: float) -> dict[int, tuple[float, float, float]]:
        used: set[int] = set()
        for element in self.elements:
            count = (
                SHELL_TRI.get(element.kind)
                or SHELL_QUAD.get(element.kind)
                or SOLID_CORNERS.get(element.kind)
            )
            if count:
                used.update(element.nodes[:count])
        return {
            nid: (
                self.nodes[nid][0] * scale,
                self.nodes[nid][1] * scale,
                self.nodes[nid][2] * scale,
            )
            for nid in used
            if nid in self.nodes
        }

    def parts(
        self,
        *,
        scale: float = 1.0,
        quad_split: str = "shortest",
        solids: str = "boundary",
        weld_tol: float = 0.0,
        names: dict[int, str] | None = None,
    ) -> list[MeshPart]:
        """Return triangles grouped by PID.

        ``solids`` is ``"boundary"`` (outer skin per PID, shared internal faces
        removed), ``"faces"`` (every element face) or ``"skip"``.
        """
        if not math.isfinite(scale) or scale <= 0.0:
            raise ValueError("scale must be a positive, finite number")
        if not math.isfinite(weld_tol) or weld_tol < 0.0:
            raise ValueError("weld_tol must be a finite, non-negative number")
        if quad_split not in {"shortest", "fixed"}:
            raise ValueError("quad_split must be 'shortest' or 'fixed'")
        if solids not in {"boundary", "faces", "skip"}:
            raise ValueError("solids must be 'boundary', 'faces' or 'skip'")
        names = {int(key): str(value) for key, value in (names or {}).items()}

        # These counters describe the triangulation of the *current* call.
        self.stats["elements_missing_nodes"] = 0
        self.stats["elements_incomplete"] = 0
        self.stats["triangles_degenerate"] = 0
        self.stats["solid_faces_internal"] = 0

        coords = self._node_coordinates(scale)
        groups: dict[int, list[Element]] = {}
        for element in self.elements:
            if element.kind in SOLID_CORNERS and solids == "skip":
                continue
            if element.kind in SHELL_TRI or element.kind in SHELL_QUAD or element.kind in SOLID_CORNERS:
                groups.setdefault(element.pid, []).append(element)

        parts: list[MeshPart] = []
        for pid in sorted(groups):
            group = groups[pid]
            triangles: list[tuple[float, ...]] = []
            solid_faces: list[tuple[str, tuple[tuple[float, float, float], ...], tuple[int, ...]]] = []
            element_count = 0
            shell_count = 0
            solid_count = 0
            for element in group:
                corner_count = (
                    SHELL_TRI.get(element.kind)
                    or SHELL_QUAD.get(element.kind)
                    or SOLID_CORNERS.get(element.kind)
                )
                if corner_count is None:
                    continue
                node_ids = element.nodes[:corner_count]
                if len(node_ids) < corner_count:
                    self.stats["elements_incomplete"] += 1
                    continue
                points = tuple(coords.get(nid) for nid in node_ids)
                if any(point is None for point in points):
                    self.stats["elements_missing_nodes"] += 1
                    continue
                points = tuple(point for point in points if point is not None)
                element_count += 1
                if element.kind in SOLID_CORNERS:
                    solid_count += 1
                    if solids == "boundary":
                        solid_faces.append((element.kind, points, node_ids))
                    else:
                        for face in SOLID_FACES[element.kind]:
                            polygon = [points[index] for index in face]
                            triangles.extend(_triangulate(polygon, quad_split, self.stats))
                elif element.kind in SHELL_TRI:
                    shell_count += 1
                    triangles.extend(
                        _triangulate([points[0], points[1], points[2]], "shortest", self.stats)
                    )
                else:
                    shell_count += 1
                    triangles.extend(
                        _triangulate(
                            [points[0], points[1], points[2], points[3]],
                            quad_split,
                            self.stats,
                        )
                    )
            if solid_faces:
                triangles.extend(
                    _boundary_triangles(
                        solid_faces, quad_split, weld_tol * scale, self.stats
                    )
                )
            if not triangles:
                continue
            property_def = self.properties.get(pid)
            kind = property_def.kind if property_def else "UNKNOWN"
            default_name = f"{kind} {pid}" if pid else "unassigned"
            parts.append(
                MeshPart(
                    pid=pid,
                    name=names.get(pid, default_name),
                    kind=kind,
                    triangles=triangles,
                    element_count=element_count,
                    shell_count=shell_count,
                    solid_count=solid_count,
                )
            )

        missing = int(self.stats["elements_missing_nodes"])
        if missing:
            self._warn(
                f"{missing} element(s) reference undefined GRID ids and were skipped"
            )
        incomplete = int(self.stats["elements_incomplete"])
        if incomplete:
            self._warn(
                f"{incomplete} element(s) have too few nodes and were skipped"
            )
        degenerate = int(self.stats["triangles_degenerate"])
        if degenerate:
            self._warn(f"{degenerate} degenerate triangle(s) skipped")
        return parts

    def _warn(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)


def triangle_bounds(
    triangles: Sequence[Sequence[float]],
) -> tuple[tuple[float, float, float], tuple[float, float, float]] | None:
    if not triangles:
        return None
    first = triangles[0]
    lo = [first[0], first[1], first[2]]
    hi = list(lo)
    for triangle in triangles:
        for index in range(0, 9, 3):
            for axis in range(3):
                value = triangle[index + axis]
                if value < lo[axis]:
                    lo[axis] = value
                if value > hi[axis]:
                    hi[axis] = value
    return (lo[0], lo[1], lo[2]), (hi[0], hi[1], hi[2])


def _triangulate(
    polygon: Sequence[Sequence[float]], quad_split: str, stats: Counter
) -> list[tuple[float, ...]]:
    if len(polygon) == 3:
        return _make_triangle(polygon[0], polygon[1], polygon[2], stats)
    if len(polygon) != 4:
        return []
    p0, p1, p2, p3 = polygon
    if quad_split == "shortest":
        d02 = _dot(_sub(p2, p0), _sub(p2, p0))
        d13 = _dot(_sub(p3, p1), _sub(p3, p1))
        if d13 < d02:
            return (
                _make_triangle(p0, p1, p3, stats)
                + _make_triangle(p1, p2, p3, stats)
            )
    return _make_triangle(p0, p1, p2, stats) + _make_triangle(p0, p2, p3, stats)


def _make_triangle(
    a: Sequence[float], b: Sequence[float], c: Sequence[float], stats: Counter
) -> list[tuple[float, ...]]:
    u = _sub(b, a)
    v = _sub(c, a)
    w = _sub(c, b)
    normal = _cross(u, v)
    area_squared = _dot(normal, normal)
    max_edge_squared = max(_dot(u, u), _dot(v, v), _dot(w, w))
    # Scale-independent degeneracy test: reject collinear / zero-area triangles
    # without rejecting legitimately tiny geometry in metres or nanometres.
    if max_edge_squared <= 0.0 or area_squared <= 1e-24 * max_edge_squared * max_edge_squared:
        stats["triangles_degenerate"] += 1
        return []
    return [
        (
            float(a[0]), float(a[1]), float(a[2]),
            float(b[0]), float(b[1]), float(b[2]),
            float(c[0]), float(c[1]), float(c[2]),
        )
    ]


def _polygon_normal(polygon: Sequence[Sequence[float]]) -> tuple[float, float, float]:
    """Newell normal (robust for non-planar quads)."""
    nx = ny = nz = 0.0
    count = len(polygon)
    for index, point in enumerate(polygon):
        nxt = polygon[(index + 1) % count]
        nx += (point[1] - nxt[1]) * (point[2] + nxt[2])
        ny += (point[2] - nxt[2]) * (point[0] + nxt[0])
        nz += (point[0] - nxt[0]) * (point[1] + nxt[1])
    return nx, ny, nz


def _centroid(points: Sequence[Sequence[float]]) -> tuple[float, float, float]:
    count = len(points)
    return (
        sum(point[0] for point in points) / count,
        sum(point[1] for point in points) / count,
        sum(point[2] for point in points) / count,
    )


def _boundary_triangles(
    solid_faces: Sequence[
        tuple[str, tuple[tuple[float, float, float], ...], tuple[int, ...]]
    ],
    quad_split: str,
    weld_tol: float,
    stats: Counter,
) -> list[tuple[float, ...]]:
    faces: dict[tuple, list[list[tuple[float, float, float]]]] = {}
    for kind, points, node_ids in solid_faces:
        element_center = _centroid(points)
        for face in SOLID_FACES[kind]:
            polygon = [points[index] for index in face]
            normal = _polygon_normal(polygon)
            center = _centroid(polygon)
            if _dot(normal, _sub(center, element_center)) < 0.0:
                polygon.reverse()
            if weld_tol > 0.0:
                key: tuple = tuple(
                    sorted(
                        (
                            round(point[0] / weld_tol),
                            round(point[1] / weld_tol),
                            round(point[2] / weld_tol),
                        )
                        for point in polygon
                    )
                )
            else:
                key = tuple(sorted(node_ids[index] for index in face))
            faces.setdefault(key, []).append(polygon)

    triangles: list[tuple[float, ...]] = []
    for polygons in faces.values():
        if len(polygons) != 1:
            stats["solid_faces_internal"] += len(polygons)
            continue
        triangles.extend(_triangulate(polygons[0], quad_split, stats))
    return triangles


# ---------------------------------------------------------------------------
# BDF parser
# ---------------------------------------------------------------------------


def _coord_system_from_card(card: Card, warnings: Warnings) -> CoordSystem | None:
    fields = card.fields
    kind = card.name[-1]  # CORD2R -> R
    if len(fields) < 11:
        warnings.once(
            ("cs_fields", card.name, card.source.name),
            f"{card.source.name}:{card.lineno}: {card.name} with too few fields ignored",
        )
        return None
    cid = parse_int(fields[0])
    rid = parse_int(fields[1])
    if cid <= 0:
        return None

    def point(offset: int) -> tuple[float, float, float]:
        return (
            parse_float(fields[offset], 0.0) or 0.0,
            parse_float(fields[offset + 1], 0.0) or 0.0,
            parse_float(fields[offset + 2], 0.0) or 0.0,
        )

    return CoordSystem(cid=cid, kind=kind, rid=rid, a=point(2), b=point(5), c=point(8))


def read_bdf(path: str | Path) -> BdfModel:
    """Parse a BDF file, including INCLUDE files."""
    source = Path(path)
    if not source.exists():
        raise NastranError(f"file not found: {source}")
    warnings = Warnings()
    stats: Counter = Counter()
    unsupported: Counter = Counter()
    raw_nodes: dict[int, tuple[tuple[float, float, float], int]] = {}
    elements: list[Element] = []
    properties: dict[int, Property] = {}
    systems: dict[int, CoordSystem] = {}

    lines = _iter_source(
        source, depth=0, seen=set(), warnings=warnings, stats=stats
    )
    for card in _iter_cards(lines, warnings):
        name = card.name
        fields = card.fields
        if name == "GRID":
            stats["grid_cards"] += 1
            if len(fields) < 5:
                warnings.once(
                    ("grid_fields", card.source.name),
                    f"{card.source.name}:{card.lineno}: GRID with too few fields ignored",
                )
                stats["grids_invalid"] += 1
                continue
            nid = parse_int(fields[0])
            cp = parse_int(fields[1]) if len(fields) > 1 else 0
            xyz = tuple(parse_float(fields[index]) for index in (2, 3, 4))
            if nid <= 0 or any(value is None for value in xyz):
                warnings.once(
                    ("grid_values", card.source.name),
                    f"{card.source.name}:{card.lineno}: invalid GRID values ignored",
                )
                stats["grids_invalid"] += 1
                continue
            if nid in raw_nodes:
                stats["grids_duplicate"] += 1
                warnings.once(
                    "grid_duplicate",
                    "duplicate GRID ids found; the last definition wins",
                )
            raw_nodes[nid] = (tuple(float(value) for value in xyz), cp)  # type: ignore[arg-type]
        elif name in SHELL_TRI or name in SHELL_QUAD or name in SOLID_CORNERS:
            corner_count = (
                SHELL_TRI.get(name)
                or SHELL_QUAD.get(name)
                or SOLID_CORNERS.get(name)
            )
            assert corner_count is not None
            if len(fields) < 2 + corner_count:
                warnings.once(
                    ("element_fields", name, card.source.name),
                    f"{card.source.name}:{card.lineno}: {name} with too few nodes ignored",
                )
                stats["elements_invalid"] += 1
                continue
            eid = parse_int(fields[0])
            pid = parse_int(fields[1])
            node_ids = tuple(parse_int(token) for token in fields[2:2 + corner_count])
            if eid <= 0 or any(nid <= 0 for nid in node_ids):
                warnings.once(
                    ("element_ids", name, card.source.name),
                    f"{card.source.name}:{card.lineno}: {name} with invalid ids ignored",
                )
                stats["elements_invalid"] += 1
                continue
            if len(fields) > 2 + corner_count and name in {"CTRIA6", "CQUAD8", "CQUAD9"}:
                stats["midside_nodes_ignored"] += 1
            if name in SOLID_CORNERS and len(fields) > 2 + corner_count:
                stats["midside_nodes_ignored"] += 1
            elements.append(Element(eid=eid, pid=pid, kind=name, nodes=node_ids))
            stats["elements_read"] += 1
        elif name in PROPERTY_CARDS:
            pid = parse_int(fields[0]) if fields else 0
            if pid > 0:
                properties[pid] = Property(pid=pid, kind=name, fields=tuple(fields))
                stats["properties_read"] += 1
        elif name.startswith("CORD2") and len(name) == 6:
            system = _coord_system_from_card(card, warnings)
            if system is not None:
                systems[system.cid] = system
                stats["coordsystems_read"] += 1
        elif name.startswith("CORD1"):
            unsupported[name] += 1
            warnings.once(
                ("cord1", name),
                f"{name} is not supported; nodes using it keep their raw coordinates",
            )
        elif name in IGNORED_CARDS:
            stats["cards_ignored"] += 1
        else:
            unsupported[name] += 1

    cache: dict[int, tuple[tuple[float, float, float], tuple[tuple[float, float, float], ...]]] = {}
    nodes: dict[int, tuple[float, float, float]] = {}
    for nid, (xyz, cp) in raw_nodes.items():
        if cp:
            system = systems.get(cp)
            resolved = (
                _resolve_cs(cp, systems, cache, set(), warnings)
                if system is not None
                else None
            )
            if system is None or resolved is None:
                stats["nodes_untransformed"] += 1
                nodes[nid] = xyz
            else:
                nodes[nid] = _apply_cs(system, resolved, xyz)
        else:
            nodes[nid] = xyz
    stats["nodes_read"] = len(nodes)

    if stats["nodes_read"] == 0:
        warnings.once("no_nodes", "no GRID cards found")
    if stats["elements_read"] == 0:
        warnings.once("no_elements", "no supported shell or solid elements found")
    if stats["nodes_untransformed"]:
        warnings.once(
            "nodes_untransformed",
            f"{stats['nodes_untransformed']} GRID(s) use an undefined coordinate "
            "system; raw coordinates were used",
        )
    if stats["midside_nodes_ignored"]:
        warnings.once(
            "midside",
            f"{stats['midside_nodes_ignored']} higher-order element(s) were "
            "linearised (midside nodes ignored)",
        )

    return BdfModel(
        source=source,
        nodes=nodes,
        elements=elements,
        properties=properties,
        coordsystems=systems,
        warnings=warnings.messages,
        stats=stats,
        unsupported=unsupported,
    )
