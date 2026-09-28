/* Private compiled deployment binding, never an environment/Python input.
 * The deployment adapter must authenticate these exact paths/digests and the
 * existing artifact callbacks together. Production installs no deployment.
 * Evidence files are canonical bytes produced by the existing offline tools;
 * this layer binds their identities, not their semantic verification callbacks. */
#include <wchar.h>
#include "attachment_observer.c"

/* Independently reviewed, compiled input; never populated from argv/environ.
 * The digest authenticates exact package bytes, not a caller's JSON claims. */
struct pa_native_binding {
    const unsigned char *bytes;
    size_t size;
    unsigned char sha256[32];
    const char *launcher;
};
struct pa_attachment_binding {
    const char *deployment, *policy, *python, *framework;
    const wchar_t *const *modules;
    size_t module_count;
    unsigned char deployment_sha256[32], policy_sha256[32];
    unsigned char python_sha256[32], framework_sha256[32], inventory_sha256[32];
    const struct pa_native_binding *native;
};
static struct {
    int attempted, invalid, loaded, bound;
    unsigned char binding_sha256[32];
    struct pa_process_identity identity;
    const struct pa_checks *checks;
    void *handle;
} attachment_launch;

static int attachment_launch_reject(void) {
    attachment_launch.invalid = 1;
    return pa_attachment_observer_reject();
}
/* All deployment paths must resolve on the observed mount, without symlinks
 * or nested mounts. The retained administrative lease protects last use. */
static int attachment_launch_path(const char *path, int directory,
                                  const unsigned char *expected) {
    const struct pa_attachment_record *r = &pa_attachment_observer.source.record;
    size_t root = strlen((const char *)r->mount_path), n;
    struct stat s; struct statfs fs;
    struct pa_attachment_stamp stamp;
    unsigned char digest[32];
    char canonical[1024] = {0};
    int fd, ok;
    if (!path || (n = strlen(path)) >= sizeof(canonical)) return 0;
    memcpy(canonical,path,n);
    if (!pa_attachment_text((const unsigned char *)canonical,sizeof(canonical),1) ||
        strncmp(path,(const char *)r->mount_path,root) || path[root] != '/') return 0;
    fd = pa_attachment_open_admin(path,directory);
    if (fd < 0) return 0;
    ok = !fstat(fd,&s) && !fstatfs(fd,&fs) &&
        (uint64_t)s.st_dev == pa_attachment_uint(r->mount_dev,8) &&
        !strcmp(fs.f_mntonname,(const char *)r->mount_path) &&
        !strcmp(fs.f_mntfromname,(const char *)r->mount_source) &&
        fs.f_flags == pa_attachment_uint(r->mount_flags,8) &&
        (uint32_t)fs.f_fsid.val[0] == pa_attachment_uint(r->mount_fsid,4) &&
        (uint32_t)fs.f_fsid.val[1] == pa_attachment_uint(r->mount_fsid+4,4);
    close(fd);
    return ok && (directory || (expected && pa_attachment_nonzero(expected,32) &&
        pa_attachment_file(path,digest,&stamp,NULL,NULL) && !memcmp(digest,expected,32)));
}
/* Retain the exact adapter configuration across every callback and handoff.
 * Pointer equality alone would miss in-place path/order or pin mutations. */
static int attachment_launch_fingerprint(const struct pa_attachment_binding *b) {
    CC_SHA256_CTX ctx; unsigned char digest[32]; size_t i, n;
    const char *paths[] = {b->deployment,b->policy,b->python,b->framework};
    if (!attachment_launch.checks->startup || !CC_SHA256_Init(&ctx) ||
        !CC_SHA256_Update(&ctx,attachment_launch.checks,sizeof(struct pa_checks)) ||
        !CC_SHA256_Update(&ctx,attachment_launch.checks->startup,sizeof(struct pa_startup_binding)) ||
        !CC_SHA256_Update(&ctx,b,sizeof(*b)) ||
        !b->modules || !b->module_count || b->module_count > 64) return 0;
    for (i = 0; i < 4; ++i) {
        if (!paths[i] || (n = strnlen(paths[i],1024)) == 1024 ||
            !CC_SHA256_Update(&ctx,paths[i],(CC_LONG)n+1)) return 0;
    }
    for (i = 0; i < b->module_count; ++i) {
        if (!b->modules[i]) return 0;
        for (n = 0; n < 1024 && b->modules[i][n]; ++n) {}
        if (n == 1024 || !CC_SHA256_Update(&ctx,b->modules[i],
                                          (CC_LONG)((n+1)*sizeof(wchar_t)))) return 0;
    }
    if (b->native && (!b->native->launcher ||
        (n = strnlen(b->native->launcher,1024)) == 1024 ||
        !CC_SHA256_Update(&ctx,b->native,sizeof(*b->native)) ||
        !CC_SHA256_Update(&ctx,b->native->launcher,(CC_LONG)n+1))) return 0;
    if (!CC_SHA256_Final(digest,&ctx)) return 0;
    if (attachment_launch.bound)
        return !memcmp(digest,attachment_launch.binding_sha256,32);
    memcpy(attachment_launch.binding_sha256,digest,32);
    attachment_launch.bound = 1;
    return 1;
}
#include "deployment_binding.c"
static int attachment_launch_binding(void) {
    const struct pa_checks *c = attachment_launch.checks;
    const struct pa_attachment_binding *b = c ? c->attachment : NULL;
    const struct pa_attachment_record *r = &pa_attachment_observer.source.record;
    unsigned char digest[32]; struct pa_attachment_stamp stamp;
    char pins[16384], expected[90]; size_t size = sizeof(pins), i, j;
    if (!b || !b->native || !attachment_launch_fingerprint(b) || !c->startup || !c->startup->bytes ||
        c->startup->size < PA_STARTUP_HEADER ||
        c->startup->size > PA_STARTUP_HEADER + PA_MAX_IMAGES * PA_STARTUP_IMAGE + 256 * PA_STARTUP_MAPPING ||
        memcmp(b->deployment_sha256,r->deployment_sha256,32) ||
        memcmp(c->startup->deployment_sha256,r->deployment_sha256,32) ||
        memcmp(c->startup->bytes+8,r->deployment_sha256,32) ||
        memcmp(c->startup->sha256,b->inventory_sha256,32) ||
        !CC_SHA256(c->startup->bytes,(CC_LONG)c->startup->size,digest) ||
        memcmp(digest,b->inventory_sha256,32) ||
        !pa_attachment_file(PA_ATTACHMENT_PINS,digest,&stamp,pins,&size) ||
        memcmp(digest,r->pin_sha256,32) || !pa_attachment_pins(r,pins,size)) return 0;
    /* pa_attachment_pins already enforces the complete canonical schema. */
    strcpy(expected,"\"launch_policy_sha256\":\"");
    for (i = 0; i < 32; ++i) snprintf(expected+24+2*i,3,"%02x",b->policy_sha256[i]);
    expected[88] = '"'; expected[89] = 0;
    if (size >= sizeof(pins)) return 0;
    pins[size] = 0;
    if (!strstr(pins,expected) ||
        !attachment_launch_path(b->deployment,0,b->deployment_sha256) ||
        !attachment_launch_path(b->policy,0,b->policy_sha256) ||
        !attachment_launch_path(b->python,0,b->python_sha256) ||
        !attachment_launch_path(b->framework,0,b->framework_sha256) ||
        !b->modules || !b->module_count || b->module_count > 64) return 0;
    for (i = 0; i < b->module_count; ++i) {
        char path[1024];
        if (!b->modules[i]) return 0;
        for (j = 0; j < sizeof(path); ++j) {
            wchar_t ch = b->modules[i][j];
            if (ch < 0 || ch > 127) return 0;
            path[j] = (char)ch;
            if (!ch) break;
        }
        if (j == sizeof(path) || !attachment_launch_path(path,1,NULL)) return 0;
    }
    return native_binding_verify(b,pins,size);
}
static int attachment_launch_boundary(void) {
    if (!attachment_launch.attempted || attachment_launch.invalid ||
        !process_identity_matches(&attachment_launch.identity) ||
        !pa_attachment_observer_check() || !attachment_launch_binding() ||
        !process_identity_matches(&attachment_launch.identity))
        return attachment_launch_reject();
    return 1;
}
static int attachment_launch_handoff(void *handle, const wchar_t *const *paths, size_t count) {
    const struct pa_attachment_binding *b;
    size_t i;
    if (!attachment_launch.loaded || handle != attachment_launch.handle ||
        !attachment_launch_boundary()) return attachment_launch_reject();
    b = attachment_launch.checks->attachment;
    if (!paths || count != b->module_count) return attachment_launch_reject();
    for (i = 0; i < count; ++i)
        if (!paths[i] || wcscmp(paths[i],b->modules[i])) return attachment_launch_reject();
    return 1;
}
