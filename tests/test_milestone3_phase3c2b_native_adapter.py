"""Native package consumer; synthetic attachment observations confer no trust."""
import json
import shutil
import sys
import unittest
from unittest.mock import patch

import test_milestone3_phase3c2b_attachment_launcher as support


@unittest.skipUnless(sys.platform == 'darwin' and shutil.which('clang'),
                     'requires existing macOS clang and Python headers')
class NativeAdapterTests(unittest.TestCase):
    run_case = support.AttachmentLauncherTests.run_case

    @classmethod
    def setUpClass(cls):
        harness = support.HARNESS
        harness = harness.replace('else assert(0);', r'''
    else if (!strcmp(argv[1],"package-missing")) binding.native = NULL;
    else if (!strcmp(argv[1],"package-mismatch")) { /* Python supplied changed fixture. */ }
    else if (!strcmp(argv[1],"package-tamper")) ++package[30];
    else if (!strcmp(argv[1],"package-truncated")) --native.size;
    else if (!strcmp(argv[1],"package-malformed")) {
        package[0] = '['; CC_SHA256(package,(CC_LONG)native.size,native.sha256);
    }
    else if (!strcmp(argv[1],"package-trailing")) {
        package[native.size++] = ' '; CC_SHA256(package,(CC_LONG)native.size,native.sha256);
    }
    else if (!strcmp(argv[1],"launcher-mismatch")) native.launcher = framework;
    else if (!strcmp(argv[1],"startup-outside")) {
        strcpy((char *)inventory+68+4,"/outside/launcher");
        CC_SHA256(inventory,sizeof(inventory),startup.sha256);
        memcpy(binding.inventory_sha256,startup.sha256,32);
    }
    else assert(0);''')
        harness = harness.replace('verified_load(NULL,0,NULL,0,caller_path,&checks)',
                                  'native_binding_load(NULL,0,NULL,0,&checks)')
        harness = harness.replace('verified_load(NULL,0,NULL,0,framework,&checks)',
                                  'native_binding_load(NULL,0,NULL,0,&checks)')
        harness = harness.replace('    strcpy(caller_path,framework);', r'''
    if (!strcmp(argv[1],"direct-package-missing")) {
        binding.native = NULL;
        assert(!verified_load(NULL,0,NULL,0,framework,&checks));
        assert(attachment_launch.invalid && loads == 0);
        binding.native = &native;
        assert(!verified_load(NULL,0,NULL,0,framework,&checks));
        assert(!attachment_launch_boundary());
        assert(!attachment_launch_handoff(&loads,modules,1));
        assert(attachment_launch.invalid && loads == 0);
        return 0;
    }
    strcpy(caller_path,framework);''')
        with patch.object(support, 'HARNESS', harness):
            support.AttachmentLauncherTests.setUpClass.__func__(cls)

    def test_package_consumed_before_load_and_handoff(self):
        self.run_case('valid')

    def test_direct_verified_load_missing_package_latches_before_dlopen(self):
        self.run_case('direct-package-missing')

    def test_bad_packages_latch_closed(self):
        for case in ('package-missing', 'package-tamper', 'package-truncated',
                     'package-malformed', 'package-trailing', 'launcher-mismatch',
                     'startup-outside', 'deployment', 'policy', 'pins', 'inventory',
                     'python', 'framework', 'outside', 'noncanonical', 'mount'):
            with self.subTest(case=case):
                self.run_case(case)

    def test_exact_schema_paths_pins_and_inventory_fields(self):
        path = self.work / 'package'
        original = path.read_bytes()
        changes = {
            'attachment_pin_sha256': '02' * 32,
            'deployment_sha256': '02' * 32,
            'launch_policy_sha256': '02' * 32,
            'launcher': str(self.work / 'framework'),
            'python_framework': str(self.work / 'python'),
            'python_interpreter': str(self.work / 'framework'),
            'module_paths': [str(self.work / 'modules2')],
            'protected_deployment': {}, 'startup_inventory': {},
            'kind': 'unsupported', 'unknown': True,
        }
        try:
            for field, value in changes.items():
                with self.subTest(field=field):
                    package = json.loads(original)
                    package[field] = value
                    path.write_bytes(json.dumps(package, sort_keys=True,
                                                separators=(',', ':')).encode())
                    self.run_case('package-mismatch')
            for raw in (original[:-1] + b',"kind":"duplicate"}',
                        original.replace(b'"module_paths":', b'"missing_modules":')):
                path.write_bytes(raw)
                self.run_case('package-mismatch')
        finally:
            path.write_bytes(original)

    def test_lease_process_and_replay_checks_remain_live(self):
        for case in ('retry', 'fork', 'disconnect', 'identity', 'module-mutation',
                     'handoff-path', 'handoff-handle', 'issuer', 'invalid', 'loader'):
            with self.subTest(case=case):
                self.run_case(case)
        for stage in range(1, 7):
            with self.subTest(stage=stage):
                self.run_case('callback-' + str(stage))
