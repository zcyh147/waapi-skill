"""Closed, provenance-bound text reads for V3 fresh-Codex tasks."""

from __future__ import annotations

import hashlib
import os
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

from tests.semantic.support.codex_harness import CodexCommandRecord
from tests.semantic.support.codex_eval_protocol_v3 import (
    materialize_typed_transaction_protocol_requests,
)
from tests.semantic.support.codex_gateway_broker import ExpectedGatewayStep
from tests.semantic.support.codex_prompt_provenance_v3 import (
    PromptProvenanceEvidence,
)


MAX_PROMPT_ASSET_CAT_BYTES = 256 * 1024
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class PromptAssetReadError(ValueError):
    """The sealed prompt asset allow-list is malformed or cross-bound."""


@dataclass(frozen=True, slots=True)
class SealedPromptFileAsset:
    """One explicit prompt file whose bytes were sealed before Codex ran."""

    input_name: str
    path: str
    owned_relative_path: str
    size: int
    sha256: str


def sealed_prompt_file_assets(
    provenance: PromptProvenanceEvidence,
) -> tuple[SealedPromptFileAsset, ...]:
    """Project exact, bounded file assets from validated prompt provenance."""

    if not isinstance(provenance, PromptProvenanceEvidence):
        raise PromptAssetReadError("prompt provenance evidence is unavailable")
    payload = provenance.payload
    request = payload.get("request") if isinstance(payload, Mapping) else None
    rows = request.get("inputs") if isinstance(request, Mapping) else None
    scenario_root = payload.get("scenario_root") if isinstance(payload, Mapping) else None
    owned_root = payload.get("owned_root") if isinstance(payload, Mapping) else None
    if (
        not isinstance(rows, list)
        or not isinstance(scenario_root, str)
        or not isinstance(owned_root, str)
        or not scenario_root
        or not owned_root
    ):
        raise PromptAssetReadError(
            "prompt provenance lacks its closed request/owned-root binding"
        )
    root = Path(os.path.abspath(os.fspath(Path(scenario_root).expanduser())))
    owned = Path(os.path.abspath(os.fspath(Path(owned_root).expanduser())))
    if owned != root / "owned":
        raise PromptAssetReadError(
            "prompt provenance owned root is not scenario_root/owned"
        )

    assets: list[SealedPromptFileAsset] = []
    seen_paths: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping) or row.get("kind") != "absolute_file_path":
            continue
        name = row.get("name")
        path_text = row.get("value")
        bindings = row.get("leaf_bindings")
        if (
            not isinstance(name, str)
            or not name
            or not isinstance(path_text, str)
            or not path_text
            or not isinstance(bindings, list)
            or len(bindings) != 1
            or not isinstance(bindings[0], Mapping)
        ):
            raise PromptAssetReadError(
                "absolute-file prompt input is not singly bound"
            )
        binding = bindings[0]
        relative_text = binding.get("owned_relative_path")
        size = binding.get("size")
        digest = binding.get("sha256")
        mtime_ns = binding.get("mtime_ns")
        candidate = Path(path_text).expanduser()
        if (
            binding.get("pointer") != ""
            or binding.get("origin_kind") != "owned_path"
            or binding.get("path_kind") != "file"
            or not candidate.is_absolute()
            or ".." in candidate.parts
            or not isinstance(relative_text, str)
            or not relative_text
            or relative_text.startswith("../")
            or PurePosixPath(relative_text).is_absolute()
            or ".." in PurePosixPath(relative_text).parts
            or type(size) is not int
            or size < 0
            or type(mtime_ns) is not int
            or mtime_ns < 0
            or not isinstance(digest, str)
            or _SHA256_RE.fullmatch(digest) is None
        ):
            raise PromptAssetReadError(
                "absolute-file prompt input has an invalid sealed path proof"
            )
        lexical = Path(os.path.abspath(os.fspath(candidate)))
        reconstructed = Path(
            os.path.abspath(os.fspath(owned / PurePosixPath(relative_text)))
        )
        if str(lexical) != path_text or lexical != reconstructed:
            raise PromptAssetReadError(
                "absolute-file prompt input does not reconnect to its owned path"
            )
        if path_text in seen_paths:
            raise PromptAssetReadError(
                "prompt provenance repeats one readable file asset"
            )
        seen_paths.add(path_text)
        if size > MAX_PROMPT_ASSET_CAT_BYTES:
            continue
        assets.append(
            SealedPromptFileAsset(
                input_name=name,
                path=path_text,
                owned_relative_path=relative_text,
                size=size,
                sha256=digest,
            )
        )
    return tuple(assets)


def _applied_tab_import_file_paths(
    provenance: PromptProvenanceEvidence,
) -> frozenset[str]:
    """Return path-only TSV inputs sealed in ordinary mutation previews."""

    protocol = provenance.protocol
    if protocol is None:
        # A few focused unit fixtures predate protocol-bearing provenance.
        return frozenset()
    steps = getattr(protocol, "steps", None)
    if not isinstance(steps, tuple):
        raise PromptAssetReadError(
            "prompt provenance transaction protocol is unavailable"
        )
    if any(not isinstance(step, ExpectedGatewayStep) for step in steps):
        raise PromptAssetReadError("prompt provenance transaction step is invalid")
    version = provenance.payload.get("version")
    if not isinstance(version, str):
        raise PromptAssetReadError("prompt provenance version is unavailable")
    try:
        requests = materialize_typed_transaction_protocol_requests(
            protocol,
            version=version,
        )
    except ValueError as exc:
        raise PromptAssetReadError(
            "prompt provenance typed transaction cannot be materialized"
        ) from exc
    import_files: set[str] = set()
    for _pointer, request in requests:
        if (
            not isinstance(request, Mapping)
            or set(request)
            != {"contract", "version", "operation", "arguments"}
            or request.get("contract") != "waapi-skill.operation-request/v1"
            or not isinstance(request.get("arguments"), Mapping)
        ):
            raise PromptAssetReadError(
                "prompt provenance transaction request is not closed"
            )
        operation = request.get("operation")
        if not isinstance(operation, str) or not operation:
            raise PromptAssetReadError(
                "prompt provenance transaction preview lacks its operation"
            )
        if operation != "audio.importTabDelimited":
            continue
        import_file = request["arguments"].get("import_file")
        if (
            not isinstance(import_file, str)
            or not import_file
            or "\x00" in import_file
        ):
            raise PromptAssetReadError(
                "tab-import transaction preview lacks its import_file"
            )
        import_files.add(import_file)
    return frozenset(import_files)


def validated_prompt_asset_cat_commands(
    records: Sequence[CodexCommandRecord],
    *,
    provenance: PromptProvenanceEvidence | None,
    turn_index: int,
) -> tuple[str, ...]:
    """Return exact first-turn ``cat`` records proven by sealed asset bytes."""

    if provenance is None or turn_index != 1:
        return ()
    path_only_inputs = _applied_tab_import_file_paths(provenance)
    assets = {
        asset.path: asset
        for asset in sealed_prompt_file_assets(provenance)
        if asset.path not in path_only_inputs
    }
    accepted: list[str] = []
    consumed_paths: set[str] = set()
    for record in records:
        if (
            not isinstance(record, CodexCommandRecord)
            or len(record.argv) != 2
            or record.argv[0] != "cat"
        ):
            continue
        asset = assets.get(record.argv[1])
        if (
            asset is None
            or asset.path in consumed_paths
            or not record.succeeded
            or record.parse_error
            or record.has_shell_operators
        ):
            continue
        try:
            output = record.aggregated_output.encode("utf-8")
        except UnicodeEncodeError:
            continue
        if (
            len(output) != asset.size
            or hashlib.sha256(output).hexdigest() != asset.sha256
        ):
            continue
        consumed_paths.add(asset.path)
        accepted.append(record.command)
    return tuple(accepted)


def remove_validated_command_occurrences(
    commands: Sequence[str],
    validated: Sequence[str],
) -> tuple[str, ...]:
    """Remove only the exact number of independently validated occurrences."""

    remaining = Counter(str(command) for command in validated)
    result: list[str] = []
    for command in commands:
        value = str(command)
        if remaining[value] > 0:
            remaining[value] -= 1
        else:
            result.append(value)
    return tuple(result)


__all__ = [
    "MAX_PROMPT_ASSET_CAT_BYTES",
    "PromptAssetReadError",
    "SealedPromptFileAsset",
    "remove_validated_command_occurrences",
    "sealed_prompt_file_assets",
    "validated_prompt_asset_cat_commands",
]
