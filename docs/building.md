# Building PL46

PL46 requires Python 3.10 or later.

## Setup

From the repository root:

```text
python -m venv .venv
python -m pip install -e .
```

Activate the virtual environment with `.venv\\Scripts\\Activate.ps1` on
Windows PowerShell, or `source .venv/bin/activate` on Linux and macOS.

## Build fonts

The command uses the current directory as the project directory:

```text
skeletonfont-build ascii
skeletonfont-build math script
```

With no build names it reads `build_list.json`. Output defaults to
`build/otf/<output_stem>.otf`.

On Windows, `build.cmd` is a convenience wrapper:

```text
build.cmd math
```

Use `--project-directory` or `--output-directory` when needed:

```text
skeletonfont-build --project-directory D:\\workspace\\pl46 ascii
skeletonfont-build math --output-directory D:\\fonts
```

## Tests

```text
python -m unittest discover -s tests
```

For the architecture and data formats behind these commands, see
[skeletonfont architecture](skeletonfont.md).
