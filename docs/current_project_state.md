# Current Project State

Generated: 2026-07-10

## Runtime

The production runtime remains the lightweight sequential design:

- one generic `Agent`;
- one deterministic `Orchestrator`;
- typed `ActionSpec` ownership and monotone state merges;
- one public, deterministic B1-B10 validator; and
- D as a route mapper that never upgrades B's verdict.

No workflow, Agent action, or D rule was converted to a graph workflow. No
GNN, learned graph judge, planner, or new model/API dependency is deployed.

## Offline QAEG Sidecar

QAEG is now an offline deterministic compiler/verifier for completed runs. It
reads the public `state.json`, checks that `decision.json` still equals a fresh
B1-B10 decision, and combines those artifacts with the public runtime registry
to build typed evidence nodes and edges. It writes per-run graph artifacts and
can aggregate a corpus without any LLM or API call.

The verifier genuinely traverses graph nodes and edges for support,
obligations, barriers, integrity, and novelty checks. B1-B10 remain the sole
authority. `graph_status` describes the health of the graph representation;
`claim_accepted` is separately true only for an already B-positive claim whose
five hard graph checks all pass. A B-negative run may therefore have a passing
graph while its claim remains unaccepted.

The implementation is a completed-run sidecar. Online constrained graph edits
by LLM actions are not implemented and must be described only as possible
future work.

## QAEG-screen-v0.1

The existing graph compiler/verifier remains unchanged. The new screening
module runs afterward and reads only the public state, graph/decision
projection, and public registry. It does not read `input.json`, `trace.jsonl`,
or PaperBench gold/evidence, and it makes no API or model call.

The screen is downward-only. It records output alignment, access upgrade,
oracle, baseline, and candidate-universe types, then assigns a separate
`research_disposition`. That field cannot change B, D, `graph_status`, or
`claim_accepted`. Family grouping and canonical selection are deterministic;
top-k output is family-deduplicated and excludes demoted, rejected,
source-repair, and invalid candidates. No GNN or weighted learned/heuristic
score decides the ordering.

Frozen aggregate files are:

- `results/fdv1_screening_v01_{summary,families,top9}.csv`
- `results/review_screening_v01_{summary,families,top9}.csv`

The zero-API replay produced:

| Existing artifact set | Research disposition | Families |
| --- | --- | ---: |
| 628 discovery/probe runs | 380 `DEMOTE_GENERIC`, 247 `REFORMULATE`, 1 `INVALID_STATE` | 594 |
| 106 copied review candidates | 78 `DEMOTE_GENERIC`, 28 `REFORMULATE` | 104 |

Both family-deduplicated top-nine files select the same nine candidate families
(the copied-run identifiers differ) and contain only non-generic `REFORMULATE`
candidates. This is a deterministic research queue, not a claim that those
candidates are correct, novel, or expert-approved.

## V1 Post-hoc Reprocessing Snapshot

The current artifact-level results are:

| Existing artifact set | Processed | QAEG status |
| --- | ---: | --- |
| discovery/probe runs | 628 | 627 `PASS`, 1 `FAIL` |
| review-candidate copy | 106 | 106 `PASS` |
| existing live PaperBench runs | 10 | 10 `PASS` |

These counts were reproduced on 2026-07-10 with the current batch script using
`--no-write-per-run`; all three invocations completed without a processing
error.

These are offline plumbing, consistency, and triage results over existing run
artifacts. The 106-run set contains copies selected for review and is not an
independent replication. The counts are not model-performance metrics, do not
measure scientific novelty, and do not prove a new quantum algorithm. The one
`FAIL` is an audit target; the other 627 discovery/probe graph passes do not
mean 627 accepted or positive claims.

The handoff contains an aggregate human-review narrative. The repository's
106-copy queue itself consists of 78 heuristic `USEFUL_SUBROUTINE_CANDIDATE`
rows and 28 heuristic `HIGH_PRIORITY_EXPERT_REVIEW` rows, with no per-run
blinded ratings or `batch_001`-`batch_022` assignments. False-positive rate,
recall, and expert-review precision therefore cannot yet be computed.

## Discovery Track

AlgorithmWiki rich and the completed final discovery run remain the main
discovery materials. Relevant locations include:

- `runs/final_discovery_run_v1/`
- `runs/final_discovery_run_v1_review_candidates/`
- `corpus/algorithm_wiki/algowiki1901_rich_v1/`
- `corpus/algorithm_wiki/algowiki1901_rich_v1_second_pass/`
- `corpus/algorithm_wiki/algowiki1901_rich_v1_third_pass/`

TACO and earlier public-blind AlgorithmWiki outputs remain controls or archived
stress data rather than the main discovery corpus.

## Next Work

1. Preserve the v1 and screening manifests when comparing later reruns.
2. Audit the single v1 graph failure at its reported field/action boundary.
3. Design blinded, parent-aware expert-review batches before reporting any
   screening accuracy metric.
4. Treat online constrained action graph edits as a separate future design
   question, not as an implemented feature.

GNN prioritization and learned graph judgment are intentionally out of scope.
Scientific acceptance remains a human expert decision supported by the public
registry, B1-B10, and auditable graph artifacts.

## Known Risks

- Live traces can contain sensitive operational metadata; review them before
  sharing and rotate any key that appeared in historical logs.
- Graph compilation inherits the correctness and coverage limits of the public
  registry and the serialized run state.
- A graph certificate establishes represented consistency, not correctness of
  free-form algorithm text or physical implementability.
- Probe results remain query/subroutine hypotheses and must not be promoted to
  gate-level or end-to-end claims without the required evidence.
