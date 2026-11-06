"""Which pins each wire joins.

Every net's pins are joined with one wire per pair of pins. With at most two wires per pin
(the default, what one wire-wrap post takes comfortably) a net is a chain, the shortest one
through its pins; with more, it is the shortest tree whose pins take at most that many.
"""

from __future__ import annotations

import itertools
import math
import re
from dataclasses import dataclass

from flywire.board import Board, Pin

# wire colours: power and ground as usual, I2C as on Gravity / Qwiic cables, the rest in
# turn from PALETTE
GROUND = re.compile(r"^(A|D|P)?GND\d*$|^VSS|^0V$", re.IGNORECASE)
POWER = re.compile(r"^\+|^V(CC|DD|BUS|IN|BAT)|^\d+V\d*($|_)", re.IGNORECASE)
NAMED_COLOURS = {"SCL": ("blue", "#1f5fd6"), "SDA": ("green", "#2ca02c")}
BLACK, RED = ("black", "#222222"), ("red", "#d62728")
PALETTE = [
    ("yellow", "#d4a400"),
    ("orange", "#ff7f0e"),
    ("violet", "#9467bd"),
    ("brown", "#8c564b"),
    ("white", "#9a9a9a"),
    ("grey", "#5f6b73"),
    ("pink", "#e377c2"),
    ("cyan", "#17becf"),
    ("olive", "#9a9a2a"),
]


def is_ground(net: str) -> bool:
    return bool(GROUND.search(net.rsplit("/", 1)[-1]))


def is_power(net: str) -> bool:
    return not is_ground(net) and bool(POWER.search(net.rsplit("/", 1)[-1]))


@dataclass
class Wire:
    no: int
    net: str
    a: Pin
    b: Pin
    mid: tuple[float, float] | None = None  # the curve's middle; None: straight until bent
    fixed: bool = False  # mid was set by hand: keep it

    @property
    def chord(self) -> float:
        return dist(self.a, self.b)


def dist(a: Pin, b: Pin) -> float:
    return math.hypot(a.x - b.x, a.y - b.y)


def net_order(nets) -> list[str]:
    """Ground first, then power (they are the longest and go in at the bottom of the wraps),
    then signals by name."""
    return sorted(nets, key=lambda n: (not is_ground(n), not is_power(n), n))


def colours(nets: list[str], given: dict[str, tuple[str, str]] | None = None) -> dict[str, tuple[str, str]]:
    given = given or {}
    palette = itertools.cycle(PALETTE)
    out = {}
    for n in net_order(nets):
        leaf = n.rsplit("/", 1)[-1].upper()
        if n in given:
            out[n] = given[n]
        elif is_ground(n):
            out[n] = BLACK
        elif is_power(n):
            out[n] = RED
        elif leaf in NAMED_COLOURS:
            out[n] = NAMED_COLOURS[leaf]
        else:
            out[n] = next(palette)
    return out


def shortest_chain(pins: list[Pin]) -> list[Pin]:
    """The shortest open path through all ``pins`` (Held-Karp; 2-opt above 13 pins)."""
    n = len(pins)
    if n <= 2:
        return list(pins)
    d = [[dist(a, b) for b in pins] for a in pins]
    if n <= 13:
        best: dict[tuple[int, int], tuple[float, int]] = {(1 << i, i): (0.0, -1) for i in range(n)}
        for size in range(2, n + 1):
            for subset in itertools.combinations(range(n), size):
                mask = sum(1 << i for i in subset)
                for last in subset:
                    prev = mask & ~(1 << last)
                    best[(mask, last)] = min(
                        (best[(prev, p)][0] + d[p][last], p) for p in subset if p != last
                    )
        full = (1 << n) - 1
        last = min(range(n), key=lambda i: best[(full, i)][0])
        order, mask = [], full
        while last != -1:
            order.append(last)
            last, mask = best[(mask, last)][1], mask & ~(1 << last)
        return [pins[i] for i in reversed(order)]

    def length(o):
        return sum(d[o[i]][o[i + 1]] for i in range(len(o) - 1))

    tours = []  # nearest neighbour from every start, then 2-opt
    for start in range(n):
        o, left = [start], set(range(n)) - {start}
        while left:
            o.append(min(left, key=lambda j: (d[o[-1]][j], j)))
            left.remove(o[-1])
        tours.append(o)
    o = min(tours, key=length)
    better = True
    while better:
        better = False
        for i in range(n - 1):
            for j in range(i + 2, n + 1):
                cand = o[:i] + o[i:j][::-1] + o[j:]
                if length(cand) < length(o) - 1e-9:
                    o, better = cand, True
    return [pins[i] for i in o]


def capped_tree(pins: list[Pin], cap: int) -> list[tuple[Pin, Pin]]:
    """The shortest spanning tree whose pins take at most ``cap`` wires (Kruskal, skipping
    edges into full pins; a net it cannot finish that way gets its shortest remaining
    edges regardless)."""
    n = len(pins)
    edges = sorted((dist(pins[i], pins[j]), i, j) for i in range(n) for j in range(i + 1, n))
    root = list(range(n))

    def find(i):
        while root[i] != i:
            root[i] = root[root[i]]
            i = root[i]
        return i

    deg = [0] * n
    chosen = []
    for strict in (True, False):
        for _, i, j in edges:
            if len(chosen) == n - 1:
                break
            if find(i) == find(j) or (strict and (deg[i] >= cap or deg[j] >= cap)):
                continue
            root[find(i)] = find(j)
            deg[i] += 1
            deg[j] += 1
            chosen.append((pins[i], pins[j]))
    return chosen


def hub(board: Board) -> str:
    """The footprint with the most wired pins: the controller, which the wires read from."""
    count: dict[str, int] = {}
    for p in board.pins:
        count[p.ref] = count.get(p.ref, 0) + 1
    return max(sorted(count), key=lambda r: count[r]) if count else ""


def from_hub(pairs: list[tuple[Pin, Pin]], start_ref: str) -> list[tuple[Pin, Pin]]:
    """``pairs`` (a tree) depth first from the hub's pin (or, failing that, from an end), each
    pair pointing away from it: the wires then read from the controller outwards, one arm
    after the other."""
    if not pairs:
        return []
    adj: dict[str, list[tuple[Pin, int]]] = {}
    for k, (a, b) in enumerate(pairs):
        adj.setdefault(a.id, []).append((b, k))
        adj.setdefault(b.id, []).append((a, k))
    pins = {p.id: p for pr in pairs for p in pr}
    starts = sorted(pins.values(), key=lambda p: (p.ref != start_ref, len(adj[p.id]) != 1, p.ref, p.pad))
    out: list[tuple[Pin, Pin]] = []
    seen: set[int] = set()

    for s in starts:
        stack = [(s, iter(adj[s.id]))]  # depth first, without recursion (nets can be long)
        while stack:
            p, it = stack[-1]
            for q, k in it:
                if k not in seen:
                    seen.add(k)
                    out.append((p, q))
                    stack.append((q, iter(adj[q.id])))
                    break
            else:
                stack.pop()
    return out


def propose(board: Board, max_per_pin: int = 2) -> list[Wire]:
    nets = board.nets()
    start = hub(board)
    wires: list[Wire] = []
    for net in net_order(nets):
        pins = sorted(nets[net], key=lambda p: (p.ref, p.pad))
        if len(pins) < 2:
            continue
        if max_per_pin <= 2:
            chain = shortest_chain(pins)
            pairs = list(itertools.pairwise(chain))
        else:
            pairs = capped_tree(pins, max_per_pin)
        for a, b in from_hub(pairs, start):
            wires.append(Wire(len(wires) + 1, net, a, b))
    return wires


def apply_edits(board: Board, wires: list[Wire], edits: dict) -> tuple[list[Wire], list[str]]:
    """Replace the proposed wires of every net ``edits`` names (an ``flywire`` JSON export)
    with its wires. Returns the wires and what could not be applied."""
    pins = {p.id: p for p in board.pins}
    problems = []
    taken = set(edits.get("nets") or [w["net"] for w in edits.get("wires", [])])
    out = [w for w in wires if w.net not in taken]
    for e in edits.get("wires", []):
        a, b = pins.get(e.get("a")), pins.get(e.get("b"))
        if a is None or b is None:
            problems.append(f"edited wire {e.get('a')} - {e.get('b')}: no such pin on the board")
            continue
        if a.net != b.net:
            problems.append(f"edited wire {a.id} - {b.id}: {a.net} and {b.net} are different nets")
            continue
        mid = e.get("mid")
        out.append(Wire(0, a.net, a, b, tuple(mid) if mid else None, bool(mid)))
    order = {n: i for i, n in enumerate(net_order({w.net for w in out}))}
    out.sort(key=lambda w: order[w.net])  # stable: a net's wires keep their order
    for i, w in enumerate(out):
        w.no = i + 1
    return out, problems


def check(board: Board, wires: list[Wire], max_per_pin: int) -> list[str]:
    """What is wrong with ``wires``: nets left in pieces, pins over the limit, repeats."""
    problems = []
    deg: dict[str, int] = {}
    seen = set()
    for w in wires:
        if w.a.id == w.b.id:
            problems.append(f"wire {w.no} joins {w.a.id} to itself")
        key = tuple(sorted((w.a.id, w.b.id)))
        if key in seen:
            problems.append(f"wire {w.no} repeats {key[0]} - {key[1]}")
        seen.add(key)
        for p in (w.a, w.b):
            deg[p.id] = deg.get(p.id, 0) + 1
    for pid, n in deg.items():
        if n > max_per_pin:
            problems.append(f"{pid} takes {n} wires (limit {max_per_pin})")
    for net, pins in board.nets().items():
        if len(pins) < 2:
            continue
        root = {p.id: p.id for p in pins}

        for w in wires:
            if w.net == net and w.a.id in root and w.b.id in root:
                root[_find(root, w.a.id)] = _find(root, w.b.id)
        groups = {_find(root, p.id) for p in pins}
        if len(groups) > 1:
            problems.append(f"{net} is in {len(groups)} pieces")
    return problems


def _find(root: dict[str, str], i: str) -> str:
    while root[i] != i:
        i = root[i]
    return i
