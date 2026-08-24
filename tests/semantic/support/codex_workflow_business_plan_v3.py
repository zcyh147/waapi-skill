"""Closed business-plan sections for reviewed multi-API workflows.

The common business-oracle envelope persists six family-owned sections.  This
module keeps that contract while adding a closed workflow topology inside the
family sections: ordered transactions, every broker step, diagnostic evidence
requirements, live bindings, and one independently hashed expectation per
transaction.

This module deliberately does not execute a workflow or inspect Wwise.  A
runner must compile the sections from reviewed inputs before Codex starts and
later compare an archived payload with those same independent inputs.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from wwise_waapi.operation_registry import (
    BUSINESS_DECLARATION_INPUT_MODE,
    COMPOSER_INPUT_MODE,
    operation_input_mode,
)


WORKFLOW_BUSINESS_PLAN_SCHEMA = "waapi-skill.workflow-business-plan/v1"
WORKFLOW_FIXTURE_KIND = "workflow_materialized_v1"
WORKFLOW_ASSERTION_IDS = (
    "workflow.identity.exact",
    "workflow.transactions.exact",
    "workflow.steps.complete",
    "workflow.diagnostics.bound",
    "workflow.live_bindings.sealed",
    "workflow.delta.closed",
)

_SECTION_KEYS = frozenset(
    {
        "fixture_spec",
        "payload_bindings",
        "assertion_ids",
        "static_expectation",
        "live_binding",
        "delta_rules",
    }
)
_STATIC_KEYS = frozenset(
    {
        "family_schema_version",
        "workflow_id",
        "transactions",
        "diagnostic_evidence",
        "workflow_steps",
    }
)
_LIVE_KEYS = frozenset(
    {
        "family_schema_version",
        "workflow_id",
        "bindings",
        "bindings_sha256",
    }
)
_TRANSACTION_KEYS = frozenset(
    {"transaction_id", "api", "operation", "phase", "primary_step"}
)
_STEP_KEYS = frozenset(
    {"name", "kind", "phase", "transaction_id", "api"}
)
_DIAGNOSTIC_KEYS = frozenset(
    {
        "evidence_id",
        "step",
        "api",
        "phase",
        "expectation",
        "expectation_sha256",
    }
)
_DELTA_KEYS = frozenset(
    {"kind", "transaction_id", "expectation", "expectation_sha256"}
)
_TRANSACTION_STEP_KINDS = (
    ("operation-schema", "operation_schema"),
    ("preview", "preview"),
    ("transaction-show", "transaction_show"),
    ("confirm", "confirm"),
    ("execute", "execute"),
    ("verify", "verify"),
)
_OBJECT_SET_COMPOSER_TAIL_KINDS = (
    ("check", "operation_compose_check"),
    ("preview", "preview"),
    ("transaction-show", "transaction_show"),
    ("confirm", "confirm"),
    ("execute", "execute"),
    ("verify", "verify"),
)
_NON_TRANSACTION_STEP_KINDS = frozenset(
    {"diagnostic", "checkpoint", "cleanup"}
)
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_TRANSACTION_ID_RE = re.compile(r"^tx[0-9]{2}$")
_API_RE = re.compile(r"^ak\.(?:wwise|soundengine)\.[A-Za-z0-9_.]+$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class WorkflowBusinessPlanError(ValueError):
    """A workflow plan is incomplete, cross-bound, or not closed."""


@dataclass(frozen=True, slots=True)
class WorkflowBusinessPlanSections:
    """The six family-owned sections accepted by the common plan writer."""

    fixture_spec: Mapping[str, Any]
    payload_bindings: Mapping[str, Any]
    assertion_ids: tuple[str, ...]
    static_expectation: Mapping[str, Any]
    live_binding: Mapping[str, Any]
    delta_rules: tuple[Mapping[str, Any], ...]

    def writer_kwargs(self) -> dict[str, Any]:
        """Return plain JSON values for ``write_business_oracle_plan``."""

        return {
            "fixture_spec": _plain(self.fixture_spec),
            "payload_bindings": _plain(self.payload_bindings),
            "assertion_ids": list(self.assertion_ids),
            "static_expectation": _plain(self.static_expectation),
            "live_binding": _plain(self.live_binding),
            "delta_rules": [_plain(item) for item in self.delta_rules],
        }


def compile_workflow_business_plan_sections(
    *,
    workflow_id: str,
    transactions: Sequence[Mapping[str, Any]],
    workflow_steps: Sequence[Mapping[str, Any]],
    diagnostic_evidence: Sequence[Mapping[str, Any]],
    live_bindings: Mapping[str, Any],
    transaction_expectations: Sequence[Mapping[str, Any]],
) -> WorkflowBusinessPlanSections:
    """Compile one immutable workflow plan from runner-owned reviewed inputs.

    ``transactions`` rows have exactly ``transaction_id``, ``api``,
    ``operation``, ``phase``, and ``primary_step``.  ``workflow_steps`` rows
    have exactly ``name``, ``kind``, ``phase``, ``transaction_id``, and
    ``api``.  Diagnostic input rows omit their derived hash and contain exactly
    ``evidence_id``, ``step``, ``api``, ``phase``, and ``expectation``.
    Transaction expectation rows contain exactly ``transaction_id`` and
    ``expectation``.
    """

    _identifier(workflow_id, "workflow_id")
    transaction_rows = _input_rows(
        transactions,
        keys=_TRANSACTION_KEYS,
        name="transactions",
        allow_empty=False,
    )
    step_rows = _input_rows(
        workflow_steps,
        keys=_STEP_KEYS,
        name="workflow_steps",
        allow_empty=False,
    )
    diagnostic_inputs = _input_rows(
        diagnostic_evidence,
        keys=_DIAGNOSTIC_KEYS - {"expectation_sha256"},
        name="diagnostic_evidence",
        allow_empty=True,
    )
    expectation_inputs = _input_rows(
        transaction_expectations,
        keys={"transaction_id", "expectation"},
        name="transaction_expectations",
        allow_empty=False,
    )
    bindings = _json_value(live_bindings, "live_bindings")
    if type(bindings) is not dict:
        raise WorkflowBusinessPlanError("live_bindings must be a JSON object")

    diagnostic_rows = [
        {
            **row,
            "expectation_sha256": _sha256(row["expectation"]),
        }
        for row in diagnostic_inputs
    ]
    delta_rows = [
        {
            "kind": "workflow.transaction-delta/v1",
            "transaction_id": row["transaction_id"],
            "expectation": row["expectation"],
            "expectation_sha256": _sha256(row["expectation"]),
        }
        for row in expectation_inputs
    ]
    static = {
        "family_schema_version": WORKFLOW_BUSINESS_PLAN_SCHEMA,
        "workflow_id": workflow_id,
        "transactions": transaction_rows,
        "diagnostic_evidence": diagnostic_rows,
        "workflow_steps": step_rows,
    }
    live = {
        "family_schema_version": WORKFLOW_BUSINESS_PLAN_SCHEMA,
        "workflow_id": workflow_id,
        "bindings": bindings,
        "bindings_sha256": _sha256(bindings),
    }
    primary_steps = [row["primary_step"] for row in transaction_rows]
    workflow_step_names = [row["name"] for row in step_rows]
    primary_set = set(primary_steps)
    payload = {
        "fixture_spec": {
            "kind": WORKFLOW_FIXTURE_KIND,
            "sha256": _sha256(
                {"static": static, "live": live, "delta_rules": delta_rows}
            ),
        },
        "payload_bindings": {
            "primary_steps": primary_steps,
            "verification_steps": [
                name for name in workflow_step_names if name not in primary_set
            ],
        },
        "assertion_ids": list(WORKFLOW_ASSERTION_IDS),
        "static_expectation": static,
        "live_binding": live,
        "delta_rules": delta_rows,
    }
    return parse_workflow_business_plan_sections(payload)


def parse_workflow_business_plan_sections(
    plan_payload: Mapping[str, Any],
) -> WorkflowBusinessPlanSections:
    """Parse and structurally validate workflow sections from a common plan."""

    if not isinstance(plan_payload, Mapping):
        raise WorkflowBusinessPlanError("workflow business plan is not an object")
    if not _SECTION_KEYS.issubset(plan_payload):
        raise WorkflowBusinessPlanError("workflow business plan omits typed sections")
    values = {name: plan_payload[name] for name in _SECTION_KEYS}
    if any(
        type(values[name]) is not dict
        for name in (
            "fixture_spec",
            "payload_bindings",
            "static_expectation",
            "live_binding",
        )
    ):
        raise WorkflowBusinessPlanError(
            "workflow fixture, bindings, static, and live sections must be objects"
        )
    if type(values["assertion_ids"]) is not list:
        raise WorkflowBusinessPlanError("workflow assertion_ids must be a JSON array")
    if type(values["delta_rules"]) is not list:
        raise WorkflowBusinessPlanError("workflow delta_rules must be a JSON array")

    sections = WorkflowBusinessPlanSections(
        fixture_spec=_freeze_json(values["fixture_spec"], "fixture_spec"),
        payload_bindings=_freeze_json(
            values["payload_bindings"], "payload_bindings"
        ),
        assertion_ids=tuple(
            _json_value(values["assertion_ids"], "assertion_ids")
        ),
        static_expectation=_freeze_json(
            values["static_expectation"], "static_expectation"
        ),
        live_binding=_freeze_json(values["live_binding"], "live_binding"),
        delta_rules=tuple(
            _freeze_json(item, f"delta_rules[{index}]")
            for index, item in enumerate(values["delta_rules"])
        ),
    )
    _validate_sections(sections)
    return sections


def validate_workflow_business_plan_sections(
    sections: Mapping[str, Any] | WorkflowBusinessPlanSections,
    *,
    workflow_id: str,
    transactions: Sequence[Mapping[str, Any]],
    workflow_steps: Sequence[Mapping[str, Any]],
    diagnostic_evidence: Sequence[Mapping[str, Any]],
    live_bindings: Mapping[str, Any],
    transaction_expectations: Sequence[Mapping[str, Any]],
) -> WorkflowBusinessPlanSections:
    """Recompile from independent reviewed inputs and compare every section."""

    actual = (
        sections
        if isinstance(sections, WorkflowBusinessPlanSections)
        else parse_workflow_business_plan_sections(sections)
    )
    _validate_sections(actual)
    expected = compile_workflow_business_plan_sections(
        workflow_id=workflow_id,
        transactions=transactions,
        workflow_steps=workflow_steps,
        diagnostic_evidence=diagnostic_evidence,
        live_bindings=live_bindings,
        transaction_expectations=transaction_expectations,
    )
    if actual.writer_kwargs() != expected.writer_kwargs():
        raise WorkflowBusinessPlanError(
            "workflow plan differs from independently recomputed reviewed inputs"
        )
    return actual


def _validate_sections(sections: WorkflowBusinessPlanSections) -> None:
    if not isinstance(sections, WorkflowBusinessPlanSections):
        raise WorkflowBusinessPlanError("workflow sections have the wrong type")
    fixture = sections.fixture_spec
    bindings = sections.payload_bindings
    static = sections.static_expectation
    live = sections.live_binding
    rules = sections.delta_rules
    if set(fixture) != {"kind", "sha256"}:
        raise WorkflowBusinessPlanError("workflow fixture_spec is not closed")
    if (
        fixture.get("kind") != WORKFLOW_FIXTURE_KIND
        or not _is_sha256(fixture.get("sha256"))
    ):
        raise WorkflowBusinessPlanError("workflow fixture identity is invalid")
    if set(bindings) != {"primary_steps", "verification_steps"}:
        raise WorkflowBusinessPlanError("workflow payload_bindings is not closed")
    if tuple(sections.assertion_ids) != WORKFLOW_ASSERTION_IDS:
        raise WorkflowBusinessPlanError("workflow assertion set drifted")
    if set(static) != _STATIC_KEYS:
        raise WorkflowBusinessPlanError("workflow static expectation is not closed")
    if set(live) != _LIVE_KEYS:
        raise WorkflowBusinessPlanError("workflow live binding is not closed")
    if (
        static.get("family_schema_version") != WORKFLOW_BUSINESS_PLAN_SCHEMA
        or live.get("family_schema_version") != WORKFLOW_BUSINESS_PLAN_SCHEMA
    ):
        raise WorkflowBusinessPlanError("workflow family schema version drifted")

    workflow_id = static.get("workflow_id")
    _identifier(workflow_id, "static_expectation.workflow_id")
    if live.get("workflow_id") != workflow_id:
        raise WorkflowBusinessPlanError("workflow live binding has another identity")

    transactions = _plain(static.get("transactions"))
    workflow_steps = _plain(static.get("workflow_steps"))
    diagnostic_evidence = _plain(static.get("diagnostic_evidence"))
    _validate_transactions(transactions)
    _validate_workflow_steps(workflow_steps, transactions)
    _validate_diagnostic_evidence(diagnostic_evidence, workflow_steps)
    _validate_payload_bindings(bindings, transactions, workflow_steps)
    _validate_live_binding(live)
    _validate_delta_rules(rules, transactions)

    expected_fixture_sha256 = _sha256(
        {
            "static": _plain(static),
            "live": _plain(live),
            "delta_rules": [_plain(item) for item in rules],
        }
    )
    if fixture.get("sha256") != expected_fixture_sha256:
        raise WorkflowBusinessPlanError("workflow fixture digest drifted")


def _validate_transactions(rows: Any) -> None:
    if type(rows) is not list or not rows:
        raise WorkflowBusinessPlanError("workflow transactions must be nonempty")
    if len(rows) > 32:
        raise WorkflowBusinessPlanError("workflow transaction count is unbounded")
    for index, row in enumerate(rows, start=1):
        if type(row) is not dict or set(row) != _TRANSACTION_KEYS:
            raise WorkflowBusinessPlanError(
                f"workflow transaction {index} is not closed"
            )
        expected_id = f"tx{index:02d}"
        if row.get("transaction_id") != expected_id:
            raise WorkflowBusinessPlanError(
                "workflow transaction ids must be contiguous and ordered"
            )
        _api(row.get("api"), f"transactions[{index - 1}].api")
        _identifier(
            row.get("operation"), f"transactions[{index - 1}].operation"
        )
        _identifier(row.get("phase"), f"transactions[{index - 1}].phase")
        if row.get("primary_step") != f"{expected_id}.execute":
            raise WorkflowBusinessPlanError(
                "workflow transaction primary step is not its execute step"
            )


def _validate_workflow_steps(
    rows: Any,
    transactions: Sequence[Mapping[str, Any]],
) -> None:
    if type(rows) is not list or not rows:
        raise WorkflowBusinessPlanError("workflow_steps must be nonempty")
    if len(rows) > 256:
        raise WorkflowBusinessPlanError("workflow step count is unbounded")
    names: list[str] = []
    transaction_positions: dict[str, list[int]] = {
        row["transaction_id"]: [] for row in transactions
    }
    first_transaction_position: int | None = None
    last_transaction_position: int | None = None
    transaction_by_id = {row["transaction_id"]: row for row in transactions}
    for index, row in enumerate(rows):
        if type(row) is not dict or set(row) != _STEP_KEYS:
            raise WorkflowBusinessPlanError(
                f"workflow_steps[{index}] is not closed"
            )
        name = row.get("name")
        kind = row.get("kind")
        phase = row.get("phase")
        transaction_id = row.get("transaction_id")
        api = row.get("api")
        _identifier(name, f"workflow_steps[{index}].name")
        _identifier(phase, f"workflow_steps[{index}].phase")
        names.append(name)

        if transaction_id is None:
            if kind not in _NON_TRANSACTION_STEP_KINDS:
                raise WorkflowBusinessPlanError(
                    "non-transaction workflow step has an invalid kind"
                )
            if kind == "diagnostic":
                _api(api, f"workflow_steps[{index}].api")
            elif api is not None:
                _api(api, f"workflow_steps[{index}].api")
            continue

        if (
            type(transaction_id) is not str
            or _TRANSACTION_ID_RE.fullmatch(transaction_id) is None
            or transaction_id not in transaction_by_id
        ):
            raise WorkflowBusinessPlanError(
                "workflow step references an unknown transaction"
            )
        transaction = transaction_by_id[transaction_id]
        if (
            not name.startswith(f"{transaction_id}.")
            or api != transaction["api"]
            or phase != transaction["phase"]
        ):
            raise WorkflowBusinessPlanError(
                "workflow transaction step differs from its transaction"
            )
        transaction_positions[transaction_id].append(index)
        if first_transaction_position is None:
            first_transaction_position = index
        last_transaction_position = index

    if len(set(names)) != len(names):
        raise WorkflowBusinessPlanError("workflow step names must be unique")

    prior_end = -1
    for transaction in transactions:
        transaction_id = transaction["transaction_id"]
        positions = transaction_positions[transaction_id]
        transaction_steps = [rows[index] for index in positions]
        if not _matches_transaction_step_sequence(transaction, transaction_steps):
            raise WorkflowBusinessPlanError(
                f"workflow {transaction_id} does not contain one complete transaction"
            )
        if positions[0] <= prior_end:
            raise WorkflowBusinessPlanError(
                "workflow transactions are interleaved or out of order"
            )
        prior_end = positions[-1]

    assert first_transaction_position is not None
    assert last_transaction_position is not None
    for index, row in enumerate(rows):
        if row["kind"] == "diagnostic" and index >= first_transaction_position:
            raise WorkflowBusinessPlanError(
                "workflow diagnostic steps must precede the first transaction"
            )
        if row["kind"] == "cleanup" and index <= last_transaction_position:
            raise WorkflowBusinessPlanError(
                "workflow cleanup steps must follow every transaction"
            )


def _matches_transaction_step_sequence(
    transaction: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
) -> bool:
    transaction_id = transaction["transaction_id"]
    actual = [(row["name"], row["kind"]) for row in rows]
    legacy = [
        (f"{transaction_id}.{suffix}", kind)
        for suffix, kind in _TRANSACTION_STEP_KINDS
    ]
    if actual == legacy:
        return True
    input_mode = operation_input_mode(
        str(transaction.get("operation")),
        str(transaction.get("version", "2022.1")),
    )
    if input_mode not in {COMPOSER_INPUT_MODE, BUSINESS_DECLARATION_INPUT_MODE}:
        return False
    if len(actual) < 9:
        return False
    if actual[:2] != [
        (f"{transaction_id}.operation-schema", "operation_schema"),
        (f"{transaction_id}.draft-start", "operation_compose"),
    ]:
        return False
    tail = [
        (f"{transaction_id}.{suffix}", kind)
        for suffix, kind in _OBJECT_SET_COMPOSER_TAIL_KINDS
    ]
    if actual[-len(tail) :] != tail:
        return False
    construction = actual[2 : -len(tail)]
    for name, kind in construction:
        if kind != "operation_compose":
            return False
    prefixes = [
        name.removeprefix(f"{transaction_id}.") for name, _kind in construction
    ]
    if input_mode == BUSINESS_DECLARATION_INPUT_MODE:
        if not prefixes:
            return False
        offset = 1 if prefixes[0] == "configure" else 0
        counters = {"bind-object": [], "bind-field": [], "declare": []}
        for prefix in prefixes[offset:]:
            family, separator, raw_index = prefix.rpartition(".")
            if (
                not separator
                or family not in counters
                or len(raw_index) != 3
                or not raw_index.isdigit()
            ):
                return False
            counters[family].append(int(raw_index))
        return (
            bool(counters["bind-object"])
            and bool(counters["declare"])
            and all(
                indexes == list(range(1, len(indexes) + 1))
                for indexes in counters.values()
            )
        )
    action_indexes: list[int] = []
    disclosure_positions: list[int] = []
    for position, prefix in enumerate(prefixes):
        if prefix.startswith("action."):
            raw_index = prefix.removeprefix("action.")
            if len(raw_index) != 3 or not raw_index.isdigit():
                return False
            action_indexes.append(int(raw_index))
        elif prefix.startswith("disclose."):
            disclosure_positions.append(position)
        else:
            return False
    if not action_indexes or sorted(action_indexes) != list(
        range(1, len(action_indexes) + 1)
    ):
        return False
    if not disclosure_positions:
        return action_indexes == sorted(action_indexes)
    cursor = 0
    initial_actions: list[int] = []
    while cursor < len(prefixes) and prefixes[cursor].startswith("action."):
        initial_actions.append(int(prefixes[cursor].removeprefix("action.")))
        cursor += 1
    if initial_actions != sorted(initial_actions):
        return False
    disclosure_index = 1
    while cursor < len(prefixes):
        disclosed = 0
        while cursor < len(prefixes) and prefixes[cursor].startswith("disclose."):
            base = f"disclose.{disclosure_index:03d}"
            if prefixes[cursor] == f"{base}.choices":
                cursor += 1
            if cursor >= len(prefixes) or prefixes[cursor] != base:
                return False
            cursor += 1
            disclosure_index += 1
            disclosed += 1
        if disclosed == 0:
            return False
        dependent_actions: list[int] = []
        while cursor < len(prefixes) and prefixes[cursor].startswith("action."):
            dependent_actions.append(
                int(prefixes[cursor].removeprefix("action."))
            )
            cursor += 1
        if not dependent_actions or dependent_actions != sorted(dependent_actions):
            return False
    return True


def _validate_diagnostic_evidence(
    rows: Any,
    workflow_steps: Sequence[Mapping[str, Any]],
) -> None:
    if type(rows) is not list:
        raise WorkflowBusinessPlanError(
            "workflow diagnostic_evidence must be an array"
        )
    diagnostic_steps = {
        row["name"]: row
        for row in workflow_steps
        if row["kind"] == "diagnostic"
    }
    if len(rows) != len(diagnostic_steps):
        raise WorkflowBusinessPlanError(
            "every diagnostic step requires exactly one sealed evidence expectation"
        )
    evidence_ids: list[str] = []
    evidence_steps: list[str] = []
    for index, row in enumerate(rows):
        if type(row) is not dict or set(row) != _DIAGNOSTIC_KEYS:
            raise WorkflowBusinessPlanError(
                f"diagnostic_evidence[{index}] is not closed"
            )
        evidence_id = row.get("evidence_id")
        step = row.get("step")
        _identifier(
            evidence_id, f"diagnostic_evidence[{index}].evidence_id"
        )
        _identifier(step, f"diagnostic_evidence[{index}].step")
        evidence_ids.append(evidence_id)
        evidence_steps.append(step)
        expected_step = diagnostic_steps.get(step)
        if (
            expected_step is None
            or row.get("api") != expected_step["api"]
            or row.get("phase") != expected_step["phase"]
        ):
            raise WorkflowBusinessPlanError(
                "diagnostic evidence is not bound to its workflow step"
            )
        expectation = row.get("expectation")
        if type(expectation) is not dict or not expectation:
            raise WorkflowBusinessPlanError(
                "diagnostic evidence expectation must be a nonempty object"
            )
        if row.get("expectation_sha256") != _sha256(expectation):
            raise WorkflowBusinessPlanError(
                "diagnostic evidence expectation digest drifted"
            )
    if len(set(evidence_ids)) != len(evidence_ids):
        raise WorkflowBusinessPlanError(
            "diagnostic evidence ids must be unique"
        )
    if evidence_steps != list(diagnostic_steps):
        raise WorkflowBusinessPlanError(
            "diagnostic evidence does not follow the exact diagnostic step order"
        )


def _validate_payload_bindings(
    bindings: Mapping[str, Any],
    transactions: Sequence[Mapping[str, Any]],
    workflow_steps: Sequence[Mapping[str, Any]],
) -> None:
    primary = _plain(bindings.get("primary_steps"))
    verification = _plain(bindings.get("verification_steps"))
    if type(primary) is not list or type(verification) is not list:
        raise WorkflowBusinessPlanError(
            "workflow step bindings must be JSON arrays"
        )
    expected_primary = [row["primary_step"] for row in transactions]
    names = [row["name"] for row in workflow_steps]
    expected_verification = [
        name for name in names if name not in set(expected_primary)
    ]
    if primary != expected_primary or verification != expected_verification:
        raise WorkflowBusinessPlanError(
            "workflow primary/verification bindings differ from complete steps"
        )
    if len(set(primary + verification)) != len(primary) + len(verification):
        raise WorkflowBusinessPlanError(
            "workflow payload bindings contain duplicate steps"
        )
    if set(primary + verification) != set(names):
        raise WorkflowBusinessPlanError(
            "workflow payload bindings omit or invent workflow steps"
        )


def _validate_live_binding(live: Mapping[str, Any]) -> None:
    bindings = _plain(live.get("bindings"))
    if type(bindings) is not dict:
        raise WorkflowBusinessPlanError(
            "workflow live bindings must be a JSON object"
        )
    if live.get("bindings_sha256") != _sha256(bindings):
        raise WorkflowBusinessPlanError("workflow live binding digest drifted")


def _validate_delta_rules(
    rules: Sequence[Mapping[str, Any]],
    transactions: Sequence[Mapping[str, Any]],
) -> None:
    if len(rules) != len(transactions):
        raise WorkflowBusinessPlanError(
            "workflow requires one delta rule per transaction"
        )
    for index, (rule, transaction) in enumerate(
        zip(rules, transactions, strict=True)
    ):
        if set(rule) != _DELTA_KEYS:
            raise WorkflowBusinessPlanError(
                f"workflow delta_rules[{index}] is not closed"
            )
        expectation = _plain(rule.get("expectation"))
        if (
            rule.get("kind") != "workflow.transaction-delta/v1"
            or rule.get("transaction_id") != transaction["transaction_id"]
            or type(expectation) is not dict
            or not expectation
            or rule.get("expectation_sha256") != _sha256(expectation)
        ):
            raise WorkflowBusinessPlanError(
                "workflow transaction delta rule is invalid or misbound"
            )


def _input_rows(
    value: Sequence[Mapping[str, Any]],
    *,
    keys: set[str] | frozenset[str],
    name: str,
    allow_empty: bool,
) -> list[dict[str, Any]]:
    if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple)):
        raise WorkflowBusinessPlanError(f"{name} must be an ordered sequence")
    if not allow_empty and not value:
        raise WorkflowBusinessPlanError(f"{name} must be nonempty")
    rows: list[dict[str, Any]] = []
    for index, row in enumerate(value):
        if not isinstance(row, Mapping) or set(row) != set(keys):
            raise WorkflowBusinessPlanError(f"{name}[{index}] is not closed")
        normalized = _json_value(row, f"{name}[{index}]")
        if type(normalized) is not dict:
            raise WorkflowBusinessPlanError(f"{name}[{index}] is not an object")
        rows.append(normalized)
    return rows


def _identifier(value: Any, name: str) -> str:
    if type(value) is not str or _IDENTIFIER_RE.fullmatch(value) is None:
        raise WorkflowBusinessPlanError(f"{name} is not a valid identifier")
    return value


def _api(value: Any, name: str) -> str:
    if type(value) is not str or _API_RE.fullmatch(value) is None:
        raise WorkflowBusinessPlanError(f"{name} is not a WAAPI route")
    return value


def _is_sha256(value: Any) -> bool:
    return type(value) is str and _SHA256_RE.fullmatch(value) is not None


def _sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            _json_value(value, "hash input"),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _json_value(value: Any, name: str) -> Any:
    if value is None or type(value) in {str, bool, int}:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise WorkflowBusinessPlanError(f"{name} contains a non-finite float")
        return value
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if type(key) is not str:
                raise WorkflowBusinessPlanError(
                    f"{name} contains a non-string object key"
                )
            result[key] = _json_value(item, f"{name}.{key}")
        return result
    if isinstance(value, (list, tuple)):
        return [
            _json_value(item, f"{name}[{index}]")
            for index, item in enumerate(value)
        ]
    raise WorkflowBusinessPlanError(
        f"{name} contains a non-JSON value: {type(value).__name__}"
    )


def _freeze_json(value: Any, name: str) -> Any:
    normalized = _json_value(value, name)
    return _freeze_normalized(normalized)


def _freeze_normalized(value: Any) -> Any:
    if type(value) is dict:
        return MappingProxyType(
            {key: _freeze_normalized(item) for key, item in value.items()}
        )
    if type(value) is list:
        return tuple(_freeze_normalized(item) for item in value)
    return value


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


__all__ = [
    "WORKFLOW_ASSERTION_IDS",
    "WORKFLOW_BUSINESS_PLAN_SCHEMA",
    "WORKFLOW_FIXTURE_KIND",
    "WorkflowBusinessPlanError",
    "WorkflowBusinessPlanSections",
    "compile_workflow_business_plan_sections",
    "parse_workflow_business_plan_sections",
    "validate_workflow_business_plan_sections",
]
