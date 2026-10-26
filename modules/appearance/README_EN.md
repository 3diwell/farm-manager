[Русский](README_RU.md) · **English**

# Appearance and themes — 0.17.2

An update of the `appearance` module based on 0.17.1. A calmer editor and reworked built-in themes; the theme schema stays at **12**. The FM core and other modules are not changed.

## Printer progress outline in 0.17.2

- A thin 1.6 px line follows the actual corners of the card, including independent rounding and the asymmetric shape. The pulsing and the neon halo of the line itself are removed; the separate user setting for the card glint is kept.
- Progress starts at the top; the line fills clockwise. At 100% the outline is closed, at partial progress it is open.
- The nested FM zoom, the card size and the border width are taken into account. Percentage readings, statuses, print start and print completion do not change. The minimum starting segment set by the FM core itself is kept.
- The fix applies to all themes while the module is enabled, with no extra settings and no need to save the theme again. Project outlines do not change.
- When the module is disabled, the original FM line is restored; the helper rendering and observers are removed. The exported user installation ZIP includes the fix.

Tested in a separate Chrome on test cards with Vue from the supplied FM: 36 outline checks, 17 data/export checks, 20 editor checks and 10 glass layer checks. Production printers and the installed application were not touched. After installing the update, restart FM and reload the page with **Ctrl+Shift+R**.

## Glass fix in 0.17.1

The cause of the shifted outlines is confirmed: the supplied FM applies `html { zoom: 1.04 }` and a nested `.zoom-wrap` zoom. The glass layer read the visual coordinates of the cards via `getBoundingClientRect()` and then wrote them as CSS coordinates inside the background layer, which was already zoomed. The zoom was applied twice; the negative background offset added to the shift.

The fix measures the coordinate system of the module's own layer and converts positions, sizes and clipping bounds into it. The size of the refraction map and the card radii under the nested zoom are taken into account as well. Production cards and FM core files are not changed.

**The glass effect is not disabled:** blur, optical refraction and edge lighting are kept. In a separate test the original version reproduced a shift of up to 64.33 px and the same outlines spilling outside the cards; the fixed version passed the alignment check with a tolerance of 0.15 px at zoom levels 0.85, 1, 1.04 and 1.25, with nested zoom and scrolling. Before/after screenshots were checked visually.

The fix also applies to themes with optical glass that were saved earlier. After installing, restart FM and reload the page with Ctrl+Shift+R; there is no need to select or configure the theme again. The check was run in an isolated Chrome with geometry from the supplied FM, not in the user's production application.

## What changed in 0.17.0

- The main settings are visible right away; detailed groups are under a single expandable item **Fine tuning**.
- Explanations open with the **?** button, the exact numeric value opens by clicking the percentage/value, the color code opens with the **HEX** button. All features are kept, but they are not all shown at once.
- The preview no longer has its own inner scrolling or two repeated instructions. The sample height is calculated from its actual content and updates when the text, font or window width changes. On a small screen you can scroll the settings section as a whole, but not a nested sample window.
- The built-in themes are independent: **Quiet**, **Aurora**, **Clarity**, **Glass**. Each has both palettes configured. The thumbnails show the characteristic surfaces, color, shape and progress; the selected one is clearly marked. They do not inherit the styling of the installed package.
- "My themes" is collapsed by default. The save form appears when you click **Save your variation**.
- The brightness slider has a fixed 0–100% range, with no mismatch between the exact value and the slider position.

Custom themes saved earlier are not replaced. Old built-in variants that the user saved to a collection or JSON can still be opened. The installed module's theme is available under **Original themes**.

## Installing the update

1. For a backup, export your theme or collection to JSON in the installed editor.
2. Upload the ZIP through the FM module manager as an update of "Appearance and themes". There is no need to remove the module first.
3. Restart FM when the module manager asks for a restart.
4. Reload the browser page with **Ctrl+Shift+R**.

The ZIP has the `appearance/module.json` and `appearance/web/…` layout expected by the FM installer. Custom themes stay in browser storage; the update does not reset them.

## How to use

Start with the **Themes** section. Pick a built-in theme, adjust it in the neighbouring sections and check the sample on the right. Until you click **Apply**, the working FM interface does not change. **Preview in FM** temporarily shows the changes in the application itself; when you end the preview, the applied appearance returns.

| Section | Shown up front | In expandable groups |
| --- | --- | --- |
| Themes | Four built-in themes and your saved variations | Apply history, transfer/backup, author and installation ZIP |
| Colors and text | Main color, text size, spacing, border contrast | Surfaces and text, statuses/borders/header, font and typography |
| Background | Base, animated background, brightness, speed and effect choice | Image, colors, shape and mixing, static pattern, motion and workload |
| Cards and effects | Material, shape, edge glow, shared glint | Glass, radii, three independent shadows, glow, highlights, buttons/tables/progress |

The separate "Simple" and "Advanced" modes no longer exist. All **86 original parameters** are kept and distributed among the groups; the extra actions for the image, font, background style and metadata are also available. Hiding a group does not reset its values. Controls that are not needed in the current mode are hidden; search can show such a parameter together with an explanation of how to enable it.

Under the group name you see the number of available settings (for the font, its name) and the number of changed visible parameters. A blue dot next to a setting means it differs from the applied theme; **↶** returns it to its applied value. The exact field opens when you click the value to the right of the setting name; in the detailed groups it is available right away. It lets you enter the internal value: for example, text size `1.28` corresponds to `128%`. Time and radii use seconds and pixels. Background brightness is now shown everywhere as a percentage of the actual value, without the former conversion of the 0–0.34 range to 0–100%; saved values do not change.

## Palettes and effects

A single **Dark / Light** switch above the sections selects the palette being edited and the sample. The working light/dark theme is still chosen by FM. The editor itself keeps readable neutral colors.

Each parameter shows its scope: the selected palette or both palettes. The **Shared effects / Separate effects** menu lets you split the supported effects: material, transparency, shadows, glow, glass parameters, brightness and colors of the animated background. Interface colors are always separate. The font, shape, animation style and speed and a number of other settings remain shared.

When you turn on separation, the shared values are copied to both palettes. When you merge them, the editor asks which effects to keep — the dark or the light ones. You can decline, or undo the merge with the **Undo** button.

## What is kept

- All six kinds of animated background; the image and the animation can run at the same time.
- Independent contributions of the base effect and the streams in the mixed background.
- Separate glints for printers/projects, their brightness and travel time; the shared switch does not change the detailed numeric values.
- Optical glass, independent radii, three kinds of shadows and precise typography.
- A custom WOFF2/WOFF/TTF/OTF font up to 2 MB and a PNG/JPEG/WEBP image up to 1.5 MB, included in the export.
- Draft autosave, undo/redo, comparison, preview in FM.
- Up to 20 of your own variations, update/rename/delete with restore, and a history of five applies.
- Import/export of a theme and a collection as JSON, export of an installation ZIP.
- Checks of theme validity and storage availability.

A built-in theme opens in the editor in full, including both palettes; your previous work can be restored with the **Undo** button. It is not applied automatically. Importing a collection adds copies without replacing existing variations.

In the sample you can click an element to jump to its settings. Printer states, ×3 speed-up, long names, enlarged text and background-only preview have moved under **Appearance checks**. These test switches are not written into the theme.

## Compatibility and limitations

Schema 12, the applied theme/draft keys v7 and the collection/history keys v4 are kept. Supported earlier theme versions are migrated by the existing mechanism. The appearance belongs to the browser profile and the FM address: there is no automatic synchronization between browsers.

The background mechanism is kept; the coordinate conversion in the glass layer is fixed. SVG refraction depends on the browser; on a plain or opaque background it may be invisible. To check it, use an image or the animated background and translucent surfaces. Refraction 0 leaves a matte blur. Economy mode limits the effects.

If something goes wrong, open FM with `?appearance=off` (or `&appearance=off` if there are already parameters). Remove the parameter to turn the appearance back on.

## Build verification

The new version passed 17 programmatic check groups and 20 scenarios in an isolated Chrome: sections and search, undo/redo, save/restore, palettes, independent mixing, JSON and ZIP, draft, apply, preview and English labels. The layout was checked at widths of 1440, 1024, 768 and 390 px. All four built-in themes were checked in both palettes, along with the absence of inner scrolling and clipping of the sample with long names and enlarged text. The final run has no console errors.

The ZIP contents are checked separately, including a trial extraction with the exact installer function from the supplied FM version into a separate test folder. The production FM instance was not reinstalled, and no printer connections were made. Effect performance and interaction with all UI 3.0 windows need to be checked in your production environment.

The final report is `QA_CHECKS.json`. `QA_PREVIOUS_PROTOTYPE29.json` is the original report of the previous author, not the results of the new run. This is an update of the appearance editor; it contains no fixes for inventory or camera switching.
