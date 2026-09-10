"""Fresh Agent runner for the packaged audio.import business interface."""

from __future__ import annotations

import json
import os
import wave
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from tests.semantic.support.codex_business_agent_runner import (
    BusinessAgentOptions,
    BusinessAgentRunSpec,
    run_business_agent_unit,
)
from tests.semantic.support.codex_eval_protocol_v3 import (
    build_audio_import_composer_transaction_steps,
)
from tests.semantic.support.codex_import_business_profile import ImportBusinessUnit


OUTCOME_CONTRACT = "waapi-skill.audio-import-business-agent-outcome/v1"
_REPORT_MINUS_TRANSLATION = str.maketrans(
    {
        "\N{MINUS SIGN}": "-",
        "\N{SMALL HYPHEN-MINUS}": "-",
        "\N{FULLWIDTH HYPHEN-MINUS}": "-",
    }
)


ImportBusinessAgentOptions = BusinessAgentOptions


@dataclass(frozen=True, slots=True)
class ImportBusinessRuntime:
    fixture_path: Path
    prompt: str
    requests: tuple[Mapping[str, Any], ...]
    media_paths: tuple[Path, ...]


@dataclass(frozen=True, slots=True)
class ImportBusinessAgentOutcome:
    scenario_id: str
    version: str
    status: str
    reason: str
    thread_id: str
    gates: Mapping[str, bool]
    command_count: int
    transaction_count: int
    production_gateway: bool
    wwise_started: bool
    final_response: str

    @property
    def passed(self) -> bool:
        return self.status == "PASS"

    def as_dict(self) -> dict[str, Any]:
        return {"contract": OUTCOME_CONTRACT, **asdict(self)}


def _business_protocol_is_exact(
    broker_evidence: Any,
    reconciliation: Any,
) -> bool:
    """Trust the Broker's dependency-aware ordering proof exactly once."""

    return bool(broker_evidence.passed and reconciliation.passed)


def _final_response_reports_preview(
    final_response: str,
    *,
    markers: Sequence[str],
) -> bool:
    """Accept a semantic prose summary or the exact machine Preview payload."""

    normalized = final_response.translate(_REPORT_MINUS_TRANSLATION).casefold()
    normalized_markers = tuple(
        marker.translate(_REPORT_MINUS_TRANSLATION).casefold()
        for marker in markers
    )
    if any(marker in normalized for marker in normalized_markers) and (
        "预览" in normalized or "preview" in normalized
    ):
        return True
    try:
        payload = json.loads(final_response)
    except (json.JSONDecodeError, TypeError):
        return False
    if not isinstance(payload, Mapping):
        return False
    request = payload.get("request")
    return bool(
        payload.get("operation") == "audio.import"
        and payload.get("state") == "awaiting_confirmation"
        and payload.get("executed") is False
        and isinstance(request, Mapping)
        and request.get("contract") == "waapi-skill.operation-request/v1"
        and request.get("operation") == "audio.import"
    )


def prepare_import_business_runtime(
    unit: ImportBusinessUnit,
    root: str | Path,
) -> ImportBusinessRuntime:
    runtime_root = Path(root).expanduser().resolve(strict=False)
    runtime_root.mkdir(parents=True, exist_ok=False)
    media_root = runtime_root / "media"
    media_root.mkdir()
    media_names = tuple(sorted(_media_names(unit.transactions)))
    media_paths = tuple(media_root / name for name in media_names)
    for path in media_paths:
        _write_silent_wav(path)
    requests = reconstruct_import_business_requests(
        unit,
        runtime_root,
        require_media_files=True,
    )
    project_path = runtime_root / "project" / "SemanticProject.wproj"
    project_path.parent.mkdir()
    for name in ("Originals", "GeneratedSoundBanks", "Commands", ".cache"):
        (project_path.parent / name).mkdir()
    project_path.write_text("<?xml version=\"1.0\" encoding=\"utf-8\"?>\n", encoding="utf-8")
    fixture_path = runtime_root / "waapi-fixture.json"
    fixture_path.write_text(
        json.dumps(
            {
                "version": unit.version,
                "platform": "windows" if os.name == "nt" else "macosx",
                "process_path": str(runtime_root / "WwiseConsole"),
                "project_path": str(project_path),
                "objects": [dict(row) for row in unit.objects],
                "fields": [dict(row) for row in unit.fields],
            },
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    prompt_values = {
        **{f"media_{path.stem}": str(path) for path in media_paths},
        **{f"path_{row['role']}": str(row["path"]) for row in unit.objects},
    }
    try:
        prompt = unit.prompt_template.format_map(prompt_values)
    except KeyError as exc:
        raise ValueError(f"audio import business prompt placeholder is unresolved: {exc}") from exc
    return ImportBusinessRuntime(
        fixture_path=fixture_path,
        prompt=prompt,
        requests=requests,
        media_paths=media_paths,
    )


def reconstruct_import_business_requests(
    unit: ImportBusinessUnit,
    runtime_root: Path,
    *,
    require_media_files: bool,
) -> tuple[Mapping[str, Any], ...]:
    """Rebuild exact requests from one sealed unit and its fixed runtime paths."""

    media_root = Path(runtime_root) / "media"
    media_paths = tuple(
        media_root / name for name in sorted(_media_names(unit.transactions))
    )
    if require_media_files and any(
        not path.is_file() or path.is_symlink() for path in media_paths
    ):
        raise ValueError("audio import business runtime media evidence is incomplete")
    media_by_name = {path.name: path for path in media_paths}
    return tuple(
        {
            "contract": "waapi-skill.operation-request/v1",
            "version": unit.version,
            "operation": "audio.import",
            "arguments": _resolve_media_tokens(
                transaction["arguments"],
                media_by_name,
            ),
        }
        for transaction in unit.transactions
    )


def build_preview_only_business_steps(
    requests: Sequence[Mapping[str, Any]],
) -> tuple[Any, ...]:
    steps: list[Any] = []
    for index, request in enumerate(requests, start=1):
        transaction_steps = build_audio_import_composer_transaction_steps(
            request,
            label=f"tx{index:02d}",
        )
        preview_index = next(
            position
            for position, step in enumerate(transaction_steps)
            if step.subcommand == "preview-from-draft"
        )
        steps.extend(transaction_steps[: preview_index + 1])
    return tuple(steps)


def run_import_business_agent_unit(
    unit: ImportBusinessUnit,
    *,
    scenario_root: Path,
    options: ImportBusinessAgentOptions,
) -> ImportBusinessAgentOutcome:
    return run_business_agent_unit(
        unit,
        scenario_root=scenario_root,
        options=options,
        spec=BusinessAgentRunSpec(
            prepare_runtime=prepare_import_business_runtime,
            build_steps=lambda runtime: build_preview_only_business_steps(
                runtime.requests
            ),
            transaction_count=lambda runtime: len(runtime.requests),
            preview_gates=_audio_preview_gates,
            outcome_factory=ImportBusinessAgentOutcome,
        ),
    )


def _audio_preview_gates(
    unit: ImportBusinessUnit,
    runtime: ImportBusinessRuntime,
    result: Any,
    broker_evidence: Any,
) -> Mapping[str, bool]:
    preview_count = sum(
        record.step_name is not None and record.step_name.endswith(".preview")
        for record in broker_evidence.records
    )
    return {
        "all_previews_reported": preview_count == len(runtime.requests)
        and _final_response_reports_preview(
            result.final_response,
            markers=unit.final_markers,
        )
    }


def _media_names(transactions: Sequence[Mapping[str, Any]]) -> set[str]:
    names: set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, Mapping):
            for nested in value.values():
                visit(nested)
        elif isinstance(value, (list, tuple)):
            for nested in value:
                visit(nested)
        elif isinstance(value, str) and value.startswith("media://"):
            name = value.removeprefix("media://")
            if not name or "/" in name or "\\" in name:
                raise ValueError("audio import business media token is invalid")
            names.add(name)

    visit(transactions)
    return names


def _resolve_media_tokens(value: Any, media_by_name: Mapping[str, Path]) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _resolve_media_tokens(nested, media_by_name) for key, nested in value.items()}
    if isinstance(value, list):
        return [_resolve_media_tokens(nested, media_by_name) for nested in value]
    if isinstance(value, str) and value.startswith("media://"):
        return str(media_by_name[value.removeprefix("media://")])
    return value


def _write_silent_wav(path: Path) -> None:
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(48000)
        stream.writeframes(b"\x00\x00" * 32)


__all__ = [
    "ImportBusinessAgentOptions",
    "ImportBusinessAgentOutcome",
    "ImportBusinessRuntime",
    "OUTCOME_CONTRACT",
    "build_preview_only_business_steps",
    "prepare_import_business_runtime",
    "reconstruct_import_business_requests",
    "run_import_business_agent_unit",
]
