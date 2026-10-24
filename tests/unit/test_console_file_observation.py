"""Native fixture evidence retains bytes independently of sandbox cleanup."""
from __future__ import annotations

import base64
from pathlib import Path

from tests.destructive.support.console_file_observation import observe_console_file


def test_console_observation_keeps_unknown_container_bytes_after_cleanup(tmp_path: Path) -> None:
    artifact = tmp_path / "Project.mediaid"
    original = b"\x00\xffOpaque native container\r\n"
    artifact.write_bytes(original)

    observation = observe_console_file(artifact, io_root=tmp_path)
    artifact.unlink()

    assert base64.b64decode(observation["content_base64"], validate=True) == original
    assert observation["file_proof"]["size"] == len(original)
    assert observation["representation"] == "uninterpreted_native_file_bytes"
    assert observation["business_effect_verified"] is False
