#!/usr/bin/env python3
"""The only code that writes to charts/. Two operations:

1. move_chord(): relocate one chord token to a new column (resolved from a
   word anchor by the caller) — used by the audit pipeline.
2. reflow_pair() / reflow_chord_line(): compress spacing on over-width lines
   so they fit the page, preserving every chord->word anchor exactly.

Safety invariants enforced on every rewrite:
- token multiset of the chord line is unchanged
- the lyric line's WORDS are unchanged (only inter-word spacing may shrink)
- every non-trailing chord keeps its anchor (same word, same offset when
  possible, never leaving the word's span)
- rewritten lines fit the rendered page budget
A run first tarballs charts/ into qc/backups/.
"""

import re
import sys
import tarfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "fakebook"))

import build  # noqa: E402
from qc.anchor import classify, words_of  # noqa: E402

LYRIC_MAX = int(build.CONTENT_W / build.CHAR_W)  # 73


def _anchor_seq(chord_line: str, lyric_line: str) -> list:
    """Ordered (chord, anchor word) sequence for non-trailing anchors."""
    words = words_of(lyric_line)
    seq = []
    for m in re.finditer(r"\S+", chord_line):
        a = classify(m.start(), m.group(), words)
        if a.placement in ("on_word", "during_word"):
            seq.append((m.group(), a.word))
    return seq


def chord_budget_ok(line: str) -> bool:
    width = 0.0
    for m in re.finditer(r"\S+", line):
        width = max(width, m.start() * build.CHAR_W
                    + len(m.group()) * 0.6 * build.CHORD_SIZE)
    return width <= build.CONTENT_W


def backup_charts(label: str = "") -> Path:
    backups = REPO / "qc" / "backups"
    backups.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out = backups / f"charts-{stamp}{('-' + label) if label else ''}.tgz"
    with tarfile.open(out, "w:gz") as tf:
        tf.add(REPO / "charts", arcname="charts")
    return out


# --- token placement ---------------------------------------------------------

def _tokens(line: str) -> list:
    return [(m.start(), m.group()) for m in re.finditer(r"\S+", line)]


def _emit(placements: list) -> tuple[str, list]:
    """Render [(target_col, text)] left-to-right, min 1 space between tokens.

    Returns (line, actual_tokens). A token shifts right when a collision
    forces it; callers check the drift against their tolerance.
    """
    line = ""
    for target, text in sorted(placements):
        col = max(target, 0)
        if line:
            col = max(col, len(line) + 1)
        line = line + " " * (col - len(line)) + text
    return line, _tokens(line)


def move_chord(chord_line: str, old_col: int, chord_text: str,
               new_col: int) -> tuple[str, str]:
    """Move one token to a new column. Returns (new_line, error)."""
    toks = _tokens(chord_line)
    if (old_col, chord_text) not in toks:
        return chord_line, (f"stale fix: {chord_text!r} not at col {old_col} "
                            f"(line tokens: {toks})")
    placements = [(new_col if (c, t) == (old_col, chord_text) else c, t)
                  for c, t in toks]
    line, actual = _emit(placements)
    # postconditions
    if sorted(t for _, t in actual) != sorted(t for _, t in toks):
        return chord_line, "token multiset changed"
    for (want, wtext), (got, gtext) in zip(sorted(placements), actual):
        if abs(got - want) > 2:
            return chord_line, (f"collision displaced {gtext!r} "
                                f"{abs(got - want)} cols from target")
    if not chord_budget_ok(line):
        return chord_line, "rewritten line exceeds page width"
    return line, ""


# --- overflow reflow -----------------------------------------------------------

def _compress_lyric(lyric: str, need: int) -> str | None:
    """Shrink interior multi-space runs by `need` columns total.

    Leading indent is preserved; every inter-word gap keeps >=1 space.
    Returns None if not enough slack.
    """
    m = re.match(r"^(\s*)(.*?)(\s*)$", lyric)
    lead, body = m.group(1), m.group(2)
    runs = [(g.start(), len(g.group())) for g in re.finditer(r"\s{2,}", body)]
    slack = sum(l - 1 for _, l in runs)
    if slack < need:
        return None
    # Shave widest runs first, one space at a time.
    gaps = {s: l for s, l in runs}
    remaining = need
    while remaining > 0:
        s = max(gaps, key=lambda k: gaps[k])
        if gaps[s] <= 1:
            break
        gaps[s] -= 1
        remaining -= 1
    out, last = [], 0
    for s, l in sorted((s, l) for s, l in runs):
        out.append(body[last:s])
        out.append(" " * gaps[s])
        last = s + l
    out.append(body[last:])
    return lead + "".join(out)


def _chord_overflow_cols(line: str) -> int:
    """How many grid columns past the budget this chord line renders."""
    width = 0.0
    for m in re.finditer(r"\S+", line):
        width = max(width, m.start() * build.CHAR_W
                    + len(m.group()) * 0.6 * build.CHORD_SIZE)
    over = width - build.CONTENT_W
    return max(0, int(over / build.CHAR_W) + (1 if over % build.CHAR_W else 0))


def reflow_pair(chord_line: str, lyric_line: str) -> tuple[list, str]:
    """Fit an over-width chord/lyric pair, preserving anchors.

    Returns ([(chord_line, lyric_line), ...], error): one pair when
    compressing inter-word spacing sufficed, two pairs when the lyric had
    to be split at a phrase boundary. A chord line whose trailing
    turnaround overflows forces lyric compression too — trailing chords
    are never pulled left into the sung text.
    """
    lyric = lyric_line.rstrip()
    need = max(len(lyric) - LYRIC_MAX, _chord_overflow_cols(chord_line))
    if need <= 0:
        return [(chord_line.rstrip(), lyric)], ""
    compressed = _compress_lyric(lyric, need)
    if compressed is not None:
        new_chord, new_lyric, err = _rebuild_on_lyric(chord_line, lyric_line,
                                                      compressed)
        if not err:
            return [(new_chord, new_lyric)], ""
    return _split_pair(chord_line, lyric_line)


def _rebuild_on_lyric(chord_line: str, lyric_line: str,
                      new_lyric: str) -> tuple[str, str, str]:
    """Re-place every chord over a re-spaced version of the same lyric."""
    old_words = words_of(lyric_line)
    new_words = words_of(new_lyric)
    if [w.text for w in old_words] != [w.text for w in new_words]:
        return chord_line, lyric_line, "reflow altered lyric words (bug)"
    col_map = {ow.col: nw.col for ow, nw in zip(old_words, new_words)}

    # Re-anchor each chord.
    placements = []
    last_word_end_old = old_words[-1].end_col if old_words else 0
    last_word_end_new = new_words[-1].end_col if new_words else 0
    for col, text in _tokens(chord_line):
        a = classify(col, text, old_words)
        if a.placement in ("on_word", "during_word") and a.word_col in col_map:
            new_word_col = col_map[a.word_col]
            target = new_word_col + a.offset
            if a.placement == "during_word":
                # never drift past the following word's new onset
                nxt = min((w.col for w in new_words if w.col > new_word_col),
                          default=10**6)
                target = min(target, nxt - len(text) - 1)
                target = max(target, new_word_col)
        elif a.placement == "trailing":
            target = last_word_end_new + (col - last_word_end_old)
        else:  # leading
            target = col
        placements.append((target, text, a.placement))

    new_chord, actual = _emit([(t, x) for t, x, _ in placements])
    if not chord_budget_ok(new_chord):
        # Repack the trailing turnaround with tighter (>=1 space) gaps, but
        # never left of the sung text — trailing chords must stay trailing.
        anchored = [(t, x) for t, x, p in placements if p != "trailing"]
        trailing = sorted((t, x) for t, x, p in placements if p == "trailing")
        line, _ = _emit(anchored)
        floor = max(last_word_end_new + 1, len(line) + 1 if line else 0)
        for _, text in trailing:
            col = max(floor, len(line) + 2 if line else floor)
            line = line + " " * (col - len(line)) + text
        new_chord = line
        if not chord_budget_ok(new_chord):
            return chord_line, lyric_line, "chord line cannot be fit"

    if sorted(t for _, t in _tokens(new_chord)) != sorted(t for _, t in _tokens(chord_line)):
        return chord_line, lyric_line, "token multiset changed (bug)"
    if _anchor_seq(new_chord, new_lyric) != _anchor_seq(chord_line, lyric_line):
        return chord_line, lyric_line, (
            "compression would move a chord onto a different word — manual fix")
    return new_chord, new_lyric, ""


def _split_pair(chord_line: str, lyric_line: str) -> tuple[list, str]:
    """Split an uncompressible over-width pair into two pairs.

    The split lands at the word boundary nearest the middle, preferring a
    punctuation boundary (,;.!?) when one is close. Chords partition by
    which side their anchor word falls on; trailing chords follow part 2.
    """
    lyric = lyric_line.rstrip()
    words = [w for w in words_of(lyric) if not w.is_syllable_sep]
    if len(words) < 4:
        return [(chord_line, lyric_line)], "too few words to split"
    lead = re.match(r"^\s*", lyric).group()

    mid = len(lyric) / 2
    def boundary_score(w):
        punct_bonus = -8 if w.text.rstrip()[-1:] in ",;.!?" else 0
        return abs(w.end_col - mid) + punct_bonus
    candidates = [w for w in words[1:-1]]
    candidates.sort(key=boundary_score)
    split_word = None
    all_words = words_of(lyric)
    for cand in candidates:
        idx = next(j for j, w in enumerate(all_words) if w.col == cand.col)
        rest = all_words[idx + 1:]
        if not rest or rest[0].is_syllable_sep:
            continue  # never split inside a hyphenated syllable group
        part1 = lyric[:cand.end_col].rstrip()
        part2 = lead + lyric[rest[0].col:].rstrip()
        if len(part1) <= LYRIC_MAX and len(part2) <= LYRIC_MAX:
            split_word, part1_lyric, part2_lyric = cand, part1, part2
            part2_first_col = rest[0].col
            break
    if split_word is None:
        return [(chord_line, lyric_line)], "no split point fits"

    shift = part2_first_col - len(lead)
    old_words = words_of(lyric_line)
    last_word = max((w for w in old_words if not w.is_syllable_sep),
                    key=lambda w: w.end_col)
    p2_words = words_of(part2_lyric)
    p2_last_end = p2_words[-1].end_col if p2_words else len(lead)

    part1_placements, part2_placements = [], []
    for col, text in _tokens(chord_line):
        a = classify(col, text, old_words)
        if a.placement == "trailing":
            part2_placements.append((p2_last_end + (col - last_word.end_col),
                                     text))
        elif a.placement == "leading" or (a.word_col > -1
                                          and a.word_col <= split_word.col):
            part1_placements.append((col, text))
        else:
            part2_placements.append((col - shift, text))

    part1_chord, _ = _emit(part1_placements)
    part2_chord, _ = _emit(part2_placements)
    for line in (part1_chord, part2_chord):
        if not chord_budget_ok(line):
            return [(chord_line, lyric_line)], "split halves still overflow"
    got = sorted(t for line in (part1_chord, part2_chord)
                 for _, t in _tokens(line))
    if got != sorted(t for _, t in _tokens(chord_line)):
        return [(chord_line, lyric_line)], "token multiset changed (bug)"
    combined = (_anchor_seq(part1_chord, part1_lyric)
                + _anchor_seq(part2_chord, part2_lyric))
    if combined != _anchor_seq(chord_line, lyric_line):
        return [(chord_line, lyric_line)], (
            "split would move a chord onto a different word — manual fix")
    return [(part1_chord, part1_lyric), (part2_chord, part2_lyric)], ""


def reflow_chord_line(chord_line: str) -> tuple[str, str]:
    """Fit an over-width standalone chord line by shrinking gaps (>=2 kept
    where the author used >=2, min 1)."""
    line = chord_line.rstrip()
    guard = 0
    while not chord_budget_ok(line) and guard < 200:
        runs = list(re.finditer(r" {3,}", line))
        if runs:
            widest = max(runs, key=lambda r: len(r.group()))
            line = (line[:widest.start()] + " " * (len(widest.group()) - 1)
                    + line[widest.end():])
        else:
            runs2 = list(re.finditer(r" {2,}", line))
            if not runs2:
                return chord_line, "cannot fit chord line"
            widest = max(runs2, key=lambda r: len(r.group()))
            line = (line[:widest.start()] + " " * (len(widest.group()) - 1)
                    + line[widest.end():])
        guard += 1
    return line, ""
