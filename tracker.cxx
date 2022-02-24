#define PY_SSIZE_T_CLEAN    // programmers love obscure statements
#include <Python.h>


/**
 * Implements a smart pointer to a PyObject.
 */
template <class O = PyObject>
class PyPtr {
public:
    // assumes a new reference
    PyPtr(O* o) : _obj(o) {}

    static PyPtr borrowed(O* o) {
        Py_IncRef((PyObject*)o);
        return PyPtr(o);
    }

    O* operator->() { return _obj; }

    operator O*() { return _obj; }

    PyPtr& operator=(O* o) {
        Py_DecRef((PyObject*)_obj);
        _obj = o;
        return *this;
    }

    // XXX is rvalue operator= worthwhile?

    PyPtr& operator=(PyPtr& ptr) {
        Py_IncRef((PyObject*)ptr._obj);
        *this = ptr._obj;
        return *this;
    }

    ~PyPtr() {
        Py_DecRef((PyObject*)_obj);
        _obj = 0;
    }

private:
    O* _obj;
};


/**
 * Tracks code coverage.
 */
class Tracker {
    PyPtr<> _sci;
    PyPtr<> _filename;
    PyPtr<> _lineno;
    bool _collect_stats;
    bool _disabled;

public:
    Tracker(PyObject* sci, PyObject* filename, PyObject* lineno):
        _sci(PyPtr<>::borrowed(sci)), _filename(PyPtr<>::borrowed(filename)),
        _lineno(PyPtr<>::borrowed(lineno)), _collect_stats(false), _disabled(false) {

        PyPtr collect_stats = PyObject_GetAttrString(_sci, "collect_stats");
        _collect_stats = (collect_stats == Py_True);
    }


    static PyObject*
    newCapsule(Tracker* t) {
        return PyCapsule_New(t, NULL,
                             [](PyObject* cap) {
                                 delete (Tracker*)PyCapsule_GetPointer(cap, NULL);
                             });
    }


    PyObject* signal() {
        if (!_disabled) {
            _disabled = !_collect_stats;

            PyPtr new_lines_seen = PyObject_GetAttrString(_sci, "new_lines_seen");
            if (!new_lines_seen) {
                return NULL;
            }

            PyPtr line_set = PyObject_GetItem(new_lines_seen, _filename);
            if (!line_set) {
                return NULL;
            }

            if (PySet_Check(line_set)) {
                if (PySet_Add(line_set, _lineno) < 0) {
                    return NULL;
                }
            }
            else {  // assume it's a collections.Counter
                PyPtr upd = PyObject_GetAttrString(line_set, "update");
                if (!upd) {
                    return NULL;
                }

                PyPtr<> tuple = PyTuple_Pack(1, (PyObject*)_lineno);
                PyPtr<> arg = PyTuple_Pack(1, (PyObject*)tuple);

                PyPtr<> result = PyObject_CallObject(upd, arg);
                if (!result) {
                    return NULL;
                }
            }
        }

        Py_RETURN_NONE;
    }


    PyObject* make_negative() {
        long lineno = 0;

        if (!PyLong_Check(_lineno) || (lineno = PyLong_AsLong(_lineno)) <= 0) {
            Py_RETURN_NONE;
        }

        PyPtr neg = PyLong_FromLong(-lineno);
        return newCapsule(new Tracker(_sci, _filename, (PyObject*)neg));
    }
};


PyObject*
tracker_register(PyObject* self, PyObject* const* args, Py_ssize_t nargs) {
    if (nargs < 3) {
        PyErr_SetString(PyExc_Exception, "Missing argument(s)");
        return NULL;
    }

    PyObject* sci = args[0];
    PyObject* filename = args[1];
    PyObject* lineno = args[2];

    return Tracker::newCapsule(new Tracker(sci, filename, lineno));
}


static PyObject*
tracker_signal(PyObject* self, PyObject* const* args, Py_ssize_t nargs) {
    if (nargs < 1) {
        PyErr_SetString(PyExc_Exception, "Missing argument");
        return NULL;
    }

    return static_cast<Tracker*>(PyCapsule_GetPointer(args[0], NULL))->signal();
}


static PyObject*
tracker_make_negative(PyObject* self, PyObject* const* args, Py_ssize_t nargs) {
    if (nargs < 1) {
        PyErr_SetString(PyExc_Exception, "Missing argument");
        return NULL;
    }

    return static_cast<Tracker*>(PyCapsule_GetPointer(args[0], NULL))->make_negative();
}


static PyMethodDef methods[] = {
    {"register", (PyCFunction)tracker_register, METH_FASTCALL, "registers a new tracker"},
    {"signal", (PyCFunction)tracker_signal, METH_FASTCALL, "signal a tracker"},
    {"make_negative", (PyCFunction)tracker_make_negative, METH_FASTCALL,
        "registers a new tracker with a negative line number"},
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

