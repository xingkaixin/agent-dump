# CLI benchmark: rust-p2-final

- Recorded: 2026-09-24T14:53:05.304067+00:00
- Reference checkout: `d074c63213dc6849f19e661121ad9b3f3f7cbf6d`; Python source SHA-256: `a5f4b5feb6fd525688a6fda930087f4446eaccbe016457524369620aa5f58237`
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
| startup-version | 5.07 | 4.58–5.43 | 2.66 |
| list-jsonl | 52.43 | 51.30–53.41 | 5.61 |
| list-sqlite | 10.00 | 9.88–13.24 | 8.14 |
| list-all | 56.90 | 56.14–58.55 | 9.83 |
| head-large-jsonl | 7.61 | 7.08–8.16 | 4.33 |
| print-large-jsonl | 52.12 | 51.59–67.40 | 55.45 |
| export-large-json-md | 85.93 | 84.35–97.88 | 55.59 |

| Case | Wall speedup (baseline/current) | RSS change % |
| --- | ---: | ---: |
| startup-version | 30.55x | -93.2 |
| list-jsonl | 4.83x | -86.8 |
| list-sqlite | 15.87x | -80.1 |
| list-all | 4.73x | -77.7 |
| head-large-jsonl | 20.33x | -89.0 |
| print-large-jsonl | 4.99x | -55.1 |
| export-large-json-md | 3.11x | -63.3 |

These synthetic workloads are not the complete functional parity suite. No real LLM requests or TTY rendering are timed.
