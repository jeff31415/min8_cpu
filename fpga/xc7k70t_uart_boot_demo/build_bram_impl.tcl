proc set_default {name value} {
    upvar #0 $name var
    if {![info exists var]} {
        set var $value
    }
}

proc mhz_tag {freq_hz} {
    return [string map {. p} [format "%.3f" [expr {double($freq_hz) / 1000000.0}]]]
}

set_default script_dir [file normalize [file dirname [info script]]]

if {[llength $argv] >= 1} {
    set core_clk_hz [expr {int(round(double([lindex $argv 0]) * 1000000.0))}]
}
if {[llength $argv] >= 2} {
    set constraint_core_clk_hz [expr {int(round(double([lindex $argv 1]) * 1000000.0))}]
}
if {[llength $argv] >= 3} {
    set run_tag [lindex $argv 2]
}

if {[info exists core_clk_hz] && ![info exists run_tag]} {
    set run_tag [format "core_%s__constraint_%s" \
        [mhz_tag $core_clk_hz] \
        [mhz_tag [expr {[info exists constraint_core_clk_hz] ? $constraint_core_clk_hz : $core_clk_hz}]]]
}

if {[info exists run_tag]} {
    set_default project_dir [file join $script_dir sweep_runs $run_tag project]
    set_default project_name [string map {. _ - _} [format "min8_uart_boot_bram_%s" $run_tag]]
    set_default reports_dir [file join $script_dir sweep_runs $run_tag reports]
    set_default impl_to_step route_design
} else {
    set_default reports_dir [file join $script_dir reports]
    set_default impl_to_step write_bitstream
}

set_default impl_jobs 6
file mkdir $reports_dir

source [file join $script_dir create_project_bram.tcl]
launch_runs impl_1 -to_step $impl_to_step -jobs $impl_jobs
wait_on_run impl_1
open_run impl_1
report_timing_summary -file [file join $reports_dir timing_summary_post_route.rpt]
report_utilization -file [file join $reports_dir utilization_post_route.rpt]
report_drc -file [file join $reports_dir drc_post_route.rpt]
