"""Fetch real images for enhancement cards that have no image.

Image search priority per enhancement:
  1. Wikipedia pageimages API — curated lead image for the linked article.
  2. Wikimedia Commons search using the trigger phrase (short, focused keyword).
  3. Wikimedia Commons search using the Wikipedia article title from the URL.
  4. Wikimedia Commons search using the enhancement card title (last resort).

Each enhancement with an empty image_url is patched in-place.

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

BOOKS_ROOT   = pathlib.Path(__file__).parent / ".." / "public" / "books"
COMMONS_API  = "https://commons.wikimedia.org/w/api.php"
WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
THUMB_WIDTH  = 330
DELAY        = 2.5   # seconds between API calls — be polite

DRY_RUN     = "--dry-run" in sys.argv
BOOK_FILTER = sys.argv[sys.argv.index("--book") + 1] if "--book" in sys.argv else None

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".tiff", ".tif"}


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

def _get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "EnhancedClassics/1.0 (educational)"})
    waits = [10, 30, 60, 120]
    for wait in waits:
        try:
            with urllib.request.urlopen(req, timeout=12) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                print(f"rate limited, waiting {wait}s...", end=" ", flush=True)
                time.sleep(wait)
            else:
                raise
    with urllib.request.urlopen(req, timeout=12) as r:
        return json.loads(r.read().decode("utf-8"))


def _commons_api(params: dict) -> dict:
    params["format"] = "json"
    return _get(COMMONS_API + "?" + urllib.parse.urlencode(params))


def _wikipedia_api(params: dict) -> dict:
    params["format"] = "json"
    return _get(WIKIPEDIA_API + "?" + urllib.parse.urlencode(params))


# ---------------------------------------------------------------------------
# Commons helpers
# ---------------------------------------------------------------------------

def _thumb_and_caption(file_title: str) -> tuple[str, str]:
    """Return (thumb_url, caption) for a Commons File: title, or ("", "")."""
    data = _commons_api({
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
            meta     = info.get("extmetadata", {})
            desc     = re.sub(r"<[^>]+>", "", meta.get("ImageDescription", {}).get("value", "")).strip()
            license_ = meta.get("LicenseShortName", {}).get("value", "")
            if desc and len(desc) < 120:
                caption = desc
            else:
                name    = re.sub(r"\.\w+$", "", file_title.replace("File:", "")).replace("_", " ")
                caption = name
            if license_:
                caption += f" ({license_})"
            caption = caption.replace('"', '\\"')[:200]
            return thumb, caption
    return "", ""


def _commons_search(query: str) -> tuple[str, str] | None:
    """Return (thumb_url, caption) for the best Commons match, or None."""
    data = _commons_api({
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
# Wikipedia pageimages (primary source)
# ---------------------------------------------------------------------------

def _wikipedia_topic(url: str) -> str:
    """Extract the article title from a Wikipedia URL."""
    m = re.search(r"/wiki/(.+)$", url)
    return m.group(1).replace("_", " ") if m else ""


def get_wikipedia_image(wiki_url: str) -> tuple[str, str] | None:
    """Return (thumb_url, caption) using Wikipedia's curated pageimages API.

    Wikipedia editors pick a lead image for every article that best represents
    the topic — far more reliable than a keyword search on Commons.
    """
    topic = _wikipedia_topic(wiki_url)
    if not topic:
        return None
    try:
        data = _wikipedia_api({
            "action": "query",
            "titles": topic,
            "prop": "pageimages",
            "pithumbsize": str(THUMB_WIDTH),
            "piprop": "thumbnail|name",
        })
    except Exception as e:
        print(f"wikipedia API error ({e})", end=" ", flush=True)
        return None

    for page in data.get("query", {}).get("pages", {}).values():
        page_image = page.get("pageimage", "")
        thumb_info = page.get("thumbnail", {})
        if page_image and thumb_info.get("source"):
            # Use Commons metadata for the license/caption where possible
            file_title = f"File:{page_image}"
            thumb_url, caption = _thumb_and_caption(file_title)
            if thumb_url:
                return thumb_url, caption
            # Commons lookup failed — use the Wikipedia thumbnail with a plain caption
            caption = re.sub(r"\.\w+$", "", page_image.replace("_", " "))
            caption = caption.replace('"', '\\"')[:200]
            return thumb_info["source"], caption
    return None


# ---------------------------------------------------------------------------
# File patching
# ---------------------------------------------------------------------------

# Matches an enhancement block where image_url and image_caption are both empty
ENH_RE = re.compile(
    r'(  - id: "[^"]*"\n'
    r'    trigger: "([^"]*)"\n'
    r'    title: "([^"]*)"\n'
    r'    wikipedia_url: "([^"]*)"\n'
    r'    image_url: ""\n'
    r'    image_caption: "")',
    re.MULTILINE,
)


def process_file(path: pathlib.Path) -> int:
    text     = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    new_text = text
    patches  = 0

    for match in ENH_RE.finditer(text):
        block      = match.group(1)
        trigger    = match.group(2)
        enh_title  = match.group(3)
        wiki_url   = match.group(4)
        topic      = _wikipedia_topic(wiki_url)

        result = None

        # 1. Wikipedia pageimages — curated lead image for the article
        print(f"    [wikipedia:{topic or '?'}]", end=" ... ", flush=True)
        time.sleep(DELAY)
        try:
            result = get_wikipedia_image(wiki_url)
        except Exception as e:
            print(f"error ({e})", end=" ", flush=True)
            result = None
        if result:
            print("OK (wikipedia)")

        # 2. Commons search: trigger phrase
        if not result and trigger:
            print(f"    [commons:{trigger}]", end=" ... ", flush=True)
            time.sleep(DELAY)
            try:
                result = _commons_search(trigger)
            except Exception as e:
                print(f"error ({e})", end=" ", flush=True)
                result = None
            if result:
                print("OK (trigger)")

        # 3. Commons search: Wikipedia article title from the URL
        if not result and topic and topic.lower() not in trigger.lower():
            print(f"    [commons:{topic}]", end=" ... ", flush=True)
            time.sleep(DELAY)
            try:
                result = _commons_search(topic)
            except Exception as e:
                print(f"error ({e})", end=" ", flush=True)
                result = None
            if result:
                print("OK (topic)")

        # 4. Commons search: enhancement card title (last resort)
        if not result:
            print(f"    [commons:{enh_title}]", end=" ... ", flush=True)
            time.sleep(DELAY)
            try:
                result = _commons_search(enh_title)
            except Exception as e:
                print(f"error ({e})", end=" ", flush=True)
                result = None
            if result:
                print("OK (title)")

        if not result:
            print("no image found")
            continue

        thumb_url, caption = result
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
