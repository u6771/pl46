from __future__ import annotations

import os
import tempfile
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
    """Serialize once and atomically replace the final OTF."""

    if output_path.suffix.lower() != ".otf":
        raise CompileError(
            f"Compiled font output must use the .otf extension: {output_path}"
        )
    temporary_path: Path | None = None
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            dir=output_path.parent,
            prefix=f".{output_path.stem}.",
            suffix=".otf",
        )
        os.close(descriptor)
        temporary_path = Path(temporary_name)
        font.save(temporary_path)
        os.replace(temporary_path, output_path)
    except Exception as error:
        raise CompileError(f"Cannot save {output_path}: {error}") from error
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
