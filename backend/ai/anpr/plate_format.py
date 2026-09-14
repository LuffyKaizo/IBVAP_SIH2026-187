"""Conservative Indian registration-plate format validation and
position-constrained character correction.

Purpose
-------
EasyOCR systematically confuses visually similar glyphs (O/0, Z/2, S/5,
I/1, B/8). A GLOBAL replace is forbidden because it fabricates plates
(e.g. "BHAVNAGAR123" -> "BH4VNAGAR123"). Instead this module only ever
changes a character when the *plate structure* demands the opposite
character class at that exact position, using a small well-known
confusion map, and only when the corrected result is itself a valid
plate format.

Nothing here invents characters: corrections always swap a character
with its documented confusable counterpart, and only under position +
format + confidence constraints. The raw OCR string is preserved by the
caller; this module returns the proposed correction + flags.
"""

import re
from typing import Optional

# ---------------------------------------------------------------------------
# Format classification
# ---------------------------------------------------------------------------

# Indian registration plates are alphanumeric, length 6-11, structured as:
#   state code (2-3 letters) + RTO code (1-2 digits) + series (1-2 letters)
#   + serial number (2-4 digits)
# e.g. MH12AB1234, DL03XY9901, KA01BC5678, GJ05DE4321.
_VALID_RE = re.compile(
    r"^(?P<state>[A-Z]{2,3})"
    r"(?P<rto>[0-9]{1,2})"
    r"(?P<series>[A-Z]{1,2})"
    r"(?P<serial>[0-9]{2,4})$"
)

# Well-known OCR confusions. Mapping is symmetric and conservative.
LETTER_TO_DIGIT = {
    "O": "0", "I": "1", "Z": "2", "S": "5", "B": "8",
}
DIGIT_TO_LETTER = {v: k for k, v in LETTER_TO_DIGIT.items()}
CONFUSABLES = {**LETTER_TO_DIGIT, **DIGIT_TO_LETTER}

# Character class expected at each position, derived from the regex groups.
# Positions 0-based within a normalized alphanumeric string.
def _class_mask(match: re.Match) -> list:
    """Return ['L'|'D'] per character based on which regex group it belongs to."""
    groups = ["state", "rto", "series", "serial"]
    cls = {"state": "L", "series": "L", "rto": "D", "serial": "D"}
    mask = []
    for gname in groups:
        g = match.groupdict().get(gname) or ""
        mask.extend(cls[gname] for _ in g)
    return mask


def format_status(text: Optional[str]) -> str:
    """Classify normalized text as VALID / INVALID / UNCERTAIN.

    VALID     -> matches a documented Indian plate structure
    INVALID   -> alphanumeric but cannot be any Indian plate structure
    UNCERTAIN -> too short / missing / not enough information
    """
    if not text:
        return "UNCERTAIN"
    s = re.sub(r"[^A-Z0-9]", "", text.strip().upper())
    if len(s) < 6:
        return "UNCERTAIN"
    if len(s) > 11:
        return "INVALID"
    if _VALID_RE.match(s):
        return "VALID"
    return "INVALID"


# ---------------------------------------------------------------------------
# Position-constrained correction
# ---------------------------------------------------------------------------

def _try_layout_10(s: str):
    """Try to interpret a 10-char string as modern AA##AA#### layout.

    Returns a class mask ['L','L','D','D','L','L','D','D','D','D']
    only if the string is consistent enough (first two letters, last four
    digits, series positions either letters or confusable digits).
    """
    if len(s) != 10:
        return None
    if not (s[0].isalpha() and s[1].isalpha()):
        return None
    if not (s[6].isdigit() and s[7].isdigit() and s[8].isdigit() and s[9].isdigit()):
        return None
    # RTO slots (2,3) and series slots (4,5) may currently be polluted
    # by confusable chars; layout 10 is still a plausible target.
    return ["L", "L", "D", "D", "L", "L", "D", "D", "D", "D"]


def _derive_mask(s: str):
    """Return (mask, layout_name) for normalized text, or (None, None)."""
    m10 = _try_layout_10(s)
    if m10:
        return m10, "AA##AA####"
    m = _VALID_RE.match(s)
    if m:
        return _class_mask(m), "regex-groups"
    return None, None


def contextual_correct(text: Optional[str], confidence: float,
                       min_confidence: float = 0.5) -> dict:
    """Propose a conservative, position-constrained correction.

    Returns a dict:
        original     raw input (uppercase alnum), unchanged
        corrected    proposed text, or None when nothing safe to change
        changed      bool
        changes      list of (position, original_char, new_char)
        status       format status of the ORIGINAL text
        corrected_status format status of the corrected text
        reason       human-readable explanation

    Rules (all must hold for a change to be applied):
      * OCR confidence >= min_confidence
      * the string has a recognisable plate layout / mask
      * a char is swapped only with its documented confusable counterpart
        AND only when its position expects the opposite class
      * the fully corrected string is itself a valid plate format
    """
    empty = {
        "original": text, "corrected": None, "changed": False, "changes": [],
        "status": format_status(text), "corrected_status": None,
        "reason": "no text",
    }
    if not text:
        return empty

    s = re.sub(r"[^A-Z0-9]", "", text.strip().upper())
    status = format_status(s)
    if len(s) < 6:
        return {**empty, "status": status, "reason": "too short"}

    if confidence < min_confidence:
        return {**empty, "status": status, "reason": "low confidence"}

    # Derive the authoritative class mask FIRST. The modern 10-char layout
    # (AA##AA####) takes precedence over the permissive generic regex, which
    # can mis-read a polluted string like DLO3XY9901 as a 3-letter state
    # (DLO + 3 + XY + 9901) and skip correction.
    mask, layout = _derive_mask(s)
    if mask is None:
        return {**empty, "status": status,
                "reason": "no recognised plate layout (INVALID/UNCERTAIN)"}

    layout10_authoritative = layout == "AA##AA####"
    if status == "VALID" and not layout10_authoritative:
        # A valid non-10-char format (e.g. KA01AB123 / LAD01A1234):
        # no class violation exists, return clean.
        return {**empty, "status": status, "corrected_status": status,
                "reason": "already valid format"}

    # Build corrected string position by position.
    chars = list(s)
    changes = []
    for i, (ch, expected_cls) in enumerate(zip(s, mask)):
        actual_cls = "L" if ch.isalpha() else "D"
        if actual_cls == expected_cls:
            continue
        mapped = CONFUSABLES.get(ch)
        if mapped is None:
            # A real violation we cannot safely resolve -> abort whole attempt.
            return {**empty, "status": status,
                    "reason": f"unresolvable char '{ch}' at pos {i}"}
        chars[i] = mapped
        changes.append((i, ch, mapped))

    if not changes:
        return {**empty, "status": status, "reason": "no changes needed"}

    corrected = "".join(chars)
    corrected_status = format_status(corrected)
    # Re-derive mask for corrected to make sure class array is now obeyed.
    mask2, _ = _derive_mask(corrected)
    if corrected_status != "VALID" or mask2 is None:
        return {**empty, "status": status,
                "reason": "corrected result not a valid format; discarded"}

    return {
        "original": s,
        "corrected": corrected,
        "changed": True,
        "changes": changes,
        "status": status,
        "corrected_status": corrected_status,
        "reason": f"{layout}: {'; '.join('%s->%s@%d' % (o, n, p) for p, o, n in changes)}",
    }
