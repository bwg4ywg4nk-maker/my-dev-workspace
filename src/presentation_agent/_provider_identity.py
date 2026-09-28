"""Offline provider identity derivation; the reviewed native package is authority.

Called only after deployment/policy re-verification. No provider is imported or
initialized. Identity declarations produced here are not activation credentials.
"""
from hashlib import sha256
from pathlib import Path

from . import layout
from ._provider_manifests import _build_manifest_id, _runtime_manifest_id, _require
from .evidence import canonical_bytes


def _document(value, namespace=b''):
    raw = canonical_bytes(value)
    _require(0 < len(raw) <= 50_000, 'provider identity document size')
    return {'bytes_hex': raw.hex(), 'sha256': sha256(namespace + raw).hexdigest()}


def collect(expected, build, build_files, native_files, module_paths, font_file, root):
    from ._deployment_binding import _protected_path
    from ._pillow_basic import _inspect_font

    manifest = {'kind': 'pillow-basic-build-v1', 'artifacts': build['artifacts'],
                'build_configuration_sha256': build['configuration_sha256']}
    build_id = _build_manifest_id(manifest)
    runtime_id = _runtime_manifest_id(expected['runtime_manifest'])
    _require(runtime_id == expected['runtime_id'], 'provider runtime identity mismatch')
    font = layout.FontIdentity(layout._FONT_SHA256, 0, 'Arial', 'Regular')
    profile = layout.LayoutProfile(layout._NAME, 1, font, '12.3.0', '2.14.3',
                                   build_id, runtime_id)
    font_path = _protected_path(font_file, root)
    with Path(font_path).open('rb') as stream:
        data = stream.read(8_388_609)
    _inspect_font(data, font)
    records = []

    def add(role, path, digest):
        path = _protected_path(path, root)
        _require(len(role) < 1024 and role.isascii(), 'provider artifact role')
        # Re-read even the already verified files; native checks repeat these
        # exact hashes under the retained lease before any interpreter load.
        h = sha256()
        with Path(path).open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                h.update(chunk)
        _require(h.hexdigest() == digest, 'provider artifact digest mismatch')
        records.append([role, path, digest])

    for role, digest in build['artifacts']:
        add('build:' + role, build_files[role], digest)
    for role, digest in expected['deployment']['native_artifacts']:
        add('native:' + role, native_files[role], digest)
    for index, tree in enumerate(expected['deployment']['module_search_paths']):
        for relative, digest in tree:
            add('module:' + str(index) + ':' + relative,
                Path(module_paths[index]) / relative, digest)
    add('font', font_path, font.sha256)
    records.sort()
    _require(0 < len(records) <= 4096 and
             len({row[0] for row in records}) == len(records), 'provider artifact population')
    return {'kind': 'protected-provider-identity-v1', 'artifacts': records,
            'adapter_sha256': dict(build['artifacts'])['measurement-adapter'],
            'build_evidence_sha256': sha256(canonical_bytes(build)).hexdigest(),
            'deployment_document_sha256': sha256(canonical_bytes(expected['deployment'])).hexdigest(),
            'build_manifest': _document(manifest), 'font_sha256': font.sha256,
            'profile': _document(layout._descriptor(profile), layout._NAMESPACE),
            'runtime_manifest': _document(expected['runtime_manifest'])}
