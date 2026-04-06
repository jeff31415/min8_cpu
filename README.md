# Min8 CPU

Min8 is a minimalist 8-bit, fixed-length ISA intended for simple software
simulation, compact RTL implementation, capable I/O handling, and enjoyable
assembly programming.

This repository contains the current end-to-end reference workspace for Min8:

- ISA documentation
- Python reference simulator
- assembler and disassembler
- GUI simulator/debugger
- Verilog RTL with lockstep verification
- FPGA bring-up demo for `xc7k70tfbg676-1`
- UART bootloader demo for `xc7k70tfbg676-1`

## Environment

Use the project-local virtual environment in `.venv`.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m unittest discover -s tests -v
```

For RTL verification, install the optional cocotb dependency:

```bash
python -m pip install -e ".[rtl]"
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

- [docs/assembler_aliases.md](docs/assembler_aliases.md)

Current scope:

- frozen ISA document in `min8_isa_v1_3.md`
- phase-0 simulator/tooling contracts
- phase-1 reference simulator with tests
- phase-2 assembler with labels, directives, short-immediate shrinking, and ALU pseudo-ops
- disassembler
- interactive session layer with breakpoints and state editing
- GUI simulator/debugger
- Verilog RTL core with BRAM-backed lockstep verification
- FPGA bring-up demo for `xc7k70tfbg676-1`
- UART bootloader demo with small FIFOs and host-side downloader

Planned next:

- broader directed/random RTL test generation
- more board demos and external I/O integration

## FPGA Demo

The current board bring-up reference lives in:

- [fpga/xc7k70t_fib_led_demo/README.md](fpga/xc7k70t_fib_led_demo/README.md)
- [fpga/xc7k70t_uart_boot_demo/README.md](fpga/xc7k70t_uart_boot_demo/README.md)

That demo targets `xc7k70tfbg676-1`, uses BRAM for the Min8 memory image,
derives a `100 MHz` core clock from the board `200 MHz` differential clock,
and exposes Min8 I/O channel `0` on the LED bank.

Open the tracked Vivado project directly:

```bash
source <vivado-install>/settings64.sh
vivado fpga/xc7k70t_fib_led_demo/vivado_proj_bram/min8_fib_led_demo_bram.xpr
```

Or rebuild it from Tcl:

```bash
source <vivado-install>/settings64.sh
vivado -mode batch -source fpga/xc7k70t_fib_led_demo/build_bram_impl.tcl
```

The UART bootloader demo preloads a self-overwriting loader into BRAM, receives
`252` bytes on `IOSEL=0x01`, and then jumps back to `0x00`. Download a program
with:

```bash
source .venv/bin/activate
min8-uart-download --port /dev/ttyUSB0 examples/uart_echo.asm
```

## RTL Tests

If you installed OSS CAD Suite locally in the repository, the RTL smoke runner
will auto-detect `oss-cad-suite/bin`. Otherwise export it yourself:

```bash
export PATH="/path/to/oss-cad-suite/bin:$PATH"
```

Run the current Verilator + cocotb RTL suite with:

```bash
source .venv/bin/activate
python -m unittest tests_rtl.test_verilator_runner -v
```

Scale up the randomized portion with parallel shards:

```bash
source .venv/bin/activate
export MIN8_RTL_RANDOM_CASES=2000
export MIN8_RTL_RANDOM_JOBS=4
python -m unittest tests_rtl.test_verilator_runner -v
```

Enable optional exact cycle detection in the randomized suite:

```bash
source .venv/bin/activate
export MIN8_RTL_RANDOM_ENABLE_CYCLE_DETECT=1
python -m unittest tests_rtl.test_verilator_runner -v
```

That suite currently includes:

- basic smoke tests for reset / HALT / simple execution
- lockstep checks against the Python reference simulator for arithmetic, memory, branching, and blocking I/O programs
- deterministic randomized-image lockstep regression with failure artifact capture
- successful randomized outcomes for `halted_match`, `bounded_match`, `cycle_match`, and `illegal_match`

RTL verification docs:

- [docs/rtl_test_framework.md](docs/rtl_test_framework.md)
- [docs/rtl_random_verifier.md](docs/rtl_random_verifier.md)
- [docs/rtl_random_verifier_contract.md](docs/rtl_random_verifier_contract.md)
