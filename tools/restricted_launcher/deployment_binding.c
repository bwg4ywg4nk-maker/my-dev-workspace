/* Strict native consumer of _deployment_binding.collect's canonical schema.
 * Compare each field to independently compiled deployment inputs and live pins.
 * No generic JSON parser, duplicate keys, unknown fields or coercions. */
#define PA_NATIVE_BINDING_ADAPTER 1
struct pa_binding_cursor { const unsigned char *p; size_t left; };
static int binding_take(struct pa_binding_cursor *c, const void *p, size_t n) {
    if (n > c->left || memcmp(c->p,p,n)) return 0;
    c->p += n; c->left -= n; return 1;
}
static int binding_literal(struct pa_binding_cursor *c, const char *s) {
    return binding_take(c,s,strlen(s));
}
static int binding_hex(struct pa_binding_cursor *c, const unsigned char *p, size_t n) {
    static const char digits[] = "0123456789abcdef";
    size_t i;
    for (i = 0; i < n; ++i) {
        char pair[2] = {digits[p[i] >> 4],digits[p[i] & 15]};
        if (!binding_take(c,pair,2)) return 0;
    }
    return 1;
}
static int binding_string(struct pa_binding_cursor *c, const char *s) {
    size_t i, n = strnlen(s,1024);
    if (!n || n == 1024 || !binding_literal(c,"\"")) return 0;
    for (i = 0; i < n; ++i) {
        unsigned char ch = (unsigned char)s[i];
        if (ch < 32 || ch > 126) return 0;
        if ((ch == '"' || ch == '\\') && !binding_literal(c,"\\")) return 0;
        if (!binding_take(c,&ch,1)) return 0;
    }
    return binding_literal(c,"\"");
}
static int native_binding_verify(const struct pa_attachment_binding *b,
                                  const char *pins, size_t pins_size) {
    const struct pa_native_binding *n = b->native;
    const struct pa_startup_binding *s = attachment_launch.checks->startup;
    const struct pa_attachment_record *r = &pa_attachment_observer.source.record;
    struct pa_binding_cursor c;
    unsigned char digest[32]; size_t i, j; uint32_t images, maps, launchers = 0;
    if (!n || !n->bytes || !n->launcher || !s || !s->bytes ||
        n->size > 2 * (PA_STARTUP_HEADER + PA_MAX_IMAGES * PA_STARTUP_IMAGE +
                       256 * PA_STARTUP_MAPPING) + 131072 ||
        !CC_SHA256(n->bytes,(CC_LONG)n->size,digest) ||
        !pa_attachment_nonzero(n->sha256,32) || memcmp(digest,n->sha256,32) ||
        s->size < PA_STARTUP_HEADER || memcmp(s->bytes,"PAEXEC01",8) ||
        !pa_attachment_nonzero(s->bytes+40,20)) return 0;
    images = startup_u32(s->bytes+60); maps = startup_u32(s->bytes+64);
    if (images < 2 || images > PA_MAX_IMAGES || !maps || maps > 256 ||
        s->size != PA_STARTUP_HEADER + images * PA_STARTUP_IMAGE + maps * PA_STARTUP_MAPPING)
        return 0;
    /* No system/shared-cache path exception: every named startup image must
     * remain on the protected deployment, even when the loader knows it. */
    for (i = 0; i < images; ++i) {
        const unsigned char *record = s->bytes + PA_STARTUP_HEADER + i * PA_STARTUP_IMAGE;
        const char *path = (const char *)record+4;
        size_t len = strnlen(path,4096);
        uint32_t kind = startup_u32(record);
        if (len >= 1024 || kind > 2 || !startup_u64(record+4164) ||
            !pa_attachment_nonzero(record+4132,32) ||
            !attachment_launch_path(path,0,record+4100)) return 0;
        for (j = len; j < 4096; ++j) if (path[j]) return 0;
        for (j = 0; j < i; ++j)
            if (!strcmp(path,(const char *)s->bytes+PA_STARTUP_HEADER+j*PA_STARTUP_IMAGE+4)) return 0;
        if (!kind) { ++launchers; if (strcmp(path,n->launcher)) return 0; }
    }
    if (launchers != 1) return 0;
    c.p = n->bytes; c.left = n->size;
    if (!binding_literal(&c,"{\"attachment_pin_sha256\":\"") ||
        !binding_hex(&c,r->pin_sha256,32) ||
        !binding_literal(&c,"\",\"deployment_sha256\":\"") ||
        !binding_hex(&c,b->deployment_sha256,32) ||
        !binding_literal(&c,"\",\"kind\":\"trusted-admin-deployment-binding-v1\",\"launch_policy_sha256\":\"") ||
        !binding_hex(&c,b->policy_sha256,32) ||
        !binding_literal(&c,"\",\"launcher\":") || !binding_string(&c,n->launcher) ||
        !binding_literal(&c,",\"module_paths\":[")) return 0;
    for (i = 0; i < b->module_count; ++i) {
        char path[1024];
        for (j = 0; j < sizeof(path); ++j) {
            wchar_t ch = b->modules[i][j];
            if (ch < 0 || ch > 127) return 0;
            path[j] = (char)ch; if (!ch) break;
        }
        if (j == sizeof(path) || (i && !binding_literal(&c,",")) ||
            !binding_string(&c,path)) return 0;
        for (j = 0; j < i; ++j) if (!wcscmp(b->modules[i],b->modules[j])) return 0;
    }
    return binding_literal(&c,"],\"protected_deployment\":") &&
        binding_take(&c,pins,pins_size) &&
        binding_literal(&c,",\"python_framework\":") && binding_string(&c,b->framework) &&
        binding_literal(&c,",\"python_interpreter\":") && binding_string(&c,b->python) &&
        binding_literal(&c,",\"startup_inventory\":{\"bytes_hex\":\"") &&
        binding_hex(&c,s->bytes,s->size) &&
        binding_literal(&c,"\",\"deployment_sha256\":\"") &&
        binding_hex(&c,b->deployment_sha256,32) &&
        binding_literal(&c,"\",\"launcher_cdhash\":\"") && binding_hex(&c,s->bytes+40,20) &&
        binding_literal(&c,"\",\"sha256\":\"") && binding_hex(&c,s->sha256,32) &&
        binding_literal(&c,"\"}}") && !c.left;
}
