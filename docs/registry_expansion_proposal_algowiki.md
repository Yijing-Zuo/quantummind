# Registry Expansion Proposal For AlgorithmWiki Probe Discovery

This is a proposal only. It does not change `primitives.yaml`, `sources.yaml`,
runtime behavior, B-rules, or the AlgorithmWiki corpus.

## Inputs Inspected

- Current registry: `src/quantummindlite/resources/configs/primitives.yaml`.
  The registry currently has ten primitives: amplitude amplification,
  amplitude estimation, QFT period finding, element-distinctness quantum walk,
  HHL-style state-output linear systems, three constant-factor/no-speedup
  guardrail entries, ordered search, oracle interrogation, and parity query.
- Current sources: `src/quantummindlite/resources/configs/sources.yaml`.
- Public probe manifest and metadata:
  `corpus/algorithm_wiki/algowiki1901_rich_v1/manifests/ready_public_probe.csv`,
  `ready_public_probe.jsonl`, and `rich_probe_manifest.json`.
- Public probe audit:
  `corpus/algorithm_wiki/algowiki1901_rich_v1/audit/probe_audit.md`
  and `.csv`.
- Public probe first-50 run outputs:
  `runs/algowiki_rich_probe_first50/*/{input,state,decision}.json`.
- Graph-walk negatives available in that first-50 run.

No OpenAI calls were run for this proposal.

## Evidence Summary

The public probe manifest has 600 ready public probe cards:

| probe type | count |
| --- | ---: |
| search_witness_probe | 351 |
| graph_walk_probe | 213 |
| estimation_sampling_probe | 30 |
| period_structure_probe | 6 |

The first-50 live probe run contains:

| result | count |
| --- | ---: |
| POSITIVE | 32 |
| NEGATIVE | 18 |

The first-50 positives are already explained by existing registry entries:

| selected primitive | count |
| --- | ---: |
| amplitude_amplification | 27 |
| amplitude_estimation | 5 |

The first-50 negatives are concentrated in registry gaps and proper guardrails:

| negative group | count | observed behavior |
| --- | ---: | --- |
| graph_walk_probe | 16 | All graph-walk probes were NEGATIVE. They exposed `local_graph_transition_oracle`, `marked_vertex_or_edge`, and `query_model_subroutine`, but no current registry primitive accepts marked-vertex walk search. Existing `quantum_walk_element_distinctness` was at best a weak analogy in 2/16 and not supported in 14/16. |
| period_structure_probe | 2 | Both remained NEGATIVE because vague cycle or period language did not establish a finite group/order-finding instance accepted by `qft_period_finding`. |

The positive audit is a corpus-quality audit, not a model-performance claim:
600/600 public probe cards passed shape, leakage, source-trace, and semantic
checks with severity `NONE` and action `ACCEPT`. It does not certify that any
new primitive should be positive.

## Recommendation

Add four narrow registry entries, and do not add the other three considered
entries yet.

Proposed now:

1. `quantum_minimum_finding`
2. `quantum_backtracking_tree_search`
3. `quantum_walk_marked_vertex_search`
4. `quantum_counting`

Deferred for now:

1. `hamiltonian_simulation`
2. `block_encoding_qsvt_linear_algebra`
3. `quantum_phase_estimation_eigenvalue`

The proposed entries are query-scope only. They should not make full-output
tasks positive, should not upgrade D-routes, and should not loosen any B-rule.

## New BarrierSpecs

Only two new barriers appear necessary for the proposed entries.

```yaml
- barrier_id: backtracking_tree_bounds
  description: "Quantum backtracking speedups require represented bounds on the search tree size/depth and a coherent tree oracle; generic branching or heuristic search language is insufficient."
  blocked_scopes: [QUERY, GATE, END_TO_END]
  satisfied_by_promises: [bounded_backtracking_tree, bounded_tree_depth]

- barrier_id: walk_spectral_gap
  description: "Quantum walk search complexity depends on represented spectral-gap and marked-fraction bounds; generic graph traversal or local adjacency access is insufficient."
  blocked_scopes: [QUERY, GATE, END_TO_END]
  satisfied_by_promises: [spectral_gap_lower_bound, marked_fraction_lower_bound]
```

Existing barriers are enough for the other obligations:
`oracle_construction`, `query_only_scope`, `precision_dependence`,
`reversible_arithmetic`, `classical_postprocessing`, `readout`, and
`full_output_information`.

## Proposed Entry: quantum_minimum_finding

```yaml
primitive_id: quantum_minimum_finding
required_structure_ids: [unstructured_minimum_selection]
allowed_access_models: [coherent_value_oracle]
allowed_output_contracts: [argmin_item, minimum_value_and_argmin]
required_promises:
  - finite_candidate_set
  - total_ordered_objective
  - coherent_objective_oracle
supported_claim_scope: QUERY
speedup_class: ASYMPTOTIC
classical_complexity: "CLASSICAL: Theta(N) value/comparison queries to find a minimum of an unstructured N-item set"
quantum_complexity: "QUERY: O(sqrt(N)) coherent value/comparison oracle queries for minimum finding"
common_barriers: [oracle_construction, query_only_scope, precision_dependence]
source_ids: [durr_hoyer_1996]
```

Required new `BarrierSpec` entries: none.

Source IDs needed:

```yaml
- source_id: durr_hoyer_1996
  title: "A quantum algorithm for finding the minimum"
  year: 1996
  result_type: asymptotic_query_upper_bound
  status: primary_source_checked
  primitive_ids: [quantum_minimum_finding]
  official_url: "https://arxiv.org/abs/quant-ph/9607014"
```

Positive fixture card:

```yaml
statement: "Given coherent oracle access to N candidate objective values, return an index attaining the minimum."
input_model: finite_candidate_set
access_model: coherent_value_oracle
output_contract: argmin_item
promises:
  - finite_candidate_set
  - total_ordered_objective
  - coherent_objective_oracle
size_parameters:
  - "N: number of candidates"
analysis_card.canonical_structure_ids: [unstructured_minimum_selection]
expected_selected_candidate: quantum_minimum_finding
expected_scope: QUERY
```

Negative fixture card:

```yaml
statement: "Given an explicit list of N items, output the full sorted order."
input_model: explicit_list
access_model: comparison_oracle
output_contract: sorted_order
promises: [total_order]
analysis_card.canonical_structure_ids: [comparison_sorting]
expected_selected_candidate: comparison_sorting_no_asymptotic_speedup
expected_verdict: NEGATIVE
```

Why this is not already covered:

`amplitude_amplification` can find one marked item but does not certify minimum
selection. `ordered_search` is constant-factor only and assumes monotone ordered
access. `comparison_sorting_no_asymptotic_speedup` intentionally blocks full
sorting, not minimum selection.

Risk of overgeneration:

Medium. Many AlgorithmWiki graph and dynamic-programming rows mention best,
shortest, lowest-cost, or minimum objects. This entry must require a coherent
value oracle over a finite unstructured candidate set and must reject full
solutions, sorted orders, MSTs, all nearest neighbors, and heuristic "best-first"
searches unless the argmin subproblem is isolated.

Tests needed:

- Positive validation fixture for `argmin_item` with `coherent_value_oracle`.
- Negative fixture showing `sorted_order` remains negative via the existing
  sorting guardrail.
- Regression fixture for Kruskal/MST-style full-output tasks: no end-to-end MST
  positive even if a minimum edge subroutine is described.
- B-rule invariant: still exactly ten `CheckResult` objects.

## Proposed Entry: quantum_backtracking_tree_search

```yaml
primitive_id: quantum_backtracking_tree_search
required_structure_ids: [bounded_backtracking_tree]
allowed_access_models: [coherent_backtracking_tree_oracle]
allowed_output_contracts: [one_solution_leaf]
required_promises:
  - bounded_backtracking_tree
  - bounded_tree_depth
  - coherent_child_and_predicate_oracles
  - marked_leaf_exists
supported_claim_scope: QUERY
speedup_class: ASYMPTOTIC
classical_complexity: "CLASSICAL: Theta(T) tree-node predicate/child queries to search a backtracking tree of size T"
quantum_complexity: "QUERY: O(poly(d) sqrt(T)) coherent tree-oracle queries for tree depth d under the backtracking-tree model"
common_barriers: [oracle_construction, query_only_scope, backtracking_tree_bounds]
source_ids: [montanaro_2015_backtracking]
```

Required new `BarrierSpec` entries: `backtracking_tree_bounds`.

Source IDs needed:

```yaml
- source_id: montanaro_2015_backtracking
  title: "Quantum walk speedup of backtracking algorithms"
  year: 2015
  result_type: asymptotic_query_upper_bound
  status: primary_source_checked
  primitive_ids: [quantum_backtracking_tree_search]
  official_url: "https://arxiv.org/abs/1509.02374"
```

Positive fixture card:

```yaml
statement: "Given coherent child and predicate oracles for a bounded-depth backtracking tree, return one marked solution leaf."
input_model: implicit_search_tree
access_model: coherent_backtracking_tree_oracle
output_contract: one_solution_leaf
promises:
  - bounded_backtracking_tree
  - bounded_tree_depth
  - coherent_child_and_predicate_oracles
  - marked_leaf_exists
size_parameters:
  - "T: upper bound on tree size"
  - "d: tree depth"
analysis_card.canonical_structure_ids: [bounded_backtracking_tree]
expected_selected_candidate: quantum_backtracking_tree_search
expected_scope: QUERY
```

Negative fixture card:

```yaml
statement: "Given an explicit weighted graph, run A* and output the complete shortest path."
input_model: explicit_graph_problem
access_model: local_graph_transition_oracle
output_contract: full_solution
promises:
  - heuristic_available
analysis_card.canonical_structure_ids: [black_box_witness_search]
expected_selected_candidate: null
expected_verdict: NEGATIVE
```

Why this is not already covered:

`amplitude_amplification` only handles unstructured one-witness search. It does
not represent tree pruning, child oracles, depth, or a bounded backtracking
model. Existing graph-walk negatives show that `local_graph_transition_oracle`
plus `one_witness` is too broad; this entry gives a precise tree-only pathway.

Risk of overgeneration:

High if matched to any branch-and-bound, A*, DFS, dynamic programming, or
heuristic search row. The matcher must require an actual tree oracle, a stated
tree-size/depth bound, and a one-leaf output. Full paths, all solutions,
optimization certificates, dynamic state updates, and full problem outputs must
remain negative.

Tests needed:

- Positive tree-oracle fixture.
- Negative A*/IDA*/branch-and-bound fixture without `coherent_backtracking_tree_oracle`.
- Negative full-output path fixture even if `marked_leaf_exists` appears in
  prose.
- B6 regression: missing `bounded_tree_depth` yields CONDITIONAL or prevents
  POSITIVE, not a silent positive.

## Proposed Entry: quantum_walk_marked_vertex_search

```yaml
primitive_id: quantum_walk_marked_vertex_search
required_structure_ids: [reversible_markov_chain_marked_vertex_search]
allowed_access_models: [coherent_markov_chain_walk_oracle]
allowed_output_contracts: [one_marked_vertex]
required_promises:
  - reversible_ergodic_markov_chain
  - efficient_marking_check
  - marked_vertex_exists
  - marked_fraction_lower_bound
  - spectral_gap_lower_bound
supported_claim_scope: QUERY
speedup_class: ASYMPTOTIC
classical_complexity: "CLASSICAL: O(1/(delta epsilon)) random-walk update/check queries under spectral gap delta and marked fraction epsilon"
quantum_complexity: "QUERY: O(1/sqrt(epsilon) * (1/sqrt(delta) update + check)) coherent walk/search queries under the same promises"
common_barriers: [oracle_construction, query_only_scope, walk_spectral_gap]
source_ids: [magniez_nayak_roland_santha_2011]
```

Required new `BarrierSpec` entries: `walk_spectral_gap`.

Source IDs needed:

```yaml
- source_id: magniez_nayak_roland_santha_2011
  title: "Search via quantum walk"
  year: 2011
  result_type: asymptotic_query_upper_bound
  status: primary_source_checked
  primitive_ids: [quantum_walk_marked_vertex_search]
  official_url: "https://doi.org/10.1137/090745854"
```

Positive fixture card:

```yaml
statement: "Given coherent setup, update, and checking access to a reversible Markov chain on graph vertices, return one marked vertex."
input_model: implicit_graph_walk_problem
access_model: coherent_markov_chain_walk_oracle
output_contract: one_marked_vertex
promises:
  - reversible_ergodic_markov_chain
  - efficient_marking_check
  - marked_vertex_exists
  - marked_fraction_lower_bound
  - spectral_gap_lower_bound
size_parameters:
  - "epsilon: lower bound on marked stationary probability"
  - "delta: lower bound on spectral gap"
analysis_card.canonical_structure_ids: [reversible_markov_chain_marked_vertex_search]
expected_selected_candidate: quantum_walk_marked_vertex_search
expected_scope: QUERY
```

Negative fixture card:

```yaml
statement: "Given local graph transitions for A*, return a full shortest path."
input_model: explicit_graph_problem
access_model: local_graph_transition_oracle
output_contract: full_solution
promises:
  - marked_vertex_or_edge
  - query_model_subroutine
analysis_card.canonical_structure_ids: [black_box_witness_search]
expected_selected_candidate: null
expected_verdict: NEGATIVE
```

Why this is not already covered:

The current `quantum_walk_element_distinctness` entry is for collision structure
and `collision_or_distinctness` output. The first-50 graph-walk negatives are
marked-vertex/edge search probes with local transition language. They are not
element distinctness and should not be forced through Ambainis's collision
walk.

Risk of overgeneration:

Very high. AlgorithmWiki has many graph traversal, path planning, MST, and
geometry rows. Generic local graph access, heuristic frontier updates, or
marked edge language must remain insufficient. The entry should select only
when spectral-gap and marked-fraction promises are explicit and the output is
one marked vertex, not a full path, tree, traversal, MST, cut, matching, or
graph drawing.

Tests needed:

- Positive marked-vertex walk fixture with gap and marked-fraction promises.
- Regression test over the first-50 graph-walk negative card shapes:
  `local_graph_transition_oracle` plus `one_witness` remains NEGATIVE.
- Negative full-output graph path/MST fixtures.
- Negative element-distinctness fixture should still select
  `quantum_walk_element_distinctness`, not this entry.

## Proposed Entry: quantum_counting

```yaml
primitive_id: quantum_counting
required_structure_ids: [marked_set_cardinality_estimation]
allowed_access_models: [coherent_boolean_oracle]
allowed_output_contracts: [additive_count_estimate, relative_count_estimate]
required_promises:
  - finite_search_space
  - coherent_boolean_oracle_available
  - count_precision_specified
supported_claim_scope: QUERY
speedup_class: ASYMPTOTIC
classical_complexity: "CLASSICAL: Theta(1/epsilon^2) predicate samples/queries for additive marked-fraction estimation"
quantum_complexity: "QUERY: O(1/epsilon) coherent Boolean-oracle calls for additive marked-fraction/count estimation"
common_barriers: [oracle_construction, query_only_scope, precision_dependence]
source_ids: [brassard_hoyer_tapp_1998, brassard_hoyer_mosca_tapp_2002]
```

Required new `BarrierSpec` entries: none.

Source IDs needed:

```yaml
- source_id: brassard_hoyer_tapp_1998
  title: "Quantum counting"
  year: 1998
  result_type: asymptotic_query_upper_bound
  status: primary_source_checked
  primitive_ids: [quantum_counting]
  official_url: "https://arxiv.org/abs/quant-ph/9805082"
```

The existing `brassard_hoyer_mosca_tapp_2002` source can also be referenced,
but its `primitive_ids` would need to include `quantum_counting` if used.

Positive fixture card:

```yaml
statement: "Given a coherent Boolean oracle for a predicate over N candidates, estimate the number of marked candidates to additive error epsilon N."
input_model: finite_candidate_set
access_model: coherent_boolean_oracle
output_contract: additive_count_estimate
promises:
  - finite_search_space
  - coherent_boolean_oracle_available
  - count_precision_specified
size_parameters:
  - "N: number of candidates"
  - "epsilon: additive marked-fraction precision"
analysis_card.canonical_structure_ids: [marked_set_cardinality_estimation]
expected_selected_candidate: quantum_counting
expected_scope: QUERY
```

Negative fixture card:

```yaml
statement: "Given a predicate over N candidates, output every marked item."
input_model: finite_candidate_set
access_model: coherent_boolean_oracle
output_contract: all_marked_items
promises:
  - finite_search_space
  - coherent_boolean_oracle_available
analysis_card.canonical_structure_ids: [marked_set_cardinality_estimation]
expected_selected_candidate: null
expected_verdict: NEGATIVE
```

Why this is not already covered:

`amplitude_estimation` can estimate a bounded mean and could encode counting as
an indicator mean, but the current registry has no typed count/cardinality
structure, no count-estimate output contract, and no finite-domain cardinality
promises. A separate entry avoids overloading generic mean estimation while
keeping count tasks away from full enumeration.

Risk of overgeneration:

Medium. Many AlgorithmWiki rows include counts as part of a larger algorithm.
This entry must be limited to cardinality estimates. Exact enumeration, full
lists, certificates for every item, and downstream full-output tasks remain
negative.

Tests needed:

- Positive additive count-estimate fixture.
- Negative all-marked-items fixture.
- Negative exact full enumeration fixture.
- Regression that generic sampling estimates can still use
  `amplitude_estimation` when no finite marked-set count structure is present.

## Deferred Entries

### hamiltonian_simulation

Do not add from the first-50 evidence. No first-50 public probe exposes a
sparse/local Hamiltonian input model, simulation time, norm bound, precision,
or a quantum-state/expectation output contract. Adding it now would create a
high-risk "simulate the algorithm quantumly" escape hatch.

Potential future source IDs, if evidence exists:

- `lloyd_1996_universal_quantum_simulators`
- `berry_childs_kothari_2015_hamiltonian_simulation`

Acceptance gate for later: require explicit `sparse_hamiltonian_oracle` or
`local_hamiltonian_terms`, `hamiltonian_norm_bound`, `simulation_time_specified`,
`simulation_precision_specified`, and output `time_evolved_state_or_observable`.

### block_encoding_qsvt_linear_algebra

Do not add from the first-50 evidence. The existing
`quantum_linear_systems_state_output` entry already provides a guarded
linear-system pathway with conditioning, state preparation, and readout
barriers. A broad block-encoding/QSVT entry would duplicate and weaken that
guardrail unless the corpus has explicit block-encoding access and state-output
contracts.

Potential future source ID:

- `gilyen_su_low_wiebe_2019_qsvt`

Acceptance gate for later: require `block_encoding_oracle`,
`normalization_bound`, `polynomial_transform_specified`,
`state_preparation_or_input_state`, `condition_or_spectral_gap_bound` when
relevant, and output only `state_or_expectation` or another non-full-readout
contract.

### quantum_phase_estimation_eigenvalue

Do not add from the first-50 evidence. The period-structure negatives show the
opposite lesson: vague "cycle", "period", or "exact value" language should not
be upgraded. QPE should be added only for an eigenphase/eigenvalue task with a
unitary and prepared eigenstate, not for generic periodic metadata.

Potential future source IDs:

- `kitaev_1995_phase_estimation`
- `abrams_lloyd_1999_eigenvalues`

Acceptance gate for later: require `unitary_eigenphase_estimation`,
`controlled_unitary_access`, `prepared_eigenstate_or_overlap_bound`,
`phase_precision_specified`, and output `phase_or_eigenvalue_estimate`.

## Implementation And Test Plan If Approved

Implementation should modify only existing config and focused tests:

1. Add proposed barriers and primitives to `primitives.yaml`.
2. Add the proposed source entries to `sources.yaml`, and update existing
   source `primitive_ids` only where reused.
3. Add focused public fixture cards for each positive and negative case.
4. Add validator/orchestrator tests proving:
   - B still returns exactly ten public `CheckResult` objects.
   - D only routes the B outcome and never upgrades a verdict.
   - Full-output graph/path/list/sorted-order/all-items tasks remain negative.
   - The first-50 generic graph-walk shape remains negative without the new
     spectral-gap and marked-fraction promises.
   - Existing amplitude amplification and amplitude estimation positives are
     not displaced incorrectly.
5. Run the required repair gate:
   - `python -m ruff format --check src tests`
   - `python -m ruff check src tests`
   - `python -m mypy src tests`
   - `python -m pytest -q`
   - relevant CLI smoke tests, especially `validate-paperbench` and the
     affected AlgorithmWiki benchmark or family commands.

## Bottom Line

The first-50 evidence supports adding precise query-scope entries for minimum
finding, bounded backtracking tree search, marked-vertex quantum walk search,
and quantum counting. The graph-walk entry is the clearest registry gap, but it
must be guarded by spectral-gap and marked-fraction promises so the existing
AlgorithmWiki graph-walk negatives do not become positives by mere graph
language. The Hamiltonian simulation, block-encoding/QSVT, and QPE entries
should wait for explicit public cards with those structures.
