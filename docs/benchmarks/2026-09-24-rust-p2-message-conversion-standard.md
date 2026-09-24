# CLI benchmark: rust-p2-message-conversion

- Recorded: 2026-09-24T12:14:06.390347+00:00
- Reference checkout: `fa39040f15a4fa8ca064e161e15305cb9fd9df17`; Python source SHA-256: `a5f4b5feb6fd525688a6fda930087f4446eaccbe016457524369620aa5f58237`
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
| startup-version | 4.99 | 4.36–10.60 | 2.70 |
| list-jsonl | 48.58 | 47.30–49.09 | 5.23 |
| list-sqlite | 9.55 | 8.98–9.70 | 7.97 |
| list-all | 51.71 | 51.15–57.74 | 9.45 |
| head-large-jsonl | 7.09 | 6.87–7.26 | 4.22 |
| print-large-jsonl | 45.62 | 44.92–48.82 | 54.75 |
| export-large-json-md | 82.58 | 77.08–103.60 | 55.53 |

| Case | Wall speedup (baseline/current) | RSS change % |
| --- | ---: | ---: |
| startup-version | 38.93x | -93.1 |
| list-jsonl | 7.76x | -87.6 |
| list-sqlite | 21.32x | -80.5 |
| list-all | 4.96x | -78.6 |
| head-large-jsonl | 20.49x | -89.2 |
| print-large-jsonl | 5.39x | -55.6 |
| export-large-json-md | 3.06x | -63.4 |

These synthetic workloads are not the complete functional parity suite. No real LLM requests or TTY rendering are timed.
