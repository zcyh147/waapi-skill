from __future__ import annotations

import json
import os
import shutil
import uuid
from pathlib import Path
from typing import Any, Mapping, Sequence

import pytest

from tests.maintenance import collect_integration_workflows_v2_baseline as collector
from tests.support.platform_filesystem import create_symlink_or_skip


REPO_ROOT = Path(__file__).resolve().parents[2]


def _guid(index: int) -> str:
    return "{" + str(uuid.UUID(int=index + 1)).upper() + "}"


class _FakeLiveGateway:
    def __init__(self, *, version: str, project: Path) -> None:
        self.version = version
        self.project = project.resolve(strict=True)
        profile = collector.load_integration_workflows_v2_profile(
            REPO_ROOT
            / "tests"
            / "semantic"
            / "data"
            / "integration-workflows-v2"
            / "profile.json"
        )
        self.specs = collector._all_object_specs(profile)
        self.fields, _lanes = collector._canonical_state_contracts(self.specs)
        present = [
            (role, spec)
            for role, spec in self.specs.items()
            if spec.baseline_state == "present"
        ]
        self.ids = {role: _guid(index) for index, (role, _spec) in enumerate(present)}
        sound_roles = [
            role
            for role, spec in present
            if collector._type_token(spec.type) == "sound"
        ]
        originals = sorted(
            (
                self.project.parent
                / "Originals"
                / "SFX"
                / "WAAPI Skill Integration V2"
            ).glob("*.wav")
        )
        assert len(originals) == len(sound_roles)
        self.sources = {
            role: (_guid(100 + index), originals[index])
            for index, role in enumerate(sound_roles)
        }
        self.queries: list[tuple[str, str]] = []

    def status(self) -> Mapping[str, Any]:
        return {
            "ok": True,
            "command": "status",
            "detected_version": self.version,
            "project": {
                "name": "SampleProject",
                "path": str(self.project),
                "isDirty": False,
            },
        }

    def query_path(
        self, path: str, *, fields: Sequence[str]
    ) -> tuple[Mapping[str, Any], ...]:
        self.queries.append(("path", path))
        match = next(
            (
                (role, spec)
                for role, spec in self.specs.items()
                if spec.path_for(self.version) == path
            ),
            None,
        )
        assert match is not None
        role, spec = match
        if spec.baseline_state == "absent":
            return ()
        row: dict[str, Any] = {
            "id": self.ids[role],
            "name": path.rsplit("\\", 1)[-1],
            "type": (
                "PropertyContainer"
                if self.version == "2025.1" and role == "audit_root"
                else spec.type
            ),
            "path": path,
        }
        for field in fields:
            if field in row:
                continue
            if field in collector._IDENTITY_FIELDS:
                if field == "activeSource":
                    row[field] = {"id": self.sources[role][0], "name": "source"}
                elif field == "Target" and role == "play_rifle_action":
                    row[field] = {
                        "id": self.ids["rifle_container"],
                        "name": "Rifle",
                    }
                else:
                    row[field] = {"id": _guid(500), "name": "reference"}
            elif field == "OutputBus":
                row[field] = {"id": _guid(501), "name": "bus"}
            elif field in {"@Volume", "@Pitch"}:
                row[field] = 0.0
            elif field in {
                "@IsLoopingEnabled",
                "@UseMaxSoundPerInstance",
            }:
                row[field] = False
            elif field == "@MaxSoundPerInstance":
                row[field] = 50
            elif field == "ActionType":
                row[field] = 1
            elif field == "notes":
                row[field] = "baseline"
            else:
                raise AssertionError(f"unhandled fake field {role}.{field}")
        return (row,)

    def query_id(
        self, object_id: str, *, fields: Sequence[str]
    ) -> tuple[Mapping[str, Any], ...]:
        self.queries.append(("id", object_id))
        if "@RTPC" in fields:
            return ({"id": object_id, "@RTPC": []},)
        action_match = next(
            (
                (role, spec)
                for role, spec in self.specs.items()
                if spec.type == "Action"
                and self.ids[role].casefold() == object_id.casefold()
            ),
            None,
        )
        if action_match is not None:
            role, spec = action_match
            return self.query_path(spec.path_for(self.version), fields=fields)
        match = next(
            (
                (role, source_path)
                for role, (source_id, source_path) in self.sources.items()
                if source_id.casefold() == object_id.casefold()
            ),
            None,
        )
        assert match is not None
        role, source_path = match
        row = {
            "id": object_id,
            "name": f"{role}_source",
            "type": "AudioFileSource",
            "path": f"\\source\\{role}",
            "parent": {"id": self.ids[role], "name": role},
            "notes": "",
            "originalFilePath": str(source_path),
            "audioSource:language": {"name": "SFX"},
        }
        return ({field: row[field] for field in fields},)

    def query_ids(
        self, object_ids: Sequence[str], *, fields: Sequence[str]
    ) -> tuple[Mapping[str, Any], ...]:
        raise AssertionError("the fake baseline has no RTPC rows")

    def query_children(self, object_id: str) -> tuple[Mapping[str, Any], ...]:
        self.queries.append(("children", object_id))
        event_actions = {
            "play_rifle_event": "play_rifle_action",
            "play_footsteps_event": "play_footsteps_action",
            "audit_close_event": "audit_close_action",
        }
        event_role = next(
            (
                role
                for role in event_actions
                if self.ids[role].casefold() == object_id.casefold()
            ),
            None,
        )
        if event_role is not None:
            action_role = event_actions[event_role]
            action_spec = self.specs[action_role]
            return (
                {
                    "id": self.ids[action_role],
                    "name": "",
                    "type": "Action",
                    "path": action_spec.path_for(self.version),
                    "parent": {"id": self.ids[event_role]},
                },
            )
        return ()

    def get_assignments(
        self, switch_container_id: str
    ) -> tuple[Mapping[str, Any], ...]:
        self.queries.append(("assignments", switch_container_id))
        return ()


def _gateway_payload(
    *, version: str, command: str, **values: Any
) -> collector.CommandResult:
    payload = {
        "ok": True,
        "status": "ok",
        "command": command,
        "detected_version": version,
        **values,
    }
    return collector.CommandResult(0, json.dumps(payload))


def test_public_gateway_routes_reads_only_through_reviewed_public_lanes() -> None:
    calls: list[tuple[str, ...]] = []
    transaction_roots: list[tuple[Path, Path]] = []
    transaction_id = "tx1-collector-read"
    artifact_hash = "a" * 64
    confirmation_token = "confirmation-token"

    def run(argv: tuple[str, ...]) -> collector.CommandResult:
        calls.append(argv)
        if "query-object" in argv:
            return _gateway_payload(
                version="2022.1",
                command="query-object",
                count=1,
                objects=[
                    {
                        "id": _guid(1),
                        "name": "Dummy",
                        "type": "Sound",
                        "path": "\\Dummy",
                    }
                ],
            )
        command = next(
            value
            for value in (
                "preview",
                "transaction-show",
                "confirm",
                "execute",
                "verify",
            )
            if value in argv
        )
        state_dir = Path(argv[argv.index("--state-dir") + 1])
        evidence_dir = Path(argv[argv.index("--evidence-dir") + 1])
        assert state_dir.is_dir()
        assert evidence_dir.is_dir()
        transaction_roots.append((state_dir, evidence_dir))
        if command == "preview":
            request = json.loads(argv[argv.index("--request-json") + 1])
            assert request == {
                "contract": "waapi-skill.operation-request/v1",
                "version": "2022.1",
                "operation": "waapi.call",
                "arguments": {
                    "api": collector.GET_ASSIGNMENTS_API,
                    "args": {"id": _guid(2)},
                    "options": {},
                },
            }
            return _gateway_payload(
                version="2022.1",
                command=command,
                state="awaiting_confirmation",
                transaction_id=transaction_id,
                artifact_hash=artifact_hash,
                executed=False,
                preview_summary={"request": request},
            )
        if command == "transaction-show":
            assert argv[-3:] == ("transaction-show", transaction_id, "--summary-only")
            return _gateway_payload(
                version="2022.1",
                command=command,
                state="awaiting_confirmation",
                transaction_id=transaction_id,
                artifact_hash=artifact_hash,
                confirmation={"token": confirmation_token},
            )
        if command == "confirm":
            assert argv[-4:] == (
                "confirm",
                transaction_id,
                "--confirmation-token",
                confirmation_token,
            )
            return _gateway_payload(
                version="2022.1",
                command=command,
                state="confirmed",
                transaction_id=transaction_id,
                artifact_hash=artifact_hash,
            )
        if command == "execute":
            assert argv[-2:] == ("execute", transaction_id)
            return _gateway_payload(
                version="2022.1",
                command=command,
                state="executed_unverified",
                transaction_id=transaction_id,
                artifact_hash=artifact_hash,
                executed=True,
            )
        assert command == "verify"
        assert argv[-2:] == ("verify", transaction_id)
        request = json.loads(
            next(
                previous[previous.index("--request-json") + 1]
                for previous in calls
                if "preview" in previous
            )
        )
        return _gateway_payload(
            version="2022.1",
            command=command,
            state="result_schema_checked",
            transaction_id=transaction_id,
            artifact_hash=artifact_hash,
            result_schema_checked=True,
            agent_result={
                "request": request,
                "executed": True,
                "result": {"return": []},
            },
        )

    gateway = collector.PublicGateway(version="2022.1", runner=run)
    gateway.query_path("\\Dummy", fields=("id", "name", "type", "path"))
    gateway.get_assignments(_guid(2))

    assert "query-object" in calls[0]
    assert [
        next(
            value
            for value in (
                "preview",
                "transaction-show",
                "confirm",
                "execute",
                "verify",
            )
            if value in command
        )
        for command in calls[1:]
    ] == ["preview", "transaction-show", "confirm", "execute", "verify"]
    assert all("call" not in command for command in calls)
    assert len({roots for roots in transaction_roots}) == 1
    assert all(not path.exists() for path in transaction_roots[-1])
    assert not any(
        "ak.wwise.core.object.get" in command for command in calls
    )


@pytest.mark.parametrize("version", collector.SUPPORTED_VERSIONS)
def test_collector_builds_closed_manifest_from_fake_gateway(
    version: str,
    tmp_path: Path,
) -> None:
    source_project = (
        REPO_ROOT / "tests" / "_org" / version / "SampleProject.wproj"
    )
    live_root = tmp_path / "sandbox-copy"
    shutil.copytree(source_project.parent, live_root)
    live_project = live_root / "SampleProject.wproj"
    (live_root / ".cache").mkdir()
    (live_root / ".cache" / "generated.cache").write_text(
        "allowed generated state\n", encoding="utf-8"
    )
    (live_root / "SampleProject.wsettings").write_text(
        "allowed local settings\n", encoding="utf-8"
    )
    gateway = _FakeLiveGateway(version=version, project=live_project)

    collection = collector.collect_integration_workflows_v2_baseline(
        version=version,
        live_project=live_project,
        repo_root=REPO_ROOT,
        gateway=gateway,
    )

    payload = collection.payload
    assert payload["contract"] == collector.BASELINE_MANIFEST_CONTRACT
    assert payload["version"] == version
    assert len(payload["objects"]) == len(gateway.fields)
    assert len(payload["media"]) == 15
    assert len(payload["storage_files"]) == 5
    assert {
        row["role"] for row in payload["objects"]
    } == set(gateway.fields)
    for row in payload["objects"]:
        assert tuple(row["state"]) == gateway.fields[row["role"]]
        assert row["state_sha256"] == collector.hashlib.sha256(
            collector.canonical_json_bytes(row["state"])
        ).hexdigest()
    assert payload["source_project"]["full_tree_sha256"] == (
        collector.wwise_fixture_tree_sha256(source_project.parent)
    )
    assert any(kind == "assignments" for kind, _value in gateway.queries)
    queried_paths = {
        value for kind, value in gateway.queries if kind == "path"
    }
    event_prefix = r"\Events\Default Work Unit\WAAPI_Skill_Integration_V2"
    expected_event_paths = (
        {
            rf"{event_prefix}\RifleRevision\Play_Rifle",
            rf"{event_prefix}\PlayerFootstepsMaintenance\Play_Footsteps",
            rf"{event_prefix}\WeaponsAudit\Play_Rifle_Close",
        }
        if version == "2022.1"
        else {
            rf"{event_prefix}\Play_Rifle",
            rf"{event_prefix}\Play_Player_Footsteps",
            rf"{event_prefix}\Play_Rifle_Close",
        }
    )
    assert expected_event_paths <= queried_paths
    objects_by_role = {row["role"]: row for row in payload["objects"]}
    assert objects_by_role["play_rifle_action"]["state"]["Target"] == {
        "id": gateway.ids["rifle_container"].upper()
    }


def test_collector_rejects_a_different_live_project_before_object_reads(
    tmp_path: Path,
) -> None:
    source = REPO_ROOT / "tests" / "_org" / "2022.1" / "SampleProject.wproj"
    first_root = tmp_path / "first-copy"
    second_root = tmp_path / "second-copy"
    shutil.copytree(source.parent, first_root)
    shutil.copytree(source.parent, second_root)
    requested = first_root / "SampleProject.wproj"
    observed = second_root / "SampleProject.wproj"
    gateway = _FakeLiveGateway(version="2022.1", project=observed)

    with pytest.raises(
        collector.IntegrationBaselineCollectionError,
        match="not using the requested sandbox project",
    ):
        collector.collect_integration_workflows_v2_baseline(
            version="2022.1",
            live_project=requested,
            repo_root=REPO_ROOT,
            gateway=gateway,
        )

    assert gateway.queries == []
    assert source.is_file()


def test_collector_rejects_sandbox_authored_storage_drift(
    tmp_path: Path,
) -> None:
    source = REPO_ROOT / "tests" / "_org" / "2022.1" / "SampleProject.wproj"
    live_root = tmp_path / "sandbox-copy"
    shutil.copytree(source.parent, live_root)
    live_project = live_root / "SampleProject.wproj"
    storage = live_root / "Actor-Mixer Hierarchy" / "Default Work Unit.wwu"
    storage.write_bytes(storage.read_bytes() + b"\n<!-- drift -->\n")
    gateway = _FakeLiveGateway(version="2022.1", project=live_project)

    with pytest.raises(
        collector.IntegrationBaselineCollectionError,
        match="fixed storage files",
    ):
        collector.collect_integration_workflows_v2_baseline(
            version="2022.1",
            live_project=live_project,
            repo_root=REPO_ROOT,
            gateway=gateway,
        )

    assert gateway.queries == []


def test_collector_rejects_committed_source_as_live_project() -> None:
    source = REPO_ROOT / "tests" / "_org" / "2022.1" / "SampleProject.wproj"
    gateway = _FakeLiveGateway(version="2022.1", project=source)

    with pytest.raises(
        collector.IntegrationBaselineCollectionError,
        match="isolated sandbox copy",
    ):
        collector.collect_integration_workflows_v2_baseline(
            version="2022.1",
            live_project=source,
            repo_root=REPO_ROOT,
            gateway=gateway,
        )

    assert gateway.queries == []


@pytest.mark.skipif(os.name == "nt", reason="Wine Y: mapping is POSIX-only")
def test_live_project_path_localizes_exact_wine_y_drive(tmp_path: Path) -> None:
    project = tmp_path / "Documents" / "Fixture" / "SampleProject.wproj"
    project.parent.mkdir(parents=True)
    project.write_text("<WwiseDocument />\n", encoding="utf-8")

    assert collector._localize_live_project_path(
        r"Y:\Documents\Fixture\SampleProject.wproj",
        account_home=tmp_path,
    ) == project.resolve(strict=True)


def test_live_project_path_accepts_native_absolute_project(tmp_path: Path) -> None:
    project = tmp_path / "SampleProject.wproj"
    project.write_text("<WwiseDocument />\n", encoding="utf-8")

    assert collector._localize_live_project_path(str(project)) == project.resolve(
        strict=True
    )


@pytest.mark.parametrize(
    "value",
    (
        r"C:\Fixture\SampleProject.wproj",
        r"Y:\Fixture\..\SampleProject.wproj",
    ),
)
def test_live_project_path_rejects_unproven_wine_paths(
    tmp_path: Path,
    value: str,
) -> None:
    with pytest.raises(collector.IntegrationBaselineCollectionError):
        collector._localize_live_project_path(value, account_home=tmp_path)


@pytest.mark.skipif(os.name == "nt", reason="Wine Z: mapping is POSIX-only")
def test_original_file_localizes_wine_z_path_inside_project(tmp_path: Path) -> None:
    original = tmp_path / "Originals" / "SFX" / "line.wav"
    original.parent.mkdir(parents=True)
    original.write_bytes(b"RIFF")
    wire = "Z:\\" + "\\".join(original.parts[1:])

    assert collector._original_file(
        wire,
        project_root=tmp_path,
        label="test original",
    ) == original.resolve(strict=True)


@pytest.mark.skipif(os.name == "nt", reason="Wine drive rejection is POSIX-only")
def test_original_file_rejects_unknown_wine_drive(tmp_path: Path) -> None:
    with pytest.raises(
        collector.IntegrationBaselineCollectionError,
        match="unsupported Wine drive",
    ):
        collector._original_file(
            r"C:\Originals\SFX\line.wav",
            project_root=tmp_path,
            label="test original",
        )


def test_original_file_accepts_native_absolute_path_inside_project(
    tmp_path: Path,
) -> None:
    original = tmp_path / "Originals" / "SFX" / "line.wav"
    original.parent.mkdir(parents=True)
    original.write_bytes(b"RIFF")

    assert collector._original_file(
        str(original),
        project_root=tmp_path,
        label="test original",
    ) == original.resolve(strict=True)


def test_atomic_manifest_write_rejects_symlink(tmp_path: Path) -> None:
    destination = tmp_path / "baseline-2022.1.json"
    target = tmp_path / "target.json"
    target.write_text("{}\n", encoding="utf-8")
    create_symlink_or_skip(destination, target)
    collection = collector.BaselineCollection(
        "2022.1",
        destination,
        {
            "objects": [],
            "media": [],
            "storage_files": [],
        },
    )

    with pytest.raises(
        collector.IntegrationBaselineCollectionError,
        match="refusing to replace symlink",
    ):
        collector.write_baseline(collection)


@pytest.mark.parametrize("broken", (False, True))
def test_repository_destination_keeps_leaf_symlink_for_writer_rejection(
    tmp_path: Path,
    broken: bool,
) -> None:
    repository = tmp_path / "repository"
    parent = repository / "tests" / "semantic" / "data"
    parent.mkdir(parents=True)
    outside = tmp_path / "outside.json"
    if not broken:
        outside.write_text("outside\n", encoding="utf-8")
    destination = parent / "baseline.json"
    create_symlink_or_skip(destination, outside)

    lexical = collector._repository_destination(
        repository,
        "tests/semantic/data/baseline.json",
        "baseline manifest",
    )
    assert lexical == destination
    assert lexical.is_symlink()
    collection = collector.BaselineCollection(
        "2022.1",
        lexical,
        {"objects": [], "media": [], "storage_files": []},
    )

    with pytest.raises(
        collector.IntegrationBaselineCollectionError,
        match="refusing to replace symlink",
    ):
        collector.write_baseline(collection)
    if not broken:
        assert outside.read_text(encoding="utf-8") == "outside\n"
