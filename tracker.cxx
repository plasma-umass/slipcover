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
    bool _signalled;
    bool _instrumented;
    int _d_miss_count;
    int _d_threshold;

public:
    Tracker(PyObject* sci, PyObject* filename, PyObject* lineno):
        _sci(PyPtr<>::borrowed(sci)), _filename(PyPtr<>::borrowed(filename)),
        _lineno(PyPtr<>::borrowed(lineno)),
        _collect_stats(false), _signalled(false), _instrumented(true),
        _d_miss_count(-1), _d_threshold(50) {

        PyPtr<> collect_stats = PyObject_GetAttrString(_sci, "collect_stats");
        _collect_stats = (collect_stats == Py_True);

        PyPtr<> d_threshold = PyObject_GetAttrString(_sci, "d_threshold");
        _d_threshold = PyLong_AsLong(d_threshold);
    }


    static PyObject*
    newCapsule(Tracker* t) {
        return PyCapsule_New(t, NULL,
                             [](PyObject* cap) {
                                 delete (Tracker*)PyCapsule_GetPointer(cap, NULL);
                             });
    }


    PyObject* signal() {
        if (!_signalled || _collect_stats) {
            _signalled = true;

            PyPtr<> new_lines_seen = PyObject_GetAttrString(_sci, "new_lines_seen");
            if (!new_lines_seen) {
                PyErr_SetString(PyExc_Exception, "new_lines_seen missing");
                return NULL;
            }

            PyPtr<> line_set = PyObject_GetItem(new_lines_seen, _filename);
            if (!line_set) {
                PyErr_SetString(PyExc_Exception, "line_set missing");
                return NULL;
            }

            if (PySet_Check(line_set)) {
                if (PySet_Add(line_set, _lineno) < 0) {
                    PyErr_SetString(PyExc_Exception, "Unable to add to set");
                    return NULL;
                }
            }
            else {  // assume it's a collections.Counter
                PyPtr<> update = PyUnicode_FromString("update");
                if (!update) {
                    PyErr_SetString(PyExc_Exception, "Unable to find update method");
                    return NULL;
                }

                PyPtr<> tuple = PyTuple_Pack(1, (PyObject*)_lineno);

                PyPtr<> result = PyObject_CallMethodObjArgs(line_set, update,
                                                            (PyObject*)tuple, NULL);
                if (!result) {
                    PyErr_SetString(PyExc_Exception, "Unable to call Counter.update");
                    return NULL;
                }
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

        Py_RETURN_NONE;
    }


    PyObject* deinstrument() {
        if (_instrumented) {
            _instrumented = false;

            if (_collect_stats) {
                PyPtr<> neg = PyLong_FromLong(-PyLong_AsLong(_lineno));

                Tracker* t = new Tracker(_sci, _filename, (PyObject*)neg);
                t->_instrumented = false;

                return newCapsule(t);
            }
        }

        Py_RETURN_NONE;
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
tracker_deinstrument(PyObject* self, PyObject* const* args, Py_ssize_t nargs) {
    if (nargs < 1) {
        PyErr_SetString(PyExc_Exception, "Missing argument");
        return NULL;
    }

    return static_cast<Tracker*>(PyCapsule_GetPointer(args[0], NULL))->deinstrument();
}


static PyMethodDef methods[] = {
    {"register", (PyCFunction)tracker_register, METH_FASTCALL, "registers a new tracker"},
    {"signal", (PyCFunction)tracker_signal, METH_FASTCALL, "signal a tracker"},
    {"deinstrument", (PyCFunction)tracker_deinstrument, METH_FASTCALL,
     "mark a tracker deinstrumented"},
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

