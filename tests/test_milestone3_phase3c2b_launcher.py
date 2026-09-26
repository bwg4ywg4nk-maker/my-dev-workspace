"""Native Phase-2 admission/order tests; no real provider qualification."""
from pathlib import Path
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'tools/restricted_launcher/launcher.c'

HARNESS = r'''
#include <assert.h>
static int loads, stage, fail;
static void *fake_load(const char *path, int flags) {
    assert(stage == 4 && !strcmp(path, "/exact/Python"));
    assert(flags == (RTLD_NOW | RTLD_LOCAL));
    ++loads; return (void *)&loads;
}
static int step(int n) { assert(++stage == n); return fail != n; }
static int launcher(void) { return step(1); }
static int framework(const char *p) { assert(!strcmp(p, "/exact/Python")); return step(2); }
static int build(void) { return step(3); }
static int runtime(void) { return step(4); }
int main(int argc, char **argv) {
    const struct pa_pair allow[] = {{"HOME", "/fixed"}, {"EMPTY", ""}};
    const struct pa_checks checks = {launcher, framework, build, runtime};
    char *good[] = {"HOME=/fixed", "EMPTY="};
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
        stage = 0; fail = 0;
        assert(!verified_load(good, 2, allow, 2, "Python", &checks));
        assert(!verified_load(good, 2, allow, 2, "/exact/Python", NULL));
        assert(!verified_load(good, 2, NULL, 0, "/exact/Python", &checks));
        assert(stage == 0 && loads == 0);
        assert(verified_load(good, 2, allow, 2, "/exact/Python", &checks));
        assert(loads == 1);
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
        source.write_text(
            '#include <dlfcn.h>\n#include <string.h>\n'
            'static void *fake_load(const char *, int);\n'
            '#define dlopen fake_load\n#define main production_main\n'
            f'#include "{SOURCE}"\n#undef main\n#undef dlopen\n' + HARNESS)
        for src, output in ((SOURCE, cls.launcher), (source, cls.harness)):
            subprocess.run(['clang', '-std=c11', '-Wall', '-Wextra', '-Werror',
                            '-I' + sysconfig.get_path('include'), str(src), '-o', str(output)], check=True, capture_output=True)

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

    def test_production_entry_remains_closed(self):
        for env in ({}, {'fReEtYpE_PROPERTIES': ''}, {'FT2_X': '1'}):
            result = subprocess.run([str(self.launcher)], env=env, capture_output=True)
            self.assertEqual(result.returncode, 78)
            self.assertIn(b'qualification denied', result.stderr)

    def test_no_python_startup_dependency(self):
        result = subprocess.run(['otool', '-L', str(self.launcher)],
                                check=True, capture_output=True, text=True)
        dependencies = result.stdout.splitlines()[1:]
        self.assertEqual(len(dependencies), 1)
        self.assertIn('/usr/lib/libSystem.B.dylib', dependencies[0])

    def test_ordinary_python_provider_gate_stays_closed(self):
        from presentation_agent import layout
        with self.assertRaises(ValueError):
            layout._open_provider(None)
