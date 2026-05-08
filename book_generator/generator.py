"""Enhanced Classics — chapter generator CLI.

Usage examples:
  # Generate everything in books.yaml not yet on disk
  python generator.py

  # One specific book
  python generator.py --book walden

  # One specific chapter
  python generator.py --book walden --chapter 6

  # Preview prompts without calling any API
  python generator.py --dry-run

  # Skip catalog.json update after generation
  python generator.py --no-catalog-sync
"""
import argparse
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv
from rich.console import Console
from rich.rule import Rule

from client import ModelClient
from checkpointer import Checkpointer
from formatter import format_chapter
from prompts import build_text_prompt, build_enhancements_prompt
import catalog_sync

load_dotenv()
console = Console()

CONFIG_PATH = Path(__file__).parent / "config" / "books.yaml"


def load_config(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


MIN_PROSE_WORDS = 150


def _check_prose(text: str) -> None:
    """Raise if all models returned suspiciously little text."""
    word_count = len(text.split())
    if word_count < MIN_PROSE_WORDS:
        raise ValueError(
            f"Prose too short ({word_count} words) — all models may have refused or truncated"
        )


def generate_chapter(client: ModelClient, book: dict, chapter: dict, config: dict) -> str:
    gen_cfg = config.get("generation", {})
    temperature = gen_cfg.get("temperature", 0.7)
    max_tokens = gen_cfg.get("max_tokens", 4096)

    console.print(f"    [cyan]→ Pass 1:[/cyan] generating prose …")
    text_messages = build_text_prompt(book, chapter, config)
    text = client.complete(text_messages, temperature=temperature, max_tokens=max_tokens)
    _check_prose(text)
    console.print(f"      {len(text.split())} words generated")

    console.print(f"    [cyan]→ Pass 2:[/cyan] generating summary + enhancements …")
    enh_messages = build_enhancements_prompt(book, chapter, text)
    # Lower temperature for structured JSON output
    enhancements_raw = client.complete(enh_messages, temperature=0.2, max_tokens=4096)

    return format_chapter(book, chapter, text, enhancements_raw)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate Enhanced Classics chapter files")
    parser.add_argument("--book", metavar="SLUG", help="Only generate this book")
    parser.add_argument("--chapter", metavar="N", type=int, help="Only generate this chapter number")
    parser.add_argument("--dry-run", action="store_true", help="Build prompts but skip API calls")
    parser.add_argument("--force", action="store_true", help="Regenerate even if output file exists")
    parser.add_argument("--no-catalog-sync", action="store_true", help="Skip updating catalog.json")
    parser.add_argument("--sync-catalog", action="store_true", help="Sync catalog.json from disk and exit")
    parser.add_argument("--config", default=str(CONFIG_PATH), help="Path to books.yaml")
    args = parser.parse_args()

    config = load_config(Path(args.config))
    checkpointer = Checkpointer(
        Path(__file__).parent / config["output_dir"]
    )

    if args.sync_catalog:
        catalog_sync.sync(config, checkpointer)
        console.print("[green]catalog.json updated[/green]")
        return

    client = ModelClient(config["models"])

    books = config["books"]
    if args.book:
        books = [b for b in books if b["slug"] == args.book]
        if not books:
            console.print(f"[red]Book '{args.book}' not found in config/books.yaml[/red]")
            sys.exit(1)

    total_done = total_skipped = total_failed = 0

    for book in books:
        console.print(Rule(f"[bold]{book['title']}[/bold] — {book['author']}"))

        chapters = book["chapters"]
        if args.chapter is not None:
            chapters = [c for c in chapters if c["number"] == args.chapter]
            if not chapters:
                console.print(f"  [red]Chapter {args.chapter} not in config for this book[/red]")
                continue

        for chapter in chapters:
            label = f"Ch. {chapter['number']}: {chapter['title']}"

            if not args.force and checkpointer.is_done(book["slug"], chapter["slug"]):
                console.print(f"  [dim]✓ {label} — already exists, skipping[/dim]")
                total_skipped += 1
                continue

            console.print(f"  [bold]{label}[/bold]")

            if args.dry_run:
                msgs = build_text_prompt(book, chapter, config)
                console.print(f"    [dim][dry-run] Would send {len(msgs)} messages to model[/dim]")
                console.print(f"    [dim]System: {msgs[0]['content'][:120]}…[/dim]")
                total_done += 1
                continue

            try:
                content = generate_chapter(client, book, chapter, config)
                path = checkpointer.save(book["slug"], chapter["slug"], content)
                console.print(f"    [green]✓ Saved → {path}[/green]")
                total_done += 1
            except Exception as exc:
                console.print(f"    [red]✗ Failed: {exc}[/red]")
                total_failed += 1

    console.print(Rule())
    console.print(
        f"Done — [green]{total_done} generated[/green], "
        f"[dim]{total_skipped} skipped[/dim], "
        f"[red]{total_failed} failed[/red]"
    )

    if not args.dry_run and not args.no_catalog_sync and total_done > 0:
        console.print("Syncing catalog.json …")
        catalog_sync.sync(config, checkpointer)
        console.print("[green]catalog.json updated[/green]")


if __name__ == "__main__":
    main()
