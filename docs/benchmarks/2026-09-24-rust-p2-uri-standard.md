# CLI benchmark: rust-p2-uri

- Recorded: 2026-09-24T10:26:03.225169+00:00
- Reference checkout: `f3af42a497ebdce43eb72b96c3198d4df390f532`; Python source SHA-256: `a5f4b5feb6fd525688a6fda930087f4446eaccbe016457524369620aa5f58237`
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
| startup-version | 4.74 | 4.39–5.17 | 2.64 |
| list-jsonl | 47.36 | 47.01–47.84 | 5.17 |
| list-sqlite | 9.33 | 9.05–9.66 | 8.09 |
| list-all | 50.94 | 50.63–51.13 | 9.58 |
| head-large-jsonl | 7.01 | 6.95–7.11 | 4.25 |
| print-large-jsonl | 46.15 | 45.44–46.64 | 55.52 |
| export-large-json-md | 78.26 | 77.18–89.08 | 55.62 |

| Case | Wall speedup (baseline/current) | RSS change % |
| --- | ---: | ---: |
| startup-version | 30.76x | -93.2 |
| list-jsonl | 5.27x | -87.8 |
| list-sqlite | 16.42x | -80.2 |
| list-all | 5.05x | -78.3 |
| head-large-jsonl | 21.18x | -89.2 |
| print-large-jsonl | 5.40x | -55.1 |
| export-large-json-md | 3.24x | -63.3 |

These synthetic workloads are not the complete functional parity suite. No real LLM requests or TTY rendering are timed.
