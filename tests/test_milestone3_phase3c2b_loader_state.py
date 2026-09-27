"""Native loader observations and fail-closed pre-entry trust boundary."""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

HARNESS = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <mach/mach.h>
#include <mach-o/dyld_images.h>
static struct dyld_all_image_infos infos;
static struct dyld_image_info images[2];
static int unavailable;
static kern_return_t fake_task_info(mach_port_t task, task_flavor_t flavor,
                                    task_info_t output,
                                    mach_msg_type_number_t *size) {
    struct task_dyld_info *out = (struct task_dyld_info *)output;
    (void)task;
    assert(flavor == TASK_DYLD_INFO && *size == TASK_DYLD_INFO_COUNT);
    if (unavailable) return KERN_FAILURE;
    memset(out, 0, sizeof(*out));
    out->all_image_info_addr = (uintptr_t)&infos;
    out->all_image_info_size = sizeof(infos);
    out->all_image_info_format = TASK_DYLD_ALL_IMAGE_INFO_64;
    return KERN_SUCCESS;
}
#define task_info fake_task_info
#include "loader_state.c"
#undef task_info
static void fixture(void) {
    memset(&infos, 0, sizeof(infos));
    memset(images, 0, sizeof(images));
    infos.version = 17;
    infos.infoArray = images;
    infos.infoArrayCount = infos.initialImageCount = 1;
    infos.libSystemInitialized = true;
    infos.dyldImageLoadAddress = (const struct mach_header *)0x1000;
    infos.dyldPath = "/usr/lib/dyld";
    infos.sharedCacheBaseAddress = 0x2000;
    infos.sharedCacheUUID[0] = 1;
    images[0].imageLoadAddress = (const struct mach_header *)0x3000;
    images[0].imageFilePath = "/verified/launcher";
}
int main(void) {
    struct pa_loader_observation *out = calloc(1, sizeof(*out));
    assert(out);
    fixture();
    assert(loader_snapshot(out));
    assert(out->pid == getpid() && out->count == 1);
    assert(out->cache_uuid[0] == 1 && out->cache_address == 0x2000);
    assert(!strcmp(out->images[0].path, "/verified/launcher"));
    /* Clean observations cannot waive missing pre-entry/deployment proof. */
    assert(!require_loader_state(NULL, NULL));
    unavailable = 1; assert(!loader_snapshot(out)); unavailable = 0;
#define REJECT(change) fixture(); change; assert(!loader_snapshot(out))
    REJECT(infos.version = 16);
    REJECT(infos.infoArray = NULL);
    REJECT(infos.infoArrayCount = PA_MAX_IMAGES + 1);
    REJECT(infos.initialImageCount = 2);
    REJECT(infos.processDetachedFromSharedRegion = true);
    REJECT(infos.libSystemInitialized = false);
    REJECT(infos.errorKind = 1);
    REJECT(infos.terminationFlags = 1);
    REJECT(infos.jitInfo = (void *)1);
    REJECT(infos.aotInfoCount = 1);
    REJECT(infos.sharedCacheBaseAddress = 0);
    REJECT(infos.sharedCacheUUID[0] = 0);
    REJECT(infos.dyldPath = "relative");
    REJECT(images[0].imageFilePath = NULL);
    REJECT(images[0].imageLoadAddress = NULL);
    fixture(); images[1] = images[0];
    infos.infoArrayCount = infos.initialImageCount = 2;
    assert(!loader_snapshot(out));
    /* An extra injected image is observational data, never admission. */
    images[1].imageFilePath = "/injected.dylib";
    images[1].imageLoadAddress = (const struct mach_header *)0x4000;
    assert(loader_snapshot(out));
    assert(!require_loader_state(NULL, NULL));
    free(out);
    return 0;
}
'''


@unittest.skipUnless(sys.platform == 'darwin' and shutil.which('clang'),
                     'requires existing macOS clang')
class LoaderStateTests(unittest.TestCase):
    def test_native_observations_never_authorize_unverified_exec(self):
        parent = ROOT / 'build/loader-state-unit'
        parent.mkdir(parents=True, exist_ok=True)
        work = Path(tempfile.mkdtemp(dir=parent))
        source = work / 'harness.c'
        source.write_text(HARNESS)
        binary = work / 'harness'
        subprocess.run(['clang', '-std=c11', '-Wall', '-Wextra', '-Werror',
                        '-I' + str(ROOT / 'tools/restricted_launcher'),
                        str(source), '-o', str(binary)],
                       check=True, capture_output=True)
        subprocess.run([str(binary)], check=True)
