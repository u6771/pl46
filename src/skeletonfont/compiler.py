from __future__ import annotations

from pathlib import Path

from fontTools.ttLib import TTFont
from ufo2ft import compileOTF
from ufoLib2 import Font

from .errors import CompileError


def _unicode_glyph_order(ufo: Font) -> list[str]:
    def sort_key(name: str) -> tuple[int, int, str]:
        if name == ".notdef":
            return 0, 0, name
        unicodes = ufo[name].unicodes
        if unicodes:
            return 1, min(unicodes), name
        return 2, 0, name

    return sorted(ufo.keys(), key=sort_key)


def compile_font(ufo: Font) -> TTFont:
    """Compile an in-memory UFO into an in-memory CFF OpenType font."""

    if ".notdef" not in ufo:
        raise CompileError("Font is missing required glyph '.notdef'.")

    try:
        return compileOTF(
            ufo,
            removeOverlaps=False,
            useProductionNames=False,
            inplace=False,
            optimizeCFF=2,
            roundTolerance=0.5,
            glyphOrder=_unicode_glyph_order(ufo),
        )
    except Exception as error:
        raise CompileError(f"Cannot compile in-memory UFO: {error}") from error


def save_otf(font: TTFont, output_path: Path) -> None:
    """Serialize a compiled font exactly once to its final OTF path."""

    if output_path.suffix.lower() != ".otf":
        raise CompileError(
            f"Compiled font output must use the .otf extension: {output_path}"
        )
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        font.save(output_path)
    except OSError as error:
        raise CompileError(f"Cannot save {output_path}: {error}") from error
