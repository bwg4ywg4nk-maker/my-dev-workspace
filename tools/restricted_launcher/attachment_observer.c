/* Standalone, single-threaded pre-Python consumer. No launcher/provider wiring.
 * One process, one attempt, one retained connection. Never reset after failure.
 * Successful evidence use is NOT provider qualification. */
#include "attachment_protocol.h"

static struct {
    int attempted, invalid, fd;
    unsigned char identity[32], issuer[32], lease[32], challenge[32];
    uint64_t sequence;
    struct pa_attachment_source source;
    struct pa_attachment_sender_client sender;
} pa_attachment_observer = {.fd = -1};

static int pa_attachment_observer_reject(void) {
    pa_attachment_observer.invalid = 1;
    if (pa_attachment_observer.fd >= 0) close(pa_attachment_observer.fd);
    pa_attachment_observer.fd = -1;
    pa_attachment_sender_client_close(&pa_attachment_observer.sender);
    return 0;
}
static int pa_attachment_observer_identity(void) {
    unsigned char self[32];
    if (pa_attachment_observer.invalid || !pa_attachment_observer.attempted ||
        !pa_attachment_self(self) ||
        memcmp(self,pa_attachment_observer.identity,32))
        return pa_attachment_observer_reject();
    return 1;
}
static int pa_attachment_observer_boundary(void) {
    unsigned char peer[32]; struct pollfd event;
    if (pa_attachment_observer.fd < 0 || !pa_attachment_observer_identity() ||
        !pa_attachment_peer(pa_attachment_observer.fd,peer,1) ||
        memcmp(peer,pa_attachment_observer.issuer,32) ||
        !pa_attachment_source_current(&pa_attachment_observer.source) ||
        !pa_attachment_observer_identity() ||
        !pa_attachment_observe(&pa_attachment_observer.source.record) ||
        !pa_attachment_observer_identity())
        return pa_attachment_observer_reject();
    event = (struct pollfd){pa_attachment_observer.fd,POLLIN,0};
    /* No unsolicited/trailing messages or buffered records between calls. */
    if (poll(&event,1,0) != 0) return pa_attachment_observer_reject();
    return pa_attachment_observer_identity();
}
static int pa_attachment_observer_response(const struct pa_attachment_request *request,
                                           const struct pa_attachment_record *response) {
    struct pa_attachment_record fixed = *response;
    if (!pa_attachment_shape(response,0) ||
        memcmp(response->challenge,request->challenge,32) ||
        memcmp(response->sequence,request->sequence,8) ||
        memcmp(response->recipient,pa_attachment_observer.identity,32) ||
        memcmp(response->issuer,pa_attachment_observer.issuer,32) ||
        (pa_attachment_observer.sequence && memcmp(response->lease,pa_attachment_observer.lease,32)))
        return pa_attachment_observer_reject();
    memset(fixed.challenge,0,32); memset(fixed.sequence,0,8);
    memset(fixed.recipient,0,32); memset(fixed.issuer,0,32); memset(fixed.lease,0,32);
    if (memcmp(&fixed,&pa_attachment_observer.source.record,sizeof(fixed)))
        return pa_attachment_observer_reject();
    memcpy(pa_attachment_observer.lease,response->lease,32);
    memcpy(pa_attachment_observer.challenge,request->challenge,32);
    pa_attachment_observer.sequence = pa_attachment_uint(request->sequence,8);
    return 1;
}
int pa_attachment_observer_check(void) {
    struct pa_attachment_request request; struct pa_attachment_record response;
    if (!pa_attachment_observer_boundary() || pa_attachment_observer.sequence == UINT64_MAX)
        return pa_attachment_observer_reject();
    memset(&request,0,sizeof(request)); request.op = pa_attachment_observer.sequence ? 2 : 1;
    memcpy(request.boot,pa_attachment_observer.source.record.boot,16);
    memcpy(request.session,pa_attachment_observer.source.record.session,32);
    pa_attachment_put(request.sequence,8,pa_attachment_observer.sequence+1);
    if (!pa_attachment_random(request.challenge) ||
        !memcmp(request.challenge,pa_attachment_observer.challenge,32) ||
        !pa_attachment_request_send(pa_attachment_observer.fd,&pa_attachment_observer.sender,&request) ||
        !pa_attachment_receive_record(pa_attachment_observer.fd,&response) ||
        !pa_attachment_observer_identity() ||
        !pa_attachment_observer_response(&request,&response))
        return pa_attachment_observer_reject();
    return pa_attachment_observer_boundary();
}
int pa_attachment_observer_open(void) {
    struct sockaddr_un address; struct stat before,after; int dir = -1, fd = -1;
    if (pa_attachment_observer.attempted || pa_attachment_observer.invalid)
        return pa_attachment_observer_reject();
    pa_attachment_observer.attempted = 1;
    if (!pa_attachment_self(pa_attachment_observer.identity) ||
        !pa_attachment_load(&pa_attachment_observer.source) ||
        !pa_attachment_observer_identity() ||
        !pa_attachment_observe(&pa_attachment_observer.source.record) ||
        !pa_attachment_observer_identity()) goto fail;
    dir = pa_attachment_open_admin(PA_ATTACHMENT_DIR,1);
    if (dir < 0 || fstatat(dir,"attachment.sock",&before,AT_SYMLINK_NOFOLLOW) ||
        before.st_uid || !S_ISSOCK(before.st_mode) || !pa_attachment_observer_identity()) goto fail;
    fd = socket(AF_UNIX,SOCK_STREAM,0);
    if (fd < 0 || !pa_attachment_socket_options(fd)) goto fail;
    memset(&address,0,sizeof(address)); address.sun_family = AF_UNIX;
    memcpy(address.sun_path,PA_ATTACHMENT_SOCKET,sizeof(PA_ATTACHMENT_SOCKET));
    address.sun_len = (unsigned char)SUN_LEN(&address);
    if (connect(fd,(struct sockaddr *)&address,address.sun_len) ||
        !pa_attachment_peer(fd,pa_attachment_observer.issuer,1) ||
        fstatat(dir,"attachment.sock",&after,AT_SYMLINK_NOFOLLOW) ||
        before.st_dev != after.st_dev || before.st_ino != after.st_ino ||
        before.st_uid != after.st_uid || before.st_mode != after.st_mode ||
        !pa_attachment_observer_identity()) goto fail;
    close(dir); dir = -1;
    pa_attachment_observer.fd = fd; fd = -1;
    if (!pa_attachment_sender_connect(&pa_attachment_observer.sender,pa_attachment_observer.fd) ||
        !pa_attachment_observer_identity()) return pa_attachment_observer_reject();
    return pa_attachment_observer_check();
 fail:
    if (fd >= 0) close(fd);
    if (dir >= 0) close(dir);
    return pa_attachment_observer_reject();
}
