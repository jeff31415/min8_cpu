set script_dir [file normalize [file dirname [info script]]]
set repo_root [file normalize [file join $script_dir .. ..]]
set project_dir [file join $script_dir vivado_proj_bram]
set project_name min8_uart_boot_bram
set io0_tick_divisor 100000000
set mem_init_file [file normalize [file join $script_dir bootloader.memh]]

create_project $project_name $project_dir -part xc7k70tfbg676-1 -force
set_property target_language Verilog [current_project]
set_property default_lib xil_defaultlib [current_project]

add_files [list \
    [file join $script_dir min8_uart_boot_bram_top.v] \
    [file join $repo_root rtl min8_alu.v] \
    [file join $repo_root rtl min8_regfile.v] \
    [file join $repo_root rtl min8_bram_wrap.v] \
    [file join $repo_root rtl min8_core.v] \
    [file join $repo_root rtl min8_sync_fifo.v] \
    [file join $repo_root rtl min8_uart_rx.v] \
    [file join $repo_root rtl min8_uart_tx.v] \
]

add_files -fileset constrs_1 [list [file join $script_dir min8_uart_boot_demo.xdc]]
add_files -fileset sources_1 [list [file join $script_dir bootloader.memh]]
set_property file_type {Memory File} [get_files [file join $script_dir bootloader.memh]]
set_property top min8_uart_boot_bram_top [current_fileset]
set_property generic [format {MEM_INIT_FILE=%s IO0_TICK_DIVISOR=%d} $mem_init_file $io0_tick_divisor] [current_fileset]
update_compile_order -fileset sources_1

puts "Created BRAM UART boot project at $project_dir/$project_name.xpr"
