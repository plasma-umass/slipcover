#include "JustUnit.hxx"
#include <Python.h>
#include <dictobject.h>
#include "pyptr.h"


class PyPtrTest : public JustUnit::TestClass {
public:
    virtual void startUp() {
        Py_Initialize();
    }


    JU_TEST(testConstructNullptr) {
        PyPtr<> p{nullptr};
        ju_assert(p == nullptr, "");
    }

    JU_TEST(testConstructObj) {
        PyObject* obj = PyDict_New();
        Py_IncRef(obj);
        ju_assert_eq(2, Py_REFCNT(obj), "");

        {
            PyPtr<> p{obj};
            ju_assert_eq(2, Py_REFCNT(obj), "");
        }

        ju_assert_eq(1, Py_REFCNT(obj), "");
        Py_DecRef(obj);
    }

    JU_TEST(testConstructObjBorrowed) {
        PyObject* obj = PyDict_New();
        ju_assert_eq(1, Py_REFCNT(obj), "");

        {
            PyPtr<> p{PyPtr<>::borrowed(obj)};
            ju_assert_eq(2, Py_REFCNT(obj), "");
        }

        ju_assert_eq(1, Py_REFCNT(obj), "");
        Py_DecRef(obj);
    }

    JU_TEST(testConstructObjBorrowedNull) {
        PyPtr<> p{PyPtr<>::borrowed(nullptr)};
        ju_assert(p == nullptr, "")
    }

    JU_TEST(testConstructCopy) {
        PyObject* obj = PyDict_New();
        PyPtr<> p{obj};
        ju_assert_eq(1, Py_REFCNT(obj), "");

        {
            PyPtr<> p2{p};
            ju_assert(p2 == obj, "");
            ju_assert_eq(2, Py_REFCNT(obj), "");
        }

        ju_assert_eq(1, Py_REFCNT(obj), "");
    }

    JU_TEST(testConstructCopyNull) {
        PyPtr<> p{nullptr};

        {
            PyPtr<> p2{p};
            ju_assert(p2 == nullptr, "");
        }
    }

    JU_TEST(testAssignObj) {
        PyObject* obj = PyDict_New();
        Py_IncRef(obj);
        ju_assert_eq(2, Py_REFCNT(obj), "");

        {
            PyPtr<> p{nullptr};
            p = obj;
            ju_assert(p == obj, "");
            ju_assert_eq(2, Py_REFCNT(obj), "");
        }

        ju_assert_eq(1, Py_REFCNT(obj), "");
        Py_DecRef(obj);
    }

    JU_TEST(testAssignNullObj) {
        PyObject* obj = PyDict_New();
        Py_IncRef(obj);

        PyPtr<> p{obj};
        ju_assert_eq(2, Py_REFCNT(obj), "");

        {
            p = nullptr;
            ju_assert(p == nullptr, "");
            ju_assert_eq(1, Py_REFCNT(obj), "");
        }

        ju_assert_eq(1, Py_REFCNT(obj), "");
        Py_DecRef(obj);
    }

    JU_TEST(testAssignCopy) {
        PyObject* obj = PyDict_New();
        PyPtr<> p{obj};
        ju_assert_eq(1, Py_REFCNT(obj), "");

        {
            PyPtr<> p2{nullptr};
            p2 = p;
            ju_assert(p2 == obj, "");
            ju_assert_eq(2, Py_REFCNT(obj), "");
        }

        ju_assert_eq(1, Py_REFCNT(obj), "");
    }

    JU_TEST(testAssignNullCopy) {
        PyObject* obj = PyDict_New();
        Py_IncRef(obj);

        PyPtr<> p{obj};
        ju_assert_eq(2, Py_REFCNT(obj), "");

        {
            PyPtr<> p2{nullptr};
            p = p2; // note p = p2
            ju_assert(p == nullptr, "");
            ju_assert_eq(1, Py_REFCNT(obj), "");
        }

        ju_assert_eq(1, Py_REFCNT(obj), "");
        Py_DecRef(obj);
    }

    static PyPtr<> makeNumber(int n) { // just something that returns PyPtr
        return PyLong_FromLong(42);
    }

    JU_TEST(testTypicalUsage) {
        PyPtr<> dict = PyDict_New();
        PyDict_SetItemString(dict, "foo", makeNumber(42));

        PyPtr<> item = PyPtr<>::borrowed(PyDict_GetItemString(dict, "foo"));
        ju_assert(nullptr != item, "");
        ju_assert(PyLong_Check(item), "");
        ju_assert_eq(42, PyLong_AsLong(item), "");
        ju_assert(Py_REFCNT(item) >= 2, "");    // PyLong_FromLong doesn't always make a new object

        ju_assert_eq(1, Py_REFCNT(dict), "");
    }

} pyptr_test;
