#!/usr/bin/env python3
"""Render the v3 semantic definitions as a bounded human-review catalog."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = REPO_ROOT / "skills" / "waapi-skill"
for import_root in (REPO_ROOT, SKILL_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from tests.semantic.support.codex_eval_bundle_v3 import (  # noqa: E402
    EvalBundleV3Error,
    OnlineScenario,
    load_eval_bundle_v3,
)


DEFAULT_SUITE = REPO_ROOT / "skills" / "waapi-skill" / "evals" / "suite-v3.json"
HEAVY_API_URIS = frozenset(
    {
        "ak.wwise.core.object.get",
        "ak.wwise.core.object.create",
        "ak.wwise.core.object.set",
        "ak.wwise.core.audio.import",
        "ak.wwise.core.audio.importTabDelimited",
        "ak.wwise.core.audio.convert",
        "ak.wwise.core.mediaPool.get",
        "ak.wwise.core.soundbank.generate",
        "ak.wwise.core.soundbank.generated",
        "ak.wwise.core.soundbank.processDefinitionFiles",
        "ak.wwise.core.soundbank.convertExternalSources",
        "ak.wwise.core.soundbank.setInclusions",
        "ak.wwise.cli.generateSoundbank",
        "ak.wwise.cli.tabDelimitedImport",
        "ak.wwise.cli.convertExternalSource",
        "ak.wwise.cli.migrate",
    }
)


def render_review(
    suite_path: Path,
    *,
    case_id: str | None = None,
    api: str | None = None,
    lane: str | None = None,
    version: str | None = None,
    heavy_only: bool = False,
    summary_only: bool = False,
) -> str:
    bundle = load_eval_bundle_v3(suite_path)
    scenarios = tuple(
        scenario
        for scenario in bundle.scenarios
        if (case_id is None or scenario.id == case_id)
        and (api is None or scenario.api == api)
        and (lane is None or scenario.lane == lane)
        and (version is None or version in scenario.versions)
        and (not heavy_only or scenario.api in HEAVY_API_URIS)
    )
    if not scenarios:
        filters = {
            "case_id": case_id,
            "api": api,
            "lane": lane,
            "version": version,
            "heavy_only": heavy_only or None,
        }
        selected_filters = {key: value for key, value in filters.items() if value is not None}
        raise EvalBundleV3Error(
            f"no v3 online scenarios match review filters {selected_filters}"
        )
    by_api: dict[str, list[OnlineScenario]] = {}
    for scenario in scenarios:
        by_api.setdefault(scenario.api, []).append(scenario)
    selected_2022 = tuple(item for item in scenarios if "2022.1" in item.versions)
    selected_2022_confirmations = sum(
        item.confirmation_turn_count for item in selected_2022
    )
    visible_input_cases = tuple(item for item in scenarios if item.visible_inputs)
    blocked_cases = tuple(
        item for item in scenarios if bundle.scenario_mapping_blockers(item.id)
    )

    lines = [
        "# WAAPI Skill v3 semantic-test review",
        "",
        f"- Online scenarios: {len(scenarios)}",
        f"- Covered APIs: {len(by_api)}",
        "- Representative-version scenarios: "
        + ", ".join(
            f"{version}={sum(version in item.versions for item in scenarios)}"
            for version in ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1")
        ),
        f"- Wwise 2022.1 execution selection: {len(selected_2022)} scenarios / "
        f"{len({item.api for item in selected_2022})} APIs",
        f"- Wwise 2022.1 fresh-task/turn cost: {len(selected_2022)} / "
        f"{len(selected_2022) + selected_2022_confirmations}",
        f"- Functions/topics: {Counter(item.item_type for item in scenarios).get('function', 0)} / "
        f"{Counter(item.item_type for item in scenarios).get('topic', 0)} scenario rows",
        f"- Dynamic visible inputs: {len(visible_input_cases)} scenarios / "
        f"{sum(len(item.visible_inputs) for item in visible_input_cases)} fields",
        f"- Offline cases (no functional credit): {len(bundle.offline_cases)}",
        f"- Adapter status: `{bundle.adapter_implementation_status}`",
        f"- Request-mapping status: `{bundle.request_mapping_implementation_status}`",
        f"- Mapping-blocked scenarios/APIs: {len(blocked_cases)} / "
        f"{len({item.api for item in blocked_cases})}",
        "- Execution evidence: not run; definitions await user review",
        "",
    ]
    if summary_only:
        lines.extend(
            [
                "| API | Definition versions | Route | Effect | Scenarios | Blocked | Families |",
                "| --- | --- | --- | --- | ---: | ---: | --- |",
            ]
        )
        coverage = {row.api: row for row in bundle.coverage}
        for uri in sorted(by_api):
            row = coverage[uri]
            selected_cases = by_api[uri]
            blocked_count = sum(
                bool(bundle.scenario_mapping_blockers(scenario.id))
                for scenario in selected_cases
            )
            lines.append(
                f"| `{uri}` | `{', '.join(row.definition_versions)}` | `{row.route}` | "
                f"`{row.effect}` | {len(selected_cases)} | {blocked_count} | "
                + ", ".join(
                    f"`{scenario.scenario_family}`" for scenario in selected_cases
                )
                + " |"
            )
        return "\n".join(lines) + "\n"

    for uri in sorted(by_api):
        lines.extend([f"## `{uri}`", ""])
        for scenario in sorted(by_api[uri], key=lambda item: (item.scenario_index, item.id)):
            lines.extend(
                [
                    f"### {scenario.id}",
                    "",
                    f"- Lane: `{scenario.lane}`",
                    f"- Versions: `{', '.join(scenario.versions)}`",
                    f"- Family: `{scenario.scenario_family}`",
                    f"- Protocol: `{scenario.protocol}`",
                    f"- Confirmation turns: {scenario.confirmation_turn_count}",
                    f"- Fixture: `{scenario.fixture['adapter']}`",
                    "",
                    f"> {scenario.prompt}",
                    "",
                ]
            )
            if scenario.visible_inputs:
                lines.extend(["Visible prompt inputs:", ""])
                for visible_input in scenario.visible_inputs:
                    lines.append(
                        f"- `{{{visible_input.name}}}` / `{visible_input.kind}`: "
                        f"{visible_input.description}"
                    )
                lines.append("")
            if scenario.confirmation_prompt is not None:
                lines.extend([f"> {scenario.confirmation_prompt}", ""])
            mapping_blockers = bundle.scenario_mapping_blockers(scenario.id)
            if mapping_blockers:
                lines.extend(["Request-mapping blockers:", ""])
                for requirement in mapping_blockers:
                    lines.append(
                        f"- `{requirement.id}` / `{requirement.status}` / "
                        f"`{', '.join(requirement.json_pointers)}`: "
                        + "; ".join(requirement.required_semantics)
                    )
                lines.append("")
            lines.extend(["Fixture prerequisites:", ""])
            for prerequisite in scenario.fixture["prerequisites"]:
                lines.append(f"- {prerequisite}")
            lines.extend(["", "Expected model dispatches:", ""])
            for dispatch in scenario.expected_dispatches:
                lines.append(
                    f"- `{dispatch.api}` × {dispatch.count}: {dispatch.effect}"
                )
            asset_spec = scenario.fixture.get("asset_spec")
            if asset_spec is not None:
                lines.extend(
                    [
                        "",
                        "Fixture asset specification:",
                        "",
                        "```json",
                        json.dumps(asset_spec, ensure_ascii=False, indent=2),
                        "```",
                    ]
                )
            if scenario.trigger is not None:
                lines.extend(
                    [
                        "",
                        "Runner-owned topic trigger:",
                        "",
                        f"- `{scenario.trigger['adapter']}` via "
                        f"`{scenario.trigger['publisher_api']}`: "
                        f"{scenario.trigger['ownership_assertion']}",
                    ]
                )
            lines.extend(["", "Assertions:", ""])
            for assertion in scenario.oracle_assertions:
                lines.append(
                    f"- `{assertion.phase}` / `{assertion.adapter}`: {assertion.expectation}"
                )
            lines.extend(["", "Cleanup postconditions:", ""])
            lines.append(f"- Adapter: `{scenario.cleanup['adapter']}`")
            for postcondition in scenario.cleanup["postconditions"]:
                lines.append(f"- `{postcondition}`")
            lines.append("")
    return "\n".join(lines) + "\n"


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", default=str(DEFAULT_SUITE))
    parser.add_argument("--case-id")
    parser.add_argument("--api")
    parser.add_argument("--lane")
    parser.add_argument("--version")
    parser.add_argument(
        "--heavy-only",
        action="store_true",
        help="render only the 16 reviewed heavy API/topic groups",
    )
    parser.add_argument("--summary-only", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    print(
        render_review(
            Path(args.suite).expanduser().resolve(strict=True),
            case_id=args.case_id,
            api=args.api,
            lane=args.lane,
            version=args.version,
            heavy_only=args.heavy_only,
            summary_only=args.summary_only,
        ),
        end="",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
