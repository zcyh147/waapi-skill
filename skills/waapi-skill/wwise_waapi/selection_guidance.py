"""Business-intent routing hints for overlapping reflected WAAPI capabilities.

These records do not grant execution authority and do not replace versioned
schemas.  They help an Agent choose among several already-public routes before
it materializes a request.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence


def _guidance(
    *,
    domain: str,
    use_when: Sequence[str],
    avoid_when: Sequence[str] = (),
    preferred_over: Sequence[tuple[str, str]] = (),
    choose_instead: Sequence[tuple[str, str]] = (),
) -> Mapping[str, Any]:
    return {
        "principle": (
            "Choose from the user's intended business outcome, not merely from "
            "whether this native API can encode the request."
        ),
        "domain": domain,
        "use_when": tuple(use_when),
        "avoid_when": tuple(avoid_when),
        "preferred_over": tuple(
            {"target": target, "when": condition}
            for target, condition in preferred_over
        ),
        "choose_instead": tuple(
            {"target": target, "when": condition}
            for target, condition in choose_instead
        ),
    }


def _specialized_authoring_mutation(
    outcome: str,
    *,
    generic_targets: Sequence[str] = ("object.setProperty", "object.set"),
) -> Mapping[str, Any]:
    return _guidance(
        domain="authoring_project_model",
        use_when=(outcome,),
        avoid_when=(
            "The Agent is treating the dedicated native concept as an ordinary property, reference, or list solely because a generic mutation could approximate it.",
        ),
        preferred_over=tuple(
            (target, f"the requested outcome is {outcome.rstrip('.')}")
            for target in generic_targets
        ),
    )


CAPABILITY_SELECTION_GUIDANCE: dict[str, Mapping[str, Any]] = {
    "ak.wwise.core.audio.setConversionPlugin": _specialized_authoring_mutation(
        "The user asks to set the Conversion Settings ShareSet used by Authoring audio conversion.",
        generic_targets=("object.setReference", "object.set"),
    ),
    "ak.wwise.core.blendContainer.addAssignment": _specialized_authoring_mutation(
        "The user asks to add a Blend Container child assignment.",
        generic_targets=("object.setReference", "object.set"),
    ),
    "ak.wwise.core.blendContainer.addTrack": _specialized_authoring_mutation(
        "The user asks to add a Blend Track to a Blend Container.",
        generic_targets=("object.create", "object.set"),
    ),
    "ak.wwise.core.blendContainer.removeAssignment": _specialized_authoring_mutation(
        "The user asks to remove a Blend Container child assignment.",
        generic_targets=("object.setReference", "object.set"),
    ),
    "ak.wwise.core.gameParameter.setRange": _specialized_authoring_mutation(
        "The user asks to set a Game Parameter minimum and maximum as one range operation.",
        generic_targets=("object.setProperty", "object.set"),
    ),
    "ak.wwise.core.object.pasteProperties": _specialized_authoring_mutation(
        "The user asks to paste or transfer a reviewed property set between Authoring objects.",
        generic_targets=("object.setProperty", "object.set"),
    ),
    "ak.wwise.core.object.setAttenuationCurve": _specialized_authoring_mutation(
        "The user asks to set an Authoring attenuation curve.",
        generic_targets=("object.setProperty", "object.set"),
    ),
    "ak.wwise.core.object.setRandomizer": _specialized_authoring_mutation(
        "The user asks to configure an Authoring property randomizer.",
        generic_targets=("object.setProperty", "object.set"),
    ),
    "ak.wwise.core.object.setStateGroups": _specialized_authoring_mutation(
        "The user asks to set an Authoring object's State Group structure.",
        generic_targets=("object.setReference", "object.set"),
    ),
    "ak.wwise.core.object.setStateProperties": _specialized_authoring_mutation(
        "The user asks to set Authoring State property values.",
        generic_targets=("object.setProperty", "object.set"),
    ),
    "ak.wwise.core.sound.setActiveSource": _specialized_authoring_mutation(
        "The user asks to select the active source of an Authoring Sound object.",
        generic_targets=("object.setReference", "object.set"),
    ),
    "ak.soundengine.setRTPCValue": _guidance(
        domain="runtime_soundengine",
        use_when=(
            "The user asks to set a runtime RTPC value for a game object or the global runtime scope.",
        ),
        avoid_when=("The user asks to author or edit an RTPC curve in the Wwise project.",),
        choose_instead=(
            ("object.setRTPC", "the requested outcome is an Authoring RTPC curve"),
            ("ak.soundengine.resetRTPCValue", "the user asks to reset rather than set the runtime value"),
        ),
    ),
    "ak.soundengine.resetRTPCValue": _guidance(
        domain="runtime_soundengine",
        use_when=("The user asks to reset a runtime RTPC value.",),
        avoid_when=("The user asks to remove or edit an Authoring RTPC curve.",),
        choose_instead=(
            ("object.setRTPC", "the requested outcome is an Authoring RTPC curve"),
            ("ak.soundengine.setRTPCValue", "the user supplies a new runtime value"),
        ),
    ),
    "ak.soundengine.setSwitch": _guidance(
        domain="runtime_soundengine",
        use_when=("The user asks to set a runtime Switch value on a game object.",),
        avoid_when=("The user asks to edit Switch Container child assignments in the project.",),
        choose_instead=(
            ("switchContainer.addAssignment", "the requested outcome is an Authoring assignment"),
            ("switchContainer.removeAssignment", "the requested outcome is removal of an Authoring assignment"),
        ),
    ),
    "ak.soundengine.setState": _guidance(
        domain="runtime_soundengine",
        use_when=("The user asks to set a runtime State value.",),
        avoid_when=("The user asks to edit Authoring State Groups or State properties.",),
        choose_instead=(
            ("ak.wwise.core.object.setStateGroups", "the requested outcome is Authoring State Group structure"),
            ("ak.wwise.core.object.setStateProperties", "the requested outcome is Authoring State property data"),
        ),
    ),
    "ak.soundengine.postTrigger": _guidance(
        domain="runtime_soundengine",
        use_when=("The user asks to post a runtime Trigger.",),
        avoid_when=("The user asks to edit the project's Trigger or assignment structure.",),
    ),
    "ak.soundengine.postEvent": _guidance(
        domain="runtime_soundengine",
        use_when=(
            "The user asks to post a runtime Event through the SoundEngine, optionally for a game object.",
        ),
        avoid_when=(
            "The user asks to audition an Authoring object without a runtime Event/Game Object context.",
            "The user explicitly asks to invoke a menu or GUI command.",
        ),
        choose_instead=(
            ("ak.wwise.core.transport.*", "the request is Authoring object audition"),
            ("ui.commands.execute", "the request explicitly names a GUI command"),
        ),
    ),
    "ak.soundengine.executeActionOnEvent": _guidance(
        domain="runtime_soundengine",
        use_when=("The user asks to execute a runtime action on an Event.",),
        avoid_when=("The user asks to control an Authoring audition transport.",),
        choose_instead=(
            ("ak.wwise.core.transport.executeAction", "the request controls Authoring audition"),
        ),
    ),
    "ak.soundengine.stopAll": _guidance(
        domain="runtime_soundengine",
        use_when=("The user asks to stop all runtime sounds, globally or for one game object.",),
        avoid_when=(
            "The user names one Playing ID or asks to execute an action on one Event.",
        ),
        choose_instead=(
            ("ak.soundengine.stopPlayingID", "one Playing ID is the requested target"),
            ("ak.soundengine.executeActionOnEvent", "one Event/action is the requested target"),
        ),
    ),
    "ak.soundengine.stopPlayingID": _guidance(
        domain="runtime_soundengine",
        use_when=("The user asks to stop one known runtime Playing ID.",),
        avoid_when=("The user asks to stop all runtime audio or an Event by identity.",),
        choose_instead=(
            ("ak.soundengine.stopAll", "the requested scope is all runtime audio"),
            ("ak.soundengine.executeActionOnEvent", "the requested target is an Event rather than a Playing ID"),
        ),
    ),
    "ak.wwise.core.transport.create": _guidance(
        domain="authoring_audition",
        use_when=("The user asks to create an Authoring audition transport for a Wwise object.",),
        avoid_when=("The user asks to post a runtime Event through the SoundEngine.",),
        choose_instead=(
            ("ak.soundengine.postEvent", "the request is runtime Event playback"),
            ("ui.commands.execute", "the user explicitly requests a menu or GUI command"),
        ),
    ),
    "ak.wwise.core.transport.executeAction": _guidance(
        domain="authoring_audition",
        use_when=("The user asks to play, stop, pause, or resume an Authoring audition transport.",),
        avoid_when=("The user asks to control runtime Event playback.",),
        choose_instead=(
            ("ak.soundengine.postEvent", "the request posts a runtime Event"),
            ("ak.soundengine.executeActionOnEvent", "the request applies a runtime Event action"),
        ),
    ),
    "ak.wwise.core.profiler.setCursorTime": _guidance(
        domain="authoring_profiler",
        use_when=("The user asks to place the Profiler cursor at an absolute time.",),
        avoid_when=("The user asks to move relative to the current cursor.",),
        choose_instead=(
            ("ak.wwise.core.profiler.moveCursor", "the requested movement is relative"),
        ),
    ),
    "ak.wwise.core.profiler.moveCursor": _guidance(
        domain="authoring_profiler",
        use_when=("The user asks to move the Profiler cursor relative to its current time.",),
        avoid_when=("The user supplies an absolute target time.",),
        choose_instead=(
            ("ak.wwise.core.profiler.setCursorTime", "the requested position is absolute"),
        ),
    ),
    "ak.wwise.core.soundbank.generated": _guidance(
        domain="authoring_topic",
        use_when=(
            "The user wants per-SoundBank, platform, and language generation result events.",
        ),
        avoid_when=("The user only wants the overall generation cycle or log summary.",),
        choose_instead=(
            ("ak.wwise.core.soundbank.generationDone", "only the overall generation cycle is requested"),
        ),
    ),
    "ak.wwise.core.soundbank.generationDone": _guidance(
        domain="authoring_topic",
        use_when=("The user wants the overall SoundBank generation-cycle or log notification.",),
        avoid_when=(
            "The user needs per-Bank/platform/language results or proof that artifacts succeeded.",
        ),
        choose_instead=(
            ("ak.wwise.core.soundbank.generated", "per-result detail is requested"),
            ("soundbank.generate verification", "artifact success or completion proof is required"),
        ),
    ),
}


_SOURCE_CONTROL_URIS = (
    "ak.wwise.core.sourceControl.add",
    "ak.wwise.core.sourceControl.checkOut",
    "ak.wwise.core.sourceControl.commit",
    "ak.wwise.core.sourceControl.delete",
    "ak.wwise.core.sourceControl.move",
    "ak.wwise.core.sourceControl.revert",
    "ak.wwise.core.sourceControl.setProvider",
)
for _uri in _SOURCE_CONTROL_URIS:
    CAPABILITY_SELECTION_GUIDANCE[_uri] = _guidance(
        domain="authoring_source_control",
        use_when=(
            "The user asks for an independent Source Control workflow rather than a side effect of another mutation.",
        ),
        avoid_when=(
            "The only Source Control intent is to add or check out files produced or modified by one supported operation.",
        ),
        choose_instead=(
            (
                "the mutation operation's auto_add_to_source_control or auto_check_out_to_source_control field",
                "Source Control is subordinate to that same mutation",
            ),
        ),
    )


_AUTHORING_TRANSPORT_COMPANIONS = (
    "ak.wwise.core.transport.destroy",
    "ak.wwise.core.transport.getList",
    "ak.wwise.core.transport.getState",
    "ak.wwise.core.transport.prepare",
    "ak.wwise.core.transport.useOriginals",
)
for _uri in _AUTHORING_TRANSPORT_COMPANIONS:
    CAPABILITY_SELECTION_GUIDANCE[_uri] = _guidance(
        domain="authoring_audition",
        use_when=(
            "The request manages or inspects an existing Authoring audition transport.",
        ),
        avoid_when=("The request controls runtime SoundEngine playback.",),
        choose_instead=(
            ("ak.soundengine.*", "the request concerns runtime Event/Game Object playback"),
        ),
    )


_GENERIC_SOUNDENGINE_SELECTION_GUIDANCE = _guidance(
    domain="runtime_soundengine",
    use_when=(
        "The request targets the current SoundEngine runtime session, including playback, registered Game Objects, listeners, spatial state, loaded Banks, or runtime values and queries.",
    ),
    avoid_when=(
        "The requested outcome is a durable Authoring project-model edit to saved objects, properties, references, curves, or relationships.",
    ),
    choose_instead=(
        (
            "the matching dedicated semantic operation or ak.wwise.core.* route",
            "the requested outcome must be authored and saved in the Wwise project",
        ),
    ),
)


def selection_guidance_for_uri(uri: str) -> Mapping[str, Any]:
    """Return exact guidance, a SoundEngine domain fallback, or an empty mapping."""

    exact = CAPABILITY_SELECTION_GUIDANCE.get(uri)
    if exact is not None:
        return exact
    if uri.startswith("ak.soundengine."):
        return _GENERIC_SOUNDENGINE_SELECTION_GUIDANCE
    return {}


__all__ = [
    "CAPABILITY_SELECTION_GUIDANCE",
    "selection_guidance_for_uri",
]
