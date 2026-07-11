# QuantumMindLite Soundness Contract

## Core runtime contract

The runtime evaluates a serialized `RunState` against a curated primitive
registry. It decides whether the represented public problem supports an
asymptotic quantum-speedup hypothesis at the candidate claim scope. It does not
prove that generated algorithm text is correct, optimal, novel, or implementable
end to end.

Barrier blocked scopes are catalog data in `primitives.yaml`, not model-authored
severity. A `SUPPORTED` barrier blocks a candidate at scope `s` iff `s` is an
explicit member of that barrier's `blocked_scopes`. An `UNKNOWN` barrier at the
claimed scope makes the result conditional, not negative. Catalog caveats with
`blocked_scopes=[]` never veto a claim by themselves.

The runtime exposes only barriers registered for plausible pathways, the
selected pathway, or a structurally matching diagnostic pattern. After a
candidate is selected, barriers belonging only to unselected alternatives do
not enter the final decision state. Catalog satisfaction conditions are checked
against the immutable public access model, output contract, and promises; when
they are met, the corresponding obstruction is deterministically
`NOT_APPLICABLE`. Entries labelled `speedup_class: NONE` are diagnostic and
cannot be selected as quantum pathways.

B1-B10 are the only authoritative validation rules. D only maps B's result to
a route and cannot upgrade it.

## Offline QAEG sidecar contract

QAEG deterministically projects a completed public `RunState`, its
`DecisionCard`, and the public runtime primitive/barrier registry into typed
nodes and edges. It does not participate in the sequential workflow and cannot
change state, B checks, the authoritative verdict, or D's route. It never calls
an LLM or API and never reads PaperBench gold/evidence data.

`process_run_dir` first requires the saved `decision.json` to equal a fresh
`build_decision(state, registry)` result. The graph verifier then inspects the
actual nodes and edges. Its five hard checks cover the represented support
subgraph, the complete set of expected registry-derived obligations, blocking
barriers, graph/B-projection integrity, and the novelty boundary. A sixth
generic-wrapper check is diagnostic only.

The graph outputs have three distinct meanings:

- `authoritative_verdict` and `authoritative_scope` are projections of B's
  decision and remain authoritative;
- `graph_status` reports whether the sidecar representation passes, warns, or
  fails its hard graph checks;
- `claim_accepted` is true only for an authoritative `POSITIVE` verdict when
  `graph_status` is `PASS` and every hard graph check is exactly `PASS`.

Consequently, `graph_status: PASS` does not imply a positive claim. A validly
represented negative run can pass the graph checks while `claim_accepted` is
false. `WARN` preserves an unresolved graph obligation or boundary; it is not
permission to strengthen a claim.

## Downward-only screening contract

`QAEG-screen-v0.1` runs after the unchanged graph verifier. Its trusted inputs
are the public `RunState`, the graph/decision projection, and the public
registry. The screening module does not read `input.json`, `trace.jsonl`, or
PaperBench gold/evidence, and it cannot write to the state, decision, graph, or
graph report.

The screen deterministically classifies represented output alignment, access
upgrade, oracle construction, classical baseline, and candidate universe. Its
`research_disposition` controls research triage only. It is distinct from the
authoritative B verdict, `graph_status`, and `claim_accepted`:

- `KEEP_FOR_EXPERT_REVIEW` requires `graph_status: PASS` and
  `claim_accepted=true`;
- the converse does not hold, because an accepted graph can be demoted or
  deferred by screening obligations; and
- no screening disposition can upgrade or alter B, D, or the graph report.

Family grouping is also deterministic. Its key is normalized parent identity,
selected primitive, original output type, provided access, and candidate
universe; a missing parent is replaced by the individual run identity.
Canonical and top-k outputs are reproducible triage views, not additional
validation rules.

## Assumptions

A1. The primitive registry and its source-backed complexity/scope labels are
correct.

A2. `ProblemCard` is constructed deterministically from the public problem
fields and is not rewritten by downstream actions.

A3. Action ownership, selection-scoped barrier filtering, catalog
reconciliation, and monotone merges within the selected pathway hold.

A4. B1-B10 are executed on the serialized `RunState` without evaluator data.

A5. For QAEG processing, the public runtime registry used to rebuild the
decision is the same registry used to project obligations and registry nodes.

A6. The deterministic graph compiler and verifier execute over the serialized
state, rebuilt decision, public registry, and their projected nodes/edges
without evaluator data.

A7. Screening classifications are interpreted only as consistency of the
represented public fields with the fixed `QAEG-screen-v0.1` rules, not as facts
about an unrepresented source task or the literature.

## Theorem

If `build_decision` returns `POSITIVE` at scope `s`, then there exists exactly
one selected `PLAUSIBLE` registry primitive `p` such that:

- `p`'s required structures, access model, output contract, and promises are
  represented;
- `p` is source-labelled `ASYMPTOTIC`;
- the candidate contains a nonempty scheme and complexity certificate;
- no supported catalog blocking barrier blocks `s`;
- `s` does not exceed `p`'s supported scope;
- no forbidden global-novelty claim is made for a known case;
- no gold/evidence field is visible.

## Proof Sketch

`build_decision` returns `POSITIVE` only after all invalid, negative, and
conditional verdict exits have been bypassed. B1 passing gives exactly one
selected `PLAUSIBLE` registry match or an explicit no-candidate result with
zero `PLAUSIBLE` matches; the no-candidate case exits as `NEGATIVE`, so the
positive case has exactly one selected match.
B2 passing gives a registry entry for that match and exact required-structure
containment. B3 passing gives `ASYMPTOTIC`, a nonempty scheme, a represented
classical baseline, and a scope-relevant quantum complexity field. B4 and B5
give access and public output compatibility. B6 gives required promise
containment in the public problem. B7 passing excludes a supported catalog
blocker at `s`. B8 passing prevents scope escalation. B9 passing excludes
forbidden global-novelty claims for known or directly prior cases. B10 passing
excludes evaluator-only gold/evidence fields.

Therefore the theorem follows by direct conjunction of B1-B10 under A1-A4.

## QAEG corollary

If `process_run_dir` returns a graph report with `claim_accepted=true`, then:

- the saved decision equals a freshly rebuilt B1-B10 decision and its
  authoritative verdict is `POSITIVE`;
- the graph digest, node/edge identifiers, endpoints, complete B1-B10
  projection, and projected `DecisionCard` content are internally consistent;
- the unique represented claim has one plausible selected match grounded in a
  known registry primitive, all required represented structure edges, and its
  scheme and scope-relevant complexity support;
- all eight represented registry-derived obligations are satisfied;
- no represented supported or unknown barrier blocks the claimed scope; and
- the represented novelty status stays within the represented prior-art
  boundary.

This follows from the equality check against `build_decision`, followed by
`G1`-`G5` all returning `PASS`. It is a graph certificate for the serialized
claim under A1-A6, not an additional scientific verdict.

The core theorem is a machine-tested consistency/safety theorem relative to
A1-A4. It is not a formal proof that a generated quantum algorithm is correct,
optimal, novel, or implementable end to end.

The QAEG corollary has the same scientific boundary. It does not establish that
the LLM's scheme is mathematically correct, that registry assumptions hold in
the physical problem, that the claim is globally novel, or that an end-to-end
advantage exists. Online constrained action-level graph editing is not
implemented and is not covered by this contract. No GNN or learned graph judge
is part of the trusted base.

Likewise, `research_disposition` is not a correctness or novelty label. The
handoff contains an aggregate human-review narrative, but the 106 copied
candidates have only heuristic queue labels in the repository, with no per-run
blinded ratings or `batch_001`-`batch_022` assignments. False-positive rate,
recall, and expert-review precision are therefore outside the present evidence
base.
