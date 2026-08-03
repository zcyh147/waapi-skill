"""Closed operation plans for Wwise Authoring UI commands.

The reflected ``ui.commands`` schemas are intentionally wider than the public
Skill boundary.  In particular, command add-on registration accepts strings
that Wwise can use to launch external programs.  This module never accepts a
raw WAAPI payload, shell command string, or script source.  Instead it:

* builds ``execute`` calls from bounded scalar fields and, on Wwise 2025.1,
  immutable local-file proofs, then requires a fresh ``getCommands`` membership
  check and proof replay immediately before dispatch;
* builds ``register`` calls from closed, version-aware command descriptors,
  structured argument-token arrays, and immutable local path proofs;
* treats standalone descriptor-backed ``unregister`` requests only as sealed
  deletion-definition evidence, with unknown ownership and no inverse;
* exposes a separately acknowledged, likewise non-reversible unregister
  boundary for pre-existing command IDs supplied without definitions.

The module performs no WAAPI calls.  Callers own preview/authorization binding,
the immediately-before/after live checks, and the single non-retried dispatch.

For any program or Lua handler, the caller must also attest
``source_authority="user_supplied_verbatim"``.  This assertion is eligible only
when the current user message supplied the exact existing path and fields.  It
must never be set for model-generated, repaired, rewritten, or wrapper code.
The assertion is sealed into the plan, but runtime path proofs cannot establish
conversational provenance; they prove only local path identity and content.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
import shlex
import stat
import subprocess
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Mapping, Sequence

from .authorization import DEFAULT_TRANSACTION_AUTHORIZATION_MODES
from .canonical import canonical_json_bytes, canonical_sha256
from .versions import SUPPORTED_WWISE_VERSION_KEYS


UI_COMMAND_PLAN_CONTRACT = "waapi-skill.ui-command-operation-plan/v2"
UI_COMMAND_FILE_PROOF_CONTRACT = "waapi-skill.ui-command-path-proof/v1"
UI_COMMAND_INVENTORY_EVIDENCE_CONTRACT = (
    "waapi-skill.ui-command-inventory-evidence/v1"
)
UI_COMMAND_REGISTRATION_RELATIONSHIP_CONTRACT = (
    "waapi-skill.ui-command-registration-relationship/v1"
)

EXECUTE_URI = "ak.wwise.ui.commands.execute"
GET_COMMANDS_URI = "ak.wwise.ui.commands.getCommands"
REGISTER_URI = "ak.wwise.ui.commands.register"
UNREGISTER_URI = "ak.wwise.ui.commands.unregister"
AUTHORING_HOST_SURFACE = "wwise-authoring"

UNREGISTER_EXISTING_ACKNOWLEDGEMENT = (
    "unregister_existing_commands_without_definition"
)
USER_SUPPLIED_SOURCE_AUTHORITY = "user_supplied_verbatim"

MAX_PLAN_BYTES = 256 * 1024
MAX_COMMANDS_PER_PLAN = 32
MAX_COMMAND_ID_CHARS = 512
MAX_DISPLAY_NAME_CHARS = 256
MAX_OBJECT_ARGUMENTS = 64
MAX_OBJECT_ARGUMENT_CHARS = 1024
MAX_PLATFORM_ARGUMENTS = 16
MAX_PLATFORM_ARGUMENT_CHARS = 256
MAX_COMMAND_FILES = 64
MAX_ARGUMENT_TOKENS = 64
MAX_ARGUMENT_TOKEN_CHARS = 4096
MAX_ENCODED_ARGUMENT_CHARS = 32 * 1024
MAX_PATH_CHARS = 4096
MAX_MENU_SEGMENTS = 8
MAX_MENU_SEGMENT_CHARS = 128
MAX_OBJECT_TYPES = 64
MAX_OBJECT_TYPE_CHARS = 128
MAX_DEFAULT_SHORTCUT_CHARS = 64
MAX_LUA_MODULE_DIRECTORIES = 16
MAX_LUA_SELECTED_RETURN_FIELDS = 64
MAX_LUA_SELECTED_RETURN_CHARS = 1024
MAX_EXECUTABLE_BYTES = 512 * 1024 * 1024
MAX_LUA_SCRIPT_BYTES = 16 * 1024 * 1024
MAX_COMMAND_FILE_BYTES = 512 * 1024 * 1024
MAX_COMMAND_FILES_TOTAL_BYTES = 2 * 1024 * 1024 * 1024
MAX_LIVE_COMMANDS = 4096
MAX_LIVE_COMMAND_ID_CHARS = 512
MAX_LIVE_INVENTORY_BYTES = 1_000_000

HOST_PLATFORMS = frozenset({"macos", "windows"})
START_MODES = frozenset(
    {
        "SingleSelectionSingleProcess",
        "MultipleSelectionSingleProcessSpaceSeparated",
        "MultipleSelectionMultipleProcesses",
    }
)
LUA_COMMAND_VERSIONS = frozenset({"2023.1", "2024.1", "2025.1"})
EXECUTE_FILES_VERSIONS = frozenset({"2025.1"})

_PLAN_FIELDS = frozenset(
    {
        "cleanup",
        "contract",
        "dispatch",
        "host_platform",
        "host_surface",
        "mode",
        "operation",
        "plan_sha256",
        "request",
        "runtime_preconditions",
        "safety",
        "verification",
        "version",
    }
)
_COMMAND_FIELDS = frozenset(
    {
        "context_menu",
        "default_shortcut",
        "display_name",
        "handler",
        "id",
        "main_menu",
    }
)
_CONTEXT_MENU_FIELDS = frozenset(
    {"base_path", "enabled_for", "visible_for"}
)
_MAIN_MENU_FIELDS = frozenset({"base_path"})
_NOTIFICATION_HANDLER_FIELDS = frozenset({"kind"})
_PROGRAM_HANDLER_FIELDS = frozenset(
    {
        "argument_tokens",
        "kind",
        "program_path",
        "redirect_outputs",
        "start_mode",
        "working_directory",
    }
)
_LUA_HANDLER_FIELDS = frozenset(
    {
        "argument_tokens",
        "kind",
        "lua_module_directories",
        "lua_script_path",
        "lua_selected_return",
        "start_mode",
        "working_directory",
    }
)
_NATIVE_COMMAND_FIELDS_BY_VERSION: Mapping[str, frozenset[str]] = {
    "2021.1": frozenset(
        {
            "args",
            "contextMenu",
            "cwd",
            "defaultShortcut",
            "displayName",
            "id",
            "mainMenu",
            "program",
            "redirectOutputs",
            "startMode",
        }
    ),
    "2022.1": frozenset(
        {
            "args",
            "contextMenu",
            "cwd",
            "defaultShortcut",
            "displayName",
            "id",
            "mainMenu",
            "program",
            "redirectOutputs",
            "startMode",
        }
    ),
    "2023.1": frozenset(
        {
            "args",
            "contextMenu",
            "cwd",
            "defaultShortcut",
            "displayName",
            "id",
            "luaPaths",
            "luaScript",
            "luaSelectedReturn",
            "mainMenu",
            "program",
            "redirectOutputs",
            "startMode",
        }
    ),
    "2024.1": frozenset(
        {
            "args",
            "contextMenu",
            "cwd",
            "defaultShortcut",
            "displayName",
            "id",
            "luaPaths",
            "luaScript",
            "luaSelectedReturn",
            "mainMenu",
            "program",
            "redirectOutputs",
            "startMode",
        }
    ),
    "2025.1": frozenset(
        {
            "args",
            "contextMenu",
            "cwd",
            "defaultShortcut",
            "displayName",
            "id",
            "luaPaths",
            "luaScript",
            "luaSelectedReturn",
            "mainMenu",
            "program",
            "redirectOutputs",
            "startMode",
        }
    ),
}
_DISALLOWED_SHELL_EXECUTABLES = frozenset(
    {
        "bash",
        "cmd",
        "cmd.exe",
        "dash",
        "fish",
        "ksh",
        "powershell",
        "powershell.exe",
        "pwsh",
        "pwsh.exe",
        "sh",
        "zsh",
    }
)
_DISALLOWED_GENERIC_EXECUTABLES = frozenset(
    {
        "arch",
        "awk",
        "bun",
        "bunx",
        "busybox",
        "cargo",
        "cmake",
        "cscript",
        "cscript.exe",
        "deno",
        "doas",
        "dotnet",
        "env",
        "env.exe",
        "explorer.exe",
        "find",
        "gawk",
        "gio",
        "go",
        "ionice",
        "java",
        "javaw",
        "javaw.exe",
        "julia",
        "launchctl",
        "lua",
        "luajit",
        "make",
        "mawk",
        "mono",
        "mshta",
        "mshta.exe",
        "nice",
        "ninja",
        "node",
        "node.exe",
        "nodejs",
        "nohup",
        "npm",
        "npx",
        "open",
        "osascript",
        "parallel",
        "perl",
        "perl.exe",
        "php",
        "pipx",
        "pnpm",
        "poetry",
        "regsvr32",
        "regsvr32.exe",
        "rscript",
        "ruby",
        "ruby.exe",
        "rundll32",
        "rundll32.exe",
        "runuser",
        "rye",
        "sed",
        "setsid",
        "ssh",
        "ssh.exe",
        "sqlite3",
        "sqlite3.exe",
        "start",
        "start.exe",
        "stdbuf",
        "su",
        "sudo",
        "swift",
        "systemd-run",
        "time",
        "timeout",
        "ts-node",
        "tsx",
        "uv",
        "wscript",
        "wscript.exe",
        "xargs",
        "xcrun",
        "xdg-open",
        "yarn",
    }
)
_GENERIC_INTERPRETER_NAME = re.compile(
    r"^(?:python(?:w)?|pythonw|ruby|perl|php|lua|luajit|node|nodejs)"
    r"(?:\d+(?:\.\d+)*)?(?:\.exe)?$",
    re.IGNORECASE,
)
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_UNSET = object()
_INVENTORY_GUARD_FIELDS = frozenset(
    {
        "command_ids",
        "expected_membership",
        "fail_closed",
        "max_command_chars",
        "max_commands",
        "max_inventory_bytes",
        "source_uri",
        "timing",
    }
)


class UiCommandContractError(ValueError):
    """A UI-command request, plan, or live proof failed closed."""

    def __init__(
        self,
        error_code: str,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.details = dict(details or {})

    def as_dict(self) -> dict[str, Any]:
        return {
            "error_code": self.error_code,
            "message": self.message,
            "details": dict(self.details),
        }


def build_ui_command_execute_plan(
    *,
    version: str,
    command: Any,
    objects: Any = (),
    platforms: Any = (),
    value: Any = _UNSET,
    files: Any = _UNSET,
) -> dict[str, Any]:
    """Build one bounded execute plan with a mandatory live inventory guard."""

    lane = _require_version(version)
    command_id = _bounded_text(
        command,
        field="command",
        maximum=MAX_COMMAND_ID_CHARS,
        allow_empty=False,
    )
    object_rows = _bounded_unique_strings(
        objects,
        field="objects",
        limit=MAX_OBJECT_ARGUMENTS,
        maximum=MAX_OBJECT_ARGUMENT_CHARS,
        allow_empty=True,
    )
    platform_rows = _bounded_unique_strings(
        platforms,
        field="platforms",
        limit=MAX_PLATFORM_ARGUMENTS,
        maximum=MAX_PLATFORM_ARGUMENT_CHARS,
        allow_empty=True,
    )
    file_rows: list[str] = []
    proof_entries: list[dict[str, Any]] = []
    if files is not _UNSET:
        _require_execute_files_version(lane)
        file_rows = _bounded_unique_strings(
            files,
            field="files",
            limit=MAX_COMMAND_FILES,
            maximum=MAX_PATH_CHARS,
            allow_empty=True,
            normalize_path=True,
        )
        proof_entries = _capture_execute_file_proofs(
            command_id,
            file_rows,
        )
    normalized_value = _normalize_property_value(value)
    request: dict[str, Any] = {"command": command_id}
    if object_rows:
        request["objects"] = object_rows
    if platform_rows:
        request["platforms"] = platform_rows
    if file_rows:
        request["files"] = file_rows
    if normalized_value is not _UNSET:
        request["value"] = normalized_value
    return _assemble_execute_plan(
        version=lane,
        request=request,
        proof_entries=proof_entries,
    )


def build_ui_commands_register_plan(
    *,
    version: str,
    host_platform: str,
    commands: Any,
    source_authority: Any = None,
) -> dict[str, Any]:
    """Build a versioned registration plan from closed command descriptors."""

    lane = _require_version(version)
    host = _require_host_platform(host_platform)
    normalized, proof_entries = _normalize_registration_commands(
        commands,
        version=lane,
        host_platform=host,
        capture_proofs=True,
    )
    authority = _normalize_source_authority(
        normalized,
        value=source_authority,
        supplied=source_authority is not None,
    )
    return _assemble_register_plan(
        version=lane,
        host_platform=host,
        commands=normalized,
        proof_entries=proof_entries,
        source_authority=authority,
    )


def build_ui_commands_unregister_plan(
    register_plan: Mapping[str, Any],
) -> dict[str, Any]:
    """Reject an unbound attempt to infer a reversible unregister plan.

    A sealed register plan proves only preview intent.  It does not prove that
    the corresponding registration executed and verified successfully.  A
    reversible unregister must therefore come from the journal-bound cleanup
    companion of that successful transaction, not from this standalone helper.
    """

    validated = validate_ui_command_plan(register_plan)
    if (
        validated["operation"] != "register"
        or validated["mode"] != "closed_descriptors"
    ):
        raise UiCommandContractError(
            "INVALID_ARGUMENT",
            "The supplied plan is not a sealed UI-command register plan.",
        )
    raise UiCommandContractError(
        "VERIFIED_REGISTER_TRANSACTION_REQUIRED",
        "A sealed register plan proves preview intent, not successful "
        "registration. Reversible unregister is available only through the "
        "journal-bound cleanup companion of a successfully executed and "
        "verified register transaction.",
        details={
            "source_register_plan_sha256": validated["plan_sha256"],
            "standalone_inverse_supported": False,
        },
    )


def build_ui_commands_unregister_descriptors_plan(
    *,
    version: str,
    host_platform: str,
    commands: Any,
    source_authority: Any = None,
) -> dict[str, Any]:
    """Build a non-reversible unregister plan from descriptor evidence.

    The descriptors deterministically define the IDs the caller asks to remove
    and retain immutable path evidence when applicable.  ``getCommands`` can
    prove only that those IDs exist; it cannot prove who registered them or
    that their live definitions match the supplied descriptors.
    """

    lane = _require_version(version)
    host = _require_host_platform(host_platform)
    normalized, proof_entries = _normalize_registration_commands(
        commands,
        version=lane,
        host_platform=host,
        capture_proofs=True,
    )
    authority = _normalize_source_authority(
        normalized,
        value=source_authority,
        supplied=source_authority is not None,
    )
    return _assemble_descriptor_unregister_plan(
        version=lane,
        host_platform=host,
        commands=normalized,
        proof_entries=proof_entries,
        source_authority=authority,
    )


def build_ui_commands_unregister_existing_plan(
    *,
    version: str,
    command_ids: Any,
    acknowledgement: Any,
) -> dict[str, Any]:
    """Build the explicit weak boundary for pre-existing command IDs.

    The caller cannot prove whether these IDs belong to built-in commands or
    add-ons, and ``getCommands`` exposes no registration definition from which
    an inverse registration could be constructed.  Therefore this plan has no
    automatic or claimed cleanup.
    """

    lane = _require_version(version)
    ids = _bounded_unique_strings(
        command_ids,
        field="command_ids",
        limit=MAX_COMMANDS_PER_PLAN,
        maximum=MAX_COMMAND_ID_CHARS,
        allow_empty=False,
        sort_values=True,
    )
    if acknowledgement != UNREGISTER_EXISTING_ACKNOWLEDGEMENT:
        raise UiCommandContractError(
            "ACKNOWLEDGEMENT_REQUIRED",
            "Unregistering existing command IDs requires the fixed ownership "
            "and irreversibility acknowledgement.",
            details={
                "required_acknowledgement": (
                    UNREGISTER_EXISTING_ACKNOWLEDGEMENT
                )
            },
        )
    request = {
        "acknowledgement": UNREGISTER_EXISTING_ACKNOWLEDGEMENT,
        "command_ids": ids,
    }
    return _assemble_existing_unregister_plan(version=lane, request=request)


def validate_ui_command_plan(plan: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a sealed plan without performing live or filesystem I/O."""

    if not isinstance(plan, Mapping):
        raise UiCommandContractError(
            "INVALID_PLAN",
            "UI-command plan must be an object.",
        )
    _require_exact_fields(plan, _PLAN_FIELDS, field="plan")
    if plan.get("contract") != UI_COMMAND_PLAN_CONTRACT:
        raise UiCommandContractError(
            "INVALID_PLAN",
            "UI-command plan uses an unknown contract.",
        )
    lane = _require_version(plan.get("version"))
    if plan.get("host_surface") != AUTHORING_HOST_SURFACE:
        raise UiCommandContractError(
            "INVALID_PLAN",
            "UI-command plans are available only on Wwise Authoring.",
        )
    expected_seal = plan.get("plan_sha256")
    if not isinstance(expected_seal, str) or not _SHA256.fullmatch(expected_seal):
        raise UiCommandContractError(
            "INVALID_PLAN",
            "UI-command plan lacks a valid SHA-256 seal.",
        )
    body = {key: value for key, value in plan.items() if key != "plan_sha256"}
    actual_seal = canonical_sha256(body)
    if actual_seal != expected_seal:
        raise UiCommandContractError(
            "PLAN_TAMPERED",
            "UI-command plan SHA-256 seal does not match its contents.",
            details={"actual": actual_seal, "expected": expected_seal},
        )
    if len(canonical_json_bytes(plan)) > MAX_PLAN_BYTES:
        raise UiCommandContractError(
            "LIMIT_EXCEEDED",
            f"UI-command plan exceeds the {MAX_PLAN_BYTES} byte ceiling.",
        )

    operation = plan.get("operation")
    mode = plan.get("mode")
    if operation == "execute" and mode == "live_inventory_bound":
        expected = _validate_and_rebuild_execute_plan(plan, version=lane)
    elif operation == "register" and mode == "closed_descriptors":
        expected = _validate_and_rebuild_register_plan(plan, version=lane)
    elif (
        operation == "unregister"
        and mode == "unknown_ownership_descriptors"
    ):
        expected = _validate_and_rebuild_descriptor_unregister_plan(
            plan,
            version=lane,
        )
    elif (
        operation == "unregister"
        and mode == "acknowledged_existing_ids"
    ):
        expected = _validate_and_rebuild_existing_unregister_plan(
            plan,
            version=lane,
        )
    else:
        raise UiCommandContractError(
            "INVALID_PLAN",
            "UI-command plan has an unknown operation or mode.",
            details={"mode": mode, "operation": operation},
        )
    if expected != dict(plan):
        raise UiCommandContractError(
            "INVALID_PLAN",
            "UI-command plan does not match its deterministic closed form.",
        )
    return expected


def validate_ui_command_runtime_preconditions(
    plan: Mapping[str, Any],
    live_get_commands_result: Mapping[str, Any],
) -> dict[str, Any]:
    """Revalidate the live inventory and local paths immediately before call.

    The caller must invoke this on the same Authoring connection immediately
    before the single dispatch.  A previously collected repository inventory
    is not a substitute because installed plug-ins, add-ons, and project state
    can change the available command IDs.
    """

    validated = validate_ui_command_plan(plan)
    guard = validated["runtime_preconditions"]["command_inventory"]
    evidence = _evaluate_inventory_guard(
        guard,
        live_get_commands_result,
        version=validated["version"],
        phase="pre_dispatch",
    )
    file_rows = revalidate_ui_command_file_proofs(validated)
    return {
        "command_inventory": evidence,
        "contract": "waapi-skill.ui-command-runtime-preconditions/v1",
        "file_proofs": file_rows,
        "passed": True,
        "plan_sha256": validated["plan_sha256"],
    }


def revalidate_ui_command_file_proofs(
    plan: Mapping[str, Any],
    *,
    cleanup: bool = False,
) -> list[dict[str, Any]]:
    """Replay path proofs for the operation or its inverse cleanup."""

    validated = validate_ui_command_plan(plan)
    container = (
        validated["cleanup"]["runtime_preconditions"]
        if cleanup
        else validated["runtime_preconditions"]
    )
    entries = container.get("file_proofs", [])
    if not isinstance(entries, list):
        raise UiCommandContractError(
            "INVALID_PLAN",
            "UI-command file proof list is malformed.",
        )
    results: list[dict[str, Any]] = []
    for entry in entries:
        _validate_proof_entry(entry)
        expected = entry["proof"]
        actual = _capture_path_proof(
            expected["path"],
            role=expected["role"],
        )
        compared = (
            "content_sha256",
            "device",
            "executable",
            "inode",
            "kind",
            "mode",
            "mtime_ns",
            "path",
            "size",
        )
        changed = [
            field
            for field in compared
            if actual.get(field) != expected.get(field)
        ]
        if changed:
            raise UiCommandContractError(
                "PATH_CHANGED",
                "A UI-command executable, script, or directory changed after "
                "preview.",
                details={
                    "changed_fields": changed,
                    "command_id": entry["command_id"],
                    "request_field": entry["request_field"],
                },
            )
        results.append(
            {
                "command_id": entry["command_id"],
                "proof_sha256": actual["proof_sha256"],
                "request_field": entry["request_field"],
            }
        )
    return results


def verify_ui_command_inventory_postcondition(
    plan: Mapping[str, Any],
    live_get_commands_result: Mapping[str, Any],
) -> dict[str, Any]:
    """Verify register/unregister membership using a fresh live inventory."""

    validated = validate_ui_command_plan(plan)
    verification = validated["verification"]
    if verification.get("kind") != "command_inventory_membership":
        raise UiCommandContractError(
            "WEAK_VERIFICATION_BOUNDARY",
            "This UI-command operation has no business-state inventory "
            "postcondition.",
            details={
                "operation": validated["operation"],
                "verification": verification,
            },
        )
    guard = {
        field: verification[field]
        for field in _INVENTORY_GUARD_FIELDS
        if field in verification
    }
    return _evaluate_inventory_guard(
        guard,
        live_get_commands_result,
        version=validated["version"],
        phase="post_dispatch",
    )


def validate_empty_ui_command_result(
    plan: Mapping[str, Any],
    result: Any,
) -> dict[str, Any]:
    """Validate the reflected empty result object without overstating effect."""

    validated = validate_ui_command_plan(plan)
    if not isinstance(result, Mapping) or dict(result):
        raise UiCommandContractError(
            "INVALID_RESULT",
            "The reflected UI-command result must be an empty object.",
        )
    effect_verified = validated["operation"] in {"register", "unregister"}
    return {
        "contract": "waapi-skill.ui-command-result-schema-evidence/v1",
        "effect_requires_inventory_postcondition": effect_verified,
        "effect_verified": False,
        "passed": True,
        "plan_sha256": validated["plan_sha256"],
        "result_schema_verified": True,
        "verification_strength": "result_schema_only",
    }


def _assemble_execute_plan(
    *,
    version: str,
    request: Mapping[str, Any],
    proof_entries: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    command = request["command"]
    guard = _inventory_guard(
        command_ids=[command],
        expected_membership="present",
        timing="immediately_before_dispatch",
    )
    body = {
        "cleanup": _no_cleanup(
            "A generic UI command can have arbitrary GUI or project effects; "
            "no inverse operation can be derived from the command ID."
        ),
        "contract": UI_COMMAND_PLAN_CONTRACT,
        "dispatch": {
            "arguments": dict(request),
            "options": {},
            "uri": EXECUTE_URI,
        },
        "host_platform": None,
        "host_surface": AUTHORING_HOST_SURFACE,
        "mode": "live_inventory_bound",
        "operation": "execute",
        "request": dict(request),
        "runtime_preconditions": {
            "command_inventory": guard,
            "file_proofs": _copy_json_sequence(proof_entries),
        },
        "safety": _safety_metadata(),
        "verification": {
            "command_effect_readback_available": False,
            "expected_result": {},
            "kind": "result_schema_only",
            "pre_dispatch_inventory_is_effect_verification": False,
            "uri": EXECUTE_URI,
        },
        "version": version,
    }
    return _seal_plan(body)


def _assemble_register_plan(
    *,
    version: str,
    host_platform: str,
    commands: Sequence[Mapping[str, Any]],
    proof_entries: Sequence[Mapping[str, Any]],
    source_authority: str | None,
) -> dict[str, Any]:
    request = {"commands": _copy_json_sequence(commands)}
    if source_authority is not None:
        request["source_authority"] = source_authority
    native_commands = _materialize_commands(
        request["commands"],
        version=version,
        host_platform=host_platform,
    )
    command_ids = [row["id"] for row in native_commands]
    relationship = _registration_relationship(
        version=version,
        host_platform=host_platform,
        commands=request["commands"],
        source_authority=source_authority,
    )
    inverse_dispatch = {
        "arguments": {"commands": command_ids},
        "options": {},
        "uri": UNREGISTER_URI,
    }
    body = {
        "cleanup": {
            "automatic": False,
            "dispatch": inverse_dispatch,
            "kind": "inverse_ui_command_registration",
            "relationship_sha256": relationship["relationship_sha256"],
            "reversible": True,
            "runtime_preconditions": {
                "command_inventory": _inventory_guard(
                    command_ids=command_ids,
                    expected_membership="present",
                    timing="immediately_before_cleanup",
                ),
                "file_proofs": [],
            },
            "verification": _inventory_verification(
                command_ids=command_ids,
                expected_membership="absent",
            ),
        },
        "contract": UI_COMMAND_PLAN_CONTRACT,
        "dispatch": {
            "arguments": {"commands": native_commands},
            "options": {},
            "uri": REGISTER_URI,
        },
        "host_platform": host_platform,
        "host_surface": AUTHORING_HOST_SURFACE,
        "mode": "closed_descriptors",
        "operation": "register",
        "request": request,
        "runtime_preconditions": {
            "command_inventory": _inventory_guard(
                command_ids=command_ids,
                expected_membership="absent",
                timing="immediately_before_dispatch",
            ),
            "file_proofs": _copy_json_sequence(proof_entries),
            "source_authority": _source_authority_metadata(
                request["commands"],
                source_authority=source_authority,
            ),
        },
        "safety": _safety_metadata(),
        "verification": _inventory_verification(
            command_ids=command_ids,
            expected_membership="present",
        ),
        "version": version,
    }
    return _seal_plan(body)


def _assemble_descriptor_unregister_plan(
    *,
    version: str,
    host_platform: str,
    commands: Sequence[Mapping[str, Any]],
    proof_entries: Sequence[Mapping[str, Any]],
    source_authority: str | None,
) -> dict[str, Any]:
    native_commands = _materialize_commands(
        commands,
        version=version,
        host_platform=host_platform,
    )
    command_ids = [row["id"] for row in native_commands]
    request = {"commands": _copy_json_sequence(commands)}
    if source_authority is not None:
        request["source_authority"] = source_authority
    body = {
        "cleanup": _no_cleanup(
            "The supplied descriptors define the requested IDs but do not "
            "prove ownership or the live registration definition; a "
            "standalone inverse registration cannot be reconstructed."
        ),
        "contract": UI_COMMAND_PLAN_CONTRACT,
        "dispatch": {
            "arguments": {"commands": command_ids},
            "options": {},
            "uri": UNREGISTER_URI,
        },
        "host_platform": host_platform,
        "host_surface": AUTHORING_HOST_SURFACE,
        "mode": "unknown_ownership_descriptors",
        "operation": "unregister",
        "request": request,
        "runtime_preconditions": {
            "command_inventory": _inventory_guard(
                command_ids=command_ids,
                expected_membership="present",
                timing="immediately_before_dispatch",
            ),
            "file_proofs": _copy_json_sequence(proof_entries),
            "live_definition_match_proven": False,
            "ownership_known": False,
            "source_authority": _source_authority_metadata(
                commands,
                source_authority=source_authority,
            ),
        },
        "safety": _safety_metadata(),
        "verification": _inventory_verification(
            command_ids=command_ids,
            expected_membership="absent",
        ),
        "version": version,
    }
    return _seal_plan(body)


def _assemble_existing_unregister_plan(
    *,
    version: str,
    request: Mapping[str, Any],
) -> dict[str, Any]:
    command_ids = list(request["command_ids"])
    body = {
        "cleanup": _no_cleanup(
            "getCommands exposes IDs but not command definitions or ownership; "
            "the Skill cannot reconstruct a removed registration."
        ),
        "contract": UI_COMMAND_PLAN_CONTRACT,
        "dispatch": {
            "arguments": {"commands": command_ids},
            "options": {},
            "uri": UNREGISTER_URI,
        },
        "host_platform": None,
        "host_surface": AUTHORING_HOST_SURFACE,
        "mode": "acknowledged_existing_ids",
        "operation": "unregister",
        "request": dict(request),
        "runtime_preconditions": {
            "command_inventory": _inventory_guard(
                command_ids=command_ids,
                expected_membership="present",
                timing="immediately_before_dispatch",
            ),
            "file_proofs": [],
            "ownership_known": False,
        },
        "safety": _safety_metadata(),
        "verification": _inventory_verification(
            command_ids=command_ids,
            expected_membership="absent",
        ),
        "version": version,
    }
    return _seal_plan(body)


def _validate_and_rebuild_execute_plan(
    plan: Mapping[str, Any],
    *,
    version: str,
) -> dict[str, Any]:
    if plan.get("host_platform") is not None:
        raise UiCommandContractError(
            "INVALID_PLAN",
            "execute plan host_platform must be null.",
        )
    request = plan.get("request")
    if not isinstance(request, Mapping):
        raise UiCommandContractError(
            "INVALID_PLAN",
            "execute request must be an object.",
        )
    allowed = {"command", "files", "objects", "platforms", "value"}
    unknown = set(request) - allowed
    if "command" not in request or unknown:
        raise UiCommandContractError(
            "INVALID_PLAN",
            "execute request contains unknown or missing fields.",
            details={"unknown": sorted(unknown)},
        )
    command = _bounded_text(
        request.get("command"),
        field="request.command",
        maximum=MAX_COMMAND_ID_CHARS,
        allow_empty=False,
    )
    objects = _bounded_unique_strings(
        request.get("objects", []),
        field="request.objects",
        limit=MAX_OBJECT_ARGUMENTS,
        maximum=MAX_OBJECT_ARGUMENT_CHARS,
        allow_empty=True,
    )
    platforms = _bounded_unique_strings(
        request.get("platforms", []),
        field="request.platforms",
        limit=MAX_PLATFORM_ARGUMENTS,
        maximum=MAX_PLATFORM_ARGUMENT_CHARS,
        allow_empty=True,
    )
    files: list[str] = []
    if "files" in request:
        _require_execute_files_version(version)
        files = _bounded_unique_strings(
            request.get("files"),
            field="request.files",
            limit=MAX_COMMAND_FILES,
            maximum=MAX_PATH_CHARS,
            allow_empty=True,
            normalize_path=True,
        )
    value = (
        _normalize_property_value(request["value"])
        if "value" in request
        else _UNSET
    )
    normalized: dict[str, Any] = {"command": command}
    if objects:
        normalized["objects"] = objects
    if platforms:
        normalized["platforms"] = platforms
    if files:
        normalized["files"] = files
    if value is not _UNSET:
        normalized["value"] = value
    preconditions = plan.get("runtime_preconditions")
    if not isinstance(preconditions, Mapping):
        raise UiCommandContractError(
            "INVALID_PLAN",
            "execute runtime preconditions must be an object.",
        )
    _require_exact_fields(
        preconditions,
        {"command_inventory", "file_proofs"},
        field="runtime_preconditions",
    )
    proofs = preconditions.get("file_proofs")
    _validate_execute_file_proofs(command, files, proofs)
    return _assemble_execute_plan(
        version=version,
        request=normalized,
        proof_entries=proofs,
    )


def _validate_and_rebuild_register_plan(
    plan: Mapping[str, Any],
    *,
    version: str,
) -> dict[str, Any]:
    host = _require_host_platform(plan.get("host_platform"))
    request = plan.get("request")
    if not isinstance(request, Mapping):
        raise UiCommandContractError(
            "INVALID_PLAN",
            "register request must be an object.",
        )
    _require_allowed_and_required_fields(
        request,
        allowed={"commands", "source_authority"},
        required={"commands"},
        field="request",
    )
    commands, _ = _normalize_registration_commands(
        request.get("commands"),
        version=version,
        host_platform=host,
        capture_proofs=False,
    )
    source_authority = _normalize_source_authority(
        commands,
        value=request.get("source_authority"),
        supplied="source_authority" in request,
    )
    preconditions = plan.get("runtime_preconditions")
    if not isinstance(preconditions, Mapping):
        raise UiCommandContractError(
            "INVALID_PLAN",
            "register runtime preconditions must be an object.",
        )
    _require_exact_fields(
        preconditions,
        {"command_inventory", "file_proofs", "source_authority"},
        field="runtime_preconditions",
    )
    proofs = preconditions.get("file_proofs")
    _validate_registration_proofs(commands, proofs)
    return _assemble_register_plan(
        version=version,
        host_platform=host,
        commands=commands,
        proof_entries=proofs,
        source_authority=source_authority,
    )


def _validate_and_rebuild_descriptor_unregister_plan(
    plan: Mapping[str, Any],
    *,
    version: str,
) -> dict[str, Any]:
    host = _require_host_platform(plan.get("host_platform"))
    request = plan.get("request")
    if not isinstance(request, Mapping):
        raise UiCommandContractError(
            "INVALID_PLAN",
            "descriptor-backed unregister request must be an object.",
        )
    _require_allowed_and_required_fields(
        request,
        allowed={"commands", "source_authority"},
        required={"commands"},
        field="request",
    )
    commands, _ = _normalize_registration_commands(
        request.get("commands"),
        version=version,
        host_platform=host,
        capture_proofs=False,
    )
    source_authority = _normalize_source_authority(
        commands,
        value=request.get("source_authority"),
        supplied="source_authority" in request,
    )
    preconditions = plan.get("runtime_preconditions")
    if not isinstance(preconditions, Mapping):
        raise UiCommandContractError(
            "INVALID_PLAN",
            "descriptor-backed unregister runtime preconditions must be an object.",
        )
    _require_exact_fields(
        preconditions,
        {
            "command_inventory",
            "file_proofs",
            "live_definition_match_proven",
            "ownership_known",
            "source_authority",
        },
        field="runtime_preconditions",
    )
    if preconditions.get("ownership_known") is not False:
        raise UiCommandContractError(
            "INVALID_PLAN",
            "descriptor-backed unregister ownership must remain unknown.",
        )
    if preconditions.get("live_definition_match_proven") is not False:
        raise UiCommandContractError(
            "INVALID_PLAN",
            "descriptor-backed unregister cannot claim a live definition match.",
        )
    proofs = preconditions.get("file_proofs")
    _validate_registration_proofs(commands, proofs)
    return _assemble_descriptor_unregister_plan(
        version=version,
        host_platform=host,
        commands=commands,
        proof_entries=proofs,
        source_authority=source_authority,
    )


def _validate_and_rebuild_existing_unregister_plan(
    plan: Mapping[str, Any],
    *,
    version: str,
) -> dict[str, Any]:
    if plan.get("host_platform") is not None:
        raise UiCommandContractError(
            "INVALID_PLAN",
            "existing-ID unregister host_platform must be null.",
        )
    request = plan.get("request")
    if not isinstance(request, Mapping):
        raise UiCommandContractError(
            "INVALID_PLAN",
            "existing-ID unregister request must be an object.",
        )
    _require_exact_fields(
        request,
        {"acknowledgement", "command_ids"},
        field="request",
    )
    ids = _bounded_unique_strings(
        request.get("command_ids"),
        field="request.command_ids",
        limit=MAX_COMMANDS_PER_PLAN,
        maximum=MAX_COMMAND_ID_CHARS,
        allow_empty=False,
        sort_values=True,
    )
    if request.get("acknowledgement") != UNREGISTER_EXISTING_ACKNOWLEDGEMENT:
        raise UiCommandContractError(
            "INVALID_PLAN",
            "existing-ID unregister acknowledgement is invalid.",
        )
    return _assemble_existing_unregister_plan(
        version=version,
        request={
            "acknowledgement": UNREGISTER_EXISTING_ACKNOWLEDGEMENT,
            "command_ids": ids,
        },
    )


def _normalize_registration_commands(
    value: Any,
    *,
    version: str,
    host_platform: str,
    capture_proofs: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows = _require_sequence(value, field="commands")
    if not rows or len(rows) > MAX_COMMANDS_PER_PLAN:
        raise UiCommandContractError(
            "LIMIT_EXCEEDED",
            "commands must be a non-empty bounded array.",
            details={"count": len(rows), "limit": MAX_COMMANDS_PER_PLAN},
        )
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(rows):
        if not isinstance(raw, Mapping):
            raise UiCommandContractError(
                "INVALID_ARGUMENT",
                f"commands[{index}] must be an object.",
            )
        _require_allowed_and_required_fields(
            raw,
            allowed=_COMMAND_FIELDS,
            required={"id", "display_name", "handler"},
            field=f"commands[{index}]",
        )
        command_id = _bounded_text(
            raw.get("id"),
            field=f"commands[{index}].id",
            maximum=MAX_COMMAND_ID_CHARS,
            allow_empty=False,
        )
        folded = command_id.casefold()
        if folded in seen:
            raise UiCommandContractError(
                "DUPLICATE_ARGUMENT",
                f"commands contains duplicate command ID {command_id!r}.",
            )
        display_name = _bounded_text(
            raw.get("display_name"),
            field=f"commands[{index}].display_name",
            maximum=MAX_DISPLAY_NAME_CHARS,
            allow_empty=False,
        )
        handler = _normalize_handler(
            raw.get("handler"),
            version=version,
            host_platform=host_platform,
            field=f"commands[{index}].handler",
        )
        row: dict[str, Any] = {
            "display_name": display_name,
            "handler": handler,
            "id": command_id,
        }
        if "default_shortcut" in raw:
            row["default_shortcut"] = _bounded_text(
                raw.get("default_shortcut"),
                field=f"commands[{index}].default_shortcut",
                maximum=MAX_DEFAULT_SHORTCUT_CHARS,
                allow_empty=True,
            )
        if "context_menu" in raw:
            row["context_menu"] = _normalize_context_menu(
                raw.get("context_menu"),
                field=f"commands[{index}].context_menu",
            )
        if "main_menu" in raw:
            row["main_menu"] = _normalize_main_menu(
                raw.get("main_menu"),
                field=f"commands[{index}].main_menu",
            )
        normalized.append(row)
        seen.add(folded)
    normalized.sort(key=lambda row: (row["id"].casefold(), row["id"]))

    proofs: list[dict[str, Any]] = []
    if capture_proofs:
        for row in normalized:
            proofs.extend(_capture_handler_proofs(row))
    return normalized, proofs


def _normalize_handler(
    value: Any,
    *,
    version: str,
    host_platform: str,
    field: str,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise UiCommandContractError(
            "INVALID_ARGUMENT",
            f"{field} must be an object.",
        )
    kind = value.get("kind")
    if kind == "notification":
        _require_exact_fields(value, _NOTIFICATION_HANDLER_FIELDS, field=field)
        return {"kind": "notification"}
    if kind == "program":
        _require_allowed_and_required_fields(
            value,
            allowed=_PROGRAM_HANDLER_FIELDS,
            required={"kind", "program_path"},
            field=field,
        )
        program_path = _normalize_absolute_path_text(
            value.get("program_path"),
            field=f"{field}.program_path",
        )
        tokens = _normalize_argument_tokens(
            value.get("argument_tokens", []),
            field=f"{field}.argument_tokens",
        )
        _validate_program_boundary(
            program_path,
            tokens,
            field=field,
        )
        redirect_outputs = _optional_bool(
            value,
            "redirect_outputs",
            default=False,
            field=f"{field}.redirect_outputs",
        )
        if redirect_outputs and host_platform != "windows":
            raise UiCommandContractError(
                "HOST_BEHAVIOR_BOUNDARY",
                "redirect_outputs is available only for Wwise Authoring on "
                "Windows.",
                details={
                    "field": "redirect_outputs",
                    "host_platform": host_platform,
                    "supported_host_platforms": ["windows"],
                },
            )
        result: dict[str, Any] = {
            "argument_tokens": tokens,
            "kind": "program",
            "program_path": program_path,
            "redirect_outputs": redirect_outputs,
            "start_mode": _normalize_start_mode(
                value.get(
                    "start_mode",
                    "SingleSelectionSingleProcess",
                ),
                field=f"{field}.start_mode",
            ),
        }
        if "working_directory" in value:
            result["working_directory"] = _normalize_absolute_path_text(
                value.get("working_directory"),
                field=f"{field}.working_directory",
            )
        _encode_argument_tokens(tokens, host_platform=host_platform)
        return result
    if kind == "lua_script":
        if version not in LUA_COMMAND_VERSIONS:
            raise UiCommandContractError(
                "VERSION_BEHAVIOR_BOUNDARY",
                "Lua command add-ons are available only in Wwise "
                "2023.1-2025.1.",
                details={
                    "supported_versions": sorted(LUA_COMMAND_VERSIONS),
                    "version": version,
                },
            )
        _require_allowed_and_required_fields(
            value,
            allowed=_LUA_HANDLER_FIELDS,
            required={"kind", "lua_script_path"},
            field=field,
        )
        tokens = _normalize_argument_tokens(
            value.get("argument_tokens", []),
            field=f"{field}.argument_tokens",
        )
        module_directories = _bounded_unique_strings(
            value.get("lua_module_directories", []),
            field=f"{field}.lua_module_directories",
            limit=MAX_LUA_MODULE_DIRECTORIES,
            maximum=MAX_PATH_CHARS,
            allow_empty=True,
            normalize_path=True,
        )
        selected_return = _bounded_unique_strings(
            value.get("lua_selected_return", []),
            field=f"{field}.lua_selected_return",
            limit=MAX_LUA_SELECTED_RETURN_FIELDS,
            maximum=MAX_LUA_SELECTED_RETURN_CHARS,
            allow_empty=True,
        )
        result = {
            "argument_tokens": tokens,
            "kind": "lua_script",
            "lua_module_directories": module_directories,
            "lua_script_path": _normalize_absolute_path_text(
                value.get("lua_script_path"),
                field=f"{field}.lua_script_path",
            ),
            "lua_selected_return": selected_return,
            "start_mode": _normalize_start_mode(
                value.get(
                    "start_mode",
                    "SingleSelectionSingleProcess",
                ),
                field=f"{field}.start_mode",
            ),
        }
        if "working_directory" in value:
            result["working_directory"] = _normalize_absolute_path_text(
                value.get("working_directory"),
                field=f"{field}.working_directory",
            )
        _encode_argument_tokens(tokens, host_platform=host_platform)
        return result
    raise UiCommandContractError(
        "INVALID_ARGUMENT",
        f"{field}.kind must be notification, program, or lua_script.",
    )


def _normalize_context_menu(value: Any, *, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise UiCommandContractError(
            "INVALID_ARGUMENT",
            f"{field} must be an object.",
        )
    _require_allowed_and_required_fields(
        value,
        allowed=_CONTEXT_MENU_FIELDS,
        required=set(),
        field=field,
    )
    result: dict[str, Any] = {}
    if "base_path" in value:
        result["base_path"] = _menu_path(
            value.get("base_path"),
            field=f"{field}.base_path",
            allow_empty=True,
        )
    for key in ("visible_for", "enabled_for"):
        if key in value:
            result[key] = _object_types(
                value.get(key),
                field=f"{field}.{key}",
            )
    return result


def _normalize_main_menu(value: Any, *, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise UiCommandContractError(
            "INVALID_ARGUMENT",
            f"{field} must be an object.",
        )
    _require_exact_fields(value, _MAIN_MENU_FIELDS, field=field)
    return {
        "base_path": _menu_path(
            value.get("base_path"),
            field=f"{field}.base_path",
            allow_empty=False,
        )
    }


def _materialize_commands(
    commands: Sequence[Mapping[str, Any]],
    *,
    version: str,
    host_platform: str,
) -> list[dict[str, Any]]:
    native: list[dict[str, Any]] = []
    allowed_native = _NATIVE_COMMAND_FIELDS_BY_VERSION[version]
    for row in commands:
        handler = row["handler"]
        item: dict[str, Any] = {
            "id": row["id"],
            "displayName": row["display_name"],
        }
        kind = handler["kind"]
        if kind == "program":
            item["program"] = handler["program_path"]
            _materialize_handler_common(
                item,
                handler,
                host_platform=host_platform,
            )
            if handler["redirect_outputs"]:
                item["redirectOutputs"] = True
        elif kind == "lua_script":
            item["luaScript"] = handler["lua_script_path"]
            _materialize_handler_common(
                item,
                handler,
                host_platform=host_platform,
            )
            if handler["lua_module_directories"]:
                item["luaPaths"] = [
                    _lua_module_search_pattern(
                        path,
                        host_platform=host_platform,
                    )
                    for path in handler["lua_module_directories"]
                ]
            if handler["lua_selected_return"]:
                item["luaSelectedReturn"] = list(
                    handler["lua_selected_return"]
                )
        if "default_shortcut" in row:
            item["defaultShortcut"] = row["default_shortcut"]
        if "context_menu" in row:
            context = row["context_menu"]
            native_context: dict[str, Any] = {}
            if "base_path" in context:
                native_context["basePath"] = "/".join(context["base_path"])
            if "visible_for" in context:
                native_context["visibleFor"] = ",".join(
                    context["visible_for"]
                )
            if "enabled_for" in context:
                native_context["enabledFor"] = ",".join(
                    context["enabled_for"]
                )
            item["contextMenu"] = native_context
        if "main_menu" in row:
            item["mainMenu"] = {
                "basePath": "/".join(row["main_menu"]["base_path"])
            }
        unknown = set(item) - allowed_native
        if unknown:
            raise UiCommandContractError(
                "VERSION_BEHAVIOR_BOUNDARY",
                "A command descriptor materialized fields unavailable in this "
                "Wwise version.",
                details={"unknown_fields": sorted(unknown), "version": version},
            )
        native.append(item)
    return native


def _lua_module_search_pattern(
    directory: str,
    *,
    host_platform: str,
) -> str:
    """Build Wwise's Lua module pattern with the target host's path rules."""

    host = _require_host_platform(host_platform)
    path_type = PureWindowsPath if host == "windows" else PurePosixPath
    return str(path_type(directory) / "?.lua")


def _materialize_handler_common(
    item: dict[str, Any],
    handler: Mapping[str, Any],
    *,
    host_platform: str,
) -> None:
    tokens = handler["argument_tokens"]
    if tokens:
        item["args"] = _encode_argument_tokens(
            tokens,
            host_platform=host_platform,
        )
    if "working_directory" in handler:
        item["cwd"] = handler["working_directory"]
    item["startMode"] = handler["start_mode"]


def _capture_handler_proofs(
    command: Mapping[str, Any],
) -> list[dict[str, Any]]:
    command_id = command["id"]
    handler = command["handler"]
    kind = handler["kind"]
    rows: list[dict[str, Any]] = []
    if kind == "program":
        rows.append(
            _proof_entry(
                command_id,
                "handler.program_path",
                _capture_path_proof(
                    handler["program_path"],
                    role="program_executable",
                ),
            )
        )
    elif kind == "lua_script":
        rows.append(
            _proof_entry(
                command_id,
                "handler.lua_script_path",
                _capture_path_proof(
                    handler["lua_script_path"],
                    role="lua_script",
                ),
            )
        )
        for index, path in enumerate(handler["lua_module_directories"]):
            rows.append(
                _proof_entry(
                    command_id,
                    f"handler.lua_module_directories[{index}]",
                    _capture_path_proof(
                        path,
                        role="lua_module_directory",
                    ),
                )
            )
    if kind in {"program", "lua_script"} and "working_directory" in handler:
        rows.append(
            _proof_entry(
                command_id,
                "handler.working_directory",
                _capture_path_proof(
                    handler["working_directory"],
                    role="working_directory",
                ),
            )
        )
    return rows


def _capture_execute_file_proofs(
    command_id: str,
    files: Sequence[str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, path in enumerate(files):
        rows.append(
            _proof_entry(
                command_id,
                f"files[{index}]",
                _capture_path_proof(path, role="command_file"),
            )
        )
        # Stop as soon as the aggregate ceiling is crossed instead of hashing
        # any later paths in the request.
        _validate_command_file_proof_budget(rows)
    return rows


def _capture_path_proof(value: Any, *, role: str) -> dict[str, Any]:
    path = _normalize_absolute_path(value, field=role)
    expected_kind = (
        "directory"
        if role in {"lua_module_directory", "working_directory"}
        else "file"
    )
    executable_required = role == "program_executable"
    try:
        leaf = path.lstat()
    except OSError as exc:
        raise UiCommandContractError(
            "INVALID_PATH",
            f"{role} must exist and be inspectable.",
            details={"error": str(exc), "path": str(path)},
        ) from exc
    if stat.S_ISLNK(leaf.st_mode):
        raise UiCommandContractError(
            "SYMLINK_NOT_ALLOWED",
            f"{role} must not be a symbolic link.",
            details={"path": str(path)},
        )
    resolved = path.resolve(strict=True)
    if resolved != path:
        raise UiCommandContractError(
            "SYMLINK_NOT_ALLOWED",
            f"{role} must not traverse symbolic links or parent aliases.",
            details={"path": str(path), "resolved_path": str(resolved)},
        )
    if expected_kind == "directory":
        if not stat.S_ISDIR(leaf.st_mode):
            raise UiCommandContractError(
                "INVALID_PATH_KIND",
                f"{role} must be a directory.",
                details={"path": str(path)},
            )
        if not os.access(path, os.R_OK | os.X_OK):
            raise UiCommandContractError(
                "PATH_NOT_ACCESSIBLE",
                f"{role} must be readable and searchable.",
                details={"path": str(path)},
            )
        content_sha256: str | None = None
        observed = leaf
    else:
        if not stat.S_ISREG(leaf.st_mode):
            raise UiCommandContractError(
                "INVALID_PATH_KIND",
                f"{role} must be a regular file.",
                details={"path": str(path)},
            )
        if role == "program_executable":
            maximum = MAX_EXECUTABLE_BYTES
        elif role == "lua_script":
            maximum = MAX_LUA_SCRIPT_BYTES
        elif role == "command_file":
            maximum = MAX_COMMAND_FILE_BYTES
        else:
            raise UiCommandContractError(
                "INVALID_PLAN",
                "UI-command file proof role has no byte ceiling.",
                details={"role": role},
            )
        if leaf.st_size > maximum:
            raise UiCommandContractError(
                "LIMIT_EXCEEDED",
                f"{role} exceeds the closed byte ceiling.",
                details={
                    "limit": maximum,
                    "path": str(path),
                    "size": leaf.st_size,
                },
            )
        if not os.access(path, os.R_OK):
            raise UiCommandContractError(
                "PATH_NOT_ACCESSIBLE",
                f"{role} must be readable.",
                details={"path": str(path)},
            )
        if executable_required and not os.access(path, os.X_OK):
            raise UiCommandContractError(
                "PATH_NOT_EXECUTABLE",
                "program_path must identify an executable regular file.",
                details={"path": str(path)},
            )
        descriptor = _open_no_follow(path)
        digest = hashlib.sha256()
        try:
            with os.fdopen(descriptor, "rb") as opened:
                before = os.fstat(opened.fileno())
                if (
                    before.st_dev != leaf.st_dev
                    or before.st_ino != leaf.st_ino
                    or not stat.S_ISREG(before.st_mode)
                ):
                    raise UiCommandContractError(
                        "PATH_CHANGED",
                        f"{role} changed while its proof was captured.",
                        details={"path": str(path)},
                    )
                for chunk in iter(lambda: opened.read(1024 * 1024), b""):
                    digest.update(chunk)
                observed = os.fstat(opened.fileno())
        except Exception:
            try:
                os.close(descriptor)
            except OSError:
                pass
            raise
        if (
            observed.st_dev != leaf.st_dev
            or observed.st_ino != leaf.st_ino
            or observed.st_size != leaf.st_size
            or observed.st_mtime_ns != leaf.st_mtime_ns
        ):
            raise UiCommandContractError(
                "PATH_CHANGED",
                f"{role} changed while its proof was captured.",
                details={"path": str(path)},
            )
        content_sha256 = digest.hexdigest()
    body = {
        "content_sha256": content_sha256,
        "contract": UI_COMMAND_FILE_PROOF_CONTRACT,
        "device": observed.st_dev,
        "executable": bool(executable_required),
        "inode": observed.st_ino,
        "kind": expected_kind,
        "mode": stat.S_IMODE(observed.st_mode),
        "mtime_ns": observed.st_mtime_ns,
        "path": str(path),
        "role": role,
        "size": observed.st_size,
    }
    return {**body, "proof_sha256": canonical_sha256(body)}


def _open_no_follow(path: Path) -> int:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        return os.open(path, flags)
    except OSError as exc:
        raise UiCommandContractError(
            "INVALID_PATH",
            "A UI-command file could not be opened without following links.",
            details={"error": str(exc), "path": str(path)},
        ) from exc


def _validate_registration_proofs(
    commands: Sequence[Mapping[str, Any]],
    value: Any,
) -> None:
    rows = _require_sequence(value, field="file_proofs")
    expected_refs: list[tuple[str, str, str]] = []
    for command in commands:
        handler = command["handler"]
        kind = handler["kind"]
        if kind == "program":
            expected_refs.append(
                (
                    command["id"],
                    "handler.program_path",
                    handler["program_path"],
                )
            )
        elif kind == "lua_script":
            expected_refs.append(
                (
                    command["id"],
                    "handler.lua_script_path",
                    handler["lua_script_path"],
                )
            )
            expected_refs.extend(
                (
                    command["id"],
                    f"handler.lua_module_directories[{index}]",
                    path,
                )
                for index, path in enumerate(
                    handler["lua_module_directories"]
                )
            )
        if kind in {"program", "lua_script"} and "working_directory" in handler:
            expected_refs.append(
                (
                    command["id"],
                    "handler.working_directory",
                    handler["working_directory"],
                )
            )
    observed_refs: list[tuple[str, str, str]] = []
    for row in rows:
        _validate_proof_entry(row)
        observed_refs.append(
            (
                row["command_id"],
                row["request_field"],
                row["proof"]["path"],
            )
        )
    if observed_refs != expected_refs:
        raise UiCommandContractError(
            "INVALID_PLAN",
            "UI-command path proofs do not exactly match the registration "
            "descriptor paths.",
            details={"expected": expected_refs, "observed": observed_refs},
        )


def _validate_execute_file_proofs(
    command_id: str,
    files: Sequence[str],
    value: Any,
) -> None:
    rows = _require_sequence(value, field="file_proofs")
    expected_refs = [
        (command_id, f"files[{index}]", path)
        for index, path in enumerate(files)
    ]
    observed_refs: list[tuple[str, str, str]] = []
    for row in rows:
        _validate_proof_entry(row)
        if row["proof"]["role"] != "command_file":
            raise UiCommandContractError(
                "INVALID_PLAN",
                "execute file proofs must use the command_file role.",
            )
        observed_refs.append(
            (
                row["command_id"],
                row["request_field"],
                row["proof"]["path"],
            )
        )
    if observed_refs != expected_refs:
        raise UiCommandContractError(
            "INVALID_PLAN",
            "UI-command execute file proofs do not exactly match files.",
            details={"expected": expected_refs, "observed": observed_refs},
        )
    _validate_command_file_proof_budget(rows)


def _validate_command_file_proof_budget(
    rows: Sequence[Mapping[str, Any]],
) -> None:
    total = 0
    for row in rows:
        proof = row.get("proof")
        if not isinstance(proof, Mapping) or proof.get("role") != "command_file":
            raise UiCommandContractError(
                "INVALID_PLAN",
                "Command-file byte accounting requires command_file proofs.",
            )
        size = proof.get("size")
        if type(size) is not int or size < 0:
            raise UiCommandContractError(
                "INVALID_PLAN",
                "Command-file proof size must be a non-negative integer.",
            )
        if size > MAX_COMMAND_FILE_BYTES:
            raise UiCommandContractError(
                "LIMIT_EXCEEDED",
                "command_file exceeds the closed per-file byte ceiling.",
                details={
                    "limit": MAX_COMMAND_FILE_BYTES,
                    "path": proof.get("path"),
                    "size": size,
                },
            )
        total += size
    if total > MAX_COMMAND_FILES_TOTAL_BYTES:
        raise UiCommandContractError(
            "LIMIT_EXCEEDED",
            "execute files exceed the closed aggregate byte ceiling.",
            details={
                "limit": MAX_COMMAND_FILES_TOTAL_BYTES,
                "size": total,
            },
        )


def _validate_proof_entry(value: Any) -> None:
    if not isinstance(value, Mapping):
        raise UiCommandContractError(
            "INVALID_PLAN",
            "UI-command path proof entry must be an object.",
        )
    _require_exact_fields(
        value,
        {"command_id", "proof", "request_field"},
        field="file_proof",
    )
    _bounded_text(
        value.get("command_id"),
        field="file_proof.command_id",
        maximum=MAX_COMMAND_ID_CHARS,
        allow_empty=False,
    )
    _bounded_text(
        value.get("request_field"),
        field="file_proof.request_field",
        maximum=MAX_PATH_CHARS,
        allow_empty=False,
    )
    proof = value.get("proof")
    if not isinstance(proof, Mapping):
        raise UiCommandContractError(
            "INVALID_PLAN",
            "UI-command path proof must be an object.",
        )
    fields = {
        "content_sha256",
        "contract",
        "device",
        "executable",
        "inode",
        "kind",
        "mode",
        "mtime_ns",
        "path",
        "proof_sha256",
        "role",
        "size",
    }
    _require_exact_fields(proof, fields, field="file_proof.proof")
    if proof.get("contract") != UI_COMMAND_FILE_PROOF_CONTRACT:
        raise UiCommandContractError(
            "INVALID_PLAN",
            "UI-command path proof contract is invalid.",
        )
    role = proof.get("role")
    if role not in {
        "command_file",
        "lua_module_directory",
        "lua_script",
        "program_executable",
        "working_directory",
    }:
        raise UiCommandContractError(
            "INVALID_PLAN",
            "UI-command path proof role is invalid.",
        )
    kind = proof.get("kind")
    expected_kind = (
        "directory"
        if role in {"lua_module_directory", "working_directory"}
        else "file"
    )
    if kind != expected_kind:
        raise UiCommandContractError(
            "INVALID_PLAN",
            "UI-command path proof kind does not match its role.",
        )
    if proof.get("executable") is not (role == "program_executable"):
        raise UiCommandContractError(
            "INVALID_PLAN",
            "UI-command executable proof flag does not match its role.",
        )
    _normalize_absolute_path_text(
        proof.get("path"),
        field="file_proof.proof.path",
    )
    for key in ("device", "inode", "mode", "mtime_ns", "size"):
        number = proof.get(key)
        if type(number) is not int or number < 0:
            raise UiCommandContractError(
                "INVALID_PLAN",
                f"UI-command path proof {key} must be a non-negative integer.",
            )
    content_digest = proof.get("content_sha256")
    if expected_kind == "file":
        if not isinstance(content_digest, str) or not _SHA256.fullmatch(
            content_digest
        ):
            raise UiCommandContractError(
                "INVALID_PLAN",
                "UI-command file proof lacks a content digest.",
            )
    elif content_digest is not None:
        raise UiCommandContractError(
            "INVALID_PLAN",
            "UI-command directory proof must not claim a content digest.",
        )
    proof_seal = proof.get("proof_sha256")
    if not isinstance(proof_seal, str) or not _SHA256.fullmatch(proof_seal):
        raise UiCommandContractError(
            "INVALID_PLAN",
            "UI-command path proof lacks a valid seal.",
        )
    body = {
        key: item for key, item in proof.items() if key != "proof_sha256"
    }
    if canonical_sha256(body) != proof_seal:
        raise UiCommandContractError(
            "PROOF_TAMPERED",
            "UI-command path proof seal does not match its contents.",
        )


def _evaluate_inventory_guard(
    guard: Mapping[str, Any],
    live_result: Mapping[str, Any],
    *,
    version: str,
    phase: str,
) -> dict[str, Any]:
    commands = _normalize_live_inventory(live_result)
    _require_exact_fields(
        guard,
        _INVENTORY_GUARD_FIELDS,
        field="command_inventory_guard",
    )
    ids = _bounded_unique_strings(
        guard.get("command_ids"),
        field="command_inventory_guard.command_ids",
        limit=MAX_COMMANDS_PER_PLAN,
        maximum=MAX_COMMAND_ID_CHARS,
        allow_empty=False,
        sort_values=True,
    )
    expected = guard.get("expected_membership")
    if expected not in {"absent", "present"}:
        raise UiCommandContractError(
            "INVALID_PLAN",
            "Command inventory guard has an invalid membership expectation.",
        )
    if (
        guard.get("source_uri") != GET_COMMANDS_URI
        or guard.get("fail_closed") is not True
        or guard.get("max_commands") != MAX_LIVE_COMMANDS
        or guard.get("max_command_chars") != MAX_LIVE_COMMAND_ID_CHARS
        or guard.get("max_inventory_bytes") != MAX_LIVE_INVENTORY_BYTES
    ):
        raise UiCommandContractError(
            "INVALID_PLAN",
            "Command inventory guard does not use the fixed live boundary.",
        )
    available = set(commands)
    present = sorted(command for command in ids if command in available)
    absent = sorted(command for command in ids if command not in available)
    passed = not absent if expected == "present" else not present
    evidence = {
        "absent_command_ids": absent,
        "command_count": len(commands),
        "contract": UI_COMMAND_INVENTORY_EVIDENCE_CONTRACT,
        "expected_membership": expected,
        "inventory_sha256": canonical_sha256(commands),
        "passed": bool(passed),
        "phase": phase,
        "present_command_ids": present,
        "requested_command_ids": ids,
        "source_uri": GET_COMMANDS_URI,
        "version": version,
    }
    if not passed:
        raise UiCommandContractError(
            "COMMAND_INVENTORY_PRECONDITION_FAILED"
            if phase == "pre_dispatch"
            else "COMMAND_INVENTORY_POSTCONDITION_FAILED",
            "The live Wwise Authoring command inventory does not satisfy the "
            "required membership boundary.",
            details=evidence,
        )
    return evidence


def _normalize_live_inventory(value: Any) -> list[str]:
    if not isinstance(value, Mapping):
        raise UiCommandContractError(
            "INVALID_LIVE_RESULT",
            "getCommands result must be an object.",
        )
    _require_exact_fields(value, {"commands"}, field="getCommands result")
    commands = _bounded_unique_strings(
        value.get("commands"),
        field="getCommands result.commands",
        limit=MAX_LIVE_COMMANDS,
        maximum=MAX_LIVE_COMMAND_ID_CHARS,
        allow_empty=True,
        sort_values=True,
    )
    if (
        len(canonical_json_bytes({"commands": commands}))
        > MAX_LIVE_INVENTORY_BYTES
    ):
        raise UiCommandContractError(
            "LIMIT_EXCEEDED",
            "getCommands result exceeds the live inventory byte ceiling.",
        )
    return commands


def _inventory_guard(
    *,
    command_ids: Sequence[str],
    expected_membership: str,
    timing: str,
) -> dict[str, Any]:
    return {
        "command_ids": sorted(command_ids),
        "expected_membership": expected_membership,
        "fail_closed": True,
        "max_command_chars": MAX_LIVE_COMMAND_ID_CHARS,
        "max_commands": MAX_LIVE_COMMANDS,
        "max_inventory_bytes": MAX_LIVE_INVENTORY_BYTES,
        "source_uri": GET_COMMANDS_URI,
        "timing": timing,
    }


def _inventory_verification(
    *,
    command_ids: Sequence[str],
    expected_membership: str,
) -> dict[str, Any]:
    return {
        **_inventory_guard(
            command_ids=command_ids,
            expected_membership=expected_membership,
            timing="immediately_after_dispatch",
        ),
        "kind": "command_inventory_membership",
        "result_schema_also_required": True,
    }


def _registration_relationship(
    *,
    version: str,
    host_platform: str,
    commands: Sequence[Mapping[str, Any]],
    source_authority: str | None,
) -> dict[str, Any]:
    body = {
        "commands": _copy_json_sequence(commands),
        "contract": UI_COMMAND_REGISTRATION_RELATIONSHIP_CONTRACT,
        "host_platform": host_platform,
        "source_authority": source_authority,
        "version": version,
    }
    return {**body, "relationship_sha256": canonical_sha256(body)}


def _normalize_source_authority(
    commands: Sequence[Mapping[str, Any]],
    *,
    value: Any,
    supplied: bool,
) -> str | None:
    required = _commands_require_source_authority(commands)
    if required and value != USER_SUPPLIED_SOURCE_AUTHORITY:
        raise UiCommandContractError(
            "SOURCE_AUTHORITY_REQUIRED",
            "Program and Lua command handlers require the fixed "
            "user-supplied-verbatim source assertion.",
            details={
                "eligible_only_when": (
                    "the current user message supplied the exact existing "
                    "path and registration fields"
                ),
                "model_generated_repaired_or_wrapped_code_eligible": False,
                "required_source_authority": (
                    USER_SUPPLIED_SOURCE_AUTHORITY
                ),
                "runtime_can_prove_conversational_provenance": False,
            },
        )
    if not supplied:
        return None
    if value != USER_SUPPLIED_SOURCE_AUTHORITY:
        raise UiCommandContractError(
            "INVALID_SOURCE_AUTHORITY",
            "source_authority must use the fixed user-supplied-verbatim "
            "assertion.",
            details={
                "required_source_authority": (
                    USER_SUPPLIED_SOURCE_AUTHORITY
                )
            },
        )
    return USER_SUPPLIED_SOURCE_AUTHORITY


def _commands_require_source_authority(
    commands: Sequence[Mapping[str, Any]],
) -> bool:
    return any(
        command["handler"]["kind"] in {"program", "lua_script"}
        for command in commands
    )


def _source_authority_metadata(
    commands: Sequence[Mapping[str, Any]],
    *,
    source_authority: str | None,
) -> dict[str, Any]:
    return {
        "assertion": source_authority,
        "eligible_only_when_current_user_message_supplied_exact_existing_path_and_fields": (
            True
        ),
        "model_generated_repaired_or_wrapped_code_eligible": False,
        "required": _commands_require_source_authority(commands),
        "runtime_can_prove_conversational_provenance": False,
    }


def _proof_entry(
    command_id: str,
    request_field: str,
    proof: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "command_id": command_id,
        "proof": dict(proof),
        "request_field": request_field,
    }


def _safety_metadata() -> dict[str, Any]:
    return {
        "arbitrary_waapi_payload_allowed": False,
        "automatic_retry": False,
        "model_generated_code_allowed": False,
        "raw_shell_string_allowed": False,
        "requires_preview_authorization": True,
        "accepted_authorization_modes": list(
            DEFAULT_TRANSACTION_AUTHORIZATION_MODES
        ),
        "same_turn_execution_allowed_by_policy": True,
        "structured_argument_tokens_required": True,
    }


def _no_cleanup(reason: str) -> dict[str, Any]:
    return {
        "automatic": False,
        "dispatch": None,
        "kind": "none",
        "reason": reason,
        "reversible": False,
        "runtime_preconditions": {"file_proofs": []},
        "verification": None,
    }


def _seal_plan(body: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(body)
    if len(canonical_json_bytes(payload)) > MAX_PLAN_BYTES:
        raise UiCommandContractError(
            "LIMIT_EXCEEDED",
            f"UI-command plan exceeds the {MAX_PLAN_BYTES} byte ceiling.",
        )
    payload["plan_sha256"] = canonical_sha256(payload)
    return payload


def _normalize_property_value(value: Any) -> Any:
    if value is _UNSET:
        return _UNSET
    if value is None or isinstance(value, (str, bool)):
        if isinstance(value, str):
            return _bounded_text(
                value,
                field="value",
                maximum=MAX_ARGUMENT_TOKEN_CHARS,
                allow_empty=True,
            )
        return value
    if type(value) is int:
        try:
            converted = float(value)
        except OverflowError as exc:
            raise UiCommandContractError(
                "INVALID_ARGUMENT",
                "value must be representable as a finite WAAPI double.",
            ) from exc
        if not math.isfinite(converted):
            raise UiCommandContractError(
                "INVALID_ARGUMENT",
                "value must be representable as a finite WAAPI double.",
            )
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise UiCommandContractError(
                "INVALID_ARGUMENT",
                "value must be a finite JSON number.",
            )
        return value
    raise UiCommandContractError(
        "INVALID_ARGUMENT",
        "value must be null, string, number, or boolean.",
    )


def _normalize_argument_tokens(value: Any, *, field: str) -> list[str]:
    return _bounded_unique_strings(
        value,
        field=field,
        limit=MAX_ARGUMENT_TOKENS,
        maximum=MAX_ARGUMENT_TOKEN_CHARS,
        allow_empty=True,
        allow_duplicates=True,
        allow_empty_items=True,
    )


def _validate_program_boundary(
    program_path: str,
    tokens: Sequence[str],
    *,
    field: str,
) -> None:
    """Require one proved final executable with no generic argument channel."""

    executable_name = Path(program_path).name.casefold()
    if executable_name in _DISALLOWED_SHELL_EXECUTABLES:
        raise UiCommandContractError(
            "SHELL_EXECUTABLE_NOT_ALLOWED",
            f"{field}.program_path must not identify a command shell.",
            details={"executable_name": executable_name},
        )
    if (
        executable_name in _DISALLOWED_GENERIC_EXECUTABLES
        or _GENERIC_INTERPRETER_NAME.fullmatch(executable_name) is not None
    ):
        raise UiCommandContractError(
            "GENERIC_EXECUTION_HOST_NOT_ALLOWED",
            f"{field}.program_path must identify the final proved executable, "
            "not an interpreter, launcher, loader, or command prefix.",
            details={"executable_name": executable_name},
        )
    if tokens:
        raise UiCommandContractError(
            "PROGRAM_ARGUMENTS_UNSUPPORTED",
            f"{field}.argument_tokens must be empty for a generic Program "
            "descriptor. Parameterized execution requires a dedicated closed "
            "adapter.",
            details={
                "argument_count": len(tokens),
                "closed_adapter_required": True,
                "generic_program_argument_tokens_allowed": False,
            },
        )


def _encode_argument_tokens(
    tokens: Sequence[str],
    *,
    host_platform: str,
) -> str:
    host = _require_host_platform(host_platform)
    encoded = (
        shlex.join(tokens)
        if host == "macos"
        else subprocess.list2cmdline(list(tokens))
    )
    if len(encoded) > MAX_ENCODED_ARGUMENT_CHARS:
        raise UiCommandContractError(
            "LIMIT_EXCEEDED",
            "Encoded command arguments exceed the closed character ceiling.",
            details={
                "limit": MAX_ENCODED_ARGUMENT_CHARS,
                "observed": len(encoded),
            },
        )
    return encoded


def _normalize_start_mode(value: Any, *, field: str) -> str:
    if value not in START_MODES:
        raise UiCommandContractError(
            "INVALID_ARGUMENT",
            f"{field} is not a supported Wwise start mode.",
            details={"supported": sorted(START_MODES)},
        )
    return str(value)


def _menu_path(value: Any, *, field: str, allow_empty: bool) -> list[str]:
    rows = _bounded_unique_strings(
        value,
        field=field,
        limit=MAX_MENU_SEGMENTS,
        maximum=MAX_MENU_SEGMENT_CHARS,
        allow_empty=allow_empty,
        allow_duplicates=True,
    )
    for index, segment in enumerate(rows):
        if "/" in segment or "\\" in segment:
            raise UiCommandContractError(
                "INVALID_ARGUMENT",
                f"{field}[{index}] must be one menu path segment.",
            )
    return rows


def _object_types(value: Any, *, field: str) -> list[str]:
    rows = _bounded_unique_strings(
        value,
        field=field,
        limit=MAX_OBJECT_TYPES,
        maximum=MAX_OBJECT_TYPE_CHARS,
        allow_empty=True,
        sort_values=True,
    )
    for index, item in enumerate(rows):
        if "," in item:
            raise UiCommandContractError(
                "INVALID_ARGUMENT",
                f"{field}[{index}] must be one object type.",
            )
    return rows


def _bounded_unique_strings(
    value: Any,
    *,
    field: str,
    limit: int,
    maximum: int,
    allow_empty: bool,
    allow_duplicates: bool = False,
    allow_empty_items: bool = False,
    normalize_path: bool = False,
    sort_values: bool = False,
) -> list[str]:
    rows = _require_sequence(value, field=field)
    if (not allow_empty and not rows) or len(rows) > limit:
        raise UiCommandContractError(
            "LIMIT_EXCEEDED",
            f"{field} must be a bounded array.",
            details={"count": len(rows), "limit": limit},
        )
    result: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(rows):
        normalized = (
            _normalize_absolute_path_text(
                item,
                field=f"{field}[{index}]",
            )
            if normalize_path
            else _bounded_text(
                item,
                field=f"{field}[{index}]",
                maximum=maximum,
                allow_empty=allow_empty_items,
            )
        )
        folded = normalized.casefold()
        if not allow_duplicates and folded in seen:
            raise UiCommandContractError(
                "DUPLICATE_ARGUMENT",
                f"{field} contains duplicate value {normalized!r}.",
            )
        result.append(normalized)
        seen.add(folded)
    if sort_values:
        result.sort(key=lambda item: (item.casefold(), item))
    return result


def _bounded_text(
    value: Any,
    *,
    field: str,
    maximum: int,
    allow_empty: bool,
) -> str:
    if not isinstance(value, str) or (not allow_empty and not value):
        qualifier = "a string" if allow_empty else "a non-empty string"
        raise UiCommandContractError(
            "INVALID_ARGUMENT",
            f"{field} must be {qualifier}.",
        )
    if len(value) > maximum:
        raise UiCommandContractError(
            "LIMIT_EXCEEDED",
            f"{field} exceeds the {maximum} character ceiling.",
        )
    if _CONTROL_CHARACTERS.search(value):
        raise UiCommandContractError(
            "INVALID_ARGUMENT",
            f"{field} must not contain control characters.",
        )
    return value


def _normalize_absolute_path_text(value: Any, *, field: str) -> str:
    path = _normalize_absolute_path(value, field=field)
    return str(path)


def _normalize_absolute_path(value: Any, *, field: str) -> Path:
    text = _bounded_text(
        value,
        field=field,
        maximum=MAX_PATH_CHARS,
        allow_empty=False,
    )
    path = Path(text)
    if not path.is_absolute():
        raise UiCommandContractError(
            "INVALID_PATH",
            f"{field} must be an absolute path.",
            details={"path": text},
        )
    normalized = Path(os.path.normpath(text))
    if str(normalized) != text:
        raise UiCommandContractError(
            "INVALID_PATH",
            f"{field} must already be lexically normalized.",
            details={"normalized": str(normalized), "path": text},
        )
    return normalized


def _require_version(value: Any) -> str:
    if not isinstance(value, str) or value not in SUPPORTED_WWISE_VERSION_KEYS:
        raise UiCommandContractError(
            "UNSUPPORTED_VERSION",
            "UI-command operations are unavailable for this Wwise version.",
            details={
                "supported_versions": list(SUPPORTED_WWISE_VERSION_KEYS),
                "version": value,
            },
        )
    return value


def _require_execute_files_version(version: str) -> None:
    if version not in EXECUTE_FILES_VERSIONS:
        raise UiCommandContractError(
            "VERSION_BEHAVIOR_BOUNDARY",
            "The ui.commands.execute files argument is available only in "
            "Wwise 2025.1.",
            details={
                "supported_versions": sorted(EXECUTE_FILES_VERSIONS),
                "version": version,
            },
        )


def _require_host_platform(value: Any) -> str:
    if value not in HOST_PLATFORMS:
        raise UiCommandContractError(
            "INVALID_ARGUMENT",
            "host_platform must be macos or windows.",
            details={"host_platform": value},
        )
    return str(value)


def _optional_bool(
    value: Mapping[str, Any],
    key: str,
    *,
    default: bool,
    field: str,
) -> bool:
    if key not in value:
        return default
    result = value.get(key)
    if type(result) is not bool:
        raise UiCommandContractError(
            "INVALID_ARGUMENT",
            f"{field} must be a JSON boolean.",
        )
    return result


def _require_sequence(value: Any, *, field: str) -> list[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise UiCommandContractError(
            "INVALID_ARGUMENT",
            f"{field} must be an array.",
        )
    return list(value)


def _require_exact_fields(
    value: Mapping[str, Any],
    expected: set[str] | frozenset[str],
    *,
    field: str,
) -> None:
    actual = set(value)
    missing = set(expected) - actual
    unknown = actual - set(expected)
    if missing or unknown:
        raise UiCommandContractError(
            "INVALID_ARGUMENT",
            f"{field} contains unknown or missing fields.",
            details={"missing": sorted(missing), "unknown": sorted(unknown)},
        )


def _require_allowed_and_required_fields(
    value: Mapping[str, Any],
    *,
    allowed: set[str] | frozenset[str],
    required: set[str] | frozenset[str],
    field: str,
) -> None:
    actual = set(value)
    missing = set(required) - actual
    unknown = actual - set(allowed)
    if missing or unknown:
        raise UiCommandContractError(
            "INVALID_ARGUMENT",
            f"{field} contains unknown or missing fields.",
            details={"missing": sorted(missing), "unknown": sorted(unknown)},
        )


def _copy_json_sequence(value: Any) -> list[dict[str, Any]]:
    rows = _require_sequence(value, field="sequence")
    return [
        _copy_json_mapping(row)
        for row in rows
    ]


def _copy_json_mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise UiCommandContractError(
            "INVALID_ARGUMENT",
            "Expected an object while copying a closed request.",
        )
    result: dict[str, Any] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise UiCommandContractError(
                "INVALID_ARGUMENT",
                "Closed request object keys must be strings.",
            )
        if isinstance(item, Mapping):
            result[key] = _copy_json_mapping(item)
        elif isinstance(item, list):
            copied: list[Any] = []
            for nested in item:
                copied.append(
                    _copy_json_mapping(nested)
                    if isinstance(nested, Mapping)
                    else nested
                )
            result[key] = copied
        else:
            result[key] = item
    return result


__all__ = [
    "AUTHORING_HOST_SURFACE",
    "EXECUTE_FILES_VERSIONS",
    "EXECUTE_URI",
    "GET_COMMANDS_URI",
    "HOST_PLATFORMS",
    "LUA_COMMAND_VERSIONS",
    "MAX_ARGUMENT_TOKENS",
    "MAX_COMMAND_FILE_BYTES",
    "MAX_COMMAND_FILES",
    "MAX_COMMAND_FILES_TOTAL_BYTES",
    "MAX_COMMANDS_PER_PLAN",
    "MAX_COMMAND_ID_CHARS",
    "MAX_DISPLAY_NAME_CHARS",
    "MAX_LIVE_COMMANDS",
    "MAX_OBJECT_ARGUMENTS",
    "MAX_PATH_CHARS",
    "MAX_PLATFORM_ARGUMENTS",
    "REGISTER_URI",
    "START_MODES",
    "UI_COMMAND_FILE_PROOF_CONTRACT",
    "UI_COMMAND_INVENTORY_EVIDENCE_CONTRACT",
    "UI_COMMAND_PLAN_CONTRACT",
    "UI_COMMAND_REGISTRATION_RELATIONSHIP_CONTRACT",
    "USER_SUPPLIED_SOURCE_AUTHORITY",
    "UNREGISTER_EXISTING_ACKNOWLEDGEMENT",
    "UNREGISTER_URI",
    "UiCommandContractError",
    "build_ui_command_execute_plan",
    "build_ui_commands_register_plan",
    "build_ui_commands_unregister_descriptors_plan",
    "build_ui_commands_unregister_existing_plan",
    "build_ui_commands_unregister_plan",
    "revalidate_ui_command_file_proofs",
    "validate_empty_ui_command_result",
    "validate_ui_command_plan",
    "validate_ui_command_runtime_preconditions",
    "verify_ui_command_inventory_postcondition",
]
