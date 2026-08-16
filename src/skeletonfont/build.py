from __future__ import annotations

from collections import Counter
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
    load_release_info,
    load_ssty_data,
    normalize_meta_name,
)
from .math_tables import apply_math_table
from .model import FontMeta, ReleaseInfo
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
        return _load_and_build_font(
            project_directory,
            meta_name,
            output_directory=output_directory,
            catalog=catalog,
        )
    except ProjectDataError as error:
        raise BuildError(meta_name, error) from error


def _load_and_build_font(
    project_directory: Path,
    meta_name: str,
    *,
    output_directory: Path | None,
    catalog: GlyphCatalog | None,
) -> Path:
    """Run one font build before adding its meta-name error context."""

    meta = load_font_meta(project_directory, meta_name)
    release_info = (
        None
        if meta.release_info_file is None
        else load_release_info(project_directory, meta.release_info_file)
    )
    return _build_font_from_meta(
        project_directory,
        meta,
        release_info=release_info,
        output_directory=output_directory,
        catalog=catalog,
    )


def _build_font_from_meta(
    project_directory: Path,
    meta: FontMeta,
    *,
    release_info: ReleaseInfo | None,
    output_directory: Path | None,
    catalog: GlyphCatalog | None,
) -> Path:
    """Build one already-loaded meta after batch preflight."""

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
    ufo = render_font(plan, release_info=release_info)
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
    """Preflight and build several fonts with one source catalog."""

    names = tuple(normalize_meta_name(name) for name in meta_names)
    duplicate_names = sorted(
        name for name, count in Counter(names).items() if count > 1
    )
    if duplicate_names:
        raise ProjectDataError(
            f"Font build contains duplicate meta names: {duplicate_names}"
        )

    metas = []
    for name in names:
        try:
            metas.append(load_font_meta(project_directory, name))
        except ProjectDataError as error:
            raise BuildError(name, error) from error

    release_infos: dict[str, ReleaseInfo | None] = {}
    for meta in metas:
        try:
            release_infos[meta.meta_name] = (
                None
                if meta.release_info_file is None
                else load_release_info(
                    project_directory,
                    meta.release_info_file,
                )
            )
        except ProjectDataError as error:
            raise BuildError(meta.meta_name, error) from error

    metas_by_output: dict[str, list[str]] = {}
    for meta in metas:
        metas_by_output.setdefault(meta.output_stem.casefold(), []).append(
            meta.meta_name
        )
    collisions = {
        output: builds
        for output, builds in metas_by_output.items()
        if len(builds) > 1
    }
    if collisions:
        descriptions = ", ".join(
            f"{output!r}: {builds}"
            for output, builds in sorted(collisions.items())
        )
        raise ProjectDataError(
            "Font builds resolve to duplicate OTF output stems: "
            f"{descriptions}"
        )

    catalog = GlyphCatalog(project_directory)
    paths: list[Path] = []
    for meta in metas:
        try:
            paths.append(
                _build_font_from_meta(
                    project_directory,
                    meta,
                    release_info=release_infos[meta.meta_name],
                    output_directory=output_directory,
                    catalog=catalog,
                )
            )
        except ProjectDataError as error:
            raise BuildError(meta.meta_name, error) from error
    return tuple(paths)
