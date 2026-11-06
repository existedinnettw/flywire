from __future__ import annotations

from pathlib import Path

import pytest

GAS_MONI_B = Path(__file__).resolve().parents[2] / "gas_moni_b" / "gas_moni_b.kicad_pcb"


def footprint(
    ref: str,
    at: tuple[float, float],
    pads: list[tuple[str, float, float, str]],
    rot: float = 0,
    crt: tuple[float, float, float, float] | None = None,
) -> str:
    """A footprint with through-hole pads (number, x, y, net) at local positions."""
    ps = []
    for k, (num, x, y, net) in enumerate(pads):
        n = f'(net {k} "{net}")' if net else ""
        ps.append(
            f'(pad "{num}" thru_hole circle (at {x} {y}) (size 1.6 1.6) (drill 0.9) '
            f'(layers "*.Cu" "*.Mask") {n} (pinfunction "P{num}"))'
        )
    c = f'(fp_rect (start {crt[0]} {crt[1]}) (end {crt[2]} {crt[3]}) (layer "F.CrtYd"))' if crt else ""
    return (
        f'(footprint "lib:fp" (layer "F.Cu") (at {at[0]} {at[1]} {rot}) '
        f'(property "Reference" "{ref}") (property "Value" "v") {c} {" ".join(ps)})'
    )


def make_board(path: Path, footprints: list[str], outline=(0, 0, 50, 40)) -> Path:
    x0, y0, x1, y1 = outline
    path.write_text(
        '(kicad_pcb (version 20240108) (generator "test") '
        + " ".join(footprints)
        + f' (gr_rect (start {x0} {y0}) (end {x1} {y1}) (layer "Edge.Cuts")))\n'
    )
    return path


@pytest.fixture
def column_board(tmp_path) -> Path:
    """Two 1x8 headers side by side whose nets chain straight down a column: the straight
    wires would run over the pads between and lie on each other."""
    g = 2.54
    left = [(str(i + 1), 0, i * g, "") for i in range(8)]
    left[0] = ("1", 0, 0, "GND")
    left[3] = ("4", 0, 3 * g, "GND")
    left[7] = ("8", 0, 7 * g, "GND")
    left[1] = ("2", 0, g, "VCC")
    left[5] = ("6", 0, 5 * g, "VCC")
    right = [(str(i + 1), 0, i * g, "") for i in range(8)]
    right[2] = ("3", 0, 2 * g, "SIG")
    right[6] = ("7", 0, 6 * g, "SIG")
    right[4] = ("5", 0, 4 * g, "VCC")
    left[6] = ("7", 0, 6 * g, "SIG")
    return make_board(
        tmp_path / "column.kicad_pcb",
        [
            footprint("J1", (10, 10), left, crt=(-1.5, -1.5, 1.5, 19.3)),
            footprint("J2", (12.54, 10), right, rot=0),
            footprint(
                "U1",
                (30, 15),
                [("1", 0, 0, "GND"), ("2", 2.54, 0, "VCC"), ("3", 5.08, 0, "SIG"), ("4", 7.62, 0, "SIG")],
                rot=90,
            ),
        ],
    )
