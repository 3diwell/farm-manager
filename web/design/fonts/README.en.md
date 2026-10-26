[Русский](README.md) · **English**

# Interface fonts

| File | Font | Based on | License |
|---|---|---|---|
| `3diwell-wide-j.woff2`, `3diwell-wide-j-bold.woff2` | 3DIWELL Wide J, 3DIWELL Wide J Bold | Jura, © 2019 The Jura Project Authors, https://github.com/ossobuffo/jura | SIL OFL 1.1 — `OFL-Jura.txt` |
| `3diwell-wide-p-regular.woff2` | 3DIWELL Wide P | Play Regular, © 2011 Jonas Hecksher, Playtypes, e-types AS | SIL OFL 1.1 — `OFL-Play.txt` |
| `3diwell-wide-p-bold.woff2` | 3DIWELL Wide P Bold | Play Bold, © 2011 Jonas Hecksher, Playtypes, e-types AS | SIL OFL 1.1 — `OFL-Play.txt` |

These are Modified Versions under the OFL. What was changed (Wide P — version 1.100, Wide J — 1.200, 26.09.2026):

- the glyphs are scaled down to the cap height of the previous interface font, and the average line length
  is matched to it, so the replacement takes up the same space on screen (Wide J is 7% larger);
- equal spacing is added between letters; the word space matches the previous font;
- Wide J: the regular style is Jura wght 850, the bold one is wght 1000 (the weight axis is extended using
  the author's own increments; the source covers 300–700), and the glyphs are 7% larger than the previous font;
  without its own bold the browser emboldened the letters itself, and they ran together;
- hinting (fitting outlines to screen pixels) was redone with ttfautohint; for Wide J it raises
  lowercase letters to a whole pixel in small text and aligns stems strictly to pixels;
- the fonts are renamed: the name "Play" is a Reserved Font Name of the Play author, so the modified fonts
  are called "3DIWELL Wide …". The authors' notices are kept in the font files themselves and in `OFL-*.txt`.

The modified fonts are distributed under the same SIL Open Font License 1.1; MPL 2.0 does not apply to
them.

Built from Google Fonts sources at pinned commits (verified by SHA-256); the result is byte-for-byte
reproducible:

```bash
python tools/build_ui_fonts.py --download --src <folder outside the project>
```

Requires `fonttools`, `brotli` and `ttfautohint-py==0.6.1` — for building only.
