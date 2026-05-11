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
import io
import re
import sys
import unicodedata
from pathlib import Path

import yaml
from dotenv import load_dotenv
from rich.console import Console
from rich.rule import Rule

# Force UTF-8 output on Windows so Rich box-drawing characters don't crash
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from client import ModelClient
from checkpointer import Checkpointer
from formatter import format_chapter
from prompts import (
    build_text_prompt, build_enhancements_prompt,
    build_phrase_prompt, make_windows, build_single_window_retry_prompt,
)
import catalog_sync

load_dotenv()
console = Console(legacy_windows=False)

CONFIG_PATH  = Path(__file__).parent / "config" / "books.yaml"
TEXTS_ROOT   = Path(__file__).parent / "source_texts"


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


# Typography normalisation: curly quotes → straight, dashes → hyphen, ligatures → plain.
# Must remain 1-to-1 (each codepoint → exactly one char) so that translated indices
# stay aligned with the original string — _find_match relies on this property.
_TYPO_NORM = str.maketrans({
    0x2018: "'", 0x2019: "'",
    0x201C: '"', 0x201D: '"',
    0x2013: "-", 0x2014: "-",
    0x200A: " ",        # hair space → regular space
    0x2026: ".",        # ellipsis → period (single char, keeps 1-to-1)
    0x00E6: "e", 0x0153: "e",   # ligatures æ, œ
    0x0152: "O",        # Œ uppercase
})


def _accent_strip_with_map(s: str) -> "tuple[str, list[int]]":
    """NFD-decompose s, drop combining marks, return (stripped, orig_pos_map).

    orig_pos_map[i] gives the index in s that produced stripped[i].
    Since accented chars decompose to base+combining, and we drop the combining
    char, the resulting string may be shorter than s — hence the explicit map.
    """
    result: list[str] = []
    pos_map: list[int] = []
    for i, c in enumerate(s):
        for ch in unicodedata.normalize("NFD", c):
            if unicodedata.category(ch) != "Mn":   # keep non-combining chars
                result.append(ch)
                pos_map.append(i)
    return "".join(result), pos_map


def _norm(s: str) -> str:
    return s.translate(_TYPO_NORM)


def _find_match(text: str, phrase: str) -> "tuple[int, int] | None":
    """Return (start, end) of the first occurrence of phrase not inside **...** spans.

    Three passes in order:
      1. Exact match
      2. Typography-normalised match (curly quotes → straight, etc.)
      3. Flexible-whitespace regex (handles phrases split across line breaks)
    """
    def _outside(idx: int) -> bool:
        return text[:idx].count("**") % 2 == 0

    # Pass 1 — exact
    pos = 0
    while pos < len(text):
        idx = text.find(phrase, pos)
        if idx == -1:
            break
        if _outside(idx):
            return idx, idx + len(phrase)
        pos = idx + 1

    # Pass 2 — typography-normalised (1-to-1 char map keeps indices aligned)
    # Always search norm_text: the text may have curly quotes/em dashes even
    # when the model's phrase has straight equivalents (norm_phrase == phrase).
    norm_text = _norm(text)
    norm_phrase = _norm(phrase)
    pos = 0
    while pos < len(norm_text):
        idx = norm_text.find(norm_phrase, pos)
        if idx == -1:
            break
        if _outside(idx):
            return idx, idx + len(norm_phrase)
        pos = idx + 1

    # Pass 3 — flexible whitespace (handles line-break splits)
    words = phrase.split()
    if len(words) > 1:
        pattern = re.compile(r'\s+'.join(re.escape(w) for w in words))
        for m in pattern.finditer(text):
            if _outside(m.start()):
                return m.start(), m.end()

    # Pass 4 — accent-normalised match (é→e, â→a, Æ→A, etc.)
    # Uses NFD decomposition so it handles any accented Latin character.
    stripped_text, text_map = _accent_strip_with_map(text)
    stripped_phrase, _ = _accent_strip_with_map(phrase)
    if stripped_text != text or stripped_phrase != phrase:
        pos = 0
        while pos < len(stripped_text):
            idx = stripped_text.find(stripped_phrase, pos)
            if idx == -1:
                break
            end_idx = idx + len(stripped_phrase) - 1
            if end_idx < len(text_map):
                orig_start = text_map[idx]
                orig_end = text_map[end_idx] + 1
                if _outside(orig_start):
                    return orig_start, orig_end
            pos = idx + 1

    return None


def _first_outside_markers(text: str, phrase: str) -> int:
    """Return the index of the first occurrence of phrase not inside **...** spans.

    Counts ** tokens before each candidate position: an odd count means we're
    inside an existing marker and should skip that occurrence.
    """
    pos = 0
    while pos < len(text):
        idx = text.find(phrase, pos)
        if idx == -1:
            return -1
        if text[:idx].count("**") % 2 == 0:
            return idx
        pos = idx + 1
    return -1


def _inject_markers(text: str, phrases: list[str]) -> str:
    """Wrap the first occurrence of each phrase in **…** markers.

    Phrases are processed longest-first to avoid wrapping a substring that is
    already part of a longer phrase.  Uses _find_match for three-pass lookup
    (exact, typography-normalised, flexible-whitespace).
    """
    failed = []
    for phrase in sorted(phrases, key=len, reverse=True):
        marker = f"**{phrase}**"
        if marker in text:
            continue   # exact marker already present
        match = _find_match(text, phrase)
        if match is None:
            failed.append(phrase)
            continue
        start, end = match
        original_span = text[start:end]
        text = text[:start] + f"**{original_span}**" + text[end:]
    if failed:
        console.print(
            f"    [yellow]Phrase injection failed for {len(failed)}: {failed}[/yellow]"
        )
    return text


def _source_text_path(book: dict, chapter: dict) -> Path:
    return TEXTS_ROOT / book["slug"] / f"{chapter['slug']}.txt"


def generate_chapter(client: ModelClient, book: dict, chapter: dict, config: dict) -> str:
    import json as _json

    gen_cfg     = config.get("generation", {})
    temperature = gen_cfg.get("temperature", 0.7)
    max_tokens  = gen_cfg.get("max_tokens", 8192)

    src_path = _source_text_path(book, chapter)

    if src_path.exists():
        # ── Source-text mode ─────────────────────────────────────────────────
        original_text = src_path.read_text(encoding="utf-8").strip()
        console.print(
            f"    [green]OK Source text loaded[/green] "
            f"({len(original_text.split())} words from {src_path.name})"
        )

        console.print(f"    [cyan]Pass 1:[/cyan] identifying annotation phrases ...")
        phrase_messages = build_phrase_prompt(book, chapter, original_text)
        phrases_raw     = client.complete(phrase_messages, temperature=0.1, max_tokens=1024)

        try:
            phrases_raw_clean = phrases_raw.strip()
            phrases_raw_clean = phrases_raw_clean.lstrip("```json").lstrip("```").rstrip("```").strip()
            phrases = _json.loads(phrases_raw_clean)
            if not isinstance(phrases, list):
                raise ValueError("Expected a JSON array")
        except Exception as exc:
            console.print(f"    [yellow]Phrase parse failed ({exc}); using text as-is[/yellow]")
            phrases = []

        # Pre-verify each phrase against its source window before injection.
        # Hallucinated phrases (not found in their window) are retried immediately.
        windows = make_windows(original_text)
        n_windows = len(windows)
        verified: list[str] = []
        for i, phrase in enumerate(phrases[:n_windows]):
            window = windows[i]
            if _find_match(window, phrase) is not None:
                verified.append(phrase)
            else:
                console.print(
                    f"      [dim]Window {i + 1}: {repr(phrase)} not in window — retrying...[/dim]"
                )
                retry_msgs = build_single_window_retry_prompt(
                    book, chapter, i + 1, n_windows, window
                )
                try:
                    retry_raw = client.complete(retry_msgs, temperature=0.3, max_tokens=128)
                    retry_clean = retry_raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip().strip('"\'')
                    if _find_match(window, retry_clean) is not None:
                        verified.append(retry_clean)
                        console.print(f"      [green]Window {i + 1}: retry -> {repr(retry_clean)}[/green]")
                    else:
                        console.print(f"      [yellow]Window {i + 1}: retry also failed, skipping[/yellow]")
                except Exception as exc:
                    console.print(f"      [yellow]Window {i + 1}: retry error ({exc}), skipping[/yellow]")

        text = _inject_markers(original_text, verified)
        marked = sum(1 for p in verified if f"**{p}**" in text)
        console.print(f"      {marked}/{len(verified)} phrases marked in text")

    else:
        # ── AI prose mode (fallback) ──────────────────────────────────────────
        console.print(f"    [dim]No source text — generating AI prose[/dim]")
        console.print(f"    [cyan]Pass 1:[/cyan] generating prose ...")
        text_messages = build_text_prompt(book, chapter, config)
        text = client.complete(text_messages, temperature=temperature, max_tokens=max_tokens)
        _check_prose(text)
        console.print(f"      {len(text.split())} words generated")

    console.print(f"    [cyan]Pass 2:[/cyan] generating summary + enhancements ...")
    enh_messages     = build_enhancements_prompt(book, chapter, text)
    enhancements_raw = client.complete(enh_messages, temperature=0.2, max_tokens=8192)

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
                console.print(f"  [dim]-- {label} -- already exists, skipping[/dim]")
                total_skipped += 1
                continue

            console.print(f"  [bold]{label}[/bold]")

            if args.dry_run:
                msgs = build_text_prompt(book, chapter, config)
                console.print(f"    [dim][dry-run] Would send {len(msgs)} messages to model[/dim]")
                console.print(f"    [dim]System: {msgs[0]['content'][:120]}...[/dim]")
                total_done += 1
                continue

            try:
                content = generate_chapter(client, book, chapter, config)
                path = checkpointer.save(book["slug"], chapter["slug"], content)
                console.print(f"    [green]OK Saved -> {path}[/green]")
                total_done += 1
            except Exception as exc:
                console.print(f"    [red]FAILED: {exc}[/red]")
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
