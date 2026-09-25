# CLI benchmark: rust-p2-sqlite

- Recorded: 2026-09-24T09:07:30.924166+00:00
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
| startup-version | 4.73 | 4.37–5.22 | 2.62 |
| list-jsonl | 47.82 | 46.94–49.27 | 5.05 |
| list-sqlite | 9.61 | 9.16–9.94 | 7.91 |
| head-large-jsonl | 8.06 | 7.46–12.01 | 4.06 |
| print-large-jsonl | 45.73 | 45.10–46.57 | 53.39 |
| export-large-json-md | 79.54 | 76.84–161.55 | 55.39 |

| Case | Wall speedup (baseline/current) | RSS change % |
| --- | ---: | ---: |
| startup-version | 46.19x | -93.2 |
| list-jsonl | 8.10x | -88.0 |
| list-sqlite | 25.94x | -80.7 |
| head-large-jsonl | 29.89x | -89.7 |
| print-large-jsonl | 10.38x | -56.9 |
| export-large-json-md | 3.40x | -63.5 |

These synthetic workloads are not the complete functional parity suite. No real LLM requests or TTY rendering are timed.
