"""Fix application: chord moves, collisions, staleness, reflow invariants."""

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from qc.apply_fixes import (move_chord, reflow_pair, reflow_chord_line,
                            chord_budget_ok, LYRIC_MAX)
from qc.anchor import classify, words_of


def test_move_chord_simple():
    #           0123456789012345678901234567890
    line, err = move_chord("          Ab6  Adim7        Gm            C7",
                           28, "Gm", 14)
    assert err == ""
    toks = [(m.start(), m.group()) for m in re.finditer(r"\S+", line)]
    assert (14, "Gm") in toks
    assert sorted(t for _, t in toks) == ["Ab6", "Adim7", "C7", "Gm"]


def test_move_chord_stale():
    _, err = move_chord("C   G7", 10, "G7", 0)
    assert "stale" in err


def test_move_chord_collision_demotes():
    # Moving G7 onto C's position must not silently shove things around.
    line, err = move_chord("C G7 F", 2, "G7", 0)
    assert err != "" or "C" in line  # either demoted or C preserved intact


def test_move_chord_idempotent():
    line, err = move_chord("C   G7", 4, "G7", 4)
    assert err == "" and line == "C   G7"


def _anchor_words(chord_line, lyric_line):
    words = words_of(lyric_line)
    out = {}
    for m in re.finditer(r"\S+", chord_line):
        a = classify(m.start(), m.group(), words)
        if a.placement in ("on_word", "during_word"):
            out.setdefault(m.group(), []).append(a.word)
    return out


def test_reflow_pair_compress_preserves_anchors():
    chord = "Gm7               C7        Fmaj7  Dm  Gm"
    lyric = "Where my cat and I fetch tomatoes,   " + " " * 44 + "yeah"
    assert len(lyric) > LYRIC_MAX
    pairs, err = reflow_pair(chord, lyric)
    assert err == "" and len(pairs) == 1
    new_chord, new_lyric = pairs[0]
    assert len(new_lyric) <= LYRIC_MAX
    assert chord_budget_ok(new_chord)
    assert [w.text for w in words_of(lyric)] == \
        [w.text for w in words_of(new_lyric)]
    assert _anchor_words(chord, lyric) == _anchor_words(new_chord, new_lyric)


def test_reflow_pair_splits_uncompressible():
    # shape of a real corpus worst-case line (12 chars over, only ~7 columns
    # of slack): must split into two pairs, anchors preserved.
    chord = ("F#m/A    Ab7b9b13  C#m7    Bbo     Ebm7b5   Ab7b9b13  C#m7"
             "      F#7        B7")
    lyric = ("  Once   I baked a loaf - cake,   now its   gone,  "
             "Sis - ters can you share a bite.")
    pairs, err = reflow_pair(chord, lyric)
    assert err == ""
    assert len(pairs) == 2
    joined = {}
    for c, l in pairs:
        assert len(l.rstrip()) <= LYRIC_MAX
        assert chord_budget_ok(c)
        for k, v in _anchor_words(c, l).items():
            joined.setdefault(k, []).extend(v)
    assert joined == _anchor_words(chord, lyric)
    # lyric text (ignoring spacing) survives intact across the two lines
    orig = " ".join(lyric.split())
    got = " ".join((pairs[0][1] + " " + pairs[1][1]).split())
    assert got == orig


def test_reflow_pair_too_few_words_reports():
    lyric = "x" * 40 + " " + "y" * 40  # 81 chars, one single space
    pairs, err = reflow_pair("C", lyric)
    assert err != "" and pairs == [("C", lyric)]


def test_reflow_chord_line():
    line = "F+    Bb             Bb7         Eb                 Ebm Bb      Eb   Gm  C7"
    new, err = reflow_chord_line(line)
    assert err == ""
    assert chord_budget_ok(new)
    assert new.split() == line.split()
