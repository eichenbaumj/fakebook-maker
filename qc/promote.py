#!/usr/bin/env python3
"""Promotion: turn agent findings into tiers + an executable fix list.

Agents propose; this code disposes. Every finding is mechanically validated
against the chart before any tier is assigned — a hallucinated line number,
quote, chord, or word kills the finding here, deterministically.

Tiers:
  CONFIRMED — auto-applicable: a pure move of an existing chord to an 'on'
              anchor at an existing word, strong evidence, refuters onside.
  PLAUSIBLE — real signal but needs the owner's eyes.
  DROPPED   — failed mechanical validation (reported, never applied).

Run: python3 -m qc.promote <results.json>  ->  writes <results>.promoted.json
"""

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from qc.anchor import extract_anchor_map, classify, words_of, _norm_word  # noqa: E402

MAX_AUTO_MOVE_COLS = 16


def _find_pair(tm, chord_line_no):
    for sec in tm.sections:
        for pair in sec.pairs:
            if pair.chord_line_no == chord_line_no:
                return sec, pair
    return None, None


def _word_occurrences(lyric_line, target_word):
    return [w for w in words_of(lyric_line)
            if not w.is_syllable_sep and not w.is_prefix
            and _norm_word(w.text) == _norm_word(target_word)]


def validate_and_tier(finding, verdicts, tm):
    """Returns (tier, detail dict). tier in CONFIRMED|PLAUSIBLE|DROPPED."""
    f = finding
    sec, pair = _find_pair(tm, f["chord_line_no"])
    if pair is None or pair.mode != "sung":
        return "DROPPED", {"why": f"no sung pair at line {f['chord_line_no']}"}

    # 1. quote check (whitespace-tolerant, content-exact)
    if " ".join(f["current_lyric_quote"].split()) != \
            " ".join((pair.lyric_line or "").split()):
        return "DROPPED", {"why": "lyric quote does not match the chart"}

    # 2. the chord token must exist on that line, at the claimed anchor
    tokens = [(m.start(), m.group())
              for m in re.finditer(r"\S+", pair.chord_line)]
    words = words_of(pair.lyric_line)
    candidates = []
    for col, text in tokens:
        if text != f["chord"]:
            continue
        a = classify(col, text, words)
        if _norm_word(a.word or "") == _norm_word(f["current_anchor_word"]):
            candidates.append((col, text, a))
    if not candidates:
        return "DROPPED", {"why": f"chord {f['chord']!r} not found anchored "
                                  f"at {f['current_anchor_word']!r}"}
    old_col, chord_text, cur_anchor = candidates[0]

    # 3. proposed word must exist in the lyric
    occs = _word_occurrences(pair.lyric_line, f["proposed_anchor_word"])
    if not occs:
        return "DROPPED", {"why": f"proposed word "
                                  f"{f['proposed_anchor_word']!r} not in lyric"}
    target_word = min(occs, key=lambda w: abs(w.col - old_col))
    new_col = target_word.col

    detail = {
        "old_col": old_col, "new_col": new_col,
        "move_cols": abs(new_col - old_col),
        "section": sec.name,
        "chord_line": pair.chord_line, "lyric_line": pair.lyric_line,
    }

    # 4. evidence gate (as reported by the critic, which promotion trusts
    # only for evidence LABELS — locations were verified above)
    ev = f["evidence"]
    strong = ((ev["stageA"] == "agree" and ev["stageB"] == "agree")
              or (ev["consistency"] == "agree"
                  and (ev["stageA"] == "agree" or ev["stageB"] == "agree"))
              or (ev["degenerate"] and ev["stageA"] == "agree"
                  and ev["stageB"] == "silent"))
    any_evidence = (ev["stageA"] == "agree" or ev["stageB"] == "agree"
                    or ev["consistency"] == "agree" or ev["degenerate"])
    disagree = ev["stageA"] == "disagree" or ev["stageB"] == "disagree"
    if not any_evidence:
        return "DROPPED", {**detail, "why": "no supporting evidence"}

    # 5. refuter gate
    d = {v["id"]: v["verdict"] for v in verdicts.get("defender", [])}
    p = {v["id"]: v["verdict"] for v in verdicts.get("prosody", [])}
    vd, vp = d.get(f["id"], "unsure"), p.get(f["id"], "unsure")
    refuted = "refute" in (vd, vp)
    upheld = (vd == "uphold" or vp == "uphold") and not refuted

    confirmed = (strong and not disagree and upheld
                 and f["type"] == "misplacement"
                 and f["proposed_anchor_type"] == "on"
                 and detail["move_cols"] <= MAX_AUTO_MOVE_COLS
                 and detail["move_cols"] > 0)
    tier = "CONFIRMED" if confirmed else "PLAUSIBLE"
    detail["verdicts"] = {"defender": vd, "prosody": vp}
    return tier, detail


def promote(results_path: Path) -> Path:
    data = json.loads(results_path.read_text())
    out = {"tunes": [], "fixes": []}
    for tune in data["tunes"]:
        slug = tune["slug"]
        tm = extract_anchor_map(REPO / "charts" / f"{slug}.txt")
        entry = {"slug": slug, "findings": [],
                 "chart_level_notes": (tune.get("c") or {}).get(
                     "chart_level_notes", []),
                 "stageA": {k: (tune.get("a") or {}).get(k) for k in
                            ("known", "confidence", "recall_notes")},
                 "stageB": {k: (tune.get("b") or {}).get(k) for k in
                            ("retrieval", "source_url", "source_key_guess")}}
        for f in ((tune.get("c") or {}).get("findings") or []):
            tier, detail = validate_and_tier(f, tune.get("verdicts", {}), tm)
            entry["findings"].append({"tier": tier, **f, "detail": detail})
            if tier == "CONFIRMED":
                out["fixes"].append({
                    "file": f"charts/{slug}.txt",
                    "chord_line_no": f["chord_line_no"],
                    "chord": f["chord"],
                    "old_col": detail["old_col"],
                    "new_col": detail["new_col"],
                    "finding_id": f["id"],
                })
        out["tunes"].append(entry)
    dest = results_path.with_suffix(".promoted.json")
    dest.write_text(json.dumps(out, indent=1))
    return dest


if __name__ == "__main__":
    dest = promote(Path(sys.argv[1]))
    data = json.loads(dest.read_text())
    for tune in data["tunes"]:
        tiers = [f["tier"] for f in tune["findings"]]
        print(f"{tune['slug']}: {len(tiers)} finding(s) "
              f"[{', '.join(tiers) if tiers else 'clean'}] "
              f"A:{tune['stageA'].get('known')} "
              f"B:{tune['stageB'].get('retrieval')}")
        for f in tune["findings"]:
            print(f"  {f['tier']:9} {f['id']} {f['type']}: {f['chord']} "
                  f"{f['current_anchor_word']!r} -> "
                  f"{f['proposed_anchor_word']!r} "
                  f"({f['detail'].get('why', 'ok')})")
    print(f"\n{len(data['fixes'])} CONFIRMED fix(es) -> {dest}")
