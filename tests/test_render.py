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


def _pair_height():
    return build.CHORD_SIZE + build.CHORD_LYRIC_GAP + build.LYRIC_SIZE + build.LINE_PAIR_AFTER


def test_lead_height_counts_pairs_singles_and_skips_blanks():
    pair = _pair_height()
    single_chord = build.CHORD_SIZE + build.CHORD_LYRIC_GAP + build.SINGLE_LINE_AFTER
    single_lyric = build.LYRIC_SIZE + build.SINGLE_LINE_AFTER
    lead = build.FakeBookRenderer._lead_height

    # chord+lyric pairs are one item each; blanks between them don't count
    assert lead([("chords", "C"), ("lyrics", "la"), ("blank", ""),
                 ("chords", "G"), ("lyrics", "la"),
                 ("chords", "F"), ("lyrics", "la")]) == 2 * pair
    # intro-style section: chord row over a bar-slash line is a pair too
    assert lead([("chords", "C  F"), ("lyrics", "| /  / |"),
                 ("chords", "G"), ("lyrics", "| /  / |")]) == 2 * pair
    # lone chord line, lone lyric line
    assert lead([("chords", "C"), ("lyrics", "la"), ("chords", "G7")]) == pair + single_chord
    assert lead([("lyrics", "la"), ("lyrics", "la"), ("lyrics", "la")]) == 2 * single_lyric
    # fewer items than requested just sums what is there
    assert lead([("chords", "C"), ("lyrics", "la")]) == pair
    assert lead([]) == 0


def test_section_header_not_orphaned_at_page_bottom(tmp_path):
    """A [Section] header must not be stranded at the bottom of a page with
    only one line under it; the whole header + first two lines move down."""
    pair = _pair_height()
    header = build.SECTION_BEFORE + build.SECTION_SIZE + build.SECTION_AFTER
    blank = 6
    content = build.PAGE_H - build.MARGIN_TOP - build.MARGIN_BOTTOM
    title_block = (build.TITLE_SIZE + 2) + (build.SUBTITLE_SIZE + 2) + build.TITLE_AFTER

    # Size section A so that after it the page has room for B's header plus
    # exactly one pair (the old rule drew it there) but not header + 2 pairs.
    n = None
    for cand in range(1, 60):
        remaining = content - title_block - (header + cand * pair + blank)
        if header + pair <= remaining < header + 2 * pair:
            n = cand
            break
    assert n is not None, "could not size the fixture; renderer spacing changed?"

    a_rows = "".join(f"C     G7\nalpha{i} beta{i}\n" for i in range(n))
    b_rows = "".join(f"F     C\ngamma{i} delta{i}\n" for i in range(4))
    chart = tmp_path / "orphan-test.txt"
    chart.write_text(f"Orphan Test - Nobody\nKey: C\n\n[Alpha]\n{a_rows}\n[Bravo]\n{b_rows}",
                     encoding="utf-8")
    song = build.parse_chart(chart)
    assert len(song["sections"]) == 2 and len(song["sections"][0]["lines"]) == 2 * n + 1

    out = tmp_path / "out.pdf"
    build.FakeBookRenderer(str(out), [song]).render()

    with pdfplumber.open(out) as pdf:
        texts = [p.extract_text() or "" for p in pdf.pages]
    bravo_pages = [i for i, t in enumerate(texts) if "[Bravo]" in t]
    assert len(bravo_pages) == 1
    page = texts[bravo_pages[0]]
    # header page also carries every one of Bravo's four lyric lines ...
    for i in range(4):
        assert f"gamma{i} delta{i}" in page
    # ... and it is a later page than the one Alpha ended on
    alpha_end = max(i for i, t in enumerate(texts) if f"alpha{n-1} beta{n-1}" in t)
    assert bravo_pages[0] == alpha_end + 1
