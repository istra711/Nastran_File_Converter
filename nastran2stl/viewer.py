"""Dependency-free 3D viewer for Nastran meshes.

The renderer uses only :mod:`tkinter` and a plain ``Canvas``.  It is meant for
quick inspection of the meshes produced by :mod:`nastran2stl`; it does not
replace a CAD/CAE viewer.

The module can be used from the command line::

    python -m nastran2stl.viewer model.bdf

or from Python::

    from nastran2stl import read_bdf, show_model

    model = read_bdf("model.bdf")
    show_model(model)

Only the GUI parts import tkinter; importing :class:`Scene` and
:class:`Camera` is safe on headless systems.
"""

from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Sequence, Tuple

from .bdf import BdfModel, NastranError, read_bdf

Point = Tuple[float, float, float]
Vector = Tuple[float, float, float]
Triangle = Tuple[float, ...]
Bounds = Tuple[Point, Point]

# Colours are intentionally pleasant on a dark background.  PIDs get colours
# in ascending PID order, so the same model always looks the same.
PALETTE = (
    "#4e9bd7",
    "#f28e2b",
    "#e15759",
    "#76b7b2",
    "#59a14f",
    "#edc948",
    "#b07aa1",
    "#ff9da7",
    "#9c755f",
    "#bab0ac",
    "#86bcb6",
    "#d37295",
    "#8cd17d",
    "#b6992d",
    "#499894",
    "#d4a6c8",
    "#a0cbe8",
    "#ffbe7d",
    "#ff9d9a",
    "#79706e",
)

BACKGROUND = "#1b1c22"
PANEL = "#262832"
PANEL_HOVER = "#343645"
FOREGROUND = "#d8dae2"
MUTED = "#8b8f9e"
AXIS_COLORS = ("#e15759", "#59a14f", "#4e9bd7")
LIGHT = (0.35, -0.5, 0.8)
_LIGHT_LENGTH = math.sqrt(sum(value * value for value in LIGHT))
LIGHT = tuple(value / _LIGHT_LENGTH for value in LIGHT)

CONTROLS = (
    "Drag: rotate  |  Shift+drag / middle: pan  |  Wheel: zoom  |  "
    "W: wireframe  |  F: fit  |  R: reset  |  T: top  |  Esc: close"
)

__all__ = [
    "Camera",
    "Scene",
    "ScenePart",
    "ViewerError",
    "ViewerWindow",
    "ask_for_bdf",
    "show_file",
    "show_model",
    "show_scene",
]


class ViewerError(Exception):
    """Raised when the 3D window cannot be opened."""


def _dot(a: Sequence[float], b: Sequence[float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a: Sequence[float], b: Sequence[float]) -> Vector:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _length(value: Sequence[float]) -> float:
    return math.sqrt(_dot(value, value))


def _normalize(value: Sequence[float]) -> Vector:
    length = _length(value)
    if length <= 1e-15:
        return (0.0, 0.0, 0.0)
    return (value[0] / length, value[1] / length, value[2] / length)


@dataclass
class ScenePart:
    """One renderable PID group."""

    pid: int
    name: str
    color: str
    triangles: list[Triangle]


@dataclass
class Scene:
    """Triangles and bounds prepared for the viewer."""

    parts: list[ScenePart]
    bounds: Bounds
    center: Point
    radius: float
    triangle_count: int

    @classmethod
    def from_parts(cls, parts: Iterable[object]) -> Scene:
        """Build a scene from ``MeshPart`` or ``ConvertedObject`` instances.

        Both types expose ``pid``, ``name`` and ``triangles``.  Duck typing
        keeps the viewer independent from the conversion layer.
        """
        items = list(parts)
        pids = sorted({int(getattr(part, "pid", 0)) for part in items})
        colors = {
            pid: PALETTE[index % len(PALETTE)] for index, pid in enumerate(pids)
        }

        scene_parts: list[ScenePart] = []
        low = [math.inf, math.inf, math.inf]
        high = [-math.inf, -math.inf, -math.inf]
        triangle_count = 0

        for part in items:
            triangles = getattr(part, "triangles", None)
            if triangles is None or len(triangles) == 0:
                continue
            pid = int(getattr(part, "pid", 0))
            name = str(getattr(part, "name", "") or f"PID {pid}")
            stored = triangles if isinstance(triangles, list) else list(triangles)
            scene_parts.append(
                ScenePart(pid=pid, name=name, color=colors[pid], triangles=stored)
            )
            triangle_count += len(stored)
            for triangle in stored:
                for offset in (0, 3, 6):
                    for axis in range(3):
                        value = float(triangle[offset + axis])
                        if value < low[axis]:
                            low[axis] = value
                        if value > high[axis]:
                            high[axis] = value

        if not scene_parts or triangle_count == 0:
            raise ViewerError("no triangles to display")

        bounds: Bounds = (
            (low[0], low[1], low[2]),
            (high[0], high[1], high[2]),
        )
        center = (
            (low[0] + high[0]) * 0.5,
            (low[1] + high[1]) * 0.5,
            (low[2] + high[2]) * 0.5,
        )
        radius = 0.5 * math.sqrt(
            (high[0] - low[0]) ** 2
            + (high[1] - low[1]) ** 2
            + (high[2] - low[2]) ** 2
        )
        if not math.isfinite(radius) or radius <= 0.0:
            radius = 1.0
        return cls(
            parts=scene_parts,
            bounds=bounds,
            center=center,
            radius=radius,
            triangle_count=triangle_count,
        )


@dataclass
class Camera:
    """Orbit camera around ``target``.

    ``yaw`` and ``pitch`` are in degrees; ``pitch`` is clamped to avoid the
    singularity at the world-up axis.
    """

    target: Point = (0.0, 0.0, 0.0)
    distance: float = 10.0
    yaw: float = 35.0
    pitch: float = 25.0
    fov: float = 45.0
    near: float = 1e-6
    min_distance: float = 1e-9
    max_distance: float = 1e12

    def fit(self, center: Sequence[float], radius: float) -> None:
        """Place the camera so a sphere around ``center`` fills the view."""
        self.target = (float(center[0]), float(center[1]), float(center[2]))
        radius = max(float(radius), 1e-9)
        half_fov = math.radians(max(1.0, min(179.0, self.fov))) * 0.5
        self.distance = radius / max(math.sin(half_fov), 1e-9) * 1.15
        self.min_distance = max(radius * 0.01, 1e-9)
        self.max_distance = max(radius * 1000.0, self.distance * 10.0)
        self.near = max(radius * 1e-5, 1e-9)

    def basis(self) -> tuple[Vector, Vector, Vector]:
        """Return the orthonormal camera axes ``(right, up, forward)``."""
        yaw = math.radians(self.yaw)
        pitch = math.radians(max(-89.0, min(89.0, self.pitch)))
        offset = (
            math.cos(pitch) * math.cos(yaw),
            math.cos(pitch) * math.sin(yaw),
            math.sin(pitch),
        )
        forward = _normalize((-offset[0], -offset[1], -offset[2]))
        right = _normalize(_cross(forward, (0.0, 0.0, 1.0)))
        if _length(right) <= 1e-12:
            right = (1.0, 0.0, 0.0)
        up = _normalize(_cross(right, forward))
        return right, up, forward

    def position(self) -> Point:
        _, _, forward = self.basis()
        return (
            self.target[0] - forward[0] * self.distance,
            self.target[1] - forward[1] * self.distance,
            self.target[2] - forward[2] * self.distance,
        )

    def project(
        self, point: Sequence[float], width: int, height: int
    ) -> tuple[float, float, float] | None:
        """Project a world point to ``(screen_x, screen_y, depth)``.

        Returns ``None`` if the point is behind the camera.
        """
        if width < 1 or height < 1:
            return None
        right, up, forward = self.basis()
        camera = self.position()
        relative = (
            point[0] - camera[0],
            point[1] - camera[1],
            point[2] - camera[2],
        )
        depth = _dot(relative, forward)
        if depth <= self.near:
            return None
        focal = 0.5 * min(width, height) / math.tan(
            math.radians(max(1.0, min(179.0, self.fov))) * 0.5
        )
        x = width * 0.5 + focal * _dot(relative, right) / depth
        y = height * 0.5 - focal * _dot(relative, up) / depth
        return (x, y, depth)

    def orbit(self, dx: float, dy: float, sensitivity: float = 0.45) -> None:
        self.yaw = (self.yaw + dx * sensitivity) % 360.0
        self.pitch = max(-89.0, min(89.0, self.pitch + dy * sensitivity))

    def pan(self, dx: float, dy: float, width: int, height: int) -> None:
        if width < 1 or height < 1:
            return
        units_per_pixel = (
            2.0
            * self.distance
            * math.tan(math.radians(max(1.0, min(179.0, self.fov))) * 0.5)
            / min(width, height)
        )
        right, up, _ = self.basis()
        self.target = (
            self.target[0] - right[0] * dx * units_per_pixel + up[0] * dy * units_per_pixel,
            self.target[1] - right[1] * dx * units_per_pixel + up[1] * dy * units_per_pixel,
            self.target[2] - right[2] * dx * units_per_pixel + up[2] * dy * units_per_pixel,
        )

    def zoom(self, factor: float) -> None:
        if not math.isfinite(factor) or factor <= 0.0:
            return
        self.distance = max(
            self.min_distance, min(self.max_distance, self.distance * factor)
        )


@lru_cache(maxsize=8192)
def _shade_color(color: str, bucket: int) -> str:
    """Shade a ``#rrggbb`` colour; ``bucket`` is 0..20."""
    bucket = max(0, min(20, int(bucket)))
    factor = 0.35 + 0.65 * bucket / 20.0
    try:
        red = int(color[1:3], 16)
        green = int(color[3:5], 16)
        blue = int(color[5:7], 16)
    except (ValueError, IndexError):
        return color
    red = max(0, min(255, int(round(red * factor))))
    green = max(0, min(255, int(round(green * factor))))
    blue = max(0, min(255, int(round(blue * factor))))
    return f"#{red:02x}{green:02x}{blue:02x}"


def _face_intensity(triangle: Triangle) -> float:
    ux = triangle[3] - triangle[0]
    uy = triangle[4] - triangle[1]
    uz = triangle[5] - triangle[2]
    vx = triangle[6] - triangle[0]
    vy = triangle[7] - triangle[1]
    vz = triangle[8] - triangle[2]
    nx = uy * vz - uz * vy
    ny = uz * vx - ux * vz
    nz = ux * vy - uy * vx
    length = math.sqrt(nx * nx + ny * ny + nz * nz)
    if length <= 1e-15:
        return 0.0
    # Two-sided lighting: open shells are visible from both sides.
    return abs((nx * LIGHT[0] + ny * LIGHT[1] + nz * LIGHT[2]) / length)


def _load_tk():
    try:
        import tkinter as tk
    except ImportError as exc:  # pragma: no cover - depends on the Python build
        raise ViewerError(
            "Tkinter is not available in this Python installation; install "
            "the tkinter package (on Linux often python3-tk) to use the viewer"
        ) from exc
    return tk


def _report_error(message: str) -> None:
    """Show an error in a GUI dialog, falling back to stderr when possible."""
    try:
        tk = _load_tk()
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Nastran Viewer", message, parent=root)
        root.destroy()
    except Exception:
        try:
            print(f"error: {message}", file=sys.stderr)
        except Exception:
            pass


def _dialog_directory(initialdir: str | Path | None) -> str:
    if initialdir is not None:
        path = Path(initialdir).expanduser()
        if path.is_dir():
            return str(path)
        if path.is_file():
            return str(path.parent)
    return str(Path.cwd())


def ask_for_bdf(
    parent=None,
    *,
    initialdir: str | Path | None = None,
    title: str = "Nastran-Datei öffnen",
) -> Path | None:
    """Show a small modal file dialog and return the selected BDF path.

    The dialog has a path field and a native "Browse" button.  It returns
    ``None`` when the user cancels.  ``parent`` may be an existing Tk widget;
    without a parent the function creates and destroys its own temporary root.
    """
    tk = _load_tk()
    try:
        from tkinter import filedialog, messagebox
    except ImportError as exc:  # pragma: no cover
        raise ViewerError("Tkinter file dialogs are not available") from exc

    owns_root = parent is None
    try:
        owner = tk.Tk() if owns_root else tk.Toplevel(parent)
    except tk.TclError as exc:
        raise ViewerError(
            "cannot open a file dialog (no graphical display available): "
            f"{exc}"
        ) from exc

    owner.title(title)
    owner.configure(bg=BACKGROUND)
    owner.resizable(False, False)
    if not owns_root:
        try:
            owner.transient(parent)
            owner.grab_set()
        except tk.TclError:
            pass

    result: Path | None = None
    path_var = tk.StringVar(master=owner)

    frame = tk.Frame(owner, bg=PANEL, padx=16, pady=14)
    frame.pack(fill=tk.BOTH, expand=True)
    tk.Label(
        frame,
        text="BDF/NAS/DAT-Datei:",
        bg=PANEL,
        fg=FOREGROUND,
        anchor=tk.W,
    ).pack(fill=tk.X)

    row = tk.Frame(frame, bg=PANEL)
    row.pack(fill=tk.X, pady=(6, 0))
    entry = tk.Entry(
        row,
        textvariable=path_var,
        width=56,
        bg="#111217",
        fg=FOREGROUND,
        insertbackground=FOREGROUND,
        relief=tk.FLAT,
        highlightthickness=1,
        highlightbackground="#3b3d4a",
        highlightcolor="#4e9bd7",
    )
    entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=4)

    button_style = {
        "bg": PANEL_HOVER,
        "fg": FOREGROUND,
        "activebackground": "#444756",
        "activeforeground": FOREGROUND,
        "relief": tk.FLAT,
        "bd": 0,
        "padx": 12,
        "pady": 5,
        "cursor": "hand2",
    }

    def browse() -> None:
        selected = filedialog.askopenfilename(
            parent=owner,
            title=title,
            initialdir=_dialog_directory(initialdir),
            filetypes=(
                ("Nastran-Dateien", "*.bdf *.nas *.dat"),
                ("Alle Dateien", "*.*"),
            ),
        )
        if selected:
            path_var.set(selected)
            entry.icursor(tk.END)
            entry.focus_set()

    tk.Button(row, text="Durchsuchen…", command=browse, **button_style).pack(
        side=tk.LEFT, padx=(8, 0)
    )

    buttons = tk.Frame(frame, bg=PANEL)
    buttons.pack(fill=tk.X, pady=(12, 0))

    def cancel(_event=None) -> None:
        owner.destroy()

    def accept(_event=None) -> None:
        nonlocal result
        raw = path_var.get().strip()
        if len(raw) >= 2 and raw[0] == raw[-1] == '"':
            raw = raw[1:-1].strip()
        if not raw:
            messagebox.showwarning(
                title,
                "Bitte eine BDF-Datei auswählen.",
                parent=owner,
            )
            return
        path = Path(raw).expanduser()
        if not path.is_file():
            messagebox.showerror(
                title,
                f"Datei nicht gefunden:\n{path}",
                parent=owner,
            )
            return
        result = path
        owner.destroy()

    tk.Button(buttons, text="Abbrechen", command=cancel, **button_style).pack(
        side=tk.RIGHT, padx=(0, 8)
    )
    tk.Button(
        buttons,
        text="Anzeigen",
        command=accept,
        bg="#3a6ea5",
        fg="#ffffff",
        activebackground="#4b82bd",
        activeforeground="#ffffff",
        relief=tk.FLAT,
        bd=0,
        padx=14,
        pady=5,
        cursor="hand2",
    ).pack(side=tk.RIGHT)

    owner.bind("<Return>", accept)
    owner.bind("<KP_Enter>", accept)
    owner.bind("<Escape>", cancel)
    owner.protocol("WM_DELETE_WINDOW", cancel)

    owner.update_idletasks()
    width = owner.winfo_reqwidth()
    height = owner.winfo_reqheight()
    x = max(0, (owner.winfo_screenwidth() - width) // 2)
    y = max(0, (owner.winfo_screenheight() - height) // 3)
    owner.geometry(f"+{x}+{y}")
    owner.lift()
    entry.focus_set()

    if owns_root:
        owner.mainloop()
    else:
        owner.wait_window()
    return result


class ViewerWindow:
    """Tkinter window with a software-rendered, interactive 3D view."""

    def __init__(
        self,
        root,
        scene: Scene,
        *,
        title: str = "Nastran 3D Viewer",
        wireframe: bool = False,
    ) -> None:
        try:
            import tkinter as tk
        except ImportError as exc:  # pragma: no cover
            raise ViewerError("Tkinter is not available") from exc

        self.tk = tk
        self.root = root
        self.scene = scene
        self.camera = Camera()
        self.camera.fit(scene.center, scene.radius)
        self.wireframe = bool(wireframe)
        self.visibility: dict[int, object] = {}
        self._drag_mode: str | None = None
        self._dragging = False
        self._last_pointer = (0, 0)
        self._pending: str | None = None
        self._needs_fit = True

        root.title(f"{title} — {scene.triangle_count} triangles")
        root.configure(bg=BACKGROUND)
        root.minsize(640, 480)
        try:
            root.geometry("1200x800")
        except tk.TclError:
            pass
        root.protocol("WM_DELETE_WINDOW", self.close)

        self._build_ui()
        self._bind_events()

    def _build_ui(self) -> None:
        tk = self.tk
        toolbar = tk.Frame(self.root, bg=PANEL)
        toolbar.pack(side=tk.TOP, fill=tk.X)

        self._button(toolbar, "Reset (R)", self.reset)
        self._button(toolbar, "Fit (F)", self.fit)
        self._button(toolbar, "Wireframe (W)", self.toggle_wireframe)
        self._button(toolbar, "Top (T)", self.top_view)

        info = f"{self.scene.triangle_count} triangles · {len(self.scene.parts)} object(s)"
        tk.Label(
            toolbar,
            text=info,
            bg=PANEL,
            fg=MUTED,
            anchor=tk.E,
        ).pack(side=tk.RIGHT, padx=12, pady=7)

        self.status_var = tk.StringVar(master=self.root, value=CONTROLS)
        status = tk.Frame(self.root, bg=PANEL)
        status.pack(side=tk.BOTTOM, fill=tk.X)
        tk.Label(
            status,
            textvariable=self.status_var,
            bg=PANEL,
            fg=MUTED,
            anchor=tk.W,
            padx=10,
            pady=4,
        ).pack(side=tk.LEFT, fill=tk.X, expand=True)

        body = tk.Frame(self.root, bg=BACKGROUND)
        body.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        sidebar = tk.Frame(body, bg=PANEL, width=210)
        sidebar.pack(side=tk.LEFT, fill=tk.Y)
        sidebar.pack_propagate(False)
        tk.Label(
            sidebar,
            text="Objects",
            bg=PANEL,
            fg=FOREGROUND,
            anchor=tk.W,
            padx=10,
            pady=8,
        ).pack(fill=tk.X)

        for part in self.scene.parts:
            visible = tk.BooleanVar(master=self.root, value=True)
            self.visibility[part.pid] = visible
            checkbutton = tk.Checkbutton(
                sidebar,
                text=f"{part.pid}  {part.name}",
                variable=visible,
                command=lambda: self.redraw(immediate=True),
                bg=PANEL,
                fg=part.color,
                selectcolor="#3b3d4a",
                activebackground=PANEL,
                activeforeground=part.color,
                anchor=tk.W,
                justify=tk.LEFT,
                wraplength=190,
                bd=0,
                highlightthickness=0,
                padx=8,
                pady=2,
            )
            checkbutton.pack(fill=tk.X, padx=2, pady=1)

        tk.Label(
            sidebar,
            text="Left-drag rotates the model.\nShift+drag or middle-drag pans.",
            bg=PANEL,
            fg=MUTED,
            anchor=tk.W,
            justify=tk.LEFT,
            wraplength=190,
            padx=10,
            pady=10,
        ).pack(side=tk.BOTTOM, fill=tk.X)

        self.canvas = tk.Canvas(
            body,
            bg=BACKGROUND,
            highlightthickness=0,
            bd=0,
            takefocus=True,
        )
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    def _button(self, parent, text: str, command) -> None:
        button = self.tk.Button(
            parent,
            text=text,
            command=command,
            bg=PANEL,
            fg=FOREGROUND,
            activebackground=PANEL_HOVER,
            activeforeground=FOREGROUND,
            relief=self.tk.FLAT,
            bd=0,
            padx=12,
            pady=5,
            cursor="hand2",
        )
        button.pack(side=self.tk.LEFT, padx=(6, 0), pady=6)

    def _bind_events(self) -> None:
        self.root.bind("<Escape>", lambda _event: self.close())
        self.root.bind("<Key-r>", lambda _event: self.reset())
        self.root.bind("<Key-R>", lambda _event: self.reset())
        self.root.bind("<Key-f>", lambda _event: self.fit())
        self.root.bind("<Key-F>", lambda _event: self.fit())
        self.root.bind("<Key-w>", lambda _event: self.toggle_wireframe())
        self.root.bind("<Key-W>", lambda _event: self.toggle_wireframe())
        self.root.bind("<Key-t>", lambda _event: self.top_view())
        self.root.bind("<Key-T>", lambda _event: self.top_view())

        self.canvas.bind("<Configure>", self._on_resize)
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_motion)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<ButtonPress-2>", self._on_middle_press)
        self.canvas.bind("<B2-Motion>", self._on_middle_motion)
        self.canvas.bind("<ButtonRelease-2>", self._on_release)
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self.canvas.bind("<Button-4>", lambda _event: self._zoom(1.0 / 1.15))
        self.canvas.bind("<Button-5>", lambda _event: self._zoom(1.15))
        self.canvas.focus_set()

    def _on_resize(self, event) -> None:
        if event.width < 10 or event.height < 10:
            return
        if self._needs_fit:
            self.camera.fit(self.scene.center, self.scene.radius)
            self._needs_fit = False
        self.redraw(immediate=True)

    def _on_press(self, event) -> None:
        self.canvas.focus_set()
        self._last_pointer = (event.x, event.y)
        self._dragging = True
        self._drag_mode = "pan" if event.state & 0x0001 else "rotate"

    def _on_motion(self, event) -> None:
        if not self._dragging:
            return
        dx = event.x - self._last_pointer[0]
        dy = event.y - self._last_pointer[1]
        self._last_pointer = (event.x, event.y)
        if self._drag_mode == "pan":
            self.camera.pan(
                dx, dy, self.canvas.winfo_width(), self.canvas.winfo_height()
            )
        else:
            self.camera.orbit(dx, dy)
        self.redraw()

    def _on_middle_press(self, event) -> None:
        self.canvas.focus_set()
        self._last_pointer = (event.x, event.y)
        self._dragging = True
        self._drag_mode = "pan"

    def _on_middle_motion(self, event) -> None:
        if not self._dragging:
            return
        dx = event.x - self._last_pointer[0]
        dy = event.y - self._last_pointer[1]
        self._last_pointer = (event.x, event.y)
        self.camera.pan(dx, dy, self.canvas.winfo_width(), self.canvas.winfo_height())
        self.redraw()

    def _on_release(self, _event) -> None:
        self._dragging = False
        self._drag_mode = None
        self.redraw(immediate=True)

    def _on_wheel(self, event) -> None:
        if not event.delta:
            return
        self._zoom(0.85 ** (event.delta / 120.0))

    def _zoom(self, factor: float) -> None:
        self.camera.zoom(factor)
        self.redraw()

    def reset(self) -> None:
        self.camera.yaw = 35.0
        self.camera.pitch = 25.0
        self.camera.fit(self.scene.center, self.scene.radius)
        self.redraw(immediate=True)

    def fit(self) -> None:
        self.camera.fit(self.scene.center, self.scene.radius)
        self.redraw(immediate=True)

    def toggle_wireframe(self) -> None:
        self.wireframe = not self.wireframe
        self.redraw(immediate=True)

    def top_view(self) -> None:
        self.camera.yaw = -90.0
        self.camera.pitch = 89.0
        self.redraw(immediate=True)

    def close(self) -> None:
        if self._pending is not None:
            try:
                self.root.after_cancel(self._pending)
            except Exception:
                pass
            self._pending = None
        try:
            self.root.destroy()
        except Exception:
            pass

    def redraw(self, immediate: bool = False) -> None:
        """Schedule a redraw, coalescing mouse-move events."""
        if self._pending is not None:
            try:
                self.root.after_cancel(self._pending)
            except Exception:
                pass
            self._pending = None
        try:
            self._pending = self.root.after(0 if immediate else 15, self._draw)
        except Exception:
            self._pending = None

    def _draw(self) -> None:
        self._pending = None
        width = self.canvas.winfo_width()
        height = self.canvas.winfo_height()
        if width < 10 or height < 10:
            return

        self.canvas.delete("all")
        adapter = self.canvas
        camera = self.camera
        project = camera.project

        # While dragging a very large mesh, draw a subsampled preview.  The
        # full-resolution frame is rendered when the mouse is released.
        stride = 1
        if self._dragging and self.scene.triangle_count > 25000:
            stride = max(1, self.scene.triangle_count // 25000)

        drawables: list[tuple[float, list[float], str, str]] = []
        for part in self.scene.parts:
            visible = self.visibility.get(part.pid)
            if visible is not None and not visible.get():
                continue
            triangles = part.triangles
            for index in range(0, len(triangles), stride):
                triangle = triangles[index]
                p0 = project((triangle[0], triangle[1], triangle[2]), width, height)
                if p0 is None:
                    continue
                p1 = project((triangle[3], triangle[4], triangle[5]), width, height)
                if p1 is None:
                    continue
                p2 = project((triangle[6], triangle[7], triangle[8]), width, height)
                if p2 is None:
                    continue

                intensity = _face_intensity(triangle)
                bucket = max(0, min(20, int(round(intensity * 20.0))))
                fill = _shade_color(part.color, bucket)
                outline = _shade_color(part.color, max(0, bucket - 5))
                coords = [p0[0], p0[1], p1[0], p1[1], p2[0], p2[1]]
                depth = (p0[2] + p1[2] + p2[2]) / 3.0
                drawables.append((depth, coords, fill, outline))

        drawables.sort(key=lambda item: item[0], reverse=True)
        for _depth, coords, fill, outline in drawables:
            if self.wireframe:
                adapter.create_polygon(
                    coords,
                    fill="",
                    outline=outline,
                    width=1,
                )
            else:
                adapter.create_polygon(
                    coords,
                    fill=fill,
                    outline=outline,
                    width=1,
                )

        if not drawables:
            adapter.create_text(
                width / 2,
                height / 2,
                text="No visible geometry\n(zoom out with the mouse wheel)",
                fill=MUTED,
                justify="center",
            )

        self._draw_axes(width, height)
        if stride > 1:
            self.status_var.set(f"Preview ({stride}× decimated) — {CONTROLS}")
        else:
            self.status_var.set(CONTROLS)

    def _draw_axes(self, width: int, height: int) -> None:
        right, up, _forward = self.camera.basis()
        origin_x = width - 70
        origin_y = height - 70
        length = 32.0
        for axis, color, label in (
            ((1.0, 0.0, 0.0), AXIS_COLORS[0], "X"),
            ((0.0, 1.0, 0.0), AXIS_COLORS[1], "Y"),
            ((0.0, 0.0, 1.0), AXIS_COLORS[2], "Z"),
        ):
            dx = _dot(axis, right) * length
            dy = -_dot(axis, up) * length
            self.canvas.create_line(
                origin_x,
                origin_y,
                origin_x + dx,
                origin_y + dy,
                fill=color,
                width=2,
            )
            self.canvas.create_text(
                origin_x + dx * 1.22,
                origin_y + dy * 1.22,
                text=label,
                fill=color,
                font=("TkDefaultFont", 9, "bold"),
            )


def show_scene(
    scene: Scene,
    *,
    title: str = "Nastran 3D Viewer",
    wireframe: bool = False,
    block: bool = True,
    parent=None,
) -> ViewerWindow:
    """Open a viewer window for a prepared :class:`Scene`."""
    tk = _load_tk()
    try:
        root = tk.Tk() if parent is None else tk.Toplevel(parent)
    except tk.TclError as exc:
        raise ViewerError(
            "cannot open a window (no graphical display available): "
            f"{exc}"
        ) from exc
    try:
        window = ViewerWindow(root, scene, title=title, wireframe=wireframe)
    except Exception:
        try:
            root.destroy()
        except Exception:
            pass
        raise
    if block:
        root.mainloop()
    return window


def show_model(
    model: BdfModel,
    parts: Iterable[object] | None = None,
    *,
    title: str | None = None,
    scale: float = 1.0,
    solids: str = "boundary",
    weld_tol: float = 0.0,
    wireframe: bool = False,
    block: bool = True,
    parent=None,
) -> ViewerWindow:
    """Display a parsed BDF model in a new window.

    ``parts`` may be supplied to reuse triangles that were already converted.
    Otherwise the triangles are generated with :meth:`BdfModel.parts`.
    """
    if parts is None:
        parts = model.parts(scale=scale, solids=solids, weld_tol=weld_tol)
    scene = Scene.from_parts(parts)
    return show_scene(
        scene,
        title=title or model.source.name,
        wireframe=wireframe,
        block=block,
        parent=parent,
    )


def show_file(
    path: str | Path,
    *,
    scale: float = 1.0,
    solids: str = "boundary",
    weld_tol: float = 0.0,
    wireframe: bool = False,
    block: bool = True,
) -> ViewerWindow:
    """Read a BDF file and display it in a new window."""
    model = read_bdf(path)
    return show_model(
        model,
        title=model.source.name,
        scale=scale,
        solids=solids,
        weld_tol=weld_tol,
        wireframe=wireframe,
        block=block,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m nastran2stl.viewer",
        description="Display a Nastran BDF shell/solid mesh in a 3D window.",
    )
    parser.add_argument(
        "input",
        nargs="?",
        metavar="BDF",
        help="input .bdf/.nas/.dat file (omit to open the file dialog)",
    )
    parser.add_argument(
        "--scale",
        type=float,
        default=1.0,
        help="coordinate scale factor (default: 1.0)",
    )
    parser.add_argument(
        "--solids",
        choices=("boundary", "faces", "skip"),
        default="boundary",
        help="volume elements: boundary skin (default), every face, or skip",
    )
    parser.add_argument(
        "--weld-tol",
        type=float,
        default=0.0,
        metavar="TOL",
        help="merge duplicated solid nodes with this source-unit tolerance",
    )
    parser.add_argument(
        "--wireframe",
        action="store_true",
        help="start in wireframe mode",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        path = Path(args.input) if args.input else ask_for_bdf()
        if path is None:
            return 0
        model = read_bdf(path)
        parts = model.parts(
            scale=args.scale,
            solids=args.solids,
            weld_tol=args.weld_tol,
        )
        show_model(
            model,
            parts,
            title=model.source.name,
            wireframe=args.wireframe,
        )
    except (NastranError, ViewerError, ValueError, OSError) as exc:
        _report_error(str(exc))
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - manual entry point
    raise SystemExit(main())
