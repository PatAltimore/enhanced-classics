"""Keeps public/catalog.json in sync with generated chapters.

After generation, call sync() to add any new books/chapters from books.yaml
into catalog.json without touching entries that already exist.
"""
import json
from pathlib import Path


CATALOG_PATH = Path(__file__).parent / ".." / "public" / "catalog.json"


def _load_catalog() -> dict:
    if CATALOG_PATH.exists():
        return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    return {"books": []}


def _save_catalog(catalog: dict) -> None:
    CATALOG_PATH.write_text(
        json.dumps(catalog, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def sync(config: dict, checkpointer) -> None:
    """Add generated books/chapters to catalog.json.

    Only adds entries whose output files exist on disk; skips anything
    already present in the catalog.
    """
    catalog = _load_catalog()
    existing_books = {b["slug"]: b for b in catalog["books"]}
    changed = False

    for book in config["books"]:
        slug = book["slug"]

        # Collect only the chapters that have been generated
        new_chapters = [
            {"number": c["number"], "title": c["title"], "slug": c["slug"]}
            for c in book["chapters"]
            if checkpointer.is_done(slug, c["slug"])
        ]

        if not new_chapters and slug not in existing_books:
            continue  # Nothing generated yet — don't create an empty catalog entry

        if slug not in existing_books:
            existing_books[slug] = {
                "slug": slug,
                "title": book["title"],
                "author": book["author"],
                "year": book["year"],
                "description": book.get("description", ""),
                "chapters": [],
            }
            changed = True

        catalog_book = existing_books[slug]
        existing_chapter_slugs = {c["slug"] for c in catalog_book["chapters"]}

        for chapter in new_chapters:
            if chapter["slug"] in existing_chapter_slugs:
                continue
            catalog_book["chapters"].append(chapter)
            changed = True

        # Keep chapters sorted by number
        catalog_book["chapters"].sort(key=lambda c: c["number"])

    if changed:
        catalog["books"] = list(existing_books.values())
        _save_catalog(catalog)
