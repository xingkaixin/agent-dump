# CLI benchmark: rust-p6-before

- Recorded: 2026-09-25T00:10:33.351418+00:00
- Reference checkout: `350efedbeee6b73f9ba172971dbfdd1a1676e5d8`; Python source SHA-256: `a5f4b5feb6fd525688a6fda930087f4446eaccbe016457524369620aa5f58237`
- Command: `'<REPO>/rust/target/release/agent-dump'`; version: `agent-dump 0.15.9`
- Host: Darwin 27.0.0 / arm64 / Apple M1 Pro
- Profile: `standard`; fixture version: 1
- Sources: 503 files, 23,839,547 bytes
- Repetitions: 5; warmups per case: 1
- Every sample passed its workload checks; source bytes remained unchanged.
- OS page cache: uncontrolled; fixture creation and warmups populate OS page cache
- RSS: fresh collector RUSAGE_CHILDREN; maximum child RSS, not simultaneous process-tree sum

| Case | Median ms | Min–max ms | Median peak RSS MiB |
| --- | ---: | ---: | ---: |
| export-batch-jsonl | 3657.62 | 3490.02–3754.57 | 47.72 |

These synthetic workloads are not the complete functional parity suite. No real LLM requests or TTY rendering are timed.
