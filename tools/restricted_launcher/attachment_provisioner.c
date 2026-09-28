/* Native issuer component, intentionally not a privileged installer/daemon.
 * A trusted single-threaded administrative host calls open(), explicitly admits
 * kernel audit tokens, then calls pump(). There is no network admission API,
 * automatic admission, subprocess, Python, or provider entrypoint. See the
 * provisioning obligations in attachment_protocol.h. Run in a dedicated
 * process; one global session, no reset. Existing socket/marker files reject
 * rather than being removed. Administrative recovery is external. */
#include "attachment_protocol.h"

struct pa_attachment_admission {
    unsigned char recipient[32], challenge[32], lease[32];
    uint64_t sequence;
    int consumed, fd;
    struct pa_attachment_sender_endpoint sender;
};
static struct {
    int attempted, invalid, listener;
    unsigned char identity[32];
    struct pa_attachment_source source;
    size_t count;
    size_t challenge_count;
    unsigned char challenges[PA_ATTACHMENT_MAX_CHALLENGES][32];
    struct pa_attachment_admission admissions[PA_ATTACHMENT_MAX_LEASES];
} pa_attachment_issuer = {.listener = -1};

static int pa_attachment_issuer_reject(void) {
    size_t i;
    pa_attachment_issuer.invalid = 1;
    if (pa_attachment_issuer.listener >= 0) {
        close(pa_attachment_issuer.listener); pa_attachment_issuer.listener = -1;
    }
    for (i = 0; i < pa_attachment_issuer.count; ++i) {
        if (pa_attachment_issuer.admissions[i].fd >= 0)
            close(pa_attachment_issuer.admissions[i].fd);
        pa_attachment_issuer.admissions[i].fd = -1;
        pa_attachment_sender_close(&pa_attachment_issuer.admissions[i].sender);
    }
    return 0;
}
static int pa_attachment_issuer_identity(void) {
    unsigned char self[32];
    if (pa_attachment_issuer.invalid || !pa_attachment_issuer.attempted ||
        !pa_attachment_self(self) || memcmp(self,pa_attachment_issuer.identity,32))
        return pa_attachment_issuer_reject();
    return 1;
}
static int pa_attachment_issuer_boundary(void) {
    if (!pa_attachment_issuer_identity() ||
        !pa_attachment_source_current(&pa_attachment_issuer.source) ||
        !pa_attachment_issuer_identity() ||
        !pa_attachment_observe(&pa_attachment_issuer.source.record) ||
        !pa_attachment_issuer_identity())
        return pa_attachment_issuer_reject();
    return 1;
}
/* Distinguish process generations independently of mutable credentials. */
static int pa_attachment_same_generation(const unsigned char a[32], const unsigned char b[32]) {
    return !memcmp(a+20,b+20,4) && !memcmp(a+28,b+28,4);
}
static int pa_attachment_claim_session(int dir, const unsigned char session[32]) {
    char name[96]; size_t i; int marker, ok;
    memcpy(name,"attachment-used-",16);
    for (i = 0; i < 32; ++i) snprintf(name+16+2*i,3,"%02x",session[i]);
    marker = openat(dir,name,O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC,0600);
    if (marker < 0) return 0;
    ok = !fsync(marker) && !fsync(dir); close(marker); return ok;
}
int pa_attachment_issuer_open(void) {
    struct sockaddr_un address; int dir = -1, socket_fd = -1;
    if (pa_attachment_issuer.attempted || pa_attachment_issuer.invalid)
        return pa_attachment_issuer_reject();
    pa_attachment_issuer.attempted = 1;
    if (getuid() || geteuid() || !pa_attachment_self(pa_attachment_issuer.identity) ||
        !pa_attachment_load(&pa_attachment_issuer.source) ||
        !pa_attachment_issuer_boundary()) goto fail;
    dir = pa_attachment_open_admin(PA_ATTACHMENT_DIR,1);
    if (dir < 0) goto fail;
    /* Persistent one-shot marker: a crash or reboot cannot restart this
     * session, even if an operator removes the old socket. Never unlink it. */
    if (!pa_attachment_claim_session(dir,pa_attachment_issuer.source.record.session)) goto fail;
    close(dir); dir = -1;
    socket_fd = socket(AF_UNIX,SOCK_STREAM,0);
    if (socket_fd < 0 || !pa_attachment_socket_options(socket_fd)) goto fail;
    memset(&address,0,sizeof(address)); address.sun_family = AF_UNIX;
    memcpy(address.sun_path,PA_ATTACHMENT_SOCKET,sizeof(PA_ATTACHMENT_SOCKET));
    address.sun_len = (unsigned char)SUN_LEN(&address);
    /* Parent protection authenticates this endpoint. The endpoint may be
     * connectable by users, but only explicitly admitted kernel tokens lease. */
    if (bind(socket_fd,(struct sockaddr *)&address,address.sun_len) ||
        chmod(PA_ATTACHMENT_SOCKET,0666) || listen(socket_fd,PA_ATTACHMENT_MAX_LEASES)) goto fail;
    pa_attachment_issuer.listener = socket_fd; socket_fd = -1;
    return pa_attachment_issuer_boundary();
 fail:
    if (socket_fd >= 0) close(socket_fd);
    if (dir >= 0) close(dir);
    return pa_attachment_issuer_reject();
}
int pa_attachment_issuer_admit(const unsigned char recipient[32]) {
    size_t i;
    if (!pa_attachment_issuer_identity() || getuid() || geteuid() ||
        !recipient || !pa_attachment_issuer_boundary() ||
        !pa_attachment_uint(recipient+20,4) || !pa_attachment_uint(recipient+28,4) ||
        pa_attachment_issuer.count == PA_ATTACHMENT_MAX_LEASES) return 0;
    for (i = 0; i < pa_attachment_issuer.count; ++i)
        if (pa_attachment_same_generation(recipient,pa_attachment_issuer.admissions[i].recipient)) return 0;
    i = pa_attachment_issuer.count++;
    memcpy(pa_attachment_issuer.admissions[i].recipient,recipient,32);
    pa_attachment_issuer.admissions[i].fd = -1;
    return 1;
}
static int pa_attachment_issuer_drop(struct pa_attachment_admission *a) {
    if (a->fd >= 0) close(a->fd);
    pa_attachment_sender_close(&a->sender);
    a->fd = -1; a->consumed = 1; return 0;
}
/* Consumption happens at accept, including failed/abandoned handshakes. */
static int pa_attachment_issuer_accept_fd(int fd) {
    unsigned char peer[32]; size_t i;
    if (!pa_attachment_socket_options(fd) || !pa_attachment_issuer_boundary() ||
        !pa_attachment_peer(fd,peer,0)) { close(fd); return 0; }
    for (i = 0; i < pa_attachment_issuer.count; ++i) {
        struct pa_attachment_admission *a = &pa_attachment_issuer.admissions[i];
        if (memcmp(peer,a->recipient,32)) continue;
        if (a->consumed) { close(fd); return 0; }
        a->consumed = 1; a->fd = fd;
        if (!pa_attachment_sender_open(&a->sender,fd)) return pa_attachment_issuer_drop(a);
        return pa_attachment_issuer_identity();
    }
    close(fd); return 0;
}
static int pa_attachment_issuer_serve(struct pa_attachment_admission *a) {
    struct pa_attachment_request request;
    struct pa_attachment_record response;
    unsigned char peer[32]; uint64_t sequence; size_t i;
    if (a->fd < 0 || !pa_attachment_issuer_boundary()) return 0;
    if (!pa_attachment_peer(a->fd,peer,0) || memcmp(peer,a->recipient,32) ||
        !pa_attachment_request_receive(a->fd,&a->sender,a->recipient,&request))
        return pa_attachment_issuer_drop(a);
    if (!pa_attachment_issuer_identity()) return 0;
    sequence = pa_attachment_uint(request.sequence,8);
    if (a->sequence == UINT64_MAX || sequence != a->sequence+1 ||
        request.op != (a->sequence ? 2 : 1) ||
        memcmp(request.boot,pa_attachment_issuer.source.record.boot,16) ||
        memcmp(request.session,pa_attachment_issuer.source.record.session,32) ||
        !pa_attachment_nonzero(request.challenge,32) ||
        !memcmp(request.challenge,a->challenge,32)) return pa_attachment_issuer_drop(a);
    /* Never forget used challenges, including those on dead connections.
     * Capacity exhaustion ends the session rather than evicting replay state. */
    if (pa_attachment_issuer.challenge_count == PA_ATTACHMENT_MAX_CHALLENGES)
        return pa_attachment_issuer_reject();
    for (i = 0; i < pa_attachment_issuer.challenge_count; ++i)
        if (!memcmp(request.challenge,pa_attachment_issuer.challenges[i],32))
            return pa_attachment_issuer_drop(a);
    memcpy(pa_attachment_issuer.challenges[pa_attachment_issuer.challenge_count++],request.challenge,32);
    if (!a->sequence) {
        if (!pa_attachment_random(a->lease)) return pa_attachment_issuer_drop(a);
    }
    a->sequence = sequence; memcpy(a->challenge,request.challenge,32);
    response = pa_attachment_issuer.source.record;
    memcpy(response.challenge,request.challenge,32);
    memcpy(response.recipient,a->recipient,32);
    memcpy(response.issuer,pa_attachment_issuer.identity,32);
    memcpy(response.lease,a->lease,32);
    memcpy(response.sequence,request.sequence,8);
    if (!pa_attachment_issuer_boundary() || !pa_attachment_issuer_identity()) return 0;
    if (!pa_attachment_send_record(a->fd,&response)) return pa_attachment_issuer_drop(a);
    return pa_attachment_issuer_boundary();
}
/* Return 1 for a live issuer (including rejected clients), 0 permanently dead.
 * Bounded client I/O; a stalled client can cause denial, never authorization.
 * The administrative host must serialize ALL calls, not run concurrent pumps. */
int pa_attachment_issuer_pump(void) {
    struct pollfd fds[PA_ATTACHMENT_MAX_LEASES+1]; size_t i;
    if (!pa_attachment_issuer_boundary() || pa_attachment_issuer.listener < 0) return 0;
    fds[0] = (struct pollfd){pa_attachment_issuer.listener,POLLIN,0};
    for (i = 0; i < pa_attachment_issuer.count; ++i)
        fds[i+1] = (struct pollfd){pa_attachment_issuer.admissions[i].fd,POLLIN,0};
    if (poll(fds,(nfds_t)pa_attachment_issuer.count+1,PA_ATTACHMENT_TIMEOUT_MS) < 0)
        return pa_attachment_issuer_reject();
    if (fds[0].revents & (POLLERR|POLLHUP|POLLNVAL)) return pa_attachment_issuer_reject();
    if (fds[0].revents & POLLIN) {
        int fd = accept(pa_attachment_issuer.listener,NULL,NULL);
        if (fd < 0) return pa_attachment_issuer_reject();
        (void)pa_attachment_issuer_accept_fd(fd);
    }
    for (i = 0; i < pa_attachment_issuer.count; ++i) {
        if (fds[i+1].revents & (POLLERR|POLLHUP|POLLNVAL))
            (void)pa_attachment_issuer_drop(&pa_attachment_issuer.admissions[i]);
        else if (fds[i+1].revents & POLLIN)
            (void)pa_attachment_issuer_serve(&pa_attachment_issuer.admissions[i]);
    }
    return pa_attachment_issuer_boundary();
}
