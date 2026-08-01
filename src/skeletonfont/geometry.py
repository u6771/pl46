"""Public geometry API backed by deterministic cubic stroke expansion."""

from __future__ import annotations

from .cubic_geometry import merge_stroke_paths, stroke_to_path


__all__ = ["merge_stroke_paths", "stroke_to_path"]
