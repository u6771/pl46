from __future__ import annotations

import unittest
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType
from unittest.mock import patch

from skeletonfont.assembler import GlyphCatalog, assemble_font
from skeletonfont.errors import AssemblyError
from skeletonfont.loader import load_font_meta
from skeletonfont.mappings import (
    GlyphIdentity,
    GlyphMapping,
    _validate_mapping_domains,
    get_mapping,
)
from skeletonfont.model import AssembledGlyph, GlyphSource, UnicodeDomain


PROJECT_DIRECTORY = Path(__file__).resolve().parents[1]


class GlyphCatalogTests(unittest.TestCase):
    def test_source_directory_is_loaded_once(self) -> None:
        catalog = GlyphCatalog(PROJECT_DIRECTORY)

        first = catalog.load("ascii")
        second = catalog.load("ascii")

        self.assertIs(first, second)
        self.assertEqual(catalog.loaded_sources, ("ascii",))
        with self.assertRaises(TypeError):
            first["new"] = first["A"]  # type: ignore[index]

    def test_missing_source_directory_has_assembly_context(self) -> None:
        catalog = GlyphCatalog(PROJECT_DIRECTORY)
        meta = load_font_meta(PROJECT_DIRECTORY, "ascii")
        missing_rule = replace(
            meta.source_rules[1],
            source_directory="math/unencoded",
        )
        meta = replace(meta, source_rules=(meta.source_rules[0], missing_rule))

        with self.assertRaisesRegex(
            AssemblyError,
            r"math[\\/]unencoded",
        ):
            assemble_font(meta, catalog)


class FontAssemblerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = GlyphCatalog(PROJECT_DIRECTORY)

    def test_existing_font_glyph_counts_match_reference(self) -> None:
        expected = {
            "ascii": (97, 96),
            "bold": (97, 96),
            "fraktur": (97, 96),
            "jp": (275, 274),
            "mono": (578, 577),
            "monobold": (549, 548),
            "script": (97, 96),
        }

        for build_name, (total, encoded) in expected.items():
            with self.subTest(build_name=build_name):
                assembled = assemble_font(
                    load_font_meta(PROJECT_DIRECTORY, build_name),
                    self.catalog,
                )
                self.assertEqual(
                    len(assembled.real_glyphs)
                    + len(assembled.generated_glyphs),
                    total,
                )
                self.assertEqual(
                    sum(
                        glyph.codepoint is not None
                        for glyph in assembled.real_glyphs.values()
                    )
                    + len(assembled.generated_glyphs),
                    encoded,
                )

    def test_source_mapping_replaces_only_glyph_identity(self) -> None:
        assembled = assemble_font(
            load_font_meta(PROJECT_DIRECTORY, "math"),
            self.catalog,
        )
        original_fraktur_a = self.catalog.load("fraktur")["A"]

        fraktur_a = next(
            glyph
            for glyph in assembled.real_glyphs.values()
            if glyph.codepoint == 0x1D504
        )
        self.assertEqual(fraktur_a.name, "A.fraktur")
        self.assertIsInstance(original_fraktur_a, GlyphSource)
        self.assertIsInstance(fraktur_a, AssembledGlyph)
        self.assertEqual(fraktur_a.codepoint, 0x1D504)
        self.assertEqual(original_fraktur_a.name, "A")
        self.assertEqual(original_fraktur_a.codepoint, 0x0041)
        self.assertIsNot(fraktur_a, original_fraktur_a)
        self.assertIs(fraktur_a.skeleton, original_fraktur_a.skeleton)
        self.assertEqual(fraktur_a.x_extent, original_fraktur_a.x_extent)
        self.assertEqual(fraktur_a.y_extent, original_fraktur_a.y_extent)
        self.assertEqual(fraktur_a.source_path, original_fraktur_a.source_path)

        italic_a = next(
            glyph
            for glyph in assembled.generated_glyphs
            if glyph.target_codepoint == 0x1D434
        )
        self.assertEqual(italic_a.source_name, "A")
        self.assertEqual(italic_a.target_name, "A.italic")

        equal = next(
            glyph
            for glyph in assembled.real_glyphs.values()
            if glyph.codepoint == 0x003D
        )
        equal_source = self.catalog.load("math")["equal"]
        self.assertIsInstance(equal, AssembledGlyph)
        self.assertIsInstance(equal_source, GlyphSource)
        self.assertIsNot(equal, equal_source)
        self.assertIs(equal.skeleton, equal_source.skeleton)
        self.assertEqual(equal.codepoint, equal_source.codepoint)
        self.assertIn("glyph_sources", str(equal.source_path))
        self.assertIn("math", equal.source_path.parts)
        self.assertEqual(len(assembled.generated_glyphs), 108)

    def test_source_rule_scales_strokes_without_mutating_source(
        self,
    ) -> None:
        meta = load_font_meta(PROJECT_DIRECTORY, "ascii")
        source = self.catalog.load("ascii")["A"]
        scaled_rule = replace(
            meta.source_rules[1],
            thickness_scale=0.75,
        )
        assembled = assemble_font(
            replace(
                meta,
                source_rules=(meta.source_rules[0], scaled_rule),
            ),
            self.catalog,
        )

        scaled = assembled.real_glyphs["A"]
        self.assertIsNot(scaled.skeleton, source.skeleton)
        self.assertEqual(len(scaled.skeleton), len(source.skeleton))
        for source_stroke, scaled_stroke in zip(
            source.skeleton,
            scaled.skeleton,
            strict=True,
        ):
            self.assertAlmostEqual(
                scaled_stroke.thickness_scale,
                source_stroke.thickness_scale * 0.75,
            )
            self.assertIsNot(scaled_stroke, source_stroke)

    def test_every_selected_source_crosses_assembly_type_boundary(self) -> None:
        assembled = assemble_font(
            load_font_meta(PROJECT_DIRECTORY, "ascii"),
            self.catalog,
        )

        self.assertTrue(
            all(
                isinstance(glyph, AssembledGlyph)
                for glyph in assembled.real_glyphs.values()
            )
        )
        self.assertTrue(
            all(
                name == glyph.name
                for name, glyph in assembled.real_glyphs.items()
            )
        )

    def test_unicode_domain_is_applied_before_merge(self) -> None:
        meta = load_font_meta(PROJECT_DIRECTORY, "ascii")
        uppercase_rule = replace(
            meta.source_rules[1],
            unicode_domain=UnicodeDomain(((0x0041, 0x005A),)),
        )
        uppercase_meta = replace(
            meta,
            source_rules=(meta.source_rules[0], uppercase_rule),
        )

        assembled = assemble_font(uppercase_meta, self.catalog)

        self.assertEqual(len(assembled.real_glyphs), 27)
        self.assertEqual(
            {
                glyph.codepoint
                for glyph in assembled.real_glyphs.values()
                if glyph.codepoint is not None
            },
            set(range(0x41, 0x5B)),
        )

    def test_unencoded_glyphs_require_explicit_opt_in(self) -> None:
        meta = load_font_meta(PROJECT_DIRECTORY, "math")
        math_rule = replace(
            meta.source_rules[4],
            replace_existing=False,
        )
        without_unencoded = replace(
            meta,
            source_rules=(
                meta.source_rules[0],
                replace(math_rule, include_unencoded=False),
            ),
            glyph_generators=(),
        )
        with_unencoded = replace(
            without_unencoded,
            source_rules=(
                meta.source_rules[0],
                replace(math_rule, include_unencoded=True),
            ),
        )

        encoded_only = assemble_font(without_unencoded, self.catalog)
        all_math = assemble_font(with_unencoded, self.catalog)

        added_names = (
            set(all_math.real_glyphs) - set(encoded_only.real_glyphs)
        )
        self.assertTrue(added_names)
        self.assertTrue(
            all(
                all_math.real_glyphs[name].codepoint is None
                for name in added_names
            )
        )
        self.assertEqual(
            {
                (glyph.name, glyph.codepoint)
                for glyph in encoded_only.real_glyphs.values()
                if glyph.codepoint is not None
            },
            {
                (glyph.name, glyph.codepoint)
                for glyph in all_math.real_glyphs.values()
                if glyph.codepoint is not None
            },
        )

    def test_conflict_requires_replace_existing(self) -> None:
        meta = load_font_meta(PROJECT_DIRECTORY, "ascii")
        notdef_rule = meta.source_rules[0]
        ascii_rule = meta.source_rules[1]
        conflicting_meta = replace(
            meta,
            source_rules=(notdef_rule, ascii_rule, ascii_rule),
        )

        with self.assertRaisesRegex(AssemblyError, "replace_existing"):
            assemble_font(conflicting_meta, self.catalog)

        replacing_meta = replace(
            meta,
            source_rules=(
                notdef_rule,
                ascii_rule,
                replace(ascii_rule, replace_existing=True),
            ),
        )
        assembled = assemble_font(replacing_meta, self.catalog)
        self.assertEqual(len(assembled.real_glyphs), 96)

    def test_notdef_is_required_after_assembly(self) -> None:
        meta = load_font_meta(PROJECT_DIRECTORY, "ascii")
        without_notdef = replace(meta, source_rules=(meta.source_rules[1],))

        with self.assertRaisesRegex(AssemblyError, r"\.notdef"):
            assemble_font(without_notdef, self.catalog)

    def test_assembled_real_glyphs_are_read_only(self) -> None:
        assembled = assemble_font(
            load_font_meta(PROJECT_DIRECTORY, "ascii"),
            self.catalog,
        )

        with self.assertRaises(TypeError):
            assembled.real_glyphs["new"] = (  # type: ignore[index]
                assembled.real_glyphs["A"]
            )

    def test_assembled_font_keeps_only_post_assembly_inputs(self) -> None:
        meta = load_font_meta(PROJECT_DIRECTORY, "ascii")
        assembled = assemble_font(meta, self.catalog)

        self.assertIs(assembled.info, meta.info)
        self.assertIs(assembled.glyph_parameters, meta.glyph_parameters)
        self.assertEqual(assembled.output_stem, "PL46-Ascii")
        self.assertEqual(
            assembled.point_radius_scale,
            meta.point_radius_scale,
        )
        self.assertFalse(hasattr(assembled, "meta"))

    def test_generator_sources_are_limited_to_real_glyphs(self) -> None:
        meta = replace(
            load_font_meta(PROJECT_DIRECTORY, "ascii"),
            glyph_generators=("first", "second"),
        )
        mappings = {
            "first": GlyphMapping(
                MappingProxyType({0x0041: 0xE000}),
                lambda source: f"{source.name}.first",
            ),
            "second": GlyphMapping(
                MappingProxyType({0xE000: 0xE001}),
                lambda source: f"{source.name}.second",
            ),
        }

        with patch(
            "skeletonfont.assembler.get_mapping",
            side_effect=lambda name: mappings[name],
        ):
            assembled = assemble_font(meta, self.catalog)

        self.assertEqual(len(assembled.generated_glyphs), 1)
        self.assertEqual(assembled.generated_glyphs[0].source_name, "A")
        self.assertEqual(assembled.generated_glyphs[0].target_name, "A.first")
        self.assertEqual(assembled.generated_glyphs[0].target_codepoint, 0xE000)

    def test_generator_mapping_can_produce_an_unencoded_glyph(self) -> None:
        meta = replace(
            load_font_meta(PROJECT_DIRECTORY, "ascii"),
            glyph_generators=("st",),
        )
        mapping = GlyphMapping(
            MappingProxyType({0x0041: None}),
            lambda source: f"{source.name}.st",
        )

        with patch("skeletonfont.assembler.get_mapping", return_value=mapping):
            assembled = assemble_font(meta, self.catalog)

        self.assertEqual(len(assembled.generated_glyphs), 1)
        generated = assembled.generated_glyphs[0]
        self.assertEqual(generated.source_name, "A")
        self.assertEqual(generated.target_name, "A.st")
        self.assertIsNone(generated.target_codepoint)

    def test_unicode_mappings_are_shared_and_read_only(self) -> None:
        first = get_mapping("upright_latin_to_italic_latin")
        second = get_mapping("upright_latin_to_italic_latin")

        self.assertIs(first, second)
        with self.assertRaises(TypeError):
            first.codepoints[0x0041] = 0x0041  # type: ignore[index]

    def test_script_latin_mapping_includes_unicode_exceptions(self) -> None:
        mapping = get_mapping("upright_latin_to_script_latin")

        self.assertEqual(len(mapping.codepoints), 52)
        self.assertEqual(mapping.codepoints[ord("A")], 0x1D49C)
        self.assertEqual(mapping.codepoints[ord("B")], 0x212C)
        self.assertEqual(mapping.codepoints[ord("R")], 0x211B)
        self.assertEqual(mapping.codepoints[ord("a")], 0x1D4B6)
        self.assertEqual(mapping.codepoints[ord("e")], 0x212F)
        self.assertEqual(mapping.codepoints[ord("g")], 0x210A)
        self.assertEqual(mapping.codepoints[ord("o")], 0x2134)
        self.assertEqual(mapping.codepoints[ord("z")], 0x1D4CF)
        self.assertEqual(
            mapping.apply(GlyphIdentity("B", 0x0042)),
            GlyphIdentity("B.script", 0x212C),
        )
        self.assertEqual(mapping.source_domain, "upright_latin")
        self.assertEqual(mapping.target_domain, "script_latin")

    def test_mapping_domain_validation_allows_unrestricted_sides(self) -> None:
        mapping = GlyphMapping(
            MappingProxyType({0xE000: 0xE001}),
            lambda source: f"{source.name}.alternate",
        )

        _validate_mapping_domains("unrestricted", mapping)

    def test_mapping_domain_validation_rejects_outliers(self) -> None:
        invalid_source = GlyphMapping(
            MappingProxyType({0x0030: 0x1D434}),
            lambda source: f"{source.name}.italic",
            source_domain="upright_latin",
            target_domain="italic_latin",
        )
        invalid_target = GlyphMapping(
            MappingProxyType({0x0041: 0x0030}),
            lambda source: f"{source.name}.italic",
            source_domain="upright_latin",
            target_domain="italic_latin",
        )

        with self.assertRaisesRegex(ValueError, "source codepoints outside"):
            _validate_mapping_domains("invalid-source", invalid_source)
        with self.assertRaisesRegex(ValueError, "target codepoints outside"):
            _validate_mapping_domains("invalid-target", invalid_target)


if __name__ == "__main__":
    unittest.main()
