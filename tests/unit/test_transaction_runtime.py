from __future__ import annotations

import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.operation_registry import OPERATION_REQUEST_CONTRACT  # pyright: ignore[reportMissingImports]
from wwise_waapi.transaction_runtime import (  # pyright: ignore[reportMissingImports]
    TRANSACTION_PREVIEW_CONTRACT,
    TransactionGuardError,
    build_project_guard,
    build_runtime_guard,
    build_transaction_artifact,
    canonical_project_path,
    validate_transaction_guards,
)


SKILL_ROOT = Path(__file__).resolve().parents[2] / "skills" / "waapi-skill"
NOW = datetime(2026, 7, 14, 6, 0, tzinfo=timezone.utc)
GUID = "{11111111-1111-1111-1111-111111111111}"


def project_guard(*, project_id: str = "{project}", port: int = 31337) -> dict[str, Any]:
    return build_project_guard(
        endpoint={"host": "127.0.0.1", "port": port, "url": f"ws://127.0.0.1:{port}/waapi"},
        version="2022.1",
        live_info={
            "displayName": "Wwise",
            "isCommandLine": True,
            "version": {"year": 2022, "major": 1, "minor": 19, "build": 8584},
        },
        project={"id": project_id, "name": "SampleProject", "path": "/tmp/SampleProject.wproj"},
    )


def request() -> dict[str, Any]:
    return {
        "contract": OPERATION_REQUEST_CONTRACT,
        "version": "2022.1",
        "operation": "object.setNotes",
        "arguments": {"object": {"kind": "id", "value": GUID}, "value": "after"},
    }


def reader(uri: str, args: Mapping[str, Any], options: Mapping[str, Any]) -> Mapping[str, Any]:
    assert uri == "ak.wwise.core.object.get"
    return {
        "return": [
            {
                "id": GUID,
                "name": "Target",
                "type": "Sound",
                "path": r"\Actor-Mixer Hierarchy\Default Work Unit\Target",
                "parent": {"id": "{parent}"},
                "notes": "before",
            }
        ]
    }


def test_project_guard_fingerprint_binds_endpoint_version_and_project() -> None:
    first = project_guard()
    same = project_guard()
    other_project = project_guard(project_id="{other}")
    other_port = project_guard(port=31338)

    assert first["fingerprint"] == same["fingerprint"]
    assert first["fingerprint"] != other_project["fingerprint"]
    assert first["fingerprint"] != other_port["fingerprint"]


def test_canonical_project_path_uses_source_filesystem_semantics() -> None:
    assert canonical_project_path(r"C:\Projects\SampleProject.wproj") == (
        r"windows:c:\projects\sampleproject.wproj"
    )
    assert canonical_project_path("c:/PROJECTS/SAMPLEPROJECT.WPROJ") == (
        r"windows:c:\projects\sampleproject.wproj"
    )
    assert canonical_project_path("/Projects/SampleProject.wproj") == (
        "posix:/Projects/SampleProject.wproj"
    )
    assert canonical_project_path("/projects/SampleProject.wproj") != (
        canonical_project_path("/Projects/SampleProject.wproj")
    )


@pytest.mark.parametrize(
    "value",
    (
        r"C:\Projects\..\SampleProject.wproj",
        r"C:\Projects\\SampleProject.wproj",
        "/Projects/./SampleProject.wproj",
        "/Projects//SampleProject.wproj",
        " Projects/SampleProject.wproj ",
        "Projects/SampleProject.wproj",
    ),
)
def test_canonical_project_path_rejects_normalizing_or_relative_spelling(
    value: str,
) -> None:
    with pytest.raises(TransactionGuardError, match="strict absolute host path"):
        canonical_project_path(value)


def test_transaction_artifact_binds_closed_preview_runtime_guard_and_expiry() -> None:
    artifact = build_transaction_artifact(
        request(),
        live_version="2022.1",
        read_call=reader,
        project_guard=project_guard(),
        skill_root=SKILL_ROOT,
        now=NOW,
        ttl_seconds=600,
    ).as_dict()

    assert artifact["contract"] == TRANSACTION_PREVIEW_CONTRACT
    assert artifact["prepared_operation"]["dispatch"] == {
        "uri": "ak.wwise.core.object.setNotes",
        "args": {"object": GUID, "value": "after"},
        "options": {},
    }
    assert artifact["runtime_guard"]["version"] == "2022.1"
    assert len(artifact["runtime_guard"]["files"]) >= 18
    assert artifact["execution_policy"]["requires_authorization"] is True
    assert artifact["execution_policy"]["accepted_authorization_modes"] == [
        "explicit_confirmation",
        "policy_authorization",
    ]
    assert (
        artifact["execution_policy"]["authorization_selected_at_preview"]
        is True
    )
    assert artifact["execution_policy"]["automatic_retry_allowed"] is False
    assert artifact["expires_at"] == "2026-07-14T06:10:00.000000Z"


def test_guard_validation_accepts_same_context_and_rejects_expiry_or_project_drift() -> None:
    artifact = build_transaction_artifact(
        request(),
        live_version="2022.1",
        read_call=reader,
        project_guard=project_guard(),
        skill_root=SKILL_ROOT,
        now=NOW,
        ttl_seconds=60,
    ).as_dict()

    valid = validate_transaction_guards(
        artifact,
        current_project_guard=project_guard(),
        skill_root=SKILL_ROOT,
        now=NOW + timedelta(seconds=30),
    )
    assert valid["status"] == "valid"

    with pytest.raises(TransactionGuardError) as expired:
        validate_transaction_guards(
            artifact,
            current_project_guard=project_guard(),
            skill_root=SKILL_ROOT,
            now=NOW + timedelta(seconds=61),
        )
    assert expired.value.error_code == "PREVIEW_EXPIRED"

    post_execution = validate_transaction_guards(
        artifact,
        current_project_guard=project_guard(),
        skill_root=SKILL_ROOT,
        now=NOW + timedelta(seconds=61),
        check_expiry=False,
    )
    assert post_execution["status"] == "valid"

    with pytest.raises(TransactionGuardError) as drifted:
        validate_transaction_guards(
            artifact,
            current_project_guard=project_guard(project_id="{other}"),
            skill_root=SKILL_ROOT,
            now=NOW + timedelta(seconds=30),
        )
    assert drifted.value.error_code == "PROJECT_GUARD_MISMATCH"


def test_runtime_guard_detects_any_packaged_builder_change(tmp_path: Path) -> None:
    copied_skill = tmp_path / "waapi-skill"
    shutil.copytree(SKILL_ROOT, copied_skill)
    guard = build_runtime_guard(copied_skill, "2022.1")
    artifact = {
        "contract": TRANSACTION_PREVIEW_CONTRACT,
        "request": {"version": "2022.1"},
        "project_guard": project_guard(),
        "runtime_guard": guard,
        "expires_at": "2026-07-14T07:00:00.000000Z",
    }
    operation_registry = copied_skill / "wwise_waapi" / "operation_registry.py"
    operation_registry.write_text(operation_registry.read_text(encoding="utf-8") + "\n# drift\n", encoding="utf-8")

    with pytest.raises(TransactionGuardError) as drifted:
        validate_transaction_guards(
            artifact,
            current_project_guard=project_guard(),
            skill_root=copied_skill,
            now=NOW,
        )
    assert drifted.value.error_code == "RUNTIME_GUARD_MISMATCH"


@pytest.mark.parametrize(
    "relative_path",
    (
        "wwise_waapi/operation_import.py",
        "wwise_waapi/builders/soundbank.py",
        "wwise_waapi/builders/switchcontainer.py",
        "wwise_waapi/builders/container_suitability.py",
    ),
)
def test_runtime_guard_covers_every_closed_workflow_builder(
    tmp_path: Path,
    relative_path: str,
) -> None:
    copied_skill = tmp_path / "waapi-skill"
    shutil.copytree(SKILL_ROOT, copied_skill)
    guard = build_runtime_guard(copied_skill, "2022.1")
    target = copied_skill / relative_path
    target.write_text(target.read_text(encoding="utf-8") + "\n# workflow drift\n", encoding="utf-8")
    artifact = {
        "contract": TRANSACTION_PREVIEW_CONTRACT,
        "request": {"version": "2022.1"},
        "project_guard": project_guard(),
        "runtime_guard": guard,
        "expires_at": "2026-07-14T07:00:00.000000Z",
    }

    with pytest.raises(TransactionGuardError) as drifted:
        validate_transaction_guards(
            artifact,
            current_project_guard=project_guard(),
            skill_root=copied_skill,
            now=NOW,
        )
    assert drifted.value.error_code == "RUNTIME_GUARD_MISMATCH"


def test_runtime_guard_is_deterministic_and_lists_relative_paths_only() -> None:
    first = build_runtime_guard(SKILL_ROOT, "2025.1")
    second = build_runtime_guard(SKILL_ROOT, "2025.1")

    assert first == second
    assert all(not Path(path).is_absolute() for path in first["files"])
    assert first["fingerprint"] == second["fingerprint"]
