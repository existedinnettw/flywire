"""flywire: propose point-to-point wires for building a KiCad board by hand.

flywire board.kicad_pcb                      # build/wiring.html, .txt, .json
flywire board.kicad_pcb --edits wiring.json  # with the wiring exported from the page
flywire board.kicad_pcb --max-per-pin 3      # trees instead of chains
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

from flywire import bend, board, plan, report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="flywire",
        description=__doc__.split("\n\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="\n".join(__doc__.split("\n\n")[1:]),
    )
    ap.add_argument("pcb", type=Path, help="the placed board (.kicad_pcb)")
    ap.add_argument(
        "-o", "--out", type=Path, default=Path("build"), help="output directory (default: %(default)s)"
    )
    ap.add_argument("--name", default="wiring", help="output file stem (default: %(default)s)")
    ap.add_argument(
        "--slack", type=float, default=10.0, help="mm added to each wire's cut length (default: %(default)s)"
    )
    ap.add_argument(
        "--max-per-pin",
        type=int,
        default=2,
        help="wires a pin may take: 2 chains each net, more allows trees (default: %(default)s)",
    )
    ap.add_argument(
        "--edits", type=Path, help="wiring exported from the page (Export): replaces the nets it names"
    )
    ap.add_argument("--straight", action="store_true", help="do not bend the wires")
    ap.add_argument("-q", "--quiet", action="store_true", help="do not print the wire list")
    args = ap.parse_args(argv)
    if args.max_per_pin < 2:
        ap.error("--max-per-pin must be at least 2")

    b = board.load(args.pcb)
    wires = plan.propose(b, args.max_per_pin)
    problems: list[str] = []
    if not args.straight:
        bend.bend(b, wires)
    proposed = copy.deepcopy(wires)
    if args.edits:
        edits = json.loads(args.edits.read_text())
        max_per_pin = edits.get("maxPerPin", args.max_per_pin)
        wires, problems = plan.apply_edits(b, wires, edits)
        if not args.straight:
            bend.bend(b, wires)  # only the wires the page left straight
    else:
        max_per_pin = args.max_per_pin
    problems += plan.check(b, wires, max_per_pin)

    args.out.mkdir(parents=True, exist_ok=True)
    txt = report.text(b, wires, args.slack, max_per_pin, problems)
    d = report.data(b, wires, proposed, args.slack, max_per_pin)
    stem = args.out / args.name
    Path(f"{stem}.txt").write_text(txt)
    Path(f"{stem}.html").write_text(report.html(d))
    Path(f"{stem}.json").write_text(
        json.dumps(
            {
                "flywire": 1,
                "board": b.name,
                "maxPerPin": max_per_pin,
                "nets": sorted(n for n, pins in b.nets().items() if len(pins) > 1),
                "wires": d["wires"],
            },
            indent=1,
        )
        + "\n"
    )
    if not args.quiet:
        print(txt, end="")
    print(f"-> {stem}.html, {stem}.txt, {stem}.json", file=sys.stderr)
    for p in problems:
        print(f"warning: {p}", file=sys.stderr)
    return 1 if problems else 0
