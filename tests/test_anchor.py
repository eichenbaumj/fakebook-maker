"""Anchor-map extraction tests — one fixture per corpus idiom."""

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from qc.anchor import (extract_anchor_map, cross_section_consistency,
                       classify, words_of, detect_prefixes)

CHARTS = REPO / "charts"


def corpus(name):
    """Resolve a private-corpus chart; skip in checkouts that don't have it.

    The public repo ships only demo charts, so tests tied to specific
    corpus tunes skip there instead of failing.
    """
    p = CHARTS / name
    if not p.exists():
        pytest.skip(f"corpus chart {name} not in this checkout")
    return p


def _write(tmp_path, text):
    p = tmp_path / "tune.txt"
    p.write_text(text, encoding="utf-8")
    return p


def test_on_word_and_during_word(tmp_path):
    p = _write(tmp_path, """Test Tune - Nobody
Key: F

[Verse]
Fmaj7     Gm   C7
Stormy weather today
""")
    tm = extract_anchor_map(p)
    anchors = tm.sections[0].pairs[0].anchors
    assert anchors[0].placement == "on_word" and anchors[0].word == "Stormy"
    # Gm at col 10 sits inside 'weather' (cols 7-14)
    assert anchors[1].placement == "during_word"
    assert anchors[1].word == "weather" and anchors[1].split == "wea|ther"
    # C7 at col 15 == onset of 'today'
    assert anchors[2].placement == "on_word" and anchors[2].word == "today"


def test_gap_chord_attaches_to_preceding_word(tmp_path):
    p = _write(tmp_path, """T - C
Key: C

[Verse]
C        G7
Why           me
""")
    tm = extract_anchor_map(p)
    a = tm.sections[0].pairs[0].anchors[1]  # G7 in the gap after 'Why'
    assert a.placement == "during_word" and a.word == "Why"


def test_trailing_turnaround_and_leading(tmp_path):
    p = _write(tmp_path, """T - C
Key: C

[Verse]
   C          A7  D7  G7
      To my heart
""")
    tm = extract_anchor_map(p)
    kinds = [a.placement for a in tm.sections[0].pairs[0].anchors]
    assert kinds[0] == "leading"
    assert kinds[2] == "trailing" and kinds[3] == "trailing"


def test_instrumental_and_barline_modes():
    tm = extract_anchor_map(corpus("stormy-weather.txt"))
    intro = tm.sections[0]
    assert all(p.mode == "instrumental" for p in intro.pairs)

    tm2 = extract_anchor_map(corpus("move-on-up.txt"))
    modes = {p.mode for _, p in tm2.all_pairs()}
    assert "barline" in modes  # '| /  /  /  / | ...' rhythm lines


def test_character_prefix_never_anchors():
    tm = extract_anchor_map(corpus("sunrise-sunset.txt"))
    for _, pair in tm.all_pairs():
        for a in pair.anchors:
            assert a.word not in ("Golde", "Tevye", "Both"), \
                f"chord {a.chord} anchored to a character name"


def test_syllable_separator_not_an_anchor(tmp_path):
    p = _write(tmp_path, """T - C
Key: C

[Verse]
C           G7
Bro - ther can you spare
""")
    tm = extract_anchor_map(p)
    for a in tm.sections[0].pairs[0].anchors:
        assert a.word != "-"


def test_known_defects_visible():
    """The extractor must expose stormy-weather's mid-word Gm placements."""
    tm = extract_anchor_map(corpus("stormy-weather.txt"))
    splits = [a.split for _, p in tm.all_pairs() for a in p.anchors if a.split]
    assert "there'|s" in splits or "there|'s" in splits
    assert any(s.startswith("mise") or s.startswith("mi|") for s in splits)


def test_cross_section_consistency_finds_real_and_skips_variation():
    # but-not-for-me: identical progression, Dm7 on 'love,' vs 'of' — real.
    issues = cross_section_consistency(
        extract_anchor_map(corpus("but-not-for-me.txt")))
    assert any(i["kind"] == "placement_mismatch" for i in issues)

    # stormy-weather: repeats are consistent — no findings.
    assert cross_section_consistency(
        extract_anchor_map(corpus("stormy-weather.txt"))) == []


def test_consistency_handles_transposed_sections(tmp_path):
    # A half-step-modulated repeat whose progression matches but whose last
    # anchor shifted one word ('pursue' vs 'to') must be flagged — this was
    # a real defect in call-me-irresponsible's outro (fixed 2026-07-18);
    # the fixture preserves the detection capability.
    p = _write(tmp_path, """T - C
Key: G

[Verse 2]
G/B        B7b9                Bm7b5/E
Downpour, I'm prepared to paddle
[Outro - up half step]
Ab/C       C7b9         Cm7b5/F
Downpour, I'm prepared to paddle
""")
    issues = cross_section_consistency(extract_anchor_map(p))
    hits = [i for i in issues if i["kind"] == "placement_mismatch"
            and i.get("transposed_by") == 1]
    assert hits, "transposed-section mismatch not detected"


def test_deliberate_ending_variation_not_flagged():
    # georgia 'Just an old sweet song...' has different chords per verse
    # (last-time endings) — chord sequences differ, so no placement issue.
    issues = cross_section_consistency(
        extract_anchor_map(corpus("georgia-on-my-mind.txt")))
    for i in issues:
        for v in i["variants"]:
            assert "old sweet song" not in i["lyric"] or \
                i["kind"] != "placement_mismatch"


def test_prefix_detection_negative():
    # Ordinary lyrics starting with a capital word must not create prefixes.
    assert detect_prefixes(["Georgia, Georgia, the whole day",
                            "Stormy weather today"]) is None
