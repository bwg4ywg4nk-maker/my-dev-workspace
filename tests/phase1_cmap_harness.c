/* Test-only fake FreeType face: exercises production audit error paths.
 * No font parser, provider, or native build qualification is simulated.
 */
#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <string.h>
#define FT_TRUETYPE_TABLES_H <stddef.h>
#define LAYOUT_FALLBACK 0
#define FT_ENCODING_UNICODE 0x756e6963UL
typedef unsigned int FT_UInt;
typedef unsigned long FT_ULong;
typedef long FT_Long;
typedef struct Face *FT_Face;
typedef struct Map {
    FT_Face face;
    unsigned short platform_id, encoding_id;
    unsigned long encoding;
    long format;
    int index;
} *FT_CharMap;
struct Face {
    FT_CharMap charmap;
    FT_CharMap *charmaps;
    int num_charmaps;
    long num_glyphs;
};
typedef struct {
    PyObject_HEAD
    FT_Face face;
    int layout_engine;
} FontObject;
static PyTypeObject HarnessFont_Type = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "_phase1_cmap_harness.Font",
    .tp_basicsize = sizeof(FontObject),
    .tp_flags = Py_TPFLAGS_DEFAULT,
};
static int mode, calls, allocations, fail_allocation;

static int FT_Set_Charmap(FT_Face face, FT_CharMap map) {
    calls++;
    /* mode 1 fails switching to second map, mode 2 fails restoration. */
    if ((mode == 1 && map->index == 1) || (mode == 2 && calls >= 3)) {
        return 1;
    }
    face->charmap = map;
    return 0;
}
static FT_UInt FT_Get_Char_Index(FT_Face face, FT_ULong cp) {
    if (cp < 32 || cp > 126) {
        Py_FatalError("unbounded codepoint in audit");
    }
    if (mode == 3 && face->charmap->index == 1) {
        return 0;
    }
    if (mode == 4 && face->charmap->index == 1) {
        return (FT_UInt)cp + 1;
    }
    if (mode == 5 && calls >= 3) {
        return (FT_UInt)cp + 1;
    }
    return (FT_UInt)cp;
}
static FT_Long FT_Get_CMap_Format(FT_CharMap map) {
    return map->format;
}
static int allocation_fails(void) {
    return ++allocations == fail_allocation;
}
#define PyTuple_New(n) (allocation_fails() ? PyErr_NoMemory() : PyTuple_New(n))
#define PyLong_FromUnsignedLong(n) \
    (allocation_fails() ? PyErr_NoMemory() : PyLong_FromUnsignedLong(n))
#define Py_BuildValue(...) \
    (allocation_fails() ? PyErr_NoMemory() : Py_BuildValue(__VA_ARGS__))
#include "pa_cmap_audit.h"
#undef PyTuple_New
#undef PyLong_FromUnsignedLong
#undef Py_BuildValue

static PyObject *exercise(PyObject *unused, PyObject *args) {
    struct Face face;
    struct Map maps[2];
    FT_CharMap pointers[2] = {&maps[0], &maps[1]};
    FontObject *font;
    PyObject *result, *error_type = NULL, *error_value = NULL, *traceback = NULL;
    PyObject *error_text, *output;
    int i;
    if (!PyArg_ParseTuple(args, "ii", &mode, &fail_allocation)) {
        return NULL;
    }
    calls = allocations = 0;
    face.charmap = &maps[0];
    face.charmaps = pointers;
    face.num_charmaps = 2;
    face.num_glyphs = 256;
    for (i = 0; i < 2; i++) {
        maps[i].face = &face;
        maps[i].platform_id = 3;
        maps[i].encoding_id = i ? 10 : 1;
        maps[i].encoding = FT_ENCODING_UNICODE;
        maps[i].format = i ? 12 : 4;
        maps[i].index = i;
    }
    if (mode == 6) {
        maps[1].format = 14;
    }
    if (mode == 7) {
        face.num_charmaps = 257;
    }
    if (mode == 8) {
        face.charmap = &maps[1];
    }
    if (mode == 9) {
        maps[1].platform_id = 1;
        maps[1].encoding_id = 0;
        maps[1].encoding = 0;
    }
    if (mode == 10) {
        pointers[1] = pointers[0];
    }
    font = PyObject_New(FontObject, &HarnessFont_Type);
    if (!font) {
        return NULL;
    }
    font->face = &face;
    font->layout_engine = LAYOUT_FALLBACK;
    result = pa_cmap_audit(font, NULL);
    PyObject_Del(font);
    if (!result) {
        if (!PyErr_Occurred()) {
            Py_FatalError("audit failed without exception");
        }
        PyErr_Fetch(&error_type, &error_value, &traceback);
        PyErr_NormalizeException(&error_type, &error_value, &traceback);
        error_text = PyObject_Str(error_value);
        Py_XDECREF(error_type);
        Py_XDECREF(error_value);
        Py_XDECREF(traceback);
        result = Py_NewRef(Py_None);
    } else {
        error_text = Py_NewRef(Py_None);
    }
    output = Py_BuildValue("(OOiii)", result, error_text, face.charmap->index,
                           calls, allocations);
    Py_DECREF(result);
    Py_XDECREF(error_text);
    return output;
}
static PyMethodDef methods[] = {
    {"exercise", exercise, METH_VARARGS, NULL},
    {NULL, NULL, 0, NULL}
};
static struct PyModuleDef module = {
    PyModuleDef_HEAD_INIT, "_phase1_cmap_harness", NULL, -1, methods
};
PyMODINIT_FUNC PyInit__phase1_cmap_harness(void) {
    if (PyType_Ready(&HarnessFont_Type) < 0) {
        return NULL;
    }
    return PyModule_Create(&module);
}
