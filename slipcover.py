import sys
import dis

# map to guide CodeType replacements on the stack
replace_map = dict()

def newCodeType(orig, code, stacksize=None, consts=None, names=None):
    """Instantiates a new CodeType, modifying it from the original"""
    # from cpython/Lib/test/test_code.py
    CodeType = type(orig)
    new = CodeType(orig.co_argcount,
                   orig.co_posonlyargcount,
                   orig.co_kwonlyargcount,
                   orig.co_nlocals,
                   (orig.co_stacksize if stacksize is None else stacksize),
                   orig.co_flags,
                   (orig.co_code if code is None else bytes(code)),
                   (orig.co_consts if consts is None else tuple(consts)),
                   (orig.co_names if names is None else tuple(names)),
                   orig.co_varnames,
                   orig.co_filename,
                   orig.co_name,
#                  orig.co_qualname,
                   orig.co_firstlineno,
                   orig.co_lnotab,
#                  orig.co_endlinetable,
#                  orig.co_columntable,
#                  orig.co_exceptiontable,
                   orig.co_freevars,
                   orig.co_cellvars)
    replace_map[orig] = new
    print("->", new)
    return new

def instrument(co):
    """Instruments a code object for coverage detection.
       If invoked on a function, instruments its code."""
    import types

    if (isinstance(co, types.FunctionType)):
        co.__code__ = instrument(co.__code__)
        return

    assert isinstance(co, types.CodeType)
#    print(f"instrumenting {co.co_name}")

    lines = list(dis.findlinestarts(co))
    consts = list(co.co_consts)

    # handle functions-within-functions
    for i in range(len(consts)):
        if isinstance(consts[i], types.CodeType):
            consts[i] = instrument(consts[i])

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
    last_offset = None
    for (offset, lineno) in lines:
        # XXX this assumes there's enough space between lines for the jump
        assert(last_offset is None or offset-last_offset >= 2)

        patch[p:p+len_t] = mk_trampoline(offset)
        patch[offset] = dis.opmap['JUMP_ABSOLUTE']
        patch[offset+1] = p

        consts.append(lineno)

        p += len_t

    return newCodeType(co, patch, stacksize=co.co_stacksize+2, # use dis.stack_effect?
                       consts=consts, names=co.co_names + ('noteCoverage',))


def deinstrument(co, lines): # antonym for "to instrument"?
    """De-instruments a code object previously instrumented for coverage detection.
       If invoked on a function, de-instruments its code."""
    import types
    if (isinstance(co, types.FunctionType)):
        co.__code__ = deinstrument(co.__code__, lines)
        return

    assert isinstance(co, types.CodeType)
#    print(f"de-instrumenting {co.co_name}")

    patch = None
    consts = None

    for i in range(len(co.co_consts)):
        if isinstance(co.co_consts[i], types.CodeType):
            nc = deinstrument(co.co_consts[i], lines)
            if nc != co.co_consts[i]:
                if consts is None: consts = list(co.co_consts)
                consts[i] = nc

    for (offset, lineno) in dis.findlinestarts(co):
        if lineno in lines:
            if co.co_code[offset] == dis.opmap['JUMP_ABSOLUTE']:
                t_offset = co.co_code[offset+1]

            if patch is None:
                patch = bytearray(co.co_code)

            patch[offset:offset+2] = patch[t_offset:t_offset+2]

    return co if (patch is None and consts is None) \
              else newCodeType(co, patch, consts=consts)

# Notes which lines have been seen.  Needs to be extended to include the filename
lines_seen = set()

def noteCoverage(lineno):
    """Invoked to mark a line as having executed."""
    lines_seen.add(lineno)
    # inspect sees trampoline code as in the last line of the function
    #import inspect
    #print("noteCoverage line", inspect.getframeinfo(inspect.stack()[1][0]).lineno)


# Remembers which lines we've already de-instrumented
lines_deinstrumented = set()

def print_coverage():
    def merge_consecutives(L):
        # Neat little trick due to John La Rooy: the difference between the numbers
        # on a list and a counter is constant for consecutive items :)
        from itertools import groupby, count
        groups = groupby(sorted(L), key=lambda item, c=count(): item-next(c))
        return [str(g[0]) if g[0]==g[-1] else f"{g[0]}-{g[-1]}" for g in [list(g) for _,g in groups]]

    # XXX fixme need file names, too!
    print("coverage:", merge_consecutives(list(lines_seen)))

def setup():
    """Sets up for coverage tracking"""
    import atexit
    import signal

    atexit.register(print_coverage)

    INTERVAL = .2
    def deinstrument_callback(signum, this_frame):
        """Periodically de-instruments lines that were already reached."""
        to_remove = lines_seen - lines_deinstrumented
        if len(to_remove) > 0:
            # XXX this could be better guided, rather than go through all_functions
            for f in all_functions():
                deinstrument(f, to_remove)
            lines_deinstrumented.update(to_remove)

#            stackpatch.patch(replace_map)
#            replace_map.clear()
        signal.setitimer(signal.ITIMER_VIRTUAL, INTERVAL)

    signal.siginterrupt(signal.SIGVTALRM, False)
    signal.signal(signal.SIGVTALRM, deinstrument_callback)
    signal.setitimer(signal.ITIMER_VIRTUAL, INTERVAL)

#    for f in all_functions():
#        instrument(f)

def all_functions():
    """Introspects, returning all functions to instrument"""
    import inspect
    # XXX get it from isolated globals, locals
    classes = [c[1] for c in inspect.getmembers(sys.modules['__main__'], inspect.isclass)]
    methods = [f[1] for c in classes for f in inspect.getmembers(c, inspect.isfunction)]
#    funcs = [f[1] for f in inspect.getmembers(sys.modules['__main__'], inspect.isfunction)]
    return methods

setup()
for file in sys.argv:
    if file != __file__:
        with open(file, 'r') as f:
            code = compile(f.read(), file, 'exec')
            code = instrument(code)
            # XXX isolate environments by passing globals, locals
            exec(code)
