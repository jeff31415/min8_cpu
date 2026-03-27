# Min8 CPU

Reference implementation workspace for the Min8 8-bit ISA.

## Environment

Use the project-local virtual environment in `.venv`.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m unittest discover -s tests -v
```

If `.venv` already exists but is missing `pip`, repair it with:

```bash
.venv/bin/python -m ensurepip --upgrade
```

## Tooling

Assemble a source file directly into a 256-byte memory image:

```bash
source .venv/bin/activate
min8-asm examples/store_demo.asm
```

That writes `examples/store_demo.bin` by default. You can also emit a Verilog-friendly hex file:

```bash
min8-asm examples/store_demo.asm --format memh
```

Launch the GUI simulator and load an assembly program immediately:

```bash
min8-gui examples/echo.asm
```

GUI debugger supports:

- source and disassembly views
- double-click line breakpoint toggling
- register / flag / `PC` / `IOSEL` editing
- memory byte editing
- color-grouped register panels
- syntax highlighting for assembly source
- per-step highlight of updated registers and memory

Assembler alias and pseudo-instruction reference:

- [docs/assembler_aliases.md](/home/j31415/repos/min8_cpu/docs/assembler_aliases.md)

Current scope:

- frozen ISA document in `min8_isa_v1_2.md`
- phase-0 simulator/tooling contracts
- phase-1 reference simulator with tests
- phase-2 assembler with labels, directives, and pseudo-ops
- disassembler
- interactive session layer with breakpoints and state editing
- GUI simulator/debugger

Planned next:

- Verilog RTL and hardware bring-up
