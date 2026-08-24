"""Deterministic WAAPI read shim for the production-Gateway semantic profile."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Mapping


FIXTURE_ENV = "WAAPI_AUDIO_IMPORT_BUSINESS_FIXTURE"
_BUILTIN_FIELDS = {
    "IsLoopingEnabled": {
        "name": "IsLoopingEnabled",
        "type": "Boolean",
        "restriction": {},
    },
    "IsLoopingInfinite": {
        "name": "IsLoopingInfinite",
        "type": "Boolean",
        "restriction": {},
    },
    "Volume": {
        "name": "Volume",
        "type": "Real32",
        "restriction": {"type": "range", "min": -96.3, "max": 96.3},
    },
    "OutputBus": {
        "name": "OutputBus",
        "type": "Reference",
        "restriction": {
            "type": "reference",
            "restrictions": [{"type": ["Bus", "AuxBus"]}],
        },
    },
}
_UNIQUE_NAME_WAQL = re.compile(
    r'^from search "(?P<name>[^"\r\n]+)" '
    r'where name = "(?P=name)" take 2$'
)


class WaapiRequestFailed(RuntimeError):
    pass


class WaapiClient:
    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        path = Path(os.environ[FIXTURE_ENV]).expanduser().resolve(strict=True)
        self.fixture = json.loads(path.read_text(encoding="utf-8"))

    def disconnect(self) -> None:
        return None

    def call(
        self,
        uri: str,
        args: Mapping[str, Any] | None = None,
        options: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        arguments = dict(args or {})
        if uri == "ak.wwise.core.getInfo":
            year, major = self.fixture["version"].split(".")
            return {
                "displayName": "Wwise",
                "isCommandLine": True,
                "sessionId": "{BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB}",
                "processId": 4242,
                "processPath": str(self.fixture["process_path"]),
                "apiVersion": 1,
                "platform": self.fixture["platform"],
                "configuration": "release",
                "version": {
                    "year": int(year),
                    "major": int(major),
                    "minor": 0,
                    "build": 1,
                    "displayName": f"v{year}.{major}.0.1",
                },
            }
        if uri == "ak.wwise.core.getProjectInfo":
            project_path = Path(self.fixture["project_path"])
            root = project_path.parent
            return {
                "id": "{AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA}",
                "name": "SemanticProject",
                "displayTitle": "SemanticProject - Wwise",
                "path": str(project_path),
                "isDirty": False,
                "currentLanguageId": "{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}",
                "referenceLanguageId": "{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}",
                "languages": [
                    {
                        "id": "{CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC}",
                        "name": "English(US)",
                        "shortId": 1,
                    }
                ],
                "currentPlatformId": "{DDDDDDDD-DDDD-DDDD-DDDD-DDDDDDDDDDDD}",
                "platforms": [
                    {
                        "id": "{DDDDDDDD-DDDD-DDDD-DDDD-DDDDDDDDDDDD}",
                        "name": "Windows",
                        "baseName": "Windows",
                        "baseDisplayName": "Windows",
                        "soundBankPath": str(root / "GeneratedSoundBanks" / "Windows"),
                        "copiedMediaPath": str(root / "GeneratedSoundBanks" / "Windows"),
                    }
                ],
                "defaultConversion": {
                    "id": "{EEEEEEEE-EEEE-EEEE-EEEE-EEEEEEEEEEEE}",
                    "name": "Default Conversion Settings",
                },
                "directories": {
                    "root": str(root),
                    "cache": str(root / ".cache"),
                    "originals": str(root / "Originals"),
                    "soundBankOutputRoot": str(root / "GeneratedSoundBanks"),
                    "commands": str(root / "Commands"),
                    "properties": str(root),
                },
            }
        if uri == "ak.wwise.core.object.getTypes":
            names = sorted({str(row["type"]) for row in self.fixture["objects"]} | {"Sound"})
            return {
                "return": [
                    {"classId": index, "name": name, "type": name}
                    for index, name in enumerate(names, start=1)
                ]
            }
        if uri == "ak.wwise.core.object.getPropertyAndReferenceNames":
            return {
                "return": sorted(
                    {*_BUILTIN_FIELDS, *(row["token"] for row in self.fixture["fields"])}
                )
            }
        if uri == "ak.wwise.core.object.getPropertyInfo":
            token = arguments.get("property")
            builtin = _BUILTIN_FIELDS.get(str(token))
            if builtin is not None:
                return dict(builtin)
            matches = [row for row in self.fixture["fields"] if row["token"] == token]
            if len(matches) != 1:
                raise WaapiRequestFailed(f"unknown fixture field: {token!r}")
            row = matches[0]
            return {
                "name": row["token"],
                "type": row["type"],
                "restriction": row["restriction"],
            }
        if uri == "ak.wwise.core.object.isPropertyEnabled":
            return {"enabled": True}
        if uri == "ak.wwise.core.object.get":
            source = arguments.get("from", {})
            if not isinstance(source, Mapping):
                source = {}
            selected: list[Mapping[str, Any]] = []
            ids = source.get("id")
            paths = source.get("path")
            waql = arguments.get("waql")
            name_match = (
                _UNIQUE_NAME_WAQL.fullmatch(waql)
                if isinstance(waql, str)
                else None
            )
            for row in self.fixture["objects"]:
                if isinstance(ids, list) and row["id"] in ids:
                    selected.append(row)
                elif isinstance(paths, list) and row["path"] in paths:
                    selected.append(row)
                elif name_match is not None and row["name"] == name_match["name"]:
                    selected.append(row)
            result = []
            for row in selected:
                value = {
                    "id": row["id"],
                    "name": row["name"],
                    "type": row["type"],
                    "path": row["path"],
                }
                if row.get("type") == "Sound":
                    value["@IsVoice"] = bool(row.get("is_voice", False))
                result.append(value)
            return {"return": result}
        raise WaapiRequestFailed(f"unexpected fixture call: {uri}")
