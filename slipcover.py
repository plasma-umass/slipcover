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
    #print("->", new)
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

    filename_index = len(consts)
    consts.append(co.co_filename)

    # handle functions-within-functions
    for i in range(len(consts)):
        if isinstance(consts[i], types.CodeType):
            consts[i] = instrument(consts[i])

    def mk_trampoline(offset):
        return [co.co_code[offset], co.co_code[offset+1],
                dis.opmap['LOAD_GLOBAL'], len(co.co_names), # <- '___noteCoverage'
                dis.opmap['LOAD_CONST'], filename_index,    # <- filename
                dis.opmap['LOAD_CONST'], len(consts),       # line number (will be added)
                dis.opmap['CALL_FUNCTION'], 2,
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
                       consts=consts, names=co.co_names + ('___noteCoverage',))


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

# Notes which lines have been seen.
lines_seen = dict()

def ___noteCoverage(filename, lineno):
    """Invoked to mark a line as having executed."""
    if not filename in lines_seen: lines_seen[filename] = set()
    lines_seen[filename].add(lineno)

# Remembers which lines we've already de-instrumented
# XXX remember those to de-instrument instead?
lines_deinstrumented = dict()

def print_coverage():
    def merge_consecutives(L):
        # Neat little trick due to John La Rooy: the difference between the numbers
        # on a list and a counter is constant for consecutive items :)
        from itertools import groupby, count
        groups = groupby(sorted(L), key=lambda item, c=count(): item-next(c))
        return [str(g[0]) if g[0]==g[-1] else f"{g[0]}-{g[-1]}" for g in [list(g) for _,g in groups]]

    for file in lines_seen:
        print(f"coverage: {file}:", merge_consecutives(lines_seen[file]))

    import signal
    signal.setitimer(signal.ITIMER_VIRTUAL, 0)

def setup():
    """Sets up for coverage tracking"""
    import atexit
    import signal

    atexit.register(print_coverage)

    INTERVAL = .2
    def deinstrument_callback(signum, this_frame):
        """Periodically de-instruments lines that were already reached."""
        import inspect
        import types

        for file in lines_seen:
            to_remove = lines_deinstrumented[file] - lines_seen[file] if file in lines_deinstrumented \
                        else lines_seen[file]
            if len(to_remove) > 0:
                # XXX this could be better guided, rather than go through all_functions
                for f in all_functions():
                    deinstrument(f, to_remove)
                if file not in lines_deinstrumented: lines_deinstrumented[file] = set()
                lines_deinstrumented[file].update(to_remove)

                # XXX this could be better guided
                frame = inspect.currentframe()
                while frame:
                    for var in list(frame.f_locals.keys()): # avoid 'dictionary changed size during iter.'
                        # replace inner functions and any other function variables
                        if isinstance(frame.f_locals[var], types.FunctionType):
                            if frame.f_locals[var].__code__ in replace_map:
                                frame.f_locals[var].__code__ = replace_map[frame.f_locals[var].__code__]
                    frame = frame.f_back

    #            stackpatch.patch(replace_map)
    #            replace_map.clear()
        signal.setitimer(signal.ITIMER_VIRTUAL, INTERVAL)

    signal.siginterrupt(signal.SIGVTALRM, False)
    signal.signal(signal.SIGVTALRM, deinstrument_callback)
    signal.setitimer(signal.ITIMER_VIRTUAL, INTERVAL)

#    for f in all_functions():
#        instrument(f)

slipcover_globals = dict() # XXX rename

def all_functions():
    """Introspects, returning all functions to instrument"""
    import inspect
    import types
    classes = [slipcover_globals[c] for c in slipcover_globals if isinstance(slipcover_globals[c], type)]
    methods = [f[1] for c in classes for f in inspect.getmembers(c, inspect.isfunction)]
    funcs = [slipcover_globals[c] for c in slipcover_globals if c != '___notecoverage' and \
                                                  isinstance(slipcover_globals[c], types.FunctionType)]
    return methods + funcs

setup()
slipcover_globals['___noteCoverage'] = ___noteCoverage
slipcover_globals['__name__'] = '__main__'
sys.argv = sys.argv[1:] # delete ourselves so as not to confuse others
# XXX do we really need a loop? what does python do with multiple files?  What about other modules?
for file in sys.argv:
    # needed? slipcover_globals['__file__'] = file
    with open(file, 'r') as f:
        code = compile(f.read(), file, 'exec')
        code = instrument(code)
        exec(code, slipcover_globals)
