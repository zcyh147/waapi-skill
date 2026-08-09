@echo off
setlocal EnableExtensions
call poetry --directory "%~dp0.." run -- python "%~dp0test_driver.py" %*
exit /b %ERRORLEVEL%
