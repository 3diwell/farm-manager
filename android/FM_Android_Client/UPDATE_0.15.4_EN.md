[Русский](UPDATE_0.15.4_RU.md) · **English**

# FM Android 0.15.4: compact interface and sorting

The ready app: `dist/FM-Client-0.15.4-debug.apk`. Install it over the previous
version; the connection, settings and inventory log are kept.

## Changes

- Projects and tasks show files as compact rows: a small thumbnail,
  name, quantities, model, readiness and a print icon. Tapping a row opens
  the full name, a large image, all parts with quantities and notes.
- Printer cards have become more compact. State, current file, progress,
  remaining time and inventory information are kept. Full details open
  in the printer card.
- QR scanning is available via the icon next to the printer list heading.
  Pause/resume, stop and repeat use standard symbols.
  Repeat keeps its explanatory heading; the parameters/bed confirmation are unchanged.
  Preheat editing opens with the settings icon next to the presets.
- The icons have a 48×48dp touch area, a TalkBack description and a tooltip
  on long press. Tab, material and status names are still shown as words.
- Printer sorting: status, model, name. Project and task files: name,
  readiness. The direction can be reversed. The settings are saved on the phone
  separately for each of the three lists, without changing the queue or the shared FM order.

## How to use it

The sort icon is to the right of the list heading. The selected order
is shown under the heading; the dialog explains the status order.

Printers by status: errors → pause → finished print → printing → preparing
→ free → unknown state → no fresh data. A state change
may move a card; while you are tapping/scrolling or TalkBack has focus,
the rearrangement is postponed. While you read a long list, the visible printer stays in place.

Files by readiness: ready to print → printing/parts in progress → plan complete
→ needs preparation → no file. "Plan complete" does not prevent printing again.
"Parts in progress" refers to linked parts and does not prove that the file itself is printing.
Quantities are taken from FM when the list is loaded; use refresh to update them.
Links of shared parts `extra_files` are taken into account for each file without changing the database.

Tapping the name opens the details. The printer icon opens the existing selection
of a compatible free printer and parameters; there is no immediate one-tap printing.
If the previous submission is unknown, a new start is still blocked.

## Compatibility

Both themes, the FM/3diwell brand, Russian/English, inventory, QR/NFC,
cameras, pause/stop, preheating and repeat with regular FM accounting are kept. Module
availability and rights are checked the same way as before. Everything still works on the local network.
The core, the Android server, modules and working data are not changed.

Analysis of 13 examples and references: `UI_RESEARCH_0.15.4_RU.md`.
Build checks and limitations: `VALIDATION_MOBILE_0.15.4.md`.
A usability check on a real phone is still required; unit tests do not replace it.
