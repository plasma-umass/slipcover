#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <frameobject.h>


static const char*
as_utf8(PyObject* obj) {
  // this avoids recursively allocating memory if the string isn't already UTF-8
  if (PyUnicode_Check(obj) && PyUnicode_IS_READY(obj)) {
    return PyUnicode_AsUTF8(obj);
  }

  return "?";
}


static PyObject *
stackpatch_patch(PyObject *self, PyObject *args)
{
    fprintf(stderr, "---patch---\n");
    PyObject* replace_map;
    if (!PyArg_ParseTuple(args, "O", &replace_map)) {
        return 0;
    }
    if (!PyDict_Check(replace_map)) {
        PyErr_SetString(PyExc_Exception, "patch requires replace_map");
        return 0;
    }

    if (PyThreadState *tstate = PyGILState_GetThisThreadState()) {
        PyFrameObject *frame = tstate->frame; // XXX PyThreadState_GetFrame(tstate) for Python 3.9+ ?

        while (frame != nullptr) {
            int line = PyCode_Addr2Line(frame->f_code, frame->f_lasti);

            const char *filename = as_utf8(frame->f_code->co_filename);
            const char *funcname = as_utf8(frame->f_code->co_name);
            fprintf(stderr, "%s %s:%d", funcname, filename, line);
            
            if (PyObject* newCode = PyDict_GetItem(replace_map,
                                                   reinterpret_cast<PyObject*>(frame->f_code))) {
                Py_INCREF(newCode);
                Py_DECREF(frame->f_code);
                fprintf(stderr, " %llx -> %llx\n", (unsigned long long)frame->f_code,
                        (unsigned long long)newCode); 
                frame->f_code = reinterpret_cast<PyCodeObject*>(newCode);
            }

            fprintf(stderr, "\n");
            frame = frame->f_back; // XXX PyFrame_GetBack(frame) for Python 3.9+
        }
    }
    
    Py_RETURN_NONE;
}

static PyMethodDef stackPatchMethods[] = {
    {"patch",  stackpatch_patch, METH_VARARGS, "Patches the stack."},
    {0, 0, 0, 0}        /* Sentinel */
};

static struct PyModuleDef stackPatchModule = {
    PyModuleDef_HEAD_INIT,
    "stackpatch",
    nullptr, /* module documentation, may be NULL */
    -1,
    stackPatchMethods 
};

PyMODINIT_FUNC
PyInit_stackpatch() {
    return PyModule_Create(&stackPatchModule);
}
