# How does Slipcover work

### How do most other tools work
Most other tools, including [Coverage.py](https://github.com/nedbat/coveragepy), rely on Python's [trace function](https://docs.python.org/3/library/sys.html?highlight=settrace#sys.settrace) to gather coverage information.
They create a callback function like

```python
def trace_callback(frame, event, arg):
    if not file_matcher.matches(frame.f_code.co_filename):
        return None # uninteresting scope

    if event == 'line':
        coverage.add((frame.f_code.co_filename, frame.f_lineno))

    return trace_function

threading.settrace(trace_callback)
sys.settrace(trace_callback)
```
that gets called whenever Python moves on to a new line of code.
Often times the trace function used is actually written in C, using Python's C APIs.

Slipcover doesn't use that at all, but _instruments_ the program, inserting bits of code
to gather that information as it executes.

### Python Execution
When you run a Python program, the interpreter doesn’t execute it directly from source, but first compiles it into _byte code_, essentially Python machine language, which it then executes. Code such as
```python
def f(n):
    x = 0
    while n > 0:
        x += n
        n -= 1
    return x
```
becomes something like
```
  2           0 LOAD_CONST               1 (0)
              2 STORE_FAST               1 (x)

  3     >>    4 LOAD_FAST                0 (n)
              6 LOAD_CONST               1 (0)
              8 COMPARE_OP               4 (>)
             10 POP_JUMP_IF_FALSE       30

  4          12 LOAD_FAST                1 (x)
             14 LOAD_FAST                0 (n)
             16 INPLACE_ADD
             18 STORE_FAST               1 (x)

  5          20 LOAD_FAST                0 (n)
             22 LOAD_CONST               2 (1)
             24 INPLACE_SUBTRACT
             26 STORE_FAST               0 (n)
             28 JUMP_ABSOLUTE            4

  6     >>   30 LOAD_FAST                1 (x)
             32 RETURN_VALUE
```
Where the numbers on the far left are the line numbers, the `>>` indicate a jump target,
the numbers next to each opcode is the offset in the code object, and the arguments are to
the right.

Byte codes are held in an internal code object which also contains other information about
the program, _metadata_ such as the file name and line number which originated each specific byte code.

### What Slipcover does
Slipcover intercepts code being loaded into the interpreter and instruments it, inserting code to track when each line gets executed.
It uses the metadata from Python itself to guide the instrumentation, inserting a few byte codes before the beginning of each line.
The code from the example above might become
```
  2           0 NOP
              2 LOAD_CONST               4 (<built-in function signal>)
              4 LOAD_CONST               5 (<capsule object NULL at 0x106b17120>)
              6 CALL_FUNCTION            1
              8 POP_TOP
             10 LOAD_CONST               1 (0)
             12 STORE_FAST               1 (x)

  3     >>   14 NOP
             16 LOAD_CONST               4 (<built-in function signal>)
             18 LOAD_CONST               6 (<capsule object NULL at 0x106b26e40>)
             20 CALL_FUNCTION            1
             22 POP_TOP
             24 LOAD_FAST                0 (n)
             26 LOAD_CONST               1 (0)
             28 COMPARE_OP               4 (>)
             30 POP_JUMP_IF_FALSE       70
[...]
```
Slipcover’s code insert starts with a `NOP` operation just to reserve space for easy/fast de-instrumentation; it will later be replaced by a jump over the other inserted byte codes.
The rest of the insert simply signals Slipcover’s tracker (wrapped in a Python `capsule`) for the line.
The return value, which is mandatory in Python but not used, is discarded, leaving Python ready to execute that line’s original byte codes.

In order to perform these insertions, Slipcover adjusts all branches'
targets (such as that of the `POP_JUMP_IF_FALSE` above), and re-calculates the
Python metadata that maps byte code offsets to line numbers.

### The tracker
Slipcover’s trackers are implemented as C++ objects, and collaborate in building Python `set`s that indicate which lines were reached during the execution.
Each tracker also counts how many times it has been signaled; if that count crosses a threshold, the tracker triggers de-instrumentation, calling back into Python for that.

<<more to say??>>

### De-instrumentation
De-instrumentation is done in two steps:
- For each newly signaled line, Slipcover first visits the corresponding code objects, replacing the `NOP` it placed at the beginning of each insert by a jump over the rest of the insert. The length of the jump varies with the insert length, but is calculated during instrumentation and placed in the code (where it is ignored as long as the opcode is `NOP`).
- Having created new code objects with all signaled lines de-instrumented, Slipcover proceeds to look for references to code objects, replacing these with new objects. This includes references in modules, classes, thread stacks, etc.

The example from above, after de-instrumentation, becomes:
```
  2           0 JUMP_FORWARD             8 (to 10)
              2 LOAD_CONST               4 (<built-in function signal>)
              4 LOAD_CONST               5 (<capsule object NULL at 0x107463180>)
              6 CALL_FUNCTION            1
              8 POP_TOP
        >>   10 LOAD_CONST               1 (0)
             12 STORE_FAST               1 (x)

  3     >>   14 JUMP_FORWARD             8 (to 24)
             16 LOAD_CONST               4 (<built-in function signal>)
             18 LOAD_CONST               6 (<capsule object NULL at 0x10747a240>)
             20 CALL_FUNCTION            1
             22 POP_TOP
        >>   24 LOAD_FAST                0 (n)
             26 LOAD_CONST               1 (0)
             28 COMPARE_OP               4 (>)
             30 POP_JUMP_IF_FALSE       70
[...]
```

The new code objects are used by the program the next time the function or method is called, but Slipcover doesn’t attempt to replace currently executing code objects. Such “on-stack replacement” seems currently very difficult to implement.

De-instrumentation does cost some performance, so it must be “amortized” by avoiding future execution.
The de-instrumentation triggering threshold in trackers is an attempt to detect when de-instrumentation is worthwhile.
Note that de-instrumentation is purely an optimization, i.e., the coverage results would be the same if it didn’t de-instrument at all.

### D-misses and U-misses
To help understand evaluate its behavior, Slipcover can optionally gather certain statistics. Taking a leaf from cache analysis, it counts two kinds of “misses”:
- “D” (de-instrument) misses are counted when a tracker is signaled more than once before it is de-instrumented, and
- “U” (use) misses are counted when the tracker signaling code was de-instrumented, but hasn’t yet been picked up by the program (for lack of on-stack replacement).
Gathering these statistics costs some performance, so it isn’t done by default.

<<insert sample output, discuss it>>
