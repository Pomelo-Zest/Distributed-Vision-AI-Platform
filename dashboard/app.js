const players = new Map();
const cameraDrafts = new Map();
const dirtyDrafts = new Set();
const redrawQueue = new Set();
const streamRetryTimers = new Map();
let cameraSignature = "";
let previewMode = "hls";
let selectedCameraId = "";
let activeTool = "zone";
let drawingPoints = [];
let camerasCache = [];
let redrawScheduled = false;
let overlayEditMode = false;
const polygonCloseThreshold = 0.04;

const cameraForm = document.getElementById("camera-form");
const cameraFormMessage = document.getElementById("camera-form-message");
const cameraNameInput = document.getElementById("camera-name");
const cameraIdInput = document.getElementById("camera-id");
const cameraSourceUriInput = document.getElementById("camera-source-uri");
const cameraTargetFpsInput = document.getElementById("camera-target-fps");
const geometryMessage = document.getElementById("geometry-message");
const geometryJson = document.getElementById("geometry-json");
const selectedCameraName = document.getElementById("selected-camera-name");
const selectedCameraIdLabel = document.getElementById("selected-camera-id");
const geometryHint = document.getElementById("geometry-hint");
const summaryMessage = document.getElementById("summary-message");
const detectionCameraName = document.getElementById("detection-camera-name");
const detectionTuningHint = document.getElementById("detection-tuning-hint");
const detectionMessage = document.getElementById("detection-message");
const detectPersonInput = document.getElementById("detect-person");
const detectVehicleInput = document.getElementById("detect-vehicle");
const detectionConfidenceInput = document.getElementById("detection-confidence");
const detectionConfidenceValue = document.getElementById("detection-confidence-value");
const detectionMinAreaInput = document.getElementById("detection-min-area");
const detectionMinAreaValue = document.getElementById("detection-min-area-value");

function updateTransportButtons() {
  document.getElementById("webrtc-mode").classList.toggle("active", previewMode === "webrtc");
  document.getElementById("hls-mode").classList.toggle("active", previewMode === "hls");
}

function updateToolButtons() {
  document.querySelectorAll(".tool-button").forEach((button) => {
    button.classList.toggle("active", button.dataset.tool === activeTool);
  });
}

function slugifyCameraId(value) {
  return value
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

function emptyGeometry() {
  return { zone: [], loitering_zone: [], line: [] };
}

function cloneGeometry(geometry = {}) {
  return {
    zone: (geometry.zone || []).map((point) => [...point]),
    loitering_zone: (geometry.loitering_zone || []).map((point) => [...point]),
    line: (geometry.line || []).map((point) => [...point]),
  };
}

function getSelectedCamera() {
  return camerasCache.find((camera) => camera.id === selectedCameraId) || null;
}

function getDraft(cameraId) {
  if (!cameraDrafts.has(cameraId)) {
    cameraDrafts.set(cameraId, emptyGeometry());
  }
  return cameraDrafts.get(cameraId);
}

function setFormMessage(message, state = "") {
  cameraFormMessage.textContent = message;
  cameraFormMessage.className = `camera-form-message ${state}`.trim();
}

function setGeometryMessage(message, state = "") {
  geometryMessage.textContent = message;
  geometryMessage.className = `camera-form-message ${state}`.trim();
}

function setSummaryMessage(message, state = "") {
  summaryMessage.textContent = message;
  summaryMessage.className = `camera-form-message ${state}`.trim();
}

function setDetectionMessage(message, state = "") {
  detectionMessage.textContent = message;
  detectionMessage.className = `camera-form-message ${state}`.trim();
}

function syncDrafts(cameras) {
  const cameraIds = new Set(cameras.map((camera) => camera.id));
  for (const camera of cameras) {
    if (!dirtyDrafts.has(camera.id)) {
      cameraDrafts.set(camera.id, cloneGeometry(camera.metadata || {}));
    }
  }
  for (const cameraId of Array.from(cameraDrafts.keys())) {
    if (!cameraIds.has(cameraId)) {
      cameraDrafts.delete(cameraId);
      dirtyDrafts.delete(cameraId);
    }
  }
  if (!selectedCameraId && cameras.length > 0) {
    selectedCameraId = cameras[0].id;
  }
  if (selectedCameraId && !cameraIds.has(selectedCameraId)) {
    selectedCameraId = cameras[0]?.id || "";
    drawingPoints = [];
  }
}

function updateSelectionPanel() {
  const camera = getSelectedCamera();
  if (!camera) {
    selectedCameraName.textContent = "Pick a camera";
    selectedCameraIdLabel.textContent = "No camera selected";
    geometryJson.textContent = JSON.stringify(emptyGeometry(), null, 2);
    geometryHint.textContent = "Select a camera, enable overlay editing, and draw directly on top of the live player.";
    detectionCameraName.textContent = "Pick a camera";
    detectionTuningHint.textContent = "Choose object types and tighten thresholds to reduce false positives.";
    return;
  }
  selectedCameraName.textContent = camera.name;
  selectedCameraIdLabel.textContent = `${camera.id} • ${overlayEditMode ? "Overlay edit mode" : camera.source_uri}`;
  geometryJson.textContent = JSON.stringify(getDraft(camera.id), null, 2);
  syncDetectionControls(camera);
  updateGeometryHint();
}

function syncDetectionControls(camera) {
  const detectionSettings = camera.metadata?.detection_settings || {};
  const categories = detectionSettings.categories || ["person", "vehicle"];
  detectPersonInput.checked = categories.includes("person");
  detectVehicleInput.checked = categories.includes("vehicle");
  detectionConfidenceInput.value = Number(detectionSettings.min_confidence ?? 0.4).toFixed(2);
  detectionConfidenceValue.textContent = Number(detectionSettings.min_confidence ?? 0.4).toFixed(2);
  detectionMinAreaInput.value = Number(detectionSettings.min_box_area ?? 0.0025).toFixed(4);
  detectionMinAreaValue.textContent = Number(detectionSettings.min_box_area ?? 0.0025).toFixed(4);
  detectionCameraName.textContent = camera.name;
  detectionTuningHint.textContent = `${camera.id} • start with vehicles-only or a higher confidence threshold if this stream is noisy.`;
}

function updateGeometryHint() {
  if (!selectedCameraId) {
    geometryHint.textContent = "Select a camera, enable overlay editing, and draw directly on top of the live player.";
    return;
  }
  if (!overlayEditMode) {
    geometryHint.textContent = "Click Edit overlay on a camera card to start drawing. Outside edit mode, the player stays fully interactive.";
    return;
  }
  if (activeTool === "line") {
    geometryHint.textContent = drawingPoints.length
      ? "Place one more point to finish the line crossing."
      : "Click two points on the player to define the line crossing.";
    return;
  }
  geometryHint.textContent =
    drawingPoints.length >= 3
      ? "Click near the first point to close the polygon, or use Finish shape. Undo point removes the last point."
      : "Click to place polygon points. Add at least three points, then click near the first point to close it.";
}

function clearStreamRetry(cameraId) {
  const timer = streamRetryTimers.get(cameraId);
  if (timer) {
    window.clearTimeout(timer);
    streamRetryTimers.delete(cameraId);
  }
}

function disposePlayer(cameraId) {
  clearStreamRetry(cameraId);
  const player = players.get(cameraId);
  if (player) {
    if (player.kind === "hls" && player.instance && typeof player.instance.destroy === "function") {
      player.instance.destroy();
    }
    if (player.kind === "webrtc" && player.instance) {
      player.instance.close();
    }
    if (player.cleanup && typeof player.cleanup === "function") {
      player.cleanup();
    }
    players.delete(cameraId);
  }
  const video = document.getElementById(`camera-preview-${cameraId}`);
  if (video) {
    video.pause?.();
    video.srcObject = null;
    video.removeAttribute("src");
    video.load();
  }
}

function teardownPlayers() {
  for (const cameraId of players.keys()) {
    disposePlayer(cameraId);
  }
  for (const cameraId of streamRetryTimers.keys()) {
    clearStreamRetry(cameraId);
  }
}

function waitForIceGatheringComplete(peerConnection) {
  if (peerConnection.iceGatheringState === "complete") {
    return Promise.resolve();
  }
  return new Promise((resolve) => {
    function checkState() {
      if (peerConnection.iceGatheringState === "complete") {
        peerConnection.removeEventListener("icegatheringstatechange", checkState);
        resolve();
      }
    }
    peerConnection.addEventListener("icegatheringstatechange", checkState);
  });
}

async function attachWebRTC(video, camera) {
  const peerConnection = new RTCPeerConnection();
  const trackReady = new Promise((resolve, reject) => {
    const timer = window.setTimeout(() => {
      reject(new Error("WebRTC media timeout"));
    }, 5000);

    peerConnection.addEventListener("track", (event) => {
      window.clearTimeout(timer);
      video.srcObject = event.streams[0];
      resolve();
    });

    peerConnection.addEventListener("connectionstatechange", () => {
      if (["failed", "disconnected", "closed"].includes(peerConnection.connectionState)) {
        window.clearTimeout(timer);
        reject(new Error(`WebRTC connection ${peerConnection.connectionState}`));
      }
    });
  });

  peerConnection.addTransceiver("video", { direction: "recvonly" });
  const offer = await peerConnection.createOffer();
  await peerConnection.setLocalDescription(offer);
  await waitForIceGatheringComplete(peerConnection);
  const response = await fetch(camera.webrtc_url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      sdp: peerConnection.localDescription.sdp,
      type: peerConnection.localDescription.type,
    }),
  });
  if (!response.ok) {
    peerConnection.close();
    throw new Error(`WebRTC offer failed: ${response.status}`);
  }
  const answer = await response.json();
  await peerConnection.setRemoteDescription(answer);
  await trackReady;
  players.set(camera.id, { kind: "webrtc", instance: peerConnection });
}

function attachHls(video, camera) {
  const streamUrl = camera.stream_url;
  if (!streamUrl) {
    throw new Error("No HLS stream URL");
  }
  const cleanup = [];
  const registerCleanup = (fn) => cleanup.push(fn);
  if (window.Hls && window.Hls.isSupported()) {
    const hls = new window.Hls({
      enableWorker: true,
      liveDurationInfinity: true,
      lowLatencyMode: true,
      backBufferLength: 15,
      maxBufferLength: 10,
      liveSyncDurationCount: 3,
      manifestLoadingTimeOut: 10000,
      levelLoadingTimeOut: 10000,
      fragLoadingTimeOut: 15000,
    });
    let recoverAttempts = 0;
    hls.on(window.Hls.Events.MANIFEST_PARSED, () => {
      setStreamState(camera.id, "");
      video.play().catch(() => {});
    });
    hls.on(window.Hls.Events.ERROR, (_, data) => {
      if (!data.fatal) {
        return;
      }
      if (data.type === window.Hls.ErrorTypes.NETWORK_ERROR && recoverAttempts < 3) {
        recoverAttempts += 1;
        setStreamState(camera.id, `Reconnecting HLS (${recoverAttempts}/3)`);
        hls.startLoad();
        return;
      }
      if (data.type === window.Hls.ErrorTypes.MEDIA_ERROR && recoverAttempts < 3) {
        recoverAttempts += 1;
        setStreamState(camera.id, `Recovering media (${recoverAttempts}/3)`);
        hls.recoverMediaError();
        return;
      }
      setStreamState(camera.id, "HLS stream unavailable");
      hls.destroy();
      scheduleStreamRetry(camera);
    });
    const onPlaying = () => setStreamState(camera.id, "");
    const onWaiting = () => setStreamState(camera.id, "Buffering live stream");
    video.addEventListener("playing", onPlaying);
    video.addEventListener("waiting", onWaiting);
    registerCleanup(() => {
      video.removeEventListener("playing", onPlaying);
      video.removeEventListener("waiting", onWaiting);
    });
    hls.loadSource(streamUrl);
    hls.attachMedia(video);
    players.set(camera.id, { kind: "hls", instance: hls, cleanup: () => cleanup.forEach((fn) => fn()) });
    return;
  }
  if (video.canPlayType("application/vnd.apple.mpegurl")) {
    video.src = streamUrl;
    video.load();
    const onError = () => {
      setStreamState(camera.id, "Native HLS playback error");
      scheduleStreamRetry(camera);
    };
    const onWaiting = () => setStreamState(camera.id, "Buffering live stream");
    const onPlaying = () => setStreamState(camera.id, "");
    const onLoadedMetadata = () => video.play().catch(() => {});
    video.addEventListener("error", onError);
    video.addEventListener("waiting", onWaiting);
    video.addEventListener("playing", onPlaying);
    video.addEventListener("loadedmetadata", onLoadedMetadata);
    registerCleanup(() => {
      video.removeEventListener("error", onError);
      video.removeEventListener("waiting", onWaiting);
      video.removeEventListener("playing", onPlaying);
      video.removeEventListener("loadedmetadata", onLoadedMetadata);
    });
    players.set(camera.id, { kind: "native-hls", instance: null, cleanup: () => cleanup.forEach((fn) => fn()) });
    return;
  }
  throw new Error("HLS unsupported in this browser");
}

function setStreamState(cameraId, message = "") {
  const label = document.getElementById(`stream-state-${cameraId}`);
  if (!label) {
    return;
  }
  label.textContent = message;
  label.classList.toggle("visible", Boolean(message));
}

function scheduleStreamRetry(camera) {
  clearStreamRetry(camera.id);
  const timer = window.setTimeout(() => {
    streamRetryTimers.delete(camera.id);
    disposePlayer(camera.id);
    const video = document.getElementById(`camera-preview-${camera.id}`);
    if (video) {
      attachStream(video, camera).catch((error) => {
        console.error(error);
        setStreamState(camera.id, "HLS retry failed");
      });
    }
  }, 2500);
  streamRetryTimers.set(camera.id, timer);
}

async function attachStream(video, camera) {
  try {
    clearStreamRetry(camera.id);
    setStreamState(camera.id, "");
    if (previewMode === "webrtc" && camera.webrtc_url) {
      await attachWebRTC(video, camera);
      return;
    }
    attachHls(video, camera);
  } catch (error) {
    console.error(error);
    if (previewMode === "webrtc") {
      try {
        attachHls(video, camera);
        setStreamState(camera.id, "WebRTC unavailable, using HLS");
        return;
      } catch (fallbackError) {
        console.error(fallbackError);
      }
    }
    setStreamState(camera.id, `${previewMode.toUpperCase()} unavailable`);
    if (previewMode === "hls") {
      scheduleStreamRetry(camera);
    }
  }
}

function renderSummary(summary) {
  document.getElementById("active-cameras").textContent = summary.active_cameras;
  document.getElementById("total-detections").textContent = summary.total_detections;
  document.getElementById("total-detections-label").textContent = "Tracks in latest frames";
  document.getElementById("total-events").textContent = summary.total_events;
}

function latestActivation(cameras, events) {
  if (events.length > 0) {
    const event = events[0];
    return `${event.rule_type} / ${event.camera_id}`;
  }
  const cameraWithEvent = cameras.find((camera) => camera.runtime && camera.runtime.last_event);
  if (!cameraWithEvent) {
    return "Waiting";
  }
  return `${cameraWithEvent.runtime.last_event.rule_type} / ${cameraWithEvent.id}`;
}

function normalizePoint(canvas, event) {
  const bounds = canvas.getBoundingClientRect();
  const x = Math.max(0, Math.min(1, (event.clientX - bounds.left) / bounds.width));
  const y = Math.max(0, Math.min(1, (event.clientY - bounds.top) / bounds.height));
  return [Number(x.toFixed(4)), Number(y.toFixed(4))];
}

function selectCamera(cameraId, enableEditing = false) {
  selectedCameraId = cameraId;
  overlayEditMode = enableEditing;
  drawingPoints = [];
  document.querySelectorAll(".camera-card").forEach((card) => {
    card.classList.toggle("selected", card.dataset.cameraId === cameraId);
    card.classList.toggle("editing", card.dataset.cameraId === cameraId && overlayEditMode);
  });
  document.querySelectorAll(".camera-focus").forEach((button) => {
    button.textContent =
      button.dataset.cameraId === cameraId && overlayEditMode ? "Stop editing" : "Edit overlay";
  });
  updateSelectionPanel();
  redrawAllCanvases();
}

function isNearPoint(firstPoint, nextPoint, threshold = polygonCloseThreshold) {
  if (!firstPoint || !nextPoint) {
    return false;
  }
  const dx = firstPoint[0] - nextPoint[0];
  const dy = firstPoint[1] - nextPoint[1];
  return Math.hypot(dx, dy) <= threshold;
}

function undoLastPoint() {
  if (!drawingPoints.length) {
    setGeometryMessage("There is no in-progress point to remove.", "error");
    return;
  }
  drawingPoints.pop();
  updateGeometryHint();
  setGeometryMessage("Removed the last point.", "success");
  redrawAllCanvases();
}

function finishShape() {
  if (!selectedCameraId || activeTool === "line") {
    return;
  }
  if (drawingPoints.length < 3) {
    setGeometryMessage("Add at least three points before finishing a polygon.", "error");
    return;
  }
  const draft = getDraft(selectedCameraId);
  draft[activeTool] = drawingPoints.map((point) => [...point]);
  dirtyDrafts.add(selectedCameraId);
  drawingPoints = [];
  updateSelectionPanel();
  setGeometryMessage("Polygon updated. Save to apply it to the event engine.", "success");
  redrawAllCanvases();
}

function clearActiveShape() {
  if (!selectedCameraId) {
    return;
  }
  const draft = getDraft(selectedCameraId);
  draft[activeTool] = [];
  drawingPoints = [];
  dirtyDrafts.add(selectedCameraId);
  updateSelectionPanel();
  setGeometryMessage("Active geometry cleared.", "success");
  redrawAllCanvases();
}

function scheduleCanvasRedraw(cameraId) {
  if (cameraId) {
    redrawQueue.add(cameraId);
  } else {
    camerasCache.forEach((camera) => redrawQueue.add(camera.id));
  }
  if (redrawScheduled) {
    return;
  }
  redrawScheduled = true;
  window.requestAnimationFrame(() => {
    redrawScheduled = false;
    const pending = Array.from(redrawQueue);
    redrawQueue.clear();
    pending.forEach((id) => redrawCanvas(id));
  });
}

async function saveGeometry() {
  const camera = getSelectedCamera();
  if (!camera) {
    setGeometryMessage("Select a camera before saving geometry.", "error");
    return;
  }
  if (activeTool !== "line" && drawingPoints.length >= 3) {
    finishShape();
  }
  const payload = getDraft(camera.id);
  setGeometryMessage("Saving geometry...", "pending");
  const response = await fetch(`/cameras/${camera.id}/geometry`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Unable to save geometry" }));
    setGeometryMessage(error.detail || "Unable to save geometry", "error");
    return;
  }
  const updated = await response.json();
  cameraDrafts.set(camera.id, cloneGeometry(updated.metadata || updated.geometry));
  dirtyDrafts.delete(camera.id);
  overlayEditMode = false;
  setGeometryMessage("Geometry saved. Event rules will pick up the new coordinates on the next frames.", "success");
  await loadDashboard(true);
}

function drawPolygon(ctx, canvas, points, fillStyle, strokeStyle, dashed = false) {
  if (!points.length) {
    return;
  }
  ctx.save();
  ctx.beginPath();
  points.forEach(([x, y], index) => {
    const px = x * canvas.width;
    const py = y * canvas.height;
    if (index === 0) {
      ctx.moveTo(px, py);
    } else {
      ctx.lineTo(px, py);
    }
  });
  ctx.closePath();
  ctx.fillStyle = fillStyle;
  ctx.strokeStyle = strokeStyle;
  ctx.lineWidth = 3;
  ctx.setLineDash(dashed ? [10, 8] : []);
  ctx.fill();
  ctx.stroke();
  ctx.restore();
}

function drawLine(ctx, canvas, points, strokeStyle) {
  if (points.length !== 2) {
    return;
  }
  ctx.save();
  ctx.beginPath();
  ctx.moveTo(points[0][0] * canvas.width, points[0][1] * canvas.height);
  ctx.lineTo(points[1][0] * canvas.width, points[1][1] * canvas.height);
  ctx.strokeStyle = strokeStyle;
  ctx.lineWidth = 4;
  ctx.stroke();
  ctx.restore();
}

function drawHandles(ctx, canvas, points, fillStyle) {
  ctx.save();
  ctx.fillStyle = fillStyle;
  points.forEach(([x, y]) => {
    ctx.beginPath();
    ctx.arc(x * canvas.width, y * canvas.height, 5, 0, Math.PI * 2);
    ctx.fill();
  });
  ctx.restore();
}

function redrawCanvas(cameraId) {
  const canvas = document.getElementById(`camera-overlay-${cameraId}`);
  if (!canvas) {
    return;
  }
  const stage = canvas.parentElement;
  const width = Math.max(stage.clientWidth, 16);
  const height = Math.max(stage.clientHeight, 16);
  if (canvas.width !== width || canvas.height !== height) {
    canvas.width = width;
    canvas.height = height;
  }
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, width, height);

  const draft = getDraft(cameraId);
  drawPolygon(ctx, canvas, draft.zone || [], "rgba(57, 224, 155, 0.16)", "#39e09b");
  drawPolygon(ctx, canvas, draft.loitering_zone || [], "rgba(255, 196, 61, 0.18)", "#ffc43d", true);
  drawLine(ctx, canvas, draft.line || [], "#f472b6");

  if (cameraId === selectedCameraId && drawingPoints.length) {
    if (activeTool === "line") {
      drawLine(ctx, canvas, drawingPoints, "#ffffff");
    } else {
      ctx.save();
      ctx.beginPath();
      drawingPoints.forEach(([x, y], index) => {
        const px = x * width;
        const py = y * height;
        if (index === 0) {
          ctx.moveTo(px, py);
        } else {
          ctx.lineTo(px, py);
        }
      });
      ctx.strokeStyle = "#ffffff";
      ctx.lineWidth = 2;
      ctx.setLineDash([8, 6]);
      ctx.stroke();
      ctx.restore();
    }
    drawHandles(ctx, canvas, drawingPoints, "#ffffff");
    if (activeTool !== "line" && drawingPoints.length) {
      drawHandles(ctx, canvas, [drawingPoints[0]], "#39e09b");
    }
  }
}

function redrawAllCanvases() {
  scheduleCanvasRedraw();
}

function bindCanvas(camera) {
  const canvas = document.getElementById(`camera-overlay-${camera.id}`);
  if (!canvas) {
    return;
  }
  canvas.addEventListener("click", (event) => {
    event.stopPropagation();
    if (selectedCameraId !== camera.id) {
      selectCamera(camera.id, true);
      return;
    }
    if (!overlayEditMode) {
      return;
    }
    const point = normalizePoint(canvas, event);
    if (activeTool === "line") {
      drawingPoints.push(point);
      if (drawingPoints.length === 2) {
        const draft = getDraft(camera.id);
        draft.line = drawingPoints.map((value) => [...value]);
        drawingPoints = [];
        dirtyDrafts.add(camera.id);
        updateSelectionPanel();
        setGeometryMessage("Line updated. Save to apply it to line-crossing events.", "success");
      }
    } else {
      if (drawingPoints.length >= 3 && isNearPoint(drawingPoints[0], point)) {
        finishShape();
        return;
      }
      drawingPoints.push(point);
      updateGeometryHint();
      setGeometryMessage("Point added.", "pending");
    }
    scheduleCanvasRedraw(camera.id);
  });
  canvas.addEventListener("dblclick", (event) => {
    event.preventDefault();
    event.stopPropagation();
    if (selectedCameraId === camera.id && overlayEditMode && activeTool !== "line") {
      finishShape();
    }
  });
  canvas.addEventListener("contextmenu", (event) => {
    event.stopPropagation();
    if (selectedCameraId !== camera.id || !overlayEditMode) {
      return;
    }
    event.preventDefault();
    undoLastPoint();
  });
}

function renderCameras(cameras, force = false, freezeDuringEdit = false) {
  const nextSignature = cameras
    .map((camera) => `${camera.id}:${camera.stream_url}:${camera.webrtc_url}:${camera.status}:${previewMode}`)
    .join("|");
  if (freezeDuringEdit || (!force && nextSignature === cameraSignature)) {
    if (!freezeDuringEdit) {
      cameraSignature = nextSignature;
    }
    updateSelectionPanel();
    redrawAllCanvases();
    return;
  }
  cameraSignature = nextSignature;
  teardownPlayers();
  updateTransportButtons();
  updateToolButtons();

  const cameraList = document.getElementById("camera-list");
  cameraList.innerHTML = cameras
    .map(
      (camera) => `
        <article class="camera-card ${camera.id === selectedCameraId ? "selected" : ""} ${camera.id === selectedCameraId && overlayEditMode ? "editing" : ""}" data-camera-id="${camera.id}">
          <div class="player-stage">
            <video
              class="camera-preview"
              id="camera-preview-${camera.id}"
              muted
              autoplay
              playsinline
              controls
            ></video>
            <canvas class="camera-overlay" id="camera-overlay-${camera.id}"></canvas>
            <div class="stream-badge" id="stream-state-${camera.id}"></div>
          </div>
          <div class="camera-card-body">
            <div class="camera-row">
              <div>
                <h3>${camera.name}</h3>
                <p>${camera.id}</p>
              </div>
              <div>
                <span class="status ${camera.status}">${camera.status}</span>
                <p>${camera.target_fps} FPS</p>
              </div>
            </div>
            <div class="camera-actions">
              <span class="camera-source">${camera.source_uri || "RTSP source"}</span>
              <div class="camera-action-group">
                <button class="camera-focus" type="button" data-camera-id="${camera.id}">${camera.id === selectedCameraId && overlayEditMode ? "Stop editing" : "Edit overlay"}</button>
                <button class="camera-delete" type="button" data-camera-id="${camera.id}">Remove</button>
              </div>
            </div>
            <div class="camera-meta">
              <span>Preview: ${previewMode.toUpperCase()}</span>
              <span>Fallback: ${camera.stream_protocol.toUpperCase()}</span>
            </div>
            <div class="camera-runtime">
              <span class="runtime-state ${camera.runtime?.stream_state || "unknown"}">${camera.runtime?.stream_state || "unknown"}</span>
              <span>${camera.runtime?.last_event ? `Trigger: ${camera.runtime.last_event.rule_type}` : "Trigger: idle"}</span>
              <span>${camera.runtime?.last_error ? `Stream issue: ${camera.runtime.last_error}` : "Stream issue: none"}</span>
            </div>
          </div>
        </article>
      `
    )
    .join("");

  cameras.forEach((camera) => {
    const card = cameraList.querySelector(`[data-camera-id="${camera.id}"]`);
    card.addEventListener("click", (event) => {
      if (event.target.closest("button")) {
        return;
      }
      selectCamera(camera.id, false);
    });
    bindCanvas(camera);
    scheduleCanvasRedraw(camera.id);
    const video = document.getElementById(`camera-preview-${camera.id}`);
    if (video) {
      attachStream(video, camera);
    }
  });

  document.querySelectorAll(".camera-focus").forEach((button) => {
    button.addEventListener("click", () => {
      const enableEditing = !(button.dataset.cameraId === selectedCameraId && overlayEditMode);
      selectCamera(button.dataset.cameraId, enableEditing);
      setGeometryMessage(
        enableEditing
          ? "Overlay editing enabled. Click on the video to draw geometry."
          : "Overlay editing disabled. Player controls are available again.",
        enableEditing ? "pending" : "success"
      );
    });
  });

  document.querySelectorAll(".camera-delete").forEach((button) => {
    button.addEventListener("click", async () => {
      const { cameraId } = button.dataset;
      if (!window.confirm(`Remove camera ${cameraId}?`)) {
        return;
      }
      button.disabled = true;
      try {
        await deleteCamera(cameraId);
        setFormMessage(`Camera ${cameraId} removed.`, "success");
        await loadDashboard(true);
      } catch (error) {
        console.error(error);
        setFormMessage(error.message, "error");
        button.disabled = false;
      }
    });
  });
}

function renderEvents(events) {
  const eventList = document.getElementById("event-list");
  eventList.innerHTML = events
    .map(
      (event) => `
        <article class="event-row">
          ${
            event.snapshot_url
              ? `<div class="event-snapshot-frame"><img class="event-snapshot" src="${event.snapshot_url}" alt="Snapshot for ${event.rule_type}" loading="lazy" /></div>`
              : `<div class="event-snapshot-frame"><div class="event-snapshot fallback">No snapshot</div></div>`
          }
          <div class="event-copy">
            <div>
              <h3>${event.rule_type}</h3>
              <p>${event.payload?.category || event.payload?.class_name || "object"} / ${event.payload?.class_name || "unknown"} / ${event.camera_id} / ${event.track_id}</p>
            </div>
            <span class="severity ${event.severity}">${event.severity}</span>
          </div>
          <time>${new Date(event.created_at).toLocaleString()}</time>
        </article>
      `
    )
    .join("");
}

async function createCamera(event) {
  event.preventDefault();
  const payload = {
    id: cameraIdInput.value.trim() || slugifyCameraId(cameraNameInput.value),
    name: cameraNameInput.value.trim(),
    source_uri: cameraSourceUriInput.value.trim(),
    target_fps: Number(cameraTargetFpsInput.value) || 5,
  };
  if (!payload.id || !payload.name || !payload.source_uri) {
    setFormMessage("Name, ID, and RTSP address are required.", "error");
    return;
  }
  setFormMessage("Adding camera...", "pending");
  const response = await fetch("/cameras", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Unable to add camera" }));
    setFormMessage(error.detail || "Unable to add camera", "error");
    return;
  }
  cameraForm.reset();
  cameraTargetFpsInput.value = "5";
  setFormMessage(`Camera ${payload.id} added.`, "success");
  await loadDashboard(true);
}

async function deleteCamera(cameraId) {
  const response = await fetch(`/cameras/${cameraId}`, { method: "DELETE" });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Unable to remove camera" }));
    throw new Error(error.detail || "Unable to remove camera");
  }
}

async function saveDetectionSettings() {
  const camera = getSelectedCamera();
  if (!camera) {
    setDetectionMessage("Select a camera before saving detection tuning.", "error");
    return;
  }
  const categories = [];
  if (detectPersonInput.checked) {
    categories.push("person");
  }
  if (detectVehicleInput.checked) {
    categories.push("vehicle");
  }
  if (!categories.length) {
    setDetectionMessage("Select at least one object category.", "error");
    return;
  }
  const payload = {
    categories,
    min_confidence: Number(detectionConfidenceInput.value),
    min_box_area: Number(detectionMinAreaInput.value),
  };
  setDetectionMessage("Saving detection tuning...", "pending");
  const response = await fetch(`/cameras/${camera.id}/detection_settings`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Unable to save detection tuning" }));
    setDetectionMessage(error.detail || "Unable to save detection tuning", "error");
    return;
  }
  setDetectionMessage("Detection tuning saved. New frames will use the updated filters.", "success");
  await loadDashboard(true);
}

async function resetSummary() {
  setSummaryMessage("Resetting live summary...", "pending");
  const response = await fetch("/metrics/reset_summary", { method: "POST" });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Unable to reset live summary" }));
    throw new Error(error.detail || "Unable to reset live summary");
  }
  setSummaryMessage("Live summary reset.", "success");
  await loadDashboard(true);
}

async function loadDashboard(forceCameraRefresh = false) {
  const [summary, cameras, events] = await Promise.all([
    fetch("/metrics/summary").then((response) => response.json()),
    fetch("/cameras").then((response) => response.json()),
    fetch("/events?limit=12").then((response) => response.json()),
  ]);
  const freezeDuringEdit = overlayEditMode && !forceCameraRefresh;
  camerasCache = cameras;
  syncDrafts(cameras);
  renderSummary(summary);
  document.getElementById("latest-activation").textContent = latestActivation(cameras, events);
  renderCameras(cameras, forceCameraRefresh, freezeDuringEdit);
  renderEvents(events);
  updateSelectionPanel();
}

document.getElementById("refresh").addEventListener("click", () => loadDashboard(true));
document.getElementById("reset-summary").addEventListener("click", () => {
  resetSummary().catch((error) => {
    console.error(error);
    setSummaryMessage(error.message, "error");
  });
});
document.getElementById("webrtc-mode").addEventListener("click", () => {
  previewMode = "webrtc";
  loadDashboard(true);
});
document.getElementById("hls-mode").addEventListener("click", () => {
  previewMode = "hls";
  loadDashboard(true);
});
document.querySelectorAll(".tool-button").forEach((button) => {
  button.addEventListener("click", () => {
    activeTool = button.dataset.tool;
    drawingPoints = [];
    updateToolButtons();
    updateGeometryHint();
    redrawAllCanvases();
  });
});
document.getElementById("finish-shape").addEventListener("click", finishShape);
document.getElementById("undo-point").addEventListener("click", undoLastPoint);
document.getElementById("clear-shape").addEventListener("click", clearActiveShape);
document.getElementById("save-geometry").addEventListener("click", () => {
  saveGeometry().catch((error) => {
    console.error(error);
    setGeometryMessage("Unable to save geometry", "error");
  });
});
document.getElementById("save-detection-settings").addEventListener("click", () => {
  saveDetectionSettings().catch((error) => {
    console.error(error);
    setDetectionMessage("Unable to save detection tuning", "error");
  });
});
cameraForm.addEventListener("submit", (event) => {
  createCamera(event).catch((error) => {
    console.error(error);
    setFormMessage("Unable to add camera", "error");
  });
});
detectionConfidenceInput.addEventListener("input", () => {
  detectionConfidenceValue.textContent = Number(detectionConfidenceInput.value).toFixed(2);
});
detectionMinAreaInput.addEventListener("input", () => {
  detectionMinAreaValue.textContent = Number(detectionMinAreaInput.value).toFixed(4);
});
cameraNameInput.addEventListener("input", () => {
  if (cameraIdInput.value.trim()) {
    return;
  }
  cameraIdInput.value = slugifyCameraId(cameraNameInput.value);
});
window.addEventListener("resize", redrawAllCanvases);
window.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && overlayEditMode) {
    drawingPoints = [];
    updateGeometryHint();
    setGeometryMessage("Cleared the in-progress shape.", "success");
    redrawAllCanvases();
  }
});

updateTransportButtons();
updateToolButtons();
updateGeometryHint();
loadDashboard(true);
setInterval(() => {
  if (overlayEditMode) {
    return;
  }
  loadDashboard(false);
}, 15000);
