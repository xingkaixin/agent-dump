# CLI benchmark: python-native-p1

- Recorded: 2026-09-24T06:47:50.526736+00:00
- Reference checkout: `b473f37d3019ce3861d68a3eadc279e3fbfde1e0`; Python source SHA-256: `a5f4b5feb6fd525688a6fda930087f4446eaccbe016457524369620aa5f58237`
- Command: `'<REPO>/dist/agent-dump'`; version: `agent-dump 0.15.9`
- Host: Darwin 27.0.0 / arm64 / Apple M1 Pro
- Profile: `standard`; fixture version: 1
- Sources: 503 files, 23,839,547 bytes
- Repetitions: 7; warmups per case: 1
- Every sample passed its workload checks; source bytes remained unchanged.
- OS page cache: uncontrolled; fixture creation and warmups populate OS page cache
- RSS: fresh collector RUSAGE_CHILDREN; maximum child RSS, not simultaneous process-tree sum

| Case | Median ms | Min–max ms | Median peak RSS MiB |
| --- | ---: | ---: | ---: |
| startup-version | 495.38 | 468.31–502.02 | 45.53 |
| list-jsonl | 588.18 | 568.69–614.26 | 47.86 |
| head-large-jsonl | 480.61 | 468.55–492.01 | 45.58 |
| print-large-jsonl | 601.26 | 582.18–607.41 | 130.02 |

| Case | Wall speedup (baseline/current) | RSS change % |
| --- | ---: | ---: |
| startup-version | 0.27x | +17.5 |
| list-jsonl | 0.39x | +13.6 |
| head-large-jsonl | 0.28x | +16.4 |
| print-large-jsonl | 0.39x | +5.5 |

These synthetic workloads are not the complete functional parity suite. No real LLM requests or TTY rendering are timed.
