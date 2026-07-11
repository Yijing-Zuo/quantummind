# QAEG: Quantum Acceleration Evidence Graph

This note describes `quantummindlite.graph`, the private `_graph_compile`,
`_graph_projection`, and `_graph_verify` modules, and the separate
`_graph_screen` research screen. It documents the code that exists now, not the
larger graph-native architecture proposed for future work.

## Implemented boundary

QAEG is an offline deterministic sidecar for completed QuantumMindLite runs.
For a serialized public run state \(S_r\), its deterministic decision \(D_r\),
and the public runtime primitive/barrier registry \(\mathcal{R}_{pub}\), the
compiler constructs

\[
G_r = \operatorname{Compile}(S_r,D_r,\mathcal{R}_{pub}).
\]

The sidecar does not call an LLM or API. It does not change the generic
`Agent`, the sequential `Orchestrator`, action ownership or merge policy,
B1-B10, or D routing. It does not read PaperBench gold/evidence data, deploy a
GNN, or use a learned judge.

Before compilation, `process_run_dir` loads `state.json` and `decision.json`,
recomputes `build_decision(state, registry)`, and rejects the run if the saved
decision is stale or altered. With per-run writing enabled, it produces:

- `evidence_graph.json`
- `graph_verifier_report.json`
- `graph_summary.json`

## Typed graph

An evidence graph is

\[
G_r=(V_r,E_r,\tau_V,\tau_E,\psi),
\]

where the implemented node types are `Run`, `ProblemFact`, `Structure`,
`AbsentStructure`, `RegistryPrimitive`, `PrimitiveMatch`, `WeakAnalogy`,
`Obligation`, `Barrier`, `Scheme`, `ComplexityTerm`, `PriorArt`,
`NoveltyStatus`, `Claim`, `BCheck`, and `Decision`.

Implemented edges represent containment, structure support for a match,
match-to-primitive instantiation, match and registry grounding of a claim,
weak or unusable support, obligations and their satisfying evidence,
scope-blocking or scope-bounding barriers, complexity support, novelty bounds,
B checks, and the final decision.

Node and edge identifiers are deterministic. `graph_id` is a digest over the
graph version, run identifier, and sorted serialized nodes and edges. The
verifier checks the digest, identifier uniqueness, and every edge endpoint.

## Registry-derived obligations

For a selected primitive \(p\) and claim scope \(s\), the current projection
materializes eight obligations:

\[
O_{\mathcal{R}}(p,s)=\{
O_{selection}, O_{registry}, O_{structures}, O_{complexity},
O_{access}, O_{output}, O_{promises}, O_{scope}
\}.
\]

Their statuses are projected from the corresponding authoritative B checks as
`SATISFIED`, `CONTRADICTED`, `UNKNOWN`, or `NOT_APPLICABLE`. Barrier and
novelty boundaries are represented by their own nodes and graph checks rather
than being counted as additional obligation-node kinds.

For a supported selected claim, the verifier requires graph relationships of
the following form:

\[
\begin{aligned}
Structure &\rightarrow PrimitiveMatch,\\
PrimitiveMatch &\rightarrow RegistryPrimitive,\\
PrimitiveMatch &\rightarrow Claim,\\
RegistryPrimitive &\rightarrow Claim,\\
Scheme/ComplexityTerm &\rightarrow Claim,\\
ProblemFact/Structure/ComplexityTerm &\rightarrow Obligation \rightarrow Claim.
\end{aligned}
\]

This is a support subgraph, not a claim that all evidence lies on one linear
path. `minimal_support` computes a deterministic fixed-point closure by
traversing the relevant incoming and outgoing typed edges around the unique
claim node. The verifier likewise queries nodes and edges directly; it does
not trust a cached `support_path_complete` flag or summary field.

Despite the API name, this artifact is a bounded dependency closure under the
implemented edge rules; the code does not solve a global minimum-cardinality
subgraph optimization problem.

## Graph checks

The report contains six graph-level checks:

- `G1_CLAIM_SUPPORT_PATH` requires one plausible selected match, a known
  registry primitive, required structure-to-match edges, match/primitive claim
  grounding, and the represented scheme and scope-relevant complexity
  certificate.
- `G2_SCOPE_DEPENDENT_OBLIGATIONS` requires all eight expected obligation
  nodes and checks their statuses.
- `G3_BARRIER_DOMINANCE` rejects a stronger claim when a represented supported
  barrier blocks its scope, and reports unresolved blocking barriers as
  unknown.
- `G4_CONTRADICTION_FREE_STATE` checks the graph digest and endpoints, the
  complete B1-B10 projection, exact agreement between projected checks and the
  `DecisionCard`, and basic claim-state consistency.
- `G5_NOVELTY_SCOPE_BOUNDED` prevents represented known/direct prior art from
  supporting a global-novelty claim and keeps unknown prior art unresolved.
- `G6_GENERIC_WRAPPER_MOTIF` is an informational deterministic diagnostic for
  generic amplitude-amplification wrappers. It does not alter graph status,
  B's verdict, or D's route.

The first five checks are hard graph checks. `graph_status` is `FAIL` if one of
them fails, `WARN` if none fails but at least one is unknown, and otherwise
`PASS`. A negative or no-candidate run can therefore have a healthy
`graph_status: PASS`.

`claim_accepted` is deliberately stricter and separate:

\[
\operatorname{claim\_accepted}
=
[D_r.authoritative\_verdict=POSITIVE]
\land[graph\_status=PASS]
\land\bigwedge_{i=1}^{5}[G_i=PASS].
\]

It is a sidecar assertion that an already B-positive serialized claim has a
complete represented graph certificate. It is not a new authoritative verdict
and can never upgrade `NEGATIVE`, `CONDITIONAL`, or `INVALID`.

## Downward-only research screening

The graph compiler/verifier above is unchanged. `QAEG-screen-v0.1` runs after
it and cannot modify the graph, B/D, `graph_status`, or `claim_accepted`. The
screen consumes only the public `RunState`, the graph/decision projection, and
the public registry. It does not read `input.json`, `trace.jsonl`, or
PaperBench gold/evidence.

The screen derives typed fields for:

- original and candidate output type plus `output_alignment`;
- provided and required access plus `access_upgrade_status`;
- `oracle_status` and hidden-hardness/circularity risk;
- `baseline_status`; and
- the represented `candidate_universe`.

It then assigns one `research_disposition`: `INVALID_STATE`,
`SOURCE_REPAIR_REQUIRED`, `REJECT_TASK_MISMATCH`, `DEMOTE_GENERIC`,
`DEMOTE_TO_BENCHMARK`, `REFORMULATE`, `LITERATURE_SEARCH_FIRST`, or
`KEEP_FOR_EXPERT_REVIEW`. This is downward-only research triage. In particular,
`KEEP_FOR_EXPERT_REVIEW` is allowed only for an accepted `PASS` graph and still
does not assert correctness, novelty, or end-to-end speedup.

`graph_status`, `claim_accepted`, and `research_disposition` therefore remain
separate outputs with different meanings. A graph can be internally healthy
and accepted relative to B while the screen demotes it for a generic oracle
wrapper or defers it for output, access, oracle, or baseline work.

## Family-level batch output

`scripts/regraph_runs.py` writes run-level summary, family-level, and top-k CSV
files. A candidate-family key contains the normalized parent algorithm,
selected primitive, original output type, provided access, and candidate
universe. If parent metadata is absent, the run's own shard/run identity is
used, preventing unrelated missing-parent rows from collapsing together.

Canonical selection is deterministic. The top-k contains only canonical
`PASS` rows with a disposition of `KEEP_FOR_EXPERT_REVIEW`,
`LITERATURE_SEARCH_FIRST`, or `REFORMULATE`; demoted, rejected, source-repair,
and invalid rows are excluded. `graph_value_label` remains in the summary only
as a v1 comparison field. The earlier single weighted triage score has been
removed.

The frozen output files are
`results/fdv1_screening_v01_{summary,families,top9}.csv` and
`results/review_screening_v01_{summary,families,top9}.csv`. The files are
deterministic screening artifacts, not learned predictions or scientific
quality scores. Their implementation, registry, and output hashes are recorded
in `results/qaeg_screen_v01_manifest.json`; the unchanged graph-v1 baseline is
recorded separately in `results/qaeg_v1_baseline_manifest.json`.

## V1 post-hoc validation snapshot

The offline batch was applied to already completed artifacts with these
observed graph-status counts. They were reproduced with the current
implementation on 2026-07-10 using `--no-write-per-run`; each batch completed
without a processing error:

- discovery/probe corpus: 628 runs, 627 `PASS`, one `FAIL`;
- review-candidate copy: 106 runs, all `PASS`;
- existing live PaperBench set: ten runs, all `PASS`.

These numbers are post-hoc compiler/verifier plumbing and triage checks. The
106-run copy is not an independent replication, and `PASS` is not a score of
model reasoning or scientific novelty. None of the counts proves a new
quantum algorithm, end-to-end speedup, or model-performance improvement. The
single graph failure is an audit target, not evidence that the other 627 runs
contain accepted claims.

The handoff provides an aggregate human-review narrative, but the 106-run
directory is not a machine-readable expert-labelled dataset. It copies the 78
heuristic `USEFUL_SUBROUTINE_CANDIDATE` rows and 28 heuristic
`HIGH_PRIORITY_EXPERT_REVIEW` rows selected from the 628-run overview. No
per-run blinded rating or `batch_001`-`batch_022` assignment is present. Until
those labels exist, screening false-positive rate, recall, and expert-review
precision are undefined and must not be reported.

## What is not implemented

The current system compiles a graph only after the ordinary sequential run is
complete. LLM actions do not yet perform online constrained graph edits, and
QAEG is not the workflow state. An online graph-native action interface is
future research and would require an explicit redesign and review; it must not
be described as a present capability.

Cross-run opportunity graphs, automated counterfactual graph repair, and
learned graph ranking are also not part of this implementation. In particular,
no GNN or learned graph judge is deployed or required. Near-term evaluation
should remain deterministic and use human expert review for scientific
judgment.

## Claim boundary

QAEG certifies consistency of a represented public run relative to the curated
runtime registry and the saved authoritative B decision. It does not prove
that generated algorithm text is correct, optimal, globally novel, physically
implementable, or asymptotically faster end to end. Its intended use is
auditing, failure localization, and conservative expert-review triage.
