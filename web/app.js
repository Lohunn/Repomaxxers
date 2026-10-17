/**
 * Logistics Dispatch Agents - Client Dashboard & Streaming SSE Controller
 */

// Bounding box for Chennai Metropolitan Dispatch Area
const CHENNAI_BBOX = {
  minLat: 12.90,
  maxLat: 13.12,
  minLon: 80.08,
  maxLon: 80.30,
};

// Known landmarks for coordinate fallback mapping
const CHENNAI_COORDS = {
  "adyar": { lat: 13.0012, lon: 80.2565 },
  "t nagar": { lat: 13.0418, lon: 80.2341 },
  "velachery": { lat: 12.9815, lon: 80.2180 },
  "guindy": { lat: 13.0067, lon: 80.2021 },
  "omr": { lat: 12.9150, lon: 80.2280 },
  "tambaram": { lat: 12.9249, lon: 80.1000 },
  "hub": { lat: 13.0827, lon: 80.2707 },
};

let clientConfig = null;
let currentVehicleId = "driver-1";
let isSimRunning = false;

// ----------------------------------------------------
// Coordinate Projection for Vector Map
// ----------------------------------------------------
function projectToSvg(lat, lon) {
  const normX = (lon - CHENNAI_BBOX.minLon) / (CHENNAI_BBOX.maxLon - CHENNAI_BBOX.minLon);
  const normY = (CHENNAI_BBOX.maxLat - lat) / (CHENNAI_BBOX.maxLat - CHENNAI_BBOX.minLat);

  const x = Math.max(30, Math.min(770, normX * 720 + 40));
  const y = Math.max(30, Math.min(470, normY * 420 + 40));
  return { x: Math.round(x), y: Math.round(y) };
}

// ----------------------------------------------------
// UI Initialization
// ----------------------------------------------------
document.addEventListener("DOMContentLoaded", async () => {
  initClock();
  setupEventListeners();
  await loadConfig();
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

async function loadConfig() {
  try {
    const res = await fetch("/api/config");
    clientConfig = await res.json();
    if (clientConfig.force_routes_failure) {
      document.getElementById("routesHealthSub").textContent = "FORCE_ROUTES_FAILURE active (Self-Healing Fallback)";
    }
  } catch (err) {
    console.error("Failed to load /api/config:", err);
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

      // Move Driver Pin on Vector Map
      const pt = projectToSvg(v.latitude, v.longitude);
      const marker = document.getElementById("driverMarkerGroup");
      if (marker) {
        marker.setAttribute("transform", `translate(${pt.x}, ${pt.y})`);
        const arrow = document.getElementById("driverHeadingArrow");
        if (arrow && v.heading !== undefined) {
          arrow.setAttribute("transform", `rotate(${v.heading})`);
        }
      }
    }

    // 2. Update Simulator State
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
    document.getElementById("simStepLabel").textContent = `Step: ${step % 21 + 1} / 21`;

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
  const pinsGroup = document.getElementById("stopPinsGroup");
  const polylineElem = document.getElementById("routePolyline");

  if (!stops || stops.length === 0) {
    tbody.innerHTML = `<tr class="empty-row"><td colspan="6">No active route planned. Submit an order prompt to optimize dispatch.</td></tr>`;
    stopCountBadge.textContent = "0 Stops";
    pinsGroup.innerHTML = "";
    polylineElem.setAttribute("d", "");
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
    document.getElementById("routeMode").textContent = routePlan.mode === "google_routes_api" ? "Google Routes API" : "Haversine TSP (Healed)";
    document.getElementById("routeHealingStatus").textContent = routePlan.degraded ? "Graceful Fallback" : "Protected";
    document.getElementById("routeHealingStatus").className = routePlan.degraded ? "stat-val text-danger" : "stat-val text-success";
  }

  // Render Pins & Polyline on Vector Map
  let pathD = "";
  if (vehicle) {
    const startPt = projectToSvg(vehicle.latitude, vehicle.longitude);
    pathD = `M ${startPt.x} ${startPt.y}`;
  }

  let pinsHtml = "";
  stops.forEach((s, idx) => {
    let lat = s.latitude;
    let lon = s.longitude;

    // Fallback geocode matching if lat/lon missing
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
      const pt = projectToSvg(lat, lon);
      if (pathD) {
        pathD += ` L ${pt.x} ${pt.y}`;
      } else {
        pathD = `M ${pt.x} ${pt.y}`;
      }

      const pinColor = s.status === "completed" ? "#10b981" : (s.breached ? "#ef4444" : "#f59e0b");
      pinsHtml += `
        <g transform="translate(${pt.x}, ${pt.y})">
          <circle cx="0" cy="0" r="12" fill="${pinColor}" fill-opacity="0.25" />
          <circle cx="0" cy="0" r="7" fill="${pinColor}" stroke="#ffffff" stroke-width="1.5" />
          <text x="0" y="3" text-anchor="middle" fill="#ffffff" font-size="8" font-weight="700">${idx + 1}</text>
          <text x="0" y="-12" text-anchor="middle" fill="#0f172a" font-size="10" font-weight="600">${s.address || ""}</text>
        </g>
      `;
    }
  });

  pinsGroup.innerHTML = pinsHtml;
  polylineElem.setAttribute("d", pathD);
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
      agent: "notifier_agent",
      title: "Notification Transmitted",
      text: `Approved and transmitted customer delay SMS/WhatsApp alert for Stop ${stopId}.`,
      type: "tool",
    });
    refreshState();
  } catch (err) {
    console.error("Approve error:", err);
  }
};

// ----------------------------------------------------
// Conversational Chat & Streaming SSE Handler
// ----------------------------------------------------
function setupEventListeners() {
  // Simulator Buttons
  document.getElementById("btnStartSim").addEventListener("click", async () => {
    await fetch("/api/sim/start", { method: "POST" });
    refreshState();
  });

  document.getElementById("btnStopSim").addEventListener("click", async () => {
    await fetch("/api/sim/stop", { method: "POST" });
    refreshState();
  });

  // Diagnostics Modal Buttons
  document.getElementById("btnOpenDiagnostics").addEventListener("click", showDiagnosticsModal);
  document.getElementById("btnCloseModal").addEventListener("click", hideDiagnosticsModal);
  document.getElementById("btnCloseModalBtn").addEventListener("click", hideDiagnosticsModal);
  document.getElementById("btnRerunDiagnostics").addEventListener("click", showDiagnosticsModal);

  // Demo Prompt Chips
  document.querySelectorAll(".chip").forEach(chip => {
    chip.addEventListener("click", () => {
      const prompt = chip.getAttribute("data-prompt");
      document.getElementById("chatInput").value = prompt;
      sendChatMessage(prompt);
    });
  });

  // Chat Form Submit
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

  // Append User Bubble
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
      appendChatMessage("bot", "Error communicating with Logistics Dispatch Agents backend.");
      sendBtn.disabled = false;
      timelineBadge.textContent = "Ready";
      timelineBadge.className = "badge badge-idle";
      return;
    }

    // Read SSE Stream
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n\n");
      buffer = lines.pop(); // Keep unfinished tail

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

// ----------------------------------------------------
// SSE Event Handler & Timeline Dispatcher
// ----------------------------------------------------
function handleSseEvent(eventType, data) {
  switch (eventType) {
    case "agent_step":
      addTimelineItem({
        agent: data.agent || "dispatcher",
        title: `Agent Transition: ${data.agent}`,
        text: data.message,
        type: "agent",
      });
      break;

    case "tool_call":
      addTimelineItem({
        agent: data.agent || "dispatcher",
        title: `Tool Call: ${data.tool}()`,
        text: `Parameters: ${JSON.stringify(data.args)}`,
        type: "tool",
      });
      break;

    case "tool_result":
      addTimelineItem({
        agent: data.agent || "dispatcher",
        title: `Tool Result: ${data.tool}()`,
        text: `Output received successfully (${Object.keys(data.result || {}).length} keys).`,
        type: "tool",
      });
      break;

    case "loop_iteration":
      addTimelineItem({
        agent: data.agent || "LoopAgent",
        title: `Loop Iteration #${data.iteration || 1} [${data.status || 'Active'}]`,
        text: data.action || data.feedback || "Auditing routing constraints...",
        type: data.status === "breached" ? "breached" : "loop",
      });
      break;

    case "healing":
      addTimelineItem({
        agent: "Self-Healing Watcher",
        title: "⚡ Self-Healing Recovery Event",
        text: data.message || "Routes API degraded fallback engaged gracefully.",
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

  const avatar = sender === "user" ? "YOU" : "ADK";
  // Simple markdown conversion for bolding
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
  content.innerHTML = `<div class="loading-spinner">Running diagnostic probe across Gemini, Routes API, Store, and MCP...</div>`;

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
            <span class="health-title">Gemini API: ${diag.gemini.status}</span>
            <span class="health-sub">Model: ${diag.gemini.model || 'gemini-3.6-flash'} | Response: "${diag.gemini.response}" | Masked Key: ...${diag.gemini.masked_key || ''}</span>
          </div>
        </div>

        <div class="health-item">
          <span class="health-icon ${diag.routes.status === 'PASS' ? 'health-pass' : 'health-warn'}">
            ${diag.routes.status === 'PASS' ? '✓' : '⚡'}
          </span>
          <div class="health-info">
            <span class="health-title">Routes API: ${diag.routes.status} (${diag.routes.mode})</span>
            <span class="health-sub">${diag.routes.details || 'Routes computation operational.'}</span>
          </div>
        </div>

        <div class="health-item">
          <span class="health-icon health-pass">✓</span>
          <div class="health-info">
            <span class="health-title">Persistence Backend: ${diag.store.status}</span>
            <span class="health-sub">Mode: ${diag.store.backend} (${diag.store.file})</span>
          </div>
        </div>

        <div class="health-item">
          <span class="health-icon health-pass">✓</span>
          <div class="health-info">
            <span class="health-title">MCP Stdio Server: ${diag.mcp.status}</span>
            <span class="health-sub">Protocol: ${diag.mcp.protocol} | Tools: ${diag.mcp.tools.join(', ')}</span>
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
