from __future__ import annotations

import copy
import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

from tests.semantic.support.codex_eval_protocol_v3 import (
    V3GatewayProtocol,
    build_metadata_transaction_protocol,
    build_transaction_protocol,
)
from tests.semantic.support.codex_harness import CodexCommandRecord
from tests.semantic.support.codex_prompt_asset_reads_v3 import (
    MAX_PROMPT_ASSET_CAT_BYTES,
    PromptAssetReadError,
    remove_validated_command_occurrences,
    sealed_prompt_file_assets,
    validated_prompt_asset_cat_commands,
)
from tests.semantic.support.codex_prompt_provenance_v3 import (
    PromptProvenanceEvidence,
)


def _transaction_protocol(operation: str) -> V3GatewayProtocol:
    return build_transaction_protocol(
        (
            {
                "contract": "waapi-skill.operation-request/v1",
                "version": "2025.1",
                "operation": operation,
                "arguments": {"fixture": "sealed-input"},
            },
        )
    )


def _tab_import_protocol(
    import_file: str,
    *,
    metadata_bound: bool,
) -> V3GatewayProtocol:
    request = {
        "contract": "waapi-skill.operation-request/v1",
        "version": "2025.1",
        "operation": "audio.importTabDelimited",
        "arguments": {
            "import_file": import_file,
            "import_location": {
                "kind": "path",
                "value": r"\Containers\Default Work Unit",
            },
            "import_language": "SFX",
            "import_operation": "createNew",
        },
    }
    if not metadata_bound:
        return build_transaction_protocol((request,))
    return build_metadata_transaction_protocol(
        (request,),
        object_type="Sound",
        metadata_queries=("looping",),
        required_tokens=("IsLoopingEnabled",),
        equivalence="audio_import_tab_v1",
    )


def _provenance(
    tmp_path: Path,
    *,
    content: str = "Object Path\t@Volume\n<Sound>A\t-3\n",
    kind: str = "absolute_file_path",
    relative: str = "assets/import.tsv",
    size: int | None = None,
    digest: str | None = None,
) -> tuple[PromptProvenanceEvidence, str, str]:
    root = tmp_path / "scenario"
    owned = root / "owned"
    path = owned / "assets" / "import.tsv"
    encoded = content.encode("utf-8")
    row = {
        "name": "import_file",
        "kind": kind,
        "value": str(path),
        "value_sha256": "a" * 64,
        "canonical_json": None,
        "leaf_bindings": [
            {
                "pointer": "",
                "value_sha256": "b" * 64,
                "origin_kind": "owned_path",
                "origin_pointer": "/steps/2/arguments/2/value/arguments/import_file",
                "path_kind": "file",
                "owned_relative_path": relative,
                "size": len(encoded) if size is None else size,
                "sha256": (
                    hashlib.sha256(encoded).hexdigest()
                    if digest is None
                    else digest
                ),
                "mtime_ns": 1,
            }
        ],
    }
    evidence = PromptProvenanceEvidence(
        path=root / "evidence" / "prompt-provenance.json",
        sha256="c" * 64,
        payload={
            "scenario_root": str(root),
            "owned_root": str(owned),
            "request": {
                "rendered_prompt": f"导入表是 {path}",
                "inputs": [row],
            },
        },
        prompts=(f"导入表是 {path}",),
        visible_values={"import_file": str(path)},
        protocol=None,  # type: ignore[arg-type]
    )
    return evidence, str(path), content


def _record(
    path: str,
    output: str,
    *,
    argv0: str = "cat",
    extra_argv: tuple[str, ...] = (),
    exit_code: int = 0,
    status: str = "completed",
    operators: bool = False,
    parse_error: str = "",
) -> CodexCommandRecord:
    return CodexCommandRecord(
        command=f"/bin/bash -lc 'cat {path}'",
        exit_code=exit_code,
        status=status,
        aggregated_output=output,
        argv=(argv0, *extra_argv, path),
        has_shell_operators=operators,
        parse_error=parse_error,
    )


def _with_auxiliary_asset(
    provenance: PromptProvenanceEvidence,
    *,
    content: str,
) -> tuple[PromptProvenanceEvidence, str]:
    payload = copy.deepcopy(provenance.payload)
    root = Path(str(payload["scenario_root"]))
    path = root / "owned" / "assets" / "instructions.txt"
    encoded = content.encode("utf-8")
    payload["request"]["inputs"].append(
        {
            "name": "instructions_file",
            "kind": "absolute_file_path",
            "value": str(path),
            "value_sha256": "d" * 64,
            "canonical_json": None,
            "leaf_bindings": [
                {
                    "pointer": "",
                    "value_sha256": "e" * 64,
                    "origin_kind": "owned_path",
                    "origin_pointer": "/trusted/instructions_file",
                    "path_kind": "file",
                    "owned_relative_path": "assets/instructions.txt",
                    "size": len(encoded),
                    "sha256": hashlib.sha256(encoded).hexdigest(),
                    "mtime_ns": 1,
                }
            ],
        }
    )
    return replace(provenance, payload=payload), str(path)


def test_exact_first_turn_cat_is_bound_to_prompt_asset_bytes(
    tmp_path: Path,
) -> None:
    provenance, path, content = _provenance(tmp_path)
    record = _record(path, content)

    assets = sealed_prompt_file_assets(provenance)

    assert [(item.path, item.size, item.sha256) for item in assets] == [
        (
            path,
            len(content.encode("utf-8")),
            hashlib.sha256(content.encode("utf-8")).hexdigest(),
        )
    ]
    assert validated_prompt_asset_cat_commands(
        (record,),
        provenance=provenance,
        turn_index=1,
    ) == (record.command,)
    assert validated_prompt_asset_cat_commands(
        (record,),
        provenance=provenance,
        turn_index=2,
    ) == ()


@pytest.mark.parametrize("metadata_bound", (False, True))
def test_tab_import_transaction_never_accepts_sealed_prompt_asset_cat(
    tmp_path: Path,
    metadata_bound: bool,
) -> None:
    provenance, path, content = _provenance(tmp_path)
    provenance = replace(
        provenance,
        protocol=_tab_import_protocol(path, metadata_bound=metadata_bound),
    )

    assert validated_prompt_asset_cat_commands(
        (_record(path, content),),
        provenance=provenance,
        turn_index=1,
    ) == ()


def test_tab_import_only_blocks_its_import_file_not_an_auxiliary_asset(
    tmp_path: Path,
) -> None:
    provenance, import_path, import_content = _provenance(tmp_path)
    provenance = replace(
        provenance,
        protocol=_tab_import_protocol(import_path, metadata_bound=True),
    )
    auxiliary_content = "这是一份独立辅助说明。\n"
    provenance, auxiliary_path = _with_auxiliary_asset(
        provenance,
        content=auxiliary_content,
    )
    auxiliary_record = _record(auxiliary_path, auxiliary_content)

    assert validated_prompt_asset_cat_commands(
        (
            _record(import_path, import_content),
            auxiliary_record,
        ),
        provenance=provenance,
        turn_index=1,
    ) == (auxiliary_record.command,)


def test_other_file_transaction_keeps_single_sealed_prompt_asset_cat(
    tmp_path: Path,
) -> None:
    provenance, path, content = _provenance(tmp_path)
    provenance = replace(
        provenance,
        protocol=_transaction_protocol("soundbank.processDefinitionFiles"),
    )
    record = _record(path, content)

    assert validated_prompt_asset_cat_commands(
        (record,),
        provenance=provenance,
        turn_index=1,
    ) == (record.command,)


def test_each_sealed_asset_cat_is_accepted_at_most_once(
    tmp_path: Path,
) -> None:
    provenance, path, content = _provenance(tmp_path)
    record = _record(path, content)

    accepted = validated_prompt_asset_cat_commands(
        (record, record),
        provenance=provenance,
        turn_index=1,
    )

    assert accepted == (record.command,)
    assert remove_validated_command_occurrences(
        (record.command, record.command),
        accepted,
    ) == (record.command,)


@pytest.mark.parametrize(
    "record_factory",
    (
        lambda path, content: _record(path, content, argv0="/bin/cat"),
        lambda path, content: _record(path, content, argv0="head"),
        lambda path, content: _record(
            path,
            content,
            extra_argv=("--",),
        ),
        lambda path, content: _record(path, content, operators=True),
        lambda path, content: _record(path, content, exit_code=1, status="failed"),
        lambda path, content: _record(path, content, parse_error="bad shell"),
        lambda path, content: _record(path, content + "tampered"),
        lambda path, content: _record(path + ".other", content),
    ),
    ids=(
        "explicit-bin-cat",
        "other-command",
        "cat-flag",
        "shell-operator",
        "failed-command",
        "parse-error",
        "wrong-output",
        "unsealed-path",
    ),
)
def test_cat_exception_rejects_every_unsealed_command_or_output_shape(
    tmp_path: Path,
    record_factory,
) -> None:
    provenance, path, content = _provenance(tmp_path)
    record = record_factory(path, content)

    assert validated_prompt_asset_cat_commands(
        (record,),
        provenance=provenance,
        turn_index=1,
    ) == ()


def test_only_bounded_absolute_file_input_is_readable(
    tmp_path: Path,
) -> None:
    non_file, path, content = _provenance(
        tmp_path / "non-file",
        kind="object_path",
    )
    oversized, _, _ = _provenance(
        tmp_path / "oversized",
        size=MAX_PROMPT_ASSET_CAT_BYTES + 1,
    )

    assert sealed_prompt_file_assets(non_file) == ()
    assert validated_prompt_asset_cat_commands(
        (_record(path, content),),
        provenance=non_file,
        turn_index=1,
    ) == ()
    assert sealed_prompt_file_assets(oversized) == ()


def test_absolute_path_mentioned_only_in_prompt_text_is_not_readable(
    tmp_path: Path,
) -> None:
    provenance, path, content = _provenance(tmp_path)
    provenance.payload["request"]["inputs"] = []

    assert path in provenance.payload["request"]["rendered_prompt"]
    assert validated_prompt_asset_cat_commands(
        (_record(path, content),),
        provenance=provenance,
        turn_index=1,
    ) == ()


@pytest.mark.parametrize(
    ("size_delta", "digest"),
    (
        (1, None),
        (0, "0" * 64),
    ),
    ids=("sealed-size", "sealed-sha256"),
)
def test_cat_output_must_match_both_sealed_size_and_sha256(
    tmp_path: Path,
    size_delta: int,
    digest: str | None,
) -> None:
    content = "Object Path\t@Volume\n<Sound>A\t-3\n"
    provenance, path, _ = _provenance(
        tmp_path,
        content=content,
        size=len(content.encode("utf-8")) + size_delta,
        digest=digest,
    )

    assert validated_prompt_asset_cat_commands(
        (_record(path, content),),
        provenance=provenance,
        turn_index=1,
    ) == ()


def test_owned_relative_path_must_reconnect_exactly(
    tmp_path: Path,
) -> None:
    provenance, _, _ = _provenance(
        tmp_path,
        relative="assets/other.tsv",
    )

    with pytest.raises(PromptAssetReadError, match="reconnect"):
        sealed_prompt_file_assets(provenance)


def test_owned_relative_path_rejects_parent_segments(
    tmp_path: Path,
) -> None:
    provenance, _, _ = _provenance(
        tmp_path,
        relative="assets/../assets/import.tsv",
    )

    with pytest.raises(PromptAssetReadError, match="invalid sealed path"):
        sealed_prompt_file_assets(provenance)
