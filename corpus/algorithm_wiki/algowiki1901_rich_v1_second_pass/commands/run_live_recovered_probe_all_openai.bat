@echo off
REM Run live recovered probe all with OpenAI
REM No API keys are stored in this file.
setlocal
if "%OPENAI_API_KEY%"=="" (
  echo OPENAI_API_KEY must be set in the environment.
  exit /b 1
)
if "%PYTHON%"=="" set "PYTHON=python"
set "QML_MANIFEST=corpus\algorithm_wiki\algowiki1901_rich_v1_second_pass\manifests\recovered_probe.csv"
set "QML_PATH_COLUMN=public_probe_path"
set "QML_ID_COLUMN=probe_id"
set "QML_REASONING_EFFORT=high"
set "QML_OUTPUT_DIR=runs\algowiki_recovered_probe_all"
echo WARNING: this runs OpenAI live analyze and may incur cost.
echo Probe positives are query/subroutine hypotheses, not end-to-end claims.
if /I not "%CONFIRM_LIVE_ALL%"=="YES" (
  echo Set CONFIRM_LIVE_ALL=YES after reviewing cost and quota.
  exit /b 1
)
set "START_INDEX=1"
set "END_INDEX=999999"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference = 'Stop'; $manifest = $env:QML_MANIFEST; if (-not (Test-Path -LiteralPath $manifest)) { throw ('Missing manifest: {0}' -f $manifest) }; $rows = @(Import-Csv -LiteralPath $manifest); $start = [int]$env:START_INDEX; $end = [int]$env:END_INDEX; $current = 0; foreach ($r in $rows) {;   $current += 1;   if ($current -lt $start -or $current -gt $end) { continue };   $cardProp = $r.PSObject.Properties[$env:QML_PATH_COLUMN];   if ($null -eq $cardProp) { throw ('Missing column: {0}' -f $env:QML_PATH_COLUMN) };   $card = [string]$cardProp.Value;   $id = 'row-' + $current;   $idProp = $r.PSObject.Properties[$env:QML_ID_COLUMN];   if ($null -ne $idProp -and -not [string]::IsNullOrWhiteSpace([string]$idProp.Value)) { $id = [string]$idProp.Value };   if ([string]::IsNullOrWhiteSpace($card)) { throw ('Missing {0} for {1}' -f $env:QML_PATH_COLUMN, $id) };   if (-not (Test-Path -LiteralPath $card)) { throw ('Missing card path for {0}: {1}' -f $id, $card) };   Write-Host ('RUN {0} {1}' -f $id, $card);   & $env:PYTHON -m quantummindlite.cli analyze --input $card --provider openai --reasoning-effort $env:QML_REASONING_EFFORT --output-dir $env:QML_OUTPUT_DIR;   if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }; }"
exit /b %ERRORLEVEL%
