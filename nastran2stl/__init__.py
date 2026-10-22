"""Stand-alone Nastran BDF -> STL/STEP converter.

Typical use::

    python -m nastran2stl model.bdf -o out
    python -m nastran2stl model.bdf -o out --shell-solid --step

Library use::

    from nastran2stl import convert

    result = convert(
        "model.bdf",
        "out",
        unit_in="mm",
        unit_out="mm",
        shell_solid=True,
        solid_elements=True,
        step=True,
    )
    for obj in result.objects:
        print(obj.pid, obj.stl_path, obj.step_path, len(obj.triangles))

The package has no third-party Python dependencies.  ``BdfModel.parts()`` can
be used directly to feed triangle arrays into another application (e.g. the
FreeCAD/openEMS GUI) without writing STL files.  STEP export is optional and
requires an installed ``FreeCADCmd``.  An optional Tkinter preview is available
through ``show_model()`` / ``python -m nastran2stl.viewer``.
"""

from __future__ import annotations

from .bdf import (
    BdfModel,
    BdfModel as Model,
    Element,
    MeshPart,
    NastranError,
    NoGeometryError,
    Property,
    read_bdf,
    triangle_bounds,
)
from .convert import (
    ConversionResult,
    ConvertedObject,
    convert,
    load_names,
    sanitize_name,
    unit_factor,
)
from .solid import SolidError, extrude_shell_triangles, is_watertight
from .step import (
    StepError,
    StepItem,
    StepResult,
    find_freecad_cmd,
    write_step_files,
)
from .stl import write_ascii_stl, write_binary_stl, write_stl

__version__ = "0.2.0"

# The viewer is imported lazily.  Besides keeping ``import nastran2stl`` free
# of GUI code, this avoids runpy's "found in sys.modules" warning when the
# module is started with ``python -m nastran2stl.viewer``.
_VIEWER_EXPORTS = frozenset(
    {
        "Camera",
        "Scene",
        "ScenePart",
        "ViewerError",
        "ViewerWindow",
        "ask_for_bdf",
        "show_file",
        "show_model",
        "show_scene",
    }
)


def __getattr__(name: str):
    if name in _VIEWER_EXPORTS:
        from . import viewer as _viewer

        value = getattr(_viewer, name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "BdfModel",
    "Camera",
    "ConversionResult",
    "ConvertedObject",
    "Element",
    "MeshPart",
    "Model",
    "NastranError",
    "NoGeometryError",
    "Property",
    "Scene",
    "ScenePart",
    "SolidError",
    "StepError",
    "StepItem",
    "StepResult",
    "ViewerError",
    "ViewerWindow",
    "__version__",
    "ask_for_bdf",
    "convert",
    "extrude_shell_triangles",
    "find_freecad_cmd",
    "is_watertight",
    "load_names",
    "read_bdf",
    "sanitize_name",
    "show_file",
    "show_model",
    "show_scene",
    "triangle_bounds",
    "unit_factor",
    "write_ascii_stl",
    "write_binary_stl",
    "write_step_files",
    "write_stl",
]
