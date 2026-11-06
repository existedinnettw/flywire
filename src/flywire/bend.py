"""Bend the wires so that they keep off other pads and off each other.

Each wire is a quadratic Bezier curve from pin to pin, given by the point it passes half
way along (``mid``; its control point is ``2 mid - (a + b) / 2``). For every wire a set of
midpoints, pushed sideways and along the chord by multiples of its length, is scored and the
cheapest kept:

* ``W_PAD`` for every sample of the curve inside a foreign pad's clearance, by how far in;
* ``W_WIRE`` for every sample nearer another wire than ``SEP`` (crossings cost little, a
  wire lying along another a lot), except near a pin both wires end at;
* ``W_OUT`` for leaving the board's bounding box, ``W_LEN`` for every extra mm of wire.

The longest wires are placed first, each against those already placed; then every wire is
placed again against all the others, until nothing changes or ``PASSES`` run out.

``web/bend.js`` is the same algorithm for the interactive page; keep the two in step (the
tests run both on the same board).
"""

from __future__ import annotations

import math

from flywire.board import Board
from flywire.plan import Wire

STEP = 0.5  # mm between samples along a curve
CELL = 2.0  # spatial hash cell, mm
CLEAR = 0.7  # mm kept between a wire's centre line and a foreign pad's edge
SEP = 1.1  # mm kept between two wires' centre lines
SHARE = 2.5  # within this of a shared pin, two wires may touch
W_PAD, W_WIRE, W_OUT, W_LEN, W_OFF = 20.0, 6.0, 50.0, 0.5, 0.05
SIDE = [0.0, 0.8, 1.6, 2.5, 3.5, 5.0, 7.0, 9.5, 12.5, 16.0]  # mm sideways
ALONG = [0.0, -0.2, 0.2]  # fraction of the chord along it
PASSES = 4

Pt = tuple[float, float]


def curve(a: Pt, m: Pt, b: Pt, n: int | None = None) -> list[Pt]:
    cx, cy = 2 * m[0] - (a[0] + b[0]) / 2, 2 * m[1] - (a[1] + b[1]) / 2
    if n is None:
        n = max(
            8, math.ceil((math.hypot(m[0] - a[0], m[1] - a[1]) + math.hypot(b[0] - m[0], b[1] - m[1])) / STEP)
        )
    out = []
    for k in range(n + 1):
        t = k / n
        u = 1 - t
        out.append(
            (u * u * a[0] + 2 * u * t * cx + t * t * b[0], u * u * a[1] + 2 * u * t * cy + t * t * b[1])
        )
    return out


def length(pts: list[Pt]) -> float:
    return sum(math.hypot(pts[k + 1][0] - pts[k][0], pts[k + 1][1] - pts[k][1]) for k in range(len(pts) - 1))


def wire_length(w: Wire) -> float:
    a, b = (w.a.x, w.a.y), (w.b.x, w.b.y)
    m = w.mid or ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    return length(curve(a, m, b, 64))


def candidates(a: Pt, b: Pt) -> list[Pt]:
    dx, dy = b[0] - a[0], b[1] - a[1]
    L = math.hypot(dx, dy)
    mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
    if L < 1e-9:
        return [(mx, my)]
    tx, ty = dx / L, dy / L
    nx, ny = -ty, tx
    limit = max(2.5, 0.6 * L)
    out = [(mx, my)]
    for s in SIDE[1:]:
        if s > limit:
            break
        for sign in (1, -1):
            for f in ALONG:
                u = f * L
                out.append((mx + sign * s * nx + u * tx, my + sign * s * ny + u * ty))
    return out


def cell(x: float, y: float) -> tuple[int, int]:
    return math.floor(x / CELL), math.floor(y / CELL)


class Field:
    """The pads and the wires placed so far, hashed by position."""

    def __init__(self, board: Board, wires: list[Wire]):
        self.wires = wires
        x0, y0, x1, y1 = board.bbox
        self.box = (x0 + 0.5, y0 + 0.5, x1 - 0.5, y1 - 0.5)
        # obstacles: (key, x, y, r); a pin's key is its id, so a wire can skip its own ends
        self.pads: dict[tuple[int, int], list[tuple[str, float, float, float]]] = {}
        for p in board.pins:
            self.pads.setdefault(cell(p.x, p.y), []).append((p.id, p.x, p.y, p.r))
        for k, h in enumerate(board.holes):
            self.pads.setdefault(cell(h.x, h.y), []).append((f"#hole{k}", h.x, h.y, h.r))
        self.samples: list[list[Pt] | None] = [None] * len(wires)
        self.grid: dict[tuple[int, int], list[tuple[int, float, float]]] = {}

    def place(self, i: int, pts: list[Pt] | None) -> None:
        old = self.samples[i]
        if old is not None:
            for c in {cell(x, y) for x, y in old}:
                self.grid[c] = [e for e in self.grid[c] if e[0] != i]
        self.samples[i] = pts
        if pts is not None:
            for x, y in pts:
                self.grid.setdefault(cell(x, y), []).append((i, x, y))

    def cost(self, i: int, m: Pt) -> float:
        w = self.wires[i]
        a, b = (w.a.x, w.a.y), (w.b.x, w.b.y)
        pts = curve(a, m, b)
        chord = math.hypot(b[0] - a[0], b[1] - a[1])
        mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
        c = W_LEN * (length(pts) - chord) + W_OFF * math.hypot(m[0] - mx, m[1] - my)
        ends = {w.a.id: (w.a.x, w.a.y), w.b.id: (w.b.x, w.b.y)}
        bx0, by0, bx1, by1 = self.box
        for x, y in pts[1:-1]:
            out = max(bx0 - x, 0.0, x - bx1) + max(by0 - y, 0.0, y - by1)
            if out > 0:
                c += W_OUT * out
            cx, cy = cell(x, y)
            near: dict[int, float] = {}
            for gx in (cx - 1, cx, cx + 1):
                for gy in (cy - 1, cy, cy + 1):
                    for key, px, py, r in self.pads.get((gx, gy), ()):
                        if key in ends:
                            continue
                        d = math.hypot(x - px, y - py)
                        lim = r + CLEAR
                        if d < lim:
                            c += W_PAD * (lim - d)
                    for j, qx, qy in self.grid.get((gx, gy), ()):
                        if j == i:
                            continue
                        d = math.hypot(x - qx, y - qy)
                        if d < SEP and d < near.get(j, SEP):
                            near[j] = d
            for j, d in near.items():
                o = self.wires[j]
                if any(
                    pid in ends and math.hypot(x - ends[pid][0], y - ends[pid][1]) < SHARE
                    for pid in (o.a.id, o.b.id)
                ):
                    continue
                c += W_WIRE * (SEP - d)
        return c

    def best(self, i: int) -> Pt:
        w = self.wires[i]
        a, b = (w.a.x, w.a.y), (w.b.x, w.b.y)
        best_m, best_c = None, math.inf
        for m in candidates(a, b):
            c = self.cost(i, m)
            if c < best_c - 1e-9:
                best_m, best_c = m, c
        return best_m if best_m is not None else ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)


def mid_or_straight(w: Wire) -> Pt:
    return w.mid or ((w.a.x + w.b.x) / 2, (w.a.y + w.b.y) / 2)


def bend(board: Board, wires: list[Wire]) -> None:
    """Set ``mid`` on every wire that is not ``fixed``."""
    f = Field(board, wires)
    free = sorted((i for i, w in enumerate(wires) if not w.fixed), key=lambda i: (-wires[i].chord, i))
    for i, w in enumerate(wires):
        if w.fixed:
            f.place(i, curve((w.a.x, w.a.y), mid_or_straight(w), (w.b.x, w.b.y)))
    for _ in range(PASSES):
        changed = False
        for i in free:
            w = wires[i]
            m = f.best(i)
            m = (round(m[0], 4), round(m[1], 4))
            if m != w.mid:
                w.mid, changed = m, True
            f.place(i, curve((w.a.x, w.a.y), w.mid, (w.b.x, w.b.y)))
        if not changed:
            break
