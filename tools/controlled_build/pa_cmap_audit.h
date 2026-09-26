/* Private Phase-1 addition to Pillow 12.3.0. Included after FontObject.
 * No new face/library, arbitrary query, pointer, setter, or trust token.
 * All face access stays inside Pillow's per-object critical section.
 */
#include FT_TRUETYPE_TABLES_H

#define PA_MAX_CHARMAPS 256
#define PA_ASCII_COUNT 95

static int
pa_ascii(FT_Face face, FT_UInt out[PA_ASCII_COUNT]) {
    int i;
    for (i = 0; i < PA_ASCII_COUNT; i++) {
        out[i] = FT_Get_Char_Index(face, (FT_ULong)(32 + i));
        if (!out[i] || out[i] >= (FT_ULong)face->num_glyphs || out[i] > 65535) {
            return 0;
        }
    }
    return 1;
}

static PyObject *
pa_glyph_tuple(const FT_UInt glyphs[PA_ASCII_COUNT]) {
    PyObject *result = PyTuple_New(PA_ASCII_COUNT);
    int i;
    if (!result) {
        return NULL;
    }
    for (i = 0; i < PA_ASCII_COUNT; i++) {
        PyObject *item = PyLong_FromUnsignedLong(glyphs[i]);
        if (!item) {
            Py_DECREF(result);
            return NULL;
        }
        PyTuple_SET_ITEM(result, i, item);
    }
    return result;
}

static PyObject *
pa_cmap_audit_impl(FontObject *self) {
    FT_Face face = self->face;
    FT_CharMap saved = NULL;
    FT_UInt original[PA_ASCII_COUNT], restored[PA_ASCII_COUNT];
    FT_UInt mapping[PA_ASCII_COUNT];
    PyObject *maps = NULL, *before = NULL, *after = NULL, *result = NULL;
    int i, j, selected = -1, eligible_count = 0, selected_eligible = 0;
    const char *failure = NULL;

    if (!face || !face->charmap || !face->charmaps ||
        face->num_charmaps < 1 || face->num_charmaps > PA_MAX_CHARMAPS ||
        face->num_glyphs < 1 || face->num_glyphs > 65535 ||
        self->layout_engine != LAYOUT_FALLBACK) {
        PyErr_SetString(PyExc_ValueError, "Unsupported bounded cmap audit face");
        return NULL; /* No mutation has occurred. */
    }
    saved = face->charmap;
    for (i = 0; i < face->num_charmaps; i++) {
        if (face->charmaps[i] == saved) {
            if (selected != -1) {
                failure = "Duplicate selected native charmap";
                goto restore;
            }
            selected = i;
        }
    }
    if (selected < 0 || !pa_ascii(face, original)) {
        failure = "Invalid original native charmap";
        goto restore;
    }
    maps = PyTuple_New(face->num_charmaps);
    if (!maps) {
        goto restore;
    }
    for (i = 0; i < face->num_charmaps; i++) {
        FT_CharMap map = face->charmaps[i];
        FT_Long format;
        int eligible;
        PyObject *glyphs, *descriptor;
        if (!map || map->face != face) {
            failure = "Invalid native charmap";
            goto restore;
        }
        format = FT_Get_CMap_Format(map);
        eligible = map->platform_id == 0 ||
            (map->platform_id == 3 && (map->encoding_id == 1 || map->encoding_id == 10));
        if (format < 0 || format > 65535 || format == 14 ||
            (map->platform_id == 0 && map->encoding_id > 4 && map->encoding_id != 6)) {
            failure = "Unsupported native charmap descriptor";
            goto restore;
        }
        if (eligible) {
            if ((format != 4 && format != 12) || map->encoding != FT_ENCODING_UNICODE ||
                FT_Set_Charmap(face, map) || face->charmap != map ||
                !pa_ascii(face, mapping)) {
                failure = "Native Unicode cmap audit failed";
                goto restore;
            }
            for (j = 0; j < PA_ASCII_COUNT; j++) {
                if (mapping[j] != original[j]) {
                    failure = "Native ASCII cmap disagreement";
                    goto restore;
                }
            }
            eligible_count++;
            if (i == selected) {
                selected_eligible = 1;
            }
            glyphs = pa_glyph_tuple(mapping);
        } else {
            glyphs = PyTuple_New(0);
        }
        if (!glyphs) {
            goto restore;
        }
        descriptor = Py_BuildValue("(iiiKlO)", i, (int)map->platform_id,
                                   (int)map->encoding_id,
                                   (unsigned long long)map->encoding, format, glyphs);
        Py_DECREF(glyphs);
        if (!descriptor) {
            goto restore;
        }
        PyTuple_SET_ITEM(maps, i, descriptor);
    }
    if (!eligible_count || !selected_eligible) {
        failure = "Original map is not an eligible Unicode map";
    }

restore:
    /* No Python allocation or return can bypass this restoration attempt.
     * A failed restore produces no result and cannot certify any measurement.
     */
    if (FT_Set_Charmap(face, saved) || face->charmap != saved) {
        PyErr_Clear();
        failure = "Native charmap restoration failed";
    }
    if (failure) {
        PyErr_SetString(PyExc_ValueError, failure);
    }
    if (PyErr_Occurred()) {
        goto done;
    }
    if (!pa_ascii(face, restored) || memcmp(original, restored, sizeof(original))) {
        PyErr_SetString(PyExc_ValueError, "Restored native ASCII glyphs changed");
        goto done;
    }
    before = pa_glyph_tuple(original);
    if (!before) {
        goto done;
    }
    after = pa_glyph_tuple(restored);
    if (!after) {
        goto done;
    }
    result = Py_BuildValue("(iOiOiO)", face->num_charmaps, maps,
                           selected, before, selected, after);
done:
    Py_XDECREF(maps);
    Py_XDECREF(before);
    Py_XDECREF(after);
    return result;
}

static PyObject *
pa_cmap_audit(FontObject *self, PyObject *Py_UNUSED(unused)) {
    PyObject *result;
    Py_BEGIN_CRITICAL_SECTION(self);
    result = pa_cmap_audit_impl(self);
    Py_END_CRITICAL_SECTION();
    return result;
}
