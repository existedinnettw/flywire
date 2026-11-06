// flywire's page: the board seen from the back, the wires as curves, the wire list beside
// it. Data: DATA (report.data() in Python); the bender: Bend (bend.js).
"use strict";

const D = DATA;
const P = D.bend;
const $ = (s) => document.querySelector(s);
const svg = $("#svg");
const NS = "http://www.w3.org/2000/svg";
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

const pinById = new Map(D.pins.map((p) => [p.id, p]));
const netInfo = new Map(D.nets.map((n, k) => [n.name, { ...n, order: k }]));
const netPins = new Map();
for (const p of D.pins) (netPins.get(p.net) || netPins.set(p.net, []).get(p.net)).push(p);
const [BX0, BY0, BX1, BY1] = D.bbox;
const label = (p) => p.id + (p.name !== p.pad ? ` (${p.name})` : "");
const sig = (w) => [w.a.id, w.b.id].sort().join("|");

// ------------------------------------------------------------------------------ state

const store = (() => {
  // key the browser's copy to the proposal, so a new board does not inherit old edits
  let h = 0;
  for (const c of D.title + JSON.stringify(D.proposed)) h = (h * 31 + c.charCodeAt(0)) | 0;
  const key = "flywire:" + D.title + ":" + (h >>> 0).toString(36);
  return {
    load() { try { return JSON.parse(localStorage.getItem(key) || "null"); } catch { return null; } },
    save(v) { try { localStorage.setItem(key, JSON.stringify(v)); } catch { /* private window */ } },
    clear() { try { localStorage.removeItem(key); } catch { /* ignore */ } },
    get(k, d) { try { return localStorage.getItem("flywire:" + k) ?? d; } catch { return d; } },
    set(k, v) { try { localStorage.setItem("flywire:" + k, v); } catch { /* ignore */ } },
  };
})();

function inflate(list) {
  return list.filter((w) => pinById.has(w.a) && pinById.has(w.b))
    .map((w) => ({ net: w.net, a: pinById.get(w.a), b: pinById.get(w.b), mid: w.mid ? w.mid.slice() : null, fixed: !!w.fixed }));
}
const deflate = (ws) => ws.map((w) => ({ net: w.net, a: w.a.id, b: w.b.id, mid: w.mid, fixed: w.fixed }));

const S = {
  wires: inflate(D.wires),
  done: new Set(),
  side: store.get("side", "back"),
  edit: false,
  numbers: store.get("numbers", "1") === "1",
  hideDone: store.get("hideDone", "0") === "1",
  sel: null,       // {wire: w} | {net: name}
  pending: null,   // pin: the first end of a wire being added
  filter: "",
  history: [],
  vb: null,        // [x, y, w, h] in view mm
};
const saved = store.load();
if (saved) {
  if (saved.wires) S.wires = inflate(saved.wires);
  S.done = new Set(saved.done || []);
}

function persist() { store.save({ wires: deflate(S.wires), done: [...S.done] }); }
function snapshot() {
  S.history.push(JSON.stringify(deflate(S.wires)));
  if (S.history.length > 200) S.history.shift();
}
function undo() {
  const prev = S.history.pop();
  if (!prev) return toast("Nothing to undo");
  S.wires = inflate(JSON.parse(prev));
  S.sel = null;
  changed();
}

// wires stay grouped by net, in the nets' order; a wire's number is its place
function sortWires() {
  const ord = (w) => (netInfo.get(w.net) || { order: 1e9 }).order;
  S.wires = S.wires.map((w, i) => [w, i]).sort((x, y) => ord(x[0]) - ord(y[0]) || x[1] - y[1]).map((x) => x[0]);
}
const no = (w) => S.wires.indexOf(w) + 1;

function bendWires(which) {
  Bend.bend(P, D.pins, D.holes, D.bbox, S.wires, which);
}

// ------------------------------------------------------------------------------ geometry

const VX = (x) => (S.side === "back" ? BX1 - x : x - BX0);
const VY = (y) => y - BY0;
const BXof = (vx) => (S.side === "back" ? BX1 - vx : vx + BX0);
const BYof = (vy) => vy + BY0;
const midOf = (w) => w.mid || [(w.a.x + w.b.x) / 2, (w.a.y + w.b.y) / 2];
const ctrl = (w) => { const m = midOf(w); return [2 * m[0] - (w.a.x + w.b.x) / 2, 2 * m[1] - (w.a.y + w.b.y) / 2]; };
const wlen = (w) => Bend.length(Bend.curve(P, [w.a.x, w.a.y], midOf(w), [w.b.x, w.b.y], 64));
const darkOn = () => document.documentElement.dataset.theme === "dark" ||
  (!document.documentElement.dataset.theme && matchMedia("(prefers-color-scheme: dark)").matches);
function hex(net) {
  // a black wire would vanish on the dark board: draw it light
  const h = (netInfo.get(net) || { hex: "#888888" }).hex;
  const v = /^#[0-9a-f]{6}$/i.test(h) ? [1, 3, 5].map((k) => parseInt(h.slice(k, k + 2), 16)) : [128, 128, 128];
  return darkOn() && 0.3 * v[0] + 0.59 * v[1] + 0.11 * v[2] < 60 ? "#e8e6e0" : h;
}

const grids = {};
function grid(p) {
  const side = S.side;
  if (!grids[side]) {
    const xs = D.pins.map((q) => VX(q.x)), ys = D.pins.map((q) => VY(q.y));
    const g = { x: Math.min(...xs), y: Math.min(...ys) };
    const at = (q) => {
      const c = (VX(q.x) - g.x) / 2.54, r = (VY(q.y) - g.y) / 2.54;
      return Math.abs(c - Math.round(c)) > 0.02 || Math.abs(r - Math.round(r)) > 0.02 ? null
        : "C" + String(Math.round(c) + 1).padStart(2, "0") + "R" + String(Math.round(r) + 1).padStart(2, "0");
    };
    g.on = D.pins.length > 0 && D.pins.filter((q) => at(q)).length >= 0.8 * D.pins.length;
    g.at = at;
    grids[side] = g;
  }
  const g = grids[side];
  return g.on ? g.at(p) || "off grid" : `${VX(p.x).toFixed(1)}, ${VY(p.y).toFixed(1)}`;
}

// ------------------------------------------------------------------------------ checks

function problems() {
  const out = [], bad = new Set(), deg = new Map(), seen = new Map();
  S.wires.forEach((w) => {
    if (w.a.id === w.b.id) { out.push({ text: `wire ${no(w)} joins ${w.a.id} to itself`, wire: w }); bad.add(w.a.id); }
    const k = sig(w);
    if (seen.has(k)) out.push({ text: `wire ${no(w)} repeats wire ${no(seen.get(k))}`, wire: w });
    else seen.set(k, w);
    for (const p of [w.a, w.b]) deg.set(p.id, (deg.get(p.id) || 0) + 1);
  });
  for (const [id, n] of deg) {
    if (n > D.maxPerPin) { out.push({ text: `${id} takes ${n} wires (limit ${D.maxPerPin})`, pin: id }); bad.add(id); }
  }
  for (const [net, pins] of netPins) {
    if (pins.length < 2) continue;
    const root = new Map(pins.map((p) => [p.id, p.id]));
    const find = (i) => { while (root.get(i) !== i) i = root.get(i); return i; };
    for (const w of S.wires) if (w.net === net && root.has(w.a.id) && root.has(w.b.id)) root.set(find(w.a.id), find(w.b.id));
    const groups = new Map();
    for (const p of pins) (groups.get(find(p.id)) || groups.set(find(p.id), []).get(find(p.id))).push(p);
    if (groups.size > 1) {
      const loose = [...groups.values()].sort((x, y) => x.length - y.length)[0];
      out.push({ text: `${net} is in ${groups.size} pieces (e.g. ${loose.map((p) => p.id).slice(0, 3).join(", ")} apart)`, net });
      for (const g of groups.values()) if (g.length <= loose.length) g.forEach((p) => bad.add(p.id));
    }
  }
  return { list: out, pins: bad };
}

// ------------------------------------------------------------------------------ drawing

function shapeSvg(s, cls) {
  if (s.k === "circle") return `<circle class="${cls}" cx="${VX(s.c[0])}" cy="${VY(s.c[1])}" r="${s.r}"/>`;
  const pts = s.pts.map(([x, y]) => `${VX(x).toFixed(3)},${VY(y).toFixed(3)}`).join(" ");
  return s.k === "poly" ? `<polygon class="${cls}" points="${pts}"/>` : `<polyline class="${cls}" points="${pts}"/>`;
}

const staticLayer = { side: null, html: "" };
function boardSvg() {
  if (staticLayer.side === S.side) return staticLayer.html;
  const o = [`<rect class="board" x="0" y="0" width="${BX1 - BX0}" height="${BY1 - BY0}"/>`];
  for (const f of D.footprints) for (const s of f.shapes) o.push(shapeSvg(s, f.back ? "crt back" : "crt"));
  for (const s of D.edges) o.push(shapeSvg(s, "edge"));
  for (const f of D.footprints) {
    const pts = f.shapes.flatMap((s) => (s.k === "circle" ? [s.c] : s.pts));
    if (!pts.length) continue;
    const cx = pts.reduce((t, p) => t + p[0], 0) / pts.length;
    const top = Math.min(...pts.map((p) => p[1])), bottom = Math.max(...pts.map((p) => p[1]));
    const y = bottom - top > 8 ? top + 2.6 : top - 0.6;
    o.push(`<text class="ref" x="${VX(cx).toFixed(2)}" y="${VY(y).toFixed(2)}">${esc(f.ref)}</text>`);
  }
  for (const [x, y, r] of D.holes) o.push(`<circle class="hole" cx="${VX(x)}" cy="${VY(y)}" r="${Math.max(0.35, r * 0.7)}"/>`);
  staticLayer.side = S.side;
  staticLayer.html = o.join("");
  return staticLayer.html;
}

function matches(w) {
  if (!S.filter) return true;
  const f = S.filter;
  return [w.net, label(w.a), label(w.b), String(no(w))].some((s) => s.toLowerCase().includes(f));
}

let drag = null;   // {kind: "mid"|"a"|"b"|"pan", ...}
let cursor = null; // [bx, by] board mm, while adding a wire
let probs = { list: [], pins: new Set() };

function render() {
  const selWire = S.sel && S.sel.wire, selNet = S.sel && (S.sel.net || (selWire && selWire.net));
  const o = [boardSvg()];
  const pathOf = (w) => {
    const c = ctrl(w);
    return `M${VX(w.a.x).toFixed(3)} ${VY(w.a.y).toFixed(3)}Q${VX(c[0]).toFixed(3)} ${VY(c[1]).toFixed(3)} ${VX(w.b.x).toFixed(3)} ${VY(w.b.y).toFixed(3)}`;
  };
  const shown = S.wires.filter((w) => !(S.hideDone && S.done.has(sig(w)) && w !== selWire));
  const dim = (w) => (selWire ? w !== selWire && w.net !== selNet : selNet ? w.net !== selNet : !matches(w));
  // halos under every wire, so crossings read; the selection on top
  const order = shown.slice().sort((x, y) => (x === selWire) - (y === selWire) || !dim(x) - !dim(y));
  for (const w of order) if (!dim(w)) o.push(`<path class="halo" d="${pathOf(w)}"/>`);
  for (const w of order) {
    const i = S.wires.indexOf(w);
    const cls = ["wire", w === selWire ? "sel" : "", dim(w) ? "dim" : "", S.done.has(sig(w)) ? "done" : ""].join(" ");
    o.push(`<path class="${cls}" stroke="${hex(w.net)}" d="${pathOf(w)}"/><path class="hit" data-wire="${i}" d="${pathOf(w)}"/>`);
  }
  // pads over the wire ends
  const pendingNet = S.pending && S.pending.net;
  for (const p of D.pins) {
    const cls = ["pad"];
    if (probs.pins.has(p.id)) cls.push("bad");
    else if (p.net === selNet || p.net === pendingNet) cls.push("net");
    if (S.pending === p) cls.push("pending");
    if (drag && drag.target === p) cls.push("target");
    o.push(`<circle class="${cls.join(" ")}" style="--c:${hex(p.net)}" data-pin="${esc(p.id)}" cx="${VX(p.x)}" cy="${VY(p.y)}" r="${Math.max(0.5, p.r * 0.85).toFixed(3)}"/>`);
  }
  if (S.numbers) {
    for (const w of order) {
      if (dim(w) && (selWire || selNet)) continue;
      const m = Bend.curve(P, [w.a.x, w.a.y], midOf(w), [w.b.x, w.b.y], 2)[1];
      const i = S.wires.indexOf(w);
      o.push(`<g class="lbl${dim(w) ? " dim" : ""}" data-wire="${i}"><circle cx="${VX(m[0]).toFixed(3)}" cy="${VY(m[1]).toFixed(3)}" r="1.05" stroke="${hex(w.net)}"/>` +
        `<text x="${VX(m[0]).toFixed(3)}" y="${VY(m[1]).toFixed(3)}" fill="${hex(w.net)}">${i + 1}</text></g>`);
    }
  }
  if (S.edit && selWire) {
    const w = selWire, c = ctrl(w), m = midOf(w);
    o.push(`<polyline class="guide" points="${VX(w.a.x)},${VY(w.a.y)} ${VX(c[0])},${VY(c[1])} ${VX(w.b.x)},${VY(w.b.y)}"/>`);
    o.push(`<circle class="handle" data-h="mid" cx="${VX(m[0])}" cy="${VY(m[1])}" r="0.9"/>`);
    for (const end of ["a", "b"]) {
      const p = drag && drag.kind === end && drag.at ? { x: drag.at[0], y: drag.at[1] } : w[end];
      o.push(`<rect class="handle" data-h="${end}" x="${VX(p.x) - 0.8}" y="${VY(p.y) - 0.8}" width="1.6" height="1.6"/>`);
    }
  }
  if (S.pending && cursor) {
    o.push(`<line class="rubber" x1="${VX(S.pending.x)}" y1="${VY(S.pending.y)}" x2="${VX(cursor[0])}" y2="${VY(cursor[1])}"/>`);
  }
  svg.innerHTML = o.join("");
  svg.setAttribute("viewBox", S.vb.map((v) => v.toFixed(3)).join(" "));
}

let frame = 0;
function redraw() { if (!frame) frame = requestAnimationFrame(() => { frame = 0; render(); }); }

function renderList() {
  const tb = $("#wires tbody");
  const o = [];
  let net = null, total = 0;
  const counts = new Map();
  for (const w of S.wires) {
    const c = counts.get(w.net) || [0, 0];
    c[0] += S.done.has(sig(w)) ? 1 : 0; c[1]++;
    counts.set(w.net, c);
  }
  S.wires.forEach((w, i) => {
    const L = wlen(w);
    total += L;
    if (!matches(w)) return;
    if (S.hideDone && S.done.has(sig(w)) && w !== (S.sel && S.sel.wire)) return;
    const c = hex(w.net);
    if (w.net !== net) {
      net = w.net;
      const n = netInfo.get(net) || { colour: "" };
      const [d, t] = counts.get(net);
      o.push(`<tr class="net" data-net="${esc(net)}" style="--c:${c}"><td colspan="5"><span class="sw"></span>${esc(net)}` +
        ` <small>${esc(n.colour)}</small><span class="count">${d}/${t}</span></td></tr>`);
    }
    const done = S.done.has(sig(w));
    const pin = (p) => `<td class="pin"><b>${esc(p.id)}</b>${p.name !== p.pad ? " " + esc(p.name) : ""}<small>${esc(grid(p))}</small></td>`;
    o.push(`<tr class="w${done ? " done" : ""}${S.sel && S.sel.wire === w ? " sel" : ""}" data-wire="${i}" style="--c:${c}">` +
      `<td><input type="checkbox" data-done="${i}"${done ? " checked" : ""} aria-label="wire ${i + 1} done"></td>` +
      `<td class="no">${i + 1}</td>${pin(w.a)}${pin(w.b)}` +
      `<td class="num">${L.toFixed(1)}<small style="display:block;color:var(--muted)">${(L + D.slack).toFixed(0)}</small></td></tr>`);
  });
  tb.innerHTML = o.join("");
  const doneN = S.wires.filter((w) => S.done.has(sig(w))).length;
  $("#stats").textContent = `${S.wires.length} wires · ${total.toFixed(0)} mm (cut ${(total + D.slack * S.wires.length).toFixed(0)}) · ${doneN}/${S.wires.length} done`;

  const pb = $("#problems");
  if (probs.list.length) {
    pb.className = "bad";
    pb.innerHTML = `<b>${probs.list.length} problem${probs.list.length > 1 ? "s" : ""}</b><ul>` +
      probs.list.map((p, k) => `<li data-prob="${k}">${esc(p.text)}</li>`).join("") + "</ul>";
  } else {
    pb.className = "ok";
    pb.textContent = `Every net is connected; no pin takes more than ${D.maxPerPin} wires.`;
  }
}

function changed() {
  tipOff();
  sortWires();
  probs = problems();
  persist();
  renderList();
  render();
}

function select(sel, scroll) {
  S.sel = sel;
  renderList();
  render();
  if (scroll && sel && sel.wire) {
    const row = $(`#wires tr[data-wire="${S.wires.indexOf(sel.wire)}"]`);
    if (row) row.scrollIntoView({ block: "nearest" });
  }
  hint();
}

function hint() {
  let t;
  if (S.edit) {
    if (S.pending) t = `Adding a wire from ${label(S.pending)}: click another ${S.pending.net} pin (Esc cancels)`;
    else if (S.sel && S.sel.wire) t = "Drag the round handle to bend, a square one onto another pin to reconnect · Del deletes · A auto-bends · S straightens";
    else t = "Edit: click a wire to change it, or a pin to start a new wire";
  } else {
    t = "Wheel zooms · drag pans · click a wire or a pin · E edits · ? helps";
  }
  $("#hint").textContent = t;
}

let toastTimer = 0;
function toast(t, ms = 2600) {
  const el = $("#toast");
  el.textContent = t;
  el.style.display = "block";
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (el.style.display = "none"), ms);
}

// ------------------------------------------------------------------------------ view box

function fit() {
  const r = svg.getBoundingClientRect();
  const m = 4, w = BX1 - BX0 + 2 * m, h = BY1 - BY0 + 2 * m;
  const aspect = r.width && r.height ? r.width / r.height : w / h;
  S.vb = aspect > w / h ? [-m - (h * aspect - w) / 2, -m, h * aspect, h] : [-m, -m - (w / aspect - h) / 2, w, w / aspect];
}

function toView(ev) {
  const pt = svg.createSVGPoint();
  pt.x = ev.clientX; pt.y = ev.clientY;
  const q = pt.matrixTransform(svg.getScreenCTM().inverse());
  return [q.x, q.y];
}
const toBoard = (ev) => { const [x, y] = toView(ev); return [BXof(x), BYof(y)]; };

svg.addEventListener("wheel", (ev) => {
  ev.preventDefault();
  const [x, y] = toView(ev);
  const k = Math.exp(ev.deltaY * (ev.deltaMode ? 0.05 : 0.0015));
  const [vx, vy, vw, vh] = S.vb;
  const nw = Math.min(Math.max(vw * k, 5), 2000), f = nw / vw;
  S.vb = [x - (x - vx) * f, y - (y - vy) * f, vw * f, vh * f];
  redraw();
}, { passive: false });

// ------------------------------------------------------------------------------ pointer

function nearestPin(at, net, except) {
  let best = null, bd = 2.6;
  for (const p of netPins.get(net) || []) {
    if (except.includes(p)) continue;
    const d = Math.hypot(p.x - at[0], p.y - at[1]);
    if (d < bd) { best = p; bd = d; }
  }
  return best;
}

svg.addEventListener("pointerdown", (ev) => {
  if (ev.button !== 0) return;
  const t = ev.target;
  const h = t.dataset && t.dataset.h;
  const wire = t.closest && t.closest("[data-wire]");
  const pinId = t.dataset && t.dataset.pin;
  svg.setPointerCapture(ev.pointerId);
  if (S.edit && h && S.sel && S.sel.wire) {
    snapshot();
    drag = { kind: h, wire: S.sel.wire, moved: false };
    return;
  }
  drag = { kind: "pan", start: [ev.clientX, ev.clientY], vb: S.vb.slice(), moved: false, wire, pinId };
});

svg.addEventListener("pointermove", (ev) => {
  if (drag && drag.kind === "pan") {
    const dx = ev.clientX - drag.start[0], dy = ev.clientY - drag.start[1];
    if (!drag.moved && Math.hypot(dx, dy) < 4) return;
    drag.moved = true;
    svg.classList.add("panning");
    const r = svg.getBoundingClientRect(), k = drag.vb[2] / r.width;
    S.vb = [drag.vb[0] - dx * k, drag.vb[1] - dy * k, drag.vb[2], drag.vb[3]];
    tipOff();
    return redraw();
  }
  if (drag && drag.kind === "mid") {
    drag.moved = true;
    drag.wire.mid = toBoard(ev).map((v) => Math.round(v * 1e4) / 1e4);
    drag.wire.fixed = true;
    return redraw();
  }
  if (drag && (drag.kind === "a" || drag.kind === "b")) {
    drag.moved = true;
    drag.at = toBoard(ev);
    const w = drag.wire, other = drag.kind === "a" ? w.b : w.a;
    drag.target = nearestPin(drag.at, w.net, [other]);
    return redraw();
  }
  if (S.pending) { cursor = toBoard(ev); redraw(); }
  hover(ev);
});

svg.addEventListener("pointerup", (ev) => {
  const d = drag;
  drag = null;
  svg.classList.remove("panning");
  if (!d) return;
  if (d.kind === "mid") {
    if (!d.moved) S.history.pop();
    return changed();
  }
  if (d.kind === "a" || d.kind === "b") {
    const w = d.wire;
    if (d.target && d.target !== w[d.kind]) {
      w[d.kind] = d.target;
      w.mid = null; w.fixed = false;
      bendWires([S.wires.indexOf(w)]);
      toast(`Wire ${no(w)} now ends at ${label(d.target)}`);
    } else if (!d.moved) S.history.pop();
    else { S.history.pop(); toast(`Drop it on another ${w.net} pin`); }
    return changed();
  }
  if (d.moved) return;
  // a click
  if (d.pinId) return clickPin(pinById.get(d.pinId));
  if (d.wire) {
    const w = S.wires[+d.wire.dataset.wire];
    if (S.pending) return;
    return select(S.sel && S.sel.wire === w ? null : { wire: w }, true);
  }
  if (S.pending) { S.pending = null; cursor = null; hint(); return render(); }
  select(null);
});

svg.addEventListener("dblclick", (ev) => {
  if (ev.target.closest("[data-wire],[data-pin],[data-h]")) return;
  fit(); render();
});

function clickPin(p) {
  if (!S.edit) return select(S.sel && S.sel.net === p.net && !S.sel.wire ? null : { net: p.net });
  if (!S.pending) {
    S.pending = p; cursor = [p.x, p.y]; S.sel = { net: p.net };
    hint(); renderList(); return render();
  }
  const a = S.pending;
  if (p === a) { S.pending = null; cursor = null; hint(); return render(); }
  if (p.net !== a.net) return toast(`${label(p)} is on ${p.net}, not ${a.net}`);
  snapshot();
  const w = { net: a.net, a, b: p, mid: null, fixed: false };
  const last = S.wires.map((x) => x.net).lastIndexOf(a.net);
  S.wires.splice(last + 1, 0, w);
  bendWires([S.wires.indexOf(w)]);
  S.pending = null; cursor = null;
  S.sel = { wire: w };
  changed();
  hint();
  toast(`Added wire ${no(w)}: ${label(a)} – ${label(p)}`);
}

// ------------------------------------------------------------------------------ tooltip

const tip = $("#tip");
function tipOff() { tip.style.display = "none"; }
function hover(ev) {
  const t = ev.target;
  let html = null;
  if (t.dataset && t.dataset.pin) {
    const p = pinById.get(t.dataset.pin);
    const ws = S.wires.filter((w) => w.a === p || w.b === p).map(no);
    html = `<b>${esc(label(p))}</b> · ${esc(p.net)}<br>${esc(grid(p))} · wires ${ws.length ? ws.join(", ") : "none"}`;
  } else {
    const g = t.closest && t.closest("[data-wire]");
    if (g) {
      const w = S.wires[+g.dataset.wire];
      const L = wlen(w);
      html = `<b>#${no(w)}</b> ${esc(w.net)} · ${esc(label(w.a))} – ${esc(label(w.b))}<br>${L.toFixed(1)} mm, cut ${(L + D.slack).toFixed(0)}` +
        (w.fixed ? " · bent by hand" : "");
    }
  }
  if (!html) return tipOff();
  tip.innerHTML = html;
  const r = $("#view").getBoundingClientRect();
  tip.style.display = "block";
  const x = Math.min(ev.clientX - r.left + 14, r.width - tip.offsetWidth - 6);
  const y = ev.clientY - r.top + 16 + tip.offsetHeight > r.height ? ev.clientY - r.top - tip.offsetHeight - 10 : ev.clientY - r.top + 16;
  tip.style.left = x + "px";
  tip.style.top = y + "px";
}
svg.addEventListener("pointerleave", tipOff);

// ------------------------------------------------------------------------------ list

$("#wires tbody").addEventListener("click", (ev) => {
  const cb = ev.target.closest("[data-done]");
  if (cb) {
    const w = S.wires[+cb.dataset.done];
    toggleDone(w);
    return;
  }
  const row = ev.target.closest("tr");
  if (!row) return;
  if (row.dataset.net) return select(S.sel && S.sel.net === row.dataset.net && !S.sel.wire ? null : { net: row.dataset.net });
  const w = S.wires[+row.dataset.wire];
  select(S.sel && S.sel.wire === w ? null : { wire: w });
});
$("#problems").addEventListener("click", (ev) => {
  const li = ev.target.closest("[data-prob]");
  if (!li) return;
  const p = probs.list[+li.dataset.prob];
  if (p.wire) select({ wire: p.wire }, true);
  else if (p.net) select({ net: p.net });
  else if (p.pin) select({ net: pinById.get(p.pin).net });
});
$("#filter").addEventListener("input", (ev) => { S.filter = ev.target.value.trim().toLowerCase(); renderList(); render(); });

function toggleDone(w) {
  const k = sig(w);
  if (S.done.has(k)) S.done.delete(k); else S.done.add(k);
  persist(); renderList(); render();
}

// ------------------------------------------------------------------------------ controls

function setSide(side) {
  S.side = side;
  store.set("side", side);
  document.querySelectorAll("#side button").forEach((b) => b.classList.toggle("on", b.dataset.side === side));
  // keep the same part of the board in view
  if (S.vb) { const [x, y, w, h] = S.vb; S.vb = [BX1 - BX0 - x - w, y, w, h]; }
  renderList(); render();
}
document.querySelectorAll("#side button").forEach((b) => b.addEventListener("click", () => setSide(b.dataset.side)));

function setEdit(on) {
  S.edit = on;
  S.pending = null; cursor = null;
  document.body.classList.toggle("editing", on);
  $("#edit").classList.toggle("on", on);
  hint(); render();
}
$("#edit").addEventListener("click", () => setEdit(!S.edit));
$("#opt-num").checked = S.numbers;
$("#opt-num").addEventListener("change", (ev) => { S.numbers = ev.target.checked; store.set("numbers", S.numbers ? "1" : "0"); render(); });
$("#opt-hide").checked = S.hideDone;
$("#opt-hide").addEventListener("change", (ev) => { S.hideDone = ev.target.checked; store.set("hideDone", S.hideDone ? "1" : "0"); renderList(); render(); });
$("#undo").addEventListener("click", undo);
$("#autobend").addEventListener("click", () => {
  snapshot();
  bendWires();
  changed();
  toast("Bent every wire not bent by hand");
});
let resetArmed = 0;
$("#reset").addEventListener("click", (ev) => {
  if (!resetArmed) {
    ev.target.classList.add("armed");
    ev.target.textContent = "Reset?";
    resetArmed = setTimeout(() => { resetArmed = 0; ev.target.classList.remove("armed"); ev.target.textContent = "Reset"; }, 2500);
    return;
  }
  clearTimeout(resetArmed); resetArmed = 0;
  ev.target.classList.remove("armed"); ev.target.textContent = "Reset";
  snapshot();
  S.wires = inflate(D.proposed);
  S.sel = null;
  changed();
  toast("Back to the proposed wiring (Undo brings your edits back)");
});
$("#export").addEventListener("click", () => {
  const nets = [...netPins.keys()].filter((n) => netPins.get(n).length > 1).sort();
  const body = { flywire: 1, board: D.title, maxPerPin: D.maxPerPin, nets, wires: deflate(S.wires) };
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([JSON.stringify(body, null, 1) + "\n"], { type: "application/json" }));
  a.download = "wiring.json";
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  toast(`Saved wiring.json · flywire ${D.title}.kicad_pcb --edits wiring.json rebuilds the list`, 5000);
});
$("#theme").addEventListener("click", () => {
  const next = darkOn() ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  store.set("theme", next);
  renderList(); render();
});
const helpDlg = $("#helpdlg");
$("#help").addEventListener("click", () => helpDlg.showModal());

// list width
$("#resizer").addEventListener("pointerdown", (ev) => {
  const el = ev.target;
  el.setPointerCapture(ev.pointerId);
  const move = (e) => document.documentElement.style.setProperty("--list-w", Math.max(260, e.clientX) + "px");
  const up = () => { el.removeEventListener("pointermove", move); el.removeEventListener("pointerup", up); };
  el.addEventListener("pointermove", move);
  el.addEventListener("pointerup", up);
});

document.addEventListener("keydown", (ev) => {
  if (ev.target.matches("input[type=search], input[type=text]") || helpDlg.open) {
    if (ev.key === "Escape") ev.target.blur();
    return;
  }
  const w = S.sel && S.sel.wire;
  if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "z") { ev.preventDefault(); return undo(); }
  if (ev.ctrlKey || ev.metaKey || ev.altKey) return;
  switch (ev.key) {
    case "Escape":
      if (S.pending) { S.pending = null; cursor = null; hint(); render(); } else select(null);
      break;
    case "e": case "E": setEdit(!S.edit); break;
    case "f": case "F": setSide(S.side === "back" ? "front" : "back"); break;
    case "n": case "N": $("#opt-num").click(); break;
    case "?": helpDlg.showModal(); break;
    case "ArrowDown": case "ArrowUp": {
      ev.preventDefault();
      const list = S.wires.filter((x) => matches(x) && !(S.hideDone && S.done.has(sig(x)) && x !== w));
      if (!list.length) break;
      const k = w ? list.indexOf(w) : -1;
      const next = ev.key === "ArrowDown" ? list[Math.min(k + 1, list.length - 1)] : list[Math.max(k - 1, 0)];
      select({ wire: next }, true);
      break;
    }
    case " ":
      if (w) { ev.preventDefault(); toggleDone(w); }
      break;
    case "Delete": case "Backspace":
      if (S.edit && w) {
        snapshot();
        const n = no(w);
        S.wires.splice(S.wires.indexOf(w), 1);
        S.sel = { net: w.net };
        changed();
        toast(`Deleted wire ${n} (Ctrl+Z undoes)`);
      }
      break;
    case "a": case "A":
      if (S.edit && w) { snapshot(); w.fixed = false; bendWires([S.wires.indexOf(w)]); changed(); }
      break;
    case "s": case "S":
      if (S.edit && w) { snapshot(); w.mid = [(w.a.x + w.b.x) / 2, (w.a.y + w.b.y) / 2]; w.fixed = true; changed(); }
      break;
    default:
  }
});

// ------------------------------------------------------------------------------ start

const theme = store.get("theme", "");
if (theme) document.documentElement.dataset.theme = theme;
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => { renderList(); render(); });
document.querySelectorAll("#side button").forEach((b) => b.classList.toggle("on", b.dataset.side === S.side));
let lastW = 0;
new ResizeObserver(() => {
  // keep the scale and the centre; the first time, fit the board
  const r = svg.getBoundingClientRect();
  if (!r.width || !r.height) return;
  if (!lastW || !S.vb) fit();
  else {
    const k = S.vb[2] / lastW, cx = S.vb[0] + S.vb[2] / 2, cy = S.vb[1] + S.vb[3] / 2;
    S.vb = [cx - (r.width * k) / 2, cy - (r.height * k) / 2, r.width * k, r.height * k];
  }
  lastW = r.width;
  render();
}).observe($("#view"));
fit();
changed();
hint();
if (saved && saved.wires) toast("Your edits from last time are back (Reset discards them)");
