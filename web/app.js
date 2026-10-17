/**
 * Logistics Dispatch Platform - Client Dashboard & Dual Map Engine Controller
 * Supports native Google Maps JavaScript API with clean OpenStreetMap fallback.
 */

// Known landmarks for coordinate fallback mapping (Chennai Metropolitan Area)
const CHENNAI_COORDS = {
  "adyar": { lat: 13.0012, lon: 80.2565 },
  "t nagar": { lat: 13.0418, lon: 80.2341 },
  "velachery": { lat: 12.9815, lon: 80.2180 },
  "guindy": { lat: 13.0067, lon: 80.2021 },
  "omr": { lat: 12.9150, lon: 80.2280 },
  "tambaram": { lat: 12.9249, lon: 80.1000 },
  "hub": { lat: 13.0827, lon: 80.2707 },
};

// Pure-white minimalist style for Google Maps
const PURE_WHITE_GOOGLE_MAP_STYLE = [
  { elementType: "geometry", stylers: [{ color: "#f8fafc" }] },
  { elementType: "labels.text.stroke", stylers: [{ color: "#ffffff" }] },
  { elementType: "labels.text.fill", stylers: [{ color: "#334155" }] },
  { featureType: "administrative.locality", elementType: "labels.text.fill", stylers: [{ color: "#0f172a" }] },
  { featureType: "poi", elementType: "labels.text.fill", stylers: [{ color: "#64748b" }] },
  { featureType: "road", elementType: "geometry", stylers: [{ color: "#ffffff" }] },
  { featureType: "road", elementType: "geometry.stroke", stylers: [{ color: "#e2e8f0" }] },
  { featureType: "road.highway", elementType: "geometry", stylers: [{ color: "#f1f5f9" }] },
  { featureType: "road.highway", elementType: "geometry.stroke", stylers: [{ color: "#cbd5e1" }] },
  { featureType: "transit", elementType: "geometry", stylers: [{ color: "#f1f5f9" }] },
  { featureType: "water", elementType: "geometry", stylers: [{ color: "#e0f2fe" }] },
  { featureType: "water", elementType: "labels.text.fill", stylers: [{ color: "#0284c7" }] },
];

let clientConfig = null;
let currentVehicleId = "driver-1";
let isSimRunning = false;

// Active map engine flag ('google' or 'leaflet')
let activeMapEngine = "google";

// Google Maps instances
let gMap = null;
let gDriverMarker = null;
let gStopMarkers = [];
let gPolyline = null;

// Leaflet instances
let lMap = null;
let lDriverMarker = null;
let lStopMarkers = [];
let lPolyline = null;

// ----------------------------------------------------
// UI Initialization
// ----------------------------------------------------
document.addEventListener("DOMContentLoaded", async () => {
  initClock();
  setupEventListeners();
  await loadConfigAndInitMap();
  await refreshState();
  setInterval(refreshState, 1500);
});

function initClock() {
  const clockElem = document.getElementById("liveClock");
  function update() {
    const now = new Date();
    clockElem.textContent = now.toTimeString().split(" ")[0] + " UTC";
  }
  update();
  setInterval(update, 1000);
}

// ----------------------------------------------------
// Map Initialization: Google Maps with Clean OSM Fallback
// ----------------------------------------------------
async function loadConfigAndInitMap() {
  try {
    const res = await fetch("/api/config");
    clientConfig = await res.json();
    if (clientConfig.force_routes_failure) {
      document.getElementById("routesHealthSub").textContent = "Traffic-Aware Routing Engine (Autonomous Recovery Active)";
    }

    const mapsApiKey = clientConfig.maps_api_key;
    if (mapsApiKey && mapsApiKey.startsWith("AIzaSy")) {
      initGoogleMapsApi(mapsApiKey);
    } else {
      switchToLeafletMap();
    }
  } catch (err) {
    console.error("Config fetch failed, using fallback map:", err);
    switchToLeafletMap();
  }
}

// Handle Google Maps Authentication Failures (e.g. key domain restrictions)
window.gm_authFailure = function() {
  console.warn("[Google Maps] Authentication failure or domain restriction detected. Switching to clean OpenStreetMap engine.");
  switchToLeafletMap();
};

function initGoogleMapsApi(apiKey) {
  // Define global callback
  window.onGoogleMapsReady = function() {
    try {
      const mapContainer = document.getElementById("googleMap");
      if (!mapContainer) return;

      gMap = new google.maps.Map(mapContainer, {
        center: { lat: 13.05, lng: 80.24 },
        zoom: 12,
        styles: PURE_WHITE_GOOGLE_MAP_STYLE,
        disableDefaultUI: false,
        zoomControl: true,
        streetViewControl: false,
        mapTypeControl: false,
      });

      // Driver custom marker icon with heading rotation SVG
      const driverSvg = {
        path: google.maps.SymbolPath.FORWARD_CLOSED_ARROW,
        scale: 6,
        fillColor: "#0f172a",
        fillOpacity: 1,
        strokeColor: "#38bdf8",
        strokeWeight: 2,
        rotation: 190,
      };

      gDriverMarker = new google.maps.Marker({
        position: { lat: 13.0827, lng: 80.2707 },
        map: gMap,
        title: "driver-1 (Active)",
        icon: driverSvg,
      });

      activeMapEngine = "google";
      const badge = document.getElementById("mapEngineBadge");
      if (badge) {
        badge.textContent = "Google Maps API";
        badge.className = "badge badge-primary";
      }

      console.info("[Google Maps] Google Maps JavaScript API loaded and operational.");
    } catch (e) {
      console.warn("Google Maps setup failed:", e);
      switchToLeafletMap();
    }
  };

  // Inject Google Maps script dynamically
  const script = document.createElement("script");
  script.src = `https://maps.googleapis.com/maps/api/js?key=${apiKey}&callback=onGoogleMapsReady&libraries=geometry`;
  script.async = true;
  script.defer = true;
  script.onerror = () => {
    console.warn("[Google Maps] Script tag error. Engaging clean OpenStreetMap fallback.");
    switchToLeafletMap();
  };
  document.head.appendChild(script);
}

function switchToLeafletMap() {
  activeMapEngine = "leaflet";
  const gElem = document.getElementById("googleMap");
  const lElem = document.getElementById("liveLeafletMap");
  if (gElem) gElem.style.display = "none";
  if (lElem) lElem.style.display = "block";

  const badge = document.getElementById("mapEngineBadge");
  if (badge) {
    badge.textContent = "Live Geographic Map";
    badge.className = "badge badge-primary";
  }

  if (!lMap) {
    try {
      lMap = L.map("liveLeafletMap", {
        zoomControl: true,
        attributionControl: true,
      }).setView([13.05, 80.24], 12);

      // Clean Standard OpenStreetMap tiles - ZERO WATERMARK, 100% FREE PUBLIC ACCESS
      L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
        maxZoom: 19,
      }).addTo(lMap);

      const driverIcon = L.divIcon({
        className: "custom-driver-icon",
        html: `
          <div style="position: relative; width: 32px; height: 32px; display: flex; align-items: center; justify-content: center;">
            <div style="position: absolute; width: 28px; height: 28px; background: rgba(37,99,235,0.25); border-radius: 50%; animation: pulse 2s infinite ease-out;"></div>
            <div style="width: 18px; height: 18px; background: #0f172a; border: 2px solid #ffffff; border-radius: 50%; display: flex; align-items: center; justify-content: center; box-shadow: 0 2px 4px rgba(0,0,0,0.3);">
              <div id="leafletDriverHeading" style="width: 0; height: 0; border-left: 4px solid transparent; border-right: 4px solid transparent; border-bottom: 7px solid #38bdf8; transform: rotate(0deg);"></div>
            </div>
          </div>
        `,
        iconSize: [32, 32],
        iconAnchor: [16, 16],
      });

      lDriverMarker = L.marker([13.0827, 80.2707], { icon: driverIcon }).addTo(lMap);
      lDriverMarker.bindPopup("<strong>Driver driver-1</strong><br>Fleet Active");

      setTimeout(() => { lMap.invalidateSize(); }, 400);
    } catch (err) {
      console.error("Leaflet fallback setup error:", err);
    }
  }
}

// ----------------------------------------------------
// State Polling & UI Sync
// ----------------------------------------------------
async function refreshState() {
  try {
    const res = await fetch(`/api/state?vehicle_id=${currentVehicleId}`);
    if (!res.ok) return;
    const state = await res.json();

    // 1. Update Vehicle Telemetry
    if (state.vehicle) {
      const v = state.vehicle;
      document.getElementById("telemetryLat").textContent = `${v.latitude.toFixed(4)}° N`;
      document.getElementById("telemetryLon").textContent = `${v.longitude.toFixed(4)}° E`;
      document.getElementById("telemetrySpeed").textContent = `${(v.speed || 0).toFixed(1)} km/h`;
      document.getElementById("telemetryHeading").textContent = `${Math.round(v.heading || 0)}°`;
      document.getElementById("telemetryAddress").textContent = v.address || `${v.latitude.toFixed(4)}, ${v.longitude.toFixed(4)}`;
      document.getElementById("telemetryPing").textContent = v.timestamp ? new Date(v.timestamp).toLocaleTimeString() : "Just now";

      // Move Driver on Active Map Engine
      if (activeMapEngine === "google" && gDriverMarker && gMap) {
        gDriverMarker.setPosition({ lat: v.latitude, lng: v.longitude });
        const icon = gDriverMarker.getIcon();
        if (icon && v.heading !== undefined) {
          icon.rotation = v.heading;
          gDriverMarker.setIcon(icon);
        }
      } else if (lDriverMarker && lMap) {
        lDriverMarker.setLatLng([v.latitude, v.longitude]);
        const headingElem = document.getElementById("leafletDriverHeading");
        if (headingElem && v.heading !== undefined) {
          headingElem.style.transform = `rotate(${v.heading}deg)`;
        }
      }
    }

    // 2. Update Controller State
    isSimRunning = state.simulator_running;
    const simBadge = document.getElementById("simStatusBadge");
    const btnStart = document.getElementById("btnStartSim");
    const btnStop = document.getElementById("btnStopSim");

    if (isSimRunning) {
      simBadge.textContent = "Driving";
      simBadge.className = "badge badge-active";
      btnStart.disabled = true;
      btnStop.disabled = false;
    } else {
      simBadge.textContent = "Idle";
      simBadge.className = "badge badge-idle";
      btnStart.disabled = false;
      btnStop.disabled = true;
    }

    const step = state.simulator_step || 0;
    const progressPct = Math.min(100, Math.round(((step % 21) / 20) * 100));
    document.getElementById("simProgressBar").style.width = `${progressPct}%`;
    document.getElementById("simStepLabel").textContent = `Waypoint: ${step % 21 + 1} / 21`;

    // 3. Update KPIs
    if (state.stats) {
      document.getElementById("kpiOnTime").textContent = `${state.stats.on_time_rate}%`;
      document.getElementById("kpiStopsDone").textContent = `${state.stats.stops_completed} / ${state.stats.total_stops}`;
      document.getElementById("kpiHealing").textContent = state.stats.healing_count;
      document.getElementById("kpiLoops").textContent = state.stats.loop_iterations;
    }

    // 4. Update Stops & Map Pins
    renderStopsAndMap(state.stops || [], state.route_plan, state.vehicle);

    // 5. Update Delay Drawer
    renderDelayDrafts(state.delay_notifications || []);

  } catch (err) {
    console.warn("Poll state error:", err);
  }
}

// ----------------------------------------------------
// Map & Route Sequence Renderer
// ----------------------------------------------------
function renderStopsAndMap(stops, routePlan, vehicle) {
  const tbody = document.getElementById("stopsTableBody");
  const stopCountBadge = document.getElementById("stopCountBadge");

  if (!stops || stops.length === 0) {
    tbody.innerHTML = `<tr class="empty-row"><td colspan="6">No active route planned. Submit an order prompt to optimize dispatch.</td></tr>`;
    stopCountBadge.textContent = "0 Stops";

    // Clear Google Maps layers
    if (gStopMarkers.length > 0) {
      gStopMarkers.forEach(m => m.setMap(null));
      gStopMarkers = [];
    }
    if (gPolyline) {
      gPolyline.setMap(null);
      gPolyline = null;
    }

    // Clear Leaflet layers
    if (lStopMarkers.length > 0 && lMap) {
      lStopMarkers.forEach(m => lMap.removeLayer(m));
      lStopMarkers = [];
    }
    if (lPolyline && lMap) {
      lMap.removeLayer(lPolyline);
      lPolyline = null;
    }
    return;
  }

  stopCountBadge.textContent = `${stops.length} Stops`;

  // Render Table
  tbody.innerHTML = stops.map((s, idx) => {
    const isCompleted = s.status === "completed";
    const isBreached = s.breached;
    const rowClass = isCompleted ? "status-completed-row" : (isBreached ? "status-breached-row" : "");
    const statusPill = isCompleted
      ? `<span class="badge badge-active">Completed</span>`
      : (isBreached
          ? `<span class="badge badge-warn">Window Breached</span>`
          : `<span class="badge badge-idle">Pending</span>`);

    return `
      <tr class="${rowClass}">
        <td><strong>#${idx + 1}</strong></td>
        <td>${s.address || "Delivery Stop"}</td>
        <td>${s.customer_name || "Customer"}</td>
        <td>${s.window_end || "17:00"}</td>
        <td><strong>${s.eta || "--:--"}</strong></td>
        <td>${statusPill}</td>
      </tr>
    `;
  }).join("");

  // Render Route Summary Ribbon
  if (routePlan) {
    document.getElementById("routeDistance").textContent = `${routePlan.total_distance_km || "--"} km`;
    document.getElementById("routeDuration").textContent = `${routePlan.total_duration_minutes || "--"} mins`;
    document.getElementById("routeMode").textContent = routePlan.mode === "google_routes_api" ? "Traffic-Aware Optimizer" : "Self-Healing Route Plan";
    document.getElementById("routeHealingStatus").textContent = routePlan.degraded ? "Autonomous Fallback" : "Protected";
    document.getElementById("routeHealingStatus").className = routePlan.degraded ? "stat-val text-danger" : "stat-val text-success";
  }

  // --- RENDER ON GOOGLE MAPS ---
  if (activeMapEngine === "google" && gMap) {
    // Clear old markers
    gStopMarkers.forEach(m => m.setMap(null));
    gStopMarkers = [];

    const bounds = new google.maps.LatLngBounds();
    const gCoords = [];

    if (vehicle && vehicle.latitude && vehicle.longitude) {
      const vPos = { lat: vehicle.latitude, lng: vehicle.longitude };
      gCoords.push(vPos);
      bounds.extend(vPos);
    }

    stops.forEach((s, idx) => {
      let lat = s.latitude;
      let lon = s.longitude;
      if (!lat || !lon) {
        const lower = (s.address || "").toLowerCase();
        for (const [key, coords] of Object.entries(CHENNAI_COORDS)) {
          if (lower.includes(key)) {
            lat = coords.lat;
            lon = coords.lon;
            break;
          }
        }
      }

      if (lat && lon) {
        const pos = { lat, lng: lon };
        gCoords.push(pos);
        bounds.extend(pos);

        const pinColor = s.status === "completed" ? "#10b981" : (s.breached ? "#ef4444" : "#f59e0b");
        const marker = new google.maps.Marker({
          position: pos,
          map: gMap,
          label: {
            text: `${idx + 1}`,
            color: "#ffffff",
            fontWeight: "bold",
            fontSize: "11px",
          },
          icon: {
            path: google.maps.SymbolPath.CIRCLE,
            fillColor: pinColor,
            fillOpacity: 1,
            strokeColor: "#ffffff",
            strokeWeight: 2,
            scale: 12,
          },
          title: `Stop #${idx + 1}: ${s.address}`,
        });

        const info = new google.maps.InfoWindow({
          content: `<strong>Stop #${idx + 1}: ${s.address}</strong><br>ETA: ${s.eta || "--:--"}<br>Status: ${s.status}`,
        });
        marker.addListener("click", () => info.open(gMap, marker));
        gStopMarkers.push(marker);
      }
    });

    if (gPolyline) gPolyline.setMap(null);
    if (gCoords.length > 1) {
      gPolyline = new google.maps.Polyline({
        path: gCoords,
        strokeColor: "#0f172a",
        strokeWeight: 4,
        strokeOpacity: 0.85,
        map: gMap,
      });
      gMap.fitBounds(bounds, { top: 40, bottom: 40, left: 40, right: 40 });
    }
    return;
  }

  // --- RENDER ON LEAFLET MAP ---
  if (!lMap) return;

  // Clear existing stop markers
  lStopMarkers.forEach(m => lMap.removeLayer(m));
  lStopMarkers = [];

  const latLngs = [];
  if (vehicle && vehicle.latitude && vehicle.longitude) {
    latLngs.push([vehicle.latitude, vehicle.longitude]);
  }

  stops.forEach((s, idx) => {
    let lat = s.latitude;
    let lon = s.longitude;

    if (!lat || !lon) {
      const lower = (s.address || "").toLowerCase();
      for (const [key, coords] of Object.entries(CHENNAI_COORDS)) {
        if (lower.includes(key)) {
          lat = coords.lat;
          lon = coords.lon;
          break;
        }
      }
    }

    if (lat && lon) {
      latLngs.push([lat, lon]);

      const pinBg = s.status === "completed" ? "#10b981" : (s.breached ? "#ef4444" : "#f59e0b");
      const pinIcon = L.divIcon({
        className: "custom-stop-pin",
        html: `
          <div style="background-color: ${pinBg}; color: #ffffff; width: 24px; height: 24px; border-radius: 50%; border: 2px solid #ffffff; display: flex; align-items: center; justify-content: center; font-size: 11px; font-weight: 700; box-shadow: 0 2px 5px rgba(0,0,0,0.25);">
            ${idx + 1}
          </div>
        `,
        iconSize: [24, 24],
        iconAnchor: [12, 12],
      });

      const marker = L.marker([lat, lon], { icon: pinIcon }).addTo(lMap);
      marker.bindPopup(`
        <strong>Stop #${idx + 1}: ${s.address || "Destination"}</strong><br>
        Customer: ${s.customer_name || "Customer"}<br>
        Window: ${s.window_end || "17:00"} | ETA: ${s.eta || "--:--"}<br>
        Status: <strong>${s.status || "Pending"}</strong>
      `);
      lStopMarkers.push(marker);
    }
  });

  // Update Route Polyline on Map
  if (lPolyline) {
    lMap.removeLayer(lPolyline);
  }

  if (latLngs.length > 1) {
    lPolyline = L.polyline(latLngs, {
      color: "#0f172a",
      weight: 4,
      dashArray: "6, 8",
      opacity: 0.85,
    }).addTo(lMap);

    try {
      lMap.fitBounds(L.latLngBounds(latLngs), { padding: [40, 40], maxZoom: 14 });
    } catch (e) {}
  }
}

// ----------------------------------------------------
// Delay Notifications Drawer
// ----------------------------------------------------
function renderDelayDrafts(drafts) {
  const drawer = document.getElementById("delayDrawer");
  const list = document.getElementById("delayList");

  if (!drafts || drafts.length === 0) {
    drawer.classList.add("hidden");
    list.innerHTML = "";
    return;
  }

  drawer.classList.remove("hidden");
  list.innerHTML = drafts.map(d => `
    <div class="delay-card-item">
      <div class="delay-msg">"${d.message}"</div>
      <div class="delay-footer">
        <span class="badge ${d.sent ? 'badge-active' : 'badge-warn'}">
          ${d.sent ? '✓ Transmitted via SMS' : 'Awaiting Dispatch Approval'}
        </span>
        ${!d.sent ? `<button class="btn btn-primary btn-sm" onclick="approveDelayNotification('${d.stop_id}')">Approve & Send</button>` : ''}
      </div>
    </div>
  `).join("");
}

window.approveDelayNotification = async function(stopId) {
  try {
    await fetch("/api/approve-notification", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ stop_id: stopId }),
    });
    addTimelineItem({
      agent: "Notifier Specialist",
      title: "Notification Transmitted",
      text: `Approved and transmitted customer delay SMS alert for Stop ${stopId}.`,
      type: "tool",
    });
    refreshState();
  } catch (err) {
    console.error("Approve error:", err);
  }
};

// ----------------------------------------------------
// Conversational Dispatcher & Streaming SSE Handler
// ----------------------------------------------------
function setupEventListeners() {
  document.getElementById("btnStartSim").addEventListener("click", async () => {
    await fetch("/api/sim/start", { method: "POST" });
    refreshState();
  });

  document.getElementById("btnStopSim").addEventListener("click", async () => {
    await fetch("/api/sim/stop", { method: "POST" });
    refreshState();
  });

  document.getElementById("btnOpenDiagnostics").addEventListener("click", showDiagnosticsModal);
  document.getElementById("btnCloseModal").addEventListener("click", hideDiagnosticsModal);
  document.getElementById("btnCloseModalBtn").addEventListener("click", hideDiagnosticsModal);
  document.getElementById("btnRerunDiagnostics").addEventListener("click", showDiagnosticsModal);

  document.querySelectorAll(".chip").forEach(chip => {
    chip.addEventListener("click", () => {
      const prompt = chip.getAttribute("data-prompt");
      document.getElementById("chatInput").value = prompt;
      sendChatMessage(prompt);
    });
  });

  document.getElementById("chatForm").addEventListener("submit", (e) => {
    e.preventDefault();
    const input = document.getElementById("chatInput");
    const msg = input.value.trim();
    if (msg) {
      sendChatMessage(msg);
      input.value = "";
    }
  });
}

async function sendChatMessage(message) {
  const chatHistory = document.getElementById("chatHistory");
  const sendBtn = document.getElementById("btnSendChat");
  const timelineBadge = document.getElementById("timelineStatusBadge");

  appendChatMessage("user", message);
  sendBtn.disabled = true;
  timelineBadge.textContent = "Executing";
  timelineBadge.className = "badge badge-active";

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: message, vehicle_id: currentVehicleId }),
    });

    if (!res.ok) {
      appendChatMessage("bot", "Error communicating with Logistics Dispatch Platform backend.");
      sendBtn.disabled = false;
      timelineBadge.textContent = "Ready";
      timelineBadge.className = "badge badge-idle";
      return;
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n\n");
      buffer = lines.pop();

      for (const chunk of lines) {
        if (!chunk.trim()) continue;
        const eventMatch = chunk.match(/^event:\s*(.+)$/m);
        const dataMatch = chunk.match(/^data:\s*(.+)$/m);

        if (eventMatch && dataMatch) {
          const eventType = eventMatch[1].trim();
          let data = {};
          try {
            data = JSON.parse(dataMatch[1].trim());
          } catch (e) {
            data = { text: dataMatch[1] };
          }
          handleSseEvent(eventType, data);
        }
      }
    }

  } catch (err) {
    console.error("Chat error:", err);
    appendChatMessage("bot", "Communication error occurred while processing dispatch request.");
  } finally {
    sendBtn.disabled = false;
    timelineBadge.textContent = "Ready";
    timelineBadge.className = "badge badge-idle";
    refreshState();
  }
}

function handleSseEvent(eventType, data) {
  switch (eventType) {
    case "agent_step":
      addTimelineItem({
        agent: data.agent || "Lead Dispatcher",
        title: `Agent Transition: ${data.agent}`,
        text: data.message,
        type: "agent",
      });
      break;

    case "tool_call":
      addTimelineItem({
        agent: data.agent || "Lead Dispatcher",
        title: `Dispatch Tool: ${data.tool}()`,
        text: `Parameters: ${JSON.stringify(data.args)}`,
        type: "tool",
      });
      break;

    case "tool_result":
      addTimelineItem({
        agent: data.agent || "Lead Dispatcher",
        title: `Tool Result: ${data.tool}()`,
        text: `Output received successfully (${Object.keys(data.result || {}).length} keys).`,
        type: "tool",
      });
      break;

    case "loop_iteration":
      addTimelineItem({
        agent: data.agent || "Route Optimizer",
        title: `Optimization Cycle #${data.iteration || 1} [${data.status || 'Active'}]`,
        text: data.action || data.feedback || "Auditing routing constraints...",
        type: data.status === "breached" ? "breached" : "loop",
      });
      break;

    case "healing":
      addTimelineItem({
        agent: "Self-Healing Engine",
        title: "⚡ Autonomous Recovery Event",
        text: data.message || "Route planner fallback engaged gracefully.",
        type: "healing",
      });
      break;

    case "message":
      appendChatMessage("bot", data.text);
      break;

    case "done":
      refreshState();
      break;
  }
}

function appendChatMessage(sender, text) {
  const history = document.getElementById("chatHistory");
  const msgElem = document.createElement("div");
  msgElem.className = `chat-message ${sender}-message`;

  const avatar = sender === "user" ? "YOU" : "DISP";
  const formattedText = (text || "").replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>").replace(/\n/g, "<br>");

  msgElem.innerHTML = `
    <div class="msg-avatar">${avatar}</div>
    <div class="msg-content"><p>${formattedText}</p></div>
  `;
  history.appendChild(msgElem);
  history.scrollTop = history.scrollHeight;
}

function addTimelineItem({ agent, title, text, type }) {
  const timeline = document.getElementById("agentTimeline");
  const emptyPlaceholder = timeline.querySelector(".timeline-empty");
  if (emptyPlaceholder) emptyPlaceholder.remove();

  const item = document.createElement("div");
  item.className = "timeline-item";

  const dotClass = type === "tool" ? "dot-tool" : (type === "healing" ? "dot-healing" : (type === "breached" ? "dot-breached" : "dot-loop"));
  const timeStr = new Date().toLocaleTimeString();

  item.innerHTML = `
    <div class="timeline-dot ${dotClass}"></div>
    <div class="timeline-body">
      <div class="timeline-header">
        <span class="timeline-agent">${agent} • ${title}</span>
        <span class="timeline-time">${timeStr}</span>
      </div>
      <div class="timeline-text">${text}</div>
    </div>
  `;

  timeline.prepend(item);
}

// ----------------------------------------------------
// Diagnostics Modal Logic
// ----------------------------------------------------
async function showDiagnosticsModal() {
  const modal = document.getElementById("diagnosticsModal");
  const content = document.getElementById("modalDiagnosticsContent");
  modal.classList.remove("hidden");
  content.innerHTML = `<div class="loading-spinner">Running diagnostic probe across core services...</div>`;

  try {
    const res = await fetch("/api/diagnostics");
    const diag = await res.json();

    content.innerHTML = `
      <div class="health-list">
        <div class="health-item">
          <span class="health-icon ${diag.gemini.status === 'PASS' ? 'health-pass' : 'health-warn'}">
            ${diag.gemini.status === 'PASS' ? '✓' : '!'}
          </span>
          <div class="health-info">
            <span class="health-title">AI Engine: ${diag.gemini.status}</span>
            <span class="health-sub">Model: ${diag.gemini.model || 'Enterprise AI'} | Status: "${diag.gemini.response}"</span>
          </div>
        </div>

        <div class="health-item">
          <span class="health-icon ${diag.routes.status === 'PASS' ? 'health-pass' : 'health-warn'}">
            ${diag.routes.status === 'PASS' ? '✓' : '⚡'}
          </span>
          <div class="health-info">
            <span class="health-title">Routing Engine: ${diag.routes.status} (${diag.routes.mode})</span>
            <span class="health-sub">${diag.routes.details || 'Routes computation operational.'}</span>
          </div>
        </div>

        <div class="health-item">
          <span class="health-icon health-pass">✓</span>
          <div class="health-info">
            <span class="health-title">Persistence Backend: ${diag.store.status}</span>
            <span class="health-sub">Mode: ${diag.store.backend}</span>
          </div>
        </div>

        <div class="health-item">
          <span class="health-icon health-pass">✓</span>
          <div class="health-info">
            <span class="health-title">Gateway Services: ${diag.mcp.status}</span>
            <span class="health-sub">Tools: ${diag.mcp.tools.join(', ')}</span>
          </div>
        </div>
      </div>
    `;
  } catch (err) {
    content.innerHTML = `<div class="text-danger">Failed to execute diagnostics: ${err.message}</div>`;
  }
}

function hideDiagnosticsModal() {
  document.getElementById("diagnosticsModal").classList.add("hidden");
}
