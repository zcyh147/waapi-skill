from __future__ import annotations

from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[2] / "skills" / "waapi-skill"
SKILL = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
QUERY = (SKILL_ROOT / "references" / "waapi-query.md").read_text(encoding="utf-8")
SETUP = (SKILL_ROOT / "references" / "waapi-setup.md").read_text(encoding="utf-8")
OPERATE = (SKILL_ROOT / "references" / "waapi-operate.md").read_text(encoding="utf-8")


def test_common_reads_use_closed_gateway_before_optional_references() -> None:
    assert SKILL.index("## Fixed gateway commands") < SKILL.index("## Routing")
    assert "Treat gateway JSON as authoritative" in SKILL
    assert "Read one lane reference only when the fixed command table does not fully answer" in SKILL
    assert "There is no raw-client fallback" in QUERY


def test_machine_readable_agent_result_is_terminal_for_fixed_reads_and_transactions() -> None:
    assert "any successful gateway payload contains `agent_result`" in SKILL
    assert "This rule applies to fixed reads as well as transactions" in SKILL
    assert "Do not reconstruct its fields from the prompt, `normalized`" in SKILL
    assert "do not run another command after receiving it" in SKILL
    assert "metadata types --summary-only" in QUERY
    assert "compact-serialize that object exactly" in QUERY


def test_initial_skill_bootstrap_is_the_only_combined_read_exception() -> None:
    assert "After this entry file has been loaded" in SKILL
    assert "same absolute file" in SKILL
    assert "this is the only combined read allowed" in SKILL
    assert "Never combine a reference read, gateway invocation, or any other commands" in SKILL


def test_exact_identity_query_is_complete_in_entry_file() -> None:
    command = (
        "query-object --path '<exact-object-path>' --return-field id "
        "--return-field name --return-field type --return-field path"
    )
    assert command in SKILL
    assert "Keep all four return fields explicit" in SKILL
    assert "do not read the query reference before or after it" in SKILL
    assert "Conditional read for a query not fully covered" in SKILL
    assert "keep those four fields explicit for an exact path/GUID identity lookup" in QUERY


def test_ordinary_wwise_work_forbids_agent_authored_code() -> None:
    for phrase in ("inline Python", "new `.py`/`.js`/`.sh` helper", "direct client construction"):
        assert phrase in SKILL
    assert "Skill development, testing, or debugging" in SKILL
    assert "Do not import builders or planners from inline Python" in OPERATE
    assert "do not bridge those gaps with generated code" in OPERATE.lower()


def test_operate_lane_uses_real_transaction_cli_in_order() -> None:
    new_transaction_sequence = (
        "gateway.py operation-schema <operation-name>",
        "preview --request-json",
    )
    continuation_sequence = (
        "transaction-show <transaction-id>",
        "confirm <transaction-id> --artifact-hash <artifact-hash>",
        "execute <transaction-id>",
        "verify <transaction-id>",
    )
    new_positions = [OPERATE.index(item) for item in new_transaction_sequence]
    continuation_positions = [OPERATE.index(item) for item in continuation_sequence]
    assert new_positions == sorted(new_positions)
    assert continuation_positions == sorted(continuation_positions)
    assert "`operations` first: that command is only for broad capability-inventory questions" in OPERATE
    assert "Do not call `operations`, `operation-schema`, or `preview` first" in OPERATE
    assert "Only after a later user message clearly confirms" in OPERATE
    assert "Never run `confirm` merely because the original request used an imperative verb" in OPERATE


def test_operate_state_directory_is_caller_owned_and_never_probed() -> None:
    for document in (SKILL, OPERATE):
        assert "omit `--state-dir`" in document
        assert "Never run `env`, `printenv`" in document
        assert "discover `WAAPI_SKILL_STATE_DIR`" in document
        assert "trusted absolute path" in document
        assert "structured state-directory error or boundary" in document

    assert "gateway.py --state-dir /absolute/state/dir" not in OPERATE
    for command in (
        "gateway.py preview --request-json",
        "gateway.py transaction-show <transaction-id> --summary-only",
        "gateway.py confirm <transaction-id> --artifact-hash <artifact-hash>",
        "gateway.py execute <transaction-id>",
        "gateway.py verify <transaction-id>",
    ):
        assert command in OPERATE


def test_transaction_state_never_grants_authority_and_hash_alone_is_insufficient() -> None:
    assert "A status or check request stops after `transaction-show`" in SKILL
    assert "the returned state only constrains which actions are legal" in SKILL
    assert "an artifact hash alone is not a transaction lookup key" in SKILL

    assert "A transaction id is required: an artifact hash alone is not a lookup key" in OPERATE
    assert "A status or check request stops after `transaction-show`" in OPERATE
    assert "state only constrains which actions are legal and never authorizes an action by itself" in OPERATE
    assert "An explicit verify-only request" in OPERATE


def test_verify_payload_is_terminal_and_must_not_be_double_checked() -> None:
    assert "`verify` already performs the operation-specific live readback" in SKILL
    assert "Do not add `query-object`, `call`, or another gateway command" in SKILL
    assert "The `verify` payload is the terminal authority" in OPERATE
    assert "Never append `query-object`, generic `call`, or another gateway command" in OPERATE
    assert "then stop without an extra query" in OPERATE


def test_operate_examples_are_generic_and_preserve_requested_import_notes() -> None:
    assert "gateway.py operation-schema <operation-name>" in OPERATE
    assert "gateway.py operation-schema object.create" not in OPERATE
    assert '"notes": "Imported through the WAAPI Skill transaction gateway"' in OPERATE


def test_operation_request_is_closed_and_runtime_owned_metadata_cannot_be_injected() -> None:
    assert '"contract": "waapi-skill.operation-request/v1"' in OPERATE
    for kind in ('"kind":"id"', '"kind":"path"', '"kind":"waql"', '"kind":"scoped-name"'):
        assert kind in OPERATE
    for forbidden_input in ("identity rows", "`property_info`", "`reference_info`", "dispatcher args/options", "WAAPI URI"):
        assert forbidden_input in OPERATE
    assert "unknown fields fail" in OPERATE


def test_closed_operations_and_boundaries_are_truthful() -> None:
    for operation in (
        "object.create",
        "object.delete",
        "object.setName",
        "object.setNotes",
        "object.setProperty",
        "object.setReference",
        "audio.import",
        "soundbank.setInclusions",
        "switchContainer.addAssignment",
        "switchContainer.removeAssignment",
    ):
        assert f"`{operation}`" in OPERATE
    for boundary in (
        "object.set",
        "object.copy",
        "object.move",
        "audio.importTabDelimited",
        "soundbank.generate",
        "soundbank.convertExternalSources",
        "soundbank.processDefinitionFiles",
    ):
        assert boundary in OPERATE
    assert "Platform-specific values are not yet accepted" in OPERATE


def test_transaction_runtime_invariants_prevent_hash_target_and_retry_drift() -> None:
    for phrase in (
        "write-once and SHA-256 bound",
        "does not accept replacement JSON",
        "verifies the live Wwise version/project/endpoint",
        "verifies the packaged implementation digest",
        "re-reads every canonical GUID role",
        "repreview_required",
        "never automatically retried",
        "executed_unverified",
        "verification_deferred",
    ):
        assert phrase in OPERATE
    assert "even with `--allow-destructive` or `WWISE_DESTRUCTIVE=1`" in OPERATE


def test_operation_specific_verification_is_not_generic_mutation_replay() -> None:
    for phrase in (
        "GUID returned by execution",
        "Delete proves GUID absence",
        "same GUID, new name/path, unchanged parent, and old-path absence",
        "Numeric properties use typed tolerance",
        "References must normalize to the target identity",
    ):
        assert phrase in OPERATE
    assert "run `verify`, not `execute` again" in OPERATE


def test_planner_and_xml_are_explicit_non_execution_boundaries() -> None:
    assert "`SemanticPlanner` is a candidate/schema planning resource, not the transaction executor" in OPERATE
    assert "do not use its generic mutation verification steps" in OPERATE
    assert "XML editing is not an automatic fallback" in OPERATE
    assert "return `unsupported_by_skill_interface`" in OPERATE


def test_public_config_surface_excludes_runtime_internals() -> None:
    for field in ("wwise_version", "waapi_host", "waapi_port", "project_modification_policy"):
        assert f"`{field}`" in SETUP
    assert "Do not describe timeout constants" in SETUP
    assert "environment wiring" in SETUP
    assert "default `WwiseConsole` paths" in SETUP
    assert "gateway.py config-show" in SETUP
    assert "gateway.py config-set" in SETUP
    assert "$XDG_CONFIG_HOME/waapi-skill/config.json" in SETUP
    assert "never writes the legacy file inside the Skill checkout" in SETUP


def test_simple_read_only_result_has_no_forced_policy_boilerplate() -> None:
    assert "Do not add policy or implementation narration to a simple read-only result" in SETUP
    assert "project modification policy" not in QUERY.lower()
