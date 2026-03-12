# Performance Report

This file is a starter template. Fill it after running the synthetic scale tests.

## Benchmark Table

| Cameras | Avg target FPS | Queue depth peak | Events/min | Notes |
| --- | --- | --- | --- | --- |
| 4 | 4.5 | TBD | TBD | baseline |
| 8 | TBD | TBD | TBD | |
| 16 | TBD | TBD | TBD | |
| 32 | TBD | TBD | TBD | |

## Observations

- the current mocked inference worker is CPU-light, so it mainly validates service wiring
- queue growth becomes the key signal once camera count is increased
- the next version should benchmark model inference latency separately from queueing latency
