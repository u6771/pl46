from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from .assembler import GlyphCatalog, assemble_font
from .compiler import compile_font, save_otf
from .errors import BuildError, ProjectDataError
from .loader import (
    load_accent_glyphs,
    load_font_meta,
    load_glyph_config,
    load_kerning_data,
    load_math_table_data,
    load_ssty_data,
)
from .math_tables import apply_math_table
from .planner import plan_font
from .renderer import render_font


def build_font(
    project_directory: Path,
    meta_name: str,
    *,
    output_directory: Path | None = None,
    catalog: GlyphCatalog | None = None,
) -> Path:
    """Run the complete in-memory build pipeline for one font."""

    try:
        return _build_font(
            project_directory,
            meta_name,
            output_directory=output_directory,
            catalog=catalog,
        )
    except ProjectDataError as error:
        raise BuildError(meta_name, error) from error


def _build_font(
    project_directory: Path,
    meta_name: str,
    *,
    output_directory: Path | None,
    catalog: GlyphCatalog | None,
) -> Path:
    """Run one font build before adding its meta-name error context."""

    meta = load_font_meta(project_directory, meta_name)
    active_catalog = catalog or GlyphCatalog(project_directory)
    assembled = assemble_font(meta, active_catalog)
    glyph_config = (
        None
        if meta.glyph_config_file is None
        else load_glyph_config(project_directory, meta.glyph_config_file)
    )
    accent_glyphs = (
        frozenset()
        if meta.accent_file is None
        else load_accent_glyphs(project_directory, meta.accent_file)
    )
    kerning = (
        None
        if meta.kerning_file is None
        else load_kerning_data(project_directory, meta.kerning_file)
    )
    ssty_data = (
        None
        if meta.ssty_file is None
        else load_ssty_data(project_directory, meta.ssty_file)
    )
    math_table_data = (
        None
        if meta.math_table is None
        else load_math_table_data(project_directory, meta.math_table)
    )
    plan = plan_font(
        assembled,
        glyph_config=glyph_config,
        accent_glyphs=accent_glyphs,
        kerning=kerning,
        ssty_data=ssty_data,
        math_table_data=math_table_data,
    )
    ufo = render_font(plan)
    otf = compile_font(ufo)
    if plan.math_table is not None:
        apply_math_table(otf, plan.math_table)

    destination = (
        project_directory / "build" / "otf"
        if output_directory is None
        else output_directory
    )
    output_path = destination / f"{plan.output_stem}.otf"
    save_otf(otf, output_path)
    return output_path


def build_fonts(
    project_directory: Path,
    meta_names: Iterable[str],
    *,
    output_directory: Path | None = None,
) -> tuple[Path, ...]:
    """Build several fonts while sharing one glyph-source catalog."""

    catalog = GlyphCatalog(project_directory)
    return tuple(
        build_font(
            project_directory,
            meta_name,
            output_directory=output_directory,
            catalog=catalog,
        )
        for meta_name in meta_names
    )
