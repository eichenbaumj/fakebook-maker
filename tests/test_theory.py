"""Chord grammar tests, including 100% coverage of the live corpus."""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "fakebook"))

import pytest

import build
from qc.theory import (Chord, parse_chord, parse_key, pitch_class, degree,
                       same_function, enharmonic_style_issue)


# --- corpus coverage: every token on every real chord line must classify ---

def _corpus_chord_tokens():
    tokens = set()
    for f in sorted((REPO / "charts").glob("*.txt")):
        song = build.parse_chart(f)
        if not song:
            continue
        for sec in song["sections"]:
            for line_type, line in sec["lines"]:
                if line_type == "chords":
                    tokens.update(line.split())
    return sorted(tokens)


def test_corpus_coverage_no_invalid_tokens():
    bad = [t for t in _corpus_chord_tokens()
           if parse_chord(t).kind == "invalid"]
    assert bad == [], f"invalid tokens on live chord lines: {bad}"


# --- the '-' disambiguation -------------------------------------------------

def test_dash_after_root_is_minor():
    c = parse_chord("E-7")
    assert c.kind == "chord" and c.quality_class == "min"
    assert c.root_spelled == "E"


def test_dash_after_extension_is_flat_alteration():
    c = parse_chord("Eb7-5")
    assert c.kind == "chord" and c.quality_class == "dom"
    c2 = parse_chord("C7-9")
    assert c2.quality_class == "dom"


# --- glyph and notation variants ---------------------------------------------

@pytest.mark.parametrize("tok,qc", [
    ("Bº", "dim"), ("F°7", "dim"), ("Adim7", "dim"), ("C#dim", "dim"),
    ("Am7b5", "half_dim"), ("Am7-5", "half_dim"),
    ("Caug", "aug"), ("C+", "aug"), ("C+7", "aug"), ("F+", "aug"),
    ("Am(maj7)", "min"), ("Gmmaj7", "min"), ("Ammaj7", "min"),
    ("Dmi", "min"), ("Ami7", "min"), ("Fmi9", "min"), ("Dmin7", "min"),
    ("Emi7b5", "half_dim"), ("Amimaj7", "min"),
    ("B6/9", "maj"), ("Db6/9", "maj"), ("F69", "maj"),
    ("A7(9)", "dom"), ("E7(13)", "dom"), ("F#7(#5)", "dom"),
    ("C7+5", "dom"), ("F9+5", "dom"), ("A9+11", "dom"),
    ("B7#5b9", "dom"), ("Ab7b9b13", "dom"), ("G13", "dom"),
    ("Dsus4", "sus"), ("A9sus4", "sus"), ("D7sus4", "sus"),
    ("Cm7/Bb", "min"), ("D9/F#", "dom"), ("F6", "maj"), ("Fmaj9", "maj"),
])
def test_quality_classes(tok, qc):
    c = parse_chord(tok)
    assert c.kind == "chord", (tok, c.problems)
    assert c.quality_class == qc, (tok, c.quality_class)


def test_wrong_ordinal_glyph_flagged():
    c = parse_chord("Bº")
    assert any("U+00BA" in p for p in c.problems)
    assert parse_chord("B°").problems == []


# --- non-chords ---------------------------------------------------------------

@pytest.mark.parametrize("tok,kind", [
    ("N.C.", "nc"), ("NC", "nc"),
    ("|", "bar"), ("/", "slash"), ("%", "repeat"),
    ("x12", "repeat"), ("(x2)", "repeat"), ("X4", "repeat"),
    ("(Repeat", "annotation"), ("fade)", "annotation"),
])
def test_structural_tokens(tok, kind):
    assert parse_chord(tok).kind == kind


@pytest.mark.parametrize("tok", [
    "Call", "Georgia,", "Deacon", "Blues", "Don't", "me", "you", "Chart",
    "All", "Corrected",
])
def test_lyric_words_are_not_chords(tok):
    assert parse_chord(tok).kind == "invalid"


def test_slash_bass():
    c = parse_chord("Cm7/Bb")
    assert c.bass_spelled == "Bb" and c.bass_pc == 10


# --- keys and degrees -----------------------------------------------------------

def test_parse_key_variants():
    assert parse_key("Key: F | Tempo: Ballad").spelled == "F"
    assert parse_key("Key: A (transposed down 1.5 steps from C)").spelled == "A"
    k = parse_key("Key: C (modulates to Db)")
    assert k.spelled == "C" and k.modulates_to == "Db"
    assert parse_key("Key: D# | Tempo: Slow jam").pc == 3
    assert parse_key("Key: G/Bb").spelled == "G"
    assert parse_key("Tempo: Swing") is None


def test_degree():
    assert degree(parse_chord("Bb7"), pitch_class("F")) == "IV"
    assert degree(parse_chord("C7"), pitch_class("F")) == "V"
    assert degree(parse_chord("Gm7"), pitch_class("F")) == "II"


def test_same_function_across_keys():
    # vi chord: F#m7 in A == Am7 in C
    assert same_function(parse_chord("F#m7"), pitch_class("A"),
                         parse_chord("Am7"), pitch_class("C"))
    # different quality: A7 vs Am7 in the same spot
    assert not same_function(parse_chord("A7"), pitch_class("C"),
                             parse_chord("Am7"), pitch_class("C"))
    # enharmonic: D#m7 in Db == Ebm7 in Db
    assert same_function(parse_chord("D#m7"), pitch_class("Db"),
                         parse_chord("Ebm7"), pitch_class("Db"))


def test_enharmonic_style():
    k = parse_key("Key: F")
    issue = enharmonic_style_issue(parse_chord("A#7"), k)
    assert issue and "Bb7" in issue
    assert enharmonic_style_issue(parse_chord("Bb7"), k) is None
