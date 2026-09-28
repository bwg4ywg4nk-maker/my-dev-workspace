"""Native integration only; mocked OS/issuer observations never qualify a deployment.

The reviewed observer's authentication/replay/fork tests remain in attachment.py.
These tests exercise real launcher ordering, evidence binding, and handoff with
controlled observer outcomes and file/mount observations, without provisioning.
"""
from pathlib import Path
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SUPPORT = ROOT / 'tools/restricted_launcher'

OBSERVER = r'''
#include "attachment_protocol.h"
static struct { struct pa_attachment_source source; } pa_attachment_observer;
static int opens, polls, failure, fail_at, loads, stages, pid_offset, mutate;
static char root[1024], pins[16384];
static int pa_attachment_observer_reject(void) { return 0; }
int pa_attachment_observer_open(void) { ++opens; return failure != 1; }
int pa_attachment_observer_check(void) { ++polls; return polls != fail_at && failure != 2; }
static int fixture_open(const char *path, int directory) {
    return open(path,O_RDONLY|O_NOFOLLOW|(directory ? O_DIRECTORY : 0));
}
static int fixture_file(const char *path, unsigned char hash[32],
                        struct pa_attachment_stamp *stamp, char *out, size_t *size) {
    unsigned char data[16384]; ssize_t n; int fd;
    memset(stamp,0,sizeof(*stamp));
    if (!strcmp(path,PA_ATTACHMENT_PINS)) {
        n = (ssize_t)strlen(pins); memcpy(data,pins,(size_t)n);
    } else {
        fd = open(path,O_RDONLY|O_NOFOLLOW); if (fd < 0) return 0;
        n = read(fd,data,sizeof(data)); close(fd); if (n < 0) return 0;
    }
    if (out) { if (!size || *size < (size_t)n) return 0;
        memcpy(out,data,(size_t)n); *size = (size_t)n; }
    return CC_SHA256(data,(CC_LONG)n,hash) != NULL;
}
static int fixture_fs(int fd, struct statfs *fs) {
    if (fstatfs(fd,fs)) return -1;
    strcpy(fs->f_mntonname,root); return 0;
}
#define pa_attachment_open_admin fixture_open
#define pa_attachment_file fixture_file
#define fstatfs fixture_fs
'''

HARNESS = r'''
#include <assert.h>
#include <sys/wait.h>
static unsigned char inventory[PA_STARTUP_HEADER];
static struct pa_startup_binding startup;
static struct pa_attachment_binding binding;
static struct pa_checks checks;
static wchar_t module[1024], other_module[1024];
static const wchar_t *modules[1] = {module};
static char deployment[1024], policy[1024], python[1024], framework[1024];
static char caller_path[1024];
static int mutate_path_at;
static pid_t fixture_pid(void) { return getpid()+pid_offset; }
static int fixture_csops(pid_t p, unsigned int op, void *out, size_t size) {
    (void)p; memset(out,0,size);
    if (op == 0) *(uint32_t *)out = 0x22013301u;
    if (op == 5) memset(out,1,size);
    return 0;
}
static int fixture_loader(const struct pa_startup_binding *b,
                          const struct pa_process_identity *p) {
    (void)b; (void)p; return failure != 3;
}
static void *fixture_load(const char *p, int flags) {
    assert(opens == 1 && polls >= 6 && stages == 4);
    assert(!strcmp(p,framework) && flags == (RTLD_NOW|RTLD_LOCAL));
    ++loads;
    if (mutate == 5) failure = 2;
    if (mutate == 6) ++pid_offset;
    return &loads;
}
static int step(void) {
    ++stages;
    if (stages == mutate_path_at) strcpy(caller_path,"/unverified/Python");
    if (mutate == stages) failure = 2;
    return 1;
}
static int framework_check(const char *p) { assert(!strcmp(p,framework)); return step(); }
static void hex(char out[65], const unsigned char bytes[32]) {
    size_t i; for (i = 0; i < 32; ++i) snprintf(out+2*i,3,"%02x",bytes[i]);
}
static void setup(const char *directory) {
    struct pa_attachment_record *r = &pa_attachment_observer.source.record;
    struct stat st; struct statfs fs; struct pa_attachment_stamp stamp;
    char dep[65], pol[65], one[65]; unsigned char ones[32];
    strcpy(root,directory);
    snprintf(deployment,sizeof(deployment),"%s/deployment",root);
    snprintf(policy,sizeof(policy),"%s/policy",root);
    snprintf(python,sizeof(python),"%s/python",root);
    snprintf(framework,sizeof(framework),"%s/framework",root);
    assert(mbstowcs(module,root,1024) != (size_t)-1);
    wcscat(module,L"/modules");
    wcscpy(other_module,module); wcscat(other_module,L"2");
    binding.deployment = deployment; binding.policy = policy;
    binding.python = python; binding.framework = framework;
    binding.modules = modules; binding.module_count = 1;
    assert(fixture_file(deployment,binding.deployment_sha256,&stamp,NULL,NULL));
    assert(fixture_file(policy,binding.policy_sha256,&stamp,NULL,NULL));
    assert(fixture_file(python,binding.python_sha256,&stamp,NULL,NULL));
    assert(fixture_file(framework,binding.framework_sha256,&stamp,NULL,NULL));
    memcpy(inventory,"PAEXEC01",8); memcpy(inventory+8,binding.deployment_sha256,32);
    startup.bytes = inventory; startup.size = sizeof(inventory);
    memcpy(startup.deployment_sha256,binding.deployment_sha256,32);
    CC_SHA256(inventory,sizeof(inventory),startup.sha256);
    memcpy(binding.inventory_sha256,startup.sha256,32);
    memcpy(r->deployment_sha256,binding.deployment_sha256,32);
    strcpy((char *)r->mount_path,root); strcpy((char *)r->backing_path,"/admin/image.dmg");
    memset(ones,1,32); memcpy(r->backing_sha256,ones,32);
    assert(!stat(root,&st) && !statfs(root,&fs));
    pa_attachment_put(r->mount_dev,8,(uint64_t)st.st_dev);
    pa_attachment_put(r->mount_flags,8,fs.f_flags);
    pa_attachment_put(r->mount_fsid,4,(uint32_t)fs.f_fsid.val[0]);
    pa_attachment_put(r->mount_fsid+4,4,(uint32_t)fs.f_fsid.val[1]);
    strcpy((char *)r->mount_source,fs.f_mntfromname);
    hex(dep,binding.deployment_sha256); hex(pol,binding.policy_sha256); hex(one,ones);
    snprintf(pins,sizeof(pins),"{\"backing_file\":\"/admin/image.dmg\",\"backing_sha256\":\"%s\","
        "\"build_sha256\":\"%s\",\"deployment_sha256\":\"%s\",\"inputs_sha256\":\"%s\","
        "\"kind\":\"trusted-admin-readonly-image-v1\",\"launch_policy_sha256\":\"%s\",\"root\":\"%s\"}",
        one,one,dep,one,pol,root);
    CC_SHA256(pins,(CC_LONG)strlen(pins),r->pin_sha256);
    checks = (struct pa_checks){step,framework_check,step,step,&startup,&binding};
}
int main(int argc, char **argv) {
    void *h; int success = 0;
    assert(argc == 3); setup(argv[2]);
    strcpy(caller_path,framework);
    if (!strcmp(argv[1],"valid") || !strcmp(argv[1],"retry") ||
        !strcmp(argv[1],"handoff-path") || !strcmp(argv[1],"handoff-handle") ||
        !strcmp(argv[1],"disconnect") || !strcmp(argv[1],"fork") ||
        !strcmp(argv[1],"module-mutation") || !strcmp(argv[1],"identity")) success = 1;
    else if (!strncmp(argv[1],"path-mutation-",14)) {
        mutate_path_at = atoi(argv[1]+14); success = 1;
    }
    else if (!strcmp(argv[1],"missing")) checks.attachment = NULL;
    else if (!strcmp(argv[1],"missing-inventory")) checks.startup = NULL;
    else if (!strcmp(argv[1],"issuer")) failure = 1;
    else if (!strcmp(argv[1],"invalid")) failure = 2;
    else if (!strcmp(argv[1],"loader")) failure = 3;
    else if (!strcmp(argv[1],"deployment")) ++binding.deployment_sha256[0];
    else if (!strcmp(argv[1],"policy")) ++binding.policy_sha256[0];
    else if (!strcmp(argv[1],"pins")) ++pa_attachment_observer.source.record.pin_sha256[0];
    else if (!strcmp(argv[1],"inventory")) ++inventory[0];
    else if (!strcmp(argv[1],"inventory-deployment")) ++startup.deployment_sha256[0];
    else if (!strcmp(argv[1],"python")) ++binding.python_sha256[0];
    else if (!strcmp(argv[1],"framework")) ++binding.framework_sha256[0];
    else if (!strcmp(argv[1],"outside")) binding.python = "/outside/python";
    else if (!strcmp(argv[1],"noncanonical")) wcscat(module,L"/../modules");
    else if (!strcmp(argv[1],"mount")) ++pa_attachment_observer.source.record.mount_dev[0];
    else if (!strncmp(argv[1],"callback-",9)) mutate = atoi(argv[1]+9);
    else if (!strncmp(argv[1],"boundary-",9)) fail_at = atoi(argv[1]+9);
    else assert(0);
    h = verified_load(NULL,0,NULL,0,caller_path,&checks);
    if (!success) {
        assert(!h && attachment_launch.invalid && loads == (mutate >= 5 || fail_at == 7));
        failure = fail_at = mutate = 0;
        assert(!verified_load(NULL,0,NULL,0,framework,&checks));
        assert(!attachment_launch_handoff(&loads,modules,1));
        return 0;
    }
    assert(h && loads == 1 && attachment_launch_handoff(h,modules,1));
    if (mutate_path_at) {
        assert(!strcmp(caller_path,"/unverified/Python"));
        assert(attachment_launch_boundary()); return 0;
    }
    if (!strcmp(argv[1],"valid")) { assert(attachment_launch_boundary()); return 0; }
    if (!strcmp(argv[1],"fork")) {
        pid_t child = fork(); int status; assert(child >= 0);
        if (!child) { assert(!attachment_launch_handoff(h,modules,1)); _exit(0); }
        assert(waitpid(child,&status,0) == child && WIFEXITED(status) && !WEXITSTATUS(status));
        assert(attachment_launch_handoff(h,modules,1)); return 0;
    }
    if (!strcmp(argv[1],"retry")) assert(!verified_load(NULL,0,NULL,0,framework,&checks));
    if (!strcmp(argv[1],"handoff-path")) {
        const wchar_t *bad[] = {other_module}; assert(!attachment_launch_handoff(h,bad,1));
    }
    if (!strcmp(argv[1],"handoff-handle")) assert(!attachment_launch_handoff(&stages,modules,1));
    if (!strcmp(argv[1],"disconnect")) failure = 2;
    if (!strcmp(argv[1],"module-mutation")) modules[0] = other_module;
    if (!strcmp(argv[1],"identity")) ++pid_offset;
    assert(!attachment_launch_boundary());
    failure = pid_offset = 0; modules[0] = module;
    assert(!attachment_launch_boundary() && !attachment_launch_handoff(h,modules,1));
    assert(loads == 1 && opens == 1);
    return 0;
}
'''


@unittest.skipUnless(sys.platform == 'darwin' and shutil.which('clang'),
                     'requires existing macOS clang and Python headers')
class AttachmentLauncherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        parent = ROOT / 'build/attachment-launcher-unit'
        parent.mkdir(parents=True, exist_ok=True)
        cls.work = Path(tempfile.mkdtemp(dir=parent)).resolve()
        for name in ('deployment', 'policy', 'python', 'framework'):
            (cls.work / name).write_text(name)
        for name in ('modules', 'modules2'):
            (cls.work / name).mkdir()
        integration = (SUPPORT / 'attachment_launcher.c').read_text().replace(
            '#include "attachment_observer.c"', OBSERVER)
        (cls.work / 'attachment_launcher.c').write_text(integration + '\n'
            '#undef pa_attachment_open_admin\n#undef pa_attachment_file\n#undef fstatfs\n')
        launcher = (SUPPORT / 'launcher.c').read_text().replace(
            '#include "loader_state.c"',
            '#include "attachment_protocol.h"\n'
            'static pid_t fixture_pid(void);\n'
            'static int fixture_csops(pid_t, unsigned int, void *, size_t);\n'
            '#define getpid fixture_pid\n#define csops fixture_csops\n'
            '#include "loader_state.c"\n'
            'static int fixture_loader(const struct pa_startup_binding *, const struct pa_process_identity *);\n'
            '#define require_loader_state fixture_loader')
        (cls.work / 'launcher.c').write_text(launcher)
        (cls.work / 'harness.c').write_text(
            '#include <dlfcn.h>\nstatic void *fixture_load(const char *, int);\n'
            '#define dlopen fixture_load\n#define main production_main\n'
            '#include "launcher.c"\n#undef main\n#undef getpid\n'
            '#undef csops\n#undef require_loader_state\n#undef dlopen\n' + HARNESS.replace(
                'assert(argc == 3);', '(void)&require_loader_state; assert(argc == 3);'))
        cls.binary = cls.work / 'harness'
        result = subprocess.run([
            'clang', '-std=c11', '-Wall', '-Wextra', '-Werror',
            '-Wno-deprecated-declarations', '-I' + sysconfig.get_path('include'),
            '-I' + str(SUPPORT), str(cls.work / 'harness.c'),
            '-framework', 'IOKit', '-framework', 'CoreFoundation', '-lbsm',
            '-o', str(cls.binary)], capture_output=True, text=True)
        if result.returncode:
            raise AssertionError(result.stderr)

    def run_case(self, case):
        result = subprocess.run([str(self.binary), case, str(self.work)],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, case + ': ' + result.stdout + result.stderr)

    def test_success_retains_one_observer_and_exact_handoff(self):
        self.run_case('valid')

    def test_callback_mutation_cannot_redirect_framework_load(self):
        for stage in range(1, 5):
            with self.subTest(stage=stage):
                self.run_case('path-mutation-' + str(stage))

    def test_missing_mismatched_and_invalid_binding_denies_before_load(self):
        for case in ('missing', 'missing-inventory', 'issuer', 'invalid', 'loader',
                     'deployment', 'policy', 'pins', 'inventory', 'inventory-deployment',
                     'python', 'framework', 'outside', 'noncanonical', 'mount'):
            with self.subTest(case=case): self.run_case(case)

    def test_observer_failures_at_every_load_boundary_latch(self):
        for prefix, count in (('callback-', 6), ('boundary-', 7)):
            for index in range(1, count + 1):
                with self.subTest(case=prefix + str(index)):
                    self.run_case(prefix + str(index))

    def test_handoff_cannot_rebind_reconnect_or_inherit(self):
        for case in ('retry', 'handoff-path', 'handoff-handle', 'disconnect',
                     'fork', 'module-mutation', 'identity'):
            with self.subTest(case=case): self.run_case(case)
