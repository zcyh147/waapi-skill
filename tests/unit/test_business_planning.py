from __future__ import annotations

from collections.abc import Sequence

import pytest

from wwise_waapi.business_declaration_state import BusinessDeclarationSession
from wwise_waapi.business_declarations import (
    BusinessContext,
    BusinessDeclarationError,
    NewDescendantTarget,
    SUPPORTED_WWISE_VERSIONS,
)
from wwise_waapi.business_planning import (
    BusinessBatch,
    BusinessEffect,
    compile_business_plan,
)


PROJECT_ID = "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}"
PARENT_ID = "{11111111-1111-1111-1111-111111111111}"


def _session(version: str = "2022.1") -> BusinessDeclarationSession:
    context = BusinessContext.create(
        task_authority="da1-" + "1" * 40,
        project_id=PROJECT_ID,
        project_path="/fixtures/SampleProject.wproj",
        wwise_version=version,
        wwise_build=f"{version}.19.8584",
    )
    session = BusinessDeclarationSession.create(context)
    parent = session.handles.bind_object(
        object_id=PARENT_ID,
        name="Weather",
        object_type="ActorMixer",
        path=r"\Actor-Mixer Hierarchy\Default Work Unit\Weather",
    )
    return session.with_new_declaration(
        declaration_id="rain-bed",
        target=NewDescendantTarget(
            parent_handle=parent.handle,
            name="Rain_Bed",
            kind="sound-sfx",
        ),
        fields={"media_file": "/tmp/rain.wav", "volume_db": -4.0},
    )


def _effect(
    effect_id: str,
    *,
    depends_on: tuple[str, ...] = (),
    batch_key: str = "audio.import",
) -> BusinessEffect:
    return BusinessEffect.create(
        effect_id=effect_id,
        declaration_id="rain-bed",
        depends_on=depends_on,
        batch_key=batch_key,
        native_fragment={"effect": effect_id},
        verifier_expectation={"effect": effect_id, "status": "present"},
        readable_lines=(f"步骤：{effect_id}",),
    )


def _materialize_audio_import(
    version: str,
    batches: Sequence[BusinessBatch],
) -> dict[str, object]:
    assert [effect for batch in batches for effect in batch.effect_ids] == [
        "container",
        "sound",
        "event",
    ]
    root = "Containers" if version == "2025.1" else "Actor-Mixer Hierarchy"
    return {
        "contract": "waapi-skill.operation-request/v1",
        "version": version,
        "operation": "audio.import",
        "arguments": {
            "imports": [
                {
                    "object_path": rf"\{root}\Default Work Unit\Weather\<Actor-Mixer>Rain_Bed",
                    "object_type": "ActorMixer",
                }
            ]
        },
    }


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSIONS)
def test_business_plan_owns_deterministic_order_batches_and_native_request(
    version: str,
) -> None:
    session = _session(version)
    effects = (
        _effect("event", depends_on=("sound",), batch_key="event"),
        _effect("sound", depends_on=("container",)),
        _effect("container"),
    )

    compiled = compile_business_plan(
        session,
        operation="audio.import",
        effects=effects,
        materialize=lambda batches: _materialize_audio_import(version, batches),
    )

    assert compiled.ordered_effect_ids == ("container", "sound", "event")
    assert [batch.effect_ids for batch in compiled.batches] == [
        ("container", "sound"),
        ("event",),
    ]
    assert compiled.request["version"] == version
    assert compiled.request["operation"] == "audio.import"
    assert len(compiled.request_digest) == 64
    assert compiled.preview.source_revision == session.revision
    assert compiled.preview.readable_lines == (
        "步骤：container",
        "步骤：sound",
        "步骤：event",
    )
    assert compiled.preview.readable_projection()["detail_available"] is True
    assert "native_request" in compiled.preview.detail


def test_business_plan_cycle_and_missing_dependencies_return_atomic_repair() -> None:
    session = _session()

    with pytest.raises(BusinessDeclarationError) as missing:
        compile_business_plan(
            session,
            operation="audio.import",
            effects=(_effect("sound", depends_on=("missing",)),),
            materialize=lambda batches: {},
        )
    assert missing.value.repair["error_code"] == "BUSINESS_PLAN_DEPENDENCY_MISSING"
    assert missing.value.repair["missing_dependencies"] == ["missing"]

    with pytest.raises(BusinessDeclarationError) as cycle:
        compile_business_plan(
            session,
            operation="audio.import",
            effects=(
                _effect("container", depends_on=("sound",)),
                _effect("sound", depends_on=("container",)),
            ),
            materialize=lambda batches: {},
        )
    assert cycle.value.repair["error_code"] == "BUSINESS_PLAN_DEPENDENCY_CYCLE"
    assert cycle.value.repair["cycle_candidates"] == ["container", "sound"]


def test_business_plan_rejects_request_for_another_operation_or_version() -> None:
    session = _session()

    with pytest.raises(BusinessDeclarationError) as mismatch:
        compile_business_plan(
            session,
            operation="audio.import",
            effects=(_effect("container"),),
            materialize=lambda batches: {
                "contract": "waapi-skill.operation-request/v1",
                "version": "2023.1",
                "operation": "object.set",
                "arguments": {"objects": []},
            },
        )
    assert mismatch.value.repair["error_code"] == "BUSINESS_PLAN_REQUEST_MISMATCH"
