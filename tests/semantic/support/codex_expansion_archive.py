"""Read-only replay of expansion evidence inside a verified formal attempt.

The campaign must first verify its existing attempt seal and immutable effective
configuration. This module binds to that configuration digest and checks the
archived protocol; it never launches a host, repairs a transaction store, writes
a grade, or promotes an original failure to a business PASS.
"""

from __future__ import annotations

import hashlib
import importlib
import io
import json
import math
import re
import sys
from dataclasses import asdict
from contextlib import redirect_stderr, redirect_stdout
from types import SimpleNamespace
from pathlib import Path
from typing import Any, Mapping

from tests.semantic.support.codex_archive_paths import parse_archive_relative_path
from tests.semantic.support.codex_expansion_policy import (
    BoundedExpansionReads, ExpansionReadScope, canonical_digest, classify_expansion_outcome,
)
from tests.semantic.support.codex_expansion_broker_policy import (
    _BUSINESS_EDITS, _DECLARATIONS, _DRAFT_READS, _READ_COMMANDS,
)
from tests.semantic.support.codex_filesystem_security import (
    path_is_link_or_reparse, read_bounded_exclusive_regular_file,
)
from tests.semantic.support.codex_harness import (
    WindowsPowerShellCoreHost, audit_session_events, completed_command_records,
    final_agent_message, classify_task_commands, recoverable_preprocess_attempt_indexes,
    classify_codex_infrastructure_failure,
    workspace_skill_install_path,
)
from tests.semantic.support.codex_gateway_broker import resolve_gateway_invocation, _validate_branching_execute_payload
from tests.semantic.support.codex_transaction_seal import (
    _validate_artifact, _validate_legal_event_states,
)
from tests.semantic.support.codex_task_runner_v3 import expansion_preview_notice
from wwise_waapi.operation_drafts import load_operation_draft_archive_records, operation_draft_authority_digest
from wwise_waapi.operation_composer import new_composition, operation_composer_digest
from wwise_waapi.business_declaration_state import BusinessDeclarationSession
from wwise_waapi.business_declarations import BusinessHandleRegistry, NewDescendantTarget
from wwise_waapi.business_adapters import business_adapter
from wwise_waapi.transactions import _validate_event, confirmation_token_for, validate_transaction_id


_SHA = re.compile(r"[0-9a-f]{64}")
_CASE_MODULES = {"C01": "voice", "C03": "media", "C06": "rtpc", "C08": "attenuation",
                 "C09": "effects", "M01": "music", "M05": "stinger"}
_READS = set(_READ_COMMANDS)
_GATES = {"memory_isolated", "completed_turn", "one_target_skill", "no_collaboration",
    "only_packaged_references", "only_authenticated_gateway_and_skill_reads",
    "no_discovery_or_direct_waapi", "no_write_like_commands", "source_and_workspace_unchanged",
    "broker_provenance", "policy_checkpoint", "visible_preview_notice", "final_response_present", "cumulative_agent_budget"}


class ExpansionArchiveError(ValueError):
    """A sealed expansion archive cannot prove its recorded outcome."""


def _require(condition: Any, message: str) -> None:
    if not condition:
        raise ExpansionArchiveError(message)


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _decode(raw: bytes) -> Any:
    def invalid(value):
        raise ExpansionArchiveError(f"non-finite JSON constant: {value}")
    return json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=invalid)


def _bytes(root: Path, relative: str, *, empty: bool = False) -> bytes:
    cursor = root
    _require(cursor.is_dir() and not path_is_link_or_reparse(cursor), "archive root is missing or linked")
    parts = parse_archive_relative_path(relative).parts
    for part in parts:
        cursor = cursor / part
        _require(not path_is_link_or_reparse(cursor), "archive path is linked")
    return read_bounded_exclusive_regular_file(cursor, max_bytes=32 * 1024 * 1024,
        require_private_posix_mode=False, allow_empty=empty).raw


def _json(root: Path, relative: str) -> dict[str, Any]:
    value = _decode(_bytes(root, relative))
    _require(isinstance(value, dict), f"{relative} must contain an object")
    return value


def _finite(value: Any) -> bool:
    return type(value) in {int, float} and math.isfinite(value) and value >= 0


def _case(plan: Mapping[str, Any]) -> tuple[Any, str]:
    case_id = str(plan["unit_id"]).split("-")[-1]
    _require(case_id in _CASE_MODULES, "unknown expansion case")
    return importlib.import_module(
        "tests.semantic.support.codex_expansion_" + _CASE_MODULES[case_id] + "_case"), case_id


def _transaction(root: Path, transaction_id: str) -> tuple[dict, list[dict], dict]:
    validate_transaction_id(transaction_id)
    prefix = f"broker/state/transactions/{transaction_id}/"
    preview = _json(root, prefix + "preview.json")
    state = _json(root, prefix + "state.json")
    raw = _bytes(root, prefix + "events.jsonl")
    _require(raw.endswith(b"\n"), "transaction journal is incomplete")
    events = [_decode(line) for line in raw.splitlines()]
    artifact = preview.get("artifact")
    _require(isinstance(artifact, dict) and preview.get("transaction_id") == transaction_id
             and preview.get("artifact_hash") == canonical_digest(artifact), "preview artifact digest mismatch")
    _validate_artifact(artifact)
    previous_hash, previous_state = "", None
    for index, event in enumerate(events, 1):
        _require(isinstance(event, dict), "transaction event must be an object")
        _validate_event(event, transaction_id=transaction_id, artifact_hash=preview["artifact_hash"],
            expected_sequence=index, expected_previous_hash=previous_hash,
            expected_from_state=previous_state, path=root / prefix / "events.jsonl")
        previous_hash, previous_state = event["event_hash"], event["to_state"]
    _validate_legal_event_states(events)
    _require(state.get("transaction_id") == transaction_id
        and state.get("artifact_hash") == preview["artifact_hash"]
        and state.get("event_sequence") == len(events)
        and state.get("last_event_hash") == previous_hash and state.get("state") == previous_state
        and state.get("created_at") == events[0]["timestamp"]
        and state.get("updated_at") == events[-1]["timestamp"], "transaction state does not match journal")
    return preview, events, state


def _public_gateway(plan: Mapping[str, Any]):
    spec = importlib.util.spec_from_file_location("waapi_expansion_archive_public_parser",
        Path(plan["skill_source"]) / "scripts" / "gateway.py")
    _require(spec is not None and spec.loader is not None, "packaged public parser is unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _scope(plan: Mapping[str, Any]) -> BoundedExpansionReads:
    value = dict(plan["read_scope"])
    for key in ("object_ids", "operations", "includes", "relationship_sources", "fields", "curve_roles", "platforms"):
        values = value.get(key, [])
        _require(isinstance(values, list) and len(values) == len(set(values)), "read scope set is malformed")
        value[key] = frozenset(values)
    scope = ExpansionReadScope(**value)
    _require(scope.digest == plan["read_scope_sha256"], "read scope digest mismatch")
    module = _public_gateway(plan)
    parser = module.build_parser()
    def parse(argv):
        _require(bool(argv) and not argv[0].startswith("-") and len(argv) <= 256, "invalid public read argv")
        try:
            return parser.parse_args(["--version", plan["version"], *argv])
        except SystemExit as exc:
            raise ExpansionArchiveError("archived read violates the public parser") from exc
    return BoundedExpansionReads(scope, public_parser=parse)


def _validate_rejected_read(record, *, argv, gate):
    """One known read-bound rejection proves no runner was dispatched.

    Replay deliberately does not ask the current admission policy to reject
    again: its bound may have been repaired since this original FAIL.
    """
    parser_rejection = "expansion policy rejected command: command does not satisfy the public Gateway parser"
    if record.get("rejection") == parser_rejection:
        _validate_predispatch_rejection(record, parser_rejection)
        _require(bool(argv) and argv[0] == "query-object", "parser rejection is not a read-only object query")
        _validate_parser_error(argv, gate)
        return
    rejection = "expansion policy rejected command: project query requires a bounded public source"
    _validate_predispatch_rejection(record, rejection)
    _require(bool(argv) and argv[0] == "query-object" and len(argv[1:]) % 2 == 0,
        "rejection is not a closed public relationship read")
    flags = argv[1::2]
    _require(set(flags) <= {"--exact-id", "--relationship", "--include", "--max-results"}
        and flags.count("--exact-id") == flags.count("--relationship") == 1
        and flags.count("--max-results") <= 1, "rejected read exceeds the closed selector contract")
    args = gate.public_parser(argv)
    _require(args.object_id in gate.scope.relationship_sources
        and (gate.scope.owned_project_reads is True or set(args.business_outputs).issubset(gate.scope.includes)),
        "rejected relationship read exceeds its sealed identity/projection scope")
    if gate.scope.owned_project_reads is True:
        _require(args.relationships == ["children"] and (
            args.max_results is None or not 1 <= args.max_results <= gate.scope.max_rows),
            "rejected owned relationship read does not violate its sealed row bound")


def _validate_parser_error(argv, gate):
    """The frozen public parser must reject with usage error, never help."""
    try:
        with redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
            gate.public_parser(argv)
    except ExpansionArchiveError as exc:
        _require(isinstance(exc.__cause__, SystemExit) and exc.__cause__.code == 2,
            "rejected command lacks its public parser error")
    else:
        raise ExpansionArchiveError("parser-rejected command has valid public syntax")


def _validate_rejected_core_declaration(record, *, argv, gate, draft_id, authority, revision, operation):
    """One malformed attenuation declaration is authenticated but undispatched."""
    _validate_predispatch_rejection(record,
        "expansion policy rejected command: command does not satisfy the public Gateway parser")
    _require(operation == "ak.wwise.core.object.setAttenuationCurve" and revision == 2
        and argv[:6] == ["draft-declare-core-plan", draft_id, "--task-authority", authority,
            "--expected-revision", "2"]
        and argv.count("--task-authority") == argv.count("--expected-revision") == 1,
        "rejected declaration changed its bound Draft authority or revision")
    _validate_parser_error(argv, gate)


def _validate_rejected_draft_check(record, *, argv, gate, draft_id, authority, revision, operation):
    """Only the exact current import Draft with a different authority is safe."""
    _validate_predispatch_rejection(record,
        "expansion policy rejected command: Draft identity, authority or revision is stale")
    args = gate.public_parser(argv)
    _require(operation == "audio.import" and revision == 3 and isinstance(authority, str)
        and len(argv) == 6 and argv[:2] == ["draft-check", draft_id]
        and argv[2] == "--task-authority" and bool(argv[3]) and argv[3] != authority
        and argv[4:] == ["--expected-revision", "3"]
        and args.draft_id == draft_id and args.expected_revision == revision,
        "rejected check is not the exact current import Draft with stale authority")


def _validate_predispatch_rejection(record, rejection):
    _require(record.get("authenticated") is True and record.get("accepted") is False
        and record.get("succeeded") is False and record.get("exit_code") == 126
        and record.get("runner_exit_code") is None and record.get("step_name") is None
        and record.get("allowed_exit_codes") == [] and record.get("payload") is None
        and record.get("payload_sha256") == record.get("payload_error")
            == record.get("runner_command_sha256") == record.get("semantic_argv_sha256") == ""
        and record.get("stdout") == "" and record.get("subscription_ack") is None
        and record.get("rejection") == rejection
        and record.get("stderr") == "Gateway broker rejected command: " + rejection + "\n",
        "rejected command lacks authenticated pre-dispatch proof")


def _validate_rejected_draft_bind(record, *, argv, gate, draft_id, authority, revision):
    _validate_predispatch_rejection(record,
        "expansion policy rejected command: bound object is outside the approved fixture")
    _require(len(argv) == 8 and argv[:2] == ["draft-bind-object", draft_id]
        and argv[2:4] == ["--task-authority", authority]
        and argv[4:6] == ["--expected-revision", "1"] and revision == 1
        and argv[6] == "--object-id" and re.fullmatch(
            r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", argv[7])
        and ("{" + argv[7] + "}").upper() in {value.upper() for value in gate.scope.object_ids},
        "rejected Draft binding is not the exact invalid brace-less fixture GUID")


def _pristine_rejected_draft(root, plan, records):
    starts = [row for row in records if row["gateway_arguments"][0] == "draft-start"]
    _require(len(starts) == 1 and all(row["gateway_arguments"][0] in _READS | {"draft-start", "draft-bind-object"}
        for row in records) and not any(row.get("accepted") is True and row["gateway_arguments"][0] == "draft-bind-object"
        for row in records), "rejected binding contains another Draft action")
    payload = starts[0]["payload"]
    draft = payload["draft"]
    stored = load_operation_draft_archive_records((root / "broker/state").absolute(), [draft["draft_id"]])[draft["draft_id"]]
    _require(stored.state.value == "editable" and stored.revision == draft.get("revision") == 1
        and stored.operation == (plan.get("request_schema_uri") or plan["operation"])
        and draft.get("binding") == {"operation": stored.operation, "version": stored.version, "schema_digest": stored.schema_digest}
        and stored.version == plan["version"]
        and stored.schema_digest == _public_gateway(plan).operation_draft_schema_digest(stored.operation, stored.version)
        and stored.authority_digest == operation_draft_authority_digest(payload["task_authority"])
        and stored.created_at == stored.updated_at == draft.get("created_at") == draft.get("updated_at")
        and stored.expires_at == draft.get("expires_at") and stored.terminal_at is None
        and stored.schema_version == 2 and stored.composer_digest == operation_composer_digest(stored.operation, stored.version)
        and stored.composition == new_composition(stored.operation, stored.version)
        and stored.check is stored.seal is None
        and len(stored.audit) == 1 and stored.audit[0]["event_type"] == "started"
        and draft.get("contract") == "waapi-skill.operation-draft/v1"
        and draft.get("lifecycle_state") == "editable" and draft.get("business_revision") == 0
        and draft.get("declarations") == [] and all(key in draft and draft[key] is None for key in ("check", "seal", "preview")),
        "rejected binding lacks its pristine Gateway-owned Draft start")
    _require(not (root / "broker/state/transactions").exists(), "rejected binding contains transaction evidence")


def _bound_draft_rejected_read(root, plan, records, *, declaration=False):
    """Prove the one unchanged editable binding preceding an owned-read FAIL."""
    operation = plan.get("request_schema_uri") or plan.get("operation")
    _require((declaration and operation == "ak.wwise.core.object.setAttenuationCurve")
        or (not declaration and plan["read_scope"].get("owned_project_reads") is True
            and operation == "audio.import"), "rejected bound Draft lacks its approved operation scope")
    starts = [row for row in records if row["gateway_arguments"][0] == "draft-start"]
    binds = [row for row in records if row["gateway_arguments"][0] == "draft-bind-object"]
    _require(len(starts) == len(binds) == 1
        and starts[0].get("succeeded") is True and binds[0].get("succeeded") is True
        and starts[0]["sequence"] < binds[0]["sequence"] < records[-1]["sequence"],
        "rejected read lacks its exact accepted Draft binding prefix")
    start, bound = starts[0]["payload"], binds[0]["payload"]
    draft, bound_draft = start["draft"], bound["draft"]
    argv = binds[0]["gateway_arguments"]
    expected_bind = ["draft-bind-object", draft["draft_id"], "--task-authority", start["task_authority"],
        "--expected-revision", "1", *(["--role", "attenuation"] if declaration else []), "--object-id", argv[-1]]
    _require(argv == expected_bind
        and argv[-1] in plan["read_scope"]["object_ids"], "rejected read has another Draft selector")
    stored = load_operation_draft_archive_records((root / "broker/state").absolute(), [draft["draft_id"]])[draft["draft_id"]]
    binding = {"operation": stored.operation, "version": stored.version, "schema_digest": stored.schema_digest}
    _require(stored.state.value == "editable" and stored.revision == bound_draft.get("revision") == 2
        and stored.operation == operation and stored.version == plan["version"]
        and stored.schema_digest == _public_gateway(plan).operation_draft_schema_digest(stored.operation, stored.version)
        and stored.composer_digest == operation_composer_digest(stored.operation, stored.version)
        and stored.authority_digest == operation_draft_authority_digest(start["task_authority"])
        and stored.schema_version == 2 and stored.check is stored.seal is stored.terminal_at is None
        and stored.created_at == draft.get("created_at") == draft.get("updated_at")
        and stored.expires_at == draft.get("expires_at")
        and len(stored.audit) == 2 and [row["event_type"] for row in stored.audit] == ["started", "handles.bound"]
        and stored.updated_at == stored.audit[-1]["timestamp"]
        and draft.get("revision") == 1 and draft.get("binding") == bound_draft.get("binding") == binding
        and all(row.get("contract") == "waapi-skill.operation-draft/v1"
            and row.get("draft_id") == stored.draft_id and row.get("lifecycle_state") == "editable"
            and row.get("business_revision") == 0 for row in (draft, bound_draft))
        and draft.get("declarations") == [] and all(key in draft and draft[key] is None for key in ("check", "seal", "preview")),
        "rejected read changed its editable Draft record or projection")
    session = BusinessDeclarationSession.from_dict(stored.composition.get("business_session"))
    handles = session.handles.as_dict()
    objects = handles["objects"]
    _require(stored.composition == {**new_composition(stored.operation, stored.version), "business_session": session.as_dict()}
        and session.context.task_authority_digest == stored.authority_digest
        and session.context.wwise_version == stored.version
        and session.revision == 0 and not session.declarations and not session.settings
        and session.active_preview is None and not session.preview_audit
        and len(objects) == 1 and not handles["fields"] and not handles["types"],
        "rejected read carries Draft declarations, fields, settings or Preview state")
    obj = objects[0]
    receipt = bound.get("bound_object", {})
    _require((not declaration or (obj.get("role") == receipt.get("role") == "attenuation"
            and obj["object_type"] == "Attenuation"))
        and obj["object_id"] == argv[-1] and all(receipt.get(key) == obj[value] for key, value in
        (("handle", "handle"), ("name", "name"), ("type", "object_type"), ("semantic_kind", "semantic_kind"))),
        "rejected read binding differs from its authenticated receipt")
    pending, identities, count = [plan["before"]], [], 0
    while pending:
        value = pending.pop()
        count += 1
        _require(count <= 2048, "rejected read baseline identity traversal exceeds its bound")
        if isinstance(value, Mapping):
            if value.get("id") == obj["object_id"] and all(key in value for key in ("name", "type", "path")):
                identities.append(value)
            pending.extend(value.values())
        elif isinstance(value, list):
            pending.extend(value)
    _require(len(identities) == 1 and all(identities[0][key] == obj[value] for key, value in
        (("name", "name"), ("type", "object_type"), ("path", "path"))),
        "rejected read stored binding differs from its independent baseline")
    _require(not (root / "broker/state/transactions").exists(), "rejected read contains transaction evidence")


def _declared_import_rejected_check(root, plan, records):
    """Rebuild the bounded editable import prefix without dispatch or writes."""
    _require(plan.get("operation") == "audio.import" and plan.get("unit_id", "").endswith("-M01")
        and plan["read_scope"].get("owned_project_reads") is True,
        "rejected check lacks its approved music import scope")
    drafts = [row for row in records[:-1] if row["gateway_arguments"][0] not in _READS]
    _require([row["gateway_arguments"][0] for row in drafts] ==
        ["draft-start", "draft-bind-object", "draft-declare-import-batch"]
        and all(row.get("accepted") is True and row.get("succeeded") is True for row in drafts),
        "rejected check changed its accepted editable import prefix")
    start, bound, declared = [row["payload"] for row in drafts]
    initial, binding, final = [row["draft"] for row in (start, bound, declared)]
    draft_id, authority = initial["draft_id"], start["task_authority"]
    stored = load_operation_draft_archive_records((root / "broker/state").absolute(), [draft_id])[draft_id]
    directory = root / "broker/state/operation-drafts-v1/records"
    _require([path.name for path in directory.iterdir()] == [draft_id + ".json"], "rejected check contains another Draft record")
    public = _public_gateway(plan)
    schema = public.operation_draft_schema_digest("audio.import", plan["version"])
    expected_binding = {"operation": "audio.import", "version": plan["version"], "schema_digest": schema}
    _require(stored.state.value == "editable" and stored.revision == 3 and stored.operation == "audio.import"
        and stored.version == plan["version"] and stored.schema_digest == schema
        and stored.composer_digest == operation_composer_digest("audio.import", plan["version"])
        and stored.authority_digest == operation_draft_authority_digest(authority) and stored.schema_version == 2
        and stored.check is stored.seal is stored.terminal_at is None
        and stored.created_at == initial.get("created_at") == initial.get("updated_at")
        and stored.expires_at == initial.get("expires_at")
        and len(stored.audit) == 3 and [row["event_type"] for row in stored.audit] ==
            ["started", "handles.bound", "declaration.batch-added"]
        and stored.updated_at == stored.audit[-1]["timestamp"]
        and all(row.get("contract") == "waapi-skill.operation-draft/v1" and row.get("draft_id") == draft_id
            and row.get("lifecycle_state") == "editable" and row.get("revision") == revision
            and row.get("binding") == expected_binding for row, revision in ((initial, 1), (binding, 2), (final, 3)))
        and initial.get("business_revision") == binding.get("business_revision") == 0
        and initial.get("declarations") == []
        and all(row.get(key) is None for row in (initial, binding, final) for key in ("check", "seal", "preview")),
        "rejected check changed its Draft binding, projection or audit")
    argv = drafts[1]["gateway_arguments"]
    parent = plan["before"].get("parent")
    _require(isinstance(parent, dict) and parent.get("type") == "MusicPlaylistContainer"
        and parent.get("id") in plan["read_scope"]["object_ids"]
        and argv == ["draft-bind-object", draft_id, "--task-authority", authority, "--expected-revision", "1", "--object-id", parent["id"]],
        "rejected check changed its independent parent binding")
    session = BusinessDeclarationSession.from_dict(stored.composition.get("business_session"))
    _require(session.context.task_authority_digest == stored.authority_digest
        and session.context.wwise_version == stored.version and session.active_preview is None
        and not session.preview_audit and not session.settings,
        "rejected check changed its business context or Preview state")
    call = bound.get("project_call")
    _require(isinstance(call, dict) and isinstance(call.get("evidence_path"), str), "rejected check lacks its project binding evidence")
    relative = Path(call["evidence_path"]).relative_to(root)
    _require(relative.parts[:2] == ("broker", "evidence"), "rejected check project evidence escaped its archive")
    project_call = _json(root, relative.as_posix())
    project = project_call.get("result")
    _require({key: value for key, value in project_call.items() if key != "result"} == call
        and call.get("api") == "ak.wwise.core.getProjectInfo" and call.get("ok") is True
        and call.get("dry_run") is False and call.get("version") == plan["version"]
        and isinstance(project, dict) and project.get("id") == session.context.project_id
        and project.get("path") == session.context.project_path,
        "rejected check project context differs from its authenticated read")
    expected = BusinessDeclarationSession.create(session.context)
    handles = BusinessHandleRegistry.from_dict(session.handles.as_dict())
    registry = handles.as_dict()
    receipt_object = bound.get("bound_object", {})
    _require(len(registry["objects"]) == 1 and not registry["fields"] and not registry["types"]
        and isinstance(receipt_object.get("handle"), str), "rejected check carries extra handles")
    obj = registry["objects"][0]
    _require(obj["handle"] == receipt_object["handle"] and obj["object_id"] == parent["id"]
        and obj["name"] == parent["name"] and obj["object_type"] == parent["type"]
        and obj["path"] == parent["path"] and obj["semantic_kind"] is obj.get("role") is None,
        "rejected check stored handle differs from its independent parent")
    expected = expected.with_handle_registry(handles)
    _require(all(receipt_object.get(key) == value for key, value in
        (("handle", obj["handle"]), ("name", obj["name"]), ("type", obj["object_type"]), ("semantic_kind", None))),
        "rejected check handle differs from its independent parent")
    args = _scope(plan).public_parser(drafts[2]["gateway_arguments"])
    _require(args.draft_id == draft_id and args.task_authority == authority and args.expected_revision == 2
        and args.new_row and not any((args.new_root_row, args.new_child_row, args.existing_row,
            args.field_value, args.switch_value, args.event)), "rejected check carries another import declaration form")
    order = [identifier for group in args.row_order for identifier in group]
    rows = {identifier: (parent_reference, name, kind) for identifier, parent_reference, name, kind in args.new_row}
    _require(len(rows) == len(args.new_row) == len(order) <= public.AUDIO_IMPORT_BUSINESS_BATCH_MAX_ROWS
        and len(set(order)) == len(order) and set(order) == set(rows), "rejected check import row order is inconsistent")
    fields = {identifier: [] for identifier in order}
    for identifier, key, value in args.field:
        _require(identifier in fields, "rejected check field has another declaration")
        fields[identifier].append((key, value))
    media = plan.get("preview_parameters", {}).get("media")
    _require(isinstance(media, dict) and all(isinstance(value, str) for value in media.values())
        and isinstance(args.media_directory, str), "rejected check lacks its sealed media scope")
    media_ids = set()
    for identifier, filename in args.media_file:
        _require(identifier in fields and identifier not in media_ids and filename not in {"", ".", ".."}
            and not any(character in filename for character in ("/", "\\", "\x00")), "rejected check media row is malformed")
        path = str(Path(args.media_directory) / filename)
        _require(path in media.values(), "rejected check media path exceeds its sealed scope")
        media_ids.add(identifier)
        fields[identifier].append(("media_file", path))
    for identifier in order:
        parent_reference, name, kind = rows[identifier]
        parents = [row for row in expected.declarations if row.declaration_id == parent_reference]
        parent_handle = parents[0].result_handle if len(parents) == 1 else parent_reference
        expected = expected.with_new_declaration(declaration_id=identifier,
            target=NewDescendantTarget(parent_handle, name, kind),
            fields=public._parse_audio_import_business_fields(expected, fields[identifier], allow_switch_value_pair=False))
    business_adapter("audio.import").materialize(expected)
    _require(session.as_dict() == expected.as_dict()
        and stored.composition == {**new_composition(stored.operation, stored.version), "business_session": expected.as_dict()},
        "rejected check composition differs from its accepted public declaration")
    _require(final.get("batch_receipt") == {"contract": "waapi-skill.business-declaration-batch-receipt/v1",
        "chunk_declaration_count": len(order), "cumulative_declaration_count": len(order), "switch_assignment_count": 0}
        and final.get("next_command", {}).get("command") == "draft-check"
        and final["next_command"].get("gateway_argv") == ["draft-check", draft_id, "--task-authority", authority, "--expected-revision", "3"],
        "rejected check declaration projection differs from its stored composition")
    _require(not (root / "broker/state/transactions").exists(), "rejected check contains transaction evidence")


def _receipts(root: Path, plan: Mapping[str, Any], broker: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    records = broker.get("records")
    _require(isinstance(records, list) and len(records) <= 128, "broker receipt count is invalid")
    gate = _scope(plan)
    draft_id = authority = revision = None
    failed_accepted = False
    expected_operation = plan.get("request_schema_uri") or plan.get("operation")
    for index, record in enumerate(records, 1):
        _require(isinstance(record, dict) and record.get("sequence") == index, "broker sequence mismatch")
        for key, digest_key in (("model_argv", "raw_argv_sha256"), ("normalized_model_argv", "argv_sha256")):
            argv = record.get(key)
            _require(isinstance(argv, list) and all(isinstance(item, str) for item in argv)
                and record.get(digest_key) == canonical_digest(argv), "broker argv digest mismatch")
        argv = record.get("gateway_arguments")
        _require(isinstance(argv, list) and all(isinstance(item, str) for item in argv), "invalid Gateway argv")
        for key in ("started_at_unix", "finished_at_unix", "duration_seconds"):
            _require(_finite(record.get(key)), "invalid broker timing")
        _require(record["finished_at_unix"] >= record["started_at_unix"], "backwards broker timing")
        _require(not failed_accepted, "accepted command followed a terminal failed receipt")
        resolved = resolve_gateway_invocation(record["model_argv"], skill_source=Path(plan["skill_source"]),
            invocation_skill_source=workspace_skill_install_path(root / "agent-workspace"),
            shim_directory=root / "broker" / "bin")
        _require(list(resolved.gateway_arguments) == argv
            and list(resolved.normalized_model_argv) == record["normalized_model_argv"], "recorded Gateway argv differs from actual invocation")
        if record.get("accepted") is not True:
            if argv[:1] == ["draft-bind-object"]:
                gate.public_parser(argv)
                _validate_rejected_draft_bind(record, argv=argv, gate=gate,
                    draft_id=draft_id, authority=authority, revision=revision)
            elif argv[:1] == ["draft-declare-core-plan"]:
                _validate_rejected_core_declaration(record, argv=argv, gate=gate,
                    draft_id=draft_id, authority=authority, revision=revision, operation=expected_operation)
            elif argv[:1] == ["draft-check"]:
                _validate_rejected_draft_check(record, argv=argv, gate=gate,
                    draft_id=draft_id, authority=authority, revision=revision, operation=expected_operation)
            else:
                _validate_rejected_read(record, argv=argv, gate=gate)
            _require(index == len(records), "dispatch followed a rejected read")
            failed_accepted = True
            continue
        gate.public_parser(argv)  # Admitted receipts must always be public syntax.
        runner = str((Path(plan["skill_source"]) / "scripts" / "run.py").resolve())
        _require(record.get("runner_command_sha256") == canonical_digest(
            [plan["trusted_python"], runner, "gateway.py", *argv]), "trusted runner command digest mismatch")
        payload = record.get("payload")
        _require(record.get("authenticated") is True and type(record.get("succeeded")) is bool,
                 "broker receipt authentication/outcome mismatch")
        if payload is None:
            _require(record.get("succeeded") is False and record.get("payload_sha256") == ""
                and bool(record.get("payload_error")) and record.get("exit_code") == 125
                and isinstance(record.get("stdout"), str), "missing payload lacks terminal failure evidence")
        else:
            _require(isinstance(payload, dict) and record.get("payload_sha256") == canonical_digest(payload),
                     "broker payload authentication/digest mismatch")
            _require(_decode(record["stdout"].encode("utf-8")) == payload, "stdout differs from receipt payload")
            _require(bool(argv) and payload.get("command") == argv[0], "receipt command mismatch")
        _require(bool(argv), "receipt has no admitted command")
        command = argv[0]
        _require(command in (_READS | _DRAFT_READS | _BUSINESS_EDITS | _DECLARATIONS.get(plan.get("operation"), frozenset())
            | {"draft-start", "preview-from-draft", "transaction-show", "confirm", "execute", "verify"}),
                 "receipt used an unapproved Gateway command")
        semantic = ["runner-owned-version", plan["version"], *argv]
        if command.startswith("draft-") or command == "preview-from-draft":
            if command == "draft-start":
                _require(draft_id is None and argv == ["draft-start", expected_operation], "unexpected second or wrong Draft")
            else:
                _require(len(argv) > 1 and argv[1] == draft_id
                    and "--task-authority" in argv
                    and argv[argv.index("--task-authority") + 1] == authority, "Draft authority changed")
                if command != "draft-inspect":
                    _require("--expected-revision" in argv and argv[argv.index("--expected-revision") + 1] == str(revision),
                             "Draft revision changed")
                    semantic[2 + argv.index("--expected-revision") + 1] = revision
                if command == "draft-bind-object":
                    object_id = argv[argv.index("--object-id") + 1] if "--object-id" in argv else None
                    segments = [argv[position + 1] for position, value in enumerate(argv) if value == "--object-path-segment"]
                    path = "\\" + "\\".join(segments) if segments else None
                    _require(object_id in gate.scope.object_ids or path in plan.get("scoped_paths", {}).values(),
                             "mutation binding exceeds the sealed object scope")
            draft = payload.get("draft") if isinstance(payload, dict) else None
            if isinstance(draft, dict):
                if command == "draft-start":
                    draft_id, authority = draft["draft_id"], payload["task_authority"]
                revision = draft["revision"]
        _require(record.get("semantic_argv_sha256") == canonical_digest(semantic), "semantic argv digest mismatch")
        if command in _READS:
            gate.admit(argv)
            if record.get("succeeded") is True:
                gate.observe(payload)
        if command == "execute" and record.get("succeeded") is True and record.get("allowed_exit_codes") == [0, 2]:
            _validate_branching_execute_payload(payload, exit_code=record.get("runner_exit_code"))
            if payload.get("status") == "indeterminate":
                failed_accepted = True  # terminal non-retryable branch, not a repairable preparation
        if record.get("succeeded") is True:
            _require(record.get("exit_code") == record.get("runner_exit_code")
                and record.get("runner_exit_code") in record.get("allowed_exit_codes", [])
                and not record.get("payload_error"), "successful receipt has inconsistent exit")
        else:
            _require(record.get("exit_code") == 125 and bool(record.get("payload_error")),
                     "failed accepted receipt lacks the Broker terminal failure")
            failed_accepted = True
    return records


def replay_c09_notice(root: Path, result: Any, command_records: Any, *, other_gates: Mapping[str, bool],
                      expected_runtime: Mapping[str, str], expected_binding_sha256: str | None = None, **kwargs: Any) -> bool:
    """Validate preserved independent evidence, never rejudge a model's meaning."""
    from tests.semantic.support.codex_c09_notice_adjudication import decide_c09_notice, verify_c09_review_receipt
    decision = decide_c09_notice(result, command_records, **kwargs)
    try:
        recorded = _json(root, "notice-decision.json")
        _require(canonical_digest(recorded) == canonical_digest(decision), "notice decision binding changed")
        receipt_path = root / "notice-review" / "receipt.json"
        hard_passed = bool(other_gates) and all(value is True for value in other_gates.values())
        if decision["outcome"] != "review_required" or not hard_passed:
            _require(not receipt_path.exists(), "review receipt cannot override deterministic hard gates")
            return hard_passed and decision["outcome"] == "accepted"
        binding = _json(root, "notice-review/invocation-binding.json")
        _require(isinstance(expected_binding_sha256, str) and _SHA.fullmatch(expected_binding_sha256)
            and binding.get("sha256") == expected_binding_sha256, "review invocation binding differs from sealed turn")
        receipt = _json(root, "notice-review/receipt.json")
        return verify_c09_review_receipt(receipt, decision=decision, expected_runtime=expected_runtime, expected_binding=binding)
    except ExpansionArchiveError:
        raise
    except Exception as exc:
        raise ExpansionArchiveError(f"invalid or missing notice review receipt: {exc}") from exc


def _turns(root: Path, plan: Mapping[str, Any], result: Mapping[str, Any],
           budget: Mapping[str, Any], records: list[Mapping[str, Any]], oracle: Mapping[str, Any]) -> list[dict]:
    turns = budget.get("turns")
    _require(isinstance(turns, list) and len(turns) <= len(plan["prompts"]), "turn budget shape is invalid")
    _require(budget.get("hard_seconds") == 600 and budget.get("slow_seconds") == 420, "budget limits changed")
    measurements = budget.get("turn_measurements")
    _require(isinstance(measurements, list) and len(measurements) == len(turns), "missing Agent time measurements")
    elapsed, prefix = 0.0, 0
    for index, turn in enumerate(turns, 1):
        _require(turn.get("index") == index and _finite(turn.get("agent_seconds")), "turn duration is invalid")
        measured = measurements[index - 1]
        _require(all(_finite(measured.get(key)) for key in ("started_monotonic", "finished_monotonic", "elapsed_seconds"))
            and measured["finished_monotonic"] >= measured["started_monotonic"]
            and math.isclose(measured["finished_monotonic"] - measured["started_monotonic"], measured["elapsed_seconds"], abs_tol=1e-6)
            and math.isclose(turn["agent_seconds"], measured["elapsed_seconds"], abs_tol=1e-6), "Agent measurement mismatch")
        if index > 1:
            _require(measured["started_monotonic"] >= measurements[index - 2]["finished_monotonic"], "overlapping Agent turns")
        elapsed += turn["agent_seconds"]
        if turn.get("incomplete") is True:
            _require(not result["passed"] and index == len(turns) and turn.get("gates") == {}, "incomplete turn cannot pass")
            continue
        directory = f"turns/turn-{index:02d}/"
        prompt = _bytes(root, directory + "prompt.txt").decode("utf-8")
        _require(prompt == plan["prompts"][index - 1] + "\n", "turn prompt changed")
        grade = _json(root, directory + "turn-grade.json")
        facts = _json(root, directory + "codex-facts.json")
        events_raw = _bytes(root, directory + "events.jsonl", empty=True)
        events = [_decode(line) for line in events_raw.splitlines() if line]
        final = _bytes(root, directory + "final.txt", empty=True).decode("utf-8")
        _bytes(root, directory + "stderr.txt", empty=True)
        _require(grade.get("index") == index
            and grade.get("prompt_sha256") == hashlib.sha256(prompt[:-1].encode("utf-8")).hexdigest()
            and grade.get("common_gates") == turn.get("gates")
            and set(grade.get("common_gates", {})) == _GATES, "turn grade binding changed")
        count = grade.get("broker_prefix_count")
        _require(type(count) is int and prefix <= count <= len(records), "broker turn prefix is invalid")
        host = (WindowsPowerShellCoreHost(**plan["windows_powershell_core_host"])
                if plan.get("windows_powershell_core_host") else None)
        commands = completed_command_records(events, platform_name=plan["platform_name"], windows_powershell_core_host=host)
        archived_commands = facts.get("command_facts", {}).get("command_records")
        _require(canonical_digest([asdict(command) for command in commands]) == canonical_digest(archived_commands),
                 "Codex command facts differ from raw events")
        resolved_commands = []
        recoverable = recoverable_preprocess_attempt_indexes(commands)
        for command_index, command in enumerate(commands):
            if command_index in recoverable:
                continue
            try:
                resolved = resolve_gateway_invocation(command.argv, skill_source=Path(plan["skill_source"]),
                    invocation_skill_source=workspace_skill_install_path(root / "agent-workspace"),
                    shim_directory=root / "broker" / "bin")
            except ValueError:
                continue  # Skill reads are classified separately below.
            resolved_commands.append((command, resolved))
        turn_records = records[prefix:count]
        _require(len(resolved_commands) == len(turn_records),
                 "raw Codex Gateway command count differs from Broker receipts")
        for (command, resolved), record in zip(resolved_commands, turn_records):
            _require(list(resolved.normalized_model_argv) == record["normalized_model_argv"]
                and list(resolved.gateway_arguments) == record["gateway_arguments"]
                and command.exit_code == record["exit_code"],
                "Broker receipt order differs from raw Codex Gateway commands")
        c09_notice = None
        if index == 1 and "notice_adjudication" in plan:
            artifact = (_transaction(root, oracle["transaction_id"])[0]["artifact"]
                        if oracle.get("transaction_id") else {})
            c09_notice = replay_c09_notice(root / directory, SimpleNamespace(stdout=events_raw.decode("utf-8")),
                commands, version=plan["version"], execute_expected=plan["policy"] == "allow_changes",
                preview_artifact=artifact, before_snapshot=oracle.get("preview_before") or plan["before"],
                transaction_id=oracle.get("transaction_id") or "", user_prompt=plan["prompts"][0],
                other_gates={key: value for key, value in grade["common_gates"].items() if key != "visible_preview_notice"},
                expected_runtime=plan["notice_adjudication"]["runtime"],
                expected_binding_sha256=turn.get("notice_invocation_binding_sha256"))
            _require(grade["common_gates"]["visible_preview_notice"] is c09_notice,
                     "recorded adjudicated notice grade differs from sealed evidence")
        rejected_read = any(record.get("accepted") is False for record in records)
        if result["passed"] or rejected_read:
            classified = classify_task_commands(commands, workspace=root / "agent-workspace",
                skill_source=Path(plan["skill_source"]), expected_wwise_version=plan["version"],
                expected_gateway_subcommands=tuple(sorted({row["gateway_arguments"][0] for row in records if row["gateway_arguments"]})))
            references = classified.skill_read_files
            allowed_references = {"SKILL.md", "references/waapi-operate.md", "references/waapi-query.md",
                                  "references/waapi-setup.md", "references/waapi-coverage.md"}
            _require(not classified.non_gateway_unexpected_commands and not classified.discovery_commands
                and not classified.direct_waapi_client_commands and not classified.write_like_commands
                and len(references) <= 12 and set(references).issubset(allowed_references)
                and (index != 1 or bool(references) and references[0] == "SKILL.md")
                and len(commands) - len(recoverable_preprocess_attempt_indexes(commands))
                    == count - prefix + len(classified.allowed_read_commands), "raw commands violate Skill-only/no-bypass gates")
            _require(not result["passed"] or index != 1 or (c09_notice if c09_notice is not None else expansion_preview_notice(SimpleNamespace(stdout=events_raw.decode("utf-8")),
                commands, version=plan["version"], execute_expected=plan["policy"] == "allow_changes",
                preview_artifact=_transaction(root, oracle["transaction_id"])[0]["artifact"],
                before_snapshot=oracle.get("preview_before") or plan["before"])),
                     "visible post-Preview notice is missing")
            if rejected_read:
                false_gates = {"broker_provenance", "policy_checkpoint", "visible_preview_notice"}
                _require(result["passed"] is False and grade.get("passed") is False
                    and set(grade.get("errors", [])) == false_gates
                    and all(value is (key not in false_gates) for key, value in grade["common_gates"].items()),
                    "read rejection changed the original failed gates")
                session = audit_session_events(events)
                _require(session.file_change_count == session.collab_call_count == 0,
                    "read rejection contains file changes or collaboration")
            _require((not result["passed"] or grade.get("passed") is True and not grade.get("errors")
                and all(value is True for value in grade["common_gates"].values()))
                and audit_session_events(events).passed
                and facts.get("thread_id") == result.get("thread_id")
                and final_agent_message(events) == facts.get("final_response")
                and final == facts.get("final_response", "") + "\n"
                and facts.get("exit_status") == 0 and facts.get("timed_out") is False
                and facts.get("prompt_audit", {}).get("passed") is True
                and facts.get("prompt_audit", {}).get("has_memory") is False
                and facts.get("isolation_audit", {}).get("passed") is True
                and facts.get("skill_tree_unchanged") is True
                and facts.get("skill_tree_sha256_before") == facts.get("skill_tree_sha256_after"),
                     "passing turn lacks complete raw session evidence")
        prefix = count
    _require(_finite(budget.get("elapsed_seconds")) and math.isclose(elapsed, budget["elapsed_seconds"], abs_tol=1e-6)
        and result.get("agent_seconds") == budget["elapsed_seconds"]
        and budget.get("slow") is (elapsed >= 420) and result.get("slow") is budget["slow"]
        and result.get("turns") == turns, "cumulative Agent budget mismatch")
    if any(record.get("accepted") is False for record in records):
        _require(prefix == len(records), "completed rejected-read turn omitted a Broker receipt")
    if result["passed"]:
        _require(elapsed <= 600 and len(turns) == len(plan["prompts"]) and prefix == len(records),
                 "passing task exhausted budget or omitted a turn")
    return turns


def verify_expansion_task_archive(task_root: Path, *, expected_unit_id: str,
        expected_version: str, expected_inputs_sha256: str) -> dict[str, Any]:
    """Recompute complete task evidence; campaign seal validation is separate."""
    try:
        return _verify_task(Path(task_root), expected_unit_id, expected_version, expected_inputs_sha256)
    except ExpansionArchiveError:
        raise
    except Exception as exc:
        raise ExpansionArchiveError(f"invalid expansion archive: {type(exc).__name__}: {exc}") from exc


def _verify_task(root: Path, unit_id: str, version: str, inputs_sha256: str) -> dict[str, Any]:
    _require(isinstance(inputs_sha256, str) and _SHA.fullmatch(inputs_sha256), "invalid expected inputs digest")
    plan = _json(root, "expansion-plan.json")
    digest = plan.pop("sha256", None)
    _require(digest == canonical_digest(plan), "plan digest mismatch")
    _require(plan.get("inputs_sha256") == inputs_sha256, "immutable campaign inputs mismatch")
    _require(plan.get("contract") == "waapi-skill.integration-expansion-task-plan/v1"
        and plan.get("unit_id") == unit_id and plan.get("version") == version, "task plan identity mismatch")
    if "notice_adjudication" in plan:
        from tests.semantic.support.codex_c09_notice_adjudication import reviewer_configuration
        review = plan["notice_adjudication"]
        _require(unit_id.endswith("-C09") and isinstance(review, dict)
            and set(review) == {"configuration", "runtime"} and review["configuration"] == reviewer_configuration()
            and isinstance(review["runtime"], dict), "adjudication is outside the pinned C09 contract")
    module, case_id = _case(plan)
    _require(unit_id == f"EXP{version[2:4]}-{case_id}" and version in {"2022.1", "2025.1"}
        and (case_id, version) != ("M05", "2022.1"), "unit is not an Agent case")
    policy = "ask_before_changes" if case_id in {"C01", "C03"} else "allow_changes"
    _require(plan.get("policy") == policy and isinstance(plan.get("prompts"), list)
        and len(plan["prompts"]) == (2 if policy == "ask_before_changes" else 1)
        and all(isinstance(prompt, str) and prompt for prompt in plan["prompts"]), "prompt/policy contract changed")
    required = getattr(module, case_id + "_ASSERTIONS")
    _require(set(plan.get("required_assertions", [])) == required, "oracle obligations changed")
    result = _json(root, "expansion-task-result.json")
    _require(type(result.get("passed")) is bool and result.get("unit_id") == unit_id
        and result.get("version") == version and result.get("plan_sha256") == digest, "terminal result binding mismatch")
    broker = _json(root, "expansion-broker.json")
    budget = _json(root, "expansion-agent-budget.json")
    oracle = _json(root, "expansion-oracle.json")
    records = _receipts(root, plan, broker)
    turns = _turns(root, plan, result, budget, records, oracle)
    mutations = [row for row in records if row.get("accepted") is True and row["gateway_arguments"][:1] == ["execute"]]
    _require(len(mutations) <= 1, "more than one execution was admitted")
    _require(oracle.get("before") == plan["before"], "independent pre-state changed")
    rejected_read = any(record.get("accepted") is False for record in records)
    if rejected_read:
        rejected_declaration = records[-1]["gateway_arguments"][:1] == ["draft-declare-core-plan"]
        rejected_check = records[-1]["gateway_arguments"][:1] == ["draft-check"]
        allowed_prefix = _READS | {"draft-start", "draft-bind-object"}
        if rejected_check:
            allowed_prefix |= {"draft-declare-import-batch"}
        _require(all(record["gateway_arguments"][0] in allowed_prefix for record in records[:-1]),
            "rejected command has another mutation or declaration in its accepted prefix")
        _require(result["passed"] is False and result.get("status") == "FAIL"
            and result.get("terminal_state") == "unprepared"
            and len(turns) == 1 and not turns[0].get("incomplete")
            and (rejected_declaration or rejected_check or records[-1]["gateway_arguments"][0] in allowed_prefix)
            and oracle.get("transaction_id") is None and oracle.get("artifact_hash") is None
            and oracle.get("authorization") is None and oracle.get("permit") is None
            and oracle.get("after") is None and result.get("assertions") == {}
            and broker.get("passed") is False and broker.get("complete") is False,
            "rejected read cannot carry a Preview, mutation or successful outcome")
        if rejected_check:
            _declared_import_rejected_check(root, plan, records)
            _require(all(key in oracle and oracle[key] is None for key in
                ("transaction_id", "artifact_hash", "authorization", "permit", "after", "preview_before", "preview_after", "gateway_verification_state"))
                and result.get("gateway_verification_state") is None and oracle.get("assertions") == {},
                "rejected check carries preparation or verification evidence")
        elif records[-1]["gateway_arguments"][0] == "draft-bind-object":
            _pristine_rejected_draft(root, plan, records)
            _require(all(key in oracle and oracle[key] is None for key in
                ("transaction_id", "artifact_hash", "authorization", "permit", "after", "preview_before", "preview_after", "gateway_verification_state"))
                and result.get("gateway_verification_state") is None,
                "rejected binding carries preparation or verification evidence")
        else:
            if any(record["gateway_arguments"][0] == "draft-start" for record in records):
                _bound_draft_rejected_read(root, plan, records, declaration=rejected_declaration)
                _require(all(key in oracle and oracle[key] is None for key in
                    ("transaction_id", "artifact_hash", "authorization", "permit", "after", "preview_before", "preview_after", "gateway_verification_state"))
                    and result.get("gateway_verification_state") is None,
                    "rejected bound read carries preparation or verification evidence")
            else:
                _require(all(record["gateway_arguments"][0] in _READS for record in records), "rejected read contains Draft actions")
        accepted_names = [record.get("step_name") for record in records if record.get("accepted") is True]
        _require(all(isinstance(name, str) and name for name in accepted_names)
            and len(accepted_names) == len(set(accepted_names))
            and broker.get("expected_step_names") == broker.get("consumed_step_names") == accepted_names,
            "rejected read lacks its exact consumed Broker prefix")
        reconciliation = oracle.get("reconciliation")
        _require(isinstance(reconciliation, dict) and reconciliation.get("status") == "completed"
            and reconciliation.get("snapshot") == plan["before"]
            and reconciliation.get("child_reaped") is True and reconciliation.get("subprocesses_reaped") is True,
            "rejected read lacks complete unchanged-state reconciliation")
    transaction_id = oracle.get("transaction_id")
    events = ()
    preview_approval: bool | None = None
    transactions_directory = root / "broker" / "state" / "transactions"
    if transactions_directory.exists():
        _require(not path_is_link_or_reparse(transactions_directory), "transaction directory is linked")
        _require({path.name for path in transactions_directory.iterdir()}
            == ({transaction_id} if transaction_id else set()), "unrecorded transaction in the Agent store")
    if transaction_id is not None:
        preview, events, state = _transaction(root, transaction_id)
        _require(oracle.get("artifact_hash") == preview["artifact_hash"], "oracle transaction binding mismatch")
        _require(oracle.get("preview_before") == oracle.get("preview_after")
            and isinstance(oracle.get("preview_before"), dict), "Preview changed business state")
        parameters = dict(plan["preview_parameters"])
        for key in ("replacement",):
            if key in parameters:
                parameters[key] = Path(parameters[key])
        for key in ("mappings", "media"):
            if key in parameters:
                parameters[key] = {name: Path(path) for name, path in parameters[key].items()}
        preview_approval = getattr(module, "approve_" + case_id.lower() + "_preview")(
            preview["artifact"], **parameters)
        _require(type(preview_approval) is bool, "adapter Preview approval is not an exact boolean")
        recorded_approval = oracle.get("preview_approved")
        if preview_approval is True:
            _require("preview_approved" not in oracle or recorded_approval is True,
                     "preview approval record differs from the independent adapter")
        else:
            preview_receipts = [row for row in records if row.get("accepted") is True
                and row["gateway_arguments"][:1] == ["preview-from-draft"]]
            _require(not result["passed"] and recorded_approval is False
                and "preview_approved" in oracle,
                "rejected Preview lacks an explicit false preview approval record")
            _require(len(preview_receipts) == 1 and preview_receipts[0].get("succeeded") is True
                and preview_receipts[0].get("payload", {}).get("transaction_id") == transaction_id
                and preview_receipts[0].get("payload", {}).get("artifact_hash") == preview["artifact_hash"],
                "rejected Preview identity is not bound to its authenticated Gateway receipt")
            _require(not any(row["gateway_arguments"][:1] in (["confirm"], ["execute"])
                    for row in records)
                and not any(event.get("to_state") in {"confirmed", "executing"} for event in events)
                and "authorization" in oracle and oracle["authorization"] is None
                and "permit" in oracle and oracle["permit"] is None,
                "rejected Preview has a confirmation or execution authorization")
            _require(oracle.get("after") is None and oracle.get("assertions") == {}
                and oracle.get("gateway_verification_state") is None
                and result.get("assertions", {}) == {}
                and result.get("gateway_verification_state") is None,
                "rejected Preview claims post-execution business verification")
        executed_events = [event for event in events if event["to_state"] == "executing"]
        # Admission consumes the at-most-once reservation before launching the
        # subprocess. A timeout can precede Gateway begin_execution; the journal
        # proves actual dispatch, while a missing receipt never permits retry.
        successful_mutations = [row for row in mutations if row.get("succeeded") is True]
        _require(len(successful_mutations) <= len(executed_events) <= len(mutations),
                 "execution receipt/journal disagreement")
        if mutations:
            prefixes = [_json(root, f"turns/turn-{index:02d}/turn-grade.json")["broker_prefix_count"]
                        for index, turn in enumerate(turns, 1) if not turn.get("incomplete")]
            _authorization(plan, oracle, events, records, turns, preview, prefixes)
        if result["passed"]:
            _require(isinstance(oracle.get("before"), dict)
                and isinstance(oracle.get("after"), dict),
                "passing archive lacks independent before/post-state for oracle replay")
        if oracle.get("after") is not None:
            assertions = getattr(module, "verify_" + case_id.lower())(
                oracle["before"], oracle["after"], **plan["oracle_parameters"])
            _require(assertions == oracle.get("assertions") == result.get("assertions")
                and set(assertions) == required, "independent oracle replay mismatch")
        if result["passed"]:
            expected_state = "result_schema_checked" if case_id == "C08" else "verified"
            verification_receipts = [row for row in records if row.get("accepted") is True
                and row["gateway_arguments"][:1] == ["verify"]]
            _require(state["state"] == oracle.get("gateway_verification_state")
                == result.get("gateway_verification_state") == expected_state
                and len(mutations) == 1 and bool(oracle.get("assertions"))
                and len(verification_receipts) == 1
                and verification_receipts[0]["sequence"] > mutations[0]["sequence"]
                and verification_receipts[0]["payload"].get("state") == expected_state
                and all(value is True for value in oracle["assertions"].values()), "business PASS lacks a complete verified effect")
    else:
        _require(not result["passed"] and not mutations, "passing/executed archive has no transaction")
    if result["passed"]:
        _require(broker.get("passed") is True and broker.get("complete") is True
            and all(row.get("succeeded") is True for row in records)
            and broker.get("expected_step_names") == broker.get("consumed_step_names")
            == [row["step_name"] for row in records], "passing Broker evidence is incomplete")
    infrastructure = result.get("infrastructure")
    if infrastructure is not None:
        _require(isinstance(infrastructure, dict) and bool(turns), "infrastructure classification lacks raw turn evidence")
        directory = f"turns/turn-{len(turns):02d}/"
        raw_events = [_decode(line) for line in _bytes(root, directory + "events.jsonl", empty=True).splitlines() if line]
        facts = _json(root, directory + "codex-facts.json")
        observed = classify_codex_infrastructure_failure(raw_events,
            stderr=_bytes(root, directory + "stderr.txt", empty=True).decode("utf-8"), timed_out=facts.get("timed_out") is True)
        _require(observed is not None and asdict(observed) == infrastructure,
                 "infrastructure classification differs from raw pre-action evidence")
    original_status = classify_expansion_outcome(passed=result["passed"], records=records, events=events,
                                                 infrastructure=infrastructure)
    if preview_approval is False:
        _require(original_status == "FAIL", "rejected Preview did not remain an ordinary business FAIL")
    reconciliation = oracle.get("reconciliation")
    if reconciliation is not None:
        _require(not result["passed"] and isinstance(reconciliation, dict)
            and reconciliation.get("status") in {"completed", "error"}
            and _finite(reconciliation.get("elapsed_seconds"))
            and reconciliation.get("seconds") == 30 and reconciliation.get("read_seconds") == 10
            and type(reconciliation.get("child_reaped")) is bool
            and type(reconciliation.get("subprocesses_reaped")) is bool,
            "reconciliation receipt lacks bounded timing/cleanup evidence")
        if reconciliation["status"] == "completed":
            _require(isinstance(reconciliation.get("snapshot"), dict)
                and len(json.dumps(reconciliation["snapshot"], ensure_ascii=False).encode("utf-8")) <= 131_072
                and reconciliation.get("snapshot_sha256") == canonical_digest(reconciliation["snapshot"]),
                "reconciliation snapshot digest or bounds changed")
        else:
            error = reconciliation.get("error")
            _require(isinstance(error, dict) and isinstance(error.get("type"), str)
                and isinstance(error.get("message"), str) and len(error["message"].encode("utf-8")) <= 2048,
                "reconciliation error is missing or unbounded")
        if reconciliation["child_reaped"] is not True or reconciliation["subprocesses_reaped"] is not True:
            original_status = "BLOCKED"
    _require(result.get("status", original_status) == original_status, "original outcome classification changed")
    if "status" in result and not result["passed"]:
        _require(reconciliation is not None, "classified negative outcome omitted reconciliation")
    return {"archive_valid": True, "original_status": original_status,
        "business_pass": result["passed"], "preview_approved": preview_approval,
        "gateway_verification_state": result.get("gateway_verification_state"),
        "agent_seconds": budget["elapsed_seconds"], "slow": budget["slow"], "reconciliation": reconciliation,
        "turn_count": len(turns), "execution_reservations": len(mutations),
        "executions": len(executed_events) if transaction_id is not None else 0}


def _authorization(plan, oracle, events, records, turns, preview, prefixes):
    policy = plan["policy"]
    explicit = policy == "ask_before_changes"
    auth_events = [event for event in events if event["to_state"] in {"confirmed", "policy_authorized"}]
    _require(len(auth_events) == 1, "execution lacks one durable authorization")
    auth = auth_events[0]
    _require(auth["to_state"] == ("confirmed" if explicit else "policy_authorized"), "authorization mode mismatch")
    authorization = oracle.get("authorization")
    _require(isinstance(authorization, dict) and authorization.get("explicit_confirmation") is explicit,
             "authorization receipt mismatch")
    _require(authorization.get("mode") == ("explicit_confirmation" if explicit else "policy_authorization"),
             "authorization mode projection mismatch")
    if not explicit:
        details = auth["details"]
        _require(details.get("policy") == "allow_changes" and details.get("explicit_confirmation") is False
            and details.get("authority") == authorization.get("authority") == "caller_asserted_current_user_change_request",
                 "allow configuration is not durable policy authorization")
    preview_rows = [row for row in records if row.get("accepted") is True and row["gateway_arguments"][:1] == ["preview-from-draft"]]
    execute = next(row for row in records if row.get("accepted") is True and row["gateway_arguments"][:1] == ["execute"])
    _require(len(preview_rows) == 1 and preview_rows[0]["sequence"] < execute["sequence"], "execution preceded unique Preview")
    for record in records:
        if record.get("accepted") is True and record["gateway_arguments"][:1] in (["execute"], ["verify"], ["confirm"], ["transaction-show"]):
            _require(record["gateway_arguments"][1] == preview["transaction_id"], "receipt refers to another transaction")
            if record["gateway_arguments"][0] in {"execute", "verify"} and record.get("succeeded") is not False:
                _require(record["payload"].get("transaction_id") == preview["transaction_id"]
                    and record["payload"].get("artifact_hash") == preview["artifact_hash"], "effect receipt is misbound")
    permit = oracle.get("permit")
    _require(isinstance(permit, dict) and permit.get("transaction_id") == preview["transaction_id"]
        and permit.get("artifact_sha256") == preview["artifact_hash"]
        and _SHA.fullmatch(str(permit.get("authorization_nonce", "")))
        and permit.get("preview_turn") == 1 and permit.get("authorized_turn") == (2 if explicit else 1),
             "runner authorization is not bound to the immutable Preview and user turn")
    if explicit:
        _require(len(turns) == 2, "confirmation has no later user turn")
        confirms = [row for row in records if row.get("accepted") is True and row["gateway_arguments"][:1] == ["confirm"]]
        _require(len(confirms) == 1 and confirms[0]["sequence"] < execute["sequence"], "confirmation receipt is missing")
        _require(len(prefixes) == 2 and preview_rows[0]["sequence"] <= prefixes[0]
            < confirms[0]["sequence"] < execute["sequence"] <= prefixes[1], "confirmation is not in the later user turn")
        awaiting = next(event for event in events if event["to_state"] == "awaiting_confirmation")
        token = confirmation_token_for(transaction_id=preview["transaction_id"], artifact_hash=preview["artifact_hash"],
            state="awaiting_confirmation", event_sequence=awaiting["sequence"], last_event_hash=awaiting["event_hash"])
        argv = confirms[0]["gateway_arguments"]
        _require(argv == ["confirm", preview["transaction_id"], "--confirmation-token", token],
                 "confirmation token is misbound")


def verify_expansion_boundary_archive(scenario_root: Path, *, expected_unit_id: str,
        expected_version: str, expected_inputs_sha256: str) -> dict[str, Any]:
    """M05/2022 unavailable-reference evidence is never an Agent/business PASS."""
    try:
        outcome = _json(Path(scenario_root), "outcome.json")
        _require((expected_unit_id, expected_version) == ("EXP22-M05", "2022.1")
            and outcome.get("scenario_id") == expected_unit_id and outcome.get("version") == expected_version
            and outcome.get("inputs_sha256") == expected_inputs_sha256
            and outcome.get("status") == "BOUNDARY_PROVEN"
            and outcome.get("task_root") is None and outcome.get("thread_id") is None, "boundary identity/outcome mismatch")
        boundary = outcome["checks"]["capability_boundary"]
        _require(boundary.get("case_id") == "M05" and boundary.get("version") == "2022.1"
            and boundary.get("agent_started") is False and boundary.get("business_pass") is False,
                 "boundary was conflated with Agent or business success")
        evidence = boundary["evidence"]
        observed = evidence["public_observation"]
        unresolved = {row["meaning"]: row["candidate_names"] for row in observed["agent_result"]["unresolved"]}
        _require(observed.get("ok") is True and observed.get("status") == "needs_clarification"
            and unresolved.get("Trigger") == [] and isinstance(unresolved.get("Segment"), list)
            and "Segment" not in unresolved["Segment"] and bool(evidence.get("identity_before"))
            and evidence["identity_before"] == evidence.get("identity_after")
            and evidence.get("agent_executed") is False and evidence.get("business_effect_verified") is False,
                 "unavailable references were not independently reproduced")
        return {"archive_valid": True, "boundary_proven": True, "business_pass": False,
                "agent_started": False, "original_status": "BOUNDARY_PROVEN"}
    except ExpansionArchiveError:
        raise
    except Exception as exc:
        raise ExpansionArchiveError(f"invalid boundary archive: {exc}") from exc
