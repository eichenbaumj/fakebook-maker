# fakebook-maker

Turn plain-text chord charts into a single, navigable PDF fake book.

You write charts in the simplest possible format — chords over lyrics, sections in brackets — and `build.py` renders a letter-size PDF with an alphabetical, clickable table of contents, PDF bookmarks for every tune, and monospace chord/lyric blocks whose alignment is preserved exactly. It was built for one use case: a laptop propped on a piano stand, read at sight, in dim lighting.

## Quick start

```bash
pip install reportlab
python3 fakebook/build.py
open fakebook/fakebook.pdf
```

The build scans `charts/*.txt` and prints one `Parsed: <Title>` line per tune. This repo ships two demo charts (`danny-boy.txt` and `demo-tune.txt`), so a fresh clone builds a small working book immediately. Add your own charts to `charts/` and rebuild.

Alternate editions (a subset of the book, a different title or output path):

```bash
python3 fakebook/build.py --include-list my-setlist.txt --output setlist.pdf --title "Tonight's Set"
```

`--include-list` takes a file with one chart filename per line (`#` comments allowed); `--charts-dir` points at a different chart folder.

## Chart format

This is `charts/demo-tune.txt`, which exercises most of the format:

```
Demo Tune - An original example for this repo
Key: C (modulates to Db) | Tempo: Medium Swing

[Intro]
C6/9     E-7      A7b9     Dm7      G13
| /  /  /  / | /  /  /  / | /  /  /  / |

[Verse]
C            E-7          A7b9
This is a demo tune in plain text
```

- **Line 1** is `Title - Composer`, split on the first ` - `.
- An optional metadata line (`Key: ... | Tempo: ...`) renders under the title. Note modulations in the key (`Key: C (modulates to Db)`) and on section headers (`[Chorus - up half step]`).
- `[Brackets]` are section headers.
- Chord lines are detected automatically — no markup. Whatever spacing you write is exactly what renders, so chords stay over the syllables you put them on. Everything renders in Courier; chords bold, lyrics regular, each chord token drawn at its text-file column on the lyric grid so nothing drifts.
- Keep lines to **73 characters max** (the build warns about anything that would overflow the page).
- Rhythm lines like `| /  /  /  / |` render as plain text under the chord header — right for a vamp bar.

## Chord grammar

Chord-line detection doesn't mean "starts with A–G" — a lyric like "Call me later" would qualify. `qc/theory.py` is a real chord-symbol tokenizer, and a line counts as chords only if a majority of its tokens parse. The grammar handles the messy conventions real charts use:

- `-` is overloaded: right after a root it means minor (`E-7` = `Em7`); after an extension digit it means a flat alteration (`Eb7-5` = `Eb7b5`). A tokenizer can tell these apart; one regex can't.
- `m`, `mi`, and `min` all spell minor. Slash basses, `N.C.`, `°`/`dim`, alterations (`B7#5b9`), and repeat marks (`x12`) all parse.
- Comparison happens in interval-from-key space, so a chart in A can be checked against a source in C.

## QC toolkit

```bash
pip install pytest pdfplumber   # dev dependencies
python3 -m qc.lint              # overflow / glyph / pairing / bad-token checks
python3 -m pytest tests/ -q    # chord grammar, anchors, reflow, renderer grid
python3 qc/verify_pdf.py overflow   # no ink past the right margin in the rendered PDF
```

Run `qc` modules from the repo root. `qc/anchor.py` maps every chord to the lyric word it sits over and cross-checks repeated sections for drift — the class of bug where a copied chord row is one column off in verse 2.

Tests marked with `corpus(...)` skip on a fresh clone (they exercise charts from the private corpus this repo doesn't ship); expect `96 passed, 5 skipped`.

There's also an LLM audit pipeline (`qc/audit_input.py`, `qc/promote.py`, `qc/report.py`, `qc/apply_confirmed.py`): for each tune it packages the chart for blind reconstruction against a model's knowledge and a published source, a conservative critic reviews the diffs, adversarial refuters attack each finding, and only mechanically validated, confirmed findings get machine-applied back to the chart. It's how the full private book got audited without trusting any single pass.

## Why no songbook ships

The private book behind this tool has ~70 tunes. Lyrics are copyrighted, so the public repo carries the tooling plus two safe demos: Danny Boy (Frederic Weatherly's 1913 words, public domain) and an original demo tune. Charts you add locally are your own business — just don't commit copyrighted lyrics to a public fork.

## Adding a tune with an agent

`.claude/commands/add-tune.md` is the Claude Code slash command that adds a tune end-to-end (fetch, format, rebuild, verify). It encodes the conventions above so you don't have to remember them.

## Versions

Tested with Python 3.13, reportlab 4.4, pytest 8.3, pdfplumber 0.11.

The write-up, and a public-domain edition of the fake book: [gizmowarehouse.org/gizmo/fakebook-maker](https://gizmowarehouse.org/gizmo/fakebook-maker). How I use Claude Code to write gospel reharmonizations for it: [gizmowarehouse.org/gizmo/gospel-of-claude-code](https://gizmowarehouse.org/gizmo/gospel-of-claude-code).

## License

MIT. The demo charts are included under the same license; Danny Boy's text is public domain.
