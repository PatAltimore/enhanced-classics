"""Phrase-matching and **marker** injection shared by generator.py and cc_chapter.py.

No model/network dependencies, so it can be used without the Azure client stack.
"""
import re
import unicodedata

# Typography normalisation: curly quotes → straight, dashes → hyphen, ligatures → plain.
# Must remain 1-to-1 (each codepoint → exactly one char) so that translated indices
# stay aligned with the original string — _find_match relies on this property.
_TYPO_NORM = str.maketrans({
    0x2018: "'", 0x2019: "'",
    0x201C: '"', 0x201D: '"',
    0x2013: "-", 0x2014: "-",
    0x200A: " ",        # hair space → regular space
    0x2026: ".",        # ellipsis → period (single char, keeps 1-to-1)
    0x00E6: "e", 0x0153: "e",   # ligatures æ, œ
    0x0152: "O",        # Œ uppercase
})


def _accent_strip_with_map(s: str) -> "tuple[str, list[int]]":
    """NFD-decompose s, drop combining marks, return (stripped, orig_pos_map).

    orig_pos_map[i] gives the index in s that produced stripped[i].
    Since accented chars decompose to base+combining, and we drop the combining
    char, the resulting string may be shorter than s — hence the explicit map.
    """
    result: list[str] = []
    pos_map: list[int] = []
    for i, c in enumerate(s):
        for ch in unicodedata.normalize("NFD", c):
            if unicodedata.category(ch) != "Mn":   # keep non-combining chars
                result.append(ch)
                pos_map.append(i)
    return "".join(result), pos_map


def _norm(s: str) -> str:
    return s.translate(_TYPO_NORM)


def _find_match(text: str, phrase: str) -> "tuple[int, int] | None":
    """Return (start, end) of the first occurrence of phrase not inside **...** spans.

    Three passes in order:
      1. Exact match
      2. Typography-normalised match (curly quotes → straight, etc.)
      3. Flexible-whitespace regex (handles phrases split across line breaks)
    """
    def _outside(idx: int) -> bool:
        return text[:idx].count("**") % 2 == 0

    # Pass 1 — exact
    pos = 0
    while pos < len(text):
        idx = text.find(phrase, pos)
        if idx == -1:
            break
        if _outside(idx):
            return idx, idx + len(phrase)
        pos = idx + 1

    # Pass 2 — typography-normalised (1-to-1 char map keeps indices aligned)
    # Always search norm_text: the text may have curly quotes/em dashes even
    # when the model's phrase has straight equivalents (norm_phrase == phrase).
    norm_text = _norm(text)
    norm_phrase = _norm(phrase)
    pos = 0
    while pos < len(norm_text):
        idx = norm_text.find(norm_phrase, pos)
        if idx == -1:
            break
        if _outside(idx):
            return idx, idx + len(norm_phrase)
        pos = idx + 1

    # Pass 3 — flexible whitespace (handles line-break splits)
    words = phrase.split()
    if len(words) > 1:
        pattern = re.compile(r'\s+'.join(re.escape(w) for w in words))
        for m in pattern.finditer(text):
            if _outside(m.start()):
                return m.start(), m.end()

    # Pass 4 — accent-normalised match (é→e, â→a, Æ→A, etc.)
    # Uses NFD decomposition so it handles any accented Latin character.
    stripped_text, text_map = _accent_strip_with_map(text)
    stripped_phrase, _ = _accent_strip_with_map(phrase)
    if stripped_text != text or stripped_phrase != phrase:
        pos = 0
        while pos < len(stripped_text):
            idx = stripped_text.find(stripped_phrase, pos)
            if idx == -1:
                break
            end_idx = idx + len(stripped_phrase) - 1
            if end_idx < len(text_map):
                orig_start = text_map[idx]
                orig_end = text_map[end_idx] + 1
                if _outside(orig_start):
                    return orig_start, orig_end
            pos = idx + 1

    return None


def _first_outside_markers(text: str, phrase: str) -> int:
    """Return the index of the first occurrence of phrase not inside **...** spans.

    Counts ** tokens before each candidate position: an odd count means we're
    inside an existing marker and should skip that occurrence.
    """
    pos = 0
    while pos < len(text):
        idx = text.find(phrase, pos)
        if idx == -1:
            return -1
        if text[:idx].count("**") % 2 == 0:
            return idx
        pos = idx + 1
    return -1


def _inject_markers(text: str, phrases: list[str]) -> "tuple[str, list[str]]":
    """Wrap the first occurrence of each phrase in **…** markers.

    Returns (marked_text, phrases_that_could_not_be_found).

    Phrases are processed longest-first to avoid wrapping a substring that is
    already part of a longer phrase.  Uses _find_match for three-pass lookup
    (exact, typography-normalised, flexible-whitespace).
    """
    failed = []
    for phrase in sorted(phrases, key=len, reverse=True):
        marker = f"**{phrase}**"
        if marker in text:
            continue   # exact marker already present
        match = _find_match(text, phrase)
        if match is None:
            failed.append(phrase)
            continue
        start, end = match
        original_span = text[start:end]
        text = text[:start] + f"**{original_span}**" + text[end:]
    return text, failed
