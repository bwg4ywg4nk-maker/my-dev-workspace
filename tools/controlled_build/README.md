# Phase-1 controlled-build foundation

This builds **Pillow 12.3.0 / FreeType 2.14.3** for one macOS architecture with
an explicitly supplied, already provisioned CPython (>=3.10, GIL enabled),
Apple compiler tools, and SDK. It installs nothing and downloads nothing.
It does not qualify the ordinary interpreter or create `provider_build_id`.

`profile.json` pins the complete upstream source archive bytes. Supply those
archives as `freetype.tar.gz` and `pillow.tar.gz` in an ignored build directory.
The URLs are locators; the SHA-256 values are the source identities. Archive
digest mismatches stop before extraction. No fonts are needed for the build.

Example from the repository root, using an existing interpreter and SDK:

```sh
.venv/bin/python tools/controlled_build/build.py \
  --sources build/phase1/sources \
  --output build/phase1/local-build \
  --sdk /Library/Developer/CommandLineTools/SDKs/MacOSX.sdk \
  --architecture x86_64 \
  --deployment-target 13.0
```

Use `arm64` only with a matching provisioned Python/toolchain. The output
directory must be new and beneath this repository's ignored `build/` directory.
Failures leave their logs and partial outputs there; they do not install a
provider. `commands.jsonl` and `build.log` record local invocations for diagnosis.
Their machine-specific paths are excluded from declaration identities.

## Fixed build route

FreeType uses its documented `docs/INSTALL.ANY` direct-compilation route.
There is no configure step or dependency discovery. `profile.json` enumerates
every C translation unit, module in registration order, and disabled option.
The recipe generates a separate include tree, `ftmodule.h`, and `ftoption.h`;
it changes FreeType's public function visibility to hidden in that include tree.
The source archives remain unchanged. The stock portable `ftconfig.h` and other
configuration headers are used and hashed as well.

The only registered modules are TrueType, SFNT, and the grayscale rasterizer.
Unicode formats 4 and 12, TrueType bytecode metrics, SFNT names, glyph, bbox,
bitmap and stroker helpers remain. `ftmm.c` supplies the APIs referenced by
unmodified Pillow; GX variation support is disabled. Other font drivers,
autohinting, compressed streams, color/embedded bitmaps, SVG, environment
properties, debug/logging, and the optional libraries are disabled. See the
literal profile for the complete list. Rejecting `FREETYPE_*` and `FT2_*` at
launcher time remains a later requirement despite the build-time disable.

Pillow's pinned `setup.py` source-list literals are parsed without executing
its discovery logic. The recipe compiles its standard `_imaging` core and
`_imagingft`, including the shared `Mode.c` helper used by both. Optional native
feature macros are absent; no Raqm, HarfBuzz, FriBiDi, zlib, JPEG, TIFF, JPEG2000,
imagequant, XCB, WebP, AVIF, LCMS or Tk dependency is linked. The unmodified
`PIL` Python package is copied so `Image`/`ImageFont` imports retain their normal
internal dependencies; no optional native extension is built.

`_imagingft` receives the static archive by explicit filename, never `-lfreetype`.
The linker exports only the relevant `PyInit__...` entry point. Actual export,
undefined-symbol and load-command reports are inspected: an external FreeType
reference, extra export, or dependency other than libSystem fails the build.
A font-free import smoke check verifies both extensions and BASIC availability.
This is a build test, not the deferred trusted fresh-exec bootstrap.

## Bounded audit addition

`pillow-12.3.0-cmap.patch` adds only `_pa_cmap_audit()` to Pillow's native font
object and includes `pa_cmap_audit.h`. It takes no arguments. It accesses the
existing `FontObject.face` inside Pillow's object critical section, opens no
face/library, and returns concrete nested tuples:

```text
(native_count, descriptors, original_index, original_glyphs,
 restored_index, restored_glyphs)
descriptor = (native_index, platform_id, encoding_id, freetype_encoding,
              cmap_format, glyphs)
```

There are at most 256 native maps; larger faces fail before traversal/allocation.
Descriptors preserve native order, including ineligible maps. Eligible maps
have exactly 95 positive glyph IDs for U+0020–U+007E; ineligible maps have an
empty tuple. The original map must be eligible. Every eligible map must agree
with it. Each glyph is checked against the actual face's glyph count. Unsupported
Unicode formats, variation maps, invalid maps, missing glyphs, allocation errors,
and selection/restoration failures return an exception, never partial evidence.
After any attempted map traversal the original map is restored, and its glyphs
are reread before success. Restoration failure cannot return a success result.
The result contains no pointers, arbitrary-query interface, setter, boolean
qualification assertion, or token. Existing upstream Pillow methods are unchanged.

`_build_evidence.validate_audit` checks this immutable bounded schema. It does
not bind an audit to parsed SFNT records or authorize measurement. Same-face
native/SFNT correspondence and final pass-11 integration remain later work.

## Evidence and verification boundaries

`configuration.json` includes source/patch/recipe identities, compiler binary,
version and resource-header identities, linker/archiver/tool identities, Python
binary/header identities, full SDK content identity, ordered flags, architecture,
deployment target, module selection, and actual generated configuration files.
Preprocessor macro dumps validate actual FreeType and Pillow disabled features;
command-line intentions alone are insufficient. SDK/header tree hashes use
sorted relative file names and content digests, plus internal symlink targets.
Absolute deployment paths and timestamps do not enter the manifests.

`evidence.json` binds that configuration to the static archive, both extensions,
link/symbol reports, copied Python implementation, adapter, and audit schema.
`evidence.sha256` identifies those canonical bytes. Declaration validation and
explicit file-byte verification are separate operations. This is deterministic
serialization and artifact evidence, not a claim of bit-for-bit reproducibility,
trusted provenance, loaded-runtime binding, or production qualification.

Unit tests use synthetic declarations and a fake native face. The C harness
injects map-selection, restoration, glyph and allocation failures into the
actual audit implementation. It does not parse fonts or simulate successful
real-font qualification. Build output and import/link checks are separate from
later real-build/font acceptance, which must test exact Arial bytes, candidate
correspondence, metrics, trusted launch, runtime dependencies, and lifecycle.
The ordinary `_open_provider()` and `_PillowBasicCore.inspect_font()` gates
remain unchanged and fail closed.

Run focused tests without installing dependencies:

```sh
PYTHONPATH=src .venv/bin/python -m unittest discover \
  -s tests -p 'test_milestone3_phase3c2b*.py'
```

The fake-face native harness requires macOS, clang and Python >=3.10; it is
explicitly skipped on unsupported development environments. Generated harness
binaries stay under ignored `build/phase1-unit/`.
