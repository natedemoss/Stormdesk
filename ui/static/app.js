// StormDesk console. Plain JS, no libraries, no network beyond this local server.
"use strict";

const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const S = {
  state: null, selected: null, trace: [], draft: null, final: "", stats: null,
  running: false, known: new Set(), queueHTML: "", roadsCache: new Map(), frame: null,
  animateRoute: false, tab: "agent", sandbox: null, redteam: null,
  userFrame: null, view: null,  // userFrame: where the dispatcher panned/zoomed to; null = fit automatically
};

const CATS = {
  requests_or_urgent_needs: "Urgent need", injured_or_dead_people: "Injured or dead",
  missing_or_found_people: "Missing person", displaced_people_and_evacuations: "Displaced, evacuation",
  infrastructure_and_utility_damage: "Infrastructure damage", caution_and_advice: "Caution, advice",
  rescue_volunteering_or_donation_effort: "Volunteers, donations", other_relevant_information: "Other",
  sympathy_and_support: "Sympathy", not_humanitarian: "Not humanitarian", dont_know_cant_judge: "Unclear",
};
// What each unit is, in plain words, for dispatchers and judges who don't know the jargon.
const UNIT_DESC = {
  swift_water_rescue: "Boat and rope team for people trapped in moving or rising water",
  high_water_vehicle: "Tall truck that drives through standing floodwater to move people out",
  ems: "Ambulance and paramedics for injuries and medical emergencies",
  fire: "Fire engine for fires, gas leaks and live power lines",
  supply_drop: "Food, water or medicine delivered to people who are cut off but safe",
  welfare_check: "Someone goes to check on a person nobody can reach",
  road_crew: "Crew that clears trees and debris and closes damaged roads",
};
const UNITS = {
  swift_water_rescue: "Swift water rescue", ems: "EMS", fire: "Fire", high_water_vehicle: "High water vehicle",
  supply_drop: "Supply drop", welfare_check: "Welfare check", road_crew: "Road crew",
};

// ------------------------------------------------------------------ helpers
async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}
function toast(msg, ms = 2800) {
  const t = $("#toast"); t.textContent = msg; t.hidden = false;
  clearTimeout(toast._t); toast._t = setTimeout(() => (t.hidden = true), ms);
}
function age(iso) {
  if (!iso) return null;
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return "now";
  if (s < 3600) return `${Math.floor(s / 60)} min`;
  if (s < 86400) return `${Math.floor(s / 3600)} h`;
  return `${Math.floor(s / 86400)} d`;
}
const hhmm = (iso) => (iso ? new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false }) : "");
const lastOk = (trace, tool) => {
  for (let i = trace.length - 1; i >= 0; i--) if (trace[i].tool === tool && !("error" in trace[i].result) && !trace[i].result._fault) return trace[i].result;
  return null;
};
const forModel = (r) => Object.fromEntries(Object.entries(r).filter(([k]) => !k.startsWith("_")));
const tidy = (name) => String(name || "").replace(" (SAMPLE)", "").replace(" (potential)", "");

function summarize(t) {
  const r = t.result, a = t.args;
  if ("error" in r) return r.error;
  if (r._malformed) return {
    geocode_location: "Says found, but returned no coordinates. Unusable, so the agent must call again.",
    plan_route: "Says ok, but returned no distance or route. Unusable, so the agent must call again.",
    find_shelters: "Returned an HTML error page instead of a shelter list. Unusable, so the agent must call again.",
  }[t.tool] || "Unusable result.";
  switch (t.tool) {
    case "geocode_location": return r.found ? `${r.name}, ${r.county}. Confidence ${r.confidence}.` : "No match in the local gazetteer. Needs a landmark or road name.";
    case "get_road_closures": {
      const unv = r.closures.filter((c) => !c.verified).length;
      const near = r.closures[0];
      return `${r.closures.length} within range${unv ? `, ${unv} unverified` : ""}.` + (near ? ` Nearest: ${near.road}, ${near.distance_km} km.` : "");
    }
    case "report_closure": return `Logged ${a.road || "closure"} as unverified.`;
    case "get_weather_alerts": return r.alerts.length ? r.alerts.map((x) => x.event).join(", ") + "." : "No active alerts for the county.";
    case "find_shelters": {
      if (!r.shelters.length) return "No shelter matches.";
      const s = r.shelters[0];
      return `${tidy(s.name)}, ${s.distance_km} km` + (s.space_left == null ? ", capacity unknown." : `, ${s.space_left} spaces.`);
    }
    case "plan_route":
      if (!r.ok) return r.reason || "No route.";
      if (r.mode === "straight_line_fallback") return `${r.distance_km} km straight line. No road graph cached.`;
      return `${r.distance_km} km` + (r.rerouted ? ", detours around a closure." : ".");
    case "draft_dispatch": return `Draft #${r.draft_id}: ${UNITS[a.unit_type] || a.unit_type}. Waiting for a dispatcher.`;
  }
  return "";
}

// ------------------------------------------------------------------ top bar
function renderStatus() {
  const st = S.state, mock = st.mode === "mock";
  const item = (k, v, cls = "") => `<div><dt>${k}</dt><dd class="${cls}">${v}</dd></div>`;
  const fresh = (k, ts) => {
    const a = age(ts);
    const hours = ts ? (Date.now() - new Date(ts).getTime()) / 3600e3 : Infinity;
    return item(k, a ? `${a} old` : "not synced", hours < 6 ? "" : "warn");
  };
  // the oldest of the synced feeds stands for all of them
  const feeds = [st.sync.ncdot, st.sync.noaa, st.sync.shelters];
  const oldest = feeds.includes(null) || feeds.includes(undefined) ? null
    : feeds.reduce((a, b) => (new Date(a) < new Date(b) ? a : b));
  const fd = fresh("Data", oldest);
  $("#status").innerHTML =
    item("Agent", mock ? "Mock, scripted" : "Nemotron 3.5 Lightning", mock ? "warn" : "") +
    item("Triage", mock ? "Mock, rules" : "Qwen3-1.7B LoRA", mock ? "warn" : "") +
    fd.replace("<dd", `<dd title="NCDOT ${age(st.sync.ncdot) || "never"} · NWS ${age(st.sync.noaa) || "never"} · shelters ${age(st.sync.shelters) || "never"}"`);
  const counties = st.counties || [];
  $("#county").textContent = counties.length > 1 ? `Western NC EOC · ${counties.length} counties` : `${counties[0] || "County"} County EOC`;
  $("#county").title = counties.join(", ");
  renderStorm();
}

// The scenario band: the demo replays the first days after a hurricane. The counts are live,
// from the cached data the agent's tools read.
const SCENARIO = "Hurricane scenario · Day 2";
function renderStorm() {
  const st = S.state;
  const names = (st.counties || []).map((c) => c.toLowerCase());
  const alerts = (st.alerts || []).filter((a) => names.some((n) => (a.area || "").toLowerCase().includes(n)));
  const events = [...new Set(alerts.map((a) => a.event))];
  const closed = st.closures.length, reported = st.closures.filter((c) => !c.verified).length;
  const space = st.shelters.filter((s) => s.capacity != null && s.capacity - (s.occupancy || 0) > 0).length;
  const offline = S.sandbox?.in_sandbox;
  const part = (b, t) => `<span><b>${b}</b> ${t}</span>`;
  $("#storm").innerHTML = `<span class="storm-tag">${SCENARIO}</span>` +
    part(offline ? "Offline" : "No internet needed", offline ? "sandbox, local models only" : "every tool reads the local cache") +
    part(closed, `road closures${reported ? ` (${reported} reported by the public)` : ""}`) +
    (alerts.length ? part(alerts.length, `NWS alerts: ${esc(events.slice(0, 2).join(", "))}`)
      : `<span>No NWS alerts in the cached feed</span>`) +
    part(space, `shelters with space of ${st.shelters.length} on file`);
}

function updateDemoOn() {  // what the Demo menu has switched away from normal, shown on its button
  const on = [];
  if (!$("#guard").checked) on.push("guard off");
  if ($("#faults").checked) on.push("faults");
  if ($("#outage").value) on.push(`${$("#outage").selectedOptions[0].textContent} down`);
  $("#demo-on").textContent = on.join(" · ");
  $("#demo-on").hidden = !on.length;
}
["guard", "faults", "outage"].forEach((id) => $("#" + id).addEventListener("change", updateDemoOn));
updateDemoOn();
document.addEventListener("click", (e) => {  // close the Demo menu on a click outside it
  const m = $("#demo-menu"); if (m.open && !m.contains(e.target)) m.open = false;
});
setInterval(() => { $("#clock").textContent = new Date().toLocaleTimeString([], { hour12: false }); }, 1000);

// ------------------------------------------------------------------ queue
function renderQueue() {
  const inc = S.state.incidents.slice().sort((a, b) =>
    (a.status === "new" ? 0 : 1) - (b.status === "new" ? 0 : 1) || b.urgency - a.urgency || b.id - a.id);
  const open = inc.filter((i) => i.status === "new" || i.status === "drafted");
  $("#queue-meta").textContent = `${open.length} open · ${S.state.filtered_out} filtered`;
  const first = S.known.size === 0;
  const html = inc.map((i) => {
    const closed = i.status === "approved" || i.status === "rejected";
    const arrived = !first && !S.known.has(i.id);
    return `<li class="row u${i.urgency}${i.id === S.selected ? " sel" : ""}${closed ? " closed" : ""}${arrived ? " arrived" : ""}" data-id="${i.id}">
      <span class="urg">${i.urgency}</span>
      <div>
        <div class="row-top"><span class="row-cat">${esc(CATS[i.category] || i.category)}</span><span>${hhmm(i.created_at)}</span></div>
        <div class="row-text">${esc(i.raw_text)}</div>
        <div class="row-foot"><span>#${i.id}</span>${i.channel === "nws-helene" ? `<span class="real" title="A real report from the National Weather Service storm log during Hurricane Helene">Real · NWS Helene log</span>` : `<span>${esc(i.channel)}</span>`}<span class="st-${i.status}">${i.status}</span>${i.flag ? `<span class="flag">${esc(i.flag)}</span>` : ""}</div>
      </div></li>`;
  }).join("") || `<li class="empty">No reports yet.</li>`;
  if (html !== S.queueHTML) { $("#rows").innerHTML = html; S.queueHTML = html; }
  if (!first && inc.some((i) => !S.known.has(i.id))) $("#rows").scrollTo({ top: 0, behavior: "smooth" });
  inc.forEach((i) => S.known.add(i.id));
}
$("#rows").addEventListener("click", (e) => {
  const r = e.target.closest(".row"); if (r && !S.running) select(+r.dataset.id);
});

function renderIncident() {
  const box = $("#incident");
  const i = S.state?.incidents.find((x) => x.id === S.selected);
  if (!i) { box.hidden = true; return; }
  box.hidden = false;
  box.className = `incident u${i.urgency}`;
  const label = S.running ? "Running" : S.trace.length ? "Run again" : "Run agent";
  box.innerHTML = `<span class="urg">${i.urgency}</span>
    <div><div class="inc-meta"><b>#${i.id} ${esc(CATS[i.category] || i.category)}</b> · ${i.channel === "nws-helene" ? `<span class="real">Real · NWS Helene log</span>` : esc(i.channel)} · received ${hhmm(i.created_at)}${i.flag ? ` · <span class="flag" title="A safety rule raised this report; the model ranked it lower">${esc(i.flag)}</span>` : ""}</div>
      <div class="inc-text">${esc(i.raw_text)}</div></div>
    <button class="btn signal" id="run" ${S.running ? "disabled" : ""}>${label}</button>`;
  $("#run").onclick = runAgent;
}

// ------------------------------------------------------------------ map
function mapSize() { const r = $("#map").getBoundingClientRect(); return { W: r.width, H: r.height }; }
function fitFrame(points) {
  const lons = points.map((p) => p[0]), lats = points.map((p) => p[1]);
  const x0 = Math.min(...lons), x1 = Math.max(...lons), y0 = Math.min(...lats), y1 = Math.max(...lats);
  const m = Math.max(x1 - x0, y1 - y0, 0.02) * 0.1 + 0.004;
  return { x0: x0 - m, x1: x1 + m, y0: y0 - m, y1: y1 + m };
}
function projector(f, hasCard, fill = false) {
  const { W, H } = mapSize();
  // an automatic fit leaves room for the route card and legend; a panned/zoomed view fills the box
  const [padL, padR, padT, padB] = fill ? [0, 0, 0, 0] : [40, hasCard ? 310 : 40, 56, 70];
  const k = Math.cos(((f.y0 + f.y1) / 2) * Math.PI / 180);
  // a narrow window can leave less room than the padding; keep the drawable area positive
  const aw = Math.max(W - padL - padR, 120), ah = Math.max(H - padT - padB, 120);
  const s = Math.min(aw / ((f.x1 - f.x0) * k), ah / (f.y1 - f.y0));
  const ox = padL + (aw - (f.x1 - f.x0) * k * s) / 2;
  const oy = padT + (ah - (f.y1 - f.y0) * s) / 2;
  const P = (lon, lat) => [(lon - f.x0) * k * s + ox, (f.y1 - lat) * s + oy];
  const inv = (x, y) => [(x - ox) / (k * s) + f.x0, f.y1 - (y - oy) / s];
  const [vx0, vy1] = inv(0, 0), [vx1, vy0] = inv(W, H);
  return { P, W, H, pxPerM: s / 110540, view: { x0: vx0, x1: vx1, y0: vy0, y1: vy1 } };
}
// Roads come for a box padded half a view on every side and snapped to a grid, so panning
// within that margin reuses the same request instead of fetching (and blanking) again.
function roadBox(v) {
  const span = Math.max(v.x1 - v.x0, v.y1 - v.y0);
  const step = Math.pow(2, Math.ceil(Math.log2(span / 2)));  // grid cell about half the view
  const snap = (n, up) => (up ? Math.ceil(n / step) : Math.floor(n / step)) * step;
  // the view width decides which road classes show; quantize it so small zooms share a request
  const detail = span < 0.3 ? 0.1 : 1;
  return { x0: snap(v.x0 - span / 2), y0: snap(v.y0 - span / 2), x1: snap(v.x1 + span / 2, true),
           y1: snap(v.y1 + span / 2, true), detail };
}
async function roadsFor(v) {
  const b = roadBox(v);
  const key = [b.x0, b.y0, b.x1, b.y1, b.detail].join(",");
  if (!S.roadsCache.has(key)) {
    S.roadsCache.set(key, api(`/api/roads?minlon=${b.x0}&minlat=${b.y0}&maxlon=${b.x1}&maxlat=${b.y1}&view=${b.detail}`)
      .catch(() => ({ segments: [] })));
  }
  return S.roadsCache.get(key);
}
function drawRoads(P, roads) {  // casings first, then fills, so crossings read like a printed road map
  const d = ["", "", ""];
  for (const [a, b, c, e, cls] of roads.segments) {
    const [x1, y1] = P(a, b), [x2, y2] = P(c, e);
    d[cls ?? 2] += `M${x1.toFixed(1)} ${y1.toFixed(1)}L${x2.toFixed(1)} ${y2.toFixed(1)}`;
  }
  const g = $("#roads");
  if (g) g.innerHTML = `<path class="r2c" d="${d[2]}"/><path class="r1c" d="${d[1]}"/><path class="r0c" d="${d[0]}"/>`
    + `<path class="r2" d="${d[2]}"/><path class="r1" d="${d[1]}"/><path class="r0" d="${d[0]}"/>`;
}
const pathD = (P, coords) => "M" + coords.map((c) => P(c[0], c[1]).map((n) => n.toFixed(1)).join(" ")).join("L");

function scaleBar(pxPerM, x, y) {
  const targets = [500, 1000, 2000, 5000, 10000, 20000, 50000];
  const m = targets.find((t) => t * pxPerM >= 70) || 50000;
  const w = m * pxPerM, h = 5;
  const label = m >= 1000 ? `${m / 1000} km` : `${m} m`;
  return `<g class="scale"><rect x="${x}" y="${y}" width="${w / 2}" height="${h}"/><rect class="w" x="${x + w / 2}" y="${y}" width="${w / 2}" height="${h}"/>
    <text x="${x}" y="${y - 5}">0</text><text x="${x + w}" y="${y - 5}" text-anchor="end">${label}</text></g>`;
}
const northArrow = (x, y) => `<g class="north"><path d="M${x} ${y - 14}L${x + 6} ${y + 4}L${x} ${y}L${x - 6} ${y + 4}Z"/><text x="${x}" y="${y + 17}" text-anchor="middle">N</text></g>`;

// Greedy label placement: try spots around each marker, take the first that collides with
// nothing; must-have labels take the least-bad spot, minor ones are dropped instead.
function placeLabels(labels, obstacles, W, H) {
  const hit = (a, b) => a.x0 < b.x1 && a.x1 > b.x0 && a.y0 < b.y1 && a.y1 > b.y0;
  const placed = [], out = [];
  for (const l of labels.slice().sort((a, b) => a.prio - b.prio)) {
    const w = l.text.length * l.size * 0.58, h = l.size * 1.25, g = l.r + 5, base = l.size * 0.36;
    const spots = [
      ["start", l.x + g, l.y + base], ["end", l.x - g, l.y + base],
      ["middle", l.x, l.y - g - 2], ["middle", l.x, l.y + g + l.size],
      ["start", l.x + g, l.y - g - 2], ["start", l.x + g, l.y + g + l.size],
      ["end", l.x - g, l.y - g - 2], ["end", l.x - g, l.y + g + l.size],
    ];
    let best = null;
    for (const [anchor, tx, ty] of spots) {
      const x0 = anchor === "start" ? tx : anchor === "end" ? tx - w : tx - w / 2;
      const box = { x0, x1: x0 + w, y0: ty - h * 0.8, y1: ty + h * 0.2 };
      let score = (box.x0 < 0 || box.x1 > W || box.y0 < 0 || box.y1 > H) ? 5 : 0;
      for (const o of placed) if (hit(box, o)) score += 10;
      for (const o of obstacles) if (o !== l.own && hit(box, o)) score += 3;
      if (!best || score < best.score) best = { anchor, tx, ty, box, score };
      if (score === 0) break;
    }
    if (best.score >= 10 && !l.must) continue;
    placed.push(best.box);
    out.push(`<text class="${l.cls}" x="${best.tx.toFixed(1)}" y="${best.ty.toFixed(1)}" text-anchor="${best.anchor}">${esc(l.text)}</text>`);
  }
  return out;
}

async function drawMap() {
  if (!S.state) return;
  const st = S.state, trace = S.trace;
  const inc = lastOk(trace, "geocode_location");
  const route = lastOk(trace, "plan_route");
  const shel = (lastOk(trace, "find_shelters") || {}).shelters || [];
  const path = route?._path || [], blocked = route?._blocked_path || [];
  // where the route starts: the start point geocode_location gave for the unit (a fire, ambulance
  // or police station, or the county staging point); before routing, the staging point
  let home = inc?.staging || st.staging;
  if (route?._from) {
    const [lon, lat] = route._from;
    const same = (p) => p && Math.abs(p.lon - lon) < 1e-5 && Math.abs(p.lat - lat) < 1e-5;
    home = [...Object.values(inc?.start_points || {}), inc?.staging].find(same) || { name: "Route start", lat, lon };
  }
  const fromStation = !!(st.stations || []).find((s) => Math.abs(s.lon - home.lon) < 1e-5 && Math.abs(s.lat - home.lat) < 1e-5);
  const staging = [home.lon, home.lat];

  let pts;
  if (inc && inc.found) {
    pts = [staging, [inc.lon, inc.lat], ...path, ...blocked];
    // a far shelter would shrink the route (and its detour) to a few pixels; it stays listed
    if (shel[0] && !(shel[0].distance_km > 10)) pts.push([shel[0].lon, shel[0].lat]);
  } else {
    pts = [staging, ...st.shelters.map((s) => [s.lon, s.lat]),
           ...st.closures.filter((c) => Math.abs(c.lat - home.lat) < 0.4 && Math.abs(c.lon - home.lon) < 0.4).map((c) => [c.lon, c.lat])];
  }
  const f = S.userFrame || fitFrame(pts);
  S.frame = f;
  const { P, W, H, pxPerM, view } = projector(f, !!route, !!S.userFrame);
  S.view = view;
  const svg = $("#map");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  $("#map-fit").hidden = !S.userFrame;
  const inView = (lon, lat) => lon >= view.x0 && lon <= view.x1 && lat >= view.y0 && lat <= view.y1;
  const out = [`<g id="roads"></g>`];
  // Labels are placed last, around their markers, so they never stack on each other.
  const labels = [], obstacles = [];
  const obstacle = (x, y, r) => { const o = { x0: x - r, y0: y - r, x1: x + r, y1: y + r }; obstacles.push(o); return o; };
  const label = (x, y, r, text, cls, size, prio, must = false) =>
    labels.push({ x, y, r, text, cls, size, prio, must, own: obstacle(x, y, r) });

  // closures: a thick red bar for a closed stretch, a dot for a point
  for (const c of st.closures) {
    const stretch = c.lat2 != null && c.lon2 != null;
    if (!inView(c.lon, c.lat) && !(stretch && inView(c.lon2, c.lat2))) continue;
    const [x, y] = P(c.lon, c.lat);
    const cls = c.verified ? "closure" : "closure unv";
    if (stretch) {
      const [x2, y2] = P(c.lon2, c.lat2);
      out.push(`<g class="${cls}"><path class="closed-line" d="M${x} ${y}L${x2} ${y2}"/></g>`);
    }
    const [lx, ly] = stretch ? P((c.lon + c.lon2) / 2, (c.lat + c.lat2) / 2) : [x, y];
    out.push(`<g class="${cls}"><circle class="closed-dot" cx="${lx}" cy="${ly}" r="6"/>
      <path class="closed-x" d="M${lx - 2.5} ${ly - 2.5}L${lx + 2.5} ${ly + 2.5}M${lx + 2.5} ${ly - 2.5}L${lx - 2.5} ${ly + 2.5}"/></g>`);
    label(lx, ly, 6, String(c.road).replace(" (sample)", "") + (c.verified ? "" : " (reported)"), "lbl-c", 11, 3);
  }

  if (blocked.length) out.push(`<path class="blocked" d="${pathD(P, blocked)}"/>`);
  if (path.length) {
    if (route.mode === "straight_line_fallback") {
      out.push(`<path class="straight" d="${pathD(P, path)}"/>`);
    } else {
      const anim = S.animateRoute ? " draw" : "";
      out.push(`<path class="route-glow${anim}" pathLength="1" d="${pathD(P, path)}"/><path class="route-case${anim}" pathLength="1" d="${pathD(P, path)}"/><path class="route${anim}" pathLength="1" d="${pathD(P, path)}"/>`);
      if (inc && inc.found) {  // off-road legs to the first and last road node
        out.push(`<path class="legline" d="${pathD(P, [staging, path[0]])}"/><path class="legline" d="${pathD(P, [path[path.length - 1], [inc.lon, inc.lat]])}"/>`);
      }
    }
  }

  const pick = shel[0]?.id;
  for (const s of st.shelters) {
    if (!inView(s.lon, s.lat)) continue;
    const [x, y] = P(s.lon, s.lat);
    const space = s.capacity == null ? null : s.capacity - (s.occupancy || 0);
    // potential shelters (capacity unknown) are most of the list: small and faint, and hidden
    // around an open incident unless the agent picked one, so the route stays readable
    if (space == null && s.id !== pick) {
      if (inc) continue;
      out.push(`<rect class="shelter pot faint" x="${x - 3}" y="${y - 3}" width="6" height="6"/>`);
      continue;
    }
    const cls = space == null ? " pot" : space <= 0 ? " full" : "";
    out.push(`<rect class="shelter${cls}${s.id === pick ? " pick" : ""}" x="${x - 5}" y="${y - 5}" width="10" height="10"/>`);
    const text = tidy(s.name) + (space == null ? "" : `, ${space > 0 ? space + " open" : "full"}`);
    if (s.id === pick) label(x, y, 5, text, "lbl-s", 11, 2, true);
    else if (!inc && space != null) label(x, y, 5, text, "lbl-s", 11, 4);
    else obstacle(x, y, 5);
  }
  for (const p of st.staging_points || []) {  // the other counties' staging points, unlabeled unless room
    if (p.name === home.name || !inView(p.lon, p.lat)) continue;
    const [x, y] = P(p.lon, p.lat);
    out.push(`<rect class="staging other" x="${x - 4}" y="${y - 4}" width="8" height="8"/>`);
    label(x, y, 4, p.name, "lbl-s", 11, 5);
  }
  for (const s of inc?.found ? st.stations || [] : []) {  // stations near an open incident, unlabeled
    if (!inView(s.lon, s.lat) || (s.lon === home.lon && s.lat === home.lat)) continue;
    const [x, y] = P(s.lon, s.lat);
    out.push(`<path class="station" d="M${x} ${y - 5}L${x + 5} ${y}L${x} ${y + 5}L${x - 5} ${y}Z"/>`);
    obstacle(x, y, 5);
  }
  const [sx, sy] = P(...staging);
  out.push(fromStation
    ? `<path class="station start" d="M${sx} ${sy - 8}L${sx + 8} ${sy}L${sx} ${sy + 8}L${sx - 8} ${sy}Z"/>`
    : `<rect class="staging" x="${sx - 6}" y="${sy - 6}" width="12" height="12"/>`);
  label(sx, sy, 6, home.name.replace(" (sample)", ""), "lbl-b", 12.5, 1, true);
  if (inc && inc.found) {
    const [ix, iy] = P(inc.lon, inc.lat);
    out.push(`<circle class="inc-ring" cx="${ix}" cy="${iy}" r="13"/><circle class="inc" cx="${ix}" cy="${iy}" r="7"/>`);
    label(ix, iy, 13, inc.name, "lbl-b", 12.5, 0, true);
  }
  obstacles.push({ x0: 0, y0: H - 96, x1: 680, y1: H });  // legend
  out.push(...placeLabels(labels, obstacles, W, H));
  out.push(scaleBar(pxPerM, 20, 30), northArrow(W - (route ? 330 : 30), 36));
  svg.innerHTML = out.join("");
  S.animateRoute = false;
  renderRouteCard(route);

  // redraw the roads already loaded at the new position right away, so nothing blanks while
  // the next box loads (most small pans and zooms need no new box at all)
  if (S.lastRoads) drawRoads(P, S.lastRoads);
  const roads = await roadsFor(view);
  if (S.frame !== f) return;
  if (roads !== S.lastRoads) { S.lastRoads = roads; drawRoads(P, roads); }
  $("#attrib").textContent = roads.graph ? "Roads © OpenStreetMap contributors, cached locally" : "No road graph cached";
}

// Pan by dragging, zoom with the wheel or the +/- buttons, "Fit" (or double-click) goes back to the
// automatic view. While dragging only the viewBox moves; the map is redrawn once on release.
function zoomMap(factor, cx, cy) {  // factor < 1 zooms in; (cx, cy) in map pixels stays put
  const v = S.view; if (!v) return;
  const { W, H } = mapSize();
  const lon = v.x0 + (cx / W) * (v.x1 - v.x0), lat = v.y1 - (cy / H) * (v.y1 - v.y0);
  const span = Math.min((v.x1 - v.x0) * factor, 6);
  if (span < 0.004) return;  // closer than ~400 m shows nothing useful
  S.userFrame = S.view = { x0: lon - (lon - v.x0) * factor, x1: lon + (v.x1 - lon) * factor,
                           y0: lat - (lat - v.y0) * factor, y1: lat + (v.y1 - lat) * factor };
  if (!S.mapQueued) {  // trackpads send many wheel events; draw once per frame
    S.mapQueued = true;
    requestAnimationFrame(() => { S.mapQueued = false; drawMap(); });
  }
}
function fitMap() { S.userFrame = null; drawMap(); }
(() => {
  const svg = $("#map");
  let drag = null;
  svg.addEventListener("pointerdown", (e) => {
    if (e.button !== 0 || !S.view) return;
    drag = { x: e.clientX, y: e.clientY, dx: 0, dy: 0 };
    svg.setPointerCapture(e.pointerId);
    svg.classList.add("dragging");
  });
  svg.addEventListener("pointermove", (e) => {
    if (!drag) return;
    drag.dx = e.clientX - drag.x; drag.dy = e.clientY - drag.y;
    const { W, H } = mapSize();
    svg.setAttribute("viewBox", `${-drag.dx} ${-drag.dy} ${W} ${H}`);
  });
  const end = () => {
    if (!drag) return;
    const { dx, dy } = drag; drag = null;
    svg.classList.remove("dragging");
    if (Math.abs(dx) + Math.abs(dy) < 3) { drawMap(); return; }  // a click, not a drag
    const v = S.view, { W, H } = mapSize();
    const mx = (dx / W) * (v.x1 - v.x0), my = (dy / H) * (v.y1 - v.y0);
    S.userFrame = { x0: v.x0 - mx, x1: v.x1 - mx, y0: v.y0 + my, y1: v.y1 + my };
    drawMap();
  };
  svg.addEventListener("pointerup", end);
  svg.addEventListener("pointercancel", end);
  svg.addEventListener("wheel", (e) => {
    e.preventDefault();
    const r = svg.getBoundingClientRect();
    const dy = e.deltaMode === 1 ? e.deltaY * 40 : e.deltaY;  // lines to pixels
    zoomMap(Math.exp(Math.max(-300, Math.min(300, dy)) * 0.002), e.clientX - r.left, e.clientY - r.top);
  }, { passive: false });
  svg.addEventListener("dblclick", fitMap);
  const mid = () => { const { W, H } = mapSize(); return [W / 2, H / 2]; };
  $("#map-in").onclick = () => zoomMap(0.67, ...mid());
  $("#map-out").onclick = () => zoomMap(1.5, ...mid());
  $("#map-fit").onclick = fitMap;
})();

function renderRouteCard(route) {
  const box = $("#route-card");
  if (!route) { box.hidden = true; return; }
  box.hidden = false;
  if (route.mode === "straight_line_fallback") {
    box.innerHTML = `<div class="rc-km">${route.distance_km}<small>km, straight line</small></div>
      <div class="rc-warn">No road graph cached. Run sync/build_road_graph.py while online.</div>`;
    return;
  }
  if (!route.ok) { box.innerHTML = `<div class="rc-note">${esc(route.reason)}</div>`; return; }
  let html = `<div class="rc-km">${route.distance_km}<small>km by road</small></div>
    <div class="rc-via">${esc((route.via || []).slice(0, 4).join(" → ") || "local roads")}</div>`;
  if (route.rerouted) {
    const extra = Math.round((route.distance_km - route.direct_route_km) * 10) / 10;
    html += `<div class="rc-note">Usual route (${route.direct_route_km} km) runs through a closure. ${extra >= 0.1 ? `Detour adds ${extra} km.` : "Detour is the same length."}</div>`;
  }
  box.innerHTML = html;
}

// ------------------------------------------------------------------ agent pane
function logItem(t, i) {
  const r = t.result;
  const kind = r._rule === "self_check" ? "check" : r.blocked_by ? "blocked" : r._outage ? "down"
    : r._malformed ? "bad" : r._fault ? "fault" : ("error" in r ? "err" : t.guard === "off" ? "off" : "pass");
  const label = { check: "Self-check failed", blocked: "Guard blocked", down: "Tool down", bad: "Injected fault (bad data)",
    fault: "Injected fault", err: "Error", off: "No guard", pass: "OK" }[kind];
  const enter = S.running && i === S.trace.length - 1 ? " enter" : "";
  return `<li class="${kind}${enter}">
    <div class="lg-head"><span class="lg-n">${String(i + 1).padStart(2, "0")}</span><span class="lg-tool">${esc(t.tool)}<span class="lg-ms">${t.ms ?? ""}${t.ms != null ? " ms" : ""}</span></span><span class="lg-st ${kind}">${label}</span></div>
    <div class="lg-sum">${esc(summarize(t))}</div>
    ${r.freshness ? `<div class="lg-fresh">${esc(r.freshness)}</div>` : ""}${r.note ? `<div class="lg-fresh">${esc(r.note)}</div>` : ""}
    <pre>${esc(JSON.stringify({ args: t.args, result: forModel(r) }, null, 2))}</pre></li>`;
}

function renderAgent() {
  const pane = $("#pane-agent");
  const i = S.state?.incidents.find((x) => x.id === S.selected);
  if (!i) { pane.innerHTML = `<div class="empty">Select a report. The agent's tool calls appear here as it works.</div>`; return; }
  const calls = S.trace.length, blocks = S.trace.filter((t) => t.result.blocked_by).length;
  const faults = S.trace.filter((t) => t.result._fault).length;
  let html = `<div class="section"><span>Tool calls</span><span class="stats">${calls ? `<span><b>${calls}</b>calls</span><span><b>${blocks}</b>blocked</span>${faults ? `<span><b>${faults}</b>faults</span>` : ""}${S.stats?.seconds != null ? `<span><b>${S.stats.seconds}</b>s</span>` : ""}` : ""}</span></div>`;
  if (!calls && !S.running) html += `<div class="empty">Not run yet.</div>`;
  else html += `<ol class="log">${S.trace.map(logItem).join("")}</ol>`;
  if (S.running) html += `<div class="thinking">${S.state.mode === "mock" ? "Next step" : "Lightning is choosing the next tool"}</div>`;
  if (S.final) html += `<div class="final">${esc(S.final)}</div>`;
  if (S.draft) html += ticketHTML(S.draft);
  pane.innerHTML = html;
  pane.querySelectorAll(".log li").forEach((li) => (li.onclick = () => li.classList.toggle("open")));
  const ap = $("#approve"), rj = $("#reject");
  if (ap) ap.onclick = () => decide("approve");
  if (rj) rj.onclick = () => decide("reject");
  if (S.running) pane.scrollTop = pane.scrollHeight;
}

function ticketHTML(d) {
  const p = d.plan, st = d.status;
  const stamp = st === "approved" ? "approved" : st === "rejected" ? "rejected" : "draft";
  return `<div class="ticket">
    <div class="tk-head"><span class="tk-title">Dispatch <span class="tk-id">#${d.id} · ${hhmm(d.created_at)}</span></span>
      <span class="stamp ${stamp}">${stamp === "draft" ? "Draft, not sent" : stamp}</span></div>
    <dl class="tk-body">
      <dt>Unit</dt><dd><span class="tk-unit">${esc(UNITS[p.unit_type] || p.unit_type)}</span>${UNIT_DESC[p.unit_type] ? `<div class="tk-desc">${esc(UNIT_DESC[p.unit_type])}</div>` : ""}</dd>
      <dt>Priority</dt><dd>${p.priority} of 5</dd>
      <dt>To</dt><dd>${esc(p.destination)}</dd>
      <dt>Route</dt><dd${/^route unavailable/i.test(p.route || "") ? ` class="tk-warn"` : ""}>${esc(p.route)}</dd>
      <dt>Notes</dt><dd>${esc(p.notes)}</dd>
    </dl>
    ${st === "pending_review" ? `<div class="tk-actions"><button class="btn ok" id="approve">Approve</button><button class="btn ghost" id="reject">Reject</button></div>` : ""}
    <div class="tk-foot">StormDesk has no way to send this. A dispatcher relays approved plans by radio or phone.</div>
  </div>`;
}

// ------------------------------------------------------------------ sandbox pane
async function loadSandbox() {
  try { S.sandbox = await api("/api/sandbox"); } catch { return; }
  const flag = $("#sandbox-flag");
  flag.className = "tab-flag " + (S.sandbox.in_sandbox ? "on" : "off");
  flag.textContent = S.sandbox.in_sandbox ? "ON" : "OFF";
  if (S.state) renderStorm();
  if (S.tab === "sandbox") renderSandbox();
}

function renderSandbox() {
  const sb = S.sandbox; if (!sb) return;
  const p = sb.policy;
  let html = sb.in_sandbox
    ? `<div class="sb-state on"><b>Running inside an OpenShell sandbox</b>Every file access and network connection below is enforced by OpenShell, outside StormDesk's own code.</div>`
    : `<div class="sb-state off"><b>Not sandboxed (development mode)</b>This policy is what the demo runs under. Start it with <code>scripts/openshell_up.sh</code> on the GPU box.</div>`;

  html += `<div class="section"><span>Who decides what</span></div>
    <div class="layer"><b>OpenShell</b><span>Is the action allowed at all? Kernel and proxy enforcement.</span>
      <b>Guard</b><span>Is this tool call valid and in a sensible order?</span>
      <b>Dispatcher</b><span>Should it actually happen? Every plan is a draft.</span></div>`;

  html += `<div class="section"><span>Network policy</span><span>default deny</span></div>
    <table class="sb"><tr><th>Destination</th><th>Allowed requests</th></tr>
    ${p.network.map((n) => `<tr><td><code>${esc(n.host)}</code> :${n.ports.join(", :")}<div class="why">${esc(n.rule)} · ${esc(n.enforcement)}</div></td><td>${n.allows.map((a) => `<code>${esc(a)}</code>`).join("<br>")}</td></tr>`).join("")}
    <tr><td colspan="2" class="why">Everything else, including SMS and email gateways, webhooks, cloud AI APIs and the open internet, is denied.</td></tr></table>`;

  html += `<div class="section"><span>Files</span><span>Landlock, ${esc(p.landlock)}</span></div>
    <table class="sb"><tr><td style="width:84px">Read</td><td>${p.read_only.map((x) => `<code>${esc(x)}</code>`).join(" ")}</td></tr>
    <tr><td>Read, write</td><td>${p.read_write.map((x) => `<code>${esc(x)}</code>`).join(" ")}</td></tr></table>`;

  html += `<div class="section"><span>Policy proof</span><span>openshell-prover</span></div>`;
  if (sb.prover.policy) {
    html += `<pre class="prover ${/within_boundary/.test(sb.prover.policy) ? "pass" : "fail"}">$ openshell-prover check policy.yaml --boundary boundary.yaml\n${esc(sb.prover.policy)}</pre>`;
    if (sb.prover["bad-policy"]) html += `<pre class="prover ${/exceeds_boundary/.test(sb.prover["bad-policy"]) ? "pass" : "fail"}">$ openshell-prover check bad-policy.yaml --boundary boundary.yaml\n${esc(sb.prover["bad-policy"])}</pre>`;
  } else {
    html += `<div class="why">Not run on this machine yet. <code>scripts/openshell_up.sh</code> runs the prover and saves its output here.</div>`;
  }

  html += `<div class="section"><span>Red-team checks</span><button class="btn ghost" id="redteam" style="padding:3px 10px;font-size:12px">Run checks</button></div>`;
  const rt = S.redteam?.results;
  if (rt) {
    // The checks finish in well under a second; rows are revealed one at a time so each can be read.
    const shown = S.rtShown ?? Infinity;
    html += `<table class="sb"><tr><th>Attempt</th><th>Result</th></tr>${rt.map((r, i) => {
      if (i > shown) return "";
      if (i === shown) return `<tr><td>${esc(r.title)}</td><td class="res skipped"><span class="trying">trying</span></td></tr>`;
      const cls = r.outcome === "skipped" || r.ok === null ? "skipped" : r.ok ? "good" : "bad";
      const word = r.outcome;
      return `<tr><td>${esc(r.title)}<div class="why">${esc(r.detail)}</div></td><td class="res ${cls}">${word}</td></tr>`;
    }).join("")}</table>`;
  } else {
    html += `<div class="why">Tries five things a compromised or prompt-injected agent might do, from inside the sandbox. None of them are agent tools.</div>`;
  }

  html += `<div class="section"><span>OpenShell audit log</span><span>${sb.audit_source ? "live" : ""}</span></div>`;
  if (sb.audit.length) {
    html += `<ol class="audit">${sb.audit.map((e) => `<li><span class="t">${e.time ? new Date(e.time).toLocaleTimeString([], { hour12: false }) : ""}</span><span class="a-${esc(e.action)}">${esc(e.action || "")}</span><span class="m">${esc(e.message)}${e.rule && e.rule !== "-" ? ` [${esc(e.rule)}]` : ""}${e.reason ? ` (${esc(e.reason)})` : ""}</span></li>`).join("")}</ol>`;
  } else {
    html += `<div class="why">${sb.in_sandbox ? "OpenShell keeps the audit log outside the sandbox, where StormDesk cannot read or change it. Watch it live on the host: <code>openshell logs stormdesk --tail --source sandbox</code>" : "Shown when running inside OpenShell. Records come from the OpenShell supervisor, not from StormDesk."}</div>`;
  }
  $("#pane-sandbox").innerHTML = html;
  if (S.rtRunning) { $("#redteam").disabled = true; $("#redteam").textContent = "Running"; }
  $("#redteam").onclick = async () => {
    S.rtRunning = true; renderSandbox();
    try {
      S.redteam = await api("/api/redteam", { method: "POST" });
      const n = S.redteam?.results?.length || 0;
      for (let i = 0; i <= n; i++) {
        S.rtShown = i; renderSandbox();
        if (i < n) await new Promise((r) => setTimeout(r, 1000));
      }
    } catch (e) { toast(e.message); }
    S.rtShown = undefined; S.rtRunning = false;
    await loadSandbox(); renderSandbox();
  };
}

document.querySelector(".tabs").addEventListener("click", (e) => {
  const b = e.target.closest("button"); if (!b) return;
  S.tab = b.dataset.tab;
  document.querySelectorAll(".tabs button").forEach((x) => x.classList.toggle("on", x === b));
  $("#pane-agent").hidden = S.tab !== "agent";
  $("#pane-sandbox").hidden = S.tab !== "sandbox";
  if (S.tab === "sandbox") renderSandbox();
});

// ------------------------------------------------------------------ actions
async function select(id) {
  S.selected = id; S.userFrame = null;
  const d = await api(`/api/incidents/${id}`);
  S.trace = d.trace; S.draft = d.draft; S.final = ""; S.stats = null;
  renderQueue(); renderIncident(); renderAgent(); drawMap();
}

async function runAgent() {
  if (S.running || !S.selected) return;
  S.running = true; S.trace = []; S.draft = null; S.final = ""; S.stats = null; S.userFrame = null;
  renderIncident(); renderAgent(); drawMap();
  try {
    const r = await fetch(`/api/incidents/${S.selected}/run?guard=${$("#guard").checked}&faults=${$("#faults").checked ? 0.3 : 0}&outage=${$("#outage").value}`, { method: "POST" });
    const reader = r.body.getReader(), dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let nl;
      while ((nl = buf.indexOf("\n")) >= 0) {
        const msg = JSON.parse(buf.slice(0, nl)); buf = buf.slice(nl + 1);
        if (msg.type === "step") {
          S.trace.push(msg.entry);
          if (msg.entry.tool === "plan_route") S.animateRoute = true;
          renderAgent();
          if (msg.entry.tool === "report_closure") await refresh();
          if (["geocode_location", "find_shelters", "plan_route", "report_closure"].includes(msg.entry.tool)) drawMap();
        } else if (msg.type === "done") { S.final = msg.final; S.stats = msg; }
        else if (msg.type === "error") toast(`Agent error: ${msg.error}`, 6000);
      }
    }
  } catch (e) { toast(`Agent error: ${e.message}`, 6000); }
  S.running = false;
  S.draft = (await api(`/api/incidents/${S.selected}`)).draft;
  await refresh(); renderIncident(); renderAgent();
}

async function decide(kind) {
  if (!S.draft) return;
  await api(`/api/drafts/${S.draft.id}/${kind}`, { method: "POST" });
  S.draft.status = kind === "approve" ? "approved" : "rejected";
  toast(kind === "approve" ? "Approved. Nothing was sent; relay it to the unit." : "Draft rejected.");
  await refresh(); renderAgent();
}

$("#compose").addEventListener("submit", async (e) => {
  e.preventDefault();
  const text = $("#report-text").value.trim(); if (!text) return;
  const out = await api("/api/reports", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text, channel: $("#channel").value }) });
  $("#report-text").value = "";
  toast(`#${out.id} triaged as ${CATS[out.category] || out.category}, urgency ${out.urgency}` +
        (out.flag ? ` (raised: ${out.flag})` : ""));
  await refresh();
});

// Two clicks, so a stray click at the hack fair table can't wipe a run in progress.
let resetArmed = null;
$("#reset").addEventListener("click", async () => {
  const btn = $("#reset");
  if (S.running) { toast("Wait for the agent to finish."); return; }
  if (!resetArmed) {
    btn.textContent = "Click again to reset"; btn.classList.add("armed");
    resetArmed = setTimeout(() => { resetArmed = null; btn.textContent = "Reset demo"; btn.classList.remove("armed"); }, 3000);
    return;
  }
  clearTimeout(resetArmed); resetArmed = null;
  btn.textContent = "Resetting"; btn.disabled = true;
  try {
    const r = await api("/api/demo/reset", { method: "POST" });
    S.selected = null; S.trace = []; S.draft = null; S.final = ""; S.stats = null;
    S.known.clear(); S.queueHTML = "";
    await refresh(); renderIncident(); renderAgent(); drawMap();
    toast(`Demo reset: ${r.loaded_reports} reports loaded.`);
  } catch (e) { toast(`Reset failed: ${e.message}`, 6000); }
  btn.textContent = "Reset demo"; btn.disabled = false; btn.classList.remove("armed");
});

// ------------------------------------------------------------------ polling
async function refresh() {
  S.state = await api("/api/state");
  renderStatus(); renderQueue();
}
async function boot() {
  await refresh();
  renderAgent(); drawMap(); loadSandbox();
  setInterval(() => { if (!S.running) refresh().catch(() => {}); }, 2500);
  setInterval(() => { if (S.tab === "sandbox") loadSandbox(); }, 4000);
  let rt; window.addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(drawMap, 150); });
}
boot().catch((e) => toast(`Cannot reach the StormDesk server: ${e.message}`, 8000));
