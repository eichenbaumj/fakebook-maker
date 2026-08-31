#!/usr/bin/env python3
"""Emit per-tune audit inputs for the agent pipeline.

Two files per tune under qc/audit/:
  <slug>.lyrics.json — title/composer/key + whitespace-normalized lyrics
                       ONLY (no chords, no alignment gaps) for the blind
                       reconstruction agent.
  <slug>.chart.json  — the full anchor map + cross-section consistency
                       evidence + raw line pairs for the critic agent.

Run: python3 -m qc.audit_input <slug> [<slug> ...]   (slug = filename stem)
"""

import json
import re
import sys
from dataclasses import asdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from qc.anchor import extract_anchor_map, cross_section_consistency  # noqa: E402

AUDIT_DIR = REPO / "qc" / "audit"


def key_info(fname: str, base_key: str) -> dict:
    overrides = json.loads((REPO / "qc" / "keys_overrides.json").read_text())
    o = overrides.get(fname)
    if o:
        return {"base": o["base"], "changes": o.get("changes", [])}
    return {"base": base_key, "changes": []}


def build_inputs(slug: str) -> tuple[Path, Path]:
    path = REPO / "charts" / f"{slug}.txt"
    tm = extract_anchor_map(path)
    keys = key_info(tm.file, tm.key)

    lyrics = {
        "file": tm.file, "title": tm.title, "composer": tm.composer,
        "key": keys["base"],
        "key_changes": [f"from source line {c['from_line']}: {c['key']}"
                        for c in keys["changes"]],
        "sections": [],
    }
    for sec in tm.sections:
        sung = [re.sub(r"\s+", " ", p.lyric_line).strip()
                for p in sec.pairs if p.mode == "sung"]
        sung += [re.sub(r"\s+", " ", t).strip() for _, t in sec.lone_lyrics]
        lyrics["sections"].append({"name": sec.name, "lyric_lines": sung})

    chart = asdict(tm)
    chart["key_info"] = keys
    chart["consistency_issues"] = cross_section_consistency(tm)

    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    lp = AUDIT_DIR / f"{slug}.lyrics.json"
    cp = AUDIT_DIR / f"{slug}.chart.json"
    lp.write_text(json.dumps(lyrics, indent=1))
    cp.write_text(json.dumps(chart, indent=1))
    return lp, cp


if __name__ == "__main__":
    for slug in sys.argv[1:]:
        lp, cp = build_inputs(slug)
        print(f"{slug}: {lp.name} ({lp.stat().st_size}B), "
              f"{cp.name} ({cp.stat().st_size}B)")
