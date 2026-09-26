/* Private launcher implementation; never built as an importable extension. */
#include <Python.h>
#if PY_MAJOR_VERSION != 3 || PY_MINOR_VERSION != 14
#error CPython 3.14 headers required
#endif
#include <sys/types.h>
extern char **environ;

#define PA_APIS(X) \
 X(PyConfig_InitIsolatedConfig) X(PyConfig_Clear) X(PyConfig_SetString) \
 X(PyWideStringList_Append) X(Py_InitializeFromConfig) X(Py_IsInitialized) \
 X(PyStatus_Exception) X(PyImport_AddModule) X(PyModule_GetDict) \
 X(PyDict_Copy) X(PyDict_Size) X(PyDict_Next) X(PyDict_GetItem) \
 X(PyDict_GetItemString) X(PyDict_SetItemString) X(PyImport_GetModuleDict) \
 X(PyCFunction_NewEx) X(PyObject_CallNoArgs) X(Py_DecRef) X(Py_IncRef) \
 X(PyBool_FromLong) X(PyErr_Clear) X(Py_GetVersion) \
 X(PySys_GetObject) X(PyList_GetSlice) X(PyList_Size) X(PyList_GetItem)
#define PA_DECLARE(name) static __typeof__(&name) pa_##name;
PA_APIS(PA_DECLARE)
#undef PA_DECLARE

static struct {
    pid_t pid;
    int attempted, invalid, ready;
    PyObject *module, *entry, *snapshot, *path, *path_snapshot;
    char **environment;
    size_t environment_count;
} lifecycle;

static int invalidate(void) { lifecycle.invalid = 1; return 0; }
static int environment_matches(void) {
    size_t i;
    for (i = 0; environ && environ[i]; ++i)
        if (i >= lifecycle.environment_count ||
            strcmp(environ[i], lifecycle.environment[i])) return 0;
    return i == lifecycle.environment_count;
}
static int boundary(void) {
    PyObject *dict, *key, *value;
    Py_ssize_t pos = 0, i;
    if (lifecycle.invalid || !lifecycle.ready || lifecycle.pid != getpid() ||
        !environment_matches()) return invalidate();
    if (pa_PyDict_GetItemString(pa_PyImport_GetModuleDict(), "_pa_private_bootstrap")
        != lifecycle.module) return invalidate();
    if (pa_PySys_GetObject("path") != lifecycle.path ||
        pa_PyList_Size(lifecycle.path) != pa_PyList_Size(lifecycle.path_snapshot))
        return invalidate();
    for (i = 0; i < pa_PyList_Size(lifecycle.path_snapshot); ++i)
        if (pa_PyList_GetItem(lifecycle.path, i) !=
            pa_PyList_GetItem(lifecycle.path_snapshot, i)) return invalidate();
    dict = pa_PyModule_GetDict(lifecycle.module);
    if (!dict || pa_PyDict_Size(dict) != pa_PyDict_Size(lifecycle.snapshot))
        return invalidate();
    while (pa_PyDict_Next(lifecycle.snapshot, &pos, &key, &value))
        if (pa_PyDict_GetItem(dict, key) != value) return invalidate();
    return 1;
}
static PyObject *private_entry(PyObject *self, PyObject *args) {
    (void)self; (void)args;
    /* No provider activation in Phase 3. Calling this cannot qualify a process. */
    return pa_PyBool_FromLong(0);
}
static PyMethodDef entry_definition = {
    "_entry", private_entry, METH_NOARGS, NULL
};

/* Only the native launch path calls this, after all Phase-2 verifications.
 * paths must be the exact artifacts covered by runtime_artifacts verification.
 * No caller-supplied script, module, argv or environment configuration. */
static int isolated_bootstrap(void *handle, const wchar_t *const *paths, size_t count) {
    PyConfig config;
    PyStatus status;
    PyObject *dict, *result;
    size_t i;
    if (lifecycle.attempted || lifecycle.invalid) return invalidate();
    lifecycle.attempted = 1;
    lifecycle.pid = getpid();
    if (!handle || !paths || !count) return invalidate();
#define PA_RESOLVE(name) do { *(void **)(&pa_##name) = dlsym(handle, #name); \
    if (!pa_##name) return invalidate(); } while (0);
    PA_APIS(PA_RESOLVE)
#undef PA_RESOLVE
    if (strncmp(pa_Py_GetVersion(), "3.14.", 5) || pa_Py_IsInitialized())
        return invalidate();
    for (i = 0; i < count; ++i)
        if (!paths[i] || paths[i][0] != L'/') return invalidate();
    for (i = 0; environ && environ[i]; ++i) {}
    lifecycle.environment_count = i;
    lifecycle.environment = calloc(i + 1, sizeof(char *));
    if (!lifecycle.environment) return invalidate();
    for (i = 0; i < lifecycle.environment_count; ++i) {
        size_t length = strlen(environ[i]) + 1;
        lifecycle.environment[i] = malloc(length);
        if (!lifecycle.environment[i]) return invalidate();
        memcpy(lifecycle.environment[i], environ[i], length);
    }
    pa_PyConfig_InitIsolatedConfig(&config);
    config.use_environment = 0;
    config.site_import = 0;
    config.user_site_directory = 0;
    config.parse_argv = 0;
    config.safe_path = 1;
    config.write_bytecode = 0;
    config.install_signal_handlers = 0;
    config.module_search_paths_set = 1;
    status = pa_PyConfig_SetString(&config, &config.program_name, L"restricted-launcher");
    for (i = 0; !pa_PyStatus_Exception(status) && i < count; ++i)
        status = pa_PyWideStringList_Append(&config.module_search_paths, paths[i]);
    if (!pa_PyStatus_Exception(status)) status = pa_Py_InitializeFromConfig(&config);
    pa_PyConfig_Clear(&config);
    if (pa_PyStatus_Exception(status)) return invalidate();
    lifecycle.module = pa_PyImport_AddModule("_pa_private_bootstrap");
    if (!lifecycle.module) return invalidate();
    pa_Py_IncRef(lifecycle.module);
    dict = pa_PyModule_GetDict(lifecycle.module);
    lifecycle.entry = pa_PyCFunction_NewEx(&entry_definition, NULL, NULL);
    if (!dict || !lifecycle.entry ||
        pa_PyDict_SetItemString(dict, "_entry", lifecycle.entry) < 0)
        return invalidate();
    lifecycle.snapshot = pa_PyDict_Copy(dict);
    if (!lifecycle.snapshot) return invalidate();
    lifecycle.path = pa_PySys_GetObject("path");
    if (!lifecycle.path) return invalidate();
    pa_Py_IncRef(lifecycle.path);
    lifecycle.path_snapshot = pa_PyList_GetSlice(lifecycle.path, 0,
                                               pa_PyList_Size(lifecycle.path));
    if (!lifecycle.path_snapshot) return invalidate();
    lifecycle.ready = 1;
    if (!boundary()) return 0;
    result = pa_PyObject_CallNoArgs(lifecycle.entry);
    if (!result) { pa_PyErr_Clear(); return invalidate(); }
    pa_Py_DecRef(result);
    return boundary();
}
