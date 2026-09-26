"""Phase 4.5A3 cache evidence only; no provider or launcher activation."""
from hashlib import sha256
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from presentation_agent import _shared_cache as cache
from presentation_agent import _deployment_evidence as deployment


BASE = 0x100000
MAIN_IMAGE = '/usr/lib/libSystem.B.dylib'
SUB_IMAGE = '/usr/lib/system/libfixture.dylib'
NAME = 'dyld_shared_cache_x86_64h'


def command(kind, path):
    raw = path.encode() + b'\0'
    size = (24 + len(raw) + 7) // 8 * 8
    return struct.pack('<6I', kind, size, 24, 0, 0, 0) + raw + bytes(size - 24 - len(raw))


def image(path, address, dependency=None):
    commands = [command(0xD, path), struct.pack('<II16s', 0x1B, 24, b'i' * 16),
                struct.pack('<II16s4Q4I', 0x19, 72, b'__TEXT', address + 1024, 3072,
                            1024, 3072, 5, 5, 0, 0)]
    if dependency:
        commands.append(command(0xC, dependency))
    body = b''.join(commands)
    return struct.pack('<8I', 0xFEEDFACF, 0x1000007, 8, 6, len(commands),
                       len(body), 0x80000000, 0) + body


def cache_file(index):
    data = bytearray(4096)
    data[:16] = b'dyld_v1 x86_64h\0'
    struct.pack_into('<II', data, 16, 456, 1)
    data[88:104] = bytes([index + 1]) * 16
    struct.pack_into('<QQQII', data, 456, BASE + index * 4096, 4096, 0, 5, 5)
    if index == 0:
        struct.pack_into('<II', data, 392, 800, 1)
        struct.pack_into('<16sQ', data, 800, bytes([2]) * 16, 4096)
        struct.pack_into('<II', data, 448, 600, 2)
        for i, path in enumerate((MAIN_IMAGE, SUB_IMAGE)):
            struct.pack_into('<QQQII', data, 600 + i * 32,
                             BASE + i * 4096 + 1024, 0, 0, 700 + i * 50, 0)
            raw = path.encode() + b'\0'
            data[700 + i * 50:700 + i * 50 + len(raw)] = raw
    mh = image(MAIN_IMAGE if index == 0 else SUB_IMAGE,
               BASE + index * 4096, SUB_IMAGE if index == 0 else None)
    data[1024:1024 + len(mh)] = mh
    return data


class Memory:
    base, size = BASE, 8192

    def __init__(self, main, sub):
        self.data = bytearray(main + sub)
        self.maximum = 5

    def read(self, address, size):
        return bytes(self.data[address - BASE:address - BASE + size])

    def protection(self, address):
        return BASE + self.size, 5, self.maximum


class SharedCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.main, self.sub = cache_file(0), cache_file(1)
        self.memory = Memory(self.main, self.sub)
        self.write()

    def write(self, update_memory=True):
        (self.root / NAME).write_bytes(self.main)
        (self.root / (NAME + '.1')).write_bytes(self.sub)
        if update_memory:
            self.memory.data = bytearray(self.main + self.sub)

    def collect(self, required=(MAIN_IMAGE,)):
        return cache._collect(required, 'x86_64', self.memory, (self.root,))

    def test_whole_files_membership_and_transitive_dependencies(self):
        evidence, artifacts, dependencies = self.collect()
        self.assertEqual(evidence['files'], [['main', sha256(self.main).hexdigest()],
                                          ['subcache-1', sha256(self.sub).hexdigest()]])
        self.assertEqual(set(artifacts), {MAIN_IMAGE, SUB_IMAGE})
        self.assertEqual(dependencies, {MAIN_IMAGE: [SUB_IMAGE], SUB_IMAGE: []})
        self.assertEqual(len(evidence['mappings']), 2)
        self.assertEqual(self.collect(), (evidence, artifacts, dependencies))
        self.assertNotIn(str(self.root), str(evidence))

    def test_uuid_is_not_the_artifact_identity(self):
        before = self.collect()[1]
        self.sub[-1] = 1
        self.write()
        self.assertNotEqual(before, self.collect()[1])

    def test_complete_file_includes_unmapped_trailer(self):
        before = self.collect()[1]
        self.sub += b'signed-file-trailer'
        self.write()
        self.assertNotEqual(before, self.collect()[1])

    def test_missing_subcache(self):
        struct.pack_into('<I', self.main, 396, 2)
        struct.pack_into('<16sQ', self.main, 824, bytes([3]) * 16, 8192)
        self.write()
        with self.assertRaisesRegex(ValueError, 'file unavailable'):
            self.collect()

    def test_declared_symbols_file_is_required(self):
        self.main[400:416] = b's' * 16
        self.write()
        with self.assertRaisesRegex(ValueError, 'file unavailable'):
            self.collect()

    def test_mapping_extent_rejected(self):
        struct.pack_into('<Q', self.sub, 464, 8192)
        self.write()
        with self.assertRaisesRegex(ValueError, 'mapping bounds'):
            self.collect()

    def test_ambiguous_active_cache_rejected(self):
        with self.assertRaisesRegex(ValueError, 'missing or ambiguous'):
            cache._collect([MAIN_IMAGE], 'x86_64', self.memory, (self.root, self.root))

    def test_missing_cache_dependency_rejected(self):
        self.main[751] = ord('X')
        self.write()
        with self.assertRaisesRegex(ValueError, 'image missing'):
            self.collect()

    def test_missing_membership(self):
        with self.assertRaisesRegex(ValueError, 'image missing'):
            self.collect(('/usr/lib/absent.dylib',))

    def test_wrong_subcache_uuid(self):
        self.sub[88] ^= 1
        self.write()
        with self.assertRaisesRegex(ValueError, 'identity/mapping'):
            self.collect()

    def test_wrong_subcache_mapping(self):
        struct.pack_into('<Q', self.main, 816, 8192)
        self.write()
        with self.assertRaisesRegex(ValueError, 'identity/mapping'):
            self.collect()

    def test_live_subcache_header_mismatch(self):
        self.memory.data[4096 + 88] ^= 1
        with self.assertRaisesRegex(ValueError, 'header mismatch'):
            self.collect()

    def test_immutable_byte_mismatch(self):
        self.memory.data[-1] ^= 1
        with self.assertRaisesRegex(ValueError, 'immutable cache byte mismatch'):
            self.collect()

    def test_live_mapping_protection_mismatch(self):
        self.memory.maximum = 7
        with self.assertRaisesRegex(ValueError, 'protection mismatch'):
            self.collect()

    def test_unknown_format_rejected(self):
        struct.pack_into('<I', self.main, 16, 512)
        self.write()
        with self.assertRaisesRegex(ValueError, 'unsupported active'):
            self.collect()

    def test_architecture_mismatch(self):
        with self.assertRaisesRegex(ValueError, 'architecture'):
            cache._collect([MAIN_IMAGE], 'arm64', self.memory, (self.root,))

    def test_image_must_be_in_immutable_mapping(self):
        struct.pack_into('<Q', self.main, 600, BASE + 9000)
        self.write()
        with self.assertRaisesRegex(ValueError, 'outside immutable'):
            self.collect()

    def test_image_install_name_mismatch(self):
        self.main[1024 + 32 + 24] = ord('X')
        self.write()
        with self.assertRaisesRegex(ValueError, 'name/UUID/segments'):
            self.collect()

    def test_unmapped_zero_file_size_segment_rejected(self):
        count, size = struct.unpack_from('<II', self.main, 1024 + 16)
        segment = struct.pack('<II16s4Q4I', 0x19, 72, b'__DATA',
                              BASE + self.memory.size, 4096, 0, 0, 3, 3, 0, 0)
        offset = 1024 + 32 + size
        self.main[offset:offset + len(segment)] = segment
        struct.pack_into('<II', self.main, 1024 + 16, count + 1, size + len(segment))
        self.write()
        with self.assertRaisesRegex(ValueError, 'cached segment mapping mismatch'):
            self.collect()

    def test_malformed_load_commands(self):
        struct.pack_into('<I', self.main, 1024 + 32 + 4, 0)
        self.write()
        with self.assertRaisesRegex(ValueError, 'load command size'):
            self.collect()

    def test_image_cpu_mismatch(self):
        struct.pack_into('<I', self.main, 1024 + 4, 0x100000C)
        self.write()
        with self.assertRaisesRegex(ValueError, 'architecture'):
            self.collect()

    def test_file_mutation_during_collection(self):
        original = self.memory.read

        def mutate(address, size):
            if size > 456:
                with (self.root / NAME).open('ab') as stream:
                    stream.write(b'x')
            return original(address, size)

        self.memory.read = mutate
        with self.assertRaisesRegex(ValueError, 'changed during collection'):
            self.collect()

    def test_collector_binds_cache_evidence_without_changing_manifest_schema(self):
        from test_milestone3_phase3c2b_deployment import DeploymentTests
        fixture = DeploymentTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        old = str(fixture.native['c-runtime'])
        fixture.native['c-runtime'] = Path(MAIN_IMAGE)
        from test_milestone3_phase3c2b_deployment import macho
        for path in set(fixture.native.values()):
            if path.is_file():
                dependencies = deployment._dependencies(path, 'x86_64')
                path.write_bytes(macho([MAIN_IMAGE if p == old else p for p in dependencies]))
        fixture.refresh_build()
        cache_result = self.collect()
        with patch.object(cache, 'collect', return_value=cache_result):
            result = fixture.collect()
            self.assertEqual(result['deployment']['shared_cache'], cache_result[0])
            self.assertIn(['c-runtime', cache_result[1][MAIN_IMAGE]],
                          result['runtime_manifest']['native_runtime_artifacts'])
            self.assertEqual(deployment.verify(result, fixture.build, fixture.build_files,
                             fixture.native, [fixture.modules], fixture.runtime), result['runtime_id'])
            changed = dict(result, deployment=dict(result['deployment'], shared_cache={}))
            with self.assertRaisesRegex(ValueError, 'evidence mismatch'):
                deployment.verify(changed, fixture.build, fixture.build_files,
                                  fixture.native, [fixture.modules], fixture.runtime)


if __name__ == '__main__':
    unittest.main()
