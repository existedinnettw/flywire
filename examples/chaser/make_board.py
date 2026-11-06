"""Write ``chaser.kicad_pcb``: a 555 clocking a CD4017 that walks four LEDs, placed on a
2.54 mm perfboard grid with KiCad's stock through-hole footprints and no copper.

It is the board the GitHub Pages demo wires. It needs KiCad's Python module (``pcbnew``),
so run it with the system Python KiCad installs, not the project's environment:

    /usr/bin/python3 examples/chaser/make_board.py
"""

from __future__ import annotations

from pathlib import Path

import pcbnew

FP = Path("/usr/share/kicad/footprints")
G = 2.54  # perfboard pitch, mm
ORIGIN = (100.0, 80.0)  # where grid (0, 0) sits on KiCad's sheet

# ref, library, footprint, value, grid (col, row), rotation, {pad: (name, net)}
PARTS = [
    (
        "J1",
        "Connector_PinHeader_2.54mm",
        "PinHeader_1x02_P2.54mm_Vertical",
        "5V in",
        (2, 7),
        0,
        {"1": ("+5V", "VCC"), "2": ("GND", "GND")},
    ),
    (
        "R1",
        "Resistor_THT",
        "R_Axial_DIN0207_L6.3mm_D2.5mm_P7.62mm_Horizontal",
        "1k",
        (6, 2),
        0,
        {"1": ("1", "VCC"), "2": ("2", "DIS")},
    ),
    (
        "R2",
        "Resistor_THT",
        "R_Axial_DIN0207_L6.3mm_D2.5mm_P7.62mm_Horizontal",
        "68k",
        (6, 4),
        0,
        {"1": ("1", "DIS"), "2": ("2", "THR")},
    ),
    (
        "U1",
        "Package_DIP",
        "DIP-8_W7.62mm",
        "NE555",
        (6, 7),
        0,
        {
            "1": ("GND", "GND"),
            "2": ("TRIG", "THR"),
            "3": ("OUT", "CLK"),
            "4": ("/RESET", "VCC"),
            "5": ("CV", "CV"),
            "6": ("THR", "THR"),
            "7": ("DIS", "DIS"),
            "8": ("VCC", "VCC"),
        },
    ),
    (
        "C1",
        "Capacitor_THT",
        "CP_Radial_D5.0mm_P2.50mm",
        "10u",
        (6, 13),
        0,
        {"1": ("+", "THR"), "2": ("-", "GND")},
    ),
    (
        "C2",
        "Capacitor_THT",
        "C_Disc_D3.0mm_W1.6mm_P2.50mm",
        "10n",
        (10, 13),
        0,
        {"1": ("1", "CV"), "2": ("2", "GND")},
    ),
    (
        "C3",
        "Capacitor_THT",
        "C_Disc_D3.0mm_W1.6mm_P2.50mm",
        "100n",
        (14, 2),
        0,
        {"1": ("1", "VCC"), "2": ("2", "GND")},
    ),
    (
        "U2",
        "Package_DIP",
        "DIP-16_W7.62mm",
        "CD4017",
        (14, 5),
        0,
        {
            "1": ("Q5", ""),
            "2": ("Q1", "Q1"),
            "3": ("Q0", "Q0"),
            "4": ("Q2", "Q2"),
            "5": ("Q6", ""),
            "6": ("Q7", ""),
            "7": ("Q3", "Q3"),
            "8": ("VSS", "GND"),
            "9": ("Q8", ""),
            "10": ("Q4", "RST"),
            "11": ("Q9", ""),
            "12": ("CO", ""),
            "13": ("/CE", "GND"),
            "14": ("CLK", "CLK"),
            "15": ("RST", "RST"),
            "16": ("VDD", "VCC"),
        },
    ),
]
for k in range(4):
    row = 4 + 2 * k
    PARTS += [
        (
            f"R{4 + k}",
            "Resistor_THT",
            "R_Axial_DIN0207_L6.3mm_D2.5mm_P7.62mm_Horizontal",
            "470",
            (20, row),
            0,
            {"1": ("1", f"Q{k}"), "2": ("2", f"LED{k}")},
        ),
        # turned round so the anode faces its resistor
        (
            f"D{1 + k}",
            "LED_THT",
            "LED_D3.0mm",
            "red",
            (27, row),
            180,
            {"1": ("K", "GND"), "2": ("A", f"LED{k}")},
        ),
    ]
OUTLINE = ((0, 0), (29, 15))  # grid


def mm(col: float, row: float) -> pcbnew.VECTOR2I:
    return pcbnew.VECTOR2I_MM(ORIGIN[0] + col * G, ORIGIN[1] + row * G)


def main() -> None:
    board = pcbnew.BOARD()
    nets: dict[str, pcbnew.NETINFO_ITEM] = {}
    for ref, lib, name, value, (col, row), rot, pads in PARTS:
        fp = pcbnew.FootprintLoad(str(FP / f"{lib}.pretty"), name)
        fp.SetReference(ref)
        fp.SetValue(value)
        fp.SetPosition(mm(col, row))
        fp.SetOrientationDegrees(rot)
        board.Add(fp)
        for pad in fp.Pads():
            pin, net = pads[pad.GetNumber()]
            pad.SetPinFunction(pin)
            if net:
                if net not in nets:
                    nets[net] = pcbnew.NETINFO_ITEM(board, net)
                    board.Add(nets[net])
                pad.SetNet(nets[net])

    edge = pcbnew.PCB_SHAPE(board)
    edge.SetShape(pcbnew.SHAPE_T_RECT)
    edge.SetStart(mm(*OUTLINE[0]))
    edge.SetEnd(mm(*OUTLINE[1]))
    edge.SetLayer(pcbnew.Edge_Cuts)
    edge.SetWidth(pcbnew.FromMM(0.1))
    board.Add(edge)

    out = Path(__file__).with_name("chaser.kicad_pcb")
    board.Save(str(out))
    print(out)


if __name__ == "__main__":
    main()
