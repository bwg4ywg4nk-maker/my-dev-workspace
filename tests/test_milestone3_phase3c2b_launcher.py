"""Native Phase-2 admission/order tests; no real provider qualification."""
from pathlib import Path
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import unittest

from attachment_launcher_test_support import STUB

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'tools/restricted_launcher/launcher.c'

HARNESS = r'''
#include <assert.h>
static int loads, stage, fail, mutate, change_pid, loader_calls;
static int fake_loader_state(const struct pa_startup_binding *binding,
                             const struct pa_process_identity *identity) {
    (void)binding; (void)identity; ++loader_calls;
    if (mutate == 5 || (mutate == 6 && loader_calls == 2)) {
        if (change_pid) ++pid_offset; else ++hash_byte;
    }
    return fail != 5;
}
static void *fake_load(const char *path, int flags) {
    assert(stage == 4 && !strcmp(path, "/exact/Python"));
    assert(flags == (RTLD_NOW | RTLD_LOCAL));
    ++loads; return (void *)&loads;
}
static int step(int n) {
    assert(++stage == n);
    if (mutate == n) { if (change_pid) ++pid_offset; else ++hash_byte; }
    return fail != n;
}
static int launcher(void) { return step(1); }
static int framework(const char *p) { assert(!strcmp(p, "/exact/Python")); return step(2); }
static int build(void) { return step(3); }
static int runtime(void) { return step(4); }
int main(int argc, char **argv) {
    const struct pa_pair allow[] = {{"HOME", "/fixed"}, {"EMPTY", ""}};
    const struct pa_attachment_binding attachment = {"/exact/Python"};
    const struct pa_checks checks = {launcher, framework, build, runtime, NULL, &attachment};
    char *good[] = {"HOME=/fixed", "EMPTY="};
    (void)&require_loader_state; /* Keep the real closed boundary compiled. */
    assert(argc == 2);
    if (!strcmp(argv[1], "environment")) {
        char *bad[] = {"FREETYPE_PROPERTIES=", "fReEtYpE_x=1", "Ft2_X=",
                       "HOME=/other", "home=/fixed", "HOME", "=x", "1A=x",
                       "A-B=x", "UNKNOWN=x"};
        size_t i;
        assert(admit(good, 2, allow, 2));
        assert(admit(NULL, 0, NULL, 0));
        for (i = 0; i < sizeof(bad)/sizeof(*bad); ++i)
            assert(!admit(&bad[i], 1, allow, 2));
        good[1] = good[0]; assert(!admit(good, 2, allow, 2));
        { const struct pa_pair forbidden[] = {{"ft2_X", ""}};
          char *e[] = {"ft2_X="}; assert(!admit(e, 1, forbidden, 1)); }
        { const char *names[] = {"DYLD_INSERT_LIBRARIES", "dyld_library_path",
                                 "LD_PRELOAD", "__XPC_DYLD_FRAMEWORK_PATH"};
          size_t k;
          for (k = 0; k < sizeof(names)/sizeof(*names); ++k) {
              char entry[128]; char *entries[] = {entry};
              const struct pa_pair override[] = {{names[k], ""}};
              snprintf(entry, sizeof(entry), "%s=", names[k]);
              assert(!admit(entries, 1, override, 1));
          }
        }
        assert(!admit(NULL, PA_MAX_ENV + 1, NULL, 0));
    } else if (!strcmp(argv[1], "original")) {
        char buf[256] = {0}, *env[PA_MAX_ENV];
        const char payload[] = "/launcher\0/launcher\0arg\0fT2_X=\0\0";
        int n = 2; size_t count;
        memcpy(buf, &n, sizeof(n)); memcpy(buf + sizeof(n), payload, sizeof(payload));
        /* Sanitizing current environ cannot repair the original record. */
        unsetenv("fT2_X");
        assert(original_record(buf, sizeof(n) + sizeof(payload), env, &count));
        assert(count == 1 && !admit(env, count, NULL, 0));
        assert(!original_record(buf, sizeof(n), env, &count));
        assert(!original_record(buf, sizeof(n) + sizeof(payload) - 4, env, &count));
        n = -1; memcpy(buf, &n, sizeof(n));
        assert(!original_record(buf, sizeof(buf), env, &count));
        n = 2; memcpy(buf, &n, sizeof(n));
        buf[sizeof(n) + sizeof(payload)] = 'X';
        assert(original_record(buf, sizeof(buf), env, &count));
        assert(count == 1); /* trailing OS data is not an environment entry */
    } else if (!strcmp(argv[1], "empty-argv0")) {
        char buf[256] = {0}, *env[PA_MAX_ENV];
        const char payload[] = "/launcher\0\0FT2_X=\0\0";
        int n = 1; size_t count;
        memcpy(buf, &n, sizeof(n)); memcpy(buf + sizeof(n), payload, sizeof(payload));
        assert(!(original_record(buf, sizeof(n) + sizeof(payload), env, &count) &&
                 admit(env, count, NULL, 0)));
        assert(!original_record(buf, sizeof(n) + sizeof(payload), env, &count));
        /* Additional padding must not make the empty argv[0] disappear. */
        { const char padded[] = "/launcher\0\0\0FT2_X=\0\0";
          memcpy(buf + sizeof(n), padded, sizeof(padded));
          assert(!original_record(buf, sizeof(n) + sizeof(padded), env, &count)); }
    } else if (!strcmp(argv[1], "live-original")) {
        int mib[] = {CTL_KERN, KERN_PROCARGS2, (int)getpid()};
        size_t size = PA_MAX_BYTES, count;
        char *buf = malloc(size), *env[PA_MAX_ENV];
        assert(buf);
        unsetenv("fT2_X");
        assert(!getenv("fT2_X"));
        assert(sysctl(mib, 3, buf, &size, NULL, 0) == 0);
        assert(original_record(buf, size, env, &count));
        assert(count == 1 && !strcmp(env[0], "fT2_X="));
        assert(!admit(env, count, NULL, 0));
        free(buf);
    } else if (!strcmp(argv[1], "ordering")) {
        int i;
        for (i = 1; i <= 4; ++i) {
            stage = 0; fail = i;
            assert(!verified_load(good, 2, allow, 2, "/exact/Python", &checks));
            assert(stage == i && loads == 0);
        }
        stage = 0; fail = 5;
        assert(!verified_load(good, 2, allow, 2, "/exact/Python", &checks));
        assert(stage == 0 && loads == 0);
        stage = 0; fail = 0;
        assert(!verified_load(good, 2, allow, 2, "Python", &checks));
        assert(!verified_load(good, 2, allow, 2, "/exact/Python", NULL));
        assert(!verified_load(good, 2, NULL, 0, "/exact/Python", &checks));
        assert(stage == 0 && loads == 0);
        assert(verified_load(good, 2, allow, 2, "/exact/Python", &checks));
        assert(loads == 1);
    } else if (!strcmp(argv[1], "entry")) {
        runtime_failure = 1;
        assert(production_main() == 78);
        assert(status_calls > 0 && loader_calls == 0 && loads == 0);
        runtime_failure = 0; status_calls = 0;
        assert(production_main() == 78);
        assert(status_calls > 0 && loader_calls == 1 && loads == 0);
    } else if (!strcmp(argv[1], "identity")) {
        int n, kind;
        for (kind = 0; kind < 2; ++kind) for (n = 1; n <= 6; ++n) {
            stage = 0; loader_calls = 0; pid_offset = 0; hash_byte = 1;
            mutate = n; change_pid = kind;
            assert(!verified_load(good, 2, allow, 2, "/exact/Python", &checks));
            assert(loads == 0);
            assert(stage == (n <= 4 ? n : n == 5 ? 0 : 4));
        }
    } else return 1;
    return 0;
}
'''


@unittest.skipUnless(sys.platform == 'darwin' and shutil.which('clang'),
                     'macOS launcher tests require existing Apple clang')
class LauncherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        parent = ROOT / 'build/phase2-unit'
        parent.mkdir(parents=True, exist_ok=True)
        cls.work = Path(tempfile.mkdtemp(dir=parent))
        cls.launcher = cls.work / 'launcher'
        cls.harness = cls.work / 'harness'
        source = cls.work / 'harness.c'
        instrumented = cls.work / 'launcher.c'
        instrumented.write_text(SOURCE.read_text().replace(
            '#include "attachment_launcher.c"', STUB).replace(
            '    if (attachment_launch.attempted || attachment_launch.invalid)',
            '    memset(&attachment_launch, 0, sizeof(attachment_launch));\n'
            '    if (attachment_launch.attempted || attachment_launch.invalid)').replace(
            '#include \"loader_state.c\"',
            '#include \"loader_state.c\"\n'
            'static int fake_loader_state(const struct pa_startup_binding *, const struct pa_process_identity *);\n'
            '#define require_loader_state fake_loader_state'))
        source.write_text(
            '#include <dlfcn.h>\n#include <string.h>\n'
            '#include <unistd.h>\n#include <stdint.h>\n'
            'static int pid_offset, hash_byte = 1, runtime_failure, status_calls;\n'
            'static pid_t fake_pid(void) { return getpid() + pid_offset; }\n'
            'static int fake_csops(pid_t p, unsigned int op, void *out, size_t size) {\n'
            ' (void)p; memset(out, 0, size);\n'
            ' if (op == 0) { ++status_calls; if (runtime_failure) return -1;\n'
            ' *(uint32_t *)out = 0x22013301u; }\n'
            ' if (op == 5) memset(out, hash_byte, size); return 0; }\n'
            '#define getpid fake_pid\n#define csops fake_csops\n'
            'static void *fake_load(const char *, int);\n'
            '#define dlopen fake_load\n#define main production_main\n'
            f'#include "{instrumented}"\n#undef main\n#undef dlopen\n#undef require_loader_state\n' + HARNESS)
        for src, output in ((SOURCE, cls.launcher), (source, cls.harness)):
            subprocess.run(['clang', '-std=c11', '-Wall', '-Wextra', '-Werror',
                            '-Wno-deprecated-declarations',
                            '-framework', 'IOKit', '-framework', 'CoreFoundation', '-lbsm',
                            '-I' + sysconfig.get_path('include'), '-I' + str(SOURCE.parent),
                            str(src), '-o', str(output)], check=True, capture_output=True)

    def test_exact_environment_admission(self):
        subprocess.run([str(self.harness), 'environment'], check=True)

    def test_original_record_and_malformed_records(self):
        subprocess.run([str(self.harness), 'original'], check=True)

    def test_empty_argv0_cannot_hide_forbidden_environment(self):
        subprocess.run([str(self.harness), 'empty-argv0'], check=True)

    def test_all_checks_precede_exact_framework_load(self):
        subprocess.run([str(self.harness), 'ordering'], check=True)

    def test_kernel_record_survives_current_environment_sanitization(self):
        subprocess.run([str(self.harness), 'live-original'],
                       env={'fT2_X': ''}, check=True)

    def test_entry_always_checks_hardened_runtime_and_remains_closed(self):
        subprocess.run([str(self.harness), 'entry'], check=True)

    def test_identity_changes_at_every_preload_step_reject(self):
        subprocess.run([str(self.harness), 'identity'], check=True)

    def test_production_entry_remains_closed(self):
        for env in ({}, {'fReEtYpE_PROPERTIES': ''}, {'FT2_X': '1'}):
            result = subprocess.run([str(self.launcher)], env=env, capture_output=True)
            self.assertEqual(result.returncode, 78)
            self.assertIn(b'qualification denied', result.stderr)

    def test_no_python_startup_dependency(self):
        result = subprocess.run(['otool', '-L', str(self.launcher)],
                                check=True, capture_output=True, text=True)
        dependencies = result.stdout.splitlines()[1:]
        self.assertTrue(any('/usr/lib/libSystem.B.dylib' in p for p in dependencies))
        self.assertTrue(any('IOKit.framework' in p for p in dependencies))
        self.assertFalse(any('Python' in p for p in dependencies))
        self.assertTrue(all(any(allowed in p for allowed in
                               ('libSystem.B.dylib', 'IOKit.framework',
                                'CoreFoundation.framework', 'libbsm.', 'libobjc.A.dylib'))
                            for p in dependencies))

    def test_ordinary_python_provider_gate_stays_closed(self):
        from presentation_agent import layout
        with self.assertRaises(ValueError):
            layout._open_provider(None)
