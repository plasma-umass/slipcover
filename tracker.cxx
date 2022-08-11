#define PY_SSIZE_T_CLEAN    // programmers love obscure statements
#include <Python.h>
#include <algorithm>
#include "pyptr.h"


/**
 * Tracks code coverage.
 */
class Tracker {
    PyPtr<> _sci;
    PyPtr<> _filename;
    PyPtr<> _lineno_or_branch;
    bool _signalled;
    bool _instrumented;
    int _d_miss_count;
    int _u_miss_count;
    int _hit_count;
    int _d_threshold;

public:
    Tracker(PyObject* sci, PyObject* filename, PyObject* lineno_or_branch, PyObject* d_threshold):
        _sci(PyPtr<>::borrowed(sci)), _filename(PyPtr<>::borrowed(filename)),
        _lineno_or_branch(PyPtr<>::borrowed(lineno_or_branch)),
        _signalled(false), _instrumented(true),
        _d_miss_count(-1), _u_miss_count(0), _hit_count(0),
        _d_threshold(PyLong_AsLong(d_threshold)) {}


    static PyObject*
    newCapsule(Tracker* t) {
        return PyCapsule_New(t, NULL,
                             [](PyObject* cap) {
                                 delete (Tracker*)PyCapsule_GetPointer(cap, NULL);
                             });
    }


    PyObject* signal() {
        if (!_signalled) {
            _signalled = true;

            PyPtr<> newly_seen = PyObject_GetAttrString(_sci, "newly_seen");
            if (!newly_seen) {
                PyErr_SetString(PyExc_Exception, "newly_seen missing");
                return NULL;
            }

            PyPtr<> newly_seen_for_file = PyObject_GetItem(newly_seen, _filename);
            if (!newly_seen_for_file) {
                PyErr_SetString(PyExc_Exception, "newly_seen_for_file missing");
                return NULL;
            }

            if (PySet_Add(newly_seen_for_file, _lineno_or_branch) < 0) {
                PyErr_SetString(PyExc_Exception, "Unable to add to set");
                return NULL;
            }
        }

        if (_instrumented) {
            // Limit D misses by deinstrumenting once we see several for a line
            // Any other lines getting D misses get deinstrumented at the same time,
            // so this needn't be a large threshold.
            if (++_d_miss_count == _d_threshold) {
                PyPtr<> deinstrument_seen = PyUnicode_FromString("deinstrument_seen");
                PyPtr<> result = PyObject_CallMethodObjArgs(_sci, deinstrument_seen, NULL);
            }
        }
        else {
            ++_u_miss_count;
        }

        Py_RETURN_NONE;
    }


    PyObject* hit() {
        ++_hit_count;
        Py_RETURN_NONE;
    }


    PyObject* deinstrument() {
        _instrumented = false;
        Py_RETURN_NONE;
    }


    PyObject* get_stats() {
        PyPtr<> d_miss_count = PyLong_FromLong(std::max(_d_miss_count, 0));
        PyPtr<> u_miss_count = PyLong_FromLong(_u_miss_count);
        PyPtr<> total_count = PyLong_FromLong(1 + _d_miss_count + _u_miss_count + _hit_count);
        return PyTuple_Pack(5, (PyObject*)_filename, (PyObject*)_lineno_or_branch,
                            (PyObject*)d_miss_count, (PyObject*)u_miss_count,
                            (PyObject*)total_count);
    }

    PyObject* is_instrumented() {
        if (_instrumented) {
            Py_RETURN_TRUE;
        }
        Py_RETURN_FALSE;
    }
};


PyObject*
tracker_register(PyObject* self, PyObject* const* args, Py_ssize_t nargs) {
    if (nargs < 4) {
        PyErr_SetString(PyExc_Exception, "Missing argument(s)");
        return NULL;
    }

    return Tracker::newCapsule(new Tracker(args[0], args[1], args[2], args[3]));
}

#define METHOD_WRAPPER(method) \
    static PyObject*\
    tracker_##method(PyObject* self, PyObject* const* args, Py_ssize_t nargs) {\
        if (nargs < 1) {\
            PyErr_SetString(PyExc_Exception, "Missing argument");\
            return NULL;\
        }\
    \
        return static_cast<Tracker*>(PyCapsule_GetPointer(args[0], NULL))->method();\
    }

METHOD_WRAPPER(signal);
METHOD_WRAPPER(hit);
METHOD_WRAPPER(deinstrument);
METHOD_WRAPPER(get_stats);
METHOD_WRAPPER(is_instrumented);


static PyMethodDef methods[] = {
    {"register",     (PyCFunction)tracker_register, METH_FASTCALL, "registers a new tracker"},
    {"signal",       (PyCFunction)tracker_signal, METH_FASTCALL, "signals the line was reached"},
    {"hit",          (PyCFunction)tracker_hit, METH_FASTCALL, "signals the line was reached after full deinstrumentation"},
    {"deinstrument", (PyCFunction)tracker_deinstrument, METH_FASTCALL, "marks a tracker deinstrumented"},
    {"get_stats",    (PyCFunction)tracker_get_stats, METH_FASTCALL, "returns tracker stats"},
    {"is_instrumented", (PyCFunction)tracker_is_instrumented, METH_FASTCALL, "returns whether tracker is instrumented"},
    {NULL, NULL, 0, NULL}
};


static struct PyModuleDef tracker_module = {
    PyModuleDef_HEAD_INIT,
    "tracker",
    NULL, // no documentation
    -1,
    methods,
    NULL,
    NULL,
    NULL,
    NULL
};


PyMODINIT_FUNC
PyInit_tracker() {
    PyObject* m = PyModule_Create(&tracker_module);
    if (m == nullptr) {
        return nullptr;
    }

    return m;
}

