# Phase 4.5A4 policy and protection observations

`_launch_policy.policy()` fixes an empty launch environment allowlist: there
are no accepted variable names or values. All entries reject, including empty
values and ASCII-case variants of `FREETYPE_*` and `FT2_*`. The existing native
launcher already admits only this empty allowlist. Admission observes the
original kernel exec environment; sanitizing it does not repair eligibility.

The exact required order is launcher admission, artifact/runtime verification,
deferred Python load, isolated bootstrap, lifecycle establishment, and provider
initialization. This is a bound policy declaration, not evidence that the last
step has executed. Provider initialization remains disabled.

The new composite build configuration binds the existing Phase-1 configuration
and evidence identities, the complete policy, and the policy collector's bytes.
The new deployment document binds that configuration, the entire reverified
deployment evidence, and protection observations. Original build/deployment
documents and frozen manifest schemas are unchanged. A later controlled build
must consume this composite configuration; it is not retroactive build evidence.

Every standalone native artifact, bootstrap/launcher alias, and module file has
its content digest, ownership, mode, filesystem flags, and read-only mount state
recorded, along with its complete ancestor chain. No-follow descriptor reads
check inode/stat stability during each observation; a second pass checks that
the observations and exact module trees remain unchanged. Bytecode caches and
symlinks reject. Absolute locations, timestamps, and inode numbers do not enter
the deterministic identity. Locations remain in the separate deployment inputs.

The collector independently invokes macOS signature verification for the
launcher. It binds dependency graphs, universal-image slice evidence and verified
shared-cache evidence from the existing collector. That cache observation is of
the collector process, not a fresh target launcher.

These observations do **not** establish protection against later substitution,
ACL-authorized writes, existing writable descriptors, privileged writers,
pre-entry native injection, or target loader changes. A valid signature alone
does not prove a trusted signer, hardened runtime, safe entitlements, or library
validation. Explicit protection gaps remain in the evidence; there is no success
flag or qualification token, and no policy evidence opens the provider gate.
Writable deployments remain unsupported for activation, even when signed.

Generate and independently recollect one evidence set without provider startup:

```sh
PYTHONPATH=src .venv/bin/python -B tools/restricted_launcher/collect_launch_policy.py \
  --deployment build/runtime/concrete-deployment/deployment-evidence.json \
  --inputs build/runtime/concrete-deployment/inputs.json \
  --output build/runtime/launch-policy
```

Actual protected deployment still requires an external trust anchor and a
provisioned substitution/preload prevention mechanism. Phase 4.5B must verify
and enforce those mechanisms and the actual fresh-exec loader/lifecycle state;
this phase neither provisions system protection nor wires launcher verifiers.

## Launcher identity hardening (Milestone 3C.2b)

The locally verified minimum model is ad-hoc signing with SHA-256, an explicit
identifier, and no timestamp. No certificate or keychain identity is needed for
this narrow immutable identity record. This is not signer authentication or
filesystem immutability. Certificate-backed signing is not accepted by this
local model; supporting it requires an explicit signing policy.

The collector now rejects unsigned, invalid, unavailable, or unsupported
signatures. It runs strict verification for all architectures before and after
reading signature metadata, and checks file digest and stat stability across
those calls. Only thin x86_64/arm64 SHA-256 ad-hoc images are supported. Evidence
binds the complete signed file SHA-256, identifier, format, CodeDirectory
version/flags, hash algorithm, CDHash, signature type, team field, and designated
requirement. Paths and diagnostic messages do not enter signature identity.
The signed file digest must match the reverified deployment launcher digest.
Recollection against retained expected policy evidence rejects a different
validly signed launcher as well as modified signature metadata.

Prepare a new signed copy and independently recollect its deployment and policy
records (the output directory must not exist):

```sh
PYTHONPATH=src .venv/bin/python -B tools/restricted_launcher/prepare_signed_launcher.py \
  --inputs build/runtime/concrete-deployment/inputs.json \
  --output build/runtime/signed-launcher-deployment
```

Signing changes bytes, so the tool creates new deployment evidence binding both
launcher and bootstrap to the signed copy. It preserves the original deployment
and does not change the frozen contract, load the launcher, or activate a
provider. The resulting `inputs.json`, `deployment-evidence.json`, and
`launch-policy-evidence.json` remain under ignored `build/`. To recheck later,
run `collect_launch_policy.py` with the new inputs/deployment and a fresh output
directory, then compare the canonical policy evidence with the retained record.
Do not treat newly collected evidence as an authorization to replace that record.

Focused tests:

```sh
PYTHONPATH=src .venv/bin/python -B -m unittest discover -s tests -p 'test_milestone3_phase3c2b_signing.py'
PYTHONPATH=src .venv/bin/python -B -m unittest discover -s tests -p 'test_milestone3_phase3c2b_launch*.py'
```

Ad-hoc signatures can be recreated by any writer. Expected evidence still needs
an external trust anchor. Path-based codesign invocations and observation checks
do not rule out adversarial transient replacement or replacement after checks.
Full substitution protection, preload prevention, and fresh-exec enforcement
remain unestablished; Phase 4.5B and Phase 5 are not implemented here.
