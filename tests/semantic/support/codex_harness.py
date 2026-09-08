"""Isolated Codex CLI harness for WAAPI skill semantic evaluations."""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import re
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from contextlib import ExitStack, contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Callable, Iterator, Mapping, Sequence

from wwise_waapi.platform_commands import (
    GATEWAY_SHELL_TOOL_TIMEOUT_MS,
    PlatformCommandError,
    WINDOWS_MODEL_COMMAND_FAMILY,
    WINDOWS_POWERSHELL_ENCODED_FAMILY,
    decode_windows_model_argv,
    decode_windows_powershell_argv,
    encode_windows_model_argv,
)
from tests.semantic.support.codex_gateway_contracts import (
    GATEWAY_RESULT_CONTRACT,
    TASK_LOCAL_RUNNER_POSIX,
    TASK_LOCAL_RUNNER_WINDOWS,
    gateway_payload_contracts,
    task_local_runner_matches_normalized,
)
from tests.semantic.support.codex_draft_commands import DRAFT_GATEWAY_SUBCOMMANDS


MACOS_APP_CODEX_FALLBACK = Path("/Applications/ChatGPT.app/Contents/Resources/codex")
DEFAULT_AUTH_JSON = Path.home() / ".codex" / "auth.json"
DEFAULT_MODEL = "gpt-5.6-sol"
DEFAULT_REASONING_EFFORT = "medium"
DEFAULT_SERVICE_TIER = "priority"
DEFAULT_TIMEOUT_SECONDS = 180.0
WINDOWS_UTF8_CODE_PAGE = 65001
SEMANTIC_SKILL_BOOTSTRAP_DEVELOPER_INSTRUCTIONS = (
    "First read SKILL.md once, standalone. "
    "Read now; no pre-read reply/questions. "
    "copy source_field/fixed_argv_prefix_copy verbatim; keep quotes/runner; never reconstruct; "
    "opaque IDs/handles/tokens/digests. draft-apply: 1 argv/fact; batch=6; "
    "final=remaining; all facts. Rows obey returned max. "
    "Composer: one action/call. "
    "allowed_action_argv owns TYPE; not Real64/int16. unapplied "
    "ancestor deferred_fact; execute_after=all_pending_ancestor_facts_in_response_"
    "tree_preorder. branch constant/value. "
    "Top facts first; exhaust tree. More=>ancestor_next_item_source; "
    "none=>completion_candidate.copy_command incl task_authority. Metadata: obey "
    "composer.start.preconditions; absent=none; prompt/schema!=live; all dynamic tokens "
    "pre-draft; single existing=>--object GUID; --object-type "
    "only new/imported/plural. "
    "SoundBank=>role_route; exact bank=>soundbank.by_exact_name. "
    "path=>by_path_segments one "
    "arg/segment; name=>query>ID=>by_id; GUID=>by_id. "
    "Else path=>path; no exact-type-name; subset reread only. "
    "one query/hop; no merge. "
    "enum/const exact. typed_operation: copy gateway_argv_prefix incl --apply; "
    "selector kind/value separate. "
    "Import type=Sound SFX; Sound query=all-sounds. Events: parents first. "
    "New path=>parent; name=>declaration only. "
    "POSIX path: single-quote; keep backslashes; one arg/child. "
    "Files absolute; no traversal. "
    "timeout_ms>=30000; use shell_tool_timeout_ms; scalars first. "
    "Draft same turn; no progress reply. "
    "draft-check!=Preview. Preview-now: finish schema/metadata/Preview now; "
    "only execution waits for confirmation. next_command unless "
    "requires_later_user_message. Omit workdir/cwd."
)


def semantic_skill_bootstrap_developer_instructions(
    runner_path: str | Path,
) -> str:
    """Bind typed-profile model guidance to one exact packaged runner prefix."""

    raw_runner = str(runner_path)
    windows_path = PureWindowsPath(raw_runner)
    posix_path = PurePosixPath(raw_runner)
    if raw_runner == TASK_LOCAL_RUNNER_WINDOWS:
        command_prefix = encode_windows_model_argv(
            ("python", raw_runner, "gateway.py")
        )
    elif raw_runner == TASK_LOCAL_RUNNER_POSIX:
        command_prefix = shlex.join(("python", raw_runner, "gateway.py"))
    elif windows_path.is_absolute():
        command_prefix = encode_windows_model_argv(
            ("python", raw_runner, "gateway.py")
        )
    elif posix_path.is_absolute():
        command_prefix = shlex.join(("python", raw_runner, "gateway.py"))
    else:
        raise CodexHarnessError(
            "semantic Skill runner path must be absolute in its owning path flavor"
        )
    return (
        SEMANTIC_SKILL_BOOTSTRAP_DEVELOPER_INSTRUCTIONS
        + " No next_command: only "
        + command_prefix
        + "; append disclosed argv verbatim."
    )


def semantic_task_developer_instructions(
    runner_path: str | Path,
    *,
    task_skill_source: str | Path,
    expected_skill_reads: Sequence[Sequence[str]],
    base_developer_instructions: str | None = None,
) -> str:
    """Seal exact host-native Skill reads into one formal task instruction."""

    try:
        schedule = tuple(tuple(row) for row in expected_skill_reads)
    except TypeError as exc:
        raise CodexHarnessError("semantic Skill read schedule is invalid") from exc
    if not schedule or schedule[0][:1] != ("SKILL.md",):
        raise CodexHarnessError(
            "semantic Skill read schedule must begin with exactly one SKILL.md read"
        )
    flattened = tuple(value for row in schedule for value in row)
    if (
        any(value not in _ALLOWED_SKILL_READS for value in flattened)
        or flattened.count("SKILL.md") != 1
        or len(flattened) != len(set(flattened))
    ):
        raise CodexHarnessError("semantic Skill read schedule is not closed")

    raw_skill_source = str(task_skill_source)
    windows_source = PureWindowsPath(raw_skill_source)
    posix_source = PurePosixPath(raw_skill_source)
    is_windows = windows_source.is_absolute()
    if not is_windows and not posix_source.is_absolute():
        raise CodexHarnessError(
            "semantic task Skill source must be absolute in its owning path flavor"
        )

    turn_rows: list[str] = []
    for turn_index, reads in enumerate(schedule, start=1):
        if not reads:
            turn_rows.append(f"{turn_index} none")
            continue
        commands: list[str] = []
        for relative in reads:
            if is_windows:
                relative_windows = relative.replace("/", "\\")
                commands.append(
                    "Get-Content -Raw -Encoding UTF8 "
                    f"'.agents\\skills\\waapi-skill\\{relative_windows}'"
                )
            else:
                path = PurePosixPath(".agents/skills/waapi-skill").joinpath(
                    *PurePosixPath(relative).parts
                )
                quoted = "'" + str(path).replace("'", "'\"'\"'") + "'"
                commands.append(f"cat {quoted}")
        turn_rows.append(
            f"{turn_index} "
            + " then ".join(f"[{command}]" for command in commands)
        )

    candidate_base = semantic_skill_bootstrap_developer_instructions(runner_path)
    base = (
        candidate_base
        if base_developer_instructions is None
        else base_developer_instructions
    )
    if not isinstance(base, str) or not base or base != base.strip():
        raise CodexHarnessError("semantic base developer instructions are invalid")
    if base == candidate_base:
        task_runner = (
            TASK_LOCAL_RUNNER_WINDOWS
            if is_windows
            else TASK_LOCAL_RUNNER_POSIX
        )
        base = semantic_skill_bootstrap_developer_instructions(task_runner)
    instructions = (
        base
        + " Reads: "
        + "; ".join(turn_rows)
        + ". Exact turn; no early/late/extra reads."
    )
    if len(instructions.encode("utf-8")) > 2048:
        raise CodexHarnessError(
            "semantic task developer instructions exceed the 2048-byte limit"
        )
    return instructions


WINDOWS_SEMANTIC_SANDBOX_MODE = "unelevated"
WINDOWS_HARD_REAP_SECONDS = 5.0
PROMPT_AUDIT_TIMEOUT_SECONDS = 30.0
PROMPT_AUDIT_MAX_ATTEMPTS = 2
CODEX_BINARY_PROBE_TIMEOUT_SECONDS = 15.0
CODEX_VERSION_PATTERN = re.compile(
    r"^(?:codex|codex-cli) (?:0|[1-9][0-9]*)\."
    r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
    r"(?:-[0-9A-Za-z]+(?:[.-][0-9A-Za-z]+)*)?"
    r"(?:\+[0-9A-Za-z]+(?:[.-][0-9A-Za-z]+)*)?$"
)
CODEX_VERSION_OUTPUT_MAX_BYTES = 256
POWERSHELL_CORE_PROBE_TIMEOUT_SECONDS = 30.0
POWERSHELL_CORE_VERSION_OUTPUT_MAX_BYTES = 256
POWERSHELL_CORE_MINIMUM_VERSION = (7, 3, 0)
POWERSHELL_CORE_VERSION_PATTERN = re.compile(
    r"^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
    r"(?:\.(?:0|[1-9][0-9]*))?$"
)
POWERSHELL_CORE_NATIVE_ARGUMENT_MODES = frozenset({"Standard", "Windows"})
WORKSPACE_SKILL_EXCLUDED_NAMES = frozenset(
    {".venv", "__pycache__", ".pytest_cache", ".DS_Store", ".coverage"}
)
MEMORY_MARKERS = (
    "MEMORY_SUMMARY",
    "## Memory",
    "<oai-mem-citation>",
    "/.codex/memories",
    "\\.codex\\memories",
)
SOURCE_SUFFIXES = frozenset(
    {
        ".py",
        ".pyw",
        ".js",
        ".ts",
        ".sh",
        ".command",
        ".rb",
        ".ps1",
        ".lua",
        ".pl",
        ".php",
        ".c",
        ".cc",
        ".cpp",
        ".h",
        ".hpp",
        ".swift",
        ".go",
        ".rs",
    }
)
SUPPORTED_WWISE_VERSIONS = frozenset({"2021.1", "2022.1", "2023.1", "2024.1", "2025.1"})
GATEWAY_SUBCOMMANDS = frozenset(
    {
        "status",
        "config-show",
        "config-set",
        "buses",
        "selected",
        "query-schema",
        "query-object",
        "metadata",
        "topic-schema",
        "wait-topic",
        "stream-topic",
        "capabilities",
        "describe",
        "operations",
        "operation-schema",
        "request-schema",
        "request-map-container",
        "request-array-item",
        "legacy-operation-schema",
        *DRAFT_GATEWAY_SUBCOMMANDS,
        "transaction-show",
        "confirm",
        "reject",
        "preview",
        "legacy-preview",
        "typed-zero-call",
        "typed-call",
        "typed-operation",
        "core-call",
        "execute",
        "verify",
        "call",
    }
)
_PROTECTED_ENV_EXACT = frozenset({"HOME", "USERPROFILE", "CODEX_HOME"})
_BROKER_COMMON_MODEL_ENV_NAMES = frozenset(
    {
        "WAAPI_CODEX_GATEWAY_BROKER_ENDPOINT",
        "WAAPI_CODEX_GATEWAY_BROKER_TOKEN",
        "WAAPI_CODEX_GATEWAY_BROKER_TRANSPORT",
        "WAAPI_CODEX_GATEWAY_REQUIRED",
    }
)
_BROKER_POSIX_MODEL_ENV_NAMES = _BROKER_COMMON_MODEL_ENV_NAMES | {"BASH_ENV"}
_BROKER_WINDOWS_TRUSTED_PYTHON_ENV = "WAAPI_CODEX_GATEWAY_SHIM_TRUSTED_PYTHON"
_BROKER_WINDOWS_MODEL_ENV_NAMES = _BROKER_COMMON_MODEL_ENV_NAMES | {
    _BROKER_WINDOWS_TRUSTED_PYTHON_ENV
}
_BROKER_ALL_MODEL_ENV_NAMES = (
    _BROKER_POSIX_MODEL_ENV_NAMES | _BROKER_WINDOWS_MODEL_ENV_NAMES
)
_BROKER_POSIX_OVERLAY_NAMES = _BROKER_POSIX_MODEL_ENV_NAMES | {"PATH"}
_BROKER_WINDOWS_OVERLAY_NAMES = _BROKER_WINDOWS_MODEL_ENV_NAMES | {"PATH", "PATHEXT"}
_SHELL_ASSIGNMENT_RE = re.compile(r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)=(?P<value>.*)", re.DOTALL)
_PYTHON_EXECUTABLE_RE = re.compile(r"python(?:3(?:\.\d+)?)?(?:\.exe)?")
_RUNNER_VERSION_SELECTORS = frozenset({"--version", "--wwise-version"})
_POSIX_COMMAND_PARSER_KINDS = frozenset({"posix-native", "posix-shell"})
_WINDOWS_POWERSHELL_CORE_PARSER_KIND = "windows-pwsh-command"
_WINDOWS_ENCODED_POWERSHELL_PARSER_KIND = "windows-powershell-encoded"
_TRANSACTION_NEXT_COMMAND_CONTRACT = "waapi-skill.gateway-next-command/v2"
_TRANSACTION_COPY_INSTRUCTION_CONTRACT = (
    "waapi-skill.gateway-command-copy-instruction/v2"
)
_TRANSACTION_COPY_ACTION = "execute_verbatim_as_one_shell_tool_call"
_TRANSACTION_FORBIDDEN_TRANSFORMATIONS = (
    "reconstruct",
    "shorten",
    "normalize",
    "substitute_path_segments",
    "select_another_field",
)
_WINDOWS_POWERSHELL_COMMAND_NAMES = frozenset({"powershell", "powershell.exe"})
_WINDOWS_POWERSHELL_CORE_COMMAND_NAMES = frozenset({"pwsh", "pwsh.exe"})
_POWERSHELL_BARE_FORBIDDEN = frozenset("|&;<>`$(){}[]@#,%*?\"'")
_POWERSHELL_SMART_QUOTES = frozenset(chr(value) for value in range(0x2018, 0x2020))
_ALLOWED_SKILL_READS = frozenset(
    {
        "SKILL.md",
        "references/waapi-setup.md",
        "references/waapi-query.md",
        "references/waapi-operate.md",
        "references/waapi-coverage.md",
    }
)


def discover_windows_user_skill_paths(
    *,
    environment: Mapping[str, str] | None = None,
    platform_name: str | None = None,
) -> tuple[Path, ...]:
    r"""Return exact user-global Skill files Codex may discover on Windows.

    Native Codex resolves ``%USERPROFILE%\.agents\skills`` through the Windows
    user profile Known Folder even when the child process receives disposable
    HOME, USERPROFILE, and CODEX_HOME values.  Formal campaign commands disable
    every pre-existing file by exact path while retaining the task-local
    ``waapi-skill`` installed below the isolated workspace.
    """

    if not _is_windows(platform_name):
        return ()
    source = os.environ if environment is None else environment
    user_profile = _environment_value_case_insensitive(source, "USERPROFILE")
    if not user_profile:
        raise CodexHarnessError(
            "native Windows user Skill isolation requires USERPROFILE"
        )
    root = Path(user_profile).expanduser() / ".agents" / "skills"
    if not root.exists():
        return ()
    if not root.is_dir() or is_link_or_junction(root):
        raise CodexHarnessError(
            f"native Windows user Skill root is not a regular directory: {root}"
        )
    paths: list[Path] = []
    for entry in sorted(root.iterdir(), key=lambda value: value.name.casefold()):
        skill_file = entry / "SKILL.md"
        if not entry.is_dir() or is_link_or_junction(entry) or not skill_file.exists():
            continue
        if not skill_file.is_file() or is_link_or_junction(skill_file):
            raise CodexHarnessError(
                f"native Windows user Skill file is not regular: {skill_file}"
            )
        paths.append(skill_file.resolve(strict=True))
    if len(paths) != len(set(paths)):
        raise CodexHarnessError("native Windows user Skill paths are duplicated")
    return tuple(paths)


def _disabled_user_skill_config_argv(paths: Sequence[Path]) -> tuple[str, ...]:
    if not paths:
        return ()
    normalized = tuple(Path(path).expanduser().resolve(strict=False) for path in paths)
    if len(normalized) != len(set(normalized)) or any(
        not path.is_absolute() or path.name != "SKILL.md" for path in normalized
    ):
        raise CodexHarnessError("disabled user Skill paths are invalid")
    rows = ",".join(
        "{path=" + json.dumps(str(path)) + ",enabled=false}"
        for path in normalized
    )
    return ("-c", f"skills.config=[{rows}]")
_POSIX_WORKSPACE_SKILL_READS = {
    ".agents/skills/waapi-skill/SKILL.md": ("SKILL.md",),
    ".agents/skills/waapi-skill/references/waapi-setup.md": (
        "references",
        "waapi-setup.md",
    ),
    ".agents/skills/waapi-skill/references/waapi-query.md": (
        "references",
        "waapi-query.md",
    ),
    ".agents/skills/waapi-skill/references/waapi-operate.md": (
        "references",
        "waapi-operate.md",
    ),
    ".agents/skills/waapi-skill/references/waapi-coverage.md": (
        "references",
        "waapi-coverage.md",
    ),
}
_WINDOWS_WORKSPACE_SKILL_READS = {
    r".agents\skills\waapi-skill\SKILL.md": ("SKILL.md",),
    r".agents\skills\waapi-skill\references\waapi-setup.md": (
        "references",
        "waapi-setup.md",
    ),
    r".agents\skills\waapi-skill\references\waapi-query.md": (
        "references",
        "waapi-query.md",
    ),
    r".agents\skills\waapi-skill\references\waapi-operate.md": (
        "references",
        "waapi-operate.md",
    ),
    r".agents\skills\waapi-skill\references\waapi-coverage.md": (
        "references",
        "waapi-coverage.md",
    ),
}
_WORKSPACE_SKILL_READS_BY_SYNTAX = {
    "posix": _POSIX_WORKSPACE_SKILL_READS,
    "windows": _WINDOWS_WORKSPACE_SKILL_READS,
}
_SKILL_LINE_RE = re.compile(
    r"(?m)^\s*-\s+(?P<name>[A-Za-z0-9_.:-]+)\s*:\s*.*?"
    r"\((?:file|source|locator)\s*:\s*(?P<locator>[^)\n]+)\)\s*$"
)
_SKILL_ROOT_LINE_RE = re.compile(
    r"(?m)^\s*-\s*`?(?P<alias>r[0-9]+)`?\s*=\s*"
    r"`?(?P<root>[^`\r\n]+?)`?\s*$"
)
_SKILL_ALIAS_LOCATOR_RE = re.compile(
    r"^(?P<alias>r[0-9]+)[/\\](?P<relative>.+)$"
)
_LEGACY_WORKSPACE_SKILL_RE = re.compile(r"(?im)^\s*workspace\s+skill\s*:\s*(?P<name>[A-Za-z0-9_.:-]+)\s*$")
_CODEX_INFRASTRUCTURE_ERROR_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "quota_or_rate_limit",
        (
            "usage limit",
            "rate limit",
            "rate_limit",
            "too many requests",
            "insufficient_quota",
            "quota exceeded",
            "purchase more credits",
        ),
    ),
    (
        "authentication",
        (
            "authentication",
            "authentication failed",
            "authentication error",
            "not authenticated",
            "unauthorized",
            "invalid api key",
            "invalid_grant",
            "login required",
            "missing bearer",
            "not logged in",
            "please log in",
            "token expired",
            "status 401",
            "status 403",
            "http 401",
            "http 403",
        ),
    ),
    (
        "service_unavailable",
        (
            "service unavailable",
            "temporarily unavailable",
            "internal server error",
            "server is overloaded",
            "server overloaded",
            "failed to connect",
            "connection error",
            "connection closed",
            "connection refused",
            "error sending request",
            "network error",
            "request timed out",
            "stream disconnected",
            "upstream error",
            "gateway timeout",
            "status 502",
            "status 503",
            "status 504",
            "http 502",
            "http 503",
            "http 504",
        ),
    ),
)


class CodexHarnessError(RuntimeError):
    """Raised when a Codex semantic run cannot satisfy the isolation contract."""


def _is_codex_sandbox_proxy(path: Path) -> bool:
    """Return whether ``path`` is Codex's outer sandbox command proxy."""

    parts = tuple(part.casefold() for part in Path(path).parts)
    return any(
        parts[index : index + 2] == (".codex", ".sandbox-bin")
        for index in range(max(0, len(parts) - 1))
    )


def _is_protected_windowsapps_path(path: Path) -> bool:
    """Recognize Microsoft Store package roots and App Execution Alias roots."""

    native_parts = tuple(part.casefold() for part in Path(path).parts)
    windows_parts = tuple(part.casefold() for part in PureWindowsPath(str(path)).parts)
    for parts in (native_parts, windows_parts):
        for index, part in enumerate(parts):
            if part != "windowsapps" or index == 0:
                continue
            if parts[index - 1] in {"microsoft", "program files", "program files (x86)"}:
                return True
    return False


def _strict_codex_binary(
    candidate: Path,
    *,
    source: str,
    platform_name: str | None = None,
) -> Path:
    """Resolve one Codex executable candidate without accepting a missing path."""

    try:
        resolved = candidate.expanduser().resolve(strict=True)
    except OSError as exc:
        raise CodexHarnessError(f"{source} Codex binary is unavailable: {candidate}") from exc
    if not resolved.is_file() or not os.access(resolved, os.X_OK):
        raise CodexHarnessError(f"{source} Codex binary is not executable: {resolved}")
    active_platform = sys.platform if platform_name is None else platform_name
    if active_platform.startswith("win") and resolved.suffix.casefold() != ".exe":
        raise CodexHarnessError(
            f"{source} Codex binary must be a host-native .exe on Windows: {resolved}"
        )
    if active_platform.startswith("win") and (
        _is_codex_sandbox_proxy(candidate) or _is_codex_sandbox_proxy(resolved)
    ):
        raise CodexHarnessError(
            f"{source} Codex binary resolves to the outer sandbox proxy {resolved}; "
            "pass --codex-binary with the real host-native Codex executable"
        )
    if active_platform.startswith("win") and (
        _is_protected_windowsapps_path(candidate)
        or _is_protected_windowsapps_path(resolved)
    ):
        raise CodexHarnessError(
            f"{source} Codex binary resolves through a protected Microsoft Store "
            f"WindowsApps path {resolved}; install the standalone Codex CLI"
        )
    return resolved


def validate_codex_version_output(value: str, *, binary: Path) -> str:
    """Require the stable machine-readable shape emitted by ``codex --version``."""

    raw = str(value)
    try:
        encoded = raw.encode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise CodexHarnessError(
            f"Codex CLI version output is not UTF-8 for {binary}"
        ) from exc
    if len(encoded) > CODEX_VERSION_OUTPUT_MAX_BYTES or "\0" in raw:
        raise CodexHarnessError(
            f"Codex CLI version output is invalid for {binary}: oversized or contains NUL"
        )
    if raw.endswith("\r\n"):
        version = raw[:-2]
    elif raw.endswith("\n"):
        version = raw[:-1]
    else:
        version = raw
    if "\r" in version or "\n" in version or version != version.strip():
        raise CodexHarnessError(
            f"Codex CLI version output is invalid for {binary}: expected one clean line"
        )
    if not CODEX_VERSION_PATTERN.fullmatch(version):
        raise CodexHarnessError(
            f"Codex CLI version output is invalid for {binary}: {version!r}"
        )
    return version


def _environment_value_case_insensitive(
    environment: Mapping[str, str],
    name: str,
) -> str | None:
    expected = name.casefold()
    for key, value in environment.items():
        if str(key).casefold() == expected:
            return str(value)
    return None


def _default_codex_path_candidates(
    platform_name: str,
    *,
    environment: Mapping[str, str],
) -> Iterator[Path]:
    """Yield lexical PATH candidates so strict resolution can explain failures."""

    executable_names = ("codex.exe",) if platform_name.startswith("win") else ("codex",)
    raw_path = _environment_value_case_insensitive(environment, "PATH") or os.defpath
    for raw_directory in raw_path.split(os.pathsep):
        directory = Path(raw_directory or os.curdir).expanduser()
        for executable_name in executable_names:
            candidate = directory / executable_name
            if os.path.lexists(candidate):
                yield candidate


def _windows_standalone_codex_candidates(
    environment: Mapping[str, str],
) -> Iterator[tuple[Path, str]]:
    """Yield official user-owned Windows CLI locations before ambient PATH."""

    user_profile = _environment_value_case_insensitive(environment, "USERPROFILE")
    codex_homes: list[Path] = []
    configured_codex_home = _environment_value_case_insensitive(environment, "CODEX_HOME")
    if configured_codex_home:
        codex_homes.append(Path(configured_codex_home).expanduser())
    if user_profile:
        default_codex_home = Path(user_profile).expanduser() / ".codex"
        if default_codex_home not in codex_homes:
            codex_homes.append(default_codex_home)
    for codex_home in codex_homes:
        current = codex_home / "packages" / "standalone" / "current"
        candidate = current / "bin" / "codex.exe"
        if os.path.lexists(candidate):
            yield candidate, "official standalone current"

    local_appdata = _environment_value_case_insensitive(environment, "LOCALAPPDATA")
    if local_appdata:
        visible = (
            Path(local_appdata).expanduser()
            / "Programs"
            / "OpenAI"
            / "Codex"
            / "bin"
            / "codex.exe"
        )
        if os.path.lexists(visible):
            yield visible, "official standalone visible command"


def discover_codex_binary(
    *,
    platform_name: str | None = None,
    which: Callable[[str], str | None] | None = None,
    macos_app_fallback: Path = MACOS_APP_CODEX_FALLBACK,
    environment: Mapping[str, str] | None = None,
    probe: Callable[[Path], str] | None = None,
) -> Path:
    """Discover the host-native Codex CLI, with an App fallback only on macOS."""

    platform_name = sys.platform if platform_name is None else platform_name
    active_environment = dict(os.environ if environment is None else environment)
    rejected_candidates: list[str] = []
    if which is None and platform_name.startswith("win"):
        candidates = (
            *_windows_standalone_codex_candidates(active_environment),
            *(
                (candidate, f"PATH ({candidate.name})")
                for candidate in _default_codex_path_candidates(
                    platform_name,
                    environment=active_environment,
                )
            ),
        )
    else:
        command_names = (
            ("codex.exe", "codex")
            if platform_name.startswith("win")
            else ("codex",)
        )
        lookup = shutil.which if which is None else which
        candidates = (
            (Path(discovered), f"PATH ({command_name})")
            for command_name in command_names
            if (discovered := lookup(command_name))
        )
    seen: set[str] = set()
    for candidate, source in candidates:
        try:
            resolved = _strict_codex_binary(
                candidate,
                source=source,
                platform_name=platform_name,
            )
        except CodexHarnessError as exc:
            if not platform_name.startswith("win"):
                raise exc
            rejected_candidates.append(str(exc))
            continue
        identity = os.path.normcase(str(resolved))
        if identity in seen:
            continue
        seen.add(identity)
        if platform_name.startswith("win"):
            try:
                codex_runtime_files(
                    resolved,
                    platform_name=platform_name,
                )
            except CodexHarnessError as exc:
                rejected_candidates.append(f"{source} {resolved}: {exc}")
                continue
            active_probe = probe or (
                lambda path: _probe_codex_binary(
                    path,
                    platform_name=platform_name,
                    environment=active_environment,
                )
            )
            try:
                validate_codex_version_output(
                    active_probe(resolved),
                    binary=resolved,
                )
            except (CodexHarnessError, OSError, subprocess.SubprocessError) as exc:
                rejected_candidates.append(f"{source} {resolved}: {type(exc).__name__}: {exc}")
                continue
        return resolved
    if platform_name == "darwin":
        return _strict_codex_binary(
            macos_app_fallback,
            source="macOS App fallback",
            platform_name=platform_name,
        )
    if rejected_candidates:
        rendered = "; ".join(rejected_candidates[:8])
        raise CodexHarnessError(
            "no usable host-native Codex CLI was found; rejected candidates: "
            f"{rendered}. Install the official standalone Codex CLI or pass "
            "--codex-binary with its real executable"
        )
    if not platform_name.startswith("win"):
        raise CodexHarnessError(
            "Codex CLI was not found on PATH; pass an explicit --codex-binary path"
        )
    raise CodexHarnessError(
        "Codex CLI was not found in the official Windows standalone locations "
        "or on PATH; install the standalone CLI or pass an explicit "
        "--codex-binary path"
    )


def resolve_codex_binary(value: str | os.PathLike[str] | None) -> Path:
    """Honor an explicit CLI path before attempting host-native discovery."""

    if value is None:
        return discover_codex_binary()
    return _strict_codex_binary(Path(value), source="explicit")


def _is_windows(platform_name: str | None = None) -> bool:
    """Return the active platform through one injectable test seam."""

    return (os.name if platform_name is None else platform_name) == "nt"


def _is_windows_platform(platform_name: str | None = None) -> bool:
    active = os.name if platform_name is None else str(platform_name)
    return active == "nt" or active.startswith("win")


def enforce_windows_console_utf8(
    *,
    platform_name: str | None = None,
    console_api: Any | None = None,
) -> tuple[int, int] | None:
    """Make every child Codex/pwsh console transport inherit UTF-8.

    ``Get-Content -Encoding UTF8`` controls file decoding, not the encoding
    used when PowerShell writes that text to an attached Windows console.  A
    native Fresh task can otherwise inherit CP936 and archive mojibake even
    though the exact read command succeeded.  Set and attest both directions
    before launching any prompt audit or Codex task; byte-exact read grading
    remains unchanged.
    """

    if not _is_windows(platform_name):
        return None
    if console_api is None:
        try:
            console_api = ctypes.windll.kernel32
        except AttributeError as exc:  # pragma: no cover - native Windows only.
            raise CodexHarnessError("Windows console API is unavailable") from exc

    before_input = int(console_api.GetConsoleCP())
    before_output = int(console_api.GetConsoleOutputCP())
    if before_input != WINDOWS_UTF8_CODE_PAGE and not console_api.SetConsoleCP(
        WINDOWS_UTF8_CODE_PAGE
    ):
        raise CodexHarnessError(
            "Windows Fresh campaign could not set console input code page to UTF-8"
        )
    if before_output != WINDOWS_UTF8_CODE_PAGE and not console_api.SetConsoleOutputCP(
        WINDOWS_UTF8_CODE_PAGE
    ):
        if before_input != WINDOWS_UTF8_CODE_PAGE:
            console_api.SetConsoleCP(before_input)
        raise CodexHarnessError(
            "Windows Fresh campaign could not set console output code page to UTF-8"
        )

    current = (int(console_api.GetConsoleCP()), int(console_api.GetConsoleOutputCP()))
    if current != (WINDOWS_UTF8_CODE_PAGE, WINDOWS_UTF8_CODE_PAGE):
        raise CodexHarnessError(
            "Windows Fresh campaign console code-page attestation failed: "
            f"expected UTF-8/UTF-8, observed {current[0]}/{current[1]}"
        )
    return current


@dataclass(frozen=True, slots=True)
class WindowsPowerShellCoreHost:
    """One exact, directly probed PowerShell Core native-command host."""

    executable: str
    version: str
    native_argument_passing: str
    sha256: str

    def __post_init__(self) -> None:
        executable = PureWindowsPath(self.executable)
        if (
            not executable.is_absolute()
            or executable.name.casefold() != "pwsh.exe"
            or any(part in {".", ".."} for part in executable.parts)
        ):
            raise ValueError("PowerShell Core host must be one absolute pwsh.exe path")
        version = _parse_powershell_core_version(self.version)
        if version[:3] < POWERSHELL_CORE_MINIMUM_VERSION:
            raise ValueError("PowerShell Core 7.3 or newer is required")
        if self.native_argument_passing not in POWERSHELL_CORE_NATIVE_ARGUMENT_MODES:
            raise ValueError(
                "PowerShell Core native argument mode must be Standard or Windows"
            )
        if re.fullmatch(r"[0-9a-f]{64}", self.sha256) is None:
            raise ValueError("PowerShell Core host SHA-256 must be lowercase hexadecimal")

    def fingerprint_dict(self) -> dict[str, str]:
        """Return the stable campaign-sealing projection for this exact host."""

        return {
            "path": self.executable,
            "version": self.version,
            "native_argument_passing": self.native_argument_passing,
            "sha256": self.sha256,
        }


def _parse_powershell_core_version(value: str) -> tuple[int, ...]:
    if POWERSHELL_CORE_VERSION_PATTERN.fullmatch(value) is None:
        raise ValueError("PowerShell Core version must be a canonical numeric version")
    return tuple(int(part) for part in value.split("."))


def validate_powershell_core_probe_output(
    output: str,
    *,
    executable: str,
    sha256: str,
) -> WindowsPowerShellCoreHost:
    """Validate the exact Core/version/native-argument tuple emitted by the probe."""

    if len(output.encode("utf-8")) > POWERSHELL_CORE_VERSION_OUTPUT_MAX_BYTES:
        raise CodexHarnessError("PowerShell Core probe output is too large")
    normalized = (
        output[:-2]
        if output.endswith("\r\n")
        else output[:-1]
        if output.endswith("\n")
        else output
    )
    if not normalized or "\n" in normalized or "\r" in normalized:
        raise CodexHarnessError("PowerShell Core probe must return exactly one line")
    parts = normalized.split("|")
    if len(parts) != 3 or parts[0] != "Core":
        raise CodexHarnessError("PowerShell Core probe did not report the Core edition")
    try:
        return WindowsPowerShellCoreHost(
            executable=executable,
            version=parts[1],
            native_argument_passing=parts[2],
            sha256=sha256,
        )
    except ValueError as exc:
        raise CodexHarnessError(f"unsupported PowerShell Core host: {exc}") from exc


def probe_windows_powershell_core(
    executable: str | os.PathLike[str],
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
) -> WindowsPowerShellCoreHost:
    """Attest one real pwsh.exe with a direct, profile-free, shell-free probe."""

    candidate = Path(executable).expanduser()
    if (
        not candidate.is_absolute()
        or candidate.name.casefold() != "pwsh.exe"
        or is_link_or_junction(candidate)
    ):
        raise CodexHarnessError(
            "PowerShell Core host must be an absolute, real, non-reparse pwsh.exe"
        )
    try:
        candidate = candidate.resolve(strict=True)
    except OSError as exc:
        raise CodexHarnessError(
            f"PowerShell Core executable does not resolve: {candidate}: {exc}"
        ) from exc
    if (
        candidate.name.casefold() != "pwsh.exe"
        or is_link_or_junction(candidate)
        or not candidate.is_file()
    ):
        raise CodexHarnessError(
            "PowerShell Core host must be an absolute, real, non-reparse pwsh.exe"
        )
    digest = _sha256_regular_file(candidate)
    probe_script = (
        "[Console]::Out.Write(('{0}|{1}|{2}' -f "
        "$PSVersionTable.PSEdition,$PSVersionTable.PSVersion.ToString(),"
        "$PSNativeCommandArgumentPassing))"
    )
    run = subprocess.run if runner is None else runner
    probe_argv = [
        str(candidate),
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        probe_script,
    ]
    try:
        completed = run(
            probe_argv,
            cwd=Path.cwd(),
            env=os.environ.copy(),
            shell=False,
            text=True,
            encoding="utf-8",
            errors="strict",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=POWERSHELL_CORE_PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError, UnicodeError) as exc:
        raise CodexHarnessError(
            f"PowerShell Core launch probe failed for {candidate}: "
            f"{type(exc).__name__}: {exc}"
        ) from exc
    if completed.returncode != 0 or completed.stderr:
        detail = completed.stderr.strip() or f"exit code {completed.returncode}"
        raise CodexHarnessError(
            f"PowerShell Core launch probe failed for {candidate}: {detail}"
        )
    return validate_powershell_core_probe_output(
        completed.stdout,
        executable=str(candidate),
        sha256=digest,
    )


def powershell_core_host_fingerprint(
    host: WindowsPowerShellCoreHost,
) -> dict[str, str]:
    """Expose the exact JSON-serializable PowerShell host seal."""

    return host.fingerprint_dict()


def discover_windows_powershell_core(
    *,
    environment: Mapping[str, str] | None = None,
    platform_name: str | None = None,
    which: Callable[..., str | None] | None = None,
    probe: Callable[[str | os.PathLike[str]], WindowsPowerShellCoreHost] | None = None,
) -> WindowsPowerShellCoreHost:
    """Select and attest the exact pwsh.exe that native Codex will see on PATH."""

    if not _is_windows_platform(platform_name):
        raise CodexHarnessError("PowerShell Core discovery is available only on Windows")
    active_environment = os.environ if environment is None else environment
    path_value = next(
        (
            str(value)
            for key, value in active_environment.items()
            if str(key).casefold() == "path"
        ),
        None,
    )
    locate = shutil.which if which is None else which
    candidate = locate("pwsh.exe", path=path_value)
    if not candidate:
        raise CodexHarnessError(
            "PowerShell Core 7.3 or newer is required on PATH for native Windows campaigns"
        )
    attest = probe_windows_powershell_core if probe is None else probe
    return attest(candidate)


def is_link_or_junction(path: Path) -> bool:
    """Reject links, junctions, and older-Python Windows reparse points."""

    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    if is_junction is not None and is_junction():
        return True
    try:
        attributes = int(getattr(path.lstat(), "st_file_attributes", 0))
    except OSError:
        return False
    reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    return bool(attributes & reparse_flag)


def _sha256_regular_file(path: Path) -> str:
    if is_link_or_junction(path) or not path.is_file():
        raise CodexHarnessError(f"expected a real regular file: {path}")
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise CodexHarnessError(f"cannot read regular file {path}: {exc}") from exc
    return digest.hexdigest()


def _windows_codex_release_root(binary: Path) -> Path:
    """Return the exact official standalone release root for one Windows CLI."""

    executable = Path(binary).expanduser().resolve(strict=True)
    if (
        executable.name.casefold() != "codex.exe"
        or executable.parent.name.casefold() != "bin"
    ):
        raise CodexHarnessError(
            "Windows semantic campaigns require the standalone executable at "
            f"<release>\\bin\\codex.exe; received: {executable}"
        )
    return executable.parent.parent


def _windows_codex_runtime_directories(binary: Path) -> tuple[Path, ...]:
    """Return directories belonging to the exact selected standalone release."""

    root = _windows_codex_release_root(binary)
    candidates = (
        root / "bin",
        root / "codex-resources",
        root / "codex-path",
    )
    directories: list[Path] = []
    for candidate in candidates:
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            continue
        if resolved.is_dir() and not is_link_or_junction(resolved) and resolved not in directories:
            directories.append(resolved)
    return tuple(directories)


def codex_runtime_files(
    binary: Path,
    *,
    platform_name: str | None = None,
) -> tuple[Path, ...]:
    """Return helper files that belong to the selected Windows standalone CLI."""

    active_platform = sys.platform if platform_name is None else platform_name
    if not active_platform.startswith("win"):
        return ()
    root = _windows_codex_release_root(binary)
    package_marker = root / "codex-package.json"
    if not package_marker.is_file():
        raise CodexHarnessError(
            "Windows semantic campaigns require an official standalone Codex "
            f"release; package marker is missing: {package_marker}"
        )
    candidates = (
        package_marker,
        root / "bin" / "codex-code-mode-host.exe",
        root / "codex-path" / "rg.exe",
        root / "codex-resources" / "codex-command-runner.exe",
        root / "codex-resources" / "codex-windows-sandbox-setup.exe",
    )
    for candidate in candidates:
        _sha256_regular_file(candidate)
    return tuple(candidate.resolve(strict=True) for candidate in candidates)


def codex_process_environment(
    binary: Path,
    environment: Mapping[str, str],
    *,
    platform_name: str | None = None,
    powershell_core_host: WindowsPowerShellCoreHost | None = None,
) -> dict[str, str]:
    """Bind Windows Codex helpers and the attested pwsh host deterministically."""

    active_platform = sys.platform if platform_name is None else platform_name
    result = {str(key): str(value) for key, value in environment.items()}
    if not active_platform.startswith("win"):
        return result
    codex_runtime_files(binary, platform_name=active_platform)
    runtime_directories = _windows_codex_runtime_directories(binary)
    if not runtime_directories:
        return result
    path_key = next((key for key in result if key.casefold() == "path"), "PATH")
    existing = result.get(path_key, os.defpath)
    existing_parts = [part for part in existing.split(";") if part]
    broker_required = any(
        key.casefold() == "waapi_codex_gateway_required" and value == "1"
        for key, value in result.items()
    )
    prefix = existing_parts[:1] if broker_required and existing_parts else []
    suffix = existing_parts[1:] if prefix else existing_parts
    powershell_directory = (
        str(PureWindowsPath(powershell_core_host.executable).parent)
        if powershell_core_host is not None
        else ""
    )
    combined = [
        *prefix,
        *([powershell_directory] if powershell_directory else []),
        *(str(path) for path in runtime_directories),
        *suffix,
    ]
    deduplicated: list[str] = []
    seen: set[str] = set()
    for item in combined:
        identity = os.path.normcase(os.path.abspath(item))
        if identity not in seen:
            seen.add(identity)
            deduplicated.append(item)
    result[path_key] = ";".join(deduplicated)
    return result


def _probe_codex_binary(
    binary: Path,
    *,
    platform_name: str,
    environment: Mapping[str, str],
) -> str:
    """Require one candidate to be hashable and directly launchable without a shell."""

    candidate = Path(binary)
    _sha256_regular_file(candidate)
    for runtime_file in codex_runtime_files(
        candidate,
        platform_name=platform_name,
    ):
        _sha256_regular_file(runtime_file)
    try:
        completed = subprocess.run(
            [str(candidate), "--version"],
            cwd=Path.cwd(),
            env=codex_process_environment(
                candidate,
                environment,
                platform_name=platform_name,
            ),
            text=True,
            encoding="utf-8",
            errors="strict",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=CODEX_BINARY_PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError, UnicodeError) as exc:
        raise CodexHarnessError(
            f"Codex CLI launch probe failed for {candidate}: {type(exc).__name__}: {exc}"
        ) from exc
    version = completed.stdout
    if completed.returncode != 0 or not version:
        detail = completed.stderr.strip() or f"exit code {completed.returncode}"
        raise CodexHarnessError(f"Codex CLI launch probe failed for {candidate}: {detail}")
    return validate_codex_version_output(version, binary=candidate)


def _workspace_skill_manifest(
    root: Path,
    *,
    exclude_names: Sequence[str] = (),
) -> tuple[dict[str, Any], ...]:
    """Return a content-only manifest while rejecting aliases and special files."""

    candidate = Path(root)
    if is_link_or_junction(candidate):
        raise CodexHarnessError(f"workspace Skill tree must be a real directory: {candidate}")
    try:
        tree = candidate.resolve(strict=True)
    except OSError as exc:
        raise CodexHarnessError(f"workspace Skill tree does not exist: {candidate}") from exc
    if not tree.is_dir():
        raise CodexHarnessError(f"workspace Skill tree must be a directory: {tree}")
    excluded = frozenset(str(name) for name in exclude_names)
    rows: list[dict[str, Any]] = []

    def walk(directory: Path) -> None:
        try:
            entries = sorted(os.scandir(directory), key=lambda entry: entry.name)
        except OSError as exc:
            raise CodexHarnessError(f"cannot scan workspace Skill tree {directory}: {exc}") from exc
        for entry in entries:
            if entry.name in excluded:
                continue
            path = Path(entry.path)
            relative = path.relative_to(tree).as_posix()
            try:
                info = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise CodexHarnessError(f"cannot stat workspace Skill entry {path}: {exc}") from exc
            if stat.S_ISLNK(info.st_mode) or is_link_or_junction(path):
                raise CodexHarnessError(f"workspace Skill tree contains a link or junction: {path}")
            if stat.S_ISDIR(info.st_mode):
                rows.append(
                    {
                        "path": relative,
                        "type": "directory",
                        "executable": bool(info.st_mode & 0o111),
                    }
                )
                walk(path)
            elif stat.S_ISREG(info.st_mode):
                rows.append(
                    {
                        "path": relative,
                        "type": "file",
                        "executable": bool(info.st_mode & 0o111),
                        "size": info.st_size,
                        "sha256": _sha256_regular_file(path),
                    }
                )
            else:
                raise CodexHarnessError(f"workspace Skill tree contains a special file: {path}")

    walk(tree)
    return tuple(rows)


def workspace_skill_tree_sha256(
    root: Path,
    *,
    exclude_names: Sequence[str] = (),
) -> str:
    """Hash the same path/content/executable tree shape used by campaign evidence."""

    payload = json.dumps(
        _workspace_skill_manifest(root, exclude_names=exclude_names),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def assert_detached_workspace_skill_copy(source: Path, installed: Path) -> None:
    """Prove a copied Skill has no hardlink alias back into the candidate tree."""

    source_tree = Path(source).resolve(strict=True)
    installed_tree = Path(installed).resolve(strict=True)
    source_ids: set[tuple[int, int]] = set()
    installed_ids: set[tuple[int, int]] = set()
    for root, excluded, identities in (
        (source_tree, WORKSPACE_SKILL_EXCLUDED_NAMES, source_ids),
        (installed_tree, frozenset(), installed_ids),
    ):
        for directory, dirnames, filenames in os.walk(root, followlinks=False):
            directory_path = Path(directory)
            dirnames[:] = [name for name in dirnames if name not in excluded]
            for name in filenames:
                if name in excluded:
                    continue
                path = directory_path / name
                if is_link_or_junction(path):
                    raise CodexHarnessError(
                        f"workspace Skill copy contains a link or junction: {path}"
                    )
                try:
                    info = path.stat()
                except OSError as exc:
                    raise CodexHarnessError(f"cannot stat workspace Skill file {path}: {exc}") from exc
                if not stat.S_ISREG(info.st_mode):
                    raise CodexHarnessError(f"workspace Skill copy contains a special file: {path}")
                identities.add((int(info.st_dev), int(info.st_ino)))
    shared = source_ids.intersection(installed_ids)
    if shared:
        raise CodexHarnessError(
            "workspace Skill copy contains hardlink aliases to the candidate Skill"
        )


def workspace_skill_install_path(workspace: Path) -> Path:
    return Path(workspace) / ".agents" / "skills" / "waapi-skill"


def _prepare_workspace_repository_boundary(workspace: Path) -> None:
    """Stop Codex from inheriting skills and instructions from an outer repo."""

    workspace.mkdir(parents=True, exist_ok=True)
    existing = tuple(workspace.iterdir())
    if existing:
        raise CodexHarnessError(
            "Agent workspace must be empty before its repository boundary is prepared"
        )
    (workspace / ".git").mkdir()


def _verify_workspace_repository_boundary(workspace: Path) -> None:
    if is_link_or_junction(workspace) or not workspace.is_dir():
        raise CodexHarnessError("Agent workspace repository boundary root is not a real directory")
    entries = tuple(sorted(path.name for path in workspace.iterdir()))
    if entries != (".agents", ".git"):
        raise CodexHarnessError(
            "Agent workspace repository boundary has unexpected entries: "
            f"{', '.join(entries) or '<none>'}"
        )
    boundary = workspace / ".git"
    if is_link_or_junction(boundary) or not boundary.is_dir():
        raise CodexHarnessError("Agent workspace repository boundary is not a real directory")
    if tuple(boundary.iterdir()):
        raise CodexHarnessError("Agent workspace repository boundary must remain empty")


def prepare_workspace_skill_install(
    workspace: Path,
    skill_source: Path,
    *,
    platform_name: str | None = None,
) -> Path:
    """Install one detached, campaign-hash-equivalent Skill copy.

    Runtime/cache directories are excluded and every host proves that the
    task-local copy shares no regular-file identities with the frozen
    candidate.  The copy is the model-facing locator only; the authenticated
    Broker continues to execute the sealed candidate runner.
    """

    source_path = Path(skill_source)
    if is_link_or_junction(source_path):
        raise CodexHarnessError(f"Skill source must be a real directory: {source_path}")
    source = source_path.expanduser().resolve(strict=True)
    if not source.is_dir():
        raise CodexHarnessError(f"Skill source must be a directory: {source}")
    _prepare_workspace_repository_boundary(Path(workspace))
    install = workspace_skill_install_path(workspace)
    install.parent.mkdir(parents=True, exist_ok=False)
    source_sha256 = workspace_skill_tree_sha256(
        source,
        exclude_names=WORKSPACE_SKILL_EXCLUDED_NAMES,
    )
    try:
        shutil.copytree(
            source,
            install,
            copy_function=shutil.copy2,
            ignore=shutil.ignore_patterns(*sorted(WORKSPACE_SKILL_EXCLUDED_NAMES)),
            symlinks=True,
        )
    except OSError as exc:
        raise CodexHarnessError(f"cannot copy Skill into task workspace: {exc}") from exc
    installed_sha256 = workspace_skill_tree_sha256(install)
    if installed_sha256 != source_sha256:
        raise CodexHarnessError(
            "workspace Skill copy does not match the candidate tree: "
            f"expected={source_sha256} actual={installed_sha256}"
        )
    assert_detached_workspace_skill_copy(source, install)
    return install


def verify_workspace_skill_install(
    workspace: Path,
    skill_source: Path,
    *,
    platform_name: str | None = None,
) -> Path:
    """Verify the detached install without accepting a weaker host shape."""

    source = Path(skill_source).expanduser().resolve(strict=True)
    _verify_workspace_repository_boundary(Path(workspace))
    install = workspace_skill_install_path(workspace)
    if is_link_or_junction(install) or not install.is_dir():
        raise CodexHarnessError(
            f"WAAPI skill install must be an independent directory copy: {install}"
        )
    expected = workspace_skill_tree_sha256(
        source,
        exclude_names=WORKSPACE_SKILL_EXCLUDED_NAMES,
    )
    observed = workspace_skill_tree_sha256(install)
    if observed != expected:
        raise CodexHarnessError(
            "WAAPI skill copy differs from the candidate tree: "
            f"expected={expected} actual={observed}"
        )
    assert_detached_workspace_skill_copy(source, install)
    return install


@dataclass(frozen=True, slots=True)
class CodexGatewayErrorExpectation:
    """One explicitly expected, structured gateway error result.

    Exit status 2 remains a failed shell command.  The harness treats it as an
    accepted packaged-gateway result only when the caller names both the exact
    gateway command and the exact top-level ``error_code`` expected from a
    ``gateway-result/v1`` payload whose ``ok`` value is ``false``.
    """

    command: str
    error_code: str

    def __post_init__(self) -> None:
        if self.command not in GATEWAY_SUBCOMMANDS:
            raise ValueError(
                "CodexGatewayErrorExpectation.command must be a known gateway subcommand"
            )
        if not self.error_code or not self.error_code.strip():
            raise ValueError("CodexGatewayErrorExpectation.error_code must be non-empty")


@dataclass(frozen=True, slots=True)
class CodexPromptAudit:
    item_count: int
    prompt_sha256: str
    has_memory: bool
    has_target_skill: bool
    has_user_agent_skills: bool
    has_codex_system_skills: bool
    skill_inventory: tuple[tuple[str, str], ...] = ()
    system_skills: tuple[tuple[str, str], ...] = ()
    unexpected_skills: tuple[tuple[str, str], ...] = ()
    target_skill_count: int = 0
    target_skill_locator_matches: bool = False
    developer_instructions_exact: bool = True

    @property
    def passed(self) -> bool:
        return (
            self.has_target_skill
            and self.target_skill_count == 1
            and self.target_skill_locator_matches
            and self.developer_instructions_exact
            and not self.has_memory
            and not self.unexpected_skills
        )


@dataclass(frozen=True, slots=True)
class CodexEnvironmentAudit:
    home: str
    codex_home: str
    home_entries: tuple[str, ...]
    codex_home_entries: tuple[str, ...]
    auth_is_symlink: bool
    auth_target: str
    expected_auth_target: str
    auth_install_mode: str = "symlink"
    auth_sha256: str = ""
    expected_auth_sha256: str = ""
    auth_same_file_as_source: bool = True
    expected_broker_environment_keys: tuple[str, ...] = tuple(
        sorted(_BROKER_POSIX_MODEL_ENV_NAMES)
    )
    broker_environment_keys: tuple[str, ...] = ()
    unexpected_sensitive_environment_keys: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        if self.auth_install_mode == "symlink":
            auth_install_passed = (
                self.auth_is_symlink
                and self.auth_target == self.expected_auth_target
            )
        elif self.auth_install_mode == "copy":
            auth_install_passed = (
                not self.auth_is_symlink
                and not self.auth_same_file_as_source
                and bool(self.auth_sha256)
                and self.auth_sha256 == self.expected_auth_sha256
            )
        else:
            auth_install_passed = False
        return (
            not self.home_entries
            and self.codex_home_entries == ("auth.json",)
            and auth_install_passed
            and not self.unexpected_sensitive_environment_keys
            and self.broker_environment_keys
            in ((), self.expected_broker_environment_keys)
        )


@dataclass(frozen=True, slots=True)
class CodexIsolationAudit:
    prompt_audit_environment: CodexEnvironmentAudit
    execution_environment: CodexEnvironmentAudit

    @property
    def passed(self) -> bool:
        audit = self.prompt_audit_environment
        execution = self.execution_environment
        return (
            audit.passed
            and execution.passed
            and audit.home != execution.home
            and audit.codex_home != execution.codex_home
        )


@dataclass(frozen=True, slots=True)
class CodexSessionAudit:
    thread_started_count: int
    turn_started_count: int
    turn_completed_count: int
    thread_ids: tuple[str, ...]
    collab_call_count: int
    file_change_count: int
    command_started_count: int
    command_completed_count: int
    incomplete_command_count: int
    unexpected_item_types: tuple[str, ...]
    invalid_json_line_count: int

    @property
    def passed(self) -> bool:
        return (
            self.thread_started_count == 1
            and self.turn_started_count == 1
            and self.turn_completed_count == 1
            and len(self.thread_ids) == 1
            and bool(self.thread_ids[0])
            and self.collab_call_count == 0
            and self.file_change_count == 0
            and self.incomplete_command_count == 0
            and not self.unexpected_item_types
            and self.invalid_json_line_count == 0
        )


@dataclass(frozen=True, slots=True)
class CodexCommandRecord:
    command: str
    exit_code: int | None
    status: str
    aggregated_output: str
    argv: tuple[str, ...]
    has_shell_operators: bool
    parse_error: str = ""
    parser_kind: str = ""

    @property
    def succeeded(self) -> bool:
        return self.exit_code == 0 and self.status == "completed" and not self.parse_error


@dataclass(frozen=True, slots=True)
class CodexCommandFacts:
    commands: tuple[str, ...]
    inline_python_commands: tuple[str, ...]
    direct_waapi_client_commands: tuple[str, ...]
    write_like_commands: tuple[str, ...]
    gateway_commands: tuple[str, ...]
    discovery_commands: tuple[str, ...]
    skill_read: bool
    gateway_before_discovery: bool
    command_records: tuple[CodexCommandRecord, ...] = ()
    gateway_attempt_commands: tuple[str, ...] = ()
    gateway_subcommands: tuple[str, ...] = ()
    gateway_results: tuple[Mapping[str, Any], ...] = ()
    gateway_evidence_apis: tuple[str, ...] = ()
    allowed_read_commands: tuple[str, ...] = ()
    skill_read_files: tuple[str, ...] = ()
    unexpected_commands: tuple[str, ...] = ()
    non_gateway_unexpected_commands: tuple[str, ...] = ()


def recoverable_preprocess_attempt_indexes(
    records: Sequence[CodexCommandRecord],
) -> tuple[int, ...]:
    """Return exact Windows commands retried after process creation failed.

    The next record must preserve the complete command and argv.  The failed
    record never entered PowerShell; the later record still receives all normal
    Skill-read, Gateway, Broker, and lifecycle validation.
    """

    return tuple(
        index
        for index, record in enumerate(records[:-1])
        if (
            getattr(record, "status", "") == "failed"
            and getattr(record, "exit_code", None) == -1
            and not getattr(record, "parse_error", "")
            and not getattr(record, "has_shell_operators", False)
            and getattr(record, "parser_kind", "")
            == _WINDOWS_POWERSHELL_CORE_PARSER_KIND
            and getattr(record, "command", "")
            == getattr(records[index + 1], "command", "")
            and getattr(record, "argv", ()) == getattr(records[index + 1], "argv", ())
            and getattr(records[index + 1], "exit_code", None) in {0, 2}
            and not getattr(records[index + 1], "aggregated_output", "").startswith(
                "execution error: Io("
            )
            and getattr(record, "aggregated_output", "").startswith(
                "execution error: Io("
            )
            and "windows sandbox: CreateProcessAsUserW failed: 267"
            in getattr(record, "aggregated_output", "")
        )
    )


@dataclass(frozen=True, slots=True)
class CodexRunResult:
    command: tuple[str, ...]
    exit_status: int
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool
    thread_id: str
    final_response: str
    usage: Mapping[str, int]
    event_count: int
    collab_call_count: int
    file_change_count: int
    prompt_audit: CodexPromptAudit
    isolation_audit: CodexIsolationAudit
    session_audit: CodexSessionAudit
    command_facts: CodexCommandFacts
    created_files: tuple[str, ...]
    modified_files: tuple[str, ...]
    deleted_files: tuple[str, ...]
    created_source_files: tuple[str, ...]
    modified_source_files: tuple[str, ...]
    deleted_source_files: tuple[str, ...]
    skill_tree_sha256_before: str
    skill_tree_sha256_after: str
    skill_tree_unchanged: bool

    def facts_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop("stdout", None)
        payload.pop("stderr", None)
        payload["prompt_audit"]["passed"] = self.prompt_audit.passed
        payload["isolation_audit"]["passed"] = self.isolation_audit.passed
        payload["session_audit"]["passed"] = self.session_audit.passed
        return payload


@dataclass(frozen=True, slots=True)
class CodexInfrastructureFailure:
    """A terminal Codex CLI failure proven to precede every agent action."""

    category: str
    message: str
    turn_failed: bool
    timed_out: bool
    agent_item_event_count: int


class CodexInfrastructureError(CodexHarnessError):
    """Raised for CLI/service failures that are not evidence about the Skill."""

    def __init__(self, failure: CodexInfrastructureFailure, result: CodexRunResult) -> None:
        self.failure = failure
        self.result = result
        super().__init__(f"Codex CLI infrastructure failure ({failure.category}): {failure.message}")


@dataclass(frozen=True, slots=True)
class CodexHarnessConfig:
    workspace: Path
    skill_source: Path
    codex_binary: Path = field(default_factory=discover_codex_binary)
    disabled_user_skill_paths: tuple[Path, ...] = field(
        default_factory=lambda: (
            discover_windows_user_skill_paths(platform_name="nt")
            if os.name == "nt"
            else ()
        )
    )
    windows_powershell_core_host: WindowsPowerShellCoreHost | None = None
    auth_json: Path = DEFAULT_AUTH_JSON
    model: str = DEFAULT_MODEL
    reasoning_effort: str = DEFAULT_REASONING_EFFORT
    service_tier: str = DEFAULT_SERVICE_TIER
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    expected_gateway_subcommands: tuple[str, ...] = ()
    expected_wwise_version: str = ""
    sandbox_mode: str = "workspace-write"
    allow_output_write: bool = True
    network_access: bool = True
    expected_gateway_errors: tuple[CodexGatewayErrorExpectation, ...] = ()
    developer_instructions: str = ""

    def __post_init__(self) -> None:
        normalized_skill_paths = tuple(
            Path(path).expanduser().resolve(strict=False)
            for path in self.disabled_user_skill_paths
        )
        if len(normalized_skill_paths) != len(set(normalized_skill_paths)) or any(
            not path.is_absolute() or path.name != "SKILL.md"
            for path in normalized_skill_paths
        ):
            raise ValueError(
                "CodexHarnessConfig.disabled_user_skill_paths must contain "
                "unique absolute SKILL.md paths"
            )
        object.__setattr__(
            self,
            "disabled_user_skill_paths",
            normalized_skill_paths,
        )
        if self.developer_instructions and (
            self.developer_instructions != self.developer_instructions.strip()
            or "\x00" in self.developer_instructions
            or len(self.developer_instructions.encode("utf-8")) > 2048
        ):
            raise ValueError(
                "CodexHarnessConfig.developer_instructions must be trimmed, NUL-free, "
                "and at most 2048 UTF-8 bytes"
            )
        commands = tuple(expectation.command for expectation in self.expected_gateway_errors)
        if len(commands) != len(set(commands)):
            raise ValueError("CodexHarnessConfig.expected_gateway_errors commands must be unique")
        expected = frozenset(self.expected_gateway_subcommands)
        if expected and any(command not in expected for command in commands):
            raise ValueError(
                "CodexHarnessConfig.expected_gateway_errors must name expected gateway subcommands"
            )


class CodexCliHarness:
    """Run one fresh Codex CLI process with no prior memory or user configuration."""

    def __init__(self, config: CodexHarnessConfig) -> None:
        self.config = config
        self._windows_powershell_core_host: WindowsPowerShellCoreHost | None = None

    @property
    def windows_powershell_core_host(self) -> WindowsPowerShellCoreHost | None:
        return self._windows_powershell_core_host

    def verify(self) -> None:
        binary = self.config.codex_binary.expanduser()
        auth = self.config.auth_json.expanduser()
        workspace = self.config.workspace.expanduser().resolve(strict=True)
        skill_source = self.config.skill_source.expanduser().resolve(strict=True)
        skills_dir = workspace / ".agents" / "skills"
        if not binary.is_file() or not os.access(binary, os.X_OK):
            raise CodexHarnessError(f"Codex binary is missing or not executable: {binary}")
        if not auth.is_file():
            raise CodexHarnessError(f"Codex auth file is missing: {auth}")
        if _is_windows():
            enforce_windows_console_utf8()
            discovered_host = discover_windows_powershell_core(
                environment=os.environ,
                platform_name="nt",
            )
            sealed_host = self.config.windows_powershell_core_host
            if (
                sealed_host is not None
                and powershell_core_host_fingerprint(discovered_host)
                != powershell_core_host_fingerprint(sealed_host)
            ):
                raise CodexHarnessError(
                    "selected PowerShell Core host differs from the campaign-sealed host"
                )
            self._windows_powershell_core_host = sealed_host or discovered_host
        else:
            if self.config.windows_powershell_core_host is not None:
                raise CodexHarnessError(
                    "PowerShell Core host attestation is valid only for native Windows"
                )
            self._windows_powershell_core_host = None
        verify_workspace_skill_install(workspace, skill_source)
        installed_skills = tuple(sorted(path.name for path in skills_dir.iterdir()))
        if installed_skills != ("waapi-skill",):
            raise CodexHarnessError(
                f"Agent workspace must install only waapi-skill; found: {', '.join(installed_skills) or '<none>'}"
            )

    def run(
        self,
        prompt: str,
        *,
        output_dir: Path,
        extra_env: Mapping[str, str] | None = None,
    ) -> CodexRunResult:
        self.verify()
        output_dir = output_dir.expanduser().resolve(strict=False)
        output_dir.mkdir(parents=True, exist_ok=True)
        before_workspace = snapshot_workspace(self.config.workspace)
        before_outputs = snapshot_workspace(output_dir)
        before_skill = snapshot_workspace(
            self.config.skill_source,
            exclude_names=WORKSPACE_SKILL_EXCLUDED_NAMES,
        )
        skill_tree_sha256_before = snapshot_tree_hash(before_skill)

        with isolated_codex_environment(self.config.auth_json, extra_env=extra_env) as audit_env:
            audit_env = codex_process_environment(
                self.config.codex_binary,
                audit_env,
                powershell_core_host=self._windows_powershell_core_host,
            )
            prompt_environment = inspect_isolated_environment(audit_env, auth_json=self.config.auth_json)
            if not prompt_environment.passed:
                raise CodexHarnessError(f"Prompt audit environment is not pristine: {prompt_environment}")
            audit = self.audit_prompt(prompt, env=audit_env)
            if not audit.passed:
                raise CodexHarnessError(f"Codex prompt isolation audit failed: {audit}")
        if snapshot_workspace(self.config.workspace) != before_workspace:
            raise CodexHarnessError("codex debug prompt-input modified the isolated agent workspace")
        if snapshot_workspace(output_dir) != before_outputs:
            raise CodexHarnessError("codex debug prompt-input modified the evaluation output directory")
        if snapshot_tree_hash(
            snapshot_workspace(
                self.config.skill_source,
                exclude_names=WORKSPACE_SKILL_EXCLUDED_NAMES,
            )
        ) != skill_tree_sha256_before:
            raise CodexHarnessError("codex debug prompt-input modified the target Skill tree")
        with isolated_codex_environment(self.config.auth_json, extra_env=extra_env) as exec_env:
            exec_env = codex_process_environment(
                self.config.codex_binary,
                exec_env,
                powershell_core_host=self._windows_powershell_core_host,
            )
            execution_environment = inspect_isolated_environment(exec_env, auth_json=self.config.auth_json)
            if not execution_environment.passed:
                raise CodexHarnessError(f"Execution environment is not pristine: {execution_environment}")
            command = build_exec_command(self.config, prompt=prompt, writable_dir=output_dir)
            completed = run_process(command, cwd=self.config.workspace, env=exec_env, timeout=self.config.timeout_seconds)

        return _finalize_codex_run(
            config=self.config,
            command=command,
            completed=completed,
            output_dir=output_dir,
            prompt_audit=audit,
            prompt_environment=prompt_environment,
            execution_environment=execution_environment,
            before_workspace=before_workspace,
            before_outputs=before_outputs,
            skill_tree_sha256_before=skill_tree_sha256_before,
            windows_powershell_core_host=self._windows_powershell_core_host,
        )

    def audit_prompt(self, prompt: str, *, env: Mapping[str, str]) -> CodexPromptAudit:
        command = build_prompt_audit_command(self.config, prompt=prompt)
        completed: ProcessResult | None = None
        for attempt in range(1, PROMPT_AUDIT_MAX_ATTEMPTS + 1):
            completed = run_process(
                command,
                cwd=self.config.workspace,
                env=env,
                timeout=PROMPT_AUDIT_TIMEOUT_SECONDS,
            )
            if completed.exit_status == 0:
                break
            retryable_timeout = completed.exit_status == 124 and completed.timed_out
            if not retryable_timeout or attempt == PROMPT_AUDIT_MAX_ATTEMPTS:
                raise CodexHarnessError(
                    "codex debug prompt-input failed "
                    f"after {attempt} attempt(s) with {completed.exit_status}: "
                    f"{completed.stderr.strip()}"
                )
        assert completed is not None
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise CodexHarnessError("codex debug prompt-input did not return JSON") from exc
        return audit_prompt_input_payload(
            payload,
            target_skill_source=workspace_skill_install_path(self.config.workspace),
            system_skill_root=Path(env["CODEX_HOME"]) / "skills" / ".system",
            expected_developer_instructions=self.config.developer_instructions,
        )


class CodexCliTask:
    """One scenario-scoped Codex thread in one disposable state directory.

    The initial turn uses a non-ephemeral ``codex exec`` so the CLI can persist
    the thread inside the task's private ``CODEX_HOME``.  Every later turn
    resumes the exact thread id emitted by that initial process.  The task is
    deliberately one-shot: leaving the context destroys both ``HOME`` and
    ``CODEX_HOME`` and the instance cannot be re-entered.
    """

    def __init__(
        self,
        config: CodexHarnessConfig,
        *,
        extra_env: Mapping[str, str] | None = None,
    ) -> None:
        self.config = config
        self._harness = CodexCliHarness(config)
        self._extra_env = dict(extra_env or {})
        self._exit_stack: ExitStack | None = None
        self._execution_env: dict[str, str] | None = None
        self._execution_environment: CodexEnvironmentAudit | None = None
        self._windows_powershell_core_host: WindowsPowerShellCoreHost | None = None
        self._thread_id = ""
        self._turn_results: list[CodexRunResult] = []
        self._state = "new"
        self._failed = False

    @property
    def thread_id(self) -> str:
        return self._thread_id

    @property
    def turn_results(self) -> tuple[CodexRunResult, ...]:
        return tuple(self._turn_results)

    @property
    def execution_environment(self) -> CodexEnvironmentAudit:
        if self._execution_environment is None:
            raise CodexHarnessError("CodexCliTask has not entered its isolated environment")
        return self._execution_environment

    @property
    def windows_powershell_core_host(self) -> WindowsPowerShellCoreHost | None:
        """Return the task's actually attested native Windows shell host."""

        return self._windows_powershell_core_host

    def __enter__(self) -> CodexCliTask:
        if self._state != "new":
            raise CodexHarnessError("CodexCliTask is one-shot and cannot be re-entered")
        self._harness.verify()
        self._windows_powershell_core_host = self._harness.windows_powershell_core_host
        stack = ExitStack()
        try:
            execution_env = stack.enter_context(
                isolated_codex_environment(self.config.auth_json, extra_env=self._extra_env)
            )
            execution_env = codex_process_environment(
                self.config.codex_binary,
                execution_env,
                powershell_core_host=self._windows_powershell_core_host,
            )
            execution_environment = inspect_isolated_environment(
                execution_env,
                auth_json=self.config.auth_json,
            )
            if not execution_environment.passed:
                raise CodexHarnessError(
                    f"Execution environment is not pristine: {execution_environment}"
                )
        except BaseException:
            stack.close()
            self._state = "closed"
            raise
        self._exit_stack = stack
        self._execution_env = execution_env
        self._execution_environment = execution_environment
        self._state = "active"
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        stack = self._exit_stack
        try:
            if stack is not None:
                stack.__exit__(exc_type, exc, traceback)
        finally:
            self._execution_env = None
            self._exit_stack = None
            self._windows_powershell_core_host = None
            self._state = "closed"

    def run_initial(self, prompt: str, *, output_dir: Path) -> CodexRunResult:
        """Start the task's only thread and capture its exact emitted id."""

        self._require_active()
        if self._turn_results or self._thread_id:
            raise CodexHarnessError("CodexCliTask initial turn has already run")
        output_dir = output_dir.expanduser().resolve(strict=False)
        command = build_task_exec_command(self.config, prompt=prompt, writable_dir=output_dir)
        result = self._record_turn(prompt, output_dir=output_dir, command=command)
        if not result.thread_id:
            self._failed = True
            raise CodexHarnessError("CodexCliTask initial turn did not emit exactly one thread id")
        self._thread_id = result.thread_id
        return result

    def run_followup(self, prompt: str, *, output_dir: Path) -> CodexRunResult:
        """Resume the task's exact initial thread for one additional turn."""

        self._require_active()
        if not self._thread_id:
            raise CodexHarnessError("CodexCliTask follow-up requires a successful initial turn")
        expected_thread_id = self._thread_id
        output_dir = output_dir.expanduser().resolve(strict=False)
        command = build_task_resume_command(
            self.config,
            thread_id=expected_thread_id,
            prompt=prompt,
            writable_dir=output_dir,
        )
        result = self._record_turn(prompt, output_dir=output_dir, command=command)
        if result.thread_id != expected_thread_id:
            self._failed = True
            raise CodexHarnessError(
                "CodexCliTask resumed thread id mismatch: "
                f"expected {expected_thread_id!r}, observed {result.thread_id!r}"
            )
        return result

    def _require_active(self) -> None:
        if self._state != "active" or self._execution_env is None:
            raise CodexHarnessError("CodexCliTask must be used inside its active context")
        if self._failed:
            raise CodexHarnessError("CodexCliTask is terminal after a harness failure")

    def _record_turn(
        self,
        prompt: str,
        *,
        output_dir: Path,
        command: Sequence[str],
    ) -> CodexRunResult:
        try:
            result = self._run_turn(prompt, output_dir=output_dir, command=command)
        except CodexInfrastructureError as exc:
            self._turn_results.append(exc.result)
            self._failed = True
            raise
        except BaseException:
            self._failed = True
            raise
        self._turn_results.append(result)
        return result

    def _run_turn(
        self,
        prompt: str,
        *,
        output_dir: Path,
        command: Sequence[str],
    ) -> CodexRunResult:
        execution_env = self._execution_env
        execution_environment = self._execution_environment
        if execution_env is None or execution_environment is None:
            raise CodexHarnessError("CodexCliTask execution environment is unavailable")

        output_dir = output_dir.expanduser().resolve(strict=False)
        output_dir.mkdir(parents=True, exist_ok=True)
        before_workspace = snapshot_workspace(self.config.workspace)
        before_outputs = snapshot_workspace(output_dir)
        before_skill = snapshot_workspace(
            self.config.skill_source,
            exclude_names=WORKSPACE_SKILL_EXCLUDED_NAMES,
        )
        skill_tree_sha256_before = snapshot_tree_hash(before_skill)

        with isolated_codex_environment(self.config.auth_json, extra_env=self._extra_env) as audit_env:
            audit_env = codex_process_environment(
                self.config.codex_binary,
                audit_env,
                powershell_core_host=self._windows_powershell_core_host,
            )
            prompt_environment = inspect_isolated_environment(
                audit_env,
                auth_json=self.config.auth_json,
            )
            if not prompt_environment.passed:
                raise CodexHarnessError(
                    f"Prompt audit environment is not pristine: {prompt_environment}"
                )
            audit = self._harness.audit_prompt(prompt, env=audit_env)
            if not audit.passed:
                raise CodexHarnessError(f"Codex prompt isolation audit failed: {audit}")
        if snapshot_workspace(self.config.workspace) != before_workspace:
            raise CodexHarnessError("codex debug prompt-input modified the isolated agent workspace")
        if snapshot_workspace(output_dir) != before_outputs:
            raise CodexHarnessError("codex debug prompt-input modified the evaluation output directory")
        if snapshot_tree_hash(
            snapshot_workspace(
                self.config.skill_source,
                exclude_names=WORKSPACE_SKILL_EXCLUDED_NAMES,
            )
        ) != skill_tree_sha256_before:
            raise CodexHarnessError("codex debug prompt-input modified the target Skill tree")

        completed = run_process(
            command,
            cwd=self.config.workspace,
            env=execution_env,
            timeout=self.config.timeout_seconds,
        )
        return _finalize_codex_run(
            config=self.config,
            command=command,
            completed=completed,
            output_dir=output_dir,
            prompt_audit=audit,
            prompt_environment=prompt_environment,
            execution_environment=execution_environment,
            before_workspace=before_workspace,
            before_outputs=before_outputs,
            skill_tree_sha256_before=skill_tree_sha256_before,
            windows_powershell_core_host=self._windows_powershell_core_host,
        )


@dataclass(frozen=True, slots=True)
class ProcessResult:
    exit_status: int
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool = False


def _finalize_codex_run(
    *,
    config: CodexHarnessConfig,
    command: Sequence[str],
    completed: ProcessResult,
    output_dir: Path,
    prompt_audit: CodexPromptAudit,
    prompt_environment: CodexEnvironmentAudit,
    execution_environment: CodexEnvironmentAudit,
    before_workspace: Mapping[str, str],
    before_outputs: Mapping[str, str],
    skill_tree_sha256_before: str,
    windows_powershell_core_host: WindowsPowerShellCoreHost | None = None,
) -> CodexRunResult:
    """Build one immutable turn result using the shared V2/V3 audit logic."""

    isolation_audit = CodexIsolationAudit(
        prompt_audit_environment=prompt_environment,
        execution_environment=execution_environment,
    )
    after_workspace = snapshot_workspace(config.workspace)
    after_outputs = snapshot_workspace(output_dir)
    after_skill = snapshot_workspace(
        config.skill_source,
        exclude_names=WORKSPACE_SKILL_EXCLUDED_NAMES,
    )
    skill_tree_sha256_after = snapshot_tree_hash(after_skill)
    workspace_created, workspace_modified = workspace_changes(before_workspace, after_workspace)
    output_created, output_modified = workspace_changes(before_outputs, after_outputs)
    workspace_deleted = tuple(sorted(set(before_workspace) - set(after_workspace)))
    output_deleted = tuple(sorted(set(before_outputs) - set(after_outputs)))
    created = tuple(workspace_created) + tuple(f"outputs/{path}" for path in output_created)
    modified = tuple(workspace_modified) + tuple(f"outputs/{path}" for path in output_modified)
    deleted = tuple(workspace_deleted) + tuple(f"outputs/{path}" for path in output_deleted)
    events = parse_jsonl_events(completed.stdout)
    command_records = completed_command_records(
        events,
        windows_powershell_core_host=windows_powershell_core_host,
    )
    command_facts = classify_task_commands(
        command_records,
        workspace=config.workspace,
        skill_source=config.skill_source,
        expected_gateway_subcommands=config.expected_gateway_subcommands,
        expected_gateway_errors=config.expected_gateway_errors,
        expected_wwise_version=config.expected_wwise_version,
    )
    final_response = final_agent_message(events)
    usage = turn_usage(events)
    session_audit = audit_session_events(
        events,
        invalid_json_line_count=count_invalid_jsonl_lines(completed.stdout),
    )
    thread_ids = session_audit.thread_ids
    created_source_files = tuple(path for path in created if Path(path).suffix.lower() in SOURCE_SUFFIXES)
    modified_source_files = tuple(path for path in modified if Path(path).suffix.lower() in SOURCE_SUFFIXES)
    deleted_source_files = tuple(path for path in deleted if Path(path).suffix.lower() in SOURCE_SUFFIXES)
    result = CodexRunResult(
        command=tuple(command),
        exit_status=completed.exit_status,
        stdout=completed.stdout,
        stderr=completed.stderr,
        duration_seconds=completed.duration_seconds,
        timed_out=completed.timed_out,
        thread_id=thread_ids[0] if len(thread_ids) == 1 else "",
        final_response=final_response,
        usage=usage,
        event_count=len(events),
        collab_call_count=session_audit.collab_call_count,
        file_change_count=session_audit.file_change_count,
        prompt_audit=prompt_audit,
        isolation_audit=isolation_audit,
        session_audit=session_audit,
        command_facts=command_facts,
        created_files=created,
        modified_files=modified,
        deleted_files=deleted,
        created_source_files=created_source_files,
        modified_source_files=modified_source_files,
        deleted_source_files=deleted_source_files,
        skill_tree_sha256_before=skill_tree_sha256_before,
        skill_tree_sha256_after=skill_tree_sha256_after,
        skill_tree_unchanged=skill_tree_sha256_before == skill_tree_sha256_after,
    )
    infrastructure_failure = classify_codex_infrastructure_failure(
        events,
        stderr=completed.stderr,
        timed_out=completed.timed_out,
    )
    if infrastructure_failure is not None:
        raise CodexInfrastructureError(infrastructure_failure, result)
    return result


def run_process(
    command: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    timeout: float,
) -> ProcessResult:
    """Run a process in its own group so timeouts also stop internal agents."""

    started = time.monotonic()
    process_group_options = subprocess_process_group_options()
    process = subprocess.Popen(
        [str(part) for part in command],
        cwd=str(cwd),
        env=dict(env),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="strict",
        **process_group_options,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
        return ProcessResult(
            exit_status=int(process.returncode),
            stdout=stdout or "",
            stderr=stderr or "",
            duration_seconds=round(time.monotonic() - started, 6),
        )
    except subprocess.TimeoutExpired:
        try:
            stdout, stderr = terminate_and_reap_process(process)
        except BaseException:
            # If cancellation interrupts the graceful wait, finish the hard
            # cleanup but preserve and re-raise that cancellation unchanged.
            try:
                force_kill_and_reap_process(process)
            except BaseException:
                pass
            raise
        return ProcessResult(
            exit_status=124,
            stdout=stdout or "",
            stderr=stderr or "",
            duration_seconds=round(time.monotonic() - started, 6),
            timed_out=True,
        )
    except BaseException:
        # KeyboardInterrupt and cancellation must not orphan a Codex process or
        # any command it spawned in the new session/process group.
        try:
            terminate_and_reap_process(process)
        except BaseException:
            try:
                force_kill_and_reap_process(process)
            except BaseException:
                pass
        raise


def terminate_and_reap_process(
    process: subprocess.Popen[str],
    *,
    grace_seconds: float = 5.0,
    platform_name: str | None = None,
) -> tuple[str, str]:
    """Terminate a process group, wait briefly, then kill and reap if needed."""

    if process.poll() is None:
        try:
            terminate_process_group(process, platform_name=platform_name)
        except CodexHarnessError:
            # Native taskkill cannot always stop a console process tree without
            # /F (notably while a child remains active).  Escalate through the
            # same tree-scoped primitive instead of leaking the descendants.
            if not _is_windows(platform_name):
                raise
            return force_kill_and_reap_process(process, platform_name=platform_name)
    try:
        return process.communicate(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        return force_kill_and_reap_process(process, platform_name=platform_name)


def force_kill_and_reap_process(
    process: subprocess.Popen[str],
    *,
    platform_name: str | None = None,
) -> tuple[str, str]:
    """Best-effort hard stop followed by an unbounded pipe/process reap."""

    if process.poll() is None:
        kill_process_group(process, platform_name=platform_name)
    if not _is_windows(platform_name):
        return process.communicate()
    try:
        return process.communicate(timeout=WINDOWS_HARD_REAP_SECONDS)
    except subprocess.TimeoutExpired as exc:
        raise CodexHarnessError(
            "native Windows process-tree cleanup left descendant pipes open "
            "after the forced kill"
        ) from exc


def terminate_process_group(
    process: subprocess.Popen[str],
    *,
    platform_name: str | None = None,
) -> None:
    """Request graceful termination without evaluating POSIX-only signals on Windows."""

    if _is_windows(platform_name):
        taskkill_process_tree(process, force=False)
        return
    signal_posix_process_group(process, signal.SIGTERM)


def kill_process_group(
    process: subprocess.Popen[str],
    *,
    platform_name: str | None = None,
) -> None:
    """Hard-stop a process without requiring ``signal.SIGKILL`` on Windows."""

    if _is_windows(platform_name):
        taskkill_process_tree(process, force=True)
        return
    signal_posix_process_group(process, signal.SIGKILL)


def signal_posix_process_group(
    process: subprocess.Popen[str],
    requested_signal: signal.Signals,
) -> None:
    """Signal a POSIX process group without failing on an exit race."""

    try:
        os.killpg(process.pid, requested_signal)
    except ProcessLookupError:
        pass


def subprocess_process_group_options(
    *,
    platform_name: str | None = None,
) -> dict[str, Any]:
    """Return the native Popen boundary needed for descendant cleanup."""

    if not _is_windows(platform_name):
        return {"start_new_session": True}
    creation_flag = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", None)
    if not isinstance(creation_flag, int) or creation_flag <= 0:
        raise CodexHarnessError(
            "native Windows Codex cleanup requires CREATE_NEW_PROCESS_GROUP"
        )
    return {"creationflags": creation_flag}


def taskkill_process_tree(
    process: subprocess.Popen[str],
    *,
    force: bool,
) -> None:
    """Terminate one native-Windows process tree through the system utility."""

    if process.poll() is not None:
        return
    executable = windows_system_executable("taskkill.exe")
    command = [executable, "/PID", str(process.pid), "/T"]
    if force:
        command.append("/F")
    try:
        completed = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=15.0,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CodexHarnessError(
            f"native Windows process-tree cleanup failed to run taskkill.exe: {exc}"
        ) from exc
    if completed.returncode == 0:
        return
    # ``taskkill /T`` can report a partial error for a console helper that is
    # already disappearing after it successfully terminates the tracked Codex
    # parent.  Reap that exit race here; the caller still requires
    # ``communicate()`` to close every inherited pipe and fails if a descendant
    # keeps the tree alive.
    for _attempt in range(5):
        process.poll()
        if process.returncode is not None:
            return
        time.sleep(0.05)
    output = f"{completed.stdout or ''}\n{completed.stderr or ''}".casefold()
    not_found = completed.returncode == 128 or any(
        marker in output
        for marker in (
            "not found",
            "no running instance",
            "not running",
            "找不到",
        )
    )
    if not_found:
        process.poll()
        if process.returncode is not None:
            return
    raise CodexHarnessError(
        "native Windows taskkill.exe could not terminate the Codex process tree: "
        f"exit={completed.returncode} output={(completed.stdout or '') + (completed.stderr or '')!r}"
    )


def windows_system_executable(
    executable_name: str,
    *,
    environment: Mapping[str, str] | None = None,
    platform_name: str | None = None,
) -> str:
    """Resolve one fixed System32 executable without consulting ``PATH``."""

    if not _is_windows(platform_name):
        raise CodexHarnessError("Windows system executable requested on a non-Windows host")
    if executable_name != "taskkill.exe":
        raise CodexHarnessError("Windows cleanup permits only taskkill.exe")
    source = os.environ if environment is None else environment
    values = [
        str(value)
        for key, value in source.items()
        if str(key).casefold() == "systemroot"
    ]
    if len(values) != 1 or not values[0] or values[0] != values[0].strip():
        raise CodexHarnessError(
            "native Windows process-tree cleanup requires one absolute SystemRoot"
        )
    root = PureWindowsPath(values[0])
    if (
        not root.is_absolute()
        or root.drive.startswith("\\")
        or any(part in {".", ".."} for part in root.parts)
    ):
        raise CodexHarnessError("native Windows SystemRoot is not a local absolute path")
    candidate_text = str(root / "System32" / executable_name)

    # A simulated Windows unit test can prove the lexical contract on POSIX;
    # the real host additionally attests every filesystem component.
    if os.name != "nt":
        return candidate_text
    candidate = Path(candidate_text)
    for label, path, expect_directory in (
        ("SystemRoot", Path(str(root)), True),
        ("System32", Path(str(root / "System32")), True),
        (executable_name, candidate, False),
    ):
        try:
            metadata = path.lstat()
        except OSError as exc:
            raise CodexHarnessError(
                f"native Windows {label} is unavailable: {path}: {exc}"
            ) from exc
        if is_link_or_junction(path):
            raise CodexHarnessError(
                f"native Windows {label} must not be a link or reparse point: {path}"
            )
        expected_kind = stat.S_ISDIR if expect_directory else stat.S_ISREG
        if not expected_kind(metadata.st_mode):
            raise CodexHarnessError(
                f"native Windows {label} has the wrong filesystem kind: {path}"
            )
    return str(candidate)


@contextmanager
def isolated_codex_environment(
    auth_json: Path,
    *,
    extra_env: Mapping[str, str] | None = None,
    platform_name: str | None = None,
) -> Iterator[dict[str, str]]:
    """Create disposable HOME/CODEX_HOME directories for exactly one prompt."""

    auth = auth_json.expanduser().resolve(strict=True)
    normalized_extra_env = {str(key): str(value) for key, value in (extra_env or {}).items()}
    validate_extra_environment(normalized_extra_env, platform_name=platform_name)
    with tempfile.TemporaryDirectory(prefix="codex-waapi-home-") as home_text:
        with tempfile.TemporaryDirectory(prefix="codex-waapi-state-") as codex_home_text:
            codex_home = Path(codex_home_text)
            auth_install = codex_home / "auth.json"
            if _is_windows(platform_name):
                try:
                    shutil.copy2(auth, auth_install)
                except OSError as exc:
                    raise CodexHarnessError(
                        f"cannot copy auth.json into isolated Windows CODEX_HOME: {exc}"
                    ) from exc
                try:
                    if os.path.samefile(auth, auth_install):
                        raise CodexHarnessError(
                            "isolated Windows auth.json must not be a hardlink to the source"
                        )
                except OSError as exc:
                    raise CodexHarnessError(
                        f"cannot attest isolated Windows auth.json identity: {exc}"
                    ) from exc
            else:
                auth_install.symlink_to(auth)
            env = {
                str(key): str(value)
                for key, value in os.environ.items()
                if not is_protected_environment_key(str(key))
                and not is_evaluation_sensitive_environment_key(str(key))
            }
            env.update(normalized_extra_env)
            env.update(
                {
                    "HOME": home_text,
                    "CODEX_HOME": codex_home_text,
                    "PYTHONDONTWRITEBYTECODE": "1",
                }
            )
            if _is_windows(platform_name):
                # Native Codex resolves the user-level .agents tree through
                # USERPROFILE even when HOME and CODEX_HOME are disposable.
                # Bind all three identity roots to the same one-shot home so
                # user skills cannot appear between campaign scenarios.
                env["USERPROFILE"] = home_text
            yield env


def validate_extra_environment(
    extra_env: Mapping[str, str],
    *,
    platform_name: str | None = None,
) -> None:
    """Reject state escapes and permit only the runner-owned broker overlay.

    Ambient Wwise/WAAPI controls are always removed.  A trusted runner may add
    the complete broker connection overlay, but it may not expose live Wwise
    connection details, transaction state, or evidence directories directly to
    the evaluated model.
    """

    protected = sorted(key for key in extra_env if is_protected_environment_key(key))
    if protected:
        raise CodexHarnessError(
            "extra_env may not override isolated HOME/USERPROFILE/CODEX/XDG state: "
            + ", ".join(protected)
        )

    forbidden_sensitive = sorted(
        key
        for key in extra_env
        if is_evaluation_sensitive_environment_key(key)
        and key not in _BROKER_ALL_MODEL_ENV_NAMES
    )
    if forbidden_sensitive:
        raise CodexHarnessError(
            "extra_env may not expose Wwise/WAAPI state to evaluated Codex: "
            + ", ".join(forbidden_sensitive)
        )

    broker_names = _BROKER_ALL_MODEL_ENV_NAMES.intersection(extra_env)
    if not broker_names:
        return
    expected_overlay = (
        _BROKER_WINDOWS_OVERLAY_NAMES
        if _is_windows(platform_name)
        else _BROKER_POSIX_OVERLAY_NAMES
    )
    missing = sorted(expected_overlay.difference(extra_env))
    if missing:
        raise CodexHarnessError(
            "broker extra_env must provide the complete controlled overlay; missing: "
            + ", ".join(missing)
        )
    unexpected_platform_fields = sorted(
        (_BROKER_ALL_MODEL_ENV_NAMES | {"PATHEXT"}).intersection(extra_env)
        - expected_overlay
    )
    if unexpected_platform_fields:
        raise CodexHarnessError(
            "broker extra_env contains fields for the wrong platform: "
            + ", ".join(unexpected_platform_fields)
        )
    validate_broker_model_overlay(extra_env, platform_name=platform_name)


def validate_broker_model_overlay(
    extra_env: Mapping[str, str],
    *,
    platform_name: str | None = None,
) -> None:
    """Validate the small environment shape emitted by CodexGatewayBroker."""

    if extra_env["WAAPI_CODEX_GATEWAY_REQUIRED"] != "1":
        raise CodexHarnessError("broker extra_env must require the packaged gateway")

    transport = extra_env["WAAPI_CODEX_GATEWAY_BROKER_TRANSPORT"]
    endpoint = extra_env["WAAPI_CODEX_GATEWAY_BROKER_ENDPOINT"]
    if transport == "tcp":
        host, separator, port_text = endpoint.rpartition(":")
        try:
            port = int(port_text)
        except ValueError as exc:
            raise CodexHarnessError("broker TCP endpoint must use an integer port") from exc
        if separator != ":" or host != "127.0.0.1" or not 1 <= port <= 65535:
            raise CodexHarnessError("broker TCP endpoint must be loopback 127.0.0.1:<port>")
    elif transport == "unix" and not _is_windows(platform_name):
        endpoint_path = Path(endpoint)
        if not endpoint_path.is_absolute():
            raise CodexHarnessError("broker Unix endpoint must be an absolute path")
        try:
            endpoint_stat = endpoint_path.stat()
        except OSError as exc:
            raise CodexHarnessError("broker Unix endpoint must exist") from exc
        if not stat.S_ISSOCK(endpoint_stat.st_mode):
            raise CodexHarnessError("broker Unix endpoint must be a socket")
    else:
        raise CodexHarnessError("broker transport must be tcp or unix")

    token = extra_env["WAAPI_CODEX_GATEWAY_BROKER_TOKEN"]
    if len(token) < 32 or any(character.isspace() for character in token):
        raise CodexHarnessError("broker token must be a non-empty high-entropy value")

    if _is_windows(platform_name):
        _validate_windows_broker_model_overlay(extra_env)
        return

    bash_env = Path(extra_env["BASH_ENV"])
    if not bash_env.is_absolute() or bash_env.is_symlink():
        raise CodexHarnessError("broker BASH_ENV must be an absolute, non-symlink file")
    try:
        bash_env_stat = bash_env.stat()
    except OSError as exc:
        raise CodexHarnessError("broker BASH_ENV must exist") from exc
    if not stat.S_ISREG(bash_env_stat.st_mode) or stat.S_IMODE(bash_env_stat.st_mode) != stat.S_IRUSR:
        raise CodexHarnessError("broker BASH_ENV must be a private read-only file")
    if hasattr(os, "getuid") and bash_env_stat.st_uid != os.getuid():
        raise CodexHarnessError("broker BASH_ENV must be owned by the current user")

    path_entries = extra_env["PATH"].split(os.pathsep)
    if not path_entries or not path_entries[0]:
        raise CodexHarnessError("broker PATH must begin with the shim directory")
    try:
        shim_directory = Path(path_entries[0]).resolve(strict=True)
        bash_env_parent = bash_env.parent.resolve(strict=True)
    except OSError as exc:
        raise CodexHarnessError("broker shim directory must exist") from exc
    if shim_directory != bash_env_parent:
        raise CodexHarnessError("broker PATH and BASH_ENV must bind to the same shim directory")
    for executable_name in ("python", "python3"):
        executable = shim_directory / executable_name
        if executable.is_symlink() or not executable.is_file() or not os.access(executable, os.X_OK):
            raise CodexHarnessError(f"broker shim is missing or unsafe: {executable_name}")


def _validate_windows_broker_model_overlay(extra_env: Mapping[str, str]) -> None:
    """Validate native-Windows PowerShell shims without POSIX mode assumptions."""

    trusted_python = Path(extra_env[_BROKER_WINDOWS_TRUSTED_PYTHON_ENV])
    if (
        not trusted_python.is_absolute()
        or is_link_or_junction(trusted_python)
        or not trusted_python.is_file()
    ):
        raise CodexHarnessError(
            "Windows broker trusted Python must be an absolute, real regular file"
        )

    extensions = extra_env["PATHEXT"].split(";")
    if not extensions or any(not item or item != item.strip() for item in extensions):
        raise CodexHarnessError("Windows broker PATHEXT must be a closed semicolon list")
    normalized_extensions = tuple(item.casefold() for item in extensions)
    if normalized_extensions[0] != ".ps1":
        raise CodexHarnessError("Windows broker PATHEXT must begin with .PS1")
    if len(normalized_extensions) != len(set(normalized_extensions)):
        raise CodexHarnessError("Windows broker PATHEXT must not contain duplicates")

    path_entries = extra_env["PATH"].split(";")
    if not path_entries or not path_entries[0]:
        raise CodexHarnessError("Windows broker PATH must begin with the shim directory")
    shim_directory = Path(path_entries[0])
    if (
        not shim_directory.is_absolute()
        or is_link_or_junction(shim_directory)
        or not shim_directory.is_dir()
    ):
        raise CodexHarnessError("Windows broker shim directory must be absolute and real")
    for filename in ("broker_shim.py", "python.ps1", "python3.ps1"):
        shim = shim_directory / filename
        if is_link_or_junction(shim) or not shim.is_file():
            raise CodexHarnessError(f"Windows broker shim is missing or unsafe: {filename}")
    for legacy_filename in ("python.cmd", "python3.cmd"):
        legacy_wrapper = shim_directory / legacy_filename
        if legacy_wrapper.exists() or is_link_or_junction(legacy_wrapper):
            raise CodexHarnessError(
                f"Windows broker shim directory contains forbidden legacy wrapper: {legacy_filename}"
            )


def is_protected_environment_key(key: str) -> bool:
    normalized = key.upper()
    return normalized in _PROTECTED_ENV_EXACT or normalized.startswith("XDG_") or normalized.startswith("CODEX_")


def is_evaluation_sensitive_environment_key(key: str) -> bool:
    """Return whether a variable can reveal or control the live WAAPI test."""

    normalized = key.upper()
    return (
        normalized == "BASH_ENV"
        or normalized.startswith(("WWISE", "WAAPI"))
    )


def inspect_isolated_environment(
    env: Mapping[str, str],
    *,
    auth_json: Path,
    platform_name: str | None = None,
) -> CodexEnvironmentAudit:
    home = Path(env["HOME"]).expanduser().resolve(strict=True)
    codex_home = Path(env["CODEX_HOME"]).expanduser().resolve(strict=True)
    auth_link = codex_home / "auth.json"
    expected_auth = auth_json.expanduser().resolve(strict=True)
    auth_exists = auth_link.exists()
    auth_is_symlink = auth_link.is_symlink()
    auth_install_mode = "copy" if _is_windows(platform_name) else "symlink"
    auth_sha256 = _sha256_regular_file(auth_link) if auth_exists and not auth_is_symlink else ""
    expected_auth_sha256 = _sha256_regular_file(expected_auth)
    auth_same_file_as_source = False
    if auth_exists:
        try:
            auth_same_file_as_source = os.path.samefile(auth_link, expected_auth)
        except OSError:
            auth_same_file_as_source = True
    sensitive_environment_keys = {
        str(key) for key in env if is_evaluation_sensitive_environment_key(str(key))
    }
    expected_broker_environment_keys = tuple(
        sorted(
            _BROKER_WINDOWS_MODEL_ENV_NAMES
            if _is_windows(platform_name)
            else _BROKER_POSIX_MODEL_ENV_NAMES
        )
    )
    return CodexEnvironmentAudit(
        home=str(home),
        codex_home=str(codex_home),
        home_entries=tuple(sorted(path.name for path in home.iterdir())),
        codex_home_entries=tuple(sorted(path.name for path in codex_home.iterdir())),
        auth_is_symlink=auth_is_symlink,
        auth_target=str(auth_link.resolve(strict=True)) if auth_exists else "",
        expected_auth_target=str(expected_auth),
        auth_install_mode=auth_install_mode,
        auth_sha256=auth_sha256,
        expected_auth_sha256=expected_auth_sha256,
        auth_same_file_as_source=auth_same_file_as_source,
        expected_broker_environment_keys=expected_broker_environment_keys,
        broker_environment_keys=tuple(
            sorted(sensitive_environment_keys & _BROKER_ALL_MODEL_ENV_NAMES)
        ),
        unexpected_sensitive_environment_keys=tuple(
            sorted(sensitive_environment_keys - _BROKER_ALL_MODEL_ENV_NAMES)
        ),
    )


def build_prompt_audit_command(config: CodexHarnessConfig, *, prompt: str) -> list[str]:
    command = [
        str(config.codex_binary),
        "--disable",
        "memories",
    ]
    command.extend(_disabled_user_skill_config_argv(config.disabled_user_skill_paths))
    command.extend(_developer_instructions_config_argv(config.developer_instructions))
    command.extend(
        (
            "-c",
            f'model="{config.model}"',
            "-c",
            f'model_reasoning_effort="{config.reasoning_effort}"',
            "debug",
            "prompt-input",
            prompt,
        )
    )
    return command


def build_exec_command(config: CodexHarnessConfig, *, prompt: str, writable_dir: Path) -> list[str]:
    """Build the historical V2 one-process, ephemeral execution command."""

    command = _build_exec_prefix(config, writable_dir=writable_dir, ephemeral=True)
    command.append(prompt)
    return command


def build_task_exec_command(
    config: CodexHarnessConfig,
    *,
    prompt: str,
    writable_dir: Path,
) -> list[str]:
    """Build the non-ephemeral initial turn for a scenario-scoped task."""

    command = _build_exec_prefix(config, writable_dir=writable_dir, ephemeral=False)
    command.append(prompt)
    return command


def build_task_resume_command(
    config: CodexHarnessConfig,
    *,
    thread_id: str,
    prompt: str,
    writable_dir: Path,
) -> list[str]:
    """Build an exact-id resume turn; implicit ``--last`` is never allowed."""

    if not thread_id or not thread_id.strip() or thread_id == "--last":
        raise CodexHarnessError("scenario task resume requires an explicit thread id")
    command = _build_exec_prefix(config, writable_dir=writable_dir, ephemeral=False)
    command.extend(("resume", thread_id, prompt))
    return command


def _build_exec_prefix(
    config: CodexHarnessConfig,
    *,
    writable_dir: Path,
    ephemeral: bool,
) -> list[str]:
    if config.sandbox_mode not in {"read-only", "workspace-write"}:
        raise CodexHarnessError(f"unsupported semantic sandbox mode: {config.sandbox_mode}")
    command = [
        str(config.codex_binary),
        "exec",
    ]
    if ephemeral:
        command.append("--ephemeral")
    if _is_windows():
        command.extend(
            (
                "-c",
                "allow_login_shell=false",
                "-c",
                f'windows.sandbox="{WINDOWS_SEMANTIC_SANDBOX_MODE}"',
            )
        )
    command.extend(_disabled_user_skill_config_argv(config.disabled_user_skill_paths))
    command.extend(_developer_instructions_config_argv(config.developer_instructions))
    command.extend(
        [
            "--model",
            config.model,
            "-c",
            f'model_reasoning_effort="{config.reasoning_effort}"',
            "-c",
            f'service_tier="{config.service_tier}"',
            "-c",
            'approval_policy="never"',
            "-c",
            f"sandbox_workspace_write.network_access={'true' if config.network_access else 'false'}",
            "--disable",
            "memories",
            "--ignore-user-config",
            "--json",
            "--sandbox",
            config.sandbox_mode,
            "--skip-git-repo-check",
        ]
    )
    if config.allow_output_write:
        command.extend(("--add-dir", str(writable_dir)))
    command.extend(("-C", str(config.workspace)))
    return command


def _developer_instructions_config_argv(value: str) -> tuple[str, ...]:
    if not value:
        return ()
    return ("-c", f"developer_instructions={json.dumps(value)}")


def audit_prompt_input_payload(
    payload: Any,
    *,
    target_skill_source: Path | None = None,
    system_skill_root: Path | None = None,
    expected_developer_instructions: str = "",
) -> CodexPromptAudit:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    serialized_casefold = serialized.casefold()
    entries = prompt_skill_inventory(payload)
    skill_roots = prompt_skill_roots(payload)
    target_source = target_skill_source.expanduser().resolve(strict=False) if target_skill_source else None
    system_skills: list[tuple[str, str]] = []
    target_entries: list[tuple[str, str]] = []
    unexpected: list[tuple[str, str]] = []
    unexpected_resolved: list[str] = []
    for name, locator in entries:
        resolved_locator = expand_short_skill_locator(locator, roots=skill_roots)
        if is_codex_system_skill(
            resolved_locator,
            system_skill_root=system_skill_root,
        ):
            system_skills.append((name, locator))
            continue
        locator_matches = target_source is None or skill_locator_resolves_to(
            resolved_locator,
            target_source,
        )
        if name == "waapi-skill" and locator_matches:
            target_entries.append((name, locator))
        else:
            unexpected.append((name, locator))
            unexpected_resolved.append(resolved_locator)
    target_locator_matches = len(target_entries) == 1
    instruction_texts = prompt_instruction_texts(payload)
    return CodexPromptAudit(
        item_count=len(payload) if isinstance(payload, list) else 0,
        prompt_sha256=hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
        has_memory=any(marker.casefold() in serialized_casefold for marker in MEMORY_MARKERS),
        has_target_skill=bool(target_entries),
        has_user_agent_skills=any(
            local_locator_contains_parts(locator, (".agents", "skills"))
            for locator in unexpected_resolved
        ),
        has_codex_system_skills=bool(system_skills),
        skill_inventory=entries,
        system_skills=tuple(system_skills),
        unexpected_skills=tuple(unexpected),
        target_skill_count=len(target_entries),
        target_skill_locator_matches=target_locator_matches,
        developer_instructions_exact=(
            not expected_developer_instructions
            or instruction_texts.count(expected_developer_instructions) == 1
        ),
    )


def prompt_skill_inventory(payload: Any) -> tuple[tuple[str, str], ...]:
    entries: list[tuple[str, str]] = []
    for text in prompt_instruction_texts(payload):
        for match in _SKILL_LINE_RE.finditer(text):
            entries.append((match.group("name"), clean_skill_locator(match.group("locator"))))
        for match in _LEGACY_WORKSPACE_SKILL_RE.finditer(text):
            entries.append((match.group("name"), ""))
    # Structured inventories are evidence only when Codex placed them in an
    # instruction role.  A user message must never be able to self-attest that
    # the target Skill was injected.
    items = payload if isinstance(payload, list) else [payload]
    for item in items:
        if not isinstance(item, Mapping):
            continue
        if str(item.get("role") or "").lower() not in {"system", "developer"}:
            continue
        entries.extend(structured_skill_entries(item))
    return tuple(entries)


def prompt_instruction_texts(payload: Any) -> tuple[str, ...]:
    texts: list[str] = []
    items = payload if isinstance(payload, list) else [payload]
    for item in items:
        if not isinstance(item, Mapping):
            continue
        role = str(item.get("role") or "").lower()
        if role not in {"system", "developer"}:
            continue
        texts.extend(nested_text_values(item.get("content")))
    return tuple(texts)


def nested_text_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        values: list[str] = []
        for key, child in value.items():
            if key in {"text", "content"}:
                values.extend(nested_text_values(child))
        return values
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        values = []
        for child in value:
            values.extend(nested_text_values(child))
        return values
    return []


def structured_skill_entries(value: Any) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            if key in {"available_skills", "skills"} and isinstance(child, Sequence) and not isinstance(
                child, (str, bytes, bytearray)
            ):
                for item in child:
                    if not isinstance(item, Mapping) or not isinstance(item.get("name"), str):
                        continue
                    locator = next(
                        (
                            str(item[candidate])
                            for candidate in ("file", "path", "locator", "source")
                            if isinstance(item.get(candidate), str)
                        ),
                        "",
                    )
                    entries.append((str(item["name"]), clean_skill_locator(locator)))
            entries.extend(structured_skill_entries(child))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for child in value:
            entries.extend(structured_skill_entries(child))
    return entries


def clean_skill_locator(locator: str) -> str:
    return locator.strip().strip("`\"'")


def prompt_skill_roots(payload: Any) -> dict[str, str]:
    candidates: dict[str, set[str]] = {}
    for text in prompt_instruction_texts(payload):
        for match in _SKILL_ROOT_LINE_RE.finditer(text):
            alias = match.group("alias")
            root = clean_skill_locator(match.group("root"))
            if root:
                candidates.setdefault(alias, set()).add(root)
    return {
        alias: next(iter(roots))
        for alias, roots in candidates.items()
        if len(roots) == 1
    }


def expand_short_skill_locator(
    locator: str,
    *,
    roots: Mapping[str, str],
) -> str:
    match = _SKILL_ALIAS_LOCATOR_RE.fullmatch(locator)
    if match is None:
        return locator
    root = roots.get(match.group("alias"))
    relative = tuple(
        part
        for part in re.split(r"[/\\]", match.group("relative"))
        if part
    )
    if root is None or not relative or any(part in {".", ".."} for part in relative):
        return locator
    pure_root, _windows = _skill_locator_pure_path(root)
    if not pure_root.is_absolute():
        return locator
    return str(pure_root.joinpath(*relative))


def _skill_locator_pure_path(
    locator: str,
) -> tuple[PurePosixPath | PureWindowsPath, bool]:
    """Select a locator's owning lexical flavor without consulting the host."""

    windows = PureWindowsPath(locator)
    posix = PurePosixPath(locator)
    if windows.drive:
        return windows, True
    if posix.is_absolute():
        return posix, False
    if "\\" in locator:
        return windows, True
    return posix, False


def local_locator_contains_parts(
    locator: str,
    expected_parts: Sequence[str],
) -> bool:
    """Match path components using the locator's owning lexical semantics."""

    if not locator or not expected_parts:
        return False
    pure, windows = _skill_locator_pure_path(locator)
    parts = pure.parts
    width = len(expected_parts)
    if windows:
        comparable = tuple(part.casefold() for part in parts)
        expected = tuple(part.casefold() for part in expected_parts)
    else:
        comparable = parts
        expected = tuple(expected_parts)
    return any(
        comparable[index : index + width] == expected
        for index in range(len(comparable) - width + 1)
    )


def is_codex_system_skill(locator: str, *, system_skill_root: Path | None = None) -> bool:
    if not locator:
        return False
    candidate = Path(locator).expanduser()
    if system_skill_root is not None:
        root = system_skill_root.expanduser().resolve(strict=False)
        try:
            relative = candidate.resolve(strict=False).relative_to(root)
        except (OSError, ValueError):
            return False
        return len(relative.parts) >= 2 and relative.name.lower() == "skill.md"
    return local_locator_contains_parts(
        locator,
        (".codex", "skills", ".system"),
    )


def skill_locator_resolves_to(locator: str, target_skill_source: Path) -> bool:
    if not locator:
        return False
    candidate = Path(locator).expanduser()
    if candidate.name.lower() == "skill.md":
        candidate = candidate.parent
    try:
        resolved = candidate.resolve(strict=True)
    except OSError:
        resolved = candidate.resolve(strict=False)
    return resolved == target_skill_source.expanduser().resolve(strict=False)


def parse_jsonl_events(text: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in text.splitlines():
        if not line.lstrip().startswith("{"):
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            events.append(payload)
    return events


def count_invalid_jsonl_lines(text: str) -> int:
    invalid = 0
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            invalid += 1
            continue
        if not isinstance(payload, Mapping):
            invalid += 1
    return invalid


def classify_codex_infrastructure_failure(
    events: Sequence[Mapping[str, Any]],
    *,
    stderr: str = "",
    timed_out: bool = False,
) -> CodexInfrastructureFailure | None:
    """Classify only failures that occurred before Codex emitted an agent item.

    A service-looking message after a command, file change, collaboration call,
    or agent message is deliberately left to normal semantic grading.  Once the
    model has acted, the run can contain real Skill behavior and must not be
    erased by a broad infrastructure-error heuristic.
    """

    agent_item_event_count = sum(
        event.get("type") in {"item.started", "item.completed"}
        and isinstance(event.get("item"), Mapping)
        for event in events
    )
    if agent_item_event_count:
        return None

    turn_failed = any(event.get("type") == "turn.failed" for event in events)
    messages = list(codex_error_messages(events))
    if stderr.strip():
        messages.append(stderr.strip())
    combined = "\n".join(messages).casefold()
    for category, markers in _CODEX_INFRASTRUCTURE_ERROR_MARKERS:
        if any(marker in combined for marker in markers):
            return CodexInfrastructureFailure(
                category=category,
                message=first_nonempty(messages, default=category),
                turn_failed=turn_failed,
                timed_out=timed_out,
                agent_item_event_count=agent_item_event_count,
            )

    if timed_out:
        return CodexInfrastructureFailure(
            category="timeout_before_agent_action",
            message=first_nonempty(messages, default="Codex CLI timed out before any agent action"),
            turn_failed=turn_failed,
            timed_out=True,
            agent_item_event_count=agent_item_event_count,
        )
    if turn_failed:
        return CodexInfrastructureFailure(
            category="turn_failed_before_agent_action",
            message=first_nonempty(messages, default="Codex turn failed before any agent action"),
            turn_failed=True,
            timed_out=False,
            agent_item_event_count=agent_item_event_count,
        )
    return None


def codex_error_messages(events: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
    """Extract ordered, de-duplicated CLI error messages from JSONL events."""

    messages: list[str] = []
    for event in events:
        if event.get("type") not in {"error", "turn.failed"}:
            continue
        candidates = (event.get("message"), event.get("error"))
        for candidate in candidates:
            if isinstance(candidate, Mapping):
                candidate = candidate.get("message")
            if isinstance(candidate, str) and candidate.strip() and candidate.strip() not in messages:
                messages.append(candidate.strip())
    return tuple(messages)


def first_nonempty(values: Sequence[str], *, default: str) -> str:
    return next((value for value in values if value.strip()), default)


def audit_session_events(
    events: Sequence[Mapping[str, Any]],
    *,
    invalid_json_line_count: int = 0,
) -> CodexSessionAudit:
    thread_ids = tuple(
        str(event.get("thread_id") or "")
        for event in events
        if event.get("type") == "thread.started"
    )
    collab_calls = collab_call_count(events)
    command_started, started_anonymous = item_ids_for_phase(events, "command_execution", "item.started")
    command_completed, completed_anonymous = item_ids_for_phase(events, "command_execution", "item.completed")
    incomplete = len(command_started ^ command_completed) + started_anonymous + completed_anonymous
    observed_item_types = {
        str(item.get("type"))
        for event in events
        if event.get("type") in {"item.started", "item.completed"}
        and isinstance((item := event.get("item")), Mapping)
        and isinstance(item.get("type"), str)
    }
    allowed_item_types = {"agent_message", "command_execution"}
    completed_error_items = tuple(
        item
        for event in events
        if event.get("type") == "item.completed"
        and isinstance((item := event.get("item")), Mapping)
        and item.get("type") == "error"
    )
    completed_turn = sum(
        event.get("type") == "turn.completed" for event in events
    ) == 1 and not any(event.get("type") == "turn.failed" for event in events)
    if completed_turn and completed_error_items and all(
        isinstance((message := item.get("message")), str)
        and message.startswith(
            "Falling back from WebSockets to HTTPS transport. "
            "stream disconnected before completion:"
        )
        for item in completed_error_items
    ):
        allowed_item_types.add("error")
    unexpected_item_types = tuple(sorted(observed_item_types - allowed_item_types))
    return CodexSessionAudit(
        thread_started_count=sum(event.get("type") == "thread.started" for event in events),
        turn_started_count=sum(event.get("type") == "turn.started" for event in events),
        turn_completed_count=sum(event.get("type") == "turn.completed" for event in events),
        thread_ids=thread_ids,
        collab_call_count=collab_calls,
        file_change_count=item_attempt_count(events, "file_change"),
        command_started_count=len(command_started) + started_anonymous,
        command_completed_count=len(command_completed) + completed_anonymous,
        incomplete_command_count=incomplete,
        unexpected_item_types=unexpected_item_types,
        invalid_json_line_count=invalid_json_line_count,
    )


def item_ids_for_phase(
    events: Sequence[Mapping[str, Any]],
    item_type: str,
    event_type: str,
) -> tuple[set[str], int]:
    item_ids: set[str] = set()
    anonymous = 0
    for event in events:
        item = event.get("item")
        if event.get("type") != event_type or not isinstance(item, Mapping) or item.get("type") != item_type:
            continue
        item_id = item.get("id")
        if isinstance(item_id, str) and item_id:
            item_ids.add(item_id)
        else:
            anonymous += 1
    return item_ids, anonymous


def collab_call_count(events: Sequence[Mapping[str, Any]]) -> int:
    """Count attempted collab calls once, including calls that never completed."""

    item_ids: set[str] = set()
    anonymous = 0
    for event in events:
        item = event.get("item")
        if event.get("type") not in {"item.started", "item.completed"} or not isinstance(item, Mapping):
            continue
        if item.get("type") != "collab_tool_call":
            continue
        item_id = item.get("id")
        if isinstance(item_id, str) and item_id:
            item_ids.add(item_id)
        else:
            anonymous += 1
    return len(item_ids) + anonymous


def item_attempt_count(events: Sequence[Mapping[str, Any]], item_type: str) -> int:
    """Count one attempted item once even when JSONL contains start and completion events."""

    item_ids: set[str] = set()
    anonymous = 0
    for event in events:
        item = event.get("item")
        if event.get("type") not in {"item.started", "item.completed"} or not isinstance(item, Mapping):
            continue
        if item.get("type") != item_type:
            continue
        item_id = item.get("id")
        if isinstance(item_id, str) and item_id:
            item_ids.add(item_id)
        else:
            anonymous += 1
    return len(item_ids) + anonymous


def completed_commands(events: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
    return tuple(record.command for record in completed_command_records(events))


def completed_command_records(
    events: Sequence[Mapping[str, Any]],
    *,
    platform_name: str | None = None,
    windows_powershell_core_host: WindowsPowerShellCoreHost | None = None,
) -> tuple[CodexCommandRecord, ...]:
    records: list[CodexCommandRecord] = []
    active_platform = os.name if platform_name is None else platform_name
    for event in events:
        item = event.get("item")
        if event.get("type") != "item.completed" or not isinstance(item, Mapping):
            continue
        if item.get("type") == "command_execution" and isinstance(item.get("command"), str):
            command = str(item["command"])
            argv, has_operators, parse_error, parser_kind = _parse_command_argv(
                command,
                platform_name=active_platform,
                windows_powershell_core_host=windows_powershell_core_host,
            )
            raw_exit = item.get("exit_code")
            records.append(
                CodexCommandRecord(
                    command=command,
                    exit_code=int(raw_exit) if isinstance(raw_exit, int) else None,
                    status=str(item.get("status") or ""),
                    aggregated_output=str(item.get("aggregated_output") or ""),
                    argv=argv,
                    has_shell_operators=has_operators,
                    parse_error=parse_error,
                    parser_kind=parser_kind,
                )
            )
    return tuple(records)


_BUSINESS_DRAFT_NEXT_ACTION_CONTRACT = (
    "waapi-skill.business-draft-next-action/v1"
)
_BUSINESS_DRAFT_COPY_INSTRUCTION_CONTRACT = (
    "waapi-skill.operation-draft-command-copy-instruction/v1"
)
_BUSINESS_DRAFT_FORBIDDEN_TRANSFORMATIONS = (
    "reconstruct",
    "shorten",
    "normalize",
    "substitute_path_segments",
    "select_another_field",
)
_BUSINESS_DRAFT_EXACT_COPY_ACTION = "copy_and_execute_verbatim_once"


def _business_draft_copy_mode(
    instruction: Any,
    *,
    source_field: str = "fixed_argv_prefix_copy",
) -> str | None:
    """Classify one closed copy instruction without coupling to business prose."""

    if (
        not isinstance(instruction, Mapping)
        or set(instruction)
        != {
            "contract",
            "source_field",
            "action",
            "forbidden_transformations",
            "opaque_token_guard",
        }
        or instruction.get("contract")
        != _BUSINESS_DRAFT_COPY_INSTRUCTION_CONTRACT
        or instruction.get("source_field") != source_field
        or instruction.get("forbidden_transformations")
        != list(_BUSINESS_DRAFT_FORBIDDEN_TRANSFORMATIONS)
        or instruction.get("opaque_token_guard")
        != {
            "task_authority": {
                "prefix": "da1-",
                "hex_characters_after_prefix": 40,
                "truncate_to_32_hex_characters": "invalid",
            }
        }
    ):
        return None
    action = instruction.get("action")
    if isinstance(action, str) and action.startswith(
        "copy_verbatim_then_append_"
    ):
        return "prefix"
    if action == _BUSINESS_DRAFT_EXACT_COPY_ACTION:
        return "exact"
    return None


def _business_draft_continuation_candidates(
    payload: Mapping[str, Any],
    *,
    platform_name: str,
) -> tuple[bool, tuple[tuple[str, str], ...]]:
    """Return valid exact/prefix copies owned by one business continuation."""

    found_contract = False
    candidates: set[tuple[str, str]] = set()

    def walk(value: Any, *, inside_business_binding: bool = False) -> None:
        nonlocal found_contract
        if isinstance(value, list):
            for item in value:
                walk(item, inside_business_binding=inside_business_binding)
            return
        if not isinstance(value, Mapping):
            return
        current_binding = inside_business_binding or (
            value.get("contract") == _BUSINESS_DRAFT_NEXT_ACTION_CONTRACT
        )
        if value.get("contract") == _BUSINESS_DRAFT_NEXT_ACTION_CONTRACT:
            found_contract = True
        standard = _selected_gateway_continuation(
            value.get("next_command"),
            platform_name=platform_name,
        )
        if standard is not None:
            _source_field, exact_command = standard
            candidates.add(("exact", exact_command))
        if current_binding:
            instruction = value.get("fixed_argv_prefix_copy_instruction")
            prefix = value.get("fixed_argv_prefix_copy")
            copy_mode = _business_draft_copy_mode(instruction)
            if (
                isinstance(prefix, str)
                and prefix
                and copy_mode is not None
            ):
                candidates.add((copy_mode, prefix))
            exact_instruction = value.get("copy_instruction")
            exact = value.get("copy_command")
            if (
                isinstance(exact, str)
                and exact
                and value.get("copy_exactly") is True
                and _business_draft_copy_mode(
                    exact_instruction,
                    source_field="copy_command",
                )
                == "exact"
            ):
                candidates.add(("exact", exact))
        for item in value.values():
            walk(item, inside_business_binding=current_binding)

    walk(payload)
    return found_contract, tuple(sorted(candidates))


def gateway_continuation_binding_errors(
    command_records: Sequence[CodexCommandRecord | Mapping[str, Any]],
    broker_records: Sequence[Any],
    *,
    platform_name: str | None = None,
    windows_powershell_core_host: WindowsPowerShellCoreHost | None = None,
    allow_compound_checked_child_handoff: bool = False,
) -> tuple[str, ...]:
    """Bind every response-derived continuation to its exact selected bytes.

    Ordinary first commands and later model-authored commands remain governed
    by argv/Broker reconciliation.  A command immediately following a trusted
    Gateway payload with ``next_command`` is different: the Gateway selected
    one response field as an immutable shell-tool continuation.  Re-parsing to
    equivalent argv is insufficient because it would give a reconstructed,
    re-quoted, or legacy fallback field the same semantic credit.

    The caller supplies only Gateway command records, in Broker order.  The
    prior Codex output must reproduce the prior Broker payload exactly before
    its copy instruction is trusted.  Diagnostics intentionally omit the raw
    command, transaction token, and payload.
    """

    active_platform = os.name if platform_name is None else platform_name
    errors: list[str] = []
    compound_parent_candidates: tuple[tuple[str, str], ...] = ()
    compound_child_bindings: set[tuple[str, str]] = set()
    if allow_compound_checked_child_handoff:
        for record_index, broker_record in enumerate(broker_records):
            arguments = _record_field(broker_record, "gateway_arguments", ())
            if not isinstance(arguments, (list, tuple)):
                continue
            arguments = tuple(arguments)
            if arguments[:2] == ("draft-start", "waapi.undoGroup"):
                payload = _record_field(broker_record, "payload")
                if (
                    isinstance(payload, Mapping)
                    and record_index < len(command_records)
                    and _command_output_matches_payload(
                        command_records[record_index],
                        payload,
                    )
                ):
                    _, compound_parent_candidates = (
                        _business_draft_continuation_candidates(
                            payload,
                            platform_name=active_platform,
                        )
                    )
            if arguments[:1] == ("draft-declare-undo-plan",):
                for argument_index, item in enumerate(arguments[:-2]):
                    if item == "--child-draft":
                        child_id = arguments[argument_index + 1]
                        child_authority = arguments[argument_index + 2]
                        if isinstance(child_id, str) and isinstance(
                            child_authority,
                            str,
                        ):
                            compound_child_bindings.add(
                                (child_id, child_authority)
                            )
    for index in range(1, len(broker_records)):
        prior_broker = broker_records[index - 1]
        prior_payload = _record_field(prior_broker, "payload")
        if not isinstance(prior_payload, Mapping):
            continue
        business_contract, business_candidates = (
            _business_draft_continuation_candidates(
                prior_payload,
                platform_name=active_platform,
            )
        )
        if "next_command" not in prior_payload and not business_contract:
            continue
        command_number = index + 1
        if index >= len(command_records) or index - 1 >= len(command_records):
            errors.append(
                f"command {command_number}: Gateway continuation raw evidence is missing"
            )
            continue
        prior_command = command_records[index - 1]
        current_command = command_records[index]
        if not _command_output_matches_payload(prior_command, prior_payload):
            errors.append(
                f"command {command_number}: prior Gateway output does not match Broker evidence"
            )
            continue
        current_arguments = _record_field(
            broker_records[index],
            "gateway_arguments",
            (),
        )
        current_arguments = (
            tuple(current_arguments)
            if isinstance(current_arguments, (list, tuple))
            else ()
        )
        prior_arguments = _record_field(
            prior_broker,
            "gateway_arguments",
            (),
        )
        prior_arguments = (
            tuple(prior_arguments)
            if isinstance(prior_arguments, (list, tuple))
            else ()
        )
        if allow_compound_checked_child_handoff:
            current_subcommand = (
                current_arguments[0] if current_arguments else None
            )
            if current_subcommand == "draft-declare-undo-plan":
                observed_command, _ = _raw_shell_tool_command(
                    current_command,
                    platform_name=active_platform,
                    windows_powershell_core_host=windows_powershell_core_host,
                )
                matches = {
                    command
                    for mode, command in compound_parent_candidates
                    if observed_command is not None
                    and _business_draft_command_matches(
                        mode=mode,
                        expected_command=command,
                        observed_command=observed_command,
                        current_record=current_command,
                        platform_name=active_platform,
                    )
                }
                longest_matches = {
                    command
                    for command in matches
                    if len(command)
                    == max((len(item) for item in matches), default=-1)
                }
                if observed_command is None or len(longest_matches) != 1:
                    errors.append(
                        f"command {command_number}: deferred compound Draft "
                        "continuation was not copied from its selected source field"
                    )
                continue
            if (
                isinstance(prior_payload.get("draft"), Mapping)
                and isinstance(
                    prior_payload["draft"].get("next_action_binding"),
                    Mapping,
                )
                and prior_payload["draft"]["next_action_binding"].get(
                    "required_next_phase"
                )
                == "declare_ordered_checked_child_business_drafts"
            ):
                continue
            if prior_arguments[:1] == ("draft-check",):
                try:
                    authority_index = prior_arguments.index("--task-authority")
                except ValueError:
                    authority_index = -1
                child_binding = (
                    (
                        prior_arguments[1],
                        prior_arguments[authority_index + 1],
                    )
                    if authority_index > 0
                    and authority_index + 1 < len(prior_arguments)
                    else None
                )
                if (
                    child_binding in compound_child_bindings
                    and current_subcommand != "preview-from-draft"
                ):
                    continue
        if "next_command" not in prior_payload:
            observed_command, _ = _raw_shell_tool_command(
                current_command,
                platform_name=active_platform,
                windows_powershell_core_host=windows_powershell_core_host,
            )
            matches = {
                command
                for mode, command in business_candidates
                if observed_command is not None
                and _business_draft_command_matches(
                    mode=mode,
                    expected_command=command,
                    observed_command=observed_command,
                    current_record=current_command,
                    platform_name=active_platform,
                )
            }
            longest_matches = {
                command
                for command in matches
                if len(command) == max((len(item) for item in matches), default=-1)
            }
            if observed_command is None or len(longest_matches) != 1:
                errors.append(
                    f"command {command_number}: Gateway business Draft "
                    "continuation was not copied from its selected source field"
                )
            continue
        selected = _selected_gateway_continuation(
            prior_payload.get("next_command"),
            platform_name=active_platform,
        )
        if selected is None:
            errors.append(
                f"command {command_number}: prior Gateway copy instruction is incomplete or invalid"
            )
            continue
        source_field, expected_command = selected
        observed_command, observed_kind = _raw_shell_tool_command(
            current_command,
            platform_name=active_platform,
            windows_powershell_core_host=windows_powershell_core_host,
        )
        expected_kind = (
            _WINDOWS_POWERSHELL_CORE_PARSER_KIND
            if source_field == "model_command" and _is_windows(active_platform)
            else _WINDOWS_ENCODED_POWERSHELL_PARSER_KIND
            if source_field == "shell_command" and _is_windows(active_platform)
            else ""
        )
        try:
            copied_exactly = (
                observed_command is not None
                and observed_command.encode("utf-8", errors="strict")
                == expected_command.encode("utf-8", errors="strict")
            )
        except UnicodeEncodeError:
            copied_exactly = False
        if (
            observed_command is None
            or not copied_exactly
            or (expected_kind and observed_kind != expected_kind)
        ):
            errors.append(
                f"command {command_number}: Gateway continuation was not copied "
                "from its selected source field"
            )
    return tuple(errors)


def _business_draft_command_matches(
    *,
    mode: str,
    expected_command: str,
    observed_command: str,
    current_record: CodexCommandRecord | Mapping[str, Any],
    platform_name: str,
) -> bool:
    """Match exact bytes, allowing only the sealed task-local runner expansion."""

    def matches(candidate: str) -> bool:
        return observed_command == candidate or (
            mode == "prefix" and observed_command.startswith(candidate + " ")
        )

    if matches(expected_command):
        return True
    if not _is_windows(platform_name):
        return False
    try:
        expected_argv = decode_windows_model_argv(expected_command)
    except PlatformCommandError:
        return False
    observed_argv = _record_field(current_record, "argv", ())
    if (
        not isinstance(observed_argv, (list, tuple))
        or len(expected_argv) < 3
        or len(observed_argv) < len(expected_argv)
        or expected_argv[0] != "python"
        or observed_argv[0] != "python"
        or not isinstance(observed_argv[1], str)
        or not task_local_runner_matches_normalized(
            expected_argv[1],
            observed_argv[1],
        )
    ):
        return False
    expanded = encode_windows_model_argv(
        (expected_argv[0], observed_argv[1], *expected_argv[2:])
    )
    return matches(expanded)


def _record_field(record: Any, name: str, default: Any = None) -> Any:
    if isinstance(record, Mapping):
        return record.get(name, default)
    return getattr(record, name, default)


def _command_output_matches_payload(
    record: CodexCommandRecord | Mapping[str, Any],
    payload: Mapping[str, Any],
) -> bool:
    raw_output = _record_field(record, "aggregated_output", "")
    if not isinstance(raw_output, str):
        return False
    try:
        observed = json.loads(raw_output.strip())
    except (json.JSONDecodeError, UnicodeError):
        return False
    return observed == payload


def _selected_gateway_continuation(
    value: Any,
    *,
    platform_name: str,
) -> tuple[str, str] | None:
    """Return the one field selected by a complete closed v2 instruction."""

    if not isinstance(value, Mapping):
        return None
    common_keys = {
        "contract",
        "command",
        "gateway_argv",
        "full_argv",
        "copy_exactly",
        "shell_tool_timeout_ms",
        "shell_family",
        "copy_instruction",
    }
    optional_keys = {
        "requires_explicit_user_confirmation",
        "requires_later_user_message",
    }
    instruction = value.get("copy_instruction")
    if (
        value.get("contract") != _TRANSACTION_NEXT_COMMAND_CONTRACT
        or value.get("copy_exactly") is not True
        or value.get("shell_tool_timeout_ms") != GATEWAY_SHELL_TOOL_TIMEOUT_MS
        or not isinstance(value.get("command"), str)
        or not value.get("command")
        or not isinstance(instruction, Mapping)
        or set(instruction)
        != {"contract", "source_field", "action", "forbidden_transformations"}
        or instruction.get("contract")
        != _TRANSACTION_COPY_INSTRUCTION_CONTRACT
        or instruction.get("action") != _TRANSACTION_COPY_ACTION
        or instruction.get("forbidden_transformations")
        != list(_TRANSACTION_FORBIDDEN_TRANSFORMATIONS)
        or any(value.get(key) is not True for key in optional_keys & set(value))
    ):
        return None
    gateway_argv = value.get("gateway_argv")
    full_argv = value.get("full_argv")
    if (
        not isinstance(gateway_argv, list)
        or not gateway_argv
        or any(not isinstance(item, str) for item in gateway_argv)
        or gateway_argv[0] != value.get("command")
        or not isinstance(full_argv, list)
        or len(full_argv) != len(gateway_argv) + 3
        or full_argv[0] != "python"
        or not isinstance(full_argv[1], str)
        or not full_argv[1]
        or full_argv[2] != "gateway.py"
        or full_argv != ["python", full_argv[1], "gateway.py", *gateway_argv]
    ):
        return None
    source_field = instruction.get("source_field")
    if source_field == "model_command":
        required_keys = common_keys | optional_keys.intersection(value) | {
            "shell_command",
            "model_shell_family",
            "model_command",
        }
        if (
            not _is_windows(platform_name)
            or set(value) != required_keys
            or value.get("shell_family") != WINDOWS_POWERSHELL_ENCODED_FAMILY
            or value.get("model_shell_family") != WINDOWS_MODEL_COMMAND_FAMILY
            or not isinstance(value.get("shell_command"), str)
            or not value.get("shell_command")
        ):
            return None
        try:
            model_argv = decode_windows_model_argv(str(value["model_command"]))
            full_argv_tuple = tuple(full_argv)
            model_runner_matches = (
                model_argv == full_argv_tuple
                or (
                    len(model_argv) == len(full_argv_tuple)
                    and model_argv[0] == "python"
                    and model_argv[2:] == full_argv_tuple[2:]
                    and task_local_runner_matches_normalized(
                        model_argv[1],
                        full_argv_tuple[1],
                    )
                )
            )
            if (
                not model_runner_matches
                or decode_windows_powershell_argv(str(value["shell_command"]))
                != full_argv_tuple
            ):
                return None
        except PlatformCommandError:
            return None
    elif source_field == "shell_command":
        required_keys = common_keys | optional_keys.intersection(value) | {
            "shell_command"
        }
        expected_family = (
            WINDOWS_POWERSHELL_ENCODED_FAMILY
            if _is_windows(platform_name)
            else "posix-sh"
        )
        if (
            set(value) != required_keys
            or value.get("shell_family") != expected_family
        ):
            return None
        try:
            if _is_windows(platform_name):
                representation_argv = decode_windows_powershell_argv(
                    str(value["shell_command"])
                )
                if representation_argv != tuple(full_argv):
                    return None
            elif value.get("shell_command") != shlex.join(full_argv):
                return None
        except PlatformCommandError:
            return None
    else:
        return None
    selected = value.get(source_field)
    if not isinstance(selected, str) or not selected:
        return None
    return str(source_field), selected


def _raw_shell_tool_command(
    record: CodexCommandRecord | Mapping[str, Any],
    *,
    platform_name: str,
    windows_powershell_core_host: WindowsPowerShellCoreHost | None,
) -> tuple[str | None, str]:
    command = _record_field(record, "command", "")
    parser_kind = _record_field(record, "parser_kind", "")
    if not isinstance(command, str) or not isinstance(parser_kind, str):
        return None, ""
    if _is_windows(platform_name):
        if windows_powershell_core_host is None:
            return None, parser_kind
        try:
            outer = tuple(shlex.split(command, posix=True))
        except ValueError:
            return None, parser_kind
        if (
            len(outer) != 4
            or PureWindowsPath(outer[0])
            != PureWindowsPath(windows_powershell_core_host.executable)
            or outer[1:3] != ("-NoProfile", "-Command")
        ):
            return None, parser_kind
        return outer[3], parser_kind
    if parser_kind == "posix-native":
        return command, parser_kind
    if parser_kind == "posix-shell":
        try:
            outer = tuple(shlex.split(command, posix=True))
        except ValueError:
            return None, parser_kind
        if len(outer) == 3 and outer[1] in {"-c", "-lc", "-ic"}:
            return outer[2], parser_kind
    return None, parser_kind


def parse_command_argv(
    command: str,
    *,
    platform_name: str | None = None,
    windows_directory: str | PureWindowsPath | None = None,
    windows_powershell_core_host: WindowsPowerShellCoreHost | None = None,
) -> tuple[tuple[str, ...], bool, str]:
    """Parse one Codex command-item presentation into its executed argv.

    Codex CLI 0.146 serializes the underlying command vector for JSONL with
    Rust ``shlex::try_join`` on every host.  That is a POSIX presentation,
    not a Windows ``CreateProcess`` command line.  Decode that outer layer
    first, then unwrap Codex's fixed native-Windows
    ``pwsh.exe -NoProfile -Command`` frame only when its exact executable has
    been attested as PowerShell Core 7.3+ with safe native argument passing and
    it contains one literal argv vector under the restricted grammar below.
    Other PowerShell and CMD shapes remain unexpected outer commands.
    """

    argv, has_operators, parse_error, _parser_kind = _parse_command_argv(
        command,
        platform_name=platform_name,
        windows_directory=windows_directory,
        windows_powershell_core_host=windows_powershell_core_host,
    )
    return argv, has_operators, parse_error


def _parse_command_argv(
    command: str,
    *,
    platform_name: str | None = None,
    windows_directory: str | PureWindowsPath | None = None,
    windows_powershell_core_host: WindowsPowerShellCoreHost | None = None,
) -> tuple[tuple[str, ...], bool, str, str]:
    active_platform = os.name if platform_name is None else platform_name
    if _is_windows(active_platform):
        has_operators = shell_script_has_operators(command, platform_name="nt")
        try:
            # ``command_execution.command`` is the client-facing result of
            # Codex's platform-independent Rust ``shlex::try_join``.  Using
            # CommandLineToArgvW here preserves the display codec's doubled
            # backslashes and corrupts Windows paths and JSON strings before
            # they can be reconciled with the Broker's actual argv.
            outer = tuple(shlex.split(command, posix=True))
        except ValueError as exc:
            return (), True, str(exc), ""
        if not outer:
            return (), False, "empty command", ""
        shell_name = PureWindowsPath(outer[0]).name.casefold()
        if shell_name in _WINDOWS_POWERSHELL_CORE_COMMAND_NAMES:
            host = windows_powershell_core_host
            if host is None:
                return (), True, "pre-attested PowerShell Core host is required", ""
            argv, operators, error = _parse_windows_powershell_core_command_wrapper(
                outer,
                powershell_core_host=host,
            )
            parser_kind = (
                _WINDOWS_ENCODED_POWERSHELL_PARSER_KIND
                if not error and outer[3].startswith("powershell.exe ")
                else _WINDOWS_POWERSHELL_CORE_PARSER_KIND
                if not error
                else ""
            )
            return (
                argv,
                operators,
                error,
                parser_kind,
            )
        if shell_name in _WINDOWS_POWERSHELL_COMMAND_NAMES:
            return (), True, "Windows PowerShell 5.1 command wrappers are not supported", ""
        if shell_name.removesuffix(".exe") in {"bash", "sh", "zsh", "dash", "ksh"}:
            argv, operators, error = _parse_posix_shell_command_wrapper(outer)
            return argv, operators, error, "posix-shell"
        return outer, has_operators, "", "windows-native"

    try:
        outer = shlex.split(command, posix=True)
    except ValueError:
        outer = []
    if not outer:
        if not command.strip():
            return (), False, "empty command", ""
    script = command
    shell_name = PureWindowsPath(outer[0]).name.casefold() if outer else ""
    shell_stem = shell_name.removesuffix(".exe")
    if shell_stem in {"bash", "sh", "zsh", "dash", "ksh"}:
        argv, operators, error = _parse_posix_shell_command_wrapper(outer)
        return argv, operators, error, "posix-shell"

    has_operators = shell_script_has_operators(script, platform_name="posix")
    try:
        argv = split_native_command_line(script, platform_name="posix")
    except (OSError, ValueError) as exc:
        return (), True, str(exc), ""
    return argv, has_operators, "", "posix-native"


def _parse_posix_shell_command_wrapper(
    outer_argv: Sequence[str],
) -> tuple[tuple[str, ...], bool, str]:
    if len(outer_argv) != 3 or outer_argv[1] not in {"-c", "-lc", "-ic"}:
        return (), True, "shell command must be executable plus one -c/-lc/-ic and its script"
    script = outer_argv[2]
    has_operators = shell_script_has_operators(script, platform_name="posix")
    try:
        argv = tuple(shlex.split(script, posix=True))
    except ValueError as exc:
        return (), True, str(exc)
    return argv, has_operators, ""


def _parse_windows_powershell_core_command_wrapper(
    outer_argv: Sequence[str],
    *,
    powershell_core_host: WindowsPowerShellCoreHost,
) -> tuple[tuple[str, ...], bool, str]:
    """Unwrap only Codex's attested, profile-free PowerShell Core frame."""

    if (
        len(outer_argv) != 4
        or outer_argv[1] != "-NoProfile"
        or outer_argv[2] != "-Command"
    ):
        return (), True, "unsupported PowerShell Core command wrapper"
    executable = PureWindowsPath(outer_argv[0])
    expected_executable = PureWindowsPath(powershell_core_host.executable)
    if executable != expected_executable:
        return (), True, "PowerShell Core wrapper executable is not the attested host"
    script = outer_argv[3]
    if script.startswith("powershell.exe "):
        try:
            return decode_windows_powershell_argv(script), False, ""
        except PlatformCommandError as exc:
            return (), True, str(exc)
    try:
        return _split_literal_powershell_argv(script), False, ""
    except ValueError as exc:
        return (), True, str(exc)


def _split_literal_powershell_argv(script: str) -> tuple[str, ...]:
    """Parse one expansion-free PowerShell native-command argv expression.

    Only whitespace-separated bare words and single-quoted literal strings are
    accepted. Doubled apostrophes inside a literal use PowerShell's exact
    single-quote escape. Composition, expansion, interpolation, redirection,
    comments, globbing, arrays, script blocks, and multiline input all fail
    closed before the command can receive semantic credit.
    """

    if not script or "\0" in script or "\r" in script or "\n" in script:
        raise ValueError("PowerShell command must be one non-empty line")
    if any(character in _POWERSHELL_SMART_QUOTES for character in script):
        raise ValueError("PowerShell smart quotes are not permitted")
    arguments: list[str] = []
    index = 0
    while index < len(script):
        while index < len(script) and script[index] in {" ", "\t"}:
            index += 1
        if index == len(script):
            break
        if script[index] == '"':
            raise ValueError("PowerShell interpolating strings are not permitted")
        if script[index] == "'":
            index += 1
            literal: list[str] = []
            while index < len(script):
                character = script[index]
                if character != "'":
                    literal.append(character)
                    index += 1
                    continue
                if index + 1 < len(script) and script[index + 1] == "'":
                    literal.append("'")
                    index += 2
                    continue
                index += 1
                break
            else:
                raise ValueError("PowerShell single-quoted literal is not closed")
            if index < len(script) and script[index] not in {" ", "\t"}:
                raise ValueError("PowerShell argv tokens must not concatenate expressions")
            arguments.append("".join(literal))
            continue

        start = index
        while index < len(script) and script[index] not in {" ", "\t"}:
            if script[index] in _POWERSHELL_BARE_FORBIDDEN:
                raise ValueError(
                    "PowerShell command contains composition, expansion, or interpolation"
                )
            index += 1
        arguments.append(script[start:index])
    if not arguments:
        raise ValueError("PowerShell command contains no argv")
    return tuple(arguments)


def split_native_command_line(
    command: str,
    *,
    platform_name: str | None = None,
) -> tuple[str, ...]:
    """Split one shell-free command according to the selected host grammar."""

    if not _is_windows(platform_name):
        return tuple(shlex.split(command, posix=True))

    # CommandLineToArgvW is the Windows system parser used for native argv
    # semantics.  Keep the import inside the Windows branch so this module
    # remains importable on POSIX hosts.
    import ctypes
    from ctypes import wintypes

    argument_count = ctypes.c_int()
    command_line_to_argv = ctypes.windll.shell32.CommandLineToArgvW
    command_line_to_argv.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
    command_line_to_argv.restype = ctypes.POINTER(wintypes.LPWSTR)
    argument_vector = command_line_to_argv(command, ctypes.byref(argument_count))
    if not argument_vector:
        raise OSError(ctypes.get_last_error(), "CommandLineToArgvW failed")
    try:
        return tuple(argument_vector[index] for index in range(argument_count.value))
    finally:
        local_free = ctypes.windll.kernel32.LocalFree
        local_free.argtypes = [ctypes.c_void_p]
        local_free.restype = ctypes.c_void_p
        local_free(ctypes.cast(argument_vector, ctypes.c_void_p))


def shell_script_has_operators(
    script: str,
    *,
    platform_name: str | None = None,
) -> bool:
    if _is_windows(platform_name):
        return windows_shell_script_has_operators(script)

    quote = ""
    escaped = False
    index = 0
    while index < len(script):
        character = script[index]
        if escaped:
            escaped = False
            index += 1
            continue
        if character == "\\" and quote != "'":
            escaped = True
            index += 1
            continue
        if quote:
            if character == quote:
                quote = ""
            elif quote == '"' and (character == "`" or script[index : index + 2] == "$("):
                return True
            index += 1
            continue
        if character in {"'", '"'}:
            quote = character
            index += 1
            continue
        if character in "|&;<>\n\r`" or script[index : index + 2] == "$(":
            return True
        index += 1
    return bool(quote or escaped)


def windows_shell_script_has_operators(script: str) -> bool:
    """Fail closed on unquoted CMD/PowerShell composition operators."""

    quoted = False
    escaped = False
    index = 0
    while index < len(script):
        character = script[index]
        if escaped:
            escaped = False
            index += 1
            continue
        if character == "^" and not quoted:
            escaped = True
            index += 1
            continue
        if character == '"':
            quoted = not quoted
            index += 1
            continue
        if not quoted and character in "|&;<>\n\r`":
            return True
        index += 1
    return quoted or escaped


def classify_commands(
    commands: Sequence[str | CodexCommandRecord],
    *,
    skill_source: Path,
    skill_read_content_source: Path | None = None,
    alternate_skill_read_sources: Sequence[Path] = (),
    alternate_gateway_skill_sources: Sequence[Path] = (),
    expected_gateway_subcommands: Sequence[str] = (),
    expected_gateway_errors: Sequence[CodexGatewayErrorExpectation] = (),
    expected_wwise_version: str = "",
) -> CodexCommandFacts:
    records = tuple(command_record(command) for command in commands)
    inline_python: list[str] = []
    direct_client: list[str] = []
    write_like: list[str] = []
    gateway: list[str] = []
    gateway_attempts: list[str] = []
    gateway_subcommands: list[str] = []
    gateway_results: list[Mapping[str, Any]] = []
    discovery: list[str] = []
    allowed_reads: list[str] = []
    read_files: list[str] = []
    unexpected: list[str] = []
    non_gateway_unexpected: list[str] = []
    skill_read = False
    expected = frozenset(str(value) for value in expected_gateway_subcommands)
    skill_read_sources = tuple(
        dict.fromkeys(
            _absolute_lexical_path(source)
            for source in (skill_source, *alternate_skill_read_sources)
        )
    )
    gateway_skill_sources = tuple(
        dict.fromkeys(
            _absolute_lexical_path(source)
            for source in (skill_source, *alternate_gateway_skill_sources)
        )
    )
    error_expectations: dict[str, str] = {}
    for expectation in expected_gateway_errors:
        if expectation.command in error_expectations:
            raise ValueError("expected_gateway_errors commands must be unique")
        error_expectations[expectation.command] = expectation.error_code

    validated_reads_by_index: dict[int, str] = {}
    for index, record in enumerate(records):
        candidates = tuple(
            value
            for source in skill_read_sources
            if (
                value := allowed_skill_read(
                    record,
                    skill_source=source,
                    skill_read_content_source=skill_read_content_source,
                )
            )
        )
        if candidates and len(set(candidates)) == 1:
            validated_reads_by_index[index] = candidates[0]
    recoverable_preprocess_indexes = frozenset(
        recoverable_preprocess_attempt_indexes(records)
    )

    for record_index, record in enumerate(records):
        if record_index in recoverable_preprocess_indexes:
            continue
        command = record.command
        lowered = command.lower()
        executable = Path(record.argv[0]).name.lower() if record.argv else ""
        matched_gateway_source_and_shape = next(
            (
                (source, shape)
                for source in gateway_skill_sources
                if (
                    shape := gateway_invocation(
                        record,
                        skill_source=source,
                        expected_wwise_version=expected_wwise_version,
                    )
                )
                is not None
            ),
            None,
        )
        matched_gateway_source = (
            matched_gateway_source_and_shape[0]
            if matched_gateway_source_and_shape is not None
            else gateway_skill_sources[0]
        )
        gateway_shape = (
            matched_gateway_source_and_shape[1]
            if matched_gateway_source_and_shape is not None
            else None
        )
        if gateway_shape is not None:
            gateway_attempts.append(command)
        gateway_payload = successful_gateway_payload(
            record,
            skill_source=matched_gateway_source,
            expected_gateway_subcommands=expected,
            expected_wwise_version=expected_wwise_version,
        )
        if gateway_payload is None and gateway_shape is not None and (not expected or gateway_shape in expected):
            expected_error_code = error_expectations.get(gateway_shape)
            if expected_error_code is not None:
                gateway_payload = expected_gateway_error_payload(
                    record,
                    skill_source=matched_gateway_source,
                    expected_subcommand=gateway_shape,
                    expected_error_code=expected_error_code,
                    expected_wwise_version=expected_wwise_version,
                )
        is_gateway = gateway_payload is not None
        if is_gateway:
            gateway.append(command)
            gateway_results.append(gateway_payload)
            gateway_subcommands.append(str(gateway_payload.get("command") or gateway_shape or ""))

        is_python = _PYTHON_EXECUTABLE_RE.fullmatch(executable) is not None
        is_packaged_runner_attempt = any(
            packaged_runner_attempt(record, skill_source=source)
            for source in gateway_skill_sources
        )
        if is_python and not is_gateway and not is_packaged_runner_attempt:
            inline_python.append(command)
        allowed_read = validated_reads_by_index.get(record_index)
        if direct_waapi_command(record):
            direct_client.append(command)
        if write_like_command(record) and not allowed_read:
            write_like.append(command)
        if discovery_command(record):
            discovery.append(command)

        if allowed_read:
            allowed_reads.append(command)
            read_files.append(allowed_read)
            if allowed_read == "SKILL.md":
                skill_read = True
        if (
            not is_gateway
            and not allowed_read
        ):
            unexpected.append(command)
            if gateway_shape is None:
                non_gateway_unexpected.append(command)

    first_gateway = next((index for index, record in enumerate(records) if record.command in gateway), None)
    first_discovery = next((index for index, record in enumerate(records) if record.command in discovery), None)
    gateway_before_discovery = first_gateway is not None and (first_discovery is None or first_gateway < first_discovery)
    runtime_apis: list[str] = []
    for payload in gateway_results:
        runtime_apis.extend(gateway_runtime_apis(payload))
    return CodexCommandFacts(
        commands=tuple(record.command for record in records),
        inline_python_commands=tuple(inline_python),
        direct_waapi_client_commands=tuple(direct_client),
        write_like_commands=tuple(write_like),
        gateway_commands=tuple(gateway),
        discovery_commands=tuple(discovery),
        skill_read=skill_read,
        gateway_before_discovery=gateway_before_discovery,
        command_records=records,
        gateway_attempt_commands=tuple(gateway_attempts),
        gateway_subcommands=tuple(gateway_subcommands),
        gateway_results=tuple(gateway_results),
        gateway_evidence_apis=tuple(dict.fromkeys(runtime_apis)),
        allowed_read_commands=tuple(allowed_reads),
        skill_read_files=tuple(read_files),
        unexpected_commands=tuple(unexpected),
        non_gateway_unexpected_commands=tuple(non_gateway_unexpected),
    )


def classify_task_commands(
    commands: Sequence[str | CodexCommandRecord],
    *,
    workspace: Path,
    skill_source: Path,
    expected_gateway_subcommands: Sequence[str] = (),
    expected_gateway_errors: Sequence[CodexGatewayErrorExpectation] = (),
    expected_wwise_version: str = "",
) -> CodexCommandFacts:
    """Classify one task against its fixed install and sealed candidate.

    Every host exposes a detached task-local Skill locator to the model while
    retaining the sealed candidate as the content and execution authority.
    Campaign archiving may replace the copy with a regular attestation before
    replay, so classification is lexical and reads candidate bytes.  Both the
    exact task-local and exact candidate runner spellings remain auditable;
    near paths are rejected.
    """

    workspace_install = workspace_skill_install_path(workspace)
    return classify_commands(
        commands,
        skill_source=workspace_install,
        skill_read_content_source=skill_source,
        alternate_skill_read_sources=(skill_source,),
        alternate_gateway_skill_sources=(skill_source,),
        expected_gateway_subcommands=expected_gateway_subcommands,
        expected_gateway_errors=expected_gateway_errors,
        expected_wwise_version=expected_wwise_version,
    )


def packaged_runner_attempt(record: CodexCommandRecord, *, skill_source: Path) -> bool:
    """Identify an exact packaged runner path even when its argv is malformed.

    This is diagnostic only: malformed attempts remain unexpected commands and
    still fail broker/grader checks. They are not ad-hoc inline Python, though,
    so do not report them as code generation merely because the packaged
    invocation failed before producing a valid gateway payload.
    """

    if len(record.argv) < 2 or record.parse_error:
        return False
    executable = Path(record.argv[0]).name.lower()
    if _PYTHON_EXECUTABLE_RE.fullmatch(executable) is None:
        return False
    supplied_runner = _supplied_absolute_lexical_path(record.argv[1])
    if supplied_runner is None:
        return False
    expected_runner = _absolute_lexical_path(skill_source) / "scripts" / "run.py"
    return supplied_runner == expected_runner


def _absolute_lexical_path(path: Path) -> Path:
    """Return an absolute locator without dereferencing any path component."""

    return Path(os.path.abspath(os.fspath(Path(path).expanduser())))


def _supplied_absolute_lexical_path(path: str | Path) -> Path | None:
    """Normalize harmless lexical spelling without accepting parent traversal."""

    supplied = Path(path)
    if not supplied.is_absolute() or ".." in supplied.parts:
        return None
    return _absolute_lexical_path(supplied)


def command_record(command: str | CodexCommandRecord) -> CodexCommandRecord:
    if isinstance(command, CodexCommandRecord):
        return command
    argv, has_operators, parse_error, parser_kind = _parse_command_argv(
        str(command)
    )
    return CodexCommandRecord(
        command=str(command),
        exit_code=None,
        status="",
        aggregated_output="",
        argv=argv,
        has_shell_operators=has_operators,
        parse_error=parse_error,
        parser_kind=parser_kind,
    )


def normalized_gateway_command_argv(
    argv: Sequence[str],
    *,
    expected_wwise_version: str = "",
) -> tuple[str, ...]:
    """Normalize the two closed, inert model-side version spellings.

    The semantic broker owns the real runner environment, so a leading
    ``WWISE_VERSION=<session version>`` only documents model intent. Keep the
    raw command in evidence, but normalize either the direct POSIX assignment
    or the exact ``env WWISE_VERSION=...`` spelling before matching it to the
    broker record. The production runner also accepts one version selector
    immediately before the exact ``gateway.py`` target; move that selector to
    the canonical gateway-global position. Every other assignment, ``env``
    option, runner-level flag, wrong version, or wrong target remains invalid.
    """

    values = tuple(str(value) for value in argv)
    if not values:
        return values
    assignment_index = 1 if values[0] == "env" else 0
    if assignment_index >= len(values):
        return ()
    assignment = _SHELL_ASSIGNMENT_RE.fullmatch(values[assignment_index])
    if assignment is None:
        if assignment_index != 0:
            return ()
    else:
        version = assignment.group("value")
        if (
            assignment.group("name") != "WWISE_VERSION"
            or not expected_wwise_version
            or expected_wwise_version not in SUPPORTED_WWISE_VERSIONS
            or version != expected_wwise_version
        ):
            return ()
        values = values[assignment_index + 1 :]
        if values and _SHELL_ASSIGNMENT_RE.fullmatch(values[0]) is not None:
            return ()

    if len(values) < 3 or values[2] == "gateway.py":
        return values

    selector = values[2]
    if selector in _RUNNER_VERSION_SELECTORS:
        if len(values) < 6:
            return ()
        supplied_version = values[3]
        gateway_target = values[4]
        remainder = values[5:]
        canonical_selector = (selector, supplied_version)
    elif any(selector.startswith(f"{option}=") for option in _RUNNER_VERSION_SELECTORS):
        if len(values) < 5:
            return ()
        supplied_version = selector.split("=", 1)[1]
        gateway_target = values[3]
        remainder = values[4:]
        canonical_selector = (selector,)
    else:
        return values

    if (
        gateway_target != "gateway.py"
        or not expected_wwise_version
        or expected_wwise_version not in SUPPORTED_WWISE_VERSIONS
        or supplied_version != expected_wwise_version
    ):
        return ()
    return (*values[:2], "gateway.py", *canonical_selector, *remainder)


def gateway_invocation(
    record: CodexCommandRecord,
    *,
    skill_source: Path,
    expected_wwise_version: str = "",
) -> str | None:
    argv = normalized_gateway_command_argv(
        record.argv,
        expected_wwise_version=expected_wwise_version,
    )
    if record.has_shell_operators or record.parse_error or len(argv) < 4:
        return None
    executable = Path(argv[0]).name.lower()
    if _PYTHON_EXECUTABLE_RE.fullmatch(executable) is None:
        return None
    runner = argv[1]
    expected_runner = _absolute_lexical_path(skill_source) / "scripts" / "run.py"
    candidate = _supplied_absolute_lexical_path(runner)
    if candidate != expected_runner and not task_local_runner_matches_normalized(
        runner,
        str(expected_runner),
    ):
        return None
    if argv[2] != "gateway.py":
        return None
    return gateway_subcommand(argv[3:])


def gateway_subcommand(arguments: Sequence[str]) -> str | None:
    """Return the argparse subcommand without matching option values or payload text."""

    global_options_with_values = frozenset(
        {
            "--host",
            "--port",
            "--version",
            "--wwise-version",
            "--timeout",
            "--evidence-dir",
            "--state-dir",
        }
    )
    index = 0
    while index < len(arguments):
        value = arguments[index]
        if value in GATEWAY_SUBCOMMANDS:
            return value
        if any(value.startswith(f"{option}=") for option in global_options_with_values):
            index += 1
            continue
        if value in global_options_with_values:
            if index + 1 >= len(arguments):
                return None
            index += 2
            continue
        # Unknown flags and arbitrary positional values before the subcommand
        # are not the closed gateway invocation contract.
        return None
    return None


def successful_gateway_payload(
    record: CodexCommandRecord,
    *,
    skill_source: Path,
    expected_gateway_subcommands: frozenset[str],
    expected_wwise_version: str = "",
) -> Mapping[str, Any] | None:
    subcommand = gateway_invocation(
        record,
        skill_source=skill_source,
        expected_wwise_version=expected_wwise_version,
    )
    if subcommand is None or (expected_gateway_subcommands and subcommand not in expected_gateway_subcommands):
        return None
    if not record.succeeded:
        return None
    try:
        if subcommand == "stream-topic":
            stream_records = tuple(
                json.loads(line)
                for line in record.aggregated_output.splitlines()
                if line.strip()
            )
            if (
                len(stream_records) < 2
                or not all(isinstance(item, Mapping) for item in stream_records)
                or stream_records[0].get("record_type") != "started"
                or stream_records[-1].get("record_type") != "terminal"
            ):
                return None
            payload = stream_records[-1]
        else:
            payload = json.loads(record.aggregated_output.strip())
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, Mapping):
        return None
    if (
        payload.get("contract") not in gateway_payload_contracts(subcommand)
        or payload.get("command") != subcommand
        or payload.get("ok") is not True
    ):
        return None
    return dict(payload)


def expected_gateway_error_payload(
    record: CodexCommandRecord,
    *,
    skill_source: Path,
    expected_subcommand: str,
    expected_error_code: str,
    expected_wwise_version: str = "",
) -> Mapping[str, Any] | None:
    """Return one explicitly expected gateway exit-2 payload, or ``None``.

    This is intentionally separate from :attr:`CodexCommandRecord.succeeded`:
    an exit-2 process is still a failed shell command and becomes acceptable
    only under the caller's closed command/error-code expectation.
    """

    subcommand = gateway_invocation(
        record,
        skill_source=skill_source,
        expected_wwise_version=expected_wwise_version,
    )
    if (
        subcommand != expected_subcommand
        or record.exit_code != 2
        or record.status != "failed"
        or record.has_shell_operators
        or record.parse_error
    ):
        return None
    try:
        payload = json.loads(record.aggregated_output.strip())
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, Mapping):
        return None
    if (
        payload.get("contract") != GATEWAY_RESULT_CONTRACT
        or payload.get("command") != expected_subcommand
        or payload.get("ok") is not False
        or payload.get("error_code") != expected_error_code
    ):
        return None
    return dict(payload)


def gateway_runtime_apis(payload: Any) -> tuple[str, ...]:
    apis: list[str] = []
    if isinstance(payload, Mapping):
        attempted = payload.get("api_attempted")
        if isinstance(attempted, str):
            apis.append(attempted)
        for key, child in payload.items():
            if key in {"calls", "call", "dispatch_result"} or key.endswith("_call"):
                apis.extend(call_payload_apis(child))
    elif isinstance(payload, Sequence) and not isinstance(payload, (str, bytes, bytearray)):
        for child in payload:
            apis.extend(gateway_runtime_apis(child))
    return tuple(dict.fromkeys(apis))


def call_payload_apis(value: Any) -> tuple[str, ...]:
    apis: list[str] = []
    if isinstance(value, Mapping):
        api = value.get("api")
        if isinstance(api, str):
            apis.append(api)
        for key, child in value.items():
            if key in {"calls", "call", "dispatch_result"} or key.endswith("_call"):
                apis.extend(call_payload_apis(child))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for child in value:
            apis.extend(call_payload_apis(child))
    return tuple(dict.fromkeys(apis))


def allowed_skill_read(
    record: CodexCommandRecord,
    *,
    skill_source: Path,
    skill_read_content_source: Path | None = None,
) -> str | None:
    if not record.succeeded or record.parse_error or not record.argv:
        return None
    if record.has_shell_operators:
        return allowed_skill_bootstrap_read(
            record,
            skill_source=skill_source,
            skill_read_content_source=skill_read_content_source,
        )
    executable = Path(record.argv[0]).name.lower()
    complete_skill_read = False
    if executable == "cat":
        if (
            record.parser_kind not in _POSIX_COMMAND_PARSER_KINDS
            or len(record.argv) != 2
        ):
            return None
        path_text = record.argv[1]
        minimum_lines = None
    elif executable == "sed":
        if (
            record.parser_kind not in _POSIX_COMMAND_PARSER_KINDS
            or len(record.argv) != 4
            or record.argv[1] != "-n"
            or record.argv[2] != "1,$p"
        ):
            return None
        complete_skill_read = True
        path_text = record.argv[3]
        minimum_lines = None
    elif executable == "get-content":
        if (
            record.parser_kind != _WINDOWS_POWERSHELL_CORE_PARSER_KIND
            or len(record.argv) != 5
            or record.argv[1] != "-Raw"
            or record.argv[2] != "-Encoding"
            or record.argv[3] != "UTF8"
        ):
            return None
        path_text = record.argv[4]
        minimum_lines = None
    else:
        return None
    validated = validated_skill_read(
        path_text,
        record.aggregated_output,
        skill_source=skill_source,
        skill_read_content_source=skill_read_content_source,
        exact_workspace_relative_syntax=(
            "posix"
            if executable == "cat"
            else "windows" if executable == "get-content" else None
        ),
        allow_one_terminal_newline=(executable == "get-content"),
    )
    if validated is None:
        return None
    relative, content = validated
    if executable == "sed" and complete_skill_read and relative != "SKILL.md":
        return None
    if minimum_lines is not None and minimum_lines < len(content.splitlines()):
        return None
    return relative


def allowed_skill_bootstrap_read(
    record: CodexCommandRecord,
    *,
    skill_source: Path,
    skill_read_content_source: Path | None = None,
) -> str | None:
    """Accept only the host's length-check plus complete initial SKILL.md read.

    The model cannot follow instructions inside ``SKILL.md`` before loading it.
    Codex may therefore bootstrap that first load with ``wc -l ... && sed ...``.
    Keeping the shape exact prevents this exception from authorizing compound
    reference reads, gateway calls, arbitrary commands, or partial content.
    """

    if record.parser_kind not in _POSIX_COMMAND_PARSER_KINDS:
        return None
    argv = record.argv
    if (
        len(argv) != 8
        or Path(argv[0]).name.lower() != "wc"
        or argv[1] != "-l"
        or argv[3] != "&&"
        or Path(argv[4]).name.lower() != "sed"
        or argv[5] != "-n"
        or argv[2] != argv[7]
    ):
        return None
    range_match = re.fullmatch(r"1,(\d+)p", argv[6])
    output_match = re.fullmatch(r"\s*(\d+)\s+([^\n]+)\n([\s\S]*)", record.aggregated_output)
    if range_match is None or output_match is None or output_match.group(2) != argv[2]:
        return None
    content = output_match.group(3)
    validated = validated_skill_read(
        argv[2],
        content,
        skill_source=skill_source,
        skill_read_content_source=skill_read_content_source,
    )
    if validated is None:
        return None
    relative, expected_content = validated
    if (
        relative != "SKILL.md"
        or int(range_match.group(1)) < len(expected_content.splitlines())
        or int(output_match.group(1)) != expected_content.count("\n")
    ):
        return None
    return relative


def validated_skill_read(
    path_text: str,
    aggregated_output: str,
    *,
    skill_source: Path,
    skill_read_content_source: Path | None = None,
    exact_workspace_relative_syntax: str | None = None,
    allow_one_terminal_newline: bool = False,
) -> tuple[str, str] | None:
    """Prove a complete approved Skill read from one closed locator."""

    workspace_path_text = path_text
    windows_absolute = PureWindowsPath(path_text).is_absolute()
    host_absolute = Path(path_text).is_absolute()
    if (
        exact_workspace_relative_syntax == "windows"
        and not windows_absolute
        and not host_absolute
    ):
        if "/" in path_text or path_text.startswith("\\") or ":" in path_text:
            return None
        windows_parts = tuple(re.split(r"\\+", path_text))
        if not windows_parts or any(part in {"", ".."} for part in windows_parts):
            return None
        workspace_path_text = "\\".join(windows_parts)
    candidate = Path(path_text)
    if ".." in candidate.parts:
        return None
    locator = Path(skill_source).expanduser()
    content_source = (
        Path(skill_read_content_source).expanduser()
        if skill_read_content_source is not None
        else locator
    )
    if not candidate.is_absolute():
        workspace_reads = _WORKSPACE_SKILL_READS_BY_SYNTAX.get(
            exact_workspace_relative_syntax or ""
        )
        relative_parts = (
            workspace_reads.get(workspace_path_text)
            if workspace_reads is not None
            else None
        )
        source_parts = tuple(part.casefold() for part in locator.parts[-3:])
        if (
            relative_parts is None
            or source_parts != (".agents", "skills", "waapi-skill")
        ):
            return None
        relative = PurePosixPath(*relative_parts).as_posix()
    elif skill_read_content_source is not None:
        # Archive replay may run after the detached Windows install has been
        # replaced by an attestation file.  Authorize only one exact lexical
        # allowed path below that fixed locator; do not normalize traversal or
        # infer another root from the archived command.
        matching = tuple(
            relative
            for relative in _ALLOWED_SKILL_READS
            if candidate == locator.joinpath(*PurePosixPath(relative).parts)
        )
        if len(matching) != 1:
            return None
        relative = matching[0]
    else:
        try:
            resolved = candidate.resolve(strict=True)
            relative = resolved.relative_to(locator.resolve(strict=True)).as_posix()
        except (OSError, ValueError):
            return None
    if relative not in _ALLOWED_SKILL_READS:
        return None
    try:
        content_root = content_source.resolve(strict=True)
        resolved_content = content_root.joinpath(
            *PurePosixPath(relative).parts
        ).resolve(strict=True)
        resolved_content.relative_to(content_root)
        raw_content = resolved_content.read_bytes().decode(
            "utf-8", errors="strict"
        )
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    content = raw_content.replace("\r\n", "\n").replace("\r", "\n")
    observed = aggregated_output.replace("\r\n", "\n").replace("\r", "\n")
    if observed != content and not (
        allow_one_terminal_newline and observed == content + "\n"
    ):
        return None
    return relative, content


def direct_waapi_command(record: CodexCommandRecord) -> bool:
    lowered = record.command.lower()
    patterns = (
        r"\bwaapiclient\b",
        r"\bfrom\s+waapi\s+import\b",
        r"\bimport\s+waapi\b",
        r"\bwwise_waapi\.dispatcher\b",
        r"\b(?:curl|wget)\b[^\n]*\bwaapi\b",
        r"\b(?:websocket|websockets|autobahn)\b",
        r"\bws://[^\s]+/waapi\b",
    )
    return any(re.search(pattern, lowered) for pattern in patterns)


def write_like_command(record: CodexCommandRecord) -> bool:
    if record.has_shell_operators:
        return True
    if not record.argv:
        return False
    executable = Path(record.argv[0]).name.lower()
    if executable in {"apply_patch", "tee", "touch", "mkdir", "cp", "mv", "rm", "install", "dd", "printf", "echo"}:
        return True
    if executable == "sed" and any(value == "-i" or value.startswith("-i") for value in record.argv[1:]):
        return True
    if executable in {"perl", "ruby"} and any(value in {"-e", "-i"} or value.startswith("-i") for value in record.argv[1:]):
        return True
    return False


def discovery_command(record: CodexCommandRecord) -> bool:
    if not record.argv:
        return False
    executable = Path(record.argv[0]).name.lower()
    if executable in {"rg", "grep", "find", "ls", "fd", "tree", "locate", "which"}:
        return True
    return executable == "command" and "-v" in record.argv[1:]


def final_agent_message(events: Sequence[Mapping[str, Any]]) -> str:
    for event in reversed(events):
        item = event.get("item")
        if event.get("type") != "item.completed" or not isinstance(item, Mapping):
            continue
        if item.get("type") == "agent_message" and isinstance(item.get("text"), str):
            return item["text"]
    return ""


def first_gateway_backed_agent_message(
    stdout: str,
    *,
    validated_gateway_commands: Sequence[str],
) -> str | None:
    """Return the first visible reply after the first validated gateway result.

    The caller supplies commands already accepted as gateway results by the
    common grader.  We intentionally inspect only completed ``agent_message``
    items after the first matching completed command, rather than searching raw
    stdout or falling back to the final response.  A later message therefore
    cannot satisfy a first-response contract retroactively.
    """

    gateway_commands = frozenset(str(command) for command in validated_gateway_commands)
    if not gateway_commands:
        return None

    first_gateway_completed = False
    for event in parse_jsonl_events(stdout):
        item = event.get("item")
        if event.get("type") != "item.completed" or not isinstance(item, Mapping):
            continue
        if (
            item.get("type") == "command_execution"
            and item.get("command") in gateway_commands
        ):
            first_gateway_completed = True
            continue
        if (
            first_gateway_completed
            and item.get("type") == "agent_message"
            and isinstance(item.get("text"), str)
        ):
            return item["text"]
    return None


def turn_usage(events: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    for event in reversed(events):
        usage = event.get("usage")
        if event.get("type") == "turn.completed" and isinstance(usage, Mapping):
            return {str(key): int(value) for key, value in usage.items() if isinstance(value, int)}
    return {}


def snapshot_workspace(
    root: Path,
    *,
    exclude_names: Sequence[str] = (),
) -> dict[str, str]:
    """Hash final file state and link targets without following Skill symlinks.

    File bytes are the portable change boundary.  On filesystems where ctime
    advances for metadata changes, it also records an otherwise-restored
    write.  Where ctime is creation time, an identical restored final state
    intentionally remains identical.
    """

    resolved = root.expanduser().resolve(strict=True)
    excluded = frozenset(str(name) for name in exclude_names)
    snapshot: dict[str, str] = {}
    for directory, dirnames, filenames in os.walk(resolved, followlinks=False):
        directory_path = Path(directory)
        retained_dirnames: list[str] = []
        for name in dirnames:
            if name in excluded:
                continue
            path = directory_path / name
            if path.is_symlink():
                relative = path.relative_to(resolved).as_posix()
                metadata = path.lstat()
                snapshot[relative] = hashlib.sha256(
                    b"symlink\0"
                    + f"{stat.S_IMODE(metadata.st_mode)}\0{metadata.st_ctime_ns}\0".encode("ascii")
                    + os.readlink(path).encode("utf-8", errors="surrogateescape")
                ).hexdigest()
            else:
                retained_dirnames.append(name)
        dirnames[:] = retained_dirnames
        for filename in filenames:
            if filename in excluded:
                continue
            path = directory_path / filename
            relative = path.relative_to(resolved).as_posix()
            if path.is_symlink():
                metadata = path.lstat()
                snapshot[relative] = hashlib.sha256(
                    b"symlink\0"
                    + f"{stat.S_IMODE(metadata.st_mode)}\0{metadata.st_ctime_ns}\0".encode("ascii")
                    + os.readlink(path).encode("utf-8", errors="surrogateescape")
                ).hexdigest()
                continue
            if not path.is_file():
                continue
            metadata = path.stat()
            snapshot[relative] = hashlib.sha256(
                b"file\0"
                + (
                    f"{stat.S_IMODE(metadata.st_mode)}\0{metadata.st_size}\0"
                    f"{metadata.st_mtime_ns}\0{metadata.st_ctime_ns}\0"
                ).encode("ascii")
                + path.read_bytes()
            ).hexdigest()
    return snapshot


def snapshot_tree_hash(snapshot: Mapping[str, str]) -> str:
    digest = hashlib.sha256()
    for path, file_hash in sorted(snapshot.items()):
        digest.update(path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_hash.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def workspace_changes(before: Mapping[str, str], after: Mapping[str, str]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    created = tuple(sorted(set(after) - set(before)))
    modified = tuple(sorted(path for path in set(before) & set(after) if before[path] != after[path]))
    return created, modified


__all__ = [
    "CodexCliHarness",
    "CodexCommandRecord",
    "CodexCommandFacts",
    "CodexEnvironmentAudit",
    "CodexHarnessConfig",
    "CodexHarnessError",
    "CodexInfrastructureError",
    "CodexInfrastructureFailure",
    "CodexIsolationAudit",
    "CodexPromptAudit",
    "CodexRunResult",
    "CodexSessionAudit",
    "ProcessResult",
    "WindowsPowerShellCoreHost",
    "WORKSPACE_SKILL_EXCLUDED_NAMES",
    "assert_detached_workspace_skill_copy",
    "audit_prompt_input_payload",
    "audit_session_events",
    "build_exec_command",
    "build_prompt_audit_command",
    "classify_commands",
    "classify_task_commands",
    "classify_codex_infrastructure_failure",
    "codex_process_environment",
    "codex_runtime_files",
    "codex_error_messages",
    "completed_command_records",
    "completed_commands",
    "count_invalid_jsonl_lines",
    "discover_codex_binary",
    "enforce_windows_console_utf8",
    "discover_windows_powershell_core",
    "discover_windows_user_skill_paths",
    "final_agent_message",
    "first_gateway_backed_agent_message",
    "gateway_continuation_binding_errors",
    "gateway_runtime_apis",
    "inspect_isolated_environment",
    "is_link_or_junction",
    "is_protected_environment_key",
    "isolated_codex_environment",
    "kill_process_group",
    "normalized_gateway_command_argv",
    "parse_jsonl_events",
    "parse_command_argv",
    "powershell_core_host_fingerprint",
    "probe_windows_powershell_core",
    "prepare_workspace_skill_install",
    "prompt_skill_inventory",
    "resolve_codex_binary",
    "run_process",
    "snapshot_workspace",
    "snapshot_tree_hash",
    "subprocess_process_group_options",
    "taskkill_process_tree",
    "turn_usage",
    "validate_codex_version_output",
    "validate_powershell_core_probe_output",
    "verify_workspace_skill_install",
    "workspace_changes",
    "workspace_skill_install_path",
    "workspace_skill_tree_sha256",
]
