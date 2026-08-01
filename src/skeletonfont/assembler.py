from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType

from .errors import AssemblyError
from .loader import load_glyph_source_directory
from .mappings import get_mapping, glyph_name_for_codepoint
from .model import (
    AssembledFont,
    FontMeta,
    GeneratedGlyph,
    GlyphSource,
    SourceRule,
)


class GlyphCatalog:
    """Load each source directory at most once and expose immutable mappings."""

    def __init__(self, project_directory: Path) -> None:
        self.project_directory = project_directory
        self._cache: dict[str, Mapping[str, GlyphSource]] = {}

    def load(self, source_directory: str) -> Mapping[str, GlyphSource]:
        cached = self._cache.get(source_directory)
        if cached is not None:
            return cached

        path = (
            self.project_directory
            / "glyph_sources"
            / Path(source_directory)
        )
        try:
            glyphs = load_glyph_source_directory(path)
        except FileNotFoundError as error:
            raise AssemblyError(
                f"Glyph source directory does not exist: {path}"
            ) from error
        except ValueError as error:
            raise AssemblyError(str(error)) from error

        result = MappingProxyType(glyphs)
        self._cache[source_directory] = result
        return result

    @property
    def loaded_sources(self) -> tuple[str, ...]:
        return tuple(self._cache)


def _matches_rule(glyph: GlyphSource, rule: SourceRule) -> bool:
    if glyph.codepoint is None:
        return rule.include_unencoded
    return any(
        start <= glyph.codepoint <= end
        for start, end in rule.unicode_ranges
    )


def _selected_glyphs(
    source_glyphs: Mapping[str, GlyphSource],
    rule: SourceRule,
) -> tuple[GlyphSource, ...]:
    mapping = (
        None
        if rule.mapping_name is None
        else get_mapping(rule.mapping_name)
    )
    selected: list[GlyphSource] = []
    produced_names: set[str] = set()

    for glyph in source_glyphs.values():
        if not _matches_rule(glyph, rule):
            continue

        if mapping is None:
            entry = glyph
        else:
            if glyph.codepoint is None:
                continue
            target_codepoint = mapping.get(glyph.codepoint)
            if target_codepoint is None:
                continue
            target_name = glyph_name_for_codepoint(target_codepoint)
            if target_name in produced_names:
                raise AssemblyError(
                    f"Mapping {rule.mapping_name!r} produced duplicate "
                    f"glyph name {target_name!r}."
                )
            produced_names.add(target_name)
            entry = replace(
                glyph,
                name=target_name,
                codepoint=target_codepoint,
            )
        selected.append(entry)

    return tuple(selected)


def _describe(entry: GlyphSource) -> str:
    return f"{entry.name!r} from {entry.source_path}"


def _remove_entry(by_name, by_codepoint, entry):
    by_name.pop(entry.name, None)

    if (
        entry.codepoint is not None
        and by_codepoint.get(entry.codepoint) is entry
    ):
        del by_codepoint[entry.codepoint]


def _merge_entry(
    by_name: dict[str, GlyphSource],
    by_codepoint: dict[int, GlyphSource],
    entry: GlyphSource,
    *,
    replace_existing: bool,
    source_directory: str,
) -> None:
    conflicts: dict[str, GlyphSource] = {}
    name_conflict = by_name.get(entry.name)
    if name_conflict is not None:
        conflicts[name_conflict.name] = name_conflict
    if entry.codepoint is not None:
        codepoint_conflict = by_codepoint.get(entry.codepoint)
        if codepoint_conflict is not None:
            conflicts[codepoint_conflict.name] = codepoint_conflict

    if conflicts and not replace_existing:
        descriptions = ", ".join(
            _describe(conflict)
            for conflict in sorted(
                conflicts.values(),
                key=lambda glyph: glyph.name,
            )
        )
        raise AssemblyError(
            f"Source {source_directory!r} cannot add {_describe(entry)}; "
            f"it conflicts with {descriptions}. Set replace_existing to "
            "true on the later source rule to replace it."
        )

    for conflict in conflicts.values():
        _remove_entry(by_name, by_codepoint, conflict)

    by_name[entry.name] = entry
    if entry.codepoint is not None:
        by_codepoint[entry.codepoint] = entry


def _apply_generators(
    real_glyphs_by_name: Mapping[str, GlyphSource],
    real_glyphs_by_codepoint: Mapping[int, GlyphSource],
    generator_names: tuple[str, ...],
) -> tuple[GeneratedGlyph, ...]:
    generated: list[GeneratedGlyph] = []
    occupied_names = set(real_glyphs_by_name)
    occupied_codepoints = set(real_glyphs_by_codepoint)

    for generator_name in generator_names:
        for source_codepoint, target_codepoint in get_mapping(
            generator_name
        ).items():
            if target_codepoint in occupied_codepoints:
                continue
            source = real_glyphs_by_codepoint.get(source_codepoint)
            if source is None:
                continue

            target_name = glyph_name_for_codepoint(target_codepoint)
            if target_name in occupied_names:
                raise AssemblyError(
                    f"Generator {generator_name!r} cannot create "
                    f"{target_name!r}; that glyph name is already in use."
                )

            generated.append(
                GeneratedGlyph(
                    source_name=source.name,
                    target_name=target_name,
                    target_codepoint=target_codepoint,
                )
            )
            occupied_names.add(target_name)
            occupied_codepoints.add(target_codepoint)

    return tuple(generated)


def assemble_font(meta: FontMeta, catalog: GlyphCatalog) -> AssembledFont:
    """Apply ordered source rules and generators to produce one glyph set."""

    by_name: dict[str, GlyphSource] = {}
    by_codepoint: dict[int, GlyphSource] = {}

    for rule in meta.source_rules:
        source_glyphs = catalog.load(rule.source_directory)
        for entry in _selected_glyphs(source_glyphs, rule):
            _merge_entry(
                by_name,
                by_codepoint,
                entry,
                replace_existing=rule.replace_existing,
                source_directory=rule.source_directory,
            )

    if ".notdef" not in by_name:
        raise AssemblyError(
            f"Font build {meta.build_name!r} is missing required glyph '.notdef'."
        )
    generated_glyphs = _apply_generators(
        by_name,
        by_codepoint,
        meta.glyph_generators,
    )
    return AssembledFont(
        info=meta.info,
        glyph_parameters=meta.glyph_parameters,
        output_stem=meta.output_stem,
        point_radius_scale=meta.point_radius_scale,
        real_glyphs=MappingProxyType(by_name),
        generated_glyphs=generated_glyphs,
    )
