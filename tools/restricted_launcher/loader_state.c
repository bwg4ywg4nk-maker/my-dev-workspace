/* Native pre-Python verification. Evidence is never qualification. */
#ifdef __APPLE__
#include <stdbool.h>
#include <mach/mach.h>
#include <mach-o/dyld_images.h>

#define PA_MAX_IMAGES 512
#define PA_IMAGE_PATH 4096
struct pa_loader_image {
    uintptr_t address, modification;
    char path[PA_IMAGE_PATH];
};
struct pa_loader_observation {
    pid_t pid;
    uintptr_t dyld_address, cache_address, cache_slide, initial_count;
    uint64_t timestamp;
    unsigned char cache_uuid[16];
    char dyld_path[PA_IMAGE_PATH];
    uint32_t count;
    struct pa_loader_image images[PA_MAX_IMAGES];
};

static int loader_path(char *out, const char *in) {
    size_t n;
    if (!in || in[0] != '/') return 0;
    n = strnlen(in, PA_IMAGE_PATH);
    if (!n || n == PA_IMAGE_PATH) return 0;
    memcpy(out, in, n + 1);
    return 1;
}

static int loader_snapshot(struct pa_loader_observation *out) {
    struct task_dyld_info task;
    mach_msg_type_number_t size = TASK_DYLD_INFO_COUNT;
    const struct dyld_all_image_infos *live;
    struct dyld_all_image_infos before, after;
    uint32_t i, j;
    unsigned char uuid_bits = 0;
    memset(out, 0, sizeof(*out));
    if (task_info(mach_task_self(), TASK_DYLD_INFO, (task_info_t)&task,
                  &size) != KERN_SUCCESS || size != TASK_DYLD_INFO_COUNT ||
        task.all_image_info_format != TASK_DYLD_ALL_IMAGE_INFO_64 ||
        task.all_image_info_size < sizeof(before) || !task.all_image_info_addr)
        return 0;
    live = (const struct dyld_all_image_infos *)(uintptr_t)task.all_image_info_addr;
    memcpy(&before, live, sizeof(before));
    /* Reject unsupported/translated/detached or actively changing states.
     * initialImageCount is only a consistency check, not exec attestation. */
    if (before.version < 17 || !before.infoArray || !before.infoArrayCount ||
        before.infoArrayCount > PA_MAX_IMAGES ||
        before.initialImageCount != before.infoArrayCount ||
        before.processDetachedFromSharedRegion || !before.libSystemInitialized ||
        before.errorMessage || before.errorKind || before.terminationFlags ||
        before.jitInfo || before.aotInfoCount || before.aotSharedCacheBaseAddress ||
        !before.dyldImageLoadAddress || !before.sharedCacheBaseAddress ||
        !loader_path(out->dyld_path, before.dyldPath)) return 0;
    for (i = 0; i < 16; ++i) uuid_bits |= before.sharedCacheUUID[i];
    if (!uuid_bits) return 0;
    out->pid = getpid();
    out->dyld_address = (uintptr_t)before.dyldImageLoadAddress;
    out->cache_address = before.sharedCacheBaseAddress;
    out->cache_slide = before.sharedCacheSlide;
    out->initial_count = before.initialImageCount;
    out->timestamp = before.infoArrayChangeTimestamp;
    memcpy(out->cache_uuid, before.sharedCacheUUID, 16);
    out->count = before.infoArrayCount;
    for (i = 0; i < out->count; ++i) {
        const struct dyld_image_info *image = &before.infoArray[i];
        out->images[i].address = (uintptr_t)image->imageLoadAddress;
        out->images[i].modification = image->imageFileModDate;
        if (!out->images[i].address ||
            !loader_path(out->images[i].path, image->imageFilePath)) return 0;
        for (j = 0; j < i; ++j)
            if (out->images[j].address == out->images[i].address ||
                !strcmp(out->images[j].path, out->images[i].path)) return 0;
    }
    memcpy(&after, live, sizeof(after));
    return !memcmp(&before, &after, sizeof(before)) && out->pid == getpid();
}

#include "hardened_runtime.c"
#include "startup_inventory.c"

static int require_loader_state(const struct pa_startup_binding *binding,
                                const struct pa_process_identity *identity) {
    struct pa_loader_observation *first = NULL, *second = NULL;
    struct pa_startup_binding pinned;
    unsigned char *copy = NULL;
    int ok = 0;
    if (!process_identity_matches(identity) || !binding || !binding->bytes ||
        binding->size < PA_STARTUP_HEADER || binding->size > 4 * 1024 * 1024) return 0;
    pinned = *binding;
    copy = malloc(pinned.size);
    first = calloc(1, sizeof(*first));
    second = calloc(1, sizeof(*second));
    if (!copy || !first || !second) goto done;
    memcpy(copy, pinned.bytes, pinned.size);
    pinned.bytes = copy;
    ok = loader_snapshot(first) && first->pid == identity->pid &&
        process_identity_matches(identity) &&
        startup_inventory(&pinned, first, identity->cdhash) &&
        process_identity_matches(identity) &&
        loader_snapshot(second) && second->pid == identity->pid &&
        !memcmp(first, second, sizeof(*first)) && process_identity_matches(identity);
 done:
    free(copy); free(first); free(second);
    return ok;
}
#else
struct pa_startup_binding;
struct pa_process_identity { int unused; };
static int pin_process_identity(struct pa_process_identity *identity) {
    (void)identity; return 0;
}
static int process_identity_matches(const struct pa_process_identity *identity) {
    (void)identity; return 0;
}
static int require_loader_state(const struct pa_startup_binding *binding,
                                const struct pa_process_identity *identity) {
    (void)binding; (void)identity;
    return 0;
}
#endif
