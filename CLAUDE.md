# fakebook-maker

Plain-text chord charts → a navigable PDF fake book. Designed for sight-reading
on a ~14" laptop screen on a piano stand. See README.md for the full story.

## Quick start

```bash
pip install reportlab
python3 fakebook/build.py
# → fakebook/fakebook.pdf
```

## Adding a new tune

1. Create `charts/<slug>.txt` using the chords-over-lyrics format (see `charts/demo-tune.txt`)
2. Run `python3 fakebook/build.py`
3. Open `fakebook/fakebook.pdf`

Never overwrite an existing chart. A new arrangement (reharm, gospel version)
goes in its own file — `charts/<slug>-gospel.txt` or similar — with a distinct
title like `Title (Gospel)`, in the key of the existing chart and keeping its
lyrics.

**Copyright:** charts you write locally are for personal use. Never commit
copyrighted lyrics to a public repo or fork — this repo ships only
public-domain and original demo charts for that reason.

## Chart format

```
Title - Composer(s)
Key: Fm | Tempo: Ballad          ← optional metadata

[Section Name]
Chord1    Chord2       Chord3
Lyrics aligned under chords
```

- First line = title + composer, split on the first ` - `
- `[Brackets]` = section headers; annotate modulations (`[Chorus - up half step]`)
- Chord lines detected automatically (majority of tokens parse as chords)
- Spacing/alignment is preserved exactly — this is what makes it sight-readable
- **73 chars max** per line (lyrics render in Courier 12pt; the build warns on overflow)

## PDF output

- Portrait, letter size, Courier monospace for chord/lyric blocks
- Helvetica titles and section headers; alphabetical clickable TOC; PDF bookmarks
- Chord tokens draw at `MARGIN_LEFT + column * CHAR_W` on the 12pt lyric grid
  (chords 11pt bold) so chord columns never drift from lyric columns

## Build flags

`--charts-dir DIR`, `--include-list FILE` (one filename per line, `#` comments),
`--output FILE`, `--title TITLE` — for alternate editions/subsets of the book.
A listed chart that doesn't exist is an error, not a warning.

## QC toolkit (qc/)

Run from the repo root:

```bash
python3 -m qc.lint                 # overflow / glyph / pairing / bad-token checks (0 errors expected)
python3 -m pytest tests/ -q      # chord grammar, anchors, reflow, renderer grid, CLI
python3 qc/verify_pdf.py overflow  # no ink past the right margin in the rendered PDF
```

- Chord-line detection uses the real grammar in `qc/theory.py` (via `parse_chord`),
  not "starts with A-G" — lyric lines like "Call me later" stay lyrics.
- The grammar accepts `m`, `mi`, and `min` minor spellings, and disambiguates
  `-` (after root = minor: `E-7`; after extension digit = flat alteration: `Eb7-5`).
- `qc/anchor.py` maps every chord to the lyric word it sits over; its
  cross-section consistency check catches copied chord rows that drift.
- Audit pipeline (blind reconstruction + web source + critic + refuters):
  inputs via `python3 -m qc.audit_input <slug>`, promotion via `python3 -m qc.promote`,
  reports via `python3 -m qc.report`, fixes via `python3 -m qc.apply_confirmed`.
  Its working dirs (`qc/audit/`, `qc/reports/`) are gitignored here.
- Don't modify `fakebook/build.py` to handle weird tokens. If a line isn't
  classifying right, it's probably a parse-the-source issue, not a renderer issue.

## Tests

Some anchor tests are tied to specific private-corpus charts and route through
the `corpus(...)` helper — they skip in this repo (expected: 96 passed, 5 skipped).

## Dependencies

- Python 3
- `reportlab` (build) · `pytest`, `pdfplumber` (dev/QC)
