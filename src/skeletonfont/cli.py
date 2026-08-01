from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from .build import build_fonts
from .errors import ProjectDataError
from .loader import load_build_list


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="skeletonfont-build",
        description="Build CFF OpenType fonts from skeleton sources.",
    )
    parser.add_argument(
        "meta_names",
        nargs="*",
        metavar="META",
        help=(
            "meta name to build; when omitted, names are read from "
            "build_list.json"
        ),
    )
    parser.add_argument(
        "--project-directory",
        type=Path,
        default=Path.cwd(),
        help=(
            "project root containing meta and glyph_sources; defaults to "
            "the current working directory"
        ),
    )
    parser.add_argument(
        "--output-directory",
        type=Path,
        help="output directory; defaults to PROJECT/build/otf",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    project_directory = args.project_directory.resolve()

    try:
        meta_names = (
            tuple(args.meta_names)
            if args.meta_names
            else load_build_list(project_directory)
        )
        paths = build_fonts(
            project_directory,
            meta_names,
            output_directory=args.output_directory,
        )
    except ProjectDataError as error:
        print(f"Build failed: {error}", file=sys.stderr)
        return 1

    print("Built:")
    for path in paths:
        print(f"  {path}")
    return 0
