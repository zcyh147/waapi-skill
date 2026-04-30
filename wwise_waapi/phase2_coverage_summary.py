"""Generate the consolidated Phase 2 WAAPI coverage summary."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

from .api_coverage_audit import Phase2CoverageStatusRecord  # pyright: ignore[reportMissingImports]
from .category_policy import category_policy  # pyright: ignore[reportMissingImports]
from .deferred_registry import DeferredRegistry
from .manifest import DeterministicJsonWriter, ManifestStore
from .phase21_uri_policy import CONFORMANCE_ONLY_URIS, load_phase21_uri_policy


DEFAULT_WWISE_VERSION = "2022.1"
SKILL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST_ROOT = SKILL_ROOT / "resources" / "manifest"
DEFAULT_COVERAGE_ROOT = SKILL_ROOT / "resources" / "coverage"
DEFAULT_SUMMARY_RESOURCE = DEFAULT_COVERAGE_ROOT / DEFAULT_WWISE_VERSION / "phase2-coverage-summary.json"

LIVE_SANDBOX_TESTED_URIS = frozenset(
    {
        "ak.wwise.core.object.get",
        "ak.wwise.core.object.getAttenuationCurve",
        "ak.wwise.core.object.getPropertyAndReferenceNames",
        "ak.wwise.core.object.getPropertyInfo",
        "ak.wwise.core.object.getTypes",
    }
)
SANDBOX_MUTATING_TESTED_URIS = frozenset(
    {
        "ak.wwise.core.audio.import",
        "ak.wwise.core.audio.importTabDelimited",
        "ak.wwise.core.audio.imported",
        "ak.wwise.core.object.create",
        "ak.wwise.core.object.delete",
        "ak.wwise.core.object.set",
        "ak.wwise.core.soundbank.generate",
        "ak.wwise.core.soundbank.generated",
        "ak.wwise.core.soundbank.generationDone",
        "ak.wwise.core.soundbank.getInclusions",
        "ak.wwise.core.soundbank.setInclusions",
        "ak.wwise.core.undo.beginGroup",
        "ak.wwise.core.undo.endGroup",
        "ak.wwise.core.undo.undo",
    }
)
PROFILER_BACKED_TESTED_URIS = frozenset[str]()
SOUNDENGINE_BACKED_TESTED_URIS = frozenset[str]()

TASK5_LIVE_COMMAND = (
    "WWISE_LIVE=1 WWISE_SAMPLE_PROJECT_PATH=/Applications/Audiokinetic/Wwise2022.1.19.8584/SampleProject "
    "python -m pytest tests/live/test_waql_live_matrix.py -q"
)
TASK6_LIVE_COMMAND = (
    "WWISE_LIVE=1 WWISE_SAMPLE_PROJECT_PATH=/Applications/Audiokinetic/Wwise2022.1.19.8584/SampleProject "
    "python -m pytest tests/live/test_object_topics_sandbox.py -q"
)
TASK7_DESTRUCTIVE_COMMAND = (
    "WWISE_LIVE=1 WWISE_DESTRUCTIVE=1 WWISE_SAMPLE_PROJECT_PATH=$WWISE_SAMPLE_PROJECT_PATH "
    "python -m pytest tests/destructive/test_project_mutation_sandbox.py -q"
)
TASK8_DESTRUCTIVE_COMMAND = (
    "WWISE_LIVE=1 WWISE_DESTRUCTIVE=1 WWISE_SAMPLE_PROJECT_PATH=$WWISE_SAMPLE_PROJECT_PATH "
    "python -m pytest tests/destructive/test_soundbank_audio_sandbox.py -q"
)
TASK9_LIVE_COMMAND = (
    "WWISE_LIVE=1 WWISE_SAMPLE_PROJECT_PATH=$WWISE_SAMPLE_PROJECT_PATH "
    "python -m pytest tests/live/test_profiler_transport_soundengine.py -q"
)
UNIT_NO_SILENT_SKIP_COMMAND = "python -m pytest tests/unit/test_no_silent_skips.py -q"
UNIT_ROUTE_COMMAND = "python -m pytest tests/unit/test_dispatch_routes_all_2022.py -q"
UNIT_WRAPPER_POLICY_COMMAND = "python -m pytest tests/unit/test_wrapper_only_categories.py -q"
UNIT_CONFORMANCE_POLICY_COMMAND = (
    "python -m pytest tests/unit/test_phase21_uri_policy.py tests/unit/test_phase2_coverage_summary.py -q"
)

TASK7_EVIDENCE = ".sisyphus/evidence/wwise-waapi-live-sandbox-coverage/task-7-object-mutation.md"
TASK7_UNDO_SWITCH_EVIDENCE = ".sisyphus/evidence/wwise-waapi-live-sandbox-coverage/task-7-undo-switch.md"
TASK8_AUDIO_EVIDENCE = ".sisyphus/evidence/wwise-waapi-live-sandbox-coverage/task-8-audio.md"
TASK8_SOUNDBANK_EVIDENCE = ".sisyphus/evidence/wwise-waapi-live-sandbox-coverage/task-8-soundbank.md"
TASK9_PROFILER_TRANSPORT_EVIDENCE = ".sisyphus/evidence/wwise-waapi-live-sandbox-coverage/task-9-profiler-transport.md"
TASK9_SOUNDENGINE_EVIDENCE = ".sisyphus/evidence/wwise-waapi-live-sandbox-coverage/task-9-soundengine.md"
TASK8_CONFORMANCE_POLICY_EVIDENCE = ".sisyphus/evidence/wwise-waapi-deferred-reevaluation/task-8-conformance-policy.md"
TASK8_SUMMARY_ACCOUNTING_EVIDENCE = ".sisyphus/evidence/wwise-waapi-deferred-reevaluation/task-8-summary-accounting.md"

SPECIFIC_BLOCKERS: dict[str, dict[str, str]] = {
    "ak.wwise.core.project.saved": {
        "blocking_condition": "WwiseConsole rejects ak.wwise.core.project.saved subscription with ak.wwise.unavailable; Topic not available for this type of Wwise instance.",
        "evidence_command": TASK6_LIVE_COMMAND,
        "evidence_path": ".sisyphus/evidence/wwise-waapi-live-sandbox-coverage/task-6-topics.md",
        "future_review_trigger": "Retry only when a Wwise Authoring fixture can subscribe to project.saved before project.save.",
    },
    "ak.wwise.core.object.created": {
        "blocking_condition": "Object-created topic still needs a reversible publisher plus payload assertion; Task 7 object mutation evidence did not assert topic delivery.",
        "evidence_command": TASK6_LIVE_COMMAND,
        "evidence_path": ".sisyphus/evidence/wwise-waapi-live-sandbox-coverage/task-6-topics.md",
        "future_review_trigger": "Promote only when disposable object creation also proves topic payload and cleanup.",
    },
    "ak.wwise.core.object.propertyChanged": {
        "blocking_condition": "Property-changed topic still needs reversible property mutation with old/new payload proof and restore cleanup.",
        "evidence_command": TASK6_LIVE_COMMAND,
        "evidence_path": ".sisyphus/evidence/wwise-waapi-live-sandbox-coverage/task-6-topics.md",
        "future_review_trigger": "Promote only with a reversible property mutation fixture and payload evidence.",
    },
    "ak.wwise.core.object.referenceChanged": {
        "blocking_condition": "Reference-changed topic still needs reversible reference mutation with old/new/reference payload proof and restore cleanup.",
        "evidence_command": TASK6_LIVE_COMMAND,
        "evidence_path": ".sisyphus/evidence/wwise-waapi-live-sandbox-coverage/task-6-topics.md",
        "future_review_trigger": "Promote only with a reversible reference mutation fixture and payload evidence.",
    },
    "ak.wwise.core.undo.cancelGroup": {
        "blocking_condition": "Local WwiseConsole left objects created after beginGroup in place after cancelGroup; evidence deletes the disposable object instead of claiming rollback.",
        "evidence_command": TASK7_DESTRUCTIVE_COMMAND,
        "evidence_path": TASK7_UNDO_SWITCH_EVIDENCE,
        "future_review_trigger": "Review when cancelGroup rollback semantics can be proven by absent-object readback in the sandbox fixture.",
    },
    "ak.wwise.core.switchContainer.addAssignment": {
        "blocking_condition": "Disposable SwitchContainer/SwitchGroup fixture did not produce a getAssignments readback pair because the Switch Group reference was not accepted.",
        "evidence_command": TASK7_DESTRUCTIVE_COMMAND,
        "evidence_path": TASK7_UNDO_SWITCH_EVIDENCE,
        "future_review_trigger": "Review when a safe fixture builder can establish an accepted Switch Group reference for the SwitchContainer.",
    },
    "ak.wwise.core.switchContainer.getAssignments": {
        "blocking_condition": "Assignment readback is blocked because addAssignment did not materialize a child/state pair in the disposable SwitchContainer fixture.",
        "evidence_command": TASK7_DESTRUCTIVE_COMMAND,
        "evidence_path": TASK7_UNDO_SWITCH_EVIDENCE,
        "future_review_trigger": "Review when addAssignment can create a deterministic assignment pair that getAssignments can read back.",
    },
    "ak.wwise.core.switchContainer.removeAssignment": {
        "blocking_condition": "Removal semantics are blocked until addAssignment and getAssignments first prove a materialized assignment pair.",
        "evidence_command": TASK7_DESTRUCTIVE_COMMAND,
        "evidence_path": TASK7_UNDO_SWITCH_EVIDENCE,
        "future_review_trigger": "Review when assignment add/readback succeeds and removal can be asserted by absent readback.",
    },
    "ak.wwise.core.soundbank.processDefinitionFiles": {
        "blocking_condition": "processDefinitionFiles returned no SoundBank object readback for the minimal sandbox definition file; Wwise logged parser/settings blockers, so no behavior is claimed.",
        "evidence_command": TASK8_DESTRUCTIVE_COMMAND,
        "evidence_path": TASK8_SOUNDBANK_EVIDENCE,
        "future_review_trigger": "Review when a version-correct SoundBank definition fixture yields a SoundBank object readback in the sandbox.",
    },
}

for _uri in (
    "ak.wwise.core.profiler.startCapture",
    "ak.wwise.core.profiler.stopCapture",
    "ak.wwise.core.transport.create",
    "ak.wwise.core.transport.getList",
    "ak.wwise.core.transport.getState",
    "ak.wwise.core.transport.executeAction",
    "ak.wwise.core.transport.destroy",
    "ak.wwise.core.transport.stateChanged",
):
    SPECIFIC_BLOCKERS.setdefault(
        _uri,
        {
            "blocking_condition": "Transport/profiler attempt did not observe a transport.stateChanged payload or getState transition; returned transport IDs and capture cursors alone are insufficient.",
            "evidence_command": TASK9_LIVE_COMMAND,
            "evidence_path": TASK9_PROFILER_TRANSPORT_EVIDENCE,
            "future_review_trigger": "Promote only when a deterministic playable event fixture produces observable transport state changes.",
        },
    )

for _uri in ("ak.soundengine.postMsgMonitor", "ak.wwise.core.profiler.captureLog.itemAdded"):
    SPECIFIC_BLOCKERS.setdefault(
        _uri,
        {
            "blocking_condition": "postMsgMonitor returned without error, but no profiler capture-log topic payload containing the unique message arrived within the bounded window.",
            "evidence_command": TASK9_LIVE_COMMAND,
            "evidence_path": TASK9_SOUNDENGINE_EVIDENCE,
            "future_review_trigger": "Promote only when captureLog.itemAdded publishes a matching monitor-message payload.",
        },
    )

for _uri in (
    "ak.soundengine.registerGameObj",
    "ak.soundengine.unregisterGameObj",
    "ak.wwise.core.profiler.gameObjectRegistered",
    "ak.wwise.core.profiler.gameObjectUnregistered",
):
    SPECIFIC_BLOCKERS.setdefault(
        _uri,
        {
            "blocking_condition": "Game-object register/unregister calls returned, but profiler game-object topic payloads were not observed within the bounded window.",
            "evidence_command": TASK9_LIVE_COMMAND,
            "evidence_path": TASK9_SOUNDENGINE_EVIDENCE,
            "future_review_trigger": "Promote only when profiler game-object topics publish payloads matching the registered fixture object.",
        },
    )

for _uri in (
    "ak.soundengine.executeActionOnEvent",
    "ak.soundengine.getState",
    "ak.soundengine.getSwitch",
    "ak.soundengine.postEvent",
    "ak.soundengine.postTrigger",
    "ak.soundengine.resetRTPCValue",
    "ak.soundengine.seekOnEvent",
    "ak.soundengine.setDefaultListeners",
    "ak.soundengine.setGameObjectAuxSendValues",
    "ak.soundengine.setGameObjectOutputBusVolume",
    "ak.soundengine.setListenerSpatialization",
    "ak.soundengine.setListeners",
    "ak.soundengine.setMultiplePositions",
    "ak.soundengine.setObjectObstructionAndOcclusion",
    "ak.soundengine.setPosition",
    "ak.soundengine.setRTPCValue",
    "ak.soundengine.setScalingFactor",
    "ak.soundengine.setState",
    "ak.soundengine.setSwitch",
    "ak.soundengine.stopAll",
    "ak.soundengine.stopPlayingID",
):
    SPECIFIC_BLOCKERS.setdefault(
        _uri,
        {
            "blocking_condition": "Soundengine call needs deterministic authored Event/State/Switch/RTPC/listener fixtures plus observable profiler/transport/event side effects; returned IDs or empty mappings are insufficient.",
            "evidence_command": TASK9_LIVE_COMMAND,
            "evidence_path": TASK9_SOUNDENGINE_EVIDENCE,
            "future_review_trigger": "Promote only after sandbox fixtures can identify matching authored objects and observe side effects for this call.",
        },
    )

for _uri in (
    "ak.wwise.core.profiler.enableProfilerData",
    "ak.wwise.core.profiler.getAudioObjects",
    "ak.wwise.core.profiler.getBusses",
    "ak.wwise.core.profiler.getCursorTime",
    "ak.wwise.core.profiler.getGameObjects",
    "ak.wwise.core.profiler.getRTPCs",
    "ak.wwise.core.profiler.getVoiceContributions",
    "ak.wwise.core.profiler.getVoices",
    "ak.wwise.core.profiler.stateChanged",
    "ak.wwise.core.profiler.switchChanged",
    "ak.wwise.core.profiler.gameObjectReset",
):
    SPECIFIC_BLOCKERS.setdefault(
        _uri,
        {
            "blocking_condition": "Profiler reads/topics need active audible voice, pipeline IDs, or authored state/switch triggers; empty arrays or no payloads are insufficient.",
            "evidence_command": TASK9_LIVE_COMMAND,
            "evidence_path": TASK9_PROFILER_TRANSPORT_EVIDENCE,
            "future_review_trigger": "Promote when a deterministic playback fixture can create profiler cursor/voice data without mutating the source project.",
        },
    )


@dataclass(slots=True)
class Phase2CoverageSummaryBuilder:
    """Build exactly one Phase 2 coverage status for every reflected URI."""

    manifest_store: ManifestStore = field(default_factory=lambda: ManifestStore(root=DEFAULT_MANIFEST_ROOT))
    coverage_root: Path = DEFAULT_COVERAGE_ROOT
    deferred_registry: DeferredRegistry = field(default_factory=lambda: DeferredRegistry.load_default(DEFAULT_WWISE_VERSION))

    def build(self, version: str = DEFAULT_WWISE_VERSION) -> dict[str, Any]:
        manifest = self.manifest_store.load(version)
        coverage_payload = self._json(self.coverage_root / version / "api-coverage.json")
        matrix_payload = self._json(self.coverage_root / version / "live-coverage-matrix.json")
        coverage_by_uri = {entry["uri"]: entry for entry in coverage_payload["coverage"]}
        matrix_entries = sorted(matrix_payload["matrix"], key=lambda entry: entry["uri"])
        entries = [self._entry(entry, coverage_by_uri[entry["uri"]]) for entry in matrix_entries]
        self._validate_reflected(manifest, entries)
        summary = self._summary(version, coverage_payload["summary"], entries)
        return {"entries": entries, "metadata": self._metadata(version), "summary": summary}

    def phase2_status_records(self, version: str = DEFAULT_WWISE_VERSION) -> list[Phase2CoverageStatusRecord]:
        return phase2_status_records_from_summary(self.build(version))

    def _entry(self, matrix_entry: Mapping[str, Any], coverage_entry: Mapping[str, Any]) -> dict[str, Any]:
        uri = str(matrix_entry["uri"])
        phase1_status = str(matrix_entry["achieved_status"])
        category = str(matrix_entry["category"])
        item_type = str(matrix_entry["item_type"])
        achieved_status = self._achieved_status(uri, category, phase1_status)
        entry: dict[str, Any] = {
            "achieved_status": achieved_status,
            "blocking_condition": "",
            "category": category,
            "counts_as_behavioral": achieved_status in {"fake-route-tested", "live-sandbox-tested", "sandbox-mutating-tested", "soundengine-backed-tested"},
            "counts_as_live_behavioral": achieved_status in {"live-sandbox-tested", "sandbox-mutating-tested", "soundengine-backed-tested"},
            "evidence_command": "",
            "evidence_class": "",
            "evidence_path": "",
            "evidence_paths": [],
            "future_review_trigger": "",
            "inventory_coverage": "reflected-schema-ok",
            "item_type": item_type,
            "phase1_behavioral_evidence": matrix_entry["phase1_behavioral_evidence"],
            "phase1_status": phase1_status,
            "review_trigger": "",
            "source_coverage_uri": matrix_entry["source_coverage_uri"],
            "source_matrix_uri": "resources/coverage/2022.1/live-coverage-matrix.json",
            "status_transition": self._status_transition(phase1_status, achieved_status),
            "substitute_test": "",
            "uri": uri,
            "user_approved_rationale": "",
            "version": matrix_entry["version"],
            "windows_validation": "pending",
        }
        if achieved_status == "fake-route-tested":
            entry.update(
                {
                    "evidence_command": UNIT_ROUTE_COMMAND,
                    "evidence_path": "resources/coverage/2022.1/api-coverage.json",
                    "evidence_paths": ["resources/coverage/2022.1/api-coverage.json"],
                }
            )
            self._add_attempted_live_context(entry, uri)
            return entry
        if achieved_status == "live-sandbox-tested":
            paths = [
                ".sisyphus/evidence/wwise-waapi-live-sandbox-coverage/task-6-object-read.md",
                *([".sisyphus/evidence/wwise-waapi-live-sandbox-coverage/task-5-waql-live.md"] if uri == "ak.wwise.core.object.get" else []),
            ]
            entry.update(
                {
                    "evidence_class": "live_behavioral_waapi",
                    "evidence_command": TASK6_LIVE_COMMAND,
                    "evidence_path": paths[0],
                    "evidence_paths": paths,
                }
            )
            return entry
        if achieved_status == "sandbox-mutating-tested":
            evidence_path, evidence_command = self._sandbox_evidence(uri)
            entry.update(
                {
                    "evidence_class": "live_behavioral_waapi",
                    "evidence_command": evidence_command,
                    "evidence_path": evidence_path,
                    "evidence_paths": [evidence_path],
                }
            )
            return entry
        if achieved_status == "profiler-backed-tested":
            entry.update(
                {
                    "evidence_class": "live_behavioral_profiler",
                    "evidence_command": TASK9_LIVE_COMMAND,
                    "evidence_path": TASK9_PROFILER_TRANSPORT_EVIDENCE,
                    "evidence_paths": [TASK9_PROFILER_TRANSPORT_EVIDENCE],
                }
            )
            return entry
        if achieved_status == "soundengine-backed-tested":
            entry.update(
                {
                    "evidence_class": "live_behavioral_waapi",
                    "evidence_command": TASK9_LIVE_COMMAND,
                    "evidence_path": TASK9_SOUNDENGINE_EVIDENCE,
                    "evidence_paths": [TASK9_SOUNDENGINE_EVIDENCE],
                }
            )
            return entry
        if achieved_status in {"wrapper-only", "skipped-approved"}:
            policy = category_policy(category)
            if policy is None:
                raise ValueError(f"Missing policy for {uri} category {category}")
            entry.update(
                {
                    "evidence_command": UNIT_WRAPPER_POLICY_COMMAND,
                    "evidence_path": "resources/coverage/2022.1/wrapper-only-category-policy.json",
                    "evidence_paths": ["resources/coverage/2022.1/wrapper-only-category-policy.json"],
                    "future_review_trigger": policy.future_review_trigger,
                    "review_trigger": policy.future_review_trigger,
                    "user_approved_rationale": policy.user_approved_rationale,
                }
            )
            return entry
        if achieved_status == "conformance-only-skip":
            policy = self._conformance_only_policy_by_uri()[uri]
            future_review_trigger = str(policy["future_review_trigger"])
            entry.update(
                {
                    "evidence_class": "conformance_only_skip",
                    "evidence_command": UNIT_CONFORMANCE_POLICY_COMMAND,
                    "evidence_path": TASK8_CONFORMANCE_POLICY_EVIDENCE,
                    "evidence_paths": [
                        TASK8_CONFORMANCE_POLICY_EVIDENCE,
                        TASK8_SUMMARY_ACCOUNTING_EVIDENCE,
                        "resources/coverage/2022.1/phase21-uri-policy.json",
                    ],
                    "future_review_trigger": future_review_trigger,
                    "review_trigger": future_review_trigger,
                    "status_policy": (
                        "User-reviewed conformance-only skip: reflected schema and route conformance remain "
                        "covered, but behavioral and live behavioral coverage are not claimed."
                    ),
                    "user_approved_rationale": str(policy["user_approved_rationale"]),
                }
            )
            if uri == "ak.wwise.core.undo.cancelGroup":
                entry["related_blocker"] = "ak.wwise.core.undo.redo is not reflected in the local 2022.1 manifest; redo remains unclaimed."
            return entry

        deferred = self.deferred_registry.get(uri)
        blocker = SPECIFIC_BLOCKERS.get(uri, {})
        substitute_test = (
            deferred.substitute_test
            if deferred is not None
            else "Phase 1 fake-route/unit dispatch remains substitute evidence for route and inventory only; not behavioral coverage."
        )
        blocking_condition = (
            blocker.get("blocking_condition")
            or (deferred.blocking_condition if deferred is not None else "Live behavioral evidence remains blocked by the recorded Phase 2 evidence condition.")
        )
        review_trigger = (
            blocker.get("future_review_trigger")
            or (deferred.review_trigger if deferred is not None else "Review when a live sandbox fixture proves the blocked behavior directly.")
        )
        entry.update(
            {
                "blocking_condition": blocking_condition,
                "evidence_command": blocker.get("evidence_command", UNIT_NO_SILENT_SKIP_COMMAND),
                "evidence_class": "still_deferred_with_evidence",
                "evidence_path": blocker.get("evidence_path", "resources/deferred/2022.1.json"),
                "future_review_trigger": review_trigger,
                "review_trigger": review_trigger,
                "substitute_test": substitute_test,
            }
        )
        entry["evidence_paths"] = [entry["evidence_path"]]
        if uri == "ak.wwise.core.undo.cancelGroup":
            entry["related_blocker"] = "ak.wwise.core.undo.redo is not reflected in the local 2022.1 manifest; redo remains unclaimed."
        return entry

    def _achieved_status(self, uri: str, category: str, phase1_status: str) -> str:
        policy = category_policy(category)
        if policy is not None:
            return policy.target_status
        if uri in CONFORMANCE_ONLY_URIS:
            return "conformance-only-skip"
        if phase1_status == "fake-route-tested":
            return "fake-route-tested"
        if uri in LIVE_SANDBOX_TESTED_URIS:
            return "live-sandbox-tested"
        if uri in SANDBOX_MUTATING_TESTED_URIS:
            return "sandbox-mutating-tested"
        if uri in PROFILER_BACKED_TESTED_URIS:
            return "profiler-backed-tested"
        if uri in SOUNDENGINE_BACKED_TESTED_URIS:
            return "soundengine-backed-tested"
        if uri in SPECIFIC_BLOCKERS:
            return "still-deferred-with-evidence"
        return "still-deferred-with-evidence"

    def _add_attempted_live_context(self, entry: dict[str, Any], uri: str) -> None:
        blocker = SPECIFIC_BLOCKERS.get(uri)
        if blocker is not None:
            entry["attempted_live_blocker"] = blocker["blocking_condition"]
            entry["attempted_live_evidence_command"] = blocker["evidence_command"]
            entry["attempted_live_evidence_path"] = blocker["evidence_path"]
            entry["attempted_live_review_trigger"] = blocker["future_review_trigger"]
        if uri in LIVE_SANDBOX_TESTED_URIS:
            entry["supplemental_live_evidence"] = {
                "evidence_command": TASK6_LIVE_COMMAND,
                "evidence_paths": [
                    ".sisyphus/evidence/wwise-waapi-live-sandbox-coverage/task-6-object-read.md",
                    *(
                        [".sisyphus/evidence/wwise-waapi-live-sandbox-coverage/task-5-waql-live.md"]
                        if uri == "ak.wwise.core.object.get"
                        else []
                    ),
                ],
                "status_policy": "Phase 1 fake-route-tested remains the achieved status per plan lines 37 and 571.",
            }
        if uri in SANDBOX_MUTATING_TESTED_URIS:
            evidence_path, evidence_command = self._sandbox_evidence(uri)
            entry["supplemental_live_evidence"] = {
                "evidence_command": evidence_command,
                "evidence_paths": [evidence_path],
                "status_policy": "Phase 1 fake-route-tested remains the achieved status per plan lines 37 and 571.",
            }

    def _sandbox_evidence(self, uri: str) -> tuple[str, str]:
        if uri.startswith("ak.wwise.core.object."):
            return TASK7_EVIDENCE, TASK7_DESTRUCTIVE_COMMAND
        if uri.startswith("ak.wwise.core.undo."):
            return TASK7_UNDO_SWITCH_EVIDENCE, TASK7_DESTRUCTIVE_COMMAND
        if uri.startswith("ak.wwise.core.audio."):
            return TASK8_AUDIO_EVIDENCE, TASK8_DESTRUCTIVE_COMMAND
        if uri.startswith("ak.wwise.core.soundbank."):
            return TASK8_SOUNDBANK_EVIDENCE, TASK8_DESTRUCTIVE_COMMAND
        raise ValueError(f"No sandbox evidence mapping for {uri}")

    def _summary(self, version: str, phase1_summary: Mapping[str, Any], entries: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        status_counts = _counts(entry["achieved_status"] for entry in entries)
        phase1_status_counts = _counts(entry["phase1_status"] for entry in entries)
        original_deferred_uris = {entry["uri"] for entry in entries if entry["phase1_status"] == "deferred-with-substitute-test"}
        still_deferred_uris = {entry["uri"] for entry in entries if entry["achieved_status"] == "still-deferred-with-evidence"}
        policy_approved_uris = {
            entry["uri"]
            for entry in entries
            if entry["achieved_status"] in {"wrapper-only", "skipped-approved", "conformance-only-skip"}
        }
        behavioral_statuses = {"fake-route-tested", "live-sandbox-tested", "sandbox-mutating-tested", "soundengine-backed-tested"}
        live_behavioral_statuses = {"live-sandbox-tested", "sandbox-mutating-tested", "soundengine-backed-tested"}
        return {
            "behavioral_covered_count": sum(1 for entry in entries if entry["achieved_status"] in behavioral_statuses),
            "evidence_model": "Phase 2 statuses count inventory separately from behavioral/live coverage.",
            "live_behavioral_covered_count": sum(
                1 for entry in entries if entry["achieved_status"] in live_behavioral_statuses
            ),
            "original_deferred_after_phase2": len(original_deferred_uris & still_deferred_uris),
            "original_deferred_before_phase2": int(phase1_summary["deferred"]),
            "original_deferred_policy_approved": len(original_deferred_uris & policy_approved_uris),
            "original_deferred_promoted_behavioral": len(
                [
                    entry
                    for entry in entries
                    if entry["uri"] in original_deferred_uris and entry["achieved_status"] in live_behavioral_statuses
                ]
            ),
            "original_fake_route_promoted_live": len(
                [
                    entry
                    for entry in entries
                    if entry["phase1_status"] == "fake-route-tested" and entry["achieved_status"] == "live-sandbox-tested"
                ]
            ),
            "phase1_status_counts": phase1_status_counts,
            "phase2_status_counts": status_counts,
            "profiler_backed_tested_count": status_counts.get("profiler-backed-tested", 0),
            "reflected_count": len(entries),
            "sandbox_mutating_tested_count": status_counts.get("sandbox-mutating-tested", 0),
            "soundengine_backed_tested_count": status_counts.get("soundengine-backed-tested", 0),
            "total_functions": int(phase1_summary["total_functions"]),
            "total_topics": int(phase1_summary["total_topics"]),
            "version": version,
            "windows_validation": "pending",
        }

    def _metadata(self, version: str) -> dict[str, Any]:
        return {
            "baseline_resource": "resources/coverage/2022.1/api-coverage.json",
            "deferred_resource": "resources/deferred/2022.1.json",
            "generator": "wwise_waapi.phase2_coverage_summary.Phase2CoverageSummaryBuilder",
            "live_matrix_resource": "resources/coverage/2022.1/live-coverage-matrix.json",
            "status_resources": [
                "resources/coverage/2022.1/phase21-uri-policy.json",
                "resources/coverage/2022.1/task-4-core-object-deferred-plan.json",
                "resources/coverage/2022.1/task-5-profiler-soundengine-evidence.json",
                "resources/coverage/2022.1/task-6-process-definition-files-plan.json",
                "resources/coverage/2022.1/task-7-switchcontainer-assignment-plan.json",
                "resources/coverage/2022.1/task-8-soundbank-audio-sandbox-plan.json",
                "resources/waql/2022.1/object-get-live-matrix.json",
                "resources/coverage/2022.1/task-6-object-topic-live-plan.json",
                "resources/coverage/2022.1/task-7-project-mutation-sandbox-plan.json",
                "resources/coverage/2022.1/task-9-profiler-soundengine-feasibility.json",
                "resources/coverage/2022.1/wrapper-only-category-policy.json",
            ],
            "version": version,
            "windows_policy": "Windows host validation remains pending; generated Windows SoundBank artifacts from macOS sandbox output are not Windows validation.",
        }

    def _validate_reflected(self, manifest: Mapping[str, Any], entries: Sequence[Mapping[str, Any]]) -> None:
        reflected = sorted(entry["uri"] for entry in manifest["functions"] + manifest["topics"])
        summarized = [entry["uri"] for entry in entries]
        if summarized != reflected:
            raise ValueError("Phase 2 summary must cover every reflected URI exactly once in sorted order")

    def _json(self, path: Path) -> Mapping[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    def _status_transition(self, phase1_status: str, achieved_status: str) -> str:
        if phase1_status == achieved_status == "fake-route-tested":
            return "phase1-fake-route-unchanged"
        if achieved_status in {"wrapper-only", "skipped-approved"}:
            return "phase1-deferred-policy-approved" if phase1_status != "fake-route-tested" else "phase1-fake-route-policy-approved"
        if achieved_status == "conformance-only-skip":
            return "phase1-deferred-conformance-only-policy-approved"
        if phase1_status == "fake-route-tested":
            return "phase1-fake-route-plus-live-evidence"
        if achieved_status == "still-deferred-with-evidence":
            return "phase1-deferred-still-blocked-with-evidence"
        return "phase1-deferred-promoted-with-evidence"

    def _conformance_only_policy_by_uri(self) -> dict[str, Mapping[str, Any]]:
        return {entry["uri"]: entry for entry in load_phase21_uri_policy()["conformance_only_apis"]}


def phase2_status_records_from_summary(payload: Mapping[str, Any]) -> list[Phase2CoverageStatusRecord]:
    records: list[Phase2CoverageStatusRecord] = []
    for entry in payload["entries"]:
        records.append(
            Phase2CoverageStatusRecord(
                uri=entry["uri"],
                version=entry["version"],
                category=entry["category"],
                inventory_coverage=entry["inventory_coverage"],
                achieved_status=entry["achieved_status"],
                evidence_path=entry["evidence_path"],
                evidence_command=entry["evidence_command"],
                evidence_class=entry.get("evidence_class", ""),
                user_approved_rationale=entry["user_approved_rationale"],
                future_review_trigger=entry["future_review_trigger"],
            )
        )
    return records


def write_default_phase2_summary(path: Path = DEFAULT_SUMMARY_RESOURCE) -> None:
    payload = Phase2CoverageSummaryBuilder().build(DEFAULT_WWISE_VERSION)
    DeterministicJsonWriter().write(path, payload)


def _counts(values: Sequence[str] | Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))
