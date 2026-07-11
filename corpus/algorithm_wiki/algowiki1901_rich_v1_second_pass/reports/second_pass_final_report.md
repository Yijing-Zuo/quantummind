# AlgorithmWiki Rich Second-Pass Final Report

- Original unresolved count: 545
- Recovered context count: 169
- Recovered probe count: 21
- Still unresolved count: 376
- Recovery rate: 31.0%
- Source quality distribution: {'HIGH': 236, 'LOW': 97, 'MEDIUM': 190}
- Domain distribution: {'combinatorics': 38, 'computational_geometry': 29, 'data_structures': 4, 'dynamic_programming': 9, 'graph': 13, 'image_processing': 39, 'matrix_linear_algebra': 3, 'parallel_algorithms': 16, 'string': 18}
- Probe type distribution: {'estimation_sampling_probe': 2, 'search_witness_probe': 19}
- Context audit severity: {'NONE': 169}
- Probe audit severity: {'NONE': 21}
- Context mock validation ok: True with 100 samples.
- Probe mock validation ok: True with 21 samples.
- Human review result: 100 recovered context cards reviewed, all ACCEPT.
- Human probe review result: 21 recovered probe cards reviewed, all ACCEPT.
- Representative recovered high-value context cards: AW-000010 Eppstein; AW-000013 Lokshtanov; AW-000034 Brute Force; AW-000057 Bjorck-Pereyra; AW-000063 Naive Implementation; AW-000081 Rabin-Karp (RK) algorithm; AW-000088 Rabin–Scott powerset construction; AW-000089 Karatsuba Algorithm; AW-000090 Toom-3; AW-000091 Long Multiplication
- Representative recovered high-value probe cards: AW-000156-SP0001 Hashing; AW-000233-SP0002 Trial division; AW-000234-SP0003 Wheel factorization; AW-000238-SP0004 Lenstra elliptic curve factorization; AW-000239-SP0005 Fermat's factorization method; AW-000240-SP0006 Euler's factorization method; AW-000241-SP0007 Dixon's algorithm; AW-000242-SP0008 Continued fraction factorization (CFRAC); AW-000243-SP0009 Quadratic sieve; AW-000243-SP0010 Quadratic sieve
- Representative still unresolved rows: AW-000002 Karpinski (No second-pass rule could identify source-backed task semantics.); AW-000004 Larmore (No second-pass rule could identify source-backed task semantics.); AW-000009 Klinz (No second-pass rule could identify source-backed task semantics.); AW-000015 Lawrence, Reilly (public_leakage_term_in_name_or_statement); AW-000100 Psinger (No second-pass rule could identify source-backed task semantics.); AW-000133 UKF (No second-pass rule could identify source-backed task semantics.); AW-000134 Compressed Extended KF (No second-pass rule could identify source-backed task semantics.); AW-000174 Harrow (Quantum) (No second-pass rule could identify source-backed task semantics.); AW-000237 Williams' p + 1 algorithm (No second-pass rule could identify source-backed task semantics.); AW-000261 Covanov and Thomé (No second-pass rule could identify source-backed task semantics.)

## Why Rows Remain Unresolved

Rows remain in still_review_needed when public metadata and source titles did not identify a concrete task, input semantics, output semantics, or conservative access model. The second pass deliberately did not convert author-only rows or rows with forbidden public terms into ready cards.

## Merge Recommendation

Optional merge staging commands (review first): copy recovered context/probe YAML and metadata sidecars from algowiki1901_rich_v1_second_pass into a future v2 package, then rerun audits and mock validation. Do not overwrite algowiki1901_rich_v1 in place.

Recommended live first-50 recovered probe command: commands/run_live_recovered_probe_first_50_openai.bat.
Recommended live first-50 recovered context command: commands/run_live_recovered_context_first_50_openai.bat.

No OpenAI calls were made. No core QuantumMindLite workflow, B-rule, route, registry, PaperBench, OpenAI provider, or prompt behavior was modified. These recovered cards are discovery inputs, not gold-labeled benchmark cases.
