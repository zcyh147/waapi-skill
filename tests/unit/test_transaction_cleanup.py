from __future__ import annotations

import json
from copy import deepcopy

import pytest

from wwise_waapi.transaction_cleanup import (
    CLEANUP_PROJECTION_CONTRACT,
    CLEANUP_SPEC_CONTRACT,
    TransactionCleanupError,
    build_transaction_cleanup_spec,
    project_transaction_cleanup,
)


OPENERS = (
    (
        "ak.soundengine.loadBank",
        {"soundBank": {"name": "Main"}},
        "ak.soundengine.unloadBank",
        {"soundBank": {"name": "Main"}},
    ),
    (
        "ak.soundengine.registerGameObj",
        {"gameObject": 42, "name": "Preview"},
        "ak.soundengine.unregisterGameObj",
        {"gameObject": 42},
    ),
    (
        "ak.wwise.core.profiler.registerMeter",
        {"object": r"\Master-Mixer Hierarchy\Default Work Unit\Master Audio Bus"},
        "ak.wwise.core.profiler.unregisterMeter",
        {"object": r"\Master-Mixer Hierarchy\Default Work Unit\Master Audio Bus"},
    ),
    (
        "ak.wwise.core.profiler.startCapture",
        {},
        "ak.wwise.core.profiler.stopCapture",
        {},
    ),
    (
        "ak.wwise.core.remote.connect",
        {"host": "127.0.0.1"},
        "ak.wwise.core.remote.disconnect",
        {},
    ),
    (
        "ak.wwise.core.transport.create",
        {"object": "{11111111-2222-3333-4444-555555555555}"},
        "ak.wwise.core.transport.destroy",
        {},
    ),
    (
        "ak.wwise.core.workUnit.load",
        {"object": {"path": r"\Actor-Mixer Hierarchy\Optional"}},
        "ak.wwise.core.workUnit.unload",
        {"object": {"path": r"\Actor-Mixer Hierarchy\Optional"}},
    ),
)


def _contract(api: str, *companions: str) -> dict[str, object]:
    return {
        "contract": "waapi-skill.public-execution-contract/v1",
        "uri": api,
        "route": "managed_transaction",
        "companion_uris": list(companions),
    }


@pytest.mark.parametrize(("api", "args", "companion", "companion_args"), OPENERS)
def test_all_reviewed_openers_build_sealed_strict_json_specs(
    api: str,
    args: dict[str, object],
    companion: str,
    companion_args: dict[str, object],
) -> None:
    spec = build_transaction_cleanup_spec(api, args, _contract(api, companion))

    assert spec["contract"] == CLEANUP_SPEC_CONTRACT
    assert spec["api"] == api
    assert spec["lifecycle_action"] == "opener"
    assert spec["companion_request"] == {
        "api": companion,
        "args": companion_args,
        "options": {},
    }
    assert len(spec["spec_sha256"]) == 64
    assert json.loads(json.dumps(spec, allow_nan=False)) == spec


def test_request_bindings_are_deep_copied_and_execution_results_cannot_override_them() -> None:
    args = {"soundBank": {"name": "Main", "ids": [1, 2]}}
    spec = build_transaction_cleanup_spec(
        "ak.soundengine.loadBank",
        args,
        _contract("ak.soundengine.loadBank", "ak.soundengine.unloadBank"),
    )
    args["soundBank"]["name"] = "Changed"  # type: ignore[index]
    args["soundBank"]["ids"].append(3)  # type: ignore[index, union-attr]

    projection = project_transaction_cleanup(
        spec,
        phase="executed",
        execution_result={
            "result": {
                "soundBank": {"name": "Injected"},
                "transport": 99,
            }
        },
    )

    assert projection["companion_request"]["args"] == {  # type: ignore[index]
        "soundBank": {"name": "Main", "ids": [1, 2]}
    }
    projection["companion_request"]["args"]["soundBank"]["name"] = "Projection mutation"  # type: ignore[index]
    assert spec["companion_request"]["args"]["soundBank"]["name"] == "Main"  # type: ignore[index]


@pytest.mark.parametrize(
    ("phase", "expected_status"),
    (
        ("preview", "not_started"),
        ("executed", "pending"),
        ("verified", "pending"),
        ("indeterminate", "unknown"),
    ),
)
def test_opener_phase_projection_is_explicit(phase: str, expected_status: str) -> None:
    spec = build_transaction_cleanup_spec(
        "ak.wwise.core.profiler.startCapture",
        {},
        _contract(
            "ak.wwise.core.profiler.startCapture",
            "ak.wwise.core.profiler.stopCapture",
        ),
    )

    projection = project_transaction_cleanup(spec, phase=phase)

    assert projection["contract"] == CLEANUP_PROJECTION_CONTRACT
    assert projection["cleanup_spec_sha256"] == spec["spec_sha256"]
    assert projection["phase"] == phase
    assert projection["status"] == expected_status
    assert projection["automatic_cleanup"] is False
    assert projection["automatic_retry"] is False


def test_transport_binding_materializes_only_from_a_valid_execution_result() -> None:
    spec = build_transaction_cleanup_spec(
        "ak.wwise.core.transport.create",
        {"object": "{11111111-2222-3333-4444-555555555555}"},
        _contract(
            "ak.wwise.core.transport.create",
            "ak.wwise.core.transport.destroy",
        ),
    )

    preview = project_transaction_cleanup(
        spec,
        phase="preview",
        execution_result={"result": {"transport": 12}},
    )
    unresolved = project_transaction_cleanup(spec, phase="executed")
    materialized = project_transaction_cleanup(
        spec,
        phase="verified",
        execution_result={"result": {"transport": 12}},
    )

    assert preview["binding"]["materialized"] is False  # type: ignore[index]
    assert preview["companion_request"]["args"] == {}  # type: ignore[index]
    assert unresolved["status"] == "pending"
    assert unresolved["binding"]["materialized"] is False  # type: ignore[index]
    assert materialized["binding"]["materialized"] is True  # type: ignore[index]
    assert materialized["companion_request"]["args"] == {"transport": 12}  # type: ignore[index]


@pytest.mark.parametrize(
    "execution_result",
    (
        {},
        {"result": {}},
        {"result": {"transport": None}},
        {"result": {"transport": True}},
        {"result": {"transport": 0}},
        {"result": {"transport": -1}},
        {"result": {"transport": 1 << 32}},
        {"result": {"transport": 1.0}},
    ),
)
def test_transport_binding_rejects_missing_or_non_uint32_ids(
    execution_result: dict[str, object],
) -> None:
    spec = build_transaction_cleanup_spec(
        "ak.wwise.core.transport.create",
        {"object": "Event:Play"},
        _contract(
            "ak.wwise.core.transport.create",
            "ak.wwise.core.transport.destroy",
        ),
    )

    with pytest.raises(TransactionCleanupError) as caught:
        project_transaction_cleanup(
            spec,
            phase="executed",
            execution_result=execution_result,
        )

    assert caught.value.error_code in {"CLEANUP_BINDING_MISSING", "INVALID_TRANSPORT_ID"}


def test_work_unit_load_exposes_an_available_reversal_not_required_cleanup() -> None:
    spec = build_transaction_cleanup_spec(
        "ak.wwise.core.workUnit.load",
        {"object": "{11111111-2222-3333-4444-555555555555}"},
        _contract("ak.wwise.core.workUnit.load", "ak.wwise.core.workUnit.unload"),
    )
    projection = project_transaction_cleanup(spec, phase="verified")

    assert spec["lifecycle_strategy"] == "reversible_state_change"
    assert spec["cleanup_requirement"] == "available_reversal"
    assert projection["status"] == "available_reversal"
    assert any("Undo history" in warning for warning in projection["warnings"])
    assert any("unsaved modifications" in warning for warning in projection["warnings"])


@pytest.mark.parametrize("closer", sorted(row[2] for row in OPENERS))
def test_closers_are_lifecycle_actions_without_more_cleanup(closer: str) -> None:
    spec = build_transaction_cleanup_spec(closer, {}, _contract(closer))
    projection = project_transaction_cleanup(spec, phase="indeterminate")

    assert spec["lifecycle_action"] == "closer"
    assert spec["cleanup_requirement"] == "not_required"
    assert spec["companion_request"] is None
    assert projection["status"] == "not_required"


def test_ordinary_calls_are_not_misreported_as_lifecycle_work() -> None:
    api = "ak.wwise.core.object.setName"
    spec = build_transaction_cleanup_spec(
        api,
        {"object": "{11111111-2222-3333-4444-555555555555}", "value": "New"},
        _contract(api),
    )

    assert spec["lifecycle_action"] == "none"
    assert spec["lifecycle_strategy"] == "not_required"
    assert project_transaction_cleanup(spec, phase="verified")["status"] == "not_required"


def test_unreviewed_or_mismatched_lifecycle_contracts_fail_closed() -> None:
    with pytest.raises(TransactionCleanupError) as wrong_companion:
        build_transaction_cleanup_spec(
            "ak.soundengine.loadBank",
            {"soundBank": "Main"},
            _contract("ak.soundengine.loadBank", "ak.soundengine.unregisterGameObj"),
        )
    assert wrong_companion.value.error_code == "CLEANUP_CONTRACT_MISMATCH"

    with pytest.raises(TransactionCleanupError) as unreviewed:
        build_transaction_cleanup_spec(
            "ak.example.open",
            {},
            _contract("ak.example.open", "ak.example.close"),
        )
    assert unreviewed.value.error_code == "UNREVIEWED_LIFECYCLE_BINDING"

    with pytest.raises(TransactionCleanupError) as mismatched_uri:
        build_transaction_cleanup_spec(
            "ak.soundengine.loadBank",
            {"soundBank": "Main"},
            _contract("ak.soundengine.registerGameObj", "ak.soundengine.unloadBank"),
        )
    assert mismatched_uri.value.error_code == "CLEANUP_CONTRACT_MISMATCH"


@pytest.mark.parametrize(
    "bad_value",
    (
        {"value": (1, 2)},
        {"value": float("nan")},
        {1: "non-string-key"},
        {"value": b"bytes"},
    ),
)
def test_non_json_inputs_are_rejected(bad_value: dict[object, object]) -> None:
    with pytest.raises(TransactionCleanupError) as caught:
        build_transaction_cleanup_spec(
            "ak.wwise.core.object.setName",
            bad_value,  # type: ignore[arg-type]
            _contract("ak.wwise.core.object.setName"),
        )

    assert caught.value.error_code == "INVALID_CLEANUP_JSON"


def test_projection_detects_any_persisted_spec_change() -> None:
    spec = build_transaction_cleanup_spec(
        "ak.soundengine.registerGameObj",
        {"gameObject": 42, "name": "Preview"},
        _contract(
            "ak.soundengine.registerGameObj",
            "ak.soundengine.unregisterGameObj",
        ),
    )
    tampered = deepcopy(spec)
    tampered["companion_request"]["args"]["gameObject"] = 99  # type: ignore[index]

    with pytest.raises(TransactionCleanupError) as caught:
        project_transaction_cleanup(tampered, phase="executed")

    assert caught.value.error_code == "CLEANUP_SPEC_TAMPERED"


def test_missing_request_binding_and_invalid_phase_are_structured_errors() -> None:
    with pytest.raises(TransactionCleanupError) as missing:
        build_transaction_cleanup_spec(
            "ak.soundengine.registerGameObj",
            {"name": "Missing ID"},
            _contract(
                "ak.soundengine.registerGameObj",
                "ak.soundengine.unregisterGameObj",
            ),
        )
    assert missing.value.error_code == "CLEANUP_BINDING_MISSING"

    spec = build_transaction_cleanup_spec(
        "ak.wwise.core.remote.connect",
        {"host": "127.0.0.1"},
        _contract("ak.wwise.core.remote.connect", "ak.wwise.core.remote.disconnect"),
    )
    with pytest.raises(TransactionCleanupError) as bad_phase:
        project_transaction_cleanup(spec, phase="done")
    assert bad_phase.value.error_code == "INVALID_CLEANUP_PHASE"
