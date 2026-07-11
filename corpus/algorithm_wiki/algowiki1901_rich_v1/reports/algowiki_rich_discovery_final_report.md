# AlgorithmWiki Rich Discovery Final Report

1. Public blind is no longer the main discovery input because it intentionally suppresses names and provenance and often collapses task semantics into conservative generic phrasing.
2. Public context is the main whole-algorithm input because it preserves source-backed names, classical I/O, complexity, bottlenecks, and uncertainty while excluding evaluator labels and verdict targets.
3. Public probe exists for assumption-bearing subroutine and query-model reformulations; it is explicitly not an end-to-end claim.
4. Rows processed: 1901.
5. Web-enriched rows: 1901 records emitted by the enrichment stage.
6. Context ready cards: 1356.
7. Probe ready cards: 600.
8. Rows still review-needed after web: 545.
9. Source quality distribution: {'HIGH': 2436, 'LOW': 1563, 'MEDIUM': 6}.
10. Domain distribution: {'combinatorics': 10, 'computational_geometry': 73, 'data_structures': 30, 'dynamic_programming': 16, 'graph': 444, 'image_processing': 24, 'matrix_linear_algebra': 97, 'numerical_analysis': 12, 'optimization': 6, 'parallel_algorithms': 354, 'randomized_sampling': 6, 'robotics': 2, 'sorting': 170, 'string': 112}.
11. Output contract distribution: {'approximation_solution': 6, 'assignment_or_schedule': 5, 'data_structure_output': 29, 'estimate': 13, 'full_classical_output': 97, 'full_sequence_output': 170, 'full_solution': 966, 'multiple_witnesses': 6, 'one_witness': 22, 'path_or_tree': 42}.
12. Probe type distribution: {'estimation_sampling_probe': 30, 'graph_walk_probe': 213, 'period_structure_probe': 6, 'search_witness_probe': 351}.
13. Audit results: context {'NONE': 1356}; probe {'NONE': 600}.
14. Mock validation results: context ok=True; probe ok=True.
15. Human-level review results: generated stratified reviews accept the sampled cards unless audit artifacts mark them for regeneration.
16. Representative high-value context cards: AW-000001 Melhorn's Approximation algorithm; AW-000003 Klawe Mumey; AW-000005 Hierarchical Navigable Small World (HNSW); AW-000006 Pisinger; AW-000007 Faaland; AW-000008 Pferschy; AW-000011 Serang; AW-000012 Serang; AW-000014 Valentin Polishchuk, and Jukka Suomela; AW-000016 Lawrence Gibbs Sampling.
17. Representative high-value probe cards: AW-000001-P0001 Melhorn's Approximation algorithm; AW-000005-P0002 Hierarchical Navigable Small World (HNSW); AW-000005-P0003 Hierarchical Navigable Small World (HNSW); AW-000006-P0004 Pisinger; AW-000007-P0005 Faaland; AW-000008-P0006 Pferschy; AW-000011-P0007 Serang; AW-000012-P0008 Serang; AW-000012-P0009 Serang; AW-000014-P0010 Valentin Polishchuk, and Jukka Suomela.
18. Representative unresolved rows: AW-000002 Karpinski; AW-000004 Larmore; AW-000009 Klinz; AW-000010 Eppstein; AW-000013 Lokshtanov; AW-000015 Lawrence, Reilly; AW-000034 Brute Force; AW-000057 Bjorck-Pereyra; AW-000063 Naive Implementation; AW-000081 Rabin-Karp (RK) algorithm.
19. Known limitations: source metadata can be thinner than full papers; PDF bodies were not downloaded; some rows remain author/title fragments; probes rely on introduced oracle assumptions.
20. Recommended first 50 context live command: commands/run_live_context_first_50_openai.bat.
21. Recommended first 50 probe live command: commands/run_live_probe_first_50_openai.bat.
22. Confirmation: no OpenAI calls were made by the corpus-generation scripts.
23. Confirmation: no core QuantumMindLite workflow or B-rule logic was weakened.
24. Confirmation: these are discovery inputs, not gold-labeled benchmark cases.
