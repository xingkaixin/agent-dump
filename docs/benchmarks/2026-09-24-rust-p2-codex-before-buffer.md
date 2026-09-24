# CLI benchmark: rust-p2-codex

- Recorded: 2026-09-24T07:20:37.818590+00:00
- Reference checkout: `ca4b1db3f9b3b9efc9d2d00e05ef7833644634c8`; Python source SHA-256: `a5f4b5feb6fd525688a6fda930087f4446eaccbe016457524369620aa5f58237`
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
| startup-version | 4.25 | 3.94–4.42 | 2.52 |
| list-jsonl | 47.67 | 47.32–48.79 | 4.58 |
| head-large-jsonl | 6.54 | 6.39–7.31 | 3.83 |
| print-large-jsonl | 43.78 | 43.39–44.10 | 54.98 |
| export-large-json-md | 771.32 | 746.69–847.31 | 53.12 |

| Case | Wall speedup (baseline/current) | RSS change % |
| --- | ---: | ---: |
| startup-version | 63.50x | -93.5 |
| list-jsonl | 7.71x | -89.1 |
| head-large-jsonl | 32.34x | -90.3 |
| print-large-jsonl | 7.68x | -55.5 |
| export-large-json-md | 0.47x | -65.0 |

These synthetic workloads are not the complete functional parity suite. No real LLM requests or TTY rendering are timed.
