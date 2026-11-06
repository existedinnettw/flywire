"""Read what point-to-point wiring needs from a ``.kicad_pcb``: the through-hole pads with
their nets, the courtyards and the board outline.

Copper tracks and zones are ignored: the wiring is for a bare perfboard or a carrier
without copper. Coordinates are KiCad's (mm, y down), seen from the front.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path

import sexpdata

Shape = tuple  # ("poly", [(x, y), ...]) | ("line", [(x, y), ...]) | ("circle", (x, y), r)


def sym(v) -> str:
    return v.value() if isinstance(v, sexpdata.Symbol) else str(v)


def kids(node: list, name: str) -> list[list]:
    return [c for c in node[1:] if isinstance(c, list) and c and sym(c[0]) == name]


def kid(node: list, name: str) -> list | None:
    found = kids(node, name)
    return found[0] if found else None


def xy(node: list | None) -> tuple[float, float]:
    if node is None:
        raise ValueError("missing coordinate")
    return float(node[1]), float(node[2])


@dataclass
class Pin:
    id: str  # "REF.PAD", unique on the board ("REF.PAD#2" for a repeated pad number)
    ref: str
    pad: str
    name: str  # the symbol's pin name ("A", "SDA/IO21"), or the pad number
    net: str
    x: float
    y: float
    r: float  # half the pad's smaller size, mm

    @property
    def label(self) -> str:
        return f"{self.ref}.{self.pad}" + (f" ({self.name})" if self.name != self.pad else "")


@dataclass
class Hole:
    """A through-hole pad on no net: not wired, but in the way."""

    x: float
    y: float
    r: float


@dataclass
class Footprint:
    ref: str
    value: str
    back: bool
    shapes: list[Shape] = field(default_factory=list)  # courtyard


@dataclass
class Board:
    name: str
    pins: list[Pin]
    holes: list[Hole]
    footprints: list[Footprint]
    edges: list[Shape]  # Edge.Cuts
    bbox: tuple[float, float, float, float]

    def pin(self, pid: str) -> Pin:
        for p in self.pins:
            if p.id == pid:
                return p
        raise KeyError(pid)

    def nets(self) -> dict[str, list[Pin]]:
        nets: dict[str, list[Pin]] = {}
        for p in self.pins:
            nets.setdefault(p.net, []).append(p)
        return nets


def load(path: Path) -> Board:
    tree = sexpdata.loads(Path(path).read_text())
    pins: list[Pin] = []
    holes: list[Hole] = []
    fps: list[Footprint] = []
    edges: list[Shape] = []
    ids: set[str] = set()

    for fp in kids(tree, "footprint"):
        at = kid(fp, "at")
        fx, fy = xy(at)
        rot = float(at[3]) if at is not None and len(at) > 3 else 0.0
        # KiCad turns a footprint counter-clockwise on screen, with y pointing down
        c, s = math.cos(math.radians(rot)), math.sin(math.radians(rot))

        def place(p: tuple[float, float], fx=fx, fy=fy, c=c, s=s) -> tuple[float, float]:
            return fx + p[0] * c + p[1] * s, fy - p[0] * s + p[1] * c

        layer = kid(fp, "layer")
        back = layer is not None and sym(layer[1]).startswith("B.")
        props = {sym(p[1]): sym(p[2]) for p in kids(fp, "property")}
        f = Footprint(props.get("Reference", "?"), props.get("Value", ""), back)
        for pad in kids(fp, "pad"):
            if sym(pad[2]) != "thru_hole":  # only what reaches the back
                continue
            size = kid(pad, "size")
            r = min(float(size[1]), float(size[2])) / 2 if size is not None else 0.8
            px, py = place(xy(kid(pad, "at")))
            net = kid(pad, "net")
            netname = sym(net[-1]) if net else ""
            if not netname or netname.startswith("unconnected-"):
                holes.append(Hole(px, py, r))
                continue
            number = sym(pad[1])
            func = kid(pad, "pinfunction")
            name = sym(func[1]) if func else number
            name = name.removesuffix(f"_{number}") or number  # KiCad appends the pad number
            if re.fullmatch(r"Pin_\d+", name):  # Connector_Generic's names say nothing
                name = number
            pid, k = f"{f.ref}.{number}", 1
            while pid in ids:
                k += 1
                pid = f"{f.ref}.{number}#{k}"
            ids.add(pid)
            pins.append(Pin(pid, f.ref, number, name, netname.lstrip("/"), px, py, r))

        for g in fp[1:]:
            if not (isinstance(g, list) and g and sym(g[0]).startswith("fp_")):
                continue
            gl = kid(g, "layer")
            gl = sym(gl[1]) if gl else ""
            if gl not in ("F.CrtYd", "B.CrtYd", "Edge.Cuts"):
                continue
            shape = local_shape(g)
            if shape is None:
                continue
            if shape[0] == "circle":
                shape = ("circle", place(shape[1]), shape[2])
            else:
                shape = (shape[0], [place(p) for p in shape[1]])
            (edges if gl == "Edge.Cuts" else f.shapes).append(shape)
        fps.append(f)

    for g in tree[1:]:
        if isinstance(g, list) and g and sym(g[0]).startswith("gr_"):
            gl = kid(g, "layer")
            if gl and sym(gl[1]) == "Edge.Cuts" and (shape := local_shape(g)):
                edges.append(shape)

    pts = [p for e in edges if e[0] != "circle" for p in e[1]]
    pts += [
        (e[1][0] + dx * e[2], e[1][1] + dy * e[2])
        for e in edges
        if e[0] == "circle"
        for dx, dy in ((-1, -1), (1, 1))
    ]
    if not pts:  # no outline: the pins with a margin
        m = 3.0
        pts = [(p.x - m, p.y - m) for p in pins] + [(p.x + m, p.y + m) for p in pins]
    if not pts:
        raise ValueError(f"{path}: no through-hole pads and no board outline")
    bbox = (min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts))
    return Board(Path(path).stem, pins, holes, fps, edges, bbox)


def local_shape(g: list) -> Shape | None:
    kind = sym(g[0]).split("_", 1)[1]
    try:
        if kind == "line":
            return ("line", [xy(kid(g, "start")), xy(kid(g, "end"))])
        if kind == "rect":
            (x0, y0), (x1, y1) = xy(kid(g, "start")), xy(kid(g, "end"))
            return ("poly", [(x0, y0), (x1, y0), (x1, y1), (x0, y1)])
        if kind == "circle":
            (cx, cy), (ex, ey) = xy(kid(g, "center")), xy(kid(g, "end"))
            return ("circle", (cx, cy), math.hypot(ex - cx, ey - cy))
        if kind == "arc":
            return ("line", arc_points(xy(kid(g, "start")), xy(kid(g, "mid")), xy(kid(g, "end"))))
        if kind == "poly":
            pts = kid(g, "pts")
            return ("poly", [xy(p) for p in kids(pts, "xy")]) if pts else None
    except (ValueError, TypeError, IndexError):
        return None
    return None


def arc_points(a, m, b, n: int = 32) -> list[tuple[float, float]]:
    """The arc from ``a`` through ``m`` to ``b`` as ``n`` segments."""
    (ax, ay), (mx, my), (bx, by) = a, m, b
    d = 2 * (ax * (my - by) + mx * (by - ay) + bx * (ay - my))
    if abs(d) < 1e-12:
        return [a, b]
    ux = ((ax**2 + ay**2) * (my - by) + (mx**2 + my**2) * (by - ay) + (bx**2 + by**2) * (ay - my)) / d
    uy = ((ax**2 + ay**2) * (bx - mx) + (mx**2 + my**2) * (ax - bx) + (bx**2 + by**2) * (mx - ax)) / d
    r = math.hypot(ax - ux, ay - uy)
    t0, tm, t1 = (math.atan2(p[1] - uy, p[0] - ux) for p in (a, m, b))
    sweep = (t1 - t0) % (2 * math.pi)
    if (tm - t0) % (2 * math.pi) > sweep:  # m is on the other way round
        sweep -= 2 * math.pi
    return [
        (ux + r * math.cos(t0 + sweep * k / n), uy + r * math.sin(t0 + sweep * k / n)) for k in range(n + 1)
    ]
