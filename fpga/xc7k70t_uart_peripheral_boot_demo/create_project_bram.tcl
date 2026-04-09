proc set_default {name value} {
    upvar #0 $name var
    if {![info exists var]} {
        set var $value
    }
}

proc find_pll_config_for_hz {clkin_hz target_hz} {
    set best [dict create]

    for {set divclk 1} {$divclk <= 56} {incr divclk} {
        set pfd_hz [expr {double($clkin_hz) / $divclk}]
        if {$pfd_hz < 19000000.0 || $pfd_hz > 450000000.0} {
            continue
        }

        for {set mult 2} {$mult <= 64} {incr mult} {
            set vco_hz [expr {double($clkin_hz) * $mult / $divclk}]
            if {$vco_hz < 400000000.0 || $vco_hz > 1080000000.0} {
                continue
            }

            set numer [expr {$clkin_hz * $mult}]
            set denom [expr {$divclk * $target_hz}]
            if {($numer % $denom) != 0} {
                continue
            }

            set outdiv [expr {$numer / $denom}]
            if {$outdiv < 1 || $outdiv > 128} {
                continue
            }

            if {![dict exists $best vco_hz] ||
                ($vco_hz > [dict get $best vco_hz]) ||
                (($vco_hz == [dict get $best vco_hz]) &&
                 ($outdiv < [dict get $best clkout0_divide]))} {
                set best [dict create \
                    clkfbout_mult $mult \
                    divclk_divide $divclk \
                    clkout0_divide $outdiv \
                    vco_hz $vco_hz]
            }
        }
    }

    if {![dict exists $best clkfbout_mult]} {
        error [format "No legal PLLE2_BASE config found for %.3f MHz output clock" \
            [expr {double($target_hz) / 1000000.0}]]
    }

    return $best
}

set_default script_dir [file normalize [file dirname [info script]]]
set_default repo_root [file normalize [file join $script_dir .. ..]]
set_default project_dir [file join $script_dir vivado_proj_bram]
set_default project_name min8_uart_peripheral_boot_bram
set_default clkin_hz 200000000
set_default core_clk_hz 150000000
set_default constraint_core_clk_hz $core_clk_hz
set_default mem_init_file [file normalize [file join $script_dir bootloader.memh]]

if {![info exists pll_clkfbout_mult] ||
    ![info exists pll_divclk_divide] ||
    ![info exists pll_clkout0_divide]} {
    set pll_config [find_pll_config_for_hz $clkin_hz $core_clk_hz]
    set pll_clkfbout_mult [dict get $pll_config clkfbout_mult]
    set pll_divclk_divide [dict get $pll_config divclk_divide]
    set pll_clkout0_divide [dict get $pll_config clkout0_divide]
}

set core_clk_hz [expr {($clkin_hz * $pll_clkfbout_mult) / ($pll_divclk_divide * $pll_clkout0_divide)}]
set_default io0_tick_divisor $core_clk_hz
set actual_core_period_ns [expr {1.0e9 / double($core_clk_hz)}]
set constraint_core_period_ns [expr {1.0e9 / double($constraint_core_clk_hz)}]
set extra_setup_uncertainty_ns 0.0
if {$constraint_core_period_ns < $actual_core_period_ns} {
    set extra_setup_uncertainty_ns [expr {$actual_core_period_ns - $constraint_core_period_ns}]
}

create_project $project_name $project_dir -part xc7k70tfbg676-1 -force
set_property target_language Verilog [current_project]
set_property default_lib xil_defaultlib [current_project]

add_files [list \
    [file join $script_dir min8_uart_peripheral_boot_bram_top.v] \
    [file join $repo_root rtl min8_alu.v] \
    [file join $repo_root rtl min8_regfile.v] \
    [file join $repo_root rtl min8_bram_wrap.v] \
    [file join $repo_root rtl min8_core.v] \
    [file join $repo_root rtl min8_io_audio.v] \
    [file join $repo_root rtl min8_io_filo.v] \
    [file join $repo_root rtl min8_io_peripheral_chain.v] \
    [file join $repo_root rtl min8_io_ps2.v] \
    [file join $repo_root rtl min8_io_ws2812.v] \
    [file join $repo_root rtl min8_sync_fifo.v] \
    [file join $repo_root rtl min8_uart_rx.v] \
    [file join $repo_root rtl min8_uart_tx.v] \
]

add_files -fileset constrs_1 [list [file join $script_dir min8_uart_peripheral_boot_demo.xdc]]
if {$extra_setup_uncertainty_ns > 0.0} {
    set timing_override_xdc [file join $project_dir timing_override.xdc]
    set timing_override_fh [open $timing_override_xdc w]
    puts $timing_override_fh [format {set_clock_uncertainty -setup %.3f [get_clocks clk_core]} $extra_setup_uncertainty_ns]
    close $timing_override_fh
    add_files -fileset constrs_1 [list $timing_override_xdc]
}
add_files -fileset sources_1 [list [file join $script_dir bootloader.memh]]
set_property file_type {Memory File} [get_files [file join $script_dir bootloader.memh]]
set_property top min8_uart_peripheral_boot_bram_top [current_fileset]
set_property generic [format {MEM_INIT_FILE=%s IO0_TICK_DIVISOR=%d CLKIN_HZ=%d PLL_CLKFBOUT_MULT=%d PLL_DIVCLK_DIVIDE=%d PLL_CLKOUT0_DIVIDE=%d} \
    $mem_init_file $io0_tick_divisor $clkin_hz $pll_clkfbout_mult $pll_divclk_divide $pll_clkout0_divide] [current_fileset]
set_property STEPS.WRITE_BITSTREAM.ARGS.BIN_FILE true [get_runs impl_1]
update_compile_order -fileset sources_1

puts [format "Created BRAM UART boot project at %s/%s.xpr" $project_dir $project_name]
puts [format "  clk_core actual      : %.3f MHz" [expr {double($core_clk_hz) / 1000000.0}]]
puts [format "  clk_core constrained : %.3f MHz" [expr {double($constraint_core_clk_hz) / 1000000.0}]]
puts [format "  PLL config           : DIVCLK=%d MULT=%d OUTDIV=%d" \
    $pll_divclk_divide $pll_clkfbout_mult $pll_clkout0_divide]
if {$extra_setup_uncertainty_ns > 0.0} {
    puts [format "  setup overconstraint : %.3f ns" $extra_setup_uncertainty_ns]
}
