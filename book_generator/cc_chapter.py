"""Claude Code workflow helper — no API keys or model clients required.

Claude (in a Claude Code session) does the annotation work; this script does the
deterministic parts: slicing the source text into annotation windows, validating
Claude's JSON, injecting **markers**, writing the chapter markdown, and syncing
catalog.json.

Usage:
  python cc_chapter.py status   --book walden
  python cc_chapter.py windows  --book walden --chapter 6
  python cc_chapter.py assemble --book walden --chapter 6 [--file work/x.json] [--no-images] [--force]
  python cc_chapter.py catalog

Claude writes work/<book>/<chapter-slug>.json:
  {
    "phrases":      ["one verbatim phrase per window, in window order", ...],
    "summary":      [{"point": "...", "link": "...", "link_label": "..."}, ... 5-6 items],
    "enhancements": [{"id": "...", "trigger": "<exactly one of phrases>", "title": "...",
                      "wikipedia_url": "...", "image_url": "", "image_caption": "",
                      "content": "250-300 words"}, ...]   # one per phrase
  }
"""
import argparse
import io
import json
import re
import sys
from pathlib import Path

import yaml

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from checkpointer import Checkpointer
from formatter import format_chapter
from markers import _find_match, _inject_markers
from prompts import make_windows
import catalog_sync

HERE        = Path(__file__).parent
CONFIG_PATH = HERE / "config" / "books.yaml"
TEXTS_ROOT  = HERE / "source_texts"
WORK_ROOT   = HERE / "work"

_FORBIDDEN_CLOSINGS = (
    "this underscores", "this highlights", "this reflects",
    "this reinforces", "this aligns with", "this exemplifies",
)


def _load():
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    return config, Checkpointer(HERE / config["output_dir"])


def _find_book_chapter(config: dict, book_slug: str, number: int | None):
    book = next((b for b in config["books"] if b["slug"] == book_slug), None)
    if book is None:
        sys.exit(f"Book '{book_slug}' not found in config/books.yaml")
    if number is None:
        return book, None
    chapter = next((c for c in book["chapters"] if c["number"] == number), None)
    if chapter is None:
        sys.exit(f"Chapter {number} not in config for '{book_slug}'")
    return book, chapter


def _source(book: dict, chapter: dict) -> str:
    path = TEXTS_ROOT / book["slug"] / f"{chapter['slug']}.txt"
    if not path.exists():
        sys.exit(f"No source text at {path} — run fetch_texts.py --book {book['slug']} first")
    return path.read_text(encoding="utf-8").strip()


def cmd_status(args) -> None:
    config, cp = _load()
    book, _ = _find_book_chapter(config, args.book, None)
    print(f"{book['title']} — {book['author']} ({book['year']})")
    for c in book["chapters"]:
        src = (TEXTS_ROOT / book["slug"] / f"{c['slug']}.txt").exists()
        done = cp.is_done(book["slug"], c["slug"])
        words = len((TEXTS_ROOT / book["slug"] / f"{c['slug']}.txt").read_text(encoding="utf-8").split()) if src else 0
        n_win = len(make_windows((TEXTS_ROOT / book["slug"] / f"{c['slug']}.txt").read_text(encoding="utf-8").strip())) if src else 0
        state = "DONE   " if done else ("pending" if src else "no-src ")
        print(f"  {c['number']:>3}  {state}  {words:>6} words  {n_win:>2} windows  {c['title']}")


def cmd_windows(args) -> None:
    config, _ = _load()
    book, chapter = _find_book_chapter(config, args.book, args.chapter)
    windows = make_windows(_source(book, chapter))
    print(f'Book: "{book["title"]}" by {book["author"]} ({book["year"]})')
    print(f'Chapter {chapter["number"]}: {chapter["title"]}  (slug: {chapter["slug"]})')
    print(f"{len(windows)} windows -> provide EXACTLY {len(windows)} phrases, one verbatim phrase per window, in order.")
    print(f"Output file: work/{book['slug']}/{chapter['slug']}.json\n")
    for i, w in enumerate(windows, 1):
        print(f"[WINDOW {i} of {len(windows)}]\n{w}\n")


def cmd_assemble(args) -> None:
    config, cp = _load()
    book, chapter = _find_book_chapter(config, args.book, args.chapter)
    json_path = Path(args.file) if args.file else WORK_ROOT / book["slug"] / f"{chapter['slug']}.json"
    if not json_path.exists():
        sys.exit(f"Missing {json_path}")
    if cp.is_done(book["slug"], chapter["slug"]) and not args.force:
        sys.exit(f"{chapter['slug']}.md already exists — pass --force to overwrite")

    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        sys.exit(f"{json_path} is not valid JSON: {exc}")

    original = _source(book, chapter)
    windows = make_windows(original)
    phrases = data.get("phrases", [])
    summary = data.get("summary", [])
    enhancements = data.get("enhancements", [])
    errors: list[str] = []
    warnings: list[str] = []

    # Phrases: one per window, verbatim within its window
    if len(phrases) != len(windows):
        errors.append(f"phrases: expected {len(windows)} (one per window), got {len(phrases)}")
    for i, (phrase, window) in enumerate(zip(phrases, windows), 1):
        if _find_match(window, phrase) is None:
            errors.append(f"window {i}: phrase {phrase!r} is not a verbatim substring of that window")
    if len(set(phrases)) != len(phrases):
        dupes = sorted({p for p in phrases if phrases.count(p) > 1})
        warnings.append(f"duplicate phrases (only first occurrence is marked): {dupes}")

    # Inject markers and confirm each one landed
    text, failed = _inject_markers(original, phrases)
    for p in failed:
        errors.append(f"could not mark phrase in text: {p!r}")
    for p in phrases:
        if f"**{p}**" not in text and p not in failed and _find_match(original, p) is not None:
            warnings.append(f"phrase marked with different casing/typography than given: {p!r}")

    # Summary
    if not 5 <= len(summary) <= 6:
        warnings.append(f"summary has {len(summary)} points (expected 5-6)")
    for s in summary:
        if not str(s.get("link", "")).startswith("https://en.wikipedia.org/wiki/"):
            errors.append(f"summary link is not a Wikipedia URL: {s.get('link')!r}")

    # Enhancements: exactly one per phrase
    triggers = [e.get("trigger", "") for e in enhancements]
    for p in phrases:
        if p not in triggers:
            errors.append(f"no enhancement card for phrase {p!r}")
    for t in triggers:
        if t not in phrases:
            errors.append(f"enhancement trigger {t!r} is not one of the phrases")
    ids = [e.get("id", "") for e in enhancements]
    if len(set(ids)) != len(ids) or not all(re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", i) for i in ids):
        errors.append("enhancement ids must be unique kebab-case")
    for e in enhancements:
        label = e.get("trigger", "?")
        words = len(str(e.get("content", "")).split())
        if not 180 <= words <= 340:
            warnings.append(f"card {label!r}: content is {words} words (target 250-300)")
        tail = str(e.get("content", "")).strip().lower()
        last_sentence = re.split(r"(?<=[.!?])\s+", tail)[-1] if tail else ""
        if last_sentence.startswith(_FORBIDDEN_CLOSINGS):
            errors.append(f"card {label!r}: ends with a forbidden closing ({last_sentence[:40]!r}...)")
        if not str(e.get("wikipedia_url", "")).startswith("https://en.wikipedia.org/wiki/"):
            errors.append(f"card {label!r}: wikipedia_url is not a Wikipedia URL")
        if e.get("image_url") or e.get("image_caption"):
            errors.append(f"card {label!r}: image_url/image_caption must be \"\" (find_images.py fills them)")

    for w in warnings:
        print(f"  warning: {w}")
    if errors:
        for e in errors:
            print(f"  ERROR: {e}")
        sys.exit(f"{len(errors)} error(s) — fix {json_path} and re-run assemble")

    content = format_chapter(book, chapter, text, json.dumps(data), no_images=args.no_images)
    path = cp.save(book["slug"], chapter["slug"], content)
    print(f"OK saved {path}  ({len(phrases)} cards, {len(original.split())} words)")


def cmd_catalog(_args) -> None:
    config, cp = _load()
    catalog_sync.sync(config, cp)
    print("catalog.json updated")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("status", help="list chapters, source availability and completion")
    s.add_argument("--book", required=True)
    s.set_defaults(fn=cmd_status)

    w = sub.add_parser("windows", help="print the numbered annotation windows for a chapter")
    w.add_argument("--book", required=True)
    w.add_argument("--chapter", type=int, required=True)
    w.set_defaults(fn=cmd_windows)

    a = sub.add_parser("assemble", help="validate work JSON and write the chapter markdown")
    a.add_argument("--book", required=True)
    a.add_argument("--chapter", type=int, required=True)
    a.add_argument("--file", help="JSON path (default work/<book>/<chapter-slug>.json)")
    a.add_argument("--no-images", action="store_true")
    a.add_argument("--force", action="store_true")
    a.set_defaults(fn=cmd_assemble)

    c = sub.add_parser("catalog", help="sync public/catalog.json from chapters on disk")
    c.set_defaults(fn=cmd_catalog)

    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
