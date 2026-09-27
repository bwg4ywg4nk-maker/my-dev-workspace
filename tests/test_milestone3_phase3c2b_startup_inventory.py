"""Deployment-derived inventory and native rejection; synthetic images only."""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from presentation_agent import _startup_inventory as startup
from presentation_agent import _shared_cache as cache
from presentation_agent.evidence import canonical_bytes
from test_milestone3_phase3c2b_deployment import macho
from test_milestone3_phase3c2b_shared_cache import (
    cache_file, Memory, NAME, MAIN_IMAGE, SUB_IMAGE)

ROOT = Path(__file__).resolve().parents[1]


def standalone(dependencies=(), kind=2):
    data = bytearray(macho(dependencies))
    size = struct.unpack_from('<I', data, 20)[0] + 72
    count = struct.unpack_from('<I', data, 16)[0] + 1
    struct.pack_into('<III', data, 12, kind, count, size)
    data += struct.pack('<II16s4Q4I', 0x19, 72, b'__TEXT', 0x100000000, 4096,
                        0, 4096, 5, 5, 0, 0)
    return bytes(data) + bytes(4096 - len(data))


HARNESS = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <mach/mach.h>
#include <mach/mach_vm.h>
static int writable;
static kern_return_t fixture_region(vm_map_t task, mach_vm_address_t *address,
    mach_vm_size_t *size, vm_region_flavor_t flavor, vm_region_info_t result,
    mach_msg_type_number_t *count, mach_port_t *object) {
    vm_region_basic_info_64_t info = (vm_region_basic_info_64_t)result;
    (void)task; (void)address; (void)flavor; (void)count;
    memset(info, 0, sizeof(*info));
    info->protection = 5; info->max_protection = writable ? 7 : 5;
    *size = 4096; *object = MACH_PORT_NULL;
    return KERN_SUCCESS;
}
#define mach_vm_region fixture_region
#include "loader_state.c"
#undef mach_vm_region
static unsigned char *read_file(const char *path, size_t *size) {
    FILE *f = fopen(path, "rb"); unsigned char *data; long n;
    assert(f && !fseek(f, 0, SEEK_END)); n = ftell(f); assert(n > 0);
    rewind(f); data = malloc((size_t)n); assert(data);
    assert(fread(data, 1, (size_t)n, f) == (size_t)n); fclose(f);
    *size = (size_t)n; return data;
}
int main(int argc, char **argv) {
    struct pa_startup_binding binding;
    struct pa_loader_observation *state = calloc(1, sizeof(*state));
    unsigned char *data, *launcher, *loader, *main_cache, *sub, *mapped;
    unsigned char cdhash[20]; size_t size;
    (void)&require_loader_state;
    assert(argc == 6 && state);
    data = read_file(argv[1], &binding.size); binding.bytes = data;
    CC_SHA256(data, (CC_LONG)binding.size, binding.sha256);
    memcpy(binding.deployment_sha256, data + 8, 32); memcpy(cdhash, data + 40, 20);
    launcher = read_file(argv[2], &size); assert(size == 4096);
    loader = read_file(argv[3], &size); assert(size == 4096);
    main_cache = read_file(argv[4], &size); assert(size == 4096);
    sub = read_file(argv[5], &size); assert(size == 4096);
    mapped = malloc(8192); assert(mapped);
    memcpy(mapped, main_cache, 4096); memcpy(mapped + 4096, sub, 4096);
    state->count = 3; state->initial_count = 3; state->pid = getpid();
    state->dyld_address = (uintptr_t)loader; strcpy(state->dyld_path, argv[3]);
    state->cache_address = (uintptr_t)mapped;
    state->cache_slide = (uintptr_t)mapped - 0x100000;
    memcpy(state->cache_uuid, mapped + 88, 16);
    state->images[0].address = (uintptr_t)launcher; strcpy(state->images[0].path, argv[2]);
    state->images[1].address = (uintptr_t)mapped + 1024;
    strcpy(state->images[1].path, "/usr/lib/libSystem.B.dylib");
    state->images[2].address = (uintptr_t)mapped + 5120;
    strcpy(state->images[2].path, "/usr/lib/system/libfixture.dylib");
#define VERIFY() startup_inventory(&binding, state, cdhash)
    assert(VERIFY());
    state->count = 2; assert(!VERIFY()); state->count = 3;
    state->images[3] = state->images[2]; strcpy(state->images[3].path, "/injected.dylib");
    state->count = 4; assert(!VERIFY()); state->count = 3;
    state->images[1].address++; assert(!VERIFY()); state->images[1].address--;
    state->cache_slide++; assert(!VERIFY()); state->cache_slide--;
    state->cache_uuid[0] ^= 1; assert(!VERIFY()); state->cache_uuid[0] ^= 1;
    state->cache_address++; assert(!VERIFY()); state->cache_address--;
    launcher[2048] ^= 1; assert(!VERIFY()); launcher[2048] ^= 1;
    loader[2048] ^= 1; assert(!VERIFY()); loader[2048] ^= 1;
    mapped[8191] ^= 1; assert(!VERIFY()); mapped[8191] ^= 1;
    writable = 1; assert(!VERIFY()); writable = 0;
    cdhash[0] ^= 1; assert(!VERIFY()); cdhash[0] ^= 1;
    binding.deployment_sha256[0] ^= 1; assert(!VERIFY()); binding.deployment_sha256[0] ^= 1;
    binding.size--; assert(!VERIFY()); binding.size++;
    data[8] ^= 1; assert(!VERIFY()); data[8] ^= 1;
    /* Replacement with a byte-different file while the original is mapped. */
    { FILE *f = fopen(argv[2], "r+b"); assert(f); assert(!fseek(f, 2048, SEEK_SET));
      assert(fputc(1, f) == 1); fclose(f); assert(!VERIFY());
      f = fopen(argv[2], "r+b"); assert(f); assert(!fseek(f, 2048, SEEK_SET));
      assert(fputc(0, f) == 0); fclose(f); }
    assert(VERIFY());
    /* dyld may also be present in the image array, but cannot be substituted. */
    state->images[3].address = (uintptr_t)loader; strcpy(state->images[3].path, argv[3]);
    state->count = 4; assert(VERIFY());
    state->images[3].address++; assert(!VERIFY());
    free(state); free(data); free(launcher); free(loader); free(main_cache); free(sub); free(mapped);
    return 0;
}
'''


class StartupInventoryTests(unittest.TestCase):
    def setUp(self):
        parent = ROOT / 'build/startup-inventory-unit'
        parent.mkdir(parents=True, exist_ok=True)
        self.work = Path(tempfile.mkdtemp(dir=parent))
        main, sub = cache_file(0), cache_file(1)
        (self.work / NAME).write_bytes(main)
        (self.work / (NAME + '.1')).write_bytes(sub)
        evidence, artifacts, _ = cache._collect(
            [MAIN_IMAGE], 'x86_64', Memory(main, sub), (self.work,))
        self.native = {'launcher': self.work / 'launcher', 'loader': self.work / 'dyld',
                       'c-runtime': MAIN_IMAGE}
        self.native['launcher'].write_bytes(standalone([MAIN_IMAGE, str(self.native['loader'])]))
        self.native['loader'].write_bytes(standalone(kind=7))
        sub_role = 'shared-cache-image-' + sha256(SUB_IMAGE.encode()).hexdigest()
        hashes = {role: sha256(self.native[role].read_bytes()).hexdigest()
                  for role in ('launcher', 'loader')}
        hashes.update({'c-runtime': artifacts[MAIN_IMAGE], sub_role: artifacts[SUB_IMAGE]})
        self.expected = {'deployment': {'native_artifacts': sorted([k, v] for k, v in hashes.items()),
            'native_dependencies': [['launcher', ['c-runtime', 'loader']], ['loader', []],
                                    ['c-runtime', [sub_role]], [sub_role, []]],
            'shared_cache': evidence}}
        self.signature = {'file_sha256': hashes['launcher'], 'metadata': {'CDHash': '11' * 20}}

    def encode(self):
        return startup._encode(self.expected, self.native, 'x86_64', self.signature)

    def test_inventory_derives_closure_and_binds_entire_deployment(self):
        before = deepcopy(self.expected)
        data = self.encode()
        magic, deployment_id, cdhash, count, mappings = startup.HEADER.unpack_from(data)
        self.assertEqual((magic, count, mappings), (b'PAEXEC01', 4, 2))
        self.assertEqual(deployment_id, sha256(canonical_bytes(self.expected)).digest())
        self.assertEqual(cdhash, bytes.fromhex('11' * 20))
        self.assertEqual(data, self.encode())
        self.assertEqual(before, self.expected)

    def test_changed_standalone_cache_binding_and_unsafe_closure_reject(self):
        for change in ('file', 'cache', 'closure'):
            before = deepcopy(self.expected)
            if change == 'file':
                path = self.native['loader']; original = path.read_bytes()
                path.write_bytes(original + b'changed')
            elif change == 'cache':
                self.expected['deployment']['shared_cache']['images'][0]['uuid'] = 'ff' * 16
            else:
                self.expected['deployment']['native_dependencies'][0][1].append('python-framework')
            with self.assertRaises(ValueError):
                self.encode()
            self.expected = before
            if change == 'file':
                path.write_bytes(original)

    def test_public_collector_reverifies_without_authorizing(self):
        with patch.object(startup.deployment, 'verify') as verify, \
             patch.object(startup.policy, '_signature', return_value=self.signature):
            data = startup.collect(self.expected, {}, {}, self.native, [],
                                   {'architecture': 'x86_64'})
            self.assertEqual(data, self.encode())
            self.assertEqual(verify.call_count, 2)
        with patch.object(startup.deployment, 'verify', side_effect=ValueError('unverified')):
            with self.assertRaises(ValueError):
                startup.collect(self.expected, {}, {}, self.native, [], {'architecture': 'x86_64'})

    @unittest.skipUnless(sys.platform == 'darwin' and shutil.which('clang'), 'requires Apple clang')
    def test_native_inventory_rejects_extra_missing_and_substituted_images(self):
        evidence_file = self.work / 'startup.bin'
        evidence_file.write_bytes(self.encode())
        source = self.work / 'harness.c'
        source.write_text(HARNESS)
        binary = self.work / 'harness'
        subprocess.run(['clang', '-std=c11', '-Wall', '-Wextra', '-Werror',
                        '-I' + str(ROOT / 'tools/restricted_launcher'),
                        str(source), '-o', str(binary)], check=True, capture_output=True)
        subprocess.run([str(binary), str(evidence_file), str(self.native['launcher']),
                        str(self.native['loader']), str(self.work / NAME),
                        str(self.work / (NAME + '.1'))], check=True)
