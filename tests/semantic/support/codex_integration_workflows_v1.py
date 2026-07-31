"""Closed loader for the six-unit cross-version integration-workflow profile.

The reviewed data describes three multi-turn business workflows for Wwise
2022.1 and 2025.1.  This module intentionally stops at loading and validating
that data: it does not register a campaign profile, create project sandboxes,
start Codex or Wwise, or execute any transaction.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import string
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


PROFILE_CONTRACT = "waapi-skill.codex-integration-workflows-profile/v1"
CASE_FILE_CONTRACT = "waapi-skill.codex-integration-workflow-cases/v1"
PROFILE_ID = "integration_workflows_cross_version_6"
DATA_FILE_NAMES = ("workflows.json",)
VERSIONS = ("2022.1", "2025.1")
WORKFLOW_IDS = (
    "interactive_weather_build",
    "alarm_diagnose_and_repair",
    "harbor_soundbank_release",
)
LOGICAL_WORKFLOW_COUNT = 3
TASK_COUNT = 6
TRANSACTION_COUNT = 12
USER_TURN_COUNT = 20

EXPECTED_TRANSACTION_SPECS = {
    "interactive_weather_build": (
        ("audio.import", "ak.wwise.core.audio.import", 1, 2),
        ("object.set", "ak.wwise.core.object.set", 2, 3),
        ("object.setRTPC", "ak.wwise.core.object.set", 3, 4),
    ),
    "alarm_diagnose_and_repair": (
        (
            "object.setReference",
            "ak.wwise.core.object.setReference",
            2,
            3,
        ),
    ),
    "harbor_soundbank_release": (
        (
            "soundbank.setInclusions",
            "ak.wwise.core.soundbank.setInclusions",
            1,
            2,
        ),
        (
            "soundbank.generate",
            "ak.wwise.core.soundbank.generate",
            2,
            3,
        ),
    ),
}
EXPECTED_TURN_KINDS = {
    "interactive_weather_build": (
        "request",
        "confirmation",
        "confirmation",
        "confirmation",
    ),
    "alarm_diagnose_and_repair": (
        "diagnosis_request",
        "change_request",
        "confirmation",
    ),
    "harbor_soundbank_release": (
        "request",
        "confirmation",
        "confirmation",
    ),
}
EXPECTED_ADAPTERS = {
    "interactive_weather_build": "interactive_weather_fixture_v1",
    "alarm_diagnose_and_repair": "alarm_reference_fixture_v1",
    "harbor_soundbank_release": "harbor_soundbank_fixture_v1",
}
EXPECTED_VISIBLE_INPUTS = {
    "interactive_weather_build": (
        "weather_source_directory",
        "weather_root_path",
        "weather_event_root_path",
        "weather_game_parameter_path",
        "weather_bus_path",
    ),
    "alarm_diagnose_and_repair": (
        "alarm_event_path",
        "alarm_target_bus_path",
    ),
    "harbor_soundbank_release": (
        "harbor_bank_name",
        "harbor_event_paths",
        "soundbank_output_directory",
        "soundbank_io_root",
    ),
}
EXPECTED_PRIMARY_API = {
    "interactive_weather_build": "ak.wwise.core.audio.import",
    "alarm_diagnose_and_repair": "ak.wwise.core.object.setReference",
    "harbor_soundbank_release": "ak.wwise.core.soundbank.generate",
}

_EXPECTED_TOTALS = {
    "logical_workflow_count": LOGICAL_WORKFLOW_COUNT,
    "task_count": TASK_COUNT,
    "transaction_count": TRANSACTION_COUNT,
    "user_turn_count": USER_TURN_COUNT,
}
_PROFILE_KEYS = {
    "contract",
    "profile_id",
    "data_files",
    "versions",
    "totals",
}
_WORKFLOW_KEYS = {
    "id",
    "versions",
    "visible_inputs",
    "turns",
    "transactions",
    "fixture",
}
_VISIBLE_INPUT_KEYS = {"name", "kind", "description"}
_TURN_KEYS = {
    "index",
    "kind",
    "prompt",
    "confirms_transaction",
    "expects_preview_transaction",
}
_TRANSACTION_KEYS = {
    "index",
    "operation",
    "api",
    "preview_turn",
    "confirmation_turn",
}
_FIXTURE_KEYS = {"adapter", "visible_bindings", "parameters", "cleanup"}
_CLEANUP = {
    "success": "remove_scenario_owned_project_assets_and_outputs",
    "failure": "seal_owned_state_never_reuse",
    "source_project": "must_remain_unchanged",
}
_VISIBLE_INPUT_KINDS = {
    "absolute_directory_path",
    "object_path",
    "string",
    "structured_array",
}
_VISIBLE_INPUT_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_UNIT_ID_RE = re.compile(r"^INT(?:22|25)-[A-Z0-9]+(?:-[A-Z0-9]+)*$")
_PROMPT_FORBIDDEN = (
    re.compile(r"\b(?:skill|gateway|harness|runner|fixture|sandbox|oracle)\b", re.I),
    re.compile(r"\b(?:eval|benchmark|test case)\b", re.I),
    re.compile(r"operation-schema", re.I),
    re.compile(r"run\.py", re.I),
    re.compile(r"\bak\.(?:wwise|soundengine)\.", re.I),
    re.compile(r"测试"),
    re.compile(r"沙箱"),
    re.compile(r"边界"),
)


class IntegrationWorkflowProfileError(ValueError):
    """The integration-workflow profile or its data is invalid."""


@dataclass(frozen=True, slots=True)
class IntegrationVisibleInput:
    name: str
    kind: str
    description: str


@dataclass(frozen=True, slots=True)
class IntegrationWorkflowTurn:
    index: int
    kind: str
    prompt: str
    confirms_transaction: int | None
    expects_preview_transaction: int | None


@dataclass(frozen=True, slots=True)
class IntegrationWorkflowTransaction:
    index: int
    operation: str
    api: str
    preview_turn: int
    confirmation_turn: int


@dataclass(frozen=True, slots=True)
class IntegrationWorkflowFixture:
    adapter: str
    visible_bindings: Mapping[str, Any]
    parameters: Mapping[str, Any]
    cleanup: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class IntegrationPrimaryDispatch:
    api: str
    count: int
    effect: str


@dataclass(frozen=True, slots=True)
class IntegrationScenarioProxy:
    """Minimal frozen scenario view for the existing read-only runner seam."""

    id: str
    api: str
    item_type: str
    versions: tuple[str, ...]
    lane: str
    scenario_family: str
    scenario_index: int
    prompt: str
    visible_inputs: tuple[IntegrationVisibleInput, ...]
    fixture: Mapping[str, Any]
    primary_dispatch: IntegrationPrimaryDispatch
    confirmation_prompt: str
    confirmation_turn_count: int
    follow_up_prompts: tuple[str, ...]
    protocol: str = "preview_confirm"

    @property
    def expected_dispatches(self) -> tuple[IntegrationPrimaryDispatch, ...]:
        return (self.primary_dispatch,)

    @property
    def prompt_sha256(self) -> str:
        return hashlib.sha256(self.prompt.encode("utf-8")).hexdigest()

    def render_prompt(self, values: Mapping[str, Any]) -> str:
        expected = {item.name for item in self.visible_inputs}
        actual = set(values)
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        if missing or unknown:
            raise IntegrationWorkflowProfileError(
                f"{self.id} visible prompt input mismatch; "
                f"missing={missing}, unknown={unknown}"
            )
        rendered = self.prompt.format_map(
            {
                key: (
                    json.dumps(value, ensure_ascii=False)
                    if isinstance(value, (list, dict))
                    else str(value)
                )
                for key, value in values.items()
            }
        )
        # The frozen template was already linted at profile load.  Dynamic
        # values are independently type/provenance bound and may legitimately
        # contain infrastructure-looking path segments such as "sandbox".
        # Re-linting the substituted text would confuse those values with
        # model-facing test coaching.
        return rendered


@dataclass(frozen=True, slots=True)
class IntegrationWorkflowCase:
    id: str
    versions: tuple[str, ...]
    visible_inputs: tuple[IntegrationVisibleInput, ...]
    turns: tuple[IntegrationWorkflowTurn, ...]
    transactions: tuple[IntegrationWorkflowTransaction, ...]
    fixture: IntegrationWorkflowFixture
    source_file: str


@dataclass(frozen=True, slots=True)
class IntegrationWorkflowUnit:
    unit_id: str
    workflow: IntegrationWorkflowCase
    version: str
    scenario: IntegrationScenarioProxy

    @property
    def workflow_id(self) -> str:
        return self.workflow.id

    @property
    def turns(self) -> tuple[IntegrationWorkflowTurn, ...]:
        return self.workflow.turns

    @property
    def transactions(self) -> tuple[IntegrationWorkflowTransaction, ...]:
        return self.workflow.transactions

    @property
    def transaction_count(self) -> int:
        return len(self.transactions)

    @property
    def user_turn_count(self) -> int:
        return len(self.turns)


@dataclass(frozen=True, slots=True)
class IntegrationWorkflowProfile:
    path: Path
    data_paths: tuple[Path, ...]
    source_digests: tuple[tuple[str, str], ...]
    definition_sha256: str
    workflows: tuple[IntegrationWorkflowCase, ...]
    units: tuple[IntegrationWorkflowUnit, ...]


def load_integration_workflows_profile(
    path: str | Path,
    *,
    unit_ids: Sequence[str] = (),
    versions: Sequence[str] = (),
) -> IntegrationWorkflowProfile:
    """Load and fully validate the three workflows before optional filtering."""

    profile_path = _resolve_regular_file(path, "integration profile")
    root, profile_digest = _load_json(profile_path, "integration profile")
    if set(root) != _PROFILE_KEYS:
        raise IntegrationWorkflowProfileError(
            "integration profile schema is not closed"
        )
    if (
        root.get("contract") != PROFILE_CONTRACT
        or root.get("profile_id") != PROFILE_ID
    ):
        raise IntegrationWorkflowProfileError(
            "integration profile identity drifted"
        )
    if _string_tuple(root.get("versions"), "profile.versions") != VERSIONS:
        raise IntegrationWorkflowProfileError(
            "integration profile versions drifted"
        )
    _validate_totals(root.get("totals"))

    file_names = _string_tuple(root.get("data_files"), "profile.data_files")
    if file_names != DATA_FILE_NAMES:
        raise IntegrationWorkflowProfileError(
            "integration profile data_files order or identity drifted"
        )
    data_paths = tuple(
        _resolve_sibling_json(profile_path, name) for name in file_names
    )

    workflows: list[IntegrationWorkflowCase] = []
    source_digests: list[tuple[str, str]] = [
        (profile_path.name, profile_digest)
    ]
    for file_name, data_path in zip(file_names, data_paths, strict=True):
        data_root, data_digest = _load_json(
            data_path,
            f"integration data file {file_name}",
        )
        source_digests.append((file_name, data_digest))
        if set(data_root) != {"contract", "workflows"}:
            raise IntegrationWorkflowProfileError(
                f"{file_name} data-file schema is not closed"
            )
        if data_root.get("contract") != CASE_FILE_CONTRACT:
            raise IntegrationWorkflowProfileError(
                f"{file_name} contract drifted"
            )
        rows = data_root.get("workflows")
        if not isinstance(rows, list):
            raise IntegrationWorkflowProfileError(
                f"{file_name}.workflows must be a JSON array"
            )
        workflows.extend(
            _parse_workflow(row, source_file=file_name, index=index)
            for index, row in enumerate(rows)
        )

    complete_workflows = tuple(workflows)
    _validate_complete_workflows(complete_workflows)
    complete_units = tuple(
        _build_unit(workflow, version)
        for version in VERSIONS
        for workflow in complete_workflows
    )
    _validate_complete_units(complete_units)

    requested_ids = _unique_strings(unit_ids, "unit ids")
    requested_versions = _unique_strings(versions, "versions")
    known_ids = {unit.unit_id for unit in complete_units}
    unknown_ids = sorted(set(requested_ids) - known_ids)
    if unknown_ids:
        raise IntegrationWorkflowProfileError(
            "unknown integration unit ids: " + ", ".join(unknown_ids)
        )
    unknown_versions = sorted(set(requested_versions) - set(VERSIONS))
    if unknown_versions:
        raise IntegrationWorkflowProfileError(
            "integration profile has no units for versions: "
            + ", ".join(unknown_versions)
        )
    selected = tuple(
        unit
        for unit in complete_units
        if (not requested_ids or unit.unit_id in requested_ids)
        and (not requested_versions or unit.version in requested_versions)
    )
    if not selected:
        raise IntegrationWorkflowProfileError(
            "no integration units matched the requested filters"
        )

    frozen_digests = tuple(source_digests)
    definition_sha256 = hashlib.sha256(
        "\n".join(
            f"{name}\0{digest}" for name, digest in frozen_digests
        ).encode("utf-8")
    ).hexdigest()
    return IntegrationWorkflowProfile(
        path=profile_path,
        data_paths=data_paths,
        source_digests=frozen_digests,
        definition_sha256=definition_sha256,
        workflows=complete_workflows,
        units=selected,
    )


def _parse_workflow(
    value: Any,
    *,
    source_file: str,
    index: int,
) -> IntegrationWorkflowCase:
    path = f"{source_file}.workflows[{index}]"
    if not isinstance(value, dict) or set(value) != _WORKFLOW_KEYS:
        raise IntegrationWorkflowProfileError(
            f"{path} schema is not closed"
        )
    workflow_id = _nonempty_string(value.get("id"), f"{path}.id")
    if workflow_id not in WORKFLOW_IDS:
        raise IntegrationWorkflowProfileError(
            f"{path}.id is not a reviewed integration workflow"
        )
    workflow_versions = _string_tuple(
        value.get("versions"),
        f"{path}.versions",
    )
    if workflow_versions != VERSIONS:
        raise IntegrationWorkflowProfileError(
            f"{path}.versions must be exactly {list(VERSIONS)}"
        )

    raw_inputs = value.get("visible_inputs")
    if not isinstance(raw_inputs, list) or not raw_inputs:
        raise IntegrationWorkflowProfileError(
            f"{path}.visible_inputs must be a non-empty JSON array"
        )
    visible_inputs = tuple(
        _parse_visible_input(row, f"{path}.visible_inputs[{row_index}]")
        for row_index, row in enumerate(raw_inputs)
    )
    input_names = tuple(item.name for item in visible_inputs)
    if input_names != EXPECTED_VISIBLE_INPUTS[workflow_id]:
        raise IntegrationWorkflowProfileError(
            f"{path}.visible_inputs order or identity drifted"
        )

    raw_turns = value.get("turns")
    if not isinstance(raw_turns, list) or not raw_turns:
        raise IntegrationWorkflowProfileError(
            f"{path}.turns must be a non-empty JSON array"
        )
    turns = tuple(
        _parse_turn(
            row,
            f"{path}.turns[{row_index}]",
            declared_inputs=set(input_names),
        )
        for row_index, row in enumerate(raw_turns)
    )
    if tuple(turn.kind for turn in turns) != EXPECTED_TURN_KINDS[workflow_id]:
        raise IntegrationWorkflowProfileError(
            f"{path}.turns topology drifted"
        )
    if tuple(turn.index for turn in turns) != tuple(
        range(1, len(turns) + 1)
    ):
        raise IntegrationWorkflowProfileError(
            f"{path}.turn indices must be contiguous from one"
        )
    first_fields = _prompt_fields(turns[0].prompt, f"{path}.turns[0].prompt")
    if set(first_fields) != set(input_names):
        raise IntegrationWorkflowProfileError(
            f"{path}.turns[0].prompt must use every declared visible input"
        )

    raw_transactions = value.get("transactions")
    if not isinstance(raw_transactions, list) or not raw_transactions:
        raise IntegrationWorkflowProfileError(
            f"{path}.transactions must be a non-empty JSON array"
        )
    transactions = tuple(
        _parse_transaction(
            row,
            f"{path}.transactions[{row_index}]",
        )
        for row_index, row in enumerate(raw_transactions)
    )
    specs = tuple(
        (
            tx.operation,
            tx.api,
            tx.preview_turn,
            tx.confirmation_turn,
        )
        for tx in transactions
    )
    if specs != EXPECTED_TRANSACTION_SPECS[workflow_id]:
        raise IntegrationWorkflowProfileError(
            f"{path}.transactions sequence drifted"
        )
    if tuple(tx.index for tx in transactions) != tuple(
        range(1, len(transactions) + 1)
    ):
        raise IntegrationWorkflowProfileError(
            f"{path}.transaction indices must be contiguous from one"
        )
    _validate_turn_transaction_links(turns, transactions, path)

    fixture = _parse_fixture(
        value.get("fixture"),
        f"{path}.fixture",
        workflow_id=workflow_id,
        visible_inputs=visible_inputs,
    )
    return IntegrationWorkflowCase(
        id=workflow_id,
        versions=workflow_versions,
        visible_inputs=visible_inputs,
        turns=turns,
        transactions=transactions,
        fixture=fixture,
        source_file=source_file,
    )


def _parse_visible_input(value: Any, path: str) -> IntegrationVisibleInput:
    if not isinstance(value, dict) or set(value) != _VISIBLE_INPUT_KEYS:
        raise IntegrationWorkflowProfileError(f"{path} schema is not closed")
    name = _nonempty_string(value.get("name"), f"{path}.name")
    if _VISIBLE_INPUT_RE.fullmatch(name) is None:
        raise IntegrationWorkflowProfileError(
            f"{path}.name is not a valid visible-input name"
        )
    kind = _nonempty_string(value.get("kind"), f"{path}.kind")
    if kind not in _VISIBLE_INPUT_KINDS:
        raise IntegrationWorkflowProfileError(
            f"{path}.kind is not supported"
        )
    return IntegrationVisibleInput(
        name=name,
        kind=kind,
        description=_nonempty_string(
            value.get("description"),
            f"{path}.description",
        ),
    )


def _parse_turn(
    value: Any,
    path: str,
    *,
    declared_inputs: set[str],
) -> IntegrationWorkflowTurn:
    if not isinstance(value, dict) or set(value) != _TURN_KEYS:
        raise IntegrationWorkflowProfileError(f"{path} schema is not closed")
    prompt = _nonempty_string(value.get("prompt"), f"{path}.prompt")
    _lint_natural_prompt(prompt, f"{path}.prompt")
    fields = _prompt_fields(prompt, f"{path}.prompt")
    unknown = sorted(set(fields) - declared_inputs)
    if unknown:
        raise IntegrationWorkflowProfileError(
            f"{path}.prompt uses undeclared visible inputs: {unknown}"
        )
    return IntegrationWorkflowTurn(
        index=_positive_integer(value.get("index"), f"{path}.index"),
        kind=_nonempty_string(value.get("kind"), f"{path}.kind"),
        prompt=prompt,
        confirms_transaction=_optional_positive_integer(
            value.get("confirms_transaction"),
            f"{path}.confirms_transaction",
        ),
        expects_preview_transaction=_optional_positive_integer(
            value.get("expects_preview_transaction"),
            f"{path}.expects_preview_transaction",
        ),
    )


def _parse_transaction(
    value: Any,
    path: str,
) -> IntegrationWorkflowTransaction:
    if not isinstance(value, dict) or set(value) != _TRANSACTION_KEYS:
        raise IntegrationWorkflowProfileError(f"{path} schema is not closed")
    return IntegrationWorkflowTransaction(
        index=_positive_integer(value.get("index"), f"{path}.index"),
        operation=_nonempty_string(
            value.get("operation"),
            f"{path}.operation",
        ),
        api=_nonempty_string(value.get("api"), f"{path}.api"),
        preview_turn=_positive_integer(
            value.get("preview_turn"),
            f"{path}.preview_turn",
        ),
        confirmation_turn=_positive_integer(
            value.get("confirmation_turn"),
            f"{path}.confirmation_turn",
        ),
    )


def _parse_fixture(
    value: Any,
    path: str,
    *,
    workflow_id: str,
    visible_inputs: Sequence[IntegrationVisibleInput],
) -> IntegrationWorkflowFixture:
    if not isinstance(value, dict) or set(value) != _FIXTURE_KEYS:
        raise IntegrationWorkflowProfileError(f"{path} schema is not closed")
    adapter = _nonempty_string(value.get("adapter"), f"{path}.adapter")
    if adapter != EXPECTED_ADAPTERS[workflow_id]:
        raise IntegrationWorkflowProfileError(f"{path}.adapter drifted")

    bindings = value.get("visible_bindings")
    if not isinstance(bindings, dict):
        raise IntegrationWorkflowProfileError(
            f"{path}.visible_bindings must be a JSON object"
        )
    expected_names = {item.name for item in visible_inputs}
    if set(bindings) != expected_names:
        raise IntegrationWorkflowProfileError(
            f"{path}.visible_bindings must exactly cover visible inputs"
        )
    kinds = {item.name: item.kind for item in visible_inputs}
    for name, binding in bindings.items():
        _validate_visible_binding(
            binding,
            f"{path}.visible_bindings.{name}",
            kind=kinds[name],
        )

    parameters = value.get("parameters")
    if not isinstance(parameters, dict) or not parameters:
        raise IntegrationWorkflowProfileError(
            f"{path}.parameters must be a non-empty JSON object"
        )
    cleanup = value.get("cleanup")
    if not isinstance(cleanup, dict) or cleanup != _CLEANUP:
        raise IntegrationWorkflowProfileError(
            f"{path}.cleanup contract drifted"
        )
    _validate_fixture_parameters(
        workflow_id,
        bindings,
        parameters,
        f"{path}.parameters",
    )
    return IntegrationWorkflowFixture(
        adapter=adapter,
        visible_bindings=copy.deepcopy(bindings),
        parameters=copy.deepcopy(parameters),
        cleanup=copy.deepcopy(cleanup),
    )


def _validate_turn_transaction_links(
    turns: Sequence[IntegrationWorkflowTurn],
    transactions: Sequence[IntegrationWorkflowTransaction],
    path: str,
) -> None:
    by_turn = {turn.index: turn for turn in turns}
    previews: list[int] = []
    confirmations: list[int] = []
    for transaction in transactions:
        preview = by_turn.get(transaction.preview_turn)
        confirmation = by_turn.get(transaction.confirmation_turn)
        if preview is None or confirmation is None:
            raise IntegrationWorkflowProfileError(
                f"{path} transaction refers to an unknown turn"
            )
        if transaction.preview_turn >= transaction.confirmation_turn:
            raise IntegrationWorkflowProfileError(
                f"{path} transaction confirmation must follow its preview"
            )
        if preview.expects_preview_transaction != transaction.index:
            raise IntegrationWorkflowProfileError(
                f"{path} preview-to-transaction link drifted"
            )
        if (
            confirmation.kind != "confirmation"
            or confirmation.confirms_transaction != transaction.index
        ):
            raise IntegrationWorkflowProfileError(
                f"{path} confirmation-to-transaction link drifted"
            )
        previews.append(transaction.index)
        confirmations.append(transaction.index)

    turn_previews = [
        turn.expects_preview_transaction
        for turn in turns
        if turn.expects_preview_transaction is not None
    ]
    turn_confirmations = [
        turn.confirms_transaction
        for turn in turns
        if turn.confirms_transaction is not None
    ]
    expected = list(range(1, len(transactions) + 1))
    if (
        previews != expected
        or confirmations != expected
        or sorted(turn_previews) != expected
        or sorted(turn_confirmations) != expected
    ):
        raise IntegrationWorkflowProfileError(
            f"{path} must reference every transaction exactly once"
        )


def _validate_visible_binding(value: Any, path: str, *, kind: str) -> None:
    if not isinstance(value, dict):
        raise IntegrationWorkflowProfileError(f"{path} must be a JSON object")
    source = value.get("source")
    if source == "owned_path":
        if set(value) != {"source", "relative_path"}:
            raise IntegrationWorkflowProfileError(
                f"{path} owned-path schema is not closed"
            )
        if kind != "absolute_directory_path":
            raise IntegrationWorkflowProfileError(
                f"{path} owned paths require an absolute-path input kind"
            )
        relative = Path(
            _nonempty_string(
                value.get("relative_path"),
                f"{path}.relative_path",
            )
        )
        if (
            relative.is_absolute()
            or not relative.parts
            or ".." in relative.parts
        ):
            raise IntegrationWorkflowProfileError(
                f"{path}.relative_path must stay under the owned root"
            )
        return
    if source == "owned_root":
        if set(value) != {"source"}:
            raise IntegrationWorkflowProfileError(
                f"{path} owned-root schema is not closed"
            )
        if kind != "absolute_directory_path":
            raise IntegrationWorkflowProfileError(
                f"{path} owned roots require an absolute-directory input kind"
            )
        return
    if source == "literal":
        if set(value) != {"source", "value"}:
            raise IntegrationWorkflowProfileError(
                f"{path} literal schema is not closed"
            )
        literal = value.get("value")
        if kind == "structured_array":
            if not isinstance(literal, list) or not literal:
                raise IntegrationWorkflowProfileError(
                    f"{path}.value must be a non-empty JSON array"
                )
        elif not isinstance(literal, str) or not literal.strip():
            raise IntegrationWorkflowProfileError(
                f"{path}.value must be a non-empty string"
            )
        return
    raise IntegrationWorkflowProfileError(
        f"{path}.source must be literal, owned_path, or owned_root"
    )


def _validate_fixture_parameters(
    workflow_id: str,
    bindings: Mapping[str, Any],
    parameters: Mapping[str, Any],
    path: str,
) -> None:
    if workflow_id == "interactive_weather_build":
        _validate_weather_parameters(bindings, parameters, path)
    elif workflow_id == "alarm_diagnose_and_repair":
        _validate_alarm_parameters(bindings, parameters, path)
    elif workflow_id == "harbor_soundbank_release":
        _validate_harbor_parameters(bindings, parameters, path)
    else:  # pragma: no cover - workflow identity is checked earlier
        raise IntegrationWorkflowProfileError(
            f"{path} has no reviewed fixture contract"
        )


def _validate_weather_parameters(
    bindings: Mapping[str, Any],
    value: Mapping[str, Any],
    path: str,
) -> None:
    expected = {
        "source_files",
        "import_rows",
        "action_updates",
        "rtpc",
        "protected_paths",
    }
    if set(value) != expected:
        raise IntegrationWorkflowProfileError(
            f"{path} weather schema is not closed"
        )
    sources = value.get("source_files")
    imports = value.get("import_rows")
    if (
        not isinstance(sources, list)
        or len(sources) != 5
        or not isinstance(imports, list)
        or len(imports) != 5
    ):
        raise IntegrationWorkflowProfileError(
            f"{path} requires five source files and five import rows"
        )
    source_keys: list[str] = []
    for index, source in enumerate(sources):
        source_path = f"{path}.source_files[{index}]"
        if not isinstance(source, dict) or set(source) != {
            "key",
            "file_name",
            "duration_ms",
            "frequency_hz",
        }:
            raise IntegrationWorkflowProfileError(
                f"{source_path} schema is not closed"
            )
        source_keys.append(
            _nonempty_string(source.get("key"), f"{source_path}.key")
        )
        if not _nonempty_string(
            source.get("file_name"),
            f"{source_path}.file_name",
        ).lower().endswith(".wav"):
            raise IntegrationWorkflowProfileError(
                f"{source_path}.file_name must be a WAV filename"
            )
        _positive_integer(source.get("duration_ms"), f"{source_path}.duration_ms")
        _positive_integer(
            source.get("frequency_hz"),
            f"{source_path}.frequency_hz",
        )
    if source_keys != [
        "rain_bed",
        "wind_bed",
        "thunder_near",
        "thunder_mid",
        "thunder_far",
    ]:
        raise IntegrationWorkflowProfileError(
            f"{path}.source_files order or identity drifted"
        )
    imported_keys: list[str] = []
    event_names: list[str] = []
    bus_path = "{weather_bus_path}"
    required_properties = {
        "IsLoopingEnabled",
        "IsLoopingInfinite",
        "IgnoreParentMaxSoundInstance",
        "UseMaxSoundPerInstance",
        "MaxSoundPerInstance",
        "Volume",
    }
    for index, row in enumerate(imports):
        row_path = f"{path}.import_rows[{index}]"
        if not isinstance(row, dict) or set(row) != {
            "source_key",
            "object_path",
            "event_name",
            "properties",
            "references",
        }:
            raise IntegrationWorkflowProfileError(
                f"{row_path} schema is not closed"
            )
        imported_keys.append(
            _nonempty_string(row.get("source_key"), f"{row_path}.source_key")
        )
        object_path = _nonempty_string(
            row.get("object_path"),
            f"{row_path}.object_path",
        )
        if "<Sound>" not in object_path:
            raise IntegrationWorkflowProfileError(
                f"{row_path}.object_path must create a Sound"
            )
        event_names.append(
            _nonempty_string(
                row.get("event_name"),
                f"{row_path}.event_name",
            )
        )
        properties = row.get("properties")
        if (
            not isinstance(properties, dict)
            or set(properties) != required_properties
            or properties.get("IsLoopingEnabled") is not True
            or properties.get("IsLoopingInfinite") is not True
            or properties.get("IgnoreParentMaxSoundInstance") is not True
            or properties.get("UseMaxSoundPerInstance") is not True
            or not isinstance(properties.get("MaxSoundPerInstance"), int)
            or isinstance(properties.get("MaxSoundPerInstance"), bool)
            or properties["MaxSoundPerInstance"] <= 0
            or not isinstance(properties.get("Volume"), (int, float))
            or isinstance(properties.get("Volume"), bool)
        ):
            raise IntegrationWorkflowProfileError(
                f"{row_path}.properties must close looping, volume, and "
                "instance-limit semantics"
            )
        references = row.get("references")
        if references != {"OutputBus": bus_path}:
            raise IntegrationWorkflowProfileError(
                f"{row_path}.references must target Weather_Bus"
            )
    if imported_keys != source_keys:
        raise IntegrationWorkflowProfileError(
            f"{path}.import_rows must reference each source in order"
        )
    expected_events = [
        "Play_Rain_Bed",
        "Play_Wind_Bed",
        "Play_Thunder_Near",
        "Play_Thunder_Mid",
        "Play_Thunder_Far",
    ]
    if event_names != expected_events:
        raise IntegrationWorkflowProfileError(
            f"{path}.import_rows must create the five reviewed Play Events"
        )

    action_updates = value.get("action_updates")
    if not isinstance(action_updates, list) or len(action_updates) != 5:
        raise IntegrationWorkflowProfileError(
            f"{path}.action_updates requires five Action rows"
        )
    action_events: list[str] = []
    for index, update in enumerate(action_updates):
        update_path = f"{path}.action_updates[{index}]"
        if (
            not isinstance(update, dict)
            or set(update) != {"event_name", "object", "properties"}
        ):
            raise IntegrationWorkflowProfileError(
                f"{update_path} schema is not closed"
            )
        event_name = _nonempty_string(
            update.get("event_name"),
            f"{update_path}.event_name",
        )
        action_events.append(event_name)
        expected_object = {
            "kind": "direct-child",
            "parent": {
                "kind": "path",
                "value": (
                    bindings["weather_event_root_path"]["value"]
                    + "\\"
                    + event_name
                ),
            },
            "type": "Action",
        }
        if update.get("object") != expected_object:
            raise IntegrationWorkflowProfileError(
                f"{update_path}.object must be the exact direct Action child"
            )
        properties = update.get("properties")
        if (
            not isinstance(properties, dict)
            or set(properties) != {"FadeTime", "Delay"}
            or any(
                not isinstance(properties[name], (int, float))
                or isinstance(properties[name], bool)
                or properties[name] < 0
                for name in ("FadeTime", "Delay")
            )
        ):
            raise IntegrationWorkflowProfileError(
                f"{update_path}.properties must set FadeTime and Delay"
            )
    if action_events != expected_events:
        raise IntegrationWorkflowProfileError(
            f"{path}.action_updates must cover all five Play Events in order"
        )

    rtpc = value.get("rtpc")
    if (
        not isinstance(rtpc, dict)
        or set(rtpc) != {
            "object_path",
            "property",
            "control_input_path",
            "mode",
            "points",
        }
        or rtpc.get("object_path")
        != "Weather_Interactive\\Rain\\Rain_Bed"
        or rtpc.get("property") != "Volume"
        or rtpc.get("mode") != "add_or_replace"
        or rtpc.get("control_input_path")
        != bindings["weather_game_parameter_path"]["value"]
        or not isinstance(rtpc.get("points"), list)
        or len(rtpc["points"]) != 3
    ):
        raise IntegrationWorkflowProfileError(f"{path}.rtpc contract drifted")
    for index, point in enumerate(rtpc["points"]):
        if (
            not isinstance(point, dict)
            or set(point) != {"x", "y", "shape"}
            or not isinstance(point.get("x"), (int, float))
            or isinstance(point.get("x"), bool)
            or not isinstance(point.get("y"), (int, float))
            or isinstance(point.get("y"), bool)
            or point.get("shape") != "Linear"
        ):
            raise IntegrationWorkflowProfileError(
                f"{path}.rtpc.points[{index}] contract drifted"
            )
    protected_paths = _nonempty_string_list(
        value.get("protected_paths"),
        f"{path}.protected_paths",
    )
    if protected_paths != (
        "{weather_game_parameter_path}",
        "{weather_bus_path}",
    ):
        raise IntegrationWorkflowProfileError(
            f"{path}.protected_paths must bind the two visible protected inputs"
        )


def _validate_alarm_parameters(
    bindings: Mapping[str, Any],
    value: Mapping[str, Any],
    path: str,
) -> None:
    expected = {
        "reference_name",
        "wrong_bus_path",
        "expected_chain",
        "diagnostic_plan",
        "protected_properties",
        "baseline",
    }
    if set(value) != expected:
        raise IntegrationWorkflowProfileError(
            f"{path} alarm schema is not closed"
        )
    if value.get("reference_name") != "OutputBus":
        raise IntegrationWorkflowProfileError(
            f"{path}.reference_name must be OutputBus"
        )
    wrong_bus = _nonempty_string(
        value.get("wrong_bus_path"),
        f"{path}.wrong_bus_path",
    )
    if wrong_bus == bindings["alarm_target_bus_path"]["value"]:
        raise IntegrationWorkflowProfileError(
            f"{path}.wrong_bus_path must differ from the repair target"
        )

    expected_chain = value.get("expected_chain")
    if not isinstance(expected_chain, dict) or set(expected_chain) != {
        "event_path",
        "action_path",
        "sound_path",
        "audio_source_file",
        "current_bus_path",
        "target_bus_path",
    }:
        raise IntegrationWorkflowProfileError(
            f"{path}.expected_chain schema is not closed"
        )
    if (
        expected_chain.get("event_path")
        != bindings["alarm_event_path"]["value"]
        or expected_chain.get("current_bus_path") != wrong_bus
        or expected_chain.get("target_bus_path")
        != bindings["alarm_target_bus_path"]["value"]
        or not _nonempty_string(
            expected_chain.get("action_path"),
            f"{path}.expected_chain.action_path",
        )
        or not _nonempty_string(
            expected_chain.get("sound_path"),
            f"{path}.expected_chain.sound_path",
        )
        or not _nonempty_string(
            expected_chain.get("audio_source_file"),
            f"{path}.expected_chain.audio_source_file",
        ).endswith(".wav")
    ):
        raise IntegrationWorkflowProfileError(
            f"{path}.expected_chain must close Event-to-Bus evidence"
        )

    diagnostic_plan = value.get("diagnostic_plan")
    stages = ("event", "action", "sound", "audio_source", "bus")
    if not isinstance(diagnostic_plan, list) or len(diagnostic_plan) != 5:
        raise IntegrationWorkflowProfileError(
            f"{path}.diagnostic_plan requires five chain stages"
        )
    for index, (row, stage) in enumerate(
        zip(diagnostic_plan, stages, strict=True)
    ):
        row_path = f"{path}.diagnostic_plan[{index}]"
        selector_key = "selector_waql" if stage == "action" else "selector"
        if (
            not isinstance(row, dict)
            or set(row) != {"stage", selector_key, "return_fields"}
            or row.get("stage") != stage
        ):
            raise IntegrationWorkflowProfileError(
                f"{row_path} schema or stage drifted"
            )
        _nonempty_string(row.get(selector_key), f"{row_path}.{selector_key}")
        fields = _nonempty_string_list(
            row.get("return_fields"),
            f"{row_path}.return_fields",
        )
        if not fields:
            raise IntegrationWorkflowProfileError(
                f"{row_path}.return_fields must not be empty"
            )
    if "target" not in diagnostic_plan[1]["return_fields"]:
        raise IntegrationWorkflowProfileError(
            f"{path}.diagnostic_plan Action stage must return its target"
        )
    if not {
        "activeSource",
        "OutputBus",
    }.issubset(diagnostic_plan[2]["return_fields"]):
        raise IntegrationWorkflowProfileError(
            f"{path}.diagnostic_plan Sound stage lacks source or Bus evidence"
        )

    protected = _nonempty_string_list(
        value.get("protected_properties"),
        f"{path}.protected_properties",
    )
    if not {"Volume", "Pitch"}.issubset(protected):
        raise IntegrationWorkflowProfileError(
            f"{path}.protected_properties lacks drift evidence"
        )
    baseline = value.get("baseline")
    if not isinstance(baseline, dict) or set(baseline) != {
        "use_max_sound_per_instance",
        "max_sound_per_instance",
        "volume",
        "pitch",
    }:
        raise IntegrationWorkflowProfileError(
            f"{path}.baseline schema is not closed"
        )


def _validate_harbor_parameters(
    bindings: Mapping[str, Any],
    value: Mapping[str, Any],
    path: str,
) -> None:
    expected = {
        "events",
        "inclusion_filter",
        "remove_event_path",
        "control_bank_name",
        "platforms",
        "languages",
        "artifact_scope",
    }
    if set(value) != expected:
        raise IntegrationWorkflowProfileError(
            f"{path} harbor schema is not closed"
        )
    events = _nonempty_string_list(value.get("events"), f"{path}.events")
    if list(events) != bindings["harbor_event_paths"]["value"]:
        raise IntegrationWorkflowProfileError(
            f"{path}.events must match the visible event list"
        )
    if value.get("inclusion_filter") != ["events", "structures", "media"]:
        raise IntegrationWorkflowProfileError(
            f"{path}.inclusion_filter drifted"
        )
    remove_event_path = _nonempty_string(
        value.get("remove_event_path"),
        f"{path}.remove_event_path",
    )
    if not remove_event_path.endswith("\\Debug"):
        raise IntegrationWorkflowProfileError(
            f"{path}.remove_event_path must target the Debug inclusion"
        )
    if value.get("control_bank_name") == bindings["harbor_bank_name"]["value"]:
        raise IntegrationWorkflowProfileError(
            f"{path}.control_bank_name must differ from the release Bank"
        )
    if value.get("control_bank_name") != "Harbor_Control":
        raise IntegrationWorkflowProfileError(
            f"{path}.control_bank_name must remain Harbor_Control"
        )
    if value.get("platforms") != [
        "Windows",
        "Mac",
    ] or value.get("languages") != ["SFX"]:
        raise IntegrationWorkflowProfileError(
            f"{path} platform or language contract drifted"
        )
    if value.get("artifact_scope") != ["bank", "media"]:
        raise IntegrationWorkflowProfileError(
            f"{path}.artifact_scope must require only stable Bank and media outputs"
        )


def _validate_complete_workflows(
    workflows: Sequence[IntegrationWorkflowCase],
) -> None:
    ids = tuple(workflow.id for workflow in workflows)
    if ids != WORKFLOW_IDS:
        raise IntegrationWorkflowProfileError(
            "integration workflow order or identity drifted"
        )
    if len(ids) != LOGICAL_WORKFLOW_COUNT or len(set(ids)) != len(ids):
        raise IntegrationWorkflowProfileError(
            "integration profile requires three unique logical workflows"
        )
    alarm = workflows[1]
    if (
        alarm.turns[0].kind != "diagnosis_request"
        or alarm.turns[0].confirms_transaction is not None
        or alarm.turns[0].expects_preview_transaction is not None
        or "只读" not in alarm.turns[0].prompt
        or "不要修改" not in alarm.turns[0].prompt
    ):
        raise IntegrationWorkflowProfileError(
            "alarm workflow must begin with a read-only diagnosis"
        )


def _build_unit(
    workflow: IntegrationWorkflowCase,
    version: str,
) -> IntegrationWorkflowUnit:
    unit_id = (
        f"INT{version.split('.', maxsplit=1)[0][-2:]}-"
        f"{workflow.id.replace('_', '-').upper()}"
    )
    if _UNIT_ID_RE.fullmatch(unit_id) is None:
        raise IntegrationWorkflowProfileError(
            f"generated integration unit id is invalid: {unit_id}"
        )
    confirmations = tuple(
        turn.prompt for turn in workflow.turns if turn.kind == "confirmation"
    )
    if not confirmations:
        raise IntegrationWorkflowProfileError(
            f"{workflow.id} has no natural confirmation prompt"
        )
    primary_api = EXPECTED_PRIMARY_API[workflow.id]
    primary_dispatch = IntegrationPrimaryDispatch(
        api=primary_api,
        count=1,
        effect=(
            f"execute the reviewed primary transaction for {workflow.id} "
            "exactly once"
        ),
    )
    scenario_fixture = {
        "adapter": workflow.fixture.adapter,
        "visible_bindings": copy.deepcopy(
            workflow.fixture.visible_bindings
        ),
        "parameters": copy.deepcopy(workflow.fixture.parameters),
        "cleanup": copy.deepcopy(workflow.fixture.cleanup),
    }
    scenario = IntegrationScenarioProxy(
        id=unit_id,
        api=primary_api,
        item_type="function",
        versions=(version,),
        lane="online_authoring",
        scenario_family=workflow.id,
        scenario_index=WORKFLOW_IDS.index(workflow.id) + 1,
        prompt=workflow.turns[0].prompt,
        visible_inputs=workflow.visible_inputs,
        fixture=scenario_fixture,
        primary_dispatch=primary_dispatch,
        confirmation_prompt=confirmations[0],
        confirmation_turn_count=len(workflow.transactions),
        follow_up_prompts=tuple(
            turn.prompt for turn in workflow.turns[1:]
        ),
    )
    return IntegrationWorkflowUnit(
        unit_id=unit_id,
        workflow=workflow,
        version=version,
        scenario=scenario,
    )


def _validate_complete_units(
    units: Sequence[IntegrationWorkflowUnit],
) -> None:
    if len(units) != TASK_COUNT:
        raise IntegrationWorkflowProfileError(
            f"integration profile requires {TASK_COUNT} units"
        )
    ids = tuple(unit.unit_id for unit in units)
    if len(ids) != len(set(ids)):
        raise IntegrationWorkflowProfileError(
            "integration unit ids must be unique"
        )
    version_counts = {
        version: sum(unit.version == version for unit in units)
        for version in VERSIONS
    }
    if version_counts != {
        version: LOGICAL_WORKFLOW_COUNT for version in VERSIONS
    }:
        raise IntegrationWorkflowProfileError(
            f"integration version distribution drifted: {version_counts}"
        )
    if (
        sum(unit.transaction_count for unit in units) != TRANSACTION_COUNT
        or sum(unit.user_turn_count for unit in units) != USER_TURN_COUNT
    ):
        raise IntegrationWorkflowProfileError(
            "integration transaction or user-turn totals drifted"
        )
    for unit in units:
        if (
            unit.scenario.id != unit.unit_id
            or unit.scenario.api
            != EXPECTED_PRIMARY_API[unit.workflow_id]
            or unit.scenario.versions != (unit.version,)
            or unit.scenario.primary_dispatch.count != 1
            or unit.scenario.follow_up_prompts
            != tuple(turn.prompt for turn in unit.turns[1:])
        ):
            raise IntegrationWorkflowProfileError(
                f"{unit.unit_id} lost the fixed scenario compatibility view"
            )


def _validate_totals(value: Any) -> None:
    if not isinstance(value, dict) or set(value) != set(_EXPECTED_TOTALS):
        raise IntegrationWorkflowProfileError(
            "profile.totals schema is not closed"
        )
    if value != _EXPECTED_TOTALS:
        raise IntegrationWorkflowProfileError(
            "integration profile totals drifted"
        )


def _prompt_fields(value: str, path: str) -> tuple[str, ...]:
    fields: list[str] = []
    try:
        parsed = tuple(string.Formatter().parse(value))
    except ValueError as exc:
        raise IntegrationWorkflowProfileError(
            f"{path} has invalid prompt-template braces"
        ) from exc
    for _, field_name, format_spec, conversion in parsed:
        if field_name is None:
            continue
        if _VISIBLE_INPUT_RE.fullmatch(field_name) is None:
            raise IntegrationWorkflowProfileError(
                f"{path} uses an invalid visible-input placeholder"
            )
        if format_spec or conversion:
            raise IntegrationWorkflowProfileError(
                f"{path} placeholders cannot use formatting or conversion"
            )
        fields.append(field_name)
    if len(fields) != len(set(fields)):
        raise IntegrationWorkflowProfileError(
            f"{path} repeats a visible-input placeholder"
        )
    return tuple(fields)


def _lint_natural_prompt(value: str, path: str) -> None:
    if len(value.strip()) < 12:
        raise IntegrationWorkflowProfileError(
            f"{path} is too short to represent a substantive user turn"
        )
    for pattern in _PROMPT_FORBIDDEN:
        if pattern.search(value):
            raise IntegrationWorkflowProfileError(
                f"{path} contains test-harness coaching forbidden from "
                f"natural user prompts: {pattern.pattern!r}"
            )


def _resolve_sibling_json(profile_path: Path, value: str) -> Path:
    relative = Path(value)
    if (
        relative.is_absolute()
        or relative.parts != (value,)
        or relative.suffix != ".json"
    ):
        raise IntegrationWorkflowProfileError(
            "profile.data_files entries must be sibling JSON filenames"
        )
    path = _resolve_regular_file(
        profile_path.parent / relative,
        f"integration data file {value}",
    )
    if path.parent != profile_path.parent:
        raise IntegrationWorkflowProfileError(
            f"profile.data_files entry escapes its directory: {value}"
        )
    return path


def _resolve_regular_file(value: str | Path, label: str) -> Path:
    try:
        path = Path(value).expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise IntegrationWorkflowProfileError(
            f"cannot resolve {label}: {value}"
        ) from exc
    if not path.is_file():
        raise IntegrationWorkflowProfileError(
            f"{label} must be a regular file"
        )
    return path


def _load_json(path: Path, label: str) -> tuple[dict[str, Any], str]:
    try:
        payload = path.read_bytes()
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite_number,
        )
    except IntegrationWorkflowProfileError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IntegrationWorkflowProfileError(
            f"cannot load {label} {path}: {exc}"
        ) from exc
    if not isinstance(value, dict):
        raise IntegrationWorkflowProfileError(
            f"{label} must be a JSON object"
        )
    return value, hashlib.sha256(payload).hexdigest()


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise IntegrationWorkflowProfileError(
                f"duplicate JSON object key is forbidden: {key}"
            )
        result[key] = value
    return result


def _reject_nonfinite_number(value: str) -> None:
    raise IntegrationWorkflowProfileError(
        f"non-finite JSON number is forbidden: {value}"
    )


def _string_tuple(value: Any, path: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise IntegrationWorkflowProfileError(
            f"{path} must be a non-empty JSON string array"
        )
    result = tuple(_nonempty_string(item, f"{path}[]") for item in value)
    if len(result) != len(set(result)):
        raise IntegrationWorkflowProfileError(
            f"{path} contains duplicate values"
        )
    return result


def _nonempty_string_list(value: Any, path: str) -> tuple[str, ...]:
    result = _string_tuple(value, path)
    return result


def _nonempty_string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise IntegrationWorkflowProfileError(
            f"{path} must be a non-empty string"
        )
    return value


def _positive_integer(value: Any, path: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise IntegrationWorkflowProfileError(
            f"{path} must be a positive integer"
        )
    return value


def _optional_positive_integer(value: Any, path: str) -> int | None:
    if value is None:
        return None
    return _positive_integer(value, path)


def _unique_strings(values: Sequence[str], label: str) -> tuple[str, ...]:
    result = tuple(_nonempty_string(value, label) for value in values)
    if len(result) != len(set(result)):
        raise IntegrationWorkflowProfileError(
            f"duplicate {label} are not allowed"
        )
    return result


__all__ = [
    "CASE_FILE_CONTRACT",
    "DATA_FILE_NAMES",
    "EXPECTED_ADAPTERS",
    "EXPECTED_PRIMARY_API",
    "EXPECTED_TRANSACTION_SPECS",
    "EXPECTED_TURN_KINDS",
    "EXPECTED_VISIBLE_INPUTS",
    "LOGICAL_WORKFLOW_COUNT",
    "PROFILE_CONTRACT",
    "PROFILE_ID",
    "TASK_COUNT",
    "TRANSACTION_COUNT",
    "USER_TURN_COUNT",
    "VERSIONS",
    "WORKFLOW_IDS",
    "IntegrationVisibleInput",
    "IntegrationPrimaryDispatch",
    "IntegrationScenarioProxy",
    "IntegrationWorkflowCase",
    "IntegrationWorkflowFixture",
    "IntegrationWorkflowProfile",
    "IntegrationWorkflowProfileError",
    "IntegrationWorkflowTransaction",
    "IntegrationWorkflowTurn",
    "IntegrationWorkflowUnit",
    "load_integration_workflows_profile",
]
