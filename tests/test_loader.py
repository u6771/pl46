from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from unittest.mock import patch

from skeletonfont.errors import ProjectDataError
from skeletonfont.loader import (
    META_FIELD_ORDER,
    _parse_math_variants_axis,
    load_accent_glyphs,
    load_build_list,
    load_font_meta,
    load_glyph_source,
    load_kerning_data,
    load_math_table_data,
    load_release_info,
    load_ssty_data,
    normalize_meta_name,
    parse_font_meta,
    parse_accent_glyphs,
    parse_glyph_source,
    parse_kerning_data,
    parse_math_accent_attachments,
    parse_math_constants,
    parse_math_italics_correction,
    parse_math_kerns,
    parse_release_info,
    parse_ssty,
    parse_stroke_record,
    read_json,
)
from skeletonfont.unicode_domains import UNICODE_DOMAINS


PROJECT_DIRECTORY = Path(__file__).resolve().parents[1]
FIXTURE_SOURCE_DIRECTORY = (
    PROJECT_DIRECTORY
    / "tests"
    / "fixtures"
    / "minimal_project"
    / "glyph_sources"
    / "basic"
)


class FontMetaLoaderTests(unittest.TestCase):
    def test_json_rejects_duplicate_object_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "duplicate.json"
            path.write_text('{"A": 1, "A": 2}', encoding="utf-8")

            with self.assertRaisesRegex(ProjectDataError, "duplicate.*'A'"):
                read_json(path)

    def test_meta_name_cannot_be_only_json_extension(self) -> None:
        with self.assertRaisesRegex(ProjectDataError, "non-empty"):
            normalize_meta_name(".json")

    def test_blackboard_domain_ends_at_double_struck_z(self) -> None:
        domain = UNICODE_DOMAINS["blackboard_latin"]

        self.assertIn(0x1D56B, domain)
        self.assertNotIn(0x1D56C, domain)

    def test_all_copied_meta_files_load(self) -> None:
        paths = sorted((PROJECT_DIRECTORY / "meta").glob("*.json"))

        loaded = [
            load_font_meta(PROJECT_DIRECTORY, path.stem)
            for path in paths
        ]

        self.assertEqual(len(loaded), 8)
        self.assertEqual(
            {meta.build_name for meta in loaded},
            {path.stem for path in paths},
        )

    def test_meta_files_follow_canonical_field_order(self) -> None:
        order = {
            field: index
            for index, field in enumerate(META_FIELD_ORDER)
        }
        for path in sorted((PROJECT_DIRECTORY / "meta").glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            positions = [order[field] for field in data]
            self.assertEqual(
                positions,
                sorted(positions),
                msg=str(path),
            )

    def test_fakebold_tracks_regular_except_identity_and_thickness(self) -> None:
        regular_path = PROJECT_DIRECTORY / "meta" / "regular.json"
        fakebold_path = PROJECT_DIRECTORY / "meta" / "fakebold.json"
        regular = json.loads(regular_path.read_text(encoding="utf-8"))
        fakebold = json.loads(fakebold_path.read_text(encoding="utf-8"))

        expected = {
            **regular,
            "style": "FakeBold",
            "weight_class": 700,
            "thickness": 100,
        }
        self.assertEqual(fakebold, expected)

    def test_omitted_unicode_domain_is_unrestricted(self) -> None:
        meta = load_font_meta(PROJECT_DIRECTORY, "regular")

        self.assertIsNone(meta.source_rules[1].unicode_domain)

    def test_unicode_domain_unions_names_ranges_and_singletons(self) -> None:
        path = PROJECT_DIRECTORY / "meta" / "ascii.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["source_rules"][1]["unicode_domain"] = [
            "upright_latin",
            ["0050", "0065"],
            ["2202"],
        ]

        meta = parse_font_meta(
            data,
            build_name="domain-union",
            meta_path=path,
        )

        domain = meta.source_rules[1].unicode_domain
        self.assertIsNotNone(domain)
        assert domain is not None
        self.assertEqual(
            domain.ranges,
            ((0x0041, 0x007A), (0x2202, 0x2202)),
        )

    def test_ascii_digits_unicode_domain(self) -> None:
        path = PROJECT_DIRECTORY / "meta" / "ascii.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["source_rules"][1]["unicode_domain"] = "ascii_digits"

        meta = parse_font_meta(
            data,
            build_name="ascii-digits",
            meta_path=path,
        )

        domain = meta.source_rules[1].unicode_domain
        self.assertIsNotNone(domain)
        assert domain is not None
        self.assertEqual(domain.ranges, ((0x0030, 0x0039),))

    def test_unicode_domain_keeps_full_range_compact(self) -> None:
        path = PROJECT_DIRECTORY / "meta" / "ascii.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["source_rules"][1]["unicode_domain"] = [
            ["0000", "10FFFF"]
        ]

        meta = parse_font_meta(
            data,
            build_name="full-domain",
            meta_path=path,
        )

        domain = meta.source_rules[1].unicode_domain
        self.assertIsNotNone(domain)
        assert domain is not None
        self.assertEqual(domain.ranges, ((0, 0x10FFFF),))

    def test_unicode_domain_string_items_are_names(self) -> None:
        path = PROJECT_DIRECTORY / "meta" / "ascii.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["source_rules"][1]["unicode_domain"] = ["0041"]

        with self.assertRaisesRegex(
            ProjectDataError,
            "unknown Unicode domain '0041'",
        ):
            parse_font_meta(
                data,
                build_name="unknown-domain",
                meta_path=path,
            )

    def test_empty_unicode_domain_selects_no_encoded_glyphs(self) -> None:
        path = PROJECT_DIRECTORY / "meta" / "ascii.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["source_rules"][1]["unicode_domain"] = []

        meta = parse_font_meta(
            data,
            build_name="empty-domain",
            meta_path=path,
        )

        domain = meta.source_rules[1].unicode_domain
        self.assertIsNotNone(domain)
        assert domain is not None
        self.assertEqual(domain.ranges, ())

    def test_math_table_config_uses_normalized_json_names(self) -> None:
        meta = load_font_meta(PROJECT_DIRECTORY, "math")

        self.assertIsNotNone(meta.math_table)
        assert meta.math_table is not None
        self.assertEqual(meta.math_table.constants_file, "math.json")
        self.assertEqual(
            meta.math_table.variants_file,
            "math.json",
        )
        self.assertEqual(meta.ssty_file, "math.json")
        self.assertEqual(
            meta.math_table.italics_correction_file,
            "math.json",
        )
        self.assertEqual(
            meta.math_table.accent_attachment_file,
            "math.json",
        )

    def test_model_names_express_source_rule_behavior(self) -> None:
        meta = load_font_meta(PROJECT_DIRECTORY, "math")
        math_rule = next(
            rule
            for rule in meta.source_rules
            if rule.source_directory == "math"
        )

        self.assertEqual(meta.build_name, "math")
        self.assertEqual(meta.meta_path.name, "math.json")
        self.assertIsNone(meta.glyph_parameters.monospace_width)
        self.assertEqual(meta.glyph_parameters.radius, 25)
        self.assertEqual(
            meta.glyph_alias_generators,
            (
                "upright_latin_to_italic_latin",
                "upright_greek_to_italic_greek",
            ),
        )
        self.assertEqual(meta.glyph_config_file, "math.json")
        self.assertEqual(meta.accent_file, "math.json")
        self.assertEqual(meta.output_stem, "PL46-Math")
        self.assertEqual(meta.info.weight_class, 400)
        self.assertEqual(meta.release_info_file, "pl46.json")
        self.assertTrue(meta.glyph_parameters.use_scaled_edge_thickness)
        self.assertEqual(math_rule.source_directory, "math")
        self.assertTrue(math_rule.replace_existing)
        self.assertIsNone(math_rule.mapping_name)
        self.assertEqual(math_rule.thickness_scale, 1)
        self.assertEqual(
            [
                (generator.ssty_alternate_name, generator.thickness_scale)
                for generator in meta.ssty_generators
            ],
            [("st", 1.2)],
        )
        assert meta.ssty_generators[0].unicode_domain is not None
        self.assertIn(0x0041, meta.ssty_generators[0].unicode_domain)
        self.assertIn(0x1D434, meta.ssty_generators[0].unicode_domain)

    def test_ssty_generators_require_valid_complete_fields(self) -> None:
        path = PROJECT_DIRECTORY / "meta" / "ascii.json"
        original = json.loads(path.read_text(encoding="utf-8"))
        valid_generator = {
            "unicode_domain": "upright_latin",
            "ssty_alternate_name": "st",
            "thickness_scale": 1.4,
        }
        data = dict(original)
        data["ssty_generators"] = [valid_generator]

        meta = parse_font_meta(
            data,
            build_name="ssty-generator",
            meta_path=path,
        )

        self.assertEqual(len(meta.ssty_generators), 1)
        self.assertEqual(meta.ssty_generators[0].ssty_alternate_name, "st")
        self.assertEqual(meta.ssty_generators[0].thickness_scale, 1.4)

        empty_domain_data = dict(original)
        empty_domain_data["ssty_generators"] = [
            {**valid_generator, "unicode_domain": []}
        ]
        empty_domain_meta = parse_font_meta(
            empty_domain_data,
            build_name="empty-ssty-domain",
            meta_path=path,
        )
        self.assertEqual(
            empty_domain_meta.ssty_generators[0].unicode_domain.ranges,
            (),
        )

        for field in valid_generator:
            with self.subTest(missing=field):
                invalid = dict(original)
                invalid["ssty_generators"] = [
                    {
                        key: value
                        for key, value in valid_generator.items()
                        if key != field
                    }
                ]
                with self.assertRaisesRegex(
                    ProjectDataError,
                    "missing required fields",
                ):
                    parse_font_meta(
                        invalid,
                        build_name="invalid-ssty-generator",
                        meta_path=path,
                    )

        for value in (None, True, "1.4", 0, -1, float("inf")):
            with self.subTest(thickness_scale=value):
                invalid = dict(original)
                invalid["ssty_generators"] = [
                    {**valid_generator, "thickness_scale": value}
                ]
                with self.assertRaisesRegex(
                    ProjectDataError,
                    "thickness_scale",
                ):
                    parse_font_meta(
                        invalid,
                        build_name="invalid-ssty-scale",
                        meta_path=path,
                    )

        unknown = dict(original)
        unknown["ssty_generators"] = [
            {**valid_generator, "unexpected": 1}
        ]
        with self.assertRaisesRegex(ProjectDataError, "unexpected"):
            parse_font_meta(
                unknown,
                build_name="unknown-ssty-field",
                meta_path=path,
            )

    def test_source_rule_thickness_scale_is_positive(self) -> None:
        path = PROJECT_DIRECTORY / "meta" / "ascii.json"
        original = json.loads(path.read_text(encoding="utf-8"))

        scaled = json.loads(path.read_text(encoding="utf-8"))
        scaled["source_rules"][1]["thickness_scale"] = 0.75
        meta = parse_font_meta(
            scaled,
            build_name="scaled",
            meta_path=path,
        )
        self.assertEqual(meta.source_rules[1].thickness_scale, 0.75)

        for value in (None, True, "0.75", 0, -1, float("inf")):
            with self.subTest(value=value):
                invalid = dict(original)
                invalid["source_rules"] = [
                    dict(rule) for rule in original["source_rules"]
                ]
                invalid["source_rules"][1]["thickness_scale"] = value
                with self.assertRaisesRegex(
                    ProjectDataError,
                    "thickness_scale",
                ):
                    parse_font_meta(
                        invalid,
                        build_name="invalid-scale",
                        meta_path=path,
                    )

    def test_disabled_math_is_none(self) -> None:
        meta = load_font_meta(PROJECT_DIRECTORY, "ascii")

        self.assertIsNone(meta.math_table)

    def test_math_table_requires_explicit_constants_file(self) -> None:
        path = PROJECT_DIRECTORY / "meta" / "ascii.json"
        original = json.loads(path.read_text(encoding="utf-8"))

        for math_table in ({}, {"variants_file": "math.json"}):
            with self.subTest(math_table=math_table):
                data = dict(original)
                data["math_table"] = math_table
                with self.assertRaisesRegex(
                    ProjectDataError,
                    "missing required fields.*constants_file",
                ):
                    parse_font_meta(
                        data,
                        build_name="missing-math-constants",
                        meta_path=path,
                    )

    def test_math_table_does_not_accept_enabled_switch(self) -> None:
        path = PROJECT_DIRECTORY / "meta" / "ascii.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["math_table"] = {"enabled": False}

        with self.assertRaisesRegex(ProjectDataError, "enabled"):
            parse_font_meta(
                data,
                build_name="broken",
                meta_path=path,
            )

    def test_optional_meta_fields_use_canonical_defaults(self) -> None:
        path = PROJECT_DIRECTORY / "meta" / "ascii.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        for key in (
            "y_shift",
            "left_spacing",
            "right_spacing",
            "monospace_width",
            "point_radius_scale",
            "use_scaled_edge_thickness",
            "glyph_alias_generators",
            "ssty_generators",
            "glyph_config_file",
            "accent_file",
            "kerning_file",
            "ssty_file",
            "release_info_file",
            "output_stem",
            "math_table",
        ):
            data.pop(key, None)

        meta = parse_font_meta(
            data,
            build_name="defaults",
            meta_path=path,
        )

        self.assertEqual(meta.glyph_parameters.y_shift, 0)
        self.assertEqual(meta.glyph_parameters.left_spacing, 0)
        self.assertEqual(meta.glyph_parameters.right_spacing, 0)
        self.assertIsNone(meta.glyph_parameters.monospace_width)
        self.assertEqual(meta.point_radius_scale, 1.6)
        self.assertTrue(
            meta.glyph_parameters.use_scaled_edge_thickness
        )
        self.assertEqual(meta.glyph_alias_generators, ())
        self.assertEqual(meta.ssty_generators, ())
        self.assertIsNone(meta.glyph_config_file)
        self.assertIsNone(meta.accent_file)
        self.assertIsNone(meta.kerning_file)
        self.assertIsNone(meta.ssty_file)
        self.assertIsNone(meta.release_info_file)
        self.assertEqual(meta.output_stem, "PL46-Ascii")
        self.assertIsNone(meta.math_table)

    def test_meta_fields_reject_explicit_null(self) -> None:
        path = PROJECT_DIRECTORY / "meta" / "ascii.json"
        original = json.loads(path.read_text(encoding="utf-8"))

        top_level_fields = (
            "output_stem",
            "glyph_alias_generators",
            "ssty_generators",
            "glyph_config_file",
            "accent_file",
            "kerning_file",
            "ssty_file",
            "release_info_file",
            "math_table",
        )
        for field in top_level_fields:
            with self.subTest(field=field):
                data = dict(original)
                data[field] = None
                with self.assertRaisesRegex(ProjectDataError, field):
                    parse_font_meta(
                        data,
                        build_name="null-meta-field",
                        meta_path=path,
                    )

        for field in ("unicode_domain", "mapping_name"):
            with self.subTest(source_rule_field=field):
                data = json.loads(path.read_text(encoding="utf-8"))
                data["source_rules"][1][field] = None
                with self.assertRaisesRegex(ProjectDataError, field):
                    parse_font_meta(
                        data,
                        build_name="null-source-rule-field",
                        meta_path=path,
                    )

        math_file_fields = (
            "variants_file",
            "italics_correction_file",
            "accent_attachment_file",
            "kern_file",
        )
        for field in math_file_fields:
            with self.subTest(math_file_field=field):
                data = dict(original)
                data["math_table"] = {
                    "constants_file": "math.json",
                    field: None,
                }
                with self.assertRaisesRegex(ProjectDataError, field):
                    parse_font_meta(
                        data,
                        build_name="null-math-file-field",
                        meta_path=path,
                    )

        data = dict(original)
        data["ssty_generators"] = [
            {
                "unicode_domain": None,
                "ssty_alternate_name": "st",
                "thickness_scale": 1.2,
            }
        ]
        with self.assertRaisesRegex(ProjectDataError, "unicode_domain"):
            parse_font_meta(
                data,
                build_name="null-ssty-domain",
                meta_path=path,
            )

    def test_required_meta_field_cannot_be_omitted(self) -> None:
        path = PROJECT_DIRECTORY / "meta" / "ascii.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        del data["grid"]

        with self.assertRaisesRegex(ProjectDataError, "grid"):
            parse_font_meta(
                data,
                build_name="broken",
                meta_path=path,
            )

    def test_weight_class_is_required_and_bounded(self) -> None:
        path = PROJECT_DIRECTORY / "meta" / "bold.json"
        original = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(
            parse_font_meta(
                original,
                build_name="bold",
                meta_path=path,
            ).info.weight_class,
            700,
        )

        for value in (None, True, 0, 1001, "700"):
            with self.subTest(value=value):
                data = dict(original)
                if value is None:
                    del data["weight_class"]
                else:
                    data["weight_class"] = value
                with self.assertRaisesRegex(
                    ProjectDataError,
                    "weight_class",
                ):
                    parse_font_meta(
                        data,
                        build_name="broken-weight",
                        meta_path=path,
                    )

    def test_math_table_rejects_legacy_variant_fields(self) -> None:
        path = PROJECT_DIRECTORY / "meta" / "ascii.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["math_table"] = {"variant_glyphs_file": "math.json"}

        with self.assertRaisesRegex(ProjectDataError, "variant_glyphs_file"):
            parse_font_meta(data, build_name="ascii", meta_path=path)

    def test_monospace_width_presence_selects_metric_mode(self) -> None:
        path = PROJECT_DIRECTORY / "meta" / "ascii.json"
        data = json.loads(path.read_text(encoding="utf-8"))

        mono = parse_font_meta(data, build_name="mono", meta_path=path)
        self.assertEqual(mono.glyph_parameters.monospace_width, 600)

        del data["monospace_width"]
        proportional = parse_font_meta(
            data,
            build_name="proportional",
            meta_path=path,
        )
        self.assertIsNone(proportional.glyph_parameters.monospace_width)

    def test_fixed_pitch_requires_monospace_without_math(self) -> None:
        mono_path = PROJECT_DIRECTORY / "meta" / "regular.json"
        mono_data = json.loads(mono_path.read_text(encoding="utf-8"))

        mono = parse_font_meta(
            mono_data,
            build_name="regular",
            meta_path=mono_path,
        )
        self.assertTrue(mono.info.is_fixed_pitch)

        mono_with_math_data = dict(mono_data)
        mono_with_math_data["math_table"] = {
            "constants_file": "math.json",
        }
        mono_with_math = parse_font_meta(
            mono_with_math_data,
            build_name="mono-with-math",
            meta_path=mono_path,
        )
        self.assertFalse(mono_with_math.info.is_fixed_pitch)

        proportional_data = dict(mono_data)
        del proportional_data["monospace_width"]
        proportional = parse_font_meta(
            proportional_data,
            build_name="proportional",
            meta_path=mono_path,
        )
        self.assertFalse(proportional.info.is_fixed_pitch)

    def test_monospace_width_must_be_positive_when_present(self) -> None:
        path = PROJECT_DIRECTORY / "meta" / "ascii.json"
        data = json.loads(path.read_text(encoding="utf-8"))

        for value in (None, 0, -1):
            with self.subTest(value=value):
                data["monospace_width"] = value
                with self.assertRaisesRegex(ProjectDataError, "monospace_width"):
                    parse_font_meta(
                        data,
                        build_name="broken",
                        meta_path=path,
                    )

    def test_opentype_meta_metric_ranges_are_validated(self) -> None:
        path = PROJECT_DIRECTORY / "meta" / "ascii.json"
        original = json.loads(path.read_text(encoding="utf-8"))
        invalid_fields = (
            ("units_per_em", 15),
            ("units_per_em", 16385),
            ("ascender", 32768),
            ("descender", -32769),
        )

        for field, value in invalid_fields:
            with self.subTest(field=field, value=value):
                data = dict(original)
                data[field] = value
                with self.assertRaisesRegex(ProjectDataError, field):
                    parse_font_meta(
                        data,
                        build_name="invalid-range",
                        meta_path=path,
                    )

        data = dict(original)
        data["grid"] = 10**400
        with self.assertRaisesRegex(ProjectDataError, "finite"):
            parse_font_meta(
                data,
                build_name="overflowing-number",
                meta_path=path,
            )

    def test_legacy_width_and_monospace_fields_are_rejected(self) -> None:
        path = PROJECT_DIRECTORY / "meta" / "math.json"
        data = json.loads(path.read_text(encoding="utf-8"))

        for field, value in (("width", 450), ("monospace", False)):
            with self.subTest(field=field):
                legacy = dict(data)
                legacy[field] = value
                with self.assertRaisesRegex(ProjectDataError, field):
                    parse_font_meta(
                        legacy,
                        build_name="broken",
                        meta_path=path,
                    )

    def test_build_list_is_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project_directory = Path(temporary_directory)
            (project_directory / "build_list.json").write_text(
                '[" ascii ", "bold"]',
                encoding="utf-8",
            )

            self.assertEqual(
                load_build_list(project_directory),
                ("ascii", "bold"),
            )


class ReleaseInfoLoaderTests(unittest.TestCase):
    fixture_path = (
        PROJECT_DIRECTORY
        / "tests"
        / "fixtures"
        / "minimal_project"
        / "data"
        / "release_info"
        / "ofl.json"
    )

    def test_release_info_is_loaded_from_its_data_directory(self) -> None:
        project_directory = self.fixture_path.parents[2]

        release_info = load_release_info(project_directory, "ofl")

        self.assertEqual(release_info.version, "1.000")
        self.assertEqual(release_info.version_major, 1)
        self.assertEqual(release_info.version_minor, 0)
        self.assertEqual(release_info.designer, "Test Author")
        self.assertEqual(release_info.vendor_id, "TEST")
        self.assertEqual(release_info.license.identifier, "OFL-1.1")
        self.assertEqual(
            release_info.embedding_permissions,
            "installable",
        )

    def test_pl46_release_info_uses_the_selected_identity(self) -> None:
        release_info = load_release_info(PROJECT_DIRECTORY, "pl46")

        self.assertEqual(release_info.version, "0.100")
        self.assertEqual(release_info.designer, "u6771")
        self.assertEqual(
            release_info.designer_url,
            "https://github.com/u6771",
        )
        self.assertEqual(
            release_info.copyright,
            "Copyright (c) 2026, u6771 (https://github.com/u6771),\n"
            "with Reserved Font Name PL46.",
        )

    def test_release_info_is_immutable(self) -> None:
        project_directory = self.fixture_path.parents[2]
        release_info = load_release_info(project_directory, "ofl")

        with self.assertRaises(FrozenInstanceError):
            release_info.version = "2.000"

    def test_release_info_requires_non_empty_known_fields(self) -> None:
        with self.assertRaisesRegex(ProjectDataError, "cannot be empty"):
            parse_release_info({}, source_path=self.fixture_path)

        unknown = {"unexpected": True}
        with self.assertRaisesRegex(ProjectDataError, "unexpected"):
            parse_release_info(unknown, source_path=self.fixture_path)

    def test_release_info_fields_are_independently_optional(self) -> None:
        designer = parse_release_info(
            {"designer": "Only Designer"},
            source_path=self.fixture_path,
        )
        self.assertEqual(designer.designer, "Only Designer")
        self.assertIsNone(designer.version)
        self.assertIsNone(designer.copyright)
        self.assertIsNone(designer.license)
        self.assertIsNone(designer.embedding_permissions)

        version = parse_release_info(
            {"version": "1.023"},
            source_path=self.fixture_path,
        )
        self.assertEqual(version.version, "1.023")
        self.assertEqual(version.version_major, 1)
        self.assertEqual(version.version_minor, 23)

        embedding = parse_release_info(
            {"embedding_permissions": "editable"},
            source_path=self.fixture_path,
        )
        self.assertEqual(embedding.embedding_permissions, "editable")
        self.assertIsNone(embedding.license)

    def test_release_info_rejects_explicit_null(self) -> None:
        fields = (
            "version",
            "copyright",
            "designer",
            "designer_url",
            "manufacturer",
            "manufacturer_url",
            "description",
            "trademark",
            "vendor_id",
            "license",
            "embedding_permissions",
        )
        for field in fields:
            with self.subTest(field=field):
                with self.assertRaisesRegex(ProjectDataError, field):
                    parse_release_info(
                        {field: None},
                        source_path=self.fixture_path,
                    )

    def test_release_info_rejects_invalid_publication_values(self) -> None:
        original = json.loads(self.fixture_path.read_text(encoding="utf-8"))
        cases = (
            ("version", "1.0"),
            ("embedding_permissions", "open"),
            ("vendor_id", "TOO-LONG"),
            ("designer_url", "example.com/designer"),
            ("designer_url", "ftp://example.com/designer"),
            ("designer_url", "file:///tmp/designer"),
        )

        for field, value in cases:
            with self.subTest(field=field):
                data = {**original, field: value}
                with self.assertRaisesRegex(ProjectDataError, field):
                    parse_release_info(data, source_path=self.fixture_path)

    def test_release_info_rejects_old_and_unknown_license_fields(self) -> None:
        original = json.loads(self.fixture_path.read_text(encoding="utf-8"))

        unknown_license = dict(original)
        unknown_license["license"] = {
            **original["license"],
            "identifier": "Custom-1.0",
        }
        with self.assertRaisesRegex(ProjectDataError, "unsupported license"):
            parse_release_info(
                unknown_license,
                source_path=self.fixture_path,
            )

        old_identifier = dict(original)
        old_identifier["license"] = {"id": "OFL-1.1"}
        with self.assertRaisesRegex(ProjectDataError, "id"):
            parse_release_info(
                old_identifier,
                source_path=self.fixture_path,
            )

        structured_rfn = dict(original)
        structured_rfn["license"] = {
            **original["license"],
            "reserved_font_names": ["Test"],
        }
        with self.assertRaisesRegex(ProjectDataError, "reserved_font_names"):
            parse_release_info(
                structured_rfn,
                source_path=self.fixture_path,
            )

    def test_license_url_is_optional(self) -> None:
        release_info = parse_release_info(
            {
                "license": {"identifier": "OFL-1.1"},
                "embedding_permissions": "installable",
            },
            source_path=self.fixture_path,
        )
        self.assertIsNotNone(release_info.license)
        assert release_info.license is not None
        self.assertIsNone(release_info.license.url)

    def test_license_requires_non_null_identifier_and_url(self) -> None:
        invalid_licenses = (
            {},
            {"identifier": None},
            {"identifier": "OFL-1.1", "url": None},
        )
        for license_data in invalid_licenses:
            with self.subTest(license=license_data):
                with self.assertRaisesRegex(
                    ProjectDataError,
                    "identifier|url",
                ):
                    parse_release_info(
                        {
                            "license": license_data,
                            "embedding_permissions": "installable",
                        },
                        source_path=self.fixture_path,
                    )

    def test_ofl_requires_explicit_installable_embedding(self) -> None:
        original = json.loads(self.fixture_path.read_text(encoding="utf-8"))
        for embedding_permissions in (None, "editable"):
            with self.subTest(embedding_permissions=embedding_permissions):
                data = {"license": original["license"]}
                if embedding_permissions is not None:
                    data["embedding_permissions"] = embedding_permissions
                with self.assertRaisesRegex(
                    ProjectDataError,
                    "explicitly set to 'installable' for OFL-1.1",
                ):
                    parse_release_info(data, source_path=self.fixture_path)

        release_info = parse_release_info(
            {
                "license": original["license"],
                "embedding_permissions": "installable",
            },
            source_path=self.fixture_path,
        )
        self.assertEqual(release_info.embedding_permissions, "installable")


class GlyphSourceLoaderTests(unittest.TestCase):
    def test_all_copied_glyph_sources_load(self) -> None:
        source_root = PROJECT_DIRECTORY / "glyph_sources"
        paths = tuple(source_root.rglob("*.json"))

        loaded = tuple(load_glyph_source(path) for path in paths)

        self.assertEqual(len(loaded), len(paths))

    def test_empty_space_uses_normalized_x_extent(self) -> None:
        glyph = load_glyph_source(
            FIXTURE_SOURCE_DIRECTORY / "space_0020.json"
        )

        self.assertEqual(glyph.name, "space")
        self.assertEqual(glyph.codepoint, 0x20)
        self.assertEqual(glyph.monospace_x_offset, 0)
        self.assertEqual(glyph.y_offset, 0)
        self.assertEqual(glyph.x_extent, 4.0)
        self.assertIsNone(glyph.y_extent)
        self.assertEqual(glyph.skeleton, ())

    def test_stroke_record_is_resolved_once(self) -> None:
        glyph = load_glyph_source(
            PROJECT_DIRECTORY
            / "glyph_sources"
            / "math"
            / "ssty"
            / "minute.st.json"
        )

        self.assertEqual(len(glyph.skeleton), 1)
        stroke = glyph.skeleton[0]
        self.assertEqual(stroke.centerline, ((2.0, 4.0), (0.0, 0.0)))
        self.assertEqual(stroke.thickness_scale, 1.4)
        self.assertEqual(stroke.start_cap, "round")
        self.assertEqual(stroke.end_cap, "round")
        self.assertFalse(stroke.filled)
        self.assertEqual(glyph.x_extent, 2.0)
        self.assertEqual(glyph.y_extent, 4.0)

    def test_skeleton_must_be_normalized_on_both_axes(self) -> None:
        for centerline, axis_name in (
            ([[1, 0], [2, 1]], "x_min"),
            ([[0, 1], [1, 2]], "y_min"),
        ):
            with self.subTest(axis=axis_name):
                with self.assertRaisesRegex(ProjectDataError, axis_name):
                    parse_glyph_source(
                        {
                            "name": "broken",
                            "unicode": None,
                            "monospace_x_offset": 0,
                            "y_offset": 0,
                            "skeleton": [{"centerline": centerline}],
                        },
                        source_path=Path("broken.json"),
                    )

    def test_stroke_record_does_not_accept_common_cap(self) -> None:
        data = {
            "centerline": [[0, 0], [1, 1]],
            "cap": "flat",
        }

        with self.assertRaisesRegex(ProjectDataError, "cap"):
            parse_stroke_record(data, location="test stroke")

    def test_stroke_record_properties_remain_optional(self) -> None:
        stroke = parse_stroke_record(
            {"centerline": [[0, 0], [1, 1]]},
            location="test stroke",
        )

        self.assertEqual(stroke.thickness_scale, 1)
        self.assertEqual(stroke.start_cap, "round")
        self.assertEqual(stroke.end_cap, "round")
        self.assertFalse(stroke.filled)

    def test_glyph_source_requires_explicit_outer_fields(self) -> None:
        data = {
            "name": "A",
            "unicode": "0041",
            "monospace_x_offset": 0,
            "y_offset": 0,
            "skeleton": [{"centerline": [[0, 0], [1, 1]]}],
        }

        for field in ("name", "unicode", "monospace_x_offset", "y_offset"):
            with self.subTest(field=field):
                incomplete = dict(data)
                del incomplete[field]
                with self.assertRaisesRegex(ProjectDataError, field):
                    parse_glyph_source(
                        incomplete,
                        source_path=Path("broken.json"),
                    )

    def test_glyph_source_requires_exactly_one_geometry_field(self) -> None:
        outer = {
            "name": "space",
            "unicode": "0020",
            "monospace_x_offset": 0,
            "y_offset": 0,
        }
        invalid_geometries = (
            {},
            {"skeleton": [], "x_extent": 4},
        )

        for geometry in invalid_geometries:
            with self.subTest(geometry=geometry):
                with self.assertRaisesRegex(ProjectDataError, "exactly one"):
                    parse_glyph_source(
                        outer | geometry,
                        source_path=Path("broken.json"),
                    )

        with self.assertRaisesRegex(ProjectDataError, "cannot be empty"):
            parse_glyph_source(
                outer | {"skeleton": []},
                source_path=Path("broken.json"),
            )

    def test_empty_glyph_rejects_meaningless_offsets(self) -> None:
        for field in ("monospace_x_offset", "y_offset"):
            with self.subTest(field=field):
                with self.assertRaisesRegex(ProjectDataError, field):
                    parse_glyph_source(
                        {
                            "name": "space",
                            "unicode": "0020",
                            "x_extent": 4,
                            field: 0,
                        },
                        source_path=Path("broken.json"),
                    )

    def test_loaded_objects_are_immutable(self) -> None:
        glyph = load_glyph_source(
            FIXTURE_SOURCE_DIRECTORY / "space_0020.json"
        )

        with self.assertRaises(FrozenInstanceError):
            glyph.x_extent = 5.0  # type: ignore[misc]

    def test_unknown_glyph_fields_are_rejected(self) -> None:
        path = Path("broken.json")
        data = {
            "name": "space",
            "unicode": "0020",
            "x_extent": 4,
            "skeleton": [],
            "advance": 500,
        }

        with self.assertRaisesRegex(ProjectDataError, "advance"):
            parse_glyph_source(data, source_path=path)

    def test_glyph_name_uses_safe_external_name_syntax(self) -> None:
        with self.assertRaisesRegex(ProjectDataError, "unsupported"):
            parse_glyph_source(
                {
                    "name": "bad name",
                    "unicode": None,
                    "x_extent": 1,
                },
                source_path=Path("broken.json"),
            )

    def test_legacy_x_offset_name_is_rejected(self) -> None:
        path = Path("broken.json")
        data = {
            "name": "A",
            "unicode": "0041",
            "x_offset": 1,
            "skeleton": [],
        }

        with self.assertRaisesRegex(ProjectDataError, "x_offset"):
            parse_glyph_source(data, source_path=path)

    def test_legacy_length_name_is_rejected(self) -> None:
        with self.assertRaisesRegex(ProjectDataError, "length"):
            parse_glyph_source(
                {
                    "name": "space",
                    "unicode": "0020",
                    "length": 4,
                    "skeleton": [],
                },
                source_path=Path("space.json"),
            )


class AccentLoaderTests(unittest.TestCase):
    def test_accent_glyphs_are_unique_valid_names(self) -> None:
        accents = load_accent_glyphs(PROJECT_DIRECTORY, "math.json")

        self.assertLessEqual(
            {"tildecomb", "circumflexcmb"},
            accents,
        )

    def test_accent_file_rejects_empty_duplicate_and_invalid_names(self) -> None:
        invalid_values = (
            [],
            ["tildecomb", "tildecomb"],
            ["tildecomb", "bad@selector"],
            ["tildecomb", 1],
        )
        for value in invalid_values:
            with self.subTest(value=value):
                with self.assertRaises(ProjectDataError):
                    parse_accent_glyphs(
                        value,
                        source_path=Path("accent.json"),
                    )


class KerningLoaderTests(unittest.TestCase):
    def test_kerning_groups_and_pairs_are_typed_and_read_only(self) -> None:
        kerning = load_kerning_data(PROJECT_DIRECTORY, "fraktur.json")

        self.assertEqual(
            kerning.groups["public.kern1.spur"],
            ("a", "i", "l", "m", "n", "u"),
        )
        self.assertEqual(
            (kerning.pairs[0].left, kerning.pairs[0].right),
            ("public.kern1.spur", "public.kern2.spur"),
        )
        self.assertEqual(kerning.pairs[0].value, -100)
        with self.assertRaises(TypeError):
            kerning.groups["new"] = ("A",)  # type: ignore[index]

    def test_empty_kerning_collections_are_valid(self) -> None:
        for value in ({}, {"groups": {}, "pairs": []}):
            with self.subTest(value=value):
                kerning = parse_kerning_data(
                    value,
                    source_path=Path("kerning.json"),
                )
                self.assertEqual(dict(kerning.groups), {})
                self.assertEqual(kerning.pairs, ())

    def test_kerning_rejects_invalid_group_sides_and_membership(self) -> None:
        invalid_values = (
            {
                "groups": {"public.kern1.empty": []},
                "pairs": [],
            },
            {
                "groups": {"group.left": ["A"]},
                "pairs": [],
            },
            {
                "groups": {
                    "public.kern1.first": ["A"],
                    "public.kern1.second": ["A"],
                },
                "pairs": [],
            },
            {
                "groups": {
                    "public.kern1.left": ["A"],
                    "public.kern2.right": ["V"],
                },
                "pairs": [["public.kern2.right", "V", -10]],
            },
        )

        for value in invalid_values:
            with self.subTest(value=value):
                with self.assertRaises(ProjectDataError):
                    parse_kerning_data(
                        value,
                        source_path=Path("kerning.json"),
                    )

    def test_kerning_value_must_fit_an_opentype_fword(self) -> None:
        with self.assertRaisesRegex(ProjectDataError, "32767"):
            parse_kerning_data(
                {"pairs": [["A", "V", 32768]]},
                source_path=Path("kerning.json"),
            )


class MathTableDataLoaderTests(unittest.TestCase):
    def test_missing_kern_file_produces_empty_data(self) -> None:
        meta = load_font_meta(PROJECT_DIRECTORY, "math")
        assert meta.math_table is not None

        data = load_math_table_data(
            PROJECT_DIRECTORY,
            replace(meta.math_table, kern_file=None),
        )

        self.assertIsNone(data.kern_source_path)
        self.assertEqual(dict(data.kerns), {})

    def test_missing_accent_attachment_file_produces_empty_data(self) -> None:
        meta = load_font_meta(PROJECT_DIRECTORY, "math")
        assert meta.math_table is not None

        data = load_math_table_data(
            PROJECT_DIRECTORY,
            replace(meta.math_table, accent_attachment_file=None),
        )

        self.assertIsNone(data.accent_attachment_source_path)
        self.assertEqual(dict(data.accent_attachments), {})

    def test_missing_italics_correction_file_produces_empty_data(self) -> None:
        meta = load_font_meta(PROJECT_DIRECTORY, "math")
        assert meta.math_table is not None

        data = load_math_table_data(
            PROJECT_DIRECTORY,
            replace(meta.math_table, italics_correction_file=None),
        )

        self.assertIsNone(data.italics_correction_source_path)
        self.assertEqual(dict(data.italic_corrections), {})

    def test_missing_variants_file_produces_empty_flattened_data(self) -> None:
        meta = load_font_meta(PROJECT_DIRECTORY, "math")
        assert meta.math_table is not None

        data = load_math_table_data(
            PROJECT_DIRECTORY,
            replace(meta.math_table, variants_file=None),
        )

        self.assertEqual(data.min_connector_overlap, 0)
        self.assertEqual(dict(data.vertical_variant_glyphs), {})
        self.assertEqual(dict(data.horizontal_variant_glyphs), {})
        self.assertEqual(dict(data.vertical_assemblies), {})
        self.assertEqual(dict(data.horizontal_assemblies), {})

    def test_project_math_inputs_are_typed_and_read_only(self) -> None:
        meta = load_font_meta(PROJECT_DIRECTORY, "math")
        assert meta.math_table is not None

        data = load_math_table_data(PROJECT_DIRECTORY, meta.math_table)
        assert meta.ssty_file is not None
        ssty = load_ssty_data(PROJECT_DIRECTORY, meta.ssty_file)

        self.assertEqual(data.constants["AxisHeight"], 225)
        self.assertEqual(ssty.substitutions["minute"], ("minute.st",))
        self.assertEqual(
            data.italic_corrections["contourintegral.v1"],
            200,
        )
        self.assertEqual(set(data.italic_corrections.values()), {200})
        self.assertEqual(data.accent_attachments["f.italic"], 1.0)
        self.assertEqual(data.accent_attachments["uni210F"], -2.0)
        self.assertEqual(data.accent_attachments["dotlessj"], 1.0)
        self.assertEqual(data.accent_attachments["uni2113"], 0.0)
        self.assertNotIn("theta", data.accent_attachments)
        self.assertEqual(data.accent_attachments["j"], 1.0)
        self.assertEqual(data.accent_attachments["t"], -1.0)
        self.assertIsNone(data.kern_source_path)
        self.assertEqual(dict(data.kerns), {})
        self.assertEqual(
            data.vertical_variant_glyphs["parenleft"][:2],
            ("parenleft.v1", "parenleft.v2"),
        )
        self.assertEqual(len(data.vertical_variant_glyphs), 46)
        self.assertEqual(len(data.horizontal_variant_glyphs), 14)
        self.assertEqual(data.min_connector_overlap, 25)
        self.assertEqual(len(data.vertical_assemblies), 17)
        self.assertEqual(len(data.horizontal_assemblies), 11)
        self.assertLessEqual(
            set(data.vertical_assemblies),
            set(data.vertical_variant_glyphs),
        )
        self.assertLessEqual(
            set(data.horizontal_assemblies),
            set(data.horizontal_variant_glyphs),
        )
        with self.assertRaises(TypeError):
            data.constants["AxisHeight"] = 0  # type: ignore[index]
        with self.assertRaises(TypeError):
            data.italic_corrections["contourintegral"] = 0  # type: ignore[index]
        with self.assertRaises(TypeError):
            data.accent_attachments["j"] = 0  # type: ignore[index]
        with self.assertRaises(TypeError):
            data.kerns["F"] = None  # type: ignore[index, assignment]

    def test_math_kerns_are_exact_typed_and_read_only(self) -> None:
        table = {
            "correction_height": [-100, 100],
            "kern_values": [-30, -20, -10],
        }
        parsed = parse_math_kerns(
            {
                "A.script": {
                    "top_right": table,
                    "top_left": table,
                    "bottom_right": table,
                    "bottom_left": table,
                }
            },
            source_path=Path("math_kern.json"),
        )

        glyph_kern = parsed["A.script"]
        assert glyph_kern.bottom_right is not None
        self.assertEqual(glyph_kern.bottom_right.correction_height, (-100, 100))
        self.assertEqual(glyph_kern.bottom_right.kern_values, (-30, -20, -10))
        with self.assertRaises(TypeError):
            parsed["A.script"] = glyph_kern  # type: ignore[index]

    def test_math_kerns_reject_selectors_and_invalid_tables(self) -> None:
        valid_table = {
            "correction_height": [],
            "kern_values": [-40],
        }
        invalid_inputs = (
            {},
            {"A@variant_glyphs": {"bottom_right": valid_table}},
            {"A": {}},
            {"A": {"unknown": valid_table}},
            {
                "A": {
                    "bottom_right": {
                        "correction_height": [0],
                        "kern_values": [-40],
                    }
                }
            },
            {
                "A": {
                    "bottom_right": {
                        "correction_height": [0, 0],
                        "kern_values": [-40, -30, -20],
                    }
                }
            },
            {
                "A": {
                    "bottom_right": {
                        "correction_height": [0],
                        "kern_values": [-40, 1.5],
                    }
                }
            },
            {
                "A": {
                    "bottom_right": {
                        "correction_height": [32768],
                        "kern_values": [-40, -30],
                    }
                }
            },
            {
                "A": {
                    "bottom_right": {
                        "correction_height": [0],
                        "kern_values": [-40, -32769],
                    }
                }
            },
        )
        for value in invalid_inputs:
            with self.subTest(value=value):
                with self.assertRaises(ProjectDataError):
                    parse_math_kerns(
                        value,
                        source_path=Path("math_kern.json"),
                    )

    def test_math_accent_attachments_accept_finite_grid_coordinates(self) -> None:
        parsed = parse_math_accent_attachments(
            {"f": 1, "j": 1.5, "A": -1},
            source_path=Path("accent_attachment.json"),
        )

        self.assertEqual(dict(parsed), {"f": 1.0, "j": 1.5, "A": -1.0})

    def test_math_accent_attachments_reject_invalid_data(self) -> None:
        with self.assertRaisesRegex(ProjectDataError, "cannot be empty"):
            parse_math_accent_attachments(
                {},
                source_path=Path("accent_attachment.json"),
            )

        for name in ("", "A@variant_glyphs"):
            with self.subTest(name=name):
                with self.assertRaises(ProjectDataError):
                    parse_math_accent_attachments(
                        {name: 1},
                        source_path=Path("accent_attachment.json"),
                    )

        for value in (True, "1", float("inf"), float("nan")):
            with self.subTest(value=value):
                with self.assertRaises(ProjectDataError):
                    parse_math_accent_attachments(
                        {"j": value},
                        source_path=Path("accent_attachment.json"),
                    )

    def test_math_italics_correction_values_are_exact_and_read_only(self) -> None:
        parsed = parse_math_italics_correction(
            {"A": 10, "contourintegral.v1": 200},
            source_path=Path("italics_correction.json"),
        )

        self.assertEqual(
            dict(parsed),
            {"A": 10, "contourintegral.v1": 200},
        )
        with self.assertRaises(TypeError):
            parsed["A"] = 20  # type: ignore[index]

    def test_math_italics_correction_rejects_invalid_data(self) -> None:
        with self.assertRaisesRegex(ProjectDataError, "cannot be empty"):
            parse_math_italics_correction(
                {},
                source_path=Path("italics_correction.json"),
            )

        for name in ("", "A@variant_glyphs"):
            with self.subTest(name=name):
                with self.assertRaises(ProjectDataError):
                    parse_math_italics_correction(
                        {name: 10},
                        source_path=Path("italics_correction.json"),
                    )

        for value in (-1, 32768, True, 1.5, "200"):
            with self.subTest(value=value):
                with self.assertRaises(ProjectDataError):
                    parse_math_italics_correction(
                        {"A": value},
                        source_path=Path("italics_correction.json"),
                    )

    def test_constants_require_the_exact_schema(self) -> None:
        with self.assertRaisesRegex(ProjectDataError, "Missing"):
            parse_math_constants({}, source_path=Path("constants.json"))

        meta = load_font_meta(PROJECT_DIRECTORY, "math")
        assert meta.math_table is not None
        data = load_math_table_data(PROJECT_DIRECTORY, meta.math_table)
        constants = dict(data.constants)
        constants["AxisHeight"] = True
        with self.assertRaisesRegex(ProjectDataError, "AxisHeight"):
            parse_math_constants(
                constants,
                source_path=Path("constants.json"),
            )

        for name, value in (
            ("AxisHeight", 32768),
            ("DelimitedSubFormulaMinHeight", -1),
            ("DisplayOperatorMinHeight", 65536),
        ):
            with self.subTest(name=name, value=value):
                invalid = dict(data.constants)
                invalid[name] = value
                with self.assertRaisesRegex(ProjectDataError, name):
                    parse_math_constants(
                        invalid,
                        source_path=Path("constants.json"),
                    )

    def test_ssty_rejects_duplicate_and_base_alternates(self) -> None:
        with self.assertRaisesRegex(ProjectDataError, "duplicate"):
            parse_ssty(
                {"minute": ["minute.st", "minute.st"]},
                source_path=Path("ssty.json"),
            )
        with self.assertRaisesRegex(ProjectDataError, "base glyph"):
            parse_ssty(
                {"minute": ["minute"]},
                source_path=Path("ssty.json"),
            )

    def test_variant_glyphs_support_both_axes_and_reject_duplicates(self) -> None:
        vertical, vertical_assemblies = _parse_math_variants_axis(
            {"parenleft": {"variant_glyphs": ["parenleft.v1"]}},
            axis="vertical",
            source_path=Path("variants.json"),
        )
        horizontal, horizontal_assemblies = _parse_math_variants_axis(
            {"arrow": {"variant_glyphs": ["arrow.h1"]}},
            axis="horizontal",
            source_path=Path("variants.json"),
        )
        self.assertEqual(
            vertical["parenleft"], ("parenleft.v1",)
        )
        self.assertEqual(horizontal["arrow"], ("arrow.h1",))
        self.assertEqual(dict(vertical_assemblies), {})
        self.assertEqual(dict(horizontal_assemblies), {})

        with self.assertRaisesRegex(ProjectDataError, "duplicate"):
            _parse_math_variants_axis(
                {
                    "parenleft": {
                        "variant_glyphs": [
                            "parenleft.v1",
                            "parenleft.v1",
                        ]
                    }
                },
                axis="vertical",
                source_path=Path("variants.json"),
            )

    def test_variant_glyphs_allow_empty_sequences(self) -> None:
        vertical, assemblies = _parse_math_variants_axis(
            {"radical": {}, "arrow": {"variant_glyphs": []}},
            axis="vertical",
            source_path=Path("variants.json"),
        )

        self.assertEqual(vertical["radical"], ())
        self.assertEqual(vertical["arrow"], ())
        self.assertEqual(dict(assemblies), {})

    def test_assemblies_are_typed_and_axis_scales_are_optional(self) -> None:
        vertical_variants, vertical_assemblies = _parse_math_variants_axis(
            {
                "parenleft": {
                    "parts": [
                        {
                            "glyph": "parenleft.bottom",
                            "start_connector_extent": 0,
                            "end_connector_extent": 0.5,
                            "bottom_scale": 0,
                            "extender": False,
                        },
                        {
                            "glyph": "parenleft.ex",
                            "start_connector_extent": 0.5,
                            "end_connector_extent": 0.5,
                            "extender": True,
                        },
                    ]
                },
            },
            axis="vertical",
            source_path=Path("variants.json"),
        )
        horizontal_variants, horizontal_assemblies = (
            _parse_math_variants_axis(
                {
                    "overbrace": {
                        "italic_correction": 10,
                        "parts": [
                            {
                                "glyph": "overbrace.ex",
                                "start_connector_extent": 1,
                                "end_connector_extent": 1,
                                "left_scale": 0,
                                "right_scale": 0,
                                "extender": True,
                            }
                        ],
                    }
                },
                axis="horizontal",
                source_path=Path("variants.json"),
            )
        )

        vertical = vertical_assemblies["parenleft"]
        self.assertEqual(vertical_variants["parenleft"], ())
        self.assertEqual(vertical.italic_correction, 0)
        self.assertEqual(vertical.parts[0].start_scale, 0)
        self.assertIsNone(vertical.parts[0].end_scale)
        self.assertIsNone(vertical.parts[1].start_scale)
        horizontal = horizontal_assemblies["overbrace"]
        self.assertEqual(horizontal_variants["overbrace"], ())
        self.assertEqual(horizontal.italic_correction, 10)
        self.assertEqual(horizontal.parts[0].start_scale, 0)
        self.assertEqual(horizontal.parts[0].end_scale, 0)
        with self.assertRaises(TypeError):
            vertical_assemblies["new"] = vertical  # type: ignore[index]

    def test_assemblies_reject_invalid_schema_and_values(self) -> None:
        with self.assertRaisesRegex(ProjectDataError, "bottom_scale"):
            _parse_math_variants_axis(
                {
                    "parenleft": {
                        "parts": [
                            {
                                "glyph": "part",
                                "start_connector_extent": 1,
                                "end_connector_extent": 1,
                                "bottom_scale": -1,
                                "extender": True,
                            }
                        ]
                    },
                },
                axis="vertical",
                source_path=Path("variants.json"),
            )

        with self.assertRaisesRegex(ProjectDataError, "cannot be empty"):
            _parse_math_variants_axis(
                {"parenleft": {"parts": []}},
                axis="vertical",
                source_path=Path("variants.json"),
            )

        with self.assertRaisesRegex(ProjectDataError, "unknown fields"):
            _parse_math_variants_axis(
                {"parenleft": {"unknown": 1}},
                axis="vertical",
                source_path=Path("variants.json"),
            )

        with self.assertRaisesRegex(ProjectDataError, "base glyph"):
            _parse_math_variants_axis(
                {"parenleft": {"variant_glyphs": ["parenleft"]}},
                axis="vertical",
                source_path=Path("variants.json"),
            )

    def test_optional_assembly_scales_reject_explicit_null(self) -> None:
        for axis, fields in (
            ("vertical", ("bottom_scale", "top_scale")),
            ("horizontal", ("left_scale", "right_scale")),
        ):
            for field in fields:
                with self.subTest(axis=axis, field=field):
                    with self.assertRaisesRegex(ProjectDataError, field):
                        _parse_math_variants_axis(
                            {
                                "base": {
                                    "parts": [
                                        {
                                            "glyph": "part",
                                            "start_connector_extent": 0,
                                            "end_connector_extent": 0,
                                            field: None,
                                            "extender": False,
                                        }
                                    ]
                                }
                            },
                            axis=axis,
                            source_path=Path("variants.json"),
                        )

    def test_construction_requires_parts_for_italic_correction(self) -> None:
        with self.assertRaisesRegex(ProjectDataError, "requires parts"):
            _parse_math_variants_axis(
                {"parenleft": {"italic_correction": 10}},
                axis="vertical",
                source_path=Path("variants.json"),
            )

    def test_variants_file_requires_min_connector_overlap(self) -> None:
        meta = load_font_meta(PROJECT_DIRECTORY, "math")
        assert meta.math_table is not None
        data = load_math_table_data(PROJECT_DIRECTORY, meta.math_table)

        def fake_read_json(path: Path) -> object:
            if path.parent.name == "constants":
                return dict(data.constants)
            if path.parent.name == "italics_correction":
                return dict(data.italic_corrections)
            if path.parent.name == "accent_attachment":
                return dict(data.accent_attachments)
            if path.parent.name == "kern":
                return {
                    "F": {
                        "bottom_right": {
                            "correction_height": [],
                            "kern_values": [-200],
                        }
                    }
                }
            if path.parent.name == "variants":
                return {"vertical": {}, "horizontal": {}}
            raise AssertionError(path)

        with patch(
            "skeletonfont.loading.math.read_json",
            side_effect=fake_read_json,
        ):
            with self.assertRaisesRegex(
                ProjectDataError,
                "min_connector_overlap",
            ):
                load_math_table_data(PROJECT_DIRECTORY, meta.math_table)


if __name__ == "__main__":
    unittest.main()
