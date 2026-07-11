# Registry V1 Probe Starting State

- Timestamp: 2026-06-29T04:57:55.631876+00:00
- Context cards ready: 1356
- Public probe cards ready: 600
- Existing probe type distribution: {'estimation_sampling_probe': 30, 'graph_walk_probe': 213, 'period_structure_probe': 6, 'search_witness_probe': 351}
- Existing public probes were generated before registry_v1 and mostly expose older search, graph-walk, estimation, and period shapes.
- They generally do not carry the access models, output contracts, and required promises for the four registry_v1 primitives.
- Registry-v1 primitives screened here: quantum_minimum_finding, quantum_backtracking_tree_search, quantum_walk_marked_vertex_search, quantum_counting.
- Boundary: all generated cards must be query/subroutine probes only; no gate-level, full-output, novelty, or end-to-end speedup claim is supported.
- Overgeneration risks: minimum/best wording can hide full optimization; tree/path wording can hide full path output; graph-walk wording can hide traversal; count wording can hide enumeration.

Preflight note: the literal `python` command resolves to the Windows Store alias on this machine, so offline checks were run with the bundled Codex Python interpreter.
