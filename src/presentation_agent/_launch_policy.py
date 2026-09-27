"""Phase 4.5A4 offline launch-policy bindings; never a qualification API.

Observation of permissions/signatures is not substitution prevention. This
collector records gaps as well as identities. No result authorizes execution.
The launcher must enforce the policy in a fresh exec in a later phase.
"""
from hashlib import sha256
import os
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


def _stamp(info):
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


def _signature(path):
    """Record verification outcome, not a caller-provided signature assertion."""
    if not Path('/usr/bin/codesign').is_file():
        return {'status': 'unavailable'}
    result = subprocess.run(
        ['/usr/bin/codesign', '--verify', '--strict', '--all-architectures', str(path)],
        capture_output=True, timeout=30, env={})
    # Do not include diagnostics: they contain deployment paths and can vary.
    return {'status': 'valid' if result.returncode == 0 else 'invalid-or-unsigned'}


def collect(expected, build, build_files, native_files, module_paths, runtime):
    """Reverify byte evidence, bind policy, and report protection gaps honestly.

    The new composite build configuration binds the unchanged Phase-1
    configuration and launch policy. It does not retroactively change the
    Phase-1 recipe or the frozen build/runtime manifest schemas. The new
    deployment document binds the *entire* verified deployment evidence.
    Expected evidence still needs a deployment-owner trust anchor.
    """
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
    # Signature validity alone does not establish hardened runtime, entitlements,
    # library validation, original loader state, or a trusted signing authority.
    gaps = [
        'external-trust-anchor-not-established',
        'substitution-prevention-through-last-use-not-established',
        'preload-prevention-before-entry-not-established',
        'fresh-exec-loader-state-not-observed',
    ]
    if signature['status'] != 'valid':
        gaps.append('launcher-signature-invalid-or-unavailable')
    if any(not node['read_only_filesystem'] for record in paths.values()
           for node in [record['file'], *record['ancestors']]):
        gaps.append('writable-artifact-or-resolution-filesystem')
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
