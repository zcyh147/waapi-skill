from __future__ import annotations

import copy
from types import MappingProxyType

import pytest

from tests.semantic.support.codex_workflow_business_plan_v3 import (
    WORKFLOW_BUSINESS_PLAN_SCHEMA,
    WorkflowBusinessPlanError,
    compile_workflow_business_plan_sections,
    parse_workflow_business_plan_sections,
    validate_workflow_business_plan_sections,
)


def _transaction(
    index: int,
    api: str,
    operation: str,
    phase: str,
) -> dict[str, object]:
    transaction_id = f"tx{index:02d}"
    return {
        "transaction_id": transaction_id,
        "api": api,
        "operation": operation,
        "phase": phase,
        "primary_step": f"{transaction_id}.execute",
    }


def _transaction_steps(transaction: dict[str, object]) -> list[dict[str, object]]:
    transaction_id = transaction["transaction_id"]
    values = (
        ("operation-schema", "operation_schema"),
        ("preview", "preview"),
        ("transaction-show", "transaction_show"),
        ("confirm", "confirm"),
        ("execute", "execute"),
        ("verify", "verify"),
    )
    return [
        {
            "name": f"{transaction_id}.{suffix}",
            "kind": kind,
            "phase": transaction["phase"],
            "transaction_id": transaction_id,
            "api": transaction["api"],
        }
        for suffix, kind in values
    ]


def _composer_transaction_steps(
    transaction: dict[str, object],
    *,
    action_count: int = 2,
) -> list[dict[str, object]]:
    transaction_id = transaction["transaction_id"]
    values = [
        ("operation-schema", "operation_schema"),
        ("draft-start", "operation_compose"),
        *(
            (f"action.{index:03d}", "operation_compose")
            for index in range(1, action_count + 1)
        ),
        ("check", "operation_compose_check"),
        ("preview", "preview"),
        ("transaction-show", "transaction_show"),
        ("confirm", "confirm"),
        ("execute", "execute"),
        ("verify", "verify"),
    ]
    return [
        {
            "name": f"{transaction_id}.{suffix}",
            "kind": kind,
            "phase": transaction["phase"],
            "transaction_id": transaction_id,
            "api": transaction["api"],
        }
        for suffix, kind in values
    ]


def _business_transaction_steps(
    transaction: dict[str, object],
    construction: list[str],
) -> list[dict[str, object]]:
    transaction_id = transaction["transaction_id"]
    values = [
        ("operation-schema", "operation_schema"),
        ("draft-start", "operation_compose"),
        *((name, "operation_compose") for name in construction),
        ("check", "operation_compose_check"),
        ("preview", "preview"),
        ("transaction-show", "transaction_show"),
        ("confirm", "confirm"),
        ("execute", "execute"),
        ("verify", "verify"),
    ]
    return [
        {
            "name": f"{transaction_id}.{suffix}",
            "kind": kind,
            "phase": transaction["phase"],
            "transaction_id": transaction_id,
            "api": transaction["api"],
        }
        for suffix, kind in values
    ]


def _workflow_inputs(kind: str) -> dict[str, object]:
    if kind == "three_transactions":
        transactions = [
            _transaction(
                1,
                "ak.wwise.core.audio.import",
                "audio.import",
                "import_weather_assets",
            ),
            _transaction(
                2,
                "ak.wwise.core.object.set",
                "object.set",
                "configure_event_actions",
            ),
            _transaction(
                3,
                "ak.wwise.core.object.set",
                "object.setRTPC",
                "bind_rain_intensity_rtpc",
            ),
        ]
        workflow_id = "interactive_weather_build"
        diagnostics: list[dict[str, object]] = []
        steps = [
            step
            for transaction in transactions
            for step in _transaction_steps(transaction)
        ]
    elif kind == "diagnosis_and_repair":
        transactions = [
            _transaction(
                1,
                "ak.wwise.core.object.setReference",
                "object.setReference",
                "repair_output_bus",
            )
        ]
        workflow_id = "alarm_diagnose_and_repair"
        diagnostic_names = (
            "diag.search",
            "diag.event_graph",
            "diag.sound",
            "diag.source",
            "diag.bus",
        )
        steps = [
            {
                "name": name,
                "kind": "diagnostic",
                "phase": "diagnose_event_chain",
                "transaction_id": None,
                "api": "ak.wwise.core.object.get",
            }
            for name in diagnostic_names
        ]
        diagnostics = [
            {
                "evidence_id": name.replace(".", "/"),
                "step": name,
                "api": "ak.wwise.core.object.get",
                "phase": "diagnose_event_chain",
                "expectation": {
                    "required_path": name,
                    "exclude_decoys": True,
                },
            }
            for name in diagnostic_names
        ]
        steps.extend(_transaction_steps(transactions[0]))
    elif kind == "two_transactions":
        transactions = [
            _transaction(
                1,
                "ak.wwise.core.soundbank.setInclusions",
                "soundbank.setInclusions",
                "replace_release_inclusions",
            ),
            _transaction(
                2,
                "ak.wwise.core.soundbank.generate",
                "soundbank.generate",
                "generate_windows_and_mac",
            ),
        ]
        workflow_id = "harbor_soundbank_release"
        diagnostics = []
        steps = [
            *_transaction_steps(transactions[0]),
            {
                "name": "checkpoint.inclusions",
                "kind": "checkpoint",
                "phase": "between_transactions",
                "transaction_id": None,
                "api": "ak.wwise.core.object.get",
            },
            *_transaction_steps(transactions[1]),
            {
                "name": "cleanup.outputs",
                "kind": "cleanup",
                "phase": "cleanup",
                "transaction_id": None,
                "api": None,
            },
        ]
    else:
        raise AssertionError(kind)

    return {
        "workflow_id": workflow_id,
        "transactions": transactions,
        "workflow_steps": steps,
        "diagnostic_evidence": diagnostics,
        "live_bindings": {
            "version": "2022.1",
            "before_snapshot_sha256": "a" * 64,
            "object_ids": {"root": "{00000000-0000-0000-0000-000000000001}"},
        },
        "transaction_expectations": [
            {
                "transaction_id": transaction["transaction_id"],
                "expectation": {
                    "phase": transaction["phase"],
                    "changed": [f"{transaction['transaction_id']}.target"],
                    "preserved": ["control"],
                },
            }
            for transaction in transactions
        ],
    }


@pytest.mark.parametrize(
    ("kind", "transaction_count", "diagnostic_count"),
    [
        ("three_transactions", 3, 0),
        ("diagnosis_and_repair", 1, 5),
        ("two_transactions", 2, 0),
    ],
)
def test_workflow_sections_round_trip_all_reviewed_topologies(
    kind: str,
    transaction_count: int,
    diagnostic_count: int,
) -> None:
    inputs = _workflow_inputs(kind)
    sections = compile_workflow_business_plan_sections(**inputs)
    payload = sections.writer_kwargs()
    parsed = parse_workflow_business_plan_sections(payload)
    validated = validate_workflow_business_plan_sections(parsed, **inputs)

    assert validated.writer_kwargs() == payload
    assert (
        sections.static_expectation["family_schema_version"]
        == WORKFLOW_BUSINESS_PLAN_SCHEMA
    )
    assert len(sections.static_expectation["transactions"]) == transaction_count
    assert (
        len(sections.static_expectation["diagnostic_evidence"])
        == diagnostic_count
    )
    assert len(sections.payload_bindings["primary_steps"]) == transaction_count
    assert {
        *sections.payload_bindings["primary_steps"],
        *sections.payload_bindings["verification_steps"],
    } == {
        row["name"] for row in sections.static_expectation["workflow_steps"]
    }


def test_workflow_sections_are_deeply_immutable() -> None:
    sections = compile_workflow_business_plan_sections(
        **_workflow_inputs("diagnosis_and_repair")
    )

    with pytest.raises(TypeError):
        sections.static_expectation["workflow_id"] = "other"  # type: ignore[index]
    with pytest.raises(TypeError):
        sections.static_expectation["transactions"][0]["api"] = "other"  # type: ignore[index]
    assert isinstance(sections.static_expectation, MappingProxyType)
    assert isinstance(sections.static_expectation["transactions"], tuple)


@pytest.mark.parametrize(
    ("transaction_index", "construction"),
    [
        (
            1,
            [
                "bind-target-01-01",
                "discover-field-01",
                "declare-existing-01",
            ],
        ),
        (
            2,
            [
                "bind-owner",
                "discover-property",
                "bind-control-input",
                "declare-rtpc",
            ],
        ),
    ],
)
def test_business_object_transactions_are_complete_workflow_transactions(
    transaction_index: int,
    construction: list[str],
) -> None:
    inputs = _workflow_inputs("three_transactions")
    transaction = inputs["transactions"][transaction_index]
    steps = inputs["workflow_steps"]
    transaction_id = transaction["transaction_id"]
    first = next(
        index
        for index, row in enumerate(steps)
        if row["transaction_id"] == transaction_id
    )
    last = max(
        index
        for index, row in enumerate(steps)
        if row["transaction_id"] == transaction_id
    )
    steps[first : last + 1] = _business_transaction_steps(
        transaction,
        construction,
    )

    sections = compile_workflow_business_plan_sections(**inputs)

    assert sections.static_expectation["transactions"][transaction_index][
        "transaction_id"
    ] == transaction_id


def _archive_test_object_set_composer_is_one_complete_ordered_transaction() -> None:
    inputs = _workflow_inputs("three_transactions")
    transaction = inputs["transactions"][1]
    steps = inputs["workflow_steps"]
    first = next(
        index
        for index, row in enumerate(steps)
        if row["transaction_id"] == "tx02"
    )
    last = max(
        index
        for index, row in enumerate(steps)
        if row["transaction_id"] == "tx02"
    )
    steps[first : last + 1] = _composer_transaction_steps(transaction)

    sections = compile_workflow_business_plan_sections(**inputs)

    names = [
        row["name"]
        for row in sections.static_expectation["workflow_steps"]
        if row["transaction_id"] == "tx02"
    ]
    assert names == [
        "tx02.operation-schema",
        "tx02.draft-start",
        "tx02.action.001",
        "tx02.action.002",
        "tx02.check",
        "tx02.preview",
        "tx02.transaction-show",
        "tx02.confirm",
        "tx02.execute",
        "tx02.verify",
    ]


def _archive_test_composer_accepts_independent_facts_before_bound_container_disclosure() -> None:
    inputs = _workflow_inputs("three_transactions")
    transaction = inputs["transactions"][1]
    steps = _composer_transaction_steps(transaction, action_count=4)
    construction = steps[2:6]
    steps[2:6] = [
        construction[0],
        construction[2],
        {
            **construction[0],
            "name": "tx02.disclose.001.choices",
        },
        {
            **construction[0],
            "name": "tx02.disclose.001",
        },
        construction[1],
        construction[3],
    ]
    workflow_steps = inputs["workflow_steps"]
    first = next(
        index
        for index, row in enumerate(workflow_steps)
        if row["transaction_id"] == "tx02"
    )
    last = max(
        index
        for index, row in enumerate(workflow_steps)
        if row["transaction_id"] == "tx02"
    )
    workflow_steps[first : last + 1] = steps

    sections = compile_workflow_business_plan_sections(**inputs)

    names = [
        row["name"]
        for row in sections.static_expectation["workflow_steps"]
        if row["transaction_id"] == "tx02"
    ]
    assert names[2:8] == [
        "tx02.action.001",
        "tx02.action.003",
        "tx02.disclose.001.choices",
        "tx02.disclose.001",
        "tx02.action.002",
        "tx02.action.004",
    ]


@pytest.mark.parametrize(
    "attack",
    (
        "action_gap",
        "duplicate_action",
        "reordered_actions",
        "orphan_disclosure",
        "split_choice_disclosure",
        "wrong_kind",
        "wrong_operation",
        "missing_check",
    ),
)
def test_object_set_composer_rejects_incomplete_or_cross_operation_steps(
    attack: str,
) -> None:
    inputs = _workflow_inputs("three_transactions")
    transaction = inputs["transactions"][1]
    steps = _composer_transaction_steps(transaction)
    if attack == "action_gap":
        steps[2]["name"] = "tx02.action.003"
    elif attack == "duplicate_action":
        steps[3]["name"] = "tx02.action.001"
    elif attack == "reordered_actions":
        steps[2], steps[3] = steps[3], steps[2]
    elif attack == "orphan_disclosure":
        steps.insert(
            4,
            {**steps[2], "name": "tx02.disclose.001"},
        )
    elif attack == "split_choice_disclosure":
        steps[2:4] = [
            {**steps[2], "name": "tx02.disclose.001.choices"},
            steps[2],
            {**steps[2], "name": "tx02.disclose.001"},
            steps[3],
        ]
    elif attack == "wrong_kind":
        steps[2]["kind"] = "checkpoint"
    elif attack == "wrong_operation":
        transaction["operation"] = "object.setReference"
    elif attack == "missing_check":
        steps[:] = [row for row in steps if row["name"] != "tx02.check"]
    else:
        raise AssertionError(attack)
    workflow_steps = inputs["workflow_steps"]
    first = next(
        index
        for index, row in enumerate(workflow_steps)
        if row["transaction_id"] == "tx02"
    )
    last = max(
        index
        for index, row in enumerate(workflow_steps)
        if row["transaction_id"] == "tx02"
    )
    workflow_steps[first : last + 1] = steps

    with pytest.raises(
        WorkflowBusinessPlanError,
        match=(
            "workflow step names must be unique"
            if attack == "duplicate_action"
            else "does not contain one complete transaction"
        ),
    ):
        compile_workflow_business_plan_sections(**inputs)


@pytest.mark.parametrize(
    "attack",
    [
        "extra_static_key",
        "transaction_gap",
        "wrong_primary",
        "incomplete_transaction",
        "step_api_drift",
        "duplicate_step",
        "diagnostic_after_transaction",
        "diagnostic_hash",
        "diagnostic_step",
        "extra_binding_key",
        "live_hash",
        "delta_hash",
        "fixture_hash",
    ],
)
def test_parse_rejects_tampered_or_incomplete_workflow(
    attack: str,
) -> None:
    payload = compile_workflow_business_plan_sections(
        **_workflow_inputs("diagnosis_and_repair")
    ).writer_kwargs()
    if attack == "extra_static_key":
        payload["static_expectation"]["extra"] = True
    elif attack == "transaction_gap":
        payload["static_expectation"]["transactions"][0][
            "transaction_id"
        ] = "tx02"
    elif attack == "wrong_primary":
        payload["payload_bindings"]["primary_steps"] = ["tx01.preview"]
    elif attack == "incomplete_transaction":
        del payload["static_expectation"]["workflow_steps"][-1]
        payload["payload_bindings"]["verification_steps"].remove("tx01.verify")
    elif attack == "step_api_drift":
        payload["static_expectation"]["workflow_steps"][-1][
            "api"
        ] = "ak.wwise.core.object.set"
    elif attack == "duplicate_step":
        payload["static_expectation"]["workflow_steps"][1][
            "name"
        ] = "diag.search"
    elif attack == "diagnostic_after_transaction":
        rows = payload["static_expectation"]["workflow_steps"]
        rows.append(rows.pop(0))
        payload["payload_bindings"]["verification_steps"] = [
            row["name"]
            for row in rows
            if row["name"] not in payload["payload_bindings"]["primary_steps"]
        ]
    elif attack == "diagnostic_hash":
        payload["static_expectation"]["diagnostic_evidence"][0][
            "expectation_sha256"
        ] = "0" * 64
    elif attack == "diagnostic_step":
        payload["static_expectation"]["diagnostic_evidence"][0][
            "step"
        ] = "tx01.preview"
    elif attack == "extra_binding_key":
        payload["payload_bindings"]["workflow_steps"] = []
    elif attack == "live_hash":
        payload["live_binding"]["bindings_sha256"] = "0" * 64
    elif attack == "delta_hash":
        payload["delta_rules"][0]["expectation_sha256"] = "0" * 64
    elif attack == "fixture_hash":
        payload["fixture_spec"]["sha256"] = "0" * 64
    else:
        raise AssertionError(attack)

    with pytest.raises(WorkflowBusinessPlanError):
        parse_workflow_business_plan_sections(payload)


def test_compile_rejects_non_json_and_open_rows() -> None:
    inputs = _workflow_inputs("three_transactions")
    inputs["live_bindings"] = {"bad": float("nan")}
    with pytest.raises(WorkflowBusinessPlanError, match="non-finite"):
        compile_workflow_business_plan_sections(**inputs)

    inputs = _workflow_inputs("three_transactions")
    inputs["transactions"][0]["extra"] = True
    with pytest.raises(WorkflowBusinessPlanError, match="not closed"):
        compile_workflow_business_plan_sections(**inputs)


def test_validate_rejects_independent_workflow_oracle_drift() -> None:
    inputs = _workflow_inputs("two_transactions")
    sections = compile_workflow_business_plan_sections(**inputs)

    changed = copy.deepcopy(inputs)
    changed["transaction_expectations"][1]["expectation"]["preserved"] = []
    with pytest.raises(
        WorkflowBusinessPlanError,
        match="independently recomputed",
    ):
        validate_workflow_business_plan_sections(sections, **changed)
