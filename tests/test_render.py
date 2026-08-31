"""End-to-end renderer test: chord tokens land on the lyric column grid."""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "fakebook"))

import pdfplumber

import build


def test_chord_tokens_on_lyric_grid(tmp_path):
    chart = tmp_path / "grid-test.txt"
    chart.write_text("""Grid Test - Nobody
Key: C

[Verse]
C         G7        Am7                    F
Twinkle twinkle little star how I wonder what
""", encoding="utf-8")

    song = build.parse_chart(chart)
    out = tmp_path / "out.pdf"
    renderer = build.FakeBookRenderer(str(out), [song])
    renderer.render()

    with pdfplumber.open(out) as pdf:
        # find bold (chord) chars on the content page (page 2, after TOC)
        chars = [c for p in pdf.pages for c in p.chars
                 if c["fontname"].endswith("Courier-Bold")
                 and round(c["size"]) == build.CHORD_SIZE]
    assert chars, "no chord chars rendered"
    # group into tokens by proximity
    chars.sort(key=lambda c: (round(c["top"]), c["x0"]))
    starts = {}
    prev_x1, prev_top = None, None
    token_start = None
    for c in chars:
        if (prev_x1 is None or round(c["top"]) != prev_top
                or c["x0"] - prev_x1 > 1.0):
            token_start = c["x0"]
            starts[token_start] = c["text"]
        else:
            starts[token_start] += c["text"]
        prev_x1, prev_top = c["x1"], round(c["top"])

    source_cols = {"C": 0, "G7": 10, "Am7": 20, "F": 43}
    char_w = 0.6 * build.LYRIC_SIZE
    found = {}
    for x0, text in starts.items():
        col = (x0 - build.MARGIN_LEFT) / char_w
        assert abs(col - round(col)) < 0.05, f"{text} off-grid at col {col}"
        found[text] = round(col)
    assert found == source_cols


def test_width_warnings():
    song = {"title": "W", "sections": [{"name": "V", "lines": [
        ("lyrics", "x" * 80),
        ("chords", " " * 70 + "Cmaj7 Dm7 G7"),
    ]}]}
    warnings = build.check_widths(song)
    assert len(warnings) == 2
