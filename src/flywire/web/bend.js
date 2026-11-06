// The wire bender of src/flywire/bend.py, for the page: the same curves, the same costs,
// the same candidates. Keep the two in step (tests/test_bend.py runs both on one board).
// Parameters come from the page's data (P), so Python stays their one source.
"use strict";

const Bend = (() => {
  function curve(P, a, m, b, n) {
    const cx = 2 * m[0] - (a[0] + b[0]) / 2, cy = 2 * m[1] - (a[1] + b[1]) / 2;
    if (n === undefined) {
      n = Math.max(8, Math.ceil((Math.hypot(m[0] - a[0], m[1] - a[1]) + Math.hypot(b[0] - m[0], b[1] - m[1])) / P.STEP));
    }
    const out = [];
    for (let k = 0; k <= n; k++) {
      const t = k / n, u = 1 - t;
      out.push([u * u * a[0] + 2 * u * t * cx + t * t * b[0], u * u * a[1] + 2 * u * t * cy + t * t * b[1]]);
    }
    return out;
  }

  function length(pts) {
    let s = 0;
    for (let k = 0; k + 1 < pts.length; k++) s += Math.hypot(pts[k + 1][0] - pts[k][0], pts[k + 1][1] - pts[k][1]);
    return s;
  }

  function candidates(P, a, b) {
    const dx = b[0] - a[0], dy = b[1] - a[1], L = Math.hypot(dx, dy);
    const mx = (a[0] + b[0]) / 2, my = (a[1] + b[1]) / 2;
    if (L < 1e-9) return [[mx, my]];
    const tx = dx / L, ty = dy / L, nx = -ty, ny = tx;
    const limit = Math.max(2.5, 0.6 * L);
    const out = [[mx, my]];
    for (const s of P.SIDE.slice(1)) {
      if (s > limit) break;
      for (const sign of [1, -1]) {
        for (const f of P.ALONG) {
          const u = f * L;
          out.push([mx + sign * s * nx + u * tx, my + sign * s * ny + u * ty]);
        }
      }
    }
    return out;
  }

  // pins: [{id, x, y, r}], holes: [[x, y, r]], wires: [{a: pin, b: pin, mid}], bbox: [x0, y0, x1, y1]
  class Field {
    constructor(P, pins, holes, bbox, wires) {
      this.P = P;
      this.wires = wires;
      this.box = [bbox[0] + 0.5, bbox[1] + 0.5, bbox[2] - 0.5, bbox[3] - 0.5];
      this.pads = new Map();
      for (const p of pins) this.push(this.pads, this.cell(p.x, p.y), [p.id, p.x, p.y, p.r]);
      holes.forEach((h, k) => this.push(this.pads, this.cell(h[0], h[1]), ["#hole" + k, h[0], h[1], h[2]]));
      this.samples = wires.map(() => null);
      this.grid = new Map();
    }
    cell(x, y) { return Math.floor(x / this.P.CELL) + "," + Math.floor(y / this.P.CELL); }
    push(map, key, v) { const l = map.get(key); if (l) l.push(v); else map.set(key, [v]); }
    place(i, pts) {
      const old = this.samples[i];
      if (old) {
        for (const c of new Set(old.map(([x, y]) => this.cell(x, y)))) {
          this.grid.set(c, this.grid.get(c).filter((e) => e[0] !== i));
        }
      }
      this.samples[i] = pts;
      if (pts) for (const [x, y] of pts) this.push(this.grid, this.cell(x, y), [i, x, y]);
    }
    cost(i, m) {
      const P = this.P, w = this.wires[i];
      const a = [w.a.x, w.a.y], b = [w.b.x, w.b.y];
      const pts = curve(P, a, m, b);
      const chord = Math.hypot(b[0] - a[0], b[1] - a[1]);
      const mx = (a[0] + b[0]) / 2, my = (a[1] + b[1]) / 2;
      let c = P.W_LEN * (length(pts) - chord) + P.W_OFF * Math.hypot(m[0] - mx, m[1] - my);
      const ends = new Map([[w.a.id, a], [w.b.id, b]]);
      const [bx0, by0, bx1, by1] = this.box;
      for (let k = 1; k + 1 < pts.length; k++) {
        const [x, y] = pts[k];
        const out = Math.max(bx0 - x, 0, x - bx1) + Math.max(by0 - y, 0, y - by1);
        if (out > 0) c += P.W_OUT * out;
        const cx = Math.floor(x / P.CELL), cy = Math.floor(y / P.CELL);
        const near = new Map();
        for (let gx = cx - 1; gx <= cx + 1; gx++) {
          for (let gy = cy - 1; gy <= cy + 1; gy++) {
            const key = gx + "," + gy;
            for (const [id, px, py, r] of this.pads.get(key) || []) {
              if (ends.has(id)) continue;
              const d = Math.hypot(x - px, y - py), lim = r + P.CLEAR;
              if (d < lim) c += P.W_PAD * (lim - d);
            }
            for (const [j, qx, qy] of this.grid.get(key) || []) {
              if (j === i) continue;
              const d = Math.hypot(x - qx, y - qy);
              if (d < P.SEP && d < (near.has(j) ? near.get(j) : P.SEP)) near.set(j, d);
            }
          }
        }
        for (const [j, d] of near) {
          const o = this.wires[j];
          const shared = [o.a.id, o.b.id].some((id) => ends.has(id) &&
            Math.hypot(x - ends.get(id)[0], y - ends.get(id)[1]) < P.SHARE);
          if (!shared) c += P.W_WIRE * (P.SEP - d);
        }
      }
      return c;
    }
    best(i) {
      const w = this.wires[i], a = [w.a.x, w.a.y], b = [w.b.x, w.b.y];
      let bestM = null, bestC = Infinity;
      for (const m of candidates(this.P, a, b)) {
        const c = this.cost(i, m);
        if (c < bestC - 1e-9) { bestM = m; bestC = c; }
      }
      return bestM || [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
    }
  }

  const round4 = (v) => Math.round(v * 1e4) / 1e4;
  const midOf = (w) => w.mid || [(w.a.x + w.b.x) / 2, (w.a.y + w.b.y) / 2];

  // Set .mid on the wires whose index is in `which` (default: every wire not .fixed),
  // against all the others as they are.
  function bend(P, pins, holes, bbox, wires, which) {
    const f = new Field(P, pins, holes, bbox, wires);
    const chord = (w) => Math.hypot(w.a.x - w.b.x, w.a.y - w.b.y);
    const free = (which || wires.map((w, i) => (w.fixed ? -1 : i)).filter((i) => i >= 0))
      .slice().sort((i, j) => chord(wires[j]) - chord(wires[i]) || i - j);
    const freeSet = new Set(free);
    const first = !which;  // a full run places the longest first, against those placed so far
    wires.forEach((w, i) => {
      if (!first || !freeSet.has(i)) f.place(i, curve(P, [w.a.x, w.a.y], midOf(w), [w.b.x, w.b.y]));
    });
    if (first) for (const i of free) wires[i].mid = null;
    for (let pass = 0; pass < P.PASSES; pass++) {
      let changed = false;
      for (const i of free) {
        const w = wires[i];
        let m = f.best(i);
        m = [round4(m[0]), round4(m[1])];
        if (!w.mid || m[0] !== w.mid[0] || m[1] !== w.mid[1]) { w.mid = m; changed = true; }
        f.place(i, curve(P, [w.a.x, w.a.y], w.mid, [w.b.x, w.b.y]));
      }
      if (!changed) break;
    }
  }

  return { curve, length, candidates, Field, bend, midOf };
})();

if (typeof module !== "undefined") module.exports = Bend;
