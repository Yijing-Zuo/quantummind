@echo off
REM No API keys are stored in this file.
python scripts\datasets\summarize_qml_discovery_runs.py --kind context --run-dir runs --manifest "corpus\algorithm_wiki\algowiki1901_rich_v1_second_pass\manifests\recovered_context.csv" --out-csv "corpus\algorithm_wiki\algowiki1901_rich_v1_second_pass\reports\recovered_context_run_summary.csv" --out-md "corpus\algorithm_wiki\algowiki1901_rich_v1_second_pass\reports\recovered_context_run_summary.md"
