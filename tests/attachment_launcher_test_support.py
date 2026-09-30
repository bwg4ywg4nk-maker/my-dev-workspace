"""Test-only attachment seam for pre-existing launcher/bootstrap mechanics."""
STUB = r'''
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
static int attachment_launch_reject(void) { attachment_launch.invalid = 1; return 0; }
static int pa_attachment_observer_open(void) { return 1; }
static int attachment_launch_boundary(void) { return 1; }
static int attachment_launch_handoff(void *h, const wchar_t *const *p, size_t n) {
    (void)h; (void)p; (void)n; return 1;
}
static const struct pa_provider_identity *native_provider_identity(void) { return NULL; }
'''
