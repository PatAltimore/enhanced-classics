import unicodedata, sys

text = open('source_texts/walden/chapter-01-economy.txt', encoding='utf-8').read()
seen = {}
for i, c in enumerate(text):
    cp = ord(c)
    if cp > 127 and cp not in seen:
        seen[cp] = text[max(0,i-20):i+20]

for cp in sorted(seen):
    name = unicodedata.name(chr(cp), "?")
    ctx  = repr(seen[cp])
    print(f"U+{cp:04X}  {name:<35}  {ctx}")

# Also report total word count and separator lines
seps = [i for i, line in enumerate(text.splitlines()) if set(line.strip()) == {'-'} and len(line.strip()) > 5]
print(f"\nTotal words: {len(text.split())}")
print(f"Separator lines (all-dash rows): {len(seps)}")

# Report how many windows the prompt builder would create
words = len(text.split())
MAX_W, MIN_W, WPW = 25, 8, 300
n = max(MIN_W, min(MAX_W, words // WPW))
print(f"Phrase windows: {n}  (~{words//n} words each)")
