#!/usr/bin/env python3
"""Chord-symbol grammar and key/degree math for the fake book QC pass.

Design notes:
- This is a tokenizer, not a single regex, because the corpus overloads
  '-': immediately after the root it means minor (E-7 = Em7, the
  our-love-is-here-to-stay convention); after an extension digit it means a
  flattened alteration (Eb7-5 = Eb7b5).
- parse_chord() never raises on weird input; it returns kind='invalid' so
  the linter can report rather than crash.
- Comparison happens in (interval-from-key, quality_class) space so that a
  chart in A can be checked against a web source in C. Spelling is kept
  separately so enharmonic style (A#7 in a flat key) stays report-only.
"""

import re
from dataclasses import dataclass, field

# --- pitch classes ---------------------------------------------------------

_LETTER_PC = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
_ACCIDENTAL = {"#": 1, "b": -1, "": 0}

DEGREE_NAMES = ["I", "bII", "II", "bIII", "III", "IV",
                "bV", "V", "bVI", "VI", "bVII", "VII"]


def pitch_class(spelled: str):
    """'Bb' -> 10, 'F#' -> 6, 'Cb' -> 11. None if unparseable."""
    m = re.fullmatch(r"([A-G])([#b]?)", spelled)
    if not m:
        return None
    return (_LETTER_PC[m.group(1)] + _ACCIDENTAL[m.group(2)]) % 12


# --- chord tokens ----------------------------------------------------------

# Non-chord things that legitimately live on chord lines.
_NC_RE = re.compile(r"^N\.?C\.?$", re.IGNORECASE)
_REPEAT_RE = re.compile(r"^\(?x\d+\)?$", re.IGNORECASE)
_ANNOTATION_WORDS = {"repeat", "to", "fade", "and", "hold", "fine", "solo",
                     "break", "riff", "intro", "outro", "vamp", "sim."}

QUALITY_CLASSES = ("maj", "min", "dom", "dim", "half_dim", "aug", "sus", "power")


@dataclass
class Chord:
    raw: str
    kind: str                    # chord|nc|bar|slash|repeat|annotation|invalid
    root_spelled: str = ""
    root_pc: int | None = None
    quality_class: str = ""      # one of QUALITY_CLASSES
    tail: str = ""               # everything after the root, as written
    bass_spelled: str = ""
    bass_pc: int | None = None
    problems: list = field(default_factory=list)


def _classify_quality(tail: str) -> tuple[str, list]:
    """Map a chord tail (root stripped, parens removed) to a quality class.

    Returns (quality_class, problems). The tail arrives with '°'/'º'
    normalized to 'dim' and a leading '-' already rewritten to 'm'.
    """
    problems = []
    t = tail

    if re.match(r"^(dim|o7|o$)", t):
        return "dim", problems
    if re.match(r"^(?:min|mi|m)7[b-]5", t):
        return "half_dim", problems
    if re.match(r"^(?:min|mi|m)maj", t):  # minor-major: Am(maj7)/Ammaj7 (parens stripped)
        return "min", problems
    # 'm', 'mi', and 'min' are all minor (Dm, Dmi, Dmin); longest match first.
    if re.match(r"^(min|mi|m)(?![a-z])", t) and not t.startswith("maj"):
        return "min", problems
    if t.startswith("sus") or re.match(r"^\d*sus", t):
        return "sus", problems
    if t.startswith("aug") or t.startswith("+"):
        return "aug", problems
    if t == "5":
        return "power", problems
    if re.match(r"^(maj|Maj|M(?=\d|$)|6|69)", t):
        return "maj", problems
    if t == "" or t.startswith("add"):
        return "maj", problems
    if re.match(r"^\d", t):  # 7, 9, 11, 13 (+ alterations)
        return "dom", problems
    return "", [f"unrecognized quality tail {tail!r}"]


def parse_chord(token: str) -> Chord:
    raw = token
    # Structural / non-chord tokens first.
    if token == "|":
        return Chord(raw, "bar")
    if token == "/":
        return Chord(raw, "slash")
    if token == "%":
        return Chord(raw, "repeat")
    if _NC_RE.match(token):
        return Chord(raw, "nc")
    if _REPEAT_RE.match(token):
        return Chord(raw, "repeat")
    if token.strip("()").lower().rstrip(".,;:") in _ANNOTATION_WORDS:
        return Chord(raw, "annotation")

    # Bar-glued chords like |Fmaj7 or Fmaj7| — strip bars, remember nothing.
    token = token.strip("|")
    # Parens: (Am7) soft chord, or a fragment of a multi-token parenthetical
    # group like "(A#7 D7)" — strip unbalanced edges too.
    token = token.strip("()")

    m = re.match(r"^([A-G])([#b]?)", token)
    if not m:
        return Chord(raw, "invalid", problems=[f"no A-G root in {token!r}"])
    root = m.group(1) + m.group(2)
    rest = token[m.end():]

    # 6/9 chords: the '/' is part of the quality, not a bass note.
    rest = rest.replace("6/9", "69")
    # Slash bass (only a trailing /<note>; interior '/' in e.g. G/B already ok)
    bass = ""
    bm = re.search(r"/([A-G][#b]?)$", rest)
    if bm:
        bass = bm.group(1)
        rest = rest[: bm.start()]

    problems = []
    # Normalize diminished glyphs (both the right one and the wrong one).
    if "º" in rest:  # U+00BA masculine ordinal — a typo for U+00B0
        problems.append("uses º (U+00BA ordinal) instead of ° (U+00B0)")
    norm = rest.replace("º", "dim").replace("°", "dim")
    # '-' immediately after the root = minor.
    if norm.startswith("-"):
        norm = "m" + norm[1:]
    # Drop interior parens for classification: A7(9), Am(maj7), F#7(#5).
    flat = norm.replace("(", "").replace(")", "")

    # Validate the tail's vocabulary: letters/digits and #b+-/, nothing else.
    if not re.fullmatch(r"[A-Za-z0-9#b+\-]*", flat):
        return Chord(raw, "invalid",
                     problems=[f"illegal characters in tail {rest!r}"])

    qclass, qproblems = _classify_quality(flat)
    problems += qproblems
    if not qclass:
        # A-G start but no recognizable chord tail: 'Call', 'Georgia,', 'Deacon'.
        # Treating these as invalid is what keeps lyric lines from being
        # misclassified as chord lines.
        return Chord(raw, "invalid", problems=problems)

    return Chord(
        raw=raw, kind="chord",
        root_spelled=root, root_pc=pitch_class(root),
        quality_class=qclass, tail=rest,
        bass_spelled=bass, bass_pc=pitch_class(bass) if bass else None,
        problems=problems,
    )


# --- keys ------------------------------------------------------------------

@dataclass
class Key:
    spelled: str            # 'F', 'D#', 'Fm'
    pc: int
    minor: bool
    modulates_to: str = ""  # spelled target if metadata says so
    raw: str = ""


def parse_key(metadata_line: str) -> Key | None:
    """Parse the chart's Key from its metadata line.

    Handles: 'Key: F | Tempo: Ballad', 'Key: A (transposed down ...)',
    'Key: C (modulates to Db)', 'Key: G/Bb', 'Key: Fm'.
    """
    if not metadata_line:
        return None
    m = re.search(r"Key\s*:\s*([A-G][#b]?)(m\b|\s*minor)?", metadata_line,
                  re.IGNORECASE)
    if not m:
        return None
    spelled = m.group(1)
    minor = bool(m.group(2))
    mod = ""
    mm = re.search(r"modulates?\s+(?:up\s+|down\s+)?to\s+([A-G][#b]?)",
                   metadata_line, re.IGNORECASE)
    if mm:
        mod = mm.group(1)
    return Key(spelled=spelled + ("m" if minor else ""),
               pc=pitch_class(spelled), minor=minor,
               modulates_to=mod, raw=metadata_line)


def degree(chord: Chord, key_pc: int) -> str | None:
    """Scale-degree label of a chord's root relative to a key. 'Bb in F' -> 'IV'."""
    if chord.root_pc is None:
        return None
    return DEGREE_NAMES[(chord.root_pc - key_pc) % 12]


def same_function(a: Chord, key_a_pc: int, b: Chord, key_b_pc: int) -> bool:
    """Do two chords play the same role in their respective keys?

    Compares (interval from key, quality class, bass interval when both
    specify one). Enharmonics collapse; spelling never matters here.
    """
    if a.kind != "chord" or b.kind != "chord":
        return a.kind == b.kind
    if (a.root_pc - key_a_pc) % 12 != (b.root_pc - key_b_pc) % 12:
        return False
    if a.quality_class != b.quality_class:
        return False
    if a.bass_pc is not None and b.bass_pc is not None:
        if (a.bass_pc - key_a_pc) % 12 != (b.bass_pc - key_b_pc) % 12:
            return False
    return True


# Flat keys (by pc of the major tonic) where sharp spellings are unidiomatic.
FLAT_KEY_PCS = {5, 10, 3, 8, 1, 6}  # F, Bb, Eb, Ab, Db, Gb


def enharmonic_style_issue(chord: Chord, key: Key | None) -> str | None:
    """FYI-level: sharp root spelled in a flat key (A#7 in F), or vice versa."""
    if chord.kind != "chord" or key is None or chord.root_pc is None:
        return None
    if "#" in chord.root_spelled and key.pc in FLAT_KEY_PCS:
        flat_name = {1: "Db", 3: "Eb", 6: "Gb", 8: "Ab", 10: "Bb"}.get(chord.root_pc)
        if flat_name:
            return (f"{chord.raw}: sharp spelling in flat key "
                    f"{key.spelled} (conventionally {flat_name}{chord.tail})")
    return None
