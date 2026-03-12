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
      `
    )
    .join("");

  const eventList = document.getElementById("event-list");
  eventList.innerHTML = events
    .map(
      (event) => `
        <div class="event-row">
          <div>
            <h3>${event.rule_type}</h3>
            <p>${event.camera_id} / ${event.track_id}</p>
          </div>
          <time>${new Date(event.created_at).toLocaleString()}</time>
        </div>
      `
    )
    .join("");
}

document.getElementById("refresh").addEventListener("click", loadDashboard);
loadDashboard();
setInterval(loadDashboard, 5000);

