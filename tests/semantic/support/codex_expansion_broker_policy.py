"""Closed dynamic business-Draft admission for the expansion Broker mode."""

from __future__ import annotations

import argparse
import importlib.util
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping, Sequence

from wwise_waapi.transactions import TransactionStore
from tests.semantic.support.codex_expansion_cases import PreparedExpansionCase
from tests.semantic.support.codex_expansion_policy import (
    BoundedExpansionReads, ExpansionPolicyError, ExpansionReadScope,
    ExpansionTransaction, canonical_digest,
)


_DECLARATIONS = {
    "audio.import": frozenset({"draft-declare-import-batch", "draft-declare-new", "draft-declare-existing", "draft-business-configure"}),
    "object.setRTPC": frozenset({"draft-declare-rtpc", "draft-business-configure"}),
    "object.createPlugin": frozenset({"draft-declare-existing", "draft-business-configure"}),
    "object.setReference": frozenset({"draft-declare-field-change", "draft-business-configure"}),
    "waapi.call": frozenset({"draft-declare-core-plan", "draft-business-configure"}),
}
_READ_COMMANDS = frozenset({"status", "operations", "query-schema", "operation-schema", "request-schema", "query-object", "metadata"})
_DRAFT_READS = frozenset({"draft-bind-object", "draft-discover-fields", "draft-discover-types", "draft-inspect", "draft-check"})
_BUSINESS_EDITS = frozenset({"draft-revise-declaration", "draft-remove-declaration", "draft-add-media"})


class ExpansionBrokerPolicy:
    """One business effect, variable safe construction, one immutable transaction.

    The profile's case adapter owns approval and before/after observations.
    The Agent never receives this instance or the fixture assertions.
    """

    def __init__(self, *, prepared: PreparedExpansionCase, version: str, skill_source: Path,
                 scoped_paths: Mapping[str, str]) -> None:
        if prepared.operation not in _DECLARATIONS:
            raise ExpansionPolicyError("expansion case has no closed declaration family")
        self.prepared = prepared
        self.version = version
        self.operation = prepared.request_schema_uri or prepared.operation
        self.paths = dict(scoped_paths)
        if not set(self.paths).issubset(prepared.read_object_ids):
            raise ExpansionPolicyError("fixture paths exceed the sealed object identities")
        self.reads = BoundedExpansionReads(ExpansionReadScope(
            object_ids=prepared.read_object_ids, operations=frozenset({self.operation}),
            includes=prepared.read_includes, fields=prepared.read_fields,
            relationship_sources=prepared.relationship_sources,
            curve_roles=prepared.read_curve_roles, platforms=prepared.read_platforms,
            owned_project_reads=True,
        ), public_parser=self._parse)
        self.transaction = ExpansionTransaction(
            policy=prepared.policy, request_prompt_sha256=canonical_digest(prepared.prompt),
            required_assertions=prepared.required_assertions, approve_preview=prepared.approve_preview,
            accepted_verification_states=prepared.accepted_verification_states,
        )
        module_path = skill_source / "scripts" / "gateway.py"
        spec = importlib.util.spec_from_file_location("waapi_expansion_public_parser", module_path)
        if spec is None or spec.loader is None:
            raise ExpansionPolicyError("public Gateway parser is unavailable")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        self.gateway_module = module
        self.parser = module.build_parser()
        self.calls = 0
        self.draft_id: str | None = None
        self.authority: str | None = None
        self.revision: int | None = None
        self.draft_start_name: str | None = None
        self.last_draft_name: str | None = None
        self.bound_handles: set[str] = set()
        self.transaction_id: str | None = None
        self.artifact_hash: str | None = None
        self.before_preview: str | None = None
        self.permit = None
        self.assertions: Mapping[str, bool] = {}
        self.turn = 0
        self.turn_prompt = ""
        self.oracle_evidence: dict[str, Any] = {
            "contract": "waapi-skill.integration-expansion-oracle/v1",
            "before": prepared.before, "after": None,
            "preview_before": None, "preview_after": None,
            "required_assertions": sorted(prepared.required_assertions), "assertions": {},
            "transaction_id": None, "artifact_hash": None,
            "authorization": None, "permit": None, "gateway_verification_state": None,
        }
        self.preparation_failures: list[Mapping[str, Any]] = []

    def repairable_preparation(self, command: str) -> bool:
        return command in (_DRAFT_READS | _BUSINESS_EDITS | _DECLARATIONS[self.prepared.operation]) and self.transaction.state == "unprepared"

    @property
    def complete(self) -> bool:
        return self.transaction.state == "verified"

    def begin_turn(self, index: int, prompt: str | None = None) -> None:
        self.transaction.begin_turn(index)
        self.turn = index
        self.turn_prompt = self.prepared.prompt if index == 1 else (prompt or "")

    def _parse(self, argv: Sequence[str]) -> argparse.Namespace:
        if not argv or argv[0].startswith("-") or len(argv) > 256:
            raise ExpansionPolicyError("runner owns global Gateway options and argv capacity")
        try:
            return self.parser.parse_args(["--version", self.version, *argv])
        except (SystemExit, ValueError) as exc:
            raise ExpansionPolicyError("command does not satisfy the public Gateway parser") from exc

    def prepare(self, argv: Sequence[str], *, state_directory: Path):
        from tests.semantic.support.codex_gateway_broker import ExpectedGatewayStep, ResponseBinding
        if self.calls >= 96:
            raise ExpansionPolicyError("case command budget exhausted")
        self.calls += 1
        argv = tuple(argv)
        args = self._parse(argv)
        command = args.command
        name = f"expansion.step.{self.calls:04d}"
        values: list[Any] = list(argv[1:])
        if command in _READ_COMMANDS:
            self.reads.admit(argv)
            return ExpectedGatewayStep(name, command, tuple(values))
        if self.complete:
            raise ExpansionPolicyError("business effect is already complete; only scoped reads remain")
        if command == "draft-start":
            if argv != ("draft-start", self.operation) or self.draft_id is not None:
                raise ExpansionPolicyError("only the sealed operation may start one Draft")
            self.draft_start_name = name
        elif command in _DRAFT_READS | _BUSINESS_EDITS | _DECLARATIONS[self.prepared.operation] | {"preview-from-draft"}:
            if (self.transaction.state != "unprepared" or not self.draft_id
                    or getattr(args, "draft_id", None) != self.draft_id
                    or getattr(args, "task_authority", None) != self.authority
                    or (command != "draft-inspect" and getattr(args, "expected_revision", None) != self.revision)):
                raise ExpansionPolicyError("Draft identity, authority or revision is stale")
            if command == "draft-bind-object":
                object_id = getattr(args, "object_id", None)
                segments = getattr(args, "object_path_segment", None)
                # The production parser's destination is checked below too;
                # no inferred type/name or descendant selector can widen scope.
                segments = segments or getattr(args, "object_path_segments", None)
                expected_path = "\\" + "\\".join(segments) if segments else None
                if ((not isinstance(object_id, str) or object_id.upper() not in {key.upper() for key in self.prepared.read_object_ids})
                        and expected_path not in self.paths.values()):
                    raise ExpansionPolicyError("bound object is outside the approved fixture")
            if command == "draft-discover-fields":
                handle = getattr(args, "object_handle", None)
                if handle is not None and handle not in self.bound_handles:
                    raise ExpansionPolicyError("field discovery has no scoped object handle")
            values[0] = ResponseBinding(self.draft_start_name, "/draft/draft_id")
            authority_index = values.index("--task-authority") + 1
            values[authority_index] = ResponseBinding(self.draft_start_name, "/task_authority")
            if "--expected-revision" in values:
                revision_index = values.index("--expected-revision") + 1
                values[revision_index] = ResponseBinding(self.last_draft_name, "/draft/revision")
            if command == "preview-from-draft":
                # Business adapters may auto-apply Preview; the persisted
                # authorization state, not an optional transport flag, is proof.
                self.oracle_evidence["preview_before"] = self.prepared.snapshot()
                self.before_preview = canonical_digest(self.oracle_evidence["preview_before"])
        elif command in {"transaction-show", "confirm", "execute", "verify"}:
            if getattr(args, "transaction_id", None) != self.transaction_id or self.transaction_id is None:
                raise ExpansionPolicyError("transaction is outside the current Preview")
            if (self.transaction.state == "preview_rejected"
                    and command in {"confirm", "execute", "verify"}):
                raise ExpansionPolicyError("confirm, execute and verification are unavailable for a rejected Preview")
            store = TransactionStore(state_directory)
            preview = store.load_preview(self.transaction_id)
            if preview.artifact_hash != self.artifact_hash:
                raise ExpansionPolicyError("sealed Preview changed")
            if command == "confirm":
                if self.prepared.policy != "ask_before_changes" or self.turn < 2:
                    raise ExpansionPolicyError("confirmation requires the later runner-owned user turn")
            if command == "execute":
                record = store.load(self.transaction_id)
                events = store.read_events(self.transaction_id)
                authorization = self.gateway_module.transaction_authorization(record=record, events=events)
                self.oracle_evidence["authorization"] = authorization
                explicit = self.prepared.policy == "ask_before_changes"
                if authorization.get("explicit_confirmation") is not explicit:
                    raise ExpansionPolicyError("durable Gateway authorization does not match case policy")
                if self.permit is None:
                    if explicit and not self.turn_prompt:
                        raise ExpansionPolicyError("later confirmation prompt was not supplied by the runner")
                    self.permit = self.transaction.authorize(
                        turn_prompt_sha256=canonical_digest(self.turn_prompt),
                        explicit_intent="confirm_current_preview" if explicit else "perform_changes",
                    )
                self.transaction.reserve_execute(self.permit, live_artifact_sha256=preview.artifact_hash,
                                                 gateway_authorization_bound=True)
                self.oracle_evidence["permit"] = asdict(self.permit)
            if command == "verify" and self.transaction.state != "executed":
                raise ExpansionPolicyError("verification needs one proven completed execution")
        else:
            raise ExpansionPolicyError("command is outside the expansion business surface")
        return ExpectedGatewayStep(name, command, tuple(values), allowed_exit_codes=(0, 2) if command == "execute" else (0,))

    def observe(self, step, payload: Mapping[str, Any], *, state_directory: Path) -> None:
        command = step.subcommand
        if command in _READ_COMMANDS:
            self.reads.observe(payload)
            return
        if (self.repairable_preparation(command)
                and (payload.get("ok") is False or payload.get("status") == "needs_clarification")):
            # Preparation has no project write path. A failed declaration may
            # only be retried against the same durable Draft revision.
            from wwise_waapi.operation_drafts import OperationDraftStore
            record = OperationDraftStore(state_directory).inspect(self.draft_id, task_authority=self.authority)
            actual_revision = record.revision if hasattr(record, "revision") else record["revision"]
            if actual_revision != self.revision:
                raise ExpansionPolicyError("failed preparation changed its durable Draft revision")
            self.preparation_failures.append(dict(payload))
            return
        if command == "draft-start":
            self.draft_id = payload["draft"]["draft_id"]
            self.authority = payload["task_authority"]
        draft = payload.get("draft")
        if isinstance(draft, Mapping):
            self.revision = draft["revision"]
            self.last_draft_name = step.name
        bound = payload.get("bound_object")
        if isinstance(bound, Mapping) and isinstance(bound.get("handle"), str):
            self.bound_handles.add(bound["handle"])
        if command == "preview-from-draft":
            transaction_id = payload["transaction_id"]
            preview = TransactionStore(state_directory).load_preview(transaction_id)
            preview_after = self.prepared.snapshot()
            preview_after_sha256 = canonical_digest(preview_after)
            self.oracle_evidence["preview_after"] = preview_after
            if (self.transaction.state != "unprepared" or self.turn < 1
                    or not isinstance(transaction_id, str) or not transaction_id.startswith("tx1-")
                    or preview.transaction_id != transaction_id
                    or preview.artifact_hash != canonical_digest(preview.artifact)
                    or self.before_preview is None or self.before_preview != preview_after_sha256):
                raise ExpansionPolicyError("Preview changed state or failed independent effect approval")
            approval = self.prepared.approve_preview(preview.artifact)
            if type(approval) is not bool:
                raise ExpansionPolicyError("Preview approval did not return an exact boolean")
            if approval is False:
                # Preserve the authenticated Gateway Preview for an ordinary
                # business FAIL, while withholding the runner-owned execution
                # permit and every later confirmation/execution action.
                self.transaction_id, self.artifact_hash = transaction_id, preview.artifact_hash
                self.transaction.state = "preview_rejected"
                self.oracle_evidence.update(transaction_id=transaction_id,
                    artifact_hash=preview.artifact_hash, preview_approved=False)
                return
            self.transaction.seal_preview(
                transaction_id=transaction_id, artifact=preview.artifact,
                artifact_sha256=preview.artifact_hash, before_sha256=self.before_preview,
                after_sha256=preview_after_sha256,
            )
            self.transaction_id, self.artifact_hash = transaction_id, preview.artifact_hash
            self.oracle_evidence.update(transaction_id=transaction_id, artifact_hash=preview.artifact_hash,
                                         preview_approved=True)
        elif command == "execute":
            record = TransactionStore(state_directory).load(self.transaction_id)
            indeterminate = (payload.get("ok") is False and payload.get("status") == "indeterminate"
                and payload.get("state") == record.state.value == "indeterminate"
                and payload.get("automatic_retry") is False and record.artifact_hash == self.artifact_hash)
            self.transaction.observe_execution(transaction_id=payload.get("transaction_id"),
                artifact_sha256=payload.get("artifact_hash"), completed=(payload.get("state") == "executed_unverified"
                    and record.state.value == "executed_unverified" and record.artifact_hash == self.artifact_hash),
                terminal_indeterminate=indeterminate)
        elif command == "verify":
            record = TransactionStore(state_directory).load(self.transaction_id)
            if record.state.value != payload.get("state") or record.artifact_hash != self.artifact_hash:
                raise ExpansionPolicyError("verification receipt differs from its durable transaction state")
            self.oracle_evidence["after"] = self.prepared.snapshot()
            self.assertions = self.prepared.verify(self.prepared.before, self.oracle_evidence["after"])
            self.oracle_evidence.update(assertions=dict(self.assertions), gateway_verification_state=payload.get("state"))
            self.transaction.verify(transaction_id=payload.get("transaction_id"),
                artifact_sha256=payload.get("artifact_hash"), assertions=self.assertions,
                gateway_verification_state=payload.get("state"))
