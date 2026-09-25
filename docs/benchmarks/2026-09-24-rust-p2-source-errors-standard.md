# CLI benchmark: rust-p2-source-errors

- Recorded: 2026-09-24T11:12:18.897352+00:00
- Reference checkout: `0d2fc2ae1e7e0fb223556bf3a637414a9f162b5f`; Python source SHA-256: `a5f4b5feb6fd525688a6fda930087f4446eaccbe016457524369620aa5f58237`
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
| startup-version | 4.34 | 4.08–4.76 | 2.66 |
| list-jsonl | 47.10 | 46.02–47.75 | 5.38 |
| list-sqlite | 9.39 | 9.12–9.88 | 8.22 |
| list-all | 51.39 | 50.91–62.80 | 9.50 |
| head-large-jsonl | 6.76 | 6.53–7.26 | 4.30 |
| print-large-jsonl | 44.40 | 43.47–45.05 | 55.59 |
| export-large-json-md | 77.26 | 74.36–81.44 | 53.77 |

| Case | Wall speedup (baseline/current) | RSS change % |
| --- | ---: | ---: |
| startup-version | 30.91x | -93.1 |
| list-jsonl | 4.85x | -87.3 |
| list-sqlite | 14.11x | -79.7 |
| list-all | 4.67x | -78.3 |
| head-large-jsonl | 20.19x | -89.0 |
| print-large-jsonl | 5.32x | -54.9 |
| export-large-json-md | 2.99x | -64.5 |

These synthetic workloads are not the complete functional parity suite. No real LLM requests or TTY rendering are timed.
