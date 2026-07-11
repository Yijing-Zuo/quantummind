# AlgorithmWiki Registry Expansion V1 Audit

Date: 2026-06-29

Audit mode: read-only adversarial audit of implemented registry/runtime behavior. Source, config, test, and runtime files were not edited. This report is the only documentation artifact written. No OpenAI provider or live analyze path was run.

## Files Inspected

- `AGENTS.md`
- `src/quantummindlite/resources/configs/primitives.yaml`
- `src/quantummindlite/resources/configs/sources.yaml`
- `src/quantummindlite/registry.py`
- `src/quantummindlite/validation.py`
- `src/quantummindlite/workflow.py`
- `tests/test_registry_expansion_algowiki.py`
- `docs/registry_expansion_algowiki_v1.md`
- `docs/registry_expansion_proposal_algowiki.md`

## Audit Results

| Claim | Result | Evidence |
| --- | --- | --- |
| All four implemented primitives are present exactly once. | PASS | Parsed `primitives.yaml`; each of `quantum_minimum_finding`, `quantum_backtracking_tree_search`, `quantum_walk_marked_vertex_search`, and `quantum_counting` appears once. |
| No deferred entries were implemented. | PASS | `hamiltonian_simulation`, `block_encoding_qsvt_linear_algebra`, and `quantum_phase_estimation_eigenvalue` are absent from registry primitives. |
| All new primitives have supported_claim_scope `QUERY`. | PASS | Parsed runtime registry reports all four as `QUERY`. |
| All new primitives have speedup_class `ASYMPTOTIC`. | PASS | Parsed runtime registry reports all four as `ASYMPTOTIC`. |
| All required new primitive fields are nonempty. | PASS | All four have nonempty structures, access models, output contracts, promises, classical/quantum complexity, barriers, and sources. |
| All referenced barriers exist. | PASS | Every `common_barriers` reference on the four entries resolves in the barrier catalog. |
| All referenced sources exist. | PASS | Every `source_ids` reference on the four entries resolves in `sources.yaml`. |
| New barriers block `QUERY`, `GATE`, and `END_TO_END`. | PASS | `backtracking_tree_bounds` and `walk_spectral_gap` both include all three blocked scopes. |
| Existing PaperBench primitives were not weakened. | PASS | Core existing registry entries remain `QUERY`/`ASYMPTOTIC` with nonempty guardrails: `amplitude_amplification`, `amplitude_estimation`, `qft_period_finding`, `quantum_walk_element_distinctness`, `quantum_linear_systems_state_output`. |
| Existing comparison sorting, ordered search, oracle interrogation, parity, and dense full-output stress entries were not weakened. | PASS | `comparison_sorting_no_asymptotic_speedup` and `dense_linear_system_full_output_stress` remain `NONE`/`NONE`; `ordered_search`, `oracle_interrogation`, and `parity_query` remain `QUERY`/`CONSTANT_FACTOR_ONLY`. |
| No B-rules or route logic were changed/expanded. | PASS | `RULE_IDS` is exactly B1-B10; `route_decision` maps INVALID->RERUN, NEGATIVE->STOP, CONDITIONAL->EXPERT_REVIEW_WITH_WARNINGS, otherwise EXPERT_REVIEW. |
| Full-output tasks cannot become POSITIVE through the new entries. | PASS | Direct adversarial full-output fixtures against the new primitives returned INVALID, never POSITIVE. A*/IDA*/path output mock probe returned NEGATIVE with no selected candidate. |
| Missing required promises cannot silently pass. | PASS | Removing one required promise from each new primitive produced B6 `UNKNOWN` and overall `CONDITIONAL`, not POSITIVE. |
| Graph-walk probe with `local_graph_transition_oracle` and no spectral gap remains NEGATIVE or weak analogy, not POSITIVE. | PASS | Mock orchestrator result was NEGATIVE with no selected candidate; the only match was weak analogy, not the new walk-search entry. |
| A*/IDA*/shortest-path full-output tasks remain NEGATIVE. | PASS | Mock orchestrator full-path probe returned NEGATIVE with `No normalized PLAUSIBLE primitive satisfies the ProblemCard.` |
| `quantum_walk_element_distinctness` remains distinct from `quantum_walk_marked_vertex_search`. | PASS | Element distinctness mock probe selected `quantum_walk_element_distinctness`. |
| `quantum_counting` does not replace amplitude estimation for generic bounded mean estimation. | PASS | Bounded mean mock probe selected `amplitude_estimation`. |
| PaperBench mock benchmark remains passing. | PASS | `benchmark-all --provider mock` returned `overall_pass: true`, `guardrail_pass: true`, `macro_raw_pass: 1.0`, and `macro_system_pass: 1.0`. |

## Behavioral Probe Notes

- Full-output adversarial fixtures: 5/5 returned INVALID, never POSITIVE.
- Missing-promise fixtures:
  - `quantum_minimum_finding`: CONDITIONAL, B6 UNKNOWN for missing `finite_candidate_set`.
  - `quantum_backtracking_tree_search`: CONDITIONAL, B6 UNKNOWN for missing `bounded_backtracking_tree`.
  - `quantum_walk_marked_vertex_search`: CONDITIONAL, B6 UNKNOWN for missing `reversible_ergodic_markov_chain`.
  - `quantum_counting`: CONDITIONAL, B6 UNKNOWN for missing `finite_search_space`.
- Graph-walk no-gap probe: NEGATIVE, `selected_candidate: null`; weak analogy only.
- A*/IDA*/shortest-path full-output probe: NEGATIVE, `selected_candidate: null`.
- Element distinctness probe: selected `quantum_walk_element_distinctness`.
- Generic bounded mean estimation probe: selected `amplitude_estimation`.

## Command Results

Plain `python` was unavailable in the audit shell because it resolved to the
Windows Store alias. The requested module commands were run with the bundled
workspace interpreter.

| Command | Result | Output Summary |
| --- | --- | --- |
| `python --version` | FAIL | Windows Store alias: `Python was not found...` |
| `python -m ruff format --check src tests scripts` | PASS | `49 files already formatted` |
| `python -m ruff check src tests scripts` | PASS | `All checks passed!` |
| `python -m mypy src tests scripts` | PASS | `Success: no issues found in 49 source files` |
| `python -m pytest -q` | PASS | `152 passed in 14.34s` |
| `python -m quantummindlite.cli validate-paperbench` | PASS | `ok: true`, `ready_count: 10`, no errors |
| `python -m quantummindlite.cli benchmark-all --provider mock --output-dir runs\mock_registry_audit` | PASS | `overall_pass: true`, `guardrail_pass: true`, `macro_raw_pass: 1.0`, `macro_system_pass: 1.0` |

The benchmark output was written to `runs/mock_registry_audit`.

## Overgeneration Risks

- `quantum_minimum_finding`: risk from vague "minimum", "best", "nearest", or "shortest" language. Current guardrails require an unstructured finite candidate set, total ordered objective, coherent objective/value oracle, and argmin/minimum output; sorting and shortest-path outputs remain blocked.
- `quantum_backtracking_tree_search`: risk from generic tree, branch-and-bound, A*, IDA*, or heuristic-search wording. Current guardrails require a bounded backtracking tree, bounded depth, coherent child/predicate oracles, marked leaf existence, and one-solution-leaf output.
- `quantum_walk_marked_vertex_search`: risk from generic graph traversal/local transition tasks. Current guardrails require a coherent Markov-chain walk oracle, reversible ergodic chain, efficient marking check, marked vertex existence, marked fraction lower bound, spectral gap lower bound, and one-marked-vertex output.
- `quantum_counting`: risk from enumeration/counting language and from confusion with generic bounded mean estimation. Current guardrails restrict it to coherent Boolean-oracle marked-set count estimates, and generic bounded mean estimation still maps to `amplitude_estimation`.

## Conclusion

Safe to proceed to `candidate_value_label`: YES.

The implemented expansion is conservative under this audit: the four intended entries are present, the three deferred entries are absent, all new entries remain query-scope only, new barriers are blocking across all higher scopes, full-output tasks do not become positive, missing promises remain visible, and PaperBench mock validation still passes.
