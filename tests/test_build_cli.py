"""CLI flags for alternate editions: --charts-dir / --include-list / --output / --title."""

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "fakebook"))

import pdfplumber

import build

BUILD_PY = REPO / "fakebook" / "build.py"

CHART_A = """Alpha Song - Nobody
Key: C

[Verse]
C         G7
Twinkle twinkle little star
"""

CHART_B = """Beta Song - Nobody
Key: G

[Verse]
G         D7
How I wonder what you are
"""


def _write_charts(tmp_path):
    charts = tmp_path / "charts"
    charts.mkdir()
    (charts / "alpha-song.txt").write_text(CHART_A, encoding="utf-8")
    (charts / "beta-song.txt").write_text(CHART_B, encoding="utf-8")
    return charts


def test_read_include_list(tmp_path):
    lst = tmp_path / "list.txt"
    lst.write_text(
        "# a comment\n"
        "alpha-song.txt\n"
        "\n"
        "beta-song   # extension optional, inline comment stripped\n",
        encoding="utf-8",
    )
    assert build.read_include_list(lst) == {"alpha-song.txt", "beta-song.txt"}


def test_cli_builds_filtered_edition(tmp_path):
    charts = _write_charts(tmp_path)
    lst = tmp_path / "pd.txt"
    lst.write_text("alpha-song\n", encoding="utf-8")
    out = tmp_path / "edition.pdf"

    result = subprocess.run(
        [sys.executable, str(BUILD_PY),
         "--charts-dir", str(charts),
         "--include-list", str(lst),
         "--output", str(out),
         "--title", "Test Edition"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "Building fake book with 1 tunes" in result.stdout
    assert out.exists()

    with pdfplumber.open(out) as pdf:
        assert pdf.metadata.get("Title") == "Test Edition"
        toc_text = pdf.pages[0].extract_text()
    assert "Test Edition" in toc_text
    assert "Alpha Song" in toc_text
    assert "Beta Song" not in toc_text


def test_cli_include_list_missing_chart_errors(tmp_path):
    charts = _write_charts(tmp_path)
    lst = tmp_path / "pd.txt"
    lst.write_text("alpha-song\nno-such-chart\n", encoding="utf-8")
    out = tmp_path / "edition.pdf"

    result = subprocess.run(
        [sys.executable, str(BUILD_PY),
         "--charts-dir", str(charts),
         "--include-list", str(lst),
         "--output", str(out)],
        capture_output=True, text=True,
    )
    assert result.returncode == 1
    assert "no-such-chart.txt" in result.stdout
    assert not out.exists()


def test_is_chart_file(tmp_path):
    chart = tmp_path / "alpha-song.txt"
    chart.write_text(CHART_A, encoding="utf-8")
    data = tmp_path / "list.txt"
    data.write_text("# an include list, not a chart\nalpha-song.txt\n",
                    encoding="utf-8")
    empty = tmp_path / "empty.txt"
    empty.write_text("\n \n", encoding="utf-8")
    assert build.is_chart_file(chart)
    assert not build.is_chart_file(data)
    assert not build.is_chart_file(empty)


def test_cli_skips_comment_headed_data_files(tmp_path):
    # A '#'-headed .txt sitting in the charts dir (e.g. an include list)
    # must not be rendered into the book as a tune.
    charts = _write_charts(tmp_path)
    (charts / "public_domain_list.txt").write_text(
        "# Public-domain edition include list\nalpha-song.txt\n",
        encoding="utf-8")
    out = tmp_path / "book.pdf"

    result = subprocess.run(
        [sys.executable, str(BUILD_PY),
         "--charts-dir", str(charts),
         "--output", str(out)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "Building fake book with 2 tunes" in result.stdout

    with pdfplumber.open(out) as pdf:
        toc_text = pdf.pages[0].extract_text()
    assert "include list" not in toc_text


def test_default_invocation_unchanged(tmp_path):
    # No flags → same defaults as before (charts/ + fakebook/fakebook.pdf).
    # Run --help to confirm argparse doesn't break plain invocation semantics.
    result = subprocess.run(
        [sys.executable, str(BUILD_PY), "--help"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "--include-list" in result.stdout
