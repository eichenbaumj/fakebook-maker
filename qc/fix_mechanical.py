#!/usr/bin/env python3
"""Apply the mechanical (no-musical-judgment) fixes the linter found:

1. Lint autofixes: º -> ° glyph typo, tab expansion.
2. Overflow reflows: compress spacing (or split a pair) so every line fits
   the rendered page, preserving all chord->word anchors.

Prints a unified-diff-style before/after for every touched line pair.
Run: python3 -m qc.fix_mechanical [--dry-run]
"""

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "fakebook"))

from build import is_chord_line  # noqa: E402
from qc.lint import lint_file  # noqa: E402
from qc.apply_fixes import (reflow_pair, reflow_chord_line,  # noqa: E402
                            backup_charts)


def fix_file(path: Path, dry: bool) -> list:
    """Returns list of human-readable change descriptions."""
    changes = []
    findings = lint_file(path)
    lines = path.read_text(encoding="utf-8").splitlines()

    # 1. character autofixes (line content swap, no structure change)
    for f in findings:
        if f.rule in ("non-ascii", "tab-character") and f.autofix:
            old = lines[f.line - 1]
            if old != f.autofix:
                lines[f.line - 1] = f.autofix
                changes.append(f"{path.name}:{f.line} [{f.rule}]\n"
                               f"  - {old}\n  + {f.autofix}")

    # 2. overflow reflows, bottom-up so line numbers stay valid
    overflow_lines = sorted({f.line for f in findings if f.rule == "overflow"},
                            reverse=True)
    handled = set()
    for lineno in overflow_lines:
        if lineno in handled:
            continue
        idx = lineno - 1
        line = lines[idx]
        if is_chord_line(line.strip()):
            nxt = lines[idx + 1] if idx + 1 < len(lines) else ""
            paired = (nxt.strip() and not nxt.strip().startswith("[")
                      and not is_chord_line(nxt.strip()))
            if paired:
                pairs, err = reflow_pair(line, nxt)
                if err:
                    changes.append(f"{path.name}:{lineno} SKIPPED: {err}")
                    continue
                new_lines = [x for pair in pairs for x in pair if x.strip()]
                lines[idx:idx + 2] = new_lines
                handled.add(lineno + 1)
                changes.append(f"{path.name}:{lineno} [overflow pair"
                               f"{' split' if len(pairs) == 2 else ''}]\n"
                               + "".join(f"  - {x}\n" for x in (line, nxt))
                               + "".join(f"  + {x}\n" for x in new_lines))
            else:
                new, err = reflow_chord_line(line)
                if err:
                    changes.append(f"{path.name}:{lineno} SKIPPED: {err}")
                    continue
                lines[idx] = new
                changes.append(f"{path.name}:{lineno} [overflow chords]\n"
                               f"  - {line}\n  + {new}")
        else:
            # over-width lyric: reflow together with the chord line above it
            prev = lines[idx - 1] if idx > 0 else ""
            if prev.strip() and is_chord_line(prev.strip()) \
                    and (idx - 1) + 1 not in handled:
                pairs, err = reflow_pair(prev, line)
                if err:
                    changes.append(f"{path.name}:{lineno} SKIPPED: {err}")
                    continue
                new_lines = [x for pair in pairs for x in pair if x.strip()]
                lines[idx - 1:idx + 1] = new_lines
                handled.add(lineno - 1)
                changes.append(f"{path.name}:{lineno - 1} [overflow pair"
                               f"{' split' if len(pairs) == 2 else ''}]\n"
                               + "".join(f"  - {x}\n" for x in (prev, line))
                               + "".join(f"  + {x}\n" for x in new_lines))
            else:
                from qc.apply_fixes import _compress_lyric, LYRIC_MAX
                need = len(line.rstrip()) - LYRIC_MAX
                new = _compress_lyric(line.rstrip(), need)
                if new is None:
                    changes.append(f"{path.name}:{lineno} SKIPPED: lone lyric "
                                   f"not compressible")
                    continue
                lines[idx] = new
                changes.append(f"{path.name}:{lineno} [overflow lyric]\n"
                               f"  - {line}\n  + {new}")

    if changes and not dry:
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return changes


def main():
    dry = "--dry-run" in sys.argv
    if not dry:
        print(f"backup: {backup_charts('mechanical')}")
    total = 0
    for path in sorted((REPO / "charts").glob("*.txt")):
        for change in fix_file(path, dry):
            print(change)
            total += 1
    print(f"\n{total} change(s){' (dry run)' if dry else ' applied'}")


if __name__ == "__main__":
    main()
