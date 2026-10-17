"""Extract pinned parent declarations without launching a Wwise process.

This developer-only source collector verifies each complete installed XML file
against the committed corpus before extracting its exact parent node.
"""
from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET


def collect(root: Path, installed_root: Path) -> dict:
    source = json.loads((root / "docs/branch-coverage-condition-sources.json").read_text())
    records, parsed, files_snapshot = {}, {}, {}
    for corpus in source["corpora"]:
        for lane in corpus["lanes"]:
            files = {f["path"]: f for f in lane["files"]}
            relative = "Authoring/Data" if corpus["name"] == "condition" else "Authoring/x64/Release/bin/plugins"
            for row in lane["rows"]:
                attrs = row["attributes"]
                if (row["tag"] != "PropertyDependency" or attrs.get("Action", "Enable") != "Enable"
                        or attrs.get("Context", "Self") != "Self"
                        or not any(n.tag in {"Enumeration", "Range"} for n in ET.fromstring(row["xml"]).iter())):
                    continue
                key = "|".join((lane["build"], corpus["name"], row["file"], row["path"]))
                cache = (lane["build"], corpus["name"], row["file"])
                if cache not in parsed:
                    path = installed_root / ("Wwise " + lane["build"]) / relative / row["file"]
                    raw = path.read_bytes()
                    if hashlib.sha256(raw).hexdigest() != files[row["file"]]["sha256"]:
                        raise ValueError("pinned installed source digest mismatch: " + str(path))
                    parsed[cache] = ET.fromstring(raw)
                    files_snapshot["|".join(cache)] = {
                        "sha256": files[row["file"]]["sha256"],
                        "bytes_base64": base64.b64encode(raw).decode("ascii")}
                node = parsed[cache]
                components = row["path"].split("/")[:-1]
                if components.pop(0) != node.tag:
                    raise ValueError("unexpected installed source root")
                for component in components:
                    match = re.fullmatch(r"([^\[]+)(?:\[(.*)\])?", component)
                    choices = [n for n in node if n.tag == match[1]
                               and (match[2] is None or n.get("Name", n.get("name")) == match[2])]
                    if len(choices) != 1:
                        raise ValueError("installed parent selector is not exact: " + key)
                    node = choices[0]
                # The complete source hash and exact parent subtree are retained;
                # runtime live metadata remains a separate fact.
                xml = ET.tostring(node, encoding="unicode").strip()
                record = {"build": lane["build"], "corpus": corpus["name"], "file": row["file"],
                          "pointer": "/".join(components), "tag": node.tag, "attributes": dict(node.attrib),
                          "source_file_sha256": files[row["file"]]["sha256"], "xml": xml,
                          "parent_xml_sha256": hashlib.sha256(xml.encode()).hexdigest()}
                if key in records and records[key] != record:
                    raise ValueError("conflicting exact installed parent")
                records[key] = record
    return {"contract": "waapi-skill.installed-condition-parent-sources/v1",
            "evidence_kind": "installed_definition_only", "parents": records, "files": files_snapshot}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installed-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    document = collect(Path(__file__).resolve().parents[2], args.installed_root)
    raw = (json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
    args.output.write_bytes(gzip.compress(raw, mtime=0) if args.output.suffix == ".gz" else raw)
