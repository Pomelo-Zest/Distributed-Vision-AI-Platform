const players = new Map();
let cameraSignature = "";

function teardownPlayers() {
  for (const player of players.values()) {
    if (player && typeof player.destroy === "function") {
      player.destroy();
    }
  }
  players.clear();
}

function attachStream(video, camera) {
  const streamUrl = camera.stream_url;
  if (!streamUrl) {
    video.replaceWith(Object.assign(document.createElement("div"), { className: "camera-preview fallback", textContent: "No stream URL" }));
    return;
  }

  if (video.canPlayType("application/vnd.apple.mpegurl")) {
    video.src = streamUrl;
    return;
  }

  if (window.Hls && window.Hls.isSupported()) {
    const hls = new window.Hls({
      liveDurationInfinity: true,
      lowLatencyMode: true,
      backBufferLength: 30,
    });
    hls.loadSource(streamUrl);
    hls.attachMedia(video);
    players.set(camera.id, hls);
    return;
  }

  video.replaceWith(
    Object.assign(document.createElement("div"), {
      className: "camera-preview fallback",
      textContent: "HLS unsupported in this browser",
    })
  );
}

function renderSummary(summary) {
  document.getElementById("active-cameras").textContent = summary.active_cameras;
  document.getElementById("total-detections").textContent = summary.total_detections;
  document.getElementById("total-events").textContent = summary.total_events;
}

function renderCameras(cameras) {
  const nextSignature = cameras.map((camera) => `${camera.id}:${camera.stream_url}:${camera.status}`).join("|");
  if (nextSignature === cameraSignature) {
    return;
  }
  cameraSignature = nextSignature;
  teardownPlayers();
  const cameraList = document.getElementById("camera-list");
  cameraList.innerHTML = cameras
    .map(
      (camera) => `
        <article class="camera-card">
          <video
            class="camera-preview"
            id="camera-preview-${camera.id}"
            muted
            autoplay
            playsinline
            controls
          ></video>
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
          <div class="camera-meta">
            <span>Transport: ${camera.stream_protocol.toUpperCase()}</span>
            <span>Inference: ${camera.last_inference_at ? new Date(camera.last_inference_at).toLocaleTimeString() : "pending"}</span>
          </div>
        </article>
      `
    )
    .join("");

  for (const camera of cameras) {
    const video = document.getElementById(`camera-preview-${camera.id}`);
    if (video) {
      attachStream(video, camera);
    }
  }
}

function renderEvents(events) {
  const eventList = document.getElementById("event-list");
  eventList.innerHTML = events
    .map(
      (event) => `
        <article class="event-row">
          ${
            event.snapshot_url
              ? `<img class="event-snapshot" src="${event.snapshot_url}" alt="Snapshot for ${event.rule_type}" />`
              : `<div class="event-snapshot fallback">No snapshot</div>`
          }
          <div class="event-copy">
            <div>
              <h3>${event.rule_type}</h3>
              <p>${event.camera_id} / ${event.track_id}</p>
            </div>
            <span class="severity ${event.severity}">${event.severity}</span>
          </div>
          <time>${new Date(event.created_at).toLocaleString()}</time>
        </article>
      `
    )
    .join("");
}

async function loadDashboard() {
  const [summary, cameras, events] = await Promise.all([
    fetch("/metrics/summary").then((response) => response.json()),
    fetch("/cameras").then((response) => response.json()),
    fetch("/events?limit=12").then((response) => response.json()),
  ]);
  renderSummary(summary);
  renderCameras(cameras);
  renderEvents(events);
}

document.getElementById("refresh").addEventListener("click", loadDashboard);
loadDashboard();
setInterval(loadDashboard, 15000);
