"""Phase 4.5B trusted provider activation tests.

Tests verify:
1. Allow provider initialization only after every trusted native prerequisite has
   verified successfully in the same process/lifecycle.
2. Keep ordinary Python execution fail-closed.
3. Do not expose:
   - Python-settable token;
   - setter;
   - boolean;
   - environment bypass;
   - public activation API.
4. Permanently reject activation after:
   - lifecycle invalidation;
   - fork;
   - lease loss;
   - evidence mismatch;
   - startup inventory mismatch;
   - provider identity mismatch.
5. Do not claim final production qualification.
"""
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import sysconfig
import tempfile
from typing import Tuple
import unittest

from presentation_agent import layout
from presentation_agent._provider_identity import _document
from presentation_agent.evidence import canonical_bytes

ROOT = Path(__file__).resolve().parents[1]
SUPPORT = ROOT / 'tools/restricted_launcher'


def c_bytes(data):
    return '{' + ','.join(str(value) for value in data) + '}'


SEAM = r'''
#include <wchar.h>
struct pa_identity_document { const unsigned char *bytes; size_t size; unsigned char sha256[32]; };
struct pa_provider_artifact { const char *role, *path; unsigned char sha256[32]; };
struct pa_provider_identity {
    unsigned char adapter_sha256[32], build_evidence_sha256[32], font_sha256[32];
    unsigned char deployment_document_sha256[32];
    struct pa_identity_document build, runtime, profile;
    const struct pa_provider_artifact *artifacts;
    size_t count;
};
struct pa_attachment_binding { const char *framework; };
static struct {
    int attempted, invalid, loaded;
    struct pa_process_identity identity;
    const struct pa_checks *checks;
    void *handle;
} attachment_launch;
static int observer_failure = 0;
static int attachment_launch_reject(void) { attachment_launch.invalid = 1; return 0; }
static int pa_attachment_observer_open(void) { return observer_failure != 1; }
static int attachment_launch_boundary(void) { return observer_failure != 2; }
static int attachment_launch_handoff(void *h, const wchar_t *const *p, size_t n) {
    (void)h; (void)p; (void)n; return 1;
}
static const struct pa_provider_identity *active_provider = NULL;
static const struct pa_provider_identity *native_provider_identity(void) {
    return active_provider;
}
'''

HARNESS = r'''
#include <assert.h>
#include <sys/wait.h>
#define main production_main
#include "launcher.c"
#undef main

int main(int argc, char **argv) {
    const wchar_t *paths[] = {STDLIB, DYNLIB, SRCPATH, SITEPATH};
    void *handle = dlopen(FRAMEWORK, RTLD_NOW | RTLD_GLOBAL);
    int (*run)(const char *, PyCompilerFlags *);
    assert(argc == 2 && handle);
    *(void **)(&run) = dlsym(handle, "PyRun_SimpleStringFlags");
    assert(run != NULL);

    if (!strcmp(argv[1], "no-provider")) {
        active_provider = NULL;
        assert(isolated_bootstrap(handle, paths, 4));
        assert(boundary());
        assert(run(
            "import _pa_private_bootstrap as b\n"
            "assert b._entry() is False\n"
            "from presentation_agent import layout\n"
            "font = layout.FontIdentity(layout._FONT_SHA256, 0, 'Arial', 'Regular')\n"
            "p = layout.LayoutProfile(layout._NAME, 1, font, '12.3.0', '2.14.3', '__BUILD_ID__', '__RUNTIME_ID__')\n"
            "try:\n"
            "    layout._open_provider(p)\n"
            "    assert False, 'must fail closed'\n"
            "except ValueError:\n"
            "    pass\n", NULL) == 0);
        return 0;
    }

    active_provider = &provider;
    assert(isolated_bootstrap(handle, paths, 4));
    assert(boundary());

    if (!strcmp(argv[1], "valid")) {
        assert(run(
            "import _pa_private_bootstrap as b\n"
            "assert b._entry() is True\n"
            "from presentation_agent import layout\n"
            "font = layout.FontIdentity(layout._FONT_SHA256, 0, 'Arial', 'Regular')\n"
            "p = layout.LayoutProfile(layout._NAME, 1, font, '12.3.0', '2.14.3', '__BUILD_ID__', '__RUNTIME_ID__')\n"
            "prov = layout._open_provider(p)\n"
            "assert prov is not None\n"
            "assert prov.basic_engine == 0\n"
            "assert hasattr(prov, 'inspect_font')\n"
            "assert hasattr(prov, 'load_font')\n"
            "assert hasattr(prov, 'audit_font')\n", NULL) == 0);
        assert(boundary());
        return 0;
    }

    if (!strcmp(argv[1], "repeated")) {
        assert(run(
            "from presentation_agent import layout\n"
            "font = layout.FontIdentity(layout._FONT_SHA256, 0, 'Arial', 'Regular')\n"
            "p = layout.LayoutProfile(layout._NAME, 1, font, '12.3.0', '2.14.3', '__BUILD_ID__', '__RUNTIME_ID__')\n"
            "p1 = layout._open_provider(p)\n"
            "p2 = layout._open_provider(p)\n"
            "p3 = layout._open_provider(p)\n"
            "assert p1 is not None and p2 is not None and p3 is not None\n", NULL) == 0);
        assert(boundary());
        return 0;
    }

    if (!strcmp(argv[1], "mismatched-profile")) {
        assert(run(
            "from presentation_agent import layout\n"
            "font = layout.FontIdentity(layout._FONT_SHA256, 0, 'Arial', 'Regular')\n"
            "wrong_p = layout.LayoutProfile(layout._NAME, 1, font, '12.3.0', '2.14.3', 'sha256:' + '99'*32, '__RUNTIME_ID__')\n"
            "try:\n"
            "    layout._open_provider(wrong_p)\n"
            "    assert False, 'mismatched profile must fail'\n"
            "except ValueError:\n"
            "    pass\n", NULL) == 0);
        assert(!boundary());
        assert(run(
            "from presentation_agent import layout\n"
            "font = layout.FontIdentity(layout._FONT_SHA256, 0, 'Arial', 'Regular')\n"
            "p = layout.LayoutProfile(layout._NAME, 1, font, '12.3.0', '2.14.3', '__BUILD_ID__', '__RUNTIME_ID__')\n"
            "try:\n"
            "    layout._open_provider(p)\n"
            "    assert False, 'must latch invalidation'\n"
            "except ValueError:\n"
            "    pass\n", NULL) == 0);
        return 0;
    }

    if (!strcmp(argv[1], "fork")) {
        pid_t child = fork(); int status;
        assert(child >= 0);
        if (!child) {
            int r = run(
                "from presentation_agent import layout\n"
                "font = layout.FontIdentity(layout._FONT_SHA256, 0, 'Arial', 'Regular')\n"
                "p = layout.LayoutProfile(layout._NAME, 1, font, '12.3.0', '2.14.3', '__BUILD_ID__', '__RUNTIME_ID__')\n"
                "try:\n"
                "    layout._open_provider(p)\n"
                "    assert False, 'fork child must reject'\n"
                "except ValueError:\n"
                "    pass\n", NULL);
            _exit(r == 0 ? 0 : 1);
        }
        assert(waitpid(child, &status, 0) == child);
        assert(WIFEXITED(status) && WEXITSTATUS(status) == 0);
        assert(boundary());
        assert(run(
            "from presentation_agent import layout\n"
            "font = layout.FontIdentity(layout._FONT_SHA256, 0, 'Arial', 'Regular')\n"
            "p = layout.LayoutProfile(layout._NAME, 1, font, '12.3.0', '2.14.3', '__BUILD_ID__', '__RUNTIME_ID__')\n"
            "assert layout._open_provider(p) is not None\n", NULL) == 0);
        return 0;
    }

    if (!strcmp(argv[1], "lease-loss")) {
        observer_failure = 2;
        assert(run(
            "from presentation_agent import layout\n"
            "font = layout.FontIdentity(layout._FONT_SHA256, 0, 'Arial', 'Regular')\n"
            "p = layout.LayoutProfile(layout._NAME, 1, font, '12.3.0', '2.14.3', '__BUILD_ID__', '__RUNTIME_ID__')\n"
            "try:\n"
            "    layout._open_provider(p)\n"
            "    assert False, 'lease loss must fail'\n"
            "except ValueError:\n"
            "    pass\n", NULL) == 0);
        assert(!boundary());
        observer_failure = 0;
        assert(run(
            "from presentation_agent import layout\n"
            "font = layout.FontIdentity(layout._FONT_SHA256, 0, 'Arial', 'Regular')\n"
            "p = layout.LayoutProfile(layout._NAME, 1, font, '12.3.0', '2.14.3', '__BUILD_ID__', '__RUNTIME_ID__')\n"
            "try:\n"
            "    layout._open_provider(p)\n"
            "    assert False, 'lease loss must latch invalidation'\n"
            "except ValueError:\n"
            "    pass\n", NULL) == 0);
        return 0;
    }

    if (!strcmp(argv[1], "sys-path-mutation")) {
        assert(run("import sys; sys.path.append('/untrusted_mutation')", NULL) == 0);
        assert(!boundary());
        assert(run(
            "from presentation_agent import layout\n"
            "font = layout.FontIdentity(layout._FONT_SHA256, 0, 'Arial', 'Regular')\n"
            "p = layout.LayoutProfile(layout._NAME, 1, font, '12.3.0', '2.14.3', '__BUILD_ID__', '__RUNTIME_ID__')\n"
            "try:\n"
            "    layout._open_provider(p)\n"
            "    assert False, 'sys.path mutation must fail'\n"
            "except ValueError:\n"
            "    pass\n", NULL) == 0);
        return 0;
    }

    if (!strcmp(argv[1], "dict-mutation")) {
        assert(run(
            "import _pa_private_bootstrap as b\n"
            "b.untrusted_field = 'mutation'\n", NULL) == 0);
        assert(!boundary());
        assert(run(
            "from presentation_agent import layout\n"
            "font = layout.FontIdentity(layout._FONT_SHA256, 0, 'Arial', 'Regular')\n"
            "p = layout.LayoutProfile(layout._NAME, 1, font, '12.3.0', '2.14.3', '__BUILD_ID__', '__RUNTIME_ID__')\n"
            "try:\n"
            "    layout._open_provider(p)\n"
            "    assert False, 'module dict mutation must fail'\n"
            "except ValueError:\n"
            "    pass\n", NULL) == 0);
        return 0;
    }

    return 1;
}
'''


@unittest.skipUnless(sys.platform == 'darwin' and sys.version_info[:2] == (3, 14)
                     and shutil.which('clang'), 'requires macOS CPython 3.14 and clang')
class NativeActivationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        parent = ROOT / 'build/phase45b-unit'
        parent.mkdir(parents=True, exist_ok=True)
        cls.work = Path(tempfile.mkdtemp(dir=parent)).resolve()

        font = layout.FontIdentity(layout._FONT_SHA256, 0, 'Arial', 'Regular')
        build_id = 'sha256:' + '01' * 32
        runtime_id = 'sha256:' + '02' * 32
        cls.profile = layout.LayoutProfile(layout._NAME, 1, font, '12.3.0', '2.14.3', build_id, runtime_id)
        profile_doc = _document(layout._descriptor(cls.profile), layout._NAMESPACE)

        declarations = []
        raw_profile = bytes.fromhex(profile_doc['bytes_hex'])
        declarations.append('static unsigned char profile_bytes[] = ' + c_bytes(raw_profile) + ';')
        declarations.append('static struct pa_provider_identity provider = {')
        declarations.append('.profile = {profile_bytes, sizeof(profile_bytes), ' +
                            c_bytes(bytes.fromhex(profile_doc['sha256'])) + '}};')

        base = Path(sys.base_prefix)
        site = Path(sys.prefix) / 'lib/python3.14/site-packages'
        src = ROOT / 'src'
        defs = [
            f'#define FRAMEWORK "{base / "Python"}"',
            f'#define STDLIB L"{base / "lib/python3.14"}"',
            f'#define DYNLIB L"{base / "lib/python3.14/lib-dynload"}"',
            f'#define SRCPATH L"{src}"',
            f'#define SITEPATH L"{site}"',
            f'#define BUILD_ID "__BUILD_ID__"',
            f'#define RUNTIME_ID "__RUNTIME_ID__"',
        ]

        launcher = (SUPPORT / 'launcher.c').read_text().replace(
            '#include "attachment_launcher.c"',
            SEAM + '\n' + '\n'.join(declarations))
        (cls.work / 'launcher.c').write_text(launcher)

        harness_src = ("\n".join(defs) + "\n" + HARNESS).replace("__BUILD_ID__", build_id).replace("__RUNTIME_ID__", runtime_id)
        (cls.work / 'harness.c').write_text(harness_src)
        cls.binary = cls.work / 'harness'
        subprocess.run(['clang', '-std=c11', '-Wall', '-Wextra', '-Werror',
                        '-Wno-deprecated-declarations',
                        '-Wno-unused-command-line-argument',
                        '-framework', 'IOKit', '-framework', 'CoreFoundation', '-lbsm',
                        '-F/Library/Frameworks', '-framework', 'Python',
                        '-I' + sysconfig.get_path('include'),
                        '-I/Library/Frameworks/Python.framework/Versions/3.14/Headers',
                        '-I' + str(cls.work),
                        '-I' + str(SUPPORT),
                        str(cls.work / 'harness.c'),
                        '-o', str(cls.binary)], check=True, capture_output=True)

    def run_case(self, case):
        subprocess.run([str(self.binary), case], check=True, timeout=15)

    def test_native_provider_activation_positive(self):
        self.run_case('valid')

    def test_native_provider_repeated_activation(self):
        self.run_case('repeated')

    def test_native_provider_no_provider_fails_closed(self):
        self.run_case('no-provider')

    def test_native_provider_mismatched_profile_latches(self):
        self.run_case('mismatched-profile')

    def test_native_provider_fork_rejection(self):
        self.run_case('fork')

    def test_native_provider_lease_loss_latches(self):
        self.run_case('lease-loss')

    def test_native_provider_sys_path_mutation_latches(self):
        self.run_case('sys-path-mutation')

    def test_native_provider_dict_mutation_latches(self):
        self.run_case('dict-mutation')


class PurePythonFailClosedTests(unittest.TestCase):
    def setUp(self):
        font = layout.FontIdentity(layout._FONT_SHA256, 0, 'Arial', 'Regular')
        self.profile = layout.LayoutProfile(
            layout._NAME, 1, font, '12.3.0', '2.14.3',
            'sha256:' + 'aa' * 32, 'sha256:' + 'bb' * 32)

    def test_ordinary_python_open_provider_fails_closed(self):
        with self.assertRaises(ValueError) as ctx:
            layout._open_provider(self.profile)
        self.assertIn('Controlled fresh-process lifecycle/build/runtime binding unavailable', str(ctx.exception))

    def test_ordinary_python_none_profile_fails_closed(self):
        with self.assertRaises(ValueError):
            layout._open_provider(None)

    def test_fake_bootstrap_module_rejected(self):
        class FakeModule:
            def _open_provider(self, desc):
                return 'fake_provider'
        original = sys.modules.get('_pa_private_bootstrap')
        try:
            sys.modules['_pa_private_bootstrap'] = FakeModule()
            with self.assertRaises(ValueError):
                layout._open_provider(self.profile)
        finally:
            if original is None:
                sys.modules.pop('_pa_private_bootstrap', None)
            else:
                sys.modules['_pa_private_bootstrap'] = original

    def test_no_public_activation_apis_exposed(self):
        for mod in (layout,):
            for name in dir(mod):
                self.assertNotIn('qualif', name.lower())
                self.assertNotIn('set_provider', name)
                self.assertNotIn('enable_provider', name)
                self.assertNotIn('activate_provider', name)

    def test_no_environment_variable_bypass(self):
        for var in ('PA_QUALIFY', 'PA_ENABLE_PROVIDER', 'PA_TRUSTED_BOOTSTRAP', 'PA_OVERRIDE'):
            with self.subTest(var=var):
                os.environ[var] = '1'
                try:
                    with self.assertRaises(ValueError):
                        layout._open_provider(self.profile)
                finally:
                    os.environ.pop(var, None)
