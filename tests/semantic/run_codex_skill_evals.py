#!/usr/bin/env python3
"""Run isolated Codex CLI semantic evals against a real WwiseConsole sandbox."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = REPO_ROOT / "skills" / "waapi-skill"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))

from tests.semantic.run_opencode_semantic_batch import _LiveSandbox  # noqa: E402  # pyright: ignore[reportPrivateUsage]
from tests.semantic.support.codex_harness import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    CodexCliHarness,
    CodexHarnessConfig,
    CodexHarnessError,
    CodexRunResult,
)
from tests.semantic.support.codex_gateway_broker import (  # noqa: E402  # pyright: ignore[reportMissingImports]
    CodexGatewayBroker,
    ExpectedGatewayStep,
)


DEFAULT_EVALS = SKILL_ROOT / "evals" / "evals.json"
DEFAULT_ITERATION_ROOT = REPO_ROOT / "skills" / "waapi-skill-workspace" / "iteration-1"
DEFAULT_AUTH_JSON = Path.home() / ".codex" / "auth.json"
DEFAULT_CODEX_BINARY = Path("/Applications/ChatGPT.app/Contents/Resources/codex")
EXPECTED_GATEWAY_SUBCOMMANDS: Mapping[str, tuple[str, ...]] = {
    "current_project": ("status",),
    "bus_listing": ("buses",),
    "selected_object": ("selected",),
}
HARD_GATE_CHECK_IDS = frozenset({"no_memory", "skill_loaded", "fixed_gateway", "no_ad_hoc_code"})


@dataclass(frozen=True, slots=True)
class EvalCase:
    id: int
    name: str
    scenario: str
    prompt: str
    expected_output: str
    required_apis: tuple[str, ...]
    checks: tuple[Mapping[str, str], ...]


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.configuration != "with_skill":
        raise SystemExit(
            "Only --configuration with_skill is implemented; old_skill/without_skill were labels, not real baselines."
        )
    evals = selected_evals(load_evals(Path(args.evals)), args.eval_id)
    skill_source = Path(args.skill_source).expanduser().resolve(strict=True)
    iteration_root = Path(args.iteration_root).expanduser().resolve(strict=False)
    failures = 0
    for case in evals:
        eval_dir = iteration_root / f"eval-{case.id}-{case.name}"
        write_json(eval_dir / "eval_metadata.json", eval_metadata(case))
        for run_number in range(1, args.runs_per_eval + 1):
            run_dir = eval_dir / args.configuration / f"run-{run_number}"
            if run_dir.exists():
                if not args.overwrite:
                    raise SystemExit(f"run directory already exists; pass --overwrite to replace it: {run_dir}")
                shutil.rmtree(run_dir)
            outputs_dir = run_dir / "outputs"
            outputs_dir.mkdir(parents=True, exist_ok=True)
            write_json(run_dir / "eval_metadata.json", eval_metadata(case))
            passed = run_one_eval(
                case,
                run_dir=run_dir,
                outputs_dir=outputs_dir,
                skill_source=skill_source,
                version=args.wwise_version,
                codex_binary=Path(args.codex_binary),
                auth_json=Path(args.auth_json),
                timeout_seconds=args.timeout,
                reasoning_effort=args.reasoning_effort,
            )
            failures += 0 if passed else 1
    return 1 if failures else 0


def run_one_eval(
    case: EvalCase,
    *,
    run_dir: Path,
    outputs_dir: Path,
    skill_source: Path,
    version: str,
    codex_binary: Path,
    auth_json: Path,
    timeout_seconds: float,
    reasoning_effort: str,
) -> bool:
    workspace = run_dir / "agent-workspace"
    prepare_agent_workspace(workspace, skill_source)
    evidence_dir = outputs_dir / "waapi-evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    live = _LiveSandbox(version)
    result: CodexRunResult | None = None
    oracle: dict[str, Any] = {}
    harness_error = ""
    started_at = utc_now()
    try:
        metadata = live.launch()
        oracle = query_oracle(case.scenario, host=metadata.waapi_host, port=metadata.waapi_port)
        runner_environment = dict(live.env)
        runner_environment.update(
            {
                "WWISE_VERSION": metadata.wwise_version,
                "WWISE_WAAPI_HOST": metadata.waapi_host,
                "WWISE_WAAPI_PORT": str(metadata.waapi_port),
            }
        )
        expected_subcommands = EXPECTED_GATEWAY_SUBCOMMANDS.get(case.scenario, ())
        if len(expected_subcommands) != 1:
            raise CodexHarnessError(f"legacy eval scenario has no exact broker route: {case.scenario}")
        with CodexGatewayBroker(
            skill_source=skill_source,
            expected_steps=(
                ExpectedGatewayStep(
                    name=f"legacy-{case.scenario}",
                    subcommand=expected_subcommands[0],
                ),
            ),
            runner_environment=runner_environment,
            working_root=run_dir / "broker",
            transport="tcp",
        ) as broker:
            harness = CodexCliHarness(
                CodexHarnessConfig(
                    workspace=workspace,
                    skill_source=skill_source,
                    codex_binary=codex_binary,
                    auth_json=auth_json,
                    timeout_seconds=timeout_seconds,
                    reasoning_effort=reasoning_effort,
                    expected_gateway_subcommands=expected_subcommands,
                )
            )
            result = harness.run(
                case.prompt,
                output_dir=outputs_dir,
                extra_env=broker.model_environment_overrides(),
            )
    except (CodexHarnessError, OSError, RuntimeError) as exc:
        harness_error = f"{type(exc).__name__}: {exc}"
    finally:
        live.cleanup()
    completed_at = utc_now()

    evidence = load_evidence(evidence_dir)
    facts = build_run_facts(case, result=result, oracle=oracle, evidence=evidence, harness_error=harness_error)
    write_json(outputs_dir / "run-facts.json", facts)
    write_json(outputs_dir / "oracle.json", oracle)
    (outputs_dir / "final.txt").write_text((result.final_response if result else harness_error) + "\n", encoding="utf-8")
    (outputs_dir / "events.jsonl").write_text(result.stdout if result else "", encoding="utf-8")
    (outputs_dir / "stderr.txt").write_text(result.stderr if result else harness_error + "\n", encoding="utf-8")
    transcript = render_transcript(case, result=result, harness_error=harness_error)
    (run_dir / "transcript.md").write_text(transcript, encoding="utf-8")
    metrics = build_metrics(result, transcript=transcript)
    write_json(outputs_dir / "metrics.json", metrics)
    timing = build_timing(result, started_at=started_at, completed_at=completed_at)
    write_json(run_dir / "timing.json", timing)
    grading = grade_case(case, result=result, oracle=oracle, evidence=evidence, facts=facts, metrics=metrics)
    write_json(run_dir / "grading.json", grading)
    return bool(grading["summary"].get("case_passed") is True)


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evals", default=str(DEFAULT_EVALS))
    parser.add_argument("--iteration-root", default=str(DEFAULT_ITERATION_ROOT))
    parser.add_argument("--skill-source", required=True)
    parser.add_argument("--configuration", choices=("with_skill", "old_skill", "without_skill"), required=True)
    parser.add_argument("--eval-id", action="append", type=int, default=[])
    parser.add_argument("--runs-per-eval", type=int, default=1)
    parser.add_argument("--wwise-version", default="2022.1")
    parser.add_argument("--codex-binary", default=str(DEFAULT_CODEX_BINARY))
    parser.add_argument("--auth-json", default=str(DEFAULT_AUTH_JSON))
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument(
        "--reasoning-effort",
        choices=("minimal", "low", "medium", "high", "xhigh", "ultra"),
        default="medium",
    )
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)
    if args.runs_per_eval <= 0:
        parser.error("--runs-per-eval must be greater than zero")
    if args.timeout <= 0:
        parser.error("--timeout must be greater than zero")
    return args


def load_evals(path: Path) -> tuple[EvalCase, ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping) or payload.get("contract") != "waapi-skill.codex-read-evals/v1":
        raise ValueError("eval suite must declare contract waapi-skill.codex-read-evals/v1")
    cases: list[EvalCase] = []
    raw_cases = payload.get("evals")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ValueError("eval suite must contain at least one eval")
    seen_ids: set[int] = set()
    for item in raw_cases:
        if not isinstance(item, Mapping):
            raise ValueError("every eval must be a JSON object")
        case = EvalCase(
            id=int(item["id"]),
            name=str(item.get("name") or f"eval-{item['id']}"),
            scenario=str(item["scenario"]),
            prompt=str(item["prompt"]),
            expected_output=str(item.get("expected_output") or ""),
            required_apis=tuple(str(api) for api in item.get("required_apis", [])),
            checks=tuple(dict(check) for check in item.get("checks", [])),
        )
        if case.id in seen_ids:
            raise ValueError(f"duplicate eval id: {case.id}")
        seen_ids.add(case.id)
        if not case.prompt.strip() or not case.checks:
            raise ValueError(f"eval {case.id} must have a non-empty prompt and checks")
        check_ids = {str(check.get("id") or "") for check in case.checks}
        missing_hard_gates = sorted(HARD_GATE_CHECK_IDS - check_ids)
        if missing_hard_gates:
            raise ValueError(f"eval {case.id} is missing hard gates: {', '.join(missing_hard_gates)}")
        cases.append(case)
    return tuple(cases)


def selected_evals(cases: Sequence[EvalCase], selected_ids: Sequence[int]) -> tuple[EvalCase, ...]:
    if not selected_ids:
        return tuple(cases)
    selected = set(selected_ids)
    resolved = tuple(case for case in cases if case.id in selected)
    missing = sorted(selected - {case.id for case in resolved})
    if missing:
        raise ValueError(f"unknown eval id(s): {', '.join(str(value) for value in missing)}")
    return resolved


def prepare_agent_workspace(workspace: Path, skill_source: Path) -> None:
    install = workspace / ".agents" / "skills" / "waapi-skill"
    install.parent.mkdir(parents=True, exist_ok=True)
    install.symlink_to(skill_source, target_is_directory=True)


def query_oracle(scenario: str, *, host: str, port: int) -> dict[str, Any]:
    from waapi import WaapiClient  # type: ignore[import-not-found]  # noqa: PLC0415

    url = f"ws://{host}:{port}/waapi"
    payload: dict[str, Any] = {"url": url, "scenario": scenario, "api_attempts": []}
    client = WaapiClient(url=url, allow_exception=True)
    try:
        if scenario == "current_project":
            payload["api_attempts"].append("ak.wwise.core.getInfo")
            payload["get_info"] = client.call("ak.wwise.core.getInfo")
            version = payload["get_info"].get("version", {}) if isinstance(payload["get_info"], Mapping) else {}
            if version.get("year") == 2021 and version.get("major") == 1:
                payload["api_attempts"].append("ak.wwise.core.object.get")
                project_query = client.call(
                    "ak.wwise.core.object.get",
                    {"waql": "from type Project"},
                    {"return": ["id", "name", "type", "path"]},
                )
                payload["project_query"] = project_query
                project_rows = oracle_rows(project_query)
                payload["get_project_info"] = dict(project_rows[0]) if project_rows else None
            else:
                payload["api_attempts"].append("ak.wwise.core.getProjectInfo")
                payload["get_project_info"] = client.call("ak.wwise.core.getProjectInfo")
        elif scenario == "bus_listing":
            payload["api_attempts"].append("ak.wwise.core.object.get")
            payload["object_get"] = client.call(
                "ak.wwise.core.object.get",
                {"waql": "from type Bus"},
                {"return": ["id", "name", "type", "path"]},
            )
        elif scenario == "selected_object":
            payload["api_attempts"].append("ak.wwise.ui.getSelectedObjects")
            try:
                payload["selected_objects"] = client.call(
                    "ak.wwise.ui.getSelectedObjects",
                    {},
                    {"return": ["id", "name", "type", "path"]},
                )
            except Exception as exc:  # noqa: BLE001 - the boundary itself is oracle data
                payload["selected_objects_error"] = {"type": type(exc).__name__, "message": str(exc)}
        else:
            raise ValueError(f"unsupported eval scenario: {scenario}")
    finally:
        client.disconnect()
    return payload


def load_evidence(root: Path) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            evidence.append({"path": str(path), "payload": payload})
    return evidence


def build_run_facts(
    case: EvalCase,
    *,
    result: CodexRunResult | None,
    oracle: Mapping[str, Any],
    evidence: Sequence[Mapping[str, Any]],
    harness_error: str,
) -> dict[str, Any]:
    return {
        "eval_id": case.id,
        "eval_name": case.name,
        "scenario": case.scenario,
        "harness_error": harness_error,
        "codex": result.facts_dict() if result else None,
        "oracle": dict(oracle),
        "evidence_apis": sorted(result.command_facts.gateway_evidence_apis if result else ()),
        "untrusted_evidence_file_apis": sorted(evidence_apis(evidence)),
        "evidence_paths": [str(item.get("path") or "") for item in evidence],
    }


def grade_case(
    case: EvalCase,
    *,
    result: CodexRunResult | None,
    oracle: Mapping[str, Any],
    evidence: Sequence[Mapping[str, Any]],
    facts: Mapping[str, Any],
    metrics: Mapping[str, Any],
) -> dict[str, Any]:
    available_apis = set(result.command_facts.gateway_evidence_apis if result else ())
    expectations: list[dict[str, Any]] = []
    for check in case.checks:
        check_id = str(check.get("id") or "")
        text = str(check.get("text") or check_id)
        passed, proof = evaluate_check(
            check_id,
            case=case,
            result=result,
            oracle=oracle,
            available_apis=available_apis,
        )
        expectations.append({"text": text, "passed": passed, "evidence": proof})
    summary = summarize_expectations(case, expectations)
    return {
        "expectations": expectations,
        "summary": summary,
        "execution_metrics": dict(metrics),
        "claims": verified_claims(case, result=result, oracle=oracle),
        "user_notes_summary": {
            "uncertainties": [str(facts.get("harness_error"))] if facts.get("harness_error") else [],
            "needs_review": [],
            "workarounds": blocker_notes(result),
        },
        "eval_feedback": {"suggestions": [], "overall": "Checks use prompt audit, command trace, runtime evidence, and a live oracle."},
    }


def summarize_expectations(
    case: EvalCase,
    expectations: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    passed_count = sum(1 for expectation in expectations if expectation.get("passed") is True)
    total = len(expectations)
    failed = total - passed_count
    raw_pass_rate = round(passed_count / total, 4) if total else 0.0
    failed_hard_gates = [
        str(check.get("id") or "")
        for check, expectation in zip(case.checks, expectations, strict=True)
        if str(check.get("id") or "") in HARD_GATE_CHECK_IDS and expectation.get("passed") is not True
    ]
    hard_gate_passed = not failed_hard_gates
    return {
        "passed": passed_count,
        "failed": failed,
        "total": total,
        "raw_pass_rate": raw_pass_rate,
        "pass_rate": raw_pass_rate if hard_gate_passed else 0.0,
        "hard_gate_passed": hard_gate_passed,
        "failed_hard_gates": failed_hard_gates,
        "case_passed": total > 0 and hard_gate_passed and failed == 0,
    }


def evaluate_check(
    check_id: str,
    *,
    case: EvalCase,
    result: CodexRunResult | None,
    oracle: Mapping[str, Any],
    available_apis: set[str],
) -> tuple[bool, str]:
    if result is None:
        return False, "The Codex run did not produce a result."
    if check_id == "no_memory":
        passed = (
            result.prompt_audit.passed
            and not result.prompt_audit.has_memory
            and result.isolation_audit.passed
            and result.session_audit.passed
        )
        return passed, (
            f"prompt audit={result.prompt_audit}; isolation_passed={result.isolation_audit.passed}; "
            f"session_audit={result.session_audit}"
        )
    if check_id == "skill_loaded":
        passed = (
            result.prompt_audit.passed
            and result.prompt_audit.has_target_skill
            and result.prompt_audit.target_skill_count == 1
            and result.prompt_audit.target_skill_locator_matches
            and not result.prompt_audit.unexpected_skills
            and result.command_facts.skill_read
        )
        return passed, (
            f"inventory={result.prompt_audit.skill_inventory}; "
            f"target_count={result.prompt_audit.target_skill_count}; "
            f"locator_matches={result.prompt_audit.target_skill_locator_matches}; "
            f"unexpected_skills={result.prompt_audit.unexpected_skills}; skill_read={result.command_facts.skill_read}"
        )
    if check_id == "fixed_gateway":
        passed = (
            len(result.command_facts.gateway_commands) == 1
            and len(result.command_facts.allowed_read_commands) == 1
            and len(result.command_facts.command_records) == 2
            and result.command_facts.gateway_before_discovery
            and not result.command_facts.unexpected_commands
            and all(record.succeeded for record in result.command_facts.command_records)
        )
        return passed, (
            f"gateway_commands={len(result.command_facts.gateway_commands)}; "
            f"gateway_subcommands={result.command_facts.gateway_subcommands}; "
            f"allowed_read_commands={len(result.command_facts.allowed_read_commands)}; "
            f"total_commands={len(result.command_facts.command_records)}; "
            f"discovery_commands={len(result.command_facts.discovery_commands)}; "
            f"gateway_before_discovery={result.command_facts.gateway_before_discovery}; "
            f"unexpected_commands={list(result.command_facts.unexpected_commands)}"
        )
    if check_id == "no_ad_hoc_code":
        workspace_mutations = [
            f"workspace:{path}"
            for path in (*result.created_files, *result.modified_files, *result.deleted_files)
            if not path.startswith("outputs/")
        ]
        violations = (
            list(result.command_facts.inline_python_commands)
            + list(result.command_facts.direct_waapi_client_commands)
            + list(result.command_facts.write_like_commands)
            + list(getattr(result.command_facts, "unexpected_commands", ()))
            + list(result.created_source_files)
            + list(result.modified_source_files)
            + list(result.deleted_source_files)
            + workspace_mutations
        )
        file_change_count = int(getattr(result, "file_change_count", 0))
        passed = (
            not violations
            and result.skill_tree_unchanged
            and result.collab_call_count == 0
            and file_change_count == 0
        )
        return passed, (
            f"violations={violations}; skill_tree_unchanged={result.skill_tree_unchanged}; "
            f"collab_call_count={result.collab_call_count}; file_change_count={file_change_count}"
        )
    if check_id == "live_evidence":
        trusted_available_apis = set(result.command_facts.gateway_evidence_apis)
        oracle_apis = oracle.get("api_attempts")
        required_apis = tuple(str(api) for api in oracle_apis) if isinstance(oracle_apis, Sequence) else case.required_apis
        missing = sorted(set(required_apis) - trusted_available_apis)
        return not missing, (
            f"required={list(required_apis)}; successful_gateway_runtime_apis={sorted(trusted_available_apis)}; "
            f"missing={missing}"
        )
    if check_id == "actual_result":
        passed, proof = response_matches_oracle(case.scenario, result.final_response, oracle)
        passed = passed and result.exit_status == 0 and not result.timed_out
        return passed, f"exit={result.exit_status}; timed_out={result.timed_out}; {proof}"
    return False, f"Unknown check id: {check_id}"


def evidence_apis(evidence: Sequence[Mapping[str, Any]]) -> set[str]:
    apis: set[str] = set()
    for item in evidence:
        payload = item.get("payload")
        if isinstance(payload, Mapping) and isinstance(payload.get("api"), str):
            apis.add(str(payload["api"]))
    return apis


def response_matches_oracle(scenario: str, response: str, oracle: Mapping[str, Any]) -> tuple[bool, str]:
    lowered = response.lower()
    if scenario == "current_project":
        get_info = oracle.get("get_info")
        version = get_info.get("version") if isinstance(get_info, Mapping) else None
        version_candidates: list[str] = []
        if isinstance(version, Mapping):
            display_name = version.get("displayName")
            if isinstance(display_name, str) and display_name:
                version_candidates.extend([display_name, display_name.removeprefix("v")])
            year = version.get("year")
            major = version.get("major")
            minor = version.get("minor")
            if isinstance(year, int) and isinstance(major, int):
                version_candidates.append(f"{year}.{major}")
                if isinstance(minor, int):
                    version_candidates.append(f"{year}.{major}.{minor}")
        project_info = oracle.get("get_project_info")
        project_name = str(project_info.get("name") or "") if isinstance(project_info, Mapping) else ""
        project_paths = [
            str(project_info[key])
            for key in ("path", "projectPath")
            if isinstance(project_info, Mapping) and isinstance(project_info.get(key), str)
        ]
        normalized_versions = {
            candidate.lower().removeprefix("v")
            for candidate in version_candidates
            if candidate
        }
        reported_versions = [
            match.group(1).lower()
            for match in re.finditer(r"(?<!\d)v?(20\d{2}\.\d+(?:\.\d+)?)(?!\d)", response, re.IGNORECASE)
        ]
        version_hit = bool(reported_versions and any(value in normalized_versions for value in reported_versions))
        version_consistent = bool(reported_versions) and all(value in normalized_versions for value in reported_versions)
        project_hit = bool(project_name and response_contains_exact_label(response, project_name))
        oracle_paths = [candidate for candidate in project_paths if candidate.lower().endswith(".wproj")]
        response_path_lines = [line for line in response.splitlines() if ".wproj" in line.lower()]
        path_consistent = not response_path_lines or all(
            reported_project_path_matches_oracle(line, oracle_paths)
            for line in response_path_lines
        )
        return version_hit and version_consistent and project_hit and path_consistent, (
            f"version_candidates={version_candidates}; project_name={project_name!r}; project_paths={project_paths}; "
            f"reported_versions={reported_versions}; version_consistent={version_consistent}; "
            f"response_path_lines={response_path_lines}; path_consistent={path_consistent}"
        )
    if scenario == "bus_listing":
        rows = oracle_rows(oracle.get("object_get"))
        names = list(dict.fromkeys(str(row.get("name")) for row in rows if row.get("name")))
        if names:
            missing_names = [name for name in names if not response_contains_exact_label(response, name)]
            count = len(rows)
            count_match = bool(
                re.search(rf"(?<!\d){count}(?!\d)\s*(?:个\s*)?(?:bus|busses|总线)", lowered, re.IGNORECASE)
                or re.search(rf"(?:bus|busses|总线)[^\n\d]{{0,12}}(?<!\d){count}(?!\d)", lowered, re.IGNORECASE)
            )
            return not missing_names and count_match, (
                f"oracle_bus_count={count}; missing_names={missing_names}; count_match={count_match}"
            )
        empty_words = ("empty", "none", "no bus", "没有", "为空", "0 个")
        return any(word in lowered for word in empty_words), "oracle returned an empty bus list"
    if scenario == "selected_object":
        error = oracle.get("selected_objects_error")
        if isinstance(error, Mapping):
            boundary_words = (
                "headless",
                "command-line",
                "command line",
                "unavailable",
                "not available",
                "not supported",
                "unsupported",
                "不可用",
                "不支持",
                "拿不到",
                "无法取得",
                "无法获取",
            )
            api_context = "getselectedobjects" in lowered or "ui" in lowered or "选择" in lowered or "选中" in lowered
            negative_boundary = any(word in lowered for word in boundary_words)
            positive_claim = bool(
                re.search(r"\bui\s+(?:is\s+)?available\b", lowered)
                or re.search(r"ui\s*(?:接口)?\s*(?:可用|支持)", lowered)
            )
            return api_context and negative_boundary and not positive_claim, (
                f"oracle_boundary={dict(error)}; api_context={api_context}; "
                f"negative_boundary={negative_boundary}; positive_claim={positive_claim}"
            )
        rows = oracle_rows(oracle.get("selected_objects"), key="objects")
        if rows:
            missing_fields: list[str] = []
            for row in rows:
                for field in ("name", "type", "path"):
                    value = row.get(field)
                    if not isinstance(value, str) or not value:
                        continue
                    if field == "path":
                        present = normalize_path(value) in normalize_path(response)
                    else:
                        present = response_contains_exact_label(response, value)
                    if not present:
                        missing_fields.append(f"{field}={value}")
            return not missing_fields, f"selected_count={len(rows)}; missing_fields={missing_fields}"
        empty_words = ("empty", "none", "no object", "未选择", "没有选中", "为空")
        return any(word in lowered for word in empty_words), "oracle returned an explicit empty selection"
    return False, f"unsupported scenario={scenario}"


def collect_strings(value: Any, *, keys: set[str]) -> list[str]:
    found: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            if str(key) in keys and isinstance(child, str) and child:
                found.append(child)
            found.extend(collect_strings(child, keys=keys))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for child in value:
            found.extend(collect_strings(child, keys=keys))
    return list(dict.fromkeys(found))


def normalize_path(value: str) -> str:
    return value.strip().strip("`\"'").replace("/", "\\").lower()


def response_contains_exact_label(response: str, label: str) -> bool:
    """Match an object label without accepting it as part of a longer identifier."""

    return bool(re.search(rf"(?<![\w-]){re.escape(label)}(?![\w-])", response, re.IGNORECASE))


def reported_project_path_matches_oracle(line: str, oracle_paths: Sequence[str]) -> bool:
    """Accept a full path, truthful suffix, or the exact oracle project filename."""

    normalized_oracles = [normalize_path(path) for path in oracle_paths]
    if any(oracle in normalize_path(line) for oracle in normalized_oracles):
        return True
    code_paths = re.findall(r"`([^`]*\.wproj)`", line, flags=re.IGNORECASE)
    for reported in code_paths:
        normalized = normalize_path(reported)
        if normalized.startswith("..."):
            normalized = normalized[3:]
        elif normalized.startswith("…"):
            normalized = normalized[1:]
        normalized = normalized.lstrip("\\")
        if "\\" not in normalized:
            if any(oracle.rsplit("\\", 1)[-1] == normalized for oracle in normalized_oracles):
                return True
            continue
        if any(oracle.endswith("\\" + normalized) or oracle.endswith(normalized) for oracle in normalized_oracles):
            return True
    return False


def oracle_rows(value: Any, *, key: str = "return") -> list[Mapping[str, Any]]:
    if isinstance(value, Mapping) and isinstance(value.get(key), list):
        return [row for row in value[key] if isinstance(row, Mapping)]
    return []


def verified_claims(case: EvalCase, *, result: CodexRunResult | None, oracle: Mapping[str, Any]) -> list[dict[str, Any]]:
    if result is None or not result.final_response:
        return []
    matched, proof = response_matches_oracle(case.scenario, result.final_response, oracle)
    return [
        {
            "claim": "The final response describes the live Wwise result.",
            "type": "factual",
            "verified": matched,
            "evidence": proof,
        }
    ]


def blocker_notes(result: CodexRunResult | None) -> list[str]:
    if result is None:
        return []
    lowered = result.final_response.lower()
    if any(word in lowered for word in ("blocked", "阻塞", "没有可执行", "无法取得")):
        return [result.final_response]
    return []


def build_metrics(result: CodexRunResult | None, *, transcript: str) -> dict[str, Any]:
    command_count = len(result.command_facts.commands) if result else 0
    collab_count = result.collab_call_count if result else 0
    final = result.final_response if result else ""
    return {
        "tool_calls": {"Bash": command_count, "Collab": collab_count},
        "total_tool_calls": command_count + collab_count,
        "total_steps": (result.event_count if result else 0),
        "files_created": list(result.created_files if result else ()),
        "errors_encountered": int(result is None or result.exit_status != 0 or result.timed_out),
        "output_chars": len(final),
        "transcript_chars": len(transcript),
    }


def build_timing(result: CodexRunResult | None, *, started_at: str, completed_at: str) -> dict[str, Any]:
    usage = result.usage if result else {}
    total_tokens = int(usage.get("input_tokens", 0)) + int(usage.get("output_tokens", 0))
    duration = result.duration_seconds if result else 0.0
    return {
        "total_tokens": total_tokens,
        "duration_ms": round(duration * 1000),
        "total_duration_seconds": duration,
        "executor_start": started_at,
        "executor_end": completed_at,
        "executor_duration_seconds": duration,
    }


def render_transcript(case: EvalCase, *, result: CodexRunResult | None, harness_error: str) -> str:
    lines = ["## Eval Prompt", "", case.prompt, "", "## Expected Output", "", case.expected_output, ""]
    if result is None:
        lines.extend(["## Harness Error", "", harness_error, ""])
        return "\n".join(lines)
    lines.extend(["## Final Response", "", result.final_response, "", "## Commands", ""])
    lines.extend(f"- `{command}`" for command in result.command_facts.commands)
    lines.extend(["", "## Runtime", "", f"- exit_status: {result.exit_status}", f"- duration_seconds: {result.duration_seconds}"])
    return "\n".join(lines) + "\n"


def eval_metadata(case: EvalCase) -> dict[str, Any]:
    return {
        "eval_id": case.id,
        "eval_name": case.name,
        "prompt": case.prompt,
        "expected_output": case.expected_output,
        "assertions": [str(check.get("text") or check.get("id") or "") for check in case.checks],
    }


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())
