# Algorithm Wiki Corpus Protocol

Algorithm Wiki rows are algorithm-level metadata, not contest-style problem
statements. The adapter therefore uses a staged curation pipeline:

CSV row -> `AlgorithmWikiRawRecord` -> `AlgorithmWikiPreCard` -> public
`ProblemCard` only when input, access, output, and complexity semantics are
clear enough.

## Scope

This corpus lives under `corpus/algorithm_wiki/` and is separate from the core
QuantumMindLite workflow, PaperBench, validation rules, prompts, providers, and
registry. It never reads PaperBench gold or evidence files.

Expected subdirectories:

- `raw/`
- `normalized/`
- `precards/`
- `public_blind/`
- `public_named/`
- `metadata/`
- `cards/`
- `manifests/`
- `reports/`
- `audit/`
- `commands/`
- `review_samples/`

## Ingestion

Use the semicolon-delimited public export:

```powershell
python scripts/datasets/algowiki_ingest.py `
  --csv algowiki-dataset-export.csv `
  --out-normalized corpus/algorithm_wiki/normalized/algowiki_records.jsonl `
  --out-manifest corpus/algorithm_wiki/manifests/algowiki_ingest_manifest.json
```

Ingestion preserves every row, assigns deterministic IDs `AW-000001`,
`AW-000002`, and so on, records duplicate canonicalized names, and writes
column missingness plus link-type and computational-model counts.

## Optional Public Page Enrichment

Page enrichment is best effort and cache backed. It only requests public
Algorithm Wiki pages and the public download page; it does not fetch external
papers.

```powershell
python scripts/datasets/algowiki_enrich_pages.py `
  --records corpus/algorithm_wiki/normalized/algowiki_records.jsonl `
  --out corpus/algorithm_wiki/normalized/algowiki_records_enriched.jsonl `
  --cache-dir corpus/algorithm_wiki/cache/pages `
  --max-pages 1901
```

Rows receive `page_fetch_status` values of `found`, `not_found`,
`fetch_failed`, or `disabled`. If the site is unavailable, the script writes a
report and leaves the corpus in CSV-only mode.

## Card Generation

```powershell
python scripts/datasets/algowiki_to_cards.py `
  --records corpus/algorithm_wiki/normalized/algowiki_records_enriched.jsonl `
  --out-metadata-dir corpus/algorithm_wiki/metadata `
  --out-precard-dir corpus/algorithm_wiki/precards `
  --out-card-dir corpus/algorithm_wiki/cards `
  --out-public-blind-dir corpus/algorithm_wiki/public_blind `
  --out-public-named-dir corpus/algorithm_wiki/public_named `
  --out-manifest corpus/algorithm_wiki/manifests/algowiki_cards_manifest.json `
  --seed 20260627
```

If the enriched JSONL file is missing, the generator falls back to
`algowiki_records.jsonl`.

Every row gets metadata, a precard, and a combined audit card. Public cards are
only emitted for rows labeled `READY_PUBLIC_BLIND` or
`READY_PUBLIC_NAMED_ONLY`.

## Readiness Labels

- `READY_PUBLIC_BLIND`: blind public card and named public card are emitted.
- `READY_PUBLIC_NAMED_ONLY`: only the named public card is emitted.
- `REVIEW_NEEDED`: row has partial semantics but needs human curation.
- `INSUFFICIENT_INFORMATION`: row lacks enough I/O/access/output semantics.
- `DUPLICATE_VARIANT`: duplicate canonicalized name after the first row.
- `BAD_SOURCE`: source link is not suitable public metadata.

## Leakage Rules

Public YAML must not contain quantum-specific hints, expected primitive labels,
PaperBench terms, gold/evidence references, or hidden benchmark markers. Blind
cards must also avoid exact canonical algorithm names when feasible. Named cards
may include the algorithm name for expert review but still must not include
quantum terms or expected primitive labels.

## QA Commands

```powershell
python scripts/datasets/algowiki_audit_cards.py
python scripts/datasets/algowiki_validate_cards.py --min-ready 1 --sample-mock-analyze 10
python scripts/datasets/algowiki_summarize_cards.py
```

Repository validation:

```powershell
python -m ruff format --check src tests scripts
python -m ruff check src tests scripts
python -m mypy src tests scripts
python -m pytest -q
python -m quantummindlite.cli validate-paperbench
```

## 10-Card Baseline

After generation and validation, run a small mock baseline:

```powershell
Get-ChildItem corpus\algorithm_wiki\public_blind\AW-*.yaml |
  Select-Object -First 10 |
  ForEach-Object { python -m quantummindlite.cli analyze --input $_.FullName --provider mock --output-dir runs\algowiki_baseline10 }
```
