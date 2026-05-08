"""Download and split Project Gutenberg texts into per-chapter source files.

Files are saved to:
    book_generator/source_texts/{book-slug}/{chapter-slug}.txt

Two split modes (set gutenberg_split in books.yaml):
  "title"   — matches chapter titles from books.yaml directly against lines in the
               Gutenberg text. Reliable when the titles match the actual headings.
  "pattern" — uses gutenberg_re (a regex) to find chapter boundaries by ordinal.
               Needed for numbered chapters (Roman numerals, "Chapter N", etc.).

Usage:
    python fetch_texts.py                       # all books with gutenberg_id
    python fetch_texts.py --book walden         # one book
    python fetch_texts.py --book walden --list  # show found sections (no files written)
    python fetch_texts.py --book walden --dump  # print first 80 lines to diagnose patterns
"""
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request

import yaml

CONFIG_PATH = pathlib.Path(__file__).parent / "config" / "books.yaml"
TEXTS_ROOT  = pathlib.Path(__file__).parent / "source_texts"

LIST_ONLY   = "--list" in sys.argv
DUMP_RAW    = "--dump" in sys.argv
BOOK_FILTER = sys.argv[sys.argv.index("--book") + 1] if "--book" in sys.argv else None

_PG_URLS = [
    "https://www.gutenberg.org/files/{id}/{id}-0.txt",
    "https://www.gutenberg.org/files/{id}/{id}.txt",
    "https://www.gutenberg.org/cache/epub/{id}/pg{id}.txt",
]

_PG_START = re.compile(
    r"\*{3}\s*START OF (?:THE |THIS )?PROJECT GUTENBERG\b.*?\*{3}",
    re.IGNORECASE | re.DOTALL,
)
_PG_END = re.compile(
    r"\*{3}\s*END OF (?:THE |THIS )?PROJECT GUTENBERG\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def _download(gutenberg_id: int) -> str:
    last_err = None
    for tmpl in _PG_URLS:
        url = tmpl.format(id=gutenberg_id)
        print(f"    Trying {url} …", end=" ", flush=True)
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "EnhancedClassics/1.0 (educational)"}
            )
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read()
            print("OK")
            try:
                return raw.decode("utf-8").replace("\r\n", "\n")
            except UnicodeDecodeError:
                return raw.decode("latin-1").replace("\r\n", "\n")
        except urllib.error.HTTPError as e:
            print(f"HTTP {e.code}")
            last_err = e
        except Exception as e:
            print(f"error: {e}")
            last_err = e
    raise RuntimeError(f"All URLs failed for Gutenberg ID {gutenberg_id}: {last_err}")


def _strip_boilerplate(text: str) -> str:
    m = _PG_START.search(text)
    if m:
        text = text[m.end():]
    m = _PG_END.search(text)
    if m:
        text = text[: m.start()]
    return text.strip()


# ---------------------------------------------------------------------------
# Splitting helpers
# ---------------------------------------------------------------------------

def _split_by_pattern(text: str, pattern: str) -> list[str]:
    """Split text at each regex match; return sections starting at each match."""
    rx = re.compile(pattern, re.MULTILINE)
    boundaries = [m.start() for m in rx.finditer(text)]
    if not boundaries:
        return []
    return [
        text[boundaries[i]: boundaries[i + 1] if i + 1 < len(boundaries) else len(text)].strip()
        for i in range(len(boundaries))
    ]


def _split_by_titles(text: str, chapters: list[dict]) -> dict[str, str]:
    """Return a dict mapping chapter slug -> section text, matched by chapter title.

    Builds one regex from all chapter titles and matches each against lines that
    are not indented (to skip TOC entries that have a leading space).
    """
    # Map normalised title -> chapter slug
    title_to_slug: dict[str, str] = {}
    for ch in chapters:
        title_to_slug[ch["title"].lower()] = ch["slug"]

    # Build pattern: match any chapter title on its own unindented line
    escaped = [re.escape(ch["title"]) for ch in chapters]
    pattern = re.compile(r"^(?:" + "|".join(escaped) + r")$", re.MULTILINE)

    boundaries: list[tuple[int, str]] = []  # (position, chapter slug)
    for m in pattern.finditer(text):
        matched_title = m.group(0).strip()
        slug = title_to_slug.get(matched_title.lower())
        if slug:
            boundaries.append((m.start(), slug))

    result: dict[str, str] = {}
    for i, (start, slug) in enumerate(boundaries):
        end = boundaries[i + 1][0] if i + 1 < len(boundaries) else len(text)
        result[slug] = text[start:end].strip()

    return result


def _strip_heading(section: str, heading_lines: int) -> str:
    """Remove the first N non-empty lines (the heading) from a section."""
    lines   = section.splitlines()
    removed = 0
    result  = []
    skip    = True
    for line in lines:
        if skip:
            if line.strip():
                removed += 1
                if removed >= heading_lines:
                    skip = False
        else:
            result.append(line)
    return "\n".join(result).strip()


# ---------------------------------------------------------------------------
# Per-book processing
# ---------------------------------------------------------------------------

def process_book(book: dict) -> None:
    gutenberg_id   = book.get("gutenberg_id")
    split_mode     = book.get("gutenberg_split", "pattern")
    gutenberg_re   = book.get("gutenberg_re")
    heading_lines  = book.get("gutenberg_heading_lines", 2)

    if not gutenberg_id:
        print(f"  [{book['slug']}] No gutenberg_id — skipping")
        return
    if split_mode == "pattern" and not gutenberg_re:
        print(f"  [{book['slug']}] split_mode=pattern but no gutenberg_re — skipping")
        return

    print(f"  Downloading Gutenberg ID {gutenberg_id} …")
    try:
        raw = _download(gutenberg_id)
    except RuntimeError as e:
        print(f"  ERROR: {e}")
        return
    time.sleep(2)

    body = _strip_boilerplate(raw)

    if DUMP_RAW:
        print(f"\n  --- First 80 lines after boilerplate strip ---")
        for i, line in enumerate(body.splitlines()[:80], 1):
            print(f"  {i:3d}: {line!r}")
        print(f"  --- End dump ---\n")
        return

    # ── Split into sections ───────────────────────────────────────────────────
    if split_mode == "title":
        slug_to_section = _split_by_titles(body, book["chapters"])
        found = len(slug_to_section)
        total = len(book["chapters"])
        print(f"  Found {found}/{total} chapters by title")

        if LIST_ONLY:
            for ch in book["chapters"]:
                sec = slug_to_section.get(ch["slug"], "")
                words = len(sec.split()) if sec else 0
                status = f"{words} words" if sec else "NOT FOUND"
                print(f"    Ch.{ch['number']:2d}  {status:12s}  {ch['title']!r}")
            return

        book_dir = TEXTS_ROOT / book["slug"]
        for ch in book["chapters"]:
            sec = slug_to_section.get(ch["slug"])
            if not sec:
                print(f"    Ch.{ch['number']:2d} NOT FOUND  {ch['title']!r}")
                continue
            chapter_text = _strip_heading(sec, heading_lines)
            words    = len(chapter_text.split())
            out_path = book_dir / f"{ch['slug']}.txt"
            existing = "(overwrite)" if out_path.exists() else "(new)"
            print(f"    Ch.{ch['number']:2d}  {words:5d} words  {ch['title']!r}  -> {out_path.name} {existing}")
            book_dir.mkdir(parents=True, exist_ok=True)
            out_path.write_text(chapter_text, encoding="utf-8")

    else:  # pattern mode
        sections = _split_by_pattern(body, gutenberg_re)
        print(f"  Found {len(sections)} sections with pattern")

        if not sections:
            print(f"  WARNING: No boundaries matched: {gutenberg_re!r}")
            print(f"  Re-run with --dump to inspect the text format.")
            return

        if LIST_ONLY:
            for i, sec in enumerate(sections, 1):
                first = sec.splitlines()[0][:70] if sec else ""
                words = len(sec.split())
                print(f"    [{i:3d}]  {words:5d} words  {first!r}")
            return

        book_dir = TEXTS_ROOT / book["slug"]
        for ch in book["chapters"]:
            n = ch.get("gutenberg_n", ch["number"])
            if n < 1 or n > len(sections):
                print(f"    Ch.{ch['number']:2d} gutenberg_n={n} out of range (1–{len(sections)}) — skipping")
                continue
            chapter_text = _strip_heading(sections[n - 1], heading_lines)
            words    = len(chapter_text.split())
            out_path = book_dir / f"{ch['slug']}.txt"
            existing = "(overwrite)" if out_path.exists() else "(new)"
            print(f"    Ch.{ch['number']:2d} [{n:3d}]  {words:5d} words  {ch['title']!r}  -> {out_path.name} {existing}")
            book_dir.mkdir(parents=True, exist_ok=True)
            out_path.write_text(chapter_text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    books = config["books"]
    if BOOK_FILTER:
        books = [b for b in books if b["slug"] == BOOK_FILTER]
        if not books:
            print(f"Book '{BOOK_FILTER}' not found in config/books.yaml")
            sys.exit(1)

    for book in books:
        print(f"\n{book['title']} ({book['author']})")
        process_book(book)

    print("\nDone.")
    if not LIST_ONLY and not DUMP_RAW:
        print(f"Source texts saved under: {TEXTS_ROOT}")
        print("Next: python generator.py --force [--book SLUG]")
        print("Then: python verify_chapters.py [--book SLUG]")


if __name__ == "__main__":
    main()
