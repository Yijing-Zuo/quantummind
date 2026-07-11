# AlgorithmWiki Rich Second-Pass Starting State

- Total unresolved rows: 545

## Failure Reason Distribution
- missing_concrete_problem_statement: 530
- unknown_access_model: 530
- unknown_input_model: 527
- unknown_output_contract: 519
- missing_size_parameters: 51
- public_leakage_term_in_name_or_statement: 3
- missing_algorithm_name: 1

## Source Link Type Distribution
- unknown: 329
- pdf: 92
- acm: 48
- sciencedirect: 31
- siam: 20
- citeseerx: 11
- doi: 7
- arxiv: 7

## Domain Distribution
- unknown: 541
- matrix_linear_algebra: 2
- parallel_algorithms: 2

## Existing Source Record Type Distribution
- algorithm_wiki: 22
- doi_metadata: 2

## Examples Of Unresolved Rows
- AW-000002 Karpinski: link_type=citeseerx; time=O(n^{0.6}); params=n: number of elements; source=https://citeseerx.ist.psu.edu/pdf/4af91d48d513fbcf64e277c07c17615c31726ec6
- AW-000004 Larmore: link_type=sciencedirect; time=O(n^{1.6}); params=n: number of elements; source=https://www.sciencedirect.com/science/article/pii/0196677487900526
- AW-000009 Klinz: link_type=doi; time=O(\sigma^{3/2}); params=\sigma: sum of integers in the set (\sigma \geq t); source=https://doi.org/10.1002/(SICI)1097-0037(199905)33:3%3C189::AID-NET5%3E3.0.CO2-2
- AW-000010 Eppstein: link_type=sciencedirect; time=\tilde{O}(n \max(S)); params=n: number of elements in the set, S: the set, t: target sum; source=https://www.sciencedirect.com/science/article/abs/pii/S019667749690841X?via%3Dihub
- AW-000013 Lokshtanov: link_type=acm; time=\tilde{O}(n^3 t); params=n: number of elements in the set, t: target sum; source=https://dl.acm.org/doi/abs/10.1145/1806689.1806735
- AW-000015 Lawrence, Reilly: link_type=unknown; time=O(nm); params=n: number of sequences, m: length of sequences; source=https://www.ncbi.nlm.nih.gov/pubmed/2184437
- AW-000034 Brute Force: link_type=unknown; time=O(4^n); params=n: number of matrices; source=-
- AW-000057 Bjorck-Pereyra: link_type=unknown; time=O(n^2); params=n: number of variables and number of equations; source=https://www.jstor.org/stable/2004623?seq=1
- AW-000063 Naive Implementation: link_type=unknown; time=O(kn^2); params=n: number of points, k: dimension of space; source=-
- AW-000081 Rabin-Karp (RK) algorithm: link_type=pdf; time=O(mn); params=m: pattern length, n: length of searchable text; source=https://pdfs.semanticscholar.org/c47d/151f09c567013761632c89e237431c6291a2.pdf
- AW-000088 Rabin–Scott powerset construction: link_type=unknown; time=O(2^n); params=n: number of states; source=https://ieeexplore.ieee.org/document/5392601
- AW-000089 Karatsuba Algorithm: link_type=unknown; time=O(n^{1.58}); params=n: length of one of the integers, in bits; source=http://www.mathnet.ru/php/archive.phtml?wshow=paper&jrnid=dan&paperid=26729&option_lang=eng
- AW-000090 Toom-3: link_type=pdf; time=O(n^{1.46}); params=n: length of one of the integers, in bits; source=https://www.ams.org/journals/tran/1969-142-00/S0002-9947-1969-0249212-8/S0002-9947-1969-0249212-8.pdf
- AW-000091 Long Multiplication: link_type=unknown; time=O(n^2); params=n: length of one of the integers, in bits; source=none
- AW-000100 Psinger: link_type=sciencedirect; time=O(n \max(S)); params=n: the number of integers in the set, \max(S): largest number in the set; source=https://www.sciencedirect.com/science/article/abs/pii/S0196677499910349

## Top Reasons V1 Could Not Make Cards

The first rich pass rejected rows when it could not identify a concrete public task, input semantics, output semantics, or conservative access model. The leading unresolved cluster is author-only or variant-title rows whose AlgorithmWiki metadata exposes complexity and parameters but not the named problem. Several rows also had source metadata failures, forbidden public leakage terms in names, or missing size parameters. The second pass will use DOI/arXiv/source titles and public metadata more aggressively, but rows remain unresolved if source-backed I/O cannot be reconstructed.
