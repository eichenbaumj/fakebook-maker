#!/usr/bin/env python3
"""Apply CONFIRMED fixes from a promoted results file to charts/.

Groups fixes by file, applies each chord move with full precondition/
postcondition checks (see apply_fixes.move_chord), re-lints the touched
files, and prints a diff-style summary. Stale fixes (file changed since
the audit) abort that file, never guess.

Run: python3 -m qc.apply_confirmed <results.promoted.json> [--dry-run]
"""

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from qc.apply_fixes import move_chord, backup_charts  # noqa: E402
from qc.lint import lint_file  # noqa: E402


def main():
    promoted = Path(sys.argv[1])
    dry = "--dry-run" in sys.argv
    fixes = json.loads(promoted.read_text())["fixes"]
    if not fixes:
        print("no CONFIRMED fixes to apply")
        return 0
    if not dry:
        print(f"backup: {backup_charts('confirmed')}")

    by_file = {}
    for f in fixes:
        by_file.setdefault(f["file"], []).append(f)

    failures = 0
    for rel, file_fixes in sorted(by_file.items()):
        path = REPO / rel
        lines = path.read_text(encoding="utf-8").splitlines()
        ok = True
        applied = []
        for f in sorted(file_fixes, key=lambda x: -x["chord_line_no"]):
            idx = f["chord_line_no"] - 1
            new_line, err = move_chord(lines[idx], f["old_col"], f["chord"],
                                       f["new_col"])
            if err:
                print(f"ABORT {rel}: {f['finding_id']}: {err}")
                ok = False
                failures += 1
                break
            applied.append((f["finding_id"], lines[idx], new_line,
                            lines[idx + 1] if idx + 1 < len(lines) else ""))
            lines[idx] = new_line
        if not ok:
            continue
        for fid, old, new, lyric in applied:
            print(f"{rel} [{fid}]\n  - {old}\n  + {new}\n    {lyric}")
        if not dry:
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            errors = [x for x in lint_file(path) if x.severity == "ERROR"]
            if errors:
                print(f"POST-LINT ERRORS in {rel} (fix left in place, review!):")
                for e in errors:
                    print(f"  {e}")
                failures += 1

    print(f"\n{len(fixes)} fix(es) across {len(by_file)} file(s)"
          f"{' (dry run)' if dry else ''}; {failures} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
