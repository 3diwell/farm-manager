[Русский](frontend.md) · **English**

# Frontend validation

Read this **only when you are editing** `web/**` or `modules/*/web/**`.
What to run and when — CLAUDE.md §3.

## Required minimum after an edit

```bash
node --check web/app.js
node --check web/components/<changed>.js        # each changed component
```

CSS brace balance — read the file **only this way** (it has a broken UTF-8 tail and a base64 font blob):

```bash
python - <<'PY'
css = open('web/app.css', encoding='utf-8', errors='surrogateescape').read()
assert css.count('{') == css.count('}'), 'CSS braces!'
PY
```

`div`/`span` balance in `index.html`:

```bash
python - <<'PY'
import re
h = open('web/index.html', encoding='utf-8').read()
assert len(re.findall(r'<div\b', h)) == h.count('</div>'), 'div!'
assert len(re.findall(r'<span\b', h)) == h.count('</span>'), 'span!'
PY
```

## Vue template compilation is mandatory

The runtime compiler silently fails to render a broken template, so a JS syntax check is not enough.

**`@vue/compiler-dom` is not installed in this project** (dependencies are not installed; see the permission
policy). Compile with `web/vendor/vue.esm-browser.js`, which is already in the repository,
with a `document` stub. A ready-made harness exists in the tests that do this: search `tools/`
for `vue.esm-browser`. For `index.html`, the contents of `<div id="app">…</div>` are extracted and
run through the same `compile()`.

A control run against a reference from HEAD is mandatory: if compilation is "green" on a deliberately broken template,
the check is vacuous.

## Bake-in after `app.js` edits

```bash
grep -c "ref('{{ VERSION }}')" web/app.js     # exactly 1
grep -c CHANGELOG_B64 web/app.js              # exactly 1
```

## Fragile spots

- **`web/app.css`** — ⚠️ edit only through Python with `errors='surrogateescape'`; appending to the end
  is safe. No line-based tools and no ordinary editors: measured on 16.09.2026 —
  one edit in an ordinary editor rewrote the line endings of 252 lines, and the commit showed 252
  changed lines instead of one. The content survived that time (byte comparison: exactly one line
  differed, no replacement characters were added), so it was not reverted — but a noisy edit
  remained in the owner's history, which is exactly what the rule is meant to prevent. Check after such an edit:
  `git diff --ignore-cr-at-eol <before> <after> -- web/app.css` must show only your own lines.
- **`web/ui3/**`** — the second interface (UI 3.0). The files are ordinary and may be edited freely, but
  pulling in anything from `web/app.css` / `web/app.js` is forbidden: this separation is the only thing that
  makes reworking the new interface safe for the working one. It is validated by the same required
  minimum (`node --check`, brace and tag balance, template compilation) — `checks.py` picks up
  `web/ui3/**` files automatically — plus the `tools/test_ui3_groundwork.py` suite.
- **`web/index.html`** — one giant line: edit only by unique anchors.
- **Vue runtime compiler**: a bare `<template>` without a v-directive silently does not render (Edge/V8);
  regex literals in template attributes (`v-if="/x/.test(...)"`) crash Firefox; on SVG `<g>` use
  `transform-box:view-box` + an explicit `transform-origin` (Firefox).
- **Tailwind is static**: arbitrary classes (`w-[13px]`) are NOT in the build — set new
  fixed sizes inline with `style="..."`.
- **Theme CSS variables**: `--fm-accent(-rgb)`, `--fm-surface-*`, `--fm-text-*`, `--fm-border-*`;
  for statuses there are `--fm-danger`, `--fm-success`, `--fm-error`. There is **no** `--fm-warn` variable —
  use `#f5a524` for an amber warning.
- **Icons** `<svg-icon name>` (`web/design/icons.js`): activity add alert archive bed bulb
  camera cap check clipboard close delete download drive edit file folder gear layers link
  module moon navigation nozzle pencil printer refresh sun trash undo upload.
- **CSS invariant 🔒**: `overscroll-behavior:contain` on
  `.ex-list/.ex-side/.ex-prev/.fm-users-list/.fm-audit-list/.fm-set-scroll/.diag-body/.fm-changelog-scroll`
  — must not be removed, otherwise scrolling a list scrolls the page behind it.

## New core UI component

`web/components/<area>/X.js` (following the `InventoryPanel` pattern) → import and
`__app.component('X', X)` in `app.js` → tag in `index.html` → the checks above.

## Browser tests

26 files in `tools/` launch headless Edge. They are slow and fragile; run only the ones
that relate to the changed area. Browser profiles are removed **only by their own marker**;
a global kill by process name is forbidden — it would kill the owner's browser.

### The "four scales" review — scale is set by the WINDOW WIDTH

Measured on 16.09.2026: `--force-device-scale-factor` in `extra_args` **does not change the page width**.
With a single `window_size`, all four runs give ~1576 CSS pixels — that is, the same layout
is checked four times, and the report to the owner "reviewed at four scales" turns out to be inaccurate.
Only an explicit window size produces different layouts:

```python
for scale, size in (("0.8", (1920, 1200)), ("1.0", (1600, 1150)),
                    ("1.25", (1366, 900)), ("1.5", (1180, 820))):
    R = stage.run(JS, window_size=size, settle_ms=5200, path="/ui3",
                  extra_args=("--force-device-scale-factor=%s" % scale,), shot_path=shot)
```

→ 1897 / 1576 / 1343 / 1156 pixels. Printing `window.innerWidth` in the report is mandatory: without it
you cannot see whether the widths were actually different.

Which profile a particular edit needs — [profile-selection.md](profile-selection.en.md).
