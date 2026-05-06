"""Fetch real Wikimedia Commons images for enhancement cards that have no image.

For each enhancement with an empty image_url, searches the Commons API
using the enhancement title, picks the first valid image result, and
patches the chapter file in place.

Usage:
    python find_images.py                  # all books
    python find_images.py --book walden    # one book
    python find_images.py --dry-run        # preview without writing
"""
import json
import pathlib
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BOOKS_ROOT = pathlib.Path(__file__).parent / ".." / "public" / "books"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
THUMB_WIDTH  = 330
DELAY        = 2.5   # seconds between API calls — be polite to Commons

DRY_RUN     = "--dry-run" in sys.argv
BOOK_FILTER = sys.argv[sys.argv.index("--book") + 1] if "--book" in sys.argv else None

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".tiff", ".tif"}


# ---------------------------------------------------------------------------
# Wikimedia Commons API helpers
# ---------------------------------------------------------------------------

def _api(params: dict) -> dict:
    params["format"] = "json"
    url = COMMONS_API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "EnhancedClassics/1.0 (educational)"})
    waits = [10, 30, 60, 120]
    for attempt, wait in enumerate(waits):
        try:
            with urllib.request.urlopen(req, timeout=12) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                print(f"rate limited, waiting {wait}s...", end=" ", flush=True)
                time.sleep(wait)
            else:
                raise
    # Final attempt after longest wait
    with urllib.request.urlopen(req, timeout=12) as r:
        return json.loads(r.read().decode("utf-8"))


def _thumb_and_caption(file_title: str) -> tuple[str, str]:
    """Return (thumb_url, caption) for a Commons File: title, or ("", "")."""
    data = _api({
        "action": "query",
        "titles": file_title,
        "prop": "imageinfo",
        "iiprop": "url|extmetadata",
        "iiurlwidth": str(THUMB_WIDTH),
    })
    for page in data.get("query", {}).get("pages", {}).values():
        for info in page.get("imageinfo", []):
            thumb = info.get("thumburl", "")
            if not thumb:
                continue
            meta    = info.get("extmetadata", {})
            desc    = re.sub(r"<[^>]+>", "", meta.get("ImageDescription", {}).get("value", "")).strip()
            license_ = meta.get("LicenseShortName", {}).get("value", "")
            # Use description if short enough, otherwise fall back to cleaned filename
            if desc and len(desc) < 120:
                caption = desc
            else:
                name = re.sub(r"\.\w+$", "", file_title.replace("File:", "")).replace("_", " ")
                caption = name
            if license_:
                caption += f" ({license_})"
            # Escape any double-quotes so the value is safe inside YAML "..."
            caption = caption.replace('"', '\\"')[:200]
            return thumb, caption
    return "", ""


def search_image(query: str) -> tuple[str, str] | None:
    """Return (thumb_url, caption) for the best Commons match, or None."""
    data = _api({
        "action": "query",
        "list": "search",
        "srsearch": query,
        "srnamespace": "6",   # File namespace only
        "srlimit": "5",
    })
    for result in data.get("query", {}).get("search", []):
        title = result["title"]
        ext   = pathlib.Path(title.lower()).suffix
        if ext not in IMAGE_EXTS:
            continue
        thumb, caption = _thumb_and_caption(title)
        if thumb:
            return thumb, caption
    return None


# ---------------------------------------------------------------------------
# File patching
# ---------------------------------------------------------------------------

# Matches an enhancement block where image_url and image_caption are both empty
ENH_RE = re.compile(
    r'(  - id: "[^"]*"\n'
    r'    trigger: "[^"]*"\n'
    r'    title: "([^"]*)"\n'
    r'    wikipedia_url: "([^"]*)"\n'
    r'    image_url: ""\n'
    r'    image_caption: "")',
    re.MULTILINE,
)


def _wikipedia_topic(url: str) -> str:
    """Extract the article title from a Wikipedia URL for use as a search hint."""
    m = re.search(r"/wiki/(.+)$", url)
    if m:
        return m.group(1).replace("_", " ")
    return ""


def process_file(path: pathlib.Path) -> int:
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    new_text = text
    patches = 0

    for match in ENH_RE.finditer(text):
        block        = match.group(1)
        enh_title    = match.group(2)
        wiki_url     = match.group(3)

        # Build search queries in preference order
        queries = [enh_title]
        topic = _wikipedia_topic(wiki_url)
        if topic and topic.lower() not in enh_title.lower():
            queries.append(topic)

        result = None
        for query in queries:
            print(f"    [{query}]", end=" ... ", flush=True)
            time.sleep(DELAY)
            try:
                result = search_image(query)
            except Exception as e:
                print(f"error ({e})")
                result = None
            if result:
                break

        if not result:
            print("no image found")
            continue

        thumb_url, caption = result
        print("OK")

        new_block = block.replace(
            '    image_url: ""\n    image_caption: ""',
            f'    image_url: "{thumb_url}"\n    image_caption: "{caption}"',
        )
        new_text = new_text.replace(block, new_block, 1)
        patches += 1

    if patches and not DRY_RUN:
        path.write_text(new_text, encoding="utf-8")

    return patches


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    books = sorted(d for d in BOOKS_ROOT.iterdir() if d.is_dir())
    if BOOK_FILTER:
        books = [b for b in books if b.name == BOOK_FILTER]
        if not books:
            print(f"Book '{BOOK_FILTER}' not found under {BOOKS_ROOT}")
            sys.exit(1)

    total = 0
    for book_dir in books:
        for md in sorted(book_dir.glob("*.md")):
            print(f"\n  {book_dir.name}/{md.name}")
            n = process_file(md)
            if n:
                print(f"  >> {n} image(s) {'would be added' if DRY_RUN else 'added'}")
            total += n

    print(f"\nDone — {total} image(s) {'would be ' if DRY_RUN else ''}added across all files.")


if __name__ == "__main__":
    main()
