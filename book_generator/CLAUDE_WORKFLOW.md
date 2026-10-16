# Adding a book with Claude Code (no API keys)

Claude Code does the annotation work itself. Deterministic steps stay in scripts.
Trigger it with `/add-book <gutenberg url>` or just ask Claude to add a book.

## Division of labour

| Step | Who | Command |
|---|---|---|
| Create the `books.yaml` entry | script | `python add_book.py <gutenberg url>` |
| Download + split source text | script | `python fetch_texts.py --book <slug> [--list]` |
| Slice a chapter into annotation windows | script | `python cc_chapter.py windows --book <slug> --chapter N` |
| Pick phrases, write summary + cards | **Claude** | writes `work/<slug>/<chapter-slug>.json` |
| Validate, inject `**markers**`, write markdown | script | `python cc_chapter.py assemble --book <slug> --chapter N` |
| Wikimedia images | script | `python find_images.py --book <slug>` |
| Confirm body text == source text | script | `python verify_chapters.py --book <slug>` |
| Update `public/catalog.json` | script | `python cc_chapter.py catalog` |

`cc_chapter.py status --book <slug>` shows which chapters are pending.

## Steps for Claude

1. **Setup.** Run `add_book.py` (use `--dry-run` first), review the entry — especially
   `gutenberg_re`, chapter titles and slugs — then `fetch_texts.py --book <slug> --list`
   and fix the split in `config/books.yaml` until it is right. Then fetch for real.
   Stop and ask the user if the chapter split looks wrong or the book is not public domain.
2. **Per chapter**, run `cc_chapter.py windows`, then write the JSON (schema below)
   to `work/<book>/<chapter-slug>.json`, then run `cc_chapter.py assemble`. Fix whatever it
   reports and re-run until it prints `OK saved`.
3. **Finish.** `find_images.py --book <slug>`, `verify_chapters.py --book <slug>`,
   `cc_chapter.py catalog`. Report any chapters that failed. Do not commit unless asked.

Chapters are independent, so several can be done in parallel (e.g. one subagent per
chapter, a handful at a time). Subagents write their own JSON and run `assemble`;
run `catalog` once at the end, from the main session.

## JSON schema

```json
{
  "phrases": ["verbatim phrase from window 1", "verbatim phrase from window 2", "..."],
  "summary": [
    {"point": "One-sentence bullet", "link": "https://en.wikipedia.org/wiki/...", "link_label": "Short label"}
  ],
  "enhancements": [
    {
      "id": "unique-kebab-case",
      "trigger": "must equal one entry in phrases, character for character",
      "title": "Curiosity-driven title, 6-10 words",
      "wikipedia_url": "https://en.wikipedia.org/wiki/...",
      "image_url": "",
      "image_caption": "",
      "content": "~100 word card"
    }
  ]
}
```

Rules (enforced by `assemble`, which refuses to write on any ERROR):

- **phrases**: exactly one per window, in window order, a verbatim substring of *that*
  window (copy character-for-character, keep curly quotes/accents as they appear), preferably
  1-5 words, specific rather than generic ("Walden Pond", not "the house"). Windows are about
  250 words each (`cc_chapter.py windows` prints the count), so a 1,100-word chapter gets 3-4 cards.
- **summary**: 5-6 points, each with a real Wikipedia link.
- **enhancements**: exactly one card per phrase, no extras; `trigger` equals the phrase.
  `image_url` and `image_caption` stay `""` — `find_images.py` fills them.
- **Card style**: the book text lives in the body; cards are short explainers anchored on a
  Wikipedia topic. Keep each to **about 100 words** (70-140; the existing books average ~100).
  Anchor to the exact moment in the chapter in one sentence, add context the reader likely does
  not know (history, myth, science, an irony), and end on a concrete point rather than a summary.
  Check `public/books/odyssey` or `walden` for the tone. Titles are curiosity-driven, 6-10 words
  (see `_ENH_SYSTEM` in `prompts.py`). Never end with "This underscores / highlights / reflects /
  reinforces / aligns with / exemplifies...". Do not quote the passage at length.
- **Density check**: other books run at a card:body word ratio of ~0.2-0.45. If a chapter's cards
  outweigh its text, there are too many or they are too long.
- Only use Wikipedia URLs you are confident exist.

The chapter text itself is never rewritten: `assemble` takes the body straight from
`source_texts/` and only adds `**markers**`, so `verify_chapters.py` will pass.
