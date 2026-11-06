"""The wire list as plain text, and the data the interactive page is built from."""

from __future__ import annotations

import json
from importlib import resources

from flywire import __version__, bend
from flywire.board import Board, Pin
from flywire.plan import Wire, colours

GRID = 2.54


class View:
    """Board coordinates as seen from one side: mm from the top-left corner (x mirrored on
    the back), and the 2.54 mm grid column / row counted from the top-left pin, if the pins
    are on such a grid."""

    def __init__(self, board: Board, back: bool = True):
        self.back = back
        self.x0, self.y0, self.x1, self.y1 = board.bbox
        pts = [self.at(p) for p in board.pins]
        self.gx = min((x for x, _ in pts), default=0.0)
        self.gy = min((y for _, y in pts), default=0.0)
        on = sum(1 for p in board.pins if not self.grid(p).endswith("!"))
        self.gridded = bool(board.pins) and on >= 0.8 * len(board.pins)

    def at(self, p: Pin) -> tuple[float, float]:
        return (self.x1 - p.x if self.back else p.x - self.x0), p.y - self.y0

    def grid(self, p: Pin) -> str:
        x, y = self.at(p)
        c, r = (x - self.gx) / GRID, (y - self.gy) / GRID
        if abs(c - round(c)) > 0.02 or abs(r - round(r)) > 0.02:
            return f"({c:.2f},{r:.2f})!"  # off the grid
        return f"C{round(c) + 1:02d}R{round(r) + 1:02d}"

    def where(self, p: Pin) -> str:
        x, y = self.at(p)
        return (self.grid(p) + " " if self.gridded else "") + f"{x:5.1f},{y:4.1f}"


def text(board: Board, wires: list[Wire], slack: float, max_per_pin: int, problems: list[str]) -> str:
    view = View(board)
    cols = colours(sorted({w.net for w in wires}))
    w_, h_ = view.x1 - view.x0, view.y1 - view.y0
    out = [
        f"{board.name} point-to-point wiring, seen from the BACK (x mirrored); board {w_:.2f} x {h_:.2f} mm",
        f"{len(wires)} wires; each joins two pins, each pin takes at most {max_per_pin} wires.",
        "Positions: mm from the top-left corner of the back"
        + ("; grid CccRrr: 2.54 mm column / row from the top-left pin." if view.gridded else "."),
        f"Length along the drawn curve; cut = length + {slack:g} mm slack (strip and wrap allowance not included).",
        "",
    ]
    wa = max([len(w.a.label) for w in wires] + [4])
    wb = max([len(w.b.label) for w in wires] + [2])
    wn = max([len(w.net) for w in wires] + [3])
    ww = max([len(view.where(w.a)) for w in wires] + [2])
    out.append(
        f"{'#':>3}  {'net':<{wn}} {'colour':<7} {'from':<{wa}} {'at':<{ww}}  {'to':<{wb}} "
        f"{'at':<{ww}}  {'mm':>5} {'cut':>4}"
    )
    net = None
    total = 0.0
    for w in wires:
        if w.net != net:
            if net is not None:
                out.append("")
            net = w.net
        L = bend.wire_length(w)
        total += L
        out.append(
            f"{w.no:>3}  {w.net:<{wn}} {cols[w.net][0]:<7} {w.a.label:<{wa}} {view.where(w.a):<{ww}}  "
            f"{w.b.label:<{wb}} {view.where(w.b):<{ww}}  {L:5.1f} {L + slack:4.0f}"
        )
    out += ["", f"total length {total:.0f} mm, cut {total + slack * len(wires):.0f} mm", ""]

    count: dict[str, list[int]] = {}
    for w in wires:
        for p in (w.a, w.b):
            count.setdefault(p.id, []).append(w.no)
    out.append("Wires per pin (wrap the lower number first, it sits nearest the board):")
    for ref in sorted({p.ref for p in board.pins}):
        pins = sorted((p for p in board.pins if p.ref == ref), key=lambda p: (len(p.pad), p.pad))
        cells = [f"{p.pad}:{'+'.join(map(str, count.get(p.id, []))) or '-'}" for p in pins]
        out.append(f"  {ref:<4} " + "  ".join(cells))
    if problems:
        out += ["", "PROBLEMS:"] + [f"  {p}" for p in problems]
    return "\n".join(out) + "\n"


def data(board: Board, wires: list[Wire], proposed: list[Wire], slack: float, max_per_pin: int) -> dict:
    """Everything the page needs: the board, the wires (``proposed``: before any edits, for
    the page's Reset) and the bender's parameters."""
    r3 = lambda v: round(v, 3)

    def shape(s):
        if s[0] == "circle":
            return {"k": "circle", "c": [r3(s[1][0]), r3(s[1][1])], "r": r3(s[2])}
        return {"k": s[0], "pts": [[r3(x), r3(y)] for x, y in s[1]]}

    def wire(w: Wire):
        return {
            "net": w.net,
            "a": w.a.id,
            "b": w.b.id,
            "mid": list(w.mid) if w.mid else None,
            "fixed": w.fixed,
        }

    nets = board.nets()
    cols = colours(list(nets))
    return {
        "generator": f"flywire {__version__}",
        "title": board.name,
        "maxPerPin": max_per_pin,
        "slack": slack,
        "bbox": [r3(v) for v in board.bbox],
        "edges": [shape(s) for s in board.edges],
        "footprints": [
            {"ref": f.ref, "value": f.value, "back": f.back, "shapes": [shape(s) for s in f.shapes]}
            for f in board.footprints
        ],
        "holes": [[r3(h.x), r3(h.y), r3(h.r)] for h in board.holes],
        "pins": [
            {
                "id": p.id,
                "ref": p.ref,
                "pad": p.pad,
                "name": p.name,
                "net": p.net,
                "x": r3(p.x),
                "y": r3(p.y),
                "r": r3(p.r),
            }
            for p in board.pins
        ],
        "nets": [{"name": n, "colour": cols[n][0], "hex": cols[n][1]} for n in cols],
        "wires": [wire(w) for w in wires],
        "proposed": [wire(w) for w in proposed],
        "bend": {
            k: getattr(bend, k)
            for k in (
                "STEP",
                "CELL",
                "CLEAR",
                "SEP",
                "SHARE",
                "W_PAD",
                "W_WIRE",
                "W_OUT",
                "W_LEN",
                "W_OFF",
                "SIDE",
                "ALONG",
                "PASSES",
            )
        },
    }


def html(d: dict) -> str:
    web = resources.files("flywire") / "web"
    page = (web / "index.html").read_text()
    payload = json.dumps(d, separators=(",", ":")).replace("</", "<\\/")
    for key, value in (
        ("/*CSS*/", (web / "style.css").read_text()),
        ("/*BEND*/", (web / "bend.js").read_text()),
        ("/*APP*/", (web / "app.js").read_text()),
        ("/*DATA*/", payload),
        ("{{TITLE}}", d["title"].replace("&", "&amp;").replace("<", "&lt;")),
    ):
        page = page.replace(key, value)
    return page
