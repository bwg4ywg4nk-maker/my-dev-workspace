/* Restricted native launcher. Python APIs are resolved only after verified load. */
#include <dlfcn.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#ifdef __APPLE__
#include <sys/sysctl.h>
#endif

#define PA_MAX_BYTES (1024 * 1024)
#define PA_MAX_ENV 4096

struct pa_pair { const char *name, *value; };
/* Private, compiled deployment seam; never supplied by Python or environment.
 * Each verifier must bind actual artifacts to immutable deployment evidence.
 * Framework verification includes the exact absolute path, byte identity,
 * dependencies and protection against substitution before dlopen. */
struct pa_startup_binding;
struct pa_attachment_binding;
struct pa_checks {
    int (*launcher)(void);
    int (*framework)(const char *);
    int (*build_evidence)(void);
    int (*runtime_artifacts)(void);
    const struct pa_startup_binding *startup;
    const struct pa_attachment_binding *attachment;
};

static unsigned char upper(unsigned char c) {
    return c >= 'a' && c <= 'z' ? (unsigned char)(c - 'a' + 'A') : c;
}
static int prefix(const char *s, size_t n, const char *p) {
    size_t i, m = strlen(p);
    if (n < m) return 0;
    for (i = 0; i < m; ++i) if (upper((unsigned char)s[i]) != (unsigned char)p[i]) return 0;
    return 1;
}
static int admit(char *const *env, size_t count,
                 const struct pa_pair *allow, size_t allowed) {
    size_t i, j;
    if (count > PA_MAX_ENV || (count && !env) || (allowed && !allow)) return 0;
    for (i = 0; i < count; ++i) {
        const char *eq;
        size_t n;
        int matched = 0;
        if (!env[i] || !(eq = strchr(env[i], '=')) || eq == env[i]) return 0;
        n = (size_t)(eq - env[i]);
        if (prefix(env[i], n, "FREETYPE_") || prefix(env[i], n, "FT2_") ||
            prefix(env[i], n, "DYLD_") || prefix(env[i], n, "LD_") ||
            prefix(env[i], n, "__XPC_DYLD_")) return 0;
        for (j = 0; j < n; ++j) {
            unsigned char c = (unsigned char)env[i][j];
            if (!((c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') ||
                  c == '_' || (j && c >= '0' && c <= '9'))) return 0;
        }
        for (j = 0; j < i; ++j)
            if (!strncmp(env[j], env[i], n) && env[j][n] == '=') return 0;
        for (j = 0; j < allowed; ++j)
            if (strlen(allow[j].name) == n && !memcmp(allow[j].name, env[i], n) &&
                !strcmp(allow[j].value, eq + 1)) matched = 1;
        if (!matched) return 0;
    }
    return 1;
}

/* KERN_PROCARGS2: argc, executable path, NUL padding, argc arguments,
 * then original exec environment ending at its empty entry. Remaining kernel
 * data is not environment (and need not be zero). Never consult libc environ.
 * Missing/truncated/ambiguous records are rejected. */
static int original_record(char *buf, size_t size, char **env, size_t *count) {
    int argc, i;
    char *p, *end, *nul;
    *count = 0;
    if (size <= sizeof(argc) || size > PA_MAX_BYTES) return 0;
    memcpy(&argc, buf, sizeof(argc));
    if (argc < 1 || argc > PA_MAX_ENV) return 0;
    p = buf + sizeof(argc); end = buf + size;
    nul = memchr(p, 0, (size_t)(end - p));
    if (!nul || nul == p) return 0;
    p = nul + 1;
    /* Padding and empty leading arguments have identical encodings. Without
     * a separate argv offset, skipping NULs can consume arguments and hide
     * environment entries. Reject this ambiguous boundary instead. */
    if (p == end || !*p) return 0;
    for (i = 0; i < argc; ++i) {
        if (p == end || !(nul = memchr(p, 0, (size_t)(end - p)))) return 0;
        p = nul + 1;
    }
    while (p < end && *p) {
        if (*count == PA_MAX_ENV || !(nul = memchr(p, 0, (size_t)(end - p)))) return 0;
        env[(*count)++] = p;
        p = nul + 1;
    }
    if (p == end) return 0;
    return 1;
}

#include "loader_state.c"
#include "attachment_launcher.c"

static void *verified_load(char *const *env, size_t count,
                           const struct pa_pair *allow, size_t allowed,
                           const char *path, const struct pa_checks *checks) {
    struct pa_process_identity identity;
    const char *framework_path;
    void *handle;
    if (attachment_launch.attempted || attachment_launch.invalid) {
        attachment_launch_reject(); return NULL;
    }
    attachment_launch.attempted = 1;
    if (!pin_process_identity(&identity) ||
        !require_loader_state(checks ? checks->startup : NULL, &identity) ||
        !process_identity_matches(&identity)) goto reject;
    if (!admit(env, count, allow, allowed) || !path || path[0] != '/' ||
        !checks || !checks->launcher || !checks->framework ||
        !checks->build_evidence || !checks->runtime_artifacts ||
        !checks->attachment || !checks->attachment->framework ||
        strcmp(path,checks->attachment->framework)) goto reject;
    attachment_launch.identity = identity;
    attachment_launch.checks = checks;
    if (!pa_attachment_observer_open() || !attachment_launch_boundary()) goto reject;
    framework_path = checks->attachment->framework;
    if (!checks->launcher() || !attachment_launch_boundary() || !process_identity_matches(&identity) ||
        !checks->framework(framework_path) || !attachment_launch_boundary() || !process_identity_matches(&identity) ||
        !checks->build_evidence() || !attachment_launch_boundary() || !process_identity_matches(&identity) ||
        !checks->runtime_artifacts() || !attachment_launch_boundary() || !process_identity_matches(&identity) ||
        !require_loader_state(checks->startup, &identity) ||
        !process_identity_matches(&identity)) goto reject;
    if (!attachment_launch_boundary()) goto reject;
    handle = dlopen(framework_path, RTLD_NOW | RTLD_LOCAL);
    if (!handle || !attachment_launch_boundary()) goto reject;
    attachment_launch.handle = handle;
    attachment_launch.loaded = 1;
    return handle;
 reject:
    attachment_launch_reject();
    return NULL;
}

#include "bootstrap.c"

#ifdef PA_NATIVE_BINDING_ADAPTER
/* Private native entry: package absence cannot fall back to the older seam.
 * verified_load owns the one-shot lifecycle and lease at every boundary. */
static void *native_binding_load(char *const *env, size_t count,
                                const struct pa_pair *allow, size_t allowed,
                                const struct pa_checks *checks) {
    struct pa_process_identity identity;
    if (!pin_process_identity(&identity) ||
        !checks || !checks->attachment || !checks->attachment->native) {
        attachment_launch_reject(); return NULL;
    }
    return verified_load(env,count,allow,allowed,checks->attachment->framework,checks);
}
#endif

int main(void) {
#ifdef __APPLE__
    int mib[] = {CTL_KERN, KERN_PROCARGS2, (int)getpid()};
    size_t size = PA_MAX_BYTES, count = PA_MAX_ENV + 1;
    char *buf = malloc(size), *env[PA_MAX_ENV];
    /* No deployment verifier or framework is authorized in Phase 2. */
    const struct pa_checks closed = {0};
    void *handle = NULL;
    if (!buf || sysctl(mib, 3, buf, &size, NULL, 0) != 0 ||
        !original_record(buf, size, env, &count)) count = PA_MAX_ENV + 1;
    /* Always enter native verification, even with no authorized deployment.
     * Missing inventory denies here; it never authorizes provider loading. */
#ifdef PA_NATIVE_BINDING_ADAPTER
    handle = native_binding_load(env, count, NULL, 0, &closed);
#else
    handle = verified_load(env, count, NULL, 0, NULL, &closed);
#endif
    free(buf);
    if (handle) {
        /* No verified deployment search paths are authorized yet. */
        (void)isolated_bootstrap(handle, NULL, 0);
        /* Process-lifetime Python references: never unload a live runtime. */
    }
#endif
    fputs("restricted launcher: deployment unavailable; qualification denied\n", stderr);
    return 78;
}
