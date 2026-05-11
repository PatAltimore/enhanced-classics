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

"enhancements": array with ONE object per bolded phrase — include ALL of them (typically 6–25 depending on chapter length) — each with:
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

The chapter text has been divided into small, equal-sized windows. Your job is to pick
EXACTLY ONE annotation phrase per window — a concept, person, place, event, or
scientific/historical idea that a modern reader would benefit from understanding more deeply.

Rules:
- Pick EXACTLY 1 phrase from EACH numbered window — no more, no fewer.
- Each phrase must be a verbatim substring of that window's text — copy character-for-character.
- Prefer short, specific phrases (1–5 words) over long ones.
- Avoid phrases that are too generic (e.g. "he said", "the house", "the man").
- Return ONLY a JSON array of the exact phrases, in window order, e.g.:
  ["Walden Pond", "transcendentalism", "bean-field"]
- No markdown fences, no commentary, no keys — just the bare JSON array.\
"""

_PHRASES_USER = """\
Book: "{title}" by {author} ({year})
Chapter {chapter_num}: {chapter_title}

The chapter has been divided into {n_windows} equal windows (~{words_per_window} words each).
Pick EXACTLY 1 verbatim annotation phrase from EACH window — {n_windows} phrases total.

{windows_text}

Return a JSON array of exactly {n_windows} phrases, one per window, in order.\
"""

# Target one phrase every ~300 words (~1 page); cap at 25 to keep enhancements tractable.
_WORDS_PER_WINDOW = 300
_MAX_WINDOWS = 25
_MIN_WINDOWS = 8


def _split_text(text: str, n: int) -> list[str]:
    """Split text into n roughly equal sections, preferring paragraph boundaries."""
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


def make_windows(text: str) -> list[str]:
    """Split text into annotation windows using the same parameters as build_phrase_prompt."""
    word_count = len(text.split())
    n = max(_MIN_WINDOWS, min(_MAX_WINDOWS, word_count // _WORDS_PER_WINDOW))
    return _split_text(text, n)


def build_phrase_prompt(book: dict, chapter: dict, text: str) -> list[dict]:
    """Pass 1 (source-text mode): identify one annotation phrase per fixed-size window."""
    windows = make_windows(text)
    n_windows = len(windows)
    words_per_window = len(text.split()) // n_windows

    windows_text = "\n\n".join(
        f"[WINDOW {i + 1} of {n_windows}]\n{win}"
        for i, win in enumerate(windows)
    )

    return [
        {"role": "system", "content": _PHRASES_SYSTEM},
        {"role": "user", "content": _PHRASES_USER.format(
            title=book["title"],
            author=book["author"],
            year=book["year"],
            chapter_num=chapter["number"],
            chapter_title=chapter["title"],
            n_windows=n_windows,
            words_per_window=words_per_window,
            windows_text=windows_text,
        )},
    ]


_RETRY_SYSTEM = """\
You are a literary annotator for Enhanced Classics.

Pick EXACTLY ONE annotation phrase from the window of text shown below — a concept,
person, place, event, or scientific/historical idea that a modern reader would benefit
from understanding more deeply.

Rules:
- The phrase MUST be a verbatim substring of the window — copy character-for-character.
- Prefer short, specific phrases (1–5 words).
- Return ONLY the phrase as a bare JSON string, e.g.: "Walden Pond"
- No markdown fences, no commentary.\
"""


def build_single_window_retry_prompt(
    book: dict, chapter: dict, window_idx: int, n_windows: int, window_text: str
) -> list[dict]:
    """Retry prompt for a single window when the original phrase failed verification."""
    return [
        {"role": "system", "content": _RETRY_SYSTEM},
        {"role": "user", "content": (
            f'Book: "{book["title"]}" by {book["author"]} ({book["year"]})\n'
            f'Chapter {chapter["number"]}: {chapter["title"]}\n\n'
            f'[WINDOW {window_idx} of {n_windows}]\n{window_text}\n\n'
            f'Return one verbatim annotation phrase from this window as a JSON string.'
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
