# xc7k70t UART Peripheral Boot Demo

This FPGA demo keeps the BRAM-resident UART bootloader from
`xc7k70t_uart_boot_demo` and adds the newer Min8 peripheral chain for board
bring-up:

- LED latch on `IO 0`
- UART passthrough / bootloader transport on unclaimed channels, including `IO 1`
- PS/2 receiver on `IO 0x10`
- 8-bit audio sigma-delta output on `IO 0x11`
- WS2812 serializer on `IO 0x12`
- FILO stack device on `IO 0x13`

Board pinout used here:

- `clk_200M_p/n`: `AA10/AB10`
- `uart_tx`: `M21`
- `uart_rx`: `K22`
- `ps2_clk`: `C22`
- `ps2_data`: `M19`
- `ws2812_out`: `F23`
- `audio_dsm_out`: `G24`

The wrapper still rate-limits `IO 0` updates so LED demos remain visible.
Audio and WS2812 timings are derived from the actual core clock, so the default
`150 MHz` build keeps the intended `16 kHz` audio sample rate and WS2812 pulse
widths.

Build the project:

```bash
source /run/media/j31415/228c191d-35f5-4acb-a476-41d3e8ff9d8a/vivado/2025.2/Vivado/settings64.sh
vivado -mode batch -source fpga/xc7k70t_uart_peripheral_boot_demo/build_bram_impl.tcl
```

The project is configured so `write_bitstream` emits both `.bit` and `.bin`.

Or create/open the project manually:

```bash
source /run/media/j31415/228c191d-35f5-4acb-a476-41d3e8ff9d8a/vivado/2025.2/Vivado/settings64.sh
vivado -mode batch -source fpga/xc7k70t_uart_peripheral_boot_demo/create_project_bram.tcl
vivado fpga/xc7k70t_uart_peripheral_boot_demo/vivado_proj_bram/min8_uart_peripheral_boot_bram.xpr
```

Rebuild the bootloader image after editing `bootloader.asm`:

```bash
source .venv/bin/activate
min8-asm fpga/xc7k70t_uart_peripheral_boot_demo/bootloader.asm --format memh -o fpga/xc7k70t_uart_peripheral_boot_demo/bootloader.memh
```

Download a Min8 program after the board is configured:

```bash
source .venv/bin/activate
min8-uart-download --port /dev/ttyUSB0 examples/uart_echo.asm
```

Useful bring-up programs:

- `examples/ps2_scan_echo.asm`
- `examples/audio_saw.asm`
- `examples/ws2812_2x2_cycle.asm`
- `examples/filo_stack.asm`

The downloader still transmits only `0x00..0xFB`. Any non-zero bytes at
`0xFC..0xFF` are rejected because those four locations stay occupied by the
bootloader loop.
