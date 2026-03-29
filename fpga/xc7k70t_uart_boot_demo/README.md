# xc7k70t UART Boot Demo

This FPGA demo boots Min8 from BRAM with a tiny self-overwriting bootloader.
On reset, memory contains the bootloader image. The bootloader selects
`IOSEL = 0x01`, receives exactly `252` bytes over UART, writes them to
`0x00..0xFB`, then falls through to `PC = 0x00`.

Channel mapping:

- `IO 0`: LED output, latched onto the 8-LED bank
- `IO 1`: UART RX/TX through small 4-byte FIFOs

`IO 0` is rate-limited in the top-level wrapper. By default it accepts one
byte per second at `100 MHz`, so programs like `fib.asm` can be watched on the
LED bank instead of immediately racing to their last value.

Board I/O used here:

- `clk_200M_p/n`: `AA10/AB10`
- `uart_tx`: `M21`
- `uart_rx`: `K22`

Files:

- `min8_uart_boot_bram_top.v`
- `min8_uart_boot_demo.xdc`
- `bootloader.asm`
- `bootloader.memh`

Build the project:

```bash
source <vivado-install>/settings64.sh
vivado -mode batch -source fpga/xc7k70t_uart_boot_demo/build_bram_impl.tcl
```

Or create/open the project manually:

```bash
source <vivado-install>/settings64.sh
vivado -mode batch -source fpga/xc7k70t_uart_boot_demo/create_project_bram.tcl
vivado fpga/xc7k70t_uart_boot_demo/vivado_proj_bram/min8_uart_boot_bram.xpr
```

Tune the LED output rate by editing `io0_tick_divisor` in
`create_project_bram.tcl` or by changing the top-level generic
`IO0_TICK_DIVISOR` in Vivado.

Rebuild the bootloader image after editing `bootloader.asm`:

```bash
source .venv/bin/activate
min8-asm fpga/xc7k70t_uart_boot_demo/bootloader.asm --format memh -o fpga/xc7k70t_uart_boot_demo/bootloader.memh
```

Download a Min8 program after the board is configured:

```bash
source .venv/bin/activate
min8-uart-download --port /dev/ttyUSB0 examples/uart_echo.asm
```

The downloader transmits only `0x00..0xFB`. Any non-zero bytes at
`0xFC..0xFF` are rejected because those four locations stay occupied by the
bootloader loop.
