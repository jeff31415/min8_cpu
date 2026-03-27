set script_dir [file normalize [file dirname [info script]]]
set reports_dir [file join $script_dir reports]
file mkdir $reports_dir
source [file join $script_dir create_project_bram.tcl]

launch_runs impl_1 -to_step write_bitstream -jobs 8
wait_on_run impl_1

open_run impl_1
report_utilization -file [file join $reports_dir utilization_post_route.rpt]
report_timing_summary -file [file join $reports_dir timing_summary_post_route.rpt]
report_drc -file [file join $reports_dir drc_post_route.rpt]

puts "BRAM implementation reports ready:"
puts [file join $reports_dir utilization_post_route.rpt]
puts [file join $reports_dir timing_summary_post_route.rpt]
puts [file join $reports_dir drc_post_route.rpt]
