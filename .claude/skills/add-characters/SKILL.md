---
name: add-characters
description: Add a Characters page (important characters, each with a summary and a short analysis of their role) to a book already in Enhanced Classics. Use when the user asks for a character summary/characters page for a book.
---

The argument is a book slug (a folder in `public/books/`) or a title. If missing or ambiguous,
ask. The book must already exist in `public/catalog.json`.

## What the page is

`public/books/<book-slug>/characters.md` is rendered by the app at `#/<book-slug>/characters`.
A "★ Characters" row appears at the top of the book's chapter list when the book's catalog
entry has `"characters": true`. (The app code, CSS and service worker already support this;
do not change them for a new book.)

## Steps

1. Read enough of the book to be accurate: the chapter summaries in each
   `public/books/<book-slug>/chapter-*.md` frontmatter (`summary:` list) plus the body text for
   anything you are unsure of. Never write from memory alone; check names, relationships
   and plot events against the text.
2. Choose the important characters: roughly 8–14 for a novel, fewer for a short work. Include
   the narrator and anyone whose actions drive the plot or theme. Order by importance
   (protagonist first), not by first appearance.
3. Write `public/books/<book-slug>/characters.md` in exactly this shape:

   ```
   ---
   title: "<Book title>"
   author: "<Author>"
   year: <year>
   book_slug: "<book-slug>"
   license: "public-domain"

   characters:
     - name: "<Name>"
       role: "<Short label: who they are, e.g. Narrator; Daisy's cousin>"
       summary: "<2–4 sentences: who they are and what they do across the plot>"
       analysis: "<2–3 sentences: their role in the book — theme, symbol, foil, narrative function>"
   ---
   ```

   Rules (the app's YAML reader is minimal):
   - Every value is ONE line in double quotes. No multi-line values, no block scalars.
   - Do not use double quotes inside a value; use single quotes, e.g. 'The Rise of ...'.
   - Do not end a value with a quote character (the reader strips edge quotes).
   - Each character has exactly the four keys `name`, `role`, `summary`, `analysis`, indented
     as above (`  - name:` then `    role:` etc.).
   - No body text after the closing `---`.
   - The page assumes the reader knows the book, so spoilers are fine. Keep each
     summary to about 50–80 words and each analysis to about 35–60 words.
4. Set `"characters": true` on the book's entry in `public/catalog.json`, after `"year"`.
   `cc_chapter.py catalog` / `catalog_sync.py` do not remove it.
5. Verify: serve `public/` (e.g. `python -m http.server <port>` from `public/`, on a port not
   used before so a stale service worker does not interfere), open `#/<book-slug>`, confirm
   the Characters row is first, open it, and check that every character renders with all
   fields and that there are no console errors. Stop the server afterwards.
6. Do not commit unless asked.

## Quality bar

- Facts match the text; no invented events. If an interpretation is debatable, say "can be
  read as" rather than stating it as fact.
- The analysis explains why the character matters to the book's themes, not a retelling of
  the plot (the summary does that).
- Original wording; short quotes only where a phrase is the point.
