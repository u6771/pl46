<p align="center">
  <img src="docs/png/pl46.png" width="200"/>
</p>

English | [中文](READMEButInChinese.md)

PL46 is a family of OpenType fonts whose glyph designs are based on line-segment skeletons with endpoints on an integer coordinate grid. It covers the Latin, Greek, and Cyrillic alphabets as well as Japanese kana, with Fraktur and Script alternatives available for the Latin letters. For the「Mado・Scientisto」who enjoys fiddling with equations, the family also provides OpenType MATH support. This means you can use it with XeLaTeX, LuaLaTeX, etc. (¦3【▓▓】

This font is currently under construction—its glyphs, spacing, and metrics may yet be adjusted or changed.

## Font specimens

<p align="center">
  <img src="docs/png/lang.png" alt="lang" width=49%>
  <img src="docs/png/jp.png" alt="jp" width=49%>
  <br>
  <img src="docs/png/style.png" alt="style" width=49%>
  <img src="docs/png/math.png" alt="math" width=49%>
</p>

## Font family

PL46 currently provides the following font files:

| Filename | Coverage | Glyph count |
| --- | --- | --- |
| `PL46-Regular.otf` | Latin, Greek, and Cyrillic alphabets | 641 |
| `PL46-JP.otf` | Latin alphabet and Japanese kana | 297 |
| `PL46-Bold.otf` | Latin alphabet | 188 |
| `PL46-Script.otf` | Latin alphabet | 97 |
| `PL46-Fraktur.otf` | Latin alphabet | 97 |
| `PL46-Mono.otf` | Latin alphabet | 97 |
| `PL46-Math.otf` | Latin and Greek alphabets and mathematical symbols | 1915 |

You can download them from [here](https://github.com/u6771/pl46/releases).

If needed, you can browse the complete glyph set by dragging the downloaded font files into [FontDrop!](https://fontdrop.info).

## skeletonfont

To build this font family, we developed a separate Python package called `skeletonfont`, located in the repository's [`src/`](src/) directory. It turns skeleton data describing the paths of glyph strokes into displayable glyph outlines, then writes additional information such as kerning and mathematical typesetting data into the finished fonts. You can learn more in [The skeletonfont Handbook](docs/skeletonfont.md).

### Building from source

This project requires Python 3.10 or later. See [The skeletonfont Build Guide](docs/building.md) for installation and build commands.

## Using PL46 in Microsoft Word

If you want to enable PL46's OpenType features in Word, such as kerning in *PL46 Fraktur* and the cursive joins in *PL46 Script*, first make sure that the document is not in **Compatibility Mode**. For an older document, use **File → Info → Convert** to upgrade its format; then save, close, and reopen it. Simply saving the document as `.docx` may not take it out of the older compatibility mode.

## Using PL46 with XeLaTeX or LuaLaTeX

### With `unicode-math`

The following example loads the fonts by name, so the corresponding OTF files must first be installed on your system:
```tex
\usepackage{unicode-math}
\setmainfont[BoldFont=PL46 Bold]{PL46 Regular}
\setmonofont{PL46 Mono}
\setmathfont{PL46 Math}
```
This sets PL46 as the document's text, mono, and mathematical typeface.

For testing directly within the repository, see the examples in the [`docs/tex/`](docs/tex/) directory.

### Styling `tikz` arrows

Users of `tikz` and `tikz-cd` can use the following settings to make arrows in `tikz` environments match the style of the font:
```tex
\usetikzlibrary{arrows.meta}
\tikzset{
  every path/.append style={
    line width=.05em
  },
  >={Straight Barb[
    length=.2em,
    width=.4em,
    round
  ]}
}
\tikzcdset{arrow style=tikz}
```

## Repository layout

- [`glyph_sources/`](glyph_sources/): normalized glyph skeleton sources
- [`glyph_sources/miscellaneous/`](glyph_sources/miscellaneous/): a design
  archive of alternative glyph sources that are not used by the current builds
- [`meta/`](meta/): font build definitions
- [`data/`](data/): glyph configuration, accent, kerning, ssty, and MATH table inputs
- [`src/skeletonfont/`](src/skeletonfont/): the `skeletonfont` Python package
- [`tools/skeletonfont_editor/`](tools/skeletonfont_editor/): the graphical
  editor for glyph skeleton sources
- [`tests/`](tests/): tests for `skeletonfont` and the editor
- [`docs/`](docs/): the `skeletonfont` handbook and build guide, together with
  TeX font specimens and their rendered images
- [`build_list.json`](build_list.json): the meta names built when none are given
  on the command line
- [`pyproject.toml`](pyproject.toml): Python package metadata, dependencies, and
  the `skeletonfont-build` command definition

## License

The generated fonts and the source data in [`glyph_sources/`](glyph_sources/),
[`meta/`](meta/), and [`data/`](data/) are licensed under the
[SIL Open Font License, Version 1.1](OFL.txt).

The Python code in [`src/`](src/), the editor in
[`tools/skeletonfont_editor/`](tools/skeletonfont_editor/), the tests, and the
documentation and examples are licensed under the [MIT License](MIT.txt).
