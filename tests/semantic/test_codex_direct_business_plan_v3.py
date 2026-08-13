from __future__ import annotations

import os

import pytest

from tests.semantic.support.codex_direct_business_plan_v3 import (
    DirectBusinessPlanError,
    compile_direct_business_plan,
    parse_direct_business_plan_sections,
    validate_direct_archived_verification,
    validate_direct_business_plan,
    validate_direct_business_plan_archive,
    validate_direct_status_archive_binding,
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
        {"name": "host.status", "subcommand": "status"},
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
        "status": {
            "wwise_build": "2021.1.8100.0",
            "process_id": 42,
            "project": {
                "id": "{16164796-C6E6-491A-8799-C42A33110A84}",
                "name": "SampleProject",
                "type": "Project",
                "path": "\\",
            },
        },
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
    with pytest.raises(DirectBusinessPlanError, match="identity|digest or derived"):
        validate_direct_business_plan_archive(
            parse_direct_business_plan_sections(tampered),
            scenario_id="O22-GET-INFO-01",
            api="ak.wwise.core.getInfo",
            version="2021.1",
            protocol_steps=steps,
        )


def test_direct_archive_rejects_a_consistently_rehashed_foreign_status_project() -> None:
    steps = (
        {"name": "host.status", "subcommand": "status"},
        {"name": "host.get-info.schema", "subcommand": "request-schema"},
        {"name": "host.get-info", "subcommand": "typed-zero-call"},
    )
    bindings = {
        "version": "2025.1",
        "build": "2025.1.0.9000",
        "process_id": 42,
        "launch_process_id": 41,
        "session_id": "session",
        "result_sha256": "a" * 64,
        "project_digest": "b" * 64,
        "status": {
            "wwise_build": "2025.1.0.9000",
            "process_id": 42,
            "project": {
                "id": "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}",
                "name": "OtherProject",
                "type": "Project",
                "path": "OtherProject.wproj",
            },
        },
    }
    sections = compile_direct_business_plan(
        scenario_id="O22-GET-INFO-01",
        api="ak.wwise.core.getInfo",
        protocol_steps=steps,
        live_bindings=bindings,
        verification_boundary="exact_host_identity",
    )
    real_status = {
        "wwise": {
            "processId": 42,
            "version": {"year": 2025, "major": 1, "minor": 0, "build": 9000},
        },
        "project": {
            "id": "{16164796-C6E6-491A-8799-C42A33110A84}",
            "name": "SampleProject",
            "type": "Project",
            "path": "/owned/SampleProject.wproj",
        },
    }

    with pytest.raises(DirectBusinessPlanError, match="lifecycle sandbox|archived"):
        validate_direct_status_archive_binding(
            sections,
            status_payload=real_status,
            sandbox_project="/owned/SampleProject.wproj",
        )


@pytest.mark.parametrize(
    ("status_path", "sandbox_project"),
    (
        ("/owned/SampleProject.wproj", "/owned/SampleProject.wproj"),
        (r"Z:\owned\SAMPLEPROJECT.WPROJ", "/owned/SampleProject.wproj"),
    ),
)
@pytest.mark.skipif(os.name == "nt", reason="POSIX/Wine path proof")
def test_direct_archive_accepts_same_project_across_posix_and_wine_path_flavors(
    status_path: str,
    sandbox_project: str,
) -> None:
    steps = (
        {"name": "host.status", "subcommand": "status"},
        {"name": "host.get-info.schema", "subcommand": "request-schema"},
        {"name": "host.get-info", "subcommand": "typed-zero-call"},
    )
    bindings = {
        "version": "2025.1",
        "build": "2025.1.0.9000",
        "process_id": 42,
        "launch_process_id": 41,
        "session_id": "session",
        "result_sha256": "a" * 64,
        "project_digest": "b" * 64,
        "status": {
            "wwise_build": "2025.1.0.9000",
            "process_id": 42,
            "project": {
                "id": "{16164796-C6E6-491A-8799-C42A33110A84}",
                "name": "SampleProject",
                "type": "Project",
                "path": "SampleProject.wproj",
            },
        },
    }
    sections = compile_direct_business_plan(
        scenario_id="O22-GET-INFO-01",
        api="ak.wwise.core.getInfo",
        protocol_steps=steps,
        live_bindings=bindings,
        verification_boundary="exact_host_identity",
    )
    status = {
        "wwise": {
            "processId": 42,
            "version": {"year": 2025, "major": 1, "minor": 0, "build": 9000},
        },
        "project": {
            **bindings["status"]["project"],
            "path": status_path,
        },
    }

    validate_direct_status_archive_binding(
        sections,
        status_payload=status,
        sandbox_project=sandbox_project,
    )


@pytest.mark.parametrize(
    ("version", "build", "version_tuple"),
    (
        ("2021.1", "2021.1.14.8108", (2021, 1, 14, 8108)),
        ("2025.1", "2025.1.0.9000", (2025, 1, 0, 9000)),
    ),
)
@pytest.mark.skipif(os.name != "nt", reason="native Windows path proof")
def test_direct_archive_accepts_native_windows_case_insensitive_project_path(
    version: str,
    build: str,
    version_tuple: tuple[int, int, int, int],
) -> None:
    bindings = {
        "version": version,
        "build": build,
        "process_id": 42,
        "launch_process_id": 41,
        "session_id": "session",
        "result_sha256": "a" * 64,
        "project_digest": "b" * 64,
        "status": {
            "wwise_build": build,
            "process_id": 42,
            "project": {
                "id": "{16164796-C6E6-491A-8799-C42A33110A84}",
                "name": "SampleProject",
                "type": "Project",
                "path": "\\" if version == "2021.1" else "SampleProject.wproj",
            },
        },
    }
    sections = compile_direct_business_plan(
        scenario_id="O22-GET-INFO-01",
        api="ak.wwise.core.getInfo",
        protocol_steps=({"name": "host.status", "subcommand": "status"},),
        live_bindings=bindings,
        verification_boundary="exact_host_identity",
    )
    status = {
        "wwise": {
            "processId": 42,
            "version": dict(
                zip(
                    ("year", "major", "minor", "build"),
                    version_tuple,
                    strict=True,
                )
            ),
        },
        "project": {
            **bindings["status"]["project"],
            "path": "\\" if version == "2021.1" else r"C:\owned\SAMPLEPROJECT.WPROJ",
        },
    }

    validate_direct_status_archive_binding(
        sections,
        status_payload=status,
        sandbox_project=r"C:\owned\SampleProject.wproj",
    )


def test_direct_archive_rejects_unmappable_unc_status_path() -> None:
    bindings = {
        "version": "2025.1",
        "build": "2025.1.0.9000",
        "process_id": 42,
        "launch_process_id": 41,
        "session_id": "session",
        "result_sha256": "a" * 64,
        "project_digest": "b" * 64,
        "status": {
            "wwise_build": "2025.1.0.9000",
            "process_id": 42,
            "project": {
                "id": "{16164796-C6E6-491A-8799-C42A33110A84}",
                "name": "SampleProject",
                "type": "Project",
                "path": "SampleProject.wproj",
            },
        },
    }
    sections = compile_direct_business_plan(
        scenario_id="O22-GET-INFO-01",
        api="ak.wwise.core.getInfo",
        protocol_steps=({"name": "host.status", "subcommand": "status"},),
        live_bindings=bindings,
        verification_boundary="exact_host_identity",
    )
    status = {
        "wwise": {
            "processId": 42,
            "version": {"year": 2025, "major": 1, "minor": 0, "build": 9000},
        },
        "project": {
            **bindings["status"]["project"],
            "path": r"\\server\share\SampleProject.wproj",
        },
    }

    with pytest.raises(DirectBusinessPlanError, match="path identity"):
        validate_direct_status_archive_binding(
            sections,
            status_payload=status,
            sandbox_project="/owned/SampleProject.wproj",
        )
