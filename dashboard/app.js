async function loadDashboard() {
  const [summary, cameras, events] = await Promise.all([
    fetch("/metrics/summary").then((response) => response.json()),
    fetch("/cameras").then((response) => response.json()),
    fetch("/events?limit=12").then((response) => response.json()),
  ]);

  document.getElementById("active-cameras").textContent = summary.active_cameras;
  document.getElementById("total-detections").textContent = summary.total_detections;
  document.getElementById("total-events").textContent = summary.total_events;

  const cameraList = document.getElementById("camera-list");
  cameraList.innerHTML = cameras
    .map(
      (camera) => `
        <article class="camera-card">
          <img
            class="camera-preview"
            src="${camera.preview_url}?ts=${new Date(camera.last_inference_at || camera.last_frame_at || Date.now()).getTime()}"
            alt="Preview for ${camera.name}"
          />
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
            <span>Frames: ${new Date(camera.last_frame_at || Date.now()).toLocaleTimeString()}</span>
            <span>Inference: ${camera.last_inference_at ? new Date(camera.last_inference_at).toLocaleTimeString() : "pending"}</span>
          </div>
        </article>
      `
    )
    .join("");

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

document.getElementById("refresh").addEventListener("click", loadDashboard);
loadDashboard();
setInterval(loadDashboard, 5000);
