"""Entry point for the standalone viewer and the PyInstaller EXE build."""

from __future__ import annotations

from nastran2stl.viewer import main

if __name__ == "__main__":
    raise SystemExit(main())
