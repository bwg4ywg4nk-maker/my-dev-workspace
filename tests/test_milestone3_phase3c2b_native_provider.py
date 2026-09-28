"""Real native identity/verifier code with synthetic OS and font observations.

No Python runtime is loaded. Only the frozen font's file-hash observation is
substituted; all other native artifact hashes use actual temporary fixture bytes.
"""
from hashlib import sha256
import json
import shutil
import subprocess
import sys
import sysconfig
import unittest
from unittest.mock import patch

from presentation_agent import layout
from presentation_agent._provider_identity import _document
from presentation_agent.evidence import canonical_bytes
import test_milestone3_phase3c2b_attachment_launcher as support


def c_bytes(data):
    return '{' + ','.join(str(value) for value in data) + '}'


MAIN = r'''
int main(int argc, char **argv) {
    void *handle; int positive;
    (void)&require_loader_state;
    assert(argc == 3); setup(argv[2]); native_setup();
    native.provider = &provider;
    checks.launcher = native_verify_launcher;
    checks.framework = native_verify_framework;
    checks.build_evidence = native_verify_build;
    checks.runtime_artifacts = native_verify_runtime;
    positive = !strcmp(argv[1],"valid") || !strcmp(argv[1],"lease") ||
        !strcmp(argv[1],"fork") || !strcmp(argv[1],"retry") ||
        !strcmp(argv[1],"lifecycle") || !strcmp(argv[1],"mutation") ||
        !strcmp(argv[1],"bootstrap-invalid");
    if (!strcmp(argv[1],"missing")) native.provider = NULL;
    else if (!strcmp(argv[1],"build")) ++provider.build.sha256[0];
    else if (!strcmp(argv[1],"runtime")) ++provider.runtime.sha256[0];
    else if (!strcmp(argv[1],"adapter")) ++provider.adapter_sha256[0];
    else if (!strcmp(argv[1],"font")) ++provider.font_sha256[0];
    else if (!strcmp(argv[1],"profile")) ++provider.profile.sha256[0];
    else if (!strcmp(argv[1],"partial")) --provider.count;
    else if (!strcmp(argv[1],"inventory")) ++inventory[0];
    else if (!strcmp(argv[1],"policy")) ++binding.policy_sha256[0];
    else if (!strcmp(argv[1],"artifact")) ++artifacts[0].sha256[0];
    else if (!strcmp(argv[1],"package")) ++package[30];
    else if (!strcmp(argv[1],"missing-document")) provider.build.bytes = NULL;
    else if (!strcmp(argv[1],"direct")) {
        assert(!native_verify_build() && attachment_launch.invalid);
        assert(!native_binding_load(NULL,0,NULL,0,&checks)); return 0;
    } else if (!positive && strcmp(argv[1],"changed-file") &&
               strcmp(argv[1],"extra-module")) assert(0);
    handle = native_binding_load(NULL,0,NULL,0,&checks);
    if (!positive) {
        assert(!handle && attachment_launch.invalid && !loads);
        assert(!native_verify_launcher() && !native_verify_build() && !native_verify_runtime());
        assert(!native_binding_load(NULL,0,NULL,0,&checks)); return 0;
    }
    assert(handle && loads == 1 && native_verify_launcher() &&
           native_verify_framework(framework) && native_verify_build() && native_verify_runtime());
    assert(!lifecycle.attempted && !lifecycle.ready); /* Never bootstrap/activate. */
    if (!strcmp(argv[1],"valid")) return 0;
    if (!strcmp(argv[1],"fork")) {
        pid_t child = fork(); int status; assert(child >= 0);
        if (!child) {
            assert(!native_verify_build() && attachment_launch.invalid);
            assert(!native_binding_load(NULL,0,NULL,0,&checks)); _exit(0);
        }
        assert(waitpid(child,&status,0) == child && WIFEXITED(status) && !WEXITSTATUS(status));
        assert(native_verify_runtime()); return 0;
    }
    if (!strcmp(argv[1],"lease")) failure = 2;
    if (!strcmp(argv[1],"lifecycle")) ++pid_offset;
    if (!strcmp(argv[1],"bootstrap-invalid")) assert(!invalidate());
    if (!strcmp(argv[1],"mutation")) ++provider.profile.sha256[0];
    if (!strcmp(argv[1],"retry")) assert(!native_binding_load(NULL,0,NULL,0,&checks));
    assert(!native_verify_runtime() && attachment_launch.invalid);
    failure = pid_offset = 0;
    if (!strcmp(argv[1],"mutation")) --provider.profile.sha256[0];
    assert(!native_verify_build() && !native_binding_load(NULL,0,NULL,0,&checks));
    assert(loads == 1); return 0;
}
'''


@unittest.skipUnless(sys.platform == 'darwin' and shutil.which('clang'),
                     'requires existing macOS clang and Python headers')
class NativeProviderTests(unittest.TestCase):
    run_case = support.AttachmentLauncherTests.run_case

    @classmethod
    def setUpClass(cls):
        font_hash = bytes.fromhex(layout._FONT_SHA256)
        observer = support.OBSERVER.replace(
            'return CC_SHA256(data,(CC_LONG)n,hash) != NULL;',
            'if (strlen(path) > 5 && !strcmp(path+strlen(path)-5,"/font")) {\n'
            'static const unsigned char h[32] = ' + c_bytes(font_hash) + ';\n'
            'memcpy(hash,h,32); return 1; }\n'
            'return CC_SHA256(data,(CC_LONG)n,hash) != NULL;')
        with patch.object(support, 'OBSERVER', observer):
            support.AttachmentLauncherTests.setUpClass.__func__(cls)
        root = cls.work
        paths = {
            'build:audit-schema': 'audit', 'build:freetype-static': 'freetype',
            'build:imaging': 'modules/imaging', 'build:imagingft': 'modules/imagingft',
            'build:measurement-adapter': 'modules/adapter.py',
            'font': 'font', 'native:bootstrap': 'python', 'native:launcher': 'python',
            'native:python-interpreter': 'python', 'native:python-framework': 'framework',
            'native:loader': 'loader', 'native:c-runtime': 'c-runtime',
            'native:imaging': 'modules/imaging', 'native:imagingft': 'modules/imagingft',
            'module:0:adapter.py': 'modules/adapter.py',
            'module:0:imaging': 'modules/imaging', 'module:0:imagingft': 'modules/imagingft',
        }
        for name in paths.values():
            if not (root / name).exists():
                (root / name).write_text(name)
        records = [[role, str(root / name), layout._FONT_SHA256 if role == 'font' else
                    sha256((root / name).read_bytes()).hexdigest()]
                   for role, name in sorted(paths.items())]
        build = {'kind': 'pillow-basic-build-v1', 'build_configuration_sha256': '01' * 32,
                 'artifacts': [[r[0][6:], r[2]] for r in records if r[0].startswith('build:')]}
        runtime = dict(kind='pillow-basic-runtime-v1', python_implementation='CPython',
            python_version=[3, 14, 0], python_abi='cpython-314', os='Darwin', os_release='fixture',
            architecture='x86_64', byteorder='little', pointer_bits=64,
            native_runtime_artifacts=sorted([['deployment-evidence', '02' * 32]] +
                [[r[0][7:], r[2]] for r in records if r[0].startswith('native:')]))
        build_doc, runtime_doc = _document(build), _document(runtime)
        profile = layout.LayoutProfile(layout._NAME, 1,
            layout.FontIdentity(layout._FONT_SHA256, 0, 'Arial', 'Regular'),
            '12.3.0', '2.14.3', 'sha256:' + build_doc['sha256'], 'sha256:' + runtime_doc['sha256'])
        identity = dict(kind='protected-provider-identity-v1', artifacts=records,
            adapter_sha256=next(r[2] for r in records if r[0] == 'build:measurement-adapter'),
            build_evidence_sha256='01' * 32, deployment_document_sha256='02' * 32,
            build_manifest=build_doc, runtime_manifest=runtime_doc,
            font_sha256=layout._FONT_SHA256,
            profile=_document(layout._descriptor(profile), layout._NAMESPACE))
        package = json.loads((root / 'package').read_bytes())
        package.update(kind='trusted-admin-deployment-binding-v2', provider_identity=identity)
        (root / 'package').write_bytes(canonical_bytes(package))
        declarations = []
        docs = {}
        for name, key in (('build', 'build_manifest'), ('runtime', 'runtime_manifest'), ('profile', 'profile')):
            doc = identity[key]
            raw = bytes.fromhex(doc['bytes_hex'])
            declarations.append('static unsigned char ' + name + '_bytes[] = ' + c_bytes(raw) + ';')
            docs[name] = '{' + name + '_bytes,sizeof(' + name + '_bytes),' + c_bytes(bytes.fromhex(doc['sha256'])) + '}'
        declarations.append('static struct pa_provider_artifact artifacts[] = {')
        for role, path, digest in records:
            declarations.append('{' + json.dumps(role) + ',' + json.dumps(path) + ',' + c_bytes(bytes.fromhex(digest)) + '},')
        declarations.append('};\nstatic struct pa_provider_identity provider = {')
        for field in ('adapter_sha256', 'build_evidence_sha256', 'font_sha256', 'deployment_document_sha256'):
            declarations.append('.' + field + '=' + c_bytes(bytes.fromhex(identity[field])) + ',')
        declarations.extend('.' + name + '=' + value + ',' for name, value in docs.items())
        declarations.append('.artifacts=artifacts,.count=sizeof(artifacts)/sizeof(*artifacts)};')
        source = (root / 'harness.c').read_text()
        source = source[:source.index('int main(int argc, char **argv) {')] + MAIN
        source = source.replace('stages == 4', 'stages == 0').replace(
            'static struct pa_native_binding native;', '\n'.join(declarations) + '\nstatic struct pa_native_binding native;')
        (root / 'harness.c').write_text(source)
        result = subprocess.run(['clang', '-std=c11', '-Wall', '-Wextra', '-Werror',
            '-Wno-deprecated-declarations', '-I' + sysconfig.get_path('include'),
            '-I' + str(support.SUPPORT), str(root / 'harness.c'),
            '-framework', 'IOKit', '-framework', 'CoreFoundation', '-lbsm',
            '-o', str(cls.binary)], capture_output=True, text=True)
        if result.returncode:
            raise AssertionError(result.stderr)

    def test_concrete_verifiers_without_provider_initialization(self):
        self.run_case('valid')

    def test_missing_partial_mismatched_native_inputs_latch(self):
        for case in ('missing', 'build', 'runtime', 'adapter', 'font', 'profile',
                     'partial', 'inventory', 'policy', 'artifact', 'direct', 'package', 'missing-document'):
            with self.subTest(case=case):
                self.run_case(case)

    def test_lease_lifecycle_fork_retry_and_restored_mutation_reject(self):
        for case in ('lease', 'lifecycle', 'fork', 'retry', 'mutation', 'bootstrap-invalid'):
            with self.subTest(case=case):
                self.run_case(case)

    def test_actual_file_changes_reject(self):
        path = self.work / 'audit'
        original = path.read_bytes()
        try:
            path.write_bytes(b'changed artifact')
            self.run_case('changed-file')
        finally:
            path.write_bytes(original)

    def test_unlisted_module_rejects(self):
        # Move a fixture in/out so all listed module files remain present.
        original = self.work / 'unlisted.py'
        original.write_text('unlisted module')
        extra = self.work / 'modules/unlisted.py'
        original.rename(extra)
        try:
            self.run_case('extra-module')
        finally:
            extra.rename(original)
