# Rust workflow extension eval

Profile: `standard`; 5 measured pairs, 1 warmup pairs.

The original P0 evaluator is unchanged. HTTP timings include a deterministic loopback service, not a real model.

| Case | Python median (ms) | Rust median (ms) | Speedup |
| --- | ---: | ---: | ---: |
| search-incremental-jsonl | 459.77 | 141.09 | 3.26× |
| search-deleted-jsonl | 518.90 | 298.92 | 1.74× |
| search-wal-sqlite | 1524.07 | 481.97 | 3.16× |
| search-four-providers | 742.61 | 381.31 | 1.95× |
| collect-http-local | 284.60 | 68.72 | 4.14× |
| collect-http-20ms | 514.95 | 289.20 | 1.78× |
