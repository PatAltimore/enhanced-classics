"""Build a Kindle-friendly EPUB 3 for a book, with the enhanced sections inline.

Each enhanced section is printed in a shaded box right after the paragraph that contains its
trigger phrase (the phrase itself is underlined). Chapter summaries go at the top of each
chapter, and the Characters page goes last (it contains spoilers).

Pure standard library plus PyYAML. Usage:

    python make_epub.py --book the-great-gatsby
    python make_epub.py --all
    python make_epub.py --book walden --out ../epub

Send the result to a Kindle with Send to Kindle (app, web or email).
"""
import argparse
import datetime
import glob
import html
import json
import re
import sys
import uuid
import zipfile
from pathlib import Path
from xml.dom import minidom

import yaml

ROOT = Path(__file__).resolve().parent.parent
BOOKS = ROOT / "public" / "books"
CATALOG = ROOT / "public" / "catalog.json"

CSS = """\
body { font-family: serif; line-height: 1.45; margin: 0 4%; }
h1 { font-size: 1.5em; text-align: center; margin: 1.2em 0 .6em; page-break-before: always; }
h2 { font-size: 1.15em; margin: 1.4em 0 .5em; }
p { margin: 0 0 .9em; text-align: left; }
hr.scene-break { border: 0; border-top: 1px solid #888; margin: 2.5em 20%; }
blockquote.verse { margin: 1em 8%; font-style: italic; }
p.lines { margin-left: 1.2em; text-indent: -1.2em; }
ul.summary { margin: 0 0 1.5em; padding-left: 1.2em; font-size: .92em; }
ul.summary li { margin-bottom: .35em; }
div.titlepage { text-align: center; margin-top: 20%; }
div.titlepage h1 { page-break-before: auto; font-size: 2em; }
p.author { font-size: 1.2em; }
p.small { font-size: .85em; }
span.trigger { text-decoration: underline; }
div.card { margin: .9em 0 1.2em; padding: .6em .9em; background-color: #ececec; color: #000;
  border: 1px solid #b5b5b5; border-left: 4px solid #777; font-size: .9em; page-break-inside: avoid; }
div.card p { margin: 0 0 .45em; text-indent: 0; }
div.card a { color: #000; }
p.card-title { font-weight: bold; }
div.character { margin: 0 0 1.2em; }
p.role { font-style: italic; margin-bottom: .3em; }
"""


COVER_W, COVER_H = 1600, 2560
COVER_COLORS = [  # (background, accent)
    ("#14213d", "#e5c07b"), ("#2b2d42", "#edc967"), ("#3d1f2b", "#e8c9a0"), ("#1f3b34", "#e2d6a7"),
    ("#2f2a4a", "#d9b8f2"), ("#40332a", "#f0d9a8"), ("#0f3057", "#f2d492"), ("#3b2f2f", "#d8c3a5"),
]
FONT_BOLD = ["georgiab.ttf", "timesbd.ttf", "Georgia Bold.ttf", "DejaVuSerif-Bold.ttf", "LiberationSerif-Bold.ttf"]
FONT_REG = ["georgia.ttf", "times.ttf", "Georgia.ttf", "DejaVuSerif.ttf", "LiberationSerif-Regular.ttf"]


def _font(names, size):
    from PIL import ImageFont
    for n in names:
        try:
            return ImageFont.truetype(n, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def _wrap(draw, text, font, width):
    lines, cur = [], ""
    for word in text.split():
        trial = (cur + " " + word).strip()
        if draw.textlength(trial, font=font) <= width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    return lines + ([cur] if cur else [])


def make_cover(meta, slug):
    """Return JPEG bytes for a simple typographic cover, or None if Pillow is not installed."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None
    import io
    bg, accent = COVER_COLORS[sum(map(ord, slug)) % len(COVER_COLORS)]
    img = Image.new("RGB", (COVER_W, COVER_H), bg)
    d = ImageDraw.Draw(img)
    d.rectangle([90, 90, COVER_W - 90, COVER_H - 90], outline=accent, width=6)
    d.rectangle([120, 120, COVER_W - 120, COVER_H - 120], outline=accent, width=2)
    text_w = COVER_W - 440

    size = 210
    while True:
        f = _font(FONT_BOLD, size)
        lines = _wrap(d, meta["title"], f, text_w)
        if len(lines) <= 4 and all(d.textlength(l, font=f) <= text_w for l in lines) or size <= 90:
            break
        size -= 10
    line_h = int(size * 1.2)
    y = 560
    for l in lines:
        d.text((COVER_W / 2, y), l, font=f, fill="#ffffff", anchor="mt")
        y += line_h
    y += 50
    d.line([COVER_W / 2 - 220, y, COVER_W / 2 + 220, y], fill=accent, width=5)
    y += 90
    fa = _font(FONT_REG, 92)
    for l in _wrap(d, meta["author"], fa, text_w):
        d.text((COVER_W / 2, y), l, font=fa, fill=accent, anchor="mt")
        y += 120
    fs = _font(FONT_REG, 58)
    d.text((COVER_W / 2, COVER_H - 330), "E N H A N C E D   C L A S S I C S", font=fs, fill=accent, anchor="mt")
    d.text((COVER_W / 2, COVER_H - 250), "with notes on people, places and ideas", font=_font(FONT_REG, 44),
           fill="#cfcfcf", anchor="mt")
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=90)
    return buf.getvalue()


def norm(s):
    s = s.replace("‘", "'").replace("’", "'").replace("“", '"').replace("”", '"')
    s = s.replace("–", "-").replace("—", "-").replace("…", "...")
    return re.sub(r"\s+", " ", s)


def esc(s):
    return html.escape(s, quote=False)


def read_md(path):
    text = Path(path).read_text(encoding="utf-8").replace("\r\n", "\n")
    m = re.match(r"---\n(.*?)\n---\n(.*)\Z", text, re.S)
    if not m:
        raise ValueError(f"{path}: no frontmatter")
    return yaml.safe_load(m.group(1)) or {}, m.group(2)


def inline(text):
    """Italics from the Gutenberg underscore/star markup (markers are already handled)."""
    text = re.sub(r"_(.+?)_", lambda m: "<em>" + m.group(1) + "</em>", text)
    text = re.sub(r"\*(.+?)\*", lambda m: "<em>" + m.group(1) + "</em>", text)
    return text


def card_html(c):
    link = ""
    if c.get("wikipedia_url"):
        link = f'<p class="small"><a href="{html.escape(c["wikipedia_url"])}">Read more on Wikipedia</a></p>'
    return (
        f'<div class="card"><p class="card-title">{esc(c["title"])}</p>'
        f'<p>{esc(c["content"])}</p>{link}</div>'
    )


def body_to_html(body, cards):
    """Return (html, shown); shown holds the cards placed inline after their paragraph."""
    by_len = sorted(range(len(cards)), key=lambda i: -len(cards[i]["trigger"]))
    shown = set()
    pending = []

    def marker(m):
        text = m.group(1)
        nt = norm(text)
        hit = next((i for i in by_len if norm(cards[i]["trigger"]) in nt), None)
        if hit is None or hit in shown:
            return "<strong>" + text + "</strong>"
        shown.add(hit)
        pending.append(hit)
        return '<span class="trigger">' + text + "</span>"

    out = []
    for block in re.split(r"\n\n+", body):
        if not block.strip():
            continue
        if re.fullmatch(r"\s*-{5,}\s*", block):
            out.append('<hr class="scene-break"/>')
            continue
        lines = [l for l in block.split("\n") if l.strip()]
        verse = len(lines) >= 2 and all(re.match(r"\s", l) for l in lines)
        # Short, unindented lines (poetry, play dialogue) keep their line breaks; hard-wrapped prose is ~70 wide.
        short = len(lines) >= 2 and sum(len(l.strip()) for l in lines[:-1]) / (len(lines) - 1) < 55
        p = esc(block.strip("\n"))
        p = re.sub(r"\*\*([\s\S]+?)\*\*", marker, p)
        p = inline(p)
        if verse:
            out.append('<blockquote class="verse">' + re.sub(r"\n[ \t]*", "<br/>", p.strip()) + "</blockquote>")
        elif short:
            out.append('<p class="lines">' + re.sub(r"\s*\n\s*", "<br/>", p.strip()) + "</p>")
        else:
            out.append("<p>" + re.sub(r"\s*\n\s*", " ", p.strip()) + "</p>")
        for i in pending:
            out.append(card_html(cards[i]))
        pending.clear()
    return "\n".join(out), shown


def xhtml(title, body):
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<!DOCTYPE html>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="en" xml:lang="en">\n'
        f"<head><title>{esc(title)}</title><link rel=\"stylesheet\" type=\"text/css\" href=\"style.css\"/></head>\n"
        f"<body>\n{body}\n</body>\n</html>\n"
    )


def chapter_title(fm):
    n = fm.get("chapter")
    t = str(fm.get("chapter_title") or "").strip()
    if t and not re.match(r"chapter\s+\d+", t, re.I) and n:
        return f"Chapter {n}: {t}" if not t.lower().startswith("chapter") else t
    return t or f"Chapter {n}"


def build_chapter(path):
    fm, body = read_md(path)
    cards = fm.get("enhancements") or []
    text_html, shown = body_to_html(body, cards)
    title = chapter_title(fm)
    summary = ""
    pts = fm.get("summary") or []
    if pts:
        lis = "".join(f"<li>{esc(p['point'])}</li>" for p in pts)
        summary = f'<ul class="summary">{lis}</ul>'
    # a card whose trigger could not be found in the text goes at the chapter end
    leftover = "".join(card_html(c) for i, c in enumerate(cards) if i not in shown)
    page = xhtml(title, f"<h1>{esc(title)}</h1>\n{summary}\n{text_html}\n{leftover}")
    return {"title": title, "page": page, "cards": len(cards), "placed": len(shown)}


def build_characters(path):
    fm, _ = read_md(path)
    items = []
    for c in fm.get("characters") or []:
        items.append(
            '<div class="character">'
            f"<h2>{esc(c['name'])}</h2>"
            f'<p class="role">{esc(c["role"])}</p>'
            f"<p>{esc(c['summary'])}</p>"
            f"<p><em>Role in the book:</em> {esc(c['analysis'])}</p></div>"
        )
    body = (
        "<h1>Characters</h1>\n"
        '<p class="small"><em>This page describes the whole book, including the ending.</em></p>\n'
        + "\n".join(items)
    )
    return {"title": "Characters (contains spoilers)", "page": xhtml("Characters", body)}


def title_page(meta):
    desc = (meta.get("description") or "").strip()
    year = meta.get("year")
    year_s = f"{abs(year)} BC" if isinstance(year, int) and year < 0 else str(year or "")
    body = (
        '<div class="titlepage">'
        f"<h1>{esc(meta['title'])}</h1>"
        f'<p class="author">{esc(meta["author"])}</p>'
        f'<p class="small">{esc(year_s)}</p></div>\n'
        f"<p>{esc(desc)}</p>\n"
        "<h2>About this Enhanced Classics edition</h2>\n"
        "<p>This is an Enhanced Classics edition: the complete original text, with short notes added as you read. "
        "Underlined phrases in the text have a shaded Enhanced Classics note just below their paragraph, giving "
        "background on people, places, words and ideas, with a link to Wikipedia. Each chapter begins with a short "
        "summary, so skip it if you would rather not read ahead.</p>\n"
        '<p class="small">The text is in the public domain (Project Gutenberg). '
        "Notes and summaries were written for Enhanced Classics.</p>"
    )
    return {"title": "Title page", "page": xhtml(meta["title"], body)}


def make_opf(meta, uid, items, modified, cover=False):
    manifest = ['<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
                '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>',
                '<item id="css" href="style.css" media-type="text/css"/>']
    spine = []
    cover_meta = ""
    if cover:
        manifest += ['<item id="cover-image" href="cover.jpg" media-type="image/jpeg" properties="cover-image"/>',
                     '<item id="cover" href="cover.xhtml" media-type="application/xhtml+xml"/>']
        spine.append('<itemref idref="cover" linear="no"/>')
        cover_meta = '<meta name="cover" content="cover-image"/>\n'
    for it in items:
        manifest.append(f'<item id="{it["id"]}" href="{it["file"]}" media-type="application/xhtml+xml"/>')
        spine.append(f'<itemref idref="{it["id"]}"/>')
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid" xml:lang="en">\n'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        f'<dc:identifier id="bookid">{uid}</dc:identifier>\n'
        f'<dc:title>{esc(meta["title"])}</dc:title>\n'
        f'<dc:creator>{esc(meta["author"])}</dc:creator>\n'
        '<dc:language>en</dc:language>\n'
        '<dc:publisher>Enhanced Classics</dc:publisher>\n'
        f'<dc:description>{esc((meta.get("description") or "").strip())}</dc:description>\n'
        f'<meta property="dcterms:modified">{modified}</meta>\n{cover_meta}'
        "</metadata>\n<manifest>\n" + "\n".join(manifest) + "\n</manifest>\n"
        '<spine toc="ncx">\n' + "\n".join(spine) + "\n</spine>\n</package>\n"
    )


def make_nav(meta, items):
    lis = "\n".join(f'<li><a href="{it["file"]}">{esc(it["title"])}</a></li>' for it in items)
    return xhtml(
        "Contents",
        f'<nav epub:type="toc" id="toc"><h1>Contents</h1>\n<ol>\n{lis}\n</ol></nav>',
    )


def make_ncx(meta, uid, items):
    pts = "\n".join(
        f'<navPoint id="np{i}" playOrder="{i}"><navLabel><text>{esc(it["title"])}</text></navLabel>'
        f'<content src="{it["file"]}"/></navPoint>'
        for i, it in enumerate(items, 1)
    )
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">\n'
        f'<head><meta name="dtb:uid" content="{uid}"/></head>\n'
        f'<docTitle><text>{esc(meta["title"])}</text></docTitle>\n<navMap>\n{pts}\n</navMap>\n</ncx>\n'
    )


def build_book(slug, out_dir):
    cat = {b["slug"]: b for b in json.loads(CATALOG.read_text(encoding="utf-8"))["books"]}
    meta = cat[slug]
    chapters = sorted(glob.glob(str(BOOKS / slug / "chapter-*.md")))
    if not chapters:
        raise SystemExit(f"no chapters for {slug}")
    items = [dict(id="title", file="title.xhtml", **title_page(meta))]
    total = placed = 0
    for i, path in enumerate(chapters, 1):
        ch = build_chapter(path)
        total += ch["cards"]
        placed += ch["placed"]
        items.append(dict(id=f"ch{i}", file=f"ch{i:02d}.xhtml", **ch))
    chars = BOOKS / slug / "characters.md"
    if chars.exists():
        items.append(dict(id="characters", file="characters.xhtml", **build_characters(chars)))

    uid = "urn:uuid:" + str(uuid.uuid5(uuid.NAMESPACE_URL, "https://enhanced-classics/" + slug))
    modified = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{slug}.epub"
    cover = make_cover(meta, slug)
    files = {
        "OEBPS/content.opf": make_opf(meta, uid, items, modified, cover=bool(cover)),
        "OEBPS/nav.xhtml": make_nav(meta, items),
        "OEBPS/toc.ncx": make_ncx(meta, uid, items),
        "OEBPS/style.css": CSS,
        "META-INF/container.xml": (
            '<?xml version="1.0"?>\n<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
            '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>'
            "</rootfiles></container>\n"
        ),
    }
    for it in items:
        files["OEBPS/" + it["file"]] = it["page"]
    if cover:
        files["OEBPS/cover.xhtml"] = xhtml(
            "Cover", '<div style="text-align:center"><img src="cover.jpg" alt="Cover" style="max-width:100%;max-height:100%"/></div>')
    else:
        print(f"{slug}: no cover (install Pillow: pip install pillow)")

    # self-check: every file is well-formed XML
    for name, data in files.items():
        if name.endswith((".xhtml", ".opf", ".ncx", ".xml")):
            try:
                minidom.parseString(data.encode("utf-8"))
            except Exception as e:
                raise SystemExit(f"{slug}: {name} is not well-formed: {e}")

    with zipfile.ZipFile(out, "w") as z:
        z.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        for name, data in files.items():
            z.writestr(name, data, compress_type=zipfile.ZIP_DEFLATED)
        if cover:
            z.writestr("OEBPS/cover.jpg", cover, compress_type=zipfile.ZIP_STORED)
    size = out.stat().st_size / 1024
    print(f"{slug}: {len(chapters)} chapters, {total} notes ({placed} after their paragraph), {size:.0f} KB -> {out}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--book", help="book slug (see public/catalog.json)")
    ap.add_argument("--all", action="store_true", help="build every book")
    ap.add_argument("--out", default=str(ROOT / "epub"), help="output folder (default: <repo>/epub)")
    a = ap.parse_args()
    if not a.book and not a.all:
        ap.error("give --book <slug> or --all")
    slugs = [b["slug"] for b in json.loads(CATALOG.read_text(encoding="utf-8"))["books"]] if a.all else [a.book]
    for s in slugs:
        build_book(s, a.out)


if __name__ == "__main__":
    sys.exit(main())
