# Milestone 3C.2b: frozen bounded provider-measured layout contract

Status: **A. READY FOR FINAL CONTRACT REVIEW — corrected contract, not yet frozen**.
Baseline: `main`, `0ad5222` (Milestone 3C.2a display resolution).
This document is the sole change in the contract-correction turn. It authorizes no
production code, dependency installation, tests, fixtures, or package exports.
Once approved, its freeze supersedes the earlier statement that 3C.2b remains
unfrozen in
`milestone3_phase3c2_display.md`; that historical document stays unchanged.

## Authority, guarantee, and exclusions

`PresentationDisplay` is the exact logical-text authority. Supported input is
successful `resolve_display()` output or equivalent trusted producer output.
Consume and validate its local display structure, without replaying composition,
binding, evidence, quantity, metadata acquisition, or provenance work. Retain
the supplied display by identity. Never reconstruct text from composition.

There is one public phase, internally separated into allocation/geometry
validation and provider measurement. Successful `layout_presentation()` proves
only **Level-2 provider-measured fit** under its bound profile: complete fields,
valid authored allocations, and four-edge containment of conservative provider
occupancy. Renderer conformance, artifact verification, and human design review
are distinct downstream gates. Provider bounding boxes are provider-relative
observations, never described as mathematically tight raster ink.

No wrapping, autofit, shrinking, pagination, fallback, substitution, or clipping
can count as success. No layout choices are inferred or repaired. Hierarchy,
whitespace optimization, automatic size selection, readability, prominence,
visual balance, and design intelligence are outside this phase. No EMU
conversion is performed here; the future renderer owns it.

## Public surface and exact types

The future `presentation_agent.layout` module exports the thirteen records
below, the three enums below, and `layout_presentation`. There are no package-root
exports in this contract. All records are frozen dataclasses. Listed order is
both field declaration order and positional constructor order. Only explicitly
shown defaults exist. Collections are exact built-in tuples, records and enums
are concrete declared types, strings are exact built-in strings, and integers
are exact built-in integers (booleans and subclasses fail). Invalid public
shape/value/contract inputs raise `ValueError`, following existing project
conventions. No constructor coerces, sorts, normalizes, or repairs inputs.

Supporting notation below is type notation, not additional public records:

- `Q = fractions.Fraction`, concrete type, reduced numerator and positive
  denominator; exact provider-pixel observations. No float stored in a record.
- `Bounds = Tuple[Q, Q, Q, Q]`, in `(left, top, right, bottom)` order, allowing
  zero extent but requiring left <= right and top <= bottom.
- Indices and reading ranks are nonnegative integers. Geometric coordinates
  are signed integers with absolute value <= `2**53 - 1`; derived rational
  observations must have numerator magnitude and denominator <= `2**53 - 1`.
  These arithmetic bounds are fixed validity rules, not caller resource knobs.
- Enum declarations: `FieldRole.TEXT = "text"`,
  `FieldRole.STATUS_LABEL = "status_label"`,
  `FieldRole.CITATION_TITLE = "citation_title"`,
  `FieldRole.CITATION_DETAIL = "citation_detail"`;
  `HorizontalAlignment.LEFT = "left"`;
  `VerticalAlignment.TOP = "top"`. Other enum values are not supported in v1.

| Record | Exact fields, in order |
| --- | --- |
| `Rect` | `left: int, top: int, right: int, bottom: int` |
| `Insets` | `left: int, top: int, right: int, bottom: int` |
| `FieldRef` | `source: BlockRef, role: FieldRole` |
| `FontIdentity` | `sha256: str, face_index: int, family: str, style: str` |
| `LayoutProfile` | `name: str, schema_version: int, font: FontIdentity, pillow_version: str, freetype_version: str, provider_build_id: str, runtime_id: str` |
| `FieldPlacement` | `field: FieldRef, box: Rect, insets: Insets, font_size: int, size_floor: int, horizontal_alignment: HorizontalAlignment, vertical_alignment: VerticalAlignment, reading_order: int` |
| `SlideLayoutSpec` | `slide_index: int, width: int, height: int, safe_margins: Insets, fields: Tuple[FieldPlacement, ...]` |
| `LayoutSpec` | `slides: Tuple[SlideLayoutSpec, ...]` |
| `LineMeasurement` | `line_index: int, source_start: int, source_end: int, baseline: int, advance: Q, provider_bounds: Bounds, occupancy: Rect` |
| `MeasuredField` | `placement: FieldPlacement, text: str, ascent: Q, descent: Q, lines: Tuple[LineMeasurement, ...], occupancy: Rect` |
| `SlideLayout` | `specification: SlideLayoutSpec, fields: Tuple[MeasuredField, ...]` |
| `PresentationLayout` | `display: PresentationDisplay, specification: LayoutSpec, profile: LayoutProfile, slides: Tuple[SlideLayout, ...]` |
| `LayoutLimits` | The eleven integer fields/defaults in the resource table below, in that order. |

`LayoutProfile.profile_id` is a read-only computed string property, not a
constructor field; its exact derivation is below. Its fixed policies are defined
by schema version 1, included in identity, and not configurable fields. This
avoids duplicating constant policy state. The full descriptor is specified here
for hashing; no public persistence/serialization method or framework is added.
These public layout models are v1-scoped to this bounded initial measurement
contract. Future Arabic/RTL or other provider support may require additive or
versioned models; passing a different LayoutProfile to unchanged v1 constructors
does not activate complex-script support.
There is no separate result hash, `fits`, confidence, trust score, certification
token, or origin flag.

## Field enumeration and canonical order

Enumerate slides in contiguous zero-based display slide order. Within each slide:

1. Each `content` item in tuple order: `FieldRef(item.source, TEXT)` maps to
   its exact `DisplayText.text`.
2. Each `qualifications` item in tuple order: first `TEXT` maps to its exact
   text, then `STATUS_LABEL` iff present, mapping to `item.status_label.value`
   (currently exactly `Unverified`).
3. Each `citations` item in tuple order: `CITATION_TITLE` maps to
   `metadata.title`, then `CITATION_DETAIL` maps to
   `metadata.bibliographic_detail`.

Preserve each `BlockRef` value, including slide, block kind, and block index.
These nonvisible references recover the retained source/provenance chain;
no marker, separator, punctuation, or source ID is inserted into text. Citation
fields and qualification labels each require their own allocation even if their
text duplicates another field. No concatenation or deduplication is allowed.

The canonical key is `(source.slide_index, kind_rank, source.block_index,
role_rank)`, with kind ranks content=0, qualification=1, citation=2, and role
ranks text=0, status_label=1, citation_title=0, citation_detail=1. A `FieldRef`
constructor permits TEXT only for content/qualification, STATUS_LABEL only for
qualification, and citation roles only for citation. Presence is factory-checked.
All field tuples use this source order, never reading order. Required field and
allocation sequences must match exactly: no extras, omissions, duplicate refs,
cross-slide allocations, or reordered allocations. Reading order is separately
authored as the permutation `0..N-1` on each slide; total presentation reading
order is `(slide_index, reading_order)`. Empty slides and empty tuples survive.

## Authored geometry and constructor validation

One model unit is 0.001 typographic point. Geometry is integer-only, x increases
rightward and y downward. Rectangles use edge coordinates; `Rect` permits zero
extent and signed edges but requires ordered edges. Field boxes, slides, safe
areas, and content boxes must have strictly positive width and height. Insets
are nonnegative bounded integers in left/top/right/bottom order.

Dimensions and safe margins live **at slide level**, explicitly provided even
for empty slides. There is no presentation-wide default or inheritance.

```
slide = Rect(0, 0, width, height)
safe = Rect(margins.left, margins.top,
            width - margins.right, height - margins.bottom)
content = Rect(box.left + insets.left, box.top + insets.top,
               box.right - insets.right, box.bottom - insets.bottom)
```

The slide contains the safe area; the safe area contains every field box; every
field box contains its content box; the content box contains the translated
measured occupancy. Containment is inclusive on all four edges, with no epsilon.
All placement box pairs on a slide must have disjoint interiors: overlap means
`max(lefts) < min(rights) AND max(tops) < min(bottoms)`. Shared edges and corners
are allowed. No comparisons across slides, and no exemptions for equal text,
different roles, or apparently empty ink. Occupancy fitting by width/height
alone is insufficient.

`font_size` and `size_floor` must each be one of `(18000, 24000, 32000)` and
`font_size >= size_floor`. The floor is an authored constraint, not permission
to shrink. Both alignments must be the declared LEFT/TOP members. Translation
places the field's unshifted line origin at the content box's left/top; it never
compensates for negative bearings or moves text to force fit.

Leaf constructors validate their declared shapes and values: refs as above;
font digest is 64 lowercase hexadecimal characters without prefix, face index
is an exact int (bool and subclasses rejected) with
`0 <= face_index <= 2**53 - 1`, family/style nonblank UTF-8 strings <= 100
characters. This upper bound makes every locally valid FontIdentity representable
by the existing canonical encoder; factory v1 still requires face_index == 0.
For profiles,
schema is exactly 1, name is the exact v1 name, version strings are nonblank
printable ASCII <= 100 characters, and build/runtime IDs are `sha256:` followed
by 64 lowercase hexadecimal characters. Fixed font/provider compatibility is
factory-checked, so a locally valid mismatch can be represented and rejected.
`FieldPlacement` validates positive box/content extents, insets, sizes and ranks.
`LineMeasurement` validates ordered source indices, nonnegative baseline and
advance, Bounds shape, and valid occupancy Rect. It does not assert that the
observation came from a provider.

Parents validate children and their local structure using default ceilings.
They apply the structural length-before-traversal rules below before recursive
validation, even for manually assembled exact-type records with malformed fields.
Frozen dataclasses do not justify trusting that their constructors ran.
`SlideLayoutSpec` enforces dimensions, safe containment, field canonical order,
unique refs, matching slide refs, rank permutation, and box overlap rules.
`LayoutSpec` enforces contiguous slide indices and structural default counts.
`MeasuredField` enforces the v1 text domain (complete nonblank field), exact LF
split/ranges, contiguous line indices, positive ascent, nonnegative descent,
positive H, baseline/occupancy formulas below, field occupancy union, and fit
against its placement. `SlideLayout` requires measured placements equal the
specification's placement sequence. `PresentationLayout` checks concrete display
type, local spec/profile/slide validity, matching output specs, contiguous slide
order, and all default output character/line/count ceilings. It does not replay
upstream provenance, compare text against display authority, load fonts, verify
the installed provider, or certify measurements. Observational arithmetic may
be locally consistent yet fabricated. Only factory success establishes Level-2
measurement and full display correspondence; manual construction does not.

## Text, lines, and exact measurement

The v1 domain is printable ASCII U+0020–U+007E plus LF U+000A, horizontal LTR.
Reject CR (including CRLF), tabs, all other controls, DEL, non-ASCII, combining
characters, surrogates, NBSP, and bidi controls. For every nonempty LF-delimited
line reject a leading or trailing U+0020; this also rejects spaces-only lines.
Preserve repeated internal spaces, every blank line, and trailing LF exactly.
LF is an abstract authored line boundary independent of PowerPoint paragraph
semantics. Do not infer paragraphs, add paragraph spacing, or collapse lines.

Split exactly as `text.split("\n")`, without stripping. Source ranges are
zero-based half-open Python character offsets into `MeasuredField.text`, exclude
LF, and are ordered so the next start is the previous end + 1. Final end equals
`len(text)`; a trailing LF creates a final empty range at that offset. An empty
internal measurement primitive has one empty line with range `[0,0)`; that
primitive is private and does not broaden upstream or public complete-field
acceptance. Complete fields remain nonblank under the existing 3C.2a contract.

Scale is fixed: 10 provider pixels per typographic point and 100 model units per
provider pixel, equivalent to 720 DPI as a measurement scale, not a display
resolution claim. Font sizes therefore load at exactly 180, 240, and 320 provider
pixels. Measure metrics separately for **all three sizes**, even if some are
unused or the presentation is empty; never scale metrics from another size.

For each size, obtain raw ascent A and descent D under the exact return protocol
below; require A > 0, D >= 0 and H = A + D > 0. Never apply abs() to metrics.
Additional leading is zero. For line i in provider pixels:

```
baseline(i) = A + i*H
line_slot(i) = [i*H, (i+1)*H]
```

Use the explicit Pillow call protocol below. Convert accepted integer outputs
directly to Fraction and accepted finite binary floats by their exact integer
ratio, without decimal formatting, precision truncation, or float arithmetic.
Keep exact advance and box coordinates in provider pixels. Empty lines use
advance 0 and box `(0,0,0,0)` without text-measurement calls; their vertical slot
still occupies space.

For advance a and provider bounds `(l,t,r,b)`, construct the rational line
envelope as the bounding rectangle of the union of:

- translated box `[l,r] x [baseline+t,baseline+b]`;
- advance segment from `(0,baseline)` to `(a,baseline)`;
- full vertical slot `{0} x [i*H,(i+1)*H]`.

The slot is a zero-width vertical segment before union, ensuring full line
height even for blank lines. Preserve negative bearings and all signed bounds;
never clamp to zero. Bounds and advance both contribute, regardless of which
is wider. Multiply rational envelope edges by 100, floor minima and ceil maxima
to obtain `LineMeasurement.occupancy` in field-local model units. The field
occupancy is the union bounding Rect of its line occupancies. It includes every
blank/trailing line. `baseline` stores `floor(100*(A+i*H) + 1/2)` model units.
This is nearest rounding with ties toward positive infinity, also for negative
scalars (`-1.5 -> -1`). The same scalar rule applies to any provider scalar
converted to integer geometry; no intermediate observation is rounded. The
exact baseline remains recoverable from ascent/descent and line index.

Translate occupancy by `(content.left, content.top)` for four-edge containment;
records retain field-local occupancy, field-local baselines, and provider-relative
bounds. Integer translation commutes with outward rounding. No rasterization or
glyph-position replay is required. A negative left bearing can legitimately
make a LEFT-aligned placement fail; no bearing compensation is implied.

## Arithmetic checkpoints (normative)

Let M = 2**53 - 1. All rational checks use the fully reduced Fraction, with
positive denominator: abs(numerator) <= M and denominator <= M. The following
are the exhaustive arithmetic checkpoints, in dependency order:

1. Stored model-unit geometry: every coordinate, inset, dimension, size, baseline
   and occupancy integer has abs(value) <= M, in addition to its sign/domain rules.
   Computed safe/content edges are checked as model-unit geometry in pass 7.
2. Provider observations: each A, D, advance and each raw bbox coordinate is
   checked as a reduced rational immediately after validating return shape/type.
3. Exact line metrics: H = A + D is checked in provider pixels. A, D and H
   multiplied by 100 are independently checked as reduced model-unit rationals.
4. Exact baselines and slots: for each i, B = A + i*H, S = i*H and E = (i+1)*H
   are checked in provider pixels, then 100*B, 100*S and 100*E in model units.
5. Scaled exact provider coordinates: 100*a, 100*l, 100*t, 100*r and 100*b
   are checked; translated provider-box vertical edges B+t and B+b are checked
   in provider pixels and after multiplication by 100. Horizontal edges remain
   l/r; the advance endpoint uses (a, B), already checked.
6. Exact occupancy-envelope edges: the four union extrema specified above are
   checked in provider pixels and again after multiplication by 100.
7. Rounded model-unit occupancy: outward-rounded line edges, rounded baseline,
   union field edges, and each content-origin-translated field edge are bounded
   integers. Translation checks occur in pass 13 before edge containment.

Steps 2–6 and local step-7 rounding are owned by factory pass 12; constructors
of measurement records enforce the same applicable equations/checkpoints.
Stored supplied geometry is validated in pass 7. No other algebraic intermediate
is independently bounded: cross products, unreduced numerators, rounding's
addition of 1/2, and expressions inside min/max are not extra checkpoints.
Exact integer/rational evaluation followed by checks on these named quantities
must give the same acceptance for equivalent algebraic evaluation orders.
This is a contract representation bound, not Python machine-integer overflow.

## Initial profile and canonical identity

Human-readable name: `ascii-lf-arial-regular-basic-720dpi-v1`.
Font: Arial Regular, static face index 0, SHA-256
`525979822591a3447cfc49d943d6f7683508e25543407871c0ed8fed05fd2bd9`.
Pillow version: `12.3.0`; linked FreeType version: `2.14.3`; engine: BASIC.
The caller supplies immutable concrete `bytes`. Verify size then digest before
any font parsing. Load those same verified bytes through an in-memory stream,
never a font path. No system font discovery, fallback, download, on-disk copy,
embedding, network, or filesystem writes. Licensing and lawful provisioning
remain deployment responsibilities.

The canonical descriptor is exactly the following JSON-shaped object; variables
refer to the declared record fields and every other value is literal. Arrays
have the displayed order. Object key ordering is handled by project encoding.

```text
{
  "schema_version": schema_version,
  "name": name,
  "font": {"sha256": font.sha256, "face_index": font.face_index,
           "family": font.family, "style": font.style, "static": true},
  "provider": {"name": "Pillow", "version": pillow_version,
               "freetype_version": freetype_version, "engine": "BASIC",
               "build_id": provider_build_id, "runtime_id": runtime_id,
               "runtime_configuration": "controlled-fresh-process-no-overrides-v1",
               "font_inspection": "sfnt-unicode-ascii-agreement-v1",
               "font_encoding": "unic", "measurement_mode": "L",
               "return_protocol": "pillow-basic-exact-shapes-v1",
               "bbox_anchor": "ls", "stroke_width": 0,
               "features": null, "language": null, "direction": null},
  "units": {"model_units_per_point": 1000, "pixels_per_point": 10,
            "model_units_per_pixel": 100},
  "font_sizes": [18000, 24000, 32000],
  "text": {"codepoint_min": 32, "codepoint_max": 126, "line_separator": 10,
           "direction": "ltr", "edge_spaces": "reject",
           "spaces_only_lines": "reject", "internal_spaces": "preserve",
           "blank_lines": "preserve", "trailing_lf": "preserve",
           "empty_primitive_lines": 1, "complete_blank_fields": "reject",
           "lf_semantics": "authored-line-boundary"},
  "measurement": {"observations": "exact-binary-rational",
                  "bounds": "provider-relative-left-baseline",
                  "empty_line": "zero-advance-zero-bounds",
                  "metrics": "independent-all-supported-sizes",
                  "line_height": "ascent-plus-positive-descent",
                  "baseline": "ascent-plus-index-times-line-height",
                  "leading": 0,
                  "envelope": ["translated-provider-box", "advance-segment",
                               "complete-vertical-slot"],
                  "negative_bearings": "preserve"},
  "rounding": {"scalar": "nearest-ties-positive-infinity",
               "minima": "floor", "maxima": "ceiling", "epsilon": 0},
  "layout": {"dimensions": "explicit-per-slide", "safe_margins": "explicit",
             "allocation": "complete-exactly-once-same-slide",
             "field_order": "source-canonical-v1",
             "reading_order": "explicit-per-slide-permutation",
             "size_floor": "supported-size-not-above-size",
             "alignment": ["left", "top"], "origin": "content-left-top",
             "containment": "inclusive-four-edges",
             "overlap": "field-box-interiors-forbidden",
             "shared_edges": "allow", "repair": "forbid",
             "wrap": "forbid", "autofit": "forbid", "shrink": "forbid",
             "pagination": "forbid", "fallback": "forbid",
             "substitution": "forbid", "clipping_success": "forbid"},
  "arithmetic": {"max_integer_magnitude": 9007199254740991,
                 "max_rational_numerator_magnitude": 9007199254740991,
                 "max_rational_denominator": 9007199254740991,
                 "checkpoints": "semantic-checkpoints-v1"},
  "resource_policy": "layout-limits-v1-lower-only",
  "guarantee": "level-2-provider-measured-fit",
  "emu_owner": "future-renderer"
}
```

Use existing `evidence.canonical_bytes()` unchanged: strict UTF-8 JSON, sorted
string keys, compact separators, no floats/coercion, existing size/depth/integer
limits. This is project encoding v1, not RFC 8785. Define:

```
profile_id = "lp1:" + sha256(
    b"presentation-agent:layout-profile:v1\0" + canonical_bytes(descriptor)
).hexdigest()
```

Human-readable name alone is insufficient. Different accepted build/runtime
bindings yield different IDs even with the same profile name. There is no
single universal ID until those bindings are supplied; no fabricated digest or
wildcard binding is allowed. Caller resource overrides are operational ceilings,
not measurement policy, and are not part of profile identity.

Build and runtime IDs bind exact versioned manifests, hashed as `sha256:` plus
the lowercase SHA-256 of `canonical_bytes(manifest)` (no additional namespace;
each manifest includes its distinguishing `kind`). Their required shapes are:

```text
build_manifest = {
  "kind": "pillow-basic-build-v1",
  "artifacts": [[logical_component_name, lowercase_sha256], ...],
  "build_configuration_sha256": lowercase_sha256
}
runtime_manifest = {
  "kind": "pillow-basic-runtime-v1",
  "python_implementation": string,
  "python_version": [major, minor, micro],
  "python_abi": string,
  "os": string,
  "os_release": string,
  "architecture": string,
  "byteorder": "little" or "big",
  "pointer_bits": integer,
  "native_runtime_artifacts": [[logical_component_name, lowercase_sha256], ...]
}
```

Component names are nonempty printable ASCII logical names, <= 100 characters,
without path separators; lists are sorted by name, unique and nonempty. Other
strings are nonempty printable ASCII <= 100 characters. Versions are three
nonnegative exact integers; pointer_bits is 32 or 64. Artifact digests cover the
measurement adapter, loaded Pillow Python/native measurement implementation,
and FreeType (including the containing binary if statically linked). Native
runtime entries cover interpreter executable/library, loader, C runtime, and
transitive native dependencies used by measurement. Duplicate binary bytes may
appear under different logical components. The configuration digest covers the
deployment's immutable build-configuration artifact, including compiler, flags,
target, and FreeType compile options. Paths, timestamps, local font locations,
floats, and unordered serialization never enter these manifests.

The private adapter is bound to a controlled deployment manifest and verifies
the active artifact/runtime bindings before parsing fonts; version strings
alone do not qualify. Read-only inspection of known provider/runtime artifacts
is permitted for identity checks, never font discovery. A deployment unable to
provide/verify this binding is unsupported and fails closed. The controlled
build/configuration manifest and fresh-process real-provider acceptance evidence
are implementation gates, not new public plugin APIs. Nothing downloads or
chooses a provider automatically. Future Arabic/RTL requires a distinct profile
and suitable provider, preserving exact logical text authority; it cannot
silently extend schema/name v1 or reinterpret its LTR/ASCII rules.

## Controlled initialization and private provider protocol

The literal `controlled-fresh-process-no-overrides-v1` binds the following policy
into profile identity. Only a dedicated fresh exec process started by a trusted,
artifact-bound bootstrap is supported. Bootstrap establishes and records the
accepted environment before any Pillow import or FreeType initialization. Use
isolated Python startup (no user site, sitecustomize, user startup hooks or
uncontrolled native preload); only manifest-verified bootstrap/provider code
may initialize or mutate provider state. A fork inheriting initialized native
state is not fresh. Public calls execute in this controlled process; this adds
no public provider plugin or process-management API.

Reject at launch any environment key whose ASCII-uppercase spelling starts
with `FREETYPE_` or `FT2_`, including FREETYPE_PROPERTIES even when empty.
Do not sanitize and then call the original launch acceptable. The bootstrap
uses an explicit deployment allowlist for remaining OS necessities; its contents
and values and provider initialization sequence are included in the immutable
build-configuration artifact. No other provider-affecting environment overrides
are allowed; the verified build audit must establish that its accepted variables
do not select FreeType behavior. Native-loader selection is bound and verified
by the runtime manifest. Runtime property setters, variation setters, monkey
patches, provider replacements and later environment mutation are forbidden.
If such mutation is detected, invalidate the process and fail subsequent calls.

A private bootstrap lifecycle record ties verification to this process and its
loaded artifacts. It is not a public trust token or measurement certification.
If initialization preceded this policy, its timing is unknown, or the trusted
launch/configuration cannot be verified, pass 10 rejects. Removing an override
after initialization or inspecting os.environ later cannot repair eligibility.
No introspection of arbitrary hidden FreeType state is claimed: the guarantee
is verified controlled initialization, not hidden-state equivalence. Repeated
calls within the unchanged controlled process are allowed.

The private `sfnt-unicode-ascii-agreement-v1` inspector uses only Python standard
library bounded binary reads (e.g. struct); Pillow does not expose sufficient
cmap inspection. No fontTools or new third-party inspection dependency is
assumed. This narrow parser accepts standalone TrueType SFNT version 0x00010000,
face 0, and rejects collections, variable fonts (fvar), duplicate table tags,
out-of-range offsets/lengths, malformed required tables, and unsupported relevant
formats. Table/record counts and lengths must fit the verified byte buffer
before traversal/allocation. It reads head, maxp, OS/2, name and cmap; requires
positive numGlyphs, no bold/italic head.macStyle bits, no bold/italic/oblique
OS/2.fsSelection bits, and the regular bit set. Unsupported inspection fails
closed; it never substitutes a font.

Unicode cmap candidates are platform 0 encoding IDs 0–4 or 6, or platform 3
encoding IDs 1 or 10. Require at least one; require format 4 or 12 for every
candidate. Reject format 14/variation and unrecognized platform-0 Unicode
records. Validate all candidate subtable structures and glyph references using
the OpenType format rules, including format-4 idDelta/idRangeOffset and
format-12 ordered nonoverlapping groups. Select via the pinned FreeType
FT_Select_Charmap(FT_ENCODING_UNICODE) algorithm, invoked by `encoding="unic"`;
the verified native build must establish this succeeds. Require every candidate
to agree on all 95 ASCII codepoints, each mapping to 0 < glyph ID < numGlyphs
(glyph 0 is .notdef). Thus multiple candidates cannot change accepted ASCII
mapping. Inspection iterates codepoints 32 through 126 once, checking all bounded
candidate records per codepoint. Do not choose an arbitrary cmap or use ink
width as coverage evidence. The verified build audit must establish that the
provider's eligible Unicode maps are precisely the inspected candidate set and
its glyph-index interpretation agrees with this parser. If this cannot be
shown for the build/font pair, reject in pass 11; no unsupported inspection API
or additional metric probe is presumed.

Require name table format 0. Validate all record bounds; for name IDs 1, 2, 4,
6, 16 and 17, inspect Windows Unicode English-US records (platform 3, encoding
1 or 10, language 0x0409) as strict UTF-16BE, and Macintosh Roman English records
(platform 1, encoding 0, language 0) as strict Mac Roman. Require IDs 1, 2, 4, 6
in at least one such record, with exact values respectively `Arial`, `Regular`,
`Arial`, `ArialMT`; optional IDs 16/17 must be `Arial`/`Regular`. Every matching
record must agree; conflicting duplicates reject, no first-record selection.
Other languages/IDs are not family/style authority and are bounds-checked only.
No trimming, normalization or heuristic name matching. For each loaded size,
getname() must return an exact two-tuple of exact strings (`Arial`, `Regular`),
equal to profile.font.family/style. This cross-check resolves provider name
selection; unsupported naming or disagreement rejects.

Load exactly three `ImageFont.FreeTypeFont` objects from separate BytesIO
streams over the same verified immutable bytes, with explicit size=180,240,320
in that order, index=0, encoding="unic", layout_engine=ImageFont.Layout.BASIC.
Never call a path-based discovery/fallback helper. Verify the resulting engine
is BASIC. Do not set variations or additional provider properties.
For each nonempty line call exactly:

```python
font.getlength(line, mode="L", direction=None, features=None, language=None)
font.getbbox(line, mode="L", direction=None, features=None, language=None,
             stroke_width=0, anchor="ls")
```

Mode L selects grayscale measurement policy; direction=None means BASIC's
horizontal processing of the accepted ASCII text, not script autodetection.
Anchor ls is the left baseline origin. No implicit stroke/anchor/mode policy.
getmetrics() must return an exact tuple of two exact ints, raw A > 0 and D >= 0;
negative descent rejects, never abs(). getlength returns an exact finite float
or exact int, nonnegative. getbbox returns an exact four-tuple of exact finite
floats or exact ints, ordered left <= right and top <= bottom. Reject bools,
subclasses, lists, wrong arity, NaN/infinity and malformed values before rational
conversion. These return rules are `pillow-basic-exact-shapes-v1` in identity.
All exceptions indicating invalid font/provider behavior fail closed as ValueError.

Protocol references: [Pillow 12.3.0 native implementation](https://github.com/python-pillow/Pillow/blob/12.3.0/src/_imagingft.c),
[Pillow ImageFont calls](https://pillow.readthedocs.io/en/stable/_modules/PIL/ImageFont.html),
and [FreeType Unicode selection](https://freetype.org/freetype2/docs/reference/ft2-character_mapping.html).
The normative restrictions above are narrower than those APIs; deployment
acceptance must verify them against the exact bound artifacts.

## Resource ceilings and preflight

`LayoutLimits` fields, constructor order, and defaults:

| Field | Default ceiling |
| --- | ---: |
| `max_slides` | 1,000 |
| `max_display_fields` | 10,000 |
| `max_fields_per_slide` | 128 |
| `max_total_characters` | 2,000,000 |
| `max_characters_per_field` | 100,000 |
| `max_characters_per_line` | 4,096 |
| `max_lines_per_field` | 256 |
| `max_total_line_slots` | 100,000 |
| `max_font_bytes` | 8,388,608 (8 MiB) |
| `max_slide_width` | 14,400,000 |
| `max_slide_height` | 14,400,000 |

Every limit is an exact positive integer <= its default. Overrides only lower.
Equality passes that ceiling; all other constraints must still pass. Count
every visible occurrence, including status labels and both citation fields;
equal strings are charged again. `len(text)` includes LF. Line character counts
exclude LF. Slots are `text.count("\n") + 1`, including empty/trailing lines.
Count both display and specification field populations before matching them,
so malformed excess allocations cannot evade preflight. Apply the same limits
to output structures; no resource charge for nonvisible provenance/IDs.

Trusted deployment/provider artifact verification is not itself charged against
LayoutLimits; a specific covered input (notably font_bytes) still is.

Shallow validation inspects only top-level concrete types and the two slide-tuple
types, without their entries. Check both slide lengths against max_slides before
traversing either. Within a bounded slide, check child tuple types and lengths
before their entries: content/qualification/citation lengths each <=
max_fields_per_slide, and their minimum visible count (content + qualifications
+ 2*citations) within per-slide and cumulative display ceilings. Check all spec
placement tuple lengths and cumulative counts before placement traversal.
Then inspect bounded display entries for optional-label occurrence counts;
non-None is counted without reading .value. Reject an excess count immediately
at its count checkpoint. Only after all structural counts pass inspect labels,
metadata and text. Bounds apply independently to both input populations.

No proportional derived list, set, tuple, field enumeration or output allocation
is allowed before its governing count passes. Already bounded upstream display
tuples can then be traversed under their declared contract, but a manually
assembled public record still receives these local/default ceilings. Measurement
parents check line-tuple length before entries, text length before scanning,
and aggregate counts before proportional derived structures. Scan bounded text
without split lists to establish line/slot limits before allocating ranges.
Structural counts and string lengths use bounded traversal before creating
measurement objects. Count LF and line spans without allocating unbounded split
lists; only split after ceilings pass. Every knowable violation is rejected
before provider measurement. No caching discounts change accounting.

Provider-call bounds for a successful call with N nonempty authored lines:
exactly three in-memory font loads, three `getmetrics` calls, N `getlength` calls,
and N `getbbox` calls. Blank lines cause neither text call. No metric probe strings,
retries, rasterization, alternate engines, or second measurement pass. Font
structure/coverage inspection is one bounded parse of verified bytes, with
95 codepoint rounds over the bounded Unicode candidates, independent of text
length; name cross-checks add three getname calls. These are upper bounds on
failures, which stop at the normative pass-order error. LF needs no glyph.

## Factory validation and failure order

```python
layout_presentation(
    display: PresentationDisplay,
    specification: LayoutSpec,
    *,
    font_bytes: bytes,
    profile: LayoutProfile,
    limits: LayoutLimits = LayoutLimits(),
) -> PresentationLayout
```

The order below is normative. Validate exact types before dereferencing values.
Within a pass use slide/source order, tuple order, and field declaration order;
geometry checks use dimensions, margins, per-field box/insets/sizes/alignment,
then box pairs in ascending index-pair order. A later pass never masks an
earlier failure. Constructor checks on supplied records are revalidated only
at the appropriate pass, not by an eager recursive call that breaks preflight.

“Fail immediately” means fail when the error is reached according to this
normative pass order. This meaning applies everywhere in this contract.
Each consumed check has exactly one factory owner below; constructor invariants
are distributed among these passes, never replayed through recursive post-init.
Explicit subpass/checkpoint orders below override general tuple order.
Missing required attributes on manually assembled records fail in the pass that
owns that attribute; never dereference them in an earlier pass.

1. **Shallow concrete types:** exact display, specification, font_bytes, profile,
   limits types (in signature order), then exact display/spec slide-tuple types.
   No slide entries, profile internals, provenance, or provider access.
2. **Limits:** positive lower-only exact-int fields in declaration order.
3. **Structural and accessible payload preflight:** (a) both slide lengths;
   (b) bounded display slide/container types and tuple length/minimum-field
   counts, then spec slide/container types and placement tuple counts;
   (c) bounded display entry types, optional-label occurrence counts (non-None
   only, no .value), final per-slide/aggregate display field counts;
   (d) payloads in canonical display order. For DisplayText, validate exact text
   type, length ceilings and aggregate cost, then status_label is None or exact
   DisplayStatusLabel.UNVERIFIED; content labels are forbidden. Only now read
   .value and charge its string length. For each citation validate exact
   SnapshotCitationMetadata, snapshot_id exact string with sha256: plus 64
   lowercase hex characters, then required title/detail exact strings,
   lengths and aggregate character costs, then their nonblank requirement.
   Citation metadata object/type/required-string/local ID checks belong solely
   here. Do not validate source refs, indices or text domain here. Strings are
   length-bounded before any nonblank scan; citation nonblank is owned here,
   while DisplayText complete-nonblank is owned by pass 8.
4. **Reference shape and slide correspondence:** first validate every display
   BlockRef, then each spec FieldPlacement outer type and FieldRef (including
   nested BlockRef). Require exact record/enum types, nonnegative exact-int
   indices, and legal role/kind combinations before any key comparison.
   Then validate display/spec slide index types/contiguity, equal slide counts,
   display source slide/kind/block-index matching its tuple location, and no
   duplicate citation snapshot_id within a slide. No metadata/type/string
   revalidation or upstream composition/provenance traversal.
5. **Field enumeration:** derive required FieldRefs/text in the specified order
   from already validated payloads/refs. This pass owns only the mapping;
   it introduces no repeated status/citation validation or provider work.
6. **Coverage and order:** compare required/allocation sequences; enforce unique,
   complete, same-slide, canonical allocations and exact nonnegative reading
   ranks forming each slide's permutation. Shapes were owned by pass 4.
7. **Allocation geometry:** exact geometry record/scalar shapes and bounds,
   dimensions/caller dimension ceilings, margins/safe area, boxes/insets/content,
   sizes/floors/alignment, authored containment and box overlap. Validate only
   these FieldPlacement/SlideLayoutSpec invariants; never replay refs/ranks.
8. **Text/line preflight:** per field in canonical order, first DisplayText
   complete-nonblank, then a full domain scan by character offset, then a scan
   of lines in line order checking length, edge spaces, per-field slot count,
   cumulative slot count, in that order at each line end (including the final
   empty line). No character-length/metadata rechecks. Allocate bounded source
   spans only after all fields' line/slot ceilings pass.
   All input geometry/text/resource checks are now complete except font byte
   size and profile/provider rules explicitly deferred to passes 9–11.
9. **Profile/font identity:** local FontIdentity/LayoutProfile fields in their
   declaration order, fixed v1 name/schema/font family/style/face policy,
   nonempty font bytes <= caller ceiling, then digest equals both profile and
   frozen font digest. Digest precedes any font parsing. Canonical profile
   derivation is owned here; installed version/binding comparison belongs to 10.
10. **Provider compatibility:** require Python >= 3.10 before provider import;
    verify controlled fresh-process lifecycle/configuration, then lazily access
    provider and compare exact Pillow/FreeType versions, BASIC capability,
    verified build/runtime manifests and profile bindings. Runtime capability
    has no installation-route check. No property or engine substitution.
11. **Font parse/coverage/loading:** execute the private protocol on verified
    bytes, establish provider/inspection agreement, then load three fonts in
    ascending size order and validate their engine/name results.
12. **Measurement:** getmetrics in ascending size order, then fields in canonical
    order and lines in line-index order, getlength before getbbox. Own return
    validation and observation/metric/baseline/envelope/local rounding arithmetic
    checkpoints. Store private observations; no containment verdict yet.
13. **Translated containment:** translation arithmetic bounds then left, top,
    right, bottom containment per field in canonical order. Containment is
    intentionally later than measurement because it depends on measured
    occupancy. Provider failure therefore precedes any containment failure,
    including an earlier field's already knowable overflow.
14. **Atomic construction:** construct immutable output retaining display, spec,
    profile and placements by identity. No new input-validation owner or second
    provider pass: constructor assertions reproduce established invariants only.
    Return the whole result; no partial public result escapes.

Competing errors have these exact outcomes:

| Competing defects | First error |
| --- | --- |
| Malformed label and slide/field-count overflow | Structural count, pass 3(a–c), before label access |
| Malformed label and character overflow | First checkpoint in pass 3(d) canonical payload order; text length precedes that item's label |
| Malformed label and line/slot/font-byte overflow | Label, pass 3(d); those resources belong to 8/9 |
| Malformed citation metadata and slide-index/count correspondence mismatch | Citation, pass 3(d), unless structural resource counts already failed |
| Malformed FieldRef and coverage mismatch | Ref shape, pass 4 |
| Geometry failure and provider mismatch | Geometry, pass 7 |
| Text-domain failure and font mismatch | Text, pass 8 |
| Provider failure and measured containment failure | Provider, pass 10–12; containment is pass 13 |

A malformed label and another pass-1/2 error follows the same earlier-pass rule;
"resource overflow" does not move a later resource check ahead of its owner.
All invalid contracts, unavailable/incompatible providers, font failures, and
measurement/containment failures surface as `ValueError` with a stage/role
diagnostic (exact prose is not API). Operational process exceptions such as
MemoryError/KeyboardInterrupt need not be converted. No input mutation, writes,
partial iterator, partial slide, repair, or success result on failure.

## Dependency and renderer boundaries

Implementation must add a named optional dependency extra **`layout`** with
explicit pin `Pillow==12.3.0`, using a `python_version >= '3.10'` marker so base
Python 3.9 resolution remains valid. Base `requires-python = ">=3.9"` stays.
The 3C.2b capability requires Python **3.10 or newer**, a verified runtime binding,
and FreeType **2.14.3**; installing the extra on Python 3.9 does not enable it,
and measurement must fail clearly before provider import. Preserve Python 3.9
syntax/importability for public models and other phases; isolate/lazily import
the measurement adapter. No Pillow import from package root or upstream phases.
The packaging pin alone does not enforce the linked FreeType/build identity;
the runtime gate does. The extra is packaging convenience and reproducibility
policy, not runtime provenance. An identical valid Pillow installation obtained transitively (or by
another route) is accepted if all observable capability, font, controlled
configuration and artifact-binding requirements pass. Never determine how
Pillow was installed. No pyproject edit/install is part of this correction.

`PresentationLayout` exposes, directly or through retained typed records:

- exact display authority and original source chain through `FieldRef.source`;
- slide dimensions/safe margins, boxes/insets, alignments, reading ranks,
  authored size/floor, and exact measured field text;
- target family/style, font digest/face, profile name and canonical profile ID;
- ordered line records with source ranges, field-local baselines, exact rational
  advances/provider bounds and field-local line/field occupancy;
- exact per-size metrics on measured fields and the profile's no-wrap/no-autofit
  policies, including preservation of authored line boundaries.

The renderer obtains a line's exact text by slicing the retained field text;
LF remains represented by the ordered source ranges. It translates geometry
using the content origin and performs its own EMU conversion, font provisioning,
paragraph mapping, and conformance checks. It must not claim replayed glyph
positions, actual artifact fit, or aesthetic quality from this result. No glyph
position stream, embedded font bytes, or renderer import is required here.

## Mandatory implementation acceptance gates

Controlled metric-double tests establish algorithmic behavior independently of
Arial's incidental metrics. Real-provider tests establish the deployment binding;
neither suite substitutes for the other.

### Controlled measurements and structure

- All 95 printable ASCII characters accepted in legal positions (space internally);
  LF accepted; reject every other ASCII control, CRLF, tabs, DEL, non-ASCII,
  surrogates, bidi/zero-width/combining characters, edge spaces, spaces-only lines,
  complete empty/blank fields. Do not weaken upstream display acceptance.
- Every visible role, optional-label absence/presence, repeated identical text,
  citation title/detail separation, source-ref preservation, no inserted markers,
  complete/duplicate/extra/missing/cross-slide coverage, canonical order and
  independent reading-order permutations, empty slides/presentation.
- Blank interior/leading lines, trailing LF (including consecutive trailing LF),
  repeated internal spaces, exact source slices/ranges; private empty-string
  primitive yields one slot. LF carries no paragraph semantics.
- Negative bearings on all applicable edges; advance wider than box and box
  wider than advance; provider bounds preserved unmodified; full slot occupancy
  even for blank lines; three independent size metrics; no added leading.
- Exact rational observations including noninteger binary ratios; scalar ties
  positive/negative; floor/ceiling signs; no early rounding; exact boundary pass
  and one-model-unit violation of each left/top/right/bottom occupancy edge;
  width/height-only false positives, final/trailing-line vertical overflow.
- Slide/safe/box/content containment, zero/negative dimensions, oversized insets,
  signed coordinates, every containment edge exact pass/one-unit failure;
  overlapping boxes rejected and shared edge/corner success; sizes and floors,
  unsupported enum values, no inferred alignment or size choice.
- Each resource ceiling: exact default, one above, lowered exact, lowered one
  above; zero/negative/bool/subclass/raised-limit rejection. If the pinned font's
  fixed length prevents a successful real-provider max-font-bytes fixture, test
  the size gate independently and use a digest mismatch to show exact size
  advanced to the next gate. Likewise isolate a ceiling when another constraint
  prevents a jointly valid example; equality passes the ceiling, not all gates.
- Preflight-before-measurement with instrumented forbidden-call sentinels;
  deterministic call bounds (including empty input), precise failure precedence,
  atomic late failure at final field, no mutation, equal repeated-call structures,
  no caching-dependent results and no provider call in constructors.
- Manual local-valid fabricated observations and mismatched retained display
  demonstrate the constructor/factory trust distinction without origin tokens.
- Missing dependency, font digest mismatch before parse, profile/version/build/
  runtime mismatch, unavailable BASIC, invalid provider outputs, static-face/name/
  cmap failures, no engine/font fallback. SHA and profile canonical preimages,
  manifest ordering, all descriptor policies and build/runtime identity changes.
- No rendering/EMU work, no upstream rebinding or provenance replay, no network,
  font discovery, filesystem writes, downloads, font copying, or embedding;
  upstream/package-root import and Python 3.9 compatibility regression gates.

### Real Arial / Pillow deployment acceptance

- Provision legally supplied exact-digest Arial bytes outside repository
  fixtures; exercise Pillow 12.3.0, linked FreeType 2.14.3 and explicit BASIC with
  verified build/runtime manifests. Missing assets may skip a developer test,
  but a skipped real-provider gate cannot qualify a deployment or completion.
- Verify all printable ASCII mappings and measure every character in valid
  contexts at all three sizes; verify reported family/style/static face, actual
  metrics, exact returned ratios and baseline-relative boxes. Include internal
  spaces, blank lines, trailing LF, multi-line and every field-role inputs.
- Exact-fit and one-unit-overflow placements derived from actual observations;
  deterministic repeated calls and a fresh process using the same controlled
  runtime yield equal observations and the same canonical profile ID.
- Reject altered bytes and changed provider/build/runtime binding in fresh
  processes; no system font access, persistent font files, network, or renderer.
- Run focused layout tests and existing regression suite after implementation;
  record real-provider environment/manifests and acceptance outcome without
  committing licensed font bytes. Do not claim renderer or artifact verification.

### Correction-specific acceptance gates (normative)

- Fresh exec with allowed environment and verified bootstrap accepts; repeated
  calls and another identically controlled exec give identical identity/results.
  Fresh launches with FREETYPE_PROPERTIES absent versus present (empty, valid
  override, malformed override), FT2_DEBUG, any FREETYPE_/FT2_ key, and case
  variants reject the latter. Initialize first and remove an override, initialize
  without bootstrap evidence, inherit a forked provider, or change properties/
  environment after initialization: reject, never retrospectively certify.
  An allowlist/build-configuration change changes the build/profile identity;
  unsupported policy changes reject. Tests need fresh-process evidence, not just
  monkeypatched environment reads in an already initialized test runner.
- Exercise every competing-failure row above with earlier-pass sentinels proving
  later provider calls/comparisons never occur. Include both earlier/later field
  character overflow versus malformed label, malformed citation object/title/
  detail versus slide mismatch, malformed nested ref versus missing allocation,
  and final-line provider failure versus first-field containment failure.
- FontIdentity face_index 0 and M encode; M+1, negative, bool and int subclass
  reject locally. Nonzero locally valid indices reject factory v1. Encode every
  boundary combination of locally valid FontIdentity string lengths and index.
- Assert exact font-load kwargs and measurement kwargs, all three size/name/
  metric calls; reject malformed tuple shapes/scalars, negative raw metrics,
  nonfinite values, cmap disagreements/missing glyph/unsupported formats,
  conflicting name records, provider-name mismatch and unproved map agreement.
  Use the exact licensed font deployment gate to prove the narrow parser accepts
  its tables; a skip is not completion. No fontTools assumption or fallback.
- For every arithmetic checkpoint item 1–7, test abs(value) or reduced numerator
  and denominator exactly M and M+1, both signs where allowed, and isolate each
  named quantity (including scaled metrics/coordinates, slots, translated bbox,
  envelope, rounding and translated occupancy). Because observations can make
  another checkpoint fail first, test those otherwise unreachable boundaries in
  private arithmetic units as well as integrated precedence fixtures. Include
  reducible fractions with large unreduced intermediates, alternate equivalent
  algebra and cancellation: identical semantic quantities give identical verdicts.
  Sign/domain rules still apply; equality only passes the isolated bound.
- Oversized slide, placement, display-container and line tuples on manually
  assembled exact records reject before entry access; malformed first entries
  cannot mask an earlier length excess. Instrument absence of proportional
  enumeration/list/set/split allocation before count gates, including lowered
  caller ceilings and default constructor ceilings. Test aggregate counts too.
- Capability tests accept identical bound installations from the optional extra,
  transitive dependency or direct provisioning; no installation-origin probe.
  Assert the public table contains exactly 13 records, and alternative profiles
  cannot activate Arabic/RTL through unchanged v1 constructors.

## Contract correction findings

No internal contradiction requires changing the proposed ceilings. Upstream
display character limits and the new per-line/slot limits are cumulative. An
exact ceiling succeeds only with respect to that ceiling, not despite another
invalid constraint. Empty internal primitives do not change complete-field
validity. Negative bearings can fail strict left/top alignment by design.

The known base Python 3.9 versus Pillow 12 boundary is resolved by the optional
`layout` extra and explicit Python 3.10+ capability gate. Concrete provider build
and runtime digests are deployment-specific and remain required acceptance
inputs; this freeze does not pretend they or real-provider acceptance were
measured. This is a contract correction only, ready for final contract review,
with no implementation or execution claim for 3C.2b. No new architectural blocker was
identified in this document review. Actual controlled deployment/font acceptance
remains an implementation gate, not an asserted result. Renderer conformance
and artifact verification remain downstream and are never implied by Level-2
success.
