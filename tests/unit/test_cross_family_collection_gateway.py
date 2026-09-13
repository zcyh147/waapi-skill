"""Closed list clearing through the public Gateway, not playlist sequencing.

The fake replaces only the external Wwise API. Existing member GUIDs must
disappear after replace-all; an unchanged owner or empty list projection alone
must not certify that the removed objects disappeared.
"""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

import pytest

from tests.unit.test_field_interface_closure_gateway import (
    FIRST, SECOND, FieldTask, VERSIONS,
)


MEMBER = "{33333333-3333-3333-3333-333333333333}"


class CollectionTask(FieldTask):
    def __init__(self, path: Path, version: str, *, retain_removed: bool) -> None:
        super().__init__(path, version, "object.set")
        self.retain_removed = retain_removed
        self.objects = {
            FIRST: {
                "id": FIRST, "name": "Fight", "type": "MusicPlaylistContainer",
                "path": r"\Interactive Music Hierarchy\Default Work Unit\Fight",
                "parent": {"id": SECOND}, "notes": "Keep the owner notes",
                "@Stingers": [{"id": MEMBER}],
            },
            SECOND: {
                "id": SECOND, "name": "Default Work Unit", "type": "WorkUnit",
                "path": r"\Interactive Music Hierarchy\Default Work Unit",
                "notes": "Unrelated object stays unchanged",
            },
            MEMBER: {
                "id": MEMBER, "name": "", "type": "MusicStinger",
                "path": "[Stinger : Bonus,Fight]", "parent": {"id": FIRST},
                "owner": {"id": FIRST}, "notes": "",
            },
        }
        self.types = [
            {"classId": 34, "name": "MusicPlaylistContainer", "type": "WObject"},
            {"classId": 38, "name": "MusicStinger", "type": "WObject"},
            {"classId": 1, "name": "WorkUnit", "type": "WObject"},
        ]

    def call(self, uri: str, args: Any = None, options: Any = None) -> Any:
        if uri.endswith("object.set"):
            self.calls.append((uri, deepcopy(args), deepcopy(options)))
            # This operation must not submit owner properties, children, or
            # another list merely because they were present in live readback.
            assert args == {
                "objects": [{"object": FIRST, "listMode": "replaceAll", "@Stingers": []}],
                "onNameConflict": "fail", "listMode": "append",
                "autoAddToSourceControl": False,
            }
            self.objects[FIRST]["@Stingers"] = []
            if not self.retain_removed:
                del self.objects[MEMBER]
            return {"objects": [{key: deepcopy(value)
                                  for key, value in self.objects[FIRST].items()
                                  if key in options["return"]}]}
        if uri.endswith("object.get") and "from" in args:
            self.calls.append((uri, deepcopy(args), deepcopy(options)))
            if args.get("transform"):
                assert args["transform"] in (
                    [{"select": ["descendants"]}], [{"select": ["children"]}],
                )
                return {"return": []}
            return {"return": [deepcopy(self.objects[value])
                               for value in args["from"]["id"] if value in self.objects]}
        if uri.endswith("object.get") and args.get("waql") == f'from object "{SECOND}" take 1':
            self.calls.append((uri, deepcopy(args), deepcopy(options)))
            return {"return": [deepcopy(self.objects[SECOND])]}
        return super().call(uri, args, options)


@pytest.mark.parametrize("version", VERSIONS[1:])
@pytest.mark.parametrize("retain_removed", (False, True))
def test_clear_owned_list_verifies_removed_guids_not_only_empty_list(
    tmp_path: Path, version: str, retain_removed: bool,
) -> None:
    task = CollectionTask(tmp_path, version, retain_removed=retain_removed)
    owner = task.bind(FIRST)
    code, cleared = task.step(
        "draft-clear-object-list", "--declaration-id", "clear-stingers",
        "--object-handle", owner, "--list-name", "Stingers",
    )
    assert code == 0, cleared
    code, checked = task.step("draft-check")
    assert code == 0, checked
    code, preview = task.step("preview-from-draft")
    assert code == 0, preview
    transaction = preview["transaction_id"]
    code, shown = task.run("transaction-show", transaction, "--summary-only")
    assert code == 0, shown
    code, confirmed = task.run(
        "confirm", transaction, "--confirmation-token", shown["confirmation"]["token"],
    )
    assert code == 0, confirmed
    code, executed = task.run("execute", transaction)
    assert code == 0, executed
    code, verified = task.run("verify", transaction)
    if retain_removed:
        assert code == 2, verified
        assert verified["state"] == "verification_failed"
    else:
        assert code == 0, json.dumps(verified)
        assert verified["verified"] is True
    # The public closed query observes an unrelated exact identity after the
    # mutation; verification is never inferred from the fake's internal state.
    code, queried = task.run("query-object", "--exact-id", SECOND,
                             "--include", "notes", "--max-results", "1")
    assert code == 0, queried
    assert queried["objects"][0]["id"] == SECOND
    assert queried["objects"][0]["notes"] == "Unrelated object stays unchanged"
