"""Phase-1 declarations and byte verification; never runtime qualification.

No provider imports or activation. Lists with semantic order are preserved;
artifact/module sets must already be sorted and unique, never silently repaired.
"""
from hashlib import sha256
from pathlib import Path
import re

from .evidence import canonical_bytes
from ._provider_manifests import _artifacts, _digest, _require, _string


_GENERATED = {'ftconfig.h', 'ftmodule.h', 'ftoption.h', 'public-macros.h',
              'ft-macros', 'imaging-macros', 'imagingft-macros',
              'pillow-configuration', 'patched-imagingft-source'}
_TOOLS = {'compiler', 'compiler-version', 'compiler-resources', 'archiver',
          'linker', 'nm', 'otool', 'patch', 'python', 'python-headers',
          'python-platform-headers'}
_PATCHES = {'build.py', 'profile.json', 'pa_cmap_audit.h', 'pillow-12.3.0-cmap.patch'}


def _fields(value, names):
    _require(type(value) is dict and all(type(k) is str for k in value)
             and value.keys() == set(names), 'evidence fields')


def _strings(value, role, ordered=False):
    _require(type(value) is list and 0 < len(value) <= 256, role)
    for item in value:
        _string(item, role)
    if not ordered:
        _require(value == sorted(set(value)), role + ' ordering/uniqueness')


def configuration_id(value):
    """Hash a validated declaration, without claiming the declared build ran."""
    _fields(value, ('kind', 'versions', 'sources', 'patches', 'tools', 'target',
                    'flags', 'modules', 'disabled', 'generated'))
    _require(type(value['kind']) is str and
             value['kind'] == 'pillow-basic-phase1-configuration-v1', 'kind')
    _fields(value['versions'], ('pillow', 'freetype'))
    _require(all(type(v) is str for v in value['versions'].values()) and
             value['versions'] == {'pillow': '12.3.0', 'freetype': '2.14.3'}, 'versions')
    for key in ('sources', 'patches', 'tools', 'generated'):
        _artifacts(value[key], key)
    for key, required in (('patches', _PATCHES), ('tools', _TOOLS), ('generated', _GENERATED)):
        _require(required <= {row[0] for row in value[key]}, 'missing ' + key)
    _require([a[0] for a in value['sources']] == ['freetype', 'pillow'], 'sources')
    _fields(value['target'], ('architecture', 'deployment_target', 'sdk_sha256'))
    _require(type(value['target']['architecture']) is str and
             value['target']['architecture'] in ('arm64', 'x86_64'), 'architecture')
    _string(value['target']['deployment_target'], 'deployment target')
    _require(re.fullmatch(r'[0-9]{1,2}\.[0-9]{1,2}', value['target']['deployment_target']) is not None,
             'deployment target')
    _digest(value['target']['sdk_sha256'], 'SDK digest')
    _fields(value['flags'], ('compile', 'link', 'configure'))
    for key, items in value['flags'].items():
        _strings(items, key, ordered=True)
    _strings(value['modules'], 'modules')
    _strings(value['disabled'], 'disabled')
    return sha256(canonical_bytes(value)).hexdigest()


def evidence_id(value):
    """Validate recorded evidence. Its identity is NOT provider_build_id."""
    _fields(value, ('kind', 'configuration', 'configuration_sha256', 'artifacts'))
    _require(type(value['kind']) is str and value['kind'] == 'pillow-basic-phase1-evidence-v1', 'kind')
    expected = configuration_id(value['configuration'])
    _digest(value['configuration_sha256'], 'configuration digest')
    _require(value['configuration_sha256'] == expected, 'configuration mismatch')
    _artifacts(value['artifacts'], 'artifacts')
    required = {'freetype-static', 'imaging', 'imagingft', 'imaging-link',
                'imagingft-link', 'imagingft-symbols'}
    _require(required <= {a[0] for a in value['artifacts']}, 'missing build artifacts')
    return sha256(canonical_bytes(value)).hexdigest()


def verify_bytes(records, files):
    """Check explicitly supplied files against declarations; no path discovery.

    This verifies byte identities only, not origin, compiler behavior, runtime
    binding, reproducibility, or font/provider acceptance.
    """
    _artifacts(records, 'files')
    _require(type(files) is dict and files.keys() == {r[0] for r in records}, 'files')
    for name, expected in records:
        digest = sha256()
        with Path(files[name]).open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
        _require(digest.hexdigest() == expected, name + ' byte digest mismatch')


def validate_audit(value):
    """Validate the immutable, bounded native result; no provider certification.

    Tuple: count, native-order descriptors, original index/glyphs, restored
    index/glyphs. Descriptor: index, platform, encoding, FT encoding, format,
    eligible-map ASCII glyphs (empty for ineligible maps).
    """
    def integer(item, lower, upper):
        _require(type(item) is int and lower <= item <= upper, 'audit integer')

    def glyphs(items):
        _require(type(items) is tuple and len(items) == 95, '95 ASCII glyphs')
        for item in items:
            integer(item, 1, 65535)

    _require(type(value) is tuple and len(value) == 6, 'audit shape')
    count, maps, before, original, after, restored = value
    integer(count, 1, 256)
    _require(type(maps) is tuple and len(maps) == count, 'audit maps')
    integer(before, 0, count - 1)
    integer(after, 0, count - 1)
    glyphs(original)
    glyphs(restored)
    _require(before == after and original == restored, 'audit restoration')
    eligible_indices = []
    for index, descriptor in enumerate(maps):
        _require(type(descriptor) is tuple and len(descriptor) == 6, 'audit descriptor')
        native, platform, encoding, ft_encoding, fmt, mapping = descriptor
        integer(native, 0, count - 1)
        _require(native == index, 'audit descriptor order')
        integer(platform, 0, 65535)
        integer(encoding, 0, 65535)
        integer(ft_encoding, 0, 2**32 - 1)
        integer(fmt, 0, 65535)
        _require(fmt != 14, 'variation map')
        _require(platform != 0 or encoding in (0, 1, 2, 3, 4, 6), 'Unicode encoding')
        eligible = platform == 0 or (platform == 3 and encoding in (1, 10))
        if eligible:
            _require(fmt in (4, 12) and ft_encoding == 0x756e6963, 'Unicode map')
            glyphs(mapping)
            _require(mapping == original, 'audit ASCII disagreement')
            eligible_indices.append(index)
        else:
            _require(type(mapping) is tuple and not mapping, 'ineligible map glyphs')
    _require(before in eligible_indices, 'selected Unicode map')
    return value
