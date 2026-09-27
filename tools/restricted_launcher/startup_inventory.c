/* Private binary evidence format emitted by _startup_inventory.py. Neither
 * its bytes nor its pins may come from environment/Python/caller assertions.
 * The deployment owner must independently protect and authenticate both pins.
 * Production installs no binding in this phase. */
#include <CommonCrypto/CommonDigest.h>
#include <mach/mach_vm.h>
#include <fcntl.h>
#include <sys/stat.h>

struct pa_startup_binding {
    const unsigned char *bytes;
    size_t size;
    unsigned char sha256[32], deployment_sha256[32];
};
#define PA_STARTUP_HEADER 68u
#define PA_STARTUP_IMAGE 4172u
#define PA_STARTUP_MAPPING 56u

static uint32_t startup_u32(const unsigned char *p) {
    return (uint32_t)p[0] | (uint32_t)p[1] << 8 |
           (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}
static uint64_t startup_u64(const unsigned char *p) {
    return (uint64_t)startup_u32(p) | (uint64_t)startup_u32(p + 4) << 32;
}
static int startup_read(uint64_t address, void *out, size_t size) {
    mach_vm_size_t actual = 0;
    return address && size <= UINT64_MAX - address &&
        mach_vm_read_overwrite(mach_task_self(), address, size,
                              (mach_vm_address_t)out, &actual) == KERN_SUCCESS &&
        actual == size;
}
static int startup_memory_hash(uint64_t address, uint64_t size,
                               const unsigned char *expected,
                               int maximum, int initial) {
    unsigned char buffer[16384], digest[32];
    CC_SHA256_CTX context;
    if (!size || size > UINT64_MAX - address || !CC_SHA256_Init(&context)) return 0;
    while (size) {
        size_t amount = size < sizeof(buffer) ? (size_t)size : sizeof(buffer);
        if (maximum >= 0) {
            mach_vm_address_t start = address;
            mach_vm_size_t extent = 0;
            vm_region_basic_info_data_64_t info;
            mach_msg_type_number_t count = VM_REGION_BASIC_INFO_COUNT_64;
            mach_port_t object = MACH_PORT_NULL;
            kern_return_t status = mach_vm_region(mach_task_self(), &start, &extent,
                VM_REGION_BASIC_INFO_64, (vm_region_info_t)&info, &count, &object);
            if (object != MACH_PORT_NULL) mach_port_deallocate(mach_task_self(), object);
            if (status != KERN_SUCCESS || start > address || !extent ||
                extent > UINT64_MAX - start || start + extent <= address ||
                info.protection != initial || info.max_protection != maximum) return 0;
            if (amount > start + extent - address) amount = (size_t)(start + extent - address);
        }
        if (!startup_read(address, buffer, amount) ||
            !CC_SHA256_Update(&context, buffer, (CC_LONG)amount)) return 0;
        address += amount; size -= amount;
    }
    return CC_SHA256_Final(digest, &context) && !memcmp(digest, expected, 32);
}
static int startup_file_hash(const char *path, const unsigned char *expected) {
    int fd = open(path, O_RDONLY | O_NOFOLLOW);
    struct stat before, after, named;
    unsigned char buffer[16384], digest[32];
    CC_SHA256_CTX context;
    ssize_t amount;
    int ok = 0;
    if (fd < 0) return 0;
    if (fstat(fd, &before) || !S_ISREG(before.st_mode) || !CC_SHA256_Init(&context)) goto done;
    while ((amount = read(fd, buffer, sizeof(buffer))) > 0)
        if (!CC_SHA256_Update(&context, buffer, (CC_LONG)amount)) goto done;
    if (amount < 0 || fstat(fd, &after) || lstat(path, &named) ||
        before.st_dev != after.st_dev || before.st_ino != after.st_ino ||
        before.st_size != after.st_size ||
        memcmp(&before.st_mtimespec, &after.st_mtimespec, sizeof(before.st_mtimespec)) ||
        memcmp(&before.st_ctimespec, &after.st_ctimespec, sizeof(before.st_ctimespec)) ||
        after.st_dev != named.st_dev || after.st_ino != named.st_ino ||
        !S_ISREG(named.st_mode)) goto done;
    ok = CC_SHA256_Final(digest, &context) && !memcmp(digest, expected, 32);
 done:
    close(fd);
    return ok;
}

static int startup_inventory(const struct pa_startup_binding *binding,
                              const struct pa_loader_observation *state,
                              const unsigned char cdhash[20]) {
    unsigned char digest[32];
    const unsigned char *data, *record, *maps;
    uint32_t count, map_count, i, j, launcher_count = 0, loader_count = 0;
    size_t matched = 0;
    unsigned char used[PA_MAX_IMAGES] = {0};
    if (!binding || !binding->bytes || binding->size < PA_STARTUP_HEADER ||
        binding->size > PA_STARTUP_HEADER + PA_MAX_IMAGES * PA_STARTUP_IMAGE + 256 * PA_STARTUP_MAPPING ||
        !CC_SHA256(binding->bytes, (CC_LONG)binding->size, digest) ||
        memcmp(digest, binding->sha256, 32)) return 0;
    data = binding->bytes;
    if (memcmp(data, "PAEXEC01", 8) || memcmp(data + 8, binding->deployment_sha256, 32) ||
        memcmp(data + 40, cdhash, 20)) return 0;
    count = startup_u32(data + 60); map_count = startup_u32(data + 64);
    if (count < 2 || count > PA_MAX_IMAGES || !map_count || map_count > 256 ||
        state->count > PA_MAX_IMAGES ||
        binding->size != PA_STARTUP_HEADER + count * PA_STARTUP_IMAGE + map_count * PA_STARTUP_MAPPING)
        return 0;
    maps = data + PA_STARTUP_HEADER + count * PA_STARTUP_IMAGE;
    for (i = 0; i < count; ++i) {
        uint64_t address = 0, unslid;
        uint32_t header[8], kind, command_size;
        const char *path;
        record = data + PA_STARTUP_HEADER + i * PA_STARTUP_IMAGE;
        kind = startup_u32(record); path = (const char *)record + 4;
        if (kind > 2 || path[0] != '/' || !memchr(path, 0, PA_IMAGE_PATH)) return 0;
        for (j = 0; j < i; ++j)
            if (!strcmp(path, (const char *)data + PA_STARTUP_HEADER + j * PA_STARTUP_IMAGE + 4)) return 0;
        for (j = 0; j < state->count; ++j) {
            if (!strcmp(path, state->images[j].path)) {
                if (used[j]) return 0;
                used[j] = 1; ++matched;
                address = state->images[j].address;
            }
        }
        if (kind == 1) {
            ++loader_count;
            if (strcmp(path, state->dyld_path) ||
                (address && address != state->dyld_address)) return 0;
            address = state->dyld_address;
        }
        if (!address || !startup_read(address, header, sizeof(header)) ||
            header[0] != 0xfeedfacf || header[5] > 1024 * 1024 - 32) return 0;
        command_size = header[5] + 32;
        unslid = startup_u64(record + 4164);
        if (kind == 2) {
            int contained = 0;
            if (!startup_memory_hash(address, command_size, record + 4132, -1, -1) ||
                !unslid || unslid > UINT64_MAX - state->cache_slide ||
                address != unslid + state->cache_slide) return 0;
            for (j = 0; j < map_count; ++j) {
                const unsigned char *m = maps + j * PA_STARTUP_MAPPING;
                uint64_t start = startup_u64(m), size = startup_u64(m + 8);
                if (size <= UINT64_MAX - start && unslid >= start &&
                    unslid <= start + size && command_size <= start + size - unslid) contained = 1;
            }
            if (!contained) return 0;
        } else {
            /* Standalone records bind all immutable __TEXT bytes, including
             * their load commands, not UUID/path agreement alone. */
            if (unslid < command_size || unslid > 64 * 1024 * 1024 ||
                !startup_memory_hash(address, unslid, record + 4132, -1, -1) ||
                !startup_file_hash(path, record + 4100)) return 0;
            if (kind == 0) {
                ++launcher_count;
                if (header[3] != 2 || address != state->images[0].address) return 0;
            } else if (header[3] != 7) return 0;
        }
    }
    if (launcher_count != 1 || loader_count != 1 || matched != state->count) return 0;
    { unsigned char uuid[16];
      uint64_t base = startup_u64(maps);
      if (base > UINT64_MAX - state->cache_slide ||
          state->cache_address != base + state->cache_slide ||
          state->cache_address > UINT64_MAX - 88 ||
          !startup_read(state->cache_address + 88, uuid, sizeof(uuid)) ||
          memcmp(uuid, state->cache_uuid, sizeof(uuid))) return 0;
    }
    for (i = 0; i < map_count; ++i) {
        const unsigned char *m = maps + i * PA_STARTUP_MAPPING;
        uint64_t start = startup_u64(m), size = startup_u64(m + 8);
        uint32_t maximum = startup_u32(m + 16), initial = startup_u32(m + 20);
        if ((maximum != 1 && maximum != 5) || initial != maximum ||
            start > UINT64_MAX - state->cache_slide ||
            !startup_memory_hash(start + state->cache_slide, size, m + 24,
                                 (int)maximum, (int)initial)) return 0;
    }
    return 1;
}
