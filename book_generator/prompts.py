"""Prompt builders for the two-pass chapter generation pipeline.

Pass 1 — chapter text:   build_text_prompt()
Pass 2 — enhancements:   build_enhancements_prompt()

The enhancements pass returns JSON; the formatter assembles the final markdown.
"""
from azure.ai.inference.models import SystemMessage, UserMessage

# ---------------------------------------------------------------------------
# Pass 1: chapter prose
# ---------------------------------------------------------------------------

_TEXT_SYSTEM = """\
You are a literary editor for Enhanced Classics, a website that presents public-domain \
literature with educational annotations.

Your task is to write one chapter of prose. Rules:
- Faithfully reproduce the substance and style of the original public-domain work.
- Target approximately {target_words} words of body text.
- Bold 8–15 key phrases using **phrase** — choose concepts, people, places, events, \
or ideas that deserve an annotation card (historical context, scientific explanation, \
cultural significance, etc.).
- Bolded phrases must appear naturally in the text, not forced.
- Output ONLY the prose. No YAML, no headings, no preamble, no commentary.\
"""

_TEXT_USER = """\
Write Chapter {chapter_num}: "{chapter_title}" from \
"{title}" by {author} ({year}).

{description}

Write the chapter now. Remember to bold 8–15 annotation phrases.\
"""


def build_text_prompt(book: dict, chapter: dict, config: dict) -> list:
    target_words = config.get("generation", {}).get("chapter_target_words", 2500)
    system = _TEXT_SYSTEM.format(target_words=target_words)
    user = _TEXT_USER.format(
        chapter_num=chapter["number"],
        chapter_title=chapter["title"],
        title=book["title"],
        author=book["author"],
        year=book["year"],
        description=book.get("description", ""),
    )
    return [SystemMessage(content=system), UserMessage(content=user)]


# ---------------------------------------------------------------------------
# Pass 2: summary + enhancements JSON
# ---------------------------------------------------------------------------

_ENH_SYSTEM = """\
You are an expert literary annotator for Enhanced Classics.

Given a chapter of text, produce a JSON object with two keys:

"summary": array of 5–6 objects, each with:
  - "point":      one-sentence summary bullet
  - "link":       a real Wikipedia URL relevant to this point
  - "link_label": short display text for the link (e.g. "Walden Pond")

"enhancements": array of one object per bolded phrase, each with:
  - "id":            unique kebab-case identifier
  - "trigger":       the exact phrase as it appears in the text (no ** markers)
  - "title":         readable card title (3–6 words)
  - "wikipedia_url": real Wikipedia URL for this topic
  - "image_url":     Wikimedia Commons image URL, or "" if unsure
  - "image_caption": brief credit/caption, or ""
  - "content":       200–400 word educational explanation of why this topic \
matters — its history, significance, and connection to the chapter

Respond ONLY with the raw JSON object. No markdown fences, no commentary.\
"""

_ENH_USER = """\
Book: "{title}" by {author} ({year})
Chapter {chapter_num}: {chapter_title}

--- CHAPTER TEXT ---
{text}
--- END ---

Generate the JSON with summary and enhancements for every bolded phrase.\
"""


def build_enhancements_prompt(book: dict, chapter: dict, text: str) -> list:
    user = _ENH_USER.format(
        title=book["title"],
        author=book["author"],
        year=book["year"],
        chapter_num=chapter["number"],
        chapter_title=chapter["title"],
        text=text,
    )
    return [SystemMessage(content=_ENH_SYSTEM), UserMessage(content=user)]
