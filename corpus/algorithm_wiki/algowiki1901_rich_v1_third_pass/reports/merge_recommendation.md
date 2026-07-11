# AlgorithmWiki Rich Merge Recommendation

- Timestamp: 2026-06-28T19:44:05.199284+00:00
- Recommended context cards: 1510
- Context cards by pass: {'second_pass': 161, 'third_pass': 138, 'v1': 1211}
- Recommended probe cards: 820
- Probe cards by pass: {'second_pass': 21, 'third_pass': 199, 'v1': 600}
- Third-pass replacement recommendations: 0

The recommendation preserves v1 and second-pass directories, then stages a reviewable merged manifest. Context rows are deduplicated by algorithm_id and card digest with later-pass rows preferred when they are more source-supported. Probe rows may coexist when probe_id is unique and card digest/parent pairs differ.

No OpenAI calls are performed by this merge script.
