from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import uuid
import xml.etree.ElementTree as ET
from collections.abc import Mapping, Sequence
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tests.semantic.support import codex_cli_runtime_v3 as cli_runtime
from tests.semantic.support.codex_cli_runtime_v3 import (
    CLI_APIS,
    CliDispatchEvidence,
    CliEventRecord,
    CliLifecyclePlan,
    CliObjectRecord,
    CliRuntimeError,
    CliRuntimePlan,
    ClosedDirectCliBackend,
    PreparedCliRuntime,
    ProcessPhaseEvidence,
    SetupAudioImport,
    _assert_backend_context,
    _localize_waapi_host_path,
    all_cli_scenarios,
    build_cli_runtime_plan,
    materialize_cli_runtime,
)
from tests.semantic.support.codex_eval_bundle_v3 import (
    OnlineScenario,
    load_eval_bundle_v3,
)
from tests.semantic.support.codex_prompt_provenance_v3 import (
    write_prompt_provenance,
)
from wwise_waapi.builders.schema import validate_semantic_payload
from wwise_waapi.operation_soundbank import parse_soundbank_definition_file


REPO_ROOT = Path(__file__).resolve().parents[2]
SUITE = REPO_ROOT / "skills" / "waapi-skill" / "evals" / "suite-v3.json"


def _guid(key: str) -> str:
    return "{" + str(uuid.uuid5(uuid.NAMESPACE_URL, "waapi-cli-v3:" + key)).upper() + "}"


class FakeBackend:
    def __init__(self, project_path: Path) -> None:
        self.project_path = project_path
        self.objects: dict[str, CliObjectRecord] = {}
        self.localized_objects: dict[tuple[str, str], CliObjectRecord] = {}
        self.events: dict[str, CliEventRecord] = {}
        self.inclusions: dict[str, tuple[str, ...]] = {}
        self.audio_imports: list[SetupAudioImport] = []
        self.audio_import_results: list[tuple[SetupAudioImport, str]] = []
        self.localized_reads: list[tuple[str, str]] = []
        self.saved = 0
        for path, object_type in (
            (r"\Actor-Mixer Hierarchy", "PhysicalFolder"),
            (r"\Actor-Mixer Hierarchy\Default Work Unit", "WorkUnit"),
            (r"\Events", "PhysicalFolder"),
            (r"\Events\Default Work Unit", "WorkUnit"),
            (r"\SoundBanks", "PhysicalFolder"),
            (r"\SoundBanks\Default Work Unit", "WorkUnit"),
            (r"\Master-Mixer Hierarchy", "PhysicalFolder"),
            (r"\Master-Mixer Hierarchy\Default Work Unit", "WorkUnit"),
            (
                r"\Master-Mixer Hierarchy\Default Work Unit\Master Audio Bus",
                "Bus",
            ),
        ):
            self._put(path, object_type)

    def get_context(self) -> Mapping[str, Any]:
        return {
            "info": {
                "version": {
                    "year": 2022,
                    "major": 1,
                    "minor": 19,
                    "build": 8584,
                }
            },
            "project": {"path": str(self.project_path)},
        }

    def read_object(self, path: str) -> CliObjectRecord | None:
        return self.objects.get(path)

    def read_localized_object(
        self,
        path: str,
        *,
        language: str,
    ) -> CliObjectRecord | None:
        self.localized_reads.append((path, language))
        return self.localized_objects.get((path, language))

    def read_event(self, path: str) -> CliEventRecord | None:
        return self.events.get(path)

    def ensure_object(self, *, path: str, object_type: str) -> CliObjectRecord:
        existing = self.objects.get(path)
        if existing is not None:
            return existing
        return self._put(path, object_type)

    def import_audio(self, request: SetupAudioImport) -> CliObjectRecord:
        self.audio_imports.append(request)
        existing = self.objects.get(request.object_path)
        originals_kind = "SFX" if request.language == "SFX" else "Voices"
        copied_source = (
            self.project_path.parent
            / "Originals"
            / originals_kind
            / request.language
            / request.audio_file.name
        )
        copied_source.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(request.audio_file, copied_source)
        if request.import_operation == "replaceExisting" or existing is None:
            record = CliObjectRecord(
                path=request.object_path,
                object_id=_guid(request.object_path + ":" + str(uuid.uuid4())),
                object_type="Sound",
                name=request.object_path.rsplit("\\", 1)[-1],
                language=request.language,
                source_path=str(copied_source),
                source_sha256=hashlib.sha256(copied_source.read_bytes()).hexdigest(),
                notes=request.notes,
                short_id=int(hashlib.sha256(request.object_path.encode()).hexdigest()[:8], 16),
            )
            self.objects[request.object_path] = record
        else:
            record = CliObjectRecord(
                path=existing.path,
                object_id=existing.object_id,
                object_type="Sound",
                name=existing.name,
                language=request.language,
                source_path=str(copied_source),
                source_sha256=hashlib.sha256(copied_source.read_bytes()).hexdigest(),
                notes=existing.notes if request.notes is None else request.notes,
                short_id=existing.short_id,
            )
        self.localized_objects[(request.object_path, request.language)] = record
        if request.event_path:
            event_id = _guid(request.event_path)
            self._put(request.event_path, "Event", object_id=event_id)
            self.events[request.event_path] = CliEventRecord(
                path=request.event_path,
                object_id=event_id,
                action_ids=(_guid(request.event_path + ":action"),),
                target_ids=(record.object_id,),
                action_types=(1,),
            )
        self.audio_import_results.append((request, record.object_id))
        return record

    def replace_soundbank_inclusions(
        self,
        *,
        soundbank_path: str,
        event_paths: Sequence[str],
        filters: Sequence[str],
    ) -> None:
        assert self.objects[soundbank_path].object_type == "SoundBank"
        assert tuple(filters) == ("events", "structures", "media")
        self.inclusions[soundbank_path] = tuple(event_paths)

    def save_project(self) -> None:
        self.saved += 1
        marker = self.project_path.parent / "FakeSetup.wwu"
        marker.write_text(
            f'<WwiseDocument WwiseVersion="v2022.1.0"><Setup Count="{self.saved}"/></WwiseDocument>',
            encoding="utf-8",
        )

    def apply_tab_business(self, runtime: PreparedCliRuntime) -> None:
        before = runtime._tab_before_by_path
        assert before is not None
        wav_by_key = {
            str(row["key"]): runtime.plan.asset_root / "wav" / str(row["name"])
            for row in runtime.plan.asset_spec["assets"]["wav"]["files"]
        }
        for row in runtime.plan.asset_spec["expected"]["objects"]:
            path = str(row["path"])
            old = before[path]
            policy = str(row["guid_policy"])
            if policy == "preserved":
                assert old is not None
                object_id = old.object_id
            else:
                object_id = _guid(path + ":after")
            wav = wav_by_key[str(row["source_key"])]
            record = CliObjectRecord(
                path=path,
                object_id=object_id,
                object_type="Sound",
                name=path.rsplit("\\", 1)[-1],
                language=str(row["language"]),
                source_path=str(wav),
                source_sha256=hashlib.sha256(wav.read_bytes()).hexdigest(),
                notes=None,
                short_id=123,
            )
            self.objects[path] = record
            self.localized_objects[(path, str(row["language"]))] = record
            event_name = row.get("event")
            if event_name:
                event_path = rf"\Events\Default Work Unit\{event_name}"
                event_id = _guid(event_path)
                self._put(event_path, "Event", object_id=event_id)
                self.events[event_path] = CliEventRecord(
                    path=event_path,
                    object_id=event_id,
                    action_ids=(_guid(event_path + ":action"),),
                    target_ids=(object_id,),
                    action_types=(1,),
                )
        (runtime.plan.project_root / "Imported.wwu").write_text(
            '<WwiseDocument WwiseVersion="v2022.1.0"><Imported/></WwiseDocument>',
            encoding="utf-8",
        )

    def _put(
        self,
        path: str,
        object_type: str,
        *,
        object_id: str | None = None,
    ) -> CliObjectRecord:
        record = CliObjectRecord(
            path=path,
            object_id=object_id or _guid(path),
            object_type=object_type,
            name=path.rsplit("\\", 1)[-1],
        )
        self.objects[path] = record
        if object_type == "Event":
            self.events.setdefault(
                path,
                CliEventRecord(
                    path=path,
                    object_id=record.object_id,
                    action_ids=(),
                    target_ids=(),
                    action_types=(),
                ),
            )
        return record


def _suite_cli_cases() -> tuple[OnlineScenario, ...]:
    return all_cli_scenarios(load_eval_bundle_v3(SUITE).scenarios)


def _absolute_strings(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,) if value.startswith("/") else ()
    if isinstance(value, Mapping):
        return tuple(
            item
            for child in value.values()
            for item in _absolute_strings(child)
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return tuple(item for child in value for item in _absolute_strings(child))
    return ()


def _make_console(tmp_path: Path) -> Path:
    path = tmp_path / "WwiseConsole"
    path.write_text("#!/bin/sh\nexit 99\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def _make_nonmigration_project(root: Path) -> tuple[Path, Path]:
    source = root / "immutable-template"
    project_root = root / "case" / "project"
    source.mkdir(parents=True)
    project_root.mkdir(parents=True)
    payload = '<WwiseDocument WwiseVersion="v2022.1.0" WwiseBuild="8584"><Project Name="Fixture" ID="{11111111-1111-1111-1111-111111111111}"/></WwiseDocument>'
    (source / "SampleProject.wproj").write_text(payload, encoding="utf-8")
    project = project_root / "SampleProject.wproj"
    project.write_text(payload, encoding="utf-8")
    return source, project


def _build(
    case: OnlineScenario,
    root: Path,
) -> tuple[CliRuntimePlan, PreparedCliRuntime, FakeBackend | None]:
    case_root = root / "case"
    if case.api == "ak.wwise.cli.migrate":
        project = case_root / "project" / "SampleProject.wproj"
        plan = build_cli_runtime_plan(
            case,
            version="2022.1",
            case_root=case_root,
            project_path=project,
        )
    else:
        source, project = _make_nonmigration_project(root)
        plan = build_cli_runtime_plan(
            case,
            version="2022.1",
            case_root=case_root,
            project_path=project,
            source_template_root=source,
        )
    runtime = materialize_cli_runtime(plan)
    backend = FakeBackend(plan.project_path) if plan.requires_setup else None
    return plan, runtime, backend


def _phase_evidence(
    spec,
    *,
    returncode: int | None = 0,
    natural_exit_before_shutdown: bool = False,
) -> ProcessPhaseEvidence:
    return ProcessPhaseEvidence(
        role=spec.role,
        argv=spec.argv,
        cwd=spec.cwd,
        shell=False,
        started=True,
        ready=True,
        process_exited=True,
        open_project_path=spec.project_path,
        returncode=returncode,
        natural_exit_before_shutdown=natural_exit_before_shutdown,
        runner_shutdown_requested=not natural_exit_before_shutdown,
    )


def _seal(
    runtime: PreparedCliRuntime,
    backend: FakeBackend | None,
    console: Path,
    port_base: int,
) -> CliLifecyclePlan:
    lifecycle = runtime.plan.lifecycle_plan(
        console_path=console,
        business_port=port_base,
        setup_port=port_base + 1 if runtime.plan.requires_setup else None,
        oracle_port=port_base + 2 if runtime.plan.requires_oracle else None,
    )
    if backend is not None:
        runtime.prepare_setup(backend)
        assert lifecycle.setup is not None
        runtime.seal_before(
            lifecycle=lifecycle,
            setup_evidence=_phase_evidence(lifecycle.setup),
        )
    else:
        runtime.seal_before(lifecycle=lifecycle)
    return lifecycle


def _dispatch(case: OnlineScenario, *, disconnect: bool = False) -> CliDispatchEvidence:
    return CliDispatchEvidence(
        api=case.api,
        primary_dispatch_count=1,
        dispatch_started=True,
        dispatch_completed=not disconnect,
        gateway_verify_state=None if disconnect else "verified",
        process_result=0,
        connection_lost=disconnect,
        connection_lost_after_dispatch=disconnect,
        stdout="completed",
        stderr="",
    )


def _write_riff(path: Path, marker: str = "new") -> None:
    payload = marker.encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"RIFF" + len(payload).to_bytes(4, "little") + b"WAVE" + payload)


def _write_bank(path: Path, marker: str = "new") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"BKHD" + marker.encode())


def _write_soundbanks_info(runtime: PreparedCliRuntime) -> None:
    spec = runtime.plan.asset_spec
    platform = str(spec["request"]["platforms"][0])
    root = ET.Element("SoundBanksInfo", Platform=platform)
    banks = ET.SubElement(root, "SoundBanks")
    artifacts = spec["expected"]["bank_artifacts"]
    for manifest_bank in spec["fixture_manifest"]["soundbanks"]:
        name = str(manifest_bank["name"])
        languages = {
            str(row["language"]) if row["language"] is not None else "SFX"
            for row in artifacts
            if row["bank"] == name and row["platform"] == platform
        }
        if not languages:
            languages = {"SFX"}
        for language in sorted(languages):
            bank = ET.SubElement(
                banks,
                "SoundBank",
                Type="User",
                Language=language,
            )
            ET.SubElement(bank, "ShortName").text = name
            relative = f"{language}/{name}.bnk" if language != "SFX" else f"{name}.bnk"
            ET.SubElement(bank, "Path").text = relative
            media_root = ET.SubElement(bank, "Media")
            for media in manifest_bank["media"]:
                if str(media["language"]) != language:
                    continue
                media_file = ET.SubElement(
                    media_root,
                    "File",
                    Language=language,
                )
                ET.SubElement(media_file, "ShortName").text = str(
                    media["relative_wav"]
                )
            event_root = ET.SubElement(bank, "Events")
            for event in manifest_bank["events"]:
                ET.SubElement(event_root, "Event", Name=str(event["name"]))
    path = runtime.plan.io_root / "SoundbanksInfo.xml"
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def _apply_success(
    runtime: PreparedCliRuntime,
    backend: FakeBackend | None,
) -> FakeBackend | None:
    operation = runtime.plan.operation
    if operation == "convertExternalSource":
        for output in runtime.expected_outputs:
            _write_riff(output.path, output.business_name)
        return None
    if operation == "generateSoundbank":
        rebuild_seeds = runtime.plan.asset_spec["fixture_manifest"].get(
            "rebuild_seeds"
        )
        if rebuild_seeds is not None:
            cache_binding = runtime.plan.asset_spec["request"]["path_bindings"]["cache"]
            cache_root = runtime.root_bindings[str(cache_binding["root_key"])]
            cache_base = cache_root / str(cache_binding["relative_path"])
            cache_seed = cache_base / str(rebuild_seeds["cache"]["relative_path"])
            cache_seed.unlink()
        for output in runtime.expected_outputs:
            if output.path.suffix.casefold() == ".bnk":
                _write_bank(output.path, output.business_name)
            else:
                output.path.parent.mkdir(parents=True, exist_ok=True)
                output.path.write_text("# generated ids\n", encoding="utf-8")
        _write_soundbanks_info(runtime)
        return None
    if operation == "tabDelimitedImport":
        assert backend is not None
        backend.apply_tab_business(runtime)
        return backend
    if operation == "migrate":
        document = ET.parse(runtime.plan.project_path)
        document.getroot().set("WwiseVersion", "v2022.1.0")
        document.getroot().set("WwiseBuild", "8584")
        document.write(runtime.plan.project_path, encoding="utf-8", xml_declaration=True)
        return FakeBackend(runtime.plan.project_path)
    raise AssertionError(operation)


def test_exact_review_set_has_five_cases_per_cli_api() -> None:
    cases = _suite_cli_cases()
    assert len(cases) == 20
    assert {api: sum(case.api == api for case in cases) for api in CLI_APIS} == {
        api: 5 for api in CLI_APIS
    }


@pytest.mark.parametrize("case", _suite_cli_cases(), ids=lambda case: case.id)
def test_all_twenty_cases_materialize_exact_waapi_call_and_three_phase_contract(
    tmp_path: Path,
    case: OnlineScenario,
) -> None:
    plan, runtime, backend = _build(case, tmp_path)
    console = _make_console(tmp_path)
    lifecycle = _seal(runtime, backend, console, 21000)

    request = runtime.operation_request()
    assert request["operation"] == "waapi.call"
    assert request["version"] == "2022.1"
    assert request["arguments"]["api"] == case.api
    assert request["arguments"]["options"] == {}
    if plan.operation in {"tabDelimitedImport", "migrate"}:
        assert request["arguments"]["io_root"] == str(plan.project_path.parent)
    else:
        write_paths = _write_paths(request["arguments"]["args"], plan.operation)
        assert request["arguments"]["io_root"] == os.path.commonpath(write_paths)
    provenance = runtime.request_provenance()
    assert set(provenance) == {
        "/contract",
        "/version",
        "/operation",
        "/arguments/api",
        "/arguments/options",
        "/arguments/io_root",
        *(f"/arguments/args/{field}" for field in request["arguments"]["args"]),
    }
    assert request["arguments"]["args"]["project"] == str(plan.project_path)
    assert all(
        plan.case_root == Path(value).resolve()
        or plan.case_root in Path(value).resolve().parents
        for value in _absolute_strings(request["arguments"])
    )
    assert not {
        "custom-global-closing-cmd",
        "custom-global-opening-cmd",
        "custom-post-gen-cmd",
        "custom-pre-gen-cmd",
    }.intersection(request["arguments"]["args"])
    schema_result = validate_semantic_payload(
        case.api,
        request["arguments"]["args"],
        request["arguments"]["options"],
        version="2022.1",
    )
    assert schema_result.uri == case.api
    assert schema_result.version == "2022.1"
    protocol = runtime.gateway_protocol()
    if runtime.plan.business_disconnect_may_occur:
        assert protocol.turn_prefix_counts == (2, 5)
        assert [step.subcommand for step in protocol.steps] == [
            "operation-schema",
            "preview",
            "transaction-show",
            "confirm",
            "execute",
        ]
        assert protocol.steps[-1].terminal_execute is True
    else:
        assert protocol.turn_prefix_counts == (2, 6)
        assert [step.subcommand for step in protocol.steps] == [
            "operation-schema",
            "preview",
            "transaction-show",
            "confirm",
            "execute",
            "verify",
        ]
    assert runtime.render_prompt() == case.render_prompt(runtime.visible_values)

    assert lifecycle.business.project_path == str(plan.business_server_project_path)
    assert str(plan.business_server_project_path) in lifecycle.business.argv
    assert plan.business_server_project_path != plan.project_path
    assert plan.business_server_project_path.parent.name == "business-host"
    assert runtime.lifecycle_contract["business_server_project"] == str(
        plan.business_server_project_path
    )
    assert lifecycle.business.argv[1] == "waapi-server"
    assert lifecycle.business.argv[-2:] == ("--http-port", "0")
    assert lifecycle.setup is not None if plan.requires_setup else lifecycle.setup is None
    assert lifecycle.oracle is not None if plan.requires_oracle else lifecycle.oracle is None
    if lifecycle.setup:
        assert lifecycle.setup.project_path == str(plan.project_path)
    if lifecycle.oracle:
        assert lifecycle.oracle.project_path == str(plan.project_path)


def test_migration_lifecycle_rejects_business_evidence_that_preopened_target(
    tmp_path: Path,
) -> None:
    case = next(case for case in _suite_cli_cases() if case.id == "O22-CLI-MIGRATE-01")
    _, runtime, _ = _build(case, tmp_path)
    lifecycle = _seal(runtime, None, _make_console(tmp_path), 29000)

    assert lifecycle.business.project_path != str(runtime.plan.project_path)
    invalid = ProcessPhaseEvidence(
        role="business",
        argv=lifecycle.business.argv,
        cwd=lifecycle.business.cwd,
        shell=False,
        started=True,
        ready=True,
        process_exited=True,
        open_project_path=str(runtime.plan.project_path),
    )
    assert "business opened the wrong project" in lifecycle.business.validate_evidence(invalid)


def test_lifecycle_rejects_a_business_control_project_that_is_the_target(
    tmp_path: Path,
) -> None:
    case = next(case for case in _suite_cli_cases() if case.id == "O22-CLI-MIGRATE-01")
    plan, _runtime, _ = _build(case, tmp_path)
    invalid = replace(plan, business_server_project_path=plan.project_path)

    with pytest.raises(CliRuntimeError, match="control project must differ from target"):
        invalid.lifecycle_plan(
            console_path=_make_console(tmp_path),
            business_port=29500,
            oracle_port=29501,
        )


def test_setup_context_requires_exact_project_path_before_fixture_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = next(case for case in _suite_cli_cases() if case.id == "O22-CLI-TAB-IMPORT-01")
    _, runtime, backend = _build(case, tmp_path)
    assert backend is not None
    context = backend.get_context()
    monkeypatch.setattr(
        backend,
        "get_context",
        lambda: {"info": context["info"], "project": {}},
    )

    with pytest.raises(
        CliRuntimeError,
        match="backend context lacks a usable project path",
    ):
        runtime.prepare_setup(backend)

    assert backend.audio_imports == []
    assert backend.saved == 0


def _write_paths(args: Mapping[str, Any], operation: str) -> list[str]:
    fields = (
        ("output",)
        if operation == "convertExternalSource"
        else ("soundbank-path", "cache", "root-output-path")
    )
    paths: list[str] = []
    for field in fields:
        value = args[field]
        if isinstance(value, str):
            paths.append(value)
        elif len(value) == 2 and all(isinstance(item, str) for item in value):
            paths.append(value[1])
        else:
            paths.extend(str(row[1]) for row in value)
    return paths


@pytest.mark.parametrize("case", _suite_cli_cases(), ids=lambda case: case.id)
def test_all_twenty_case_specific_business_oracles_accept_exact_success_state(
    tmp_path: Path,
    case: OnlineScenario,
) -> None:
    _, runtime, setup_backend = _build(case, tmp_path)
    lifecycle = _seal(runtime, setup_backend, _make_console(tmp_path), 21500)
    oracle_backend = _apply_success(runtime, setup_backend)
    disconnect = False
    kwargs: dict[str, Any] = {}
    if runtime.plan.requires_oracle:
        assert lifecycle.oracle is not None
        assert oracle_backend is not None
        kwargs = {
            "oracle_backend": oracle_backend,
            "oracle_evidence": _phase_evidence(lifecycle.oracle),
        }
    result = runtime.verify_after(
        dispatch=_dispatch(case, disconnect=disconnect),
        lifecycle=lifecycle,
        business_evidence=_phase_evidence(lifecycle.business),
        **kwargs,
    )
    result.assert_passed()


def test_cli_platform_mappings_use_reflected_pair_shapes(tmp_path: Path) -> None:
    cases = {case.id: case for case in _suite_cli_cases()}
    _, single, _ = _build(
        cases["O22-CLI-CONVERT-EXTERNAL-01"],
        tmp_path / "convert-single",
    )
    console = _make_console(tmp_path)
    _seal(single, None, console, 21900)
    request = single.operation_request()
    assert request["arguments"]["args"]["output"] == [
        "Windows",
        str(single.plan.io_root / "output"),
    ]
    assert request["arguments"]["io_root"] == str(single.plan.io_root / "output")

    _, shared, _ = _build(
        cases["O22-CLI-CONVERT-EXTERNAL-02"],
        tmp_path / "convert-shared",
    )
    _seal(shared, None, console, 21925)
    shared_request = shared.operation_request()
    assert shared_request["arguments"]["args"]["source-file"] == str(
        shared.plan.asset_root / "manifests" / "dialogue_shared.wsources"
    )
    assert shared_request["arguments"]["io_root"] == str(shared.plan.io_root)

    _, platform_specific, _ = _build(
        cases["O22-CLI-CONVERT-EXTERNAL-03"],
        tmp_path / "convert-platform-specific",
    )
    _seal(platform_specific, None, console, 21950)
    platform_request = platform_specific.operation_request()
    assert platform_request["arguments"]["args"]["source-by-platform"] == [
        [
            "Windows",
            str(
                platform_specific.plan.asset_root
                / "manifests"
                / "windows_only.wsources"
            ),
        ],
        [
            "Mac",
            str(
                platform_specific.plan.asset_root
                / "manifests"
                / "mac_only.wsources"
            ),
        ],
    ]
    assert platform_request["arguments"]["io_root"] == str(
        platform_specific.plan.io_root
    )

    _, convert, _ = _build(cases["O22-CLI-CONVERT-EXTERNAL-04"], tmp_path / "convert")
    _seal(convert, None, console, 22000)
    convert_request = convert.operation_request()
    args = convert_request["arguments"]["args"]
    union = str(convert.plan.asset_root / "manifests" / "bulk_union.wsources")
    assert args["source-file"] == union
    assert "source-by-platform" not in args
    assert args["output"] == [
        ["Windows", str(convert.plan.io_root / "windows")],
        ["Mac", str(convert.plan.io_root / "mac")],
    ]
    assert convert.visible_values["source_list_path"] == union
    assert convert_request["arguments"]["io_root"] == str(convert.plan.io_root)

    _, generate, backend = _build(cases["O22-CLI-GENERATE-BANK-01"], tmp_path / "generate")
    _seal(generate, backend, console, 22100)
    args = generate.operation_request()["arguments"]["args"]
    assert args["soundbank-path"] == [
        ["Windows", str(generate.plan.io_root / "output" / "Windows")],
        ["Mac", str(generate.plan.io_root / "output" / "Mac")],
    ]


def test_single_platform_convert_provenance_binds_visible_root_to_pair_value(
    tmp_path: Path,
) -> None:
    case = next(
        case
        for case in _suite_cli_cases()
        if case.id == "O22-CLI-CONVERT-EXTERNAL-01"
    )
    scenario_root = tmp_path / "scenario"
    (scenario_root / "evidence").mkdir(parents=True)
    (scenario_root / "owned").mkdir()
    _, runtime, _ = _build(case, scenario_root / "owned" / "cli-runtime")
    _seal(runtime, None, _make_console(tmp_path), 22150)
    evidence = write_prompt_provenance(
        scenario=case,
        version="2022.1",
        scenario_root=scenario_root,
        prompts=(runtime.render_prompt(), case.confirmation_prompt),
        visible_values=runtime.visible_values,
        protocol=runtime.gateway_protocol(),
    )

    row = next(
        item
        for item in evidence.payload["request"]["inputs"]
        if item["name"] == "output_directory"
    )
    assert row["value"] == str(runtime.plan.io_root / "output")
    assert len(row["leaf_bindings"]) == 1
    binding = row["leaf_bindings"][0]
    assert binding["pointer"] == ""
    assert binding["origin_kind"] == "owned_path"
    assert binding["origin_pointer"] == (
        "/steps/1/arguments/2/value/arguments/args/output/1"
    )
    assert binding["path_kind"] == "directory"
    assert binding["owned_relative_path"].endswith("/cli-io/output")


@pytest.mark.parametrize(
    "case_id",
    (
        "O22-CLI-CONVERT-EXTERNAL-01",
        "O22-CLI-CONVERT-EXTERNAL-02",
        "O22-CLI-CONVERT-EXTERNAL-03",
        "O22-CLI-CONVERT-EXTERNAL-04",
        "O22-CLI-CONVERT-EXTERNAL-05",
    ),
)
def test_convert_external_source_manifest_uses_project_relative_windows_root(
    tmp_path: Path,
    case_id: str,
) -> None:
    case = next(case for case in _suite_cli_cases() if case.id == case_id)
    _, runtime, _ = _build(case, tmp_path)

    manifest_root = runtime.plan.asset_root / "manifests"
    for manifest in sorted(manifest_root.glob("*.wsources")):
        root = ET.parse(manifest).getroot()
        wire_root = root.attrib["Root"]
        assert wire_root == r"..\cli-assets\wav"
        assert not wire_root.startswith("/")
        assert (
            runtime.plan.project_root / wire_root.replace("\\", "/")
        ).resolve() == (runtime.plan.asset_root / "wav").resolve()


def test_localized_generate_reuses_two_logical_sounds_and_creates_events_once(
    tmp_path: Path,
) -> None:
    case = next(
        case
        for case in _suite_cli_cases()
        if case.id == "O22-CLI-GENERATE-BANK-02"
    )
    _, runtime, backend = _build(case, tmp_path)
    assert backend is not None
    _seal(runtime, backend, _make_console(tmp_path), 22200)

    by_object_path: dict[str, list[tuple[SetupAudioImport, str]]] = {}
    for request, object_id in backend.audio_import_results:
        by_object_path.setdefault(request.object_path, []).append(
            (request, object_id)
        )
    assert len(by_object_path) == 2
    logical_object_ids: set[str] = set()
    for rows in by_object_path.values():
        assert len({object_id for _request, object_id in rows}) == 1
        logical_object_ids.add(rows[0][1])
        assert [request.language for request, _object_id in rows] == [
            "English(US)",
            "Japanese",
            "Chinese(PRC)",
        ]
        assert [request.import_operation for request, _object_id in rows] == [
            "createNew",
            "useExisting",
            "useExisting",
        ]
        assert [request.event_path is not None for request, _object_id in rows] == [
            True,
            False,
            False,
        ]
        assert [request.notes is not None for request, _object_id in rows] == [
            True,
            False,
            False,
        ]
        expected_media = [
            media
            for media in runtime.plan.asset_spec["fixture_manifest"]["soundbanks"][0]["media"]
            if media["object_path"] == rows[0][0].object_path
        ]
        assert [request.audio_file.name for request, _object_id in rows] == [
            media["relative_wav"] for media in expected_media
        ]
        assert len(
            {
                hashlib.sha256(request.audio_file.read_bytes()).hexdigest()
                for request, _object_id in rows
            }
        ) == 3
    assert len(logical_object_ids) == 2
    assert len(backend.events) == 2
    assert {
        event.target_ids[0]
        for event in backend.events.values()
        if event.action_types == (1,) and len(event.target_ids) == 1
    } == logical_object_ids
    assert all(len(event.action_ids) == 1 for event in backend.events.values())
    assert len(backend.localized_objects) == 6
    for (object_path, language), localized in backend.localized_objects.items():
        assert localized.object_id in logical_object_ids
        assert localized.language == language
        assert localized.source_path is not None
        copied = Path(localized.source_path)
        assert runtime.plan.project_root / "Originals" in copied.parents
        matching_request = next(
            request
            for request, _object_id in by_object_path[object_path]
            if request.language == language
        )
        assert localized.source_sha256 == hashlib.sha256(
            matching_request.audio_file.read_bytes()
        ).hexdigest()

    args = runtime.operation_request()["arguments"]["args"]
    assert args["language"] == ["English(US)", "Japanese", "Chinese(PRC)"]
    assert {
        output.path.parent.name
        for output in runtime.expected_outputs
        if output.kind == "bank"
    } == {"English(US)", "Japanese", "Chinese(PRC)"}


def test_localized_generate_rejects_wrong_language_source_readback(
    tmp_path: Path,
) -> None:
    case = next(
        case
        for case in _suite_cli_cases()
        if case.id == "O22-CLI-GENERATE-BANK-02"
    )
    _, runtime, backend = _build(case, tmp_path)
    assert backend is not None
    exact_read = backend.read_localized_object

    def wrong_read(path: str, *, language: str) -> CliObjectRecord | None:
        value = exact_read(path, language=language)
        if value is not None and language == "Japanese":
            return replace(value, language="Chinese(PRC)")
        return value

    backend.read_localized_object = wrong_read  # type: ignore[method-assign]
    with pytest.raises(CliRuntimeError, match="Audio Source language mismatch"):
        runtime.prepare_setup(backend)


def test_generate02_requires_exact_per_language_soundbanksinfo_manifest(
    tmp_path: Path,
) -> None:
    case = next(
        case
        for case in _suite_cli_cases()
        if case.id == "O22-CLI-GENERATE-BANK-02"
    )
    _, runtime, backend = _build(case, tmp_path)
    assert backend is not None
    lifecycle = _seal(runtime, backend, _make_console(tmp_path), 22250)
    _apply_success(runtime, backend)

    success = runtime.verify_after(
        dispatch=_dispatch(case),
        lifecycle=lifecycle,
        business_evidence=_phase_evidence(lifecycle.business),
    )
    success.assert_passed()

    info_path = runtime.plan.io_root / "SoundbanksInfo.xml"
    original = info_path.read_bytes()
    document = ET.parse(info_path)
    japanese = next(
        bank
        for bank in document.getroot().findall("./SoundBanks/SoundBank")
        if bank.attrib["Language"] == "Japanese"
    )
    media_root = japanese.find("Media")
    assert media_root is not None and len(media_root) == 2
    media_root.remove(media_root[0])
    document.write(info_path, encoding="utf-8", xml_declaration=True)
    missing_media = runtime.verify_after(
        dispatch=_dispatch(case),
        lifecycle=lifecycle,
        business_evidence=_phase_evidence(lifecycle.business),
    )
    assert not missing_media.passed
    assert any("localized media manifest" in item for item in missing_media.failures)

    info_path.write_bytes(original)
    document = ET.parse(info_path)
    japanese = next(
        bank
        for bank in document.getroot().findall("./SoundBanks/SoundBank")
        if bank.attrib["Language"] == "Japanese"
    )
    event = japanese.find("./Events/Event")
    assert event is not None
    event.set("Name", "Play_Unreviewed_Event")
    document.write(info_path, encoding="utf-8", xml_declaration=True)
    wrong_event = runtime.verify_after(
        dispatch=_dispatch(case),
        lifecycle=lifecycle,
        business_evidence=_phase_evidence(lifecycle.business),
    )
    assert not wrong_event.passed
    assert any("localized Event manifest" in item for item in wrong_event.failures)


def test_generate_definition_files_parse_as_guid_event_rows_with_exact_filters(
    tmp_path: Path,
) -> None:
    case = next(
        case
        for case in _suite_cli_cases()
        if case.id == "O22-CLI-GENERATE-BANK-05"
    )
    _, runtime, backend = _build(case, tmp_path)
    assert backend is not None
    _seal(runtime, backend, _make_console(tmp_path), 22300)

    definitions = runtime.plan.asset_spec["assets"]["definition_files"]
    for definition in definitions:
        path = runtime.plan.asset_root / "definitions" / str(definition["name"])
        raw_rows = [line.split("\t") for line in path.read_text(encoding="utf-8").splitlines()]
        assert all(cells[1].startswith("{") and cells[1] != "Event" for cells in raw_rows)
        parsed = parse_soundbank_definition_file(path)
        expected_ids: list[str] = []
        for row in definition["rows"]:
            event = backend.read_event(str(row["identity"]))
            assert event is not None
            expected_ids.append(event.object_id)
        assert [row["definition_keyword"] for row in parsed["rows"]] == [
            "Event"
        ] * len(expected_ids)
        assert [row["identity"] for row in parsed["rows"]] == [
            {"kind": "guid", "value": object_id}
            for object_id in expected_ids
        ]
        assert [row["filters"] for row in parsed["rows"]] == [
            ["events", "structures", "media"]
        ] * len(expected_ids)


def test_convert_oracle_requires_exact_nonempty_riff_outputs_and_preserves_controls(
    tmp_path: Path,
) -> None:
    case = next(case for case in _suite_cli_cases() if case.id == "O22-CLI-CONVERT-EXTERNAL-05")
    _, runtime, _ = _build(case, tmp_path)
    lifecycle = _seal(runtime, None, _make_console(tmp_path), 23000)
    assert runtime.verify_preview_unchanged().passed
    for output in runtime.expected_outputs:
        _write_riff(output.path, output.business_name)
    result = runtime.verify_after(
        dispatch=_dispatch(case),
        lifecycle=lifecycle,
        business_evidence=_phase_evidence(lifecycle.business),
    )
    result.assert_passed()

    extra = runtime.plan.io_root / "output" / "unexpected.wem"
    _write_riff(extra)
    failed = runtime.verify_after(
        dispatch=_dispatch(case),
        lifecycle=lifecycle,
        business_evidence=_phase_evidence(lifecycle.business),
    )
    assert not failed.passed
    assert any("WEM set" in value for value in failed.failures)


def test_generate_oracle_checks_banks_metadata_events_and_project_immutability(
    tmp_path: Path,
) -> None:
    case = next(case for case in _suite_cli_cases() if case.id == "O22-CLI-GENERATE-BANK-04")
    _, runtime, backend = _build(case, tmp_path)
    assert backend is not None
    lifecycle = _seal(runtime, backend, _make_console(tmp_path), 24000)
    _apply_success(runtime, backend)
    generated_analysis = (
        runtime.plan.project_root
        / "Originals"
        / "Voices"
        / "English(US)"
        / "generated.akd"
    )
    generated_analysis.parent.mkdir(parents=True, exist_ok=True)
    generated_analysis.write_bytes(b"generated analysis cache")
    (runtime.plan.project_root / "SampleProject.crossover.validationcache").write_bytes(
        b"generated validation cache"
    )
    result = runtime.verify_after(
        dispatch=_dispatch(case),
        lifecycle=lifecycle,
        business_evidence=_phase_evidence(lifecycle.business),
    )
    result.assert_passed()

    runtime.plan.project_path.write_text("corrupted", encoding="utf-8")
    failed = runtime.verify_after(
        dispatch=_dispatch(case),
        lifecycle=lifecycle,
        business_evidence=_phase_evidence(lifecycle.business),
    )
    assert not failed.passed
    assert any("changed the project" in value for value in failed.failures)


def test_generate04_rebuild_requires_cache_marker_and_header_digest_delta(
    tmp_path: Path,
) -> None:
    case = next(case for case in _suite_cli_cases() if case.id == "O22-CLI-GENERATE-BANK-04")
    _, runtime, backend = _build(case, tmp_path)
    assert backend is not None
    lifecycle = _seal(runtime, backend, _make_console(tmp_path), 24100)
    seeds = runtime.plan.asset_spec["fixture_manifest"]["rebuild_seeds"]
    cache_seed = runtime.root_bindings["cache_directory"] / seeds["cache"]["relative_path"]
    header_seed = runtime.root_bindings["root_output_directory"] / seeds["header"]["relative_path"]
    stale_cache = cache_seed.read_bytes()
    stale_header = header_seed.read_bytes()
    _apply_success(runtime, backend)
    success = runtime.verify_after(
        dispatch=_dispatch(case), lifecycle=lifecycle,
        business_evidence=_phase_evidence(lifecycle.business),
    )
    success.assert_passed()

    cache_seed.parent.mkdir(parents=True, exist_ok=True)
    cache_seed.write_bytes(stale_cache)
    failed_cache = runtime.verify_after(
        dispatch=_dispatch(case), lifecycle=lifecycle,
        business_evidence=_phase_evidence(lifecycle.business),
    )
    assert not failed_cache.passed
    assert any("cache marker" in value for value in failed_cache.failures)
    cache_seed.unlink()

    header_seed.write_bytes(stale_header)
    failed_header = runtime.verify_after(
        dispatch=_dispatch(case), lifecycle=lifecycle,
        business_evidence=_phase_evidence(lifecycle.business),
    )
    assert not failed_header.passed
    assert any("header" in value for value in failed_header.failures)


def test_generate01_proves_exact_nonempty_init_artifacts_without_dependency_overclaim(
    tmp_path: Path,
) -> None:
    case = next(case for case in _suite_cli_cases() if case.id == "O22-CLI-GENERATE-BANK-01")
    _, runtime, backend = _build(case, tmp_path)
    assert backend is not None
    lifecycle = _seal(runtime, backend, _make_console(tmp_path), 24200)
    _apply_success(runtime, backend)
    success = runtime.verify_after(
        dispatch=_dispatch(case), lifecycle=lifecycle,
        business_evidence=_phase_evidence(lifecycle.business),
    )
    success.assert_passed()

    windows_init = next(
        output.path for output in runtime.expected_outputs
        if output.business_name == "Init.bnk" and output.platform == "Windows"
    )
    windows_init.unlink()
    failed = runtime.verify_after(
        dispatch=_dispatch(case), lifecycle=lifecycle,
        business_evidence=_phase_evidence(lifecycle.business),
    )
    assert not failed.passed
    assert any("SoundBank file set" in value or "missing" in value for value in failed.failures)


def test_tab_oracle_checks_guid_policy_source_binding_events_controls_and_xml(
    tmp_path: Path,
) -> None:
    case = next(case for case in _suite_cli_cases() if case.id == "O22-CLI-TAB-IMPORT-05")
    _, runtime, backend = _build(case, tmp_path)
    assert backend is not None
    lifecycle = _seal(runtime, backend, _make_console(tmp_path), 25000)
    backend.apply_tab_business(runtime)
    assert lifecycle.oracle is not None
    result = runtime.verify_after(
        dispatch=_dispatch(case),
        lifecycle=lifecycle,
        business_evidence=_phase_evidence(lifecycle.business),
        oracle_backend=backend,
        oracle_evidence=_phase_evidence(lifecycle.oracle),
    )
    result.assert_passed()

    target = str(runtime.plan.asset_spec["expected"]["objects"][0]["path"])
    language = str(runtime.plan.asset_spec["expected"]["objects"][0]["language"])
    old = backend.localized_objects[(target, language)]
    backend.localized_objects[(target, language)] = CliObjectRecord(
        path=old.path,
        object_id=old.object_id,
        object_type=old.object_type,
        name=old.name,
        language=old.language,
        source_path=old.source_path,
        source_sha256="0" * 64,
    )
    failed = runtime.verify_after(
        dispatch=_dispatch(case),
        lifecycle=lifecycle,
        business_evidence=_phase_evidence(lifecycle.business),
        oracle_backend=backend,
        oracle_evidence=_phase_evidence(lifecycle.oracle),
    )
    assert not failed.passed
    assert any("source binding" in value for value in failed.failures)


def test_tab01_existing_localized_rows_have_media_only_wire_and_absent_rows_create(
    tmp_path: Path,
) -> None:
    case = next(
        case for case in _suite_cli_cases() if case.id == "O22-CLI-TAB-IMPORT-01"
    )
    _, runtime, backend = _build(case, tmp_path)
    assert backend is not None
    table_path = runtime.root_bindings["import_file"]
    with table_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))

    assert len(rows) == 6
    expected_objects = runtime.plan.asset_spec["expected"]["objects"]
    for row, expected in zip(rows[:2], expected_objects[:2], strict=True):
        assert {key for key, value in row.items() if value} == {
            "Audio File",
            "Object Path",
        }
        parent, _, name = str(expected["path"]).rpartition("\\")
        assert row["Object Path"] == f"{parent}\\<Sound Voice>{name}"
        assert row["Object Type"] == ""
        assert row["Notes"] == ""
    for row, expected in zip(rows[2:], expected_objects[2:], strict=True):
        assert row["Object Path"] == expected["path"]
        assert row["Object Type"] == "Sound Voice"
        assert row["Notes"]

    lifecycle = _seal(runtime, backend, _make_console(tmp_path), 25100)
    expected_paths = {
        str(row["path"]) for row in runtime.plan.asset_spec["expected"]["objects"]
    }
    assert expected_paths.issubset(
        {path for path, language in backend.localized_reads if language == "Japanese"}
    )

    backend.apply_tab_business(runtime)
    backend.localized_reads.clear()
    assert lifecycle.oracle is not None
    result = runtime.verify_after(
        dispatch=_dispatch(case),
        lifecycle=lifecycle,
        business_evidence=_phase_evidence(lifecycle.business),
        oracle_backend=backend,
        oracle_evidence=_phase_evidence(lifecycle.oracle),
    )
    result.assert_passed()
    assert backend.localized_reads == [
        (str(row["path"]), "Japanese")
        for row in runtime.plan.asset_spec["expected"]["objects"]
    ]


def test_tab_oracle_rejects_empty_localized_language_evidence(
    tmp_path: Path,
) -> None:
    case = next(
        case for case in _suite_cli_cases() if case.id == "O22-CLI-TAB-IMPORT-01"
    )
    _, runtime, backend = _build(case, tmp_path)
    assert backend is not None
    lifecycle = _seal(runtime, backend, _make_console(tmp_path), 25200)
    backend.apply_tab_business(runtime)
    target = str(runtime.plan.asset_spec["expected"]["objects"][0]["path"])
    exact = backend.localized_objects[(target, "Japanese")]
    backend.localized_objects[(target, "Japanese")] = replace(exact, language=None)
    assert lifecycle.oracle is not None

    result = runtime.verify_after(
        dispatch=_dispatch(case),
        lifecycle=lifecycle,
        business_evidence=_phase_evidence(lifecycle.business),
        oracle_backend=backend,
        oracle_evidence=_phase_evidence(lifecycle.oracle),
    )

    assert not result.passed
    assert f"imported object language mismatch: {target}" in result.failures


def test_migration_copies_sealed_source_and_accepts_only_version_metadata_delta(
    tmp_path: Path,
) -> None:
    case = next(case for case in _suite_cli_cases() if case.id == "O22-CLI-MIGRATE-01")
    _, runtime, _ = _build(case, tmp_path)
    lifecycle = _seal(runtime, None, _make_console(tmp_path), 26000)
    source_before = runtime.before.source_template_tree
    document = ET.parse(runtime.plan.project_path)
    document.getroot().set("WwiseVersion", "v2022.1.0")
    document.getroot().set("WwiseBuild", "8584")
    document.write(runtime.plan.project_path, encoding="utf-8", xml_declaration=True)
    oracle = FakeBackend(runtime.plan.project_path)
    assert lifecycle.oracle is not None
    result = runtime.verify_after(
        dispatch=_dispatch(case, disconnect=True),
        lifecycle=lifecycle,
        business_evidence=_phase_evidence(
            lifecycle.business,
            returncode=0,
            natural_exit_before_shutdown=True,
        ),
        oracle_backend=oracle,
        oracle_evidence=_phase_evidence(lifecycle.oracle),
    )
    result.assert_passed()
    assert runtime.before.source_template_tree == source_before


def test_migration_forced_runner_shutdown_never_proves_a_disconnect(
    tmp_path: Path,
) -> None:
    case = next(case for case in _suite_cli_cases() if case.id == "O22-CLI-MIGRATE-01")
    _, runtime, _ = _build(case, tmp_path)
    lifecycle = _seal(runtime, None, _make_console(tmp_path), 26100)
    oracle = _apply_success(runtime, None)
    assert lifecycle.oracle is not None
    assert oracle is not None
    forced_shutdown = ProcessPhaseEvidence(
        role=lifecycle.business.role,
        argv=lifecycle.business.argv,
        cwd=lifecycle.business.cwd,
        shell=False,
        started=True,
        ready=True,
        process_exited=True,
        open_project_path=lifecycle.business.project_path,
        returncode=-15,
        natural_exit_before_shutdown=False,
        runner_shutdown_requested=True,
    )
    result = runtime.verify_after(
        dispatch=CliDispatchEvidence(
            api=case.api,
            primary_dispatch_count=1,
            dispatch_started=True,
            dispatch_completed=True,
            gateway_verify_state="executed_unverified",
            process_result=2,
            connection_lost=True,
            connection_lost_after_dispatch=True,
            stdout="",
            stderr="",
        ),
        lifecycle=lifecycle,
        business_evidence=forced_shutdown,
        oracle_backend=oracle,
        oracle_evidence=_phase_evidence(lifecycle.oracle),
    )

    assert not result.passed
    assert "migration disconnect was not a natural server exit" in result.failures
    assert "runner shutdown cannot prove a migration disconnect" in result.failures


@pytest.mark.parametrize("process_result", (None, 1, -1, 3))
def test_migration_natural_disconnect_rejects_unreviewed_process_result(
    tmp_path: Path,
    process_result: int | None,
) -> None:
    case = next(case for case in _suite_cli_cases() if case.id == "O22-CLI-MIGRATE-01")
    _, runtime, _ = _build(case, tmp_path)
    lifecycle = _seal(runtime, None, _make_console(tmp_path), 26200)
    oracle = _apply_success(runtime, None)
    assert lifecycle.oracle is not None
    assert oracle is not None

    result = runtime.verify_after(
        dispatch=replace(
            _dispatch(case, disconnect=True),
            process_result=process_result,
        ),
        lifecycle=lifecycle,
        business_evidence=_phase_evidence(
            lifecycle.business,
            returncode=0,
            natural_exit_before_shutdown=True,
        ),
        oracle_backend=oracle,
        oracle_evidence=_phase_evidence(lifecycle.oracle),
    )

    assert not result.passed
    assert (
        "CLI process result is neither success nor reviewed warnings-only"
        in result.failures
    )


def test_migration_reviewed_warning_result_still_requires_complete_oracle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = next(case for case in _suite_cli_cases() if case.id == "O22-CLI-MIGRATE-01")
    _, runtime, _ = _build(case, tmp_path)
    lifecycle = _seal(runtime, None, _make_console(tmp_path), 26300)
    oracle = _apply_success(runtime, None)
    assert lifecycle.oracle is not None
    assert oracle is not None
    context = oracle.get_context()
    dispatch = replace(
        _dispatch(case, disconnect=True),
        process_result=2,
    )
    business_evidence = _phase_evidence(
        lifecycle.business,
        returncode=2,
        natural_exit_before_shutdown=True,
    )
    runtime.verify_after(
        dispatch=dispatch,
        lifecycle=lifecycle,
        business_evidence=business_evidence,
        oracle_backend=oracle,
        oracle_evidence=_phase_evidence(lifecycle.oracle),
    ).assert_passed()

    monkeypatch.setattr(
        oracle,
        "get_context",
        lambda: {"info": context["info"], "project": {}},
    )

    result = runtime.verify_after(
        dispatch=dispatch,
        lifecycle=lifecycle,
        business_evidence=business_evidence,
        oracle_backend=oracle,
        oracle_evidence=_phase_evidence(lifecycle.oracle),
    )

    assert not result.passed
    assert (
        "oracle/setup backend context lacks a usable project path"
        in result.failures
    )


def test_migration_reference_or_identity_drift_fails_closed(tmp_path: Path) -> None:
    case = next(case for case in _suite_cli_cases() if case.id == "O22-CLI-MIGRATE-01")
    _, runtime, _ = _build(case, tmp_path)
    lifecycle = _seal(runtime, None, _make_console(tmp_path), 27000)
    path = runtime.plan.project_root / "Events" / "Minigun.wwu"
    text = path.read_text(encoding="utf-8")
    assert "Minigun_Barrel_Start" in text
    path.write_text(text.replace("Minigun_Barrel_Start", "Broken_Target", 1), encoding="utf-8")
    document = ET.parse(runtime.plan.project_path)
    document.getroot().set("WwiseVersion", "v2022.1.0")
    document.write(runtime.plan.project_path, encoding="utf-8", xml_declaration=True)
    oracle = FakeBackend(runtime.plan.project_path)
    assert lifecycle.oracle is not None
    result = runtime.verify_after(
        dispatch=_dispatch(case, disconnect=True),
        lifecycle=lifecycle,
        business_evidence=_phase_evidence(
            lifecycle.business,
            returncode=0,
            natural_exit_before_shutdown=True,
        ),
        oracle_backend=oracle,
        oracle_evidence=_phase_evidence(lifecycle.oracle),
    )
    assert not result.passed
    assert any("inventory drifted" in value for value in result.failures)


def test_migration_car_engine_oracle_captures_rtpc_curve_points(tmp_path: Path) -> None:
    case = next(case for case in _suite_cli_cases() if case.id == "O22-CLI-MIGRATE-04")
    _, runtime, _ = _build(case, tmp_path)
    lifecycle = _seal(runtime, None, _make_console(tmp_path), 27500)
    car_engine = runtime.plan.project_root / "Actor-Mixer Hierarchy" / "Car Engine.wwu"
    document = ET.parse(car_engine)
    parent_map = {
        child: parent for parent in document.iter() for child in parent
    }
    reference = next(
        element
        for element in document.iter()
        if element.tag.endswith("Ref") and element.attrib.get("Name") == "RPM"
    )
    rtpc = reference
    while rtpc.tag != "RTPC":
        rtpc = parent_map[rtpc]
    y_position = next(rtpc.iter("YPos"))
    y_position.text = str(float(y_position.text or "0") + 1.0)
    document.write(car_engine, encoding="utf-8", xml_declaration=True)
    project = ET.parse(runtime.plan.project_path)
    project.getroot().set("WwiseVersion", "v2022.1.0")
    project.write(runtime.plan.project_path, encoding="utf-8", xml_declaration=True)
    assert lifecycle.oracle is not None
    result = runtime.verify_after(
        dispatch=_dispatch(case, disconnect=True),
        lifecycle=lifecycle,
        business_evidence=_phase_evidence(
            lifecycle.business,
            natural_exit_before_shutdown=True,
        ),
        oracle_backend=FakeBackend(runtime.plan.project_path),
        oracle_evidence=_phase_evidence(lifecycle.oracle),
    )
    assert not result.passed
    assert any("inventory drifted" in value for value in result.failures)


def test_migration_car_engine_oracle_normalizes_2021_and_2022_rtpc_layouts() -> None:
    case = next(case for case in _suite_cli_cases() if case.id == "O22-CLI-MIGRATE-04")
    spec = case.fixture["asset_spec"]

    before = cli_runtime._migration_inventory(REPO_ROOT / "tests" / "_org" / "2021.1", spec)
    after = cli_runtime._migration_inventory(REPO_ROOT / "tests" / "_org" / "2022.1", spec)

    assert after == before


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        ("missing-property-name", "lacks its controlled Property"),
        ("duplicate-property-name", "ambiguous serialized PropertyName rows"),
        ("open-point-shape", "Point shape is not closed"),
    ),
)
def test_migration_car_engine_2022_rtpc_layout_rejects_open_shapes(
    tmp_path: Path,
    mutation: str,
    message: str,
) -> None:
    case = next(case for case in _suite_cli_cases() if case.id == "O22-CLI-MIGRATE-04")
    spec = case.fixture["asset_spec"]
    source_root = REPO_ROOT / "tests" / "_org" / "2022.1"
    project_root = tmp_path / "migrated"
    for relative in (
        Path("Game Parameters") / "Car Engine.wwu",
        Path("Actor-Mixer Hierarchy") / "Car Engine.wwu",
    ):
        destination = project_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_root / relative, destination)

    car_engine = project_root / "Actor-Mixer Hierarchy" / "Car Engine.wwu"
    document = ET.parse(car_engine)
    target_rtpc: ET.Element | None = None
    for rtpc in document.iter("RTPC"):
        if not any(
            element.tag.endswith("Ref") and element.attrib.get("Name") == "RPM"
            for element in rtpc.iter()
        ):
            continue
        target_rtpc = rtpc
        break
    if target_rtpc is None:  # pragma: no cover - the fixture contract proves this.
        raise AssertionError("reviewed RPM RTPC was not found")
    property_list = next(
        element for element in target_rtpc.iter("PropertyList")
    )
    property_name = next(
        element
        for element in property_list
        if element.tag == "Property"
        and element.attrib.get("Name") == "PropertyName"
    )
    if mutation == "missing-property-name":
        property_list.remove(property_name)
    elif mutation == "duplicate-property-name":
        ET.SubElement(
            property_list,
            "Property",
            {"Name": "PropertyName", "Type": "string", "Value": "Volume"},
        )
    elif mutation == "open-point-shape":
        unexpected = ET.SubElement(next(target_rtpc.iter("Point")), "Unexpected")
        unexpected.text = "1"
    else:  # pragma: no cover - the parametrization is closed above.
        raise AssertionError(f"unknown mutation: {mutation}")
    document.write(car_engine, encoding="utf-8", xml_declaration=True)

    with pytest.raises(CliRuntimeError, match=message):
        cli_runtime._migration_inventory(project_root, spec)


def test_scoped_migration_ignores_new_defaults_but_catches_reviewed_property_drift(
    tmp_path: Path,
) -> None:
    case = next(case for case in _suite_cli_cases() if case.id == "O22-CLI-MIGRATE-05")
    _, runtime, _ = _build(case, tmp_path)
    lifecycle = _seal(runtime, None, _make_console(tmp_path), 27700)
    document = ET.parse(runtime.plan.project_path)
    root = document.getroot()
    root.set("WwiseVersion", "v2022.1.0")
    project = next(
        element
        for element in root.iter("Project")
        if element.attrib.get("Name") == "SampleProject"
    )
    property_list = next(project.iter("PropertyList"))
    ET.SubElement(
        property_list,
        "Property",
        {"Name": "New2022Default", "Type": "int32", "Value": "1"},
    )
    document.write(runtime.plan.project_path, encoding="utf-8", xml_declaration=True)
    assert lifecycle.oracle is not None
    kwargs = {
        "dispatch": _dispatch(case, disconnect=True),
        "lifecycle": lifecycle,
        "business_evidence": _phase_evidence(
            lifecycle.business,
            natural_exit_before_shutdown=True,
        ),
        "oracle_backend": FakeBackend(runtime.plan.project_path),
        "oracle_evidence": _phase_evidence(lifecycle.oracle),
    }
    runtime.verify_after(**kwargs).assert_passed()

    document = ET.parse(runtime.plan.project_path)
    reviewed = next(
        element
        for element in document.iter("Property")
        if element.attrib.get("Name") == "DefaultLanguage"
        and element.attrib.get("Value") == "English(US)"
    )
    reviewed.set("Value", "Japanese")
    document.write(runtime.plan.project_path, encoding="utf-8", xml_declaration=True)
    failed = runtime.verify_after(
        **{
            **kwargs,
            "oracle_backend": FakeBackend(runtime.plan.project_path),
        }
    )
    assert not failed.passed
    assert any("inventory drifted" in value for value in failed.failures)


def test_source_template_drift_is_never_a_semantic_pass(tmp_path: Path) -> None:
    case = next(case for case in _suite_cli_cases() if case.id == "O22-CLI-CONVERT-EXTERNAL-01")
    _, runtime, _ = _build(case, tmp_path)
    lifecycle = _seal(runtime, None, _make_console(tmp_path), 28000)
    for output in runtime.expected_outputs:
        _write_riff(output.path)
    (runtime.plan.source_template_root / "SampleProject.wproj").write_text("drift", encoding="utf-8")
    result = runtime.verify_after(
        dispatch=_dispatch(case),
        lifecycle=lifecycle,
        business_evidence=_phase_evidence(lifecycle.business),
    )
    assert not result.passed
    assert "immutable source project/template changed" in result.failures


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("primary_dispatch_count", 2, "exactly once"),
        ("connection_lost", True, "unexpected"),
        ("process_result", 1, "neither success nor reviewed warnings-only"),
        ("unclassified_load_issues", ("warning",), "unclassified"),
    ],
)
def test_dispatch_ambiguity_error_result_warning_and_unexpected_disconnect_fail_closed(
    tmp_path: Path,
    field: str,
    value: Any,
    expected: str,
) -> None:
    case = next(case for case in _suite_cli_cases() if case.id == "O22-CLI-CONVERT-EXTERNAL-01")
    _, runtime, _ = _build(case, tmp_path)
    lifecycle = _seal(runtime, None, _make_console(tmp_path), 29000)
    for output in runtime.expected_outputs:
        _write_riff(output.path)
    values = asdict(_dispatch(case))
    values[field] = value
    if field == "connection_lost":
        values["connection_lost_after_dispatch"] = True
    dispatch = CliDispatchEvidence(**values)
    result = runtime.verify_after(
        dispatch=dispatch,
        lifecycle=lifecycle,
        business_evidence=_phase_evidence(lifecycle.business),
    )
    assert not result.passed
    assert any(expected in failure for failure in result.failures)


@pytest.mark.parametrize("api", tuple(CLI_APIS))
def test_warnings_only_result_is_closed_to_reviewed_2022_uri(api: str) -> None:
    assert cli_runtime._is_reviewed_2022_warnings_only_result(
        version="2022.1",
        api=api,
        process_result=2,
    )
    for version, candidate_api, result in (
        ("2023.1", api, 2),
        ("2022.1", "ak.wwise.cli.verify", 2),
        ("2022.1", api, 1),
        ("2022.1", api, None),
    ):
        assert not cli_runtime._is_reviewed_2022_warnings_only_result(
            version=version,
            api=candidate_api,
            process_result=result,
        )


def _write_sealed_convert_side_effects(runtime: PreparedCliRuntime) -> None:
    for wav in runtime.plan.asset_root.rglob("*.wav"):
        wav.with_suffix(".akd").write_bytes(b"\r\x00\x00\x00" + b"sealed-akd" * 3)
    cache_version = runtime.plan.project_root / ".cache" / "CacheVersion"
    cache_version.parent.mkdir(parents=True, exist_ok=True)
    cache_version.write_bytes(b"F\x00\x00\x00")
    settings = runtime.plan.project_root / (
        runtime.plan.project_path.stem + ".crossover.wsettings"
    )
    root = ET.Element(
        "WwiseDocument",
        Type="UserProjectSettings",
        SchemaVersion="110",
    )
    ET.SubElement(root, "UserProjectSettingsInfo")
    ET.ElementTree(root).write(settings, encoding="utf-8", xml_declaration=True)


def test_reviewed_result_two_and_relational_convert_side_effects_pass_only_with_oracle(
    tmp_path: Path,
) -> None:
    case = next(
        case
        for case in _suite_cli_cases()
        if case.id == "O22-CLI-CONVERT-EXTERNAL-01"
    )
    _, runtime, _ = _build(case, tmp_path)
    lifecycle = _seal(runtime, None, _make_console(tmp_path), 29020)
    _apply_success(runtime, None)
    _write_sealed_convert_side_effects(runtime)
    warning_dispatch = replace(_dispatch(case), process_result=2)

    passed = runtime.verify_after(
        dispatch=warning_dispatch,
        lifecycle=lifecycle,
        business_evidence=_phase_evidence(lifecycle.business),
    )
    passed.assert_passed()

    runtime.expected_outputs[0].path.unlink()
    failed = runtime.verify_after(
        dispatch=warning_dispatch,
        lifecycle=lifecycle,
        business_evidence=_phase_evidence(lifecycle.business),
    )
    assert not failed.passed
    assert any("WEM set" in failure or "missing" in failure for failure in failed.failures)


@pytest.mark.parametrize(
    ("tamper", "expected"),
    (
        ("unbound_akd", "outside sealed Wwise .akd side effects"),
        ("changed_wav", "outside sealed Wwise .akd side effects"),
        ("invalid_bound_akd", "outside sealed Wwise .akd side effects"),
        ("unexpected_project_file", "changed the project copy"),
        ("invalid_settings", "changed the project copy"),
        ("invalid_cache_version", "changed the project copy"),
    ),
)
def test_convert_side_effect_allowlist_rejects_unsealed_tamper(
    tmp_path: Path,
    tamper: str,
    expected: str,
) -> None:
    case = next(
        case
        for case in _suite_cli_cases()
        if case.id == "O22-CLI-CONVERT-EXTERNAL-01"
    )
    _, runtime, _ = _build(case, tmp_path)
    lifecycle = _seal(runtime, None, _make_console(tmp_path), 29040)
    _apply_success(runtime, None)
    _write_sealed_convert_side_effects(runtime)

    if tamper == "unbound_akd":
        (runtime.plan.asset_root / "wav" / "unsealed.akd").write_bytes(
            b"\r\x00\x00\x00" + b"unsealed" * 3
        )
    elif tamper == "changed_wav":
        next(runtime.plan.asset_root.rglob("*.wav")).write_bytes(b"changed")
    elif tamper == "invalid_bound_akd":
        next(runtime.plan.asset_root.rglob("*.akd")).write_bytes(b"not-an-akd")
    elif tamper == "unexpected_project_file":
        (runtime.plan.project_root / "unexpected.txt").write_text(
            "tamper",
            encoding="utf-8",
        )
    elif tamper == "invalid_settings":
        settings = runtime.plan.project_root / (
            runtime.plan.project_path.stem + ".crossover.wsettings"
        )
        settings.write_text("<NotWwise/>", encoding="utf-8")
    elif tamper == "invalid_cache_version":
        (runtime.plan.project_root / ".cache" / "CacheVersion").write_bytes(
            b"BAD!"
        )
    else:  # pragma: no cover - parameter list closes the variants.
        raise AssertionError(tamper)

    result = runtime.verify_after(
        dispatch=replace(_dispatch(case), process_result=2),
        lifecycle=lifecycle,
        business_evidence=_phase_evidence(lifecycle.business),
    )
    assert not result.passed
    assert any(expected in failure for failure in result.failures)


def test_nonmigration_natural_business_exit_fails_closed(
    tmp_path: Path,
) -> None:
    case = next(
        case
        for case in _suite_cli_cases()
        if case.id == "O22-CLI-CONVERT-EXTERNAL-01"
    )
    _, runtime, _ = _build(case, tmp_path)
    lifecycle = _seal(runtime, None, _make_console(tmp_path), 29100)
    _apply_success(runtime, None)
    result = runtime.verify_after(
        dispatch=_dispatch(case),
        lifecycle=lifecycle,
        business_evidence=_phase_evidence(
            lifecycle.business,
            natural_exit_before_shutdown=True,
        ),
    )

    assert not result.passed
    assert "business WAAPI server exited unexpectedly before runner shutdown" in result.failures


def test_lifecycle_rejects_shell_extra_args_wrong_project_and_residual_process(
    tmp_path: Path,
) -> None:
    case = next(case for case in _suite_cli_cases() if case.id == "O22-CLI-TAB-IMPORT-01")
    _, runtime, backend = _build(case, tmp_path)
    assert backend is not None
    console = _make_console(tmp_path)
    lifecycle = runtime.plan.lifecycle_plan(
        console_path=console,
        setup_port=30001,
        business_port=30002,
        oracle_port=30003,
    )
    runtime.prepare_setup(backend)
    assert lifecycle.setup is not None
    bad = ProcessPhaseEvidence(
        role="setup",
        argv=(*lifecycle.setup.argv, "--custom-global-opening-cmd", "bad"),
        cwd=lifecycle.setup.cwd,
        shell=True,
        started=True,
        ready=True,
        process_exited=True,
        residual_pids=(999,),
        open_project_path=str(tmp_path / "wrong.wproj"),
    )
    with pytest.raises(CliRuntimeError) as caught:
        runtime.seal_before(lifecycle=lifecycle, setup_evidence=bad)
    message = str(caught.value)
    assert "argv mismatch" in message
    assert "shell=False" in message
    assert "residual" in message
    assert "wrong project" in message


def test_closed_direct_backend_exposes_only_fixed_waapi_shapes(tmp_path: Path) -> None:
    calls: list[tuple[str, Mapping[str, Any], Mapping[str, Any]]] = []

    def call(uri: str, args: Mapping[str, Any], options: Mapping[str, Any]) -> Any:
        calls.append((uri, args, options))
        if uri == "ak.wwise.core.getInfo":
            return {"version": {"major": 2022, "minor": 1}}
        if uri == "ak.wwise.core.getProjectInfo":
            return {"path": str(tmp_path / "Project.wproj")}
        if uri == "ak.wwise.core.object.get":
            return {"return": []}
        if uri == "ak.wwise.core.project.save":
            return {}
        raise AssertionError(uri)

    backend = ClosedDirectCliBackend(call)
    assert backend.get_context()["project"]["path"].endswith("Project.wproj")
    assert backend.read_object(r"\Actor-Mixer Hierarchy\Missing") is None
    backend.save_project()
    assert [row[0] for row in calls] == [
        "ak.wwise.core.getInfo",
        "ak.wwise.core.getProjectInfo",
        "ak.wwise.core.object.get",
        "ak.wwise.core.project.save",
    ]
    assert not hasattr(backend, "call")


def test_closed_direct_backend_encodes_setup_event_with_explicit_play_action(
    tmp_path: Path,
) -> None:
    audio_file = tmp_path / "voice.wav"
    audio_file.write_bytes(b"RIFF-reviewed-voice")
    object_path = r"\Actor-Mixer Hierarchy\Default Work Unit\Voice"
    event_path = r"\Events\Default Work Unit\Play_Voice"
    sound_id = _guid("setup-event-sound")
    calls: list[tuple[str, Mapping[str, Any], Mapping[str, Any]]] = []

    def call(uri: str, args: Mapping[str, Any], options: Mapping[str, Any]) -> Any:
        calls.append((uri, args, options))
        if uri == "ak.wwise.core.audio.import":
            if args["imports"][0].get("event") != f"{event_path}@Play":
                raise AssertionError(
                    "invalid_arguments: Invalid action ''. Defaulting to 'Play' action."
                )
            return {"objects": [{"id": sound_id}]}
        assert uri == "ak.wwise.core.object.get"
        assert args == {"from": {"path": [object_path]}}
        return {
            "return": [
                {
                    "id": sound_id,
                    "name": "Voice",
                    "type": "Sound",
                    "path": object_path,
                    "audioSource:language": "English(US)",
                }
            ]
        }

    result = ClosedDirectCliBackend(call).import_audio(
        SetupAudioImport(
            audio_file=audio_file,
            object_path=object_path,
            object_type="Sound Voice",
            language="English(US)",
            notes="reviewed setup voice",
            event_path=event_path,
        )
    )

    assert result.object_id == sound_id
    assert calls[0][0] == "ak.wwise.core.audio.import"
    assert calls[0][1] == {
        "importOperation": "createNew",
        "imports": [{
            "audioFile": str(audio_file),
            "objectPath": object_path,
            "importLanguage": "English(US)",
            "objectType": "Sound Voice",
            "notes": "reviewed setup voice",
            "event": f"{event_path}@Play",
        }],
        "autoAddToSourceControl": False,
    }


@pytest.mark.parametrize(
    ("object_type", "language", "typed_leaf"),
    (
        ("Sound Voice", "Japanese", "<Sound Voice>Voice"),
        ("Sound SFX", "SFX", "<Sound SFX>Voice"),
    ),
)
def test_closed_direct_backend_uses_minimal_2022_localized_addition_row(
    tmp_path: Path,
    object_type: str,
    language: str,
    typed_leaf: str,
) -> None:
    audio_file = tmp_path / "voice_ja.wav"
    audio_file.write_bytes(b"RIFF-reviewed-japanese-voice")
    object_path = r"\Actor-Mixer Hierarchy\Default Work Unit\Voice"
    sound_id = _guid("localized-existing-sound")
    calls: list[tuple[str, Mapping[str, Any], Mapping[str, Any]]] = []

    def call(uri: str, args: Mapping[str, Any], options: Mapping[str, Any]) -> Any:
        calls.append((uri, args, options))
        if uri == "ak.wwise.core.audio.import":
            return {"objects": [{"id": sound_id}]}
        assert uri == "ak.wwise.core.object.get"
        assert args == {"from": {"path": [object_path]}}
        return {
            "return": [{
                "id": sound_id,
                "name": "Voice",
                "type": "Sound",
                "path": object_path,
                "audioSource:language": language,
            }]
        }

    result = ClosedDirectCliBackend(call).import_audio(
        SetupAudioImport(
            audio_file=audio_file,
            object_path=object_path,
            object_type=object_type,
            language=language,
            import_operation="useExisting",
        )
    )

    assert result.object_id == sound_id
    assert calls[0] == (
        "ak.wwise.core.audio.import",
        {
            "importOperation": "useExisting",
            "imports": [{
                "audioFile": str(audio_file),
                "objectPath": (
                    r"\Actor-Mixer Hierarchy\Default Work Unit" + "\\" + typed_leaf
                ),
                "importLanguage": language,
            }],
            "autoAddToSourceControl": False,
        },
        {"return": list(cli_runtime._OBJECT_FIELDS)},
    )
    assert set(calls[0][1]["imports"][0]) == {
        "audioFile",
        "objectPath",
        "importLanguage",
    }
    assert calls[1][0] == "ak.wwise.core.object.get"
    assert calls[1][1] == {"from": {"path": [object_path]}}
    assert calls[1][2]["language"] == language


@pytest.mark.parametrize(
    ("object_path", "object_type", "language", "message"),
    (
        (
            r"\Actor-Mixer Hierarchy\Default Work Unit\Voice",
            "Sound",
            "Japanese",
            "object_type must be closed",
        ),
        (
            r"\Actor-Mixer Hierarchy\Default Work Unit\Voice",
            "Random Container",
            "Japanese",
            "object_type must be closed",
        ),
        (
            r"\Actor-Mixer Hierarchy\Default Work Unit\<Sound Voice>Voice",
            "Sound Voice",
            "Japanese",
            "untyped canonical path",
        ),
        (
            r"\Actor-Mixer Hierarchy\Default Work Unit\Voice",
            "Sound SFX",
            "Japanese",
            "ambiguous for importLanguage",
        ),
        (
            r"\Actor-Mixer Hierarchy\Default Work Unit\Voice",
            "Sound Voice",
            "SFX",
            "ambiguous for importLanguage",
        ),
    ),
)
def test_closed_direct_backend_rejects_open_or_pretyped_use_existing_targets(
    tmp_path: Path,
    object_path: str,
    object_type: str,
    language: str,
    message: str,
) -> None:
    audio_file = tmp_path / "voice.wav"
    audio_file.write_bytes(b"RIFF-reviewed-target-contract")
    calls: list[str] = []

    def call(uri: str, args: Mapping[str, Any], options: Mapping[str, Any]) -> Any:
        del args, options
        calls.append(uri)
        raise AssertionError("open useExisting target reached WAAPI")

    with pytest.raises(CliRuntimeError, match=message):
        ClosedDirectCliBackend(call).import_audio(
            SetupAudioImport(
                audio_file=audio_file,
                object_path=object_path,
                object_type=object_type,
                language=language,
                import_operation="useExisting",
            )
        )
    assert calls == []


@pytest.mark.parametrize(
    ("notes", "event_path"),
    [
        ("must not update the Sound", None),
        (None, r"\Events\Default Work Unit\Play_Voice"),
    ],
)
def test_closed_direct_backend_rejects_non_audio_localization_fields(
    tmp_path: Path,
    notes: str | None,
    event_path: str | None,
) -> None:
    audio_file = tmp_path / "voice_localized.wav"
    audio_file.write_bytes(b"RIFF-reviewed-localized-voice")
    calls: list[str] = []

    def call(uri: str, args: Mapping[str, Any], options: Mapping[str, Any]) -> Any:
        del args, options
        calls.append(uri)
        raise AssertionError("invalid localization payload reached WAAPI")

    with pytest.raises(
        CliRuntimeError,
        match="accepts only an audio-file addition",
    ):
        ClosedDirectCliBackend(call).import_audio(
            SetupAudioImport(
                audio_file=audio_file,
                object_path=r"\Actor-Mixer Hierarchy\Default Work Unit\Voice",
                object_type="Sound Voice",
                language="Japanese",
                notes=notes,
                event_path=event_path,
                import_operation="useExisting",
            )
        )
    assert calls == []


def test_closed_direct_backend_rejects_preencoded_setup_event_action(
    tmp_path: Path,
) -> None:
    audio_file = tmp_path / "voice.wav"
    audio_file.write_bytes(b"RIFF-reviewed-voice")
    calls: list[str] = []

    def call(uri: str, args: Mapping[str, Any], options: Mapping[str, Any]) -> Any:
        calls.append(uri)
        raise AssertionError("invalid setup request reached WAAPI")

    with pytest.raises(CliRuntimeError, match="must not embed an Event action"):
        ClosedDirectCliBackend(call).import_audio(
            SetupAudioImport(
                audio_file=audio_file,
                object_path=r"\Actor-Mixer Hierarchy\Default Work Unit\Voice",
                object_type="Sound Voice",
                language="English(US)",
                event_path=r"\Events\Default Work Unit\Play_Voice@Stop",
            )
        )
    assert calls == []


def test_closed_direct_backend_uses_only_required_2022_object_accessors(
    tmp_path: Path,
) -> None:
    source_file = tmp_path / "voice.wav"
    source_file.write_bytes(b"reviewed-source")
    sound_id = _guid("projection-sound")
    source_id = _guid("projection-source")
    parent_id = _guid("projection-parent")
    requested_returns: list[tuple[str, ...]] = []

    def call(uri: str, args: Mapping[str, Any], options: Mapping[str, Any]) -> Any:
        assert uri == "ak.wwise.core.object.get"
        requested_returns.append(tuple(options["return"]))
        origin = args["from"]
        if "path" in origin:
            return {
                "return": [{
                    "id": sound_id,
                    "name": "Voice",
                    "type": "Sound",
                    "path": r"\Actor-Mixer Hierarchy\Default Work Unit\Voice",
                    "parent": {"id": parent_id},
                    "notes": "reviewed",
                    "shortId": 1234,
                    "activeSource": {"id": source_id},
                }]
            }
        assert origin == {"id": [source_id]}
        return {
            "return": [{
                "id": source_id,
                "name": "Voice",
                "type": "AudioFileSource",
                "path": r"\Actor-Mixer Hierarchy\Default Work Unit\Voice\Voice",
                "parent": {"id": sound_id},
                "originalFilePath": str(source_file),
                "audioSource:language": "English(US)",
            }]
        }

    record = ClosedDirectCliBackend(call).read_object(
        r"\Actor-Mixer Hierarchy\Default Work Unit\Voice"
    )

    assert record is not None
    assert record.source_path == str(source_file)
    assert record.language == "English(US)"
    assert len(requested_returns) == 2
    required = {
        "id", "name", "type", "path", "parent", "notes", "shortId",
        "activeSource", "originalFilePath", "sound:originalWavFilePath",
        "audioSource:language",
    }
    assert all(required.issubset(fields) for fields in map(set, requested_returns))
    assert all("originalRelativeFilePath" not in fields for fields in requested_returns)


def test_closed_direct_backend_binds_localized_active_source_with_language_option(
    tmp_path: Path,
) -> None:
    source_file = tmp_path / "voice_ja.wav"
    source_file.write_bytes(b"reviewed-japanese-source")
    object_path = r"\Actor-Mixer Hierarchy\Default Work Unit\Voice"
    sound_id = _guid("localized-option-sound")
    source_id = _guid("localized-option-source")
    options_seen: list[Mapping[str, Any]] = []

    def call(uri: str, args: Mapping[str, Any], options: Mapping[str, Any]) -> Any:
        assert uri == "ak.wwise.core.object.get"
        options_seen.append(dict(options))
        assert options["language"] == "Japanese"
        if "path" in args["from"]:
            return {
                "return": [{
                    "id": sound_id,
                    "name": "Voice",
                    "type": "Sound",
                    "path": object_path,
                    "activeSource": {"id": source_id},
                    "audioSource:language": {"name": "English(US)"},
                    "originalFilePath": str(tmp_path / "sound-must-not-win.wav"),
                    "sound:originalWavFilePath": str(
                        tmp_path / "sound-wav-must-not-win.wav"
                    ),
                }]
            }
        assert args == {"from": {"id": [source_id]}}
        return {
            "return": [{
                "id": source_id,
                "name": "Voice",
                "type": "AudioFileSource",
                "path": object_path + r"\Voice",
                "parent": {"id": sound_id},
                "originalFilePath": str(source_file),
                "audioSource:language": {"name": "Japanese"},
            }]
        }

    localized = ClosedDirectCliBackend(call).read_localized_object(
        object_path,
        language="Japanese",
    )

    assert localized is not None
    assert localized.object_id == sound_id
    assert localized.language == "Japanese"
    assert localized.source_sha256 == hashlib.sha256(
        b"reviewed-japanese-source"
    ).hexdigest()
    assert len(options_seen) == 2
    assert all(options["language"] == "Japanese" for options in options_seen)


def test_closed_direct_backend_falls_back_to_sound_language_mapping(
    tmp_path: Path,
) -> None:
    source_file = tmp_path / "voice_ja.wav"
    source_file.write_bytes(b"reviewed-japanese-fallback")
    object_path = r"\Actor-Mixer Hierarchy\Default Work Unit\Voice"
    sound_id = _guid("localized-fallback-sound")
    source_id = _guid("localized-fallback-source")

    def call(uri: str, args: Mapping[str, Any], options: Mapping[str, Any]) -> Any:
        assert uri == "ak.wwise.core.object.get"
        assert options["language"] == "Japanese"
        if "path" in args["from"]:
            return {
                "return": [{
                    "id": sound_id,
                    "name": "Voice",
                    "type": "Sound",
                    "path": object_path,
                    "activeSource": {"id": source_id},
                    "audioSource:language": {"value": "Japanese"},
                    "originalFilePath": str(source_file),
                    "sound:originalWavFilePath": str(tmp_path / "must-not-win.wav"),
                }]
            }
        return {
            "return": [{
                "id": source_id,
                "name": "Voice",
                "type": "AudioFileSource",
                "path": object_path + r"\Voice",
                "parent": {"id": sound_id},
                "audioSource:language": None,
            }]
        }

    localized = ClosedDirectCliBackend(call).read_localized_object(
        object_path,
        language="Japanese",
    )

    assert localized is not None
    assert localized.language == "Japanese"
    assert localized.source_sha256 == hashlib.sha256(
        b"reviewed-japanese-fallback"
    ).hexdigest()


def test_closed_direct_backend_falls_back_to_sound_wav_path_accessor(
    tmp_path: Path,
) -> None:
    source_file = tmp_path / "voice_sound_accessor.wav"
    source_file.write_bytes(b"reviewed-sound-wav-accessor")
    object_path = r"\Actor-Mixer Hierarchy\Default Work Unit\Voice"
    sound_id = _guid("localized-sound-accessor")
    source_id = _guid("localized-source-without-path")

    def call(uri: str, args: Mapping[str, Any], options: Mapping[str, Any]) -> Any:
        assert uri == "ak.wwise.core.object.get"
        assert options["language"] == "Japanese"
        if "path" in args["from"]:
            return {
                "return": [{
                    "id": sound_id,
                    "name": "Voice",
                    "type": "Sound",
                    "path": object_path,
                    "activeSource": {"id": source_id},
                    "audioSource:language": {"name": "Japanese"},
                    "sound:originalWavFilePath": str(source_file),
                }]
            }
        return {
            "return": [{
                "id": source_id,
                "name": "Voice",
                "type": "AudioFileSource",
                "path": object_path + r"\Voice",
                "parent": {"id": sound_id},
                "audioSource:language": {"name": "Japanese"},
            }]
        }

    localized = ClosedDirectCliBackend(call).read_localized_object(
        object_path,
        language="Japanese",
    )

    assert localized is not None
    assert localized.source_path == str(source_file)
    assert localized.source_sha256 == hashlib.sha256(
        b"reviewed-sound-wav-accessor"
    ).hexdigest()


def test_closed_direct_backend_rejects_wrong_source_language_mapping(
    tmp_path: Path,
) -> None:
    source_file = tmp_path / "voice_zh.wav"
    source_file.write_bytes(b"reviewed-wrong-localization")
    object_path = r"\Actor-Mixer Hierarchy\Default Work Unit\Voice"
    sound_id = _guid("localized-wrong-sound")
    source_id = _guid("localized-wrong-source")

    def call(uri: str, args: Mapping[str, Any], options: Mapping[str, Any]) -> Any:
        assert uri == "ak.wwise.core.object.get"
        assert options["language"] == "Japanese"
        if "path" in args["from"]:
            return {
                "return": [{
                    "id": sound_id,
                    "name": "Voice",
                    "type": "Sound",
                    "path": object_path,
                    "activeSource": {"id": source_id},
                    "audioSource:language": {"name": "Japanese"},
                }]
            }
        return {
            "return": [{
                "id": source_id,
                "name": "Voice",
                "type": "AudioFileSource",
                "path": object_path + r"\Voice",
                "parent": {"id": sound_id},
                "originalFilePath": str(source_file),
                "audioSource:language": {"name": "Chinese(PRC)"},
            }]
        }

    with pytest.raises(CliRuntimeError, match="language mismatch"):
        ClosedDirectCliBackend(call).read_localized_object(
            object_path,
            language="Japanese",
        )


@pytest.mark.parametrize(
    "value",
    (
        None,
        "",
        " Japanese ",
        {},
        {"name": ""},
        {"name": "Japanese", "value": "English(US)"},
        17,
    ),
)
def test_closed_language_name_parser_rejects_empty_or_open_shapes(value: Any) -> None:
    with pytest.raises(CliRuntimeError):
        cli_runtime._language_name(value, "reviewed language")


def test_closed_direct_backend_localizes_wine_y_source_before_reading(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account_home = tmp_path / "account-home"
    source_file = account_home / "Documents" / "case" / "Originals" / "Voice.wav"
    source_file.parent.mkdir(parents=True)
    source_file.write_bytes(b"reviewed-wine-source")
    monkeypatch.setattr(
        cli_runtime,
        "pwd",
        SimpleNamespace(
            getpwuid=lambda _uid: SimpleNamespace(pw_dir=str(account_home))
        ),
    )
    sound_id = _guid("wine-projection-sound")
    source_id = _guid("wine-projection-source")

    def call(uri: str, args: Mapping[str, Any], options: Mapping[str, Any]) -> Any:
        assert uri == "ak.wwise.core.object.get"
        assert "originalRelativeFilePath" not in options["return"]
        if "path" in args["from"]:
            return {
                "return": [{
                    "id": sound_id,
                    "name": "Voice",
                    "type": "Sound",
                    "path": r"\Actor-Mixer Hierarchy\Default Work Unit\Voice",
                    "activeSource": {"id": source_id},
                }]
            }
        return {
            "return": [{
                "id": source_id,
                "name": "Voice",
                "type": "AudioFileSource",
                "path": r"\Actor-Mixer Hierarchy\Default Work Unit\Voice\Voice",
                "parent": {"id": sound_id},
                "originalFilePath": r"Y:\Documents\case\Originals\Voice.wav",
                "audioSource:language": "English(US)",
            }]
        }

    record = ClosedDirectCliBackend(call).read_object(
        r"\Actor-Mixer Hierarchy\Default Work Unit\Voice"
    )

    assert record is not None
    assert record.source_path == str(source_file.resolve())
    assert record.source_sha256 == hashlib.sha256(
        b"reviewed-wine-source"
    ).hexdigest()


def test_oracle_context_localizes_wine_project_paths_and_requires_exact_target(
    tmp_path: Path,
) -> None:
    host_home = Path.home().resolve(strict=False)
    target = host_home / "waapi-cli-runtime-v3" / "case" / "project" / "SampleProject.wproj"
    relative = target.relative_to(host_home).as_posix().replace("/", "\\")
    y_path = "Y:\\" + relative
    context = {
        "info": {"version": {"year": 2022, "major": 1}},
        "project": {"path": y_path},
    }

    _assert_backend_context(context, version="2022.1", project_path=target)
    assert _localize_waapi_host_path(y_path, field="test") == target

    for missing_or_open_project in ({}, {"path": None}, {"path": 17}):
        with pytest.raises(CliRuntimeError, match="lacks a usable project path"):
            _assert_backend_context(
                {
                    "info": {"version": {"year": 2022, "major": 1}},
                    "project": missing_or_open_project,
                },
                version="2022.1",
                project_path=target,
            )

    with pytest.raises(CliRuntimeError, match="must be an absolute host path"):
        _assert_backend_context(
            {
                "info": {"version": {"year": 2022, "major": 1}},
                "project": {"path": "relative/SampleProject.wproj"},
            },
            version="2022.1",
            project_path=target,
        )

    # Matching basenames are not identity evidence: the oracle must be bound
    # to this case's exact migrated target, not any SampleProject.wproj.
    wrong_relative = (
        host_home / "waapi-cli-runtime-v3" / "case" / "business-host" / "SampleProject.wproj"
    ).relative_to(host_home).as_posix().replace("/", "\\")
    with pytest.raises(CliRuntimeError, match="wrong project"):
        _assert_backend_context(
            {
                "info": {"version": {"year": 2022, "major": 1}},
                "project": {"path": "Y:\\" + wrong_relative},
            },
            version="2022.1",
            project_path=target,
        )

    z_path = "Z:" + str(
        tmp_path / "case" / "project" / "SampleProject.wproj"
    ).replace("/", "\\")
    z_target = (
        tmp_path / "case" / "project" / "SampleProject.wproj"
    )
    assert _localize_waapi_host_path(z_path, field="test") == z_target
    _assert_backend_context(
        {
            "info": {"version": {"year": 2022, "major": 1}},
            "project": {"projectPath": z_path},
        },
        version="2022.1",
        project_path=z_target,
    )
    with pytest.raises(CliRuntimeError, match="unmappable Wine drive"):
        _localize_waapi_host_path("X:\\case\\SampleProject.wproj", field="test")


def test_waapi_host_path_localizer_rejects_escape_unc_relative_and_symlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account_home = tmp_path / "account-home"
    account_home.mkdir()
    monkeypatch.setattr(
        cli_runtime,
        "pwd",
        SimpleNamespace(
            getpwuid=lambda _uid: SimpleNamespace(pw_dir=str(account_home))
        ),
    )

    for value in (
        r"Y:\..\outside.wav",
        r"Y:\case\.\Voice.wav",
        r"Y:\\absolute.wav",
        r"Z:\..\etc\passwd",
        r"X:\case\Voice.wav",
        r"\\server\share\Voice.wav",
        "relative/Voice.wav",
        "~/Voice.wav",
    ):
        with pytest.raises(CliRuntimeError):
            _localize_waapi_host_path(value, field="test source")

    outside = tmp_path / "outside"
    outside.mkdir()
    (account_home / "escape").symlink_to(outside, target_is_directory=True)
    with pytest.raises(CliRuntimeError, match="symlink component"):
        _localize_waapi_host_path(
            r"Y:\escape\Voice.wav",
            field="test source",
        )


def test_no_runtime_subprocess_or_shell_escape_surface_is_present() -> None:
    source = (
        REPO_ROOT / "tests" / "semantic" / "support" / "codex_cli_runtime_v3.py"
    ).read_text(encoding="utf-8")
    assert "subprocess" not in source
    assert "shell=True" not in source
    assert "os.system" not in source
