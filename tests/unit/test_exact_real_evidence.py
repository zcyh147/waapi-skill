from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from tests.destructive.support import exact_real_evidence


class _Lock:
    def __init__(self) -> None:
        self.released = False

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.released = True


def _request(module_file: Path, *, call: str = "passed") -> SimpleNamespace:
    item = SimpleNamespace(
        path=module_file,
        nodeid="tests/example.py::test_case",
        _waapi_phase_reports={"setup": "passed", "call": call},
    )
    return SimpleNamespace(session=SimpleNamespace(items=[item]))


def _sandbox(quarantine: Path) -> SimpleNamespace:
    return SimpleNamespace(
        sandbox_path=quarantine,
        metadata=SimpleNamespace(
            process_cleanup_result="cleaned",
            process_cleanup_details={"residual_processes": []},
        ),
    )


def _finalize(
    tmp_path: Path,
    monkeypatch,
    *,
    append,
) -> tuple[BaseException | None, Path, _Lock]:
    module_file = tmp_path / "example.py"
    module_file.write_text("", encoding="utf-8")
    quarantine = tmp_path / "quarantine"
    quarantine.mkdir()
    lock = _Lock()
    monkeypatch.setattr(exact_real_evidence, "exact_transaction_outcomes", lambda _path: [])
    monkeypatch.setattr(
        exact_real_evidence,
        "cleanup_sandbox",
        lambda sandbox, **_kwargs: sandbox.sandbox_path,
    )
    monkeypatch.setattr(exact_real_evidence, "append_category_evidence", append)
    error = exact_real_evidence.finalize_exact_real_evidence(
        repo_root=tmp_path,
        candidate="a" * 40,
        version="2025.1",
        request=_request(module_file),
        module_file=module_file,
        started_at_unix_ns=1,
        active_error=None,
        deferred_error=None,
        sandbox=_sandbox(quarantine),
        lock=lock,
        state_dir=tmp_path / "state",
        host={"display_name": "WwiseConsole"},
        categories=[
            {
                "category": "object-topology",
                "status": "PASS",
                "verifier_strength": "readback",
            }
        ],
        source={"hash_before": "same", "hash_after": "same"},
    )
    return error, quarantine, lock


def test_pass_is_prepared_before_cleanup_and_finalized_after_release(
    tmp_path: Path,
    monkeypatch,
) -> None:
    records: list[dict] = []

    error, quarantine, lock = _finalize(
        tmp_path,
        monkeypatch,
        append=lambda **payload: records.append(payload),
    )

    assert error is None
    assert lock.released is True
    assert not quarantine.exists()
    assert [row["invocation"]["phase"] for row in records] == ["prepared", "final"]
    assert [row["invocation"]["outcome"] for row in records] == ["PENDING", "PASS"]
    assert [row["residual_state"]["sandbox"] for row in records] == [
        "quarantined_pending_release",
        "deleted",
    ]


def test_prepared_evidence_failure_leaves_quarantine_and_no_false_pass(
    tmp_path: Path,
    monkeypatch,
) -> None:
    records: list[dict] = []

    def fail_append(**payload) -> None:
        records.append(payload)
        raise OSError("evidence unavailable")

    error, quarantine, lock = _finalize(
        tmp_path,
        monkeypatch,
        append=fail_append,
    )

    assert isinstance(error, OSError)
    assert lock.released is True
    assert quarantine.is_dir()
    assert len(records) == 1
    assert records[0]["invocation"]["outcome"] == "PENDING"


def test_quarantine_failure_reports_retained_state_not_false_quarantine(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module_file = tmp_path / "example.py"
    module_file.write_text("", encoding="utf-8")
    retained = tmp_path / "retained"
    retained.mkdir()
    lock = _Lock()
    records: list[dict] = []
    monkeypatch.setattr(exact_real_evidence, "exact_transaction_outcomes", lambda _path: [])
    monkeypatch.setattr(
        exact_real_evidence,
        "cleanup_sandbox",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("move failed")),
    )
    monkeypatch.setattr(
        exact_real_evidence,
        "append_category_evidence",
        lambda **payload: records.append(payload),
    )

    error = exact_real_evidence.finalize_exact_real_evidence(
        repo_root=tmp_path,
        candidate="a" * 40,
        version="2025.1",
        request=_request(module_file),
        module_file=module_file,
        started_at_unix_ns=1,
        active_error=None,
        deferred_error=None,
        sandbox=_sandbox(retained),
        lock=lock,
        state_dir=tmp_path / "state",
        host={"display_name": "WwiseConsole"},
        categories=[
            {
                "category": "object-topology",
                "status": "PASS",
                "verifier_strength": "readback",
            }
        ],
        source={},
    )

    assert isinstance(error, OSError)
    assert retained.is_dir()
    assert len(records) == 1
    assert records[0]["invocation"]["outcome"] == "FAIL"
    assert records[0]["residual_state"]["sandbox"] == "retained"
    assert records[0]["residual_state"]["quarantine_path"] is None


def test_node_outcomes_preserve_skip_and_blocked_states(tmp_path: Path) -> None:
    module_file = tmp_path / "example.py"
    module_file.write_text("", encoding="utf-8")
    skipped = _request(module_file, call="skipped")
    blocked = _request(module_file, call="missing")

    skipped_rows = exact_real_evidence._selected_node_outcomes(  # noqa: SLF001
        skipped,
        module_file,
        active_error=None,
    )
    blocked_rows = exact_real_evidence._selected_node_outcomes(  # noqa: SLF001
        blocked,
        module_file,
        active_error=None,
    )

    assert skipped_rows == [
        {"nodeid": "tests/example.py::test_case", "outcome": "SKIP"}
    ]
    assert blocked_rows == [
        {"nodeid": "tests/example.py::test_case", "outcome": "BLOCKED"}
    ]
