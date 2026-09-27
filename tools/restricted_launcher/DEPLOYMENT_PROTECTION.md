# Trusted-admin read-only image prerequisite

Hostile root/admin, a compromised kernel, and administrator replacement of
mounts, backing storage, or authenticated pins are explicitly outside this
deployment's threat model. The administrator must maintain the provisioned
state until every consuming process exits. Rechecking detects violations; it
does not make intermittent observation a defence against malicious root.

The supported profile is one administrator-attached, local HFS+/APFS read-only
disk image, without a shadow/overlay, mounted at a fixed canonical path. The
backing file, mount-point ancestors, and independently installed pin file must
be root-owned, non-writable by group/others, on local administrator-mounted
filesystems with ownership enabled, without extended ACLs or symlinks. Writable
ancestor filesystems outside the image are permitted under this trusted-admin
ownership model. The original ordinary collector remains conservative and does
not silently relax its read-only-ancestor checks.

Provision the backing file and underlying mount-point directory securely from
the outset: do not reuse objects for which an untrusted writer can retain an
existing writable descriptor. Mount with ownership enabled, without a shadow,
using an administrator-controlled attachment. Users must not have authority to
replace the mount namespace, change backing bytes, or write the device. Freeze
this deployment operationally until process exit; updates require stopping its
consumers and starting a new lifecycle. No sudo, mount, signing, installation,
or permission changes are performed by the verifier.

## Protected closure and authentication

All supplied build-artifact files, native-artifact files (including launcher/
bootstrap, Python, and Pillow), and complete ordered module-search trees must
resolve within the one protected mount. Empty module directories are included.
Nested mounts, symlinks, absent/cache-only artifact paths, and escaped paths
reject. This is deliberately a narrow profile: it introduces no exception for
system paths outside the image and no new shared-cache authorization. Existing
native startup-inventory and shared-cache checks are unchanged. Installing this
prerequisite alone does not demonstrate that a deployment meets those checks.

The trust anchor is the fixed file
`/Library/ProfessionalPresentationAgent/deployment-protection.json`, outside the
image. Root ownership, the entire protected ancestor chain, and rejection of
ACLs authenticate this administrator-installed file under the chosen threat
model. A pin file supplied by Python, the environment, or inside the image is
not accepted as an alternative trust anchor. Ad-hoc signing and hashes alone
are not treated as signer authentication.

Its exact JSON fields are:

```json
{
  "kind": "trusted-admin-readonly-image-v1",
  "root": "/administrator/chosen/mount",
  "backing_file": "/administrator/protected/deployment.dmg",
  "backing_sha256": "<SHA-256 of the complete backing file>",
  "deployment_sha256": "<SHA-256 of canonical deployment evidence>",
  "build_sha256": "<SHA-256 of canonical build evidence>",
  "launch_policy_sha256": "<SHA-256 of the entire canonical launch-policy evidence>",
  "inputs_sha256": "<SHA-256 of canonical exact deployment inputs>"
}
```

Digests are lowercase 64-character hex strings. The input document has exactly
`build_files`, `native_files`, `module_paths`, and `runtime`; file mappings use
absolute string paths and module paths retain their order. Canonical encoding
is the existing `evidence.canonical_bytes` encoding. Unknown or duplicate pin
fields reject. The administrator must obtain and approve expected bytes and
digests independently; copying hashes from an untrusted deployment is not
authentication.

For provisioning, install the other independently verified pins with a
temporary all-zero `launch_policy_sha256`. In a separate trusted offline
process, `collect_protected_evidence(expected, build, build_files, native_files,
module_paths, runtime)` collects a candidate while verifying the installed
image/backing/input pins. It does **not** approve that candidate or alter the
runtime lifecycle. Independently approve its digest and install the final pin
file before starting a new verification process. The temporary pin cannot pass
`require_substitution_protection`. This two-step procedure avoids embedding an
image's own digest into that image or silently authenticating newly observed
policy evidence.

## Verification and lifetime

`require_substitution_protection` now returns normally only after:

- Descriptor-based Darwin `fstatfs$INODE64` checks establish a read-only, local,
  ownership-enabled, non-union mount and bind filesystem ID, owner, flags,
  filesystem type, mount point, and device.
- `/usr/bin/hdiutil info -plist`, with a fixed command and empty environment,
  identifies exactly one administrator-owned read-only image attachment at that
  mount, matching its device/backing path, with no shadow/overlay metadata.
- Root/ACL/path-chain verification and complete backing-file hashing match the
  independently installed pins; all artifact paths and module-tree entries
  resolve on the same mount.
- Existing deployment hashes, dependency/module inventories, launcher signature
  checks, and complete launch-policy evidence comparison succeed.

The prerequisite retains PID, attachment record, mount identity, path/inode
identities, backing digest, and authenticated pins across calls. It rechecks
before evidence collection, after deployment verification, after signature
verification, after resolution checks, and after the last policy-evidence use.
Every subsequent prerequisite-use call rechecks against that original state.
Observed failure, fork inheritance, or changed pins/mounts permanently rejects
that verification process, including retries after restoring the old state.
There is no reset method or qualification value returned.

These are **prerequisite evidence-use boundaries**, not native provider
qualification. The production launcher, native Hardened Runtime and inventory
checks, bootstrap lifecycle, and provider gate remain unchanged and closed.
Phase 4.5B must connect the prerequisite to the trusted native lifecycle; Python
objects or this verifier's normal return must never serve as an activation token.
The offline evidence's existing qualification/gap fields are intentionally not
rewritten into a production-qualification claim.

## Focused verification

The new protection tests simulate root-owned mounts and attachment observations
while using real file contents, descriptors and inode identities. A read-only
host check verifies the Darwin filesystem ABI. Tests do not provision a real
protected deployment or assert production qualification.

```sh
PYTHONPATH=src:tests .venv/bin/python -B -m unittest \
  test_milestone3_phase3c2b_protection \
  test_milestone3_phase3c2b_launch_policy \
  test_milestone3_phase3c2b_substitution
```

Darwin ACL return semantics follow Apple's
[acl_entry.c](https://github.com/apple-oss-distributions/Libc/blob/main/posix1e/acl_entry.c):
a present entry returns zero; an empty ACL returns minus one with `EINVAL`.
The local SDK's `sys/mount.h` defines the 64-bit filesystem ABI.
