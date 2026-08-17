from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from fontTools.ttLib import TTFont

from skeletonfont.build import build_font, build_fonts
from skeletonfont.errors import BuildError, PlanError, ProjectDataError
from skeletonfont.loader import load_font_meta, parse_release_info


PROJECT_DIRECTORY = Path(__file__).resolve().parents[1]
FIXTURE_PROJECT_DIRECTORY = (
    PROJECT_DIRECTORY / "tests" / "fixtures" / "minimal_project"
)


class BuildPipelineTests(unittest.TestCase):
    def test_batch_rejects_duplicate_meta_names_before_loading(self) -> None:
        with (
            patch("skeletonfont.build.load_font_meta") as load_meta,
            self.assertRaisesRegex(ProjectDataError, "duplicate meta"),
        ):
            build_fonts(PROJECT_DIRECTORY, ["ascii", "ascii.json"])

        load_meta.assert_not_called()

    def test_batch_rejects_output_collisions_before_building(self) -> None:
        first = load_font_meta(PROJECT_DIRECTORY, "ascii")
        second = replace(
            load_font_meta(PROJECT_DIRECTORY, "bold"),
            output_stem=first.output_stem.upper(),
        )
        with (
            patch(
                "skeletonfont.build.load_font_meta",
                side_effect=(first, second),
            ),
            patch(
                "skeletonfont.build._build_font_from_meta"
            ) as build_from_meta,
            self.assertRaisesRegex(ProjectDataError, "duplicate OTF"),
        ):
            build_fonts(PROJECT_DIRECTORY, ["ascii", "bold"])

        build_from_meta.assert_not_called()

    def test_batch_validates_release_info_before_building(self) -> None:
        released = load_font_meta(FIXTURE_PROJECT_DIRECTORY, "released")
        with (
            patch(
                "skeletonfont.build.load_font_meta",
                return_value=released,
            ),
            patch(
                "skeletonfont.build.load_release_info",
                side_effect=ProjectDataError("invalid release info"),
            ),
            patch(
                "skeletonfont.build._build_font_from_meta"
            ) as build_from_meta,
            self.assertRaisesRegex(BuildError, "invalid release info"),
        ):
            build_fonts(FIXTURE_PROJECT_DIRECTORY, ["released"])

        build_from_meta.assert_not_called()

    def test_build_error_identifies_meta_and_preserves_cause(self) -> None:
        cause = PlanError("invalid glyph roles")
        with (
            patch(
                "skeletonfont.build.load_font_meta",
                side_effect=cause,
            ),
            self.assertRaises(BuildError) as caught,
        ):
            build_font(PROJECT_DIRECTORY, "mono")

        error = caught.exception
        self.assertEqual(str(error), "Meta 'mono': invalid glyph roles")
        self.assertEqual(error.meta_name, "mono")
        self.assertIs(error.cause, cause)
        self.assertIs(error.__cause__, cause)

    def test_ascii_is_built_directly_to_final_otf(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_directory = Path(temporary_directory)

            output_path = build_font(
                PROJECT_DIRECTORY,
                "ascii",
                output_directory=output_directory,
            )

            self.assertEqual(output_path.name, "PL46-Ascii.otf")
            self.assertEqual(list(output_directory.iterdir()), [output_path])
            font = TTFont(output_path)
            self.assertEqual(font.getBestCmap()[0x0041], "A")
            self.assertEqual(font["hmtx"].metrics["A"][0], 600)
            self.assertNotIn("MATH", font)
            self.assertEqual(font["OS/2"].usWeightClass, 400)
            self.assertEqual(font["OS/2"].fsType, 0)
            self.assertEqual(font["post"].isFixedPitch, 1)
            self.assertEqual(font["name"].getDebugName(5), "Version 0.100")
            self.assertAlmostEqual(
                font["head"].fontRevision,
                0.1,
                places=4,
            )
            self.assertEqual(font["name"].getDebugName(9), "u6771")
            self.assertEqual(
                font["name"].getDebugName(12),
                "https://github.com/u6771",
            )
            self.assertEqual(
                font["name"].getDebugName(13),
                "This Font Software is licensed under the SIL Open Font "
                "License, Version 1.1.",
            )
            self.assertEqual(
                font["name"].getDebugName(0),
                "Copyright (c) 2026, u6771 "
                "(https://github.com/u6771),\n"
                "with Reserved Font Name PL46.",
            )
            font.close()

    def test_omitted_release_info_keeps_development_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_path = build_font(
                FIXTURE_PROJECT_DIRECTORY,
                "basic",
                output_directory=Path(temporary_directory),
            )

            font = TTFont(output_path)
            self.assertEqual(font["name"].getDebugName(5), "Version 0.000")
            self.assertEqual(font["head"].fontRevision, 0.0)
            self.assertEqual(font["OS/2"].fsType, 4)
            self.assertEqual(font["OS/2"].achVendID, "NONE")
            self.assertIsNone(font["name"].getDebugName(0))
            self.assertIsNone(font["name"].getDebugName(13))
            self.assertIsNone(font["name"].getDebugName(14))
            font.close()

    def test_partial_license_omits_unwritten_name_records(self) -> None:
        release_info = parse_release_info(
            {
                "license": {"identifier": "OFL-1.1"},
                "embedding_permissions": "installable",
            },
            source_path=PROJECT_DIRECTORY / "partial-release.json",
        )
        with (
            tempfile.TemporaryDirectory() as temporary_directory,
            patch(
                "skeletonfont.build.load_release_info",
                return_value=release_info,
            ),
        ):
            output_path = build_font(
                FIXTURE_PROJECT_DIRECTORY,
                "released",
                output_directory=Path(temporary_directory),
            )

            font = TTFont(output_path)
            self.assertEqual(font["name"].getDebugName(5), "Version 0.000")
            self.assertEqual(font["OS/2"].fsType, 0)
            self.assertEqual(
                font["name"].getDebugName(13),
                "This Font Software is licensed under the SIL Open Font "
                "License, Version 1.1.",
            )
            self.assertIsNone(font["name"].getDebugName(0))
            self.assertIsNone(font["name"].getDebugName(9))
            self.assertIsNone(font["name"].getDebugName(14))
            font.close()

    def test_release_info_is_embedded_in_the_final_otf(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_directory = Path(temporary_directory)

            output_path = build_font(
                FIXTURE_PROJECT_DIRECTORY,
                "released",
                output_directory=output_directory,
            )

            font = TTFont(output_path)
            self.assertEqual(output_path.name, "Test-Released.otf")
            self.assertEqual(font["OS/2"].usWeightClass, 700)
            self.assertEqual(font["OS/2"].fsType, 0)
            self.assertEqual(font["OS/2"].achVendID, "TEST")
            self.assertEqual(font["post"].isFixedPitch, 1)
            self.assertEqual(font["head"].fontRevision, 1.0)
            self.assertEqual(font["name"].getDebugName(5), "Version 1.000")
            self.assertEqual(font["name"].getDebugName(8), "Test Foundry")
            self.assertEqual(font["name"].getDebugName(9), "Test Author")
            self.assertEqual(
                font["name"].getDebugName(10),
                "A release-info integration test font.",
            )
            self.assertEqual(
                font["name"].getDebugName(13),
                "This Font Software is licensed under the SIL Open Font "
                "License, Version 1.1.",
            )
            self.assertEqual(
                font["name"].getDebugName(14),
                "https://openfontlicense.org",
            )
            self.assertEqual(
                font["name"].getDebugName(0),
                "Copyright 2026 Test Author",
            )
            self.assertEqual(
                font["name"].getDebugName(7),
                "Test is a trademark of Test Author.",
            )
            cff_metadata = font["CFF "].cff.topDictIndex[0].rawDict
            self.assertEqual(cff_metadata["version"], "1.000")
            self.assertEqual(
                cff_metadata["Copyright"],
                "Copyright 2026 Test Author",
            )
            self.assertEqual(
                cff_metadata["Notice"],
                "Test is a trademark of Test Author.",
            )
            font.close()

    def test_math_is_built_with_math_and_ssty_tables(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_directory = Path(temporary_directory)
            output_path = build_font(
                PROJECT_DIRECTORY,
                "math",
                output_directory=output_directory,
            )

            self.assertEqual(output_path.name, "PL46-Math.otf")
            self.assertEqual(list(output_directory.iterdir()), [output_path])
            font = TTFont(output_path)
            self.assertIn("MATH", font)
            self.assertIn("GSUB", font)
            self.assertEqual(font["post"].isFixedPitch, 0)
            self.assertEqual(
                font["MATH"].table.MathConstants.AxisHeight.Value,
                225,
            )
            italics_correction = (
                font["MATH"]
                .table.MathGlyphInfo.MathItalicsCorrectionInfo
            )
            serialized_italic_corrections = dict(
                zip(
                    italics_correction.Coverage.glyphs,
                    (
                        value.Value
                        for value in italics_correction.ItalicsCorrection
                    ),
                    strict=True,
                )
            )
            self.assertEqual(
                serialized_italic_corrections["contourintegral.v1"],
                300,
            )
            self.assertEqual(
                serialized_italic_corrections["uni2231.v1"],
                400,
            )
            self.assertEqual(
                set(serialized_italic_corrections.values()),
                {200, 300, 400},
            )
            accent_attachment = (
                font["MATH"]
                .table.MathGlyphInfo.MathTopAccentAttachment
            )
            serialized_accent_attachments = dict(
                zip(
                    accent_attachment.TopAccentCoverage.glyphs,
                    (
                        value.Value
                        for value in accent_attachment.TopAccentAttachment
                    ),
                    strict=True,
                )
            )
            self.assertEqual(serialized_accent_attachments["j"], 500)
            self.assertEqual(serialized_accent_attachments["j.italic"], 500)
            self.assertEqual(serialized_accent_attachments["t"], 200)
            self.assertEqual(serialized_accent_attachments["t.italic"], 200)
            self.assertEqual(serialized_accent_attachments["J.st"], 505)
            self.assertEqual(
                serialized_accent_attachments["J.italic.st"],
                505,
            )

            self.assertIsNone(
                font["MATH"].table.MathGlyphInfo.MathKernInfo
            )

            scripts = {
                record.ScriptTag: record.Script
                for record in font["GSUB"].table.ScriptList.ScriptRecord
            }
            self.assertIn("math", scripts)
            feature_records = font["GSUB"].table.FeatureList.FeatureRecord
            math_feature_indexes = scripts["math"].DefaultLangSys.FeatureIndex
            self.assertEqual(
                [feature_records[index].FeatureTag for index in math_feature_indexes],
                ["ssty"],
            )
            ssty_feature = feature_records[math_feature_indexes[0]].Feature
            ssty_lookups = [
                font["GSUB"].table.LookupList.Lookup[index]
                for index in ssty_feature.LookupListIndex
            ]
            self.assertEqual(
                {lookup.LookupType for lookup in ssty_lookups},
                {1},
            )
            single_substitutions = {
                base: alternate
                for lookup in ssty_lookups
                if lookup.LookupType == 1
                for subtable in lookup.SubTable
                for base, alternate in subtable.mapping.items()
            }
            self.assertEqual(
                single_substitutions["A"],
                "A.st",
            )
            self.assertEqual(
                single_substitutions["A.italic"],
                "A.italic.st",
            )

            variants = font["MATH"].table.MathVariants
            self.assertEqual(variants.MinConnectorOverlap, 25)
            index = variants.VertGlyphCoverage.glyphs.index("parenleft")
            construction = variants.VertGlyphConstruction[index]
            self.assertEqual(
                [
                    (record.VariantGlyph, record.AdvanceMeasurement)
                    for record in construction.MathGlyphVariantRecord
                ],
                [
                    ("parenleft", 850),
                    ("parenleft.v1", 1050),
                    ("parenleft.v2", 1250),
                    ("parenleft.v3", 1450),
                    ("parenleft.v4", 1670),
                    ("parenleft.v5", 1870),
                    ("parenleft.v6", 2070),
                    ("parenleft.v7", 2270),
                ],
            )
            expected_vertical_advances = (
                850,
                1050,
                1250,
                1450,
                1670,
                1870,
                2070,
                2270,
            )
            vertical_bases = (
                "uni27E8",
                "uni27E9",
                "uni27EA",
                "uni27EB",
                "uni2308",
                "uni2309",
                "uni230A",
                "uni230B",
                "uni27E6",
                "uni27E7",
            )
            expected_parts_by_base = {
                "uni2308": ("uni2308.bt", "uni23A2", "uni23A1"),
                "uni2309": ("uni2309.bt", "uni23A5", "uni23A4"),
                "uni230A": ("uni23A3", "uni23A2", "uni230A.tp"),
                "uni230B": ("uni23A6", "uni23A5", "uni230B.tp"),
                "uni27E6": ("uni27E6.bt", "uni27E6.ex", "uni27E6.tp"),
                "uni27E7": ("uni27E7.bt", "uni27E7.ex", "uni27E7.tp"),
            }
            for base in vertical_bases:
                index = variants.VertGlyphCoverage.glyphs.index(base)
                construction = variants.VertGlyphConstruction[index]
                self.assertEqual(
                    [
                        (record.VariantGlyph, record.AdvanceMeasurement)
                        for record in construction.MathGlyphVariantRecord
                    ],
                    [
                        (
                            base if variant_index == 0 else f"{base}.v{variant_index}",
                            advance,
                        )
                        for variant_index, advance in enumerate(
                            expected_vertical_advances
                        )
                    ],
                )
                if base in vertical_bases[4:]:
                    self.assertEqual(
                        [
                            (part.glyph, part.PartFlags)
                            for part in construction.GlyphAssembly.PartRecords
                        ],
                        [
                            (expected_parts_by_base[base][0], 0),
                            (expected_parts_by_base[base][1], 1),
                            (expected_parts_by_base[base][2], 0),
                        ],
                    )
            expected_advances = (
                250,
                450,
                650,
                850,
                1050,
                1250,
                1450,
                1650,
            )
            for base in ("tildecomb", "circumflexcmb", "caroncmb"):
                index = variants.HorizGlyphCoverage.glyphs.index(base)
                construction = variants.HorizGlyphConstruction[index]
                self.assertEqual(
                    [
                        (record.VariantGlyph, record.AdvanceMeasurement)
                        for record in construction.MathGlyphVariantRecord
                    ],
                    [
                        (
                            base if variant_index == 0 else f"{base}.h{variant_index}",
                            advance,
                        )
                        for variant_index, advance in enumerate(
                            expected_advances
                        )
                    ],
                )
                self.assertEqual(font["hmtx"].metrics[base][0], 0)
            self.assertIn(
                "parenleft",
                font[
                    "MATH"
                ].table.MathGlyphInfo.ExtendedShapeCoverage.glyphs,
            )
            font.close()

    def test_accent_metrics_apply_without_math(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            output_path = build_font(
                PROJECT_DIRECTORY,
                "regular",
                output_directory=Path(temporary_directory),
            )

            font = TTFont(output_path)
            self.assertNotIn("MATH", font)
            self.assertEqual(font["hmtx"].metrics["tildecomb"][0], 0)
            self.assertEqual(font["hmtx"].metrics["circumflexcmb"][0], 0)
            font.close()


if __name__ == "__main__":
    unittest.main()
