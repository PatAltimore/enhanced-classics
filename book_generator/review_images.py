"""Review the Wikimedia images attached to a book's enhancement cards.

Claude (or a person) looks at contact sheets and removes images that do not illustrate the
card's Wikipedia topic. Two commands:

  python review_images.py sheet  --book <slug> [--out DIR] [--per-sheet 20]
      Writes numbered HTML contact sheets (image, #id, Wikipedia topic, trigger, caption) into
      DIR (default: work/<slug>/image_review). Serve DIR with `python -m http.server <port>`
      and open s0.html, s1.html, ... in a browser, comparing each image with its topic and
      caption. rows.json in the same folder maps every #id to its chapter file and card id.

  python review_images.py remove --book <slug> --ids 3,17,42 [--out DIR]
      Blanks image_url and image_caption for those #ids (the card itself is kept).
"""
import argparse
import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent
BOOKS = ROOT / ".." / "public" / "books"

_CARD = re.compile(
    r'  - id: "(?P<id>.*?)"\r?\n    trigger: "(?P<trigger>.*?)"\r?\n    title: "(?P<title>.*?)"\r?\n'
    r'    wikipedia_url: "(?P<wiki>.*?)"\r?\n    image_url: "(?P<img>.*?)"\r?\n    image_caption: "(?P<cap>.*?)"'
)


def _rows(slug: str) -> list[dict]:
    rows = []
    for path in sorted((BOOKS / slug).glob("chapter-*.md")):
        text = path.read_text(encoding="utf-8")
        for m in _CARD.finditer(text):
            rows.append({
                "file": path.name, "id": m["id"], "trigger": m["trigger"],
                "wiki": m["wiki"].split("/wiki/")[-1], "img": m["img"], "cap": m["cap"],
            })
    return rows


def _out_dir(args) -> Path:
    return Path(args.out) if args.out else ROOT / "work" / args.book / "image_review"


def cmd_sheet(args) -> None:
    rows = _rows(args.book)
    with_img = [(i, r) for i, r in enumerate(rows) if r["img"]]
    if not with_img:
        sys.exit(f"No images found for {args.book} (nothing to review).")
    out = _out_dir(args)
    out.mkdir(parents=True, exist_ok=True)
    (out / "rows.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    style = ("<meta charset='utf-8'><style>body{font:12px sans-serif;margin:4px}"
             ".g{display:grid;grid-template-columns:repeat(5,1fr);gap:6px}.c{border:1px solid #999;padding:2px}"
             "img{width:100%;height:130px;object-fit:contain;background:#eee}</style>")
    n = args.per_sheet
    sheets = 0
    for b in range(0, len(with_img), n):
        cells = "".join(
            f"<div class='c'><img src='{html.escape(r['img'])}'><div><b>#{i}</b> {html.escape(r['wiki'])}"
            f"<br><small>{html.escape(r['trigger'][:40])} ({html.escape(r['file'][8:10])})</small>"
            f"<br><small>{html.escape(r['cap'][:80])}</small></div></div>"
            for i, r in with_img[b:b + n])
        (out / f"s{b // n}.html").write_text(style + f"<div class='g'>{cells}</div>", encoding="utf-8")
        sheets += 1
    print(f"{len(with_img)} images on {sheets} sheets in {out}")
    print(f"Serve:  cd {out} && python -m http.server 8000   then open s0.html ... s{sheets - 1}.html")


def cmd_remove(args) -> None:
    out = _out_dir(args)
    rows = json.loads((out / "rows.json").read_text(encoding="utf-8"))
    ids = sorted({int(x) for x in args.ids.split(",") if x.strip()})
    by_file: dict[str, list[dict]] = {}
    for i in ids:
        by_file.setdefault(rows[i]["file"], []).append(rows[i])
    for name, items in by_file.items():
        path = BOOKS / args.book / name
        text = path.read_text(encoding="utf-8", newline="")
        for r in items:
            pat = re.compile(
                r'(  - id: "' + re.escape(r["id"]) + r'"\r?\n    trigger: ".*?"\r?\n    title: ".*?"\r?\n'
                r'    wikipedia_url: ".*?"\r?\n    image_url: )".*?"(\r?\n    image_caption: )".*?"')
            text, n = pat.subn(r'\1""\2""', text, count=1)
            if n != 1:
                sys.exit(f"Could not find card {r['id']} in {name}")
        path.write_text(text, encoding="utf-8", newline="")
    print(f"Removed images from {len(ids)} cards; {len(_rows(args.book)) and sum(1 for r in _rows(args.book) if r['img'])} images remain.")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("sheet", "remove"):
        p = sub.add_parser(name)
        p.add_argument("--book", required=True)
        p.add_argument("--out")
    sub.choices["sheet"].add_argument("--per-sheet", type=int, default=20)
    sub.choices["remove"].add_argument("--ids", required=True)
    args = ap.parse_args()
    {"sheet": cmd_sheet, "remove": cmd_remove}[args.cmd](args)


if __name__ == "__main__":
    main()
