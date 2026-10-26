[Русский](TOUR_SELECTOR_AUDIT_RU.md) · **English**

# 3DIWELL Farm Manager — tour selector review

Review date: 2026-06-29  
Reviewed baseline: the version after `3DIWELL_tour_update_15_fix_language_highlight.zip`

## Safety rule

Only the elements of the interactive tour were checked: highlight selectors, anchor points, callout lines and the position of the description window. The server, API, databases, real printers, Quick Tasks, projects and print logic were not changed.

## What was checked

For each tour step it was checked that:

1. the selector exists in `web/index.html` or is created by the tour demo data;
2. the selector points to the element described in the step text;
3. the highlight does not capture neighbouring elements without need;
4. the description window does not deliberately cover an important highlighted element;
5. the anchor point and the callout line are built from the correct element.

## Issues found and fixed

### 1. Step 10 — "Diagnostics"

**Before:** the step showed the demo diagnostics window, but the highlight selector stayed on the settings gear:

```text
[data-tour="settings"]
```

**After:** the highlight was moved to the body of the demo diagnostics log:

```text
[data-tour="diag"]
```

A separate safe marker was added to `web/index.html` for the demo window:

```html
<div data-tour="diag" data-scene="diagbody" ...>
```

This is not the real diagnostics window and not a server log. It is only a visual demo scene of the tour.

### 2. Step 18 — "Card and status colors"

**Before:** the generic printer card selector was used:

```text
[data-tour="pcard"]
```

During the tour usually only the demo printer remains, but such a selector is still less precise.

**After:** the step is bound directly to the demo printer card:

```text
#tour-demo-printer
```

Now steps 18, 19 and 20 work consistently with the same demo printer card.

## Review table of all steps

| No. | step id | Selector | Status | Comment |
|---:|---|---|---|---|
| 1 | `welcome` | `[data-tour="header"]` | OK | Highlights the header/logo, matches the welcome text. |
| 2 | `connection-sync` | `[data-tour="broker"]` | OK | Highlights the Data Broker and the sync indicator. |
| 3 | `language` | `[data-tour="lang"]` | OK | After the previous fix highlights only EN/RU, without the gear. |
| 4 | `settings-open` | `[data-tour="settings"]` | OK | Highlights the settings button. |
| 5 | `settings-edition` | `[data-tour="set-edition"]` | OK | Highlights the "Interface mode" block in the settings. |
| 6 | `settings-appearance` | `[data-tour="set-theme"]` | OK | Highlights the theme and the font. |
| 7 | `settings-dates` | `[data-tour="set-dates"]` | OK | Highlights creation dates and deadlines. |
| 8 | `settings-slicer` | `[data-tour="set-slicer"]` | OK | Highlights the slicer selection. |
| 9 | `settings-tools` | `[data-tour="set-tools"]` | OK | Highlights the tools block. |
| 10 | `diagnostics-demo` | `[data-tour="diag"]` | Fixed | Now highlights the demo diagnostics log instead of the gear. |
| 11 | `settings-access-roles-audit` | `[data-tour="set-security"]` | OK | Highlights access, roles and audit. |
| 12 | `settings-modules` | `[data-tour="set-modules"]` | OK | Highlights the modules block. |
| 13 | `settings-about` | `[data-tour="set-about"]` | OK | Highlights the "About" block. |
| 14 | `printers-overview` | `[data-tour="printers"]` | OK | Highlights the whole printer column. |
| 15 | `printers-sort` | `[data-tour="psort"]` | OK | Highlights the sort switch. |
| 16 | `printers-view` | `[data-tour="pview"]` | OK | Highlights the list/grid switch. |
| 17 | `printers-add` | `[data-tour="add-printer"]` | OK | Highlights the add printer button. |
| 18 | `printer-card-grid` | `#tour-demo-printer` | Fixed | Now bound precisely to the demo printer instead of the generic card selector. |
| 19 | `printer-card-expanded` | `#tour-demo-printer` | OK | Highlight and numbered marks checked after the preview fix. |
| 20 | `printer-ams-print` | `#tour-demo-printer` | OK | Highlights the demo printer during the print/AMS scene. |
| 21 | `projects-overview` | `#tour-demo-project-board` | OK | Highlights the demo project panel. |
| 22 | `projects-create` | `[data-tour="newproj"]` | OK | Highlights the create project button. |
| 23 | `projects-import-files` | `#tour-demo-project-import` | OK | Highlights file import in the demo project. |
| 24 | `projects-part-counters` | `#tour-demo-project-table` | OK | Highlights the counter table and column hints. |
| 25 | `projects-label-objects` | `#tour-demo-project-labels` | OK | Highlights the Label Objects block. |
| 26 | `projects-counting-fallback` | `#tour-demo-project-fallback` | OK | Highlights the warning that reliable counting is not possible. |
| 27 | `projects-card` | `#tour-demo-projcell` | OK | Highlights the Demo Project card in the real project grid. |
| 28 | `projects-archive` | `[data-tour="archivebtn"]` | OK | Highlights the archive button. |
| 29 | `quick-tasks-overview` | `[data-tour="qtsection"]` | OK | Highlights the Quick Tasks section. |
| 30 | `quick-tasks-drop` | `[data-tour="qtdrop"]` | OK | Highlights the file drop zone. |
| 31 | `quick-tasks-load` | `[data-tour="qtsection"]` | OK | Highlights Quick Tasks over the file loading demo scene. |
| 32 | `quick-tasks-row` | `#tour-demo-staging` | OK | Highlights the demo file row in Quick Tasks. |
| 33 | `quick-tasks-find-printer` | `#tour-demo-status` | OK | Highlights the clickable file status. |
| 34 | `suggestions-alerts` | `[data-tour="suggest"]` | OK | Highlights the suggestions and alerts block. |
| 35 | `finish` | `[data-tour="header"]` | OK | The final step returns the highlight to the header. |

## Checks after the review

After the fixes, run:

```bash
node --check web/app.js
node --check web/composables/tourSteps.js
node --check web/tour/validate-tour.mjs
node web/tour/validate-tour.mjs
python3 -m py_compile server.py app/*.py
```

Expected validator result: `OK. Обучение прошло автоматическую проверку.` (printed in Russian: "OK. The tour passed the automatic check.")
