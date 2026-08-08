# PL46

PL46 is a work-in-progress geometric typeface family built from normalized
skeleton sources. The project includes text, display, mathematical, script, and
Fraktur-oriented styles, with PL46-Math providing OpenType MATH and `ssty`
support.

## Fonts

Current builds are written to [`build/otf/`](build/otf/):

- `PL46-Ascii`
- `PL46-Bold`
- `PL46-Fraktur`
- `PL46-JP`
- `PL46-Math`
- `PL46-Mono`
- `PL46-Script`

The available glyph coverage and individual designs are evolving; the files in
this repository should be treated as development builds.

## Math typesetting

PL46-Math can be tested with XeLaTeX or LuaLaTeX and `unicode-math`:

```tex
\usepackage{unicode-math}
\setmathfont[Path=build/otf/]{PL46-Math.otf}
```

The repository's [`tex/`](tex/) directory contains example documents and
positioning tests.

## Build from source

The project requires Python 3.10 or later. See the
[build guide](docs/building.md) for setup and commands.

## Development documentation

PL46 is built by the in-repository `skeletonfont` toolchain. Its data model,
assembly pipeline, MATH-table inputs, and project schema are documented in
[skeletonfont architecture](docs/skeletonfont.md).

```text
load -> assemble -> plan -> render -> compile
```

## Repository layout

- [`glyph_sources/`](glyph_sources/) - normalized glyph skeleton sources
- [`meta/`](meta/) - font-build definitions
- [`data/`](data/) - glyph configuration, accent, kerning, ssty, and MATH-table inputs
- [`tests/`](tests/) - build-system tests
- [`tex/`](tex/) - TeX specimens and regression documents
