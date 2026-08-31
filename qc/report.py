#!/usr/bin/env python3
"""Render promoted audit results as a human review report (markdown).

Every finding gets a monospace before/after block showing exactly how the
pair will read, so the owner can judge at sight-reading speed.

Run: python3 -m qc.report <results.promoted.json> [out.md]
"""

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from qc.apply_fixes import move_chord  # noqa: E402

TIER_ORDER = {"CONFIRMED": 0, "PLAUSIBLE": 1, "DROPPED": 2}


def _block(finding):
    d = finding["detail"]
    lines = [f"```", d.get("chord_line", "?"), d.get("lyric_line", "?")]
    if "old_col" in d and "new_col" in d and d.get("chord_line"):
        fixed, err = move_chord(d["chord_line"], d["old_col"],
                                finding["chord"], d["new_col"])
        if not err:
            lines += ["--- after fix ---", fixed, d.get("lyric_line", "?")]
        else:
            lines += [f"(fix preview unavailable: {err})"]
    lines.append("```")
    return "\n".join(lines)


def render(promoted_path: Path) -> str:
    data = json.loads(promoted_path.read_text())
    out = ["# Fake book audit report", ""]
    n_conf = len(data.get("fixes", []))
    n_tunes = len(data["tunes"])
    n_findings = sum(len(t["findings"]) for t in data["tunes"])
    out.append(f"{n_tunes} tune(s) audited — {n_findings} finding(s), "
               f"{n_conf} CONFIRMED (auto-applicable).")
    out.append("")

    for tune in data["tunes"]:
        out.append(f"## {tune['slug']}")
        a, b = tune["stageA"], tune["stageB"]
        out.append(f"- blind reconstruction: known={a.get('known')} "
                   f"({a.get('confidence')})")
        src = b.get("source_url") or "none"
        out.append(f"- published source: {b.get('retrieval')} — {src} "
                   f"(key {b.get('source_key_guess') or '?'})")
        if not tune["findings"]:
            out.append("- **clean** — no placement findings")
        for f in sorted(tune["findings"],
                        key=lambda x: TIER_ORDER.get(x["tier"], 9)):
            d = f["detail"]
            out.append("")
            out.append(f"### {f['tier']} `{f['id']}` — {f['type']}: "
                       f"**{f['chord']}** moves "
                       f"{f['current_anchor_word']!r} → "
                       f"{f['proposed_anchor_word']!r}")
            ev = f["evidence"]
            out.append(f"- evidence: knowledge={ev['stageA']}, "
                       f"source={ev['stageB']}, "
                       f"consistency={ev['consistency']}, "
                       f"degenerate={ev['degenerate']}"
                       + (f"; refuters: defender={d['verdicts']['defender']}, "
                          f"prosody={d['verdicts']['prosody']}"
                          if "verdicts" in d else ""))
            out.append(f"- {f['rationale']}")
            if f["tier"] == "DROPPED":
                out.append(f"- dropped: {d.get('why')}")
                continue
            out.append(_block(f))
        if tune["chart_level_notes"]:
            out.append("")
            out.append("FYI notes:")
            for note in tune["chart_level_notes"]:
                out.append(f"- {note}")
        out.append("")
    return "\n".join(out)


if __name__ == "__main__":
    src = Path(sys.argv[1])
    dest = (Path(sys.argv[2]) if len(sys.argv) > 2
            else REPO / "qc" / "reports" / (src.stem + ".md"))
    dest.write_text(render(src))
    print(f"wrote {dest}")
