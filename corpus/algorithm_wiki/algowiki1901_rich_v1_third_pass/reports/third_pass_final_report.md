# AlgorithmWiki Rich Third-Pass Source-Saturation Report

1. Starting unresolved count: 376
2. Recovered context count: 142
3. Recovered probe count: 199
4. Still unresolved saturated count: 234
5. Recovery rate: 37.8%
6. Cycles completed: 4
7. Total queries attempted: 5410
8. Total URLs/API endpoints attempted: 2813
9. Source family coverage: {'algorithm_wiki_local': 376, 'arxiv': 376, 'citeseerx': 229, 'course_notes': 229, 'cp_algorithms': 229, 'crossref': 376, 'dblp': 270, 'general_web_search': 229, 'local_previous_cache': 376, 'nist_dads': 229, 'openalex': 270, 'original_source': 376, 'publisher_abstract': 270, 'semantic_scholar': 270, 'the_algorithms': 229, 'wikidata': 270, 'wikipedia': 376}
10. New sources discovered: 692
11. New facts discovered: 7051
12. Rows recovered because of each source family: {'algorithm_wiki_local': 142, 'arxiv': 142, 'crossref': 142, 'dblp': 39, 'local_previous_cache': 142, 'openalex': 39, 'original_source': 142, 'publisher_abstract': 39, 'semantic_scholar': 39, 'wikidata': 39, 'wikipedia': 142}
13. Rows still unresolved by terminal status: {'AMBIGUOUS_AUTHOR_TITLE_FRAGMENT': 2, 'BLOCKED_BY_PAYWALL_OR_MISSING_SOURCE': 4, 'DUPLICATE_OR_VARIANT_ONLY': 1, 'SATURATED_NO_RECOVERY': 227}
14. Examples of successfully recovered difficult rows: ['AW-000133 UKF', 'AW-000134 Compressed Extended KF', "AW-000237 Williams' p + 1 algorithm", 'AW-000261 Covanov and Thomé', 'AW-000263 Harvey Hoeven Lecerf', 'AW-000287 J. J. Koenderink and W. Richards 1988', 'AW-000292 T. Lindeberg and J. Garding (1997)', 'AW-000298 Geert Willems Tinne Tuytelaars and Luc van Gool (2008)', 'AW-000299 Tao Luo, Zaifeng Shi and Pumeng Wang', 'AW-000300 T. Lindeberg DoG 2012', 'AW-000301 T. Lindeberg DoG 2015', 'AW-000307 Spatio-temporal Geert Willems Tinne Tuytelaars and Luc van Gool (2008)']
15. Examples of saturated unresolved rows and why: ['AW-000002 Karpinski (SATURATED_NO_RECOVERY)', 'AW-000004 Larmore (SATURATED_NO_RECOVERY)', 'AW-000009 Klinz (SATURATED_NO_RECOVERY)', 'AW-000015 Lawrence, Reilly (BLOCKED_BY_PAYWALL_OR_MISSING_SOURCE)', 'AW-000100 Psinger (SATURATED_NO_RECOVERY)', 'AW-000174 Harrow (Quantum) (SATURATED_NO_RECOVERY)', 'AW-000284 A. Chalmers T. Davis and E. Reinhard 2002 (SATURATED_NO_RECOVERY)', 'AW-000288 Lindeberg (1994) (SATURATED_NO_RECOVERY)', 'AW-000293 Lindeberg 2005 (SATURATED_NO_RECOVERY)', 'AW-000294 The Wang and Brady corner detection algorithm 1995 (BLOCKED_BY_PAYWALL_OR_MISSING_SOURCE)', 'AW-000303 Hessain Determinant Lindeberg 1994 (SATURATED_NO_RECOVERY)', 'AW-000304 Hessain Determinant Lindeberg 1998 (SATURATED_NO_RECOVERY)']
16. Non-terminal row count: 0
17. Saturation is operational: it means the configured independent query/source families and retry cycles stopped yielding distinct facts, not that no information exists anywhere.
18. Confirmation: no OpenAI calls were made.
19. Confirmation: no core QuantumMindLite workflow, B-rules, route logic, registry prerequisites, PaperBench data, provider, or prompts were changed.
20. Recommended merge command: python scripts/datasets/algowiki_merge_rich_passes.py --v1-root corpus/algorithm_wiki/algowiki1901_rich_v1 --second-pass-root corpus/algorithm_wiki/algowiki1901_rich_v1_second_pass --third-pass-root corpus/algorithm_wiki/algowiki1901_rich_v1_third_pass
21. Recommended first 50 recovered probe live command: commands/run_live_third_pass_recovered_probe_first_50_openai.bat

Probe positives, if run later, are query/subroutine hypotheses and not end-to-end claims.

## Post-Generation Audit And Mock Validation

- Context audit: 142 total, 142 ACCEPT, severity NONE, thresholds passed.
- Probe audit: 199 total, 199 ACCEPT, severity NONE, thresholds passed.
- Context mock validation: ok=True, 100 sampled mock analyze runs passed.
- Probe mock validation: ok=True, 50 sampled mock analyze runs passed.
- Human-level review files: reports/recovered_context_review.md reviews 100 recovered context cards; reports/recovered_probe_review.md reviews 60 recovered probe cards.
- Merge recommendation: manifests/merged_ready_public_context_recommendation.csv and manifests/merged_ready_public_probe_recommendation.csv were regenerated after validation.
