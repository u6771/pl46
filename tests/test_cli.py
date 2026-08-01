from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from skeletonfont.cli import _parser, main


PROJECT_DIRECTORY = Path(__file__).resolve().parents[1]


class CommandLineTests(unittest.TestCase):
    def test_project_directory_defaults_to_current_working_directory(self) -> None:
        with patch(
            "skeletonfont.cli.Path.cwd",
            return_value=PROJECT_DIRECTORY,
        ):
            args = _parser().parse_args(["ascii"])

        self.assertEqual(args.project_directory, PROJECT_DIRECTORY)

    def test_main_uses_current_working_directory_by_default(self) -> None:
        with (
            patch(
                "skeletonfont.cli.Path.cwd",
                return_value=PROJECT_DIRECTORY,
            ),
            patch(
                "skeletonfont.cli.build_fonts",
                return_value=(),
            ) as build_fonts,
        ):
            exit_code = main(["ascii"])

        self.assertEqual(exit_code, 0)
        build_fonts.assert_called_once_with(
            PROJECT_DIRECTORY.resolve(),
            ("ascii",),
            output_directory=None,
        )

    def test_explicit_project_directory_is_resolved(self) -> None:
        with patch("skeletonfont.cli.build_fonts", return_value=()) as build_fonts:
            exit_code = main(
                [
                    "ascii",
                    "--project-directory",
                    str(PROJECT_DIRECTORY / "."),
                ]
            )

        self.assertEqual(exit_code, 0)
        build_fonts.assert_called_once_with(
            PROJECT_DIRECTORY.resolve(),
            ("ascii",),
            output_directory=None,
        )


if __name__ == "__main__":
    unittest.main()
