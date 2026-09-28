"""Phase-3 mechanics with the local runtime; not deployment qualification."""
from pathlib import Path
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import unittest

from attachment_launcher_test_support import STUB

ROOT = Path(__file__).resolve().parents[1]

HARNESS = r'''
#include <assert.h>
#include <sys/wait.h>
#define main production_main
#include "launcher.c"
#undef main
int main(int argc, char **argv) {
    const wchar_t *paths[] = {STDLIB, DYNLIB};
    void *handle = dlopen(FRAMEWORK, RTLD_NOW | RTLD_LOCAL);
    assert(argc == 2 && handle);
    if (!strcmp(argv[1], "bad-path")) {
        const wchar_t *bad[] = {L"relative"};
        assert(!isolated_bootstrap(handle, bad, 1));
        assert(!isolated_bootstrap(handle, paths, 2));
        return 0;
    }
    assert(isolated_bootstrap(handle, paths, 2));
    assert(boundary());
    if (!strcmp(argv[1], "config")) {
        int (*run)(const char *, PyCompilerFlags *);
        *(void **)(&run) = dlsym(handle, "PyRun_SimpleStringFlags");
        assert(run && run(
            "import sys\n"
            "assert sys.version_info[:2] == (3, 14)\n"
            "assert sys.flags.isolated and sys.flags.ignore_environment\n"
            "assert sys.flags.no_site and sys.flags.no_user_site\n"
            "assert sys.flags.safe_path and sys.dont_write_bytecode\n"
            "assert 'site' not in sys.modules\n"
            "assert len(sys.path) == 2 and '' not in sys.path\n"
            "import _pa_private_bootstrap as b\n"
            "assert b._entry() is False\n", NULL) == 0);
        assert(boundary());
    } else if (!strcmp(argv[1], "path")) {
        int (*run)(const char *, PyCompilerFlags *);
        *(void **)(&run) = dlsym(handle, "PyRun_SimpleStringFlags");
        assert(run("import sys; sys.path.append('/untrusted')", NULL) == 0);
        assert(!boundary());
        assert(run("sys.path.pop()", NULL) == 0);
        assert(!boundary());
    } else if (!strcmp(argv[1], "fork")) {
        pid_t child = fork(); int status;
        assert(child >= 0);
        if (!child) {
            assert(!boundary() && lifecycle.invalid);
            assert(!isolated_bootstrap(handle, paths, 2));
            _exit(0);
        }
        assert(waitpid(child, &status, 0) == child);
        assert(WIFEXITED(status) && WEXITSTATUS(status) == 0);
        assert(boundary());
    } else if (!strcmp(argv[1], "environment")) {
        assert(setenv("FT2_PHASE3_MUTATION", "1", 1) == 0);
        assert(!boundary());
        unsetenv("FT2_PHASE3_MUTATION");
        assert(!boundary());
    } else if (!strcmp(argv[1], "callable")) {
        PyObject *dict = pa_PyModule_GetDict(lifecycle.module);
        assert(pa_PyDict_SetItemString(dict, "_entry", lifecycle.module) == 0);
        assert(!boundary());
        assert(pa_PyDict_SetItemString(dict, "_entry", lifecycle.entry) == 0);
        assert(!boundary());
    } else if (!strcmp(argv[1], "module")) {
        assert(pa_PyDict_SetItemString(pa_PyImport_GetModuleDict(),
                                     "_pa_private_bootstrap", lifecycle.entry) == 0);
        assert(!boundary());
        assert(pa_PyDict_SetItemString(pa_PyImport_GetModuleDict(),
                                     "_pa_private_bootstrap", lifecycle.module) == 0);
        assert(!boundary());
    } else if (!strcmp(argv[1], "retry")) {
        assert(!isolated_bootstrap(handle, paths, 2));
        assert(!boundary());
    } else return 1;
    return 0;
}
'''


@unittest.skipUnless(sys.platform == 'darwin' and sys.version_info[:2] == (3, 14)
                     and shutil.which('clang'), 'requires existing macOS CPython 3.14 and clang')
class BootstrapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        parent = ROOT / 'build/phase3-unit'
        parent.mkdir(parents=True, exist_ok=True)
        work = Path(tempfile.mkdtemp(dir=parent))
        source = work / 'harness.c'
        (work / 'launcher.c').write_text(
            (ROOT / 'tools/restricted_launcher/launcher.c').read_text().replace(
                '#include "attachment_launcher.c"', STUB))
        cls.binary = work / 'harness'
        base = Path(sys.base_prefix)
        source.write_text(
            f'#define FRAMEWORK "{base / "Python"}"\n'
            f'#define STDLIB L"{base / "lib/python3.14"}"\n'
            f'#define DYNLIB L"{base / "lib/python3.14/lib-dynload"}"\n' + HARNESS)
        subprocess.run(['clang', '-std=c11', '-Wall', '-Wextra', '-Werror',
                        '-I' + sysconfig.get_path('include'),
                        '-I' + str(ROOT / 'tools/restricted_launcher'),
                        str(source), '-o', str(cls.binary)], check=True, capture_output=True)

    def run_case(self, case):
        subprocess.run([str(self.binary), case], check=True,
                       env={'PYTHONPATH': '/untrusted', 'PYTHONHOME': '/untrusted'})

    def test_isolated_configuration_and_fixed_entry(self): self.run_case('config')
    def test_search_path_mutation_latches(self): self.run_case('path')
    def test_fork_rejection(self): self.run_case('fork')
    def test_environment_mutation_latches(self): self.run_case('environment')
    def test_callable_mutation_latches(self): self.run_case('callable')
    def test_module_mutation_latches(self): self.run_case('module')
    def test_no_requalification(self): self.run_case('retry')
    def test_invalid_paths_latch(self): self.run_case('bad-path')
