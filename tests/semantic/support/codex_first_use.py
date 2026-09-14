"""Two offline first-use tasks in the existing matrix/Harness/Broker lane.

Prompts contain no welcome hint. This narrow profile never prepares a Wwise
fixture, and its Broker authorizes only one production config-show per task.
"""

from __future__ import annotations

import hashlib
import re
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

from tests.semantic.support.codex_gateway_broker import CodexGatewayBroker, ExpectedGatewayStep
from tests.semantic.support.codex_harness import (
    CodexCliTask,
    CodexHarnessConfig,
    first_gateway_backed_agent_message,
    parse_jsonl_events,
)


CASE_IDS = ("bare-slash", "bare-link")
FOLLOWUP = "先不操作，等我下一条消息。"


def initial_prompt(case_id: str, installed_skill: Path) -> str:
    if case_id == "bare-slash":
        return "/waapi-skill"
    if case_id == "bare-link":
        destination = str(installed_skill / "SKILL.md")
        if re.search(r"[\s()]", destination):
            destination = f"<{destination}>"
        return f"[$waapi-skill]({destination})"
    raise ValueError(f"unknown first-use case: {case_id}")


def introduction_checks(text: str, facts: Mapping[str, Any]) -> dict[str, bool]:
    """Check facts, not a prescribed sentence or presentation order."""
    folded = text.casefold()
    product = re.sub(r"[\s_-]+", "", folded)
    try:
        port = urlsplit(str(facts.get("endpoint_url") or "")).port
    except ValueError:
        port = None
    return {
        "skill_named": "waapiskill" in product,
        "endpoint": port is not None and bool(re.search(rf"(?<!\d){port}(?!\d)", text)),
        "adapter_version": bool(facts.get("adapter_version")) and str(facts["adapter_version"]) in text,
        "policy": bool(facts.get("project_modification_policy")) and str(facts["project_modification_policy"]) in text,
        "all_modes": all(mode in text for mode in ("read_only", "ask_before_changes", "allow_changes")),
        "offline_wording": not bool(re.search(r"当前连接的|已(?:成功)?连接|(?<!not )\bconnected to\b", folded)),
    }


def agent_messages(stdout: str) -> str:
    return "\n".join(
        str(event["item"].get("text", ""))
        for event in parse_jsonl_events(stdout)
        if event.get("type") == "item.completed"
        and isinstance(event.get("item"), dict)
        and event["item"].get("type") == "agent_message"
    )


def common_checks(result: Any) -> dict[str, bool]:
    facts = result.command_facts
    return {
        "completed": result.exit_status == 0 and not result.timed_out and result.session_audit.passed,
        "memory_off": result.prompt_audit.passed and result.isolation_audit.passed,
        "unchanged": result.skill_tree_unchanged and not any((
            result.created_files, result.modified_files, result.deleted_files,
            result.created_source_files, result.modified_source_files, result.deleted_source_files,
        )),
        "no_bypass": not any((facts.unexpected_commands, facts.discovery_commands,
            facts.inline_python_commands, facts.direct_waapi_client_commands, facts.write_like_commands)),
        "reply": bool(result.final_response.strip()),
    }


def save_turn(directory: Path, result: Any) -> None:
    """CodexCliTask returns evidence in memory; the matrix owns persistence."""
    from tests.semantic import run_codex_skill_matrix as matrix

    matrix.write_text(directory / "events.jsonl", result.stdout)
    matrix.write_text(directory / "stderr.txt", result.stderr)
    matrix.write_text(directory / "final-response.txt", result.final_response)
    matrix.write_json(directory / "codex-result.json", result.facts_dict())


def run_first_use_matrix(options: Any) -> int:
    # Reuse matrix installation, environment sanitization, argv extraction and
    # evidence serialization; no alternate agent runtime or direct WAAPI client.
    from tests.semantic import run_codex_skill_matrix as matrix
    from tests.semantic.run_codex_skill_campaign import require_skill_local_campaign_interpreter

    require_skill_local_campaign_interpreter(options.skill_source)
    root = options.iteration_root
    matrix.prepare_iteration_root(root, overwrite=False)
    matrix.write_json(root / "run-config.json", {
        "profile": "first_use_2", "memory": "disabled", "offline_only": True,
        "wwise_started": False, "model": options.model,
        "reasoning_effort": options.reasoning_effort, "service_tier": options.service_tier,
        "codex_binary": str(options.codex_binary), "skill_source": str(options.skill_source),
        "codex_sha256": hashlib.sha256(options.codex_binary.read_bytes()).hexdigest(),
        "python": sys.executable,
        "python_sha256": hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest(),
        "profile_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "expected_tasks": 2, "expected_turns": 4,
    })
    outcomes = []
    for case_id in CASE_IDS:
        case_root = root / case_id
        workspace = case_root / "agent-workspace"
        installed = matrix.prepare_agent_workspace(workspace, options.skill_source)
        prompt = initial_prompt(case_id, installed)
        policy = "ask_before_changes" if case_id == "bare-slash" else "allow_changes"
        matrix.write_json(case_root / "prompts.json", {"turns": [prompt, FOLLOWUP]})
        outcome: dict[str, Any] = {"case_id": case_id, "status": "BLOCKED"}
        turn_directory = case_root / "turn-1"
        try:
            with CodexGatewayBroker(
                skill_source=options.skill_source, invocation_skill_source=installed,
                expected_steps=(ExpectedGatewayStep("config-show", "config-show"),),
                expected_wwise_version="2024.1", project_modification_policy=policy,
                runner_environment=matrix.trusted_gateway_environment({"WWISE_WAAPI_PORT": "18765"}),
                working_root=case_root / "broker", transport="tcp",
            ) as broker:
                config = CodexHarnessConfig(
                    workspace=workspace, skill_source=options.skill_source,
                    codex_binary=options.codex_binary, auth_json=options.auth_json,
                    model=options.model, reasoning_effort=options.reasoning_effort,
                    service_tier=options.service_tier, timeout_seconds=options.timeout_seconds,
                    expected_gateway_subcommands=("config-show",),
                    expected_wwise_version="2024.1", allow_output_write=False,
                    windows_powershell_core_host=options.windows_powershell_core_host,
                )
                with CodexCliTask(config, extra_env=broker.model_environment_overrides()) as task:
                    first = task.run_initial(prompt, output_dir=turn_directory)
                    save_turn(turn_directory, first)
                    argv = matrix.gateway_candidate_argvs(first, skill_source=installed,
                        alternate_skill_sources=(options.skill_source,), expected_wwise_version="2024.1")
                    evidence = broker.evidence()
                    checks = common_checks(first)
                    checks["one_offline_call"] = evidence.passed and broker.reconcile(argv).passed
                    checks["skill_read_once_first"] = (
                        first.command_facts.skill_read
                        and len(first.command_facts.allowed_read_commands) == 1
                        and len(first.command_facts.commands) == 2
                        and first.command_facts.commands[0] == first.command_facts.allowed_read_commands[0]
                    )
                    payload = evidence.records[0].payload if evidence.records else {}
                    facts = (payload or {}).get("session_context", {}).get("one_time_introduction", {}).get("facts", {})
                    intro = first_gateway_backed_agent_message(first.stdout,
                        validated_gateway_commands=first.command_facts.gateway_commands) or ""
                    checks.update(introduction_checks(intro, facts))
                    outcome.update(thread_id=task.thread_id, first_turn_checks=checks)
                    if all(checks.values()):
                        turn_directory = case_root / "turn-2"
                        later = task.run_followup(FOLLOWUP, output_dir=turn_directory)
                        save_turn(turn_directory, later)
                        later_checks = followup_checks(later, first.thread_id, facts)
                        outcome["followup_checks"] = later_checks
                        checks = {**checks, **{f"followup_{k}": v for k, v in later_checks.items()}}
                    matrix.write_json(case_root / "broker-evidence.json", asdict(broker.evidence()))
                    outcome["status"] = "PASS" if all(checks.values()) else "FAIL"
        except Exception as exc:
            if getattr(exc, "result", None) is not None:
                save_turn(turn_directory, exc.result)
            outcome["error"] = f"{type(exc).__name__}: {exc}"
        outcomes.append(outcome)
        matrix.write_json(case_root / "outcome.json", outcome)
        matrix.write_json(root / "summary.json", {"profile": "first_use_2", "outcomes": outcomes})
        print(f"[{outcome['status']}] {case_id}", flush=True)
        if outcome["status"] == "BLOCKED":
            break
    # Hash retained evidence, including raw per-turn events, without traversing
    # installed Skill symlinks. Never rewrite a root or convert a failed attempt.
    hashes = {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*")) if path.is_file() and not path.is_symlink()}
    matrix.write_json(root / "evidence-manifest.json", {"sha256": hashes})
    if any(row["status"] == "BLOCKED" for row in outcomes):
        return 3
    return 0 if len(outcomes) == 2 and all(row["status"] == "PASS" for row in outcomes) else 1


def followup_checks(result: Any, thread_id: str, facts: Mapping[str, Any]) -> dict[str, bool]:
    checks = common_checks(result)
    checks["no_commands"] = not result.command_facts.commands
    checks["same_thread"] = result.thread_id == thread_id
    text = agent_messages(result.stdout)
    checks["no_repeated_welcome"] = not all(
        mode in text for mode in ("read_only", "ask_before_changes", "allow_changes")
    ) and not all(introduction_checks(text, facts).values())
    return checks
