"""Assembles the final chapter markdown file from generated parts.

Output format:
  ---
  <YAML frontmatter with metadata, summary, enhancements>
  ---
  <prose text>
"""
import json
import re
import io
import yaml


# Custom representer so long strings use YAML literal block style (|)
# instead of being collapsed into a single quoted line.
class _LiteralStr(str):
    pass


def _literal_representer(dumper, data):
    if "\n" in data or len(data) > 80:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


yaml.add_representer(_LiteralStr, _literal_representer)


def _literalize(obj):
    """Recursively wrap long string values so they render as YAML literal blocks."""
    if isinstance(obj, dict):
        return {k: _literalize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_literalize(i) for i in obj]
    if isinstance(obj, str) and (len(obj) > 80 or "\n" in obj):
        return _LiteralStr(obj)
    return obj


def _parse_json(raw: str) -> dict:
    """Parse JSON from model output, tolerating markdown fences or extra text."""
    raw = raw.strip()
    # Strip ```json ... ``` fences if present
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Last resort: find the first {...} block
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            return json.loads(match.group())
        raise ValueError(f"Could not parse JSON from model output:\n{raw[:400]}")


def format_chapter(book: dict, chapter: dict, text: str, enhancements_raw: str) -> str:
    data = _parse_json(enhancements_raw)

    frontmatter = {
        "title": book["title"],
        "author": book["author"],
        "year": book["year"],
        "chapter": chapter["number"],
        "chapter_title": chapter["title"],
        "slug": chapter["slug"],
        "book_slug": book["slug"],
        "license": "public-domain",
        "summary": data.get("summary", []),
        "enhancements": data.get("enhancements", []),
    }

    frontmatter = _literalize(frontmatter)
    yaml_str = yaml.dump(frontmatter, allow_unicode=True, default_flow_style=False, sort_keys=False)

    return f"---\n{yaml_str}---\n{text.strip()}\n"
