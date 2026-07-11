# AlgorithmWiki Third-Pass Starting State

- Unresolved row count: 376
- Unresolved reason distribution: {'No second-pass rule could identify source-backed task semantics.': 372, 'source-backed I/O reconstruction is still insufficient': 2, 'public_leakage_term_in_name_or_statement': 1, 'missing_size_parameters': 1}
- Source link type distribution: {'acm': 34, 'arxiv': 4, 'citeseerx': 9, 'doi': 7, 'pdf': 61, 'sciencedirect': 20, 'siam': 13, 'unknown': 228}
- Domain distribution: {'combinatorics': 1, 'image_processing': 2, 'string': 1, 'unknown': 372}
- Rows with DOI/arXiv/ACM/SIAM/ScienceDirect/CiteSeerX/PDF/unknown links: {'acm': 1, 'arxiv': 4, 'citeseerx': 5, 'doi': 76, 'pdf': 56, 'sciencedirect': 20, 'unknown': 214}

## Examples Of 30 Unresolved Rows
- AW-000002 Karpinski: No second-pass rule could identify source-backed task semantics. (source_link_type=citeseerx, domain=unknown)
- AW-000004 Larmore: No second-pass rule could identify source-backed task semantics. (source_link_type=sciencedirect, domain=unknown)
- AW-000009 Klinz: No second-pass rule could identify source-backed task semantics. (source_link_type=doi, domain=unknown)
- AW-000015 Lawrence, Reilly: public_leakage_term_in_name_or_statement (source_link_type=unknown, domain=string)
- AW-000100 Psinger: No second-pass rule could identify source-backed task semantics. (source_link_type=sciencedirect, domain=unknown)
- AW-000133 UKF: No second-pass rule could identify source-backed task semantics. (source_link_type=pdf, domain=unknown)
- AW-000134 Compressed Extended KF: No second-pass rule could identify source-backed task semantics. (source_link_type=citeseerx, domain=unknown)
- AW-000174 Harrow (Quantum): No second-pass rule could identify source-backed task semantics. (source_link_type=unknown, domain=unknown)
- AW-000237 Williams' p + 1 algorithm: No second-pass rule could identify source-backed task semantics. (source_link_type=unknown, domain=unknown)
- AW-000261 Covanov and Thomé: No second-pass rule could identify source-backed task semantics. (source_link_type=unknown, domain=unknown)
- AW-000263 Harvey Hoeven Lecerf: No second-pass rule could identify source-backed task semantics. (source_link_type=arxiv, domain=unknown)
- AW-000284 A. Chalmers T. Davis and E. Reinhard 2002: No second-pass rule could identify source-backed task semantics. (source_link_type=unknown, domain=unknown)
- AW-000287 J. J. Koenderink and W. Richards 1988: No second-pass rule could identify source-backed task semantics. (source_link_type=unknown, domain=unknown)
- AW-000288 Lindeberg (1994): No second-pass rule could identify source-backed task semantics. (source_link_type=unknown, domain=unknown)
- AW-000292 T. Lindeberg and J. Garding (1997): No second-pass rule could identify source-backed task semantics. (source_link_type=unknown, domain=unknown)
- AW-000293 Lindeberg 2005: No second-pass rule could identify source-backed task semantics. (source_link_type=unknown, domain=unknown)
- AW-000294 The Wang and Brady corner detection algorithm 1995: No second-pass rule could identify source-backed task semantics. (source_link_type=unknown, domain=unknown)
- AW-000298 Geert Willems Tinne Tuytelaars and Luc van Gool (2008): No second-pass rule could identify source-backed task semantics. (source_link_type=citeseerx, domain=unknown)
- AW-000299 Tao Luo, Zaifeng Shi and Pumeng Wang: No second-pass rule could identify source-backed task semantics. (source_link_type=unknown, domain=unknown)
- AW-000300 T. Lindeberg DoG 2012: No second-pass rule could identify source-backed task semantics. (source_link_type=unknown, domain=unknown)
- AW-000301 T. Lindeberg DoG 2015: No second-pass rule could identify source-backed task semantics. (source_link_type=unknown, domain=unknown)
- AW-000303 Hessain Determinant Lindeberg 1994: No second-pass rule could identify source-backed task semantics. (source_link_type=unknown, domain=unknown)
- AW-000304 Hessain Determinant Lindeberg 1998: No second-pass rule could identify source-backed task semantics. (source_link_type=unknown, domain=unknown)
- AW-000307 Spatio-temporal Geert Willems Tinne Tuytelaars and Luc van Gool (2008): No second-pass rule could identify source-backed task semantics. (source_link_type=unknown, domain=unknown)
- AW-000309 Maximally stable extremal regions Matas 2002: No second-pass rule could identify source-backed task semantics. (source_link_type=unknown, domain=unknown)
- AW-000310 A. Baumberg. 2000: No second-pass rule could identify source-backed task semantics. (source_link_type=unknown, domain=unknown)
- AW-000311 Y. Dufournaud C. Schmid and R. Horaud 2000: No second-pass rule could identify source-backed task semantics. (source_link_type=unknown, domain=unknown)
- AW-000313 T. Tuytelaars and L. Van Gool 2000: No second-pass rule could identify source-backed task semantics. (source_link_type=unknown, domain=unknown)
- AW-000319 CNN Based Gatys Leon A 2001: No second-pass rule could identify source-backed task semantics. (source_link_type=unknown, domain=unknown)
- AW-000320 P.Hanrahan and W.Krueger 1993: No second-pass rule could identify source-backed task semantics. (source_link_type=unknown, domain=unknown)

## Why Previous Passes Did Not Recover Them

The remaining rows are mostly unknown-domain rows with author/title fragments, empty source links, PDF-only links, publisher pages that returned only metadata, or names whose task/input/output semantics were too thin for the first two conservative reconstruction passes.

## Third-Pass Search Plan

Each row receives a saturation certificate. The script attempts local AlgorithmWiki and previous-pass cache records, original links, Crossref, OpenAlex, Semantic Scholar, arXiv, DBLP, publisher metadata, CiteSeerX handling, Wikipedia, Wikidata, NIST DADS/reference-family checks, exact public algorithm-reference checks, course-notes availability, and a recorded general-web endpoint check. A row stops only after recovery, duplicate/blocked classification, or at least three cycles with five source families covered and two consecutive zero-new-fact cycles.
