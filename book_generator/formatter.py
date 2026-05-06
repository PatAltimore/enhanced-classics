"""Assembles the final chapter markdown file from generated parts.

Builds YAML frontmatter manually to match the format expected by the
custom parser in public/js/app.js, which does not support block scalars
(|-) or unindented list items. All values are double-quoted single-line
strings; list items are indented with two spaces.
"""
import json
import re


def _q(value: str) -> str:
    """Wrap a string in double quotes, escaping backslashes and inner quotes."""
    s = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{s}"'


def _parse_json(raw: str) -> dict:
    """Parse JSON from model output, tolerating markdown fences or extra text."""
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            return json.loads(match.group())
        raise ValueError(f"Could not parse JSON from model output:\n{raw[:400]}")


def _build_yaml(book: dict, chapter: dict, data: dict) -> str:
    lines = ["---"]

    # Scalar metadata
    lines.append(f'title: {_q(book["title"])}')
    lines.append(f'author: {_q(book["author"])}')
    lines.append(f'year: {book["year"]}')
    lines.append(f'chapter: {chapter["number"]}')
    lines.append(f'chapter_title: {_q(chapter["title"])}')
    lines.append(f'slug: {_q(chapter["slug"])}')
    lines.append(f'book_slug: {_q(book["slug"])}')
    lines.append('license: "public-domain"')
    lines.append("")

    # Summary list
    lines.append("summary:")
    for s in data.get("summary", []):
        lines.append(f'  - point: {_q(s.get("point", ""))}')
        lines.append(f'    link: {_q(s.get("link", ""))}')
        lines.append(f'    link_label: {_q(s.get("link_label", ""))}')
    lines.append("")

    # Enhancements list
    lines.append("enhancements:")
    for e in data.get("enhancements", []):
        lines.append(f'  - id: {_q(e.get("id", ""))}')
        lines.append(f'    trigger: {_q(e.get("trigger", ""))}')
        lines.append(f'    title: {_q(e.get("title", ""))}')
        lines.append(f'    wikipedia_url: {_q(e.get("wikipedia_url", ""))}')
        lines.append(f'    image_url: {_q(e.get("image_url", ""))}')
        lines.append(f'    image_caption: {_q(e.get("image_caption", ""))}')
        lines.append(f'    content: {_q(e.get("content", ""))}')

    lines.append("---")
    return "\n".join(lines)


def format_chapter(book: dict, chapter: dict, text: str, enhancements_raw: str) -> str:
    data = _parse_json(enhancements_raw)
    yaml_block = _build_yaml(book, chapter, data)
    return f"{yaml_block}\n{text.strip()}\n"
