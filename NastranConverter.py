"""Entry point for the standalone converter and the PyInstaller EXE build."""

from __future__ import annotations

from nastran2stl.converter_gui import main

if __name__ == "__main__":
    raise SystemExit(main())
