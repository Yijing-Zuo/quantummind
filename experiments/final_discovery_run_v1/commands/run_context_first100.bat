@echo off
REM Wrapper for a recommended first slice. No API keys are stored in this file.
setlocal
set "RUN_SUBSET=public_context_v1"
set "START_INDEX=1"
set "END_INDEX=100"
set "SHARD_ID="
call "%~dp0run_shard.bat"
exit /b %ERRORLEVEL%
