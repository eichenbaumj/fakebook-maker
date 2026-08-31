#!/usr/bin/env python3
"""
build.py — Compile .txt chord charts into a navigable PDF fake book.

Usage:
    python3 build.py              # from sheet-music/ or fakebook/
    python3 fakebook/build.py     # from sheet-music/

Scans charts/*.txt, parses chords-over-lyrics format, outputs fakebook/fakebook.pdf.

Optional flags for alternate editions (e.g. a public-domain-only book):
    --charts-dir DIR      read charts from DIR instead of charts/
    --include-list FILE   only build charts whose filename is listed in FILE
                          (one filename per line; '#' comments and blanks ok)
    --output FILE         write the PDF somewhere other than fakebook/fakebook.pdf
    --title TITLE         book title for the cover TOC and PDF metadata
"""

import argparse
import os
import re
import sys
from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
SHEET_MUSIC_DIR = SCRIPT_DIR.parent
CHARTS_DIR = SHEET_MUSIC_DIR / "charts"
OUTPUT_PDF = SCRIPT_DIR / "fakebook.pdf"

sys.path.insert(0, str(SHEET_MUSIC_DIR))
from qc.theory import parse_chord  # noqa: E402  (single source of chord grammar)


# ---------------------------------------------------------------------------
# Layout constants
# ---------------------------------------------------------------------------

PAGE_W, PAGE_H = letter  # 8.5 x 11 portrait
MARGIN_LEFT = 0.6 * inch
MARGIN_RIGHT = 0.6 * inch
MARGIN_TOP = 0.7 * inch
MARGIN_BOTTOM = 0.6 * inch

CONTENT_W = PAGE_W - MARGIN_LEFT - MARGIN_RIGHT

# Font sizes
TITLE_SIZE = 20
SUBTITLE_SIZE = 11
SECTION_SIZE = 11
CHORD_SIZE = 11
LYRIC_SIZE = 12
# Master column grid: chords are drawn per-token at lyric-column x positions
# so that text-file column N lands at the same x for chords and lyrics.
# (Courier advance = 0.6 x point size; chord glyphs at 11pt on a 12pt grid.)
CHAR_W = 0.6 * LYRIC_SIZE
TOC_TITLE_SIZE = 24
TOC_ENTRY_SIZE = 12

# Spacing
TITLE_AFTER = 4        # pts after title block
SECTION_BEFORE = 12    # pts before [Section] header
SECTION_AFTER = 2      # pts after [Section] header
CHORD_LYRIC_GAP = 1    # pts between chord line and lyric line
LINE_PAIR_AFTER = 4    # pts after a chord+lyric pair
SINGLE_LINE_AFTER = 4  # pts after a standalone line


# ---------------------------------------------------------------------------
# Chord detection
# ---------------------------------------------------------------------------

def is_chord_token(token: str) -> bool:
    """Check if a token is a real chord symbol (or N.C.).

    Delegates to the qc.theory grammar so that lyric words that merely
    start with A-G ('Call', 'Georgia,', 'Deacon') don't count — a line of
    those used to be misclassified as a chord line and rendered bold.
    Bars/slashes/repeat marks deliberately don't count, so rhythm lines
    like '| /  /  /  / |' keep rendering as plain text.
    """
    return parse_chord(token).kind in ("chord", "nc")


def is_chord_line(line: str) -> bool:
    """A line is a chord line if the majority of its tokens look like chords.

    Structural tokens (bars '|', rhythm slashes, repeat marks like x12) are
    neutral — excluded from the ratio — so '| Fmaj7 | A#7 | Cmaj7 | Am7 |'
    counts 4/4 chords, not 4/9. A line of only structural tokens (pure
    rhythm notation '| / / / / |') stays a plain-text line.
    """
    tokens = line.split()
    if not tokens:
        return False
    kinds = [parse_chord(t).kind for t in tokens]
    countable = [k for k in kinds if k not in ("bar", "slash", "repeat")]
    if not countable:
        return False
    chord_count = sum(1 for k in countable if k in ("chord", "nc"))
    return chord_count / len(countable) >= 0.5


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def is_chart_file(filepath: Path) -> bool:
    """A charts-dir .txt is a chart unless its first non-blank line is a '#'
    comment — that marks a data file (e.g. an include list kept alongside the
    charts), which must never be rendered as a tune."""
    for raw in filepath.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line:
            return not line.startswith("#")
    return False


def parse_chart(filepath: Path) -> dict:
    """Parse a .txt chord chart into structured data."""
    lines = filepath.read_text(encoding="utf-8").splitlines()
    if not lines:
        return None

    # First line: title - composer
    first = lines[0].strip()
    if " - " in first:
        title, composer = first.split(" - ", 1)
    else:
        title, composer = first, ""

    # Scan for metadata lines (Key:, Tempo:, Capo:, etc.)
    metadata = {}
    content_start = 1
    for i in range(1, min(len(lines), 5)):
        line = lines[i].strip()
        if not line:
            continue
        if re.match(r'^(Key|Tempo|Capo|Time|Transposed)\s*:', line, re.IGNORECASE):
            metadata["info"] = line
            content_start = i + 1
        elif line.startswith("["):
            break
        else:
            content_start = i
            break

    # Parse sections
    sections = []
    current_section = {"name": None, "lines": []}

    for line in lines[content_start:]:
        stripped = line.rstrip()

        # Section header
        m = re.match(r'^\[(.+)\]', stripped)
        if m:
            if current_section["lines"] or current_section["name"]:
                sections.append(current_section)
            current_section = {"name": m.group(1), "lines": []}
            continue

        # Blank line
        if not stripped:
            if current_section["lines"]:
                current_section["lines"].append(("blank", ""))
            continue

        # Chord or lyric line — preserve original spacing
        if is_chord_line(stripped):
            current_section["lines"].append(("chords", line.rstrip()))
        else:
            current_section["lines"].append(("lyrics", line.rstrip()))

    if current_section["lines"] or current_section["name"]:
        sections.append(current_section)

    return {
        "title": title.strip(),
        "composer": composer.strip(),
        "metadata": metadata,
        "sections": sections,
        "filename": filepath.name,
    }


# ---------------------------------------------------------------------------
# PDF renderer
# ---------------------------------------------------------------------------

class FakeBookRenderer:
    def __init__(self, output_path: Path, songs: list, title: str = "Joe's Fake Book"):
        self.songs = sorted(songs, key=lambda s: s["title"].lower())
        self.title = title
        self.c = canvas.Canvas(str(output_path), pagesize=letter)
        self.c.setTitle(title)
        self.c.setAuthor("Joe Eichenbaum")
        self.page_num = 0
        self.y = PAGE_H - MARGIN_TOP
        self.song_pages = []  # (title, page_number) for TOC

    def _new_page(self):
        if self.page_num > 0:
            self.c.showPage()
        self.page_num += 1
        self.y = PAGE_H - MARGIN_TOP

    def _check_space(self, needed: float):
        """Start a new page if not enough vertical space."""
        if self.y - needed < MARGIN_BOTTOM:
            self.c.showPage()
            self.page_num += 1
            self.y = PAGE_H - MARGIN_TOP

    def render(self):
        # Reserve page 1+ for TOC (we'll draw it at the end via a second pass)
        # First, render all songs and track page numbers
        # We'll use a two-pass approach: render songs, then prepend TOC

        # Pass 1: render all songs, track page assignments
        song_data = []
        for song in self.songs:
            self._new_page()
            page = self.page_num
            self._render_song(song)
            song_data.append((song["title"], song["composer"], page))
            # Add bookmark
            self.c.bookmarkPage(f"song_{page}")
            self.c.addOutlineEntry(song["title"], f"song_{page}", level=0)

        total_song_pages = self.page_num

        # Pass 2: add TOC pages at the end (we'll reorder mentally —
        # actually ReportLab doesn't support page reordering easily,
        # so we'll do it all in one pass with TOC first)

        self.c.save()

        # Rebuild with TOC first
        self._build_with_toc(output_path=self.c._filename, songs_data=song_data)

    def _build_with_toc(self, output_path: str, songs_data: list):
        """Rebuild the PDF with TOC as the first page(s), then songs."""
        c = canvas.Canvas(output_path, pagesize=letter)
        c.setTitle(self.title)
        c.setAuthor("Joe Eichenbaum")
        self.c = c
        self.page_num = 0

        # Calculate how many TOC pages we need — must mirror the pagination
        # logic in _render_toc (row height, header on page 1, bottom limit)
        row_h = TOC_ENTRY_SIZE + 8
        limit = MARGIN_BOTTOM + 20
        first_y = PAGE_H - MARGIN_TOP - (TOC_TITLE_SIZE + 4) - 24
        cont_y = PAGE_H - MARGIN_TOP
        first_cap = int((first_y - limit) / row_h) + 1
        cont_cap = int((cont_y - limit) / row_h) + 1
        n = len(songs_data)
        toc_pages = 1 if n <= first_cap else 1 + -(-(n - first_cap) // cont_cap)

        # Render TOC
        self._render_toc(songs_data, toc_pages)

        # Render songs
        for i, song in enumerate(self.songs):
            self._new_page()
            bookmark_key = f"song_{i}"
            c.bookmarkPage(bookmark_key)
            c.addOutlineEntry(song["title"], bookmark_key, level=0)
            self._render_song(song)

        c.save()

    def _render_toc(self, songs_data: list, toc_pages: int):
        self._new_page()
        self.y = PAGE_H - MARGIN_TOP

        # Title
        self.c.setFont("Helvetica-Bold", TOC_TITLE_SIZE)
        self.c.drawString(MARGIN_LEFT, self.y, self.title)
        self.y -= TOC_TITLE_SIZE + 4

        self.c.setFont("Helvetica", 10)
        self.c.drawString(MARGIN_LEFT, self.y, f"{len(songs_data)} tunes")
        self.y -= 24

        # Entries
        for i, (title, composer, orig_page) in enumerate(songs_data):
            if self.y < MARGIN_BOTTOM + 20:
                self._new_page()
                self.y = PAGE_H - MARGIN_TOP

            # Pass 1 tracked each song's real start page (songs can span
            # multiple pages); the rebuild just shifts everything by the TOC
            actual_page = toc_pages + orig_page
            bookmark_key = f"song_{i}"
            self.c.setFont("Helvetica", TOC_ENTRY_SIZE)

            # Title on left
            display = title
            if composer:
                display = f"{title} — {composer}"
            self.c.drawString(MARGIN_LEFT, self.y, display)

            # Page number on right
            page_str = str(actual_page)
            self.c.drawRightString(PAGE_W - MARGIN_RIGHT, self.y, page_str)

            # Clickable link over the entire TOC row
            rect = (MARGIN_LEFT, self.y - 2,
                    PAGE_W - MARGIN_RIGHT, self.y + TOC_ENTRY_SIZE)
            self.c.linkRect("", bookmark_key, rect, Border='[0 0 0]')

            # Dot leader
            title_width = pdfmetrics.stringWidth(display, "Helvetica", TOC_ENTRY_SIZE)
            page_width = pdfmetrics.stringWidth(page_str, "Helvetica", TOC_ENTRY_SIZE)
            dot_start = MARGIN_LEFT + title_width + 8
            dot_end = PAGE_W - MARGIN_RIGHT - page_width - 8
            if dot_end > dot_start:
                dots = " . " * int((dot_end - dot_start) / pdfmetrics.stringWidth(" . ", "Helvetica", TOC_ENTRY_SIZE))
                self.c.setFillColorRGB(0.6, 0.6, 0.6)
                self.c.drawString(dot_start, self.y, dots)
                self.c.setFillColorRGB(0, 0, 0)

            self.y -= TOC_ENTRY_SIZE + 8

    def _render_song(self, song: dict):
        """Render a single song on the current page."""
        # Title
        self.c.setFont("Helvetica-Bold", TITLE_SIZE)
        self.c.drawString(MARGIN_LEFT, self.y, song["title"])
        self.y -= TITLE_SIZE + 2

        # Composer + metadata
        subtitle_parts = []
        if song["composer"]:
            subtitle_parts.append(song["composer"])
        if song["metadata"].get("info"):
            subtitle_parts.append(song["metadata"]["info"])
        if subtitle_parts:
            self.c.setFont("Helvetica-Oblique", SUBTITLE_SIZE)
            self.c.drawString(MARGIN_LEFT, self.y, "  |  ".join(subtitle_parts))
            self.y -= SUBTITLE_SIZE + 2

        self.y -= TITLE_AFTER

        # Sections
        for section in song["sections"]:
            self._render_section(section)

    def _draw_chord_line(self, text: str):
        """Draw a chord line token-by-token on the lyric column grid.

        Chord and lyric point sizes differ, so drawing the whole line as one
        string would make chord columns drift left of the lyric columns as
        the line gets longer. Placing each token at its text-file column
        keeps chords exactly over the syllables they were aligned to.
        """
        self.c.setFont("Courier-Bold", CHORD_SIZE)
        for m in re.finditer(r'\S+', text):
            self.c.drawString(MARGIN_LEFT + m.start() * CHAR_W, self.y, m.group())

    def _render_section(self, section: dict):
        """Render a song section (header + chord/lyric lines)."""
        # Section header
        if section["name"]:
            self._check_space(SECTION_BEFORE + SECTION_SIZE + SECTION_AFTER + 30)
            self.y -= SECTION_BEFORE
            self.c.setFont("Helvetica-Bold", SECTION_SIZE)
            self.c.drawString(MARGIN_LEFT, self.y, f"[{section['name']}]")
            self.y -= SECTION_SIZE + SECTION_AFTER

        # Lines
        lines = section["lines"]
        i = 0
        while i < len(lines):
            line_type, text = lines[i]

            if line_type == "blank":
                self.y -= 6
                i += 1
                continue

            if line_type == "chords":
                # Check if next line is lyrics (chord+lyric pair)
                needed = CHORD_SIZE + CHORD_LYRIC_GAP + LYRIC_SIZE + LINE_PAIR_AFTER
                self._check_space(needed)

                self._draw_chord_line(text)
                self.y -= CHORD_SIZE + CHORD_LYRIC_GAP

                # If next line is lyrics, draw them
                if i + 1 < len(lines) and lines[i + 1][0] == "lyrics":
                    self.c.setFont("Courier", LYRIC_SIZE)
                    self.c.drawString(MARGIN_LEFT, self.y, lines[i + 1][1])
                    self.y -= LYRIC_SIZE + LINE_PAIR_AFTER
                    i += 2
                else:
                    self.y -= SINGLE_LINE_AFTER
                    i += 1

            elif line_type == "lyrics":
                self._check_space(LYRIC_SIZE + SINGLE_LINE_AFTER)
                self.c.setFont("Courier", LYRIC_SIZE)
                self.c.drawString(MARGIN_LEFT, self.y, text)
                self.y -= LYRIC_SIZE + SINGLE_LINE_AFTER
                i += 1
            else:
                i += 1


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def check_widths(song: dict) -> list:
    """Flag lines that will render past the right margin.

    Lyrics advance CHAR_W per char; chord tokens sit on the CHAR_W grid but
    their glyphs advance at CHORD_SIZE. Anything wider than CONTENT_W runs
    off the printable area (and past ~79 chars, off the physical page).
    """
    warnings = []
    for section in song["sections"]:
        for line_type, text in section["lines"]:
            if line_type == "lyrics":
                width = len(text) * CHAR_W
            elif line_type == "chords":
                width = 0
                for m in re.finditer(r'\S+', text):
                    width = max(width, m.start() * CHAR_W
                                + len(m.group()) * 0.6 * CHORD_SIZE)
            else:
                continue
            if width > CONTENT_W:
                over = int((width - CONTENT_W) / CHAR_W) + 1
                warnings.append(
                    f"{song['title']}: {line_type} line ~{over} chars past "
                    f"the right margin: {text[:60]!r}...")
    return warnings


def read_include_list(path: Path) -> set:
    """Read an include-list file: one chart filename per line.

    Blank lines and '#' comments are skipped. Entries may be given with or
    without the .txt extension; matching is on the chart's filename.
    """
    names = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        entry = raw.split("#", 1)[0].strip()
        if not entry:
            continue
        if not entry.endswith(".txt"):
            entry += ".txt"
        names.add(entry)
    return names


def main():
    parser = argparse.ArgumentParser(description="Build a PDF fake book from .txt chord charts.")
    parser.add_argument("--charts-dir", type=Path, default=CHARTS_DIR,
                        help=f"directory of .txt charts (default: {CHARTS_DIR})")
    parser.add_argument("--include-list", type=Path, default=None,
                        help="file listing chart filenames to include (one per line)")
    parser.add_argument("--output", type=Path, default=OUTPUT_PDF,
                        help=f"output PDF path (default: {OUTPUT_PDF})")
    parser.add_argument("--title", default="Joe's Fake Book",
                        help="book title for the TOC page and PDF metadata")
    args = parser.parse_args()

    charts_dir = args.charts_dir
    if not charts_dir.exists():
        print(f"Error: charts directory not found at {charts_dir}")
        sys.exit(1)

    txt_files = sorted(f for f in charts_dir.glob("*.txt") if is_chart_file(f))
    if not txt_files:
        print(f"No .txt files found in {charts_dir}")
        sys.exit(1)

    if args.include_list:
        if not args.include_list.exists():
            print(f"Error: include list not found at {args.include_list}")
            sys.exit(1)
        wanted = read_include_list(args.include_list)
        txt_files = [f for f in txt_files if f.name in wanted]
        missing = wanted - {f.name for f in txt_files}
        if missing:
            # A listed chart that doesn't exist is a data error, not a warning:
            # a silently thinner book would ship without anyone noticing.
            print(f"Error: include list names {len(missing)} chart(s) not in {charts_dir}:")
            for name in sorted(missing):
                print(f"  {name}")
            sys.exit(1)
        if not txt_files:
            print("Include list matched no charts.")
            sys.exit(1)

    songs = []
    width_warnings = []
    for f in txt_files:
        song = parse_chart(f)
        if song:
            songs.append(song)
            print(f"  Parsed: {song['title']}")
            width_warnings.extend(check_widths(song))

    if not songs:
        print("No valid charts found.")
        sys.exit(1)

    if width_warnings:
        print(f"\nWARNING: {len(width_warnings)} line(s) will overflow the page:")
        for w in width_warnings:
            print(f"  {w}")

    print(f"\nBuilding fake book with {len(songs)} tunes...")
    renderer = FakeBookRenderer(args.output, songs, title=args.title)
    renderer.render()
    print(f"Done: {args.output}")


if __name__ == "__main__":
    main()
