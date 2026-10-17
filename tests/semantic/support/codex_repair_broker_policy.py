"""Opt-in repair policy using the formal Broker's existing transaction guard."""
from __future__ import annotations

from tests.semantic.support.codex_expansion_broker_policy import ExpansionBrokerPolicy
from tests.semantic.support.codex_expansion_policy import ExpansionPolicyError


class RepairBrokerPolicy(ExpansionBrokerPolicy):
    declarations = {
        **ExpansionBrokerPolicy.declarations,
        "object.create": frozenset({"draft-declare-new", "draft-business-configure"}),
        "object.setProperty": frozenset({"draft-declare-field-change", "draft-business-configure"}),
        "ak.wwise.core.object.get": frozenset(),
    }

    def __init__(self, **kwargs):
        from dataclasses import replace
        self.read_receipts = []
        original = kwargs["prepared"]
        if original.operation == "object.setProperty":
            from tests.semantic.support.codex_repair_cases import metadata_chain_proven
            kwargs["prepared"] = replace(original, verify=lambda before, after: {
                **original.verify(before, after), "metadata_list_page_detail": metadata_chain_proven(self.read_receipts)})
        super().__init__(**kwargs)
        self.read_complete = False

    @property
    def complete(self):
        return self.read_complete if self.prepared.policy == "read_only" else super().complete

    def prepare(self, argv, *, state_directory):
        from tests.semantic.support.codex_repair_gateway_argv import repair_command_argv
        argv = repair_command_argv(argv, parser=self.parser, version=self.version)
        if self.prepared.policy == "read_only" and (not argv or argv[0] not in {
                "status", "operations", "query-schema", "operation-schema", "request-schema", "query-object", "metadata"}):
            raise ExpansionPolicyError("repair read-only workflow cannot prepare or execute a transaction")
        return super().prepare(argv, state_directory=state_directory)

    def observe(self, step, payload, *, state_directory):
        super().observe(step, payload, state_directory=state_directory)
        if step.subcommand in {"query-object", "metadata", "draft-discover-fields"}:
            self.read_receipts.append({"command": step.subcommand, "arguments": list(step.arguments), "payload": payload})

    def finish_read(self):
        if self.prepared.policy != "read_only":
            return
        from tests.semantic.support.codex_repair_cases import read_refinement_proven
        self.oracle_evidence["after"] = self.prepared.snapshot()
        self.assertions = dict(self.prepared.verify(self.prepared.before, self.oracle_evidence["after"]))
        self.assertions["read_refinement"] = read_refinement_proven(self.read_receipts,
            target_id=self.prepared.archive_oracle_parameters["target_id"],
            expected=self.prepared.archive_oracle_parameters["expected"])
        self.oracle_evidence.update(assertions=self.assertions, read_receipts=self.read_receipts)
        self.read_complete = bool(self.assertions) and all(value is True for value in self.assertions.values())
