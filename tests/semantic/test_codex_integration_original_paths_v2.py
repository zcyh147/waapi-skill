from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any, Callable

import pytest

from tests.semantic.support.codex_integration_footsteps_runtime_v2 import (
    FootstepsIntegrationRuntimeError,
    _copied_original_proof as footsteps_original_proof,
)
from tests.semantic.support.codex_integration_paths_v2 import (
    IntegrationOriginalPathError,
    localize_copied_original_path,
)
from tests.semantic.support.codex_integration_rifle_runtime_v2 import (
    RifleIntegrationRuntimeError,
    _copied_original_proof as rifle_original_proof,
)
from tests.semantic.support.codex_integration_weapons_runtime_v2 import (
    WeaponsIntegrationRuntimeError,
    _copied_original_proof as weapons_original_proof,
)


ProofFunction = Callable[..., Any]
RUNTIME_PROOFS: tuple[tuple[str, ProofFunction, type[Exception]], ...] = (
    ("rifle", rifle_original_proof, RifleIntegrationRuntimeError),
    ("footsteps", footsteps_original_proof, FootstepsIntegrationRuntimeError),
    ("weapons", weapons_original_proof, WeaponsIntegrationRuntimeError),
)


def _sandbox_original(tmp_path: Path) -> tuple[Path, Path, Path]:
    account_home = tmp_path / "account-home"
    sandbox_root = account_home / "campaign" / "sandbox"
    original = sandbox_root / "Originals" / "SFX" / "test.wav"
    original.parent.mkdir(parents=True)
    original.write_bytes(b"integration-v2-original\n")
    return account_home, sandbox_root, original


def _wine_y_path(path: Path, *, account_home: Path) -> str:
    relative = path.relative_to(account_home).as_posix()
    return "Y:\\" + relative.replace("/", "\\")


@pytest.mark.skipif(os.name == "nt", reason="Wine aliases are POSIX-host paths")
@pytest.mark.parametrize(
    ("runtime_name", "proof", "error_type"),
    RUNTIME_PROOFS,
    ids=[row[0] for row in RUNTIME_PROOFS],
)
@pytest.mark.parametrize(
    ("version", "path_kind"),
    (("2022.1", "wine-y"), ("2025.1", "native")),
)
def test_runtime_accepts_representative_2022_and_2025_original_paths(
    tmp_path: Path,
    runtime_name: str,
    proof: ProofFunction,
    error_type: type[Exception],
    version: str,
    path_kind: str,
) -> None:
    del runtime_name, error_type
    account_home, sandbox_root, original = _sandbox_original(tmp_path)
    value = (
        _wine_y_path(original, account_home=account_home)
        if path_kind == "wine-y"
        else str(original)
    )

    result = proof(
        value,
        sandbox_root=sandbox_root,
        account_home=account_home,
    )

    assert result.relative_path == "Originals/SFX/test.wav"
    assert result.sha256 == hashlib.sha256(original.read_bytes()).hexdigest()
    assert version in {"2022.1", "2025.1"}


@pytest.mark.skipif(os.name == "nt", reason="Wine aliases are POSIX-host paths")
@pytest.mark.parametrize(
    ("runtime_name", "proof", "error_type"),
    RUNTIME_PROOFS,
    ids=[row[0] for row in RUNTIME_PROOFS],
)
def test_runtime_accepts_wine_z_root_mapping(
    tmp_path: Path,
    runtime_name: str,
    proof: ProofFunction,
    error_type: type[Exception],
) -> None:
    del runtime_name, error_type
    account_home, sandbox_root, original = _sandbox_original(tmp_path)

    result = proof(
        "Z:" + original.as_posix(),
        sandbox_root=sandbox_root,
        account_home=account_home,
    )

    assert result.relative_path == "Originals/SFX/test.wav"


@pytest.mark.skipif(os.name == "nt", reason="Wine aliases are POSIX-host paths")
@pytest.mark.parametrize(
    ("runtime_name", "proof", "error_type"),
    RUNTIME_PROOFS,
    ids=[row[0] for row in RUNTIME_PROOFS],
)
@pytest.mark.parametrize(
    ("value", "message"),
    (
        ("X:/campaign/sandbox/Originals/SFX/test.wav", "unsupported Wine drive X:"),
        ("//server/share/test.wav", "unsupported UNC path"),
        (
            "Y:/campaign/sandbox/Originals/../SFX/test.wav",
            "unsafe path component",
        ),
    ),
)
def test_runtime_rejects_unreviewed_or_unsafe_wine_paths(
    tmp_path: Path,
    runtime_name: str,
    proof: ProofFunction,
    error_type: type[Exception],
    value: str,
    message: str,
) -> None:
    del runtime_name
    account_home, sandbox_root, _original = _sandbox_original(tmp_path)

    with pytest.raises(error_type, match=message):
        proof(
            value,
            sandbox_root=sandbox_root,
            account_home=account_home,
        )


@pytest.mark.skipif(os.name == "nt", reason="Wine aliases are POSIX-host paths")
@pytest.mark.parametrize(
    ("runtime_name", "proof", "error_type"),
    RUNTIME_PROOFS,
    ids=[row[0] for row in RUNTIME_PROOFS],
)
def test_runtime_rejects_y_path_outside_its_sandbox_originals(
    tmp_path: Path,
    runtime_name: str,
    proof: ProofFunction,
    error_type: type[Exception],
) -> None:
    del runtime_name
    account_home, sandbox_root, _original = _sandbox_original(tmp_path)
    outside = account_home / "other" / "Originals" / "outside.wav"
    outside.parent.mkdir(parents=True)
    outside.write_bytes(b"outside\n")

    with pytest.raises(error_type, match="outside the sandbox|escapes the sandbox"):
        proof(
            _wine_y_path(outside, account_home=account_home),
            sandbox_root=sandbox_root,
            account_home=account_home,
        )


@pytest.mark.skipif(os.name == "nt", reason="Wine aliases are POSIX-host paths")
def test_wine_y_uses_os_account_home_not_disposable_home(monkeypatch: pytest.MonkeyPatch) -> None:
    try:
        import pwd
    except ImportError:  # pragma: no cover - guarded by the platform skip.
        pytest.skip("pwd is unavailable")
    account_home = Path(pwd.getpwuid(os.getuid()).pw_dir).resolve(strict=True)
    monkeypatch.setenv("HOME", "/tmp/disposable-codex-home-must-not-be-used")

    assert localize_copied_original_path("Y:/Documents/example.wav") == (
        account_home / "Documents" / "example.wav"
    )


@pytest.mark.skipif(os.name == "nt", reason="Wine aliases are POSIX-host paths")
def test_shared_localizer_rejects_malformed_drive_path(tmp_path: Path) -> None:
    with pytest.raises(
        IntegrationOriginalPathError,
        match="malformed Wine drive path",
    ):
        localize_copied_original_path("Y:relative.wav", account_home=tmp_path)
