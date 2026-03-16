# Mock RTSP

The stream gateway now supports real OpenCV ingest for RTSP, HTTP, local files, and GStreamer/FFmpeg-backed sources.

The default seeded cameras use the person and vehicle clips from `assets/human_streams/` and `assets/traffic_streams/`.

`mock://camera-name` remains as a compatibility URI for local demos and seeded test cameras while you migrate to real streams.
