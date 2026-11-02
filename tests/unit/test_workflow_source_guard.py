"""Source/lifecycle protections and representative developer collector wiring.

Gateway business suites own exhaustive request/version validation. Collector
variants retain their distinct independent observations and durable receipts;
only representative cases replay the category finalizer.
"""
from __future__ import annotations

import importlib
import json
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


def _new_result_reference_runtime(tmp_path, workflow, version, *, fault=None, noisy_fields=False, native_conditions=False, compound_exact_rename_history=False):
    """The real public Gateway above an exact, independently mutated native tree."""
    from copy import deepcopy
    import uuid
    from tests.unit.test_object_graph_owned_choices_gateway import OwnedGraphTask

    operation = "object.create" if version == "2021.1" or compound_exact_rename_history else "object.set"
    task = OwnedGraphTask(tmp_path, version, operation)
    parent = "{ABABABAB-ABAB-ABAB-ABAB-ABABABABABAB}"
    root, target, source = ("{" + str(uuid.UUID(int=value)) + "}" for value in (3, 5, 6))
    task.types = [{"name": name, "classId": value, "type": "WObject"} for name, value in (
        ("WorkUnit", 1638416), ("Bus", 1376272), ("AuxBus", 3997712))]
    parent_path = (r"\Busses\Default Work Unit" if version == "2025.1"
                   else r"\Master-Mixer Hierarchy\Default Work Unit")
    task.objects = {parent: {"id": parent, "name": "Default Work Unit", "type": "WorkUnit", "classId": 1638416,
        "path": parent_path, "parent": None, "notes": "Keep parent"}}
    commands, writes = [], []
    independent_read = False
    original = task.call
    base = parent_path + r"\WAAPI_RESULT_REFERENCE_TEST"
    # Exact names from the owned 2025 receipt; target metadata below stays a unit fixture.
    task.reference_field_names = [
        'Attenuation', '3DPosition', '3DSpatialization', 'AttenuationDistanceScaling',
        'BusChannelConfig', 'BusVolume', 'BypassEffect', 'CenterPercentage',
        'Color', 'EnableAttenuation', 'EnableDiffraction', 'GameAuxSendHPF',
        'GameAuxSendDSF', 'GameAuxSendLPF', 'GameAuxSendVolume', 'Highpass',
        'HoldEmitterPositionOrientation', 'HoldListenerOrientation', 'ListenerRelativeRouting', 'Lowpass',
        'OutputBusHighpass', 'OutputBusDualshelf', 'OutputBusLowpass', 'OutputBusVolume',
        'OverrideColor', 'Pitch', 'ReflectionsVolume', 'SpeakerPanning',
        'SpeakerPanning3DSpatializationMix', 'UseGameAuxSends', 'UserAuxSendHPF0', 'UserAuxSendHPF1',
        'UserAuxSendHPF2', 'UserAuxSendHPF3', 'UserAuxSendLPF0', 'UserAuxSendLPF1',
        'UserAuxSendLPF2', 'UserAuxSendLPF3', 'UserAuxSendVolume0', 'UserAuxSendVolume1',
        'UserAuxSendVolume2', 'UserAuxSendVolume3', 'Volume', 'ReflectionsAuxSend',
        'UserAuxSend0', 'UserAuxSend1', 'UserAuxSend2', 'UserAuxSend3',
    ] if noisy_fields else ["UserAuxSend0"]

    history = {}
    def call(uri, args=None, options=None):
        nonlocal base
        if compound_exact_rename_history:
            if uri.endswith('getProjectInfo'):
                platform = '{44444444-4444-4444-4444-444444444444}'
                return {**original(uri, args, options), 'currentPlatformId': platform,
                    'platforms': [{'id': platform, 'name': 'Windows'}]}
            if uri in {'ak.wwise.core.undo.beginGroup', 'ak.wwise.core.undo.endGroup', 'ak.wwise.core.undo.cancelGroup',
                    'ak.wwise.core.undo.undo', 'ak.wwise.core.undo.redo'}:
                task.calls.append((uri, deepcopy(args), deepcopy(options))); writes.append((uri, deepcopy(args), deepcopy(options)))
                if uri.endswith('.beginGroup'): history['before'] = deepcopy(task.objects)
                elif uri.endswith('.endGroup'): history['after'] = deepcopy(task.objects)
                elif uri.endswith(('.undo', '.cancelGroup')): task.objects = deepcopy(history['before'])
                else: task.objects = deepcopy(history['after'])
                return {}
            if uri.endswith('object.setNotes'):
                task.calls.append((uri, deepcopy(args), deepcopy(options))); writes.append((uri, deepcopy(args), deepcopy(options)))
                task.objects[args['object']]['notes'] = args['value']
                return {}
            if uri.endswith('object.set'):
                task.calls.append((uri, deepcopy(args), deepcopy(options))); writes.append((uri, deepcopy(args), deepcopy(options)))
                node, = args['objects']; assert args['onNameConflict'] == 'fail'
                row = task.objects[node['object']]; old = row['path']
                assert not any(other['id'] != row['id'] and other['name'] == node['name']
                    and other.get('parent') == row.get('parent') for other in task.objects.values())
                row.update(name=node['name'], path=old.rsplit('\\', 1)[0] + '\\' + node['name'])
                for child in task.objects.values():
                    if child['path'].startswith(old + '\\'): child['path'] = row['path'] + child['path'][len(old):]
                return {'objects': [{'id': row['id'], 'name': row['name']}]}
            if uri.endswith('object.create') and not args.get('children'):
                task.calls.append((uri, deepcopy(args), deepcopy(options))); writes.append((uri, deepcopy(args), deepcopy(options)))
                identity = '{' + str(uuid.UUID(int=100 + len(writes))).upper() + '}'
                task.objects[identity] = {'id': identity, 'name': args['name'], 'type': args['type'], 'classId': 1376272,
                    'path': task.objects[args['parent']]['path'] + '\\' + args['name'],
                    'parent': {'id': args['parent']}, 'notes': args.get('notes', '')}
                return {'id': identity, 'name': args['name']}
            if uri.endswith('object.get') and args.get('waql') != 'from type Project take 1':
                task.calls.append((uri, deepcopy(args), deepcopy(options)))
                if 'waql' in args:
                    import re
                    match = re.fullmatch(r'from object "([^"]+)"( select children)?(?: take (\d+))?', args['waql'])
                    assert match, args
                    selected = [row for row in task.objects.values() if match[1] in (row['id'], row['path'])]
                    transforms = [{'select': ['children']}] if match[2] else []
                else:
                    source_selector = args['from']
                    selected = [row for row in task.objects.values() if (row['id'] in source_selector['id']
                        if 'id' in source_selector else row['path'] in source_selector['path'])]
                    transforms = args.get('transform', [])
                for transform in transforms:
                    assert len(selected) == 1
                    if transform == {'select': ['children']}:
                        selected = [row for row in task.objects.values() if row.get('parent') == {'id': selected[0]['id']}]
                    else:
                        assert transform == {'select': ['descendants']}, transform
                        selected = [row for row in task.objects.values() if row['path'].startswith(selected[0]['path'] + '\\')]
                return {'return': task.project_rows(selected, options)}
        if (compound_exact_rename_history and uri.endswith('getPropertyAndReferenceNames')
                and task.objects.get(args.get('object'), {}).get('type') == 'Bus'):
            return original(uri, args, options)  # Existing base fake's object-scoped names; no Bus property is selected.
        if uri.endswith(("getPropertyAndReferenceNames", "getPropertyInfo")):
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            assert args.get("classId") == 3997712 or args.get("object") == source, args
            if uri.endswith("getPropertyAndReferenceNames"):
                return {"return": task.reference_field_names}
            if args["property"].startswith(("UserAuxSendHPF", "UserAuxSendLPF")):
                name = args["property"]
                band, index = ("HPF" if "HPF" in name else "LPF"), name[-1]
                return {"name": name, "type": "int16", "default": 0,
                    "display": {"name": "User-Defined Auxiliary " + band + " " + index},
                    "restriction": {"type": "range", "min": 0, "max": 100},
                    "dependencies": [{"action": "Show", "context": "Self", "type": "isMasterBus", "value": False},
                        {"action": "Enable", "context": "Self", "property": "OverrideUserAuxSends", "type": "override"}]}
            if native_conditions and args["property"] == "OverrideUserAuxSends":
                raise RuntimeError("Literal native 553: controller property does not exist on AuxBus")
            assert args["property"] == "UserAuxSend0", args
            if native_conditions:
                # Literal relevant 2025 native shape; older program lanes use their XML group grammar, not claimed native observations.
                return {"name": "UserAuxSend0", "type": "", "default": None,
                    "supports": {"unlink": False, "randomizer": False, "rtpc": "None"},
                    "display": {"name": "User-Defined Auxiliary Send 0"},
                    "restriction": {"type": "reference", "restrictions": [{"type": ["Auxiliary Bus"], "sharedOnlyTypes": []}]},
                    "dependencies": ([{"type": "isMasterBus", "value": False, "action": "Show", "context": "Self"}]
                        if version in {"2024.1", "2025.1"} else []) + [
                        {"type": "override", "action": "Enable", "context": "Self", "property": "OverrideUserAuxSends"}]}
            return {"name": "UserAuxSend0", "type": "Reference", "display": {"name": "User-Defined Auxiliary Send 0"},
                "restriction": {"type": "reference", "restrictions": [{"type": ["AuxBus"]}]}}
        if uri in {"ak.wwise.core.object.create", "ak.wwise.core.object.set"}:
            writes.append((uri, deepcopy(args), deepcopy(options)))
            children = [{"type": "AuxBus", "name": "Destination"},
                {"type": "AuxBus", "name": "Sender", "@UserAuxSend0": base + r"\Destination"}]
            if operation == "object.create":
                native_parent = args['parent'] if compound_exact_rename_history else parent
                if compound_exact_rename_history:
                    base = task.objects[native_parent]['path'] + r'\WAAPI_RESULT_REFERENCE_TEST'
                    children[1]['@UserAuxSend0'] = base + r'\Destination'
                assert args == {"parent": native_parent, "type": "Bus", "name": "WAAPI_RESULT_REFERENCE_TEST",
                    "children": children, "onNameConflict": "fail", "autoAddToSourceControl": False}
            else:
                assert args == {"objects": [{"object": parent, "children": [{"type": "Bus",
                    "name": "WAAPI_RESULT_REFERENCE_TEST", "children": children}]}], "onNameConflict": "fail",
                    "autoAddToSourceControl": False, "listMode": "append"}
            if fault == "native-error":
                raise RuntimeError("Frozen native graph rejection; never replay")
            task.objects[root] = {"id": root, "name": "WAAPI_RESULT_REFERENCE_TEST", "type": "Bus", "classId": 1376272,
                "path": base, "parent": {"id": args['parent'] if compound_exact_rename_history else parent}, "notes": ""}
            for identity, name in ((target, "Destination"), (source, "Sender")):
                task.objects[identity] = {"id": identity, "name": name, "type": "AuxBus", "classId": 3997712,
                    "path": base + "\\" + name, "parent": {"id": root}, "notes": ""}
            task.objects[source]["@UserAuxSend0"] = {"id": root if fault == "wrong-guid" else target}
            if native_conditions:
                if fault == "wrong-parent-effect":
                    task.objects[source]["parent"] = {"id": parent}
            result = {"id": root, "name": "WAAPI_RESULT_REFERENCE_TEST", "children": [
                {"id": target, "name": "Destination"}, {"id": source, "name": "Sender"}]}
            return result if operation == "object.create" else {"objects": [{"id": parent, "name": "Default Work Unit", "children": [result]}]}
        if uri.endswith("object.get") and args.get("waql", "").startswith('from object "') and not args["waql"].endswith(" take 1"):
            expression = args["waql"]
            identity = expression.split('"')[1]
            assert expression == f'from object "{identity}"', expression
            result = {"return": [deepcopy(row) for row in task.objects.values() if identity in {row["id"], row["path"]}]}
        else:
            result = original(uri, args, options)
        if uri.endswith("object.get") and args.get("waql") != "from type Project take 1":
            # Honor the literal native return projection, including reference spelling.
            rows = []
            for row in result["return"]:
                projected = {key: deepcopy(row.get(key, row.get("@" + key))) for key in options["return"]
                    if key in row or "@" + key in row}
                if independent_read and fault == "independent-path" and row["id"] == target:
                    projected["path"] = base + r"\NotRequested"
                if independent_read and fault == "independent-guid" and row["id"] == source and "UserAuxSend0" in projected:
                    projected["UserAuxSend0"] = {"id": root}
                if independent_read and fault == "independent-class" and row["id"] == target and "classId" in projected:
                    projected["classId"] = True
                if independent_read and fault == "independent-parent" and row["id"] == target and "parent" in projected:
                    projected["parent"] = {"id": parent}
                rows.append(projected)
            return {"return": rows}
        return result

    task.call = call
    runtime = SimpleNamespace(version=version, state_dir=tmp_path / "state", env=task.env,
        candidate="fixture-candidate", category_results=[])
    def raw(command):
        nonlocal independent_read
        commands.append(list(command))
        independent_read = command[0] == "query-object"
        return workflow.waapi_gateway.execute_gateway(["--state-dir", str(runtime.state_dir), *command],
            env=runtime.env, client_factory=lambda _url: task)
    if compound_exact_rename_history:
        runtime.port = 31337
        runtime.lifecycle = SimpleNamespace(host='127.0.0.1', waapi_url='ws://127.0.0.1:31337/waapi')
        runtime.env['WWISE_EVIDENCE_DIR'] = str(tmp_path / 'native-evidence')
        public_raw = raw
        def compound_raw(command):
            code, payload = public_raw(command)
            if command[0] == 'verify' and code == 0:
                if fault == 'independent-reference' and writes[-1][0].endswith('.endGroup'):
                    task.objects[source]['@UserAuxSend0'] = {'id': root}
                elif fault == 'independent-undo' and writes[-1][0].endswith('.undo'):
                    task.objects = deepcopy(history['after'])
            return code, payload
        runtime.raw_gateway = compound_raw
    else:
        runtime.raw_gateway = raw
    return runtime, commands, writes, task


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


def test_workflow_failure_captures_owned_process_before_cleanup_with_bounded_tails(tmp_path, workflow, monkeypatch):
    fixture, events, records = _fixture_run(tmp_path, workflow, monkeypatch)
    runtime = next(fixture)
    class OwnedProcess:
        pid = 123456
        def poll(self):
            events.append('owned-poll')
            return 17
    class Output:
        def tail(self, stream, max_lines=20):
            assert max_lines == 20
            events.append('tail:' + stream)
            return stream + ':' + '声音' * 6000
    runtime.lifecycle.process = OwnedProcess()
    runtime.lifecycle.output = Output()
    shutdown = workflow.shutdown_sandboxed_wwise
    def cleanup(*args):
        path = runtime.state_dir / 'workflow-pre-teardown-process.json'
        assert path.is_file(), 'pre-teardown diagnostics must exist before cleanup'
        observed = json.loads(path.read_text())
        assert observed['owned_launch_pid'] == 123456 and observed['observed_exit_code'] == 17
        assert observed['process_state'] == 'exited' and observed['phase'] == 'before_owned_shutdown'
        assert type(observed['captured_at_unix_ns']) is int
        for stream in ('stdout', 'stderr'):
            assert 0 < len(observed[stream + '_tail'].encode('utf-8')) <= 4096
            assert observed[stream + '_truncated'] is True
        events.append('diagnostic-exists')
        shutdown(*args)
    monkeypatch.setattr(workflow, 'shutdown_sandboxed_wwise', cleanup)
    original = RuntimeError('Original workflow failure remains the verdict')
    with pytest.raises(RuntimeError) as caught:
        fixture.throw(original)
    assert caught.value is original
    assert events.index('owned-poll') < events.index('diagnostic-exists') < events.index('shutdown') < events.index('release')
    assert records[-1]['invocation']['outcome'] == 'FAIL'


def test_workflow_diagnostic_capture_error_preserves_original_failure_and_cleanup(tmp_path, workflow, monkeypatch, capsys):
    fixture, events, records = _fixture_run(tmp_path, workflow, monkeypatch)
    next(fixture)
    def failed_capture(*args, **kwargs):
        events.append('capture-error')
        raise OSError('Diagnostic disk error')
    monkeypatch.setattr(workflow, '_capture_workflow_pre_teardown_process', failed_capture)
    original = RuntimeError('Original failure must survive diagnostic capture error')
    with pytest.raises(RuntimeError) as caught:
        fixture.throw(original)
    assert caught.value is original
    assert events.index('capture-error') < events.index('shutdown') < events.index('release')
    assert records[-1]['invocation']['outcome'] == 'FAIL'
    assert 'Diagnostic disk error' in capsys.readouterr().err


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


def _rtpc_graph_runtime(tmp_path, workflow, version='2025.1', *, fault=None, exclusive=True):
    """Actual Gateway; source-shaped native graph state, not native receipts."""
    from copy import deepcopy
    import uuid
    from tests.unit.test_unnamed_rtpc_graph_gateway import rtpc_task
    task, _ = rtpc_task(tmp_path, version)
    task.types.append({'name': 'ModulatorTime', 'classId': 5111824, 'type': 'WObject'})
    actor, parameters = ('{' + str(uuid.UUID(int=n)).upper() + '}' for n in (101, 102))
    actor_path = ('\\Containers' if version == '2025.1' else '\\Actor-Mixer Hierarchy') + '\\Default Work Unit'
    task.objects = {identity: {'id': identity, 'name': 'Default Work Unit', 'type': 'WorkUnit',
        'classId': 1638416, 'path': path, 'parent': None, 'notes': 'Keep work unit'}
        for identity, path in [(actor, actor_path), (parameters, r'\Game Parameters\Default Work Unit')]}
    task.metadata.update({
        'Min': {'name': 'Min', 'type': 'Real64', 'default': -10},
        'Max': {'name': 'Max', 'type': 'Real64', 'default': 90},
        'TimeModDuration': {'name': 'TimeModDuration', 'type': 'Real64', 'default': 1,
            'restriction': {'type': 'range', 'min': 0.1, 'max': 100}},
        'EnvelopeStopPlayback': {'name': 'EnvelopeStopPlayback', 'type': 'bool', 'default': True},
        'CenterPercentage': {'name': 'CenterPercentage', 'type': 'int32', 'default': 0,
            'supports': {'rtpc': 'Exclusive' if exclusive else 'None'},
            'restriction': {'type': 'range', 'min': 0, 'max': 100}}})
    task.metadata['ControlInput']['restriction']['restrictions'] = [
        {'type': ['ModulatorTime', 'ModulatorLfo', 'ModulatorEnvelope', 'GameParameter', 'MidiParameter']}]
    fields = {'Sound': ['Volume', 'Pitch', 'CenterPercentage'], 'GameParameter': ['Min', 'Max'],
        'RTPC': ['PropertyName', 'ControlInput', 'Curve'], 'Curve': [], 'WorkUnit': [],
        'ModulatorTime': ['TimeModDuration', 'EnvelopeStopPlayback']}
    if fault in {'names-overflow', 'paged-sound-fields'}:
        fields['Sound'] = ['Volume', 'Pitch', 'CenterPercentage'] + [f'Other{i:03}' for i in range(254 if fault == 'names-overflow' else 108)]
    original, writes, commands = task.call, [], []
    next_id = 201
    def allocate():
        nonlocal next_id
        next_id += 1
        return '{' + str(uuid.UUID(int=next_id)).upper() + '}'
    def create(node, parent, *, owned=False):
        matches = [row for row in task.objects.values() if row.get('parent') == {'id': parent}
            and row['name'] == node['name'] and row['type'] == node['type']]
        if matches and task.conflict != 'merge': raise ValueError('Native name collision requires selected merge')
        row = matches[0] if matches else None
        if row is None:
            if fault == 'replacement-nonlexicographic-guids' and owned and node['type'] == 'RTPC' and task.list_mode == 'replaceAll':
                identity = '{' + str(uuid.UUID(int=902 if node['@PropertyName'] == 'Volume' else 901)).upper() + '}'
            else:
                identity = allocate()
            row = {'id': identity, 'name': node['name'], 'type': node['type'],
                'classId': next(entry['classId'] for entry in task.types if entry['name'] == node['type']),
                'path': ('\\opaque-' + identity if owned else task.objects[parent]['path'] + '\\' + node['name']),
                'notes': node.get('notes', ''), **({'owner': {'id': parent}} if owned else {'parent': {'id': parent}})}
            if node['type'] == 'Sound':
                row.update({'@RTPC': [], '@Volume': 0, '@Pitch': 0, '@CenterPercentage': 0})
            if node['type'] == 'GameParameter':
                row.update({'@Min': -10 if node['name'].endswith('_A') else 20, '@Max': 90 if node['name'].endswith('_A') else 220})
                if fault == 'invalid-range': row['@Min'] = row['@Max']
            task.objects[identity] = row
        return apply(node, row)
    def apply(node, row):
        result = {'id': row['id'], 'name': row['name']}
        if 'notes' in node: row['notes'] = node['notes']
        if 'children' in node:
            result['children'] = [create(child, row['id']) for child in node['children']]
        if '@RTPC' in node:
            if task.list_mode == 'replaceAll':
                for old in row['@RTPC']:
                    curve_id = task.objects[old['id']]['@Curve']['id']
                    del task.objects[curve_id]; del task.objects[old['id']]
                row['@RTPC'] = []
            result['@RTPC'] = []
            for child in node['@RTPC']:
                member = create(child, row['id'], owned=True)
                row['@RTPC'].append({'id': member['id']})
                result['@RTPC'].append(member)
        if '@PropertyName' in node: row['@PropertyName'] = node['@PropertyName']
        if '@ControlInput' in node:
            if isinstance(node['@ControlInput'], dict):
                result['@ControlInput'] = create(node['@ControlInput'], row['id'], owned=True)
                row['@ControlInput'] = {'id': result['@ControlInput']['id']}
            else:
                row['@ControlInput'] = {'id': node['@ControlInput']}
        for token in ('TimeModDuration', 'EnvelopeStopPlayback', 'Min', 'Max'):
            if '@' + token in node: row['@' + token] = node['@' + token]
        if '@Curve' in node:
            curve = row.get('@Curve', {}).get('id') or allocate()
            points = deepcopy(node['@Curve']['points'])
            row['@Curve'] = {'id': curve, 'points': points}
            task.objects[curve] = {'id': curve, 'name': '', 'type': 'Curve', 'classId': 917520,
                'path': '\\opaque-curve-' + curve, 'owner': {'id': row['id']}, 'notes': '', 'points': deepcopy(points)}
            if fault == 'curve-owner-sound': task.objects[curve]['owner'] = deepcopy(row['owner'])
            elif fault == 'curve-owner-omitted': task.objects[curve].pop('owner')
        return result
    def call(uri, args=None, options=None):
        args, options = args or {}, options or {}
        if uri.endswith('getProjectInfo'):
            return {**original(uri, args, options), 'currentPlatformId': '{55555555-5555-5555-5555-555555555555}'}
        if uri.endswith('isPropertyEnabled'):
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            if fault in {'exclusive-disabled-after-create', 'exclusive-state-read-error'} and args['property'] == 'CenterPercentage':
                # Literal native28dc transition: the base scalar becomes disabled
                # once this Exclusive RTPC exists; its Curve remains a distinct edit.
                controlled = any(row.get('@PropertyName') == 'CenterPercentage' for row in task.objects.values())
                if controlled and fault == 'exclusive-state-read-error': return {'return': 'unavailable'}
                return {'return': not controlled}
            return {'return': True}
        if uri.endswith(('getPropertyAndReferenceNames', 'getPropertyInfo')):
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            if uri.endswith('getPropertyInfo'): return deepcopy(task.metadata[args['property']])
            kind = task.objects[args['object']]['type'] if 'object' in args else next(t['name'] for t in task.types if t['classId'] == args['classId'])
            return {'return': fields[kind]}
        if uri.endswith('object.set'):
            task.calls.append((uri, deepcopy(args), deepcopy(options))); writes.append(deepcopy(args))
            task.list_mode = args.get('listMode', 'append')
            task.conflict = args.get('onNameConflict', 'fail')
            results = []
            for node in args['objects']:
                target = task.objects[node['object']]
                result = apply(node, target)
                # Native field-only rows may have no result association.
                if target['type'] != 'RTPC': results.append(result)
            return {'objects': results}
        if uri.endswith('object.get') and args.get('waql') != 'from type Project take 1':
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            expression = args.get('waql', '')
            source = args.get('from', {})
            if expression:
                assert expression.startswith('from object "'), expression
                identity = expression.split('"')[1]
                rows = [row for row in task.objects.values() if identity in (row['id'], row['path'])]
                if 'select @RTPC' in expression:
                    rows = [task.objects[item['id']] for item in rows[0]['@RTPC']]
                elif 'select @Curve' in expression:
                    rows = [task.objects[rows[0]['@Curve']['id']]]
                elif 'select children' in expression:
                    rows = [row for row in task.objects.values() if row.get('parent') == {'id': rows[0]['id']}]
            elif 'id' in source: rows = [task.objects[key] for key in source['id'] if key in task.objects]
            else: rows = [row for row in task.objects.values() if row['path'] in source['path']]
            for transform in args.get('transform', []):
                token = transform['select'][0]
                if token == 'children': rows = [row for row in task.objects.values() if row.get('parent') == {'id': rows[0]['id']}]
                elif token == 'descendants': rows = [row for row in task.objects.values() if row['path'].startswith(rows[0]['path'] + '\\')]
                else: raise AssertionError(transform)
            return {'return': [{key: deepcopy(row.get(key, row.get('@' + key))) for key in options['return']
                if key in row or '@' + key in row} for row in rows]}
        return original(uri, args, options)
    task.call = call
    runtime = SimpleNamespace(version=version, state_dir=tmp_path / 'state', env=task.env,
        candidate='fixture-candidate', category_results=[])
    def raw(command):
        commands.append(list(command))
        code, payload = workflow.waapi_gateway.execute_gateway(['--state-dir', str(runtime.state_dir), *command],
            env=runtime.env, client_factory=lambda _url: task)
        if fault == 'identity-drift' and command[0] == 'query-object' and '--path-segment' in command and 'WAAPI_RTPC_TEST' in command:
            created = next(row for row in task.objects.values() if row['name'] == 'WAAPI_RTPC_TEST')
            created.update(name='Changed between path and exact ID', path=created['path'] + '_Changed')
        if command[0] == 'verify' and code == 0 and len(writes) == 2 and fault == 'wrong-input-owner':
            # Deliberately after the real Gateway has verified its own readbacks:
            # the collector must independently reject the altered native state.
            control, = [row for row in task.objects.values() if row['type'] == 'ModulatorTime']
            control['owner'] = {'id': parameters}
        if command[0] == 'transaction-show' and code == 0 and len(writes) == 2 and fault in {
                'journal-foreign-result-handle', 'journal-missing-result-handle'}:
            payload = deepcopy(payload)
            verification, = [event['details']['verification'] for event in payload['events']
                if event['event_type'] == 'verification_recorded']
            check, = [check for check in verification['assertions']
                if check.get('kind') == 'verified_owned_control_input_identity']
            assert check['passed'] is True
            if fault == 'journal-missing-result-handle': check['evidence'].pop('result_handle')
            else: check['evidence']['result_handle'] = 'bnh1-' + 'f' * 32
        if command[0] == 'verify' and code == 0 and len(writes) == 3 and fault:
            owner = next(row for row in task.objects.values() if row['name'] == 'WAAPI_RTPC_TEST')
            members = [task.objects[row['id']] for row in owner['@RTPC']]
            spare, selected = members[0], members[1]
            if fault == 'wrong-pair': selected['@ControlInput'] = deepcopy(members[2]['@ControlInput'])
            elif fault == 'spare-curve':
                spare['@Curve']['points'][0]['y'] += 1
                task.objects[spare['@Curve']['id']]['points'] = deepcopy(spare['@Curve']['points'])
            elif fault == 'owner-property': owner['@Volume'] = 7
            elif fault == 'spare-curve-owner': task.objects[spare['@Curve']['id']]['owner'] = {'id': parameters}
            elif fault == 'missing-member': owner['@RTPC'].pop(0)
            elif fault == 'wrong-owner': selected['owner'] = {'id': parameters}
        return code, payload
    runtime.raw_gateway = raw
    if version == '2022.1':
        runtime.sandbox = SimpleNamespace(metadata=SimpleNamespace(get_info_version={
            'year': 2022, 'major': 1, 'minor': 19, 'build': 8584}))
    return runtime, commands, writes, task


@pytest.mark.parametrize('failed_effect', [False, True])
def test_rtpc_graph_collector_categories_survive_existing_exact_finalizer(tmp_path, workflow, monkeypatch, failed_effect):
    runtime, _commands, _writes, _task = _rtpc_graph_runtime(tmp_path / 'collector', workflow,
        version='2023.1', exclusive=False, fault='wrong-pair' if failed_effect else None)
    if failed_effect:
        with pytest.raises(AssertionError):
            workflow._collect_rtpc_graph_acceptance(runtime, name='WAAPI_RTPC_TEST')
        receipt = json.loads((runtime.state_dir / 'rtpc-graph-acceptance.json').read_text())
        phase = next(row for row in receipt['effects'] if row['phase'] == 'exact_update_and_append')
        assert phase['execute']['exit_code'] == phase['verify']['exit_code'] == 0
        assert phase['verify']['payload']['verification']['business_state_verified'] is True
        assert phase['effect_verified'] is False and len(_writes) == 3
    else:
        workflow._collect_rtpc_graph_acceptance(runtime, name='WAAPI_RTPC_TEST')
    (tmp_path / 'lifecycle').mkdir()
    fixture, events, records = _fixture_run(tmp_path / 'lifecycle', workflow, monkeypatch)
    from tests.destructive.support import category_evidence
    target = tmp_path / 'category.jsonl'
    monkeypatch.setenv('WWISE_CATEGORY_EVIDENCE_PATH', str(target))
    monkeypatch.setattr(exact_real_evidence, 'append_category_evidence', category_evidence.append_category_evidence)
    fixture_runtime = next(fixture)
    fixture_runtime.category_results.extend(runtime.category_results)
    with pytest.raises(StopIteration):
        next(fixture)
    retained_rows = [json.loads(line) for line in target.read_text().splitlines()]
    assert retained_rows[-1]['invocation']['phase'] == 'final'
    retained = retained_rows[-1]['categories']
    phases = [row for row in retained if row['category'].startswith('rtpc-graph-')]
    assert phases and all(row['verifier_strength'] for row in phases)
    assert any(row['status'] == ('FAIL' if failed_effect else 'blocked') for row in phases)
    assert events.index('shutdown') < events.index('release')


def _created_fields_history_runtime(tmp_path, workflow, version='2025.1', *, fault=None, null_value=None, source_metadata=None):
    """Public Gateway with native-shaped create/history state, never manufactured receipts."""
    from copy import deepcopy
    import uuid
    from tests.unit.test_object_graph_owned_choices_gateway import OwnedGraphTask, SECOND
    task = OwnedGraphTask(tmp_path, version, 'object.create')
    actor = ('\\Containers' if version == '2025.1' else '\\Actor-Mixer Hierarchy') + '\\Default Work Unit'
    attenuation_parent = '{66666666-6666-6666-6666-666666666666}'
    task.objects = {identity: {'id': identity, 'name': 'Default Work Unit', 'type': 'WorkUnit',
        'classId': 1638416, 'path': path, 'parent': None, 'notes': 'Keep parent'}
        for identity, path in [(SECOND, actor), (attenuation_parent, r'\Attenuations\Default Work Unit')]}
    task.types = [{'name': name, 'classId': value, 'type': 'WObject'} for name, value in (
        ('Sound', 65552), ('Attenuation', 655376), ('WorkUnit', 1638416))]
    task.metadata = {'IsLoopingEnabled': {'name': 'IsLoopingEnabled', 'type': 'bool', 'default': False},
        'IsLoopingInfinite': {'name': 'IsLoopingInfinite', 'type': 'bool', 'default': False},
        'Volume': {'name': 'Volume', 'type': 'Real32', 'restriction': {'type': 'range', 'min': -96, 'max': 6}},
        'Attenuation': {'name': 'Attenuation', 'type': '', 'restriction': {
            'type': 'reference', 'restrictions': [{'type': ['Attenuation']}]}}}
    if version == '2022.1':
        # Retained519 native2022 class metadata certifies a PRESENT null default.
        task.metadata['Attenuation']['default'] = None
    if source_metadata is not None:
        task.metadata.update(deepcopy(source_metadata))
        task.types.extend([{'name': 'Bus', 'classId': 1376272, 'type': 'WObject'},
            {'name': 'AuxBus', 'classId': 3997712, 'type': 'WObject'}])
    platform = '{77777777-7777-7777-7777-777777777777}'
    original, commands, writes = task.call, [], []
    history = {}
    def call(uri, args=None, options=None):
        args, options = args or {}, options or {}
        if uri.endswith('getProjectInfo'):
            return {**original(uri, args, options), 'currentPlatformId': platform,
                'platforms': [{'id': platform, 'name': 'Windows'}]}
        if uri.endswith('object.create'):
            task.calls.append((uri, deepcopy(args), deepcopy(options))); writes.append((uri, deepcopy(args)))
            identity = '{' + str(uuid.UUID(int=200 + len(writes))).upper() + '}'
            row = {'id': identity, 'name': args['name'], 'type': args['type'],
                'classId': next(item['classId'] for item in task.types if item['name'] == args['type']),
                'path': task.objects[args['parent']]['path'] + '\\' + args['name'],
                'parent': {'id': args['parent']}, 'notes': args.get('notes', '')}
            if args['type'] == 'Sound':
                row.update({'@' + key: deepcopy(info['default']) for key, info in task.metadata.items() if 'default' in info})
            row.update({key: deepcopy(value) for key, value in args.items() if key.startswith('@')})
            if '@Attenuation' in row and row['@Attenuation'] is None:
                row['@Attenuation'] = deepcopy(null_value)
            task.objects[identity] = row
            if row['type'] == 'Sound': history.update(id=identity, after=deepcopy(row))
            return {'id': identity, 'name': row['name']}
        if uri in {'ak.wwise.core.undo.undo', 'ak.wwise.core.undo.redo'}:
            task.calls.append((uri, deepcopy(args), deepcopy(options))); writes.append((uri, deepcopy(args)))
            if fault == 'undo-error' and uri.endswith('.undo'): raise RuntimeError('fixture undo native refused')
            if uri.endswith('.undo'): task.objects.pop(history['id'], None)
            else: task.objects[history['id']] = deepcopy(history['after'])
            return {}
        if uri.endswith('object.get') and args.get('waql') != 'from type Project take 1':
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            source = args.get('from', {})
            if 'id' in source: rows = [task.objects[key] for key in source['id'] if key in task.objects]
            elif 'path' in source: rows = [row for row in task.objects.values() if row['path'] in source['path']]
            else:
                expression = args['waql']; assert expression.startswith('from object "'), expression
                selector = expression.split('"')[1]
                rows = [row for row in task.objects.values() if selector in (row['id'], row['path'])]
            for transform in args.get('transform', []):
                assert transform == {'select': ['children']}, transform
                rows = [row for row in task.objects.values() if row.get('parent') == {'id': rows[0]['id']}]
            return {'return': [{key: deepcopy(row.get(key, row.get('@' + key))) for key in options['return']
                if key in row or '@' + key in row} for row in rows]}
        return original(uri, args, options)
    task.call = call
    runtime = SimpleNamespace(version=version, state_dir=tmp_path / 'state', env=task.env,
        candidate='fixture-candidate', category_results=[], port=31337,
        lifecycle=SimpleNamespace(host='127.0.0.1', waapi_url='ws://127.0.0.1:31337/waapi'))
    def raw(command):
        commands.append(list(command))
        code, payload = workflow.waapi_gateway.execute_gateway(['--state-dir', str(runtime.state_dir), *command],
            env=runtime.env, client_factory=lambda _url: task)
        if command[0] == 'status' and code == 0:
            if fault == 'endpoint-drift': payload['endpoint'] = {**payload['endpoint'], 'port': 31338}
            elif fault == 'version-drift': payload['detected_version'] = '2024.1'
        if fault == 'source-query-path' and command[0] == 'query-object' and '--exact-id' in command and history:
            for row in payload.get('objects', []):
                if row['id'] == history['id']: row['path'] = r'\Different\Returned\Path'
        if command[0] == 'verify' and code == 0 and history:
            last = writes[-1][0]
            if last.endswith('object.create') and fault == 'derived-after-verify':
                task.objects[history['id']]['@IsLoopingInfinite'] = False
            elif last.endswith('object.create') and fault == 'target-after-verify':
                next(row for row in task.objects.values() if row['type'] == 'Attenuation')['notes'] = 'Unexpected target change'
            elif last.endswith('object.create') and fault == 'null-cross-root-after-verify' and history['after']['name'].endswith('_null'):
                other = next(row for row in task.objects.values() if row['type'] == 'Sound' and row['name'].endswith('_existing'))
                task.objects[history['id']]['@Attenuation'] = deepcopy(other['@Attenuation'])
            elif last.endswith('.undo') and fault == 'undo-after-verify':
                task.objects[history['id']] = deepcopy(history['after'])
            elif last.endswith('.redo') and fault == 'redo-after-verify':
                task.objects[history['id']].pop('@Attenuation')
        return code, payload
    runtime.raw_gateway = raw
    return runtime, commands, writes, task


# Exact raw six-field metadata from retained807 native2025.1 draft discovery.
# Source/provenance: /tmp/full-coverage-180-new-object-non-master-condition-plan.md.
_CREATED_HISTORY_NATIVE_2025_METADATA = {'Volume': {'audioEngineId': 0,
            'default': 0.0,
            'dependencies': [],
            'display': {'group': 'Voice', 'index': 1520, 'name': 'Voice Volume'},
            'name': 'Volume',
            'restriction': {'max': 200.0, 'min': -200.0, 'type': 'range'},
            'supports': {'randomizer': True, 'rtpc': 'Additive', 'unlink': True},
            'type': 'Real64',
            'ui': {'autoUpdate': False,
                   'dataMeaning': 'Decibels',
                   'displayAs': {'bitfield': False, 'lrMix': False, 'musicNote': False, 'percentage': False},
                   'value': {'decimals': 1,
                             'fine': 0.1,
                             'infinity': 0,
                             'max': 12.0,
                             'min': -96.0,
                             'step': 1.0}}},
 'Attenuation': {'audioEngineId': 4294967295,
                 'default': None,
                 'dependencies': [{'action': 'Show',
                                   'context': 'Self',
                                   'type': 'isMasterBus',
                                   'value': False},
                                  {'action': 'Enable',
                                   'conditions': [{'restriction': {'type': 'enum',
                                                                   'values': [{'displayName': 'True',
                                                                               'value': True}]}}],
                                   'context': 'Self',
                                   'property': 'ListenerRelativeRouting',
                                   'type': 'property'},
                                  {'action': 'Enable',
                                   'conditions': [{'restriction': {'type': 'enum',
                                                                   'values': [{'displayName': 'True',
                                                                               'value': True}]}}],
                                   'context': 'Self',
                                   'property': 'ListenerRelativeRouting',
                                   'type': 'property'},
                                  {'action': 'Enable',
                                   'context': 'Self',
                                   'property': 'OverridePositioning',
                                   'type': 'override'}],
                 'display': {'group': 'Listener Relative Routing/Attenuation',
                             'index': 1641,
                             'name': 'Attenuation'},
                 'name': 'Attenuation',
                 'restriction': {'restrictions': [{'sharedOnlyTypes': [], 'type': ['Attenuation']}],
                                 'type': 'reference'},
                 'supports': {'randomizer': False, 'rtpc': 'None', 'unlink': True},
                 'type': '',
                 'ui': {'autoUpdate': False,
                        'dataMeaning': 'None',
                        'displayAs': {'bitfield': False,
                                      'lrMix': False,
                                      'musicNote': False,
                                      'percentage': False},
                        'value': {'decimals': 0,
                                  'fine': 0.0,
                                  'infinity': 0,
                                  'max': 0.0,
                                  'min': 0.0,
                                  'step': 0.0}}},
 'ListenerRelativeRouting': {'audioEngineId': 4294967295,
                             'default': True,
                             'dependencies': [{'action': 'Enable',
                                               'context': 'Self',
                                               'property': 'OverridePositioning',
                                               'type': 'override'}],
                             'display': {'group': 'Listener Relative Routing',
                                         'index': 1636,
                                         'name': 'Listener Relative Routing'},
                             'name': 'ListenerRelativeRouting',
                             'restriction': {},
                             'supports': {'randomizer': False, 'rtpc': 'None', 'unlink': False},
                             'type': 'bool',
                             'ui': {'autoUpdate': False,
                                    'dataMeaning': 'None',
                                    'displayAs': {'bitfield': False,
                                                  'lrMix': False,
                                                  'musicNote': False,
                                                  'percentage': False},
                                    'value': {'decimals': 0,
                                              'fine': 0.0,
                                              'infinity': 0,
                                              'max': 0.0,
                                              'min': 0.0,
                                              'step': 0.0}}},
 'OverridePositioning': {'audioEngineId': 4294967295,
                         'default': False,
                         'dependencies': [{'action': 'Enable',
                                           'context': 'Self',
                                           'property': 'OverridePositioning',
                                           'type': 'override'}],
                         'display': {'group': '', 'index': 1633, 'name': 'Override Positioning'},
                         'name': 'OverridePositioning',
                         'restriction': {},
                         'supports': {'randomizer': False, 'rtpc': 'None', 'unlink': False},
                         'type': 'bool',
                         'ui': {'autoUpdate': False,
                                'dataMeaning': 'None',
                                'displayAs': {'bitfield': False,
                                              'lrMix': False,
                                              'musicNote': False,
                                              'percentage': False},
                                'value': {'decimals': 0,
                                          'fine': 0.0,
                                          'infinity': 0,
                                          'max': 0.0,
                                          'min': 0.0,
                                          'step': 0.0}}},
 'IsLoopingEnabled': {'audioEngineId': 4294967295,
                      'default': False,
                      'dependencies': [],
                      'display': {'group': 'Loop', 'index': 1568, 'name': 'Loop'},
                      'name': 'IsLoopingEnabled',
                      'restriction': {},
                      'supports': {'randomizer': False, 'rtpc': 'None', 'unlink': False},
                      'type': 'bool',
                      'ui': {'autoUpdate': False,
                             'dataMeaning': 'None',
                             'displayAs': {'bitfield': False,
                                           'lrMix': False,
                                           'musicNote': False,
                                           'percentage': False},
                             'value': {'decimals': 0,
                                       'fine': 0.0,
                                       'infinity': 0,
                                       'max': 0.0,
                                       'min': 0.0,
                                       'step': 0.0}}},
 'IsLoopingInfinite': {'audioEngineId': 4294967295,
                       'default': True,
                       'dependencies': [{'action': 'Enable',
                                         'conditions': [{'restriction': {'type': 'enum',
                                                                         'values': [{'displayName': 'True',
                                                                                     'value': True}]}}],
                                         'context': 'Self',
                                         'property': 'IsLoopingEnabled',
                                         'type': 'property'}],
                       'display': {'group': 'Loop', 'index': 1569, 'name': 'Loop Infinite'},
                       'name': 'IsLoopingInfinite',
                       'restriction': {},
                       'supports': {'randomizer': False, 'rtpc': 'None', 'unlink': False},
                       'type': 'bool',
                       'ui': {'autoUpdate': False,
                              'dataMeaning': 'None',
                              'displayAs': {'bitfield': False,
                                            'lrMix': False,
                                            'musicNote': False,
                                            'percentage': False},
                              'value': {'decimals': 0,
                                        'fine': 0.0,
                                        'infinity': 0,
                                        'max': 0.0,
                                        'min': 0.0,
                                        'step': 0.0}}}}


def _planned_source_characterization_runtime(tmp_path, workflow, *, fault=None, version='2025.1'):
    """Public Gateway plus independently stored native constructor results."""
    from copy import deepcopy
    import uuid
    from tests.unit.test_sound_voice_creation_gateway import planned_source_task, SOURCE_CLASS, JAPANESE, SECOND
    task = planned_source_task(tmp_path, version)
    captured = json.loads((Path(__file__).resolve().parents[1] / 'fixtures/metadata/tone-source-2025.1-properties.json').read_text())
    assert captured['type'] == {'classId': SOURCE_CLASS, 'name': 'Wwise Tone Generator', 'type': 'Source'}
    task.metadata.pop('Frequency')
    task.metadata.update(deepcopy(captured['metadata']))
    if fault == 'missing-field':
        task.metadata.pop('StartFreq')
    task.languages = deepcopy(captured['project_languages'])
    language_objects = deepcopy(captured['language_objects'])
    if fault == 'language-membership':
        language_objects = [row for row in language_objects if row['name'] != 'English(US)']
    task.types.append({'name': 'Language', 'classId': 4915216, 'type': 'WObject'})
    french = '{CDCDCDCD-CDCD-CDCD-CDCD-CDCDCDCDCDCD}'
    if fault == 'two-locales':
        task.languages.append({'id': french, 'name': 'French', 'shortId': 4})
        language_objects.append({'id': french, 'name': 'French', 'type': 'Language', 'path': 'French'})
    task.objects[SECOND]['path'] = (r'\Containers' if version == '2025.1' else r'\Actor-Mixer Hierarchy') + r'\Default Work Unit'
    native = tmp_path / 'native'; native.mkdir()
    task.env['WWISE_EVIDENCE_DIR'] = str(native)
    task.env['WWISE_CATEGORY_EVIDENCE_PATH'] = str(tmp_path / 'category.jsonl')
    created_sources, writes, commands = [], [], []
    def create(node, parent, *, owned=False):
        identity = '{' + str(uuid.uuid4()).upper() + '}'
        if node['type'] == 'Source' and fault == 'reuse' and created_sources:
            identity = created_sources[0]
        row = {'id': identity, 'name': node['name'], 'type': 'SourcePlugin' if node['type'] == 'Source' else 'Sound',
            'classId': SOURCE_CLASS if node['type'] == 'Source' else 65552,
            'path': task.objects[parent]['path'] + '\\' + node['name'], 'parent': {'id': parent},
            'notes': node.get('notes', ''), **{key: deepcopy(value) for key, value in node.items() if key.startswith('@')}}
        if node['type'] == 'Source':
            row.setdefault('@StartFreq', captured['metadata']['StartFreq']['default'])
            row.setdefault('@WaveType', captured['metadata']['WaveType']['default'])
            if fault == 'ignored-real-field': row['@StartFreq'] = 220
            row['audioSource:language'] = {'name': node.get('language', 'SFX')}
            if fault == 'ignored-language' and node.get('language'): row['audioSource:language']['name'] = 'SFX'
            created_sources.append(identity)
            if fault == 'staged-atomic-order':
                # Adding the first Source may change this observation; it is
                # not a requested active-source switch or a Voice field change.
                task.objects[parent]['activeSource'] = {'id': identity}
        else:
            row.setdefault('@IsVoice', False)
            row['activeSource'] = None
        task.objects[identity] = row
        children = [create(child, identity) for child in node.get('children', [])]
        return {'id': identity, 'name': row['name'], **({'children': children} if children else {})}
    task._create = create
    original = task.call
    class WaapiRequestFailed(Exception):
        uri = 'ak.wwise.invalid_language'
        kwargs = {'details': {'procedureUri': 'ak.wwise.core.object.set'},
            'message': 'Language can only be used on the Source of a Voice.'}
    def atomic_localized_source(node):
        if isinstance(node, dict):
            if node.get('type') == 'Sound' and any(child.get('type') == 'Source' and 'language' in child
                    for child in node.get('children', [])):
                return True
            return any(atomic_localized_source(value) for value in node.values())
        return isinstance(node, list) and any(atomic_localized_source(value) for value in node)
    def call(uri, args=None, options=None):
        if uri.endswith('object.get') and (args or {}).get('waql', '').startswith('from type Language '):
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            return {'return': deepcopy(language_objects)}
        expression = (args or {}).get('waql', '')
        if uri.endswith('object.get') and expression.startswith('from object "'):
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            selected = expression.split('"')[1]
            rows = [row for row in task.objects.values() if row['id'] == selected or row['path'] == selected]
            if ' select children ' in expression:
                assert len(rows) == 1, args
                rows = [row for row in task.objects.values() if row.get('parent') == {'id': rows[0]['id']}]
            return {'return': task.project_rows(rows, options or {})}
        if uri.endswith('object.set'):
            writes.append(deepcopy(args))
            if fault == 'staged-atomic-order' and atomic_localized_source(args):
                task.calls.append((uri, deepcopy(args), deepcopy(options)))
                raise WaapiRequestFailed('Language can only be used on the Source of a Voice.')
        result = original(uri, args, options)
        if uri.endswith('object.set') and fault == 'extra-child' and len(writes) == 2:
            original_owner = task.objects[created_sources[0]]['parent']['id']
            extra = '{FAFAFAFA-FAFA-FAFA-FAFA-FAFAFAFAFAFA}'
            task.objects[extra] = {'id': extra, 'name': 'Unexpected retained child', 'type': 'SourcePlugin',
                'classId': SOURCE_CLASS, 'path': task.objects[original_owner]['path'] + r'\Unexpected retained child',
                'parent': {'id': original_owner}, 'notes': 'Unexpected'}
        if uri.endswith('getInfo'):
            minor, build = {'2022.1': (19, 8584), '2023.1': (19, 8928), '2024.1': (13, 9056), '2025.1': (7, 9143)}[version]
            result['version'].update(minor=minor, build=build, displayName=f'v{version}.{minor}.{build}')
        return result
    task.call = call
    runtime = SimpleNamespace(version=version, candidate='a' * 40, category_results=[],
        state_dir=tmp_path / 'state', env=task.env, port=31337,
        sandbox=SimpleNamespace(source_project=task.project_file),
        lifecycle=SimpleNamespace(host='127.0.0.1', port=31337, waapi_url='ws://127.0.0.1:31337/waapi'))
    def raw(argv):
        commands.append(list(argv))
        if fault == 'staged-wrong-voice' and argv[0] == 'query-object' and '--exact-id' in argv and '--include-field' in argv:
            selected = argv[argv.index('--exact-id') + 1]
            row = task.objects.get(selected, {})
            if row.get('type') == 'Sound' and len(writes) == 1:
                row['@IsVoice'] = False
        code, result = task.run(*argv)
        if argv[0] == 'draft-discover-fields' and code == 0 and fault == 'ambiguous-field':
            meaning, = result['meaning_results']
            selected, = [row for row in meaning['candidates'] if row['metadata']['name'] == 'StartFreq']
            meaning['candidates'].append(deepcopy(selected))
            meaning['candidate_count'] += 1
            result['candidate_count'] += 1
        return code, result
    runtime.raw_gateway = raw
    return runtime, commands, writes, task


def _source_plugin_selection_runtime(tmp_path, workflow, *, fault=None, version='2025.1'):
    """Reuse the public workflow producer, with exact retained Tone metadata."""
    from copy import deepcopy
    runtime, commands, writes, task = _planned_source_characterization_runtime(tmp_path, workflow, version=version)
    fixture = json.loads((Path(__file__).parents[1] / 'fixtures/metadata/tone-source-2025-native-catalog.json').read_text())
    task.types = deepcopy(fixture['catalog']['return'])
    from tests.unit.test_sound_voice_creation_gateway import SECOND
    task.objects[SECOND]['classId'] = 1638416
    task.objects[SECOND]['parent'] = None
    platform = {'id': '{C0C0C0C0-C0C0-C0C0-C0C0-C0C0C0C0C0C0}', 'name': 'Observed Target',
        'type': 'Platform', 'classId': 4522000, 'path': r'\Platforms\Observed Target', 'parent': None, 'notes': ''}
    if version == '2022.1':
        task.objects[platform['id']] = deepcopy(platform)
    create = task._create
    def create_source(node, parent, *, owned=False):
        result = create(node, parent, owned=owned)
        if node['type'] == 'Source':
            row = task.objects[result['id']]
            # Native default is modeled independently of the requested setter.
            if task.objects[parent].get('activeSource') is None:
                task.objects[parent]['activeSource'] = {'id': row['id'], 'name': row['name']}
        return result
    task._create = create_source
    original = task.call
    selections = []
    def call(uri, args=None, options=None):
        scope = (args or {}).get('object')
        source_scope = scope == 6684674 or task.objects.get(scope, {}).get('type') in {'Source', 'SourcePlugin'}
        if uri.endswith('getPropertyAndReferenceNames') and source_scope:
            task.calls.append((uri, deepcopy(args), deepcopy(options)))
            return deepcopy(fixture['property_names'])
        if uri == 'ak.wwise.core.sound.setActiveSource':
            task.calls.append((uri, deepcopy(args), deepcopy(options))); selections.append(deepcopy(args))
            owner, source = task.objects[args['sound']], task.objects[args['source']]
            if fault != 'ignored': owner['activeSource'] = {'id': source['id'], 'name': source['name']}
            if fault == 'source-field':
                other = next(r for r in task.objects.values() if r['type'] == 'SourcePlugin' and r['id'] != source['id'])
                other['@StartFreq'] = 999
            if fault == 'extra-child':
                identity = '{FEFEFEFE-FEFE-FEFE-FEFE-FEFEFEFEFEFE}'
                task.objects[identity] = dict(source, id=identity, name='Unexpected', path=owner['path'] + r'\Unexpected')
            return {}
        previous = set(task.objects)
        result = original(uri, args, options)
        if version == '2022.1' and uri.endswith('getProjectInfo'):
            result['currentPlatformId'] = platform['id']
            result['platforms'] = [{'id': platform['id'], 'name': platform['name'], 'baseName': 'Mac'}]
        if uri.endswith('object.set'):
            # Model the valid omitted shape after the producer's fake defaults.
            for identity in set(task.objects) - previous:
                if task.objects[identity]['type'] == 'Sound':
                    task.objects[identity].pop('activeSource')
        return result
    task.call = call
    return runtime, commands, writes, selections, task
