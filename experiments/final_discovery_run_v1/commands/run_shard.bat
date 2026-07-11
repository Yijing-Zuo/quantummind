@echo off
REM Run one final discovery shard. No API keys are stored in this file.
setlocal
if "%OPENAI_API_KEY%"=="" (
  echo OPENAI_API_KEY must be set in the environment.
  exit /b 1
)
if "%PYTHON%"=="" set "PYTHON=python"
set "FINAL_MANIFEST=experiments\final_discovery_run_v1\manifests\master_run_manifest.csv"
set "FINAL_LOG_DIR=experiments\final_discovery_run_v1\logs"
echo WARNING: this runs OpenAI live analyze/benchmark commands and may incur cost.
echo Probe positives are query/subroutine hypotheses, not end-to-end speedup claims.
if "%SHARD_ID%"=="" (
  if "%START_INDEX%"=="" set "START_INDEX=1"
  if "%END_INDEX%"=="" set "END_INDEX=50"
)
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference = 'Stop'; $manifest = $env:FINAL_MANIFEST; if (-not (Test-Path -LiteralPath $manifest)) { throw ('Missing manifest: {0}' -f $manifest) }; $logDir = $env:FINAL_LOG_DIR; New-Item -ItemType Directory -Force -Path $logDir | Out-Null; $rows = @(Import-Csv -LiteralPath $manifest | Where-Object { $_.status -eq 'READY' }); if (-not [string]::IsNullOrWhiteSpace($env:RUN_SUBSET)) { $rows = @($rows | Where-Object { $_.subset -eq $env:RUN_SUBSET }) }; if (-not [string]::IsNullOrWhiteSpace($env:SHARD_ID)) { $rows = @($rows | Where-Object { $_.shard_id -eq $env:SHARD_ID }) } else { $start=[int]$env:START_INDEX; $end=[int]$env:END_INDEX; $i=0; $rows = @($rows | Where-Object { $i += 1; $i -ge $start -and $i -le $end }) }; if ($rows.Count -eq 0) { throw 'No READY rows matched the requested shard/range.' }; foreach ($r in $rows) {;   $inputPath = [string]$r.input_path;   if ([string]::IsNullOrWhiteSpace($inputPath) -or -not (Test-Path -LiteralPath $inputPath)) { Write-Host ('SKIP missing input {0}: {1}' -f $r.global_task_id, $inputPath); continue };   New-Item -ItemType Directory -Force -Path ([string]$r.output_dir) | Out-Null;   $stdout = Join-Path $logDir ($r.global_task_id + '.stdout.log');   $stderr = Join-Path $logDir ($r.global_task_id + '.stderr.log');   $cmdArgs = @('-m','quantummindlite.cli');   if ($r.kind -eq 'benchmark') { $cmdArgs += @('benchmark','--case-id',[string]$r.card_id) } else { $cmdArgs += @('analyze','--input',$inputPath) };   $cmdArgs += @('--provider','openai','--reasoning-effort',[string]$r.reasoning_effort,'--output-dir',[string]$r.output_dir);   if (-not [string]::IsNullOrWhiteSpace([string]$r.timeout)) { $cmdArgs += @('--timeout',[string]$r.timeout) };   Write-Host ('RUN {0} {1} {2}' -f $r.global_task_id, $r.kind, $inputPath);   & $env:PYTHON @cmdArgs > $stdout 2> $stderr;   if ($LASTEXITCODE -ne 0) { Write-Host ('FAILED {0}; see {1} and {2}' -f $r.global_task_id, $stdout, $stderr); exit $LASTEXITCODE }; }"
exit /b %ERRORLEVEL%
