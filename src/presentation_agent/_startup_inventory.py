"""Derive native startup evidence; never authorize execution or qualification.

The binary record has its own hash/pin and binds the entire existing deployment
record. It is consumed only by the private native verifier, never from Python
inside a target process. A trusted deployment must retain both pins externally.
"""
from hashlib import sha256
from pathlib import Path
import struct

from . import _deployment_evidence as deployment
from . import _launch_policy as policy
from ._provider_manifests import _require
from .evidence import canonical_bytes

HEADER = struct.Struct('<8s32s20sII')
IMAGE = struct.Struct('<I4096s32s32sQ')
MAPPING = struct.Struct('<QQII32s')


def collect(expected, build, build_files, native_files, module_paths, runtime):
    deployment.verify(expected, build, build_files, native_files, module_paths, runtime)
    signature = policy._signature(native_files['launcher'])
    result = _encode(expected, native_files, runtime['architecture'], signature)
    # No observations taken after identity verification may silently replace it.
    deployment.verify(expected, build, build_files, native_files, module_paths, runtime)
    _require(signature == policy._signature(native_files['launcher']),
             'startup launcher signature changed')
    return result


def _encode(expected, native_files, architecture, signature):
    document = expected['deployment']
    artifacts = dict(document['native_artifacts'])
    graph = dict(document['native_dependencies'])
    selected, pending = set(), ['launcher', 'loader']
    while pending:
        role = pending.pop()
        if role in selected:
            continue
        _require(role in graph and role in artifacts, 'startup dependency missing')
        selected.add(role)
        pending.extend(graph[role])
    _require(not selected & {'bootstrap', 'python-framework', 'python-interpreter',
                            'imaging', 'imagingft'}, 'non-system startup dependency')
    cache = document.get('shared_cache', {})
    cache_images = {image['path']: image for image in cache.get('images', [])}
    records, paths = [], set()
    for role in sorted(selected):
        if role in native_files:
            path = str(native_files[role])
        else:
            matches = [p for p in cache_images if role ==
                       'shared-cache-image-' + sha256(p.encode()).hexdigest()]
            _require(len(matches) == 1, 'startup cache role missing')
            path = matches[0]
        encoded = path.encode('utf-8')
        _require(path.startswith('/') and 0 < len(encoded) < 4096 and
                 b'\0' not in encoded and path not in paths, 'startup image path')
        paths.add(path)
        digest, address = None, 0
        if role in ('launcher', 'loader'):
            data = Path(path).read_bytes()
            _require(sha256(data).hexdigest() == artifacts[role], 'startup file changed')
            payload, _ = deployment._native_slice(data, architecture)
            deployment._dependencies_bytes(payload, architecture)
            length = 32 + struct.unpack_from('<I', payload, 20)[0]
            offset, text = 32, []
            for _ in range(struct.unpack_from('<I', payload, 16)[0]):
                command, size = struct.unpack_from('<II', payload, offset)
                if command == 0x19 and payload[offset + 8:offset + 24].rstrip(b'\0') == b'__TEXT':
                    _require(size >= 72, 'startup text segment')
                    _, _, file_offset, file_size, maximum, initial = struct.unpack_from(
                        '<4Q2I', payload, offset + 24)
                    _require(file_offset == 0 and length <= file_size <= len(payload)
                             and maximum == initial == 5, 'immutable startup text')
                    text.append(file_size)
                offset += size
            _require(len(text) == 1, 'startup text segment missing/duplicate')
            address = text[0]  # Standalone record: __TEXT file extent, not an address.
            digest = sha256(payload[:address]).digest()
            kind = 0 if role == 'launcher' else 1
        else:
            # Restrict startup to the launcher, Apple dyld, and cache images.
            # Standalone third-party dependencies are deliberately unsupported.
            _require(path in cache_images, 'startup image not in verified cache')
            image = cache_images[path]
            cache_id = sha256(canonical_bytes(cache)).hexdigest()
            _require(sha256(canonical_bytes([cache_id, image])).hexdigest() ==
                     artifacts[role], 'startup cache artifact mismatch')
            digest = bytes.fromhex(image['load_commands_sha256'])
            address, kind = image['address'], 2
        records.append(IMAGE.pack(kind, encoded, bytes.fromhex(artifacts[role]),
                                  digest, address))
    mappings = []
    for _, address, size, _, maximum, initial, digest in cache.get('mappings', []):
        if not maximum & 2:
            _require(digest is not None and size > 0, 'immutable startup cache mapping')
            mappings.append(MAPPING.pack(address, size, maximum, initial,
                                         bytes.fromhex(digest)))
    _require(2 <= len(records) <= 512 and 0 < len(mappings) <= 256,
             'startup inventory/cache unavailable')
    _require(signature['file_sha256'] == artifacts['launcher'], 'startup launcher binding')
    cdhash = bytes.fromhex(signature['metadata']['CDHash'])
    _require(len(cdhash) == 20 and any(cdhash), 'startup launcher CDHash')
    return HEADER.pack(b'PAEXEC01', sha256(canonical_bytes(expected)).digest(),
                       cdhash, len(records), len(mappings)) + b''.join(records + mappings)
