# CLI benchmark: rust-p2-jsonl

- Recorded: 2026-09-24T08:07:16.839113+00:00
- Reference checkout: `366954255f7cdb38841f3dbd2950121a418e69e3`; Python source SHA-256: `a5f4b5feb6fd525688a6fda930087f4446eaccbe016457524369620aa5f58237`
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
| startup-version | 3.97 | 3.88–5.00 | 2.59 |
| list-jsonl | 46.57 | 46.31–49.19 | 4.95 |
| head-large-jsonl | 6.43 | 6.31–10.30 | 4.05 |
| print-large-jsonl | 43.63 | 42.73–44.68 | 53.31 |
| export-large-json-md | 74.89 | 73.51–76.22 | 53.38 |

| Case | Wall speedup (baseline/current) | RSS change % |
| --- | ---: | ---: |
| startup-version | 34.87x | -93.3 |
| list-jsonl | 5.13x | -88.3 |
| head-large-jsonl | 22.15x | -89.7 |
| print-large-jsonl | 5.47x | -56.8 |
| export-large-json-md | 3.22x | -64.8 |

These synthetic workloads are not the complete functional parity suite. No real LLM requests or TTY rendering are timed.
