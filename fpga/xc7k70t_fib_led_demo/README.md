# xc7k70t BRAM Fibonacci LED Demo

This is the current FPGA reference demo for the rough-board `xc7k70tfbg676-1`.

Commands below assume the current working directory is the repository root and
Vivado has already been added to `PATH`, or its `settings64.sh` has been
sourced separately.

What it does:

- uses the verified `200 MHz` differential clock on `AA10/AB10`
- derives a clean `100 MHz clk_core` with `PLLE2_BASE + BUFG`
- instantiates the current BRAM-backed `min8_core`
- preloads BRAM from `fib_led_demo.memh`
- runs a Min8 program that writes Fibonacci numbers to I/O channel `0`
- exposes channel `0` on the 8 user LEDs
- only asserts `tx_ready` once per second, so the LED value advances at `1 Hz`

Key files:

- `min8_fib_led_demo_bram_top.v`
- `min8_fib_led_demo.xdc`
- `fib_led_demo.asm`
- `fib_led_demo.memh`
- `create_project_bram.tcl`
- `build_bram_synth.tcl`
- `build_bram_impl.tcl`
- `vivado_proj_bram/min8_fib_led_demo_bram.xpr`

Current validated results are snapshot in `reports/`.

Open the demo project directly in Vivado:

```bash
vivado fpga/xc7k70t_fib_led_demo/vivado_proj_bram/min8_fib_led_demo_bram.xpr
```

Recreate the project from Tcl:

```bash
vivado -mode batch -source fpga/xc7k70t_fib_led_demo/create_project_bram.tcl
```

Rebuild synthesis only:

```bash
vivado -mode batch -source fpga/xc7k70t_fib_led_demo/build_bram_synth.tcl
```

Rebuild implementation and bitstream:

```bash
vivado -mode batch -source fpga/xc7k70t_fib_led_demo/build_bram_impl.tcl
```

If the repository is moved, rerun `create_project_bram.tcl` once to refresh the
project-local absolute memory-init path used by the tracked `.xpr`.
