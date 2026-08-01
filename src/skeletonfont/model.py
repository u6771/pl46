from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Mapping


Point = tuple[float, float]
UnicodeRange = tuple[int, int]
CapStyle = Literal["round", "flat"]


@dataclass(frozen=True, slots=True)
class StrokeRecord:
    """One normalized centerline and its outline-expansion settings."""

    centerline: tuple[Point, ...]
    thickness_scale: float
    start_cap: CapStyle
    end_cap: CapStyle
    filled: bool


@dataclass(frozen=True, slots=True)
class GlyphSource:
    """A validated glyph design before font-specific metrics are resolved."""

    name: str
    codepoint: int | None
    monospace_x_offset: float
    y_offset: float
    x_extent: float
    y_extent: float | None
    skeleton: tuple[StrokeRecord, ...]
    source_path: Path


@dataclass(frozen=True, slots=True)
class SourceRule:
    """Select and optionally remap glyphs from one source directory."""

    source_directory: str
    unicode_ranges: tuple[UnicodeRange, ...]
    include_unencoded: bool
    replace_existing: bool
    mapping_name: str | None


@dataclass(frozen=True, slots=True)
class MathConfig:
    """Names of the optional inputs used to construct OpenType math data."""

    constants_file: str
    variants_file: str | None
    ssty_file: str | None


@dataclass(frozen=True, slots=True)
class MathAssemblyPartData:
    """One validated assembly part before units and scales are resolved."""

    glyph_name: str
    start_connector_extent: float
    end_connector_extent: float
    start_scale: float | None
    end_scale: float | None
    extender: bool


@dataclass(frozen=True, slots=True)
class MathGlyphAssemblyData:
    """One ordered raw MATH glyph assembly."""

    italic_correction: int
    parts: tuple[MathAssemblyPartData, ...]


@dataclass(frozen=True, slots=True)
class MathData:
    """Validated project inputs used to plan OpenType math data."""

    constants_source_path: Path
    constants: Mapping[str, int]
    ssty_source_path: Path | None
    ssty: Mapping[str, tuple[str, ...]]
    min_connector_overlap: int
    vertical_variant_glyphs: Mapping[str, tuple[str, ...]]
    horizontal_variant_glyphs: Mapping[str, tuple[str, ...]]
    vertical_assemblies: Mapping[str, MathGlyphAssemblyData]
    horizontal_assemblies: Mapping[str, MathGlyphAssemblyData]


@dataclass(frozen=True, slots=True)
class FontInfo:
    """Immutable identity and vertical metrics for one font."""

    family: str
    style: str
    units_per_em: int
    ascender: float
    descender: float
    cap_height: float
    x_height: float


@dataclass(frozen=True, slots=True)
class GlyphParameters:
    """Font-wide parameters used to resolve glyph geometry and metrics."""

    radius: float
    grid: float
    y_shift: float
    monospace_width: float | None
    left_spacing: float
    right_spacing: float
    use_scaled_edge_thickness: bool


@dataclass(frozen=True, slots=True)
class FontMeta:
    """Validated parameters for one font build."""

    build_name: str
    meta_path: Path
    info: FontInfo
    glyph_parameters: GlyphParameters
    point_radius_scale: float
    source_rules: tuple[SourceRule, ...]
    glyph_generators: tuple[str, ...]
    glyph_config_file: str | None
    kerning_file: str | None
    output_stem: str
    math_config: MathConfig | None


@dataclass(frozen=True, slots=True)
class GeneratedGlyph:
    """One glyph copied from a real glyph after rendering."""

    source_name: str
    target_name: str
    target_codepoint: int


@dataclass(frozen=True, slots=True)
class AssembledFont:
    """The immutable glyph set selected for one font build."""

    info: FontInfo
    glyph_parameters: GlyphParameters
    output_stem: str
    point_radius_scale: float
    real_glyphs: Mapping[str, GlyphSource]
    generated_glyphs: tuple[GeneratedGlyph, ...]


@dataclass(frozen=True, slots=True)
class GlyphSpacingOverride:
    """Additive spacing adjustments for one proportional glyph."""

    left_spacing: float
    right_spacing: float


@dataclass(frozen=True, slots=True)
class KerningPair:
    """One resolved UFO kerning pair."""

    left: str
    right: str
    value: float


@dataclass(frozen=True, slots=True)
class KerningData:
    """Validated kerning groups and pairs loaded from one file."""

    source_path: Path
    groups: Mapping[str, tuple[str, ...]]
    pairs: tuple[KerningPair, ...]


@dataclass(frozen=True, slots=True)
class StrokePlan:
    """A topology-resolved centerline with its final expansion radius."""

    centerline: tuple[Point, ...]
    radius: float
    start_cap: CapStyle
    end_cap: CapStyle
    closed: bool
    filled: bool


@dataclass(frozen=True, slots=True)
class RealGlyphPlan:
    """Resolved metrics and drawing inputs for one rendered glyph."""

    name: str
    codepoint: int | None
    source_path: Path
    width: int
    strokes: tuple[StrokePlan, ...]


@dataclass(frozen=True, slots=True)
class MathVariantRecord:
    """One resolved size option in a MATH glyph construction."""

    glyph_name: str
    full_advance: int


@dataclass(frozen=True, slots=True)
class MathAssemblyPartPlan:
    """One fully resolved OpenType MathGlyphAssembly part record."""

    glyph_name: str
    start_connector_length: int
    end_connector_length: int
    full_advance: int
    extender: bool


@dataclass(frozen=True, slots=True)
class MathGlyphAssemblyPlan:
    """One fully resolved OpenType MathGlyphAssembly."""

    italic_correction: int
    parts: tuple[MathAssemblyPartPlan, ...]


@dataclass(frozen=True, slots=True)
class MathPlan:
    """All resolved inputs needed to compile GSUB and MATH data."""

    constants: Mapping[str, int]
    ssty_feature: str | None
    vertical_variant_records: Mapping[str, tuple[MathVariantRecord, ...]]
    horizontal_variant_records: Mapping[str, tuple[MathVariantRecord, ...]]
    min_connector_overlap: int
    vertical_assemblies: Mapping[str, MathGlyphAssemblyPlan]
    horizontal_assemblies: Mapping[str, MathGlyphAssemblyPlan]
    extended_shapes: frozenset[str]


@dataclass(frozen=True, slots=True)
class FontPlan:
    """A font build with no remaining metric or transform decisions."""

    info: FontInfo
    output_stem: str
    point_radius_scale: float
    kerning: KerningData | None
    math: MathPlan | None
    real_glyphs: Mapping[str, RealGlyphPlan]
    generated_glyphs: tuple[GeneratedGlyph, ...]
