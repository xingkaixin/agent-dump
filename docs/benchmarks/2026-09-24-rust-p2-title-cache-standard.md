# CLI benchmark: rust-p2-title-cache

- Recorded: 2026-09-24T11:56:01.559246+00:00
- Reference checkout: `768e4baeb2c57a55f6961309a6a5b39990eb6aa6`; Python source SHA-256: `a5f4b5feb6fd525688a6fda930087f4446eaccbe016457524369620aa5f58237`
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
| startup-version | 4.43 | 4.21–4.65 | 2.62 |
| list-jsonl | 47.23 | 46.96–48.85 | 5.33 |
| list-sqlite | 9.44 | 9.23–10.82 | 8.03 |
| list-all | 51.02 | 50.21–51.83 | 9.48 |
| head-large-jsonl | 7.11 | 6.75–7.40 | 4.23 |
| print-large-jsonl | 45.79 | 44.96–52.51 | 53.97 |
| export-large-json-md | 81.68 | 76.93–86.86 | 54.86 |

| Case | Wall speedup (baseline/current) | RSS change % |
| --- | ---: | ---: |
| startup-version | 32.17x | -93.3 |
| list-jsonl | 5.15x | -87.4 |
| list-sqlite | 15.77x | -80.4 |
| list-all | 4.97x | -78.4 |
| head-large-jsonl | 20.36x | -89.2 |
| print-large-jsonl | 5.35x | -56.3 |
| export-large-json-md | 3.04x | -63.8 |

These synthetic workloads are not the complete functional parity suite. No real LLM requests or TTY rendering are timed.
