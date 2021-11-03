import dis

def noteCoverage():
    import inspect as i
    print("noteCoverage line", i.getframeinfo(i.stack()[1][0]).lineno)
    # now we'd need to patch the line back to normal

# Simple function to try to patch.
def hello():
    print("hello world")

#dis.dis(hello.__code__)

def insertCall(f):
    co = f.__code__
    patch = bytearray(len(co.co_code)+6)
    patch[0:6] = [dis.opmap['LOAD_GLOBAL'], len(co.co_names), # <- 'noteCoverage'
                  dis.opmap['CALL_FUNCTION'], 0,
                  dis.opmap['POP_TOP'], 0]
    patch[6:] = co.co_code
    # from cpython/Lib/test/test_code.py
    CodeType = type(co)
    f.__code__ = CodeType(co.co_argcount,
                          co.co_posonlyargcount,
                          co.co_kwonlyargcount,
                          co.co_nlocals,
                          co.co_stacksize+1,
                          co.co_flags,
                          bytes(patch),
                          co.co_consts,
                          co.co_names + ('noteCoverage',),
                          co.co_varnames,
                          co.co_filename,
                          co.co_name,
#                          co.co_qualname,
                          co.co_firstlineno,
                          co.co_lnotab,
#                          co.co_endlinetable,
#                          co.co_columntable,
#                          co.co_exceptiontable,
                          co.co_freevars,
                          co.co_cellvars)

hello()

insertCall(hello)
#dis.dis(hello.__code__)

hello()
