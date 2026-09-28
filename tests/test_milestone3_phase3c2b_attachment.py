"""Private native attachment protocol; simulated admin state, real socket I/O.

These tests neither provision a privileged attachment nor qualify a provider.
Generated harnesses stay under ignored build/; no installs or signing required.
"""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SUPPORT = ROOT / 'tools/restricted_launcher'

HARNESS = r'''
#define PA_ATTACHMENT_TEST 1
#include "attachment_provisioner.c"
#include "attachment_observer.c"
#include <assert.h>
#include <pthread.h>
#include <sys/wait.h>

static struct pa_attachment_record observed;
static int observation_available = 1, source_current = 1, wrong_peer;
static int fork_observation, fork_source, observation_child;
static pid_t forked_pid;
int pa_attachment_test_self(unsigned char out[32]) {
    return pa_attachment_native_self(out);
}
int pa_attachment_test_peer(int fd, unsigned char out[32], int root) {
    (void)fd; (void)root;
    pa_attachment_test_self(out); if (wrong_peer) out[31] ^= 1; return 1;
}
static void fork_inside_observation(int *trigger) {
    if (!*trigger) return;
    *trigger = 0;
    forked_pid = fork(); assert(forked_pid >= 0);
    if (!forked_pid) observation_child = 1;
}
int pa_attachment_test_observe(const struct pa_attachment_record *r) {
    fork_inside_observation(&fork_observation);
    return observation_available && !memcmp(r,&observed,sizeof(observed));
}
int pa_attachment_test_source(const struct pa_attachment_source *s) {
    fork_inside_observation(&fork_source);
    (void)s; return source_current;
}
static struct pa_attachment_record fixture(void) {
    struct pa_attachment_record r = {0};
    pa_attachment_put(r.version,4,1); r.boot[0] = 1; r.session[0] = 2;
    pa_attachment_put(r.attachment_id,8,1); pa_attachment_put(r.media_id,8,2);
    r.attachment_readonly[0] = r.overlay_absent[0] = r.shadow_absent[0] = 1;
    strcpy((char *)r.mount_path,"/protected/image");
    strcpy((char *)r.mount_source,"/dev/disk99s1"); strcpy((char *)r.mount_type,"hfs");
    strcpy((char *)r.backing_path,"/protected/backing.dmg");
    pa_attachment_put(r.backing_dev,8,1); pa_attachment_put(r.backing_ino,8,2);
    pa_attachment_put(r.backing_size,8,1024);
    memset(r.backing_sha256,0x11,32); memset(r.pin_sha256,0x22,32);
    memset(r.deployment_sha256,0x33,32);
    assert(pa_attachment_shape(&r,1)); return r;
}
static void setup(int pair[2]) {
    assert(socketpair(AF_UNIX,SOCK_STREAM,0,pair) == 0);
    assert(pa_attachment_socket_options(pair[0]) && pa_attachment_socket_options(pair[1]));
    observed = fixture();
    pa_attachment_issuer.attempted = 1;
    pa_attachment_test_self(pa_attachment_issuer.identity);
    pa_attachment_issuer.source.record = observed;
    pa_attachment_issuer.count = 1;
    pa_attachment_test_self(pa_attachment_issuer.admissions[0].recipient);
    pa_attachment_issuer.admissions[0].fd = -1;
    assert(pa_attachment_issuer_accept_fd(pair[1]));
    pa_attachment_observer.attempted = 1; pa_attachment_observer.fd = pair[0];
    pa_attachment_observer.source.record = observed;
    pa_attachment_test_self(pa_attachment_observer.identity);
    pa_attachment_test_self(pa_attachment_observer.issuer);
    assert(pa_attachment_sender_connect(&pa_attachment_observer.sender,pair[0]));
}
static void *serve(void *arg) {
    int count = *(int *)arg, i;
    for (i = 0; i < count; ++i) assert(pa_attachment_issuer_serve(&pa_attachment_issuer.admissions[0]));
    return NULL;
}
static void valid_check(void) {
    pthread_t thread; int count = 1;
    assert(!pthread_create(&thread,NULL,serve,&count));
    assert(pa_attachment_observer_check()); assert(!pthread_join(thread,NULL));
}
static struct pa_attachment_request request(void) {
    struct pa_attachment_request q = {0}; q.op = 1;
    memcpy(q.boot,observed.boot,16); memcpy(q.session,observed.session,32);
    q.challenge[0] = 99; pa_attachment_put(q.sequence,8,1); return q;
}
static void *bad_response(void *arg) {
    const char *mode = arg; struct pa_attachment_request q;
    struct pa_attachment_record r = observed;
    int fd = pa_attachment_issuer.admissions[0].fd;
    assert(pa_attachment_request_receive(fd,&pa_attachment_issuer.admissions[0].sender,
                                         pa_attachment_issuer.admissions[0].recipient,&q));
    memcpy(r.challenge,q.challenge,32); memcpy(r.sequence,q.sequence,8);
    pa_attachment_test_self(r.recipient); pa_attachment_test_self(r.issuer); r.lease[0] = 1;
    if (!strcmp(mode,"challenge")) r.challenge[0] ^= 1;
    else if (!strcmp(mode,"recipient")) r.recipient[31] ^= 1;
    else if (!strcmp(mode,"boot")) r.boot[0] ^= 1;
    else if (!strcmp(mode,"session")) r.session[0] ^= 1;
    else if (!strcmp(mode,"backing")) r.backing_sha256[0] ^= 1;
    else if (!strcmp(mode,"backing-path")) r.backing_path[1] ^= 1;
    else if (!strcmp(mode,"pin")) r.pin_sha256[0] ^= 1;
    else if (!strcmp(mode,"deployment")) r.deployment_sha256[0] ^= 1;
    else if (!strcmp(mode,"media")) r.media_id[0] ^= 1;
    else if (!strcmp(mode,"attachment")) r.attachment_id[0] ^= 1;
    else if (!strcmp(mode,"owner")) r.attachment_owner[3] = 1;
    else if (!strcmp(mode,"shadow")) r.shadow_absent[0] = 0;
    else if (!strcmp(mode,"overlay")) r.overlay_absent[0] = 0;
    else if (!strcmp(mode,"readonly")) r.attachment_readonly[0] = 0;
    else if (!strcmp(mode,"sequence")) r.sequence[7] = 0;
    else if (!strcmp(mode,"version")) r.version[3] = 2;
    else assert(0);
    assert(pa_attachment_send_record(fd,&r)); return NULL;
}
int main(int argc, char **argv) {
    int pair[2]; const char *mode; assert(argc == 2); mode = argv[1];
    if (!strcmp(mode,"native")) {
        unsigned char self[32], peer[32], boot[16];
        assert(pa_attachment_native_self(self)); assert(pa_attachment_boot(boot));
        assert(pa_attachment_uint(self+20,4) == (uint64_t)getpid());
        assert(socketpair(AF_UNIX,SOCK_STREAM,0,pair) == 0);
        assert(pa_attachment_native_peer(pair[0],peer,0));
        assert(!memcmp(self,peer,32));
        if (geteuid() != 0) assert(!pa_attachment_native_peer(pair[0],peer,1));
        assert(!pa_attachment_native_observe(&(struct pa_attachment_record){0}));
        return 0;
    }
    if (!strcmp(mode,"codec")) {
        struct pa_attachment_record r = fixture(), decoded;
        char data[PA_ATTACHMENT_MAX_WIRE], copy[PA_ATTACHMENT_MAX_WIRE]; size_t n, i;
        n = pa_attachment_encode(&r,data); assert(n && n < sizeof(data));
        assert(pa_attachment_decode(&decoded,data,n)); assert(!memcmp(&r,&decoded,sizeof(r)));
        for (i = 0; i < n; ++i) assert(!pa_attachment_decode(&decoded,data,i));
        data[n] = ' '; assert(!pa_attachment_decode(&decoded,data,n+1));
        memcpy(copy,data,n); copy[2] = 'X'; assert(!pa_attachment_decode(&decoded,copy,n));
        memcpy(copy,data,n); copy[18] = 'A'; assert(!pa_attachment_decode(&decoded,copy,n));
        memcpy(copy,data,n); copy[n-1] = ','; assert(!pa_attachment_decode(&decoded,copy,n));
        r.mount_path[500] = 1; assert(!pa_attachment_shape(&r,1));
        return 0;
    }
    if (!strcmp(mode,"protected-path")) {
        /* Ordinary workspace/tmp files cannot be an administrative anchor. */
        assert(pa_attachment_open_admin("/tmp/attachment-session.json",0) < 0);
        assert(pa_attachment_open_admin("/Library/../tmp",1) < 0);
        assert(pa_attachment_open_admin("/Library//missing",1) < 0);
        return 0;
    }
    if (!strcmp(mode,"session-marker")) {
        char directory[] = "session-XXXXXX"; unsigned char session[32] = {1}; int fd;
        assert(mkdtemp(directory)); fd = open(directory,O_RDONLY|O_DIRECTORY); assert(fd >= 0);
        assert(pa_attachment_claim_session(fd,session));
        assert(!pa_attachment_claim_session(fd,session));
        close(fd); fd = open(directory,O_RDONLY|O_DIRECTORY); assert(fd >= 0);
        assert(!pa_attachment_claim_session(fd,session)); /* Survives reopening. */
        session[0] = 2; assert(pa_attachment_claim_session(fd,session)); close(fd);
        return 0;
    }
    if (!strcmp(mode,"pins")) {
        struct pa_attachment_record r = fixture();
        char pins[2048], backing[65], deployment[65]; size_t i; int n;
        for (i = 0; i < 32; ++i) {
            snprintf(backing+2*i,3,"%02x",r.backing_sha256[i]);
            snprintf(deployment+2*i,3,"%02x",r.deployment_sha256[i]);
        }
        n = snprintf(pins,sizeof(pins),"{\"backing_file\":\"/protected/backing.dmg\","
            "\"backing_sha256\":\"%s\",\"build_sha256\":\"%s\","
            "\"deployment_sha256\":\"%s\",\"inputs_sha256\":\"%s\","
            "\"kind\":\"trusted-admin-readonly-image-v1\","
            "\"launch_policy_sha256\":\"%s\",\"root\":\"/protected/image\"}",
            backing,backing,deployment,backing,backing);
        assert(n > 0 && n < (int)sizeof(pins)); assert(pa_attachment_pins(&r,pins,(size_t)n));
        r.deployment_sha256[0] ^= 1; assert(!pa_attachment_pins(&r,pins,(size_t)n));
        r = fixture(); r.backing_path[1] ^= 1; assert(!pa_attachment_pins(&r,pins,(size_t)n));
        r = fixture(); for (i = 0; i < (size_t)n; ++i) assert(!pa_attachment_pins(&r,pins,i));
        pins[n] = ' '; assert(!pa_attachment_pins(&r,pins,(size_t)n+1));
        return 0;
    }
    setup(pair);
    if (!strcmp(mode,"valid")) {
        valid_check(); valid_check(); assert(pa_attachment_observer.sequence == 2);
    } else if (!strcmp(mode,"reconnect")) {
        int second[2]; valid_check(); assert(socketpair(AF_UNIX,SOCK_STREAM,0,second) == 0);
        assert(!pa_attachment_issuer_accept_fd(second[1])); close(second[0]);
        assert(!pa_attachment_observer_open()); assert(pa_attachment_observer.invalid);
    } else if (!strcmp(mode,"replay") || !strcmp(mode,"request-boot") ||
               !strcmp(mode,"request-session") || !strcmp(mode,"request-sequence")) {
        struct pa_attachment_request q = request(); struct pa_attachment_record r;
        if (!strcmp(mode,"replay")) {
            assert(pa_attachment_request_send(pair[0],&pa_attachment_observer.sender,&q));
            assert(pa_attachment_issuer_serve(&pa_attachment_issuer.admissions[0]));
            assert(pa_attachment_receive_record(pair[0],&r));
        } else if (!strcmp(mode,"request-boot")) q.boot[0] ^= 1;
        else if (!strcmp(mode,"request-session")) q.session[0] ^= 1;
        else q.sequence[7] = 2;
        assert(pa_attachment_request_send(pair[0],&pa_attachment_observer.sender,&q));
        assert(!pa_attachment_issuer_serve(&pa_attachment_issuer.admissions[0]));
        assert(pa_attachment_issuer.admissions[0].fd == -1);
        assert(pa_attachment_issuer.admissions[0].consumed);
    } else if (!strcmp(mode,"challenge-reuse") || !strcmp(mode,"replay-capacity")) {
        struct pa_attachment_request q = request(); struct pa_attachment_record r;
        assert(pa_attachment_request_send(pair[0],&pa_attachment_observer.sender,&q));
        assert(pa_attachment_issuer_serve(&pa_attachment_issuer.admissions[0]));
        assert(pa_attachment_receive_record(pair[0],&r));
        q.op = 2; q.challenge[0] = 100; pa_attachment_put(q.sequence,8,2);
        assert(pa_attachment_request_send(pair[0],&pa_attachment_observer.sender,&q));
        assert(pa_attachment_issuer_serve(&pa_attachment_issuer.admissions[0]));
        assert(pa_attachment_receive_record(pair[0],&r));
        if (!strcmp(mode,"replay-capacity"))
            pa_attachment_issuer.challenge_count = PA_ATTACHMENT_MAX_CHALLENGES;
        q.challenge[0] = 99; pa_attachment_put(q.sequence,8,3);
        assert(pa_attachment_request_send(pair[0],&pa_attachment_observer.sender,&q));
        assert(!pa_attachment_issuer_serve(&pa_attachment_issuer.admissions[0]));
        assert(pa_attachment_issuer.admissions[0].fd == -1);
    } else if (!strcmp(mode,"disconnect")) {
        valid_check(); close(pair[1]); pa_attachment_issuer.admissions[0].fd = -1;
        assert(!pa_attachment_observer_check()); assert(pa_attachment_observer.invalid);
    } else if (!strcmp(mode,"fork")) {
        pid_t child; int status; valid_check(); child = fork(); assert(child >= 0);
        if (!child) {
            assert(!pa_attachment_observer_check()); assert(pa_attachment_observer.invalid);
            assert(!pa_attachment_issuer_boundary()); _exit(0);
        }
        assert(waitpid(child,&status,0) == child && WIFEXITED(status) && !WEXITSTATUS(status));
        valid_check(); /* Child invalidation cannot damage the parent's state. */
    } else if (!strcmp(mode,"inherited-sender")) {
        pid_t child; int status; unsigned char peer[32];
        struct pa_attachment_request q = request();
        /* Establish the parent connection identity with the real kernel
         * lookup before the fork, not the test peer wrapper. */
        assert(pa_attachment_native_peer(pair[1],peer,0));
        assert(!memcmp(peer,pa_attachment_issuer.admissions[0].recipient,32));
        child = fork(); assert(child >= 0);
        if (!child) {
            struct pa_attachment_sender_client stolen = {0}; stolen.owner = getpid();
            /* Deliberately bypass the cooperating observer's owner guard.
             * Lookup grants routing access, never the parent's audit identity. */
            assert(bootstrap_look_up(bootstrap_port,pa_attachment_issuer.admissions[0].sender.name,
                                    &stolen.port) == KERN_SUCCESS);
            assert(pa_attachment_request_send(pair[0],&stolen,&q));
            pa_attachment_sender_client_close(&stolen); _exit(0);
        }
        assert(waitpid(child,&status,0) == child && WIFEXITED(status) && !WEXITSTATUS(status));
        /* Do not depend on a kernel's connection-lookup behavior after the
         * child exits. The fixture deliberately still supplies the admitted
         * parent's connection token; the real per-message audit must reject. */
        assert(pa_attachment_peer(pair[1],peer,0));
        assert(!memcmp(peer,pa_attachment_issuer.admissions[0].recipient,32));
        assert(!pa_attachment_issuer_serve(&pa_attachment_issuer.admissions[0]));
        assert(pa_attachment_issuer.admissions[0].fd == -1);
        assert(pa_attachment_issuer.admissions[0].sequence == 0);
        assert(pa_attachment_issuer.challenge_count == 0);
        assert(!pa_attachment_observer_check());
    } else if (!strncmp(mode,"during-",7)) {
        int result, status, issuer = strstr(mode,"issuer") != NULL;
        valid_check(); /* Fork only after the worker has joined. */
        if (strstr(mode,"source")) fork_source = 1; else fork_observation = 1;
        result = issuer ? pa_attachment_issuer_boundary() : pa_attachment_observer_boundary();
        if (observation_child) {
            assert(!result);
            assert(issuer ? pa_attachment_issuer.invalid : pa_attachment_observer.invalid);
            /* Returning to ordinary observations must not restore eligibility. */
            assert(!(issuer ? pa_attachment_issuer_boundary() : pa_attachment_observer_boundary()));
            _exit(0);
        }
        assert(result && forked_pid > 0);
        assert(waitpid(forked_pid,&status,0) == forked_pid && WIFEXITED(status) && !WEXITSTATUS(status));
        valid_check();
    } else if (!strcmp(mode,"unavailable") || !strcmp(mode,"observed-backing") ||
               !strcmp(mode,"observed-pin") || !strcmp(mode,"identity") || !strcmp(mode,"source")) {
        valid_check();
        if (!strcmp(mode,"unavailable")) observation_available = 0;
        else if (!strcmp(mode,"observed-backing")) observed.backing_sha256[0] ^= 1;
        else if (!strcmp(mode,"observed-pin")) observed.pin_sha256[0] ^= 1;
        else if (!strcmp(mode,"identity")) wrong_peer = 1;
        else source_current = 0;
        assert(!pa_attachment_observer_check());
        observed = fixture(); observation_available = source_current = 1; wrong_peer = 0;
        assert(!pa_attachment_observer_check()); assert(pa_attachment_observer.invalid);
    } else if (!strcmp(mode,"unadmitted")) {
        int second[2]; wrong_peer = 1;
        assert(socketpair(AF_UNIX,SOCK_STREAM,0,second) == 0);
        assert(!pa_attachment_issuer_accept_fd(second[1])); close(second[0]);
    } else if (!strcmp(mode,"issuer-invalid")) {
        source_current = 0; assert(!pa_attachment_issuer_boundary());
        source_current = 1; assert(!pa_attachment_issuer_boundary());
        assert(pa_attachment_issuer.invalid);
    } else {
        pthread_t thread;
        assert(!pthread_create(&thread,NULL,bad_response,(void *)mode));
        assert(!pa_attachment_observer_check()); assert(!pthread_join(thread,NULL));
        assert(pa_attachment_observer.invalid); assert(!pa_attachment_observer_check());
    }
    (void)pa_attachment_observer_reject(); (void)pa_attachment_issuer_reject();
    return 0;
}
'''


@unittest.skipUnless(sys.platform == 'darwin' and shutil.which('clang'),
                     'requires existing Apple native tools')
class AttachmentProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        parent = ROOT / 'build/attachment-protocol-unit'
        parent.mkdir(parents=True, exist_ok=True)
        cls.work = Path(tempfile.mkdtemp(dir=parent))
        source = cls.work / 'attachment.c'
        source.write_text(HARNESS)
        cls.binary = cls.work / 'attachment'
        cls.flags = ['clang', '-std=c11', '-Wall', '-Wextra', '-Werror',
                     '-Wno-deprecated-declarations', '-I' + str(SUPPORT)]
        result = subprocess.run([*cls.flags, str(source), '-framework', 'IOKit',
                                 '-framework', 'CoreFoundation', '-lbsm',
                                 '-o', str(cls.binary)], capture_output=True, text=True)
        if result.returncode:
            raise AssertionError(result.stderr)

    def run_case(self, name):
        result = subprocess.run([str(self.binary), name], capture_output=True,
                                text=True, timeout=15, cwd=self.work)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_production_components_compile_without_test_seams(self):
        result = subprocess.run([*self.flags, '-fsyntax-only',
                                 str(SUPPORT / 'attachment_provisioner.c'),
                                 str(SUPPORT / 'attachment_observer.c')],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_native_kernel_identity_and_closed_observation(self):
        self.run_case('native')

    def test_canonical_schema_and_protected_path_rejection(self):
        for name in ('codec', 'protected-path', 'pins'):
            with self.subTest(name=name):
                self.run_case(name)

    def test_valid_lease_and_retained_connection(self):
        self.run_case('valid')

    def test_wrong_response_fields_fail_closed(self):
        for name in ('challenge', 'recipient', 'boot', 'session', 'backing',
                     'backing-path', 'pin', 'deployment', 'media', 'attachment',
                     'owner', 'shadow', 'overlay', 'readonly', 'sequence', 'version'):
            with self.subTest(name=name):
                self.run_case(name)

    def test_replay_reconnect_and_stale_requests(self):
        for name in ('replay', 'reconnect', 'request-boot', 'request-session',
                     'request-sequence', 'unadmitted', 'challenge-reuse',
                     'replay-capacity', 'session-marker'):
            with self.subTest(name=name):
                self.run_case(name)

    def test_lifecycle_failure_is_permanent(self):
        for name in ('disconnect', 'fork', 'unavailable', 'observed-backing',
                     'observed-pin', 'identity', 'source', 'issuer-invalid'):
            with self.subTest(name=name):
                self.run_case(name)

    def test_inherited_descriptor_cannot_authenticate_as_parent(self):
        self.run_case('inherited-sender')

    def test_fork_during_observation_permanently_invalidates_child(self):
        for name in ('during-issuer-source', 'during-issuer-observe',
                     'during-observer-source', 'during-observer-observe'):
            with self.subTest(name=name):
                self.run_case(name)
