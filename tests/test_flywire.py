from __future__ import annotations

import json
import math
import shutil
import subprocess

import pytest
from conftest import GAS_MONI_B

from flywire import bend, board, cli, plan, report


def samples(w: plan.Wire) -> list[tuple[float, float]]:
    return bend.curve((w.a.x, w.a.y), w.mid, (w.b.x, w.b.y))


def test_load(column_board):
    b = board.load(column_board)
    assert {p.ref for p in b.pins} == {"J1", "J2", "U1"}
    assert len(b.holes) == 16 - 9  # the header pins on no net
    u1 = {p.pad: p for p in b.pins if p.ref == "U1"}
    # turned 90 degrees counter-clockwise on screen: local +x goes up (-y)
    assert (u1["2"].x, u1["2"].y) == pytest.approx((30, 15 - 2.54))
    assert u1["2"].name == "P2" and u1["2"].label == "U1.2 (P2)"
    assert b.bbox == (0, 0, 50, 40)
    assert [len(f.shapes) for f in b.footprints if f.ref == "J1"] == [1]


def test_chains(column_board):
    b = board.load(column_board)
    wires = plan.propose(b)
    assert plan.check(b, wires, 2) == []
    nets = {}
    for w in wires:
        nets.setdefault(w.net, []).append(w)
    for net, pins in b.nets().items():
        assert len(nets[net]) == len(pins) - 1
    # ground first, then power, then signals
    assert [w.net for w in wires] == sorted((w.net for w in wires), key=["GND", "VCC", "SIG"].index)
    # numbered in order, reading from the hub (U1 has 4 pins... J1 has more: the hub)
    assert [w.no for w in wires] == list(range(1, len(wires) + 1))
    assert plan.hub(b) == "J1"


def test_trees(column_board):
    b = board.load(column_board)
    wires = plan.propose(b, max_per_pin=3)
    assert plan.check(b, wires, 3) == []
    assert sum(1 for w in wires if w.net == "SIG") == 4  # five pins


def test_check_finds_problems(column_board):
    b = board.load(column_board)
    wires = plan.propose(b)
    gnd = [w for w in wires if w.net == "GND"]
    wires.remove(gnd[0])
    wires.append(plan.Wire(99, "VCC", b.pin("J1.2"), b.pin("J1.2")))
    probs = plan.check(b, wires, 2)
    assert any("GND is in 2 pieces" in p for p in probs)
    assert any("to itself" in p for p in probs)
    assert any("J1.2 takes" in p for p in probs)


def test_bend_keeps_off_pads_and_wires(column_board):
    b = board.load(column_board)
    wires = plan.propose(b)
    straight = bend.Field(b, wires)
    for i, w in enumerate(wires):
        w.mid = ((w.a.x + w.b.x) / 2, (w.a.y + w.b.y) / 2)
        straight.place(i, samples(w))
    before = sum(straight.cost(i, w.mid) for i, w in enumerate(wires))
    for w in wires:
        w.mid = None
    bend.bend(b, wires)
    f = bend.Field(b, wires)
    for i, w in enumerate(wires):
        f.place(i, samples(w))
    after = sum(f.cost(i, w.mid) for i, w in enumerate(wires))
    assert after < before / 4

    # no curve runs over a pad it does not end at
    obstacles = [(p.id, p.x, p.y, p.r) for p in b.pins] + [("h", h.x, h.y, h.r) for h in b.holes]
    for w in wires:
        for x, y in samples(w)[1:-1]:
            for pid, px, py, r in obstacles:
                if pid not in (w.a.id, w.b.id):
                    assert math.hypot(x - px, y - py) > r, (w.no, pid)
    # and no two wires lie along each other: few samples near another wire
    for w in wires:
        for o in wires:
            if o is w:
                continue
            ends = {w.a.id: w.a, w.b.id: w.b}
            shared = [ends[k] for k in (o.a.id, o.b.id) if k in ends]
            near = sum(
                1
                for x, y in samples(w)
                if not any(math.hypot(x - p.x, y - p.y) < bend.SHARE for p in shared)
                and min(math.hypot(x - qx, y - qy) for qx, qy in samples(o)) < 0.5
            )
            assert near <= 3, (w.no, o.no, near)


def test_cli_round_trip(column_board, tmp_path):
    out = tmp_path / "out"
    assert cli.main([str(column_board), "-o", str(out), "-q"]) == 0
    html = (out / "wiring.html").read_text()
    assert "/*" + "DATA*/" not in html and "{{TITLE}}" not in html
    assert '"generator":"flywire' in html
    txt = (out / "wiring.txt").read_text()
    assert "column point-to-point wiring" in txt and "PROBLEMS" not in txt
    exported = json.loads((out / "wiring.json").read_text())

    # an edit: move one wire's end and bend another by hand
    sig = [w for w in exported["wires"] if w["net"] == "SIG"]
    sig[0]["mid"] = [40.0, 30.0]
    edits = tmp_path / "edits.json"
    edits.write_text(json.dumps(exported))
    out2 = tmp_path / "out2"
    assert cli.main([str(column_board), "-o", str(out2), "-q", "--edits", str(edits)]) == 0
    again = json.loads((out2 / "wiring.json").read_text())
    assert [(w["a"], w["b"]) for w in again["wires"]] == [(w["a"], w["b"]) for w in exported["wires"]]
    assert [40.0, 30.0] in [w["mid"] for w in again["wires"]]

    # a broken edit is reported and fails the run
    exported["wires"] = [w for w in exported["wires"] if w["net"] != "SIG"] + [
        {"net": "SIG", "a": "J1.7", "b": "U1.1"}
    ]
    edits.write_text(json.dumps(exported))
    assert cli.main([str(column_board), "-o", str(out2), "-q", "--edits", str(edits)]) == 1
    assert "PROBLEMS" in (out2 / "wiring.txt").read_text()


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_js_bender_matches(column_board, tmp_path):
    """web/bend.js prices every wire as bend.py does, and bends them the same way."""
    b = board.load(column_board)
    wires = plan.propose(b)
    bend.bend(b, wires)
    d = report.data(b, wires, wires, 10, 2)
    f = bend.Field(b, wires)
    for i, w in enumerate(wires):
        f.place(i, samples(w))
    costs = [f.cost(i, w.mid) for i, w in enumerate(wires)]
    js = tmp_path / "run.js"
    js.write_text("""
const Bend = require(process.argv[2]);
const D = JSON.parse(require("fs").readFileSync(process.argv[3], "utf8"));
const pins = new Map(D.pins.map((p) => [p.id, p]));
const wires = D.wires.map((w) => ({ a: pins.get(w.a), b: pins.get(w.b), mid: w.mid, fixed: false }));
const f = new Bend.Field(D.bend, D.pins, D.holes, D.bbox, wires);
wires.forEach((w, i) => f.place(i, Bend.curve(D.bend, [w.a.x, w.a.y], w.mid, [w.b.x, w.b.y])));
const costs = wires.map((w, i) => f.cost(i, w.mid));
Bend.bend(D.bend, D.pins, D.holes, D.bbox, wires);
console.log(JSON.stringify({ costs, mids: wires.map((w) => w.mid) }));
""")
    data = tmp_path / "data.json"
    data.write_text(json.dumps(d))
    web = board.Path(bend.__file__).parent / "web" / "bend.js"
    r = json.loads(
        subprocess.run(
            ["node", str(js), str(web), str(data)], capture_output=True, text=True, check=True
        ).stdout
    )
    assert r["costs"] == pytest.approx(costs, abs=1e-6)
    assert [tuple(m) for m in r["mids"]] == [w.mid for w in wires]


@pytest.mark.skipif(not GAS_MONI_B.exists(), reason="gas_moni_b is not checked out next to flywire")
def test_gas_moni_b(tmp_path):
    b = board.load(GAS_MONI_B)
    wires = plan.propose(b)
    assert len(wires) == 24
    assert plan.check(b, wires, 2) == []
    bend.bend(b, wires)
    # the four sensors' GND and VCC chains run down one column; bent, they no longer share it
    assert all(
        w.mid != ((w.a.x + w.b.x) / 2, (w.a.y + w.b.y) / 2)
        for w in wires
        if w.a.x == w.b.x and abs(w.a.y - w.b.y) > 10
    )
