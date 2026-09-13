from __future__ import annotations

from collections.abc import Sequence
import shlex
from pathlib import Path

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
    BusinessFileEvidence,
    BusinessPlanningDeadline,
    MAX_BUSINESS_FILE_BYTES,
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
    deadline: BusinessPlanningDeadline,
) -> dict[str, object]:
    deadline.checkpoint()
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


def _continuation(
    request: dict[str, object],
    request_digest: str,
    deadline: BusinessPlanningDeadline,
) -> dict[str, object]:
    deadline.checkpoint()
    assert request_digest
    gateway_argv = ["transaction-preview", "--draft", "od1"]
    full_argv = [
        "python",
        "skill/scripts/run.py",
        "gateway.py",
        *gateway_argv,
    ]
    return {
        "contract": "waapi-skill.gateway-next-command/v2",
        "gateway_argv": gateway_argv,
        "full_argv": full_argv,
        "shell_family": "posix-sh",
        "shell_command": shlex.join(full_argv),
        "copy_exactly": True,
        "copy_instruction": {
            "contract": "waapi-skill.gateway-command-copy-instruction/v2",
            "source_field": "shell_command",
            "action": "execute_verbatim_as_one_shell_tool_call",
        },
    }


def _materialize_audio_file(
    version: str,
    batches: Sequence[BusinessBatch],
    deadline: BusinessPlanningDeadline,
    path: Path,
) -> dict[str, object]:
    deadline.checkpoint()
    root = "Containers" if version == "2025.1" else "Actor-Mixer Hierarchy"
    return {
        "contract": "waapi-skill.operation-request/v1",
        "version": version,
        "operation": "audio.import",
        "arguments": {
            "imports": [
                {
                    "object_path": rf"\{root}\Default Work Unit\<Sound SFX>Rain_Bed",
                    "object_type": "Sound SFX",
                    "audio_file": str(path),
                    "import_language": "SFX",
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
        materialize=lambda batches, deadline: _materialize_audio_import(
            version, batches, deadline
        ),
        build_continuation=_continuation,
        file_evidence=(),
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
    assert compiled.continuation["copy_instruction"]["source_field"] == (
        "shell_command"
    )


def test_business_plan_preserves_gateway_order_for_dependency_free_siblings() -> None:
    session = _session()
    effects = (
        _effect("import:rifle-close"),
        _effect("import:rifle-tail"),
        _effect("import:rifle-mechanical"),
        _effect("import:shotgun-close"),
        _effect("import:shotgun-tail"),
        _effect("import:shotgun-mechanical"),
    )

    compiled = compile_business_plan(
        session,
        operation="audio.import",
        effects=effects,
        materialize=lambda batches, deadline: {
            "contract": "waapi-skill.operation-request/v1",
            "version": session.context.wwise_version,
            "operation": "audio.import",
            "arguments": {
                "imports": [
                    {
                        "object_path": (
                            r"\Actor-Mixer Hierarchy\Default Work Unit"
                            r"\<Sound SFX>Rain_Bed"
                        ),
                        "object_type": "Sound SFX",
                    }
                ]
            },
        },
        build_continuation=_continuation,
        file_evidence=(),
    )

    assert compiled.ordered_effect_ids == tuple(effect.effect_id for effect in effects)


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSIONS)
def test_business_plan_cycle_and_missing_dependencies_return_atomic_repair(
    version: str,
) -> None:
    session = _session(version)

    with pytest.raises(BusinessDeclarationError) as missing:
        compile_business_plan(
            session,
            operation="audio.import",
            effects=(_effect("sound", depends_on=("missing",)),),
            materialize=lambda batches, deadline: {},
            build_continuation=_continuation,
            file_evidence=(),
        )
    assert missing.value.repair["error_code"] == "BUSINESS_PLAN_DEPENDENCY_MISSING"
    assert missing.value.repair["missing_dependencies"] == ["missing"]
    assert missing.value.repair["draft_revision"] == session.revision

    with pytest.raises(BusinessDeclarationError) as cycle:
        compile_business_plan(
            session,
            operation="audio.import",
            effects=(
                _effect("container", depends_on=("sound",)),
                _effect("sound", depends_on=("container",)),
            ),
            materialize=lambda batches, deadline: {},
            build_continuation=_continuation,
            file_evidence=(),
        )
    assert cycle.value.repair["error_code"] == "BUSINESS_PLAN_DEPENDENCY_CYCLE"
    assert cycle.value.repair["cycle_candidates"] == ["container", "sound"]


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSIONS)
def test_business_plan_rejects_request_for_another_operation_or_version(
    version: str,
) -> None:
    session = _session(version)

    with pytest.raises(BusinessDeclarationError) as mismatch:
        compile_business_plan(
            session,
            operation="audio.import",
            effects=(_effect("container"),),
            materialize=lambda batches, deadline: {
                "contract": "waapi-skill.operation-request/v1",
                "version": "2023.1",
                "operation": "object.set",
                "arguments": {"objects": []},
            },
            build_continuation=_continuation,
            file_evidence=(),
        )
    assert mismatch.value.repair["error_code"] == "BUSINESS_PLAN_REQUEST_MISMATCH"


def test_business_effect_detaches_nested_adapter_inputs() -> None:
    fragment = {"rows": [{"value": -4.0}]}
    verifier = {"expected": {"value": -4.0}}
    effect = BusinessEffect.create(
        effect_id="sound",
        declaration_id="rain-bed",
        batch_key="audio.import",
        native_fragment=fragment,
        verifier_expectation=verifier,
        readable_lines=("音量：-4 dB",),
    )

    fragment["rows"][0]["value"] = 99.0
    verifier["expected"]["value"] = 99.0

    assert effect.native_fragment == {"rows": [{"value": -4.0}]}
    assert effect.verifier_expectation == {"expected": {"value": -4.0}}


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSIONS)
def test_business_plan_enforces_file_and_time_budgets(
    version: str,
    tmp_path: Path,
) -> None:
    session = _session(version)
    effects = (
        _effect("container"),
        _effect("sound", depends_on=("container",)),
        _effect("event", depends_on=("sound",), batch_key="event"),
    )
    with pytest.raises(BusinessDeclarationError) as oversized:
        compile_business_plan(
            session,
            operation="audio.import",
            effects=effects,
            materialize=lambda batches, deadline: _materialize_audio_import(
                version, batches, deadline
            ),
            build_continuation=_continuation,
            file_evidence=(
                BusinessFileEvidence.create(
                    path="/tmp/huge.wav",
                    size_bytes=MAX_BUSINESS_FILE_BYTES + 1,
                    sha256="a" * 64,
                ),
            ),
        )
    assert oversized.value.repair["error_code"] == "BUSINESS_FILE_LIMIT_EXCEEDED"

    media = tmp_path / "rain.wav"
    media.write_bytes(b"RIFF-test")
    with pytest.raises(BusinessDeclarationError) as missing_evidence:
        compile_business_plan(
            session,
            operation="audio.import",
            effects=effects,
            materialize=lambda batches, deadline: _materialize_audio_file(
                version,
                batches,
                deadline,
                media,
            ),
            build_continuation=_continuation,
            file_evidence=(),
        )
    assert missing_evidence.value.repair["error_code"] == (
        "BUSINESS_FILE_EVIDENCE_MISMATCH"
    )
    compiled_file = compile_business_plan(
        session,
        operation="audio.import",
        effects=effects,
        materialize=lambda batches, deadline: _materialize_audio_file(
            version,
            batches,
            deadline,
            media,
        ),
        build_continuation=_continuation,
        file_evidence=(
            BusinessFileEvidence.from_path(str(media)),
        ),
    )
    assert compiled_file.preview.detail["file_evidence"][0]["path"] == str(media)

    current_time = 0.0

    def timed_out_materializer(
        batches: Sequence[BusinessBatch],
        deadline: BusinessPlanningDeadline,
    ) -> dict[str, object]:
        nonlocal current_time
        current_time = 31.0
        deadline.checkpoint()
        raise AssertionError("deadline checkpoint must stop materialization")

    with pytest.raises(BusinessDeclarationError) as timed_out:
        compile_business_plan(
            session,
            operation="audio.import",
            effects=effects,
            materialize=timed_out_materializer,
            build_continuation=_continuation,
            file_evidence=(),
            clock=lambda: current_time,
        )
    assert timed_out.value.repair["error_code"] == "BUSINESS_PLANNING_TIMEOUT"


def test_business_plan_rejects_inconsistent_continuation_envelope() -> None:
    session = _session()
    effects = (
        _effect("container"),
        _effect("sound", depends_on=("container",)),
        _effect("event", depends_on=("sound",), batch_key="event"),
    )

    def inconsistent(
        request: dict[str, object],
        request_digest: str,
        deadline: BusinessPlanningDeadline,
    ) -> dict[str, object]:
        payload = _continuation(request, request_digest, deadline)
        payload["shell_command"] = "python wrong.py"
        return payload

    with pytest.raises(BusinessDeclarationError) as captured:
        compile_business_plan(
            session,
            operation="audio.import",
            effects=effects,
            materialize=lambda batches, deadline: _materialize_audio_import(
                "2022.1", batches, deadline
            ),
            build_continuation=inconsistent,
            file_evidence=(),
        )
    assert captured.value.repair["error_code"] == "BUSINESS_CONTINUATION_INVALID"


@pytest.mark.parametrize("version", SUPPORTED_WWISE_VERSIONS)
@pytest.mark.parametrize("tamper", (None, "runner", "revision", "absolute-binding", "cwd", "shell-suffix"))
def test_business_plan_accepts_only_exact_gateway_task_local_posix_continuation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, version: str, tamper: str | None,
) -> None:
    from tests.unit.test_transaction_gateway import waapi_gateway

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(waapi_gateway, "os", type("PosixOS", (), {"name": "posix"})())
    runner = tmp_path / ".agents/skills/waapi-skill/scripts/run.py"
    monkeypatch.setattr(waapi_gateway, "GATEWAY_RUNNER_PATH", runner)
    session = _session(version)
    effects = (
        _effect("container"),
        _effect("sound", depends_on=("container",)),
        _effect("event", depends_on=("sound",), batch_key="event"),
    )

    def continuation(request, request_digest, deadline):
        payload = waapi_gateway.transaction_next_command(
            "preview-from-draft", ["preview-from-draft", "od1-test", "--expected-revision", "7"]
        )
        if tamper == "runner":
            payload["shell_command"] = payload["shell_command"].replace("scripts/run.py", "scripts/other.py")
        elif tamper == "revision":
            payload["shell_command"] = payload["shell_command"].replace("--expected-revision 7", "--expected-revision 8")
        elif tamper == "absolute-binding":
            payload["full_argv"][1] = str(tmp_path / "elsewhere/scripts/run.py")
        elif tamper == "cwd":
            other = tmp_path / "other-workspace"
            other.mkdir()
            monkeypatch.chdir(other)
        elif tamper == "shell-suffix":
            payload["shell_command"] += " ; echo unsafe"
        return payload

    def compile_plan():
        return compile_business_plan(
            session, operation="audio.import", effects=effects,
            materialize=lambda batches, deadline: _materialize_audio_import(version, batches, deadline),
            build_continuation=continuation, file_evidence=(),
        )

    if tamper is not None:
        with pytest.raises(BusinessDeclarationError) as caught:
            compile_plan()
        assert caught.value.repair["error_code"] == "BUSINESS_CONTINUATION_INVALID"
        return
    result = compile_plan().preview.detail["continuation"]
    assert result["full_argv"][1] == str(runner)
    assert result["shell_command"] == (
        "python .agents/skills/waapi-skill/scripts/run.py gateway.py "
        "preview-from-draft od1-test --expected-revision 7"
    )
