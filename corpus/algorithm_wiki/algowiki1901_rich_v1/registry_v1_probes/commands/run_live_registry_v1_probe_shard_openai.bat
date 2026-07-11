@echo off
REM Run live registry-v1 probe shard with OpenAI
REM No API keys are stored in this file.
setlocal
if "%OPENAI_API_KEY%"=="" (
  echo OPENAI_API_KEY must be set in the environment.
  exit /b 1
)
if "%PYTHON%"=="" set "PYTHON=python"
set "QML_MANIFEST=corpus\algorithm_wiki\algowiki1901_rich_v1\registry_v1_probes\manifests\ready_public_probe_registry_v1.csv"
set "QML_PATH_COLUMN=public_probe_path"
set "QML_ID_COLUMN=probe_id"
set "QML_REASONING_EFFORT=high"
set "QML_OUTPUT_DIR=runs\registry_v1_probe_%START_INDEX%_%END_INDEX%"
echo WARNING: this runs OpenAI live analyze and may incur cost.
echo Registry-v1 probe positives are query/subroutine hypotheses, not end-to-end speedup claims.
if "%START_INDEX%"=="" set "START_INDEX=1"
if "%END_INDEX%"=="" set "END_INDEX=50"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference = 'Stop'; $manifest = $env:QML_MANIFEST; if (-not (Test-Path -LiteralPath $manifest)) { throw ('Missing manifest: {0}' -f $manifest) }; $rows = @(Import-Csv -LiteralPath $manifest); $start = [int]$env:START_INDEX; $end = [int]$env:END_INDEX; $current = 0; foreach ($r in $rows) {;   $current += 1;   if ($current -lt $start -or $current -gt $end) { continue };   $card = [string]$r.PSObject.Properties[$env:QML_PATH_COLUMN].Value;   $id = [string]$r.PSObject.Properties[$env:QML_ID_COLUMN].Value;   if ([string]::IsNullOrWhiteSpace($id)) { $id = 'row-' + $current };   if ([string]::IsNullOrWhiteSpace($card)) { throw ('Missing card path for {0}' -f $id) };   if (-not (Test-Path -LiteralPath $card)) { throw ('Missing card path for {0}: {1}' -f $id, $card) };   Write-Host ('RUN {0} {1}' -f $id, $card);   & $env:PYTHON -m quantummindlite.cli analyze --input $card --provider openai --reasoning-effort $env:QML_REASONING_EFFORT --output-dir $env:QML_OUTPUT_DIR;   if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }; }"
exit /b %ERRORLEVEL%
