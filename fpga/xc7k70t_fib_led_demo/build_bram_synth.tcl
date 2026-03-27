set script_dir [file normalize [file dirname [info script]]]
set reports_dir [file join $script_dir reports]
file mkdir $reports_dir
source [file join $script_dir create_project_bram.tcl]

launch_runs synth_1 -jobs 8
wait_on_run synth_1

open_run synth_1
report_utilization -file [file join $reports_dir utilization_synth.rpt]
report_timing_summary -file [file join $reports_dir timing_summary_synth.rpt]

puts "BRAM synthesis reports ready:"
puts [file join $reports_dir utilization_synth.rpt]
puts [file join $reports_dir timing_summary_synth.rpt]
