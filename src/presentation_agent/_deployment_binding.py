"""Offline, authenticated binding inputs; never a lease or qualification token.

Only the existing fixed trusted-admin pin file supplies trust. This deterministic
package is derived from independently pinned evidence and exact inputs; it must
be independently retained/reviewed before any future native adapter consumes it.
No workspace defaults, pin installation, attachment provisioning, or loading.
"""
from hashlib import sha256
from pathlib import Path

from . import _deployment_protection as protection
from . import _launch_policy as policy
from . import _startup_inventory as inventory
from ._provider_manifests import _require
from .evidence import canonical_bytes


def _protected_path(value, root):
    text = str(value)
    path = Path(text)
    _require(text.isascii() and len(text) < 1024 and '\0' not in text and
             path.is_absolute() and str(path) == text and
             path.resolve(strict=True) == path and path.is_relative_to(root),
             'binding path outside or noncanonical protected deployment')
    return text


def _startup_binding(data, deployment_hash, root, launcher):
    _require(type(data) is bytes and len(data) >= inventory.HEADER.size,
             'binding startup inventory missing')
    magic, dep, cdhash, images, mappings = inventory.HEADER.unpack_from(data)
    _require(magic == b'PAEXEC01' and dep.hex() == deployment_hash and any(cdhash)
             and 2 <= images <= 512 and 0 < mappings <= 256 and
             len(data) == inventory.HEADER.size + images * inventory.IMAGE.size +
             mappings * inventory.MAPPING.size, 'binding startup inventory mismatch')
    paths, launchers = set(), []
    for index in range(images):
        kind, raw, digest, text_digest, extent = inventory.IMAGE.unpack_from(
            data, inventory.HEADER.size + index * inventory.IMAGE.size)
        name, separator, padding = raw.partition(b'\0')
        _require(separator and not any(padding) and kind in (0, 1, 2) and
                 any(digest) and any(text_digest) and extent > 0,
                 'binding startup image malformed')
        path = _protected_path(name.decode('ascii'), root)
        _require(path not in paths, 'binding duplicate startup path')
        paths.add(path)
        if kind == 0:
            launchers.append(path)
    _require(launchers == [launcher], 'binding startup launcher mismatch')
    return {'sha256': sha256(data).hexdigest(), 'deployment_sha256': deployment_hash,
            'launcher_cdhash': cdhash.hex(), 'bytes_hex': data.hex()}


def collect(expected, expected_policy, build, build_files, native_files,
            module_paths, runtime, *, font_file=None):
    """Return canonical bytes only after authenticated offline re-verification.

    The existing process-wide protection lifecycle latches failures and rejects
    fork/rebinding. Identity uses protected root/backing/input pins, not transient
    lease/session fields. A future native consumer still needs its own live lease.
    All referenced artifact paths, including startup images, must be protected;
    this does not introduce exceptions for system/shared-cache paths.
    """
    args = (expected, build, build_files, native_files, module_paths, runtime)
    lifecycle = protection._lifecycle
    try:
        pins = lifecycle.check(args)
        _require(protection._digest(expected_policy) == pins['launch_policy_sha256'],
                 'binding launch-policy evidence-pin mismatch')
        root = Path(pins['root'])
        for value in (*build_files.values(), *native_files.values(), *module_paths):
            _protected_path(value, root)
        launcher = _protected_path(native_files['launcher'], root)
        framework = _protected_path(native_files['python-framework'], root)
        python = _protected_path(native_files['python-interpreter'], root)
        modules = [_protected_path(p, root) for p in module_paths]
        _require(modules and len(modules) <= 64 and len(set(modules)) == len(modules),
                 'binding module paths missing or duplicate')

        def checkpoint():
            _require(lifecycle.check(args) == pins, 'binding pins changed')

        def resolution(*unused):
            checkpoint()
            return lifecycle.snapshot

        actual = policy._collect(*args, resolution=resolution, checkpoint=checkpoint)
        _require(canonical_bytes(actual) == canonical_bytes(expected_policy),
                 'binding launch-policy evidence changed')
        checkpoint()
        startup = _startup_binding(inventory.collect(*args),
                                   pins['deployment_sha256'], root, launcher)
        checkpoint()
        package = {
            'kind': 'trusted-admin-deployment-binding-v1',
            # Exact installed pin bytes, also bound by the native attachment
            # record's pin_sha256; semantic JSON equality cannot replace this.
            'attachment_pin_sha256': lifecycle.snapshot[0][1],
            'deployment_sha256': pins['deployment_sha256'],
            'launch_policy_sha256': pins['launch_policy_sha256'],
            'startup_inventory': startup,
            'launcher': launcher, 'python_framework': framework,
            'python_interpreter': python, 'module_paths': modules,
            'protected_deployment': dict(pins),
        }
        if font_file is not None:
            from ._provider_identity import collect as provider_identity
            package['kind'] = 'trusted-admin-deployment-binding-v2'
            package['provider_identity'] = provider_identity(
                expected, build, build_files, native_files, module_paths, font_file, root)
        result = canonical_bytes(package)
        checkpoint()
        return result
    except BaseException:
        lifecycle.reject()
        raise


def verify(package, *args, **kwargs):
    """Re-derive exact bytes against installed pins; return no authorization."""
    try:
        _require(type(package) is bytes and collect(*args, **kwargs) == package,
                 'binding package mismatch')
    except BaseException:
        protection._lifecycle.reject()
        raise
