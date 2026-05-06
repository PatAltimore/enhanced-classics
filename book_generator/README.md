# Enhanced Classics — Book Generator

Generates chapter markdown files for the Enhanced Classics website using Azure AI Foundry.
Each chapter is produced in two passes: prose generation followed by summary and annotation
generation. Results are written directly into `public/books/` and `catalog.json` is updated
automatically.

## Prerequisites

- Python 3.11+
- Azure AI Foundry project with the following models deployed:
  - **Azure OpenAI**: `gpt-4o`, `gpt-4o-mini`
  - **Serverless (Model Catalog)**: `Meta-Llama-3.3-70B-Instruct`, `Mistral-Large-3`

## Setup

```bash
cd book_generator
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` with your Azure credentials:

```env
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com
AZURE_OPENAI_KEY=your-key

AZURE_FOUNDRY_ENDPOINT=https://your-project.eastus.models.ai.azure.com
AZURE_FOUNDRY_KEY=your-key
```

Endpoint URLs and keys are found in **Azure AI Foundry → your project → Models + endpoints**.

## Usage

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

## Adding books and chapters

Edit `config/books.yaml`. Add a new entry under `books:` or append chapters to an existing book:

```yaml
- slug: "moby-dick"
  title: "Moby-Dick"
  author: "Herman Melville"
  year: 1851
  description: >
    Captain Ahab's obsessive quest to hunt the white whale Moby Dick,
    narrated by the sailor Ishmael.
  chapters:
    - number: 1
      title: "Loomings"
      slug: "chapter-01-loomings"
```

The `slug` must match the folder name used under `public/books/`. Chapter files are written as
`public/books/{book-slug}/{chapter-slug}.md`.

## Changing the model chain

The generator tries models in priority order and falls back automatically on rate limits or
errors. To change the chain, edit `config/books.yaml`:

```yaml
models:
  primary: "gpt-4o"
  fallback:
    - "Meta-Llama-3.3-70B-Instruct"
    - "Mistral-Large-3"
    - "gpt-4o-mini"
```

To add a new model, also add it to `_ENDPOINT_MAP` in `client.py` with the correct endpoint
environment variable:

```python
"My-New-Model": ("AZURE_FOUNDRY_ENDPOINT", "AZURE_FOUNDRY_KEY"),
```

## Resilience

| Problem | Behaviour |
|---|---|
| Rate limit (429) | Exponential backoff, up to 3 retries on the same model |
| Server error (5xx) | Linear backoff, up to 3 retries |
| Model fails all retries | Falls through to the next model in the chain |
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
