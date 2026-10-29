from __future__ import annotations

import os
import subprocess
import sys
import time
import tomllib
from importlib import metadata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = REPO_ROOT / "skills" / "waapi-skill"
# The standalone launcher also uses the existing developer-only test helpers.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SKILL_DIR) not in sys.path:
    sys.path.insert(0, str(SKILL_DIR))

if __package__:
    from .test_readiness import report_readiness, ReadinessBlocked, validate_nonlive_readiness, pytest_token_roles
    from .resolve_live_test_config import LiveTestConfigError
    from .run_live_test_command import main as run_live_test_command
else:  # Executed directly by ci/test.sh or ci/test.bat.
    from test_readiness import report_readiness, ReadinessBlocked, validate_nonlive_readiness, pytest_token_roles
    from resolve_live_test_config import LiveTestConfigError
    from run_live_test_command import main as run_live_test_command


SUPPORTED_VERSIONS = ("2021.1", "2022.1", "2023.1", "2024.1", "2025.1")
SUPPORTED_VERSION_ARGUMENTS = frozenset((*SUPPORTED_VERSIONS, "all", "none"))
SUPPORTED_MODES = frozenset(
    {
        "program",
        "nonlive",
        "notice-fast",
        "default",
        "all",
        "smoke",
        "live",
        "destructive",
        "matrix",
        "focused",
    }
)
DEFAULT_VERSION_BY_MODE = {
    "program": "none",
    "nonlive": "none",
    "notice-fast": "none",
    "default": "none",
    "all": "all",
    "matrix": "all",
    "focused": "all",
}
WWISE_BUILDS = {
    "2021.1": "2021.1.14.8108",
    "2022.1": "2022.1.19.8584",
    "2023.1": "2023.1.19.8928",
    "2024.1": "2024.1.13.9056",
    "2025.1": "2025.1.7.9143",
}

LIVE_TEST_NODES = {
    "2021.1": (
        "tests/live/test_2021_1_live_prerequisites.py::test_2021_1_live_read_only_prerequisites_validate_exact_get_info_before_matrix",
        "tests/live/test_2021_1_reflection_prerequisites.py::test_2021_1_live_reflection_prerequisites_and_resource_generation",
        "tests/live/test_2021_1_object_get_matrix.py::test_2021_1_live_waql_object_get_matrix_runs_read_only_against_sandbox",
        "tests/live/test_2021_1_object_topics_sandbox.py::test_2021_1_live_safe_object_topics_against_sandbox",
        "tests/live/test_gateway_live_matrix.py::test_gateway_read_only_matrix_runs_once_against_copied_sandbox",
    ),
    "2022.1": (
        "tests/live/test_2022_live_prerequisites.py::test_2022_live_environment_prerequisites_fail_fast",
        "tests/live/test_2022_reflection_inventory.py::test_2022_live_reflection_inventory_runs_against_sandbox",
        "tests/live/test_2022_waql_live_matrix.py::test_2022_live_waql_object_get_matrix_runs_read_only_against_sandbox",
        "tests/live/test_2022_1_topic_business_sandbox.py::test_2022_1_topic_business_inputs_against_sandbox",
        "tests/live/test_gateway_live_matrix.py::test_gateway_read_only_matrix_runs_once_against_copied_sandbox",
    ),
    "2023.1": (
        "tests/live/test_2023_reflection_inventory.py::test_2023_live_reflection_inventory_runs_against_sandbox",
        "tests/live/test_2023_waql_live_matrix.py::test_2023_live_waql_object_get_matrix_runs_read_only_against_sandbox",
        "tests/live/test_gateway_live_matrix.py::test_gateway_read_only_matrix_runs_once_against_copied_sandbox",
    ),
    "2024.1": (
        "tests/live/test_2024_reflection_inventory.py::test_2024_live_reflection_inventory_runs_against_sandbox",
        "tests/live/test_2024_waql_live_matrix.py::test_2024_live_waql_object_get_matrix_runs_read_only_against_sandbox",
        "tests/live/test_2024_object_topics_sandbox.py::test_2024_1_live_safe_object_topics_against_sandbox",
        "tests/live/test_gateway_live_matrix.py::test_gateway_read_only_matrix_runs_once_against_copied_sandbox",
    ),
    "2025.1": (
        "tests/live/test_2025_1_reflection_inventory.py::test_2025_live_reflection_inventory_runs_against_sandbox",
        "tests/live/test_2025_1_waql_live_matrix.py::test_2025_live_waql_object_get_matrix_runs_read_only_against_sandbox",
        "tests/live/test_2025_1_object_topics_sandbox.py::test_2025_1_live_safe_object_topics_against_sandbox",
        "tests/live/test_gateway_live_matrix.py::test_gateway_read_only_matrix_runs_once_against_copied_sandbox",
    ),
}

_DESTRUCTIVE_FILE_VERSION = {
    "2021.1": "2021_1",
    "2022.1": "2022",
    "2023.1": "2023",
    "2024.1": "2024",
    "2025.1": "2025_1",
}
DESTRUCTIVE_TEST_NODES = {
    version: (
        f"tests/destructive/test_{file_version}_project_mutation_sandbox.py",
        f"tests/destructive/test_{file_version}_soundbank_audio_sandbox.py",
        f"tests/destructive/test_{file_version}_switchcontainer_assignment_sandbox.py",
        "tests/destructive/test_gateway_transaction_matrix.py",
        "tests/destructive/test_gateway_workflow_transaction_matrix.py",
    )
    for version, file_version in _DESTRUCTIVE_FILE_VERSION.items()
}


class TestDriverError(ValueError):
    """Raised when the public test-launcher request is invalid."""


class TestEnvironmentError(ValueError):
    """Raised before collection when the selected developer Python is incomplete."""


@dataclass(frozen=True)
class TestRequest:
    version: str
    mode: str
    pytest_args: tuple[str, ...]
    batch_plan: Path | None = None


@dataclass(frozen=True)
class LiveDefaults:
    config: Path
    console: Path
    project: Path
    sandbox: Path


def usage(*, windows: bool | None = None) -> str:
    on_windows = os.name == "nt" if windows is None else windows
    launcher = r"ci\test.bat" if on_windows else "ci/test.sh"
    default_note = (
        "  - Default Windows Console paths use "
        r"C:\Audiokinetic\Wwise<build>\Authoring\x64\Release\bin\WwiseConsole.exe."
        if on_windows
        else "  - Default macOS paths use the version-matched Audiokinetic installation."
    )
    return f"""Usage:
  {launcher} --version <version> --mode <mode> [-- <extra pytest args...>]
  {launcher} --batch-plan /absolute/path/to/plan.json
  {launcher} -v <version> -m <mode> [-- <extra pytest args...>]
  {launcher} <version> <mode> [-- <extra pytest args...>]  # backwards compatible

Versions:
  2021.1 | 2022.1 | 2023.1 | 2024.1 | 2025.1 | all | none

Modes:
  program      Run the focused pure-program public-route and transaction contract gate
  notice-fast  Run fixed notice/fake runner/archive development regressions
  nonlive      Run default non-live test suite
  all          Run non-live suite first, then strict real matrix
  smoke        Run focused WAAPI getInfo smoke via HeadlessLifecycle
  live         Run focused live suite for the selected version
  destructive  Run focused destructive suite for the selected version
  matrix       Run focused live + destructive sequentially (all five versions)
  focused      Alias for matrix

Notes:
  - Opt-in test-batch/v1 plans select finite groups, sources and dependencies.
    See ci/test_batch.py; an existing evidence root is never reused.
  - Environment overrides are respected if already set:
      WWISE_TEST_CONFIG, WWISE_CONSOLE, WWISE_SAMPLE_PROJECT_PATH,
      WWISE_SANDBOX_ROOT, WWISE_STARTUP_TIMEOUT, WWISE_READINESS_TIMEOUT,
      WWISE_PROBE_TIMEOUT, WWISE_SHUTDOWN_TIMEOUT
      WAAPI_TEST_PYTHON (exact pre-provisioned developer Python)
{default_note}
  - Live/destructive explicit pytest paths or nodes replace the version defaults.
    Flags alone (including -k/-m filters) apply to the version default selection.
  - Default sandbox root if not set:
      .waapi-skill-state/runtime/wwise-waapi-sandboxes/<version>-<mode>

Examples:
  {launcher} --mode program
  {launcher} --mode program -- -q -ra
  {launcher} --version 2021.1 --mode live
  {launcher} --mode nonlive
  {launcher} --version all --mode all -- -q -ra
  {launcher} -v all -m matrix
  {launcher} --version 2024.1 --mode live -- -k object_topics -q
  {launcher} --version 2025.1 --mode live -- tests/live/test_gateway_live_matrix.py -q
  {launcher} 2021.1 live
  {launcher} 2025.1 destructive
  {launcher} all matrix
  {launcher} all smoke
  {launcher} none nonlive
  {launcher} 2022.1 smoke -- -q
"""


def _owned_authoring_requested(pytest_args: Sequence[str]) -> bool:
    return any(value == '--owned-authoring-batch-root' or value.startswith('--owned-authoring-batch-root=')
               for value in pytest_args)


_SCALAR_PROGRAM_ENV = ("WAAPI_SCALAR_PROGRAM_BATCH_ROOT", "WAAPI_SCALAR_PROGRAM_SELECTION")


def _standalone_scalar_program_requested(arguments: Sequence[str], repo_root: Path) -> bool:
    """Preserve evidence inputs only for the one explicit standalone pytest file."""
    expected = (repo_root / "tests/unit/test_scalar_condition_product_gateway.py").resolve()
    targets = []
    index = 0
    while index < len(arguments):
        value = arguments[index]
        if value in {"-k", "-m", "--basetemp", "--maxfail", "--tb", "--capture"}:
            if index + 1 >= len(arguments):
                return False
            index += 2
            continue
        if value in {"-q", "--quiet", "-v", "--verbose", "-ra", "-rA", "-s", "-x", "--exitfirst",
                     "--disable-warnings", "--collect-only"} or value.startswith(("--basetemp=", "--maxfail=", "--tb=", "--capture=")):
            index += 1
            continue
        if value.startswith("-"):
            return False
        path, separator, node = value.partition("::")
        selected = Path(path)
        if not selected.is_absolute():
            selected = repo_root / selected
        if selected.resolve() != expected or (separator and node not in {
                "test_product_self_scalar_source_conditions",
                *("test_product_self_scalar_source_conditions[" + version + "]" for version in SUPPORTED_VERSIONS)}):
            return False
        targets.append(value)
        index += 1
    return len(targets) == 1


def parse_request(arguments: Sequence[str]) -> TestRequest | None:
    if arguments and arguments[0] == '--batch-plan':
        if len(arguments) != 2:
            raise TestDriverError('--batch-plan requires exactly one plan path')
        return TestRequest('none', 'batch', (), Path(arguments[1]))
    version = ""
    mode = ""
    positional: list[str] = []
    pytest_args: tuple[str, ...] = ()
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument in {"-h", "--help"}:
            return None
        if argument in {"-v", "--version", "-m", "--mode"}:
            if index + 1 >= len(arguments):
                raise TestDriverError(f"Missing value for {argument}")
            value = arguments[index + 1]
            if argument in {"-v", "--version"}:
                version = value
            else:
                mode = value
            index += 2
            continue
        if argument == "--":
            pytest_args = tuple(arguments[index + 1 :])
            break
        if argument.startswith("-"):
            raise TestDriverError(f"Unknown option: {argument}")
        positional.append(argument)
        index += 1

    if len(positional) > 2:
        raise TestDriverError(f"Unsupported positional argument: {positional[2]}")
    if not version and positional:
        version = positional[0]
    if not mode and len(positional) == 2:
        mode = positional[1]
    if not mode:
        raise TestDriverError("Mode is required (use --mode or positional form).")
    if mode not in SUPPORTED_MODES:
        raise TestDriverError(f"Unsupported mode: {mode}")
    if not version:
        version = DEFAULT_VERSION_BY_MODE.get(mode, "")
    if not version:
        raise TestDriverError(
            f"Version is required for mode '{mode}' (use --version or positional form)."
        )
    if version not in SUPPORTED_VERSION_ARGUMENTS:
        raise TestDriverError(f"Unsupported version: {version}")
    if mode == "notice-fast" and version != "none":
        raise TestDriverError("notice-fast mode is non-live and requires version 'none'")
    if mode == "program" and version != "none":
        raise TestDriverError("program mode is all-version and requires version 'none'")
    if mode == "all" and version != "all":
        raise TestDriverError("all mode requires version 'all'")
    if mode in {"matrix", "focused"} and version != "all":
        raise TestDriverError("matrix/focused mode requires version 'all'")
    if mode in {"smoke", "live", "destructive"} and version == "none":
        raise TestDriverError(f"mode '{mode}' requires a real Wwise version or 'all'")
    if _owned_authoring_requested(pytest_args) and (mode != 'destructive' or version not in SUPPORTED_VERSIONS):
        raise TestDriverError('owned Authoring requires one exact supported destructive lane')
    return TestRequest(version=version, mode=mode, pytest_args=pytest_args)


def validate_test_environment(
    *,
    repo_root: Path = REPO_ROOT,
    python_version: tuple[int, int] | None = None,
    distribution_version: Callable[[str], str] = metadata.version,
) -> None:
    """Fail before test context or Wwise startup on an incomplete dev runtime."""

    selected_version = (
        (sys.version_info.major, sys.version_info.minor)
        if python_version is None
        else python_version
    )
    if not (3, 11) <= selected_version < (3, 14):
        raise TestEnvironmentError(
            "the selected interpreter must be Python 3.11 through 3.13; "
            f"observed {selected_version[0]}.{selected_version[1]}"
        )
    try:
        with (repo_root / "pyproject.toml").open("rb") as handle:
            project = tomllib.load(handle)
        locked = {
            "waapi-client": project["tool"]["poetry"]["dependencies"]["waapi-client"],
            "pytest": project["tool"]["poetry"]["group"]["dev"]["dependencies"]["pytest"],
        }
    except (KeyError, OSError, tomllib.TOMLDecodeError) as exc:
        raise TestEnvironmentError(
            "pyproject.toml does not expose the locked test runtime"
        ) from exc
    for distribution, constraint in locked.items():
        if not isinstance(constraint, str) or not constraint.startswith("=="):
            raise TestEnvironmentError(
                f"{distribution} must use one exact pyproject version"
            )
        expected = constraint.removeprefix("==")
        try:
            observed = distribution_version(distribution)
        except Exception as exc:  # noqa: BLE001 - metadata providers vary by host
            raise TestEnvironmentError(
                f"{distribution} is unavailable in {sys.executable}"
            ) from exc
        if observed != expected:
            raise TestEnvironmentError(
                f"{distribution} version {observed} does not match locked {expected}"
            )


def default_live_paths(
    version: str,
    mode: str,
    *,
    repo_root: Path = REPO_ROOT,
    windows: bool | None = None,
) -> LiveDefaults:
    if version not in WWISE_BUILDS:
        raise TestDriverError(f"Unsupported version: {version}")
    on_windows = os.name == "nt" if windows is None else windows
    build = WWISE_BUILDS[version]
    if on_windows:
        console = Path(
            rf"C:\Audiokinetic\Wwise{build}\Authoring\x64\Release\bin\WwiseConsole.exe"
        )
        project = repo_root / "tests" / "_org" / version / "SampleProject.wproj"
    else:
        console = Path(
            f"/Applications/Audiokinetic/Wwise{build}/Wwise.app/Contents/Tools/WwiseConsole.sh"
        )
        if version == "2022.1":
            project = repo_root / "tests" / "_org" / version / "SampleProject.wproj"
        else:
            project = Path(
                f"/Applications/Audiokinetic/SampleProject{build}/SampleProject/SampleProject.wproj"
            )
    return LiveDefaults(
        config=repo_root / "tests" / "fixtures" / "local" / "live-environment.json",
        console=console,
        project=project,
        sandbox=(
            repo_root
            / ".waapi-skill-state"
            / "runtime"
            / "wwise-waapi-sandboxes"
            / f"{version}-{mode}"
        ),
    )


def build_base_environment(
    environment: Mapping[str, str], *, repo_root: Path = REPO_ROOT
) -> dict[str, str]:
    result = dict(environment)
    skill_dir = str(repo_root / "skills" / "waapi-skill")
    inherited = result.get("PYTHONPATH")
    result["PYTHONPATH"] = (
        f"{skill_dir}{os.pathsep}{inherited}" if inherited else skill_dir
    )
    return result


class TestDriver:
    def __init__(
        self,
        *,
        repo_root: Path = REPO_ROOT,
        environment: Mapping[str, str] | None = None,
        python_executable: str | None = None,
        command_runner: Callable[..., subprocess.CompletedProcess[Any]] | None = None,
        windows: bool | None = None,
    ) -> None:
        self.repo_root = repo_root.expanduser().resolve(strict=False)
        self.environment = build_base_environment(
            os.environ if environment is None else environment,
            repo_root=self.repo_root,
        )
        self.python_executable = sys.executable if python_executable is None else python_executable
        self.command_runner = subprocess.run if command_runner is None else command_runner
        self.windows = os.name == "nt" if windows is None else windows

    def run(self, request: TestRequest) -> int:
        if request.batch_plan is not None:
            if __package__:
                from .test_batch import run_batch
            else:
                from test_batch import run_batch
            return run_batch(self, request.batch_plan)
        if request.mode == "notice-fast":
            return self._run_notice_fast(request.pytest_args)
        if request.mode == "program":
            return self._run_program(request.pytest_args)
        if request.mode in {"nonlive", "default"}:
            return self._run_nonlive(request.pytest_args, allow_scalar_program=True)
        if request.mode == "all":
            result = self._run_nonlive(request.pytest_args)
            if result != 0:
                return result
            return self._run_matrix(request.pytest_args)
        if request.mode in {"matrix", "focused"}:
            return self._run_matrix(request.pytest_args)
        versions = SUPPORTED_VERSIONS if request.version == "all" else (request.version,)
        for version in versions:
            result = self._run_real(version, request.mode, request.pytest_args)
            if result != 0:
                return result
        return 0

    def _run_child(self, command: Sequence[str], environment: Mapping[str, str]) -> int:
        try:
            completed = self.command_runner(
                tuple(command),
                cwd=self.repo_root,
                env=dict(environment),
                shell=False,
                check=False,
            )
        except OSError as exc:
            print(f"test command failed to start: {exc}", file=sys.stderr)
            return 2
        return int(completed.returncode)

    def _nonlive_environment(self) -> dict[str, str]:
        environment = dict(self.environment)
        environment.update(
            {
                "WWISE_LIVE": "0",
                "WWISE_DESTRUCTIVE": "0",
                "WWISE_STRICT_REAL": "0",
                "PYTHONUTF8": "1",
            }
        )
        for name in _SCALAR_PROGRAM_ENV:
            environment.pop(name, None)
        return environment

    def _print_context(
        self,
        *,
        environment: Mapping[str, str],
        version: str,
        mode: str,
        pytest_args: Sequence[str],
    ) -> None:
        print("== Test Context ==")
        print(f"version:      {version}")
        print(f"mode:         {mode}")
        print(f"console:      {environment.get('WWISE_CONSOLE', '<unset>')}")
        print(f"project:      {environment.get('WWISE_SAMPLE_PROJECT_PATH', '<unset>')}")
        print(f"sandbox_root: {environment.get('WWISE_SANDBOX_ROOT', '<unset>')}")
        print(f"test_config:  {environment.get('WWISE_TEST_CONFIG', '<unset>')}")
        print(f"pytest args:  {' '.join(pytest_args) if pytest_args else '<none>'}")
        print(flush=True)

    def _run_nonlive(self, pytest_args: Sequence[str], *, allow_scalar_program: bool = False) -> int:
        started = time.perf_counter()
        try:
            validate_nonlive_readiness(self.repo_root, tuple(pytest_args))
        except (ReadinessBlocked, ValueError, OSError) as exc:
            report_readiness(started, reason=str(exc), blocked=True)
            print(f"TEST_READINESS_BLOCKED: {exc}", file=sys.stderr)
            return 1
        report_readiness(started, reason="selected Non-live prerequisites ready")
        environment = self._nonlive_environment()
        if allow_scalar_program and _standalone_scalar_program_requested(pytest_args, self.repo_root):
            environment.update({name: self.environment[name] for name in _SCALAR_PROGRAM_ENV if name in self.environment})
        self._print_context(
            environment=environment,
            version="none",
            mode="nonlive",
            pytest_args=pytest_args,
        )
        return self._run_child(
            (
                self.python_executable,
                "-m",
                "pytest",
                "-m",
                "not live and not destructive",
                *pytest_args,
            ),
            environment,
        )

    def _run_notice_fast(self, pytest_args: Sequence[str]) -> int:
        environment = self._nonlive_environment()
        for name in (
            "WWISE_VERSION", "WWISE_CONSOLE", "WWISE_SAMPLE_PROJECT_PATH",
            "WWISE_SANDBOX_ROOT", "WWISE_TEST_CONFIG", "WWISE_WAAPI_HOST",
            "WWISE_WAAPI_PORT", "PYTEST_ADDOPTS", "PYTEST_PLUGINS",
        ):
            environment.pop(name, None)
        self._print_context(
            environment=environment, version="none", mode="notice-fast",
            pytest_args=pytest_args,
        )
        return self._run_child(
            (self.python_executable,
             str(self.repo_root / "ci" / "run_notice_fast_tests.py"), *pytest_args),
            environment,
        )

    def _run_program(self, pytest_args: Sequence[str]) -> int:
        environment = self._nonlive_environment()
        for name in (
            "WWISE_VERSION",
            "WWISE_CONSOLE",
            "WWISE_SAMPLE_PROJECT_PATH",
            "WWISE_SANDBOX_ROOT",
            "WWISE_TEST_CONFIG",
            "WWISE_WAAPI_HOST",
            "WWISE_WAAPI_PORT",
            "PYTEST_ADDOPTS",
            "PYTEST_PLUGINS",
        ):
            environment.pop(name, None)
        self._print_context(
            environment=environment,
            version="none",
            mode="program",
            pytest_args=pytest_args,
        )
        return self._run_child(
            (
                self.python_executable,
                str(self.repo_root / "ci" / "run_program_tests.py"),
                str(self.repo_root / "ci" / "program-test-nodes.txt"),
                *pytest_args,
            ),
            environment,
        )

    def _run_real(
        self, version: str, mode: str, pytest_args: Sequence[str]
    ) -> int:
        owned_authoring = _owned_authoring_requested(pytest_args)
        if owned_authoring and (mode != 'destructive' or version not in SUPPORTED_VERSIONS or self.windows):
            raise TestDriverError('owned Authoring currently requires one exact Mac supported destructive lane')
        defaults = default_live_paths(
            version,
            mode,
            repo_root=self.repo_root,
            windows=self.windows,
        )
        selectors, _ = pytest_token_roles(tuple(pytest_args))
        if mode == "smoke":
            child = (str(self.repo_root / "ci" / "wwise_smoke.py"),)
        elif mode == "live":
            child = ("-m", "pytest", *(() if selectors else LIVE_TEST_NODES[version]), *pytest_args)
        elif mode == "destructive":
            child = ("-m", "pytest", *(() if owned_authoring or selectors else DESTRUCTIVE_TEST_NODES[version]), *pytest_args)
        else:
            raise TestDriverError(f"Unsupported real-test mode: {mode}")
        # The live helper treats this fixed prefix only as an argv schema and
        # replaces it with this already-active absolute interpreter. No Poetry
        # or shell child is started.
        helper_argv = (
            "--version",
            version,
            "--mode",
            mode,
            "--repo-root",
            str(self.repo_root),
            "--default-config",
            str(defaults.config),
            "--default-console",
            str(defaults.console),
            "--default-project",
            str(defaults.project),
            "--default-sandbox",
            str(defaults.sandbox),
            "--",
            "poetry",
            "run",
            "python",
            *child,
        )
        return run_live_test_command(
            helper_argv,
            command_runner=self.command_runner,
            python_executable=self.python_executable,
            environment={**self.environment, **({'WWISE_AUTHORING_LIVE': '1'} if owned_authoring else {})},
        )

    def _run_matrix(self, pytest_args: Sequence[str]) -> int:
        for version in SUPPORTED_VERSIONS:
            for mode in ("live", "destructive"):
                result = self._run_real(version, mode, pytest_args)
                if result != 0:
                    return result
        return 0


def main(
    argv: Sequence[str] | None = None,
    *,
    environment: Mapping[str, str] | None = None,
    python_executable: str | None = None,
    command_runner: Callable[..., subprocess.CompletedProcess[Any]] | None = None,
    repo_root: Path = REPO_ROOT,
    windows: bool | None = None,
) -> int:
    arguments = tuple(sys.argv[1:] if argv is None else argv)
    try:
        request = parse_request(arguments)
        if request is not None and request.mode in {"matrix", "focused", "all"}:
            selectors, _ = pytest_token_roles(request.pytest_args)
            unit_root = (repo_root / "tests" / "unit").resolve(strict=False)
            for selector in selectors:
                path = Path(selector.split("::", 1)[0]).expanduser()
                selected_path = path if path.is_absolute() else repo_root / path
                if selected_path.resolve(strict=False).is_relative_to(unit_root):
                    raise TestDriverError(
                        "Unit selectors cannot run in matrix/focused/all mode; "
                        "use --mode nonlive -- with the same pytest selection."
                    )
    except TestDriverError as exc:
        print(str(exc), file=sys.stderr)
        print(usage(windows=windows), file=sys.stderr, end="")
        return 1
    if request is None:
        print(usage(windows=windows), end="")
        return 0
    started = time.perf_counter()
    try:
        validate_test_environment(repo_root=repo_root)
    except TestEnvironmentError as exc:
        report_readiness(started, reason=str(exc), blocked=True)
        print(f"TEST_ENVIRONMENT_BLOCKED: {exc}", file=sys.stderr)
        print(
            "Select a complete interpreter with WAAPI_TEST_PYTHON or provision "
            "this worktree with Poetry before retrying.",
            file=sys.stderr,
        )
        return 4
    report_readiness(started, reason="locked developer interpreter ready")
    try:
        return TestDriver(
            repo_root=repo_root,
            environment=environment,
            python_executable=python_executable,
            command_runner=command_runner,
            windows=windows,
        ).run(request)
    except (LiveTestConfigError, TestDriverError, OSError) as exc:
        print(f"test driver error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
