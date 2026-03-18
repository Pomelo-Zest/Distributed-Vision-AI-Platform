from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse

import imageio_ffmpeg

from libs.common.config import settings
from libs.common.db import Camera


def resolve_hls_root() -> Path:
    path = Path(settings.hls_dir)
    if not path.is_absolute():
        path = Path.cwd() / path
    path.mkdir(parents=True, exist_ok=True)
    return path


def resolve_source_uri(source_uri: str) -> str:
    if source_uri.startswith("file://"):
        return urlparse(source_uri).path
    if "://" not in source_uri and not source_uri.startswith("mock://"):
        return str((Path.cwd() / source_uri).resolve())
    return source_uri


class HLSStreamManager:
    def __init__(self) -> None:
        self._processes: dict[str, subprocess.Popen] = {}

    def ensure_stream(self, camera: Camera) -> Path:
        playlist_path = self.playlist_path(camera.id)
        process = self._processes.get(camera.id)
        if process is not None and process.poll() is None and playlist_path.exists():
            return playlist_path
        self.stop_stream(camera.id)
        self._reset_output(camera.id)
        command = self._ffmpeg_command(camera)
        self._processes[camera.id] = subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return playlist_path

    def wait_until_ready(self, camera: Camera, timeout_seconds: float = 6.0) -> Path:
        playlist_path = self.ensure_stream(camera)
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            process = self._processes.get(camera.id)
            if process is None:
                break
            if playlist_path.exists() and playlist_path.stat().st_size > 0:
                return playlist_path
            if process.poll() is not None:
                break
            time.sleep(0.2)
        raise RuntimeError(f"HLS playlist not ready for camera {camera.id}")

    def stop_all(self) -> None:
        for camera_id in list(self._processes):
            self.stop_stream(camera_id)

    def stop_stream(self, camera_id: str) -> None:
        process = self._processes.pop(camera_id, None)
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)

    def stream_dir(self, camera_id: str) -> Path:
        path = resolve_hls_root() / camera_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def playlist_path(self, camera_id: str) -> Path:
        return self.stream_dir(camera_id) / "index.m3u8"

    def asset_path(self, camera_id: str, asset_name: str) -> Path:
        return self.stream_dir(camera_id) / asset_name

    def _reset_output(self, camera_id: str) -> None:
        output_dir = self.stream_dir(camera_id)
        shutil.rmtree(output_dir, ignore_errors=True)
        output_dir.mkdir(parents=True, exist_ok=True)

    def _ffmpeg_command(self, camera: Camera) -> list[str]:
        source_uri = resolve_source_uri(camera.source_uri)
        output_dir = self.stream_dir(camera.id)
        segment_pattern = str(output_dir / "segment_%05d.ts")
        playlist_path = str(output_dir / "index.m3u8")
        command = [imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error"]
        if source_uri.startswith("mock://"):
            raise RuntimeError("HLS transport does not support mock:// sources")
        if "://" not in source_uri:
            command.extend(["-stream_loop", "-1", "-re"])
        command.extend(
            [
                "-i",
                source_uri,
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-pix_fmt",
                "yuv420p",
                "-g",
                "48",
                "-sc_threshold",
                "0",
                "-f",
                "hls",
                "-hls_time",
                str(settings.hls_segment_seconds),
                "-hls_list_size",
                str(settings.hls_list_size),
                "-hls_flags",
                "delete_segments+append_list+independent_segments+omit_endlist",
                "-hls_segment_filename",
                segment_pattern,
                playlist_path,
            ]
        )
        return command
