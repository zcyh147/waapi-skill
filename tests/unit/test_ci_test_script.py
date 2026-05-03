from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
CI_TEST = REPO_ROOT / "ci" / "test.sh"


def _write_fake_python(bin_dir: Path, fail_on_nonlive: bool = False) -> Path:
    script = bin_dir / "python"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "from __future__ import annotations\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        f"log_path = Path(os.environ['CI_TEST_LOG'])\n"
        "argv = sys.argv[1:]\n"
        "with log_path.open('a', encoding='utf-8') as handle:\n"
        "    handle.write(json.dumps(argv) + '\\n')\n"
        f"if {str(fail_on_nonlive)} and argv[:3] == ['-m', 'pytest', '-m'] and 'not live and not destructive' in argv:\n"
        "    sys.exit(7)\n"
        "sys.exit(0)\n"
    )
    script.chmod(0o755)
    return script


def _run_ci_test(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(CI_TEST), *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_ci_test_help_mentions_all_mode() -> None:
    result = _run_ci_test(os.environ.copy(), "--help")

    assert result.returncode == 0
    assert "all          Run non-live suite first, then strict real matrix" in result.stdout
    assert "ci/test.sh --version all --mode all -- -q -ra" in result.stdout


def test_ci_test_all_runs_nonlive_before_matrix(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "python.log"
    _write_fake_python(bin_dir)

    console_path = tmp_path / "WwiseConsole.sh"
    console_path.write_text("#!/usr/bin/env bash\nexit 0\n")
    console_path.chmod(0o755)

    project_path = tmp_path / "SampleProject.wproj"
    project_path.write_text("<Project />\n")

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env.get('PATH', '')}",
            "CI_TEST_LOG": str(log_path),
            "WWISE_CONSOLE": str(console_path),
            "WWISE_SAMPLE_PROJECT_PATH": str(project_path),
            "WWISE_SANDBOX_ROOT": str(tmp_path / "sandbox"),
        }
    )

    result = _run_ci_test(env, "--version", "all", "--mode", "all", "--", "-q", "-ra")

    assert result.returncode == 0, result.stderr
    calls = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert len(calls) >= 2
    assert calls[0] == ["-m", "pytest", "-m", "not live and not destructive", "-q", "-ra"]
    assert calls[1][0:4] == ["-m", "pytest", "tests/live/test_2021_1_live_prerequisites.py::test_2021_1_live_read_only_prerequisites_validate_exact_get_info_before_matrix", "tests/live/test_2021_1_reflection_prerequisites.py::test_2021_1_live_reflection_prerequisites_and_resource_generation"]


def test_ci_test_all_stops_when_nonlive_fails(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log_path = tmp_path / "python.log"
    _write_fake_python(bin_dir, fail_on_nonlive=True)

    console_path = tmp_path / "WwiseConsole.sh"
    console_path.write_text("#!/usr/bin/env bash\nexit 0\n")
    console_path.chmod(0o755)

    project_path = tmp_path / "SampleProject.wproj"
    project_path.write_text("<Project />\n")

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env.get('PATH', '')}",
            "CI_TEST_LOG": str(log_path),
            "WWISE_CONSOLE": str(console_path),
            "WWISE_SAMPLE_PROJECT_PATH": str(project_path),
            "WWISE_SANDBOX_ROOT": str(tmp_path / "sandbox"),
        }
    )

    result = _run_ci_test(env, "--version", "all", "--mode", "all", "--", "-q", "-ra")

    assert result.returncode != 0
    calls = log_path.read_text(encoding="utf-8").splitlines()
    assert len(calls) == 1
