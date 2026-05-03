"""Phase 2.1 exact URI policy lists for deferred WAAPI reevaluation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


DEFAULT_WWISE_VERSION = "2022.1"
SKILL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY_RESOURCE = SKILL_ROOT / "resources" / "capabilities" / DEFAULT_WWISE_VERSION / "phase21-uri-policy.json"


REOPENED_CORE_OBJECT_URIS = frozenset(
    {
        "ak.wwise.core.object.attenuationCurveChanged",
        "ak.wwise.core.object.attenuationCurveLinkChanged",
        "ak.wwise.core.object.childAdded",
        "ak.wwise.core.object.childRemoved",
        "ak.wwise.core.object.copy",
        "ak.wwise.core.object.created",
        "ak.wwise.core.object.curveChanged",
        "ak.wwise.core.object.diff",
        "ak.wwise.core.object.move",
        "ak.wwise.core.object.nameChanged",
        "ak.wwise.core.object.notesChanged",
        "ak.wwise.core.object.pasteProperties",
        "ak.wwise.core.object.postDeleted",
        "ak.wwise.core.object.preDeleted",
        "ak.wwise.core.object.propertyChanged",
        "ak.wwise.core.object.referenceChanged",
        "ak.wwise.core.object.setAttenuationCurve",
        "ak.wwise.core.object.setName",
        "ak.wwise.core.object.setNotes",
        "ak.wwise.core.object.setProperty",
        "ak.wwise.core.object.setRandomizer",
        "ak.wwise.core.object.setReference",
    }
)
REOPENED_CORE_SOUNDBANK_URIS = frozenset({"ak.wwise.core.soundbank.processDefinitionFiles"})
REOPENED_CORE_SWITCH_CONTAINER_URIS = frozenset(
    {
        "ak.wwise.core.switchContainer.addAssignment",
        "ak.wwise.core.switchContainer.assignmentAdded",
        "ak.wwise.core.switchContainer.assignmentRemoved",
        "ak.wwise.core.switchContainer.removeAssignment",
    }
)
PROFILER_PROBED_URIS = frozenset(
    {
        "ak.wwise.core.profiler.captureLog.itemAdded",
        "ak.wwise.core.profiler.enableProfilerData",
        "ak.wwise.core.profiler.gameObjectRegistered",
        "ak.wwise.core.profiler.gameObjectReset",
        "ak.wwise.core.profiler.gameObjectUnregistered",
        "ak.wwise.core.profiler.startCapture",
        "ak.wwise.core.profiler.stateChanged",
        "ak.wwise.core.profiler.stopCapture",
        "ak.wwise.core.profiler.switchChanged",
    }
)
ACCEPTED_FAKE_ROUTE_PROFILER_READ_URIS = frozenset(
    {"ak.wwise.core.transport.getList", "ak.wwise.core.transport.getState"}
)
REOPENED_SOUNDENGINE_URIS = frozenset(
    {
        "ak.soundengine.executeActionOnEvent",
        "ak.soundengine.getState",
        "ak.soundengine.getSwitch",
        "ak.soundengine.postEvent",
        "ak.soundengine.postMsgMonitor",
        "ak.soundengine.postTrigger",
        "ak.soundengine.registerGameObj",
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
        "ak.soundengine.unregisterGameObj",
    }
)
CONFORMANCE_ONLY_URIS = frozenset(
    {
        "ak.wwise.core.project.loaded",
        "ak.wwise.core.project.postClosed",
        "ak.wwise.core.project.preClosed",
        "ak.wwise.core.project.save",
        "ak.wwise.core.project.saved",
        "ak.wwise.core.transport.create",
        "ak.wwise.core.transport.destroy",
        "ak.wwise.core.transport.executeAction",
        "ak.wwise.core.transport.prepare",
        "ak.wwise.core.transport.stateChanged",
        "ak.wwise.core.undo.cancelGroup",
    }
)


def load_phase21_uri_policy(path: Path = DEFAULT_POLICY_RESOURCE) -> Mapping[str, Any]:
    """Load the exact Phase 2.1 URI policy resource."""

    return json.loads(path.read_text(encoding="utf-8"))


def reopened_uris() -> frozenset[str]:
    """URIs reopened for future live behavioral WAAPI probing without promoting status in Task 1."""

    return frozenset(
        {
            *REOPENED_CORE_OBJECT_URIS,
            *REOPENED_CORE_SOUNDBANK_URIS,
            *REOPENED_CORE_SWITCH_CONTAINER_URIS,
            *REOPENED_SOUNDENGINE_URIS,
        }
    )
