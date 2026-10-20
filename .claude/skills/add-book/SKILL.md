---
name: add-book
description: Add a new book to Enhanced Classics using Claude itself to write the annotation phrases, summaries and enhancement cards (no Azure/Foundry). Use when the user asks to add a book, given a Project Gutenberg URL or title.
---

Read `book_generator/CLAUDE_WORKFLOW.md` and follow it exactly, working from the
`book_generator/` directory. The argument is a Project Gutenberg ebook URL (or a title to
look up); if it is missing or ambiguous, ask for it.

Summary: `add_book.py` -> review/fix `config/books.yaml` -> `fetch_texts.py` -> for each chapter
`cc_chapter.py windows` -> write `work/<book>/<chapter-slug>.json` -> `cc_chapter.py assemble` ->
`find_images.py` -> review the images (`review_images.py sheet`, look at the contact sheets in the
browser, `review_images.py remove --ids ...` for any that do not match their Wikipedia topic) -> `verify_chapters.py` -> `cc_chapter.py catalog` -> invoke the `add-characters`
skill (Skill tool, argument: the book slug) to add the book's Characters page. Do not commit unless asked.
