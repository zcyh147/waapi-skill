from __future__ import annotations

import os
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping, Sequence

import pytest

from tests.semantic import run_codex_skill_campaign as campaign
from tests.semantic import run_codex_skill_matrix as matrix
from tests.semantic.support.codex_campaign import (
    ATTEMPT_MANIFEST_FILE,
    CampaignEvidenceError,
    create_attempt,
    list_campaign_attempts,
    load_verified_json,
    sha256_file,
    stable_tree_sha256,
)
from tests.semantic.support.codex_campaign_runner import (
    LIVE_READINESS_RETRY_CATEGORY,
    ChildValidation,
    PhaseVerdict,
)
from tests.semantic.support.codex_eval_suite import EvalSession, load_eval_suite


_SCREENING = load_eval_suite(matrix.DEFAULT_SUITE).expand_profile("screening")
_C1 = next(session for session in _SCREENING if session.case.id == "C1")


def test_typed_input_profile_uses_a_bounded_long_form_turn_budget(
    tmp_path: Path,
) -> None:
    options = campaign.parse_args(
        [
            "--campaign-root",
            str(tmp_path / "typed-input"),
            "--profile",
            matrix.TYPED_INPUT_PROFILE_ID,
        ]
    )

    assert options.timeout_seconds == matrix.TYPED_INPUT_CODEX_TIMEOUT_SECONDS
    assert options.timeout_seconds == 360.0
    assert options.max_pre_action_retries == 0


def test_campaign_readiness_timeout_is_explicit_positive_and_finite(
    tmp_path: Path,
) -> None:
    explicit = campaign.parse_args(
        [
            "--campaign-root",
            str(tmp_path / "campaign"),
            "--wwise-readiness-timeout",
            "180",
        ]
    )

    assert explicit.wwise_readiness_timeout_seconds == 180.0
    for invalid in ("0", "-1", "nan", "inf"):
        with pytest.raises(SystemExit):
            campaign.parse_args(
                [
                    "--campaign-root",
                    str(tmp_path / invalid),
                    "--wwise-readiness-timeout",
                    invalid,
                ]
            )


@pytest.mark.parametrize(
    "semantic_tree_sha256",
    [
        "b152de8c55f8cb1085321da3ec877507627352acb10bed43e2ba7dbfae8b37df",
        "5100e2c672d2461fe0ce96dba4b0cf1536a43d48e100ad2ac3fc5dbc0203efdb",
    ],
)
def test_reviewed_audio_import_harness_selects_sfx_protocol_revision(
    semantic_tree_sha256: str,
) -> None:
    effective = {
        "selection": {"profile": matrix.AUDIO_IMPORT_BUSINESS_PROFILE_ID},
        "harness": {"semantic_tree_sha256": semantic_tree_sha256},
    }

    assert campaign._sealed_protocol_manifest_revision(effective) == (
        campaign.AUDIO_IMPORT_DERIVED_SFX_PROTOCOL_REVISION
    )


def test_unreviewed_harness_does_not_select_protocol_revision() -> None:
    effective = {
        "selection": {"profile": matrix.AUDIO_IMPORT_BUSINESS_PROFILE_ID},
        "harness": {"semantic_tree_sha256": "0" * 64},
    }

    with pytest.raises(
        CampaignEvidenceError,
        match="historical harness hash is unreviewed",
    ):
        campaign._sealed_protocol_manifest_revision(effective)


def test_current_audio_import_effective_selects_sealed_protocol_revision() -> None:
    effective = {
        "selection": {"profile": matrix.AUDIO_IMPORT_BUSINESS_PROFILE_ID},
        "harness": {
            "semantic_tree_sha256": "0" * 64,
            "protocol_manifest_revision": (
                campaign._CURRENT_AUDIO_IMPORT_PROTOCOL_REVISION
            ),
        },
    }

    assert campaign._sealed_protocol_manifest_revision(effective) == (
        campaign._CURRENT_AUDIO_IMPORT_PROTOCOL_REVISION
    )



def _options(
    tmp_path: Path,
    *,
    pair_ids: tuple[str, ...] = (_C1.pair_id,),
) -> campaign.CampaignOptions:
    skill = tmp_path / "skill"
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text("# frozen candidate\n", encoding="utf-8")
    codex = (
        tmp_path / "codex-release" / "bin" / "codex.exe"
        if os.name == "nt"
        else tmp_path / "codex"
    )
    codex.parent.mkdir(parents=True, exist_ok=True)
    codex.write_text("synthetic executable; never invoked\n", encoding="utf-8")
    if os.name == "nt":
        release = codex.parent.parent
        (release / "codex-package.json").write_text(
            '{"version":"1.2.3"}\n',
            encoding="utf-8",
        )
        for helper in (
            release / "bin" / "codex-code-mode-host.exe",
            release / "codex-path" / "rg.exe",
            release / "codex-resources" / "codex-command-runner.exe",
            release / "codex-resources" / "codex-windows-sandbox-setup.exe",
        ):
            helper.parent.mkdir(parents=True, exist_ok=True)
            helper.write_text("synthetic helper\n", encoding="utf-8")
    auth = tmp_path / "auth.json"
    auth.write_text("{}\n", encoding="utf-8")
    live_config = tmp_path / "live-config.json"
    live_config.write_text("{}\n", encoding="utf-8")
    return campaign.CampaignOptions(
        campaign_root=tmp_path / "workspace" / "campaign",
        resume=False,
        verify_only=False,
        profile="screening",
        suite_path=matrix.DEFAULT_SUITE.resolve(),
        skill_source=skill.resolve(),
        codex_binary=codex.resolve(),
        auth_json=auth.resolve(),
        live_config=live_config.resolve(),
        model="synthetic-model",
        reasoning_effort="medium",
        service_tier="priority",
        timeout_seconds=5.0,
        case_ids=(),
        versions=(),
        pair_ids=pair_ids,
        offline_only=False,
        lock_timeout_seconds=1.0,
        max_pre_action_retries=0,
    )


def _effective_for(options: campaign.CampaignOptions) -> dict[str, Any]:
    harness_excludes = ["__pycache__", ".pytest_cache", ".DS_Store", ".coverage"]
    interpreter = Path(campaign.sys.executable).resolve(strict=True)
    return {
        "contract": campaign.CAMPAIGN_EFFECTIVE_CONTRACT,
        "selection": {
            "profile": options.profile,
            "pair_ids": list(options.pair_ids),
            "required_units": {_C1.pair_id: ["single"]},
        },
        "candidate": {
            "path": str(options.skill_source),
            "tree_sha256": stable_tree_sha256(options.skill_source),
            "excluded_names": [],
        },
        "codex": {
            "path": str(options.codex_binary),
            "sha256": sha256_file(options.codex_binary),
            "runtime_files": campaign._codex_runtime_fingerprints(
                options.codex_binary
            ),
            **campaign._codex_shell_effective_config(),
            "memory": "disabled",
            "fresh_session_per_phase": True,
        },
        "suite": {
            "path": str(options.suite_path),
            "sha256": sha256_file(options.suite_path),
        },
        "live_config": {
            "path": str(options.live_config),
            "sha256": sha256_file(options.live_config),
        },
        "runtime": {
            "interpreter": str(interpreter),
            "interpreter_sha256": sha256_file(interpreter),
        },
        "harness": {
            "semantic_tree_sha256": stable_tree_sha256(
                campaign.REPO_ROOT / "tests" / "semantic",
                exclude_names=harness_excludes,
            ),
            "destructive_support_tree_sha256": stable_tree_sha256(
                campaign.REPO_ROOT / "tests" / "destructive" / "support",
                exclude_names=harness_excludes,
            ),
            "excluded_names": harness_excludes,
        },
    }


def _pass_validation(expected_sessions: Sequence[EvalSession]) -> ChildValidation:
    session = expected_sessions[0]
    return ChildValidation(
        observations=(
            {
                "unit_id": session.pair_id,
                "status": "PASS",
                "phases": [{"phase": session.phase, "status": "PASS"}],
            },
        ),
        phase_verdicts=(
            PhaseVerdict(
                session_id=session.session_id,
                phase=session.phase,
                status="PASS",
                reason="synthetic trusted PASS",
            ),
        ),
        executed_session_ids=(session.session_id,),
        pending_session_ids=(),
        retry_categories=(),
        summary={"synthetic": True},
    )


def _pre_session_readiness_retry_validation(
    expected_sessions: Sequence[EvalSession],
) -> ChildValidation:
    session = expected_sessions[0]
    verdict = PhaseVerdict(
        session_id=session.session_id,
        phase=session.phase,
        status="RETRYABLE",
        reason="synthetic runner-owned readiness failure before Codex",
        retry_category=LIVE_READINESS_RETRY_CATEGORY,
    )
    return ChildValidation(
        observations=(
            {
                "unit_id": session.pair_id,
                "status": "RETRYABLE",
                "phases": [{"phase": session.phase, "status": "RETRYABLE"}],
            },
        ),
        phase_verdicts=(verdict,),
        executed_session_ids=(),
        pending_session_ids=tuple(item.session_id for item in expected_sessions),
        retry_categories=(LIVE_READINESS_RETRY_CATEGORY,),
        summary={"synthetic": True},
    )


def _install_synthetic_execution(
    monkeypatch: pytest.MonkeyPatch,
    *,
    options: campaign.CampaignOptions,
) -> list[list[str]]:
    effective = _effective_for(options)
    child_calls: list[list[str]] = []

    monkeypatch.setattr(campaign, "WORKSPACE_ROOT", options.campaign_root.parent)
    monkeypatch.setattr(
        campaign,
        "require_skill_local_campaign_interpreter",
        lambda _skill_source: Path(campaign.sys.executable),
    )
    monkeypatch.setattr(
        campaign,
        "build_effective_config",
        lambda _options, *, sessions, required_units: effective,
    )

    def fake_child(argv: Sequence[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
        child_calls.append(list(argv))
        return subprocess.CompletedProcess(list(argv), 0, "synthetic stdout\n", "")

    monkeypatch.setattr(campaign, "run_child", fake_child)
    monkeypatch.setattr(
        campaign,
        "validate_child_run",
        lambda _root, *, expected_sessions, **_kwargs: _pass_validation(expected_sessions),
    )
    return child_calls


def test_campaign_lock_is_cross_platform_exclusive(tmp_path: Path) -> None:
    root = tmp_path / "campaign"
    root.mkdir()

    with campaign.CampaignLock(root, timeout_seconds=0.1) as holder:
        assert holder._descriptor is not None
        assert campaign.os.fstat(holder._descriptor).st_size >= 1
        owner = load_verified_json(root / campaign.LOCK_OWNER_FILE)
        assert owner["pid"] == campaign.os.getpid()
        assert owner["campaign_root"] == str(root.resolve(strict=True))
        with pytest.raises(campaign.CampaignConfigError, match="remained busy"):
            with campaign.CampaignLock(root, timeout_seconds=0.01):
                pytest.fail("a second campaign writer acquired the same lock")

    expected_unlocked_bytes = b"\0" if campaign.os.name == "nt" else b""
    assert (root / campaign.LOCK_FILE).read_bytes() == expected_unlocked_bytes


def test_campaign_child_process_owns_utf8_protocol_encoding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, Any] = {}

    def fake_run(argv: Sequence[str], **options: Any) -> subprocess.CompletedProcess[str]:
        observed["argv"] = list(argv)
        observed.update(options)
        return subprocess.CompletedProcess(list(argv), 0, "ok\n", "")

    monkeypatch.setenv("pythonioencoding", "cp936")
    monkeypatch.setenv("PYTHONIOENCODING", "cp1252")
    monkeypatch.setenv("WWISE_VERSION", "ambient-version")
    monkeypatch.setenv("WWISEROOT", "/ambient/legacy-root")
    monkeypatch.setenv("wwiseconsole", "/ambient/legacy-console")
    monkeypatch.setenv("WwiseSdk", "/ambient/sdk")
    monkeypatch.setenv("WAAPI_URL", "ws://ambient.invalid/waapi")
    monkeypatch.setenv("waapiurl", "ws://ambient-lower.invalid/waapi")
    monkeypatch.setenv("BASH_ENV", "/ambient/bash-env")
    monkeypatch.setattr(campaign.subprocess, "run", fake_run)

    completed = campaign.run_child(["python", "child.py"], cwd=tmp_path)

    assert completed.returncode == 0
    assert observed["encoding"] == "utf-8"
    assert observed["errors"] == "strict"
    environment = observed["env"]
    assert isinstance(environment, dict)
    matching_names = [
        name for name in environment if name.casefold() == "pythonioencoding"
    ]
    assert matching_names == ["PYTHONIOENCODING"]
    assert environment["PYTHONIOENCODING"] == "utf-8:strict"
    assert not any(
        campaign.is_evaluation_sensitive_environment_key(name)
        for name in environment
    )


def test_campaign_lock_fails_closed_without_supported_backend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(campaign, "_campaign_lock_platform_name", lambda: "unknown")

    with pytest.raises(campaign.CampaignConfigError, match="no supported backend"):
        with campaign.CampaignLock(tmp_path, timeout_seconds=0.01):
            pytest.fail("an unsupported host ran without a campaign lock")


def test_windows_campaign_lock_materializes_and_preserves_lock_region(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[int, int, int]] = []

    class FakeMsvcrt:
        LK_NBLCK = 1
        LK_UNLCK = 2

        @staticmethod
        def locking(descriptor: int, mode: int, _length: int) -> None:
            calls.append(
                (
                    mode,
                    campaign.os.lseek(descriptor, 0, campaign.os.SEEK_CUR),
                    campaign.os.fstat(descriptor).st_size,
                )
            )

    monkeypatch.setattr(campaign, "_campaign_lock_platform_name", lambda: "nt")
    monkeypatch.setattr(campaign, "_msvcrt", FakeMsvcrt)

    with campaign.CampaignLock(tmp_path, timeout_seconds=0.01):
        assert (tmp_path / campaign.LOCK_FILE).read_bytes().startswith(b"pid=")

    assert [(mode, offset) for mode, offset, _ in calls] == [
        (FakeMsvcrt.LK_NBLCK, 0),
        (FakeMsvcrt.LK_UNLCK, 0),
    ]
    assert all(size >= 1 for _, _, size in calls)
    assert (tmp_path / campaign.LOCK_FILE).read_bytes() == b"\0"


def test_campaign_lock_cleanup_does_not_mask_protected_exception(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingCleanupBackend:
        def try_acquire(self, _descriptor: int) -> bool:
            return True

        def clear_owner(self, _descriptor: int) -> None:
            raise RuntimeError("cleanup failed")

        def release(self, _descriptor: int) -> None:
            return None

    monkeypatch.setattr(
        campaign,
        "_campaign_lock_backend",
        lambda: FailingCleanupBackend(),
    )

    with pytest.raises(ValueError, match="protected failure"):
        with campaign.CampaignLock(tmp_path, timeout_seconds=0.01):
            raise ValueError("protected failure")


def test_live_readiness_category_auto_retries_exactly_once_per_invocation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    options = replace(_options(tmp_path), max_pre_action_retries=1)
    child_calls = _install_synthetic_execution(monkeypatch, options=options)
    monkeypatch.setattr(
        campaign,
        "validate_child_run",
        lambda _root, *, expected_sessions, **_kwargs: (
            _pre_session_readiness_retry_validation(expected_sessions)
        ),
    )

    assert campaign.run_campaign(options) == campaign.EXIT_PENDING
    assert len(child_calls) == 2
    assert len(list_campaign_attempts(options.campaign_root)) == 2


def test_candidate_frozen_hash_drift_is_detected(tmp_path: Path) -> None:
    options = _options(tmp_path)
    effective = _effective_for(options)
    campaign.assert_candidate_frozen(options.skill_source, effective=effective)

    (options.skill_source / "SKILL.md").write_text(
        "# changed during campaign\n",
        encoding="utf-8",
    )

    with pytest.raises(CampaignEvidenceError, match="candidate Skill drifted"):
        campaign.assert_candidate_frozen(options.skill_source, effective=effective)


def test_windows_shell_effective_config_seals_exact_profile_free_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fingerprint = {
        "path": r"C:\Program Files\PowerShell\7\pwsh.exe",
        "version": "7.6.4",
        "native_argument_passing": "Windows",
        "sha256": "a" * 64,
    }

    class SyntheticHost:
        def fingerprint_dict(self) -> dict[str, str]:
            return dict(fingerprint)

    monkeypatch.setattr(
        campaign,
        "discover_windows_powershell_core",
        lambda *, platform_name: SyntheticHost(),
    )

    assert campaign._windows_powershell_core_host_seal(
        platform_name="win32"
    ) == {"edition": "Core", **fingerprint}
    assert campaign._windows_powershell_core_host_seal(
        platform_name="posix"
    ) is None


def test_ordinary_effective_config_records_shell_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    options = _options(tmp_path)
    monkeypatch.setattr(
        campaign,
        "_codex_version_fingerprint",
        lambda _binary, *, windows_powershell_core_host=None: "codex-cli 1.2.3",
    )
    monkeypatch.setattr(campaign.importlib.metadata, "distributions", lambda: ())

    effective = campaign.build_effective_config(
        options,
        sessions=(_C1,),
        required_units={_C1.pair_id: (_C1.phase,)},
    )

    assert effective["live_config"]["readiness_timeout_seconds"] == 60.0
    assert effective["codex"]["allow_login_shell"] is False
    if os.name == "nt":
        assert effective["codex"]["windows_shell_backend"] == (
            campaign.WINDOWS_SHELL_BACKEND
        )
        assert set(effective["codex"]["windows_powershell_core_host"]) == {
            "edition",
            "path",
            "version",
            "native_argument_passing",
            "sha256",
        }
    else:
        assert effective["codex"]["windows_shell_backend"] is None
        assert effective["codex"]["windows_powershell_core_host"] is None


def test_windows_shell_frozen_reprobes_exact_sealed_executable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fingerprint = {
        "path": r"C:\Program Files\PowerShell\7\pwsh.exe",
        "version": "7.6.4",
        "native_argument_passing": "Windows",
        "sha256": "b" * 64,
    }
    probed: list[str] = []

    class SyntheticHost:
        def fingerprint_dict(self) -> dict[str, str]:
            return dict(fingerprint)

    def fake_probe(executable: str) -> SyntheticHost:
        probed.append(executable)
        return SyntheticHost()

    monkeypatch.setattr(campaign, "probe_windows_powershell_core", fake_probe)
    codex = {
        "windows_powershell_core_host": {"edition": "Core", **fingerprint},
        "windows_shell_backend": campaign.WINDOWS_SHELL_BACKEND,
        "allow_login_shell": False,
    }

    campaign._assert_codex_shell_frozen(codex, platform_name="nt")

    assert probed == [fingerprint["path"]]
    codex["windows_powershell_core_host"] = {
        "edition": "Core",
        **{**fingerprint, "sha256": "c" * 64},
    }
    with pytest.raises(CampaignEvidenceError, match="host drifted"):
        campaign._assert_codex_shell_frozen(codex, platform_name="nt")


def test_effective_input_freeze_revalidates_shell_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    options = _options(tmp_path)
    effective = _effective_for(options)
    observed: list[Mapping[str, Any]] = []
    monkeypatch.setattr(
        campaign,
        "_assert_codex_shell_frozen",
        lambda codex: observed.append(codex),
    )

    campaign.assert_effective_inputs_frozen(options, effective=effective)

    assert observed == [effective["codex"]]


def test_candidate_drift_during_child_is_sealed_as_blocked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    options = _options(tmp_path)
    effective = _effective_for(options)
    monkeypatch.setattr(campaign, "WORKSPACE_ROOT", options.campaign_root.parent)
    monkeypatch.setattr(
        campaign,
        "require_skill_local_campaign_interpreter",
        lambda _skill_source: Path(campaign.sys.executable),
    )
    monkeypatch.setattr(
        campaign,
        "build_effective_config",
        lambda _options, *, sessions, required_units: effective,
    )

    def mutate_candidate(
        argv: Sequence[str], *, cwd: Path
    ) -> subprocess.CompletedProcess[str]:
        (options.skill_source / "SKILL.md").write_text(
            "# drifted inside synthetic child boundary\n",
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(list(argv), 0, "", "")

    monkeypatch.setattr(campaign, "run_child", mutate_candidate)
    monkeypatch.setattr(
        campaign,
        "validate_child_run",
        lambda *_args, **_kwargs: pytest.fail(
            "drift must block before child evidence is accepted"
        ),
    )

    assert campaign.run_campaign(options) == campaign.EXIT_BLOCKED
    attempts = list_campaign_attempts(options.campaign_root)
    assert len(attempts) == 1
    assert (attempts[0] / ATTEMPT_MANIFEST_FILE).is_file()
    assert (attempts[0] / "candidate-drift-before-seal.json").is_file()


def test_invalid_pair_exits_two_before_creating_campaign_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    options = _options(
        tmp_path,
        pair_ids=("screening:not-a-real-case:2022.1:r1",),
    )
    monkeypatch.setattr(campaign, "WORKSPACE_ROOT", options.campaign_root.parent)
    monkeypatch.setattr(campaign, "parse_args", lambda _argv: options)
    monkeypatch.setattr(
        campaign,
        "build_effective_config",
        lambda *_args, **_kwargs: pytest.fail(
            "invalid selection must fail before campaign fingerprinting"
        ),
    )

    assert campaign.main([]) == campaign.EXIT_CONFIG
    assert not options.campaign_root.exists()


def test_build_child_argv_never_requests_overwrite(tmp_path: Path) -> None:
    options = replace(
        _options(tmp_path),
        wwise_readiness_timeout_seconds=180.0,
    )
    group = campaign.ChildGroup(
        group_id="offline",
        version=None,
        pair_ids=(_C1.pair_id,),
        sessions=(_C1,),
    )

    argv = campaign.build_child_argv(
        options,
        group=group,
        matrix_root=tmp_path / "matrix",
    )

    assert "--overwrite" not in argv
    assert argv.count("--pair-id") == 1
    assert argv[argv.index("--pair-id") + 1] == _C1.pair_id
    assert argv[argv.index("--wwise-readiness-timeout") + 1] == "180.0"


def test_windows_shell_seal_round_trips_into_matrix_child_argv(
    tmp_path: Path,
) -> None:
    options = _options(tmp_path)
    group = campaign.ChildGroup(
        group_id="offline",
        version=None,
        pair_ids=(_C1.pair_id,),
        sessions=(_C1,),
    )
    host = campaign.WindowsPowerShellCoreHost(
        executable=r"C:\Program Files\PowerShell\7\pwsh.exe",
        version="7.6.4",
        native_argument_passing="Windows",
        sha256="d" * 64,
    )

    argv = campaign.build_child_argv(
        options,
        group=group,
        matrix_root=tmp_path / "matrix",
        windows_powershell_core_host=host,
    )

    seal_index = argv.index("--sealed-windows-powershell-core-host-json")
    parsed = matrix._parse_sealed_windows_powershell_core_host(
        argv[seal_index + 1],
        platform_name="nt",
    )
    assert parsed == host


def test_sealed_pass_resumes_verify_only_without_starting_another_child(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    options = _options(tmp_path)
    child_calls = _install_synthetic_execution(monkeypatch, options=options)

    assert campaign.run_campaign(options) == campaign.EXIT_PASS
    assert len(child_calls) == 1
    attempts = list_campaign_attempts(options.campaign_root)
    assert len(attempts) == 1
    assert (attempts[0] / ATTEMPT_MANIFEST_FILE).is_file()

    monkeypatch.setattr(
        campaign,
        "_require_standard_windows_path_budget",
        lambda *_args, **_kwargs: pytest.fail(
            "verify-only must not apply a process-cwd launch budget"
        ),
    )
    resume = replace(options, resume=True, verify_only=True)
    assert campaign.run_campaign(resume) == campaign.EXIT_PASS
    assert len(child_calls) == 1


def test_resume_with_unsealed_attempt_exits_blocked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    options = _options(tmp_path)
    child_calls = _install_synthetic_execution(monkeypatch, options=options)
    assert campaign.run_campaign(options) == campaign.EXIT_PASS
    assert len(child_calls) == 1

    _attempt_id, unsealed = create_attempt(options.campaign_root)
    assert not (unsealed / ATTEMPT_MANIFEST_FILE).exists()
    resume = replace(options, resume=True, verify_only=True)
    monkeypatch.setattr(campaign, "parse_args", lambda _argv: resume)

    assert campaign.main([]) == campaign.EXIT_BLOCKED
    assert len(child_calls) == 1
