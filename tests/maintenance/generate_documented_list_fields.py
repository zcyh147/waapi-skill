"""Extract every indexed Wwise Objects Reference page; no native connection."""
from __future__ import annotations

import argparse
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re


class Node:
    def __init__(self, tag="", attrs=()):
        self.tag, self.attrs, self.children = tag, dict(attrs), []

    def text(self):
        return " ".join(" ".join(child.text() if isinstance(child, Node) else child
                                 for child in self.children).split())

    def walk(self, tag):
        for child in self.children:
            if isinstance(child, Node):
                if child.tag == tag:
                    yield child
                yield from child.walk(tag)


class Document(HTMLParser):
    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.root = Node()
        self.stack = [self.root]
        self.feed(text)
        self.close()

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in {"br", "hr", "img", "meta", "link", "input", "wbr", "area", "base", "embed", "source"}:
            self.stack.append(node)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def cells(row):
    return [child for child in row.children if isinstance(child, Node) and child.tag in {"td", "th"}]


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def extract(corpus: Path, version: str, build: str, archive: Path):
    index_path = corpus / "wobjects_index.html"
    index = Document(index_path.read_text(encoding="utf-8"))
    entries = []
    for row in index.root.walk("tr"):
        columns = cells(row)
        if len(columns) != 3:
            continue
        links = [link for link in columns[0].walk("a")
                 if re.fullmatch(r"wwiseobject_[a-z0-9_]+\.html", link.attrs.get("href", ""))]
        if not links:
            continue
        if len(links) != 1 or not columns[2].text().isdigit():
            raise ValueError("Malformed indexed per-type declaration")
        entries.append({"name": links[0].text(), "class_id": int(columns[2].text()),
                        "source_member": links[0].attrs["href"]})
    if not entries or len({row["source_member"] for row in entries}) != len(entries):
        raise ValueError("The full per-type index is empty or duplicated")
    type_ids = {row["name"]: row["class_id"] for row in entries}
    if len(type_ids) != len(entries) or len({row["class_id"] for row in entries}) != len(entries):
        raise ValueError("The per-type index has ambiguous names/class IDs")
    omissions = []
    classes = []
    for entry in entries:
        path = corpus / entry["source_member"]
        if not path.is_file():
            omissions.append({**entry, "reason": "indexed_member_not_extracted"})
            continue
        raw = path.read_bytes()
        page = Document(raw.decode("utf-8"))
        ids = re.findall(r"Class ID\s*:\s*(\d+)", page.root.text())
        if ids != [str(entry["class_id"])]:
            raise ValueError(f"Index/page class mismatch: {path.name}")
        lists, scalar_references = [], []
        fields = set()
        for table in page.root.walk("table"):
            if table.attrs.get("class") != "doxtable":
                continue
            for row in table.walk("tr"):
                columns = cells(row)
                if len(columns) < 5 or not list(columns[0].walk("b")):
                    continue
                name, label, kind = (column.text() for column in columns[:3])
                if name in fields:
                    raise ValueError(f"Duplicate published field: {entry['name']}.{name}")
                fields.add(name)
                if kind == "Reference":
                    scalar_references.append(name)
                if kind != "List":
                    continue
                restrictions = columns[4]
                if "Possible types :" not in restrictions.text():
                    raise ValueError(f"List has unparsed element restrictions: {entry['name']}.{name}")
                allowed = [cells(child)[0].text() for child in restrictions.walk("tr") if len(cells(child)) == 1]
                if not allowed or len(set(allowed)) != len(allowed):
                    raise ValueError("List element declaration is empty or duplicated")
                lists.append({"name": name, "display_name": label, "declared_kind": "List",
                    "element_classes": [{"name": name, "class_id": type_ids[name]} for name in allowed if name in type_ids],
                    "unresolved_element_types": [name for name in allowed if name not in type_ids]})
        classes.append({**entry, "source_sha256": hashlib.sha256(raw).hexdigest(),
                        "lists": lists, "scalar_references": scalar_references})
    archive_hash = hashlib.sha256()
    with archive.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            archive_hash.update(chunk)
    payload = {"contract": "waapi-skill.documented-list-fields/v1", "version": version,
        "source": {"build": build, "archive": archive.name, "archive_sha256": archive_hash.hexdigest(),
                   "index_member": index_path.name, "index_sha256": hashlib.sha256(index_path.read_bytes()).hexdigest()},
        "coverage": {"indexed_pages": len(entries), "extracted_pages": len(classes), "omissions": omissions,
            "inheritance": "explicit published per-type rows only; unlisted inherited/plugin fields remain unresolved",
            "native_availability": "not inferred from absent source declarations"},
        "classes": classes}
    return {**payload, "catalog_sha256": digest(payload)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--build", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = extract(args.corpus, args.version, args.build, args.archive)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"version": args.version, **payload["coverage"],
                      "list_fields": sum(len(row["lists"]) for row in payload["classes"])}))


if __name__ == "__main__":
    main()
