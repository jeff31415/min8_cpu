from __future__ import annotations

from pathlib import Path

import cocotb

from tests_rtl.support.lockstep import make_reference_state_key, run_lockstep_image
from tests_rtl.support.randomized import (
    RandomizedIOScript,
    build_random_case,
    load_randomized_test_config_from_env,
    random_case_seed,
)


@cocotb.test()
async def test_randomized_images_lockstep(dut) -> None:
    config = load_randomized_test_config_from_env()
    artifact_root = Path(config.artifact_root)
    outcome_counts = {
        "halted_match": 0,
        "bounded_match": 0,
        "cycle_match": 0,
        "illegal_match": 0,
    }

    for local_case_index in range(config.case_count):
        case_index = config.case_offset + local_case_index
        case_seed = random_case_seed(config.base_seed, case_index)
        case = build_random_case(case_seed, case_index, max_program_bytes=config.max_program_bytes)
        io_script = RandomizedIOScript(case.io_seed)
        cycle_state_key = None
        if config.enable_cycle_detect:
            cycle_state_key = lambda cpu, io, _event_index, io_script=io_script: (
                make_reference_state_key(cpu, io),
                io_script.replay_state_key(),
            )

        result = await run_lockstep_image(
            dut,
            case.image,
            case_name=case.label,
            max_events=config.max_events,
            setup_io=io_script.setup,
            on_event=io_script.on_event,
            artifact_root=artifact_root,
            failure_context=lambda case=case, io_script=io_script: {
                "random_case": case.to_metadata(),
                "io_script": io_script.snapshot(),
            },
            cycle_state_key=cycle_state_key,
        )
        outcome_counts[result.outcome] += 1

    cocotb.log.info(
        "Randomized lockstep outcomes: halted=%d bounded=%d cycle=%d illegal=%d",
        outcome_counts["halted_match"],
        outcome_counts["bounded_match"],
        outcome_counts["cycle_match"],
        outcome_counts["illegal_match"],
    )
