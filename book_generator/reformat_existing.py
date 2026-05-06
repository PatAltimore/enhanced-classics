"""Fix frontmatter format in already-generated chapter files.

Reads each file using Python's yaml library (which handles block scalars
correctly), then rewrites it using the formatter that the app's custom
YAML parser can actually read.

Usage:
    python reformat_existing.py
"""
import sys
from pathlib import Path
import yaml

sys.path.insert(0, str(Path(__file__).parent))
from formatter import _build_yaml, _q

BOOKS_ROOT = Path(__file__).parent / ".." / "public" / "books"
SEPARATOR = "---"


def split_file(text: str):
    """Split a chapter file into (frontmatter_str, body_str)."""
    if not text.startswith("---"):
        return None, text
    second = text.index("---", 3)
    fm = text[3:second].strip()
    body = text[second + 3:].strip()
    return fm, body


def reformat(path: Path) -> bool:
    raw = path.read_text(encoding="utf-8")
    fm_str, body = split_file(raw)
    if fm_str is None:
        return False

    meta = yaml.safe_load(fm_str)
    if not meta:
        return False

    # Reconstruct the book/chapter dicts formatter.py expects
    book = {
        "title": meta.get("title", ""),
        "author": meta.get("author", ""),
        "year": meta.get("year", 0),
        "slug": meta.get("book_slug", ""),
    }
    chapter = {
        "number": meta.get("chapter", 0),
        "title": meta.get("chapter_title", ""),
        "slug": meta.get("slug", ""),
    }
    data = {
        "summary": meta.get("summary", []),
        "enhancements": meta.get("enhancements", []),
    }

    new_yaml = _build_yaml(book, chapter, data)
    new_content = f"{new_yaml}\n{body}\n"

    if new_content == raw:
        return False

    path.write_text(new_content, encoding="utf-8")
    return True


def main():
    fixed = skipped = 0
    for md in sorted(BOOKS_ROOT.rglob("*.md")):
        try:
            if reformat(md):
                print(f"  fixed   {md.relative_to(BOOKS_ROOT.parent.parent)}")
                fixed += 1
            else:
                skipped += 1
        except Exception as e:
            print(f"  ERROR   {md.name}: {e}")

    print(f"\n{fixed} reformatted, {skipped} already correct.")


if __name__ == "__main__":
    main()
