"""Private-file proofs for closed provider profiles; never serialize native values."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import stat
from typing import Any, Mapping

from .canonical import canonical_json_bytes
from .filesystem_security import path_is_link_or_reparse

PROFILE_CONTRACT = "waapi-skill.source-control-profile/v1"
BINDING_CONTRACT = "waapi-skill.source-control-profile-binding/v1"
SET_PROVIDER = "ak.wwise.core.sourceControl.setProvider"
_CONNECTION = frozenset({"host", "port", "server", "username", "workspace"})
_KEYS = frozenset({"contract", "handle", "label", "selection", "provider", "config_file", "profile_file",
                   "credential_file", "state_root", "key_id", "file_proofs", "content_mac"})


class ProviderProfileError(ValueError):
    error_code = "SOURCE_CONTROL_PROFILE_PROOF_REQUIRED"


def _fail() -> Any:
    raise ProviderProfileError("Provider profile proof is unavailable or changed. Configure one closed owner-private profile and credential file, use an owner-private state directory, and create a new Draft after any change.")


def _private(path: Path, metadata: os.stat_result, *, directory: bool) -> None:
    if os.name == "posix":
        if metadata.st_uid != os.geteuid() or stat.S_IMODE(metadata.st_mode) & 0o077:
            _fail()
    elif os.name == "nt":
        from .source_control_windows_permissions import require_private_windows_path
        require_private_windows_path(path, directory=directory)
    else:
        _fail()


def _path(path: Path, *, directory: bool = False, private: bool = True) -> os.stat_result:
    if not path.is_absolute():
        _fail()
    for ancestor in (path, *path.parents):
        metadata = ancestor.lstat()
        if path_is_link_or_reparse(ancestor, metadata=metadata):
            _fail()
    metadata = path.lstat()
    if directory:
        if not stat.S_ISDIR(metadata.st_mode):
            _fail()
    elif not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        _fail()
    if private:
        _private(path, metadata, directory=directory)
    return metadata


def _proof(path: Path, metadata: os.stat_result) -> dict[str, Any]:
    return {"path": str(path), "device": metadata.st_dev, "inode": metadata.st_ino,
            "size": metadata.st_size, "mtime_ns": metadata.st_mtime_ns,
            "ctime_ns": metadata.st_ctime_ns if os.name != "nt" else None, "mode": metadata.st_mode}


def _read(path: Path, maximum: int, *, private: bool = True) -> tuple[bytes, dict[str, Any]]:
    before = _path(path, private=private)
    if before.st_size > maximum:
        _fail()
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0))
    try:
        opened = os.fstat(fd)
        if not os.path.samestat(before, opened):
            _fail()
        data = bytearray()
        while len(data) <= maximum:
            chunk = os.read(fd, min(4096, maximum + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
        after = os.fstat(fd)
        final = _path(path, private=private)
        if _proof(path, before) != _proof(path, after) or _proof(path, after) != _proof(path, final) or len(data) != after.st_size or len(data) > maximum:
            _fail()
        return bytes(data), _proof(path, final)
    finally:
        os.close(fd)


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _fail()
        result[key] = value
    return result


def _document(data: bytes) -> dict[str, Any]:
    value = json.loads(data.decode("utf-8"), object_pairs_hook=_pairs,
                       parse_constant=lambda _value: _fail())
    allowed = {"contract", "label", "selection", "provider", "connection", "password_file"}
    if not isinstance(value, dict) or set(value) - allowed or value.get("contract") != PROFILE_CONTRACT:
        _fail()
    label = value.get("label")
    if not isinstance(label, str) or not label.strip() or label != label.strip() or len(label.encode()) > 120 or any(ord(ch) < 32 for ch in label):
        _fail()
    if value.get("selection") == "disabled":
        if set(value) != {"contract", "label", "selection"}:
            _fail()
    elif value.get("selection") == "provider":
        provider = value.get("provider")
        connection = value.get("connection", {})
        if not isinstance(provider, str) or not provider or len(provider.encode()) > 256 or any(ord(ch) < 32 for ch in provider):
            _fail()
        if not isinstance(connection, dict) or set(connection) - _CONNECTION or any(not isinstance(v, str) for v in connection.values()):
            _fail()
        if provider == "Perforce" and (not {"host", "port", "username", "workspace"} <= set(connection) or "password_file" not in value):
            _fail()
    else:
        _fail()
    return value


def _bundle(config_file: Path, profile_file: Path) -> tuple[dict[str, Any], list[bytes], list[dict[str, Any]], str | None]:
    _path(profile_file.parent, directory=True)
    config, config_proof = _read(config_file, 64 * 1024, private=False)
    profile, profile_proof = _read(profile_file, 16 * 1024)
    document = _document(profile)
    contents, proofs = [config, profile], [config_proof, profile_proof]
    credential = None
    if "password_file" in document:
        name = document["password_file"]
        if not isinstance(name, str) or not name or name in {".", ".."} or any(ch in name for ch in ("/", "\\", "\x00")) or len(name.encode()) > 255:
            _fail()
        credential = profile_file.parent / name
        data, proof = _read(credential, 8 * 1024)
        data.decode("utf-8")
        contents.append(data)
        proofs.append(proof)
    return document, contents, proofs, str(credential) if credential else None


def _key(state: Path, *, create: bool) -> bytes:
    _path(state, directory=True)
    private = state / "provider-profiles"
    if create:
        try:
            private.mkdir(mode=0o700)
        except FileExistsError:
            pass
    _path(private, directory=True)
    path = private / "content.key"
    if create and not path.exists():
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            key = secrets.token_bytes(32)
            if os.write(fd, key) != len(key):
                _fail()
            os.fsync(fd)
        finally:
            os.close(fd)
    data, _ = _read(path, 32)
    if len(data) != 32:
        _fail()
    return data


def _mac(key: bytes, binding: Mapping[str, Any], contents: list[bytes]) -> str:
    digest = hmac.new(key, canonical_json_bytes({k: v for k, v in binding.items() if k != "content_mac"}), hashlib.sha256)
    for data in contents:
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def capture_profile(*, config_file: Path, profile_file: Path | None, state_root: Path, project_root: Path) -> dict[str, Any]:
    try:
        if profile_file is None or profile_file.is_relative_to(project_root):
            _fail()
        document, contents, proofs, credential = _bundle(config_file, profile_file)
        key = _key(state_root, create=True)
        binding = {"contract": BINDING_CONTRACT, "handle": "scp1-" + secrets.token_hex(16),
                   "label": document["label"], "selection": document["selection"],
                   "provider": document.get("provider", ""), "config_file": str(config_file),
                   "profile_file": str(profile_file), "credential_file": credential,
                   "state_root": str(state_root), "key_id": hashlib.sha256(key).hexdigest(), "file_proofs": proofs}
        binding["content_mac"] = _mac(key, binding, contents)
        return binding
    except (OSError, ValueError, TypeError, UnicodeError):
        _fail()


def validate_binding(binding: Any) -> dict[str, Any]:
    if not isinstance(binding, Mapping) or set(binding) != _KEYS or binding.get("contract") != BINDING_CONTRACT:
        _fail()
    if not isinstance(binding.get("handle"), str) or not binding["handle"].startswith("scp1-"):
        _fail()
    return dict(binding)


def _observe_binding(binding: Any) -> tuple[dict[str, Any], dict[str, Any], list[bytes], str | None]:
    try:
        bound = validate_binding(binding)
        key = _key(Path(bound["state_root"]), create=False)
        if not hmac.compare_digest(hashlib.sha256(key).hexdigest(), bound["key_id"]):
            _fail()
        document, contents, proofs, credential = _bundle(Path(bound["config_file"]), Path(bound["profile_file"]))
        if (proofs != bound["file_proofs"] or credential != bound["credential_file"]
            or document["label"] != bound["label"] or document["selection"] != bound["selection"]
            or document.get("provider", "") != bound["provider"]
            or not hmac.compare_digest(_mac(key, bound, contents), bound["content_mac"])):
            _fail()
        return bound, document, contents, credential
    except (OSError, ValueError, TypeError, KeyError, UnicodeError):
        _fail()


def resolve_profile(binding: Any) -> dict[str, str]:
    """Return transient native values only to the protected dispatcher resolver."""
    try:
        bound, document, contents, credential = _observe_binding(binding)
        args = {"provider": bound["provider"], **document.get("connection", {})}
        if credential is not None:
            args["password"] = contents[-1].decode("utf-8")
        return args
    except (OSError, ValueError, TypeError, KeyError, UnicodeError):
        _fail()


def check_profile(binding: Any) -> None:
    _observe_binding(binding)
