from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from wwise_waapi import operation_registry
from wwise_waapi.operation_composer import operation_composer_digest
from wwise_waapi.operation_drafts import (
    OperationDraftRecreateRequired,
    OperationDraftStore,
)
from wwise_waapi.transactions import (
    TRANSACTION_SCHEMA_VERSION,
    TransactionRecreateRequired,
    TransactionState,
    TransactionStore,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
GATEWAY_PATH = REPO_ROOT / "skills" / "waapi-skill" / "scripts" / "gateway.py"
SPEC = importlib.util.spec_from_file_location(
    "waapi_single_typed_input_cutover_gateway",
    GATEWAY_PATH,
)
assert SPEC is not None and SPEC.loader is not None
gateway = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = gateway
SPEC.loader.exec_module(gateway)


REMOVED_PRODUCT_COMMANDS = frozenset(
    {
        "legacy-operation-schema",
        "preview",
        "legacy-preview",
        "call",
    }
)
REMOVED_PRODUCT_OPTIONS = frozenset(
    {
        "--request-json",
        "--advanced-request-json",
        "--where-json",
        "--args-json",
        "--options-json",
        "--result-json",
        "--match-json",
        "--post-filter-json",
        "--action-json",
        "--artifact-hash",
    }
)


def _subparser_choices(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    action = next(
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    )
    return dict(action.choices)


def _option_strings(parser: argparse.ArgumentParser) -> set[str]:
    return {
        option
        for action in parser._actions
        for option in action.option_strings
    }


def test_packaged_gateway_parser_has_no_legacy_or_raw_json_product_entry() -> None:
    parser = gateway.build_parser()
    choices = _subparser_choices(parser)

    assert REMOVED_PRODUCT_COMMANDS.isdisjoint(choices)
    assert REMOVED_PRODUCT_OPTIONS.isdisjoint(_option_strings(parser))
    for command in (
        "query-object",
        "wait-topic",
        "stream-topic",
        "draft-apply",
        "confirm",
    ):
        assert REMOVED_PRODUCT_OPTIONS.isdisjoint(_option_strings(choices[command]))


def test_packaged_guidance_contains_no_model_facing_raw_json_spelling() -> None:
    product_documents = (
        REPO_ROOT / "skills" / "waapi-skill" / "SKILL.md",
        *(REPO_ROOT / "skills" / "waapi-skill" / "references").glob("waapi-*.md"),
        REPO_ROOT / "README.md",
    )
    forbidden = (
        "legacy-operation-schema",
        "legacy-preview",
        "preview --request-json",
        "call --args-json",
        "--advanced-request-json",
        "--where-json",
        "--options-json",
        "--match-json",
        "--post-filter-json",
        "--action-json",
    )

    for document in product_documents:
        text = document.read_text(encoding="utf-8")
        for spelling in forbidden:
            assert spelling not in text, (document, spelling)


def test_packaged_skill_contains_no_retired_audio_import_composer_surface() -> None:
    skill_root = REPO_ROOT / "skills" / "waapi-skill"

    assert not (
        skill_root / "wwise_waapi" / "audio_import_business_migration.py"
    ).exists()
    assert not (
        skill_root / "resources" / "business" / "audio-import-migration.json"
    ).exists()
    assert not hasattr(operation_registry, "audio_import_composer_fragment_contract")
    assert not hasattr(operation_registry, "validate_audio_import_composer_fragment")

    public_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            skill_root / "SKILL.md",
            *(skill_root / "references").glob("waapi-*.md"),
        )
    )
    for retired in (
        "add_import_row",
        "set_import_operation",
        "audio-import-composer-fragments",
    ):
        assert retired not in public_text


def test_internal_canonical_waapi_call_is_not_a_public_operation() -> None:
    code, payload = gateway.execute_gateway(["operations"])
    assert code == 0, payload
    assert "waapi.call" not in {row["name"] for row in payload["operations"]}

    code, payload = gateway.execute_gateway(
        ["--version", "2025.1", "operation-schema", "waapi.call"]
    )
    assert code == 2
    assert payload["error_code"] == "INTERNAL_CANONICAL_OPERATION"


def test_describe_and_operation_schema_disclose_no_copyable_request_document() -> None:
    code, described = gateway.execute_gateway(
        ["--version", "2025.1", "describe", "ak.wwise.cli.generateSoundbank"]
    )
    assert code == 0, described
    code, operation = gateway.execute_gateway(
        ["--version", "2025.1", "operation-schema", "object.setNotes"]
    )
    assert code == 0, operation

    public_projection = json.dumps(
        {"describe": described, "operation_schema": operation},
        separators=(",", ":"),
    )
    for key in (
        "request_template",
        "request_envelope",
        "canonical_request_template",
    ):
        assert key not in public_projection
    capability = described["availability"]["2025.1"]["capability"]
    assert "call" not in capability["interface"]["gateway_commands"]
    assert "preview" not in capability["interface"]["gateway_commands"]


def test_pre_cutover_draft_and_preview_require_recreation_without_execution(
    tmp_path: Path,
) -> None:
    drafts = OperationDraftStore(tmp_path / "drafts")
    old = drafts.start(
        operation="object.set",
        version="2022.1",
        schema_digest="a" * 64,
    )
    before = next(drafts.records_dir.glob("*.json")).read_bytes()
    with pytest.raises(OperationDraftRecreateRequired, match="recreated"):
        drafts.apply_action(
            old.draft_id,
            task_authority=old.task_authority,
            expected_revision=1,
            schema_digest="a" * 64,
            composer_digest=operation_composer_digest("object.set", "2022.1"),
            action={"action": "inspect"},
        )
    assert next(drafts.records_dir.glob("*.json")).read_bytes() == before

    transactions = TransactionStore(tmp_path / "transactions")
    transactions.create_preview("tx-old", {"request": {"safe": True}})
    transaction_dir = (
        tmp_path / "transactions" / "transactions" / "tx-old"
    )
    for name in ("preview.json", "state.json"):
        path = transaction_dir / name
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["schema_version"] == TRANSACTION_SCHEMA_VERSION
        payload["schema_version"] = 1
        path.write_text(json.dumps(payload), encoding="utf-8")
    before = {
        path.name: path.read_bytes()
        for path in transaction_dir.iterdir()
    }
    for action in (
        lambda: transactions.load_snapshot("tx-old"),
        lambda: transactions.confirm(
            "tx-old",
            confirmation_token="ct1-" + ("a" * 24),
        ),
        lambda: transactions.begin_execution(
            "tx-old",
            expected_authorization=TransactionState.CONFIRMED,
        ),
    ):
        with pytest.raises(TransactionRecreateRequired, match="must be recreated"):
            action()
        assert {
            path.name: path.read_bytes()
            for path in transaction_dir.iterdir()
        } == before
