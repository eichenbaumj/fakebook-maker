#!/usr/bin/env python3
"""Deterministic linter for the fake book charts.

Every rule here is mechanically checkable — no musical judgment. Findings:
  ERROR — will render wrong (overflow, misparse, broken pairing)
  WARN  — likely wrong or fragile (ambiguous classification, bad tokens)
  INFO  — style/FYI (non-ASCII glyphs, notation inconsistencies)

Run: python3 -m qc.lint [chart.txt ...]   (defaults to all of charts/)
"""

import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "fakebook"))

import build  # noqa: E402
from build import is_chord_line, is_chord_token  # noqa: E402
from qc.theory import parse_chord, parse_key, enharmonic_style_issue  # noqa: E402

LYRIC_MAX = int(build.CONTENT_W / build.CHAR_W)  # 73 chars at 12pt


@dataclass
class Finding:
    file: str
    line: int          # 1-based; 0 = file-level
    severity: str      # ERROR|WARN|INFO
    rule: str
    message: str
    autofix: str = ""  # replacement line, when mechanically safe

    def __str__(self):
        loc = f"{self.file}:{self.line}" if self.line else self.file
        return f"{self.severity:5} {self.rule:20} {loc}: {self.message}"


def _content_start(lines):
    """Mirror build.parse_chart's metadata window; also return metadata lines."""
    meta = []
    start = 1
    for i in range(1, min(len(lines), 5)):
        s = lines[i].strip()
        if not s:
            continue
        if re.match(r"^(Key|Tempo|Capo|Time|Transposed)\s*:", s, re.IGNORECASE):
            meta.append((i + 1, s))
            start = i + 1
        else:
            break
    return start, meta


def lint_file(path: Path) -> list:
    f = []
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    name = path.name
    if not lines:
        return [Finding(name, 0, "ERROR", "empty-file", "file is empty")]

    # R1: tabs anywhere destroy column alignment silently.
    for i, line in enumerate(lines, 1):
        if "\t" in line:
            f.append(Finding(name, i, "ERROR", "tab-character",
                             "tab character breaks monospace alignment",
                             autofix=line.expandtabs(4)))

    # R2: non-ASCII. º (ordinal) is a typo for ° (degree); both are minority
    # style vs 'dim' but only the wrong glyph is auto-fixed.
    for i, line in enumerate(lines, 1):
        for ch in set(line):
            if ord(ch) > 127:
                sev = "WARN" if ch == "º" else "INFO"
                fix = line.replace("º", "°") if ch == "º" else ""
                f.append(Finding(name, i, sev, "non-ascii",
                                 f"non-ASCII {ch!r} (U+{ord(ch):04X})",
                                 autofix=fix))

    # R3: title line shape.
    if " - " not in lines[0]:
        f.append(Finding(name, 1, "INFO", "title-no-composer",
                         f"no ' - ' in title line: {lines[0].strip()!r}"))

    start, meta = _content_start(lines)
    # R4: multiple metadata lines — parse_chart keeps only the last.
    if len(meta) > 1:
        f.append(Finding(name, meta[0][0], "ERROR", "metadata-dropped",
                         f"{len(meta)} metadata lines; the PDF only shows the "
                         f"last one — combine with ' | '"))
    key = parse_key(meta[-1][1]) if meta else None
    if not meta:
        f.append(Finding(name, 2, "INFO", "no-key",
                         "no 'Key:' metadata line"))

    seen_enharmonic = set()
    for i in range(start, len(lines)):
        line = lines[i]
        s = line.strip()
        lineno = i + 1
        if not s or s.startswith("["):
            continue

        is_chords = is_chord_line(s)
        tokens = s.split()
        # Same countable-token ratio the classifier uses (bars/slashes/repeat
        # marks are neutral).
        countable = [t for t in tokens
                     if parse_chord(t).kind not in ("bar", "slash", "repeat")]
        ratio = (sum(1 for t in countable if is_chord_token(t)) / len(countable)
                 if countable else 0.0)

        # R5: near-threshold classification is fragile.
        if 0.4 <= ratio < 0.65 and len(countable) > 1:
            f.append(Finding(name, lineno, "WARN", "ambiguous-line",
                             f"{ratio:.0%} chord tokens — classified as "
                             f"{'chords' if is_chords else 'lyrics'}: {s[:50]!r}"))

        if is_chords:
            # R6: invalid tokens on chord lines.
            for t in tokens:
                c = parse_chord(t)
                if c.kind == "invalid":
                    f.append(Finding(name, lineno, "WARN", "bad-chord-token",
                                     f"{t!r}: {'; '.join(c.problems)}"))
                elif c.problems:
                    f.append(Finding(name, lineno, "WARN", "chord-token",
                                     f"{t!r}: {'; '.join(c.problems)}"))
                # R7: enharmonic style (FYI, once per spelling per file).
                issue = enharmonic_style_issue(c, key)
                if issue and issue not in seen_enharmonic:
                    seen_enharmonic.add(issue)
                    f.append(Finding(name, lineno, "INFO", "enharmonic", issue))

            # R8: chord line followed by blank then lyric = broken pairing.
            if (i + 2 < len(lines) and not lines[i + 1].strip()
                    and lines[i + 2].strip()
                    and not lines[i + 2].strip().startswith("[")
                    and not is_chord_line(lines[i + 2].strip())):
                f.append(Finding(name, lineno, "WARN", "pair-broken-by-blank",
                                 "blank line between chords and lyrics — they "
                                 "won't pair in the PDF"))

            # R9: chord-line width (tokens sit on the lyric grid; glyphs
            # advance at CHORD_SIZE).
            width = 0.0
            for m in re.finditer(r"\S+", line):
                width = max(width, m.start() * build.CHAR_W
                            + len(m.group()) * 0.6 * build.CHORD_SIZE)
            if width > build.CONTENT_W:
                over = int((width - build.CONTENT_W) / build.CHAR_W) + 1
                f.append(Finding(name, lineno, "ERROR", "overflow",
                                 f"chord line ~{over} char(s) past right margin"))
        else:
            # R9: lyric-line width.
            if len(line.rstrip()) > LYRIC_MAX:
                over = len(line.rstrip()) - LYRIC_MAX
                f.append(Finding(name, lineno, "ERROR", "overflow",
                                 f"lyric line {over} char(s) past right margin "
                                 f"(max {LYRIC_MAX})"))

    return f


def main(argv):
    targets = ([Path(a) for a in argv[1:]]
               or sorted((REPO / "charts").glob("*.txt")))
    all_f = []
    for t in targets:
        all_f.extend(lint_file(t))
    order = {"ERROR": 0, "WARN": 1, "INFO": 2}
    all_f.sort(key=lambda x: (order[x.severity], x.file, x.line))
    for x in all_f:
        print(x)
    n = {s: sum(1 for x in all_f if x.severity == s) for s in order}
    print(f"\n{len(targets)} file(s): "
          f"{n['ERROR']} errors, {n['WARN']} warnings, {n['INFO']} info")
    return 1 if n["ERROR"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
