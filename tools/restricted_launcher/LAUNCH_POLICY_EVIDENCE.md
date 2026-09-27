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
The present writable, unsigned deployment remains unsupported for activation.

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
