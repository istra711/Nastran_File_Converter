# Contributing

Thanks for your interest in `nastran2stl`.  This guide keeps contributions
consistent with the project's design goals.

## Principles

- **No runtime dependencies.**  The package must keep working with only the
  Python standard library.  STEP is allowed to require an external FreeCAD
  process, never a Python package.
- **Correct geometry over cleverness.**  Prefer faithful triangles; do not
  introduce surface reconstruction.
- **Small, layered API.**  Keep the parser, geometry helpers and file
  conversion separate.
- **Document behaviour.**  New options belong in the README, the CLI help, the
  GUI help and the `docs/` pages.

## Getting started

```bat
git clone https://github.com/istra711/Nastran_File_Converter.git
cd Nastran_File_Converter
python -m pip install -e ".[test]"
python -m pytest -q
```

The suite must pass (`96 passed`) before you open a pull request.

## Project layout

See [docs/architecture.md](docs/architecture.md) for the module map and data
flow, and [docs/testing.md](docs/testing.md) for the test layout.

## Coding style

- Target Python **3.9+**; use `from __future__ import annotations` in modules.
- Follow the existing style: standard library only, type hints, small pure
  functions, no global state.
- Keep user-visible CLI/GUI strings consistent.  The GUI is German; the CLI and
  library are English.
- Add docstrings to public functions.

## Adding an element type

1. Add the card to `KNOWN_CARDS` in `nastran2stl/bdf.py`.
2. Register its corner-node count in `SHELL_TRI`, `SHELL_QUAD` or
   `SOLID_CORNERS`.
3. For volume elements, add a `SOLID_FACES` entry (local face index tuples).
4. Add a minimal fixture under `tests/fixtures/` and a triangulation test.

Triangulation, boundary extraction, shell extrusion, STL and STEP then work
unchanged.

## Tests

- Put new fixtures in `tests/fixtures/` and keep them tiny.
- Assert on geometry (counts, bounds, watertightness), not float strings.
- Use `tmp_path` for outputs.
- Guard FreeCAD usage so the suite still passes without FreeCAD.
- Do not open GUI windows in tests; test pure functions.

## Documentation

- Update `README.md` for user-facing changes.
- Update the relevant page under `docs/` and add an entry to
  `docs/changelog.md`.
- Keep Markdown GitHub-friendly (tables, fenced code, blockquotes) and avoid
  renderer-specific syntax.

## Commits and pull requests

- Write clear commit messages describing the change and the reason.
- Keep pull requests focused; separate unrelated changes.
- Mention which tests you ran.
- For behaviour changes, describe the effect on STL and STEP output.

## Reporting issues

Please include:

- the converter version (`python -m nastran2stl --version`),
- the command line or GUI options used,
- a minimal BDF fixture that reproduces the problem (anonymised if needed),
- the manifest (`*_nastran2stl.json`) and the console/log output,
- whether FreeCAD is installed and its version.
