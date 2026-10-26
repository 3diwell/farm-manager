[Русский](IPHONE_THEME_NOTES_RU.md) · **English**

# iPhone · Clear — Prototype 29

An adaptation of the iPhone look for the FM working interface. Reference: https://www.apple.com/newsroom/2025/06/apple-introduces-a-delightful-and-elegant-new-software-design/ . No Apple assets are included; the system font is chosen on the user's device.

## New theme parameters

| Parameter | Value |
| --- | --- |
| Text scale | 1.28 |
| Body text | Weight 400, line spacing 1.45 |
| Headings | Weight 600, line spacing 1.2 |
| Captions | Weight 400, line spacing 1.35 |
| Button / input / card radii | 12 / 10 / 20 px |
| Panel surface | Optical glass |
| Buttons and inputs | Translucent |

| Per-palette parameter | Dark | Light |
| --- | --- | --- |
| First background color | #65a9fa | #90b9ed |
| Second background color | #af92ed | #c3ade5 |
| Background brightness | 0.075 | 0.035 |
| Fill opacity | 0.78 | 0.84 |
| Standard shadow | 0.30 | 0.18 |
| Panel depth | 0.12 | 0.06 |
| Soft shadow | 0.08 | 0.04 |
| Matte / gloss | 0.15 / 0.12 | 0.22 / 0.08 |
| Refraction | 0.38 | 0.25 |
| Glass blur | 4 px | 6 px |
| Edge light | 0.22 | 0.12 |

Both full palettes of surfaces and statuses are kept, along with the system font, smooth slow color flows, a neutral glint on the outlines and calm progress without an extra shimmer. All fields of the current schema are set. Both background colors are independent of the theme accents.

Full processing of the background pixels is done by an SVG displacement map in the module's own layers. Support for rendering SVG refraction depends on the browser; this is not a promise of an exact reproduction of Liquid Glass. The main limitations and a variant with ordinary matte blur are described in README_EN.md.

## Technical basis

Displacement map specification: https://www.w3.org/TR/filter-effects-1/#feDisplacementMapElement . Backdrop filtering model: https://drafts.csswg.org/filter-effects-2/ . Refraction shifts the background pixels near the edges without distorting the working text. Forbidden properties of FM core elements are not changed.
