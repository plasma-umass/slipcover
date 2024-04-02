#define PY_SSIZE_T_CLEAN    // programmers love obscure statements
#include <Python.h>
#include <algorithm>
#include "pyptr.h"
#ifndef PYPY_VERSION
    #include "opcode.h"
#endif


/**
 * Tracks code coverage.
 */
class Probe {
    PyPtr<> _sci;
    PyPtr<> _filename;
    PyPtr<> _lineno_or_branch;
    bool _signalled;
    bool _removed;
    int _d_miss_count;
    int _d_miss_threshold;
    std::byte* _code;

public:
    Probe(PyObject* sci, PyObject* filename, PyObject* lineno_or_branch, PyObject* d_miss_threshold):
        _sci(PyPtr<>::borrowed(sci)), _filename(PyPtr<>::borrowed(filename)),
        _lineno_or_branch(PyPtr<>::borrowed(lineno_or_branch)),
        _signalled(false), _removed(false),
        _d_miss_count(-1),
        _d_miss_threshold(PyLong_AsLong(d_miss_threshold)), _code(nullptr) {}


    static PyObject*
    newCapsule(Probe* p) {
        return PyCapsule_New(p, NULL,
                             [](PyObject* cap) {
                                 delete (Probe*)PyCapsule_GetPointer(cap, NULL);
                             });
    }


    PyObject* signal() {
        // _d_miss_threshold == -1 means de-instrument (disable) this block,
        //      but don't de-instrument Python;
        // _d_miss_threshold == -2 means don't de-instrument either
        if (!_signalled || (_code == nullptr && _d_miss_threshold < -1)) {
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

        if (!_removed) {
            ++_d_miss_count;

#ifndef PYPY_VERSION
            if (_code) {    // immediate de-instrumentation
                *_code = static_cast<std::byte>(JUMP_FORWARD);
                _removed = true;
            }
            else
#endif
            if (_d_miss_count == _d_miss_threshold) {
                // Limit D misses by deinstrumenting once we see several for a line
                // Any other lines getting D misses get deinstrumented at the same time,
                // so this needn't be a large threshold.
                PyPtr<> deinstrument_seen = PyUnicode_FromString("deinstrument_seen");
                PyPtr<> result = PyObject_CallMethodObjArgs(_sci, deinstrument_seen, NULL);
            }
        }
        else {
            // U miss
        }

        Py_RETURN_NONE;
    }


    PyObject* mark_removed() {
        _removed = true;
        Py_RETURN_NONE;
    }

    PyObject* was_removed() {
        if (_removed) {
            Py_RETURN_TRUE;
        }
        Py_RETURN_FALSE;
    }

    PyObject* set_immediate(PyObject* code_bytes, PyObject* offset) {
#ifdef PYPY_VERSION
        PyErr_SetString(PyExc_Exception, "Error: set_immediate does not work with PyPy");
        return NULL;
#endif

        _code = reinterpret_cast<std::byte*>(PyBytes_AsString(code_bytes));
        if (_code == nullptr) {
            return NULL;
        }
        _code += PyLong_AsLong(offset);

        Py_RETURN_NONE;
    }
};


PyObject*
probe_new(PyObject* self, PyObject* const* args, Py_ssize_t nargs) {
    if (nargs < 4) {
        PyErr_SetString(PyExc_Exception, "Missing argument(s)");
        return NULL;
    }

    return Probe::newCapsule(new Probe(args[0], args[1], args[2], args[3]));
}


PyObject*
probe_set_immediate(PyObject* self, PyObject* const* args, Py_ssize_t nargs) {
    if (nargs < 3) {
        PyErr_SetString(PyExc_Exception, "Missing argument(s)");
        return NULL;
    }

    return static_cast<Probe*>(PyCapsule_GetPointer(args[0], NULL))->set_immediate(args[1], args[2]);
}

#define METHOD_WRAPPER(method) \
    static PyObject*\
    probe_##method(PyObject* self, PyObject* const* args, Py_ssize_t nargs) {\
        if (nargs < 1) {\
            PyErr_SetString(PyExc_Exception, "Missing argument");\
            return NULL;\
        }\
    \
        return static_cast<Probe*>(PyCapsule_GetPointer(args[0], NULL))->method();\
    }

METHOD_WRAPPER(signal);
METHOD_WRAPPER(mark_removed);
METHOD_WRAPPER(was_removed);


static PyMethodDef methods[] = {
    {"new", (PyCFunction)probe_new, METH_FASTCALL, "creates a new probe"},
    {"set_immediate", (PyCFunction)probe_set_immediate, METH_FASTCALL, "sets up for immediate removal"},
    {"signal", (PyCFunction)probe_signal, METH_FASTCALL, "signals this probe's line or branch was reached"},
    {"mark_removed", (PyCFunction)probe_mark_removed, METH_FASTCALL, "marks a probe removed (de-instrumented)"},
    {"was_removed", (PyCFunction)probe_was_removed, METH_FASTCALL, "returns whether probe was removed"},
    {NULL, NULL, 0, NULL}
};


static struct PyModuleDef probe_module = {
    PyModuleDef_HEAD_INIT,
    "probe",
    NULL, // no documentation
    -1,
    methods,
    NULL,
    NULL,
    NULL,
    NULL
};


PyMODINIT_FUNC
PyInit_probe() {
    PyObject* m = PyModule_Create(&probe_module);
    if (m == nullptr) {
        return nullptr;
    }

    return m;
}

