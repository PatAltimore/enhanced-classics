"""Add a book from a Gutenberg URL to config/books.yaml.

Fetches metadata from the Gutenberg catalog page, downloads the plain text,
auto-detects chapter heading patterns, and generates a books.yaml entry.

Usage:
    python add_book.py https://www.gutenberg.org/ebooks/8868
    python add_book.py https://www.gutenberg.org/ebooks/8868 --dry-run
    python add_book.py https://www.gutenberg.org/ebooks/8868 --no-append
"""
import html.parser
import pathlib
import re
import sys
import textwrap
import urllib.error
import urllib.request

import yaml

CONFIG_PATH = pathlib.Path(__file__).parent / "config" / "books.yaml"

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

# Common chapter heading patterns to try, in order of specificity
_CHAPTER_PATTERNS = [
    (r'^CHAPTER [IVXLC]+\.?\s*$', "Roman numeral CHAPTER headings"),
    (r'^CHAPTER \d+\.?\s*$', "Numbered CHAPTER headings"),
    (r'^Chapter [IVXLC]+\.?\s*$', "Title-case Roman numeral Chapter headings"),
    (r'^Chapter \d+\.?\s*$', "Title-case numbered Chapter headings"),
    (r'^ {10,}[IVXLC]+\s*$', "Indented Roman numerals"),
    (r'^ {10,}\d+\s*$', "Indented Arabic numerals"),
    (r'^[IVXLC]+\.\s*$', "Bare Roman numerals with period"),
    (r'^ [IVXLC]+\.\s*$', "Space-prefixed Roman numerals with period"),
    (r'^BOOK [IVXLC]+', "BOOK Roman numeral headings"),
    (r'^PART [IVXLC]+', "PART Roman numeral headings"),
    (r'^ACT [IVXLC]+', "ACT Roman numeral headings"),
    # Inline-title headings: the number and title share one line, e.g.
    # "Chapter I. Into the Primitive". Anchored at column 0 so the indented
    # table-of-contents entries (" Chapter I. …") are not matched. Listed last so
    # that books whose body uses bare headings still win the count tie-break.
    (r'^CHAPTER [IVXLC]+\.\s+\S.*$', "CHAPTER Roman numeral with inline title"),
    (r'^CHAPTER \d+\.\s+\S.*$',      "CHAPTER number with inline title"),
    (r'^Chapter [IVXLC]+\.\s+\S.*$', "Chapter Roman numeral with inline title"),
    (r'^Chapter \d+\.\s+\S.*$',      "Chapter number with inline title"),
]


# ---------------------------------------------------------------------------
# Gutenberg metadata parser
# ---------------------------------------------------------------------------

class _GutenbergMetadataParser(html.parser.HTMLParser):
    """Parse title, author, and subject from a Gutenberg ebook page."""

    def __init__(self):
        super().__init__()
        self._in_table = False
        self._current_header = None
        self._capture = False
        self._data_buf = []
        self.metadata: dict[str, str] = {}
        # Parse the <h1> for "Title by Author"
        self._in_h1 = False
        self._h1_text = ""

    def handle_starttag(self, tag, attrs):
        if tag == "h1":
            self._in_h1 = True
            self._h1_text = ""
        if tag == "td":
            self._capture = True
            self._data_buf = []
        if tag == "th":
            self._capture = True
            self._data_buf = []

    def handle_endtag(self, tag):
        if tag == "h1":
            self._in_h1 = False
        if tag == "th":
            self._capture = False
            self._current_header = "".join(self._data_buf).strip()
        if tag == "td":
            self._capture = False
            value = "".join(self._data_buf).strip()
            if self._current_header and value:
                self.metadata[self._current_header] = value
            self._current_header = None

    def handle_data(self, data):
        if self._in_h1:
            self._h1_text += data
        if self._capture:
            self._data_buf.append(data)


def _fetch_metadata(gutenberg_id: int) -> dict[str, str]:
    """Fetch book metadata from the Gutenberg HTML page."""
    url = f"https://www.gutenberg.org/ebooks/{gutenberg_id}"
    req = urllib.request.Request(
        url, headers={"User-Agent": "EnhancedClassics/1.0 (educational)"}
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        page_html = r.read().decode("utf-8", errors="replace")

    parser = _GutenbergMetadataParser()
    parser.feed(page_html)

    # Also extract from h1 "Title by Author"
    m = re.search(r"<h1[^>]*>(.+?)</h1>", page_html, re.DOTALL)
    if m:
        h1_text = re.sub(r"<[^>]+>", "", m.group(1)).strip()
        parser.metadata["_h1"] = h1_text

    return parser.metadata


def _parse_author_dates(author_raw: str) -> tuple[str, int | None, int | None]:
    """Parse 'LastName, FirstName, YYYY-YYYY' into (name, birth, death)."""
    # Remove dates at end like ", 1867-1916"
    m = re.search(r",\s*(\d{4})-(\d{4})\s*$", author_raw)
    birth = death = None
    if m:
        birth, death = int(m.group(1)), int(m.group(2))
        author_raw = author_raw[: m.start()].strip()
    # Flip "Last, First" to "First Last"
    parts = [p.strip() for p in author_raw.split(",", 1)]
    if len(parts) == 2:
        return f"{parts[1]} {parts[0]}", birth, death
    return author_raw, birth, death


# ---------------------------------------------------------------------------
# Download and strip boilerplate
# ---------------------------------------------------------------------------

def _download(gutenberg_id: int) -> str:
    last_err = None
    for tmpl in _PG_URLS:
        url = tmpl.format(id=gutenberg_id)
        print(f"  Trying {url} …", end=" ", flush=True)
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
# Chapter detection
# ---------------------------------------------------------------------------

def _detect_chapters(body: str) -> tuple[str | None, int, list[str]]:
    """Try common patterns and return (regex, count, first_lines).

    Returns the best-matching pattern (most chapters found) or None.
    """
    best_pattern = None
    best_count = 0
    best_lines: list[str] = []
    best_desc = ""

    for pattern, desc in _CHAPTER_PATTERNS:
        rx = re.compile(pattern, re.MULTILINE)
        matches = list(rx.finditer(body))
        count = len(matches)
        if count > best_count and count >= 2:  # need at least 2 chapters
            best_pattern = pattern
            best_count = count
            best_lines = [m.group(0).strip() for m in matches]
            best_desc = desc

    return best_pattern, best_count, best_lines, best_desc


def _heading_to_title(heading: str) -> str:
    """Convert a chapter heading line into a human-friendly title stub."""
    # Strip leading/trailing whitespace
    h = heading.strip()
    # If it's just "CHAPTER IV" or "CHAPTER 4", return the numeral
    m = re.match(r'^(?:CHAPTER|Chapter|BOOK|PART|ACT)\s+(.+)$', h)
    if m:
        return m.group(1).strip().rstrip(".")
    return h.rstrip(".")


def _inline_title(heading: str) -> "str | None":
    """Extract a chapter title that shares the heading line with the number.

    'Chapter I. Into the Primitive' -> 'Into the Primitive'. Returns None when the
    heading is only a number/numeral (the title is on a separate line instead, and
    the caller should fall back to _get_chapter_subtitle).
    """
    h = heading.strip()
    m = re.match(
        r'^(?:CHAPTER|Chapter|BOOK|PART|ACT)\s+[IVXLCDM\d]+\s*[.:\-—]?\s*(.+)$',
        h,
    )
    if m and m.group(1).strip():
        return m.group(1).strip()
    return None


def _roman_to_int(s: str) -> int:
    """Convert a Roman numeral string to integer."""
    roman_vals = {'I': 1, 'V': 5, 'X': 10, 'L': 50, 'C': 100, 'D': 500, 'M': 1000}
    s = s.upper().strip().rstrip(".")
    result = 0
    prev = 0
    for ch in reversed(s):
        val = roman_vals.get(ch, 0)
        if val < prev:
            result -= val
        else:
            result += val
        prev = val
    return result


# Words kept lowercase in a title unless they are the first or last word.
_TITLE_STOPWORDS = {
    "a", "an", "the", "and", "but", "or", "nor", "for", "of", "on", "in", "to",
    "with", "as", "at", "by", "from", "off", "up", "via", "per", "vs",
}


def _needs_titlecasing(text: str) -> bool:
    """True when a multi-word title looks under-capitalised (e.g. Gutenberg's
    'the call of the wild') — i.e. no word after the first starts uppercase."""
    words = text.split()
    return len(words) >= 2 and not any(w[:1].isupper() for w in words[1:])


def _titlecase(text: str) -> str:
    """Title-case a string, keeping small joining words lowercase mid-title."""
    words = text.split()
    out = []
    for i, w in enumerate(words):
        lw = w.lower()
        if 0 < i < len(words) - 1 and lw in _TITLE_STOPWORDS:
            out.append(lw)
        else:
            out.append(lw[:1].upper() + lw[1:])
    return " ".join(out)


def _slugify(text: str) -> str:
    """Turn text into a URL-friendly slug."""
    text = text.lower()
    text = re.sub(r"[''']", "", text)  # remove apostrophes
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def _guess_heading_lines(body: str, pattern: str) -> int:
    """Guess how many heading lines to skip by looking at the first match."""
    rx = re.compile(pattern, re.MULTILINE)
    m = rx.search(body)
    if not m:
        return 1
    # Look at lines after the match
    after = body[m.end():].lstrip("\n")
    first_line = after.split("\n", 1)[0].strip() if after else ""
    # If the next non-empty line looks like a subtitle (short, title case), it's 2 heading lines
    if first_line and len(first_line) < 80 and not first_line[0].islower():
        # Check if it's actual prose (long) or a subtitle (short)
        if len(first_line.split()) <= 8:
            return 2
    return 1


def _get_chapter_subtitle(body: str, pattern: str, chapter_idx: int) -> str | None:
    """Try to get the subtitle line after a chapter heading (e.g., CHAPTER I / A SUBTITLE)."""
    rx = re.compile(pattern, re.MULTILINE)
    matches = list(rx.finditer(body))
    if chapter_idx >= len(matches):
        return None
    m = matches[chapter_idx]
    # Get lines after the heading
    after = body[m.end():].lstrip("\r")
    lines = after.split("\n")
    # Skip empty lines
    for line in lines:
        stripped = line.strip()
        if stripped:
            # If it looks like a title (short, mostly uppercase or title case)
            if len(stripped) < 80 and len(stripped.split()) <= 10:
                return stripped
            break
    return None


# ---------------------------------------------------------------------------
# YAML generation
# ---------------------------------------------------------------------------

def _generate_entry(
    gutenberg_id: int,
    title: str,
    author: str,
    year: int | None,
    description: str,
    slug: str,
    pattern: str,
    heading_lines: int,
    chapters: list[dict],
) -> str:
    """Generate a books.yaml entry as a YAML string."""
    entry = {
        "slug": slug,
        "title": title,
        "author": author,
    }
    if year:
        entry["year"] = year
    entry["gutenberg_id"] = gutenberg_id
    entry["gutenberg_split"] = "pattern"
    entry["gutenberg_re"] = pattern
    entry["gutenberg_heading_lines"] = heading_lines
    entry["description"] = description
    entry["chapters"] = chapters

    # Use yaml.dump but with nicer formatting
    lines = []
    lines.append(f'  - slug: "{slug}"')
    lines.append(f'    title: "{title}"')
    lines.append(f'    author: "{author}"')
    if year:
        lines.append(f'    year: {year}')
    lines.append(f'    gutenberg_id: {gutenberg_id}')
    lines.append(f'    gutenberg_split: pattern')
    lines.append(f"    gutenberg_re: '{pattern}'")
    lines.append(f'    gutenberg_heading_lines: {heading_lines}')
    lines.append(f'    description: >')
    # Wrap description to ~70 chars
    for wrap_line in textwrap.wrap(description, width=70):
        lines.append(f'      {wrap_line}')
    lines.append(f'    chapters:')
    for ch in chapters:
        lines.append(f'      - number: {ch["number"]}')
        lines.append(f'        title: "{ch["title"]}"')
        lines.append(f'        slug: "{ch["slug"]}"')

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1].startswith("-"):
        print("Usage: python add_book.py <gutenberg-url-or-id> [--dry-run] [--no-append]")
        print("Example: python add_book.py https://www.gutenberg.org/ebooks/8868")
        sys.exit(1)

    dry_run = "--dry-run" in sys.argv
    no_append = "--no-append" in sys.argv

    # Parse Gutenberg ID from URL or bare number
    arg = sys.argv[1]
    m = re.search(r"(\d+)\s*$", arg)
    if not m:
        print(f"ERROR: Could not extract Gutenberg ID from: {arg}")
        sys.exit(1)
    gutenberg_id = int(m.group(1))

    print(f"Gutenberg ID: {gutenberg_id}")
    print()

    # --- Fetch metadata ---
    print("Fetching metadata from Gutenberg catalog page…")
    try:
        meta = _fetch_metadata(gutenberg_id)
    except Exception as e:
        print(f"ERROR fetching metadata: {e}")
        sys.exit(1)

    # Parse title and author
    title = meta.get("Title", "")
    author_raw = meta.get("Author", "")
    author, birth_year, death_year = _parse_author_dates(author_raw)

    # If title not found in table, try h1
    if not title and "_h1" in meta:
        h1 = meta["_h1"]
        by_match = re.match(r"(.+?)\s+by\s+(.+)", h1, re.IGNORECASE)
        if by_match:
            title = by_match.group(1).strip()
            if not author:
                author = by_match.group(2).strip()

    if not title:
        title = input("  Title not found. Enter title: ").strip()
    if not author:
        author = input("  Author not found. Enter author: ").strip()

    # Some Gutenberg records store the title all-lowercase ("the call of the
    # wild"); normalise those while leaving already-cased titles untouched.
    if _needs_titlecasing(title):
        fixed = _titlecase(title)
        if fixed != title:
            print(f"  Title looks lower-cased; normalised to: {fixed!r}")
            title = fixed

    # Try to guess publication year (not always available from Gutenberg)
    year = None
    release_date = meta.get("Release Date", "")
    # Gutenberg gives release date, not publication year. Ask user.
    print(f"\n  Title:  {title}")
    print(f"  Author: {author}")
    if birth_year:
        print(f"  Author dates: {birth_year}–{death_year}")

    year_input = input(f"  Original publication year (or Enter to skip): ").strip()
    if year_input.isdigit():
        year = int(year_input)

    description = input(f"  Short description (1-2 sentences): ").strip()
    if not description:
        description = f"A classic work by {author}."

    slug = _slugify(title)
    print(f"  Slug: {slug}")
    slug_input = input(f"  Press Enter to accept or type a custom slug: ").strip()
    if slug_input:
        slug = slug_input

    # --- Check for duplicate ---
    with open(CONFIG_PATH, encoding="utf-8") as f:
        config = yaml.safe_load(f)
    existing_slugs = {b["slug"] for b in config["books"]}
    if slug in existing_slugs:
        print(f"\n  WARNING: slug '{slug}' already exists in books.yaml!")
        resp = input("  Continue anyway? [y/N]: ").strip().lower()
        if resp != "y":
            sys.exit(0)

    # --- Download text ---
    print(f"\nDownloading text…")
    try:
        raw = _download(gutenberg_id)
    except RuntimeError as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    body = _strip_boilerplate(raw)
    total_words = len(body.split())
    print(f"  Text body: {total_words:,} words")

    # --- Detect chapters ---
    print("\nDetecting chapter pattern…")
    pattern, count, heading_lines_list, desc = _detect_chapters(body)

    if not pattern:
        print("  No chapter pattern auto-detected.")
        print("  Common patterns to try:")
        for p, d in _CHAPTER_PATTERNS:
            print(f"    {d:45s}  {p}")
        custom = input("\n  Enter a regex pattern (or Enter to use whole text as 1 chapter): ").strip()
        if custom:
            rx = re.compile(custom, re.MULTILINE)
            matches = list(rx.finditer(body))
            if matches:
                pattern = custom
                count = len(matches)
                heading_lines_list = [m.group(0).strip() for m in matches]
                desc = "Custom pattern"
            else:
                print("  Pattern matched 0 sections. Exiting.")
                sys.exit(1)
        else:
            pattern = None
            count = 1

    if pattern:
        print(f"  Pattern: {pattern}")
        print(f"  Description: {desc}")
        print(f"  Chapters found: {count}")
        print(f"  First few headings:")
        for h in heading_lines_list[:5]:
            print(f"    {h!r}")
        if count > 5:
            print(f"    … and {count - 5} more")

        # Inline-title headings ("Chapter I. Into the Primitive") are a single
        # line, so only that line is skipped — the subtitle heuristic would
        # wrongly count a following epigraph/first line as a second heading line.
        if heading_lines_list and _inline_title(heading_lines_list[0]):
            heading_lines = 1
        else:
            heading_lines = _guess_heading_lines(body, pattern)
        print(f"  Heading lines to skip: {heading_lines}")

    # --- Build chapter list ---
    print("\nBuilding chapter list…")
    chapters = []

    if pattern:
        for i in range(count):
            # Prefer a title on the heading line itself ("Chapter I. Into the
            # Primitive"); otherwise fall back to a subtitle on the next line.
            heading   = heading_lines_list[i] if i < len(heading_lines_list) else ""
            raw_title = _inline_title(heading)
            if not raw_title:
                subtitle  = _get_chapter_subtitle(body, pattern, i)
                raw_title = subtitle.strip() if subtitle else None
            if raw_title:
                # Title-case ALL-CAPS headings; keep mixed-case titles as written.
                ch_title = raw_title.title() if raw_title.isupper() else raw_title
            else:
                ch_title = f"Chapter {i + 1}"

            ch_slug = f"chapter-{i + 1:02d}-{_slugify(ch_title)}"
            # Truncate slug if too long
            if len(ch_slug) > 50:
                ch_slug = ch_slug[:50].rstrip("-")

            chapters.append({
                "number": i + 1,
                "title": ch_title,
                "slug": ch_slug,
            })
    else:
        chapters.append({
            "number": 1,
            "title": title,
            "slug": f"chapter-01-{slug}",
        })

    # --- Generate YAML entry ---
    print("\n" + "=" * 70)
    print("Generated books.yaml entry:")
    print("=" * 70)

    entry_yaml = _generate_entry(
        gutenberg_id=gutenberg_id,
        title=title,
        author=author,
        year=year,
        description=description,
        slug=slug,
        pattern=pattern or ".*",
        heading_lines=heading_lines if pattern else 0,
        chapters=chapters,
    )
    print()
    print(entry_yaml)
    print()
    print("=" * 70)

    if dry_run:
        print("\n--dry-run: not writing anything.")
        return

    if no_append:
        print("\n--no-append: entry printed above but not written to books.yaml.")
        print("Copy and paste it into config/books.yaml manually.")
        return

    # --- Append to books.yaml ---
    resp = input("\nAppend this entry to config/books.yaml? [Y/n]: ").strip().lower()
    if resp in ("", "y", "yes"):
        with open(CONFIG_PATH, "a", encoding="utf-8") as f:
            f.write("\n" + entry_yaml + "\n")
        print(f"  ✓ Appended to {CONFIG_PATH}")
        print(f"\nNext steps:")
        print(f"  1. Review/edit the entry in config/books.yaml")
        print(f"     (especially chapter titles and slugs)")
        print(f"  2. python fetch_texts.py --book {slug} --list")
        print(f"  3. python fetch_texts.py --book {slug}")
        print(f"  4. python generator.py --book {slug} --force")
    else:
        print("  Not written. Copy the entry above manually.")


if __name__ == "__main__":
    main()
