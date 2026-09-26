# Phase 4.5A offline deployment evidence

`presentation_agent._deployment_evidence.collect(build, build_files,
native_files, module_paths, runtime)` returns canonical-JSON-compatible
`deployment`, `runtime_manifest`, and `runtime_id` values. Serialize with the
existing `evidence.canonical_bytes`. It does not activate a provider or replace
the launcher's verification hooks.

Inputs are explicit deployment-owner selections:

- `build`: existing Phase-1 evidence; `build_files`: its exact logical-name to
  absolute-file map. All declared bytes must match.
- `native_files`: absolute resolved files keyed by `python-interpreter`,
  `python-framework`, `launcher`, `bootstrap`, `loader`, `c-runtime`, `imaging`,
  `imagingft`, and any required native extension/dependency roles. `bootstrap`
  must name the launcher containing it; other duplicate locations reject.
- `module_paths`: ordered absolute resolved directories. Every file is bound
  by relative name and SHA-256. Symlinks, overlapping roots, empty roots, and
  unlisted native modules reject. Native modules are dependency-closure roots.
  The fixed source inventory in `_deployment_evidence._REQUIRED_MODULES` is
  mandatory: Pillow's ImageFont/Image import path, the measurement provider
  and its application dependencies, and CPython 3.14 source dependencies,
  including bootstrap encodings. Each required source must occur exactly once
  at its import-relative path; a package cannot be split across search roots.
  Filesystem resolution follows search-root order, package-before-module order,
  and CPython 3.14 Darwin extension/source/bytecode suffix precedence. Every
  required source and declared Pillow source must resolve to its verified file
  with the expected package/module shape. Earlier shadow modules, replacement
  packages, and extension or bytecode redirections reject. Resolution never
  executes module code or consults the collecting process's import hooks.
  Required and declared Pillow sources (including package initializers) must
  have no adjacent `.pyc` or matching `__pycache__/<stem>.*.pyc` artifacts.
  All cache tags and optimization levels reject, regardless of cache-header
  validity: a source loader can otherwise use cached code instead of source.
  Bytecode-only, zip-only, or differently frozen source layouts are unsupported.
  Built-in/frozen interpreter bootstrap code is bound by the Python framework;
  the private native bootstrap is bound by the launcher.
- `runtime`: frozen runtime-manifest fields except `native_runtime_artifacts`.
  These platform fields are declarations supplied for the selected interpreter,
  not observations of a running or qualified provider. Darwin, little-endian,
  64-bit CPython 3.14 is required. Runtime and build architectures must agree,
  and every native image must match that architecture.

Collection parses native load commands recursively, rejects missing or unused
native artifacts, and checks controlled Pillow paths against build evidence.
Required Pillow sources, `measurement-adapter`, and `audit-schema` must be
present in build evidence and bound to the exact files in the module inventory.
Every additional declared `PIL.*` source receives the same path binding.
The controlled extensions may link only the declared C runtime: their containing
binary hashes and the Phase-1 static archive evidence bind static FreeType.
Module order, inventories, dependency edges, and build evidence are bound through
a `deployment-evidence` digest in the frozen runtime manifest. Absolute paths do
not enter identities. The existing `_runtime_manifest_id` remains a pure
manifest declaration hash, separate from file verification.

`verify(expected, ...)` recollects all evidence and compares canonical bytes,
rejecting missing, extra, changed, or mismatched evidence. The expected document
must be retained by the deployment owner; collecting new hashes is not proof of
trusted provenance. This offline check does not prevent replacement before load,
verify currently loaded images, or qualify a fresh process.

Supported native inputs are thin little-endian 64-bit Mach-O images for arm64 or
x86_64 with absolute dependency names. Universal binaries, relative or `@rpath`
dependencies, loader environment commands, and runtime search-path commands
reject. Shared-cache-only system images without readable matching files also
reject; no placeholder digest or fallback is produced. No concrete local
runtime deployment is claimed by the synthetic focused tests.
