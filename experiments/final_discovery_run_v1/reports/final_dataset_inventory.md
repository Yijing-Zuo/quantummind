# Final Dataset Inventory

- Total READY tasks: 2525
- Total shards: 37
- READY by subset: {'paperbench10': 10, 'public_context_v1': 1356, 'public_probe_v1': 600, 'recovered_context_second_pass': 169, 'recovered_context_third_pass': 142, 'recovered_probe_second_pass': 21, 'recovered_probe_third_pass': 199, 'registry_v1_probes': 28}
- READY by kind: {'benchmark': 10, 'context': 1356, 'probe': 600, 'recovered_context': 311, 'recovered_probe': 220, 'registry_v1_probe': 28}

## Inclusion Notes
- Included 28 READY rows from registry_v1_probes (corpus\algorithm_wiki\algowiki1901_rich_v1\registry_v1_probes\manifests\ready_public_probe_registry_v1.csv).
- Included 600 READY rows from public_probe_v1 (corpus\algorithm_wiki\algowiki1901_rich_v1\manifests\ready_public_probe.csv).
- Included 1356 READY rows from public_context_v1 (corpus\algorithm_wiki\algowiki1901_rich_v1\manifests\ready_public_context.csv).
- Included 169 READY rows from recovered_context_second_pass (corpus\algorithm_wiki\algowiki1901_rich_v1_second_pass\manifests\recovered_context.csv).
- Included 21 READY rows from recovered_probe_second_pass (corpus\algorithm_wiki\algowiki1901_rich_v1_second_pass\manifests\recovered_probe.csv).
- Included 142 READY rows from recovered_context_third_pass (corpus\algorithm_wiki\algowiki1901_rich_v1_third_pass\manifests\recovered_context.csv).
- Included 199 READY rows from recovered_probe_third_pass (corpus\algorithm_wiki\algowiki1901_rich_v1_third_pass\manifests\recovered_probe.csv).
- Skipped public_blind control: no public blind cards found in expected locations.
- Skipped TACO control: corpus/taco/taco1000_v1 is not present.
- Included 10 PaperBench-10 command rows.

## Shards

| shard_id | subset | ready_count | output_dir |
| --- | --- | ---: | --- |
| fdv1_registry_v1_probes_001 | registry_v1_probes | 28 | runs/final_discovery_run_v1/fdv1_registry_v1_probes_001 |
| fdv1_public_probe_v1_001 | public_probe_v1 | 50 | runs/final_discovery_run_v1/fdv1_public_probe_v1_001 |
| fdv1_public_probe_v1_002 | public_probe_v1 | 50 | runs/final_discovery_run_v1/fdv1_public_probe_v1_002 |
| fdv1_public_probe_v1_003 | public_probe_v1 | 50 | runs/final_discovery_run_v1/fdv1_public_probe_v1_003 |
| fdv1_public_probe_v1_004 | public_probe_v1 | 50 | runs/final_discovery_run_v1/fdv1_public_probe_v1_004 |
| fdv1_public_probe_v1_005 | public_probe_v1 | 50 | runs/final_discovery_run_v1/fdv1_public_probe_v1_005 |
| fdv1_public_probe_v1_006 | public_probe_v1 | 50 | runs/final_discovery_run_v1/fdv1_public_probe_v1_006 |
| fdv1_public_probe_v1_007 | public_probe_v1 | 50 | runs/final_discovery_run_v1/fdv1_public_probe_v1_007 |
| fdv1_public_probe_v1_008 | public_probe_v1 | 50 | runs/final_discovery_run_v1/fdv1_public_probe_v1_008 |
| fdv1_public_probe_v1_009 | public_probe_v1 | 50 | runs/final_discovery_run_v1/fdv1_public_probe_v1_009 |
| fdv1_public_probe_v1_010 | public_probe_v1 | 50 | runs/final_discovery_run_v1/fdv1_public_probe_v1_010 |
| fdv1_public_probe_v1_011 | public_probe_v1 | 50 | runs/final_discovery_run_v1/fdv1_public_probe_v1_011 |
| fdv1_public_probe_v1_012 | public_probe_v1 | 50 | runs/final_discovery_run_v1/fdv1_public_probe_v1_012 |
| fdv1_public_context_v1_001 | public_context_v1 | 100 | runs/final_discovery_run_v1/fdv1_public_context_v1_001 |
| fdv1_public_context_v1_002 | public_context_v1 | 100 | runs/final_discovery_run_v1/fdv1_public_context_v1_002 |
| fdv1_public_context_v1_003 | public_context_v1 | 100 | runs/final_discovery_run_v1/fdv1_public_context_v1_003 |
| fdv1_public_context_v1_004 | public_context_v1 | 100 | runs/final_discovery_run_v1/fdv1_public_context_v1_004 |
| fdv1_public_context_v1_005 | public_context_v1 | 100 | runs/final_discovery_run_v1/fdv1_public_context_v1_005 |
| fdv1_public_context_v1_006 | public_context_v1 | 100 | runs/final_discovery_run_v1/fdv1_public_context_v1_006 |
| fdv1_public_context_v1_007 | public_context_v1 | 100 | runs/final_discovery_run_v1/fdv1_public_context_v1_007 |
| fdv1_public_context_v1_008 | public_context_v1 | 100 | runs/final_discovery_run_v1/fdv1_public_context_v1_008 |
| fdv1_public_context_v1_009 | public_context_v1 | 100 | runs/final_discovery_run_v1/fdv1_public_context_v1_009 |
| fdv1_public_context_v1_010 | public_context_v1 | 100 | runs/final_discovery_run_v1/fdv1_public_context_v1_010 |
| fdv1_public_context_v1_011 | public_context_v1 | 100 | runs/final_discovery_run_v1/fdv1_public_context_v1_011 |
| fdv1_public_context_v1_012 | public_context_v1 | 100 | runs/final_discovery_run_v1/fdv1_public_context_v1_012 |
| fdv1_public_context_v1_013 | public_context_v1 | 100 | runs/final_discovery_run_v1/fdv1_public_context_v1_013 |
| fdv1_public_context_v1_014 | public_context_v1 | 56 | runs/final_discovery_run_v1/fdv1_public_context_v1_014 |
| fdv1_recovered_context_second_pass_001 | recovered_context_second_pass | 100 | runs/final_discovery_run_v1/fdv1_recovered_context_second_pass_001 |
| fdv1_recovered_context_second_pass_002 | recovered_context_second_pass | 69 | runs/final_discovery_run_v1/fdv1_recovered_context_second_pass_002 |
| fdv1_recovered_probe_second_pass_001 | recovered_probe_second_pass | 21 | runs/final_discovery_run_v1/fdv1_recovered_probe_second_pass_001 |
| fdv1_recovered_context_third_pass_001 | recovered_context_third_pass | 100 | runs/final_discovery_run_v1/fdv1_recovered_context_third_pass_001 |
| fdv1_recovered_context_third_pass_002 | recovered_context_third_pass | 42 | runs/final_discovery_run_v1/fdv1_recovered_context_third_pass_002 |
| fdv1_recovered_probe_third_pass_001 | recovered_probe_third_pass | 50 | runs/final_discovery_run_v1/fdv1_recovered_probe_third_pass_001 |
| fdv1_recovered_probe_third_pass_002 | recovered_probe_third_pass | 50 | runs/final_discovery_run_v1/fdv1_recovered_probe_third_pass_002 |
| fdv1_recovered_probe_third_pass_003 | recovered_probe_third_pass | 50 | runs/final_discovery_run_v1/fdv1_recovered_probe_third_pass_003 |
| fdv1_recovered_probe_third_pass_004 | recovered_probe_third_pass | 49 | runs/final_discovery_run_v1/fdv1_recovered_probe_third_pass_004 |
| fdv1_paperbench10_001 | paperbench10 | 10 | runs/final_discovery_run_v1/fdv1_paperbench10_001 |
