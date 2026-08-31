"""Linter rule tests — positive and negative cases per rule."""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from qc.lint import lint_file


def _lint(tmp_path, text):
    p = tmp_path / "t.txt"
    p.write_text(text, encoding="utf-8")
    return lint_file(p)


def _rules(findings):
    return {f.rule for f in findings}


def test_clean_chart_is_clean(tmp_path):
    f = _lint(tmp_path, """Nice Tune - Someone
Key: F | Tempo: Swing

[Verse]
Fmaj7     Gm7   C7
Words go here nicely
""")
    assert {x.severity for x in f} <= {"INFO"}, [str(x) for x in f]


def test_tab_error(tmp_path):
    f = _lint(tmp_path, "T - C\nKey: C\n\n[V]\nC\tG7\nhello world\n")
    assert "tab-character" in _rules(f)


def test_wrong_ordinal_glyph_warns_with_autofix(tmp_path):
    f = _lint(tmp_path, "T - C\nKey: F\n\n[V]\nBb9   Bº\nhello world again\n")
    hits = [x for x in f if x.rule == "non-ascii" and x.severity == "WARN"]
    assert hits and "°" in hits[0].autofix


def test_degree_glyph_is_info_only(tmp_path):
    f = _lint(tmp_path, "T - C\nKey: F\n\n[V]\nBb9   B°\nhello world again\n")
    hits = [x for x in f if x.rule == "non-ascii"]
    assert hits and hits[0].severity == "INFO" and hits[0].autofix == ""


def test_metadata_dropped(tmp_path):
    f = _lint(tmp_path, "T - C\nKey: F\nTempo: Swing\n\n[V]\nC\nla la la\n")
    assert "metadata-dropped" in _rules(f)
    assert any(x.severity == "ERROR" for x in f if x.rule == "metadata-dropped")


def test_overflow_lyric(tmp_path):
    f = _lint(tmp_path, "T - C\nKey: C\n\n[V]\nC\n" + "la " * 30 + "\n")
    assert "overflow" in _rules(f)


def test_pair_broken_by_blank(tmp_path):
    f = _lint(tmp_path, "T - C\nKey: C\n\n[V]\nC   G7\n\nthe lyric line\n")
    assert "pair-broken-by-blank" in _rules(f)


def test_bracket_inside_lyric_is_not_a_section(tmp_path):
    # a bracketed shout mid-lyric (a real corpus idiom) must not be parsed
    # as a section header or trip any rule
    f = _lint(tmp_path, """T - C
Key: F

[Verse]
F           C7
We hear the [KNOCK-KNOCK-KNOCK-KNOCK] at the gate
""")
    assert all(x.severity == "INFO" for x in f), [str(x) for x in f]


def test_live_corpus_has_no_crashes():
    for p in sorted((REPO / "charts").glob("*.txt")):
        lint_file(p)  # must not raise
