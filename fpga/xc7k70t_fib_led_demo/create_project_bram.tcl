set script_dir [file normalize [file dirname [info script]]]
set repo_root [file normalize [file join $script_dir .. ..]]
set project_dir [file join $script_dir vivado_proj_bram]
set project_name min8_fib_led_demo_bram
set mem_init_file [file normalize [file join $script_dir fib_led_demo.memh]]

create_project $project_name $project_dir -part xc7k70tfbg676-1 -force
set_property target_language Verilog [current_project]
set_property default_lib xil_defaultlib [current_project]

add_files [list \
    [file join $script_dir min8_fib_led_demo_bram_top.v] \
    [file join $repo_root rtl min8_alu.v] \
    [file join $repo_root rtl min8_regfile.v] \
    [file join $repo_root rtl min8_bram_wrap.v] \
    [file join $repo_root rtl min8_core.v] \
]

add_files -fileset constrs_1 [list [file join $script_dir min8_fib_led_demo.xdc]]
add_files -fileset sources_1 [list [file join $script_dir fib_led_demo.memh]]
set_property file_type {Memory File} [get_files [file join $script_dir fib_led_demo.memh]]
set_property top min8_fib_led_demo_bram_top [current_fileset]
set_property generic [format {MEM_INIT_FILE=%s} $mem_init_file] [current_fileset]
update_compile_order -fileset sources_1

puts "Created BRAM project at $project_dir/$project_name.xpr"
