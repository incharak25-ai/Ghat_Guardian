/**
 * GHAT-GUARDIAN panels.js
 * WebSocket connection + all 7 panel update logic + demo simulation.
 * Requires map.js to be loaded first.
 */

// ── State ─────────────────────────────────────────────────────────────────
const vehicles     = {};   // vehicle_id → latest payload
const v2vLog       = [];   // V2V alert history
let   rescueUnits  = [];   // loaded from backend/Overpass
let   activeSOS    = null; // current SOS payload
let   sosEtaTimer  = null;
let   demoTick     = 0;
let   wsConnected  = false;

// ── WebSocket ─────────────────────────────────────────────────────────────
function connectWebSocket() {
  const wsUrl = window.WS_URL || 'ws://localhost:8000/ws/telemetry/';
  let   ws;

  try {
    ws = new WebSocket(wsUrl);
  } catch {
    startDemoSimulation();
    return;
  }

  ws.onopen = () => {
    wsConnected = true;
    document.getElementById('ws-status').textContent = 'LIVE';
    document.getElementById('ws-status').style.color = '#1D9E75';
  };

  ws.onmessage = (e) => {
    try {
      const msg = JSON.parse(e.data);
      handleWSMessage(msg);
    } catch {}
  };

  ws.onclose = () => {
    wsConnected = false;
    document.getElementById('ws-status').textContent = 'DEMO';
    document.getElementById('ws-status').style.color = '#EF9F27';
    // Fall back to demo after 2s
    setTimeout(startDemoSimulation, 2000);
  };

  ws.onerror = () => {
    ws.close();
  };
}

function handleWSMessage(msg) {
  switch (msg.type) {
    case 'snapshot':
      msg.payload.vehicles?.forEach(v => processTelementry(v));
      break;
    case 'telemetry':
      processTelementry(msg.payload);
      break;
    case 'sos':
      handleSOS(msg.payload);
      break;
    case 'v2v':
      handleV2V(msg.payload);
      break;
  }
}

// ── Process telemetry payload ─────────────────────────────────────────────
function processTelementry(p) {
  vehicles[p.vehicle_id] = p;

  // Update map marker
  if (window.updateVehicleMarker) window.updateVehicleMarker(p);

  // Panel 02 — vehicle status table
  updateVehicleTable();

  // Panel 03 — AI risk (show highest risk vehicle)
  updateRiskPanel();

  // Panel 04 — fog & visibility
  updateFogPanel();

  // Panel 01 status bar
  updateStatusBar();

  // If SOS flag in telemetry
  if (p.sos_active && !activeSOS) {
    handleSOS({
      sos_id:       'auto',
      vehicle_id:   p.vehicle_id,
      lat:          p.lat,
      lng:          p.lng,
      trigger:      'AUTO_IMU',
      nearest_unit: rescueUnits[0]?.name || 'Nearest Unit',
      eta_minutes:  12,
      triggered_at: p.timestamp,
    });
  }

  // V2V from telemetry
  if (p.v2v_alert) {
    handleV2V({
      from_vehicle: p.vehicle_id,
      alert:        p.v2v_alert,
      mode:         p.v2v_mode || 'SERVER_SIMULATION',
      timestamp:    p.timestamp,
    });
  }
}

// ── Panel 01: Status bar ──────────────────────────────────────────────────
function updateStatusBar() {
  const vList  = Object.values(vehicles);
  const count  = vList.length;
  const alerts = vList.filter(v => v.risk_level === 'CRITICAL' || v.sos_active).length;
  const avgSpd = count ? (vList.reduce((s,v) => s + (v.speed||0), 0) / count).toFixed(0) : 0;

  setEl('stat-vehicles',  count);
  setEl('stat-alerts',    alerts);
  setEl('stat-speed',     avgSpd);
  setEl('stat-latency',   wsConnected ? '~45ms' : 'DEMO');
}

// ── Panel 02: Vehicle status table ────────────────────────────────────────
function updateVehicleTable() {
  const tbody = document.getElementById('vehicle-tbody');
  if (!tbody) return;
  tbody.innerHTML = '';

  Object.values(vehicles).forEach(v => {
    const tr = document.createElement('tr');
    const ts = v.timestamp ? new Date(v.timestamp).toLocaleTimeString('en-IN',{hour12:false}) : '--';
    tr.innerHTML = `
      <td>${v.vehicle_id}</td>
      <td>${(v.speed||0).toFixed(0)}</td>
      <td><span class="risk-badge risk-${v.risk_level}">${v.risk_level}</span></td>
      <td>${v.fog_visibility != null ? v.fog_visibility.toFixed(0)+'%' : '--'}</td>
      <td style="font-size:9px;color:var(--text-secondary)">${ts}</td>
    `;
    tbody.appendChild(tr);
  });
}

// ── Panel 03: AI risk panel ───────────────────────────────────────────────
const RISK_ORDER = ['LOW','MEDIUM','HIGH','CRITICAL'];

function updateRiskPanel() {
  const vList = Object.values(vehicles);
  if (!vList.length) return;

  // Show highest risk vehicle
  const top = vList.reduce((a,b) =>
    RISK_ORDER.indexOf(b.risk_level) > RISK_ORDER.indexOf(a.risk_level) ? b : a
  );

  const color   = window.RISK_COLORS[top.risk_level] || window.RISK_COLORS.LOW;
  const bigEl   = document.getElementById('risk-level-big');
  const warnEl  = document.getElementById('risk-warning');
  const ttcEl   = document.getElementById('ttc-display');
  const vehEl   = document.getElementById('risk-vehicle');

  if (bigEl)  { bigEl.textContent = top.risk_level; bigEl.style.color = color; }
  if (warnEl)   warnEl.textContent = top.warning || '';
  if (vehEl)    vehEl.textContent  = top.vehicle_id;

  if (ttcEl) {
    if (top.ttc_seconds && top.ttc_seconds < 30) {
      ttcEl.textContent = `TTC: ${top.ttc_seconds.toFixed(1)}s`;
      ttcEl.classList.add('visible');
    } else {
      ttcEl.classList.remove('visible');
    }
  }
}

// ── Panel 04: Fog & visibility ────────────────────────────────────────────
function updateFogPanel() {
  const container = document.getElementById('fog-container');
  if (!container) return;
  container.innerHTML = '';

  Object.values(vehicles).forEach(v => {
    const vis  = v.fog_visibility ?? 100;
    const lux  = v.ambient_light  ?? 0;
    const temp = v.temperature     ?? '--';
    const hum  = v.humidity        ?? '--';

    const div = document.createElement('div');
    div.className = 'fog-vehicle';
    div.innerHTML = `
      <div class="fog-label">
        <span>${v.vehicle_id}</span>
        <span style="color:${vis < 40 ? 'var(--critical)' : vis < 70 ? 'var(--medium)' : 'var(--low)'}">
          ${vis.toFixed(0)}% visibility
        </span>
      </div>
      <div class="fog-bar-bg">
        <div class="fog-bar-fill" style="width:${vis}%"></div>
      </div>
      <div class="fog-readings">
        <div class="fog-reading">LUX <span>${lux.toFixed(0)}</span></div>
        <div class="fog-reading">TEMP <span>${temp}°C</span></div>
        <div class="fog-reading">HUM <span>${hum}%</span></div>
      </div>
    `;
    container.appendChild(div);
  });
}

// ── Panel 05: SOS alert ───────────────────────────────────────────────────
function handleSOS(payload) {
  activeSOS = payload;

  const panel      = document.getElementById('sos-panel');
  const inactive   = document.getElementById('sos-inactive');
  const activeDiv  = document.getElementById('sos-active');

  if (panel)    panel.classList.add('active');
  if (inactive) inactive.style.display = 'none';
  if (activeDiv) {
    activeDiv.style.display = 'block';
    setEl('sos-vehicle-id', payload.vehicle_id);
    setEl('sos-coords',     `${payload.lat?.toFixed(5)}, ${payload.lng?.toFixed(5)}`);
    setEl('sos-trigger',    payload.trigger === 'AUTO_IMU' ? '🤖 AUTO — IMU Crash Detected' : '🔴 MANUAL — SOS Button');
    setEl('sos-unit',       payload.nearest_unit || 'Locating...');
  }

  // Show SOS marker on map
  if (window.showSOSMarker) window.showSOSMarker(payload.lat, payload.lng, payload.vehicle_id);

  // Play emergency siren — sounds on dashboard immediately
  startSiren();

  // ETA countdown
  let etaSec = (payload.eta_minutes || 10) * 60;
  if (sosEtaTimer) clearInterval(sosEtaTimer);
  sosEtaTimer = setInterval(() => {
    etaSec = Math.max(0, etaSec - 1);
    const min = Math.floor(etaSec / 60);
    const sec = etaSec % 60;
    setEl('sos-eta', `${min}:${sec.toString().padStart(2,'0')}`);
    if (etaSec === 0) clearInterval(sosEtaTimer);
  }, 1000);
}

// ── Panel 06: V2V message log ─────────────────────────────────────────────
function handleV2V(payload) {
  v2vLog.unshift({
    time:    new Date().toLocaleTimeString('en-IN', { hour12: false }),
    vehicle: payload.from_vehicle,
    msg:     payload.alert,
  });

  if (v2vLog.length > 20) v2vLog.pop();

  const log = document.getElementById('v2v-log');
  if (!log) return;
  log.innerHTML = '';

  v2vLog.forEach(entry => {
    const div = document.createElement('div');
    div.className = 'v2v-entry';
    div.innerHTML = `
      <div class="v2v-time">${entry.time} · ${entry.vehicle}</div>
      <div class="v2v-msg">${entry.msg}</div>
    `;
    log.appendChild(div);
  });

  setEl('v2v-count', v2vLog.length);
}

// ── Panel 07: Rescue units ────────────────────────────────────────────────
window.addEventListener('rescue-units-loaded', (e) => {
  rescueUnits = e.detail;
  renderRescueUnits();
});

function renderRescueUnits(sosLat, sosLng) {
  const container = document.getElementById('rescue-container');
  if (!container) return;
  container.innerHTML = '';

  rescueUnits.slice(0, 6).forEach(unit => {
    let etaText = '--';
    if (sosLat && sosLng && unit.latitude && unit.longitude) {
      const dist = haversine(sosLat, sosLng, unit.latitude, unit.longitude);
      const eta  = Math.round(dist / (unit.avg_speed_kmh || 40) * 60 * (1/0.6));
      etaText    = `${eta} min`;
    }

    const icon = unit.icon || '🚑';
    const div  = document.createElement('div');
    div.className = 'rescue-unit';
    div.innerHTML = `
      <div class="rescue-icon">${icon}</div>
      <div class="rescue-name">${unit.name}</div>
      <div class="rescue-eta">${etaText}</div>
    `;
    container.appendChild(div);
  });
}

function haversine(lat1, lng1, lat2, lng2) {
  const R  = 6371;
  const dL = (lat2-lat1)*Math.PI/180;
  const dN = (lng2-lng1)*Math.PI/180;
  const a  = Math.sin(dL/2)**2 + Math.cos(lat1*Math.PI/180)*Math.cos(lat2*Math.PI/180)*Math.sin(dN/2)**2;
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
}

// ── Demo simulation (when backend offline) ────────────────────────────────
const DEMO_ROUTE   = window.getRoutePoints ? window.getRoutePoints() : [];
const DEMO_VEHICLES = [
  { id:'GG-001', pos:0,   speed:40, offset:0   },
  { id:'GG-002', pos:100, speed:36, offset:100 },
  { id:'GG-003', pos:220, speed:30, offset:220 },
];

let demoRunning = false;

function startDemoSimulation() {
  if (demoRunning) return;
  demoRunning = true;

  setInterval(() => {
    demoTick++;
    const route = window.getRoutePoints ? window.getRoutePoints() : NH75_FALLBACK;

    DEMO_VEHICLES.forEach(v => {
      v.pos = (v.pos + 1) % route.length;
      const curr = route[v.pos];
      const next = route[(v.pos + 1) % route.length];
      const heading = calcHeading(curr, next);

      const progress    = v.pos / route.length;
      const inGhat      = progress > .6 && progress < .85;
      const fogVis      = inGhat ? 25 + Math.random()*30 : 80 + Math.random()*15;
      const riskLevel   = fogVis < 40 ? 'HIGH' : fogVis < 60 ? 'MEDIUM' : 'LOW';
      const twoVehiclesClose = Math.abs(DEMO_VEHICLES[0].pos - DEMO_VEHICLES[1].pos) < 15;
      const finalRisk   = (v.id === 'GG-001' && twoVehiclesClose) ? 'CRITICAL' : riskLevel;

      processTelementry({
        vehicle_id:    v.id,
        lat:           curr[0] + (Math.random()-.5)*.0001,
        lng:           curr[1] + (Math.random()-.5)*.0001,
        speed:         v.speed + (Math.random()-0.5)*4,
        heading,
        risk_level:    finalRisk,
        warning:       finalRisk === 'CRITICAL' ? 'COLLISION IMMINENT — BRAKE NOW' :
                       inGhat ? 'Low visibility — Reduce speed' : '',
        fog_visibility: fogVis,
        temperature:   inGhat ? 17 + Math.random()*4 : 24 + Math.random()*4,
        humidity:      inGhat ? 88 + Math.random()*8 : 65 + Math.random()*10,
        ambient_light: inGhat ? 150 + Math.random()*100 : 500 + Math.random()*200,
        sos_active:    false,
        v2v_alert:     (finalRisk === 'CRITICAL')
                         ? `[SERVER V2V] ${v.id === 'GG-001' ? 'GG-002' : 'GG-001'} approaching — CRITICAL`
                         : null,
        ttc_seconds:   finalRisk === 'CRITICAL' ? 4 + Math.random()*3 : null,
        nearby_count:  finalRisk === 'CRITICAL' ? 1 : 0,
        in_black_spot: inGhat ? 'Shiradi Ghat — Gundya Blind Curve Cluster' : null,
        led_status:    finalRisk === 'CRITICAL' ? 'RED' : inGhat ? 'YELLOW' : 'GREEN',
        timestamp:     new Date().toISOString(),
      });
    });

    // Auto SOS at tick 100 for demo
    if (demoTick === 100 && !activeSOS) {
      const route = window.getRoutePoints ? window.getRoutePoints() : [];
      const pos   = route[Math.floor(route.length * .72)] || [12.75, 75.68];
      handleSOS({
        sos_id:       'demo-1',
        vehicle_id:   'GG-003',
        lat:          pos[0],
        lng:          pos[1],
        trigger:      'AUTO_IMU',
        nearest_unit: 'Sakleshpur Fire & Rescue Station',
        eta_minutes:  8,
        triggered_at: new Date().toISOString(),
      });
    }

    // Demo V2V at tick 50
    if (demoTick === 50) {
      handleV2V({
        from_vehicle: 'GG-001',
        alert:        '[SERVER V2V] GG-002 detected 320m ahead — Monitor speed',
        mode:         'SERVER_SIMULATION',
        timestamp:    new Date().toISOString(),
      });
    }

  }, 1000);
}

function calcHeading(curr, next) {
  const dLng = (next[1]-curr[1]) * Math.PI/180;
  const lat1 = curr[0]*Math.PI/180, lat2 = next[0]*Math.PI/180;
  const x = Math.sin(dLng)*Math.cos(lat2);
  const y = Math.cos(lat1)*Math.sin(lat2) - Math.sin(lat1)*Math.cos(lat2)*Math.cos(dLng);
  return ((Math.atan2(x,y)*180/Math.PI) + 360) % 360;
}

const NH75_FALLBACK = [
  [12.9716,77.5946],[13.0979,77.3952],[13.0210,77.0253],
  [13.0050,76.1000],[12.9420,75.7850],[12.7500,75.6800],[12.9579,75.3750]
];

// ── Route change → update rescue units ────────────────────────────────────
window.addEventListener('route-changed', (e) => {
  const pts = e.detail.points;
  const mid = pts[Math.floor(pts.length/2)];
  if (mid && window.loadRescueUnits) window.loadRescueUnits(mid[0], mid[1], 60);
});

// ── Helpers ───────────────────────────────────────────────────────────────
function setEl(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val;
}

// ── Boot ──────────────────────────────────────────────────────────────────
window.addEventListener('load', () => {
  connectWebSocket();
  // Also start demo immediately for visual feedback
  setTimeout(() => { if (!wsConnected) startDemoSimulation(); }, 1500);
});

// ── Emergency Siren (Web Audio API) ──────────────────────────────────────
// Generates ambulance-style wailing siren — no MP3 file needed.
// Sweeps 800Hz → 1200Hz → 800Hz like Indian civil defence emergency drill.

let audioCtx     = null;
let sirenRunning = false;
let sirenOsc     = null;

function unlockAudio() {
  if (!audioCtx) {
    audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    const buf = audioCtx.createBuffer(1, 1, 22050);
    const src = audioCtx.createBufferSource();
    src.buffer = buf;
    src.connect(audioCtx.destination);
    src.start(0);
  }
}

function startSiren() {
  if (sirenRunning || !audioCtx) return;
  sirenRunning = true;

  sirenOsc = audioCtx.createOscillator();
  const gain = audioCtx.createGain();
  sirenOsc.connect(gain);
  gain.connect(audioCtx.destination);
  sirenOsc.type      = 'sawtooth';
  gain.gain.value    = 0.7;

  // Wail: 800Hz → 1200Hz → 800Hz every second (Indian ambulance pattern)
  const now = audioCtx.currentTime;
  for (let i = 0; i < 30; i++) {
    const t = now + i;
    sirenOsc.frequency.setValueAtTime(800,  t);
    sirenOsc.frequency.linearRampToValueAtTime(1200, t + 0.5);
    sirenOsc.frequency.linearRampToValueAtTime(800,  t + 1.0);
  }
  sirenOsc.start(now);
  sirenOsc.stop(now + 30);
  sirenOsc.onended = () => {
    sirenRunning = false;
    if (activeSOS) startSiren(); // Loop while SOS is active
  };
}

function stopSiren() {
  sirenRunning = false;
  try { if (sirenOsc) sirenOsc.stop(); } catch {}
  sirenOsc = null;
}

// Start monitoring button — unlocks Web Audio on first click
document.addEventListener('DOMContentLoaded', () => {
  const btn = document.createElement('button');
  btn.id = 'monitor-btn';
  btn.textContent = '▶ START MONITORING';
  btn.style.cssText = [
    'position:fixed','bottom:16px','right:16px','z-index:9998',
    "font-family:'Orbitron',monospace",'font-size:11px','font-weight:700',
    'padding:10px 18px','border-radius:4px','cursor:pointer','letter-spacing:3px',
    'background:transparent','color:#00b4d8','border:1px solid #00b4d8',
  ].join(';');
  btn.onclick = () => {
    unlockAudio();
    btn.textContent       = '● MONITORING ACTIVE';
    btn.style.color       = '#1D9E75';
    btn.style.borderColor = '#1D9E75';
    btn.style.cursor      = 'default';
    btn.onclick           = null;
  };
  document.body.appendChild(btn);
});

// Hook siren into SOS handler
const _origHandleSOS = handleSOS;
// Extend handleSOS to also play siren
const _handleSOSBase = handleSOS;
window._handleSOSWithSiren = function(payload) {
  _handleSOSBase(payload);
  startSiren();
};
