# CLI benchmark: rust-p2-record-warnings

- Recorded: 2026-09-24T11:32:30.719977+00:00
- Reference checkout: `dd9582193bb905c14d75eb02249fbe8d742cd5c5`; Python source SHA-256: `a5f4b5feb6fd525688a6fda930087f4446eaccbe016457524369620aa5f58237`
- Command: `'<REPO>/rust/target/release/agent-dump'`; version: `agent-dump 0.15.9`
- Host: Darwin 27.0.0 / arm64 / Apple M1 Pro
- Profile: `standard`; fixture version: 1
- Sources: 503 files, 23,839,547 bytes
- Repetitions: 7; warmups per case: 1
- Every sample passed its workload checks; source bytes remained unchanged.
- OS page cache: uncontrolled; fixture creation and warmups populate OS page cache
- RSS: fresh collector RUSAGE_CHILDREN; maximum child RSS, not simultaneous process-tree sum

| Case | Median ms | Min–max ms | Median peak RSS MiB |
| --- | ---: | ---: | ---: |
| startup-version | 4.59 | 4.41–4.69 | 2.70 |
| list-jsonl | 47.48 | 46.94–48.80 | 5.33 |
| list-sqlite | 9.22 | 9.09–10.89 | 8.08 |
| list-all | 53.69 | 52.99–64.94 | 9.56 |
| head-large-jsonl | 7.35 | 7.16–7.93 | 4.31 |
| print-large-jsonl | 47.09 | 45.92–47.69 | 53.50 |
| export-large-json-md | 79.03 | 75.96–80.22 | 53.53 |

| Case | Wall speedup (baseline/current) | RSS change % |
| --- | ---: | ---: |
| startup-version | 31.35x | -93.0 |
| list-jsonl | 5.20x | -87.4 |
| list-sqlite | 16.20x | -80.3 |
| list-all | 4.60x | -77.9 |
| head-large-jsonl | 22.38x | -89.0 |
| print-large-jsonl | 5.47x | -56.6 |
| export-large-json-md | 3.50x | -64.7 |

These synthetic workloads are not the complete functional parity suite. No real LLM requests or TTY rendering are timed.
