from __future__ import annotations

import importlib
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.destructive.support.sandbox_fixture import hash_project
from tests.destructive.support import exact_real_evidence
from tests.support.platform_filesystem import create_symlink_or_skip


@pytest.fixture
def workflow(monkeypatch):
    monkeypatch.setenv("WWISE_LIVE", "1")
    monkeypatch.setenv("WWISE_DESTRUCTIVE", "1")
    return importlib.import_module("tests.destructive.test_gateway_workflow_transaction_matrix")


def _source(root: Path) -> Path:
    root.mkdir()
    (root / "SampleProject.wproj").write_bytes(b"project")
    (root / "Music.wwu").write_bytes(b"workunit")
    media = root / "Originals" / "music.wav"
    media.parent.mkdir()
    media.write_bytes(b"original media")
    return media


def test_full_source_hash_detects_media_tamper_with_identical_size_and_mtime(tmp_path, workflow):
    root = tmp_path / "source"
    media = _source(root)
    before = workflow._hash_mutation_bearing_project_files(root)
    metadata_before = workflow._source_tree_inventory(root)
    info = media.stat()
    media.write_bytes(b"modified media")
    os.utime(media, ns=(info.st_atime_ns, info.st_mtime_ns))
    assert media.stat().st_size == info.st_size
    assert workflow._source_tree_inventory(root) == metadata_before
    after = workflow._hash_mutation_bearing_project_files(root)
    assert before[1:] == after[1:]
    assert before[0] != after[0]


def test_full_source_hash_counts_all_files_and_matches_existing_full_digest(tmp_path, workflow):
    root = tmp_path / "source"
    _source(root)
    (root / "notes.txt").write_bytes(b"non-project content")
    expected = hash_project(root, preferred_strategy="full")
    observed = workflow._hash_mutation_bearing_project_files(root)
    assert observed == (expected.digest, 4, expected.bytes_hashed)
    assert workflow._hash_mutation_bearing_project_files(root) == observed


@pytest.mark.parametrize("target_is_directory", (False, True))
def test_full_source_hash_rejects_links_before_reading_content(tmp_path, workflow, monkeypatch, target_is_directory):
    root = tmp_path / "source"
    _source(root)
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside if target_is_directory else outside / "media.wav"
    if not target_is_directory:
        target.write_bytes(b"outside")
    create_symlink_or_skip(root / "link", target, target_is_directory=target_is_directory)
    monkeypatch.setattr(os, "open", lambda *_args, **_kwargs: pytest.fail("link must stop before content reads"))
    with pytest.raises(workflow.SandboxFixtureError, match="link|reparse"):
        workflow._hash_mutation_bearing_project_files(root)


@pytest.mark.parametrize("bound", ("SOURCE_HASH_MAX_FILES", "SOURCE_HASH_MAX_BYTES"))
def test_full_source_hash_preflights_bounds_before_content_reads(tmp_path, workflow, monkeypatch, bound):
    root = tmp_path / "source"
    _source(root)
    monkeypatch.setattr(workflow, bound, 1, raising=False)
    monkeypatch.setattr(os, "open", lambda *_args, **_kwargs: pytest.fail("bounds must stop before content reads"))
    with pytest.raises(workflow.SandboxFixtureError, match="bound"):
        workflow._hash_mutation_bearing_project_files(root)


def test_full_source_hash_rejects_linked_root(tmp_path, workflow):
    source = tmp_path / "source"
    _source(source)
    linked = tmp_path / "linked"
    create_symlink_or_skip(linked, source, target_is_directory=True)
    with pytest.raises(workflow.SandboxFixtureError, match="link|reparse"):
        workflow._hash_mutation_bearing_project_files(linked)


def test_full_source_hash_rejects_windows_reparse_metadata(tmp_path, workflow, monkeypatch):
    source = tmp_path / "source"
    _source(source)
    lstat = Path.lstat

    def marked_root(path, *args, **kwargs):
        info = lstat(path, *args, **kwargs)
        return (SimpleNamespace(st_mode=info.st_mode, st_file_attributes=0x400)
                if path == source else info)

    monkeypatch.setattr(Path, "lstat", marked_root)
    with pytest.raises(workflow.SandboxFixtureError, match="reparse"):
        workflow._hash_mutation_bearing_project_files(source)


def _fixture_run(tmp_path, workflow, monkeypatch, *, tamper_on_shutdown=False):
    source = tmp_path / "source"
    media = _source(source)
    events, records = [], []
    lock_root = tmp_path / "sandboxes"
    lock_root.mkdir()
    task_root = tmp_path / "task"
    task_root.mkdir()

    class Lock:
        def __init__(self, root):
            self.root = root

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            events.append("release")

    def prepare(_env, *, sandbox_root, hash_strategy):
        assert hash_strategy == "bounded"  # Copy audit is separate from the full guard.
        copied = sandbox_root / "copy"
        copied.mkdir(parents=True)
        project = copied / "SampleProject.wproj"
        project.write_bytes(b"project")
        return SimpleNamespace(
            source_root=source, source_project=source / "SampleProject.wproj",
            sandbox_path=copied, sandbox_root=sandbox_root, sandbox_project=project,
            env={}, metadata=SimpleNamespace(
                selected_port=7312, launch_project_path=str(project),
                get_info_display_name="WwiseConsole", get_info_version="2023.1",
                process_cleanup_result="cleaned", process_cleanup_details={"residual_processes": []},
            ),
        )

    def launch(*_args, **_kwargs):
        events.append("launch")
        return SimpleNamespace(host="127.0.0.1", port=7312)

    def shutdown(*_args):
        events.append("shutdown")
        if tamper_on_shutdown:
            info = media.stat()
            media.write_bytes(b"modified media")
            os.utime(media, ns=(info.st_atime_ns, info.st_mtime_ns))

    def append(**record):
        events.append("record:" + record["invocation"]["phase"])
        records.append(record)

    def quarantine(sandbox, **_kwargs):
        destination = tmp_path / "quarantine"
        sandbox.sandbox_path.rename(destination)
        return destination

    monkeypatch.setenv("WWISE_VERSION", "2023.1")
    monkeypatch.setattr(workflow, "_safe_lock_root", lambda _env: lock_root)
    monkeypatch.setattr(workflow, "LiveSandboxLock", Lock)
    monkeypatch.setattr(workflow, "exact_git_candidate", lambda _root: "a" * 40)
    monkeypatch.setattr(workflow, "prepare_sample_project_sandbox", prepare)
    monkeypatch.setattr(workflow, "launch_sandboxed_wwise", launch)
    monkeypatch.setattr(workflow, "shutdown_sandboxed_wwise", shutdown)
    monkeypatch.setattr(exact_real_evidence, "exact_transaction_outcomes", lambda _path: [])
    monkeypatch.setattr(exact_real_evidence, "cleanup_sandbox", quarantine)
    monkeypatch.setattr(exact_real_evidence, "append_category_evidence", append)
    item = SimpleNamespace(
        path=workflow.__file__, nodeid="tests/native.py::test_source",
        _waapi_phase_reports={"setup": "passed", "call": "passed"},
    )
    request = SimpleNamespace(module=workflow, session=SimpleNamespace(items=[item]))
    factory = SimpleNamespace(mktemp=lambda _name: task_root)
    return workflow.workflow_sandbox_runtime.__wrapped__(request, factory), events, records


@pytest.mark.parametrize("tamper", (False, True))
def test_source_full_guard_runs_after_shutdown_and_before_final_pass(tmp_path, workflow, monkeypatch, tamper):
    fixture, events, records = _fixture_run(
        tmp_path, workflow, monkeypatch, tamper_on_shutdown=tamper,
    )
    next(fixture)
    if tamper:
        with pytest.raises(AssertionError, match="source hash changed"):
            next(fixture)
    else:
        with pytest.raises(StopIteration):
            next(fixture)
    assert events.index("shutdown") < events.index("record:final")
    final = records[-1]
    assert final["invocation"]["outcome"] == ("FAIL" if tamper else "PASS")
    source = final["source"]
    assert source["hash_scope"] == "all-source-regular-file-content"
    assert source["hash_algorithm"] == "sha256"
    assert source["file_count_before"] == source["file_count_after"] == 3
    assert source["bytes_hashed_before"] == source["bytes_hashed_after"] == 29
    assert (source["hash_before"] == source["hash_after"]) is (not tamper)
    assert source["tree_metadata_before"] == source["tree_metadata_after"]


def test_source_hash_bound_stops_fixture_before_launch(tmp_path, workflow, monkeypatch):
    fixture, events, records = _fixture_run(tmp_path, workflow, monkeypatch)
    monkeypatch.setattr(workflow, "SOURCE_HASH_MAX_BYTES", 1)
    with pytest.raises(workflow.SandboxFixtureError, match="bound"):
        next(fixture)
    assert "launch" not in events
    assert "release" in events
    assert records == []


@pytest.mark.parametrize("after_read", (False, True))
def test_full_source_hash_rejects_changed_open_file_identity(
    tmp_path, workflow, monkeypatch, after_read,
):
    root = tmp_path / "source"
    _source(root)
    original_fstat = os.fstat
    calls = 0

    def switched_identity(descriptor):
        nonlocal calls
        calls += 1
        info = original_fstat(descriptor)
        fields = {name: getattr(info, name) for name in (
            "st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns", "st_ctime_ns",
        )}
        if calls == (2 if after_read else 1):
            fields["st_ino"] += 1
        return SimpleNamespace(**fields)

    monkeypatch.setattr(os, "fstat", switched_identity)
    with pytest.raises(workflow.SandboxFixtureError, match="changed.*hashing"):
        workflow._hash_mutation_bearing_project_files(root)


def _curve_probe_runtime(tmp_path, workflow, *, version="2025.1", curve_query_error=False,
                         repeat_names_page=False):
    import json
    import uuid

    state = tmp_path / "state"
    evidence = tmp_path / "dispatcher"
    evidence.mkdir()
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"wwise_version": version, "waapi_host": "127.0.0.1",
                                  "waapi_port": 31337, "project_modification_policy": "read_only"}))
    commands = []
    owner = "{11111111-1111-1111-1111-111111111111}"
    curve = "{22222222-2222-2222-2222-222222222222}"

    def gateway(command):
        command = list(command)
        commands.append(command)
        assert command[0] in {"config-show", "status", "metadata", "query-object", "query-schema"}
        payload = {"ok": True, "fixture_only": True, "detected_version": version,
                   "endpoint": {"host": "127.0.0.1", "port": 31337, "url": "ws://127.0.0.1:31337/waapi"}}
        if command[:2] == ["metadata", "types"]:
            payload["agent_result"] = {"complete": True, "types": [
                {"name": "RTPC", "type": "WObject", "classId": 655360, "selection": "rtpc-type"},
                {"name": "Curve", "type": "WObject", "classId": 917520, "selection": "curve-type"},
            ]}
        elif command[:2] == ["metadata", "list"]:
            payload["agent_result"] = {"complete": not repeat_names_page, "fields": [
                {"name": "Curve", "selection": "selected-Curve"},
            ]}
            if repeat_names_page:
                payload["agent_result"]["next_command"] = {"gateway_argv": command + ["--page", "fixture-page"]}
        elif command[:2] == ["metadata", "detail"]:
            assert command[-2:] == ["--selection", "selected-Curve"]
            payload["agent_result"] = {"complete": True, "metadata": {
                # Preserve genuine omission of optional name/type in the result.
                "restriction": {"type": "reference", "restrictions": [{"type": ["Curve"]}]},
                "nativeOptionalNull": None,
            }}
        elif command[0] == "query-object":
            if "--advanced-waql" in command or "--exact-id" in command:
                if "--advanced-waql" in command:
                    assert command[2] == f'from object "{owner}" select @Curve'
                    assert command[command.index("--max-results") + 1] == "1"
                else:
                    assert command[2] == curve
                if curve_query_error:
                    return 2, {"ok": False, "error_code": "fixture-native-unavailable",
                               "native_observation": {"fixture_only": True}}
                payload["objects"] = [{"id": curve, "name": "", "type": "Curve", "path": "\\Curve",
                                       "class_id": 917520, "curve_points": [{"x": 0, "y": -6, "shape": "Linear"}]}]
            else:
                assert command == ["query-object", "--type-selection", "rtpc-type", "--max-results", "2"]
                payload["objects"] = [{"id": owner, "name": "", "type": "RTPC", "path": "\\RTPC"}]
        (evidence / (uuid.uuid4().hex + ".json")).write_text(json.dumps({"fixture_only": True,
                                            "command": command, "result": payload}))
        return 0, payload

    return SimpleNamespace(state_dir=state, env={"WWISE_EVIDENCE_DIR": str(evidence),
                          "WAAPI_SKILL_CONFIG_PATH": str(config)}, version=version,
                          candidate="a" * 40, lifecycle=SimpleNamespace(host="127.0.0.1", waapi_url="ws://127.0.0.1:31337/waapi"),
                          port=31337, category_results=[], raw_gateway=gateway), commands


@pytest.mark.parametrize("version", ["2021.1", "2022.1", "2023.1", "2024.1", "2025.1"])
def test_curve_probe_retains_exact_read_only_observations_without_native_launch(
    tmp_path, workflow, version,
):
    import hashlib
    import json
    from wwise_waapi.object_query_outputs import available_query_outputs

    runtime, commands = _curve_probe_runtime(tmp_path, workflow, version=version)
    category = workflow._collect_rtpc_curve_metadata_probe(runtime)
    observed = json.loads(Path(category["observation_path"]).read_text())
    # Collector fixture only; no real category publisher ran.
    assert category["status"] == ("blocked" if version == "2021.1" else "PASS")
    assert observed["candidate"] == "a" * 40 and observed["version"] == version
    assert ("curve-points" in available_query_outputs(version)) is (version != "2021.1")
    if version == "2021.1":
        assert "curve-points" not in commands[-1]
        assert any(row["reason"] == "curve_points_output_unavailable_in_public_version" for row in observed["boundaries"])
    assert observed["mutation_authority"] is False and observed["business_effect_verified"] is False
    details = [row for row in observed["calls"] if row["stage"].endswith("-detail")]
    assert len(details) == 2
    for row in details:
        metadata = row["payload"]["agent_result"]["metadata"]
        assert "name" not in metadata and "type" not in metadata
        assert metadata["nativeOptionalNull"] is None
    assert details[0]["gateway_argv"][2:4] == ["--type-selection", "rtpc-type"]
    assert details[1]["gateway_argv"][2:4] == ["--exact-id", "{11111111-1111-1111-1111-111111111111}"]
    assert len(observed["native_evidence"]) == len(commands)
    assert hashlib.sha256(Path(category["observation_path"]).read_bytes()).hexdigest() == category["observation_sha256"]
    assert all(Path(row["path"]).is_file() for row in observed["native_evidence"])


def test_curve_probe_records_failed_public_curve_read_as_boundary(tmp_path, workflow):
    import json
    runtime, _commands = _curve_probe_runtime(tmp_path, workflow, curve_query_error=True)
    category = workflow._collect_rtpc_curve_metadata_probe(runtime)
    observed = json.loads(Path(category["observation_path"]).read_text())
    assert category["status"] == "blocked"
    assert any(row.get("error_code") == "fixture-native-unavailable" for row in observed["boundaries"])
    assert observed["calls"][-1]["payload"]["native_observation"] == {"fixture_only": True}


def test_curve_probe_stops_incomplete_name_paging_at_owned_bound(tmp_path, workflow):
    import json
    runtime, commands = _curve_probe_runtime(tmp_path, workflow, repeat_names_page=True)
    category = workflow._collect_rtpc_curve_metadata_probe(runtime)
    observed = json.loads(Path(category["observation_path"]).read_text())
    assert category["status"] == "blocked"
    assert any(row["reason"] == "eight_page_bound_reached" for row in observed["boundaries"])
    assert len([command for command in commands if command[:2] == ["metadata", "list"]]) == 16
    assert not any(command[:2] == ["metadata", "detail"] for command in commands)


@pytest.mark.parametrize("version", ["2021.1", "2022.1", "2023.1", "2024.1", "2025.1"])
def test_curve_probe_reference_read_uses_existing_public_gateway_contract(tmp_path, workflow, version):
    from tests.unit.test_object_graph_business_gateway import _info

    runtime, _commands = _curve_probe_runtime(tmp_path, workflow, version=version)
    calls = []
    owner = "{11111111-1111-1111-1111-111111111111}"
    curve = "{22222222-2222-2222-2222-222222222222}"

    class Client:
        def call(self, uri, args=None, options=None):
            calls.append((uri, args, options))
            if uri == "ak.wwise.core.getInfo":
                return _info(version)
            assert uri == "ak.wwise.core.object.get", (uri, args, options)
            assert args == {"waql": f'from object "{owner}" select @Curve take 1'}
            assert options["return"] == ["id", "name", "type", "path", "classId", *(["points"] if version != "2021.1" else [])]
            return {"return": [{"id": curve, "name": "", "type": "Curve", "path": "\\Curve",
                                "classId": 917520, "points": [{"x": 0, "y": -6, "shape": "Linear"}]}]}

        def disconnect(self):
            pass

    code, payload = workflow.waapi_gateway.execute_gateway([
        "--state-dir", str(runtime.state_dir), "query-object", "--advanced-waql",
        f'from object "{owner}" select @Curve', "--max-results", "1", "--include", "class-id",
        *(["--include", "curve-points"] if version != "2021.1" else []),
    ], env=runtime.env, client_factory=lambda _url: Client())
    assert code == 0, payload
    assert payload["objects"][0]["id"] == curve and payload["objects"][0]["type"] == "Curve"
    if version != "2021.1":
        assert payload["objects"][0]["curve_points"] == [{"x": 0, "y": -6, "shape": "Linear"}]
    assert all(uri in {"ak.wwise.core.getInfo", "ak.wwise.core.object.get"} for uri, _args, _options in calls)


def _owned_probe_runtime(tmp_path, workflow, *, version="2025.1", missing_list=False, overflow=False):
    import json
    import uuid

    runtime, commands = _curve_probe_runtime(tmp_path, workflow, version=version)
    ids = {name: "{" + str(uuid.UUID(int=index)) + "}" for index, name in enumerate(
        ("sound", "rtpc", "bus", "effect", "music", "group", "slot"), start=1)}
    def row(name, kind, owner=None):
        return {"id": ids[name], "name": name, "type": kind, "path": "\\" + name,
                "parent": None, "owner": {"id": ids[owner]} if owner else None}
    sound, music = row("sound", "Sound"), row("music", "MusicSwitchContainer")
    rtpc, bus = row("rtpc", "RTPC", "sound"), row("bus", "Bus")
    effect = row("effect", "Effect" if version < "2023.1" else "EffectSlot", "sound")
    group, slot = row("group", "SwitchGroup"), row("slot", "MusicArgumentsSlot", "music")
    rows = {value["id"]: value for value in (sound, music, rtpc, bus, effect, group, slot)}
    effect_field = "Effect0" if version < "2023.1" else "Effects"
    hops = {(ids["sound"], "OutputBus"): [bus], (ids["sound"], "RTPC"): [rtpc],
            (ids["sound"], effect_field): [effect], (ids["music"], "Arguments"): [slot if version == "2025.1" else group],
            (ids["slot"], "Argument"): [group]}

    def gateway(command):
        command = list(command)
        commands.append(command)
        assert command[0] in {"config-show", "status", "metadata", "query-object", "query-schema"}
        payload = {"ok": True, "detected_version": version,
                   "endpoint": {"host": "127.0.0.1", "port": 31337, "url": "ws://127.0.0.1:31337/waapi"}}
        if command[:2] == ["metadata", "types"]:
            payload["agent_result"] = {"complete": True, "types": [
                {"name": kind, "selection": kind + "-type"} for kind in ("Sound", "MusicSwitchContainer", "RTPC")]}
        elif command[:2] == ["metadata", "list"]:
            fields = ["OutputBus", effect_field, *([] if missing_list else ["RTPC"])] if command[3] == ids["sound"] else (
                ["Arguments"] if command[3] == ids["music"] else ["Argument"])
            payload["agent_result"] = {"complete": True, "fields": [{"name": name, "selection": name + "-field"} for name in fields]}
        elif command[:2] == ["metadata", "detail"]:
            payload["agent_result"] = {"complete": True, "metadata": {"restriction": {"type": "reference"}, "fixtureOptional": None}}
        elif command[0] == "query-object":
            if "--exact-id" in command:
                found = [rows[command[command.index("--exact-id") + 1]]]
            elif "--type-selection" in command:
                found = [music if command[2] == "MusicSwitchContainer-type" else sound]
            else:
                expression = command[command.index("--advanced-waql") + 1]
                if expression.startswith("from type RTPC"):
                    found = [sound]
                elif expression.startswith("from project where owner.id"):
                    found = [rtpc, effect] if ids["sound"] in expression else ([slot] if version == "2025.1" else [])
                else:
                    owner = expression.split('"')[1]
                    field = expression.split("select @")[1]
                    found = hops[owner, field]
                    if overflow and field == "RTPC":
                        found = found * 5
            payload.update(objects=found, limit_reached=len(found) == int(command[command.index("--max-results") + 1])
                           if "--max-results" in command else False)
        path = Path(runtime.env["WWISE_EVIDENCE_DIR"]) / (uuid.uuid4().hex + ".json")
        path.write_text(json.dumps({"fixture_only": True, "command": command, "result": payload}))
        return 0, payload

    runtime.raw_gateway = gateway
    return runtime, commands, ids


@pytest.mark.parametrize("version", ["2021.1", "2022.1", "2023.1", "2024.1", "2025.1"])
def test_owned_list_probe_retains_sample_only_graph_and_fresh_metadata(tmp_path, workflow, version):
    import json
    runtime, commands, ids = _owned_probe_runtime(tmp_path, workflow, version=version)
    category = workflow._collect_owned_list_metadata_probe(runtime)
    observed = json.loads(Path(category["observation_path"]).read_text())
    assert category["status"] == "PASS", observed
    assert observed["complete_owned_list_discovery_proven"] is False
    assert observed["field_cardinality_permission_proven"] is False
    assert observed["mutation_authority"] is False
    assert observed["owner_comparisons"][0]["missing_known_owned_ids"] == []
    assert observed["native_evidence"] and observed["calls"]
    details = [call for call in observed["calls"] if call["gateway_argv"][:2] == ["metadata", "detail"]]
    assert "name" not in details[0]["payload"]["agent_result"]["metadata"]
    assert "type" not in details[0]["payload"]["agent_result"]["metadata"]
    assert all("Curve" not in " ".join(command) for command in commands)
    if version == "2025.1":
        assert any(f'from object "{ids["slot"]}" select @Argument' in command for command in commands)
    else:
        assert not any(part.endswith("select @Argument") for command in commands for part in command)


@pytest.mark.parametrize("fault", ("missing-list", "row-overflow", "metadata-error", "paging-overflow", "owner-filter"))
def test_owned_list_probe_keeps_incomplete_observation_blocked(tmp_path, workflow, fault):
    import json
    runtime, commands, ids = _owned_probe_runtime(tmp_path, workflow,
        missing_list=fault == "missing-list", overflow=fault == "row-overflow")
    original = runtime.raw_gateway

    def gateway(command):
        code, payload = original(command)
        if fault == "metadata-error" and list(command[:2]) == ["metadata", "detail"]:
            return 2, {"ok": False, "error_code": "fixture-metadata-rejected", "original_raw_error": {"fixture": None}}
        if fault == "paging-overflow" and list(command[:2]) == ["metadata", "list"]:
            payload["agent_result"].update(complete=False, next_command={"gateway_argv": list(command)})
        if fault == "owner-filter" and any(str(value).startswith("from project where owner.id") for value in command):
            payload["objects"][0]["owner"] = None
        return code, payload

    runtime.raw_gateway = gateway
    category = workflow._collect_owned_list_metadata_probe(runtime)
    observed = json.loads(Path(category["observation_path"]).read_text())
    assert category["status"] == "blocked", observed
    expected = {"missing-list": "field_not_uniquely_listed_gateway_discovery_boundary",
                "row-overflow": "query_row_bound_reached", "metadata-error": "public_read_rejected",
                "paging-overflow": "metadata_page_bound_reached", "owner-filter": "owner_filter_readback_mismatch"}[fault]
    assert any(row["reason"] == expected for row in observed["boundaries"])
    assert len(commands) <= 96 and len(observed["calls"]) == len(commands)
    if fault == "missing-list":
        assert not any(command[-1] == "RTPC-field" for command in commands)
        assert any(f'from object "{ids["sound"]}" select @RTPC' in command for command in commands)
    if fault == "metadata-error":
        assert any(row["payload"].get("original_raw_error") == {"fixture": None} for row in observed["calls"])


@pytest.mark.parametrize("version", ["2021.1", "2022.1", "2023.1", "2024.1", "2025.1"])
def test_owned_probe_reads_use_existing_public_gateway_with_owned_projection(tmp_path, workflow, version):
    from tests.unit.test_object_graph_business_gateway import _info

    runtime, _commands, ids = _owned_probe_runtime(tmp_path, workflow, version=version)
    effect = "Effect0" if version < "2023.1" else "Effects"
    expressions = ['from type RTPC select owner where type = "Sound"',
                   f'from object "{ids["sound"]}" select @RTPC',
                   f'from object "{ids["sound"]}" select @OutputBus',
                   f'from object "{ids["sound"]}" select @{effect}',
                   f'from project where owner.id = "{ids["sound"]}"']
    if version >= "2023.1":
        expressions.append(f'from object "{ids["music"]}" select @Arguments')
    if version == "2025.1":
        expressions.append(f'from object "{ids["slot"]}" select @Argument')
    observed = []

    class Client:
        def call(self, uri, args=None, options=None):
            if uri == "ak.wwise.core.getInfo":
                return _info(version)
            assert uri == "ak.wwise.core.object.get", (uri, args, options)
            observed.append(args["waql"])
            assert options["return"] == ["id", "name", "type", "path", "parent", "owner"]
            return {"return": [{"id": ids["rtpc"], "name": "", "type": "RTPC", "path": "\\RTPC",
                                "parent": None, "owner": {"id": ids["sound"]}}]}

        def disconnect(self):
            pass

    for expression in expressions:
        code, payload = workflow.waapi_gateway.execute_gateway([
            "--state-dir", str(runtime.state_dir), "query-object", "--advanced-waql", expression,
            "--max-results", "5", "--include", "parent", "--include", "owner"],
            env=runtime.env, client_factory=lambda _url: Client())
        assert code == 0, payload
        rows = payload.get("objects", payload.get("agent_result"))
        assert rows[0]["owner"]["id"] == ids["sound"] and rows[0]["parent"] is None
    assert observed == [expression + " take 5" for expression in expressions]
