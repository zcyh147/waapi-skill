"""Exact-table Source lifecycle through the public Gateway transaction seam."""
import csv
import base64
from copy import deepcopy
from pathlib import Path

import pytest

from tests.support.gateway_config import set_gateway_config
from tests.unit.test_audio_import_business_gateway import _env, waapi_gateway, _project_path, PARENT_ID
from tests.unit.test_audio_import_named_sources import NamedSourcesClient, VERSIONS


class TableSourcesClient(NamedSourcesClient):
    def call(self, uri, args=None, options=None):
        args, options = args or {}, options or {}
        if uri == "ak.wwise.core.getProjectInfo" and getattr(self, "language", "SFX") != "SFX":
            result = super().call(uri, args, options)
            result["languages"].append({"id": "{88888888-8888-8888-8888-888888888888}", "name": self.language, "shortId": 2})
            return result
        if uri == "ak.wwise.core.object.get" and args.get("transform") == [{"select": ["descendants"]}]:
            self.calls.append((uri, deepcopy(args), deepcopy(options)))
            root = self.objects.get(args["from"]["id"][0], {})
            prefix = root.get("path", "") + "\\"
            return {"return": [{key: deepcopy(value) for key, value in row.items() if key in options["return"]}
                for row in self.objects.values() if root and row["path"].startswith(prefix)]}
        if uri == "ak.wwise.core.object.get" and args.get("waql", "").startswith('from object "') and "select children" in args["waql"]:
            owner_id = args["waql"].split('"')[1]
            self.calls.append((uri, deepcopy(args), deepcopy(options)))
            return {"return": [{key: deepcopy(value) for key, value in row.items() if key in options["return"]}
                for row in self.objects.values() if row.get("parent", {}).get("id") == owner_id]}
        if uri == "ak.wwise.core.audio.importTabDelimited":
            self.calls.append((uri, deepcopy(args), deepcopy(options)))
            if self.OWNER not in self.objects:
                self.objects[self.OWNER] = self.owner()
            owner_id = self.OWNER
            with Path(args["importFile"]).open(encoding="utf-8", newline="") as stream:
                table = list(csv.DictReader(stream, delimiter="\t"))
            replaces_owner = args["importOperation"] == "replaceExisting" and any(
                not row.get("Audio File") and not row.get("Audio File Base64") and row["Object Type"] == "Sound SFX" for row in table)
            if replaces_owner:
                self.objects.pop(self.OWNER)
                self.objects = {key: row for key, row in self.objects.items()
                    if not row["path"].startswith(self.owner_path + "\\")
                    or self.fault == "kept-retired-child" and row["id"] == "{77777777-7777-7777-7777-777777777777}"}
                owner_id = "{66666666-6666-6666-6666-666666666666}"
                self.objects[owner_id] = {**self.owner(), "id": owner_id}
            returned = [self.objects[owner_id]]
            for index, row in enumerate(table):
                if not row.get("Audio File") and not row.get("Audio File Base64"):
                    self.objects[owner_id]["notes"] = row.get("Notes", "")
                    continue
                name = row["Object Path"].rsplit("\\", 1)[-1].removeprefix("<AudioFileSource>")
                old = [item for item in self.objects.values() if item["path"] == self.owner_path + "\\" + name]
                if old and args["importOperation"] == "replaceExisting": self.objects.pop(old[0]["id"])
                object_id = old[0]["id"] if old and args["importOperation"] == "useExisting" else "{55555555-5555-5555-5555-555555555555}"
                if row.get("Audio File Base64"):
                    filename, encoded = row["Audio File Base64"].split("|", 1)
                    media_bytes = base64.b64decode(encoded)
                else:
                    incoming = Path(row["Audio File"])
                    filename, media_bytes = incoming.name, incoming.read_bytes()
                folder = "SFX" if args["importLanguage"] == "SFX" else "Voices/" + args["importLanguage"]
                copied = _project_path(self.tmp_path).parent / "Originals" / folder / filename
                copied.parent.mkdir(parents=True, exist_ok=True)
                copied.write_bytes(b"ignored media" if self.fault == "ignored-media" else media_bytes)
                source = self.source(object_id, name, copied)
                source["notes"] = row.get("Notes", "")
                source["parent"] = {"id": self.OWNER if self.fault == "wrong-replacement-parent" else owner_id}
                source["audioSource:language"]["name"] = args["importLanguage"]
                if "Property[Volume]" in row: source["@Volume"] = float(row["Property[Volume]"])
                self.objects[object_id] = source
                returned.append(source)
            if self.fault == "missing-owner": self.objects.pop(owner_id)
            if self.fault == "extra-source":
                extra_id = "{99999999-9999-9999-9999-999999999999}"
                self.objects[extra_id] = {**self.source(extra_id, "Unexpected", copied), "parent": {"id": owner_id}}
            return {"objects": [{key: row[key] for key in options["return"] if key in row} for row in returned]}
        return super().call(uri, args, options)


def table_draft(tmp_path, version, *, mode="create", existing_owner=True, existing_source=False, language="SFX"):
    client = TableSourcesClient(tmp_path, version, existing=existing_owner)
    client.language = language
    if language != "SFX":
        client.objects[client.OWNER]["@IsVoice"] = True
        project = _project_path(tmp_path)
        project.write_text(project.read_text().replace("</LanguageList>",
            '<Language Name="English(US)" ID="{88888888-8888-8888-8888-888888888888}"/></LanguageList>'), encoding="utf-8")
    old_id = "{22222222-2222-2222-2222-222222222222}"
    if existing_source:
        old_file = _project_path(tmp_path).parent / "Originals/SFX/old.wav"
        old_file.write_bytes(b"old Source bytes")
        client.objects[old_id] = client.source(old_id, "NamedSource", old_file)
        client.objects[old_id]["audioSource:language"]["name"] = language
    media = tmp_path / "different_filename.wav"
    media.write_bytes(b"requested Source bytes")
    table = tmp_path / "user.tsv"
    table.write_text("Audio File\tObject Path\tObject Type\tNotes\n" + str(media)
        + "\t<Sound SFX>MySound\\<AudioFileSource>NamedSource\tAudioFileSource\trequested Source notes\n", encoding="utf-8")
    env = set_gateway_config(_env(tmp_path), wwise_version=version)
    def run(*argv):
        return waapi_gateway.execute_gateway(["--state-dir", str(tmp_path / "state"), *argv],
            env=env, client_factory=lambda _: client)
    code, started = run("draft-start", "audio.importTabDelimited")
    assert code == 0, started
    draft_id, authority, revision = started["draft"]["draft_id"], started["task_authority"], 1
    def command(name, *argv, expected_error=None):
        nonlocal revision
        code, result = run(name, draft_id, "--task-authority", authority, "--expected-revision", str(revision), *argv)
        assert code == (2 if expected_error else 0), result
        if expected_error: assert result["error_code"] == expected_error
        if "draft" in result: revision = result["draft"]["revision"]
        return result
    bound = command("draft-bind-object", "--role", "import_location", "--object-id", PARENT_ID)
    command("draft-declare-artifact-plan", "--table-file", str(table), "--location-handle",
        bound["bound_object"]["handle"], "--language", language, "--mode", mode)
    return command, run, client, table


def execute_table(command, run):
    command("draft-check")
    preview = command("preview-from-draft")
    code, shown = run(*preview["next_command"]["gateway_argv"])
    assert code == 0, shown
    code, confirmed = run(*shown["next_command"]["gateway_argv"])
    assert code == 0, confirmed
    code, executed = run("execute", preview["transaction_id"])
    assert code == 0, executed
    code, verified = run("verify", preview["transaction_id"])
    return code, verified


@pytest.mark.parametrize("version", VERSIONS)
def test_exact_table_creates_named_source_preserving_existing_sound_and_sibling_media(tmp_path, version):
    command, run, client, table = table_draft(tmp_path, version)
    before = deepcopy(client.objects)
    original_table = table.read_bytes()
    code, verified = execute_table(command, run)
    assert code == 0 and verified["verified"] is True, verified
    assert all(client.objects[key] == row for key, row in before.items())
    assert client.unrelated_file.read_bytes() == b"unrelated bytes" and table.read_bytes() == original_table
    source = client.objects["{55555555-5555-5555-5555-555555555555}"]
    assert source["name"] == "NamedSource" and source["parent"]["id"] == client.OWNER
    assert source["notes"] == "requested Source notes"
    assert Path(source["originalFilePath"]).read_bytes() == b"requested Source bytes"
    calls = [args for uri, args, _ in client.calls if uri == "ak.wwise.core.audio.importTabDelimited"]
    assert len(calls) == 1 and calls[0]["importFile"] == str(table.resolve())
    assert calls[0]["importOperation"] == "createNew"


@pytest.mark.parametrize("mode", ("reimport", "replace"))
def test_exact_table_source_reuse_and_replacement_preserve_owner_and_unrelated_media(tmp_path, mode):
    command, run, client, table = table_draft(tmp_path, "2022.1", mode=mode, existing_source=True)
    original_table = table.read_bytes()
    before_owner = deepcopy(client.objects[client.OWNER])
    before_sibling = deepcopy(client.objects[client.UNRELATED])
    code, verified = execute_table(command, run)
    assert code == 0 and verified["verified"] is True, verified
    old_id = "{22222222-2222-2222-2222-222222222222}"
    assert (old_id in client.objects) is (mode == "reimport")
    assert client.objects[client.OWNER] == before_owner and client.objects[client.UNRELATED] == before_sibling
    assert client.unrelated_file.read_bytes() == b"unrelated bytes" and table.read_bytes() == original_table


def test_exact_table_source_creates_its_typed_missing_sound_owner(tmp_path):
    command, run, client, table = table_draft(tmp_path, "2025.1", existing_owner=False)
    original_table = table.read_bytes()
    code, verified = execute_table(command, run)
    assert code == 0 and verified["verified"] is True, verified
    assert len([row for row in client.objects.values() if row["type"] == "Sound"]) == 1
    assert table.read_bytes() == original_table


def test_exact_table_source_uses_same_table_typed_owner_declaration(tmp_path):
    command, run, client, table = table_draft(tmp_path, "2025.1", mode="reimport", existing_owner=False)
    table.write_text("Audio File\tObject Path\tObject Type\tNotes\n"
        "\tMySound\tSound SFX\trequested owner notes\n"
        + str(tmp_path / "different_filename.wav") + "\tMySound\\<AudioFileSource>NamedSource\tAudioFileSource\trequested Source notes\n", encoding="utf-8")
    original = table.read_bytes()
    code, verified = execute_table(command, run)
    assert code == 0 and verified["verified"] is True, verified
    assert client.objects[client.OWNER]["notes"] == "requested owner notes" and table.read_bytes() == original


@pytest.mark.parametrize("drift", ("source_path", "owner", "table", "media"))
def test_exact_table_new_source_immutable_binding_blocks_prewrite_drift(tmp_path, drift):
    command, run, client, table = table_draft(tmp_path, "2025.1")
    command("draft-check")
    preview = command("preview-from-draft")
    code, shown = run(*preview["next_command"]["gateway_argv"]); assert code == 0, shown
    assert run(*shown["next_command"]["gateway_argv"])[0] == 0
    if drift == "source_path":
        key = "{22222222-2222-2222-2222-222222222222}"
        client.objects[key] = client.source(key, "NamedSource", client.unrelated_file)
    elif drift == "owner": client.objects[client.OWNER]["@IsVoice"] = True
    elif drift == "table": table.write_text(table.read_text() + "\n", encoding="utf-8")
    else: (tmp_path / "different_filename.wav").write_bytes(b"changed media")
    code, rejected = run("execute", preview["transaction_id"])
    assert code == 2 and rejected["state"] == "repreview_required", rejected
    assert not any(uri == "ak.wwise.core.audio.importTabDelimited" for uri, _, _ in client.calls)


@pytest.mark.parametrize("fault", ("wrong_owner_kind", "wrong_source_language", "create_collision", "midi_for_audio_source"))
def test_exact_table_source_invalid_scope_fails_before_preview(tmp_path, fault):
    command, _, client, table = table_draft(tmp_path, "2025.1",
        mode="create" if fault == "create_collision" else "reimport", existing_source=fault != "wrong_owner_kind")
    if fault == "wrong_owner_kind": client.objects[client.OWNER]["@IsVoice"] = True
    elif fault == "wrong_source_language":
        client.objects["{22222222-2222-2222-2222-222222222222}"]["audioSource:language"]["name"] = "English(US)"
    elif fault == "midi_for_audio_source":
        midi = tmp_path / "unsupported.mid"
        midi.write_bytes(b"MThd")
        table.write_text(table.read_text().replace(str(tmp_path / "different_filename.wav"), str(midi)), encoding="utf-8")
    expected = {"wrong_owner_kind": "INVALID_TARGET_TYPE", "wrong_source_language": "AMBIGUOUS_SOURCE_WIRE_PATH", "create_collision": "TARGET_EXISTS", "midi_for_audio_source": "INVALID_TARGET_TYPE"}[fault]
    original = table.read_bytes()
    command("draft-check", expected_error=expected)
    assert table.read_bytes() == original
    assert not any(uri == "ak.wwise.core.audio.importTabDelimited" for uri, _, _ in client.calls)


def test_exact_table_explicit_sound_replacement_rebinds_child_source_and_retires_old_children(tmp_path):
    command, run, client, table = table_draft(tmp_path, "2025.1", mode="replace", existing_source=True)
    client.objects["{77777777-7777-7777-7777-777777777777}"] = {
        "id": "{77777777-7777-7777-7777-777777777777}", "name": "Nested", "type": "Effect",
        "path": client.owner_path + r"\NamedSource\Nested", "parent": {"id": "{22222222-2222-2222-2222-222222222222}"}}
    table.write_text("Audio File\tObject Path\tObject Type\tNotes\n"
        "\t<Sound SFX>MySound\tSound SFX\treplacement Sound notes\n"
        + str(tmp_path / "different_filename.wav")
        + "\t<Sound SFX>MySound\\<AudioFileSource>NamedSource\tAudioFileSource\trequested Source notes\n", encoding="utf-8")
    original = table.read_bytes()
    code, verified = execute_table(command, run)
    assert code == 0 and verified["verified"] is True, verified
    assert client.OWNER not in client.objects and client.UNRELATED not in client.objects
    assert "{22222222-2222-2222-2222-222222222222}" not in client.objects
    assert client.objects["{55555555-5555-5555-5555-555555555555}"]["parent"]["id"] == "{66666666-6666-6666-6666-666666666666}"
    assert table.read_bytes() == original


@pytest.mark.parametrize("fault", ("wrong-replacement-parent", "missing-owner", "kept-retired-child"))
def test_exact_table_sound_replacement_requires_new_parent_and_complete_child_retirement(tmp_path, fault):
    command, run, client, table = table_draft(tmp_path, "2025.1", mode="replace", existing_source=True)
    client.fault = fault
    client.objects["{77777777-7777-7777-7777-777777777777}"] = {
        "id": "{77777777-7777-7777-7777-777777777777}", "name": "Nested", "type": "Effect",
        "path": client.owner_path + r"\NamedSource\Nested", "parent": {"id": "{22222222-2222-2222-2222-222222222222}"}}
    table.write_text("Audio File\tObject Path\tObject Type\tNotes\n"
        "\t<Sound SFX>MySound\tSound SFX\treplacement Sound notes\n"
        + str(tmp_path / "different_filename.wav")
        + "\t<Sound SFX>MySound\\<AudioFileSource>NamedSource\tAudioFileSource\trequested Source notes\n", encoding="utf-8")
    code, verified = execute_table(command, run)
    assert code == 2 and verified["state"] == "verification_failed", verified


@pytest.mark.parametrize("fault", ("ignored-media", "extra-source"))
def test_exact_table_source_rejects_missing_effect_and_unplanned_source(tmp_path, fault):
    command, run, client, _ = table_draft(tmp_path, "2025.1")
    client.fault = fault
    code, verified = execute_table(command, run)
    assert code == 2 and verified["state"] == "verification_failed", verified


def test_exact_table_localized_source_inline_media_and_live_source_field_keep_owner_scope(tmp_path):
    command, run, client, table = table_draft(tmp_path, "2025.1", mode="reimport", existing_source=True, language="English(US)")
    client.objects["{22222222-2222-2222-2222-222222222222}"]["@Volume"] = -2.0
    wav = b"RIFF" + (4).to_bytes(4, "little") + b"WAVEdata"
    inline = "inline.wav|" + base64.b64encode(wav).decode("ascii")
    table.write_text("Audio File Base64\tObject Path\tObject Type\tNotes\tProperty[Volume]\n" + inline
        + "\t<Sound Voice>MySound\\<AudioFileSource>NamedSource\tAudioFileSource\tinline Source notes\t-4\n", encoding="utf-8")
    original = table.read_bytes()
    before_owner, before_sibling = deepcopy(client.objects[client.OWNER]), deepcopy(client.objects[client.UNRELATED])
    code, verified = execute_table(command, run)
    assert code == 0 and verified["verified"] is True, verified
    source = client.objects["{22222222-2222-2222-2222-222222222222}"]
    assert source["@Volume"] == -4.0 and Path(source["originalFilePath"]).read_bytes() == wav
    assert client.objects[client.OWNER] == before_owner and client.objects[client.UNRELATED] == before_sibling
    assert table.read_bytes() == original and client.unrelated_file.read_bytes() == b"unrelated bytes"


def test_exact_table_sound_replacement_rejects_descendant_drift_before_write(tmp_path):
    command, run, client, table = table_draft(tmp_path, "2025.1", mode="replace", existing_source=True)
    table.write_text("Audio File\tObject Path\tObject Type\tNotes\n"
        "\t<Sound SFX>MySound\tSound SFX\treplacement Sound notes\n"
        + str(tmp_path / "different_filename.wav")
        + "\t<Sound SFX>MySound\\<AudioFileSource>NamedSource\tAudioFileSource\trequested Source notes\n", encoding="utf-8")
    command("draft-check")
    preview = command("preview-from-draft")
    code, shown = run(*preview["next_command"]["gateway_argv"]); assert code == 0, shown
    assert run(*shown["next_command"]["gateway_argv"])[0] == 0
    nested_id = "{77777777-7777-7777-7777-777777777777}"
    client.objects[nested_id] = {"id": nested_id, "name": "Nested", "type": "Effect",
        "path": client.owner_path + r"\NamedSource\Nested", "parent": {"id": "{22222222-2222-2222-2222-222222222222}"}}
    code, rejected = run("execute", preview["transaction_id"])
    assert code == 2 and rejected["state"] == "repreview_required", rejected
    assert not any(uri == "ak.wwise.core.audio.importTabDelimited" for uri, _, _ in client.calls)
