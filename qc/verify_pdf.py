#!/usr/bin/env python3
"""Rendered-PDF verification for the fake book QC pass.

Three jobs:
  snapshot  — dump per-character (text, font, size, x0, y0) for every page,
              used as a golden file to prove renderer changes don't move
              anything they shouldn't.
  compare   — diff two snapshots under the Layer-0 renderer-fix contract:
              lyric chars byte-identical, chord tokens moved onto the
              lyric column grid (x = MARGIN_LEFT + col * CHAR_W).
  overflow  — assert no ink past the right margin (the build's usable width).

Chord vs lyric lines are distinguished by font, which is robust here because
build.py renders chords in Courier-Bold and lyrics in Courier — no heuristics.
"""

import json
import sys
from pathlib import Path

import pdfplumber

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "fakebook"))
import build  # noqa: E402  (reuses MARGIN_LEFT etc. — single source of truth)

MARGIN_LEFT = build.MARGIN_LEFT          # 43.2
RIGHT_EDGE = build.PAGE_W - build.MARGIN_RIGHT  # 568.8
LYRIC_CHAR_W = 0.6 * build.LYRIC_SIZE    # 7.2 — the master column grid
TOL = 0.5  # pt

CHORD_FONT = "Courier-Bold"
LYRIC_FONT = "Courier"


def snapshot(pdf_path: Path) -> dict:
    pages = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            chars = [
                [c["text"], c["fontname"], round(c["size"], 2),
                 round(c["x0"], 3), round(c["x1"], 3), round(c["top"], 3)]
                for c in page.chars
            ]
            pages.append({"page": page.page_number, "chars": chars})
    return {"pdf": str(pdf_path), "pages": pages}


def _tokens(chars):
    """Group same-line (font,size,y) chars into whitespace-separated tokens.

    Returns list of (font, size, y, x0, x1, text) using real char extents.
    """
    from collections import defaultdict
    lines = defaultdict(list)
    for text, font, size, x0, x1, y in chars:
        lines[(font, size, round(y, 1))].append((x0, x1, text))
    toks = []
    for (font, size, y), cs in lines.items():
        cs.sort()
        cur = None  # [x0, x1, text]
        for x0, x1, text in cs:
            if text == " ":
                if cur and cur[2].strip():
                    toks.append((font, size, y, cur[0], cur[1], cur[2]))
                cur = None
                continue
            if cur is None:
                cur = [x0, x1, text]
            else:
                cur[1], cur[2] = x1, cur[2] + text
        if cur and cur[2].strip():
            toks.append((font, size, y, cur[0], cur[1], cur[2]))
    return toks


def compare(before: dict, after: dict) -> list[str]:
    """Golden diff under the Layer-0 contract. Returns list of violations."""
    problems = []
    if len(before["pages"]) != len(after["pages"]):
        problems.append(
            f"page count changed: {len(before['pages'])} -> {len(after['pages'])}")
        return problems

    for pb, pa in zip(before["pages"], after["pages"]):
        n = pb["page"]
        # 1. Everything that is NOT a chord char must be byte-identical.
        non_chord_b = [c for c in pb["chars"] if c[1] != CHORD_FONT]
        non_chord_a = [c for c in pa["chars"] if c[1] != CHORD_FONT]
        if non_chord_b != non_chord_a:
            problems.append(f"page {n}: non-chord content moved or changed")
        # 2. Chord chars: same glyphs in same line order, x on the lyric grid.
        # Space glyphs are excluded: the old renderer emitted chord-line
        # spaces as invisible ink, the per-token renderer doesn't.
        chord_b = [c for c in pb["chars"] if c[1] == CHORD_FONT and c[0] != " "]
        chord_a = [c for c in pa["chars"] if c[1] == CHORD_FONT and c[0] != " "]
        if [c[0] for c in chord_b] != [c[0] for c in chord_a]:
            problems.append(f"page {n}: chord glyph sequence changed")
            continue
        for cb, ca in zip(chord_b, chord_a):
            if abs(cb[5] - ca[5]) > TOL:
                problems.append(
                    f"page {n}: chord char {cb[0]!r} moved vertically "
                    f"{cb[5]} -> {ca[5]}")
        # Token-level grid check on the AFTER snapshot.
        for font, size, y, x0, x1, text in _tokens(pa["chars"]):
            if font != CHORD_FONT:
                continue
            col = (x0 - MARGIN_LEFT) / LYRIC_CHAR_W
            if abs(col - round(col)) * LYRIC_CHAR_W > TOL:
                problems.append(
                    f"page {n}: chord token {text!r} off the column grid "
                    f"(x0={x0:.2f}, col={col:.3f})")
    return problems


def overflow(snap: dict) -> list[str]:
    """Ink past the right printable edge. Returns offending tokens."""
    hits = []
    for page in snap["pages"]:
        for font, size, y, x0, x1, text in _tokens(page["chars"]):
            if x1 > RIGHT_EDGE + TOL:
                hits.append(
                    f"page {page['page']}: {font} {text!r} ends at "
                    f"x={x1:.1f} (edge {RIGHT_EDGE}, page width {build.PAGE_W})")
    return hits


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    reports = REPO / "qc" / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    pdf = REPO / "fakebook" / "fakebook.pdf"

    if cmd == "snapshot":
        out = Path(sys.argv[2]) if len(sys.argv) > 2 else reports / "snapshot.json"
        snap = snapshot(pdf)
        out.write_text(json.dumps(snap))
        n_chars = sum(len(p["chars"]) for p in snap["pages"])
        print(f"Wrote {out} ({len(snap['pages'])} pages, {n_chars} chars)")
    elif cmd == "compare":
        before = json.loads(Path(sys.argv[2]).read_text())
        after = json.loads(Path(sys.argv[3]).read_text())
        problems = compare(before, after)
        for p in problems:
            print("VIOLATION:", p)
        print(f"{len(problems)} violations" if problems else "PASS: golden diff clean")
        sys.exit(1 if problems else 0)
    elif cmd == "overflow":
        src = Path(sys.argv[2]) if len(sys.argv) > 2 else None
        snap = json.loads(src.read_text()) if src else snapshot(pdf)
        hits = overflow(snap)
        for h in hits:
            print("OVERFLOW:", h)
        print(f"{len(hits)} overflows" if hits else "PASS: no overflow")
        sys.exit(1 if hits else 0)
    else:
        print(__doc__)
        print("usage: verify_pdf.py snapshot [out.json] | compare before.json "
              "after.json | overflow [snap.json]")
        sys.exit(2)


if __name__ == "__main__":
    main()
