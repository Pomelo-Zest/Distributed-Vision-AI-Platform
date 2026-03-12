# Mock RTSP

This MVP uses `mock://camera-name` URIs instead of real RTSP. The stream gateway treats them as synthetic live streams and emits frame metadata at the configured FPS.

Replace the synthetic source handler in `services/stream_gateway/app/main.py` when you are ready to ingest real video frames.

