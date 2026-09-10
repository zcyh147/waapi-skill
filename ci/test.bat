@echo off
setlocal EnableExtensions
if not defined WAAPI_TEST_PYTHON goto :poetry
if not exist "%WAAPI_TEST_PYTHON%" (
  echo TEST_ENVIRONMENT_BLOCKED: WAAPI_TEST_PYTHON does not exist: %WAAPI_TEST_PYTHON% 1>&2
  exit /b 4
)
"%WAAPI_TEST_PYTHON%" "%~dp0test_driver.py" %*
exit /b %ERRORLEVEL%
:poetry
call poetry --directory "%~dp0.." run -- python "%~dp0test_driver.py" %*
exit /b %ERRORLEVEL%
