from __future__ import annotations

import asyncio
from typing import Any

from libs.common.db import Camera
from libs.common.hls import resolve_source_uri

try:
    from aiortc import RTCPeerConnection, RTCSessionDescription
    from aiortc.contrib.media import MediaPlayer, MediaRelay
except ImportError:  # pragma: no cover - depends on installed runtime extras
    RTCPeerConnection = None
    RTCSessionDescription = None
    MediaPlayer = None
    MediaRelay = None


class WebRTCStreamManager:
    def __init__(self) -> None:
        self._relay = MediaRelay() if MediaRelay is not None else None
        self._players: dict[str, Any] = {}
        self._peer_connections: set[Any] = set()

    async def create_answer(self, camera: Camera, sdp: str, offer_type: str) -> dict[str, str]:
        self._ensure_runtime()
        player = self._player_for(camera)
        if player.video is None:
            raise RuntimeError(f"WebRTC video track unavailable for camera {camera.id}")
        peer_connection = RTCPeerConnection()
        self._peer_connections.add(peer_connection)

        @peer_connection.on("connectionstatechange")
        async def on_connectionstatechange() -> None:
            if peer_connection.connectionState in {"failed", "closed", "disconnected"}:
                await self._discard_peer(peer_connection)

        peer_connection.addTrack(self._relay.subscribe(player.video))
        await peer_connection.setRemoteDescription(RTCSessionDescription(sdp=sdp, type=offer_type))
        answer = await peer_connection.createAnswer()
        await peer_connection.setLocalDescription(answer)
        await self._wait_for_ice_complete(peer_connection)
        return {
            "sdp": peer_connection.localDescription.sdp,
            "type": peer_connection.localDescription.type,
        }

    async def close_all(self) -> None:
        for peer_connection in list(self._peer_connections):
            await self._discard_peer(peer_connection)
        for player in self._players.values():
            if getattr(player, "audio", None):
                player.audio.stop()
            if getattr(player, "video", None):
                player.video.stop()
        self._players.clear()

    async def close_camera(self, camera_id: str) -> None:
        player = self._players.pop(camera_id, None)
        if player is not None:
            if getattr(player, "audio", None):
                player.audio.stop()
            if getattr(player, "video", None):
                player.video.stop()

    async def _discard_peer(self, peer_connection: Any) -> None:
        if peer_connection in self._peer_connections:
            self._peer_connections.remove(peer_connection)
        await peer_connection.close()

    def _player_for(self, camera: Camera) -> Any:
        player = self._players.get(camera.id)
        if player is not None:
            return player
        source_uri = resolve_source_uri(camera.source_uri)
        if source_uri.startswith("mock://"):
            raise RuntimeError("WebRTC transport does not support mock:// sources")
        options = {"fflags": "nobuffer", "flags": "low_delay"}
        if camera.source_uri.startswith("rtsp://"):
            options["rtsp_transport"] = "tcp"
        player = MediaPlayer(
            source_uri,
            loop="://" not in source_uri,
            decode=True,
            options=options,
        )
        self._players[camera.id] = player
        return player

    @staticmethod
    def _ensure_runtime() -> None:
        if RTCPeerConnection is None or RTCSessionDescription is None or MediaPlayer is None or MediaRelay is None:
            raise RuntimeError("aiortc is not installed. Install project dependencies to enable WebRTC transport.")

    @staticmethod
    async def _wait_for_ice_complete(peer_connection: Any) -> None:
        if peer_connection.iceGatheringState == "complete":
            return
        completed = asyncio.get_running_loop().create_future()

        @peer_connection.on("icegatheringstatechange")
        def on_icegatheringstatechange() -> None:
            if peer_connection.iceGatheringState == "complete" and not completed.done():
                completed.set_result(None)

        await asyncio.wait_for(completed, timeout=5)
