@echo off
setlocal EnableExtensions

set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..") do set "ROOT_DIR=%%~fI"
set "SKILL_DIR=%ROOT_DIR%\skills\waapi-skill"
set "DEFAULT_SANDBOX_BASE=%ROOT_DIR%\.sisyphus\runtime\wwise-waapi-sandboxes"

if defined PYTHONPATH (
    set "PYTHONPATH=%SKILL_DIR%;%PYTHONPATH%"
) else (
    set "PYTHONPATH=%SKILL_DIR%"
)

set "INITIAL_WWISE_CONSOLE=%WWISE_CONSOLE%"
set "INITIAL_WWISE_SAMPLE_PROJECT_PATH=%WWISE_SAMPLE_PROJECT_PATH%"
set "INITIAL_WWISE_SANDBOX_ROOT=%WWISE_SANDBOX_ROOT%"
set "HAS_INITIAL_WWISE_CONSOLE=0"
set "HAS_INITIAL_WWISE_SAMPLE_PROJECT_PATH=0"
set "HAS_INITIAL_WWISE_SANDBOX_ROOT=0"

if defined WWISE_CONSOLE set "HAS_INITIAL_WWISE_CONSOLE=1"
if defined WWISE_SAMPLE_PROJECT_PATH set "HAS_INITIAL_WWISE_SAMPLE_PROJECT_PATH=1"
if defined WWISE_SANDBOX_ROOT set "HAS_INITIAL_WWISE_SANDBOX_ROOT=1"

set "VERSION="
set "MODE="
set "PYTEST_EXTRA_ARGS="
set "AFTER_DASHDASH=0"
set "POSITIONAL_COUNT=0"

if "%~1"=="--help" goto usage_and_exit
if "%~1"=="-h" goto usage_and_exit

:parse_args
if "%~1"=="" goto args_done

if "%AFTER_DASHDASH%"=="1" (
    call :append_pytest_arg "%~1"
    shift
    goto parse_args
)

if "%~1"=="-h" goto usage_and_exit
if "%~1"=="--help" goto usage_and_exit

if "%~1"=="-v" (
    if "%~2"=="" goto missing_version_value
    set "VERSION=%~2"
    shift
    shift
    goto parse_args
)

if "%~1"=="--version" (
    if "%~2"=="" goto missing_version_value
    set "VERSION=%~2"
    shift
    shift
    goto parse_args
)

if "%~1"=="-m" (
    if "%~2"=="" goto missing_mode_value
    set "MODE=%~2"
    shift
    shift
    goto parse_args
)

if "%~1"=="--mode" (
    if "%~2"=="" goto missing_mode_value
    set "MODE=%~2"
    shift
    shift
    goto parse_args
)

if "%~1"=="--" (
    set "AFTER_DASHDASH=1"
    shift
    goto parse_args
)

set "CURRENT_ARG=%~1"
if "%CURRENT_ARG:~0,1%"=="-" goto unknown_option

if "%POSITIONAL_COUNT%"=="0" (
    set "VERSION=%~1"
    set "POSITIONAL_COUNT=1"
    shift
    goto parse_args
)

if "%POSITIONAL_COUNT%"=="1" (
    set "MODE=%~1"
    set "POSITIONAL_COUNT=2"
    shift
    goto parse_args
)

echo Unsupported positional argument: %~1 1>&2
goto usage_error

:args_done
if not defined MODE (
    echo Mode is required ^(use --mode or positional form^). 1>&2
    goto usage_error
)

if /I "%MODE%"=="nonlive" if not defined VERSION set "VERSION=none"
if /I "%MODE%"=="default" if not defined VERSION set "VERSION=none"
if /I "%MODE%"=="all" if not defined VERSION set "VERSION=all"
if /I "%MODE%"=="matrix" if not defined VERSION set "VERSION=all"
if /I "%MODE%"=="focused" if not defined VERSION set "VERSION=all"

if not defined VERSION (
    echo Version is required for mode '%MODE%' ^(use --version or positional form^). 1>&2
    goto usage_error
)

call :validate_mode "%MODE%"
if errorlevel 1 exit /b %errorlevel%

call :validate_version "%VERSION%"
if errorlevel 1 exit /b %errorlevel%

if /I "%MODE%"=="nonlive" goto dispatch_nonlive
if /I "%MODE%"=="default" goto dispatch_nonlive
if /I "%MODE%"=="all" goto dispatch_all
if /I "%MODE%"=="smoke" call :run_smoke_dispatch
if /I "%MODE%"=="smoke" exit /b %ERRORLEVEL%
if /I "%MODE%"=="live" goto dispatch_live
if /I "%MODE%"=="destructive" goto dispatch_destructive
if /I "%MODE%"=="matrix" goto dispatch_matrix
if /I "%MODE%"=="focused" goto dispatch_matrix

echo Unsupported mode: %MODE% 1>&2
goto usage_error

:dispatch_nonlive
call :run_nonlive
exit /b %ERRORLEVEL%

:run_smoke_dispatch
if /I "%VERSION%"=="all" (
    for %%V in (2021.1 2022.1 2023.1 2024.1 2025.1) do (
        call :run_smoke_for_version "%%V"
        if errorlevel 1 exit /b %ERRORLEVEL%
    )
    exit /b 0
)
call :run_smoke_for_version "%VERSION%"
exit /b %ERRORLEVEL%

:dispatch_all
if /I not "%VERSION%"=="all" (
    echo all mode requires version 'all' 1>&2
    exit /b 1
)
call :run_nonlive
if errorlevel 1 exit /b %ERRORLEVEL%
call :run_matrix_all
exit /b %ERRORLEVEL%

:dispatch_live
if /I "%VERSION%"=="all" (
    for %%V in (2021.1 2023.1 2024.1 2025.1) do (
        call :run_live_for_version "%%V"
        if errorlevel 1 exit /b %ERRORLEVEL%
    )
    exit /b 0
)
call :run_live_for_version "%VERSION%"
exit /b %ERRORLEVEL%

:dispatch_destructive
if /I "%VERSION%"=="all" (
    for %%V in (2021.1 2023.1 2024.1 2025.1) do (
        call :run_destructive_for_version "%%V"
        if errorlevel 1 exit /b %ERRORLEVEL%
    )
    exit /b 0
)
call :run_destructive_for_version "%VERSION%"
exit /b %ERRORLEVEL%

:dispatch_matrix
if /I not "%VERSION%"=="all" (
    echo matrix/focused mode requires version 'all' 1>&2
    exit /b 1
)
call :run_matrix_all
exit /b %ERRORLEVEL%

:append_pytest_arg
if defined PYTEST_EXTRA_ARGS (
    set "PYTEST_EXTRA_ARGS=%PYTEST_EXTRA_ARGS% %~1"
) else (
    set "PYTEST_EXTRA_ARGS=%~1"
)
exit /b 0

:validate_mode
set "CHECK_MODE=%~1"
if /I "%CHECK_MODE%"=="nonlive" exit /b 0
if /I "%CHECK_MODE%"=="default" exit /b 0
if /I "%CHECK_MODE%"=="all" exit /b 0
if /I "%CHECK_MODE%"=="smoke" exit /b 0
if /I "%CHECK_MODE%"=="live" exit /b 0
if /I "%CHECK_MODE%"=="destructive" exit /b 0
if /I "%CHECK_MODE%"=="matrix" exit /b 0
if /I "%CHECK_MODE%"=="focused" exit /b 0
echo Unsupported mode: %CHECK_MODE% 1>&2
goto usage_error

:validate_version
set "CHECK_VERSION=%~1"
if "%CHECK_VERSION%"=="2021.1" exit /b 0
if "%CHECK_VERSION%"=="2022.1" exit /b 0
if "%CHECK_VERSION%"=="2023.1" exit /b 0
if "%CHECK_VERSION%"=="2024.1" exit /b 0
if "%CHECK_VERSION%"=="2025.1" exit /b 0
if "%CHECK_VERSION%"=="all" exit /b 0
if "%CHECK_VERSION%"=="none" exit /b 0
echo Unsupported version: %CHECK_VERSION% 1>&2
goto usage_error

:resolve_version_paths
set "RESOLVED_CONSOLE="
set "RESOLVED_PROJECT="
if "%~1"=="2021.1" set "RESOLVED_BUILD=2021.1.14.8108"
if "%~1"=="2022.1" set "RESOLVED_BUILD=2022.1.19.8584"
if "%~1"=="2023.1" set "RESOLVED_BUILD=2023.1.19.8928"
if "%~1"=="2024.1" set "RESOLVED_BUILD=2024.1.13.9056"
if "%~1"=="2025.1" set "RESOLVED_BUILD=2025.1.7.9143"
if not defined RESOLVED_BUILD (
    echo Unsupported version: %~1 1>&2
    exit /b 1
)
set "RESOLVED_CONSOLE=C:\Audiokinetic\Wwise%RESOLVED_BUILD%\Authoring\x64\Release\bin\WwiseConsole.exe"
set "RESOLVED_PROJECT=C:\Audiokinetic\SampleProject%RESOLVED_BUILD%\SampleProject\SampleProject.wproj"
exit /b 0

:set_version_environment
call :resolve_version_paths "%~1"
if errorlevel 1 exit /b %ERRORLEVEL%

set "WWISE_VERSION=%~1"
if "%HAS_INITIAL_WWISE_CONSOLE%"=="1" (
    set "WWISE_CONSOLE=%INITIAL_WWISE_CONSOLE%"
) else (
    set "WWISE_CONSOLE=%RESOLVED_CONSOLE%"
)

if "%HAS_INITIAL_WWISE_SAMPLE_PROJECT_PATH%"=="1" (
    set "WWISE_SAMPLE_PROJECT_PATH=%INITIAL_WWISE_SAMPLE_PROJECT_PATH%"
) else (
    set "WWISE_SAMPLE_PROJECT_PATH=%RESOLVED_PROJECT%"
)

if "%HAS_INITIAL_WWISE_SANDBOX_ROOT%"=="1" (
    set "WWISE_SANDBOX_ROOT=%INITIAL_WWISE_SANDBOX_ROOT%"
) else (
    set "WWISE_SANDBOX_ROOT=%DEFAULT_SANDBOX_BASE%\%~1-%~2"
)
exit /b 0

:print_context
echo == Test Context ==
echo version:      %~1
echo mode:         %~2
if defined WWISE_CONSOLE (
    echo console:      %WWISE_CONSOLE%
) else (
    echo console:      ^<unset^>
)
if defined WWISE_SAMPLE_PROJECT_PATH (
    echo project:      %WWISE_SAMPLE_PROJECT_PATH%
) else (
    echo project:      ^<unset^>
)
if defined WWISE_SANDBOX_ROOT (
    echo sandbox_root: %WWISE_SANDBOX_ROOT%
) else (
    echo sandbox_root: ^<unset^>
)
if defined PYTEST_EXTRA_ARGS (
    echo pytest args:  %PYTEST_EXTRA_ARGS%
) else (
    echo pytest args:  ^<none^>
)
echo.
exit /b 0

:set_mode_flags
set "WWISE_LIVE=0"
set "WWISE_DESTRUCTIVE=0"
set "WWISE_STRICT_REAL=0"

if /I "%~1"=="live" (
    set "WWISE_LIVE=1"
    set "WWISE_STRICT_REAL=1"
)
if /I "%~1"=="destructive" (
    set "WWISE_LIVE=1"
    set "WWISE_DESTRUCTIVE=1"
    set "WWISE_STRICT_REAL=1"
)
if /I "%~1"=="smoke" (
    set "WWISE_LIVE=1"
    set "WWISE_STRICT_REAL=1"
)
exit /b 0

:require_real_prerequisites
if not "%WWISE_STRICT_REAL%"=="1" exit /b 0
if not defined WWISE_CONSOLE (
    echo Strict real %~2 for %~1 requires WWISE_CONSOLE to be set 1>&2
    exit /b 1
)
if not exist "%WWISE_CONSOLE%" (
    echo Strict real %~2 for %~1 requires executable WWISE_CONSOLE: %WWISE_CONSOLE% 1>&2
    exit /b 1
)
if not defined WWISE_SAMPLE_PROJECT_PATH (
    echo Strict real %~2 for %~1 requires WWISE_SAMPLE_PROJECT_PATH to be set 1>&2
    exit /b 1
)
if not exist "%WWISE_SAMPLE_PROJECT_PATH%" (
    echo Strict real %~2 for %~1 requires an existing .wproj WWISE_SAMPLE_PROJECT_PATH: %WWISE_SAMPLE_PROJECT_PATH% 1>&2
    exit /b 1
)
if /I not "%WWISE_SAMPLE_PROJECT_PATH:~-6%"==".wproj" (
    echo Strict real %~2 for %~1 requires an existing .wproj WWISE_SAMPLE_PROJECT_PATH: %WWISE_SAMPLE_PROJECT_PATH% 1>&2
    exit /b 1
)
exit /b 0

:run_pytest_with_extra
pushd "%ROOT_DIR%" >nul
call python -m pytest %* %PYTEST_EXTRA_ARGS%
set "RESULT=%ERRORLEVEL%"
popd >nul
exit /b %RESULT%

:run_nonlive
call :set_mode_flags "nonlive"
call :print_context "none" "nonlive"
call :run_pytest_with_extra -m "not live and not destructive"
exit /b %ERRORLEVEL%

:run_smoke_for_version
call :set_version_environment "%~1" "smoke"
if errorlevel 1 exit /b %ERRORLEVEL%
call :set_mode_flags "smoke"
call :require_real_prerequisites "%~1" "smoke"
if errorlevel 1 exit /b %ERRORLEVEL%
call :print_context "%~1" "smoke"
pushd "%ROOT_DIR%" >nul
call python "%ROOT_DIR%\ci\wwise_smoke.py"
set "RESULT=%ERRORLEVEL%"
popd >nul
exit /b %RESULT%

:run_live_for_version
call :set_version_environment "%~1" "live"
if errorlevel 1 exit /b %ERRORLEVEL%
call :set_mode_flags "live"
call :require_real_prerequisites "%~1" "live"
if errorlevel 1 exit /b %ERRORLEVEL%
call :print_context "%~1" "live"

if "%~1"=="2021.1" (
    call :run_pytest_with_extra tests/live/test_2021_1_live_prerequisites.py::test_2021_1_live_read_only_prerequisites_validate_exact_get_info_before_matrix tests/live/test_2021_1_reflection_prerequisites.py::test_2021_1_live_reflection_prerequisites_and_resource_generation tests/live/test_2021_1_object_get_matrix.py::test_2021_1_live_waql_object_get_matrix_runs_read_only_against_sandbox tests/live/test_2021_1_object_topics_sandbox.py::test_2021_1_live_safe_object_topics_against_sandbox
    exit /b %ERRORLEVEL%
)
if "%~1"=="2022.1" (
    echo Focused live matrix is not defined for 2022.1; use smoke mode for this version. 1>&2
    exit /b 1
)
if "%~1"=="2023.1" (
    call :run_pytest_with_extra tests/live/test_2023_reflection_inventory.py::test_2023_live_reflection_inventory_runs_against_sandbox tests/live/test_2023_waql_live_matrix.py::test_2023_live_waql_object_get_matrix_runs_read_only_against_sandbox
    exit /b %ERRORLEVEL%
)
if "%~1"=="2024.1" (
    call :run_pytest_with_extra tests/live/test_2024_reflection_inventory.py::test_2024_live_reflection_inventory_runs_against_sandbox tests/live/test_2024_waql_live_matrix.py::test_2024_live_waql_object_get_matrix_runs_read_only_against_sandbox tests/live/test_2024_object_topics_sandbox.py::test_2024_1_live_safe_object_topics_against_sandbox
    exit /b %ERRORLEVEL%
)
if "%~1"=="2025.1" (
    call :run_pytest_with_extra tests/live/test_2025_1_reflection_inventory.py::test_2025_live_reflection_inventory_runs_against_sandbox tests/live/test_2025_1_waql_live_matrix.py::test_2025_live_waql_object_get_matrix_runs_read_only_against_sandbox tests/live/test_2025_1_object_topics_sandbox.py::test_2025_1_live_safe_object_topics_against_sandbox
    exit /b %ERRORLEVEL%
)

echo Unsupported live version: %~1 1>&2
exit /b 1

:run_destructive_for_version
call :set_version_environment "%~1" "destructive"
if errorlevel 1 exit /b %ERRORLEVEL%
call :set_mode_flags "destructive"
call :require_real_prerequisites "%~1" "destructive"
if errorlevel 1 exit /b %ERRORLEVEL%
call :print_context "%~1" "destructive"

if "%~1"=="2021.1" (
    call :run_pytest_with_extra tests/destructive/test_2021_1_project_mutation_sandbox.py tests/destructive/test_2021_1_soundbank_audio_sandbox.py tests/destructive/test_2021_1_switchcontainer_assignment_sandbox.py
    exit /b %ERRORLEVEL%
)
if "%~1"=="2022.1" (
    echo Focused destructive matrix is not defined for 2022.1; use smoke mode for this version. 1>&2
    exit /b 1
)
if "%~1"=="2023.1" (
    call :run_pytest_with_extra tests/destructive/test_2023_project_mutation_sandbox.py tests/destructive/test_2023_soundbank_audio_sandbox.py tests/destructive/test_2023_switchcontainer_assignment_sandbox.py
    exit /b %ERRORLEVEL%
)
if "%~1"=="2024.1" (
    call :run_pytest_with_extra tests/destructive/test_2024_project_mutation_sandbox.py tests/destructive/test_2024_soundbank_audio_sandbox.py tests/destructive/test_2024_switchcontainer_assignment_sandbox.py
    exit /b %ERRORLEVEL%
)
if "%~1"=="2025.1" (
    call :run_pytest_with_extra tests/destructive/test_2025_1_project_mutation_sandbox.py tests/destructive/test_2025_1_soundbank_audio_sandbox.py tests/destructive/test_2025_1_switchcontainer_assignment_sandbox.py
    exit /b %ERRORLEVEL%
)

echo Unsupported destructive version: %~1 1>&2
exit /b 1

:run_matrix_all
for %%V in (2021.1 2023.1 2024.1 2025.1) do (
    call :run_live_for_version "%%V"
    if errorlevel 1 exit /b %ERRORLEVEL%
    call :run_destructive_for_version "%%V"
    if errorlevel 1 exit /b %ERRORLEVEL%
)
exit /b 0

:missing_version_value
echo Missing value for %~1 1>&2
goto usage_error

:missing_mode_value
echo Missing value for %~1 1>&2
goto usage_error

:unknown_option
echo Unknown option: %~1 1>&2
goto usage_error

:usage_and_exit
call :usage
exit /b 0

:usage_error
call :usage 1>&2
exit /b 1

:usage
echo Usage:
echo   ci\test.bat --version ^<version^> --mode ^<mode^> [-- ^<extra pytest args...^>]
echo   ci\test.bat -v ^<version^> -m ^<mode^> [-- ^<extra pytest args...^>]
echo   ci\test.bat ^<version^> ^<mode^> [-- ^<extra pytest args...^>]  ^(backwards compatible^)
echo.
echo Versions:
echo   2021.1 ^| 2022.1 ^| 2023.1 ^| 2024.1 ^| 2025.1 ^| all ^| none
echo.
echo Modes:
echo   nonlive      Run default non-live test suite
echo   all          Run non-live suite first, then strict real matrix
echo   smoke        Run focused WAAPI getInfo smoke via HeadlessLifecycle
echo   live         Run focused live suite for the selected version
echo   destructive  Run focused destructive suite for the selected version
echo   matrix       Run focused live + destructive sequentially ^(2021.1/2023.1/2024.1/2025.1^)
echo   focused      Alias for matrix
echo.
echo Notes:
echo   - Environment overrides are respected if already set:
echo       WWISE_CONSOLE, WWISE_SAMPLE_PROJECT_PATH, WWISE_SANDBOX_ROOT,
echo       WWISE_STARTUP_TIMEOUT, WWISE_READINESS_TIMEOUT,
echo       WWISE_PROBE_TIMEOUT, WWISE_SHUTDOWN_TIMEOUT
echo   - Default Windows paths if not set:
echo       C:\Audiokinetic\Wwise^<build^>\Authoring\x64\Release\bin\WwiseConsole.exe
echo       C:\Audiokinetic\SampleProject^<build^>\SampleProject\SampleProject.wproj
echo   - Default sandbox root if not set:
echo       .sisyphus\runtime\wwise-waapi-sandboxes\^<version^>-^<mode^>
echo.
echo Examples:
echo   ci\test.bat --version 2021.1 --mode live
echo   ci\test.bat --mode nonlive
echo   ci\test.bat --version all --mode all -- -q -ra
echo   ci\test.bat -v all -m matrix
echo   ci\test.bat --version 2024.1 --mode live -- -k object_topics -q
echo   ci\test.bat 2021.1 live
echo   ci\test.bat 2025.1 destructive
echo   ci\test.bat all matrix
echo   ci\test.bat all smoke
echo   ci\test.bat none nonlive
echo   ci\test.bat 2022.1 smoke -- -q
exit /b 0
