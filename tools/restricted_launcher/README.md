# Restricted native launcher: Phase 3 bootstrap

Compile with existing Apple tools and CPython 3.14 headers (no Python linkage):

```sh
mkdir -p build/phase2
clang -std=c11 -Wall -Wextra -Werror \
  -I/Library/Frameworks/Python.framework/Versions/3.14/include/python3.14 \
  -Wno-deprecated-declarations \
  tools/restricted_launcher/launcher.c -framework IOKit \
  -framework CoreFoundation -lbsm -o build/phase2/launcher
```

The native entry reads macOS `KERN_PROCARGS2` for its own original exec
environment before any Python load. It does not use `getenv` or `environ`.
Unavailable, truncated or malformed records fail closed. Admission rejects
ASCII-case-insensitive `FREETYPE_`/`FT2_` prefixes, malformed names, duplicate
names, and any name/value pair outside the compiled exact allowlist. The
foundation's allowlist is empty; no deployment policy is yet authorized.

Private native verification interfaces cover launcher identity, the exact
absolute Python framework path/identity, controlled Pillow/FreeType evidence,
and required runtime artifacts. All must succeed after admission before the
single `dlopen` call. Implementations must establish artifact binding and
prevent substitution between verification and load; these are interfaces,
not implemented production verification. There is no search-path fallback.

Production supplies no verifiers, framework, or verified search paths and always
exits 78. After verified load, the private native bootstrap resolves CPython APIs
from that handle and rejects versions other than 3.14 or an already initialized
interpreter. Isolated configuration disables environment processing, site, user
site, argv parsing, and bytecode writes; enables safe path; and uses only the
explicit absolute module search paths covered by runtime artifact verification.
The fixed native bootstrap entry returns false and never opens a provider.

Native process-lifetime state records the original PID, retained module/callable
and search-path identities, and a copy of the current native environment. Boundary
checks reject fork inheritance, module dictionary replacement or mutation,
search-path replacement or mutation, and environment changes. Observed failure
or any second startup attempt irreversibly invalidates the lifecycle. There is
no reset or Python qualification API. Retained references are intentionally kept
until process exit; a live interpreter's framework must not be unloaded.

Checks cover this controlled bootstrap boundary, not arbitrary hostile Python,
transient mutations restored before a check, or future provider state. No provider
is active and no Python-side environment mapping is used by this bootstrap.
Concrete deployment verifiers, provider qualification/binding,
and pass-11 integration remain deferred and fail closed.

Tests compile a separate native harness with a fake loader to check sequencing
and failure injection; its successful load is not runtime qualification. They
also execute the production entry and inspect its native load dependencies.
Generated binaries remain under ignored `build/phase2-unit/`.

```sh
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p 'test_milestone3_phase3c2b_launcher.py'
```

Phase-3 tests use the existing local CPython 3.14 framework to exercise bootstrap
mechanics, not deployment provenance or qualification:

```sh
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p 'test_milestone3_phase3c2b_bootstrap.py'
```

The loader-state boundary now rejects `DYLD_`, `LD_`, and `__XPC_DYLD_`
variables (ASCII case insensitive), including when explicitly allowlisted.
Before artifact callbacks or Python loading, native observations bind the PID,
initial/current image counts, image paths/addresses, dyld path/address, and active
shared-cache UUID/base/slide. Unsupported, detached, translated, malformed, or
changing observations reject. These observations do not replace existing byte,
launcher, deployment, substitution, or whole-shared-cache checks.

The signing preparation tool uses `--options runtime` without entitlements.
Hardened Runtime supplies pre-entry protection against loader injection, with
library validation enabled. The actual launcher entry always reaches native
runtime verification, including when deployment inputs or environment records
are unavailable. It requires valid, enforced signing and Hardened Runtime,
rejects debugging/exception states and all entitlements, and pins PID/CDHash
once for the complete pre-load boundary. Every artifact callback, loader snapshot,
and startup-inventory check must preserve that identity.

Startup inventory verification exists: the offline collector reverifies deployment
and launcher evidence and emits a deployment/CDHash-bound binary inventory. Native
verification checks its independently trusted pins, exact image closure, standalone
bytes, and immutable shared-cache mappings. Missing evidence or any mismatch denies.
Production supplies no trusted inventory binding or artifact verifiers, so provider
loading and qualification still remain denied, even after runtime checks succeed.

This does not establish deployment trust/provenance or a trusted fresh-exec handoff.
The deployment owner must authenticate and protect inventory/deployment pins;
concrete deployment adapters, substitution protection, and supported deployment
constraints remain unresolved. A fork before the initial identity pin is not
attested by these checks. Offline launch-policy gaps remain unchanged. Test-only
harness substitutions never authorize production execution or qualification.

The attachment observer is now retained by the native launcher before Python
loading. Its single lease binds the protected deployment and launch-policy
bytes, startup inventory, exact interpreter/framework files, and ordered module
roots supplied by the private compiled deployment adapter. Each artifact
callback, the load boundary, and the isolated bootstrap handoff recheck the
observer and original PID/CDHash. Bootstrap boundaries retain that identity
instead of establishing a replacement lease. Failures latch permanently.

The observer's IOKit/audit dependencies are native startup dependencies and must
be included in any future authenticated startup inventory. Existing inventories
and launcher signatures do not authorize this rebuilt binary. The production
entry still supplies no deployment adapter and exits 78; provider loading,
qualification, and Phase 4.5B remain closed. This integration does not implement
the observer's administrative provisioning prerequisite.
