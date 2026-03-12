# Troubleshooting

## API is healthy but cameras stay idle

- confirm `scheduler` started and seeded the camera table
- inspect `GET /cameras`; new cameras should move from `idle` to `online`
- check Redis connectivity because the gateway writes frames there

## Events are missing

- check `GET /metrics/summary` for detection counts
- if detections exist but events do not, confirm camera metadata contains `zone`, `line`, and `loitering_zone`
- reduce `LOITERING_SECONDS` during local testing

## Queue depth keeps growing

- inference worker throughput is lower than ingress rate
- lower target FPS or add another inference worker instance
- in a real deployment, add stale-frame dropping before or inside inference

