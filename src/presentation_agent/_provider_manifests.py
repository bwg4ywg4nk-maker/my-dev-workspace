"""Private declaration identities, not artifact verification or qualification."""
from hashlib import sha256

from .evidence import MAX_RECORDS, canonical_bytes


def _require(condition, role):
    if not condition:
        raise ValueError('Invalid manifest ' + role)


def _shape(manifest, keys, kind):
    _require(type(manifest) is dict, 'object')
    _require(len(manifest) == len(keys) and
             all(type(key) is str for key in manifest) and
             manifest.keys() == keys, 'fields')
    _require(type(manifest['kind']) is str and manifest['kind'] == kind, 'kind')


def _string(value, role):
    _require(type(value) is str and 0 < len(value) <= 100 and
             all(' ' <= char <= '~' for char in value), role)


def _digest(value, role):
    _require(type(value) is str and len(value) == 64 and
             all(char in '0123456789abcdef' for char in value), role)


def _artifacts(value, role):
    _require(type(value) is list and 0 < len(value) <= MAX_RECORDS, role)
    previous = None
    for entry in value:
        _require(type(entry) is list and len(entry) == 2, role + ' entry')
        name, digest = entry
        _string(name, role + ' component name')
        _require('/' not in name and '\\' not in name, role + ' component name')
        _require(previous is None or previous < name, role + ' ordering/uniqueness')
        _digest(digest, role + ' digest')
        previous = name


def _build_manifest_id(manifest):
    """Validate a build declaration and hash its unmodified canonical bytes."""
    _shape(manifest, {'kind', 'artifacts', 'build_configuration_sha256'},
           'pillow-basic-build-v1')
    _artifacts(manifest['artifacts'], 'artifacts')
    _digest(manifest['build_configuration_sha256'], 'build configuration digest')
    return 'sha256:' + sha256(canonical_bytes(manifest)).hexdigest()


def _runtime_manifest_id(manifest):
    """Validate a runtime declaration without inspecting the active runtime."""
    strings = ('python_implementation', 'python_abi', 'os', 'os_release',
               'architecture')
    _shape(manifest, {'kind', *strings, 'python_version', 'byteorder',
                      'pointer_bits', 'native_runtime_artifacts'},
           'pillow-basic-runtime-v1')
    for field in strings:
        _string(manifest[field], field)
    version = manifest['python_version']
    _require(type(version) is list and len(version) == 3 and
             all(type(part) is int and part >= 0 for part in version),
             'python_version')
    _require(type(manifest['byteorder']) is str and
             manifest['byteorder'] in ('little', 'big'), 'byteorder')
    _require(type(manifest['pointer_bits']) is int and
             manifest['pointer_bits'] in (32, 64), 'pointer_bits')
    _artifacts(manifest['native_runtime_artifacts'], 'native_runtime_artifacts')
    # The shared encoder supplies the integer, nesting, collection and byte limits.
    return 'sha256:' + sha256(canonical_bytes(manifest)).hexdigest()
