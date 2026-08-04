from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType

from .errors import AssemblyError
from .loader import load_glyph_source_directory
from .mappings import GlyphIdentity, get_mapping
from .model import (
    AssembledFont,
    AssembledGlyph,
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


def _assembled_glyph(
    source: GlyphSource,
    *,
    name: str,
    codepoint: int | None,
    thickness_scale: float,
) -> AssembledGlyph:
    skeleton = source.skeleton
    if thickness_scale != 1:
        skeleton = tuple(
            replace(
                stroke,
                thickness_scale=(
                    stroke.thickness_scale * thickness_scale
                ),
            )
            for stroke in skeleton
        )
    return AssembledGlyph(
        name=name,
        codepoint=codepoint,
        monospace_x_offset=source.monospace_x_offset,
        y_offset=source.y_offset,
        x_extent=source.x_extent,
        y_extent=source.y_extent,
        skeleton=skeleton,
        source_path=source.source_path,
    )


def _selected_glyphs(
    source_glyphs: Mapping[str, GlyphSource],
    rule: SourceRule,
) -> tuple[AssembledGlyph, ...]:
    mapping = (
        None
        if rule.mapping_name is None
        else get_mapping(rule.mapping_name)
    )
    selected: list[AssembledGlyph] = []
    produced_names: set[str] = set()

    for glyph in source_glyphs.values():
        if not _matches_rule(glyph, rule):
            continue

        if mapping is None:
            entry = _assembled_glyph(
                glyph,
                name=glyph.name,
                codepoint=glyph.codepoint,
                thickness_scale=rule.thickness_scale,
            )
        else:
            if glyph.codepoint is None:
                continue
            target = mapping.apply(
                GlyphIdentity(glyph.name, glyph.codepoint)
            )
            if target is None:
                continue
            target_name = target.name
            if target_name in produced_names:
                raise AssemblyError(
                    f"Mapping {rule.mapping_name!r} produced duplicate "
                    f"glyph name {target_name!r}."
                )
            produced_names.add(target_name)
            entry = _assembled_glyph(
                glyph,
                name=target_name,
                codepoint=target.codepoint,
                thickness_scale=rule.thickness_scale,
            )
        selected.append(entry)

    return tuple(selected)


def _describe(entry: AssembledGlyph) -> str:
    return f"{entry.name!r} from {entry.source_path}"


def _remove_entry(by_name, by_codepoint, entry):
    by_name.pop(entry.name, None)

    if (
        entry.codepoint is not None
        and by_codepoint.get(entry.codepoint) is entry
    ):
        del by_codepoint[entry.codepoint]


def _merge_entry(
    by_name: dict[str, AssembledGlyph],
    by_codepoint: dict[int, AssembledGlyph],
    entry: AssembledGlyph,
    *,
    replace_existing: bool,
    source_directory: str,
) -> None:
    conflicts: dict[str, AssembledGlyph] = {}
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
    real_glyphs_by_name: Mapping[str, AssembledGlyph],
    real_glyphs_by_codepoint: Mapping[int, AssembledGlyph],
    generator_names: tuple[str, ...],
) -> tuple[GeneratedGlyph, ...]:
    generated: list[GeneratedGlyph] = []
    occupied_names = set(real_glyphs_by_name)
    occupied_codepoints = set(real_glyphs_by_codepoint)

    for generator_name in generator_names:
        mapping = get_mapping(generator_name)
        for source_codepoint in mapping.codepoints:
            source = real_glyphs_by_codepoint.get(source_codepoint)
            if source is None:
                continue

            target = mapping.apply(
                GlyphIdentity(source.name, source.codepoint)
            )
            assert target is not None
            if (
                target.codepoint is not None
                and target.codepoint in occupied_codepoints
            ):
                continue
            target_name = target.name
            if target_name in occupied_names:
                raise AssemblyError(
                    f"Generator {generator_name!r} cannot create "
                    f"{target_name!r}; that glyph name is already in use."
                )

            generated.append(
                GeneratedGlyph(
                    source_name=source.name,
                    target_name=target_name,
                    target_codepoint=target.codepoint,
                )
            )
            occupied_names.add(target_name)
            if target.codepoint is not None:
                occupied_codepoints.add(target.codepoint)

    return tuple(generated)


def assemble_font(meta: FontMeta, catalog: GlyphCatalog) -> AssembledFont:
    """Apply ordered source rules and generators to produce one glyph set."""

    by_name: dict[str, AssembledGlyph] = {}
    by_codepoint: dict[int, AssembledGlyph] = {}

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
