# PL46 Font Project

PL46 fonts are built from normalized skeleton JSON sources. The reusable Python
build engine is named `skeletonfont`; `PL46` remains the font family and project
name rather than the engine namespace.

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
- `SourceRule` says which `source_directory` participates in a build and whether
  mapped glyphs may `replace_existing` glyphs.
- `FontInfo` contains immutable font identity and vertical metrics, while
  `GlyphParameters` contains the grid, radius, spacing, and other values used
  to resolve glyph geometry. `FontMeta` combines them with the ordered source
  rules and filenames needed only while loading and assembling a build.
- `MathConfig` contains filenames only. Constants, ssty substitutions, discrete
  variant glyphs, and assemblies are loaded into immutable `MathData` instead
  of being carried through as raw dictionaries. One optional `variants_file`
  selects the unified `math_variants/*.json` input; `MathData` directly stores
  its vertical/horizontal variant-glyph mappings, vertical/horizontal assembly
  mappings, and `min_connector_overlap` without wrapper dataclasses.
  Omitting `math_config`, setting it to `null`, or using an empty object disables
  MATH. A non-empty object enables it, so there is no separate `enabled` switch.

## Assemble stage

`GlyphCatalog` is the read-through cache for source directories. The first rule
that refers to a directory loads and validates it; later builds receive the same
immutable mapping instead of reading those JSON files again.

The assembler processes `source_rules` in order. It selects encoded glyphs by
`unicode_ranges`, includes unencoded glyphs only when requested, applies an
optional Unicode mapping, and then checks both glyph-name and Unicode conflicts.
A later rule may remove conflicting entries only with `replace_existing: true`.

An optional mapping replaces only a selected `GlyphSource`'s name and Unicode.
Every selected source, mapped or unchanged, crosses the assembly boundary into
an immutable `AssembledGlyph` with the same fields and shared design data.
`AssembledFont` contains those selected real glyphs, simple generated-glyph copy
records,
`FontInfo`, `GlyphParameters`, the resolved output stem, and point radius scale.
Source rules, generator names, and configuration filenames do not cross the
assemble boundary.

## Plan stage

Glyph config files are parsed before planning into immutable `GlyphAdjustment`
objects. Version 1 supports optional additive `left_adjustment` and
`right_adjustment` fields. These are independent of, and added to, the font-wide
`left_spacing` and `right_spacing` meta values. `plan_font()` performs no file
I/O: it receives an `AssembledFont` and the already-loaded adjustments, then
resolves every remaining metric and transform decision.

A config key is either a real glyph name or a MATH group selector of the form
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
from this owner-closure rule because the shared real glyph is explicit.

Kerning files follow the same boundary. The loader parses them into immutable
`KerningData`; planning verifies every group member and pair side against the
assembled glyph set. The renderer therefore only copies already-validated groups
and pairs into the UFO.

Each source `StrokeRecord` becomes a `StrokePlan`. Its centerline coordinates are
already in font units, consecutive points that coincide at font-unit tolerance
have been removed, and it is non-empty. Planning also resolves `closed`; a closed
plan stores `closed=True` and omits the source centerline's repeated final point.
Its `radius` already includes `thickness_scale`.
Each `RealGlyphPlan` stores only the glyph identity, source path for diagnostics,
final integer width, and planned strokes. Spacing, source offsets, and skeleton
measurements have already been consumed. A `FontPlan` adds the unchanged
`FontInfo`, resolved output stem, point radius scale, kerning, generated copy
records, and an optional `MathPlan`.

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

Planning first groups every real glyph into exactly one role: ordinary, vertical
variant glyph, horizontal variant glyph, vertical assembly part, or horizontal
assembly part, then passes each group to its own role planner. Variant-glyph
planners return both real glyph plans and FullAdvances; each axis-specific planner
returns its real glyph plans and construction records. `plan_font()` merges the
five disjoint glyph-plan mappings only after those planners finish. A glyph may
be reused by several constructions of the same role but cannot cross roles.
Ordinary glyphs
follow the font's normal metric mode; every math
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
`math_variants/*.json` file. Its required `min_connector_overlap` is followed by
`vertical` and `horizontal` construction mappings. Every construction key is a
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
planning, and rendering path as every other real glyph. Assembly fails when it
is missing. Compilation explicitly places it at glyph ID 0.

When a math plan contains ssty substitutions, render writes one `ssty` feature
for the `math` script. One alternate uses a single substitution; two alternates
use an alternate substitution. ufo2ft therefore compiles GSUB together with the
font rather than requiring a later GSUB rewrite.

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
constants, resolved vertical and horizontal variant records, and optional glyph
assemblies are added directly to the returned `TTFont`; a `math/dflt` GSUB
script is retained or created as needed.
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
location. A build declaring `math_config` loads and validates its mathematical
inputs and emits MATH plus the associated math GSUB data. It fails before saving
if those inputs refer to missing glyphs or invalid constructions.

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
| Glyph set | `source_rules`, `glyph_generators` |
| Additional data | `glyph_config_file`, `kerning_file`, `math_config` |

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
| `glyph_generators` | no generators |
| `glyph_config_file`, `kerning_file` | no file |
| `math_config` | MATH disabled |

The nullable fields `output_stem`, `glyph_generators`, `glyph_config_file`,
`kerning_file`, and `math_config` may also be written explicitly as `null`, though
omitting them is preferred when the default is intended.
