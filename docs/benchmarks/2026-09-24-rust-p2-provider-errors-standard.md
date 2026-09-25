# CLI benchmark: rust-p2-provider-errors

- Recorded: 2026-09-24T10:46:07.385636+00:00
- Reference checkout: `99575b92353f8810d25e8b030e0e6ff3e433c907`; Python source SHA-256: `a5f4b5feb6fd525688a6fda930087f4446eaccbe016457524369620aa5f58237`
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
| startup-version | 4.46 | 4.27–4.82 | 2.66 |
| list-jsonl | 47.07 | 46.20–48.40 | 5.25 |
| list-sqlite | 9.17 | 8.76–9.57 | 7.94 |
| list-all | 51.37 | 50.58–57.24 | 9.45 |
| head-large-jsonl | 7.11 | 6.75–8.05 | 4.28 |
| print-large-jsonl | 46.26 | 45.03–46.55 | 55.41 |
| export-large-json-md | 78.95 | 77.48–87.18 | 53.61 |

| Case | Wall speedup (baseline/current) | RSS change % |
| --- | ---: | ---: |
| startup-version | 33.33x | -93.2 |
| list-jsonl | 5.21x | -87.6 |
| list-sqlite | 16.77x | -80.6 |
| list-all | 4.86x | -78.5 |
| head-large-jsonl | 20.06x | -89.1 |
| print-large-jsonl | 5.29x | -55.1 |
| export-large-json-md | 3.14x | -64.6 |

These synthetic workloads are not the complete functional parity suite. No real LLM requests or TTY rendering are timed.
