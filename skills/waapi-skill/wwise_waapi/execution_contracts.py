"""Versioned public execution contracts for the packaged WAAPI gateway.

The reflected manifests are the version authority, but reflection alone never
grants a public route.  This module binds the five checked-in inventories to a
reviewed digest and assigns every reflected row to exactly one executable lane
or one explicit exclusion.  It is deliberately data driven: adding a new
manifest row changes the digest and fails closed until the contract is reviewed.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from .manifest import ManifestStore
from .versions import SUPPORTED_WWISE_VERSION_KEYS


SKILL_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_ROOT = SKILL_ROOT / "resources" / "manifest"

PUBLIC_EXECUTION_CONTRACT = "waapi-skill.public-execution-contract/v1"
PACKAGED_INVENTORY_SHA256 = "4644c792fdf55fe498e7dd9fc7de1475831801d1b363be8488fb13cbdfa826fa"

EXPECTED_VERSION_COUNTS: Mapping[str, Mapping[str, int]] = MappingProxyType(
    {
        "2021.1": MappingProxyType(
            {"functions": 99, "topics": 27, "public_functions": 93, "public_topics": 26, "public_total": 119}
        ),
        "2022.1": MappingProxyType(
            {"functions": 112, "topics": 32, "public_functions": 106, "public_topics": 31, "public_total": 137}
        ),
        "2023.1": MappingProxyType(
            {"functions": 149, "topics": 32, "public_functions": 139, "public_topics": 31, "public_total": 170}
        ),
        "2024.1": MappingProxyType(
            {"functions": 148, "topics": 30, "public_functions": 139, "public_topics": 29, "public_total": 168}
        ),
        "2025.1": MappingProxyType(
            {"functions": 154, "topics": 31, "public_functions": 145, "public_topics": 30, "public_total": 175}
        ),
    }
)

EXPECTED_PUBLIC_VERSION_ROWS = 769
EXPECTED_MANIFEST_VERSION_ROWS = 814
EXPECTED_PUBLIC_UNIQUE_URIS = 188

EXPECTED_VERSION_INVENTORY_SHA256: Mapping[str, str] = MappingProxyType(
    {
        "2021.1": "80caea46b0613135df09ea9b74ba55d261061b7b7e6f0cc54a93793bccc60e43",
        "2022.1": "3c7ee729d0e50453bb7b1b04c955f3a94562a9b3e5abcbde8f53f8ab902145df",
        "2023.1": "cb513e3584a00f40fd0998d7a73c4a46ecd2528a1351c6ee4f6c26e88734af33",
        "2024.1": "67c37cdb37c48ac0955f9a0a1aea6e1d69a524165346c7415d348c29be8b019a",
        "2025.1": "550c12a60062cbe468862c5e04a8aedcecb2f9bebd0cb9412cc2ba9ae15902a9",
    }
)


APPROVED_EXCLUSIONS: Mapping[str, str] = MappingProxyType(
    {
        "ak.wwise.cli.executeLuaScript": (
            "Arbitrary Lua would bypass the packaged Skill implementation and recreate ad-hoc code execution."
        ),
        "ak.wwise.core.executeLuaScript": (
            "Arbitrary Lua would bypass the packaged Skill implementation and recreate ad-hoc code execution."
        ),
        "ak.wwise.debug.enableAsserts": (
            "This debug-only call changes process-wide assert behavior and can destabilize the Wwise host."
        ),
        "ak.wwise.debug.enableAutomationMode": (
            "This debug-only call changes global automation/dialog behavior in the Wwise host."
        ),
        "ak.wwise.debug.getWalTree": (
            "This private debug endpoint exposes internal WAL state and has no supported business contract."
        ),
        "ak.wwise.debug.restartWaapiServers": (
            "This internal endpoint deliberately interrupts WAAPI and cannot provide a reliable completion contract."
        ),
        "ak.wwise.debug.testAssert": "This private test endpoint deliberately triggers an assertion.",
        "ak.wwise.debug.testCrash": "This private test endpoint deliberately crashes Wwise.",
        "ak.wwise.debug.validateCall": (
            "This debug-build endpoint validates arbitrary nested call documents rather than a business operation."
        ),
        "ak.wwise.debug.assertFailed": (
            "Observing this debug topic reliably requires manufacturing an unsafe assertion."
        ),
        "ak.wwise.ui.commands.register": (
            "Command add-ons can persist for the Wwise process and launch arbitrary external programs or scripts."
        ),
        "ak.wwise.ui.commands.execute": (
            "Executing an unrestricted command ID can launch external add-ons or bypass reviewed project-transition guards."
        ),
    }
)


FIXED_COMMANDS_BY_URI: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "ak.wwise.core.getInfo": ("status",),
        "ak.wwise.core.getProjectInfo": ("status",),
        "ak.wwise.core.object.get": ("query-object", "buses"),
        "ak.wwise.core.object.getAttenuationCurve": ("metadata attenuation-curve",),
        "ak.wwise.core.object.getPropertyAndReferenceNames": ("metadata names",),
        "ak.wwise.core.object.getPropertyInfo": ("metadata property-info",),
        "ak.wwise.core.object.getTypes": ("metadata types",),
        "ak.wwise.core.object.isPropertyEnabled": ("metadata property-enabled",),
        "ak.wwise.ui.getSelectedObjects": ("selected",),
    }
)

DEFAULT_TOPIC_TIMEOUT_SECONDS = 10.0
TOPIC_TIMEOUT_OVERRIDES: Mapping[str, float] = MappingProxyType(
    {
        # SoundBank generation is deliberately started only after the
        # subscription is established. Real multi-bank/platform generation can
        # exceed the ordinary short observation window, so this reviewed topic
        # must not silently cap the gateway's documented 120-second wait at 10.
        "ak.wwise.core.soundbank.generated": 120.0,
    }
)


# These functions have a small, side-effect-free request/result contract and
# may use ``gateway call`` directly. Broader reads intentionally use a reviewed
# transaction so the operator sees and confirms their exact payload first.
BOUNDED_DIRECT_CALL_URIS = frozenset(
    {
        "ak.soundengine.getState",
        "ak.soundengine.getSwitch",
        "ak.wwise.core.audioSourcePeaks.getMinMaxPeaksInRegion",
        "ak.wwise.core.audioSourcePeaks.getMinMaxPeaksInTrimmedRegion",
        "ak.wwise.core.mediaPool.get",
        "ak.wwise.core.mediaPool.getFields",
        "ak.wwise.core.object.diff",
        "ak.wwise.core.object.isLinked",
        "ak.wwise.core.ping",
        "ak.wwise.core.profiler.getCursorTime",
        "ak.wwise.core.remote.getConnectionStatus",
        "ak.wwise.core.transport.getState",
        "ak.wwise.ui.commands.getCommands",
        "ak.wwise.waapi.getFunctions",
        "ak.wwise.waapi.getSchema",
        "ak.wwise.waapi.getTopics",
    }
)


FILESYSTEM_OR_EXTERNAL_PREFIXES = (
    "ak.wwise.cli.",
    "ak.wwise.console.",
    "ak.wwise.core.sourceControl.",
)
FILESYSTEM_OR_EXTERNAL_URIS = frozenset(
    {
        "ak.wwise.core.audio.convert",
        "ak.wwise.core.audio.import",
        "ak.wwise.core.audio.importTabDelimited",
        "ak.wwise.core.profiler.saveCapture",
        "ak.wwise.core.soundbank.convertExternalSources",
        "ak.wwise.core.soundbank.generate",
        "ak.wwise.core.soundbank.processDefinitionFiles",
        "ak.wwise.debug.generateToneWAV",
        "ak.wwise.ui.captureScreen",
        # Opening or creating a UI project can migrate, check out, or write
        # project files.  Keep those calls in the same isolated lane as their
        # Wwise Console equivalents instead of treating them as UI-only state.
        "ak.wwise.ui.project.create",
        "ak.wwise.ui.project.open",
    }
)

PROJECT_GUARD_INVARIANT = "invariant"
PROJECT_GUARD_TRANSITION_TO_PATH = "transition_to_path"
PROJECT_GUARD_TRANSITION_TO_NONE = "transition_to_none"
PROJECT_GUARD_MODES = frozenset(
    {
        PROJECT_GUARD_INVARIANT,
        PROJECT_GUARD_TRANSITION_TO_PATH,
        PROJECT_GUARD_TRANSITION_TO_NONE,
    }
)
PROJECT_TRANSITION_GUARD_MODES: Mapping[str, str] = MappingProxyType(
    {
        "ak.wwise.console.project.create": PROJECT_GUARD_TRANSITION_TO_PATH,
        "ak.wwise.console.project.open": PROJECT_GUARD_TRANSITION_TO_PATH,
        "ak.wwise.console.project.close": PROJECT_GUARD_TRANSITION_TO_NONE,
        "ak.wwise.ui.project.create": PROJECT_GUARD_TRANSITION_TO_PATH,
        "ak.wwise.ui.project.open": PROJECT_GUARD_TRANSITION_TO_PATH,
        "ak.wwise.ui.project.close": PROJECT_GUARD_TRANSITION_TO_NONE,
    }
)

POST_EXECUTION_PROJECT_GUARD_REVALIDATE = "revalidate"
POST_EXECUTION_PROJECT_GUARD_CONTEXT_RUNTIME_ONLY = "context_runtime_only"
POST_EXECUTION_PROJECT_GUARD_POLICIES = frozenset(
    {
        POST_EXECUTION_PROJECT_GUARD_REVALIDATE,
        POST_EXECUTION_PROJECT_GUARD_CONTEXT_RUNTIME_ONLY,
    }
)
CONTEXT_RUNTIME_ONLY_POST_EXECUTION_URIS = frozenset(
    {
        "ak.wwise.cli.convertExternalSource",
        "ak.wwise.cli.generateSoundbank",
        "ak.wwise.cli.migrate",
        "ak.wwise.cli.tabDelimitedImport",
    }
)
POST_EXECUTION_PROJECT_GUARD_POLICY_BY_URI: Mapping[str, str] = MappingProxyType(
    {
        # These reviewed explicit-project WwiseConsole calls can tear down
        # their Authoring project context after returning a complete result.
        # Verification therefore binds the sealed result to the fresh
        # endpoint/getInfo context and packaged runtime guard without issuing
        # a second project probe.  Business state remains explicitly
        # unverified here and is checked independently by live test oracles.
        uri: POST_EXECUTION_PROJECT_GUARD_CONTEXT_RUNTIME_ONLY
        for uri in CONTEXT_RUNTIME_ONLY_POST_EXECUTION_URIS
    }
)

MANAGED_SESSION_PREFIXES = (
    "ak.soundengine.",
    "ak.wwise.core.profiler.",
    "ak.wwise.core.remote.",
    "ak.wwise.core.transport.",
    "ak.wwise.core.undo.",
    "ak.wwise.core.workUnit.",
    "ak.wwise.ui.",
)

LIFECYCLE_COMPANIONS: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "ak.soundengine.loadBank": ("ak.soundengine.unloadBank",),
        "ak.soundengine.registerGameObj": ("ak.soundengine.unregisterGameObj",),
        "ak.wwise.core.profiler.registerMeter": ("ak.wwise.core.profiler.unregisterMeter",),
        "ak.wwise.core.profiler.startCapture": ("ak.wwise.core.profiler.stopCapture",),
        "ak.wwise.core.remote.connect": ("ak.wwise.core.remote.disconnect",),
        "ak.wwise.core.transport.create": ("ak.wwise.core.transport.destroy",),
        "ak.wwise.core.undo.beginGroup": (
            "ak.wwise.core.undo.endGroup",
            "ak.wwise.core.undo.cancelGroup",
        ),
        "ak.wwise.core.workUnit.load": ("ak.wwise.core.workUnit.unload",),
    }
)
LIFECYCLE_CLOSERS = frozenset(
    companion
    for companions in LIFECYCLE_COMPANIONS.values()
    for companion in companions
)

# Undo groups are scoped to one WAMP session.  Publishing their three member
# functions as independent ``waapi.call`` transactions would disconnect between
# begin/end/cancel and can therefore auto-cancel or strand the group.  Keep all
# reflected rows executable, but route them only through the packaged
# ``waapi.undoGroup`` same-connection composite operation.
UNDO_GROUP_MEMBER_URIS = frozenset(
    {
        "ak.wwise.core.undo.beginGroup",
        "ak.wwise.core.undo.endGroup",
        "ak.wwise.core.undo.cancelGroup",
    }
)

READ_OPERATION_NAMES = frozenset({"diff", "ping", "verify"})


class ExecutionContractError(ValueError):
    """The packaged public route inventory is malformed or out of date."""


@dataclass(frozen=True, slots=True)
class ExecutionContract:
    """One version-specific function/topic route consumed by the gateway."""

    version: str
    uri: str
    item_type: str
    route: str
    effect: str
    gateway_commands: tuple[str, ...]
    timeout_seconds: float
    result_limit_bytes: int
    verification_strategy: str
    requires_confirmation: bool
    program_case: str
    lifecycle_strategy: str = "none"
    companion_uris: tuple[str, ...] = ()
    project_guard_mode: str = PROJECT_GUARD_INVARIANT
    post_execution_project_guard_policy: str = POST_EXECUTION_PROJECT_GUARD_REVALIDATE
    excluded_reason: str | None = None

    @property
    def executable(self) -> bool:
        return self.route != "excluded"

    @property
    def read_only(self) -> bool:
        return self.effect in {"read", "observation"}

    def as_dict(self) -> dict[str, Any]:
        return {
            "contract": PUBLIC_EXECUTION_CONTRACT,
            "version": self.version,
            "uri": self.uri,
            "item_type": self.item_type,
            "route": self.route,
            "effect": self.effect,
            "gateway_commands": list(self.gateway_commands),
            "timeout_seconds": self.timeout_seconds,
            "result_limit_bytes": self.result_limit_bytes,
            "verification_strategy": self.verification_strategy,
            "requires_confirmation": self.requires_confirmation,
            "program_case": self.program_case,
            "lifecycle_strategy": self.lifecycle_strategy,
            "companion_uris": list(self.companion_uris),
            "project_guard_mode": self.project_guard_mode,
            "post_execution_project_guard_policy": self.post_execution_project_guard_policy,
            "executable": self.executable,
            "excluded_reason": self.excluded_reason,
        }


@dataclass(slots=True)
class ExecutionContractRegistry:
    """Build fail-closed route contracts from the five immutable manifests."""

    manifest_store: ManifestStore = field(default_factory=lambda: ManifestStore(root=MANIFEST_ROOT))

    def entries(self, version: str) -> tuple[ExecutionContract, ...]:
        _require_supported_version(version)
        manifest = self.manifest_store.load(version)
        rows: list[ExecutionContract] = []
        seen: set[tuple[str, str]] = set()
        for item_type, section in (("function", "functions"), ("topic", "topics")):
            payloads = manifest.get(section)
            if not isinstance(payloads, list):
                raise ExecutionContractError(f"Manifest {version} lacks a {section} array")
            for payload in payloads:
                uri = payload.get("uri") if isinstance(payload, Mapping) else None
                if not isinstance(uri, str) or not uri:
                    raise ExecutionContractError(f"Manifest {version} contains a malformed {item_type} row")
                key = (item_type, uri)
                if key in seen:
                    raise ExecutionContractError(f"Manifest {version} contains duplicate {item_type} URI {uri}")
                seen.add(key)
                rows.append(self._build(version, uri, item_type))
        result = tuple(sorted(rows, key=lambda entry: (entry.uri, entry.item_type)))
        _validate_version_counts(version, result)
        _validate_version_inventory_digest(version, result)
        return result

    def describe(self, version: str, uri: str) -> ExecutionContract:
        matches = tuple(entry for entry in self.entries(version) if entry.uri == uri)
        if not matches:
            raise ExecutionContractError(f"WAAPI URI {uri!r} is not reflected by Wwise {version}")
        if len(matches) != 1:
            raise ExecutionContractError(f"WAAPI URI {uri!r} is ambiguous in Wwise {version}")
        return matches[0]

    def executable_entries(self, version: str) -> tuple[ExecutionContract, ...]:
        return tuple(entry for entry in self.entries(version) if entry.executable)

    def _build(self, version: str, uri: str, item_type: str) -> ExecutionContract:
        excluded_reason = APPROVED_EXCLUSIONS.get(uri)
        if excluded_reason is not None:
            return ExecutionContract(
                version=version,
                uri=uri,
                item_type=item_type,
                route="excluded",
                effect="unsafe",
                gateway_commands=(),
                timeout_seconds=0.0,
                result_limit_bytes=0,
                verification_strategy="none",
                requires_confirmation=False,
                program_case="excluded-before-connect",
                excluded_reason=excluded_reason,
            )
        if item_type == "topic":
            return ExecutionContract(
                version=version,
                uri=uri,
                item_type=item_type,
                route="bounded_topic_wait",
                effect="observation",
                gateway_commands=("wait-topic",),
                timeout_seconds=TOPIC_TIMEOUT_OVERRIDES.get(
                    uri, DEFAULT_TOPIC_TIMEOUT_SECONDS
                ),
                result_limit_bytes=256 * 1024,
                verification_strategy="topic_event_schema",
                requires_confirmation=False,
                program_case="subscribe-event-unsubscribe",
            )
        if item_type != "function":
            raise ExecutionContractError(f"Unsupported manifest item type {item_type!r} for {uri}")
        fixed = FIXED_COMMANDS_BY_URI.get(uri)
        if fixed is not None:
            return ExecutionContract(
                version=version,
                uri=uri,
                item_type=item_type,
                route="fixed_command",
                effect="read",
                gateway_commands=fixed,
                timeout_seconds=10.0,
                result_limit_bytes=256 * 1024,
                verification_strategy="fixed_result_contract",
                requires_confirmation=False,
                program_case="fixed-command-dispatch",
            )
        if uri in BOUNDED_DIRECT_CALL_URIS:
            return ExecutionContract(
                version=version,
                uri=uri,
                item_type=item_type,
                route="bounded_call",
                effect="read",
                gateway_commands=("call",),
                timeout_seconds=10.0,
                result_limit_bytes=256 * 1024,
                verification_strategy="result_schema",
                requires_confirmation=False,
                program_case="call-result-schema",
            )

        effect = classify_function_effect(uri)
        route = _transaction_route(uri, effect)
        project_guard_mode = PROJECT_TRANSITION_GUARD_MODES.get(
            uri,
            PROJECT_GUARD_INVARIANT,
        )
        companions = () if route == "compound_transaction_member" else LIFECYCLE_COMPANIONS.get(uri, ())
        if route == "compound_transaction_member":
            lifecycle_strategy = "same_connection_compound_only"
        elif uri == "ak.wwise.core.workUnit.load":
            # Loading/unloading a Work Unit clears the Undo history and unload
            # can fail when unsaved changes exist.  Expose the inverse as an
            # explicit reversible action, never as promised cleanup.
            lifecycle_strategy = "reversible_state_change"
        elif companions:
            lifecycle_strategy = "paired_follow_up_required"
        elif uri in LIFECYCLE_CLOSERS:
            lifecycle_strategy = "session_close"
        elif route == "managed_transaction":
            lifecycle_strategy = "single_guarded_runtime_call"
        else:
            lifecycle_strategy = "none"
        return ExecutionContract(
            version=version,
            uri=uri,
            item_type=item_type,
            route=route,
            effect=effect,
            gateway_commands=("preview", "confirm", "execute", "verify"),
            timeout_seconds=120.0 if route == "isolated_transaction" else 30.0,
            result_limit_bytes=1024 * 1024,
            verification_strategy=(
                "result_schema_and_project_transition"
                if project_guard_mode != PROJECT_GUARD_INVARIANT
                else "result_schema"
            ),
            requires_confirmation=True,
            program_case=f"{route}-result-schema",
            lifecycle_strategy=lifecycle_strategy,
            companion_uris=companions,
            project_guard_mode=project_guard_mode,
            post_execution_project_guard_policy=POST_EXECUTION_PROJECT_GUARD_POLICY_BY_URI.get(
                uri,
                POST_EXECUTION_PROJECT_GUARD_REVALIDATE,
            ),
        )


def validate_packaged_execution_contracts(
    registry: ExecutionContractRegistry | None = None,
) -> dict[str, Any]:
    """Validate the complete five-version inventory and return stable counts."""

    selected = registry or ExecutionContractRegistry()
    rows: list[ExecutionContract] = []
    inventory_rows: list[str] = []
    for version in SUPPORTED_WWISE_VERSION_KEYS:
        entries = selected.entries(version)
        rows.extend(entries)
        inventory_rows.extend(
            f"{entry.version}\t{entry.item_type}\t{entry.uri}\n" for entry in entries
        )
    digest = hashlib.sha256("".join(sorted(inventory_rows)).encode("utf-8")).hexdigest()
    if digest != PACKAGED_INVENTORY_SHA256:
        raise ExecutionContractError(
            "The packaged WAAPI inventory changed without a reviewed execution-contract update: "
            f"expected {PACKAGED_INVENTORY_SHA256}, got {digest}"
        )
    if len(rows) != EXPECTED_MANIFEST_VERSION_ROWS:
        raise ExecutionContractError(
            f"Expected {EXPECTED_MANIFEST_VERSION_ROWS} manifest rows, got {len(rows)}"
        )
    executable = tuple(entry for entry in rows if entry.executable)
    if len(executable) != EXPECTED_PUBLIC_VERSION_ROWS:
        raise ExecutionContractError(
            f"Expected {EXPECTED_PUBLIC_VERSION_ROWS} executable rows, got {len(executable)}"
        )
    unique_public = {entry.uri for entry in executable}
    if len(unique_public) != EXPECTED_PUBLIC_UNIQUE_URIS:
        raise ExecutionContractError(
            f"Expected {EXPECTED_PUBLIC_UNIQUE_URIS} unique public URIs, got {len(unique_public)}"
        )
    reflected_exclusions = {entry.uri for entry in rows if not entry.executable}
    if reflected_exclusions != set(APPROVED_EXCLUSIONS):
        raise ExecutionContractError(
            "Reflected exclusions do not match the approved exclusion registry: "
            f"expected={sorted(APPROVED_EXCLUSIONS)!r}, actual={sorted(reflected_exclusions)!r}"
        )
    invalid_post_execution_policies = tuple(
        (entry.version, entry.uri, entry.post_execution_project_guard_policy)
        for entry in rows
        if entry.post_execution_project_guard_policy not in POST_EXECUTION_PROJECT_GUARD_POLICIES
    )
    if invalid_post_execution_policies:
        raise ExecutionContractError(
            "Execution contracts contain unsupported post-execution project-guard policies: "
            f"{invalid_post_execution_policies!r}"
        )
    context_runtime_only = tuple(
        entry
        for entry in rows
        if entry.post_execution_project_guard_policy
        == POST_EXECUTION_PROJECT_GUARD_CONTEXT_RUNTIME_ONLY
    )
    expected_context_runtime_only = {
        (version, uri)
        for version in SUPPORTED_WWISE_VERSION_KEYS
        for uri in CONTEXT_RUNTIME_ONLY_POST_EXECUTION_URIS
    }
    actual_context_runtime_only = {
        (entry.version, entry.uri) for entry in context_runtime_only
    }
    if actual_context_runtime_only != expected_context_runtime_only or any(
        entry.route != "isolated_transaction"
        or entry.project_guard_mode != PROJECT_GUARD_INVARIANT
        or entry.verification_strategy != "result_schema"
        for entry in context_runtime_only
    ):
        raise ExecutionContractError(
            "The context/runtime-only post-execution project policy must apply exactly "
            "to the reviewed explicit-project Wwise CLI isolated/result-schema rows"
        )
    if any(
        entry.post_execution_project_guard_policy
        != POST_EXECUTION_PROJECT_GUARD_REVALIDATE
        for entry in rows
        if (entry.version, entry.uri) not in expected_context_runtime_only
    ):
        raise ExecutionContractError(
            "Every other execution-contract row must retain post-execution project revalidation"
        )
    return {
        "contract": PUBLIC_EXECUTION_CONTRACT,
        "manifest_rows": len(rows),
        "executable_rows": len(executable),
        "excluded_rows": len(rows) - len(executable),
        "unique_public_uris": len(unique_public),
        "inventory_sha256": digest,
        "by_version": {
            version: {
                "manifest": len(selected.entries(version)),
                "executable": len(selected.executable_entries(version)),
            }
            for version in SUPPORTED_WWISE_VERSION_KEYS
        },
    }


def classify_function_effect(uri: str) -> str:
    """Return the reviewed effect class used by safety and routing."""

    if uri.startswith(FILESYSTEM_OR_EXTERNAL_PREFIXES) or uri in FILESYSTEM_OR_EXTERNAL_URIS:
        return "external"
    operation = uri.rsplit(".", 1)[-1]
    if operation.startswith(("get", "is")) or operation in READ_OPERATION_NAMES:
        return "read"
    if uri.startswith(MANAGED_SESSION_PREFIXES):
        return "runtime_mutation"
    return "project_mutation"


def _transaction_route(uri: str, effect: str) -> str:
    if uri in UNDO_GROUP_MEMBER_URIS:
        return "compound_transaction_member"
    if effect == "external":
        return "isolated_transaction"
    if effect == "runtime_mutation" or uri.startswith(MANAGED_SESSION_PREFIXES):
        return "managed_transaction"
    return "transaction"


def _validate_version_counts(version: str, entries: Iterable[ExecutionContract]) -> None:
    rows = tuple(entries)
    expected = EXPECTED_VERSION_COUNTS[version]
    actual = {
        "functions": sum(entry.item_type == "function" for entry in rows),
        "topics": sum(entry.item_type == "topic" for entry in rows),
        "public_functions": sum(entry.item_type == "function" and entry.executable for entry in rows),
        "public_topics": sum(entry.item_type == "topic" and entry.executable for entry in rows),
        "public_total": sum(entry.executable for entry in rows),
    }
    if actual != dict(expected):
        raise ExecutionContractError(
            f"Wwise {version} execution-contract counts changed: expected={dict(expected)!r}, actual={actual!r}"
        )


def _validate_version_inventory_digest(
    version: str,
    entries: Iterable[ExecutionContract],
) -> None:
    inventory = "".join(
        sorted(
            f"{entry.version}\t{entry.item_type}\t{entry.uri}\n"
            for entry in entries
        )
    ).encode("utf-8")
    actual = hashlib.sha256(inventory).hexdigest()
    expected = EXPECTED_VERSION_INVENTORY_SHA256[version]
    if actual != expected:
        raise ExecutionContractError(
            f"Wwise {version} inventory changed without a reviewed execution-contract update: "
            f"expected {expected}, got {actual}"
        )


def _require_supported_version(version: str) -> None:
    if version not in SUPPORTED_WWISE_VERSION_KEYS:
        raise ExecutionContractError(
            f"Unsupported Wwise version {version!r}; supported versions: {', '.join(SUPPORTED_WWISE_VERSION_KEYS)}"
        )


__all__ = [
    "APPROVED_EXCLUSIONS",
    "BOUNDED_DIRECT_CALL_URIS",
    "CONTEXT_RUNTIME_ONLY_POST_EXECUTION_URIS",
    "EXPECTED_MANIFEST_VERSION_ROWS",
    "EXPECTED_PUBLIC_UNIQUE_URIS",
    "EXPECTED_PUBLIC_VERSION_ROWS",
    "EXPECTED_VERSION_COUNTS",
    "EXPECTED_VERSION_INVENTORY_SHA256",
    "ExecutionContract",
    "ExecutionContractError",
    "ExecutionContractRegistry",
    "FIXED_COMMANDS_BY_URI",
    "LIFECYCLE_COMPANIONS",
    "PACKAGED_INVENTORY_SHA256",
    "POST_EXECUTION_PROJECT_GUARD_CONTEXT_RUNTIME_ONLY",
    "POST_EXECUTION_PROJECT_GUARD_POLICIES",
    "POST_EXECUTION_PROJECT_GUARD_POLICY_BY_URI",
    "POST_EXECUTION_PROJECT_GUARD_REVALIDATE",
    "UNDO_GROUP_MEMBER_URIS",
    "PROJECT_GUARD_INVARIANT",
    "PROJECT_GUARD_MODES",
    "PROJECT_GUARD_TRANSITION_TO_NONE",
    "PROJECT_GUARD_TRANSITION_TO_PATH",
    "PROJECT_TRANSITION_GUARD_MODES",
    "PUBLIC_EXECUTION_CONTRACT",
    "classify_function_effect",
    "validate_packaged_execution_contracts",
]
