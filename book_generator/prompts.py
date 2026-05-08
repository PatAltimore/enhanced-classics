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
- Write AT LEAST {target_words} words. Do not summarise, truncate, or end early — \
  write out every scene, reflection, and detail in full.
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

"enhancements": array of 16–24 objects — include ALL bolded phrases distributed across the full chapter — each with:
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


_PHRASES_SYSTEM = """\
You are a literary annotator for Enhanced Classics.

Given the original text of a classic chapter divided into numbered sections, identify
annotation phrase candidates — concepts, people, places, events, or scientific/historical
ideas that a modern reader would benefit from understanding more deeply.

Rules:
- Each phrase must be a verbatim substring of the provided text — copy it character-for-character.
- You MUST contribute 4–6 phrases from EACH numbered section — spread your selections evenly \
  across all sections, do not cluster them in the first section.
- Prefer short, specific phrases (1–5 words) over long ones.
- Avoid phrases that are too generic (e.g. "he said" or "the house").
- Return ONLY a JSON array of the exact phrases, e.g.:
  ["Walden Pond", "transcendentalism", "bean-field"]
- No markdown fences, no commentary, no keys — just the bare JSON array.\
"""

_PHRASES_USER = """\
Book: "{title}" by {author} ({year})
Chapter {chapter_num}: {chapter_title}

The chapter has been divided into {n_sections} equal sections. \
Return 2–3 verbatim annotation phrases from EACH section ({total_min}–{total_max} total).

{sections_text}

Return the JSON array of {total_min}–{total_max} annotation phrases, \
with at least 2 from each of the {n_sections} sections.\
"""


def _split_text(text: str, n: int) -> list[str]:
    """Split text into n roughly equal sections, breaking at paragraph boundaries."""
    total = len(text)
    target = total // n
    sections = []
    pos = 0
    for i in range(n - 1):
        ideal = pos + target
        margin = total // (n * 4)
        lo = max(pos + 1, ideal - margin)
        hi = min(total, ideal + margin)
        chunk = text[lo:hi]
        para = chunk.rfind('\n\n')
        if para != -1:
            split = lo + para
        else:
            sp = text.rfind(' ', lo, hi)
            split = sp if sp != -1 else ideal
        sections.append(text[pos:split].strip())
        pos = split
    sections.append(text[pos:].strip())
    return sections


def build_phrase_prompt(book: dict, chapter: dict, text: str) -> list[dict]:
    """Pass 1 (source-text mode): identify annotation trigger phrases in the original text."""
    word_count = len(text.split())
    if word_count < 1000:
        n_sections = 3
    elif word_count < 2000:
        n_sections = 4
    else:
        n_sections = 5

    sections = _split_text(text, n_sections)
    sections_text = "\n\n".join(
        f"[SECTION {i + 1} of {n_sections}]\n{sec}"
        for i, sec in enumerate(sections)
    )
    total_min = n_sections * 4
    total_max = n_sections * 6

    return [
        {"role": "system", "content": _PHRASES_SYSTEM},
        {"role": "user", "content": _PHRASES_USER.format(
            title=book["title"],
            author=book["author"],
            year=book["year"],
            chapter_num=chapter["number"],
            chapter_title=chapter["title"],
            n_sections=n_sections,
            total_min=total_min,
            total_max=total_max,
            sections_text=sections_text,
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
