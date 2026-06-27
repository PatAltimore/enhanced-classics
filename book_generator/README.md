# Enhanced Classics — Book Generator

Generates chapter markdown files for the Enhanced Classics website using Azure AI Foundry.

Each chapter is produced using **original public-domain text** from Project Gutenberg when
available, or AI-generated prose as a fallback. The pipeline:

1. **`fetch_texts.py`** — downloads the Gutenberg text for each book, splits it into
   per-chapter files under `source_texts/`, and stores them locally.
2. **`generator.py`** — for each chapter that has a source text file, asks the AI to identify
   8–15 annotation phrases (exact substrings), injects `**markers**` programmatically, then
   generates summary + enhancement cards. Falls back to AI prose if no source file exists.
3. **`find_images.py`** — fetches Wikimedia images for enhancement cards.
4. **`verify_chapters.py`** — confirms each generated markdown body matches its source text.

Results are written to `public/books/` and `catalog.json` is updated automatically.

## Prerequisites

- Python 3.11+
- Azure AI Foundry project with the following models deployed:
  - **Azure OpenAI**: `gpt-4o`
  - **Serverless (Model Catalog)**: `Llama-3.3-70B-Instruct`, `Mistral-Large-3`, `Phi-4`

## Setup

```bash
cd book_generator
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` with your Azure credentials:

```env
# Azure OpenAI resource (gpt-4o)
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com
AZURE_OPENAI_KEY=your-key

# Azure AI Foundry unified endpoint — all three serverless models share this URL
AZURE_LLAMA_ENDPOINT=https://your-project.services.ai.azure.com/models/chat/completions?api-version=2024-05-01-preview
AZURE_LLAMA_KEY=your-foundry-project-key

AZURE_MISTRAL_ENDPOINT=https://your-project.services.ai.azure.com/models/chat/completions?api-version=2024-05-01-preview
AZURE_MISTRAL_KEY=your-foundry-project-key

AZURE_PHI4_ENDPOINT=https://your-project.services.ai.azure.com/models/chat/completions?api-version=2024-05-01-preview
AZURE_PHI4_KEY=your-foundry-project-key
```

Endpoint URLs and keys are found in **Azure AI Foundry → your project → Models + endpoints**.
The `AZURE_OPENAI_KEY` comes from the Azure OpenAI resource; the Foundry keys come from the
Foundry project (**Settings → API keys**) — these are different values.

## Usage

### Recommended workflow for original text

> **The book must exist in `config/books.yaml` before you fetch anything.**
> `fetch_texts.py` looks the book up by `--book <slug>` and reads its `gutenberg_id`
> and split settings from that file — it will skip a slug that isn't there. Add the
> entry first (see [Adding books and chapters](#adding-books-and-chapters)), either
> with `add_book.py` or by editing the YAML by hand.

```bash
# 1. Add the book to config/books.yaml (auto-detects chapters from a Gutenberg URL)
python add_book.py https://www.gutenberg.org/ebooks/205   # creates the "walden" entry

# 2. Preview how the Gutenberg text will be split into chapters (no files written)
python fetch_texts.py --book walden --list

# 3. Download and split the text into source_texts/walden/*.txt
python fetch_texts.py --book walden

# 4. Generate (or regenerate) chapters using the original text
python generator.py --book walden --force

# 5. Verify every chapter body matches its source text
python verify_chapters.py --book walden
```

If the `--list` output shows incorrect splits or missing chapters, adjust
`gutenberg_heading_lines` or add `gutenberg_n` per chapter in `config/books.yaml`,
then re-run `fetch_texts.py`.

### generator.py

```bash
# Generate all chapters not yet on disk
python generator.py

# One book
python generator.py --book walden

# One chapter
python generator.py --book walden --chapter 6

# Preview prompts without calling any API
python generator.py --dry-run

# Regenerate a chapter (overwrite existing file)
python generator.py --book walden --chapter 6 --force

# Generate without updating catalog.json
python generator.py --no-catalog-sync
```

### find_images.py

```bash
# Fetch Wikimedia images for all enhancement cards that have no image
python find_images.py

# One book only
python find_images.py --book walden

# Preview without writing
python find_images.py --dry-run
```

### verify_chapters.py

```bash
# Check all books
python verify_chapters.py

# One book
python verify_chapters.py --book walden
```

Chapters reported as `mismatch` need to be regenerated with `--force`.

## Adding books and chapters

**Add the book here before running `fetch_texts.py` or `generator.py`** — both look the
book up by slug in `config/books.yaml`, so a book that isn't listed can't be fetched or
generated.

### Option A — `add_book.py` (recommended)

Pass a Project Gutenberg ebook URL. The script fetches the metadata, downloads the text,
auto-detects the chapter heading pattern, and appends a ready-to-use entry to
`config/books.yaml`:

```bash
python add_book.py https://www.gutenberg.org/ebooks/2701            # append the entry
python add_book.py https://www.gutenberg.org/ebooks/2701 --dry-run  # print without writing
python add_book.py https://www.gutenberg.org/ebooks/2701 --no-append # print entry to copy manually
```

Review the generated entry (especially `gutenberg_re` and the chapter list), then continue
with `fetch_texts.py --book <slug> --list`.

### Option B — edit `config/books.yaml` by hand

Add a new entry under `books:` with a Gutenberg ID and chapter split pattern so
`fetch_texts.py` can download the original text automatically:

```yaml
- slug: "moby-dick"
  title: "Moby-Dick"
  author: "Herman Melville"
  year: 1851
  gutenberg_id: 2701
  gutenberg_re: '^CHAPTER \d+'      # regex that matches each chapter heading line
  gutenberg_heading_lines: 2        # lines to skip at the top of each section (the heading itself)
  description: >
    Captain Ahab's obsessive quest to hunt the white whale Moby Dick,
    narrated by the sailor Ishmael.
  chapters:
    - number: 1
      title: "Loomings"
      slug: "chapter-01-loomings"
      # gutenberg_n: 1   # optional — set when books.yaml chapter N ≠ Gutenberg chapter N
```

The `slug` must match the folder name used under `public/books/`. Chapter files are written as
`public/books/{book-slug}/{chapter-slug}.md`.

**`gutenberg_n`** is only needed when the chapter numbers in `books.yaml` don't match the
ordinal position of chapters in the Gutenberg text (e.g. Hamlet, where books.yaml "chapters"
are thematic groupings of Acts).

Run `python fetch_texts.py --book moby-dick --list` to verify the regex finds the right
sections before writing any files.

## Changing the model chain

The generator tries models in priority order and falls back automatically on rate limits or
errors. To change the chain, edit `config/books.yaml`:

```yaml
models:
  primary: "gpt-4o"
  fallback:
    - "Phi-4"
    - "Llama-3.3-70B-Instruct"
    - "Mistral-Large-3"
```

To add a new model, also add it to `_MODEL_CONFIGS` in `client.py` with the endpoint kind
and environment variables:

```python
"My-New-Model": ("foundry", "AZURE_MYMODEL_ENDPOINT", "AZURE_MYMODEL_KEY"),
```

## Resilience

| Problem | Behaviour |
|---|---|
| Rate limit (429) | Exponential backoff, up to 3 retries on the same model |
| Server error (5xx) | Linear backoff, up to 3 retries |
| Model fails all retries | Falls through to the next model in the chain |
| Content filter (400) | Chain aborted immediately — other models will reject the same prompt |
| Script interrupted | Already-written `.md` files are skipped on restart |
| Bad JSON from enhancements pass | Strips markdown fences, falls back to regex extraction |

## Output format

Each generated file is a markdown document with YAML frontmatter:

```
---
title: "Walden"
author: "Henry David Thoreau"
year: 1854
chapter: 6
chapter_title: "Visitors"
slug: "chapter-06-visitors"
book_slug: "walden"
license: "public-domain"
summary:
  - point: "..."
    link: "https://en.wikipedia.org/wiki/..."
    link_label: "..."
enhancements:
  - id: "unique-id"
    trigger: "phrase bolded in text"
    title: "Card Title"
    wikipedia_url: "..."
    image_url: "..."
    image_caption: "..."
    content: "200–400 word explanation"
---
Chapter prose text with **bolded annotation triggers** throughout...
```

## File structure

```
book_generator/
├── .env                  # your credentials (gitignored)
├── .env.example          # template
├── requirements.txt
├── config/
│   └── books.yaml        # books, chapters, model chain, generation settings
├── generator.py          # CLI entry point
├── client.py             # model fallback + retry logic
├── prompts.py            # prompt builders (text pass + enhancements pass)
├── formatter.py          # assembles YAML frontmatter + markdown output
├── checkpointer.py       # skips already-generated chapters
└── catalog_sync.py       # updates public/catalog.json after generation
```
