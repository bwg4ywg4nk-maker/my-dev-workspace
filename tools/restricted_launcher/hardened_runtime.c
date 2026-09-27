/* XNU csops ABI: bsd/sys/codesign.h and osfmk/kern/cs_blobs.h.
 * Read-only operations only; never try to repair or relax a running process.
 * These constants are not exported by the public macOS SDK. Unsupported
 * kernels/operations reject rather than falling back to codesign output. */
#include <stdint.h>
extern int csops(pid_t, unsigned int, void *, size_t);
#define PA_CS_REQUIRED (0x1u | 0x100u | 0x200u | 0x1000u | 0x10000u | 0x2000000u | 0x20000000u)
#define PA_CS_FORBIDDEN (0x4u | 0x8u | 0x20u | 0x8000u | 0x20000u | 0x1000000u | 0x10000000u | 0x80000000u)

static int hardened_runtime(unsigned char cdhash[20]) {
    uint32_t before = 0, after = 0;
    unsigned char xml[8] = {0}, der[8] = {0};
    static const unsigned char zero[20] = {0};
    /* Ad-hoc identity is verified offline and bound by CDHash: CS_OPS_STATUS
     * does not consistently report CS_ADHOC on supported macOS kernels.
     * STATUS, XML/DER entitlements, CDHASH. A nonempty entitlement blob either
     * fills this header or returns ERANGE. Both outcomes reject. */
    if (csops(getpid(), 0, &before, sizeof(before)) ||
        (before & PA_CS_REQUIRED) != PA_CS_REQUIRED ||
        (before & PA_CS_FORBIDDEN) ||
        (before & ~(PA_CS_REQUIRED | 0x2u | 0x10u | 0x400u | 0x800u | 0x2000u)) || !(before & (0x10u | 0x2000u)) ||
        csops(getpid(), 7, xml, sizeof(xml)) ||
        csops(getpid(), 16, der, sizeof(der)) ||
        memcmp(xml, zero, sizeof(xml)) || memcmp(der, zero, sizeof(der)) ||
        csops(getpid(), 5, cdhash, 20) || !memcmp(cdhash, zero, 20) ||
        csops(getpid(), 0, &after, sizeof(after)) || before != after) return 0;
    return 1;
}

/* One identity is retained for the entire pre-load boundary, never refreshed
 * after callbacks or loader observations. */
struct pa_process_identity {
    pid_t pid;
    unsigned char cdhash[20];
};
static inline int process_identity_matches(const struct pa_process_identity *identity) {
    unsigned char cdhash[20];
    return identity && identity->pid == getpid() && hardened_runtime(cdhash) &&
        identity->pid == getpid() && !memcmp(identity->cdhash, cdhash, 20);
}
static inline int pin_process_identity(struct pa_process_identity *identity) {
    identity->pid = getpid();
    return hardened_runtime(identity->cdhash) && process_identity_matches(identity);
}
