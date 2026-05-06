"""Disk-based checkpoint tracker.

A chapter is considered done if its output file already exists.
This means the generator can be interrupted and restarted at any time
without regenerating completed chapters.
"""
from pathlib import Path


class Checkpointer:
    def __init__(self, output_dir: str):
        self.root = Path(output_dir)

    def path_for(self, book_slug: str, chapter_slug: str) -> Path:
        return self.root / book_slug / f"{chapter_slug}.md"

    def is_done(self, book_slug: str, chapter_slug: str) -> bool:
        return self.path_for(book_slug, chapter_slug).exists()

    def save(self, book_slug: str, chapter_slug: str, content: str) -> Path:
        path = self.path_for(book_slug, chapter_slug)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path
