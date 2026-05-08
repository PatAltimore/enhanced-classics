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
  - "title":         captivating, curiosity-driven title (6–10 words) that makes a reader \
want to open the card — use intrigue, surprise, or a compelling question. \
Avoid dry encyclopedic labels. \
Examples of GOOD titles: "The Pond That Quietly Changed American Literature", \
"Why Priests Voluntarily Sat Between Four Fires", \
"The Book Adam Smith Never Expected to Matter This Much", \
"What Thoreau Got Wrong About Money (And Right About Everything Else)". \
Examples of BAD titles: "Walden Pond's Historical Significance", "Brahmin Ascetic Practices".
  - "wikipedia_url": real Wikipedia URL for this topic
  - "image_url":     always use "" — image URLs cannot be reliably verified at generation time
  - "image_caption": always use ""
  - "content":       200–300 word documentary-style narrative structured in three beats: \
BEAT 1 — Open by anchoring to the exact moment in this chapter. Quote or closely \
paraphrase the specific line. Do NOT open with a definition or "X is a Y." \
BEAT 2 — Deliver context the reader almost certainly does not know: a surprising \
historical fact, a scientific explanation, a cultural detail, or an irony. This beat \
should make the reader think "I had no idea." \
BEAT 3 — Close by returning to the book. Show what this context reveals about the \
author's intent, the chapter's deeper meaning, or the work's themes. \
Write in the style of a great documentary narrator — vivid, specific, and building \
toward insight. Every sentence must earn its place. Aim for 250–300 words. \
FORBIDDEN closings — never end a card with any of these phrases: \
"This underscores...", "This highlights...", "This reflects...", "This reinforces...", \
"This aligns with...", "This exemplifies...". These are clichés that kill the \
narrative. End instead with a concrete implication, a provocative observation, or \
a final image that lingers. \
EXAMPLE (Benvenuto Cellini, Walden Ch.10): \
"When Thoreau stands in the arch of a rainbow and notices a faint halo encircling his \
own shadow, he reaches for the most audacious comparison he can think of: Benvenuto \
Cellini. Cellini was the 16th-century Florentine goldsmith who gave the world some of \
the Renaissance's most dazzling metalwork — and one of history's most outrageously \
self-aggrandizing memoirs. While imprisoned in Castel Sant'Angelo on charges of robbery, \
he claimed a radiant aureole appeared around his shadow every morning at sunrise — proof, \
he declared, of divine election. Modern optics has a name for what Cellini saw: a Brocken \
spectre, a magnified shadow projected onto mist with a halo of diffracted light around it. \
It is real, rare, and genuinely awe-inspiring. Thoreau almost certainly knew this. His \
comparison is not random; it is a philosophical argument. The same transcendent \
experiences that Renaissance artists located in courts and cathedrals, Thoreau finds \
beside a Massachusetts pond. Nature, he is saying, is the only studio that matters." \
EXAMPLE (pickerel-weed, Walden Ch.10): \
"Standing in the shallows, water up to his middle, casting over the pickerel-weed to \
reach the fish below, Thoreau is doing something more deliberate than it looks. \
Pickerelweed — Pontederia cordata — is one of the most recognizable aquatic plants in \
New England, its purple flower spikes rising above slow water all summer. It takes its \
common name from the pickerel fish that shelter beneath it, and Indigenous peoples used \
its seeds as grain and its leaves as greens. It is, in other words, a food system hiding \
in plain sight — an ecosystem of interdependence that the casual fisherman walks right \
past. Thoreau sees it. To him, the plant, the fish, and the man are all threads in the \
same net, and the act of standing waist-deep in cold water is not deprivation but \
participation. This is the argument of the entire chapter in miniature: the life \
everyone else calls poor, Thoreau experiences as abundance."

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
