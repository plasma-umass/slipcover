from types import CodeType
import copy
import dis
import inspect

# Pick an illegal opcode, any illegal opcode.
all_opcodes = { i for i in range(256) }
legal_opcodes = { dis.opmap[i] for i in dis.opmap }
illegal_opcodes = all_opcodes - legal_opcodes
illegal_opcode = (list(illegal_opcodes)[-1]).to_bytes(2, byteorder='little')

# Simple function to try to patch.
def hello():
    print("hello world")

# Grab the source code for the function
hello_src = inspect.getsourcelines(hello)
full_src = ''.join(hello_src[0])
# Compile it.
code = compile(full_src, "", "exec")
# Print the disassembly.
dis.dis(code)

# Run it for kicks.
hello()

# Now alter the code; we need to create a whole new object.
payload = copy.copy(code.co_code)
original_payload = copy.copy(code.co_code) # Backup copy of original code
old_payload_opcodes = payload[0:1] # Grab the first two bytes to save
payload = illegal_opcode + payload[1:]
hello.__code__ = hello.__code__.replace(co_code=payload)

try:
    hello()
except SystemError:
    # We will get here because the first bytecode (byteword, really) is illegal.
    print("trapped")
    # Now restore the original code.
    hello.__code__ = hello.__code__.replace(co_code=original_payload)
    code = compile(full_src, "", "exec")
    exec(code)
    hello()

