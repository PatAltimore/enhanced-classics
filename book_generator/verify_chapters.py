"""Verify that each generated chapter's body text matches its source text.

For each chapter that has a source_texts file, strips the ** markers from the
markdown body and checks whether it is an exact match (or close match) to the
source text.  Reports mismatches and missing source files.

Usage:
    python verify_chapters.py                  # all books
    python verify_chapters.py --book walden    # one book
"""
import pathlib
import re
import sys

import yaml

CONFIG_PATH = pathlib.Path(__file__).parent / "config" / "books.yaml"
TEXTS_ROOT  = pathlib.Path(__file__).parent / "source_texts"
BOOKS_ROOT  = pathlib.Path(__file__).parent / ".." / "public" / "books"

BOOK_FILTER = sys.argv[sys.argv.index("--book") + 1] if "--book" in sys.argv else None

_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")


def _strip_markers(text: str) -> str:
    """Remove ** markers but keep the phrase text."""
    return _BOLD_RE.sub(r"\1", text)


def _normalize(text: str) -> str:
    """Collapse whitespace for loose comparison."""
    return re.sub(r"\s+", " ", text).strip()


def _extract_body(md_path: pathlib.Path) -> str:
    """Return the prose body from a generated markdown file (after the closing ---)."""
    text  = md_path.read_text(encoding="utf-8").replace("\r\n", "\n")
    parts = text.split("---\n")
    return parts[2].strip() if len(parts) > 2 else ""


def verify_chapter(book: dict, chapter: dict) -> str:
    """Return one of: 'ok', 'no_source', 'no_output', 'mismatch'."""
    src_path = TEXTS_ROOT / book["slug"] / f"{chapter['slug']}.txt"
    md_path  = BOOKS_ROOT / book["slug"] / f"{chapter['slug']}.md"

    if not src_path.exists():
        return "no_source"
    if not md_path.exists():
        return "no_output"

    source_text = src_path.read_text(encoding="utf-8").strip()
    body_text   = _strip_markers(_extract_body(md_path))

    if _normalize(source_text) == _normalize(body_text):
        return "ok"

    # Partial match check: is the source text substantially present?
    # (Some chapters may have very minor whitespace or encoding differences.)
    src_norm  = _normalize(source_text)
    body_norm = _normalize(body_text)

    # If the stripped body contains 90%+ of the source text characters, call it ok
    overlap = sum(1 for a, b in zip(src_norm, body_norm) if a == b)
    ratio   = overlap / max(len(src_norm), 1)
    if ratio >= 0.97:
        return "ok"

    return "mismatch"


def main() -> None:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    books = config["books"]
    if BOOK_FILTER:
        books = [b for b in books if b["slug"] == BOOK_FILTER]

    totals = {"ok": 0, "no_source": 0, "no_output": 0, "mismatch": 0}

    for book in books:
        print(f"\n{book['title']}")
        for chapter in book["chapters"]:
            status = verify_chapter(book, chapter)
            totals[status] += 1
            icon = {"ok": "✓", "no_source": "·", "no_output": "✗", "mismatch": "!"}[status]
            label = {
                "ok":        "source matches markdown body",
                "no_source": "no source text (run fetch_texts.py first)",
                "no_output": "chapter not yet generated",
                "mismatch":  "MISMATCH — body text differs from source",
            }[status]
            print(f"  {icon} Ch.{chapter['number']:2d} {chapter['title']!r}: {label}")

    print(f"\nSummary: {totals['ok']} ok, {totals['no_source']} no source, "
          f"{totals['no_output']} not generated, {totals['mismatch']} mismatched")

    if totals["mismatch"]:
        print("\nMismatched chapters need to be regenerated with --force:")
        print("  python generator.py --force [--book SLUG] [--chapter N]")
    if totals["no_source"]:
        print("\nMissing source texts — run:")
        print("  python fetch_texts.py [--book SLUG]")


if __name__ == "__main__":
    main()
