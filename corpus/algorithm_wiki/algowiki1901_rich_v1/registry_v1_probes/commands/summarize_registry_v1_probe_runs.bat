@echo off
REM Summarize registry-v1 probe runs. No API keys are stored in this file.
setlocal
if "%PYTHON%"=="" set "PYTHON=python"
"%PYTHON%" scripts\datasets\summarize_qml_discovery_runs.py --kind probe --run-dir runs --manifest "corpus\algorithm_wiki\algowiki1901_rich_v1\registry_v1_probes\manifests\ready_public_probe_registry_v1.csv" --out-csv "corpus\algorithm_wiki\algowiki1901_rich_v1\registry_v1_probes\reports\registry_v1_probe_run_summary.csv" --out-md "corpus\algorithm_wiki\algowiki1901_rich_v1\registry_v1_probes\reports\registry_v1_probe_run_summary.md"
