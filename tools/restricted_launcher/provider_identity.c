/* Private v2 identity consumer. Its bytes and hashes are authenticated by the
 * independently pinned package, never by a Python return value. All file reads
 * use the same protected namespace and retained attachment as the bootstrap. */
#include <dirent.h>
#include <errno.h>

static int provider_document(struct pa_binding_cursor *c,
                             const struct pa_identity_document *d, int profile) {
    unsigned char hash[32]; CC_SHA256_CTX ctx;
    static const char ns[] = "presentation-agent:layout-profile:v1";
    if (!d->bytes || !d->size || d->size > 50000 ||
        !pa_attachment_nonzero(d->sha256,32) || !CC_SHA256_Init(&ctx) ||
        (profile && !CC_SHA256_Update(&ctx,ns,sizeof(ns))) ||
        !CC_SHA256_Update(&ctx,d->bytes,(CC_LONG)d->size) ||
        !CC_SHA256_Final(hash,&ctx) || memcmp(hash,d->sha256,32)) return 0;
    return binding_literal(c,"{\"bytes_hex\":\"") &&
        binding_hex(c,d->bytes,d->size) && binding_literal(c,"\",\"sha256\":\"") &&
        binding_hex(c,d->sha256,32) && binding_literal(c,"\"}");
}
static const struct pa_provider_artifact *provider_role(
        const struct pa_provider_identity *p, const char *role) {
    size_t i;
    for (i = 0; i < p->count; ++i)
        if (!strcmp(p->artifacts[i].role,role)) return &p->artifacts[i];
    return NULL;
}
/* Locate a canonical field in already authenticated, bounded document bytes.
 * Offline derivation validates the complete frozen schema; these additional
 * comparisons bind the native file table and the three document identities. */
static int provider_field(struct pa_binding_cursor *c,
                          const struct pa_identity_document *d, const char *field) {
    size_t i, n = strlen(field), found = 0;
    if (!d->bytes || d->size > 50000) return 0;
    for (i = 0; i + n <= d->size; ++i)
        if (!memcmp(d->bytes+i,field,n)) {
            c->p = d->bytes+i+n; c->left = d->size-i-n; ++found;
        }
    return found == 1;
}
static int provider_digest_field(const struct pa_identity_document *d,
                                  const char *field, const unsigned char *hash) {
    struct pa_binding_cursor c;
    return provider_field(&c,d,field) && binding_hex(&c,hash,32) && binding_literal(&c,"\"");
}
static int provider_manifest(const struct pa_provider_identity *p, int runtime) {
    struct pa_binding_cursor c;
    size_t i, count = 0; int inserted = 0;
    const char *prefix = runtime ? "native:" : "build:";
    size_t length = strlen(prefix);
    if (!provider_field(&c,runtime ? &p->runtime : &p->build,
                        runtime ? "\"native_runtime_artifacts\":[" : "\"artifacts\":[")) return 0;
    for (i = 0; i < p->count; ++i) {
        const struct pa_provider_artifact *a = p->artifacts+i;
        const char *name;
        if (strncmp(a->role,prefix,length)) continue;
        name = a->role+length;
        if (runtime && !inserted && strcmp(name,"deployment-evidence") > 0) {
            if ((count && !binding_literal(&c,",")) ||
                !binding_literal(&c,"[\"deployment-evidence\",\"") ||
                !binding_hex(&c,p->deployment_document_sha256,32) ||
                !binding_literal(&c,"\"]")) return 0;
            inserted = 1; ++count;
        }
        if ((count && !binding_literal(&c,",")) || !binding_literal(&c,"[") ||
            !binding_string(&c,name) || !binding_literal(&c,",\"") ||
            !binding_hex(&c,a->sha256,32) || !binding_literal(&c,"\"]")) return 0;
        ++count;
    }
    return count && (!runtime || inserted) && binding_literal(&c,"]");
}
static int provider_module_path(const struct pa_attachment_binding *b,
                                size_t index, char path[1024]) {
    size_t i;
    for (i = 0; i < 1024; ++i) {
        wchar_t ch = b->modules[index][i];
        if (ch < 0 || ch > 127) return 0;
        path[i] = (char)ch;
        if (!ch) return 1;
    }
    return 0;
}
static int provider_tree(const struct pa_provider_identity *p, const char *path,
                         unsigned depth, size_t *visited) {
    DIR *directory; struct dirent *entry; struct stat st;
    char child[1024]; size_t i; int ok = 1, found;
    if (depth > 64 || ++*visited > 16384 || !attachment_launch_path(path,1,NULL) ||
        !(directory = opendir(path))) return 0;
    for (;;) {
        errno = 0;
        entry = readdir(directory);
        if (!entry) { if (errno) ok = 0; break; }
        if (!strcmp(entry->d_name,".") || !strcmp(entry->d_name,"..")) continue;
        if (snprintf(child,sizeof(child),"%s/%s",path,entry->d_name) >= (int)sizeof(child) ||
            lstat(child,&st)) { ok = 0; break; }
        if (S_ISDIR(st.st_mode)) {
            if (!provider_tree(p,child,depth+1,visited)) { ok = 0; break; }
        } else {
            found = 0;
            for (i = 0; i < p->count; ++i)
                if (!strncmp(p->artifacts[i].role,"module:",7) &&
                    !strcmp(child,p->artifacts[i].path)) ++found;
            if (!S_ISREG(st.st_mode) || found != 1 || ++*visited > 16384) { ok = 0; break; }
        }
    }
    if (closedir(directory)) ok = 0;
    return ok;
}
static int provider_identity_verify(struct pa_binding_cursor *c,
                                     const struct pa_attachment_binding *b,
                                     const char *pins) {
    static const unsigned char font[32] = {
        0x52,0x59,0x79,0x82,0x25,0x91,0xa3,0x44,0x7c,0xfc,0x49,0xd9,0x43,0xd6,0xf7,0x68,
        0x35,0x08,0xe2,0x55,0x43,0x40,0x78,0x71,0xc0,0xed,0x8f,0xed,0x05,0xfd,0x2b,0xd9 };
    const struct pa_provider_identity *p = b->native->provider;
    const struct pa_provider_artifact *a;
    static const char *required[] = {"build:freetype-static", "build:imaging", "build:imagingft",
        "build:measurement-adapter", "build:audit-schema", "native:bootstrap", "native:launcher",
        "native:python-interpreter", "native:python-framework", "native:loader", "native:c-runtime",
        "native:imaging", "native:imagingft", "font"};
    char build_pin[84] = "\"build_sha256\":\"", path[1024], role[1024];
    size_t i, j, visited = 0;
    if (!p || !p->artifacts || !p->count || p->count > 4096 ||
        memcmp(p->font_sha256,font,32) ||
        !pa_attachment_nonzero(p->adapter_sha256,32) ||
        !pa_attachment_nonzero(p->build_evidence_sha256,32) ||
        !pa_attachment_nonzero(p->deployment_document_sha256,32)) return 0;
    for (i = 0; i < 32; ++i) snprintf(build_pin+16+2*i,3,"%02x",p->build_evidence_sha256[i]);
    build_pin[80] = '"'; build_pin[81] = 0;
    if (!strstr(pins,build_pin) ||
        !binding_literal(c,"{\"adapter_sha256\":\"") || !binding_hex(c,p->adapter_sha256,32) ||
        !binding_literal(c,"\",\"artifacts\":[")) return 0;
    for (i = 0; i < p->count; ++i) {
        a = p->artifacts+i;
        if (!a->role || !a->path || !a->role[0] || strnlen(a->role,1024) == 1024 ||
            (i && strcmp(p->artifacts[i-1].role,a->role) >= 0) ||
            !attachment_launch_path(a->path,0,a->sha256) ||
            (i && !binding_literal(c,",")) || !binding_literal(c,"[") ||
            !binding_string(c,a->role) || !binding_literal(c,",") ||
            !binding_string(c,a->path) || !binding_literal(c,",\"") ||
            !binding_hex(c,a->sha256,32) || !binding_literal(c,"\"]")) return 0;
        if (!strncmp(a->role,"module:",7)) {
            int found = 0;
            for (j = 0; j < b->module_count; ++j) {
                size_t n;
                if (!provider_module_path(b,j,path)) return 0;
                n = strlen(path);
                if (strncmp(a->path,path,n) || a->path[n] != '/') continue;
                if (snprintf(role,sizeof(role),"module:%zu:%s",j,a->path+n+1) >= (int)sizeof(role)) return 0;
                if (!strcmp(role,a->role)) ++found;
            }
            if (found != 1) return 0;
        } else if (strncmp(a->role,"build:",6) && strncmp(a->role,"native:",7) &&
                   strcmp(a->role,"font")) return 0;
    }
    for (i = 0; i < sizeof(required)/sizeof(*required); ++i)
        if (!provider_role(p,required[i])) return 0;
    for (i = 0; i < 2; ++i) {
        const struct pa_provider_artifact *build = provider_role(p,i ? "build:imagingft" : "build:imaging");
        const struct pa_provider_artifact *runtime = provider_role(p,i ? "native:imagingft" : "native:imaging");
        if (strcmp(build->path,runtime->path) || memcmp(build->sha256,runtime->sha256,32)) return 0;
    }
    a = provider_role(p,"build:measurement-adapter");
    for (i = 0; i < p->count; ++i)
        if (!strncmp(p->artifacts[i].role,"module:",7) &&
            !strcmp(p->artifacts[i].path,a->path) && !memcmp(p->artifacts[i].sha256,a->sha256,32)) break;
    if (i == p->count) return 0;
    if (memcmp(provider_role(p,"font")->sha256,font,32) ||
        memcmp(provider_role(p,"build:measurement-adapter")->sha256,p->adapter_sha256,32) ||
        strcmp(provider_role(p,"native:launcher")->path,b->native->launcher) ||
        strcmp(provider_role(p,"native:bootstrap")->path,b->native->launcher) ||
        strcmp(provider_role(p,"native:python-framework")->path,b->framework) ||
        strcmp(provider_role(p,"native:python-interpreter")->path,b->python) ||
        !provider_manifest(p,0) || !provider_manifest(p,1) ||
        !provider_digest_field(&p->profile,"\"build_id\":\"sha256:",p->build.sha256) ||
        !provider_digest_field(&p->profile,"\"runtime_id\":\"sha256:",p->runtime.sha256) ||
        !provider_digest_field(&p->profile,"\"sha256\":\"",font)) return 0;
    for (i = 0; i < b->module_count; ++i)
        if (!provider_module_path(b,i,path) || !provider_tree(p,path,0,&visited)) return 0;
    return binding_literal(c,"],\"build_evidence_sha256\":\"") &&
        binding_hex(c,p->build_evidence_sha256,32) && binding_literal(c,"\",\"build_manifest\":") &&
        provider_document(c,&p->build,0) &&
        binding_literal(c,",\"deployment_document_sha256\":\"") &&
        binding_hex(c,p->deployment_document_sha256,32) &&
        binding_literal(c,"\",\"font_sha256\":\"") && binding_hex(c,font,32) &&
        binding_literal(c,"\",\"kind\":\"protected-provider-identity-v1\",\"profile\":") &&
        provider_document(c,&p->profile,1) && binding_literal(c,",\"runtime_manifest\":") &&
        provider_document(c,&p->runtime,0) && binding_literal(c,"}");
}
