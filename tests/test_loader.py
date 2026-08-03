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
    load_math_data,
    parse_font_meta,
    parse_accent_glyphs,
    parse_glyph_source,
    parse_math_accent_attachments,
    parse_math_constants,
    parse_math_italics_correction,
    parse_math_ssty,
    parse_stroke_record,
)


PROJECT_DIRECTORY = Path(__file__).resolve().parents[1]


class FontMetaLoaderTests(unittest.TestCase):
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

    def test_unicode_ranges_are_normalized(self) -> None:
        meta = load_font_meta(PROJECT_DIRECTORY, "mono")

        self.assertEqual(
            meta.source_rules[1].unicode_ranges,
            ((0, 0x10FFFF),),
        )

    def test_math_config_uses_normalized_json_names(self) -> None:
        meta = load_font_meta(PROJECT_DIRECTORY, "math")

        self.assertIsNotNone(meta.math_config)
        assert meta.math_config is not None
        self.assertEqual(meta.math_config.constants_file, "math.json")
        self.assertEqual(
            meta.math_config.variants_file,
            "math.json",
        )
        self.assertEqual(meta.math_config.ssty_file, "math.json")
        self.assertEqual(
            meta.math_config.italics_correction_file,
            "math.json",
        )
        self.assertEqual(
            meta.math_config.accent_attachment_file,
            "math.json",
        )

    def test_model_names_express_source_rule_behavior(self) -> None:
        meta = load_font_meta(PROJECT_DIRECTORY, "math")
        math_rule = meta.source_rules[4]

        self.assertEqual(meta.build_name, "math")
        self.assertEqual(meta.meta_path.name, "math.json")
        self.assertIsNone(meta.glyph_parameters.monospace_width)
        self.assertEqual(meta.glyph_parameters.radius, 25)
        self.assertEqual(
            meta.glyph_generators,
            ("italic_latin", "italic_greek"),
        )
        self.assertEqual(meta.glyph_config_file, "math.json")
        self.assertEqual(meta.accent_file, "math.json")
        self.assertEqual(meta.output_stem, "PL46-Math")
        self.assertTrue(meta.glyph_parameters.use_scaled_edge_thickness)
        self.assertEqual(math_rule.source_directory, "math")
        self.assertTrue(math_rule.replace_existing)
        self.assertIsNone(math_rule.mapping_name)

    def test_disabled_math_is_none(self) -> None:
        meta = load_font_meta(PROJECT_DIRECTORY, "ascii")

        self.assertIsNone(meta.math_config)

    def test_empty_math_config_is_none(self) -> None:
        path = PROJECT_DIRECTORY / "meta" / "ascii.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["math_config"] = {}

        meta = parse_font_meta(
            data,
            build_name="empty-math",
            meta_path=path,
        )

        self.assertIsNone(meta.math_config)

    def test_math_config_does_not_accept_enabled_switch(self) -> None:
        path = PROJECT_DIRECTORY / "meta" / "ascii.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["math_config"] = {"enabled": False}

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
            "glyph_generators",
            "glyph_config_file",
            "accent_file",
            "kerning_file",
            "output_stem",
            "math_config",
        ):
            data.pop(key, None)
        data["glyph_generators"] = None
        data["math_config"] = None

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
        self.assertFalse(
            meta.glyph_parameters.use_scaled_edge_thickness
        )
        self.assertEqual(meta.glyph_generators, ())
        self.assertIsNone(meta.glyph_config_file)
        self.assertIsNone(meta.accent_file)
        self.assertIsNone(meta.kerning_file)
        self.assertEqual(meta.output_stem, "PL46-Ascii")
        self.assertIsNone(meta.math_config)

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

    def test_math_config_rejects_legacy_variant_fields(self) -> None:
        path = PROJECT_DIRECTORY / "meta" / "ascii.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["math_config"] = {"variant_glyphs_file": "math.json"}

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


class GlyphSourceLoaderTests(unittest.TestCase):
    def test_all_copied_glyph_sources_load(self) -> None:
        source_root = PROJECT_DIRECTORY / "glyph_sources"
        paths = tuple(source_root.rglob("*.json"))

        loaded = tuple(load_glyph_source(path) for path in paths)

        self.assertEqual(len(loaded), len(paths))

    def test_empty_space_uses_normalized_x_extent(self) -> None:
        glyph = load_glyph_source(
            PROJECT_DIRECTORY
            / "glyph_sources"
            / "ascii"
            / "space_0020.json"
        )

        self.assertEqual(glyph.name, "space")
        self.assertEqual(glyph.codepoint, 0x20)
        self.assertEqual(glyph.monospace_x_offset, -3)
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

    def test_loaded_objects_are_immutable(self) -> None:
        glyph = load_glyph_source(
            PROJECT_DIRECTORY
            / "glyph_sources"
            / "ascii"
            / "space_0020.json"
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


class MathDataLoaderTests(unittest.TestCase):
    def test_missing_accent_attachment_file_produces_empty_data(self) -> None:
        meta = load_font_meta(PROJECT_DIRECTORY, "math")
        assert meta.math_config is not None

        data = load_math_data(
            PROJECT_DIRECTORY,
            replace(meta.math_config, accent_attachment_file=None),
        )

        self.assertIsNone(data.accent_attachment_source_path)
        self.assertEqual(dict(data.accent_attachments), {})

    def test_missing_italics_correction_file_produces_empty_data(self) -> None:
        meta = load_font_meta(PROJECT_DIRECTORY, "math")
        assert meta.math_config is not None

        data = load_math_data(
            PROJECT_DIRECTORY,
            replace(meta.math_config, italics_correction_file=None),
        )

        self.assertIsNone(data.italics_correction_source_path)
        self.assertEqual(dict(data.italic_corrections), {})

    def test_missing_variants_file_produces_empty_flattened_data(self) -> None:
        meta = load_font_meta(PROJECT_DIRECTORY, "math")
        assert meta.math_config is not None

        data = load_math_data(
            PROJECT_DIRECTORY,
            replace(meta.math_config, variants_file=None),
        )

        self.assertEqual(data.min_connector_overlap, 0)
        self.assertEqual(dict(data.vertical_variant_glyphs), {})
        self.assertEqual(dict(data.horizontal_variant_glyphs), {})
        self.assertEqual(dict(data.vertical_assemblies), {})
        self.assertEqual(dict(data.horizontal_assemblies), {})

    def test_real_math_inputs_are_typed_and_read_only(self) -> None:
        meta = load_font_meta(PROJECT_DIRECTORY, "math")
        assert meta.math_config is not None

        data = load_math_data(PROJECT_DIRECTORY, meta.math_config)

        self.assertEqual(data.constants["AxisHeight"], 225)
        self.assertEqual(data.ssty["minute"], ("minute.st",))
        self.assertEqual(
            data.italic_corrections["contourintegral.v1"],
            200,
        )
        self.assertEqual(set(data.italic_corrections.values()), {200})
        self.assertEqual(data.accent_attachments["u1D453"], 1.0)
        self.assertEqual(data.accent_attachments["j"], 1.0)
        self.assertEqual(data.accent_attachments["t"], -1.0)
        self.assertEqual(
            data.vertical_variant_glyphs["parenleft"][:2],
            ("parenleft.v1", "parenleft.v2"),
        )
        self.assertEqual(len(data.vertical_variant_glyphs), 36)
        self.assertEqual(len(data.horizontal_variant_glyphs), 6)
        self.assertEqual(data.min_connector_overlap, 20)
        self.assertEqual(len(data.vertical_assemblies), 11)
        self.assertEqual(len(data.horizontal_assemblies), 6)
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

        for value in (-1, True, 1.5, "200"):
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
        assert meta.math_config is not None
        data = load_math_data(PROJECT_DIRECTORY, meta.math_config)
        constants = dict(data.constants)
        constants["AxisHeight"] = True
        with self.assertRaisesRegex(ProjectDataError, "AxisHeight"):
            parse_math_constants(
                constants,
                source_path=Path("constants.json"),
            )

    def test_ssty_rejects_duplicate_and_base_alternates(self) -> None:
        with self.assertRaisesRegex(ProjectDataError, "duplicate"):
            parse_math_ssty(
                {"minute": ["minute.st", "minute.st"]},
                source_path=Path("ssty.json"),
            )
        with self.assertRaisesRegex(ProjectDataError, "base glyph"):
            parse_math_ssty(
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

    def test_construction_requires_parts_for_italic_correction(self) -> None:
        with self.assertRaisesRegex(ProjectDataError, "requires parts"):
            _parse_math_variants_axis(
                {"parenleft": {"italic_correction": 10}},
                axis="vertical",
                source_path=Path("variants.json"),
            )

    def test_variants_file_requires_min_connector_overlap(self) -> None:
        meta = load_font_meta(PROJECT_DIRECTORY, "math")
        assert meta.math_config is not None
        data = load_math_data(PROJECT_DIRECTORY, meta.math_config)

        def fake_read_json(path: Path) -> object:
            if path.parent.name == "math_constants":
                return dict(data.constants)
            if path.parent.name == "math_ssty":
                return {
                    base: list(alternates)
                    for base, alternates in data.ssty.items()
                }
            if path.parent.name == "math_italics_correction":
                return dict(data.italic_corrections)
            if path.parent.name == "math_accent_attachment":
                return dict(data.accent_attachments)
            return {"vertical": {}, "horizontal": {}}

        with patch("skeletonfont.loader.read_json", side_effect=fake_read_json):
            with self.assertRaisesRegex(
                ProjectDataError,
                "min_connector_overlap",
            ):
                load_math_data(PROJECT_DIRECTORY, meta.math_config)


if __name__ == "__main__":
    unittest.main()
