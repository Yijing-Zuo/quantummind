# AlgorithmWiki Registry Expansion V1

This document records the implemented minimal AlgorithmWiki registry expansion.
It is registry-relative only: these entries support conservative query-scope
hypotheses for expert review, not new quantum algorithms and not end-to-end
speedup claims.

## Entries Added

Four QUERY-scope primitives were added:

- `quantum_minimum_finding`
- `quantum_backtracking_tree_search`
- `quantum_walk_marked_vertex_search`
- `quantum_counting`

Two barriers were added:

- `backtracking_tree_bounds`
- `walk_spectral_gap`

Four source records were added:

- `durr_hoyer_1996`
- `montanaro_2015_backtracking`
- `magniez_nayak_roland_santha_2011`
- `brassard_hoyer_tapp_1998`

The existing `brassard_hoyer_mosca_tapp_2002` source now also lists
`quantum_counting`, because the new counting entry references it.

## Query-Scope Boundary

All four primitives have `supported_claim_scope: QUERY` and
`speedup_class: ASYMPTOTIC`. The registry may certify only that a candidate
card is internally consistent with a known query-model primitive.

The expansion does not support:

- gate-level implementation claims,
- end-to-end AlgorithmWiki speedup claims,
- full-output classical tasks,
- new novelty claims,
- model-performance claims from mock benchmarks.

The normal B-rules still control the outcome. B still returns exactly ten public
`CheckResult` objects, and D still maps the B outcome to a route without
upgrading verdicts.

## Negative Examples

The new entries must not make these task shapes positive:

- sorting or `sorted_order`,
- full sequence output,
- MST or full graph tree output,
- complete shortest path output,
- full graph traversal,
- all marked items or full enumeration,
- full matrix or full classical vector output,
- generic graph-walk language without spectral-gap and marked-fraction promises,
- generic branching or heuristic search without a coherent bounded tree oracle.

## Deferred Entries

These entries remain intentionally unimplemented:

- `hamiltonian_simulation`
- `block_encoding_qsvt_linear_algebra`
- `quantum_phase_estimation_eigenvalue`

They were deferred because the AlgorithmWiki public-probe first-50 evidence did
not expose the required access models, output contracts, and promises. In
particular, vague words such as "period", "cycle", "simulate", or "linear
algebra" should not create a selectable registry pathway.

## AlgorithmWiki Effect

Existing `search_witness_probe` cases continue to route to
`amplitude_amplification` when they expose the required coherent Boolean oracle,
`one_witness` output, and `marked_item_exists` promise.

Existing `estimation_sampling_probe` cases continue to route to
`amplitude_estimation` when they expose the required coherent estimation oracle,
`additive_estimate` output, and promises.

Generic first-50-style `graph_walk_probe` cards with
`local_graph_transition_oracle`, `one_witness`, and no spectral-gap or
marked-fraction promises remain negative. The new marked-vertex quantum walk
entry requires `coherent_markov_chain_walk_oracle`, `one_marked_vertex`, and
explicit reversible-chain, marking, marked-fraction, and spectral-gap promises.

## Overgeneration Risks

`quantum_minimum_finding` is risky around shortest, best, nearest, minimum, or
lowest-cost wording. It requires an isolated unstructured argmin subproblem with
coherent value-oracle access, not a full optimization workflow.

`quantum_backtracking_tree_search` is risky around A*, IDA*, branch-and-bound,
DFS, and dynamic-programming rows. It requires a coherent bounded
backtracking-tree oracle and one solution leaf, not a full path or all
solutions.

`quantum_walk_marked_vertex_search` is risky around graph traversal and path
planning. It requires a reversible Markov-chain walk model with represented
spectral-gap and marked-fraction promises.

`quantum_counting` is risky around enumeration. It supports count estimates
only, not outputting every marked item.

## Validation

The implementation includes direct validator fixtures and deterministic
workflow regressions in `tests/test_registry_expansion_algowiki.py`. The tests
cover registry loading, positive query-scope fixtures, missing-promise
downgrades, full-output negatives, graph-walk overgeneration, and preservation
of existing amplitude-amplification, amplitude-estimation, and
element-distinctness pathways.
