"""Native Hardened Runtime state and pre-entry injection rejection only."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SUPPORT = ROOT / 'tools/restricted_launcher'
PRELUDE = '#include <unistd.h>\n#include <stddef.h>\n#include <string.h>\n#include <stdint.h>\n'


@unittest.skipUnless(sys.platform == 'darwin' and shutil.which('clang'),
                     'requires existing Apple tools')
class HardenedRuntimeTests(unittest.TestCase):
    def setUp(self):
        parent = ROOT / 'build/hardened-runtime-unit'
        parent.mkdir(parents=True, exist_ok=True)
        self.work = Path(tempfile.mkdtemp(dir=parent))

    def compile(self, name, body, *flags):
        source = self.work / (name + '.c')
        binary = self.work / name
        source.write_text(PRELUDE + body)
        result = subprocess.run(['clang', '-std=c11', '-Wall', '-Wextra', '-Werror',
                                 '-I' + str(SUPPORT), *flags, str(source), '-o', str(binary)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return binary

    def test_kernel_enforces_signed_runtime_before_entry(self):
        binary = self.compile('probe', '''
#include "hardened_runtime.c"
#include <stdio.h>
#include <errno.h>
int main(void) {
    unsigned char hash[20];
    if (hardened_runtime(hash)) return 0;
    { uint32_t flags = 0; unsigned char b[8] = {0};
      int status = csops(getpid(), 0, &flags, sizeof(flags));
      fprintf(stderr, "status=%d flags=%x\\n", status, flags);
      status = csops(getpid(), 7, b, 8);
      fprintf(stderr, "xml=%d errno=%d first=%x\\n", status, errno, b[0]);
      status = csops(getpid(), 16, b, 8);
      fprintf(stderr, "der=%d errno=%d first=%x\\n", status, errno, b[0]); }
    return 78;
}
''')
        subprocess.run(['codesign', '--force', '--sign', '-', str(binary)],
                       check=True, capture_output=True)
        self.assertEqual(subprocess.run([str(binary)], env={}).returncode, 78)
        subprocess.run(['codesign', '--force', '--sign', '-', '--options', 'runtime',
                        str(binary)], check=True, capture_output=True)
        self.assertEqual(subprocess.run([str(binary)], env={}).returncode, 0)
        injected = self.compile('injected.dylib', '''
__attribute__((constructor)) static void injected(void) { _exit(91); }
''', '-dynamiclib')
        subprocess.run(['codesign', '--force', '--sign', '-', str(injected)],
                       check=True, capture_output=True)
        self.assertEqual(subprocess.run([str(binary)], env={
            'DYLD_INSERT_LIBRARIES': str(injected),
            'DYLD_LIBRARY_PATH': str(self.work),
        }, capture_output=True).returncode, 0)

    def test_unavailable_invalid_debugged_entitled_or_changed_state_rejects(self):
        binary = self.compile('flags', r'''
#include <assert.h>
static uint32_t flags;
static int fail_op = -1, entitled, changed, statuses;
static int fake_csops(pid_t pid, unsigned int op, void *out, size_t size) {
    assert(pid == getpid());
    if ((int)op == fail_op) return -1;
    memset(out, 0, size);
    if (op == 0) { *(uint32_t *)out = flags ^ ((changed && statuses++) ? 1 : 0); }
    else if (op == 5) memset(out, 1, size);
    else if ((op == 7 || op == 16) && entitled == (int)op) memset(out, 1, size);
    return 0;
}
#define csops fake_csops
#include "hardened_runtime.c"
int main(void) {
    unsigned char hash[20];
    uint32_t bit;
    int ops[] = {0, 5, 7, 16};
    size_t i;
    flags = PA_CS_REQUIRED | 0x2000;
    assert(hardened_runtime(hash));
    for (bit = 1; bit; bit <<= 1) {
        if (PA_CS_REQUIRED & bit) {
            flags = (PA_CS_REQUIRED | 0x2000) & ~bit;
            assert(!hardened_runtime(hash));
        }
        if (PA_CS_FORBIDDEN & bit) {
            flags = PA_CS_REQUIRED | 0x2000 | bit;
            assert(!hardened_runtime(hash));
        }
    }
    flags = PA_CS_REQUIRED; assert(!hardened_runtime(hash));
    flags |= 0x10; assert(hardened_runtime(hash));
    for (i = 0; i < sizeof(ops)/sizeof(*ops); ++i) {
        fail_op = ops[i]; assert(!hardened_runtime(hash));
    }
    fail_op = -1;
    entitled = 7; assert(!hardened_runtime(hash));
    entitled = 16; assert(!hardened_runtime(hash));
    entitled = 0; changed = 1; assert(!hardened_runtime(hash));
    return 0;
}
''')
        subprocess.run([str(binary)], check=True)

    def test_identity_is_retained_through_snapshots_and_inventory(self):
        loader = (SUPPORT / 'loader_state.c').read_text().replace(
            'static int require_loader_state(',
            'static int fixture_snapshot(struct pa_loader_observation *);\n'
            'static int fixture_inventory(const struct pa_startup_binding *, '
            'const struct pa_loader_observation *, const unsigned char *);\n'
            '#define loader_snapshot fixture_snapshot\n'
            '#define startup_inventory fixture_inventory\n'
            'static int require_loader_state(', 1)
        binary = self.compile('identity', r'''
#include <assert.h>
#include <stdlib.h>
static int pid_offset, hash_byte = 1, mutation, step, change_pid;
static pid_t fixture_pid(void) { return getpid() + pid_offset; }
static int fixture_csops(pid_t pid, unsigned int op, void *out, size_t size) {
    (void)pid; memset(out, 0, size);
    if (op == 0) *(uint32_t *)out = 0x22013301u;
    if (op == 5) memset(out, hash_byte, size);
    return 0;
}
#define getpid fixture_pid
#define csops fixture_csops
''' + loader + r'''
#undef loader_snapshot
#undef startup_inventory
static void advance(void) {
    if (++step == mutation) {
        if (change_pid) ++pid_offset; else ++hash_byte;
    }
}
static int fixture_snapshot(struct pa_loader_observation *out) {
    memset(out, 0, sizeof(*out)); out->pid = getpid();
    advance(); return 1;
}
static int fixture_inventory(const struct pa_startup_binding *binding,
    const struct pa_loader_observation *state, const unsigned char *hash) {
    (void)binding; (void)state; assert(hash[0] == 1);
    advance(); return 1;
}
int main(void) {
    unsigned char bytes[PA_STARTUP_HEADER] = {0};
    struct pa_startup_binding binding = {0};
    struct pa_process_identity identity;
    int kind, n;
    (void)&loader_snapshot; (void)&startup_inventory;
    binding.bytes = bytes; binding.size = sizeof(bytes);
    for (kind = 0; kind < 2; ++kind) for (n = 0; n <= 3; ++n) {
        pid_offset = 0; hash_byte = 1; step = 0;
        mutation = n; change_pid = kind;
        assert(pin_process_identity(&identity));
        assert(require_loader_state(&binding, &identity) == (n == 0));
        assert(step == (n ? n : 3));
    }
    return 0;
}
''')
        subprocess.run([str(binary)], check=True)
