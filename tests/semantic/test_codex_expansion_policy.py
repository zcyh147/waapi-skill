"""Fail-closed scope, intent, nonce and ambiguous-execution regressions."""

from dataclasses import replace

import pytest

from tests.semantic.support.codex_expansion_policy import (
    BoundedExpansionReads, CumulativeAgentBudget, ExpansionPolicyError,
    ExpansionReadScope, ExpansionTransaction, canonical_digest,
)


OWNER = "{11111111-1111-1111-1111-111111111111}"
OUTSIDER = "{22222222-2222-2222-2222-222222222222}"
PROMPT = canonical_digest("Please import the two tracks and execute")
BEFORE = canonical_digest({"objects": [OWNER]})
ARTIFACT = {"operation": "audio.import", "parent": OWNER, "media": ["a.wav", "b.wav"]}
HASH = canonical_digest(ARTIFACT)


def reads(**overrides):
    return BoundedExpansionReads(ExpansionReadScope(
        object_ids=frozenset({OWNER}), operations=frozenset({"audio.import"}),
        includes=frozenset({"volume"}), relationship_sources=frozenset({OWNER}),
        **overrides,
    ))


def query_receipt(limit=None):
    return {"ok": True, "command": "query-object", "objects": [], "count": 0,
            "query_bound": {"mode": "exact-object"} if limit is None else {"mode": "take", "value": limit}}


def transaction(policy="allow_changes"):
    value = ExpansionTransaction(
        policy=policy, request_prompt_sha256=PROMPT,
        required_assertions=frozenset({"media_hashes", "owner_graph", "siblings_unchanged"}),
        approve_preview=lambda artifact: artifact == ARTIFACT,
    )
    value.begin_turn(1)
    return value


def preview(value, **overrides):
    args = dict(transaction_id="tx1-test", artifact=ARTIFACT,
                artifact_sha256=HASH, before_sha256=BEFORE, after_sha256=BEFORE)
    value.seal_preview(**(args | overrides))


def authorize(value):
    return value.authorize(turn_prompt_sha256=PROMPT, explicit_intent="perform_changes")


def test_independent_scoped_reads_can_use_different_orders_and_counts():
    for commands in [
        [("query-schema",), ("query-object", "--max-results", "2", "--exact-id", OWNER)],
        [("operations",), ("operation-schema", "audio.import"),
         ("query-object", "--exact-id", OWNER, "--relationship", "children", "--max-results", "64")],
    ]:
        gate = reads()
        for command in commands:
            assert gate.admit(command) == command
            gate.observe(query_receipt(int(command[command.index("--max-results") + 1])) if command[0] == "query-object"
                         else {"ok": True, "command": command[0]})
        assert len(gate.receipts) == len(commands)


@pytest.mark.parametrize("argv", [
    ("execute", "tx1-test"), ("call", "ak.wwise.core.object.get"),
    ("query-object", "--exact-id", OUTSIDER, "--max-results", "1"),
    ("query-object", "--exact-id", OWNER, "--max-results", "65"),
    ("query-object", "--exact-id", OWNER, "--max-results", "1", "--max-results", "1"),
    ("query-object", "--exact-id", OWNER, "--max-results", "1", "--relationship", "referencesTo"),
    ("query-object", "--exact-id", OWNER, "--max-results", "1", "--waql", "$ from objects"),
    ("query-object", "--exact-id", OWNER, "--max-results", "1", "--include", "undeclared"),
    ("--host", "elsewhere", "query-schema"),
    ("request-schema", "ak.wwise.core.executeLuaScript"),
])
def test_read_policy_rejects_scope_escape_or_unbounded_input(argv):
    with pytest.raises(ExpansionPolicyError):
        reads().admit(argv)


def test_failed_read_attempts_cannot_evade_capacity():
    gate = reads(max_calls=1)
    with pytest.raises(ExpansionPolicyError):
        gate.admit(("call", "ak.anything"))
    with pytest.raises(ExpansionPolicyError, match="capacity"):
        gate.admit(("query-schema",))


def test_public_row_ceiling_applies_only_to_owned_scopes_and_preserves_legacy_default():
    assert reads().scope.max_rows == reads(owned_project_reads=True).scope.max_rows == 64
    assert reads(owned_project_reads=True, max_rows=1000).scope.max_rows == 1000
    for overrides in ({"max_rows": 65}, {"owned_project_reads": True, "max_rows": 1001}):
        with pytest.raises(ExpansionPolicyError, match="ceilings"):
            reads(**overrides)


@pytest.mark.parametrize("flag", [0, 1, "true", "false", None, [], {}])
def test_owned_read_scope_rejects_non_boolean_ownership_flags(flag):
    with pytest.raises(ExpansionPolicyError, match="boolean"):
        reads(owned_project_reads=flag)


def test_exact_id_default_is_intrinsically_bounded_and_failed_read_can_be_repaired():
    gate = reads()
    gate.admit(("query-object", "--exact-id", OWNER))
    assert gate.observe({"ok": False, "command": "query-object", "error_code": "GatewayInputError"}) is False
    assert gate.receipts == [] and len(gate.failed_receipts) == 1
    gate.admit(("query-object", "--exact-id", OWNER))
    assert gate.observe(query_receipt()) is True
    assert len(gate.receipts) == 1 and gate.calls == 2


@pytest.mark.parametrize("change", [
    {"limit_reached": True}, {"query_bound": {}},
    {"command": "execute"}, {"ok": False},
    {"objects": [{}] * 65},
])
def test_read_receipts_fail_closed_and_do_not_unlock_next_command(change):
    gate = reads()
    gate.admit(("query-object", "--exact-id", OWNER, "--max-results", "2"))
    with pytest.raises(ExpansionPolicyError):
        gate.observe(query_receipt(2) | change)
    assert gate.receipts == []
    with pytest.raises(ExpansionPolicyError, match="pending"):
        gate.admit(("query-schema",))


def test_read_receipt_byte_limit_is_utf8_not_character_count():
    gate = reads(max_result_bytes=80)
    gate.admit(("query-schema",))
    with pytest.raises(ExpansionPolicyError, match="byte"):
        gate.observe({"ok": True, "command": "query-schema", "text": "音" * 20})


@pytest.mark.parametrize("change", [
    {"after_sha256": canonical_digest("changed")},
    {"artifact_sha256": canonical_digest("wrong")},
    {"artifact": ARTIFACT | {"parent": OUTSIDER},
     "artifact_sha256": canonical_digest(ARTIFACT | {"parent": OUTSIDER})},
])
def test_preview_must_be_immutable_and_independently_approved(change):
    value = transaction()
    with pytest.raises(ExpansionPolicyError):
        preview(value, **change)
    assert value.state == "unprepared"


def test_read_only_never_mints_a_mutation_authorization():
    value = transaction("read_only")
    with pytest.raises(ExpansionPolicyError):
        preview(value)
    with pytest.raises(ExpansionPolicyError):
        authorize(value)


def test_ask_requires_later_explicit_confirmation_bound_to_current_preview():
    value = transaction("ask_before_changes")
    preview(value)
    confirmation = dict(turn_prompt_sha256=canonical_digest("confirm"),
                        explicit_intent="confirm_current_preview")
    with pytest.raises(ExpansionPolicyError):
        value.authorize(**confirmation)
    value.begin_turn(2)
    permit = value.authorize(**confirmation)
    assert permit.preview_turn == 1 and permit.authorized_turn == 2


@pytest.mark.parametrize("intent", ["design_only", "ambiguous", "confirm_current_preview"])
def test_allow_configuration_does_not_authorize_design_or_ambiguous_intent(intent):
    value = transaction()
    preview(value)
    with pytest.raises(ExpansionPolicyError):
        value.authorize(turn_prompt_sha256=PROMPT, explicit_intent=intent)


def test_exact_nonce_artifact_and_gateway_authorization_required_before_reservation():
    value = transaction()
    preview(value)
    permit = authorize(value)
    for candidate, digest, bound in [
        (replace(permit, authorization_nonce="forged"), HASH, True),
        (permit, canonical_digest("drift"), True), (permit, HASH, False),
    ]:
        with pytest.raises(ExpansionPolicyError):
            value.reserve_execute(candidate, live_artifact_sha256=digest,
                                  gateway_authorization_bound=bound)
    assert value.state == "authorized"
    value.reserve_execute(permit, live_artifact_sha256=HASH, gateway_authorization_bound=True)
    with pytest.raises(ExpansionPolicyError):
        value.reserve_execute(permit, live_artifact_sha256=HASH, gateway_authorization_bound=True)


def test_timeout_after_reservation_is_indeterminate_and_cannot_retry():
    value = transaction()
    preview(value)
    permit = authorize(value)
    value.reserve_execute(permit, live_artifact_sha256=HASH, gateway_authorization_bound=True)
    with pytest.raises(ExpansionPolicyError, match="do not retry"):
        value.observe_execution(transaction_id="tx1-test", artifact_sha256=HASH, completed=False)
    assert value.state == "indeterminate"
    with pytest.raises(ExpansionPolicyError):
        value.reserve_execute(permit, live_artifact_sha256=HASH, gateway_authorization_bound=True)


def test_verified_flag_alone_is_not_business_acceptance():
    value = transaction()
    preview(value)
    permit = authorize(value)
    value.reserve_execute(permit, live_artifact_sha256=HASH, gateway_authorization_bound=True)
    value.observe_execution(transaction_id="tx1-test", artifact_sha256=HASH, completed=True)
    for assertions in ({}, {"media_hashes": True},
                       {"media_hashes": True, "owner_graph": True, "siblings_unchanged": False}):
        with pytest.raises(ExpansionPolicyError):
            value.verify(transaction_id="tx1-test", artifact_sha256=HASH,
                         assertions=assertions, gateway_verification_state="verified")
    value.verify(transaction_id="tx1-test", artifact_sha256=HASH,
                 assertions={key: True for key in value.required_assertions}, gateway_verification_state="verified")
    assert value.state == "verified"


def test_new_object_read_scope_requires_executed_preview_and_exact_approved_paths():
    value = transaction()
    preview(value)
    permit = authorize(value)
    gate = reads()
    args = dict(transaction_id="tx1-test", artifact_sha256=HASH,
                execution_rows=[{"id": OUTSIDER, "path": r"\Music\New"}],
                approved_paths=frozenset({r"\Music\New"}))
    with pytest.raises(ExpansionPolicyError):
        value.extend_read_scope(gate, **args)
    value.reserve_execute(permit, live_artifact_sha256=HASH, gateway_authorization_bound=True)
    value.observe_execution(transaction_id="tx1-test", artifact_sha256=HASH, completed=True)
    for changes in ({"artifact_sha256": canonical_digest("other")},
                    {"execution_rows": [{"id": OUTSIDER, "path": r"\Outside"}]},
                    {"execution_rows": args["execution_rows"] * 2}):
        with pytest.raises(ExpansionPolicyError):
            value.extend_read_scope(gate, **(args | changes))
        assert OUTSIDER not in gate.scope.object_ids
    value.extend_read_scope(gate, **args)
    gate.admit(("query-object", "--exact-id", OUTSIDER))
    assert gate.observe(query_receipt() | {"objects": [{"id": OUTSIDER}], "count": 1}) is True


def test_agent_budget_accumulates_turns_excludes_fixture_time_and_never_resets():
    budget = CumulativeAgentBudget()
    assert budget.start_turn(1000) == 600
    budget.finish_turn(1300)
    assert budget.start_turn(9000) == 300  # long runner-only gap is excluded
    budget.finish_turn(9125)
    assert budget.slow is True
    assert budget.start_turn(9200) == 175
    budget.finish_turn(9375)
    with pytest.raises(ExpansionPolicyError, match="exhausted"):
        budget.start_turn(9400)


@pytest.mark.parametrize("hard,slow", [(float("nan"), 420), (600, float("inf")),
                                        (True, 0.5), (420, 420), (-1, -2)])
def test_budget_rejects_nonfinite_bool_or_unordered_bounds(hard, slow):
    with pytest.raises(ExpansionPolicyError):
        CumulativeAgentBudget(hard_seconds=hard, slow_seconds=slow)


@pytest.mark.parametrize("argv", (["execute", "tx1-owned"], ("execute", "tx1-owned")))
@pytest.mark.parametrize("state,expected", [("executing", "INDETERMINATE"), ("indeterminate", "INDETERMINATE"),
                                            ("policy_authorized", "INDETERMINATE"), ("executed_unverified", "FAIL"),
                                            ("execution_failed", "FAIL")])
def test_outcome_distinguishes_unproven_execution_from_incomplete_agent_work(state, expected, argv):
    from tests.semantic.support.codex_expansion_policy import classify_expansion_outcome
    records = [{"accepted": True, "gateway_arguments": argv, "succeeded": False}]
    events = [{"to_state": state}]
    assert classify_expansion_outcome(passed=False, records=records, events=events) == expected


@pytest.mark.parametrize("category", ("authentication", "quota_or_rate_limit", "service_unavailable", "timeout_before_agent_action"))
def test_pre_agent_infrastructure_is_blocked_without_mutation(category):
    from tests.semantic.support.codex_expansion_policy import classify_expansion_outcome
    assert classify_expansion_outcome(passed=False, records=[], events=[],
        infrastructure={"category": category, "agent_item_event_count": 0}) == "BLOCKED"


def test_infrastructure_label_cannot_erase_an_admitted_uncertain_mutation_or_agent_failure():
    from tests.semantic.support.codex_expansion_policy import classify_expansion_outcome
    infrastructure = {"category": "quota_or_rate_limit", "agent_item_event_count": 0}
    assert classify_expansion_outcome(passed=False, records=[{"accepted": True, "gateway_arguments": ["execute", "tx1-owned"]}],
        events=[], infrastructure=infrastructure) == "INDETERMINATE"
    assert classify_expansion_outcome(passed=False, records=[], events=[],
        infrastructure={**infrastructure, "agent_item_event_count": 1}) == "FAIL"
