"""Phase 4.5A4 offline launch-policy bindings; never a qualification API.

Observation of permissions/signatures is not substitution prevention. This
collector records gaps as well as identities. No result authorizes execution.
The launcher must enforce the policy in a fresh exec in a later phase.
"""
from hashlib import sha256
import os
import plistlib
import re
from pathlib import Path
import stat
import subprocess

from . import _deployment_evidence as deployment
from ._build_evidence import evidence_id
from ._provider_manifests import _require
from .evidence import canonical_bytes


def policy():
    """No OS environment necessities have been authorized for this deployment."""
    return {
        'kind': 'protected-launch-policy-v1',
        'environment': {
            'accepted_name_value_pairs': [],
            'reject_unlisted': True,
            'reject_duplicate_or_malformed_names': True,
            'ascii_case_insensitive_rejected_prefixes': ['FREETYPE_', 'FT2_'],
            'observation': 'original-kernel-exec-environment-before-python-load',
            'sanitize_before_admission': False,
        },
        'initialization_sequence': [
            'launcher-admission', 'artifact-runtime-verification',
            'deferred-python-load', 'isolated-python-bootstrap',
            'lifecycle-establishment', 'provider-initialization',
        ],
        'python': {
            'use_environment': False, 'site_import': False,
            'user_site_directory': False, 'parse_argv': False,
            'safe_path': True, 'write_bytecode': False,
            'search_paths': 'exact-ordered-verified-deployment-roots',
        },
        'protection_requirements': [
            'externally-trusted-launcher-and-expected-evidence',
            'prevent-file-and-ancestor-substitution-through-last-use',
            'prevent-uncontrolled-preload-before-first-launcher-instruction',
            'verify-actual-loaded-images-and-shared-cache-before-python-load',
            'retain-artifact-module-path-environment-and-process-bindings',
            'irreversible-invalidation-on-boundary-failure',
        ],
    }


def _identity(value):
    return sha256(canonical_bytes(value)).hexdigest()


def _directory_stamp(info):
    # Directory size/timestamps describe all entries, including unrelated
    # siblings. Bind path identity and protection instead; module inventories
    # and the resolution snapshot's path set separately bind relevant entries.
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
            getattr(info, 'st_flags', 0))


def _stamp(info):
    if stat.S_ISDIR(info.st_mode):
        return _directory_stamp(info)
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
            info.st_ctime_ns, info.st_mode, info.st_uid, info.st_gid,
            getattr(info, 'st_flags', 0))


def _observation(path, directory=False):
    """Hash through a no-follow fd; detect replacement during this observation.

    Mode/owner/flags and read-only mount state are diagnostic observations,
    not a claim that ACLs, existing writable descriptors, privileged writers,
    or a later mount/path change cannot replace an artifact.
    """
    path = Path(path)
    _require(path.is_absolute() and path.resolve() == path, 'protected path')
    flags = os.O_RDONLY | os.O_NOFOLLOW
    if directory:
        flags |= os.O_DIRECTORY
    fd = os.open(path, flags)
    try:
        before = os.fstat(fd)
        _require((stat.S_ISDIR if directory else stat.S_ISREG)(before.st_mode),
                 'protected artifact type')
        digest = sha256()
        if not directory:
            for chunk in iter(lambda: os.read(fd, 1024 * 1024), b''):
                digest.update(chunk)
        result = {
            'uid': before.st_uid, 'gid': before.st_gid,
            'mode': stat.S_IMODE(before.st_mode),
            'flags': getattr(before, 'st_flags', 0),
            'read_only_filesystem': bool(os.fstatvfs(fd).f_flag & os.ST_RDONLY),
        }
        if not directory:
            result['sha256'] = digest.hexdigest()
        _require(_stamp(before) == _stamp(os.fstat(fd)) == _stamp(path.lstat()),
                 'artifact changed during protection observation')
        return result
    finally:
        os.close(fd)


def _path_observation(path):
    path = Path(path)
    return {
        'file': _observation(path),
        # Root first; no absolute deployment locations enter identity.
        'ancestors': [_observation(p, True) for p in reversed(path.parents)],
    }


def _resolution_protection(native_files, module_paths):
    """Require read-only filesystems for the complete resolution namespace.

    This is a necessary offline condition, not a mount-lifetime guarantee.
    Modes, ownership, ACLs and immutable flags cannot establish this condition:
    writers may already hold descriptors or be able to replace an ancestor.
    Missing cache-backed paths are unsupported here until their backing files
    and absent-path resolution can receive equivalent protection evidence.
    """
    observations = {}

    def check(path, directory):
        path = Path(path)
        for ancestor in reversed(path.parents):
            observe(ancestor, True)
        observe(path, directory)

    def observe(path, directory):
        if path in observations:
            return
        info = path.lstat()
        _require((stat.S_ISDIR if directory else stat.S_ISREG)(info.st_mode),
                 'protected artifact type')
        before = _stamp(info)
        record = _observation(path, directory)
        _require(before == _stamp(path.lstat()),
                 'deployment path changed during protection check')
        _require(record['read_only_filesystem'],
                 'writable or substitutable deployment path')
        observations[path] = (before, record)

    for location in native_files.values():
        check(location, False)
    for location in module_paths:
        root = Path(location)
        check(root, True)
        # Walk only after the parent is checked. Include empty directories:
        # they can host a new package, extension or bytecode cache later.
        pending = [root]
        while pending:
            directory = pending.pop()
            for child in sorted(directory.iterdir()):
                _require(not child.is_symlink(), 'substitutable module symlink')
                is_directory = child.is_dir()
                check(child, is_directory)
                if is_directory:
                    pending.append(child)
    return observations


def require_substitution_protection(*args):
    """Fail closed at a prospective use boundary; never a qualification token.

    Recollect all byte/signature/path evidence. Even read-only observations
    cannot demonstrate that mounts and their backing stores remain protected
    through last use. No supported lifetime enforcement exists in this phase.
    Caller-supplied assertions or previously collected evidence cannot waive it.
    """
    collect(*args)
    raise ValueError('substitution protection through last use not established')


def _signature(path):
    """Verify the local thin-image ad-hoc model and bind stable metadata.

    The full file digest is the identity anchor; ad-hoc signing supplies no
    signer authentication. Expected evidence must be retained independently.
    """
    before = _observation(path)
    stamp = _stamp(Path(path).lstat())

    def codesign(*options):
        try:
            result = subprocess.run(
                ['/usr/bin/codesign', *options, str(path)],
                capture_output=True, timeout=30, env={}, text=True)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ValueError('launcher signature verification unavailable') from exc
        _require(result.returncode == 0, 'launcher signature invalid or unsigned')
        return result.stdout + result.stderr

    codesign('--verify', '--strict', '--all-architectures')
    output = codesign('--display', '--verbose=4', '-r-')
    fields = {}
    for prefix in ('Identifier=', 'Format=', 'CodeDirectory ', 'Hash type=',
                   'CDHash=', 'Signature=', 'TeamIdentifier=', '# designated => '):
        matches = [line[len(prefix):] for line in output.splitlines()
                   if line.startswith(prefix)]
        _require(len(matches) == 1 and bool(matches[0]),
                 'unsupported launcher signature metadata')
        fields[prefix.rstrip('= ')] = matches[0]
    _require(fields['Signature'] == 'adhoc' and
             fields['Format'] in ('Mach-O thin (x86_64)', 'Mach-O thin (arm64)') and
             fields['Hash type'] == 'sha256 size=32',
             'unsupported launcher signing model')
    flags = re.search(r'(?:^| )flags=0x([0-9a-fA-F]+)(?:\(| |$)',
                      fields['CodeDirectory'])
    _require(flags is not None and int(flags[1], 16) & 0x10000,
             'launcher hardened runtime missing')
    # Reject all entitlements, including false-valued exceptions. The local
    # ad-hoc model needs none, and unknown future exceptions must fail closed.
    result = subprocess.run(
        ['/usr/bin/codesign', '--display', '--entitlements', '-', str(path)],
        capture_output=True, timeout=30, env={})
    _require(result.returncode == 0, 'launcher entitlements unavailable')
    if result.stdout:
        try:
            entitlements = plistlib.loads(result.stdout)
        except (ValueError, plistlib.InvalidFileException) as exc:
            raise ValueError('unsupported launcher entitlements') from exc
        _require(entitlements == {}, 'launcher entitlements prohibited')
    codesign('--verify', '--strict', '--all-architectures')
    _require(before == _observation(path) and stamp == _stamp(Path(path).lstat()),
             'launcher changed during signature verification')
    return {'status': 'valid', 'model': 'ad-hoc-sha256-pinned-v1',
            'file_sha256': before['sha256'], 'metadata': fields}


def collect(expected, build, build_files, native_files, module_paths, runtime):
    """Reverify byte evidence, bind policy, and report protection gaps honestly.

    The new composite build configuration binds the unchanged Phase-1
    configuration and launch policy. It does not retroactively change the
    Phase-1 recipe or the frozen build/runtime manifest schemas. The new
    deployment document binds the *entire* verified deployment evidence.
    Expected evidence still needs a deployment-owner trust anchor.
    """
    protection = _resolution_protection(native_files, module_paths)
    deployment.verify(expected, build, build_files, native_files, module_paths, runtime)
    original = expected['deployment']
    records = dict(original['native_artifacts'])
    paths = {}
    for role, location in sorted(native_files.items()):
        path = Path(location)
        if path.exists():
            record = _path_observation(path)
            _require(record['file']['sha256'] == records[role], 'native byte binding')
            paths['native:' + role] = record
        else:
            _require('shared_cache' in original, 'missing shared-cache binding')
    for index, (root, tree) in enumerate(zip(module_paths, original['module_search_paths'])):
        _require(deployment._tree(root) == tree, 'module tree changed')
        for relative, digest in tree:
            _require('__pycache__' not in Path(relative).parts and
                     Path(relative).suffix not in ('.pyc', '.pyo'), 'bytecode prohibited')
            record = _path_observation(Path(root) / relative)
            _require(record['file']['sha256'] == digest, 'module byte binding')
            paths['module:' + str(index) + ':' + relative] = record
    signature = _signature(native_files['launcher'])
    _require(signature['status'] == 'valid' and
             signature['file_sha256'] == records['launcher'],
             'launcher signature byte binding')
    for role, location in sorted(native_files.items()):
        if 'native:' + role in paths:
            _require(_path_observation(location) == paths['native:' + role],
                     'native protection observation changed')
    for index, (root, tree) in enumerate(zip(module_paths, original['module_search_paths'])):
        _require(deployment._tree(root) == tree, 'module tree changed')
        for relative, _ in tree:
            _require(_path_observation(Path(root) / relative) ==
                     paths['module:' + str(index) + ':' + relative],
                     'module protection observation changed')
    _require(protection == _resolution_protection(native_files, module_paths),
             'deployment resolution protection changed')
    # Signature validity alone does not establish hardened runtime, entitlements,
    # library validation, original loader state, or a trusted signing authority.
    gaps = [
        'external-trust-anchor-not-established',
        'substitution-prevention-through-last-use-not-established',
        'preload-prevention-before-entry-not-established',
        'fresh-exec-loader-state-not-observed',
    ]
    configuration = {
        'kind': 'protected-launch-build-configuration-v1',
        'phase1_configuration_sha256': build['configuration_sha256'],
        'phase1_build_evidence_sha256': evidence_id(build),
        'launch_policy': policy(),
        'policy_collector_sha256': sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    document = {
        'kind': 'protected-launch-deployment-evidence-v1',
        'build_configuration_sha256': _identity(configuration),
        'deployment_evidence_sha256': _identity(expected),
        'runtime_id': expected['runtime_id'],
        'artifact_protection_observations': paths,
        'substitution_protection': {
            'minimum': 'read-only-artifacts-and-complete-resolution-namespace',
            'observation': 'before-and-after-byte-and-signature-verification',
            'through_last_use': 'not-established',
        },
        'launcher_signature': signature,
        'loader_binding': {
            'native_dependencies_sha256': _identity(original['native_dependencies']),
            'native_slices_sha256': _identity(original.get('native_slices', [])),
            'shared_cache_sha256': _identity(original.get('shared_cache')),
            'observation_scope': 'offline-collector-not-target-fresh-exec',
        },
        'protection_gaps': sorted(gaps),
        'qualification': 'not-established',
    }
    return {'build_configuration': configuration, 'deployment': document,
            'evidence_sha256': _identity(document)}


def verify(expected_policy_evidence, *args):
    """Recollect; caller-supplied success flags cannot establish protection."""
    actual = collect(*args)
    _require(canonical_bytes(expected_policy_evidence) == canonical_bytes(actual),
             'launch policy evidence mismatch')
    return actual['evidence_sha256']
