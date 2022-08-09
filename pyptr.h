#ifndef PYPTR_H
#define PYPTR_H
#pragma once

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

#endif
