[Русский](TOUR_GUIDE_RU.md) · **English**

# 3DIWELL Farm Manager — guide to editing the interface tour

> **The tour is currently disabled** (owner's decision of 12.09.2026): the `TOUR_ENABLED = false` flag at the top of
> `web/app.js`. The selection window does not open at startup, the buttons in "Settings → General" are hidden,
> and `startTour` and `resumeTour` do nothing. The tour code and the script are not deleted — set it to
> `true` before further work.
>
> **Decision of 16.10.2026: do not turn this tour back on.** Reasons:
> 1. The steps were written for interface 2.0 (demo explorer, expanded printer card, demo scenes),
>    while the main interface since 2.982 is 3.0; 2.0 remains only as the fallback `/?ui=2`.
> 2. The tour sandbox is dangerous on a live farm: for the duration of the tour, real printers, parts and projects
>    are replaced with demo data (alerts from real printers are not visible), and `window.fetch` is patched so
>    that any non-GET request to `/api/` gets a fake 200 `{}` response — the action "succeeds" without
>    reaching the server, including in module windows.
>
> Guidance in 3.0 is **hover hints** (`web/composables/helpHints.js`; every
> `data-help` in the markup has RU and EN text, checked by `tools/test_help_hints_coverage.py`). On first
> launch, the "Suggestions" panel offers once to turn them on (a "Turn on hints" /
> "No, thanks" card, the `farm_help_offer_v1` flag in the browser). If a step-by-step tour is needed, that is a new
> task: a short 3.0 tour of no more than 7 steps, only over real elements, with no demo data and no
> `fetch` patching.

## Main rule

The interface tour must be edited without affecting the application's working logic: printers, projects, API, server-side calculations, databases and print handlers.

If a new tour step requires not just a change of text or highlighting but a change in application behaviour, demo scenes, server code or real actions with files/printers, such an edit must be treated as potentially risky and approved separately.

## Which files are responsible for the tour now

| File | Purpose |
|---|---|
| `web/composables/tourSteps.js` | tour script: full tour, quick tour, order, texts, selectors, groups and section names |
| `web/app.js` | tour display logic, demo data, highlight measurement, protection against POST requests during the tour |
| `web/index.html` | interface elements and `data-tour` markers that the tour highlights |
| `web/app.css` | look of the highlight, cards, animations and demo scenes |

## Tour modes

There are currently two modes:

| Mode | Launch | Purpose |
|---|---|---|
| Quick tour | `startTour('quick')` | a fast first introduction to the interface, 13 steps |
| Full interface tour | `startTour('full')` | a detailed tour of the interface, 35 steps |

The quick tour contains no copies of steps. It is assembled from the full tour using the `quickTourStepIds` list at the end of `web/composables/tourSteps.js`.

The tour card now shows the current section, for example "Projects and production · 2 of 8". The bottom bar has a "Skip section" button.

To change the quick tour, it is enough to change the `quickTourStepIds` list:

```js
export const quickTourStepIds = [
    'welcome',
    'connection-sync',
    'projects-overview',
    'finish'
];
```

Important: `quickTourStepIds` may only contain existing `id` values from the full `tourSteps` list.


## Tour sections

Section names are at the beginning of `web/composables/tourSteps.js`:

```js
export const tourGroupLabels = {
    basics: 'Basics',
    settings: 'Settings',
    printers: 'Printers',
    projects: 'Projects and production',
    quick_tasks: 'Quick Tasks',
    alerts: 'Suggestions and alerts',
    finish: 'Finish'
};
```

If a new group is added, you need to:

1. add it to `tourGroupLabels`;
2. add it to `tourGroupOrder`;
3. add the Russian translation of the group name to the `Object.assign(RU, {...})` block in `web/app.js`;
4. update the list of allowed groups in `web/tour/validate-tour.mjs` if the group is really new.

## Navigation inside the tour

During the tour the following are available:

- the "Back" button;
- the "Next" button;
- the "Skip section" button;
- the `←` and `→` keys to go back/forward;
- the `Enter` key to go forward;
- the `Esc` key to close the tour.

These keys work only while the tour is open. If the focus is in an input field, the keys are not intercepted.

## What can be changed safely in `web/composables/tourSteps.js`

You can change:

- the order of steps;
- `title` and `text`;
- `card` — the position of the hint card;
- `sel` — if the element already exists in `web/index.html`;
- `group` and `id`;
- add new steps if they use existing interface elements.

Do not change without a separate check:

- server APIs;
- real actions with printers;
- file uploads;
- part counting;
- project saving;
- print completion logic;
- the `_tourBlockFetch` protection, which blocks non-GET requests during the tour.

## Step format

```js
{
    id: 'projects-label-objects',
    group: 'projects',
    sel: '#tour-demo-projcell',
    card: 'below',
    title: 'Automatic part counting',
    text: 'Automatic counting depends on data saved inside the print file...'
}
```

### Fields

| Field | Required | Description |
|---|---:|---|
| `id` | recommended | a stable step name for future edits |
| `group` | recommended | logical group: `basics`, `settings`, `printers`, `projects`, `quick_tasks`, `alerts`, `finish` |
| `sel` | yes | CSS selector of the element to highlight |
| `title` | yes | English title key |
| `text` | yes | English text key |
| `card` | no | position of the hint card |
| `view` | no | `grid` or `list`, temporarily switches the printer view |
| `scene` | no | starts a demo scene |
| `expand` | no | expands the demo printer card |
| `marks` | no | shows numbered badges on buttons |

## Translations

The tour still uses the shared `RU` dictionary inside `web/app.js`. A separate block was added for the new texts in this version:

```js
Object.assign(RU, {
    "English text": "Русский перевод"
});
```

If a new step with a new `title` or `text` is added, its Russian translation must be added to this block. Otherwise the Russian version of the application will show this text in English.

## Allowed demo scenes

| `scene` | Purpose |
|---|---|
| `diag` | diagnostics demo |
| `print` | demo of choosing a file and an AMS slot |
| `load` | demo of loading a file into Quick Tasks |
| `project` | static demo panel of a project and part counting, without API or database |
| `attach` | old scene of attaching a file to a part, currently unused |
| `slice` | old scene of opening a model in the slicer, currently unused |
| `reveal` | old scene of opening the file location, currently unused |

New demo scenes require edits to `web/app.js`. That is no longer a simple text edit, so the risks must be checked separately before adding a new scene.


## Automatic tour check

A separate file was added for safe edits:

```text
web/tour/validate-tour.mjs
```

It changes nothing in the application and only reads the tour files. It checks:

- that every step has a unique `id`;
- that `quickTourStepIds` refers only to existing steps of the full tour;
- that `quickTourSteps` is really assembled in the same order;
- that `group`, `scene`, `card` and `view` are among the allowed values;
- that `sel` can be found in `web/index.html`;
- that every `title` and `text` has a Russian translation in the `RU` dictionary;
- that every group has a section name and a Russian translation.

### How to run the check

From the application root folder:

```bash
node web/tour/validate-tour.mjs
```

Or on Windows you can open the file:

```text
web/tour/validate-tour.bat
```

If everything is fine, the output is (the validator prints it in Russian; it means "Result: OK. The tour passed the automatic check."):

```text
Результат: OK. Обучение прошло автоматическую проверку.
```

If there is an error, the script shows the specific step and the reason: for example a missing translation, a duplicate `id` or a selector that does not exist in `index.html`.

## What changed in this version

1. The tour script was moved out of the large `web/app.js` into `web/composables/tourSteps.js`.
2. Every step got an `id` and a `group`.
3. A production block about projects was added to the tour:
   - importing a project from files;
   - part counters;
   - automatic counting via `Label Objects / gcode_label_objects`;
   - safe behaviour when a file cannot be counted reliably.
4. Two tour modes were added: a quick tour and a full tour.
5. The settings menu now has two tour buttons instead of one: "Quick tour" and "Full interface tour".
6. An automatic tour check was added: `web/tour/validate-tour.mjs` and a convenient Windows launcher `web/tour/validate-tour.bat`.
7. A section structure was added to the tour card: the name of the current section and the progress within the section.
8. The "Skip section" button was added.
9. Keyboard navigation was added: `←`, `→`, `Enter`, `Esc`.
10. The validator now checks the tour section names.
11. The overlay tour was adapted to small screens: the card gets narrower, the bottom bar wraps its buttons into two rows, the keyboard hint is hidden on mobile devices, and hints do not go off screen.
12. An expandable "Details" block was added to the tour cards: the main text is shorter, and long explanations open with a button.
13. The validator now checks the Russian translation of the `more` field.
14. Server code, API, databases, printer handlers and calculations were not changed.


## Adapting the tour to small screens

The adaptation is in `web/app.css`, in the block titled (in Russian, "Adapting the interactive tour to small screens"):

```text
Адаптация интерактивного обучения для небольших экранов
```

This block changes only the look of the overlay tour: card sizes, wrapping of the bottom bar buttons, hiding the keyboard hint on mobile devices and limiting the width of pop-up hints. It does not change the tour script, demo data, server requests, printers, projects or part counting.

In addition, card positioning in `web/app.js` takes a compact screen into account: on narrow or short screens the card is placed at the top or bottom centre so that it does not slide out of the window.

## Checks after edits

The minimum check after any change to the tour:

```bash
python -m py_compile server.py app/*.py
node --check web/app.js
node --check web/composables/tourSteps.js
node --check web/tour/validate-tour.mjs
node web/tour/validate-tour.mjs
```

Additionally, by hand:

1. Start the application.
2. Open the settings.
3. Start "Quick tour" and go through it to the end.
4. Start "Full interface tour" and check that it has more steps.
5. Go through the new steps in Russian.
6. Check that there are no English phrases in the new steps.
7. Check the "Skip section" button.
8. Check the `←`, `→`, `Enter`, `Esc` keys.
9. Check the tour in a narrow browser window, for example 430×800 or 390×844: the card must fit the width, the bottom bar must be reachable, and the step numbers must scroll horizontally.
10. Check on a short screen, for example 600–620 px high: the card must not cover the bottom navigation.
11. Check that the tour closes and the real data comes back as it was.

## Expandable "Details" block

Starting with version `tour_update_06`, a tour step can have an optional field:

```js
more: 'Detailed explanation text'
```

Usage rules:

1. Keep a short explanation in `text` that the user sees right away.
2. Move long explanations, examples and clarifications to `more`.
3. If a step has `more`, a "Details" button appears in the tour card.
4. When moving to the next step, the expanded block closes automatically.
5. `more` must have a Russian translation in `web/app.js`, otherwise the validator reports an error.

This change concerns only the tour card. It does not change the server, API, printers, projects, databases, part counting or print start.

An example of a safe edit:

```js
{
  id: 'projects-label-objects',
  group: 'projects',
  sel: '#tour-demo-projcell',
  title: 'Automatic part counting',
  text: 'Automatic counting works best when the print file contains object labels from the slicer.',
  more: 'For reliable recognition, enable Label Objects / gcode_label_objects before exporting g-code or 3MF.'
}
```



---

## Update 07 — saving tour progress

Local saving of tour progress in the browser was added.

What changed:

- if the user closed the tour with `×`, `Esc` or simply did not reach the end, the application remembers the current mode and step;
- a `Continue tour` button appears in the settings;
- if the user clicked `Done` on the last step, the progress is cleared;
- the `Reset tour progress` button clears the saved progress manually.

Technically, the progress is stored only in the browser's `localStorage`:

```js
farm_tour_progress_v1
```

It is not sent to the server and does not change databases or affect printers, projects, Quick Tasks or part counting.

When the list of steps changes, it is safer to rely on the step `id` rather than its number. That is why the progress saves both `stepId` and `stepIndex`. If the order of steps changes, the application tries to restore the position by `stepId`.

## Stage 8 — tour start window

A tour start window was added. It helps the user choose to:

- continue a previously started tour;
- take the quick tour;
- take the full tour;
- postpone the tour;
- stop showing this window at startup.

Technically this is a safe front-end change:

- data is stored only in `localStorage`;
- the server, API, databases, printers and projects are not changed;
- the keys `farm_tour_progress_v1`, `farm_tour_completed_v1`, `farm_tour_start_prompt_v1` are used;
- if the tour is completed with the "Done" button, the window is no longer shown automatically;
- if the tour is closed halfway, the window offers to continue.

Check after edits:

```bash
node --check web/app.js
node --check web/composables/tourSteps.js
node --check web/tour/validate-tour.mjs
node web/tour/validate-tour.mjs
```

Manual check in the browser:

1. Open the application in a new browser or clear the `farm_tour_*` keys in `localStorage`.
2. Make sure the tour selection window appears.
3. Start the quick tour.
4. Close the tour halfway — the settings and the start window must show "Continue tour".
5. Finish the tour with the "Done" button — the progress must be cleared, and the automatic window must not appear again.
6. Tick "Do not show this window on startup" — the `farm_tour_start_prompt_v1` key must become `0`.


---

## Stage 9 — table of contents in the tour start window

A short table of contents of the full tour was added to the start window.

What the table of contents shows:

- the names of the tour sections;
- the number of steps in each section of the full tour;
- a `quick` mark for the sections included in the quick tour.

Technically this is a safe front-end change:

- the list is built automatically from `tourSteps`, `quickTourSteps`, `tourGroupLabels` and `tourGroupOrder`;
- the server, API, databases, printers, projects and part counting are not changed;
- when a new step is added to `web/composables/tourSteps.js`, the step count in the table of contents updates automatically;
- if a new group is added, it must be added to `tourGroupLabels` and `tourGroupOrder`.

Files related to this stage:

```text
web/app.js
web/index.html
web/app.css
web/composables/tourSteps.js
```

Check after edits:

```bash
node --check web/app.js
node --check web/composables/tourSteps.js
node --check web/tour/validate-tour.mjs
node web/tour/validate-tour.mjs
```

Manual check in the browser:

1. Open the tour start window.
2. Check that it shows the `Full tour outline` block.
3. Check that the sections are displayed: basics, settings, printers, projects, Quick Tasks, alerts, finish.
4. Check that long names do not break the window at mobile width.
5. Start the quick and the full tour — the tour behaviour must stay the same.


---

## Stage 10 — demo scene of a project and part counting

A safe demo panel was added for the `Projects and production` section.

What the panel shows:

- an example production project;
- an imported `gcode.3mf` file;
- the `Label Objects` found;
- part rows with the columns `On plate`, `Needed`, `Printed`, `Status`, `File`;
- an example of how the `Printed` counter increases after a file prints successfully;
- a warning that without object labels the application must not guess the quantity.

Technically this is a safe front-end change:

- the panel is rendered only during a tour step with `scene: 'project'`;
- the panel does not call the API;
- the panel does not write to the database;
- the panel does not create or change real projects;
- the panel does not affect part counting or print logic.

Related files:

```text
web/app.js
web/index.html
web/app.css
web/composables/tourSteps.js
web/tour/validate-tour.mjs
web/tour/TOUR_GUIDE_RU.md
```

When adding new elements to this demo panel, you need to:

1. add a new `id` or `data-tour` to `web/index.html`;
2. use this selector in `web/composables/tourSteps.js`;
3. if a new `scene` is added, add it to `web/tour/validate-tour.mjs`;
4. if new step or hint texts are added, add their Russian translation to `web/app.js`;
5. run `node web/tour/validate-tour.mjs`.


## Tour text review — stage 17

At this stage the tour texts were brought to a single terminology for a farm operator.

Recommended terms:

| Term | How to use it |
|---|---|
| print file | a ready g-code / 3MF that can be sent to a printer |
| model | an STL / STEP or other file that still needs to be sliced |
| plate | a set of parts inside one print file |
| On plate | how many of a given part are printed by one file |
| Needed | the required number of parts |
| Printed | the accepted finished quantity |
| reprint | printing a part again after a defect / rework |
| Quick Tasks | section name, not translated in the interface text |

Rule for new texts: the main `text` must be short and understandable without expanding the "Details" block. Add the details to `more` if the card becomes too long without them.
