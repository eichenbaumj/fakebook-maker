Add a tune to the fake book: $ARGUMENTS

`$ARGUMENTS` is a local file path (or pasted text) containing chord-over-lyric text. End-to-end: read → parse → write `charts/<slug>.txt` → rebuild PDF → verify.

## Project

Read the repo's `CLAUDE.md` for the chart format and quick-start. The book is read from a ~14" laptop on a piano stand at gigs; sight-readability beats everything else.

## Workflow

### 1. Get the chord chart text

Have the source chart as a local file: open the source page in your own browser, copy the chord text, and save it to a file — then pass the file path. Copy from a plain-text/monospace view so the chord-over-lyric alignment survives; if the columns are already broken in your copy, they can't be reconstructed.

**Copyright note:** charts you add locally are for personal use. Never commit copyrighted lyrics to a public repo or fork.

### 2. Identify metadata

- **Title + composer:** prefer composer over performer (e.g., "Eugene McDaniels", not "Roberta Flack"). Use ` - ` as the separator on line 1: `Title - Composer`.
- **Key:** if the song modulates, write `Key: F (modulates to F#)` — see `charts/demo-tune.txt` for the convention.
- **Tempo:** include if you can name it confidently (Medium, Ballad, Shuffle, Bossa, Medium Funk, etc.). Skip if unsure.
- **Ignore capo notes.** This is a piano book — capo info is noise. Drop entirely.

### 3. Annotate modulations on section headers

When a section is in a different key from the surrounding sections, append a hyphenated note:
- `[Chorus - up half step]`
- `[Verse 3 - up a whole step]`

This is load-bearing at the show. Source charts sometimes hide modulations as a trailing space on the section name (`[Chorus ]` vs `[Chorus]`) — invisible in print. Make it visible.

### 4. Write `charts/<slug>.txt`

Filename: kebab-case lowercase, drop apostrophes/punctuation. `you-are-my-sunshine.txt`, not `You Are My Sunshine.txt`.

Format:
```
Title - Composer
Key: X | Tempo: Y

[Section]
Chord1    Chord2       Chord3
Lyrics aligned under chords

[Next Section]
...
```

**Preserve the source's chord-line spacing exactly.** Don't reflow, don't normalize, don't "clean up" alignment. Whitespace position = sight-reading. The renderer uses Courier monospace; columns must line up.

Keep accidentals **as written** in the source (`A#` stays `A#`, not `Bb`).

### 5. Build and verify

```bash
python3 fakebook/build.py
```

- Console must list `Parsed: <Your Title>`. If it doesn't, the title line is malformed (missing ` - ` separator) or the file isn't in `charts/`.
- Run `python3 -m qc.lint` — 0 errors expected.
- Open `fakebook/fakebook.pdf`:
  - Song slots into the alphabetical TOC.
  - Chord/lyric columns align cleanly under Courier.
  - Modulation annotations are visible.
  - One page is ideal; **two pages is fine** — don't compress the chart to force a single page.

## Reference charts to model on

- `charts/demo-tune.txt` — the format tour: modulation convention, `E-7`/`Eb7-5` tokens, `N.C.`, rhythm lines
- `charts/danny-boy.txt` — a real tune: slash basses, chord-per-syllable passages

## What the renderer handles automatically

`fakebook/build.py` detects chord lines with the real chord grammar in `qc/theory.py` (a majority of a line's tokens must parse as chords). This means:
- Exotic tokens like `Cm7+5`, `Em11`, `B7#5b9`, `A#m/C#`, `Gm11/C`, `Am7-5` all work without code changes.
- Lyric lines whose words start with A–G ("Call me later") stay lyrics.
- Lines like `| /  /  /  / | /  /  /  / |` render as plain text under the chord header — that's the right behavior for a vamp bar.
- Don't modify `fakebook/build.py` to handle weird tokens. If a line isn't classifying right, it's probably a parse-the-source issue, not a renderer issue.
