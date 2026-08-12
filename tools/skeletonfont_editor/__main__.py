from __future__ import annotations

import argparse
import tkinter as tk
from pathlib import Path

from skeletonfont.errors import ProjectDataError

from .app import SkeletonFontEditor


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="skeletonfont-editor",
        description="Edit SkeletonFont glyph-source projects.",
    )
    parser.add_argument(
        "--project-directory",
        type=Path,
        required=True,
        help="project root containing glyph_sources (required)",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    root = tk.Tk()
    try:
        SkeletonFontEditor(root, args.project_directory.resolve())
    except ProjectDataError as error:
        root.destroy()
        raise SystemExit(f"Cannot open editor: {error}") from error
    root.mainloop()
    return 0


raise SystemExit(main())
