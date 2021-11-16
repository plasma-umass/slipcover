import copy
import sys
import dis

# map to guide CodeType replacements on the stack
replace_map = dict()

def newCodeType(orig, code, stacksize=None, consts=None, names=None):
    """Instantiates a new CodeType, modifying it from the original"""
    new = copy.copy(orig)
    new.replace(co_stacksize=orig.co_stacksize if stacksize is None else stacksize,
                co_code=orig.co_code if code is None else bytes(code),
                co_consts=(orig.co_consts if consts is None else tuple(consts)),
                co_names=(orig.co_names if names is None else tuple(names)))
    replace_map[orig] = new
    # print("->", new)
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

    def opcode_arg(opcode, arg):
        """Emits an opcode and its (variable length) argument."""
        bytecode = []
        ext = (arg.bit_length()-1)//8
        assert ext <= 3
        for i in range(ext):
            bytecode.extend([dis.opmap['EXTENDED_ARG'], (arg >> (ext-i)*8) & 0xFF])
        bytecode.extend([dis.opmap[opcode], arg & 0xFF])
        return bytecode

    def mk_trampoline(offset, after_jump):
        tr = list(co.co_code[offset:offset+after_jump])
        tr.extend(opcode_arg('LOAD_GLOBAL', len(co.co_names))) # <- '___noteCoverage'
        tr.extend(opcode_arg('LOAD_CONST', filename_index))    # <- filename
        tr.extend(opcode_arg('LOAD_CONST', len(consts)))       # line number (will be added)
        tr.extend([dis.opmap['CALL_FUNCTION'], 2,
                   dis.opmap['POP_TOP'], 0])
        tr.extend(opcode_arg('JUMP_ABSOLUTE', offset+after_jump))
        return tr

    patch = bytearray(co.co_code)
    last_offset = None
    for (offset, lineno) in lines:
        # Verify there's been enough space between lines for the jump
        assert(last_offset is None or offset-last_offset >= len(j))
        last_offset = offset

        j = opcode_arg('JUMP_ABSOLUTE', len(patch))
        patch.extend(mk_trampoline(offset, len(j)))
        patch[offset:offset+len(j)] = j

        consts.append(lineno)

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
    print(f"de-instrumenting {co.co_name}")

    patch = None
    consts = None

    for i in range(len(co.co_consts)):
        if isinstance(co.co_consts[i], types.CodeType):
            nc = deinstrument(co.co_consts[i], lines)
            if nc != co.co_consts[i]:
                if consts is None: consts = list(co.co_consts)
                consts[i] = nc

    for (offset, lineno) in dis.findlinestarts(co):
        if lineno in lines: # FIXME this assumes all lines are on the same file
            ext = 0
            t_offset = co.co_code[offset+1]
            while co.co_code[offset+ext] == dis.opmap['EXTENDED_ARG']:
                ext += 2
                t_offset = (t_offset << 8) | co.co_code[offset+ext+1]

            if co.co_code[offset+ext] == dis.opmap['JUMP_ABSOLUTE']:
                if patch is None:
                    patch = bytearray(co.co_code)

                patch[offset:offset+ext+2] = patch[t_offset:t_offset+ext+2]

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

    INTERVAL = .5
    def deinstrument_callback(signum, this_frame):
        """Periodically de-instruments lines that were already reached."""
        import inspect
        import types

        print("deinstrument_callback")
        for file in lines_seen:
            to_remove = lines_deinstrumented[file] - lines_seen[file] if file in lines_deinstrumented \
                        else lines_seen[file]
            print(f"{file} to_remove:", len(to_remove))
            if len(to_remove) > 0:
                # XXX this could be better guided, rather than go through all_functions
                for f in all_functions():
                    deinstrument(f, to_remove)
                if file not in lines_deinstrumented: lines_deinstrumented[file] = set()
                lines_deinstrumented[file].update(to_remove)

                # Replace inner functions and any other function variables
                # XXX this could be better guided
                frame = inspect.currentframe()
                while frame:
                    for var in list(frame.f_locals.keys()): # avoid 'dictionary changed size during iter.'
                        if isinstance(frame.f_locals[var], types.FunctionType):
                            if frame.f_locals[var].__code__ in replace_map:
                                frame.f_locals[var].__code__ = replace_map[frame.f_locals[var].__code__]
                    frame = frame.f_back

    #            stackpatch.patch(replace_map)
                replace_map.clear()
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
    funcs = [slipcover_globals[c] for c in slipcover_globals if c != '___noteCoverage' and \
                                                  isinstance(slipcover_globals[c], types.FunctionType)]
    return methods + funcs

setup()
slipcover_globals['___noteCoverage'] = ___noteCoverage
slipcover_globals['__name__'] = '__main__'
sys.argv = sys.argv[1:] # delete ourselves so as not to confuse others
# XXX do we really need a loop? what does python do with multiple files?  What about other modules?
for file in sys.argv:
    slipcover_globals['__file__'] = file
    with open(file, 'r') as f:
        code = compile(f.read(), file, 'exec')
        code = instrument(code)
#        dis.dis(code)
        exec(code, slipcover_globals)
