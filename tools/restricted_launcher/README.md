# Phase 2 restricted native launcher foundation

Compile with the existing Apple tools (no Python linkage):

```sh
mkdir -p build/phase2
clang -std=c11 -Wall -Wextra -Werror tools/restricted_launcher/launcher.c -o build/phase2/launcher
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

Production supplies no verifiers or framework and always exits 78. No Python
initialization, lifecycle record, qualification token, setter, or provider
activation exists. Loader hardening, concrete deployment identities/verifiers,
isolated Python startup and lifecycle integration remain deferred. This is
not yet a trusted production launch, including against pre-main loader effects.

Tests compile a separate native harness with a fake loader to check sequencing
and failure injection; its successful load is not runtime qualification. They
also execute the production entry and inspect its native load dependencies.
Generated binaries remain under ignored `build/phase2-unit/`.

```sh
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -p 'test_milestone3_phase3c2b_launcher.py'
```
