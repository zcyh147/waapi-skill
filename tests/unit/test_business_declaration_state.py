from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

from wwise_waapi.business_declaration_state import (
    BusinessDeclarationSession,
    BusinessPreview,
)
from wwise_waapi.business_declarations import (
    BusinessContext,
    BusinessDeclarationError,
    NewDescendantTarget,
    SUPPORTED_WWISE_VERSIONS,
)
from wwise_waapi.operation_composer import operation_composer_digest
from wwise_waapi.operation_drafts import (
    OperationDraftInvalidTransition,
    OperationDraftRevisionConflict,
    OperationDraftStore,
)
from wwise_waapi.operation_registry import operation_request_schema_digest


PROJECT_ID = "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}"
PARENT_ID = "{11111111-1111-1111-1111-111111111111}"


def _context(
    task_authority: str = "da1-" + "1" * 40,
    version: str = "2022.1",
) -> BusinessContext:
    return BusinessContext.create(
        task_authority=task_authority,
        project_id=PROJECT_ID,
        project_path="/fixtures/SampleProject.wproj",
        wwise_version=version,
        wwise_build=f"{version}.19.8584",
    )


def _session(
    task_authority: str = "da1-" + "1" * 40,
    version: str = "2022.1",
) -> BusinessDeclarationSession:
    session = BusinessDeclarationSession.create(_context(task_authority, version))
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


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSIONS)
def test_business_session_round_trips_without_exposing_native_planning(
    version: str,
) -> None:
    session = _session(version=version)

    restored = BusinessDeclarationSession.from_dict(session.as_dict())

    assert restored.as_dict() == session.as_dict()
    assert restored.revision == 1
    declaration = restored.declarations[0]
    assert declaration.fields == {
        "media_file": "/tmp/rain.wav",
        "volume_db": -4.0,
    }
    assert "object_path" not in declaration.fields
    assert "object_type" not in declaration.fields
    assert "loop" not in declaration.fields


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSIONS)
def test_invalid_or_incomplete_declaration_is_atomic(version: str) -> None:
    session = _session(version=version)
    before = session.as_dict()

    with pytest.raises(BusinessDeclarationError) as captured:
        session.with_new_declaration(
            declaration_id="broken",
            target=NewDescendantTarget(
                parent_handle=session.declarations[0].target.parent_handle,
                name="",
                kind="sound-sfx",
            ),
            fields={"volume_db": -4.0},
        )

    assert captured.value.repair["error_code"] == "DECLARATION_INCOMPLETE"
    assert captured.value.repair["missing_fields"] == ["name"]
    assert captured.value.repair["draft_revision"] == session.revision
    assert session.as_dict() == before

    with pytest.raises(BusinessDeclarationError) as invalid_value:
        session.revise_declaration(
            declaration_id="rain-bed",
            fields={"volume_db": float("nan")},
        )
    assert invalid_value.value.repair["error_code"] == (
        "DECLARATION_FIELD_VALUE_INVALID"
    )
    assert invalid_value.value.repair["draft_revision"] == session.revision
    assert session.as_dict() == before

    with pytest.raises(BusinessDeclarationError) as stale_parent:
        session.with_new_declaration(
            declaration_id="stale",
            target=NewDescendantTarget(
                parent_handle="boh1-" + "0" * 32,
                name="Stale",
                kind="sound-sfx",
            ),
            fields={},
        )
    assert stale_parent.value.repair["error_code"] == "OBJECT_HANDLE_NOT_AVAILABLE"
    assert stale_parent.value.repair["draft_revision"] == session.revision
    assert session.as_dict() == before


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSIONS)
def test_revision_invalidates_active_preview_and_preserves_audit(
    version: str,
) -> None:
    session = _session(version=version).with_preview(
        BusinessPreview.create(
            source_revision=1,
            readable_lines=(
                "对象：Rain_Bed",
                "类型：Sound SFX",
                "音量：-4 dB",
            ),
            detail={"plan_digest": "a" * 64, "native_call_count": 1},
        )
    )
    assert session.active_preview is not None

    revised = session.revise_declaration(
        declaration_id="rain-bed",
        fields={"media_file": "/tmp/rain.wav", "volume_db": -6.0},
    )

    assert revised.revision == 2
    assert revised.active_preview is None
    assert len(revised.preview_audit) == 1
    assert revised.preview_audit[0]["preview"]["source_revision"] == 1
    assert (
        revised.preview_audit[0]["preview"]["preview_digest"]
        == session.active_preview.preview_digest
    )
    assert revised.preview_audit[0]["preview"]["readable_lines"] == [
        "对象：Rain_Bed",
        "类型：Sound SFX",
        "音量：-4 dB",
    ]
    assert session.active_preview is not None


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSIONS)
def test_batch_settings_and_declaration_removal_are_atomic_revisions(
    version: str,
) -> None:
    session = _session(version=version)

    configured = session.with_settings(
        {
            "mode": "create",
            "add_to_source_control": True,
            "defaults": {"volume_db": -4.0},
        }
    )
    assert configured.revision == 2
    assert configured.settings == {
        "add_to_source_control": True,
        "defaults": {"volume_db": -4.0},
        "mode": "create",
    }

    removed = configured.remove_declaration("rain-bed")
    assert removed.revision == 3
    assert removed.declarations == ()
    assert removed.settings == configured.settings

    before = removed.as_dict()
    with pytest.raises(BusinessDeclarationError) as missing:
        removed.remove_declaration("rain-bed")
    assert missing.value.repair["error_code"] == "DECLARATION_NOT_AVAILABLE"
    assert missing.value.repair["draft_revision"] == removed.revision
    assert removed.as_dict() == before


def test_handle_binding_is_a_fact_preserving_durable_transition() -> None:
    context = _context()
    session = BusinessDeclarationSession.create(context)
    previous = session.as_dict()
    handles = type(session.handles).from_dict(session.handles.as_dict())
    bound = handles.bind_object(
        object_id=PARENT_ID,
        name="Weather",
        object_type="ActorMixer",
        path=r"\Actor-Mixer Hierarchy\Default Work Unit\Weather",
    )

    candidate = session.with_handle_registry(handles)

    BusinessDeclarationSession.validate_transition(
        previous,
        candidate,
        event_type="handles.bound",
    )
    assert candidate.revision == 0
    assert candidate.handles.resolve_object(bound.handle) == bound

    with pytest.raises(ValueError, match="handle transition"):
        BusinessDeclarationSession.validate_transition(
            previous,
            session,
            event_type="handles.bound",
        )


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSIONS)
def test_operation_draft_business_update_is_durable_atomic_and_cas_bound(
    tmp_path: Path,
    version: str,
) -> None:
    store = OperationDraftStore(tmp_path / "state")
    schema_digest = operation_request_schema_digest("audio.import", version)
    composer_digest = operation_composer_digest("audio.import", version)
    started = store.start(
        operation="audio.import",
        version=version,
        schema_digest=schema_digest,
        composer_digest=composer_digest,
    )
    context = _context(started.task_authority, version)
    record_path = store.records_dir / f"{started.draft_id}.json"
    before = record_path.read_bytes()

    def reject(session: BusinessDeclarationSession) -> BusinessDeclarationSession:
        raise BusinessDeclarationError(
            {
                "contract": "waapi-skill.business-repair/v1",
                "error_code": "DECLARATION_INCOMPLETE",
                "field": "name",
                "draft_changed": False,
                "action": "provide the missing fact",
            }
        )

    with pytest.raises(BusinessDeclarationError):
        store.apply_business_update(
            started.draft_id,
            task_authority=started.task_authority,
            expected_revision=1,
            schema_digest=schema_digest,
            composer_digest=composer_digest,
            context=context,
            update=reject,
            event_type="declaration.added",
        )
    assert record_path.read_bytes() == before

    updated = store.apply_business_update(
        started.draft_id,
        task_authority=started.task_authority,
        expected_revision=1,
        schema_digest=schema_digest,
        composer_digest=composer_digest,
        context=context,
        update=lambda session: _add_weather(session),
        event_type="declaration.added",
    )
    assert updated.revision == 2
    assert updated.check is None
    assert updated.seal is None

    before_malicious_preview = record_path.read_bytes()

    def mutate_then_preview(
        current: BusinessDeclarationSession,
    ) -> BusinessDeclarationSession:
        fields = current.declarations[0].fields
        assert isinstance(fields, dict)
        fields["volume_db"] = 99.0
        return current.with_preview(
            BusinessPreview.create(
                source_revision=current.revision,
                readable_lines=("对象：Rain_Bed", "音量：99 dB"),
                detail={"plan_digest": "f" * 64},
            )
        )

    with pytest.raises(OperationDraftInvalidTransition):
        store.apply_business_update(
            started.draft_id,
            task_authority=started.task_authority,
            expected_revision=2,
            schema_digest=schema_digest,
            composer_digest=composer_digest,
            context=context,
            update=mutate_then_preview,
            event_type="preview.recorded",
        )
    assert record_path.read_bytes() == before_malicious_preview

    restored = store.inspect(started.draft_id, task_authority=started.task_authority)
    assert restored.composition is not None
    session = BusinessDeclarationSession.from_dict(
        restored.composition["business_session"]
    )
    assert session.declarations[0].declaration_id == "rain-bed"

    previewed = store.apply_business_update(
        started.draft_id,
        task_authority=started.task_authority,
        expected_revision=2,
        schema_digest=schema_digest,
        composer_digest=composer_digest,
        context=context,
        update=lambda current: current.with_preview(
            BusinessPreview.create(
                source_revision=current.revision,
                readable_lines=("对象：Rain_Bed", "音量：-4 dB"),
                detail={"plan_digest": "a" * 64},
            )
        ),
        event_type="preview.recorded",
    )
    assert previewed.revision == 3

    revised = store.apply_business_update(
        started.draft_id,
        task_authority=started.task_authority,
        expected_revision=3,
        schema_digest=schema_digest,
        composer_digest=composer_digest,
        context=context,
        update=lambda current: current.revise_declaration(
            declaration_id="rain-bed",
            fields={"media_file": "/tmp/rain.wav", "volume_db": -6.0},
        ),
        event_type="declaration.revised",
    )
    durable_revised = BusinessDeclarationSession.from_dict(
        revised.composition["business_session"]
    )
    assert durable_revised.active_preview is None
    assert len(durable_revised.preview_audit) == 1

    with pytest.raises(OperationDraftRevisionConflict):
        store.apply_business_update(
            started.draft_id,
            task_authority=started.task_authority,
            expected_revision=1,
            schema_digest=schema_digest,
            composer_digest=composer_digest,
            context=context,
            update=lambda current: current,
                event_type="declaration.revised",
        )


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSIONS)
def test_business_updates_serialize_concurrent_writers(
    tmp_path: Path,
    version: str,
) -> None:
    state_dir = tmp_path / "state"
    store = OperationDraftStore(state_dir)
    schema_digest = operation_request_schema_digest("audio.import", version)
    composer_digest = operation_composer_digest("audio.import", version)
    started = store.start(
        operation="audio.import",
        version=version,
        schema_digest=schema_digest,
        composer_digest=composer_digest,
    )
    context = _context(started.task_authority, version)
    barrier = Barrier(2)

    def writer() -> str:
        local = OperationDraftStore(state_dir)
        barrier.wait()
        try:
            local.apply_business_update(
                started.draft_id,
                task_authority=started.task_authority,
                expected_revision=1,
                schema_digest=schema_digest,
                composer_digest=composer_digest,
                context=context,
                update=_add_weather,
                event_type="declaration.added",
            )
        except OperationDraftRevisionConflict:
            return "conflict"
        return "committed"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = sorted(executor.map(lambda _: writer(), range(2)))

    assert outcomes == ["committed", "conflict"]
    record = store.inspect(started.draft_id, task_authority=started.task_authority)
    assert record.revision == 2


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSIONS)
def test_business_update_storage_crash_preserves_previous_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    version: str,
) -> None:
    store = OperationDraftStore(tmp_path / "state")
    schema_digest = operation_request_schema_digest("audio.import", version)
    composer_digest = operation_composer_digest("audio.import", version)
    started = store.start(
        operation="audio.import",
        version=version,
        schema_digest=schema_digest,
        composer_digest=composer_digest,
    )
    path = store.records_dir / f"{started.draft_id}.json"
    before = path.read_bytes()

    def crash(*args: object, **kwargs: object) -> None:
        raise OSError("simulated publish crash")

    monkeypatch.setattr(store, "_replace_record", crash)
    with pytest.raises(OSError, match="simulated publish crash"):
        store.apply_business_update(
            started.draft_id,
            task_authority=started.task_authority,
            expected_revision=1,
            schema_digest=schema_digest,
            composer_digest=composer_digest,
            context=_context(started.task_authority, version),
            update=_add_weather,
            event_type="declaration.added",
        )

    assert path.read_bytes() == before


def _add_weather(session: BusinessDeclarationSession) -> BusinessDeclarationSession:
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
