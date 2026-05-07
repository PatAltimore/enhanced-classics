"""Prompt builders for the two-pass chapter generation pipeline.

Pass 1 — chapter text:   build_text_prompt()
Pass 2 — enhancements:   build_enhancements_prompt()

Messages are plain dicts (OpenAI format) so they work with both
AzureOpenAI and the OpenAI-compatible Foundry serverless clients.
"""

_TEXT_SYSTEM = """\
You are a creative writer for Enhanced Classics, an educational literature website \
that publishes original prose inspired by classic works.

Your task: write an entirely original prose chapter inspired by the themes, voice, \
and narrative of a given classic. You are NOT reproducing existing text — you are \
composing new, original writing in the spirit of the source work.

Rules:
- Write in the authentic voice, style, and period of the source author.
- Capture the events, characters, setting, and themes of the chapter faithfully \
  through your own original prose.
- Target approximately {target_words} words of body text.
- Bold 8–15 key phrases using **phrase** — choose concepts, people, places, events, \
or ideas that deserve an annotation card (historical context, scientific explanation, \
cultural significance, etc.).
- Bolded phrases must appear naturally in the text, not forced.
- Output ONLY the prose. No YAML, no headings, no preamble, no commentary.\
"""

_TEXT_USER = """\
Write an original prose piece capturing Chapter {chapter_num}: "{chapter_title}" \
from the classic "{title}" by {author} (published {year}).

About the work: {description}

Compose the chapter now in {author}'s voice. Remember to bold 8–15 annotation phrases.\
"""

_ENH_SYSTEM = """\
You are an expert literary annotator for Enhanced Classics.

Given a chapter of text, produce a JSON object with two keys:

"summary": array of 5–6 objects, each with:
  - "point":      one-sentence summary bullet
  - "link":       a real Wikipedia URL relevant to this point
  - "link_label": short display text for the link (e.g. "Walden Pond")

"enhancements": array of 8–10 objects (pick the most interesting bolded phrases), each with:
  - "id":            unique kebab-case identifier
  - "trigger":       the exact phrase as it appears in the text (no ** markers)
  - "title":         readable card title (3–6 words)
  - "wikipedia_url": real Wikipedia URL for this topic
  - "image_url":     always use "" — image URLs cannot be reliably verified at generation time
  - "image_caption": always use ""
  - "content":       100–200 word educational explanation of why this topic \
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


def build_text_prompt(book: dict, chapter: dict, config: dict) -> list[dict]:
    target_words = config.get("generation", {}).get("chapter_target_words", 2500)
    return [
        {"role": "system", "content": _TEXT_SYSTEM.format(target_words=target_words)},
        {"role": "user", "content": _TEXT_USER.format(
            chapter_num=chapter["number"],
            chapter_title=chapter["title"],
            title=book["title"],
            author=book["author"],
            year=book["year"],
            description=book.get("description", ""),
        )},
    ]


def build_enhancements_prompt(book: dict, chapter: dict, text: str) -> list[dict]:
    return [
        {"role": "system", "content": _ENH_SYSTEM},
        {"role": "user", "content": _ENH_USER.format(
            title=book["title"],
            author=book["author"],
            year=book["year"],
            chapter_num=chapter["number"],
            chapter_title=chapter["title"],
            text=text,
        )},
    ]
