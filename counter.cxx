#define PY_SSIZE_T_CLEAN    // programmers love obscure statements
#include <Python.h>


/**
 * Implements a smart pointer to a PyObject.
 */
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
count_line(PyObject* self, PyObject* const* args, Py_ssize_t nargs) {
    if (nargs < 4) {
        return NULL;
    }

    if (bool* flag = (bool*)PyCapsule_GetPointer(args[0], NULL)) {
        if (*flag) {
            Py_RETURN_NONE;
        }
        *flag = true;
    }

    PyObject* filename = args[1];
    PyObject* lineno = args[2];
    PyObject* sc = args[3];

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


void
flag_destructor(PyObject* capsule) {
    bool* flag = (bool*)PyCapsule_GetPointer(capsule, NULL);
    delete flag;
}


PyObject*
alloc_flag(PyObject* self) {
    bool* flag = new bool(false);
    return PyCapsule_New(flag, NULL, flag_destructor);
}

static PyMethodDef methods[] = {
    {"count_line", (PyCFunction)count_line, METH_FASTCALL, "counts a line"},
    {"alloc_flag", (PyCFunction)alloc_flag, METH_NOARGS, "allocates a flag"},
    {NULL, NULL, 0, NULL}
};


static struct PyModuleDef counter_module = {
    PyModuleDef_HEAD_INIT,
    "counter",
    NULL, // no documentation
    -1,
    methods,
    NULL,
    NULL,
    NULL,
    NULL
};


PyMODINIT_FUNC
PyInit_counter() {
  PyObject* m = PyModule_Create(&counter_module);
  if (m == nullptr) {
    return nullptr;
  }

  return m;
}

