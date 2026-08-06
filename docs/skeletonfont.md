# skeletonfont architecture

This document describes the in-repository `skeletonfont` build system used by
PL46. It is developer documentation, not the font project's public overview;
see the [root README](../README.md) for PL46 itself.

The build pipeline is organized around five explicit stages:

```text
load -> assemble -> plan -> render -> compile
```

- **load** parses JSON into validated, immutable objects;
- **assemble** selects, maps, and generates the glyph set for one font;
- **plan** resolves transforms, thickness, spacing, glyph metrics, and math
  constructions exactly once;
- **render** turns the resolved plan into an in-memory UFO;
- **compile** creates an OTF in memory, applies OpenType tables, and saves once.

The previous implementation is kept separately in `../pl46_old` as a behavior
reference while the new pipeline is developed.

## Naming conventions

- Dimensionless multiplicative factors use `<quantity>_scale`, such as
  `thickness_scale` and `point_radius_scale`.
- Boolean options describe the behavior they enable, such as
  `use_scaled_edge_thickness`.
- Fields that contain a filename end in `_file`; fields that contain a directory
  end in `_directory`.
- Serialized JSON uses one canonical schema without legacy aliases. The loader
  also resolves derived runtime values: in particular, authored `thickness`
  becomes `GlyphParameters.radius = thickness / 2`.

The load stage produces a small set of immutable objects:

- `StrokeRecord` contains one `centerline` plus the settings needed to expand it
  into an outline. Its `thickness_scale` multiplies the font's resolved radius.
- `GlyphSource` contains the original design data. It deliberately has no final
  glyph width yet; width is resolved later by the plan stage. Every source
  explicitly writes `name`, `unicode`, `monospace_x_offset`, and `y_offset`.
  A non-empty source writes a non-empty `skeleton`, is validated as glyph-wide
  normalized (`x_min = y_min = 0`), and stores its derived `x_extent` and
  `y_extent`. An empty source writes `x_extent` instead. `skeleton` and
  `x_extent` are mutually exclusive and exactly one must be present.
- `SourceRule` says which `source_directory` participates in a build, whether
  mapped glyphs may `replace_existing` glyphs, and may apply `mapping_name` and
  a font-specific `thickness_scale` while assembling them.
- `FontInfo` contains immutable font identity and vertical metrics, while
  `GlyphParameters` contains the grid, radius, spacing, and other values used
  to resolve glyph geometry. `FontMeta` combines them with the ordered source
  rules and filenames needed only while loading and assembling a build.
- `SstyData` contains optional explicitly authored `ssty` substitutions selected
  by the top-level `ssty_file`; it is independent of MATH.
- `SstyGenerator` selects assembled encoded glyphs by `unicode_domain`, names an
  unencoded script-style alternate, and multiplies a positive
  `thickness_scale` into its existing skeleton.
- `MathTableConfig` contains filenames only. Constants, italic corrections, top
  accent attachments, mathematical kerns, discrete variant glyphs, and
  assemblies are loaded into immutable `MathTableData` instead of being carried
  through as raw dictionaries. Its files live under `math_table/`: respectively
  `constants/`, `italics_correction/`, `accent_attachment/`, `kern/`, and
  `variants/`.
  Omitting `math_table`, setting it to `null`, or using an empty object disables
  MATH. A non-empty object enables it, so there is no separate `enabled` switch.

## Assemble stage

`GlyphCatalog` is the read-through cache for source directories. The first rule
that refers to a directory loads and validates it; later builds receive the same
immutable mapping instead of reading those JSON files again.

The assembler processes `source_rules` in order. It selects encoded glyphs by
the optional `unicode_domain`, includes unencoded glyphs only when requested,
applies an optional glyph-identity mapping, and then checks both glyph-name and
Unicode conflicts. A later rule may remove conflicting entries only with
`replace_existing: true`.

`unicode_domain` accepts a registered domain name or an array whose items are
registered names, one-codepoint arrays, or inclusive two-codepoint ranges. The
loader unions and normalizes them into the smallest sorted collection of
disjoint ranges, without expanding the codepoints. Omitting the field leaves
encoded glyphs unrestricted. For example:

```json
"unicode_domain": [
  "upright_latin",
  ["2202"],
  ["0030", "0039"]
]
```

Registered domains currently include `ascii_digits`, `upright_latin`,
`upright_greek`, `italic_latin`, `italic_greek`, `script_latin`,
`fraktur_latin`, `blackboard_latin`, `bold_latin`, and `bold_greek`. A string
is always a registered name, so a literal singleton must use the nested
`["2202"]` form.
Their explicit range definitions are authoritative and independent of the
registered glyph mappings.

A source rule's optional `thickness_scale` defaults to `1`. The identity case
reuses the source skeleton directly. Any other positive scale is multiplied into
each stroke's authored `thickness_scale` while producing the immutable
`AssembledGlyph`, so all later outline and edge measurements consume one
effective stroke scale.

A `GlyphMapping` independently maps the source codepoint and renames the source
identity. Mathematical alphabet mapping names state both sides, for example
`upright_latin_to_italic_latin` and `upright_latin_to_fraktur_latin`, while
retaining compact codepoint-range builders and producing semantic names such as
`A.italic`, `A.script`, and `A.fraktur`. An optional mapping replaces only a
selected `GlyphSource`'s name and Unicode. Built-in mappings declare optional
source and target domain names and are checked against those explicit domains
once when the immutable mapping registry is created. A `None` side is
unrestricted and skips that check.

Every selected source, mapped or unchanged, crosses the assembly boundary into
an immutable `AssembledGlyph` with the same fields and shared design data.
`AssembledFont` contains those selected glyphs, `GlyphAlias` copy records,
automatically derived ssty substitutions and their assembled glyph
sources, `FontInfo`, `GlyphParameters`, the resolved output stem, and point
radius scale. Source rules, generator names, and configuration filenames do not
cross the assemble boundary.

First, ordered `glyph_alias_generators` produce `GlyphAlias` records from
assembled encoded glyphs. An alias carries a source name and a target identity,
but no independent skeleton. Then ordered `ssty_generators` select both
assembled and alias encoded glyph identities. `ssty_alternate_name` chooses a
total name transformation (`st` or `sts`), while `thickness_scale` is multiplied
into the assembled source glyph with the same skeleton-scaling helper used by
source rules.
The resulting alternate is an unencoded `AssembledGlyph`, so planning resolves
its geometry once like any other glyph. Alternates are not fed back into later
generators. At most two alternates are allowed per base, and generator order
defines the two ssty levels.

```json
"ssty_generators": [
  {
    "unicode_domain": ["upright_latin", "italic_latin"],
    "ssty_alternate_name": "st",
    "thickness_scale": 1.4
  },
  {
    "unicode_domain": ["upright_latin", "italic_latin"],
    "ssty_alternate_name": "sts",
    "thickness_scale": 1.6
  }
]
```

## Plan stage

Glyph config files are parsed before planning into immutable `GlyphAdjustment`
objects. Version 1 supports optional additive `left_adjustment` and
`right_adjustment` fields. These are independent of, and added to, the font-wide
`left_spacing` and `right_spacing` meta values. `plan_font()` performs no file
I/O: it receives an `AssembledFont` and the already-loaded adjustments, then
resolves every remaining metric and transform decision.

An optional top-level `accent_file` selects an `accent/*.json` array of exact
glyph names. It is independent of MATH and may be used by proportional or
monospace builds:

```json
[
  "tildecomb",
  "circumflexcmb"
]
```

Planning separates these glyphs from the ordinary role. An accent receives zero
advance width, and its authored `monospace_x_offset` places its outline around
the combining origin. Accent membership is mutually exclusive with vertical or
horizontal variant and assembly-part roles. Unknown names, duplicate input
names, role overlap, and left/right spacing adjustments on accents are rejected.

A config key is either an assembled glyph name or a MATH group selector of the form
`base@group`. The supported groups are:

| Group | Selected target | Axes |
| --- | --- | --- |
| `variant_glyphs` | the base and all of its discrete variants | vertical and horizontal |
| `parts` | the base's assembly parts, excluding the base | vertical only |
| `variants` | `variant_glyphs` and `parts` together | vertical assemblies only |

For example:

```json
{
  "parenleft@variant_glyphs": {
    "left_adjustment": 50,
    "right_adjustment": 50
  },
  "parenleft@parts": {
    "left_adjustment": 25,
    "right_adjustment": 25
  }
}
```

Part spacing adjustments belong to the vertical construction layout rather than
to individual part glyphs. The current left/right spacing component cannot
target horizontal assembly parts, though the selector remains available for
future components that support them. No assembly part may be configured directly
by glyph name. A construction without an assembly cannot use `parts` or
`variants`.

Configuration order never establishes precedence. A concrete glyph and a group
may not overlap, and overlapping groups on the same base are rejected except for
the disjoint `variant_glyphs` and `parts` pair. When several constructions share
variant glyphs or parts, all owner constructions must be assigned the same
effective group adjustment; equal assignments coalesce and unequal or missing
assignments are rejected. A directly named shared discrete variant is exempt
from this owner-closure rule because the shared glyph is explicit.

Kerning files follow the same boundary. The loader parses them into immutable
`KerningData`; planning verifies every group member and pair side against the
assembled glyph set. The renderer therefore only copies already-validated groups
and pairs into the UFO.

Each source `StrokeRecord` becomes a `StrokePlan`. Its centerline coordinates are
already in font units, consecutive points that coincide at font-unit tolerance
have been removed, and it is non-empty. Planning also resolves `closed`; a closed
plan stores `closed=True` and omits the source centerline's repeated final point.
Its `radius` already includes `thickness_scale`.
Each `GlyphPlan` stores only the glyph identity, source path for diagnostics,
final integer width, and planned strokes. Spacing, source offsets, and skeleton
measurements have already been consumed. A `FontPlan` adds the unchanged
`FontInfo`, resolved output stem, point radius scale, kerning, glyph aliases, an
optional `ssty_feature`, and an optional `MathTablePlan`.

For proportional glyphs with a skeleton, width is resolved as:

```text
x_max * grid
+ left edge radius + right edge radius
+ left spacing + right spacing
```

When `use_scaled_edge_thickness` is enabled, each edge radius uses the greatest
`thickness_scale` among strokes touching that edge. Empty proportional glyphs use
`x_extent * grid + spacing`. When `monospace_width` is present, ordinary glyphs
use `monospace_width + left_spacing + right_spacing`; when it is absent, the
font is proportional. The same font-wide spacing is added to every ordinary
monospace glyph, so their advances remain equal. The current left and right
glyph-adjustment fields are not allowed for ordinary glyphs in monospace builds;
non-ordinary MATH roles continue to use proportional metrics and may use them.

Planning first groups every assembled glyph into exactly one role: ordinary, accent,
vertical variant glyph, horizontal variant glyph, vertical assembly part, or
horizontal assembly part, then passes each group to its own role planner.
Variant-glyph planners return both glyph plans and FullAdvances; each
axis-specific planner returns its glyph plans and construction records.
`plan_font()` merges the six disjoint glyph-plan mappings only after those
planners finish. A glyph may be reused by several constructions of the same role
but cannot cross roles. Ordinary glyphs follow the font's normal metric mode;
every math
construction role uses proportional planning even in a monospace font. Variant
roles include both dictionary keys and alternates, so an empty variant array is
legal and still produces a one-record construction containing its proportional
base. Full advances are resolved while planning each glyph, and each construction
is sorted by full advance.

The source coordinates and their explicit `monospace_x_offset` and `y_offset`
use design grid units. In a monospace build, design x coordinate zero is the
horizontal center axis and maps to `left_spacing + monospace_width / 2` in font
units.
`monospace_x_offset` participates in that positioning and also places vertical
assembly parts in their shared horizontal design coordinates; ordinary
proportional glyphs ignore it. `y_offset` participates in ordinary glyphs and
assembly parts. The planner applies these offsets before multiplying by `grid`.
In contrast, the meta-level `y_shift` uses font units and is added after that
multiplication. Generated glyphs are copied from the rendered source glyph rather
than being planned or expanded again.

Discrete variants and MATH assemblies are authored together in an optional
`math_table/variants/*.json` file. Its required `min_connector_overlap` is
followed by `vertical` and `horizontal` construction mappings. Every construction key is a
variant base. `variant_glyphs` may be omitted or empty, in which case planning
still produces a base-only variant record and assigns that base to the
proportional variant-glyph role. `parts` may be omitted; when present it must be
non-empty and may be accompanied by `italic_correction`. For example:

```json
{
  "min_connector_overlap": 20,
  "vertical": {
    "parenleft": {
      "variant_glyphs": ["parenleft.v1"]
    }
  },
  "horizontal": {}
}
```

An assembly construction adds a non-empty `parts` array; a construction without
an assembly omits `parts` entirely. Each part records grid-unit connector
extents, its extender flag, and optional growth-axis edge scales. A missing scale
uses the measured edge
`thickness_scale`; an explicit value, including zero, overrides that measurement.
Vertical parts use `bottom_scale` and `top_scale`, while horizontal parts use
`left_scale` and `right_scale`.

Vertical constructions need no authored range. Planning overlays all parts after
adding their `monospace_x_offset`, finds the common centerline x extrema, and
uses the largest edge thickness among parts touching each common extremum. Every
part then receives the same proportional width and font-unit x shift. Horizontal
parts receive no left or right spacing. Their width and MATH FullAdvance are the
same resolved growth-axis measurement.

Before any shared part is rendered, planning verifies that every use writes the
same optional growth-axis scales. Each vertical construction then produces one
immutable common layout. A part shared by several constructions is accepted only
when those layouts are equal; a reverse `vertical_layout_by_glyph_name` index
lets the unique glyph plan reference that verified layout directly. Connector
extents and extender flags remain properties of each MATH part occurrence and
may differ.
Consequently every unique part has its edge scales, FullAdvance, and transformed
strokes resolved once while every construction retains its complete ordered part
records.

In other words, an ordinary source y coordinate is transformed as
`(y + source.y_offset) * parameters.grid + parameters.y_shift + radius`.
Thickness, monospace width, spacing, and `y_shift` remain font-unit values.

## Render stage

`render_font()` consumes a `FontPlan` and creates an in-memory `ufoLib2.Font`.
It does not read configuration, recalculate metrics, save a UFO, or compile an
OTF. Font info, Unicode values, and glyph widths are copied directly from the
resolved plan.

`.notdef` is a normal unencoded source glyph and follows the same assembly,
planning, and rendering path as every other assembled glyph. Assembly fails when it
is missing. Compilation explicitly places it at glyph ID 0.

When a font plan contains ssty substitutions, render writes one `ssty` feature
for the `math` script. One alternate uses a single substitution; two alternates
use an alternate substitution. This works independently of whether the build
also emits a MATH table. ufo2ft therefore compiles GSUB together with the font
rather than requiring a later GSUB rewrite. Automatic substitutions and an
optional explicit `ssty_file` may coexist, but defining the same base in both is
an error. An automatically derived alternate inherits the resolved MATH
top-accent attachment of its final assembled source unless it has an
explicit attachment of its own.

An optional `math_table/italics_correction/*.json` file maps exact glyph names to
non-negative italic-correction values in font units. It deliberately has no
group-selector syntax; every glyph that needs a value, including a discrete
size variant, is listed explicitly:

```json
{
  "contourintegral": 200,
  "contourintegral.v1": 200
}
```

Loading validates names and values, and planning rejects references to glyphs
that are not present in the build. The mapping is then written directly to
`MathItalicsCorrectionInfo`.

An optional `math_table/accent_attachment/*.json` file maps exact glyph names to top
accent attachment points in the offset-applied grid coordinate system:

```json
{
  "u1D453": 1,
  "j": 1
}
```

Only ordinary glyphs and vertical or horizontal discrete variant glyphs may be
configured. Combining-accent and assembly-part roles are rejected. Planning
uses the same coordinate transform as its glyph plan. Proportional ordinary and
discrete variant glyphs convert each authored point with:

```text
(attachment - monospace_x_offset) * grid
+ resolved_start_scale * radius
+ effective_left_spacing
```

Monospace ordinary glyphs instead use the same fixed design origin as their
strokes:

```text
(attachment + monospace_x_offset) * grid
+ left_spacing
+ monospace_width / 2
```

The rounded results are written to `MathTopAccentAttachment`.
Glyph aliases cannot be configured directly. After resolving assembled glyphs,
each alias whose `source_name` has an attachment inherits that same final
font-unit value. Inheritance is deliberately limited to this direct
source-to-alias relationship.

Optional per-glyph mathematical kerning is authored in
`math_table/kern/*.json` and enabled with `math_table.kern_file`. Keys are exact
glyph names; group
selectors such as `@variant_glyphs`, `@parts`, and `@variants` are not accepted.
As with top accent attachments, only ordinary and vertical or horizontal
discrete variant glyphs may be configured. Accent and assembly-part roles are
rejected. A glyph alias cannot be configured directly, but inherits the complete
MathKern value of its configured assembled source.

Each glyph defines one or more of `top_right`, `top_left`, `bottom_right`, and
`bottom_left`. A corner's `correction_height` values must be strictly increasing,
and `kern_values` must contain exactly one more integer. Both arrays are already
in font units. An empty height array defines a constant kern:

```json
{
  "A.script": {
    "bottom_right": {
      "correction_height": [],
      "kern_values": [-40]
    }
  }
}
```

The cubic geometry layer expands each `StrokePlan` independently. Open
centerlines use cubic round joins and independently selectable round or flat end
caps. An isolated point becomes a cubic circle using `point_radius_scale`; a
closed centerline may produce either a hollow stroke or a filled shape. A glyph's
expanded strokes are passed to one n-ary pathops union, then simplified once
before being drawn into the UFO. This avoids making the boolean result depend on
an arbitrary sequence of pairwise unions.

For a filled closed centerline, its signed area determines the winding and hence
which offset side is the outer contour. Only that outer contour is emitted. Such
input must have non-zero signed area and is expected to be a simple,
non-self-intersecting path. Circular arcs preserve their supplied start and end
points exactly and calculate only their cubic control points trigonometrically.
The earlier pathops-stroke implementation remains in `pathops_geometry.py`
temporarily as an experimental comparison backend.

Generated glyphs copy their already-rendered source glyph and replace only their
name and Unicode value. This avoids performing the same expansion and boolean
operations again and preserves the assembly provenance through the render stage.

## Compile stage

`compile_font()` passes the in-memory `ufoLib2.Font` directly to
`ufo2ft.compileOTF()` and receives an in-memory `fontTools.ttLib.TTFont`. It does
not save or reopen a UFO, invoke `fontmake`, or create an intermediate OTF.

Compilation keeps overlaps because render has already unioned each glyph, keeps
the planned glyph names instead of applying production-name renaming, and leaves
the input UFO unchanged. Encoded glyphs receive GIDs in ascending Unicode order;
unencoded glyphs follow in glyph-name order. This makes GID assignment independent
of source-rule, source-file, and planning-branch order. For a math build,
constants, italic corrections, resolved vertical and horizontal variant
records, and optional glyph assemblies are added directly to the returned
`TTFont`; a `math/dflt` GSUB script is retained or created as needed.
Connector extents are converted from grid units to font-unit lengths during
planning, before `buildMathTable()` receives them. `save_otf()` then serializes
the font once to the final output path. UFO output remains an optional debugging
artifact rather than part of the normal build pipeline.

## Command line

PL46 requires Python 3.10 or later. From the repository root, create and
activate a virtual environment, then install the build engine in editable mode:

```text
python -m venv .venv
python -m pip install -e .
```

On Windows PowerShell, activate the environment with
`.venv\Scripts\Activate.ps1`; on Linux and macOS, use
`source .venv/bin/activate`.

The CLI uses the current working directory as the project directory by default.
It never infers project data from the installed Python package location or
searches parent directories:

```text
cd D:\workspace\pl46
skeletonfont-build ascii
skeletonfont-build ascii fraktur script
```

`--project-directory` explicitly overrides the current directory when needed:

```text
skeletonfont-build --project-directory D:\workspace\pl46 ascii
```

With no names, the command reads `build_list.json`. Output defaults to
`build/otf/<output_stem>.otf`; `--output-directory` can override the output
location. A build declaring `math_table` loads and validates its mathematical
inputs and emits MATH. A build with automatic or explicit `ssty` substitutions
emits the corresponding GSUB feature independently. It fails
before saving if those inputs refer to missing glyphs or invalid constructions.

Run the committed test suite with:

```text
python -m unittest discover -s tests
```

## Meta schema

Meta fields follow this canonical order. Fields omitted from a particular file
keep their relative position; they are not written merely to show a default.

| Group | Fields, in order |
| --- | --- |
| Identity | `family`, `style`, `output_stem` |
| Font metrics | `units_per_em`, `ascender`, `descender`, `cap_height`, `x_height` |
| Geometry | `grid`, `thickness`, `point_radius_scale`, `y_shift`, `use_scaled_edge_thickness` |
| Horizontal metrics | `monospace_width`, `left_spacing`, `right_spacing` |
| Glyph set | `source_rules`, `glyph_alias_generators`, `ssty_generators` |
| Additional data | `glyph_config_file`, `accent_file`, `kerning_file`, `ssty_file`, `math_table` |

The following fields are required and must always be written:

`family`, `style`, `units_per_em`, `ascender`, `descender`, `cap_height`,
`x_height`, `grid`, `thickness`, and `source_rules`.

All other meta fields are optional:

| Field | Default when omitted |
| --- | --- |
| `output_stem` | derived during loading from `family` and `style` |
| `point_radius_scale` | `1.6` |
| `y_shift` | `0` |
| `use_scaled_edge_thickness` | `false` |
| `monospace_width` | absent; the font uses proportional metrics |
| `left_spacing`, `right_spacing` | `0` |
| `glyph_alias_generators` | no glyph aliases |
| `ssty_generators` | no automatically derived ssty alternates |
| `glyph_config_file`, `accent_file`, `kerning_file`, `ssty_file` | no file |
| `math_table` | MATH disabled |

The nullable fields `output_stem`, `glyph_alias_generators`, `ssty_generators`,
`glyph_config_file`, `accent_file`, `kerning_file`, `ssty_file`, and
`math_table` may also be written explicitly as `null`, though
omitting them is preferred when the default is intended.
