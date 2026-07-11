# AlgorithmWiki Rich Corpus Starting State

This report records the Phase 0 baseline before constructing `algowiki1901_rich_v1`.
The existing `algowiki1901_v1/public_blind` corpus remains a leakage-control input and is not deleted or rewritten by the rich corpus workflow.

## Baseline Counts

- Row count: 1901
- Public blind ready count: 591
- Public named ready count: 697
- Review-needed manifest count: 1310
- Duplicate-variant count: 566
- Insufficient-information count: 536
- Additional review-needed count: 204
- Named-only ready count: 4

## Readiness Distribution

- READY_PUBLIC_BLIND: 591
- READY_PUBLIC_NAMED_ONLY: 4
- REVIEW_NEEDED: 204
- INSUFFICIENT_INFORMATION: 536
- DUPLICATE_VARIANT: 566

## Output Contract Distribution

- full_solution: 954
- unknown_output_contract: 614
- full_sequence_output: 166
- full_classical_output: 93
- path_or_tree: 25
- data_structure_output: 20
- estimate: 8
- approximation_solution: 6
- multiple_witnesses: 6
- assignment_or_schedule: 5
- one_witness: 4

## Domain Distribution

- unknown: 614
- graph: 419
- parallel_algorithms: 356
- sorting: 166
- string: 105
- matrix_linear_algebra: 93
- computational_geometry: 68
- image_processing: 24
- data_structures: 20
- dynamic_programming: 11
- numerical_analysis: 9
- randomized_sampling: 5
- optimization: 5
- combinatorics: 4
- robotics: 2

## Source Link Type Distribution

- unknown: 921
- pdf: 310
- acm: 285
- sciencedirect: 183
- siam: 87
- citeseerx: 50
- arxiv: 36
- doi: 29

## Known Weakness Of Blind Cards

The blind cards are intentionally conservative. They suppress algorithm names, source links, years, and other provenance-bearing identifiers, which makes them useful as leakage-control inputs. That same blinding also makes many cards too generic for discovery: representative statements include broad phrases such as computing a graph object, decomposition, image transformation, or combinatorial output targeted by the row. The final report for `algowiki1901_v1` also records that public Algorithm Wiki page enrichment found no per-row pages, so the blind cards are mostly metadata-derived rather than full source-backed reconstructions.

## Why Rich Context Is The Main Discovery Mode

QuantumMindLite discovery needs enough classical context to reason about input semantics, output semantics, bottlenecks, barriers, and possible subroutine-level probes. The rich corpus therefore prioritizes source-backed reconstruction over anonymity. Public context cards may name the algorithm and describe the classical task, complexity, model, bottleneck, and uncertainty while still excluding expected quantum primitives, expected verdicts, gold labels, hidden evidence, and PaperBench labels. This makes `public_context` the main whole-algorithm discovery input, while `public_blind` remains a useful control set.

## Phase 0 Validation

The baseline repository checks passed with the Codex bundled Python interpreter because the local `python` command resolves to the Windows Store alias on this machine.

- `python -m ruff format --check src tests scripts`: pass with bundled Python
- `python -m ruff check src tests scripts`: pass
- `python -m mypy src tests scripts`: pass
- `python -m pytest -q`: pass, 125 tests
- `python -m quantummindlite.cli validate-paperbench`: pass, 10 ready cases
