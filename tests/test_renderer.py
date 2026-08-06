from __future__ import annotations

import unittest
from dataclasses import replace
from pathlib import Path

from skeletonfont.assembler import GlyphCatalog, assemble_font
from skeletonfont.loader import (
    load_font_meta,
    load_glyph_config,
    load_kerning_data,
    load_math_table_data,
    load_ssty_data,
)
from skeletonfont.planner import plan_font
from skeletonfont.renderer import render_font
from skeletonfont.model import GlyphAlias


PROJECT_DIRECTORY = Path(__file__).resolve().parents[1]


class FontRendererTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        meta = load_font_meta(PROJECT_DIRECTORY, "math")
        assembled = assemble_font(
            meta,
            GlyphCatalog(PROJECT_DIRECTORY),
        )
        config = load_glyph_config(
            PROJECT_DIRECTORY,
            meta.glyph_config_file,
        )
        assert meta.math_table is not None
        math_data = load_math_table_data(PROJECT_DIRECTORY, meta.math_table)
        assert meta.ssty_file is not None
        ssty_data = load_ssty_data(PROJECT_DIRECTORY, meta.ssty_file)
        cls.glyph_count = (
            len(assembled.glyphs) + len(assembled.glyph_aliases)
        )
        cls.font = render_font(
            plan_font(
                assembled,
                config,
                math_table_data=math_data,
                ssty_data=ssty_data,
            )
        )

    def test_font_info_and_notdef_are_rendered(self) -> None:
        font = self.font

        self.assertEqual(len(font), self.glyph_count)
        self.assertEqual(font.info.familyName, "PL46")
        self.assertEqual(font.info.styleName, "Math")
        self.assertEqual(font.info.unitsPerEm, 1000)
        self.assertEqual(font[".notdef"].width, 600)
        self.assertGreater(len(font[".notdef"].contours), 0)

    def test_rendered_and_empty_glyphs_receive_resolved_metrics(self) -> None:
        a = self.font["A"]
        space = self.font["space"]

        self.assertEqual(a.width, 600)
        self.assertEqual(a.unicodes, [0x0041])
        self.assertGreater(len(a.contours), 0)
        self.assertEqual(space.width, 550)
        self.assertEqual(space.contours, [])

    def test_glyph_alias_copies_rendered_source_outline(self) -> None:
        source = self.font["A"]
        alias = self.font["A.italic"]

        self.assertEqual(alias.width, source.width)
        self.assertEqual(alias.contours, source.contours)
        self.assertEqual(alias.unicodes, [0x1D434])
        self.assertEqual(source.unicodes, [0x0041])

    def test_alias_copy_does_not_depend_on_generator_order(self) -> None:
        meta = load_font_meta(PROJECT_DIRECTORY, "math")
        assembled = assemble_font(meta, GlyphCatalog(PROJECT_DIRECTORY))
        assembled = replace(
            assembled,
            glyph_aliases=tuple(reversed(assembled.glyph_aliases)),
        )
        config = load_glyph_config(
            PROJECT_DIRECTORY,
            meta.glyph_config_file,
        )
        assert meta.math_table is not None
        math_data = load_math_table_data(PROJECT_DIRECTORY, meta.math_table)

        font = render_font(
            plan_font(assembled, config, math_table_data=math_data)
        )

        self.assertEqual(font["A.italic"].contours, font["A"].contours)

    def test_unencoded_alias_copy_has_no_unicode(self) -> None:
        assembled = assemble_font(
            load_font_meta(PROJECT_DIRECTORY, "ascii"),
            GlyphCatalog(PROJECT_DIRECTORY),
        )
        plan = replace(
            plan_font(assembled),
            glyph_aliases=(GlyphAlias("A", "A.st", None),),
        )

        font = render_font(plan)

        self.assertEqual(font["A.st"].contours, font["A"].contours)
        self.assertEqual(font["A.st"].unicodes, [])

    def test_ssty_feature_is_written_before_compilation(self) -> None:
        feature = self.font.features.text
        self.assertTrue(feature.startswith("feature ssty {\n"))
        self.assertIn("    script math;\n", feature)
        self.assertIn("    sub minute by minute.st;\n", feature)
        self.assertTrue(feature.endswith("} ssty;\n"))

    def test_planned_kerning_is_written_to_ufo(self) -> None:
        meta = load_font_meta(PROJECT_DIRECTORY, "fraktur")
        assembled = assemble_font(
            meta,
            GlyphCatalog(PROJECT_DIRECTORY),
        )
        kerning = load_kerning_data(
            PROJECT_DIRECTORY,
            meta.kerning_file,
        )

        font = render_font(plan_font(assembled, kerning=kerning))

        self.assertEqual(
            font.groups["public.kern1.spur"],
            ["a", "i", "l", "m", "n", "u"],
        )
        self.assertEqual(
            font.kerning[
                ("public.kern1.spur", "public.kern2.spur")
            ],
            -100,
        )


if __name__ == "__main__":
    unittest.main()
