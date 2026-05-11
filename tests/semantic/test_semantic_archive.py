from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest  # pyright: ignore[reportMissingImports]

from tests.semantic.support.archive import (
    ALLOWED_VERDICTS,
    DEFAULT_ARCHIVE_ROOT,
    EXCLUDED_ARTIFACT_CLASSES,
    SemanticArchiveError,
    write_semantic_archive_record,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
REQUIRED_RECORD_FIELDS = {
    "archive_path",
    "archive_policy",
    "assistant_output",
    "bug_classes",
    "command_line",
    "dispatcher_evidence_paths",
    "evidence_references",
    "expected_assertions",
    "failure_notes",
    "opencode_session_id",
    "planner_facts",
    "prompt",
    "run_id",
    "sandbox_metadata_path",
    "scenario_id",
    "schema_version",
    "timestamps",
    "verdict",
    "waapi_host",
    "waapi_port",
    "wwise_version",
}


def test_task_9_archive_schema_records_all_verdicts(tmp_path: Path) -> None:
    for verdict in sorted(ALLOWED_VERDICTS):
        scenario_id = f"semantic-{verdict}"
        record_path = write_semantic_archive_record(
            archive_root=tmp_path,
            scenario_id=scenario_id,
            prompt="List all selected Actor-Mixer objects.",
            expected_assertions=["uses WAAPI before source research", "reports object names"],
            assistant_output=f"assistant transcript for {verdict}",
            verdict=verdict,
            bug_classes=["routing", "assertion-mismatch"] if verdict == "fail" else [],
            wwise_version="2024.1",
            waapi_host="127.0.0.1",
            waapi_port=8080,
            opencode_session_id="ses_task9_schema",
            sandbox_metadata_path="tests/_sandboxes/sample/sandbox-metadata.json",
            dispatcher_evidence_paths=[".sisyphus/evidence/dispatcher/object-get.json"],
            evidence_references=[".sisyphus/evidence/waapi-live/object-get.json"],
            command_line=["opencode", "run", "--attach", "ses_task9_schema"],
            timestamps={
                "started_at": "2026-05-11T00:00:00Z",
                "completed_at": "2026-05-11T00:00:01Z",
                "archived_at": "2026-05-11T00:00:02Z",
            },
            failure_notes=["expected names missing"] if verdict == "fail" else [],
            run_id="task-9-run",
        )

        payload = _read_json(record_path)
        assert REQUIRED_RECORD_FIELDS <= payload.keys()
        assert payload["scenario_id"] == scenario_id
        assert payload["prompt"] == "List all selected Actor-Mixer objects."
        assert payload["expected_assertions"] == ["uses WAAPI before source research", "reports object names"]
        assert payload["assistant_output"] == f"assistant transcript for {verdict}"
        assert payload["verdict"] == verdict
        assert payload["wwise_version"] == "2024.1"
        assert payload["waapi_host"] == "127.0.0.1"
        assert payload["waapi_port"] == 8080
        assert payload["opencode_session_id"] == "ses_task9_schema"
        assert payload["sandbox_metadata_path"].endswith("sandbox-metadata.json")
        assert payload["dispatcher_evidence_paths"] == [".sisyphus/evidence/dispatcher/object-get.json"]
        assert payload["evidence_references"] == [".sisyphus/evidence/waapi-live/object-get.json"]
        assert payload["command_line"] == ["opencode", "run", "--attach", "ses_task9_schema"]
        assert payload["timestamps"] == {
            "started_at": "2026-05-11T00:00:00Z",
            "completed_at": "2026-05-11T00:00:01Z",
            "archived_at": "2026-05-11T00:00:02Z",
        }
        assert set(EXCLUDED_ARTIFACT_CLASSES) <= set(payload["archive_policy"]["excluded_artifact_classes"])
        assert payload["archive_policy"]["copies_artifacts"] is False
        assert payload["archive_policy"]["references_only"] is True
        assert record_path == tmp_path / "task-9-run" / scenario_id / "record.json"


def test_semantic_archive_rejects_unknown_verdict(tmp_path: Path) -> None:
    with pytest.raises(SemanticArchiveError, match="verdict must be one of"):
        write_semantic_archive_record(
            archive_root=tmp_path,
            scenario_id="bad-verdict",
            prompt="prompt",
            expected_assertions=[],
            assistant_output="output",
            verdict="unknown",
            wwise_version="2024.1",
            waapi_host="127.0.0.1",
            waapi_port=8080,
            opencode_session_id="ses_bad",
            sandbox_metadata_path=None,
        )


def test_task_9_archive_excludes_copied_artifacts_and_keeps_archives_local(tmp_path: Path) -> None:
    sandbox = tmp_path / "sample-project-sandbox"
    metadata_path = sandbox / "sandbox-metadata.json"
    _write_fake_excluded_artifacts(sandbox, metadata_path)

    record_path = write_semantic_archive_record(
        archive_root=tmp_path / "archive",
        scenario_id="semantic-excludes",
        prompt="Read a work unit.",
        expected_assertions=["references sandbox metadata only"],
        assistant_output="assistant transcript",
        verdict="blocked",
        bug_classes=["environment"],
        wwise_version="2025.1",
        waapi_host="localhost",
        waapi_port=8090,
        opencode_session_id="ses_task9_excludes",
        sandbox_metadata_path=metadata_path,
        dispatcher_evidence_paths=[tmp_path / "dispatcher-evidence.json"],
        evidence_references=[".sisyphus/evidence/waapi-dispatcher/existing.json"],
        command_line=["opencode", "run", "semantic batch"],
        timestamps={"started_at": None, "completed_at": None, "archived_at": "2026-05-11T00:00:02Z"},
        failure_notes=["Wwise was unavailable"],
        run_id="task-9-excludes",
    )

    payload = _read_json(record_path)
    assert payload["sandbox_metadata_path"] == str(metadata_path)
    assert payload["dispatcher_evidence_paths"] == [str(tmp_path / "dispatcher-evidence.json")]
    assert payload["archive_policy"]["copies_artifacts"] is False
    assert payload["archive_policy"]["references_only"] is True

    run_root = record_path.parents[1]
    archived_entries = [path.relative_to(run_root) for path in run_root.rglob("*")]
    assert archived_entries == [Path("semantic-excludes"), Path("semantic-excludes/record.json")]
    assert not any(path.name in {".venv", "__pycache__", ".cache", "logs"} for path in run_root.rglob("*"))
    assert not any(path.suffix in {".db", ".sqlite", ".log"} for path in run_root.rglob("*") if path.is_file())

    default_record = write_semantic_archive_record(
        scenario_id="semantic-gitignore-safety",
        prompt="Safety check.",
        expected_assertions=["archive remains local"],
        assistant_output="assistant transcript",
        verdict="pass",
        wwise_version="2024.1",
        waapi_host="127.0.0.1",
        waapi_port=8080,
        opencode_session_id="pytest-default",
        sandbox_metadata_path="tests/_sandboxes/sample/sandbox-metadata.json",
        run_id="pytest-default",
    )
    relative_default_record = default_record.relative_to(REPO_ROOT)
    assert relative_default_record.parts[:2] == (".sisyphus", "evidence")
    assert DEFAULT_ARCHIVE_ROOT.parts[:2] == (".sisyphus", "evidence")
    assert ".sisyphus/" in (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    _assert_git_ignores_default_archive(relative_default_record)


def test_semantic_capability_archive_carries_planner_facts(tmp_path: Path) -> None:
    record_path = write_semantic_archive_record(
        archive_root=tmp_path,
        scenario_id="semantic-capability-crud-preview",
        prompt="Prepare a preview to create a small SFX container.",
        expected_assertions=["planner facts are archived"],
        assistant_output="SEMANTIC_RESULT_JSON: {}",
        verdict="pass",
        wwise_version="2022.1",
        waapi_host="127.0.0.1",
        waapi_port=8080,
        opencode_session_id="ses_capability_planner_facts",
        sandbox_metadata_path="tests/_sandboxes/sample/sandbox-metadata.json",
        planner_facts={
            "support_status": "supported",
            "plan_family": "crud_authoring",
            "preview_hash": "sha256:semantic-preview",
            "builder_refs": ["wwise_waapi.builders.object_mutation"],
            "unsupported_boundary_reason": "",
            "verification_status": "preview_only",
        },
        run_id="task-9-capability-planner-facts",
    )

    payload = _read_json(record_path)
    assert payload["planner_facts"] == {
        "support_status": "supported",
        "plan_family": "crud_authoring",
        "preview_hash": "sha256:semantic-preview",
        "builder_refs": ["wwise_waapi.builders.object_mutation"],
        "unsupported_boundary_reason": "",
        "verification_status": "preview_only",
    }


def _write_fake_excluded_artifacts(sandbox: Path, metadata_path: Path) -> None:
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(json.dumps({"metadata_path": str(metadata_path)}) + "\n", encoding="utf-8")
    for directory in (sandbox / ".venv", sandbox / "__pycache__", sandbox / ".cache", sandbox / "logs"):
        directory.mkdir(parents=True, exist_ok=True)
    for path in (
        sandbox / "SampleProject.wproj",
        sandbox / ".venv" / "python",
        sandbox / "__pycache__" / "archive.pyc",
        sandbox / ".cache" / "waapi.cache",
        sandbox / "opencode.db",
        sandbox / "session.sqlite",
        sandbox / "logs" / "opencode.log",
    ):
        path.write_text("not archived\n", encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _assert_git_ignores_default_archive(relative_path: Path) -> None:
    if not (REPO_ROOT / ".git").exists():
        pytest.skip("git metadata is unavailable for status-style archive ignore assertion")
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", relative_path.as_posix()],
        cwd=REPO_ROOT,
        check=False,
    )
    assert ignored.returncode == 0
    status = subprocess.run(
        ["git", "status", "--porcelain", "--", relative_path.as_posix()],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert status.stdout == ""
