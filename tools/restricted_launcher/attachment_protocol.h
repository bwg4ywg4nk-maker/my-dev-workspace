/* Private attachment protocol v1. No qualification or launcher integration.
 *
 * Administration prerequisite (not implemented by this protocol): root must
 * independently establish the complete, shadow-free attachment and install
 * attachment-session.json outside the image. All ancestors must be local,
 * root-owned, non-writable by other users, without ACLs/symlinks. Provision
 * these objects securely from creation (no previously retained writer FDs).
 * Root must freeze the attachment/backing/pins until ALL consumers exit,
 * including after issuer failure. A session cannot be restarted. Recovery
 * requires consumers to exit and a newly approved session; never remove a
 * used-session marker to revive it. Hostile administrators remain excluded.
 *
 * Canonical JSON: exactly the alphabetically ordered fields below, all values
 * lowercase fixed-width hex strings, no whitespace/escapes/optional fields.
 * Integers are unsigned big-endian; paths/text are NUL-terminated byte strings
 * padded with zeros (unsupported non-ASCII or noncanonical paths reject).
 * This representation avoids JSON integer rounding and parser ambiguity.
 * The administrative template has zero challenge/issuer/lease/recipient/
 * sequence fields; only the issuer fills them in responses. Other fields are
 * immutable. State fields must be readonly=1, owner=0, shadow/overlay absent=1.
 * boot is the kernel boot UUID; session is a fresh administrative random 256
 * bit identifier. Tokens contain all eight kernel audit-token words.
 *
 * Request = op(1), boot(16), session(32), challenge(32), sequence(8).
 * Requests travel in Mach messages with kernel-generated audit trailers;
 * connection-time Unix credentials alone cannot authenticate their sender.
 * Each admitted socket gets its own random, ephemeral Mach endpoint. Its
 * bootstrap name is sent over the authenticated Unix connection. Lookup is
 * routing only, not authentication: the issuer checks the actual sender of
 * every complete request against the admitted audit token. Missing endpoints,
 * unsupported trailers, or a different bootstrap namespace fail closed.
 * Unix carries a one-byte request notification and responses, and remains
 * retained for disconnect/lifecycle detection. No legacy raw-request fallback.
 * Response = big-endian uint32 length followed by canonical JSON. First
 * sequence is 1; subsequent requests increment it on the retained connection.
 * Limits/timeout exhaustion reject; no retry/reconnect or automatic recovery.
 */
#ifndef PA_ATTACHMENT_PROTOCOL_H
#define PA_ATTACHMENT_PROTOCOL_H
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <stdio.h>
#include <stdlib.h>
#include <errno.h>
#include <limits.h>
#include <unistd.h>
#include <fcntl.h>
#include <poll.h>
#include <time.h>
#include <sys/stat.h>
#include <sys/mount.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <sys/sysctl.h>
#include <sys/random.h>
#include <sys/acl.h>
#include <mach/mach.h>
#include <servers/bootstrap.h>
#include <bsm/libbsm.h>
#include <uuid/uuid.h>
#include <CommonCrypto/CommonDigest.h>
#include <IOKit/IOKitLib.h>

#define PA_ATTACHMENT_DIR "/Library/ProfessionalPresentationAgent"
#define PA_ATTACHMENT_SESSION PA_ATTACHMENT_DIR "/attachment-session.json"
#define PA_ATTACHMENT_SOCKET PA_ATTACHMENT_DIR "/attachment.sock"
#define PA_ATTACHMENT_PINS PA_ATTACHMENT_DIR "/deployment-protection.json"
#define PA_ATTACHMENT_MAX_WIRE 16384
#define PA_ATTACHMENT_MAX_LEASES 64
#define PA_ATTACHMENT_MAX_CHALLENGES 4096
#define PA_ATTACHMENT_TIMEOUT_MS 2000

#define PA_ATTACHMENT_FIELDS(X) \
 X(attachment_id,8) X(attachment_owner,4) X(attachment_readonly,1) \
 X(backing_dev,8) X(backing_ino,8) X(backing_path,1024) \
 X(backing_sha256,32) X(backing_size,8) X(boot,16) X(challenge,32) \
 X(deployment_sha256,32) X(issuer,32) X(lease,32) X(media_id,8) \
 X(mount_dev,8) X(mount_flags,8) X(mount_fsid,8) X(mount_ino,8) \
 X(mount_owner,4) X(mount_path,1024) X(mount_source,128) X(mount_type,16) \
 X(overlay_absent,1) X(pin_sha256,32) X(recipient,32) X(sequence,8) \
 X(session,32) X(shadow_absent,1) X(version,4)
struct pa_attachment_record {
#define PA_FIELD(name,n) unsigned char name[n];
    PA_ATTACHMENT_FIELDS(PA_FIELD)
#undef PA_FIELD
};
struct pa_attachment_field { const char *name; size_t offset, size; };
static const struct pa_attachment_field pa_attachment_fields[] = {
#define PA_FIELD(name,n) {#name, offsetof(struct pa_attachment_record,name),n},
    PA_ATTACHMENT_FIELDS(PA_FIELD)
#undef PA_FIELD
};
struct pa_attachment_request {
    unsigned char op, boot[16], session[32], challenge[32], sequence[8];
};
_Static_assert(sizeof(struct pa_attachment_request) == 89,"request must have no padding");
struct pa_attachment_sender_endpoint {
    mach_port_t port;
    pid_t owner;
    char name[128];
};
struct pa_attachment_sender_client {
    mach_port_t port;
    pid_t owner;
};
struct pa_attachment_stamp {
    dev_t dev; ino_t ino; off_t size;
    struct timespec modified, changed;
};
struct pa_attachment_source {
    struct pa_attachment_record record;
    struct pa_attachment_stamp stamp;
};

/* Private, single-threaded components. Administrative admission is an explicit
 * in-process root operation, never a request accepted from the public socket.
 * No function initializes Python or changes any provider/qualification state. */
int pa_attachment_issuer_open(void);
int pa_attachment_issuer_admit(const unsigned char recipient[32]);
int pa_attachment_issuer_pump(void);
int pa_attachment_observer_open(void);
int pa_attachment_observer_check(void);

static inline uint64_t pa_attachment_uint(const unsigned char *p, size_t n) {
    uint64_t v = 0; size_t i;
    for (i = 0; i < n; ++i) v = (v << 8) | p[i];
    return v;
}
static inline void pa_attachment_put(unsigned char *p, size_t n, uint64_t v) {
    while (n) { p[--n] = (unsigned char)v; v >>= 8; }
}
static inline int pa_attachment_nonzero(const unsigned char *p, size_t n) {
    unsigned char v = 0; while (n--) v |= *p++; return v != 0;
}
static inline int pa_attachment_text(const unsigned char *p, size_t n, int path) {
    size_t i = 0, j;
    if (!n || !p[0] || (path && p[0] != '/')) return 0;
    while (i < n && p[i]) {
        if (p[i] < 32 || p[i] > 126 || p[i] == '\\' || p[i] == '"') return 0;
        ++i;
    }
    if (i == n || (path && (i < 2 || p[i-1] == '/' ||
        strstr((const char *)p,"//") || strstr((const char *)p,"/./") ||
        strstr((const char *)p,"/../") ||
        (i >= 2 && !strcmp((const char *)p+i-2,"/.")) ||
        (i >= 3 && !strcmp((const char *)p+i-3,"/.."))))) return 0;
    for (j = i; j < n; ++j) if (p[j]) return 0;
    return 1;
}
static inline int pa_attachment_shape(const struct pa_attachment_record *r, int template) {
    if (pa_attachment_uint(r->version,4) != 1 ||
        pa_attachment_uint(r->attachment_owner,4) ||
        r->attachment_readonly[0] != 1 || r->shadow_absent[0] != 1 ||
        r->overlay_absent[0] != 1 || pa_attachment_uint(r->mount_owner,4) ||
        !pa_attachment_nonzero(r->boot,16) || !pa_attachment_nonzero(r->session,32) ||
        !pa_attachment_nonzero(r->backing_sha256,32) ||
        !pa_attachment_nonzero(r->deployment_sha256,32) ||
        !pa_attachment_nonzero(r->pin_sha256,32) ||
        !pa_attachment_uint(r->attachment_id,8) || !pa_attachment_uint(r->media_id,8) ||
        !memcmp(r->attachment_id,r->media_id,8) ||
        !pa_attachment_uint(r->backing_size,8) ||
        !pa_attachment_text(r->backing_path,sizeof(r->backing_path),1) ||
        !pa_attachment_text(r->mount_path,sizeof(r->mount_path),1) ||
        !pa_attachment_text(r->mount_source,sizeof(r->mount_source),1) ||
        !pa_attachment_text(r->mount_type,sizeof(r->mount_type),0)) return 0;
    if (template) return !pa_attachment_nonzero(r->challenge,32) &&
        !pa_attachment_nonzero(r->issuer,32) && !pa_attachment_nonzero(r->lease,32) &&
        !pa_attachment_nonzero(r->recipient,32) && !pa_attachment_uint(r->sequence,8);
    return pa_attachment_nonzero(r->challenge,32) && pa_attachment_nonzero(r->issuer,32) &&
        pa_attachment_nonzero(r->lease,32) && pa_attachment_nonzero(r->recipient,32) &&
        pa_attachment_uint(r->sequence,8);
}
static inline size_t pa_attachment_encode(const struct pa_attachment_record *r,
                                          char out[PA_ATTACHMENT_MAX_WIRE]) {
    static const char hex[] = "0123456789abcdef";
    size_t i, j, used = 0;
    out[used++] = '{';
    for (i = 0; i < sizeof(pa_attachment_fields)/sizeof(*pa_attachment_fields); ++i) {
        const struct pa_attachment_field *f = &pa_attachment_fields[i];
        const unsigned char *p = (const unsigned char *)r + f->offset;
        size_t len = strlen(f->name);
        if (used + len + 2*f->size + 8 >= PA_ATTACHMENT_MAX_WIRE) return 0;
        if (i) out[used++] = ',';
        out[used++] = '"'; memcpy(out+used,f->name,len); used += len;
        memcpy(out+used,"\":\"",3); used += 3;
        for (j = 0; j < f->size; ++j) {
            out[used++] = hex[p[j] >> 4]; out[used++] = hex[p[j] & 15];
        }
        out[used++] = '"';
    }
    out[used++] = '}'; return used;
}
static inline int pa_attachment_nibble(unsigned char c) {
    if (c >= '0' && c <= '9') return c-'0';
    if (c >= 'a' && c <= 'f') return c-'a'+10;
    return -1;
}
static inline int pa_attachment_decode(struct pa_attachment_record *r,
                                        const char *data, size_t size) {
    size_t i, j, at = 0;
    if (!size || size > PA_ATTACHMENT_MAX_WIRE || data[at++] != '{') return 0;
    memset(r,0,sizeof(*r));
    for (i = 0; i < sizeof(pa_attachment_fields)/sizeof(*pa_attachment_fields); ++i) {
        const struct pa_attachment_field *f = &pa_attachment_fields[i];
        unsigned char *p = (unsigned char *)r + f->offset;
        size_t len = strlen(f->name);
        if (size-at < len+2*f->size+5+(i != 0)) return 0;
        if (i && data[at++] != ',') return 0;
        if (data[at++] != '"' || memcmp(data+at,f->name,len)) return 0;
        at += len;
        if (memcmp(data+at,"\":\"",3)) return 0;
        at += 3;
        for (j = 0; j < f->size; ++j) {
            int a = pa_attachment_nibble(data[at++]), b = pa_attachment_nibble(data[at++]);
            if (a < 0 || b < 0) return 0;
            p[j] = (unsigned char)(a*16+b);
        }
        if (data[at++] != '"') return 0;
    }
    return at+1 == size && data[at] == '}';
}
static inline int pa_attachment_random(unsigned char out[32]) {
    return getentropy(out,32) == 0 && pa_attachment_nonzero(out,32);
}
static inline int pa_attachment_boot(unsigned char out[16]) {
    char value[64] = {0}; size_t n = sizeof(value);
    return sysctlbyname("kern.bootsessionuuid",value,&n,NULL,0) == 0 &&
        n == 37 && value[36] == 0 && uuid_parse(value,out) == 0;
}
static inline void pa_attachment_token(unsigned char out[32], audit_token_t token) {
    size_t i; for (i = 0; i < 8; ++i) pa_attachment_put(out+4*i,4,token.val[i]);
}
static inline int pa_attachment_native_self(unsigned char out[32]) {
    audit_token_t token; mach_msg_type_number_t n = TASK_AUDIT_TOKEN_COUNT;
    if (task_info(mach_task_self(),TASK_AUDIT_TOKEN,(task_info_t)&token,&n) != KERN_SUCCESS ||
        n != TASK_AUDIT_TOKEN_COUNT || audit_token_to_pid(token) != getpid()) return 0;
    pa_attachment_token(out,token); return 1;
}
static inline int pa_attachment_native_peer(int fd, unsigned char out[32], int root) {
    audit_token_t token; socklen_t n = sizeof(token); uid_t uid; gid_t gid;
    if (getsockopt(fd,SOL_LOCAL,LOCAL_PEERTOKEN,&token,&n) || n != sizeof(token) ||
        getpeereid(fd,&uid,&gid) || (root && uid != 0) ||
        audit_token_to_euid(token) != uid || audit_token_to_egid(token) != gid ||
        audit_token_to_pid(token) <= 0) return 0;
    pa_attachment_token(out,token); return 1;
}
static inline int64_t pa_attachment_now(void) {
    struct timespec t;
    if (clock_gettime(CLOCK_MONOTONIC,&t)) return -1;
    return (int64_t)t.tv_sec*1000+t.tv_nsec/1000000;
}
static inline int pa_attachment_io(int fd, void *data, size_t size, int sending) {
    unsigned char *p = data; int64_t start = pa_attachment_now(), now;
    if (start < 0) return 0;
    while (size) {
        struct pollfd event = {fd, sending ? POLLOUT : POLLIN,0}; ssize_t n;
        now = pa_attachment_now();
        if (now < start || now-start >= PA_ATTACHMENT_TIMEOUT_MS) return 0;
        if (poll(&event,1,(int)(PA_ATTACHMENT_TIMEOUT_MS-(now-start))) <= 0 ||
            (event.revents & (POLLERR|POLLHUP|POLLNVAL))) return 0;
        n = sending ? send(fd,p,size,MSG_DONTWAIT) : recv(fd,p,size,MSG_DONTWAIT);
        if (n < 0 && (errno == EINTR || errno == EAGAIN)) continue;
        if (n <= 0) return 0;
        p += n; size -= (size_t)n;
    }
    return 1;
}
static inline int pa_attachment_socket_options(int fd) {
    int one = 1;
    return !setsockopt(fd,SOL_SOCKET,SO_NOSIGPIPE,&one,sizeof(one)) &&
        !fcntl(fd,F_SETFD,FD_CLOEXEC);
}
/* The Mach proof is the request itself, not a client-supplied PID or bearer
 * credential. Inheriting/transferring either transport does not transfer the
 * kernel audit identity on subsequent sends. There are no test replacements
 * for this authentication path. All endpoint names are public routing data. */
static inline void pa_attachment_sender_close(struct pa_attachment_sender_endpoint *e) {
    if (e->owner == getpid() && e->port != MACH_PORT_NULL) {
        if (e->name[0]) (void)bootstrap_register(bootstrap_port,e->name,MACH_PORT_NULL);
        (void)mach_port_destroy(mach_task_self(),e->port);
    }
    /* A fork child must not unregister its parent's endpoint or use inherited
     * integer port names in its different Mach port namespace. */
    memset(e,0,sizeof(*e));
}
static inline void pa_attachment_sender_client_close(struct pa_attachment_sender_client *c) {
    if (c->owner == getpid() && c->port != MACH_PORT_NULL)
        (void)mach_port_deallocate(mach_task_self(),c->port);
    memset(c,0,sizeof(*c));
}
static inline int pa_attachment_sender_open(struct pa_attachment_sender_endpoint *e, int fd) {
    unsigned char nonce[32]; size_t i; char name[128] = "org.ppa.attachment.";
    memset(e,0,sizeof(*e)); e->owner = getpid();
    if (!pa_attachment_random(nonce) ||
        mach_port_allocate(mach_task_self(),MACH_PORT_RIGHT_RECEIVE,&e->port) != KERN_SUCCESS)
        return 0;
    for (i = 0; i < 32; ++i) snprintf(name+19+2*i,3,"%02x",nonce[i]);
    if (mach_port_insert_right(mach_task_self(),e->port,e->port,MACH_MSG_TYPE_MAKE_SEND) != KERN_SUCCESS ||
        bootstrap_register(bootstrap_port,name,e->port) != KERN_SUCCESS) {
        pa_attachment_sender_close(e); return 0;
    }
    memcpy(e->name,name,sizeof(name));
    if (!pa_attachment_io(fd,e->name,sizeof(e->name),1)) {
        pa_attachment_sender_close(e); return 0;
    }
    return 1;
}
static inline int pa_attachment_sender_connect(struct pa_attachment_sender_client *c, int fd) {
    char name[128]; size_t i;
    memset(c,0,sizeof(*c)); c->owner = getpid();
    if (!pa_attachment_io(fd,name,sizeof(name),0) || memcmp(name,"org.ppa.attachment.",19)) return 0;
    for (i = 19; i < 83; ++i) if (pa_attachment_nibble((unsigned char)name[i]) < 0) return 0;
    for (i = 83; i < sizeof(name); ++i) if (name[i]) return 0;
    return bootstrap_look_up(bootstrap_port,name,&c->port) == KERN_SUCCESS &&
        c->port != MACH_PORT_NULL;
}
struct pa_attachment_sender_message {
    mach_msg_header_t header;
    struct pa_attachment_request request;
    unsigned char padding[3];
};
_Static_assert(sizeof(struct pa_attachment_sender_message) == sizeof(mach_msg_header_t)+92,
               "Mach request padding must be explicit");
#define PA_ATTACHMENT_REQUEST_ID 0x50414131
static inline int pa_attachment_request_send(int fd, const struct pa_attachment_sender_client *c,
                                              const struct pa_attachment_request *request) {
    struct pa_attachment_sender_message msg = {0}; unsigned char notify = 1;
    if (c->owner != getpid() || c->port == MACH_PORT_NULL) return 0;
    msg.header.msgh_bits = MACH_MSGH_BITS(MACH_MSG_TYPE_COPY_SEND,0);
    msg.header.msgh_remote_port = c->port;
    msg.header.msgh_size = sizeof(msg); msg.header.msgh_id = PA_ATTACHMENT_REQUEST_ID;
    msg.request = *request;
    return mach_msg(&msg.header,MACH_SEND_MSG|MACH_SEND_TIMEOUT,sizeof(msg),0,
                    MACH_PORT_NULL,PA_ATTACHMENT_TIMEOUT_MS,MACH_PORT_NULL) == MACH_MSG_SUCCESS &&
        pa_attachment_io(fd,&notify,1,1);
}
static inline int pa_attachment_request_receive(int fd, const struct pa_attachment_sender_endpoint *e,
                                                 const unsigned char recipient[32],
                                                 struct pa_attachment_request *request) {
    struct {
        struct pa_attachment_sender_message msg;
        mach_msg_audit_trailer_t trailer;
    } received = {0};
    unsigned char notify, sender[32]; int ok;
    if (e->owner != getpid() || e->port == MACH_PORT_NULL ||
        !pa_attachment_io(fd,&notify,1,0) || notify != 1) return 0;
    if (mach_msg(&received.msg.header,MACH_RCV_MSG|MACH_RCV_TIMEOUT|
                 MACH_RCV_TRAILER_TYPE(MACH_MSG_TRAILER_FORMAT_0)|
                 MACH_RCV_TRAILER_ELEMENTS(MACH_RCV_TRAILER_AUDIT),0,sizeof(received),
                 e->port,PA_ATTACHMENT_TIMEOUT_MS,MACH_PORT_NULL) != MACH_MSG_SUCCESS) return 0;
    ok = !(received.msg.header.msgh_bits & MACH_MSGH_BITS_COMPLEX) &&
        received.msg.header.msgh_size == sizeof(received.msg) &&
        received.msg.header.msgh_id == PA_ATTACHMENT_REQUEST_ID &&
        received.msg.header.msgh_remote_port == MACH_PORT_NULL &&
        received.msg.header.msgh_local_port == e->port &&
        received.trailer.msgh_trailer_type == MACH_MSG_TRAILER_FORMAT_0 &&
        received.trailer.msgh_trailer_size == sizeof(received.trailer) &&
        !pa_attachment_nonzero(received.msg.padding,sizeof(received.msg.padding));
    if (ok) {
        pa_attachment_token(sender,received.trailer.msgh_audit);
        ok = !memcmp(sender,recipient,32);
        if (ok) *request = received.msg.request;
    }
    mach_msg_destroy(&received.msg.header);
    return ok;
}
static inline int pa_attachment_send_record(int fd, const struct pa_attachment_record *r) {
    char data[PA_ATTACHMENT_MAX_WIRE]; unsigned char length[4];
    size_t n = pa_attachment_encode(r,data);
    pa_attachment_put(length,4,n);
    return n && pa_attachment_io(fd,length,4,1) && pa_attachment_io(fd,data,n,1);
}
static inline int pa_attachment_receive_record(int fd, struct pa_attachment_record *r) {
    char data[PA_ATTACHMENT_MAX_WIRE]; unsigned char length[4]; size_t n;
    if (!pa_attachment_io(fd,length,4,0)) return 0;
    n = (size_t)pa_attachment_uint(length,4);
    return n && n <= sizeof(data) && pa_attachment_io(fd,data,n,0) &&
        pa_attachment_decode(r,data,n);
}
static inline int pa_attachment_stamp_equal(const struct pa_attachment_stamp *a,
                                            const struct pa_attachment_stamp *b) {
    return a->dev == b->dev && a->ino == b->ino && a->size == b->size &&
        a->modified.tv_sec == b->modified.tv_sec && a->modified.tv_nsec == b->modified.tv_nsec &&
        a->changed.tv_sec == b->changed.tv_sec && a->changed.tv_nsec == b->changed.tv_nsec;
}
static inline struct pa_attachment_stamp pa_attachment_stamp(const struct stat *s) {
    struct pa_attachment_stamp r = {s->st_dev,s->st_ino,s->st_size,s->st_mtimespec,s->st_ctimespec};
    return r;
}
/* Walk using openat: no symlink traversal, including intermediate components.
 * Reject extended ACLs even when they appear harmless. */
static inline int pa_attachment_admin_fd(int fd) {
    struct stat s; struct statfs fs; acl_t acl; acl_entry_t entry; int empty, saved;
    if (fstat(fd,&s) || s.st_uid || (s.st_mode & 022) || fstatfs(fd,&fs) ||
        fs.f_owner || !(fs.f_flags & MNT_LOCAL) ||
        (fs.f_flags & (MNT_IGNORE_OWNERSHIP|MNT_UNION))) return 0;
    errno = 0; acl = acl_get_fd_np(fd,ACL_TYPE_EXTENDED);
    if (!acl) return errno == ENOENT;
    errno = 0; empty = acl_get_entry(acl,ACL_FIRST_ENTRY,&entry); saved = errno;
    acl_free(acl); return empty == -1 && saved == EINVAL;
}
static inline int pa_attachment_open_admin(const char *path, int directory) {
    char copy[1024], *part, *next; int fd, child;
    size_t n = strlen(path);
    if (n >= sizeof(copy) || n < 2 || path[0] != '/' || path[n-1] == '/') return -1;
    memcpy(copy,path,n+1); fd = open("/",O_RDONLY|O_DIRECTORY|O_CLOEXEC);
    if (fd < 0) return -1;
    part = copy+1;
    for (;;) {
        struct stat s;
        next = strchr(part,'/'); if (next) *next = 0;
        if (!*part || !strcmp(part,".") || !strcmp(part,"..") || !pa_attachment_admin_fd(fd)) break;
        child = openat(fd,part,O_RDONLY|O_NOFOLLOW|O_NONBLOCK|O_CLOEXEC|
                       ((next || directory) ? O_DIRECTORY : 0));
        close(fd); fd = child;
        if (fd < 0) return -1;
        if (!next) {
            if (fstat(fd,&s) || !pa_attachment_admin_fd(fd) ||
                (directory ? !S_ISDIR(s.st_mode) : !S_ISREG(s.st_mode))) break;
            return fd;
        }
        part = next+1;
    }
    close(fd); return -1;
}
static inline int pa_attachment_file(const char *path, unsigned char digest[32],
                                    struct pa_attachment_stamp *stamp,
                                    char *data, size_t *size) {
    int fd = pa_attachment_open_admin(path,0), ok = 0;
    struct stat a,b,named; CC_SHA256_CTX ctx; unsigned char chunk[16384];
    size_t used = 0; ssize_t n;
    if (fd < 0) return 0;
    if (fstat(fd,&a) || !CC_SHA256_Init(&ctx)) goto done;
    while ((n = read(fd,chunk,sizeof(chunk))) > 0) {
        if (!CC_SHA256_Update(&ctx,chunk,(CC_LONG)n)) goto done;
        if (data) {
            if (!size || (size_t)n > *size-used) goto done;
            memcpy(data+used,chunk,(size_t)n); used += (size_t)n;
        }
    }
    if (n < 0 || fstat(fd,&b) || lstat(path,&named) || !S_ISREG(named.st_mode)) goto done;
    *stamp = pa_attachment_stamp(&a);
    { struct pa_attachment_stamp end = pa_attachment_stamp(&b), name = pa_attachment_stamp(&named);
      if (!pa_attachment_stamp_equal(stamp,&end) || !pa_attachment_stamp_equal(stamp,&name)) goto done; }
    if (!pa_attachment_admin_fd(fd) || !CC_SHA256_Final(digest,&ctx)) goto done;
    if (data) *size = used;
    ok = 1;
 done: close(fd); return ok;
}
static inline int pa_attachment_load(struct pa_attachment_source *source) {
    char bytes[PA_ATTACHMENT_MAX_WIRE]; size_t n = sizeof(bytes); unsigned char digest[32];
    return pa_attachment_file(PA_ATTACHMENT_SESSION,digest,&source->stamp,bytes,&n) &&
        pa_attachment_decode(&source->record,bytes,n) && pa_attachment_shape(&source->record,1);
}
static inline int pa_attachment_source_matches(const struct pa_attachment_source *source) {
    struct pa_attachment_source now;
    return pa_attachment_load(&now) && pa_attachment_stamp_equal(&now.stamp,&source->stamp) &&
        !memcmp(&now.record,&source->record,sizeof(now.record));
}
static inline int pa_attachment_media(const struct pa_attachment_record *r) {
    io_service_t media; io_registry_entry_t entry, parent;
    uint64_t id; unsigned int depth = 0; int found = 0;
    if (strncmp((const char *)r->mount_source,"/dev/",5)) return 0;
    media = IOServiceGetMatchingService(kIOMasterPortDefault,
        IOBSDNameMatching(kIOMasterPortDefault,0,(const char *)r->mount_source+5));
    if (!media) return 0;
    if (IORegistryEntryGetRegistryEntryID(media,&id) || id != pa_attachment_uint(r->media_id,8) ||
        !IOObjectConformsTo(media,"IOMedia")) { IOObjectRelease(media); return 0; }
    entry = media;
    /* Only an observable direct ancestry is supported. APFS topologies that
     * cannot establish this relationship reject; no guessed device mapping. */
    while (depth++ < 64) {
        if (IORegistryEntryGetRegistryEntryID(entry,&id)) break;
        if (id == pa_attachment_uint(r->attachment_id,8)) { found = 1; break; }
        if (IORegistryEntryGetParentEntry(entry,kIOServicePlane,&parent)) break;
        IOObjectRelease(entry); entry = parent;
    }
    IOObjectRelease(entry); return found;
}
/* Parse ONLY the existing canonical pin schema, without changing that schema.
 * Unsupported escaped/non-ASCII paths are deliberately rejected. */
static inline int pa_attachment_pins(const struct pa_attachment_record *r,
                                     const char *data, size_t size) {
    static const char *keys[] = {"backing_file","backing_sha256","build_sha256",
        "deployment_sha256","inputs_sha256","kind","launch_policy_sha256","root"};
    size_t i, at = 0;
    if (!size || data[at++] != '{') return 0;
    for (i = 0; i < 8; ++i) {
        size_t len = strlen(keys[i]), start, j; unsigned char hash[32];
        if (size-at < len+5+(i != 0)) return 0;
        if (i && data[at++] != ',') return 0;
        if (data[at++] != '"' || memcmp(data+at,keys[i],len)) return 0;
        at += len; if (memcmp(data+at,"\":\"",3)) return 0; at += 3; start = at;
        while (at < size && data[at] != '"') {
            if ((unsigned char)data[at] < 32 || (unsigned char)data[at] > 126 || data[at] == '\\') return 0;
            ++at;
        }
        if (at == size) return 0;
        len = at-start; ++at;
        if (i == 0 || i == 5 || i == 7) {
            const char *expected = i == 0 ? (const char *)r->backing_path :
                i == 7 ? (const char *)r->mount_path : "trusted-admin-readonly-image-v1";
            if (strlen(expected) != len || memcmp(expected,data+start,len)) return 0;
        } else {
            if (len != 64) return 0;
            for (j = 0; j < 32; ++j) {
                int a = pa_attachment_nibble(data[start+2*j]), b = pa_attachment_nibble(data[start+2*j+1]);
                if (a < 0 || b < 0) return 0;
                hash[j] = (unsigned char)(a*16+b);
            }
            if (!pa_attachment_nonzero(hash,32) ||
                (i == 1 && memcmp(hash,r->backing_sha256,32)) ||
                (i == 3 && memcmp(hash,r->deployment_sha256,32))) return 0;
        }
    }
    return at+1 == size && data[at] == '}';
}
static inline int pa_attachment_native_observe(const struct pa_attachment_record *r) {
    static int retained;
    static struct pa_attachment_stamp original_backing, original_pins;
    unsigned char boot[16], digest[32]; struct pa_attachment_stamp backing, pins_stamp;
    struct stat a,b; struct statfs fs,after; int fd, ok = 0;
    char pins[16384]; size_t n = sizeof(pins);
    size_t rootlen;
    if (!pa_attachment_shape(r,1)) return 0;
    rootlen = strlen((const char *)r->mount_path);
    if (!pa_attachment_boot(boot) || memcmp(boot,r->boot,16) ||
        (!strncmp(PA_ATTACHMENT_DIR,(const char *)r->mount_path,rootlen) &&
         (PA_ATTACHMENT_DIR[rootlen] == '/' || PA_ATTACHMENT_DIR[rootlen] == 0)) ||
        (!strncmp((const char *)r->backing_path,(const char *)r->mount_path,rootlen) &&
         (r->backing_path[rootlen] == '/' || r->backing_path[rootlen] == 0))) return 0;
    fd = pa_attachment_open_admin((const char *)r->mount_path,1);
    if (fd < 0) return 0;
    if (fstat(fd,&a) || fstatfs(fd,&fs) ||
        !(fs.f_flags & MNT_RDONLY) || !(fs.f_flags & MNT_LOCAL) ||
        fs.f_flags & (MNT_UNION|MNT_IGNORE_OWNERSHIP) || fs.f_owner ||
        (strcmp(fs.f_fstypename,"hfs") && strcmp(fs.f_fstypename,"apfs")) ||
        strcmp(fs.f_fstypename,(const char *)r->mount_type) ||
        strcmp(fs.f_mntonname,(const char *)r->mount_path) ||
        strcmp(fs.f_mntfromname,(const char *)r->mount_source) ||
        (uint64_t)a.st_dev != pa_attachment_uint(r->mount_dev,8) ||
        (uint64_t)a.st_ino != pa_attachment_uint(r->mount_ino,8) ||
        fs.f_flags != pa_attachment_uint(r->mount_flags,8) ||
        (uint32_t)fs.f_fsid.val[0] != pa_attachment_uint(r->mount_fsid,4) ||
        (uint32_t)fs.f_fsid.val[1] != pa_attachment_uint(r->mount_fsid+4,4) ||
        !pa_attachment_media(r)) goto done;
    if (!pa_attachment_file((const char *)r->backing_path,digest,&backing,NULL,NULL) ||
        memcmp(digest,r->backing_sha256,32) ||
        (uint64_t)backing.dev != pa_attachment_uint(r->backing_dev,8) ||
        (uint64_t)backing.ino != pa_attachment_uint(r->backing_ino,8) ||
        (uint64_t)backing.size != pa_attachment_uint(r->backing_size,8) ||
        !pa_attachment_file(PA_ATTACHMENT_PINS,digest,&pins_stamp,pins,&n) ||
        memcmp(digest,r->pin_sha256,32) || !pa_attachment_pins(r,pins,n) ||
        (retained && (!pa_attachment_stamp_equal(&backing,&original_backing) ||
                      !pa_attachment_stamp_equal(&pins_stamp,&original_pins))) ||
        !pa_attachment_media(r) || fstatfs(fd,&after) || fstat(fd,&b) ||
        a.st_dev != b.st_dev || a.st_ino != b.st_ino ||
        fs.f_flags != after.f_flags || fs.f_owner != after.f_owner ||
        memcmp(&fs.f_fsid,&after.f_fsid,sizeof(fs.f_fsid)) ||
        strcmp(fs.f_mntonname,after.f_mntonname) || strcmp(fs.f_mntfromname,after.f_mntfromname) ||
        strcmp(fs.f_fstypename,after.f_fstypename)) goto done;
    original_backing = backing; original_pins = pins_stamp; retained = 1; ok = 1;
 done: close(fd); return ok;
}
/* Test harnesses replace observations, never a production runtime switch. */
#ifdef PA_ATTACHMENT_TEST
int pa_attachment_test_self(unsigned char out[32]);
int pa_attachment_test_peer(int fd, unsigned char out[32], int root);
int pa_attachment_test_observe(const struct pa_attachment_record *r);
int pa_attachment_test_source(const struct pa_attachment_source *s);
#define pa_attachment_self pa_attachment_test_self
#define pa_attachment_peer pa_attachment_test_peer
#define pa_attachment_observe pa_attachment_test_observe
#define pa_attachment_source_current pa_attachment_test_source
#else
#define pa_attachment_self pa_attachment_native_self
#define pa_attachment_peer pa_attachment_native_peer
#define pa_attachment_observe pa_attachment_native_observe
#define pa_attachment_source_current pa_attachment_source_matches
#endif
#endif
