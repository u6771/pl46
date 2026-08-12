from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Mapping


Point = tuple[float, float]
UnicodeRange = tuple[int, int]
CapStyle = Literal["round", "flat"]
EmbeddingPermissions = Literal[
    "installable",
    "restricted",
    "preview_and_print",
    "editable",
]


@dataclass(frozen=True, slots=True)
class UnicodeDomain:
    """A canonical union of disjoint, non-adjacent Unicode ranges."""

    ranges: tuple[UnicodeRange, ...]

    def __contains__(self, codepoint: int) -> bool:
        return any(
            start <= codepoint <= end
            for start, end in self.ranges
        )


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
class AssembledGlyph:
    """A glyph after source selection and optional remapping."""

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
    unicode_domain: UnicodeDomain | None
    include_unencoded: bool
    replace_existing: bool
    mapping_name: str | None
    thickness_scale: float


@dataclass(frozen=True, slots=True)
class SstyGenerator:
    """Generate script-style alternates from assembled encoded glyphs."""

    unicode_domain: UnicodeDomain
    ssty_alternate_name: str
    thickness_scale: float


@dataclass(frozen=True, slots=True)
class MathTableConfig:
    """Names of the optional inputs used to construct the OpenType MATH table."""

    constants_file: str
    variants_file: str | None
    italics_correction_file: str | None
    accent_attachment_file: str | None
    kern_file: str | None


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
class MathKernTableData:
    """One validated height-dependent mathematical kern table."""

    correction_height: tuple[int, ...]
    kern_values: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class MathGlyphKernData:
    """Optional mathematical kern tables for a glyph's four corners."""

    top_right: MathKernTableData | None = None
    top_left: MathKernTableData | None = None
    bottom_right: MathKernTableData | None = None
    bottom_left: MathKernTableData | None = None


@dataclass(frozen=True, slots=True)
class MathTableData:
    """Validated project inputs used to plan the OpenType MATH table."""

    constants_source_path: Path
    constants: Mapping[str, int]
    italics_correction_source_path: Path | None
    italic_corrections: Mapping[str, int]
    accent_attachment_source_path: Path | None
    accent_attachments: Mapping[str, float]
    kern_source_path: Path | None
    kerns: Mapping[str, MathGlyphKernData]
    min_connector_overlap: int
    vertical_variant_glyphs: Mapping[str, tuple[str, ...]]
    horizontal_variant_glyphs: Mapping[str, tuple[str, ...]]
    vertical_assemblies: Mapping[str, MathGlyphAssemblyData]
    horizontal_assemblies: Mapping[str, MathGlyphAssemblyData]


@dataclass(frozen=True, slots=True)
class SstyData:
    """Explicit GSUB ssty substitutions loaded from one project file."""

    source_path: Path
    substitutions: Mapping[str, tuple[str, ...]]


@dataclass(frozen=True, slots=True)
class FontLicense:
    """Validated license identity shared by one release."""

    identifier: str
    description: str
    url: str | None


@dataclass(frozen=True, slots=True)
class ReleaseInfo:
    """Optional publication metadata applied after design planning."""

    source_path: Path
    version: str | None
    version_major: int | None
    version_minor: int | None
    copyright: str | None
    designer: str | None
    designer_url: str | None
    manufacturer: str | None
    manufacturer_url: str | None
    description: str | None
    trademark: str | None
    vendor_id: str | None
    license: FontLicense | None
    embedding_permissions: EmbeddingPermissions | None


@dataclass(frozen=True, slots=True)
class FontInfo:
    """Immutable identity, classification, and vertical font metrics."""

    family: str
    style: str
    weight_class: int
    is_fixed_pitch: bool
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
    glyph_alias_generators: tuple[str, ...]
    ssty_generators: tuple[SstyGenerator, ...]
    glyph_config_file: str | None
    accent_file: str | None
    kerning_file: str | None
    ssty_file: str | None
    release_info_file: str | None
    output_stem: str
    math_table: MathTableConfig | None


@dataclass(frozen=True, slots=True)
class GlyphAlias:
    """One glyph identity that copies an assembled glyph after rendering."""

    source_name: str
    target_name: str
    target_codepoint: int | None


@dataclass(frozen=True, slots=True)
class AssembledFont:
    """The immutable glyph set selected for one font build."""

    info: FontInfo
    glyph_parameters: GlyphParameters
    output_stem: str
    point_radius_scale: float
    glyphs: Mapping[str, AssembledGlyph]
    glyph_aliases: tuple[GlyphAlias, ...]
    ssty_substitutions: Mapping[str, tuple[str, ...]]
    ssty_alternate_sources: Mapping[str, str]


GlyphAdjustmentGroup = Literal["variant_glyphs", "parts", "variants"]


@dataclass(frozen=True, slots=True)
class GlyphAdjustmentSelector:
    """One exact-glyph or MATH-construction group selector."""

    base_name: str
    group: GlyphAdjustmentGroup | None

    @property
    def text(self) -> str:
        if self.group is None:
            return self.base_name
        return f"{self.base_name}@{self.group}"


@dataclass(frozen=True, slots=True)
class GlyphSpacingAdjustment:
    """Optional additive changes to a glyph's left and right spacing."""

    left: float | None = None
    right: float | None = None


@dataclass(frozen=True, slots=True)
class GlyphAdjustment:
    """Build-time adjustment components selected for glyphs or groups."""

    spacing: GlyphSpacingAdjustment | None = None


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
class GlyphPlan:
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
class MathTablePlan:
    """All resolved inputs needed to compile the OpenType MATH table."""

    constants: Mapping[str, int]
    vertical_variant_records: Mapping[str, tuple[MathVariantRecord, ...]]
    horizontal_variant_records: Mapping[str, tuple[MathVariantRecord, ...]]
    min_connector_overlap: int
    vertical_assemblies: Mapping[str, MathGlyphAssemblyPlan]
    horizontal_assemblies: Mapping[str, MathGlyphAssemblyPlan]
    extended_shapes: frozenset[str]
    italic_corrections: Mapping[str, int]
    top_accent_attachments: Mapping[str, int]
    kerns: Mapping[str, MathGlyphKernData]


@dataclass(frozen=True, slots=True)
class FontPlan:
    """A font build with no remaining metric or transform decisions."""

    info: FontInfo
    output_stem: str
    point_radius_scale: float
    kerning: KerningData | None
    ssty_feature: str | None
    math_table: MathTablePlan | None
    glyphs: Mapping[str, GlyphPlan]
    glyph_aliases: tuple[GlyphAlias, ...]
