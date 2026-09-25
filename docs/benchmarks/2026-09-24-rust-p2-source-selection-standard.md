# CLI benchmark: rust-p2-source-selection

- Recorded: 2026-09-24T12:35:12.961497+00:00
- Reference checkout: `3e599a98efc7460dbf4c6aff547a70c10a5a9853`; Python source SHA-256: `a5f4b5feb6fd525688a6fda930087f4446eaccbe016457524369620aa5f58237`
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
| startup-version | 4.61 | 4.31–5.14 | 2.73 |
| list-jsonl | 47.40 | 47.23–47.86 | 5.20 |
| list-sqlite | 9.13 | 8.68–9.52 | 7.72 |
| list-all | 50.79 | 49.96–51.31 | 9.25 |
| head-large-jsonl | 6.78 | 6.70–7.12 | 4.17 |
| print-large-jsonl | 46.79 | 46.54–47.78 | 55.50 |
| export-large-json-md | 78.13 | 77.15–86.96 | 53.69 |

| Case | Wall speedup (baseline/current) | RSS change % |
| --- | ---: | ---: |
| startup-version | 32.52x | -93.0 |
| list-jsonl | 5.22x | -87.7 |
| list-sqlite | 16.77x | -81.2 |
| list-all | 5.02x | -78.9 |
| head-large-jsonl | 21.88x | -89.4 |
| print-large-jsonl | 5.36x | -55.1 |
| export-large-json-md | 3.25x | -64.6 |

These synthetic workloads are not the complete functional parity suite. No real LLM requests or TTY rendering are timed.
