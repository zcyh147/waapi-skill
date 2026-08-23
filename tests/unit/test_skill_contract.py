from __future__ import annotations

from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[2] / "skills" / "waapi-skill"


def doc_text(*relative_paths: str) -> str:
    return "\n".join((SKILL_ROOT / path).read_text(encoding="utf-8") for path in relative_paths)


def test_skill_contract_documents_fixed_runner_and_versioned_runtime() -> None:
    text = doc_text("SKILL.md")

    for command in (
        "python scripts/run.py gateway.py status",
        "python scripts/run.py gateway.py buses",
        "python scripts/run.py gateway.py selected",
        "python scripts/run.py gateway.py query-object --type Event --take 100",
        "python scripts/run.py gateway.py metadata types --summary-only",
    ):
        assert command in text
    for resource in (
        "resources/manifest/<version>/",
        "resources/semantic/<version>/",
        "resources/waql/<version>/",
        "resources/deferred/<version>.json",
    ):
        assert resource in text


def test_skill_contract_documents_gateway_inputs_outputs_and_failure_boundary() -> None:
    text = doc_text("SKILL.md", "references/waapi-query.md")

    for required in ("<uri>", "request-schema", "typed-call", "--timeout", "--apply", "read_only"):
        assert required in text
    for required in ("API_NOT_FOUND", "MANIFEST_NOT_FOUND", "TRANSACTION_REQUIRED", "unsupported_by_skill_interface"):
        assert required in text
    assert "There is no raw-client fallback" in text


def test_skill_contract_prefers_fixed_live_query_before_discovery() -> None:
    text = doc_text("SKILL.md")

    assert "run the matching gateway command immediately" in text
    assert "before `ls`, `find`, `rg`" in text
    assert "Do not scan unrelated ports or processes" in text
    assert "Do not search the repository to recover from a gateway error" in text


def test_skill_contract_keeps_windows_reference_reads_on_the_short_task_locator() -> None:
    text = doc_text("SKILL.md")

    assert (
        "Native Windows always copies the short task-local form "
        "`Get-Content -Raw -Encoding UTF8 "
        "'.agents\\skills\\waapi-skill\\references\\<file>.md'` exactly"
    ) in text
    assert "reconstructing a scenario-root absolute path" in text


def test_skill_contract_requires_confirmation_before_retargeting_invalid_parent() -> None:
    text = doc_text("references/waapi-operate.md")

    assert "not a valid direct writable parent" in text
    assert "do not silently retarget the mutation" in text
    assert "ask the user to confirm the intended writable child container" in text


def test_operate_contract_preserves_posix_wwise_path_backslashes() -> None:
    text = doc_text("references/waapi-operate.md")

    assert "On POSIX, single-quote every Wwise path value" in text
    assert "so backslashes survive" in text
