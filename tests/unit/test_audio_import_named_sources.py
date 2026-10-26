"""Closed Draft/transaction behavior for the SDK's independently named Sources."""
from copy import deepcopy
from pathlib import Path

import pytest
from tests.support.gateway_config import set_gateway_config

from tests.unit.test_audio_import_business_gateway import (
    ImportFieldsClient, _import_fields_draft, _project_path, PARENT_ID, _env, waapi_gateway,
)

VERSIONS = ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1")


class NamedSourcesClient(ImportFieldsClient):
    OWNER = "{33333333-3333-3333-3333-333333333333}"
    UNRELATED = "{44444444-4444-4444-4444-444444444444}"

    def __init__(self, tmp_path, version, *, existing=False, fault=None):
        super().__init__(tmp_path, version)
        self.owner_path = self.parent["path"] + r"\MySound"
        self.objects = {}
        self.fault = fault
        if existing:
            self.objects[self.OWNER] = self.owner()
            self.unrelated_file = _project_path(tmp_path).parent / "Originals/SFX/keep.wav"
            self.unrelated_file.parent.mkdir(parents=True)
            self.unrelated_file.write_bytes(b"unrelated bytes")
            self.objects[self.UNRELATED] = self.source(self.UNRELATED, "Keep", self.unrelated_file)

    def owner(self):
        return {"id": self.OWNER, "name": "MySound", "type": "Sound", "classId": 65552,
            "path": self.owner_path, "parent": {"id": PARENT_ID}, "notes": "keep Sound notes", "@IsVoice": False}

    def source(self, object_id, name, copied):
        return {"id": object_id, "name": name, "type": "AudioFileSource", "classId": 16,
            "path": self.owner_path + "\\" + name, "parent": {"id": self.OWNER}, "notes": "",
            "audioSource:language": {"id": "{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}", "name": "SFX"},
            "originalFilePath": str(copied), "originalWavFilePath": str(copied)}

    def call(self, uri, args=None, options=None):
        args, options = args or {}, options or {}
        if uri.startswith("ak.wwise.core.undo."):
            self.calls.append((uri, deepcopy(args), deepcopy(options)))
            return {}
        if uri == "ak.wwise.core.audio.import":
            self.calls.append((uri, deepcopy(args), deepcopy(options)))
            rows, files = [], []
            if self.OWNER not in self.objects:
                self.objects[self.OWNER] = self.owner()
            rows.append(self.objects[self.OWNER])
            for index, item in enumerate(args["imports"]):
                name = item["objectPath"].rsplit("\\", 1)[-1].removeprefix("<AudioFileSource>")
                old = [obj for obj in self.objects.values() if obj["path"] == self.owner_path + "\\" + name]
                if old and args["importOperation"] == "replaceExisting":
                    self.objects.pop(old[0]["id"])
                object_id = old[0]["id"] if old and args["importOperation"] == "useExisting" else "{" + str(index + 5) * 8 + "-" + str(index + 5) * 4 + "-" + str(index + 5) * 4 + "-" + str(index + 5) * 4 + "-" + str(index + 5) * 12 + "}"
                incoming = Path(item["audioFile"])
                copied = _project_path(self.tmp_path).parent / "Originals/SFX" / incoming.name
                copied.parent.mkdir(parents=True, exist_ok=True)
                copied.write_bytes(incoming.read_bytes())
                source = self.source(object_id, name, copied)
                source["notes"] = item.get("notes", "")
                if self.fault == "wrong-parent": source["parent"] = {"id": PARENT_ID}
                if self.fault == "wrong-name": source["name"] = "IgnoredRequestedName"
                self.objects[object_id] = source
                rows.append(source)
                files.append(str(copied))
            if self.fault == "unrelated-media": self.unrelated_file.write_bytes(b"changed unrelated")
            if self.fault == "extra-source":
                self.objects["{99999999-9999-9999-9999-999999999999}"] = self.source("{99999999-9999-9999-9999-999999999999}", "Unexpected", copied)
            result = {"objects": [{key: row[key] for key in options["return"] if key in row} for row in rows]}
            if self.version in {"2023.1", "2024.1", "2025.1"}: result.update(log=[], files=files)
            return result
        if uri == "ak.wwise.core.object.get":
            identity = args.get("from", {})
            if identity or args.get("waql") == f'from object "{self.OWNER}" select children take 129':
                self.calls.append((uri, deepcopy(args), deepcopy(options)))
                if args.get("waql"):
                    rows = [row for row in self.objects.values() if row.get("parent", {}).get("id") == self.OWNER]
                else:
                    rows = [row for row in [self.parent, *self.objects.values()] if row["id"] in identity.get("id", []) or row["path"] in identity.get("path", [])]
                return {"return": [{key: deepcopy(value) for key, value in row.items() if key in options["return"]} for row in rows]}
        return super().call(uri, args, options)


def draft(tmp_path, version, *, existing=False, fault=None):
    client = NamedSourcesClient(tmp_path, version, existing=existing, fault=fault)
    command, parent, client = _import_fields_draft(tmp_path, version, client)
    schema = command("operation-schema", "audio.import")
    assert "source_name" in schema["business_adapter"]["declaration_fields"]
    assert schema["business_adapter"]["row_requirements"]["named_source"]["field"] == "source_name"
    command("draft-business-configure", "--mode", "replace")
    for row_id, source_name in (("first", "_MyActiveSource"), ("second", "OtherSource")):
        media = tmp_path / (row_id + ".wav")
        media.write_bytes(b"RIFF-" + row_id.encode())
        command("draft-declare-new", "--declaration-id", row_id, "--parent-handle", parent,
            "--name", "MySound", "--kind", "sound-sfx", "--field", "source_name", source_name,
            "--field", "media_file", str(media))
    return command, client


def execute(command, preview, client):
    shown = command(*preview["next_command"]["gateway_argv"])
    command(*shown["next_command"]["gateway_argv"])
    command("execute", preview["transaction_id"])
    code, result = waapi_gateway.execute_gateway(
        ["--state-dir", str(client.tmp_path / "state"), "verify", preview["transaction_id"]],
        env=set_gateway_config(_env(client.tmp_path), wwise_version=client.version), client_factory=lambda _: client)
    assert code == (0 if result["state"] == "verified" else 2)
    return result


@pytest.mark.parametrize("version", VERSIONS)
def test_sdk_two_named_sources_share_one_sound_and_preserve_existing_owner(tmp_path, version):
    command, client = draft(tmp_path, version, existing=True)
    before = deepcopy(client.objects)
    command("draft-check")
    preview = command("preview-from-draft")
    result = execute(command, preview, client)
    assert result["state"] == "verified", result
    assert all(client.objects[key] == row for key, row in before.items())
    assert client.unrelated_file.read_bytes() == b"unrelated bytes"
    assert {row["name"] for row in client.objects.values() if row["type"] == "AudioFileSource"} == {"Keep", "_MyActiveSource", "OtherSource"}
    calls = [args for uri, args, _ in client.calls if uri == "ak.wwise.core.audio.import"]
    assert len(calls) == 1
    assert calls[0]["importOperation"] == "replaceExisting"
    assert [row["objectPath"] for row in calls[0]["imports"]] == [
        client.parent["path"] + r"\<Sound SFX>MySound\<AudioFileSource>_MyActiveSource",
        client.parent["path"] + r"\<Sound SFX>MySound\<AudioFileSource>OtherSource"]


def test_two_named_sources_create_their_single_missing_sound_owner(tmp_path):
    command, client = draft(tmp_path, "2025.1")
    command("draft-check")
    result = execute(command, command("preview-from-draft"), client)
    assert result["state"] == "verified", result
    assert len([row for row in client.objects.values() if row["type"] == "Sound"]) == 1
    assert {row["name"] for row in client.objects.values() if row["type"] == "AudioFileSource"} == {"_MyActiveSource", "OtherSource"}


@pytest.mark.parametrize("version,mode", (("2022.1", "replace"), ("2025.1", "reimport")))
def test_bound_named_source_lifecycle_preserves_sound_and_other_source(tmp_path, version, mode):
    client = NamedSourcesClient(tmp_path, version, existing=True)
    old_id = "{22222222-2222-2222-2222-222222222222}"
    old_file = _project_path(tmp_path).parent / "Originals/SFX/old.wav"
    old_file.write_bytes(b"old media")
    client.objects[old_id] = client.source(old_id, "_MyActiveSource", old_file)
    original_owner = deepcopy(client.objects[client.OWNER])
    unrelated = deepcopy(client.objects[client.UNRELATED])
    command, _, _ = _import_fields_draft(tmp_path, version, client)
    bound = command("draft-bind-object", "--object-id", old_id)
    if mode == "replace": command("draft-business-configure", "--mode", "replace")
    media = tmp_path / "different-filename.wav"
    media.write_bytes(b"replacement bytes")
    command("draft-declare-existing", "--declaration-id", "source", "--object-handle", bound["bound_object"]["handle"],
        "--field", "language", "SFX", "--field", "media_file", str(media), "--field", "audio_source_notes", "requested Source notes")
    command("draft-check")
    result = execute(command, command("preview-from-draft"), client)
    assert result["state"] == "verified", result
    assert (old_id in client.objects) is (mode == "reimport")
    assert next(row for row in client.objects.values() if row["name"] == "_MyActiveSource")["notes"] == "requested Source notes"
    assert client.objects[client.OWNER] == original_owner
    assert client.objects[client.UNRELATED] == unrelated
    assert client.unrelated_file.read_bytes() == b"unrelated bytes"


@pytest.mark.parametrize("fault", ("wrong-parent", "wrong-name", "extra-source", "unrelated-media"))
def test_named_source_verification_reports_wrong_ownership_and_unrelated_changes(tmp_path, fault):
    command, client = draft(tmp_path, "2025.1", existing=True, fault=fault)
    command("draft-check")
    assert execute(command, command("preview-from-draft"), client)["state"] == "verification_failed"


@pytest.mark.parametrize("drift", ("owner", "source_collection", "media"))
def test_named_sources_reject_drift_before_the_only_execution(tmp_path, drift):
    command, client = draft(tmp_path, "2025.1", existing=True)
    command("draft-check")
    preview = command("preview-from-draft")
    shown = command(*preview["next_command"]["gateway_argv"])
    command(*shown["next_command"]["gateway_argv"])
    if drift == "owner": client.objects[client.OWNER]["notes"] = "changed since Preview"
    elif drift == "media": (tmp_path / "first.wav").write_bytes(b"changed since Preview")
    else: client.objects[client.UNRELATED]["name"] = "changed since Preview"
    result = command("execute", preview["transaction_id"], expected_error="ROLE_GUARD_MISMATCH")
    assert result["state"] == "repreview_required"
    assert not any(uri == "ak.wwise.core.audio.import" for uri, _, _ in client.calls)
