# flywire

Point-to-point wiring for building a KiCad board by hand: wire wrap, fly wires on a
perfboard, or a carrier without copper. flywire reads the placed `.kicad_pcb`, joins every
net's through-hole pins with one wire per pair of pins, bends the wires so they keep off
other pads and off each other, and writes:

* `wiring.html`: one self-contained interactive page (no network needed, like
  [InteractiveHtmlBom](https://github.com/openscopeproject/InteractiveHtmlBom)): the board
  seen from the back with the wires as curves, and the wire list beside it;
* `wiring.txt`: the same wire list as text, with pin positions, lengths, cut lengths and
  the wires per pin (which to wrap first);
* `wiring.json`: the wiring, in the form the page exports and `--edits` reads back.

Copper tracks and zones are ignored; SMD pads are too (they do not reach the back).

## use

```bash
uv tool install git+https://github.com/existedinnettw/flywire   # or: uvx --from ... flywire
flywire board.kicad_pcb                      # build/wiring.html, .txt, .json
flywire board.kicad_pcb --max-per-pin 3      # trees instead of chains
flywire board.kicad_pcb --edits wiring.json  # with what you changed on the page
```

| option | |
|---|---|
| `-o DIR`, `--name STEM` | where the files go (`build/wiring.*`) |
| `--max-per-pin N` | wires one pin may take. 2 (default): every net is the shortest chain through its pins; more: the shortest tree whose pins take at most N |
| `--slack MM` | added to every wire's cut length (10) |
| `--edits FILE` | a JSON export from the page: replaces the wires of every net it names, keeping its bends |
| `--straight` | do not bend the wires |

The exit status is 1 when the wiring has problems (a net in pieces, a pin over the limit);
they are listed at the end of `wiring.txt`.

## the page

* Wheel zooms, drag pans, double-click fits; **Back** / **Front** (`F`) flips the view (the
  back, where the wires are, is the default: x is mirrored).
* Click a wire or a row to select it, a pin to show its net; `↑` `↓` step through the list,
  `Space` ticks a wire done (kept in the browser, per board), **Hide done** hides them.
* **Edit** (`E`):
  * drag a wire's round handle to bend it;
  * drag a square end handle onto another pin of the same net to reconnect it;
  * click a pin, then another pin of its net, to add a wire;
  * `Del` deletes, `A` bends automatically, `S` straightens, `Ctrl+Z` undoes;
  * **Auto-bend** bends again every wire not bent by hand; **Reset** goes back to the proposal.
* The box above the list says when a net falls apart or a pin takes too many wires.
* **Export** downloads `wiring.json`; `flywire board.kicad_pcb --edits wiring.json` rebuilds
  the text list and the page with your changes, so they can be committed with the board.

## how the wires are bent

Each wire is a quadratic Bézier from pin to pin, given by the point half way along it. For
every wire a set of such midpoints, pushed sideways and along the chord, is priced: samples
of the curve inside a foreign pad's clearance, near another wire (a crossing costs little, a
wire lying along another a lot, except near a pin both end at), outside the board, and the
extra length. The longest wires go first, then every wire is placed again against all the
others until nothing changes. `src/flywire/bend.py` is the reference;
`src/flywire/web/bend.js` is the same algorithm for the page, and the tests check that the
two agree.

## develop

```bash
uv sync
uv run pytest        # needs node for the Python / JS bender comparison
uv run ruff format src tests && uv run ruff check src tests
```

The page is `src/flywire/web/` (`index.html`, `style.css`, `bend.js`, `app.js`), inlined
into one file with the board data by `report.html()`; it uses no libraries.
