from __future__ import annotations

from pathlib import Path

import pytest  # pyright: ignore[reportMissingImports]

from wwise_waapi.live_environment import (  # pyright: ignore[reportMissingImports]
    LiveEnvironmentError,
    WWISE_2023_1_CONSOLE_PATH,
    WWISE_2023_1_SAMPLE_PROJECT_PATH,
    path_is_under_immutable_sample_source,
    path_is_under_org_fixture,
    require_destructive_environment,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
ORG_FIXTURE_2023_ROOT = REPO_ROOT / "tests" / "_org" / "2023.1"


def test_2023_destructive_target_must_be_sandbox_copy(monkeypatch: pytest.MonkeyPatch) -> None:
    existing_path_exists = Path.exists
    fake_existing_paths = {
        WWISE_2023_1_CONSOLE_PATH.resolve(strict=False),
        WWISE_2023_1_SAMPLE_PROJECT_PATH.resolve(strict=False),
        WWISE_2023_1_SAMPLE_PROJECT_PATH.parent.resolve(strict=False),
    }

    def fake_exists(path: Path) -> bool:
        if path.resolve(strict=False) in fake_existing_paths:
            return True
        return existing_path_exists(path)

    monkeypatch.setattr(Path, "exists", fake_exists)
    installed_env = _destructive_env(
        fixture_project=WWISE_2023_1_SAMPLE_PROJECT_PATH,
        sandbox_root=WWISE_2023_1_SAMPLE_PROJECT_PATH.parent,
    )
    org_fixture_env = _destructive_env(
        fixture_project=ORG_FIXTURE_2023_ROOT / "SampleProject.wproj",
        sandbox_root=ORG_FIXTURE_2023_ROOT,
    )

    assert path_is_under_immutable_sample_source(WWISE_2023_1_SAMPLE_PROJECT_PATH)
    assert path_is_under_org_fixture(ORG_FIXTURE_2023_ROOT / "SampleProject.wproj")
    with pytest.raises(LiveEnvironmentError, match="immutable installed SampleProject"):
        require_destructive_environment(installed_env)
    with pytest.raises(LiveEnvironmentError, match="tests/_org"):
        require_destructive_environment(org_fixture_env)


def _destructive_env(*, fixture_project: Path, sandbox_root: Path) -> dict[str, str]:
    return {
        "WWISE_LIVE": "1",
        "WWISE_DESTRUCTIVE": "1",
        "WWISE_VERSION": "2023.1",
        "WWISE_FIXTURE_PROJECT": str(fixture_project),
        "WWISE_SANDBOX_ROOT": str(sandbox_root),
    }
