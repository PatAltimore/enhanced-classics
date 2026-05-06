"""Check every image_url in generated chapter files and blank out 404s.

Usage:
    python fix_image_urls.py [--dry-run]
"""
import re
import sys
import pathlib
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed

DRY_RUN = "--dry-run" in sys.argv
BOOKS_ROOT = pathlib.Path(__file__).parent / ".." / "public" / "books"
IMAGE_RE = re.compile(r'(    image_url: )"(https?://[^"]+)"')
TIMEOUT = 8


def check_url(url: str) -> bool:
    try:
        req = urllib.request.Request(url, method="HEAD",
                                     headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.status < 400
    except Exception:
        return False


def collect_urls(files):
    """Return {url: [path, ...]} mapping."""
    index = {}
    for path in files:
        for url in IMAGE_RE.findall(path.read_text(encoding="utf-8", errors="replace")):
            _, u = url
            index.setdefault(u, []).append(path)
    return index


def main():
    files = sorted(BOOKS_ROOT.rglob("*.md"))
    url_map = collect_urls(files)

    if not url_map:
        print("No image URLs found.")
        return

    print(f"Checking {len(url_map)} unique image URLs …\n")

    bad = set()
    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(check_url, url): url for url in url_map}
        for i, future in enumerate(as_completed(futures), 1):
            url = futures[future]
            ok = future.result()
            status = "OK  " if ok else "404 "
            print(f"  {status} {url}")
            if not ok:
                bad.add(url)

    print(f"\n{len(bad)} bad URL(s) found out of {len(url_map)}.")

    if not bad:
        print("Nothing to fix.")
        return

    fixed_files = set()
    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        new_text = text
        for _, url in IMAGE_RE.findall(text):
            if url in bad:
                new_text = new_text.replace(
                    f'    image_url: "{url}"',
                    '    image_url: ""'
                )
                # Also clear the caption
                new_text = re.sub(
                    r'(    image_caption: )"[^"]*"',
                    r'\1""',
                    new_text,
                    count=1
                )
        if new_text != text:
            fixed_files.add(path)
            if not DRY_RUN:
                path.write_text(new_text, encoding="utf-8")

    if DRY_RUN:
        print(f"[dry-run] Would fix {len(fixed_files)} file(s).")
    else:
        print(f"Fixed {len(fixed_files)} file(s).")
        for p in sorted(fixed_files):
            print(f"  {p.relative_to(BOOKS_ROOT.parent.parent)}")


if __name__ == "__main__":
    main()
