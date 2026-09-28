# Provider identity prerequisite (activation remains closed)

`_deployment_binding.collect(..., font_file=absolute_path)` emits
`trusted-admin-deployment-binding-v2` after the existing independently pinned
deployment, build, policy and protection checks. No supplied build/runtime ID or
profile claim is accepted. The collector derives the frozen build manifest from
the verified controlled-build artifacts and their actual configuration digest,
and derives the runtime ID from the reverified runtime manifest. It constructs
the existing fixed layout profile, verifies the explicitly selected font's
frozen SHA-256 and pure SFNT checks, and hashes the unchanged profile descriptor
with its existing namespace. It never initializes Pillow or discovers fonts.

The new `provider_identity` record contains:

- The adapter digest, pinned build-evidence digest and deployment-document digest.
- Exact canonical build/runtime manifest bytes and their SHA-256 identities.
- Exact canonical layout descriptor bytes and its namespaced profile identity.
- The fixed font digest and its explicit protected path.
- Sorted `build:`, `native:`, `module:<root-index>:` and `font` file records,
  each binding an exact protected path to its expected SHA-256.

These are candidate deployment inputs, **not authorization returned by Python**.
The deployment owner must independently review/authenticate the entire v2
package and compile its expected digest, bytes, identity records and matching
startup/attachment bindings into `deployment_inputs.h` before signing the
launcher. Runtime argv, environment, Python objects and files containing newly
collected claims cannot populate that header. The checked-in inputs remain
absent; the production callbacks are concrete but this default deployment denies
loading. Existing v1 packages remain usable for legacy prerequisite inspection;
the production provider artifact callbacks reject them.

The native consumer checks exact package bytes against that compiled trust
anchor, cross-binds the package to the live authenticated attachment pins, checks
all identity document hashes, compares manifest artifact lists to the native
file table, and checks the profile's build/runtime/font digests. It rehashes every
listed artifact through the existing no-symlink, protected-mount reader. The
adapter must occur in the module inventory, controlled native Pillow files must
match the build files, and every module directory is checked for unlisted files.
Each callback repeats the attachment/process boundary; failures permanently
invalidate the shared lifecycle. Bootstrap invalidation also revokes that state.

No layout contract or frozen manifest schema changes. The build identity covers
the recorded Phase-1 build configuration; this does not assert that a later
composite launch configuration was used to rebuild those artifacts. The default
launcher still exits 78, `_open_provider` stays closed, and the private bootstrap
entry still returns false. There is no activation setter, Python credential or
qualification claim. Fresh-process provider acceptance and final production
qualification remain outstanding.

Focused tests use synthetic mounts/leases and explicitly substituted font
observations; they confer no deployment trust. Run with the existing environment:

```sh
PYTHONPATH=src:tests .venv/bin/python -B -m unittest \
  test_milestone3_phase3c2b_provider_identity \
  test_milestone3_phase3c2b_native_provider
```
