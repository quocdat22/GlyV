"""Generate 134 precomposed Vietnamese characters and check a font's cmap.

Usage: .venv/bin/python scripts/vietnamese_coverage.py path/to/font.otf
"""
import argparse
import json
import unicodedata as ud

from fontTools.ttLib import TTFont


def vietnamese_characters():
    shapes = (("a", ""), ("a", "BREVE"), ("a", "CIRCUMFLEX ACCENT"),
              ("e", ""), ("e", "CIRCUMFLEX ACCENT"), ("i", ""),
              ("o", ""), ("o", "CIRCUMFLEX ACCENT"), ("o", "HORN"),
              ("u", ""), ("u", "HORN"), ("y", ""))
    tones = ("", "GRAVE ACCENT", "ACUTE ACCENT", "HOOK ABOVE", "TILDE", "DOT BELOW")
    characters = []
    for letter, shape in shapes:
        for base in (letter.upper(), letter):
            for tone in tones:
                if not shape and not tone:
                    continue
                marks = "".join(ud.lookup("COMBINING " + mark) for mark in (shape, tone) if mark)
                characters.append(ud.normalize("NFC", base + marks))
    characters.extend(ud.lookup("LATIN " + case + " LETTER D WITH STROKE")
                      for case in ("CAPITAL", "SMALL"))
    assert len(characters) == len(set(characters)) == 134
    assert all(len(c) == 1 and ud.category(c) in ("Lu", "Ll") for c in characters)
    assert sum(c.isupper() for c in characters) == 67
    assert not set(characters) & set("aeiouyAEIOUY")
    return characters


def coverage(font_path):
    with TTFont(font_path) as font:
        cmap = font.getBestCmap() or {}
        glyphs = set(font.getGlyphOrder()) - {".notdef"}
        entries = [{"character": c, "codepoint": f"U+{ord(c):04X}",
                    "name": ud.name(c),
                    "glyph": cmap.get(ord(c)) if cmap.get(ord(c)) in glyphs else None}
                   for c in vietnamese_characters()]
        present = [e["character"] for e in entries if e["glyph"] is not None]
        missing = [e["character"] for e in entries if e["glyph"] is None]
        report = {"font": str(font_path), "total": len(entries),
                  "present_count": len(present), "missing_count": len(missing),
                  "present": present, "missing": missing, "characters": entries,
                  "missing_plain_vowels": [c for c in "AEIOUYaeiouy"
                                           if cmap.get(ord(c)) not in glyphs]}
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("font")
    args = parser.parse_args()
    print(json.dumps(coverage(args.font), ensure_ascii=False, indent=2))
