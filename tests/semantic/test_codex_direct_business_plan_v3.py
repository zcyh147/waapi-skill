from __future__ import annotations

import pytest

from tests.semantic.support.codex_direct_business_plan_v3 import (
    DirectBusinessPlanError,
    compile_direct_business_plan,
    parse_direct_business_plan_sections,
    validate_direct_archived_verification,
    validate_direct_business_plan,
    validate_direct_business_plan_archive,
)


def test_direct_plan_seals_zero_read_protocol_and_exact_host_identity() -> None:
    plan = compile_direct_business_plan(
        scenario_id="TYP21-ZERO-GET-INFO",
        api="ak.wwise.core.getInfo",
        protocol_steps=(
            {"name": "direct", "subcommand": "typed-zero-call"},
        ),
        live_bindings={"version": "2021.1", "process_id": 42},
        verification_boundary="exact_host_identity",
    )

    assert plan.static_expectation["api"] == "ak.wwise.core.getInfo"
    assert plan.live_binding["bindings"]["version"] == "2021.1"
    assert validate_direct_business_plan(
        plan,
        scenario_id="TYP21-ZERO-GET-INFO",
        api="ak.wwise.core.getInfo",
        protocol_steps=(
            {"name": "direct", "subcommand": "typed-zero-call"},
        ),
        live_bindings={"version": "2021.1", "process_id": 42},
        verification_boundary="exact_host_identity",
    ) == plan


def test_direct_plan_rejects_unknown_verification_boundary() -> None:
    with pytest.raises(DirectBusinessPlanError, match="verification boundary"):
        compile_direct_business_plan(
            scenario_id="TYP25-LUA",
            api="ak.wwise.core.executeLuaScript",
            protocol_steps=(
                {"name": "tx01.verify", "subcommand": "verify"},
            ),
            live_bindings={"version": "2025.1"},
            verification_boundary="invented_business_readback",
        )


def test_direct_archive_recomputes_get_info_plan_and_rejects_tamper() -> None:
    steps = (
        {"name": "host.get-info.schema", "subcommand": "request-schema"},
        {"name": "host.get-info", "subcommand": "typed-zero-call"},
    )
    bindings = {
        "version": "2021.1",
        "build": "2021.1.8100.0",
        "process_id": 42,
        "launch_process_id": 41,
        "session_id": "session",
        "result_sha256": "a" * 64,
        "project_digest": "b" * 64,
    }
    plan = compile_direct_business_plan(
        scenario_id="O22-GET-INFO-01",
        api="ak.wwise.core.getInfo",
        protocol_steps=steps,
        live_bindings=bindings,
        verification_boundary="exact_host_identity",
    )
    parsed = parse_direct_business_plan_sections(plan.writer_kwargs())

    assert validate_direct_business_plan_archive(
        parsed,
        scenario_id="O22-GET-INFO-01",
        api="ak.wwise.core.getInfo",
        version="2021.1",
        protocol_steps=steps,
    ) == parsed
    validate_direct_archived_verification(
        parsed,
        {
            "passed": True,
            "failures": [],
            "evidence": {
                "expected_build": bindings["build"],
                "expected_process_id": 42,
                "expected_result_sha256": "a" * 64,
                "actual_result_sha256": "a" * 64,
            },
        },
    )

    tampered = plan.writer_kwargs()
    tampered["live_binding"]["bindings"]["process_id"] = 43
    with pytest.raises(DirectBusinessPlanError, match="digest or derived"):
        validate_direct_business_plan_archive(
            parse_direct_business_plan_sections(tampered),
            scenario_id="O22-GET-INFO-01",
            api="ak.wwise.core.getInfo",
            version="2021.1",
            protocol_steps=steps,
        )
