# The skeletonfont Build Guide

PL46 requires Python 3.10 or later.

In this guide, `<project>` means the repository root containing
`pyproject.toml`, `meta/`, `glyph_sources/`, and `data/`. Text enclosed in angle
brackets is a placeholder and must be replaced with an actual value.

## Setup

From `<project>`, create a virtual environment:

```text
python -m venv .venv
```

Activate it on Windows PowerShell with:

```powershell
.\.venv\Scripts\Activate.ps1
```

Or on Linux and macOS with:

```sh
source .venv/bin/activate
```

Then install `skeletonfont` from the repository:

```text
python -m pip install -e .
```

## Build fonts

The complete command form is:

```text
skeletonfont-build [--project-directory <project>] [--output-directory <output>] [<meta-name> ...]
```

Square brackets mark optional parts of the command; they are not typed
literally.

- `<meta-name>` is the filename of a meta file without its `.json` extension:
  for example, the name `math` selects `meta/math.json`. Supply one name to
  build one font, or several space-separated names to build several fonts.
- If every `<meta-name>` is omitted, the command builds the meta names listed
  in `<project>/build_list.json`.
- `--project-directory <project>` selects the project to build. If the option
  is omitted, the current working directory is used, so running the command
  from `<project>` needs no directory option. The CLI does not search parent
  directories or infer a project location from the installed package.
- `--output-directory <output>` changes where the OTF files are written. If it
  is omitted, the destination is `<project>/build/otf/`. The destination
  directory is created automatically. A relative `<output>` is interpreted
  from the current working directory, not from `<project>`.

Each output filename is `<output_stem>.otf`, using the effective `output_stem`
of the selected meta file.

## Tests

With the virtual environment active, run the tests from `<project>`:

```text
python -m unittest discover -s tests
```

For the architecture and data formats behind these commands, see
[The skeletonfont Handbook](skeletonfont.md).
