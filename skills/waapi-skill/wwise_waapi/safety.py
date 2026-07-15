"""Shared safety classification for manifest-backed WAAPI execution.

The safety model is deliberately conservative.  Reflection proves that a URI
exists; it does not prove that calling it is read-only.  Public callers may run
known read operations directly, while every other function must cross the
destructive gate (and, at the higher Skill interface, a preview/confirmation
transaction).
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from .category_policy import is_unsafe_debug_live_uri


REVIEWED_FIXED_FUNCTION_URIS = frozenset(
    {
        "ak.wwise.core.getInfo",
        "ak.wwise.core.getProjectInfo",
        "ak.wwise.core.object.get",
        "ak.wwise.core.object.getAttenuationCurve",
        "ak.wwise.core.object.getPropertyAndReferenceNames",
        "ak.wwise.core.object.getPropertyInfo",
        "ak.wwise.core.object.getTypes",
        "ak.wwise.core.object.isPropertyEnabled",
        "ak.wwise.ui.getSelectedObjects",
    }
)

REVIEWED_PUBLIC_CALL_URIS = frozenset(
    {
        "ak.wwise.waapi.getFunctions",
        "ak.wwise.waapi.getTopics",
    }
)

# These reads are useful candidates, but their reflected top-level schemas do
# not close the work or result contract.  Keep them separate from the public
# allowlist so a future implementation must add a dedicated bounded command or
# exact URI-specific validator before changing the interface classification.
BOUNDED_CALL_CANDIDATES: Mapping[str, str] = MappingProxyType({
    "ak.soundengine.getState": (
        "This sound-engine read depends on an initialized engine and a deterministic authored State fixture; "
        "the Skill has no closed State identity, return-field, or cross-version live contract. A dedicated "
        "bounded command is required before it can be public."
    ),
    "ak.soundengine.getSwitch": (
        "This sound-engine read depends on an initialized engine, a deterministic authored Switch fixture, "
        "and a validated game-object identity; the Skill has no closed cross-version live contract. A "
        "dedicated bounded command is required before it can be public."
    ),
    "ak.wwise.core.blendContainer.getAssignments": (
        "This read accepts an unresolved Blend Track GUID reference and returns a project-sized assignment "
        "array. A dedicated command must validate one exact track and enforce a strict result contract first."
    ),
    "ak.wwise.core.mediaPool.getFields": (
        "This 2025-only field-registry read has no behavior-backed public contract or strict result bound. A "
        "dedicated command must validate and bound the returned field inventory first."
    ),
    "ak.wwise.core.object.diff": (
        "This read accepts two unresolved object references. A dedicated command must require bounded exact "
        "identities and validate the shallow property/list-name result before public execution."
    ),
    "ak.wwise.core.object.isLinked": (
        "This read has unresolved object and platform references plus an unconstrained property name. A "
        "dedicated command must validate all three against packaged metadata before public execution."
    ),
    "ak.wwise.core.ping": (
        "This version-limited availability probe lacks a behavior-backed fixed result contract. It must be "
        "promoted through a dedicated bounded status command rather than the generic call surface."
    ),
    "ak.wwise.core.profiler.getAudioObjects": (
        "This profiler read requires capture-aware cursor validation, a mandatory Bus pipeline scope, bounded "
        "return fields, and a strict result ceiling. Those constraints require a dedicated command."
    ),
    "ak.wwise.core.profiler.getBusses": (
        "This profiler read can enumerate every captured Bus when its optional pipeline ID is absent. A "
        "dedicated command must require one validated pipeline ID and a strict result contract."
    ),
    "ak.wwise.core.profiler.getCursorTime": (
        "This profiler read uses an unresolved cursor reference and depends on current capture state. A "
        "dedicated command must validate the cursor enum and exact integer result first."
    ),
    "ak.wwise.core.profiler.getPerformanceMonitor": (
        "This profiler read depends on capture state and returns a counter inventory without a public result "
        "contract. A dedicated command must validate time and bound counters to the packaged catalog first."
    ),
    "ak.wwise.core.profiler.getVoiceContributions": (
        "This profiler read accepts unresolved pipeline IDs, an unbounded Bus pipeline array, and returns a "
        "hierarchical contribution tree. A dedicated command must cap and validate all three dimensions."
    ),
    "ak.wwise.core.profiler.getVoices": (
        "This profiler read can enumerate every captured voice when its optional pipeline ID is absent. A "
        "dedicated command must require one validated voice pipeline ID and a strict result contract."
    ),
    "ak.wwise.core.remote.getConnectionStatus": (
        "This runtime-dependent status read can expose remote host or profiler-session path data and lacks a "
        "reviewed cross-version projection. A dedicated bounded and redacted status command is required."
    ),
    "ak.wwise.core.soundbank.getInclusions": (
        "This read accepts an unresolved SoundBank reference and returns a project-sized inclusion array. A "
        "dedicated command must validate one exact SoundBank and enforce a strict result contract first."
    ),
    "ak.wwise.core.switchContainer.getAssignments": (
        "This read accepts an unresolved Switch Container reference and returns a project-sized assignment "
        "array. A dedicated command must validate one exact container and enforce a strict result contract first."
    ),
    "ak.wwise.core.transport.getList": (
        "This read returns the complete session transport inventory without a public row bound. A dedicated "
        "command must enforce a reviewed lifecycle and strict result ceiling first."
    ),
    "ak.wwise.core.transport.getState": (
        "This read accepts an unresolved transport ID and depends on a live transport lifecycle. A dedicated "
        "command must validate the ID and exact state enum result before public execution."
    ),
    "ak.wwise.ui.commands.getCommands": (
        "This GUI-dependent command inventory is absent from newer manifests and has only substitute evidence. "
        "A dedicated bounded UI command must validate availability and the returned string list first."
    ),
    "ak.wwise.waapi.getSchema": (
        "This reflection read accepts an arbitrary URI and can include large examples. A dedicated offline or "
        "bounded command must require membership in the detected-version manifest and disable examples first."
    ),
})

REVIEWED_READ_ONLY_FUNCTION_URIS = (
    REVIEWED_FIXED_FUNCTION_URIS | REVIEWED_PUBLIC_CALL_URIS
)

REVIEWED_TOPIC_URIS = frozenset(
    {
        "ak.wwise.core.audio.imported",
        "ak.wwise.core.log.itemAdded",
        "ak.wwise.core.object.attenuationCurveChanged",
        "ak.wwise.core.object.attenuationCurveLinkChanged",
        "ak.wwise.core.object.childAdded",
        "ak.wwise.core.object.childRemoved",
        "ak.wwise.core.object.created",
        "ak.wwise.core.object.curveChanged",
        "ak.wwise.core.object.nameChanged",
        "ak.wwise.core.object.notesChanged",
        "ak.wwise.core.object.postDeleted",
        "ak.wwise.core.object.preDeleted",
        "ak.wwise.core.object.propertyChanged",
        "ak.wwise.core.object.referenceChanged",
        "ak.wwise.core.object.structureChanged",
        "ak.wwise.core.profiler.captureLog.itemAdded",
        "ak.wwise.core.profiler.gameObjectRegistered",
        "ak.wwise.core.profiler.gameObjectReset",
        "ak.wwise.core.profiler.gameObjectUnregistered",
        "ak.wwise.core.profiler.stateChanged",
        "ak.wwise.core.profiler.switchChanged",
        "ak.wwise.core.project.loaded",
        "ak.wwise.core.project.postClosed",
        "ak.wwise.core.project.preClosed",
        "ak.wwise.core.project.saved",
        "ak.wwise.core.soundbank.generated",
        "ak.wwise.core.soundbank.generationDone",
        "ak.wwise.core.switchContainer.assignmentAdded",
        "ak.wwise.core.switchContainer.assignmentRemoved",
        "ak.wwise.core.transport.stateChanged",
    }
)

EXPLICIT_UNSUPPORTED_LIVE_URIS: Mapping[str, str] = MappingProxyType({
    "ak.wwise.cli.dumpObjects": (
        "This CLI URI requires an output path and writes an external file; "
        "the Skill has no closed output-path or file-lifecycle contract for it."
    ),
    "ak.wwise.cli.verify": (
        "This CLI URI loads an arbitrary project outside the active Authoring session; "
        "the Skill has no project-path confinement or disposable CLI lifecycle contract for it."
    ),
    "ak.wwise.core.audioSourcePeaks.getMinMaxPeaksInRegion": (
        "This peak query permits an effectively unbounded numPeaks value and base64 result; "
        "the Skill has no closed work or result-size contract for it."
    ),
    "ak.wwise.core.audioSourcePeaks.getMinMaxPeaksInTrimmedRegion": (
        "This trimmed peak query permits an effectively unbounded numPeaks value and base64 result; "
        "the Skill has no closed work or result-size contract for it."
    ),
    "ak.wwise.core.log.get": (
        "This log query returns an entire channel history without server-side pagination or a count limit; "
        "a post-call result ceiling cannot bound Wwise-side enumeration or transport work. Use a bounded "
        "ak.wwise.core.log.itemAdded wait for new observations instead."
    ),
    "ak.wwise.core.mediaPool.get": (
        "This Media Pool search can perform unbounded feature work and read an external audio path; "
        "the Skill has no approved database, path-scope, or result-size contract for it."
    ),
    "ak.wwise.core.profiler.getCpuUsage": (
        "This profiler query returns unfilterable full-frame CPU rows for every captured element, including "
        "plug-ins; the Skill has no server-side item or work bound for it."
    ),
    "ak.wwise.core.profiler.getGameObjects": (
        "This profiler query returns every captured game object at a frame and provides no server-side "
        "identity, count, or pagination bound."
    ),
    "ak.wwise.core.profiler.getLoadedMedia": (
        "This profiler query returns the complete loaded-media set for a capture frame and provides no "
        "server-side media, count, or pagination bound."
    ),
    "ak.wwise.core.profiler.getMeters": (
        "This profiler query returns every registered Bus, Aux Bus, and device meter, including channel data, "
        "with no server-side meter or channel-count bound."
    ),
    "ak.wwise.core.profiler.getRTPCs": (
        "This profiler query returns all active RTPC rows associated with captured voices and provides no "
        "server-side RTPC, voice, or result-count bound."
    ),
    "ak.wwise.core.profiler.getStreamedMedia": (
        "This profiler query returns the complete streamed-media set for a capture frame and provides no "
        "server-side stream, count, or pagination bound."
    ),
    "ak.wwise.core.remote.getAvailableConsoles": (
        "This remote-discovery query crosses network and profiler-session boundaries, can expose host or file "
        "paths, and has no reviewed discovery scope or result-count contract."
    ),
    "ak.wwise.core.sourceControl.getSourceFiles": (
        "This source-control query can recursively traverse an unbounded Originals tree; "
        "the Skill has no root-confined pagination or result-size contract for it."
    ),
    "ak.wwise.core.sourceControl.getStatus": (
        "This source-control query accepts unbounded absolute paths and may invoke an external provider; "
        "the Skill has no project-root, provider, network, or file-count contract for it."
    ),
    "ak.wwise.debug.getWalTree": (
        "This private debug URI exposes an unbounded internal WAL tree; "
        "the Skill has no bounded debug-data contract for it."
    ),
    "ak.wwise.debug.validateCall": (
        "This Debug-build-only URI accepts arbitrary nested args, options, and result documents and can perform "
        "unbounded schema-validation work; the debug family has no behavior-backed public contract."
    ),
})

IMMEDIATE_UNSUPPORTED_CALL_URIS = frozenset(
    {
        "ak.wwise.core.log.get",
        "ak.wwise.core.profiler.getCpuUsage",
        "ak.wwise.core.profiler.getGameObjects",
        "ak.wwise.core.profiler.getLoadedMedia",
        "ak.wwise.core.profiler.getMeters",
        "ak.wwise.core.profiler.getRTPCs",
        "ak.wwise.core.profiler.getStreamedMedia",
        "ak.wwise.core.remote.getAvailableConsoles",
        "ak.wwise.debug.validateCall",
    }
)

if len(REVIEWED_PUBLIC_CALL_URIS) != 2:
    raise RuntimeError("The public generic-call allowlist must contain exactly the two reviewed reflection lists")
if len(BOUNDED_CALL_CANDIDATES) != 20:
    raise RuntimeError("The bounded-call candidate registry must contain exactly 20 audited URI boundaries")
if len(IMMEDIATE_UNSUPPORTED_CALL_URIS) != 9:
    raise RuntimeError("The immediate unsupported-call registry must contain exactly 9 audited URI boundaries")
if not IMMEDIATE_UNSUPPORTED_CALL_URIS <= frozenset(EXPLICIT_UNSUPPORTED_LIVE_URIS):
    raise RuntimeError("Every immediate unsupported call must have an explicit structured boundary reason")
if (
    REVIEWED_PUBLIC_CALL_URIS & frozenset(BOUNDED_CALL_CANDIDATES)
    or REVIEWED_PUBLIC_CALL_URIS & IMMEDIATE_UNSUPPORTED_CALL_URIS
    or frozenset(BOUNDED_CALL_CANDIDATES) & IMMEDIATE_UNSUPPORTED_CALL_URIS
):
    raise RuntimeError("Public, bounded-candidate, and immediate-unsupported call sets must be disjoint")

EXPLICIT_UNSUPPORTED_TOPIC_URIS: Mapping[str, str] = MappingProxyType({
    "ak.wwise.debug.assertFailed": (
        "This debug topic lacks a deterministic reviewed observation fixture and remains outside "
        "the public bounded-topic interface."
    ),
    "ak.wwise.ui.commands.executed": (
        "This UI command topic lacks reviewed no-state-change evidence and remains outside "
        "the public bounded-topic interface."
    ),
    "ak.wwise.ui.selectionChanged": (
        "This UI selection topic lacks reviewed no-state-change evidence and remains outside "
        "the public bounded-topic interface."
    ),
})


@dataclass(frozen=True, slots=True)
class ApiSafety:
    """Stable safety facts used by the catalog and dispatcher."""

    read_only: bool
    requires_destructive_gate: bool
    requires_confirmation: bool
    interface_status: str
    reason: str

    def as_dict(self) -> dict[str, object]:
        return {
            "read_only": self.read_only,
            "requires_destructive_gate": self.requires_destructive_gate,
            "requires_confirmation": self.requires_confirmation,
            "interface_status": self.interface_status,
            "reason": self.reason,
        }


def classify_api_safety(uri: str, item_type: str, category: str) -> ApiSafety:
    """Classify one reflected URI without relying on incomplete evidence data."""

    if item_type == "topic":
        if uri not in REVIEWED_TOPIC_URIS:
            reason = EXPLICIT_UNSUPPORTED_TOPIC_URIS.get(uri) or (
                "This topic is not in the immutable reviewed topic allowlist; reflected or future "
                "topics remain unavailable until their bounded observation contract is reviewed."
            )
            return ApiSafety(
                read_only=False,
                requires_destructive_gate=True,
                requires_confirmation=True,
                interface_status="unsupported_by_skill_interface",
                reason=reason,
            )
        return ApiSafety(
            read_only=True,
            requires_destructive_gate=False,
            requires_confirmation=False,
            interface_status="available",
            reason=(
                "This topic is in the immutable reviewed topic allowlist and is exposed only "
                "through one bounded wait with guaranteed unsubscribe."
            ),
        )
    if item_type != "function":
        raise ValueError(f"Unsupported WAAPI item type: {item_type!r}")
    explicit_boundary = EXPLICIT_UNSUPPORTED_LIVE_URIS.get(uri)
    if explicit_boundary is not None:
        return ApiSafety(
            read_only=False,
            requires_destructive_gate=True,
            requires_confirmation=True,
            interface_status="unsupported_by_skill_interface",
            reason=explicit_boundary,
        )
    bounded_candidate = BOUNDED_CALL_CANDIDATES.get(uri)
    if bounded_candidate is not None:
        return ApiSafety(
            read_only=False,
            requires_destructive_gate=True,
            requires_confirmation=True,
            interface_status="unsupported_by_skill_interface",
            reason=bounded_candidate,
        )
    if is_unsafe_debug_live_uri(uri, category):
        return ApiSafety(
            read_only=False,
            requires_destructive_gate=True,
            requires_confirmation=True,
            interface_status="unsupported_by_skill_interface",
            reason="This debug URI can assert, crash, or alter automation behavior and is never dispatched live.",
        )

    if uri in REVIEWED_READ_ONLY_FUNCTION_URIS:
        return ApiSafety(
            read_only=True,
            requires_destructive_gate=False,
            requires_confirmation=False,
            interface_status="available",
            reason="This exact URI is in the immutable reviewed read-only function allowlist.",
        )
    return ApiSafety(
        read_only=False,
        requires_destructive_gate=True,
        requires_confirmation=True,
        interface_status="available_via_transaction",
        reason=(
            "This exact URI is not in the immutable reviewed read-only function allowlist. "
            "It can become executable only through a closed operation-registry transaction; "
            "otherwise the Skill interface keeps it unsupported."
        ),
    )


def requires_destructive_gate(uri: str, item_type: str, category: str) -> bool:
    """Return the shared dispatcher gate decision for one API."""

    return classify_api_safety(uri, item_type, category).requires_destructive_gate
