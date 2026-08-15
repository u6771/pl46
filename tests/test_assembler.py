from __future__ import annotations

import unittest
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType
from unittest.mock import patch

from skeletonfont.assembler import (
    GlyphCatalog,
    _apply_ssty_generators,
    assemble_font,
)
from skeletonfont.errors import AssemblyError
from skeletonfont.loader import load_font_meta
from skeletonfont.mappings import (
    GlyphIdentity,
    GlyphMapping,
    _validate_mapping_domains,
    get_mapping,
)
from skeletonfont.model import (
    AssembledGlyph,
    GlyphSource,
    SstyGenerator,
    UnicodeDomain,
)


PROJECT_DIRECTORY = Path(__file__).resolve().parents[1]
FIXTURE_PROJECT_DIRECTORY = (
    PROJECT_DIRECTORY / "tests" / "fixtures" / "minimal_project"
)


class GlyphCatalogTests(unittest.TestCase):
    def test_source_directory_is_loaded_once(self) -> None:
        catalog = GlyphCatalog(FIXTURE_PROJECT_DIRECTORY)

        first = catalog.load("basic")
        second = catalog.load("basic")

        self.assertIs(first, second)
        self.assertEqual(catalog.loaded_sources, ("basic",))
        with self.assertRaises(TypeError):
            first["new"] = first["A"]  # type: ignore[index]

    def test_missing_source_directory_has_assembly_context(self) -> None:
        catalog = GlyphCatalog(FIXTURE_PROJECT_DIRECTORY)
        meta = load_font_meta(FIXTURE_PROJECT_DIRECTORY, "basic")
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

    def test_all_project_fonts_assemble_with_notdef(self) -> None:
        for meta_path in sorted((PROJECT_DIRECTORY / "meta").glob("*.json")):
            build_name = meta_path.stem
            with self.subTest(build_name=build_name):
                assembled = assemble_font(
                    load_font_meta(PROJECT_DIRECTORY, build_name),
                    self.catalog,
                )
                self.assertIn(".notdef", assembled.glyphs)
                self.assertIsNone(assembled.glyphs[".notdef"].codepoint)
                self.assertGreater(len(assembled.glyphs), 0)

    def test_source_mapping_replaces_only_glyph_identity(self) -> None:
        assembled = assemble_font(
            load_font_meta(PROJECT_DIRECTORY, "math"),
            self.catalog,
        )
        original_fraktur_a = self.catalog.load("fraktur")["A"]

        fraktur_a = next(
            glyph
            for glyph in assembled.glyphs.values()
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
            alias
            for alias in assembled.glyph_aliases
            if alias.target_codepoint == 0x1D434
        )
        self.assertEqual(italic_a.source_name, "A")
        self.assertEqual(italic_a.target_name, "A.italic")

        equal = next(
            glyph
            for glyph in assembled.glyphs.values()
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
        self.assertEqual(len(assembled.glyph_aliases), 108)

    def test_source_rule_scales_strokes_without_mutating_source(
        self,
    ) -> None:
        catalog = GlyphCatalog(FIXTURE_PROJECT_DIRECTORY)
        meta = load_font_meta(FIXTURE_PROJECT_DIRECTORY, "basic")
        source = catalog.load("basic")["A"]
        scaled_rule = replace(
            meta.source_rules[1],
            thickness_scale=0.75,
        )
        assembled = assemble_font(
            replace(
                meta,
                source_rules=(meta.source_rules[0], scaled_rule),
            ),
            catalog,
        )

        scaled = assembled.glyphs["A"]
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

    def test_source_rule_monospace_width_follows_final_selected_glyph(self) -> None:
        catalog = GlyphCatalog(FIXTURE_PROJECT_DIRECTORY)
        meta = load_font_meta(FIXTURE_PROJECT_DIRECTORY, "basic")
        parameters = replace(meta.glyph_parameters, monospace_width=None)
        local_rule = replace(meta.source_rules[1], monospace_width=550)

        local = assemble_font(
            replace(
                meta,
                glyph_parameters=parameters,
                source_rules=(meta.source_rules[0], local_rule),
            ),
            catalog,
        )

        self.assertEqual(local.glyphs["A"].ordinary_monospace_width, 550)
        self.assertIsNone(
            local.glyphs[".notdef"].ordinary_monospace_width
        )

        replaced = assemble_font(
            replace(
                meta,
                glyph_parameters=parameters,
                source_rules=(
                    meta.source_rules[0],
                    local_rule,
                    replace(
                        local_rule,
                        replace_existing=True,
                        monospace_width=None,
                    ),
                ),
            ),
            catalog,
        )

        self.assertIsNone(replaced.glyphs["A"].ordinary_monospace_width)

        math_meta = load_font_meta(PROJECT_DIRECTORY, "math")
        fraktur_rule = next(
            rule
            for rule in math_meta.source_rules
            if rule.mapping_name == "upright_latin_to_fraktur_latin"
        )
        mapped = assemble_font(
            replace(
                math_meta,
                source_rules=tuple(
                    replace(rule, monospace_width=525)
                    if rule is fraktur_rule
                    else rule
                    for rule in math_meta.source_rules
                ),
            ),
            self.catalog,
        )

        self.assertEqual(
            mapped.glyphs["A.fraktur"].ordinary_monospace_width,
            525,
        )

    def test_ssty_generators_derive_glyph_and_alias_bases(self) -> None:
        assembled = assemble_font(
            load_font_meta(PROJECT_DIRECTORY, "math"),
            self.catalog,
        )

        self.assertEqual(
            assembled.ssty_substitutions["A"],
            ("A.st",),
        )
        self.assertEqual(
            assembled.ssty_substitutions["A.italic"],
            ("A.italic.st",),
        )
        self.assertNotIn("A.st.sts", assembled.glyphs)
        self.assertIsNone(assembled.glyphs["A.st"].codepoint)
        self.assertIsNone(assembled.glyphs["A.italic.st"].codepoint)
        self.assertEqual(assembled.ssty_alternate_sources["A.st"], "A")
        self.assertEqual(
            assembled.ssty_alternate_sources["A.italic.st"],
            "A",
        )
        with self.assertRaises(TypeError):
            assembled.ssty_substitutions["new"] = (  # type: ignore[index]
                "new.st",
            )
        with self.assertRaises(TypeError):
            assembled.ssty_alternate_sources["new.st"] = "new"  # type: ignore[index]

        source = assembled.glyphs["A"]
        alternate = assembled.glyphs["A.st"]
        for source_stroke, alternate_stroke in zip(
            source.skeleton,
            alternate.skeleton,
            strict=True,
        ):
            self.assertAlmostEqual(
                alternate_stroke.thickness_scale,
                source_stroke.thickness_scale * 1.2,
            )

    def test_ssty_generator_scaling_multiplies_source_rule_scaling(self) -> None:
        catalog = GlyphCatalog(FIXTURE_PROJECT_DIRECTORY)
        meta = load_font_meta(FIXTURE_PROJECT_DIRECTORY, "basic")
        scaled_source = replace(
            meta.source_rules[1],
            thickness_scale=1.25,
        )
        ssty_generator = SstyGenerator(
            UnicodeDomain(((0x0041, 0x0041),)),
            "st",
            1.4,
            None,
        )

        assembled = assemble_font(
            replace(
                meta,
                source_rules=(meta.source_rules[0], scaled_source),
                ssty_generators=(ssty_generator,),
            ),
            catalog,
        )

        authored = catalog.load("basic")["A"]
        alternate = assembled.glyphs["A.st"]
        for authored_stroke, alternate_stroke in zip(
            authored.skeleton,
            alternate.skeleton,
            strict=True,
        ):
            self.assertAlmostEqual(
                alternate_stroke.thickness_scale,
                authored_stroke.thickness_scale * 1.25 * 1.4,
            )

    def test_ssty_generator_owns_its_alternate_monospace_width(self) -> None:
        catalog = GlyphCatalog(FIXTURE_PROJECT_DIRECTORY)
        meta = load_font_meta(FIXTURE_PROJECT_DIRECTORY, "basic")
        parameters = replace(meta.glyph_parameters, monospace_width=None)
        local_rule = replace(meta.source_rules[1], monospace_width=600)
        domain = UnicodeDomain(((0x0041, 0x0041),))

        proportional_alternate = assemble_font(
            replace(
                meta,
                glyph_parameters=parameters,
                source_rules=(meta.source_rules[0], local_rule),
                ssty_generators=(
                    SstyGenerator(domain, "st", 1.2, None),
                ),
            ),
            catalog,
        )

        self.assertEqual(
            proportional_alternate.glyphs["A"].ordinary_monospace_width,
            600,
        )
        self.assertIsNone(
            proportional_alternate.glyphs["A.st"].ordinary_monospace_width
        )

        fixed_alternate = assemble_font(
            replace(
                meta,
                glyph_parameters=parameters,
                source_rules=(meta.source_rules[0], local_rule),
                ssty_generators=(
                    SstyGenerator(domain, "st", 1.2, 450),
                    SstyGenerator(domain, "sts", 1.4, 350),
                ),
            ),
            catalog,
        )

        self.assertEqual(
            fixed_alternate.glyphs["A.st"].ordinary_monospace_width,
            450,
        )
        self.assertEqual(
            fixed_alternate.glyphs["A.sts"].ordinary_monospace_width,
            350,
        )

    def test_ssty_generators_skip_missing_codepoints(self) -> None:
        meta = load_font_meta(PROJECT_DIRECTORY, "ascii")
        assembled = assemble_font(
            replace(
                meta,
                ssty_generators=(
                    SstyGenerator(
                        UnicodeDomain(((0xE000, 0xE000),)),
                        "st",
                        1.4,
                        None,
                    ),
                ),
            ),
            self.catalog,
        )

        self.assertEqual(dict(assembled.ssty_substitutions), {})
        self.assertEqual(dict(assembled.ssty_alternate_sources), {})

    def test_empty_ssty_domain_is_an_explicit_noop(self) -> None:
        meta = load_font_meta(PROJECT_DIRECTORY, "ascii")
        assembled = assemble_font(
            replace(
                meta,
                ssty_generators=(
                    SstyGenerator(UnicodeDomain(()), "st", 1.4, None),
                ),
            ),
            self.catalog,
        )

        self.assertEqual(dict(assembled.ssty_substitutions), {})
        self.assertEqual(dict(assembled.ssty_alternate_sources), {})

    def test_ssty_generators_do_not_mutate_input_glyph_mapping(self) -> None:
        meta = load_font_meta(PROJECT_DIRECTORY, "ascii")
        assembled = assemble_font(
            replace(meta, ssty_generators=()),
            self.catalog,
        )
        glyphs_by_name = dict(assembled.glyphs)
        glyphs_by_codepoint = {
            glyph.codepoint: glyph
            for glyph in assembled.glyphs.values()
            if glyph.codepoint is not None
        }
        original_glyphs = dict(glyphs_by_name)

        result = _apply_ssty_generators(
            glyphs_by_name,
            glyphs_by_codepoint,
            assembled.glyph_aliases,
            (
                SstyGenerator(
                    UnicodeDomain(((0x0041, 0x0041),)),
                    "st",
                    1.4,
                    None,
                ),
            ),
        )

        self.assertEqual(glyphs_by_name, original_glyphs)
        self.assertIn("A.st", result.glyphs)

    def test_ssty_generators_reject_unknown_names_collisions_and_third_level(
        self,
    ) -> None:
        meta = load_font_meta(PROJECT_DIRECTORY, "ascii")
        domain = UnicodeDomain(((0x0041, 0x0041),))

        with self.assertRaisesRegex(AssemblyError, "Unknown ssty"):
            assemble_font(
                replace(
                    meta,
                    ssty_generators=(
                        SstyGenerator(domain, "unknown", 1.4, None),
                    ),
                ),
                self.catalog,
            )

        with self.assertRaisesRegex(AssemblyError, "already in use"):
            assemble_font(
                replace(
                    meta,
                    ssty_generators=(
                        SstyGenerator(domain, "st", 1.4, None),
                        SstyGenerator(domain, "st", 1.6, None),
                    ),
                ),
                self.catalog,
            )

        with self.assertRaisesRegex(AssemblyError, "more than two"):
            assemble_font(
                replace(
                    meta,
                    ssty_generators=(
                        SstyGenerator(domain, "st", 1.2, None),
                        SstyGenerator(domain, "sts", 1.4, None),
                        SstyGenerator(domain, "st", 1.6, None),
                    ),
                ),
                self.catalog,
            )

    def test_every_selected_source_crosses_assembly_type_boundary(self) -> None:
        assembled = assemble_font(
            load_font_meta(PROJECT_DIRECTORY, "ascii"),
            self.catalog,
        )

        self.assertTrue(
            all(
                isinstance(glyph, AssembledGlyph)
                for glyph in assembled.glyphs.values()
            )
        )
        self.assertTrue(
            all(
                name == glyph.name
                for name, glyph in assembled.glyphs.items()
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

        self.assertEqual(len(assembled.glyphs), 27)
        self.assertEqual(
            {
                glyph.codepoint
                for glyph in assembled.glyphs.values()
                if glyph.codepoint is not None
            },
            set(range(0x41, 0x5B)),
        )

    def test_empty_unicode_domain_can_select_only_unencoded_glyphs(self) -> None:
        meta = load_font_meta(PROJECT_DIRECTORY, "math")
        math_rule = next(
            rule
            for rule in meta.source_rules
            if rule.source_directory == "math"
        )
        unencoded_math_rule = replace(
            math_rule,
            unicode_domain=UnicodeDomain(()),
            include_unencoded=True,
            replace_existing=False,
        )
        unencoded_meta = replace(
            meta,
            source_rules=(meta.source_rules[0], unencoded_math_rule),
            glyph_alias_generators=(),
            ssty_generators=(),
        )

        assembled = assemble_font(unencoded_meta, self.catalog)

        self.assertGreater(len(assembled.glyphs), 1)
        self.assertTrue(
            all(glyph.codepoint is None for glyph in assembled.glyphs.values())
        )

    def test_unencoded_glyphs_require_explicit_opt_in(self) -> None:
        meta = load_font_meta(PROJECT_DIRECTORY, "math")
        source_rule = next(
            rule
            for rule in meta.source_rules
            if rule.source_directory == "math"
        )
        math_rule = replace(
            source_rule,
            replace_existing=False,
        )
        without_unencoded = replace(
            meta,
            source_rules=(
                meta.source_rules[0],
                replace(math_rule, include_unencoded=False),
            ),
            glyph_alias_generators=(),
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
            set(all_math.glyphs) - set(encoded_only.glyphs)
        )
        self.assertTrue(added_names)
        self.assertTrue(
            all(
                all_math.glyphs[name].codepoint is None
                for name in added_names
            )
        )
        self.assertEqual(
            {
                (glyph.name, glyph.codepoint)
                for glyph in encoded_only.glyphs.values()
                if glyph.codepoint is not None
            },
            {
                (glyph.name, glyph.codepoint)
                for glyph in all_math.glyphs.values()
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
        self.assertEqual(len(assembled.glyphs), 96)

    def test_notdef_is_required_after_assembly(self) -> None:
        meta = load_font_meta(PROJECT_DIRECTORY, "ascii")
        without_notdef = replace(meta, source_rules=(meta.source_rules[1],))

        with self.assertRaisesRegex(AssemblyError, r"\.notdef"):
            assemble_font(without_notdef, self.catalog)

    def test_assembled_glyphs_are_read_only(self) -> None:
        assembled = assemble_font(
            load_font_meta(PROJECT_DIRECTORY, "ascii"),
            self.catalog,
        )

        with self.assertRaises(TypeError):
            assembled.glyphs["new"] = (  # type: ignore[index]
                assembled.glyphs["A"]
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

    def test_alias_generator_sources_are_limited_to_assembled_glyphs(self) -> None:
        meta = replace(
            load_font_meta(PROJECT_DIRECTORY, "ascii"),
            glyph_alias_generators=("first", "second"),
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

        self.assertEqual(len(assembled.glyph_aliases), 1)
        self.assertEqual(assembled.glyph_aliases[0].source_name, "A")
        self.assertEqual(assembled.glyph_aliases[0].target_name, "A.first")
        self.assertEqual(assembled.glyph_aliases[0].target_codepoint, 0xE000)

    def test_generator_mapping_can_produce_an_unencoded_glyph(self) -> None:
        meta = replace(
            load_font_meta(PROJECT_DIRECTORY, "ascii"),
            glyph_alias_generators=("st",),
        )
        mapping = GlyphMapping(
            MappingProxyType({0x0041: None}),
            lambda source: f"{source.name}.st",
        )

        with patch("skeletonfont.assembler.get_mapping", return_value=mapping):
            assembled = assemble_font(meta, self.catalog)

        self.assertEqual(len(assembled.glyph_aliases), 1)
        alias = assembled.glyph_aliases[0]
        self.assertEqual(alias.source_name, "A")
        self.assertEqual(alias.target_name, "A.st")
        self.assertIsNone(alias.target_codepoint)

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

    def test_ascii_digits_map_to_mathematical_bold_digits(self) -> None:
        mapping = get_mapping("ascii_digits_to_bold_digits")

        self.assertEqual(len(mapping.codepoints), 10)
        self.assertEqual(mapping.codepoints[ord("0")], 0x1D7CE)
        self.assertEqual(mapping.codepoints[ord("9")], 0x1D7D7)
        self.assertEqual(
            mapping.apply(GlyphIdentity("zero", 0x0030)),
            GlyphIdentity("zero.bold", 0x1D7CE),
        )
        self.assertEqual(mapping.source_domain, "ascii_digits")
        self.assertEqual(mapping.target_domain, "bold_digits")

    def test_mapping_domain_validation_allows_unrestricted_sides(self) -> None:
        mapping = GlyphMapping(
            MappingProxyType({0xE000: 0xE001}),
            lambda source: f"{source.name}.alternate",
        )

        _validate_mapping_domains("unrestricted", mapping)

    def test_mapping_domain_validation_rejects_duplicate_targets(self) -> None:
        mapping = GlyphMapping(
            MappingProxyType({0x0041: 0xE000, 0x0042: 0xE000}),
            lambda identity: identity.name,
        )

        with self.assertRaisesRegex(ValueError, "duplicate encoded target"):
            _validate_mapping_domains("duplicates", mapping)

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
