from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fontTools.ttLib import TTFont
from ufoLib2 import Font

from skeletonfont.assembler import GlyphCatalog, assemble_font
from skeletonfont.compiler import (
    _unicode_glyph_order,
    compile_font,
    save_otf,
)
from skeletonfont.errors import CompileError
from skeletonfont.loader import load_font_meta
from skeletonfont.planner import plan_font
from skeletonfont.renderer import render_font


PROJECT_DIRECTORY = Path(__file__).resolve().parents[1]


class FontCompilerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        meta = load_font_meta(PROJECT_DIRECTORY, "ascii")
        assembled = assemble_font(
            meta,
            GlyphCatalog(PROJECT_DIRECTORY),
        )
        cls.ufo = render_font(plan_font(assembled))
        cls.otf = compile_font(cls.ufo)

    def test_compile_returns_in_memory_cff_font(self) -> None:
        otf = self.otf

        self.assertIsInstance(otf, TTFont)
        self.assertIn("CFF ", otf)
        self.assertIn("cmap", otf)
        self.assertIn("hmtx", otf)
        self.assertEqual(len(otf.getGlyphOrder()), 97)
        self.assertEqual(otf.getGlyphOrder()[0], ".notdef")

    def test_glyph_order_uses_unicode_then_unencoded_name(self) -> None:
        font = Font()
        for name, codepoint in (
            ("unencoded.z", None),
            ("B", 0x42),
            (".notdef", None),
            ("A", 0x41),
            ("unencoded.a", None),
        ):
            glyph = font.newGlyph(name)
            if codepoint is not None:
                glyph.unicodes = [codepoint]

        self.assertEqual(
            _unicode_glyph_order(font),
            [".notdef", "A", "B", "unencoded.a", "unencoded.z"],
        )

    def test_names_unicode_and_metrics_survive_compilation(self) -> None:
        otf = self.otf

        self.assertEqual(otf.getBestCmap()[0x0041], "A")
        self.assertEqual(otf["hmtx"].metrics["A"][0], 600)
        self.assertIn("uni6771", otf.getGlyphOrder())

    def test_compile_does_not_mutate_rendered_ufo(self) -> None:
        self.assertEqual(len(self.ufo), 97)
        self.assertEqual(self.ufo["A"].width, 600)
        self.assertEqual(self.ufo["A"].unicodes, [0x0041])

    def test_final_otf_is_saved_once_and_can_be_reopened(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "PL46-Ascii.otf"

            save_otf(self.otf, path)

            self.assertTrue(path.is_file())
            reopened = TTFont(path)
            self.assertEqual(reopened.getBestCmap()[0x0041], "A")
            reopened.close()

    def test_save_rejects_non_otf_destination(self) -> None:
        with self.assertRaisesRegex(CompileError, "\.otf"):
            save_otf(self.otf, Path("font.ttf"))

    def test_compile_requires_notdef_in_source_font(self) -> None:
        with self.assertRaisesRegex(CompileError, r"\.notdef"):
            compile_font(Font())


if __name__ == "__main__":
    unittest.main()
