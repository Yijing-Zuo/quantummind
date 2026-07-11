@echo off
REM Wrapper for a recommended first slice. No API keys are stored in this file.
setlocal
set "RUN_SUBSET=registry_v1_probes"
set "START_INDEX=1"
set "END_INDEX=50"
set "SHARD_ID="
call "%~dp0run_shard.bat"
exit /b %ERRORLEVEL%
