import dis

def newCodeType(orig, code, stacksize=None, consts=None, names=None):
    # from cpython/Lib/test/test_code.py
    CodeType = type(orig)
    return CodeType(orig.co_argcount,
                    orig.co_posonlyargcount,
                    orig.co_kwonlyargcount,
                    orig.co_nlocals,
                    (orig.co_stacksize if stacksize is None else stacksize),
                    orig.co_flags,
                    bytes(code),
                    (orig.co_consts if consts is None else tuple(consts)),
                    (orig.co_names if names is None else tuple(names)),
                    orig.co_varnames,
                    orig.co_filename,
                    orig.co_name,
#                   orig.co_qualname,
                    orig.co_firstlineno,
                    orig.co_lnotab,
#                   orig.co_endlinetable,
#                   orig.co_columntable,
#                   orig.co_exceptiontable,
                    orig.co_freevars,
                    orig.co_cellvars)

def instrument(f):
    co = f.__code__
    lines = list(dis.findlinestarts(co))
    consts = list(co.co_consts)

    def mk_trampoline(offset):
        return [co.co_code[offset], co.co_code[offset+1],
                dis.opmap['LOAD_GLOBAL'], len(co.co_names), # <- 'noteCoverage'
                dis.opmap['LOAD_CONST'], len(consts), # line number (will be added)
                dis.opmap['CALL_FUNCTION'], 1,
                dis.opmap['POP_TOP'], 0,
                dis.opmap['JUMP_ABSOLUTE'], offset+2]

    len_t = len(mk_trampoline(0))

    patch = bytearray(len(co.co_code) + len(lines)*len_t)

    p = len(co.co_code)
    patch[:p] = co.co_code
    for (offset, lineno) in lines:
        patch[p:p+len_t] = mk_trampoline(offset)
        patch[offset] = dis.opmap['JUMP_ABSOLUTE']
        patch[offset+1] = p

        consts.append(lineno)

        p += len_t

    f.__code__ = newCodeType(co, patch, stacksize=co.co_stacksize+2, # use dis.stack_effect?
                             consts=consts, names=co.co_names + ('noteCoverage',))


def deinstrument(f, lines): # antonym for "to instrument"?
    co = f.__code__
    patch = None

    for (offset, lineno) in dis.findlinestarts(co):
        if lineno in lines:
            if co.co_code[offset] == dis.opmap['JUMP_ABSOLUTE']:
                t_offset = co.co_code[offset+1]

            if patch is None:
                patch = bytearray(co.co_code)

            patch[offset:offset+2] = patch[t_offset:t_offset+2]

    if not patch is None:
        f.__code__ = newCodeType(co, patch)

lines_seen = set()

def noteCoverage(lineno):
    print(f"noteCoverage {lineno}")
    lines_seen.add(lineno)
    # inspect sees trampoline code as in the last line of the function
    #import inspect
    #print("noteCoverage line", inspect.getframeinfo(inspect.stack()[1][0]).lineno)


# Simple function to try to patch.
def hello():
    N = 2
    for i in range(N):
        print(f"hello world {i}")

print("--original--")
dis.dis(hello.__code__)
hello()

print("--instrumented--")
instrument(hello)
dis.dis(hello.__code__)

hello()

print("--reversed--")
deinstrument(hello, lines_seen)
dis.dis(hello.__code__)

hello()
