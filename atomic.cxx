#define PY_SSIZE_T_CLEAN    // programmers love obscure statements
#include <Python.h>


template <class O = PyObject>
class PyPtr {
 public:
  PyPtr(O* o) : _obj(o) {}

  O* operator->() { return _obj; }

  operator O*() { return _obj; }

  PyPtr& operator=(O* o) {
    Py_DecRef((PyObject*)_obj);
    _obj = o;
    return *this;
  }

  PyPtr& operator=(PyPtr& ptr) {
    Py_IncRef((PyObject*)ptr._obj);
    *this = ptr._obj;
    return *this;
  }

  ~PyPtr() {
      Py_DecRef((PyObject*)_obj);
  }

 private:
  O* _obj;
};


static PyObject*
count_line(PyObject* self, PyObject* args) {
    PyObject* sc;
    PyObject* filename;
    PyObject* lineno;
    if (!PyArg_ParseTuple(args, "OUO", &lineno, &filename, &sc)) {
        return NULL;
    }

    PyPtr new_lines_seen = PyObject_GetAttrString(sc, "new_lines_seen");
    if (!new_lines_seen) {
        return NULL;
    }

    PyPtr line_set = PyObject_GetItem(new_lines_seen, filename);
    if (!line_set) {
        return NULL;
    }

    if (PySet_Check(line_set)) {
        if (PySet_Add(line_set, lineno) < 0) {
            return NULL;
        }
    }
    else {  // assume it's a collections.Counter
        PyPtr upd = PyObject_GetAttrString(line_set, "update");
        if (!upd) {
            return NULL;
        }

        PyPtr tuple = PyTuple_Pack(1, lineno);
        PyPtr arg = PyTuple_Pack(1, (PyObject*)tuple);

        PyPtr result = PyObject_CallObject(upd, arg);
        if (!result) {
            return NULL;
        }
    }

    Py_RETURN_NONE;
}


static PyMethodDef methods[] = {
    {"count_line", count_line, METH_VARARGS, "counts a line"},
    {NULL, NULL, 0, NULL}
};


static struct PyModuleDef atomic_module = {
    PyModuleDef_HEAD_INIT,
    .m_name = "atomic",
    .m_doc = NULL, // no documentation
    .m_size = -1,
    .m_methods = methods,
    .m_slots = NULL,
    .m_traverse = NULL,
    .m_clear = NULL,
    .m_free = NULL
};


PyMODINIT_FUNC
PyInit_atomic() {
  PyObject* m = PyModule_Create(&atomic_module);
  if (m == nullptr) {
    return nullptr;
  }

  return m;
}

