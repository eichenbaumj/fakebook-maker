#!/usr/bin/env python3
"""Anchor-map extraction: which lyric word does each chord sit over?

This is the deterministic backbone of the alignment audit. Agents never do
column arithmetic — they talk about anchors ("Gm lands on 'gloom'"), and
this module converts chart columns -> anchors (here) and anchors -> columns
(apply_fixes). Placement vocabulary:

  on_word      chord column within 1 of a word onset
  during_word  chord mid-word or in the whitespace after a word (a chord
               sustained/changed while the previous word is held — normal)
  leading      chord before the first word of the line
  trailing     chord past the end of the sung lyric (turnaround idiom)
  instrumental chord line with no lyric line under it
  barline      measure-bar or rhythm-slash line (| / tokens)

Line classification mirrors fakebook/build.py exactly (same functions).
"""

import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "fakebook"))

from build import is_chord_line  # noqa: E402
from qc.theory import parse_chord, parse_key, Key  # noqa: E402


@dataclass
class Word:
    text: str
    col: int          # 0-based start column
    end_col: int      # exclusive
    is_syllable_sep: bool = False   # a bare '-' between sung syllables
    is_prefix: bool = False         # character-name column (Tevye/Golde)
    in_parens: bool = False


@dataclass
class Anchor:
    chord: str
    col: int
    kind: str            # from theory: chord|nc|bar|slash|repeat|annotation|invalid
    placement: str       # on_word|during_word|leading|trailing
    word: str = ""       # anchor word text ('' when trailing/leading)
    word_col: int = -1
    offset: int = 0      # chord.col - word.col
    split: str = ""      # 'mi|sery' when mid-word


@dataclass
class Pair:
    chord_line_no: int          # 1-based source line numbers
    lyric_line_no: int | None
    chord_line: str
    lyric_line: str | None
    mode: str                   # sung|instrumental|barline
    anchors: list = field(default_factory=list)
    skew: int | None = None     # uniform nonzero onset offset, if any


@dataclass
class Section:
    name: str
    pairs: list = field(default_factory=list)
    lone_lyrics: list = field(default_factory=list)  # (line_no, text)


@dataclass
class TuneMap:
    file: str
    title: str
    composer: str
    key_raw: str
    key: str            # e.g. 'F', 'D#', 'Fm', '' if unknown
    sections: list = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=1)

    def all_pairs(self):
        for sec in self.sections:
            for pair in sec.pairs:
                yield sec, pair


# --- lyric-line tokenization ------------------------------------------------

def words_of(lyric_line: str, prefix_cols: tuple | None = None) -> list:
    """Split a lyric line into Word tokens with column spans."""
    words = []
    paren_depth = 0
    for m in re.finditer(r"\S+", lyric_line):
        text = m.group()
        is_prefix = bool(prefix_cols and m.start() == prefix_cols[0]
                         and text in prefix_cols[1])
        words.append(Word(
            text=text, col=m.start(), end_col=m.end(),
            is_syllable_sep=(text == "-"),
            is_prefix=is_prefix,
            in_parens=paren_depth > 0 or text.startswith("("),
        ))
        paren_depth += text.count("(") - text.count(")")
    return words


def detect_prefixes(lyric_lines: list) -> tuple | None:
    """Detect a character-name column (sunrise-sunset: 'Golde   I don't...').

    Requires >=2 lines starting at column 0 with a capitalized name followed
    by >=3 spaces, with <=4 distinct names, and the sung text starting at a
    consistent column.
    """
    hits = []
    for line in lyric_lines:
        m = re.match(r"^([A-Z][a-z]+)(\s{3,})(\S)", line)
        if m:
            hits.append((m.group(1), m.start(3)))
    if len(hits) < 2:
        return None
    names = {h[0] for h in hits}
    body_cols = {h[1] for h in hits}
    if len(names) <= 4 and len(body_cols) == 1:
        return (0, names)
    return None


# --- anchor classification ---------------------------------------------------

def classify(col: int, chord: str, words: list) -> Anchor:
    kind = parse_chord(chord).kind
    anchorable = [w for w in words if not w.is_prefix and not w.is_syllable_sep]
    if not anchorable:
        return Anchor(chord, col, kind, "trailing")

    # 1. Word-onset proximity wins (±1 column).
    for w in anchorable:
        if abs(col - w.col) <= 1:
            return Anchor(chord, col, kind, "on_word", w.text, w.col, col - w.col)

    first, last = anchorable[0], anchorable[-1]
    if col < first.col:
        return Anchor(chord, col, kind, "leading")
    if col >= last.end_col:
        return Anchor(chord, col, kind, "trailing")

    # 2. Inside a word's span -> during that word.
    for w in anchorable:
        if w.col < col < w.end_col:
            cut = col - w.col
            return Anchor(chord, col, kind, "during_word", w.text, w.col,
                          cut, f"{w.text[:cut]}|{w.text[cut:]}")

    # 3. In a whitespace gap -> sustained during the preceding word.
    prev = max((w for w in anchorable if w.end_col <= col),
               key=lambda w: w.end_col)
    return Anchor(chord, col, kind, "during_word", prev.text, prev.col,
                  col - prev.col)


def detect_skew(pair: Pair) -> int | None:
    """Uniform nonzero offset of every chord from its nearest word onset."""
    words = [w for w in words_of(pair.lyric_line or "")
             if not w.is_prefix and not w.is_syllable_sep]
    if not words:
        return None
    onsets = [w.col for w in words]
    offsets = set()
    counted = 0
    for a in pair.anchors:
        if a.kind not in ("chord", "nc") or a.placement == "trailing":
            continue
        nearest = min(onsets, key=lambda o: abs(a.col - o))
        offsets.add(a.col - nearest)
        counted += 1
    if counted >= 2 and len(offsets) == 1:
        k = offsets.pop()
        if k != 0 and abs(k) <= 3:
            return k
    return None


_BARLINE_KINDS = {"bar", "slash", "repeat", "annotation"}


def _is_barline(chord_line: str) -> bool:
    s = chord_line.strip()
    if s.startswith("|"):
        return True
    kinds = {parse_chord(t).kind for t in s.split()}
    return bool(kinds) and kinds <= _BARLINE_KINDS | {"chord", "nc"} \
        and ("bar" in kinds or "slash" in kinds)


# --- chart walk ---------------------------------------------------------------

def extract_anchor_map(path: Path) -> TuneMap:
    lines = path.read_text(encoding="utf-8").splitlines()
    first = lines[0].strip() if lines else ""
    if " - " in first:
        title, composer = first.split(" - ", 1)
    else:
        title, composer = first, ""

    # Metadata window: mirror build.parse_chart (lines 1-4).
    info = ""
    content_start = 1
    for i in range(1, min(len(lines), 5)):
        s = lines[i].strip()
        if not s:
            continue
        if re.match(r"^(Key|Tempo|Capo|Time|Transposed)\s*:", s, re.IGNORECASE):
            info = s
            content_start = i + 1
        else:
            break

    key = parse_key(info)
    lyric_candidates = [l for l in lines[content_start:]
                        if l.strip() and not l.strip().startswith("[")
                        and not is_chord_line(l.strip())]
    prefix_cols = detect_prefixes(lyric_candidates)

    tune = TuneMap(file=path.name, title=title, composer=composer,
                   key_raw=info, key=key.spelled if key else "")
    section = Section(name="")

    i = content_start
    while i < len(lines):
        raw = lines[i]
        s = raw.strip()
        lineno = i + 1
        if not s:
            i += 1
            continue
        m = re.match(r"^\[(.+)\]", s)
        if m:
            if section.pairs or section.lone_lyrics or section.name:
                tune.sections.append(section)
            section = Section(name=m.group(1))
            i += 1
            continue
        if _is_barline(raw):
            # Rhythm/measure lines ('| / / / |', '| Cm | F7 | x12') carry no
            # word anchors regardless of how the renderer classifies them.
            section.pairs.append(Pair(lineno, None, raw.rstrip(), None, "barline"))
            i += 1
        elif is_chord_line(s):
            # Look ahead (through blanks is NOT allowed — mirrors renderer
            # pairing, which only pairs an immediately-following lyric line).
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            nxt_s = nxt.strip()
            is_lyric_next = bool(nxt_s) and not nxt_s.startswith("[") \
                and not is_chord_line(nxt_s) and not _is_barline(nxt)
            if is_lyric_next:
                pair = Pair(lineno, lineno + 1, raw.rstrip(), nxt.rstrip(), "sung")
                words = words_of(nxt, prefix_cols)
                for wm in re.finditer(r"\S+", raw):
                    pair.anchors.append(classify(wm.start(), wm.group(), words))
                pair.skew = detect_skew(pair)
                i += 2
            else:
                pair = Pair(lineno, None, raw.rstrip(), None, "instrumental")
                i += 1
            section.pairs.append(pair)
        else:
            section.lone_lyrics.append((lineno, raw.rstrip()))
            i += 1
    if section.pairs or section.lone_lyrics or section.name:
        tune.sections.append(section)
    return tune


# --- cross-section consistency -------------------------------------------------

def _norm_lyric(text: str) -> str:
    return re.sub(r"[^a-z' ]", "", re.sub(r"\s+", " ", text.lower())).strip()


def _norm_word(w: str) -> str:
    """'anybody,' == 'anybody'; 'around----,' == 'around'."""
    return re.sub(r"[^a-z']", "", w.lower())


def _sung_anchors(pair: Pair) -> list:
    """Anchors that carry placement signal: real chords over the sung text.

    Trailing turnaround chords and pickup 'leading' chords legitimately vary
    between repeats, so they carry no consistency signal.
    """
    return [a for a in pair.anchors
            if a.kind in ("chord", "nc")
            and a.placement in ("on_word", "during_word")]


def _transposition_interval(seq_a: list, seq_b: list) -> int | None:
    """If seq_b is seq_a transposed by a constant interval, return it (0 =
    identical chords). Requires equal length, matching quality classes."""
    if len(seq_a) != len(seq_b) or not seq_a:
        return None
    intervals = set()
    for a, b in zip(seq_a, seq_b):
        ca, cb = parse_chord(a.chord), parse_chord(b.chord)
        if ca.kind != "chord" or cb.kind != "chord":
            if a.chord != b.chord:
                return None
            continue
        if ca.quality_class != cb.quality_class:
            return None
        intervals.add((cb.root_pc - ca.root_pc) % 12)
    return intervals.pop() if len(intervals) == 1 else None


def cross_section_consistency(tune: TuneMap) -> list:
    """Same lyric in >=2 places, same progression, different word anchors.

    Deliberate variation is filtered out: variants whose chord sequences
    genuinely differ (last-time endings, reharms on the repeat) are NOT
    inconsistencies. A variant that is the same progression — identical or
    uniformly transposed (modulated sections) — but anchors a chord to a
    different word is real evidence that one placement is wrong.
    Near-miss sequences (one chord inserted/dropped, rest matching) are
    reported as weak evidence of a missing/extra chord.
    """
    groups = {}
    for sec, pair in tune.all_pairs():
        if pair.mode != "sung":
            continue
        key = _norm_lyric(pair.lyric_line)
        if len(key) < 10:
            continue
        groups.setdefault(key, []).append((sec.name, pair))

    def variant(name, pair):
        return {
            "section": name,
            "chord_line_no": pair.chord_line_no,
            "chord_line": pair.chord_line,
            "lyric_line": pair.lyric_line,
            "anchors": [(a.chord, a.word) for a in _sung_anchors(pair)],
        }

    issues = []
    for key, occurrences in groups.items():
        if len(occurrences) < 2:
            continue
        base_name, base = occurrences[0]
        base_anchors = _sung_anchors(base)
        for name, pair in occurrences[1:]:
            anchors = _sung_anchors(pair)
            interval = _transposition_interval(base_anchors, anchors)
            if interval is not None:
                words_a = [_norm_word(a.word) for a in base_anchors]
                words_b = [_norm_word(a.word) for a in anchors]
                if words_a != words_b:
                    issues.append({
                        "kind": "placement_mismatch",
                        "transposed_by": interval,
                        "lyric": base.lyric_line.strip(),
                        "variants": [variant(base_name, base),
                                     variant(name, pair)],
                    })
            else:
                # One insertion/deletion with everything else matching?
                sig_a = [(a.chord, _norm_word(a.word)) for a in base_anchors]
                sig_b = [(a.chord, _norm_word(a.word)) for a in anchors]
                if abs(len(sig_a) - len(sig_b)) == 1:
                    small, large = sorted([sig_a, sig_b], key=len)
                    for drop in range(len(large)):
                        if large[:drop] + large[drop + 1:] == small:
                            issues.append({
                                "kind": "possible_missing_chord",
                                "differs": large[drop],
                                "lyric": base.lyric_line.strip(),
                                "variants": [variant(base_name, base),
                                             variant(name, pair)],
                            })
                            break
                # Otherwise: deliberate variation — no issue.
    return issues


if __name__ == "__main__":
    target = Path(sys.argv[1])
    tm = extract_anchor_map(target)
    print(tm.to_json())
    issues = cross_section_consistency(tm)
    if issues:
        print(f"\n// {len(issues)} cross-section inconsistencies:",
              file=sys.stderr)
        for iss in issues:
            print(json.dumps(iss, indent=1), file=sys.stderr)
