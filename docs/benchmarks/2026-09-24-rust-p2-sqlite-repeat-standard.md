# CLI benchmark: rust-p2-sqlite-repeat

- Recorded: 2026-09-24T09:08:29.808535+00:00
- Reference checkout: `aec8b471ca9e4dc0a686ae0b0616145361621757`; Python source SHA-256: `a5f4b5feb6fd525688a6fda930087f4446eaccbe016457524369620aa5f58237`
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
| startup-version | 4.67 | 4.50–5.32 | 2.62 |
| list-jsonl | 46.19 | 45.96–47.69 | 5.06 |
| list-sqlite | 9.15 | 8.49–9.64 | 7.80 |
| head-large-jsonl | 7.01 | 6.46–7.05 | 4.08 |
| print-large-jsonl | 44.44 | 43.45–46.73 | 53.36 |
| export-large-json-md | 74.60 | 73.93–75.88 | 53.44 |

| Case | Wall speedup (baseline/current) | RSS change % |
| --- | ---: | ---: |
| startup-version | 34.57x | -93.3 |
| list-jsonl | 5.25x | -88.0 |
| list-sqlite | 16.28x | -80.9 |
| head-large-jsonl | 21.16x | -89.6 |
| print-large-jsonl | 5.51x | -56.8 |
| export-large-json-md | 3.34x | -64.8 |

These synthetic workloads are not the complete functional parity suite. No real LLM requests or TTY rendering are timed.
