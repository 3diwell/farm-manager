[Русский](modules.md) · **English**

# Plugin modules: builder and policies

Read this **only when you are working with** `modules/**` or adding a large feature.
What to run and when — CLAUDE.md §3.

## 1. Large feature → plugin module (the preferred path)

There are **no** built-in modules in the program (a principled decision by the owner): every module
is installed separately from a `.zip` and removed the same way. The only home of installed modules is
`DATA_DIR/modules/<id>/`. In the repository, `modules/<id>/` holds the **sources** from which the
installable `.zip` is built; they do not go into the `.exe` build.

```
modules/<id>/
  module.json      {"id","ru","en","version","icon","entry":"web/Panel.js",
                    "settings_entry":"web/Settings.js",               # optional
                    "launchers":[{"ru","en","icon","props":{...}}]}   # launchers are optional
  backend.py       def register(core): ...
  web/Panel.js     module window (Vue component)
  web/Settings.js  settings cell in the "Settings → Modules" tab (Vue component)
```

**The window and the settings are independent (2.1002).** `entry` and `settings_entry` are each optional
on their own, but at least one must be present, otherwise there is nothing to show the module with:

| what is declared | what the owner sees |
|---|---|
| `entry` only | the module window; a tile in the list and (optionally) a button on the bar |
| `entry` + `settings_entry` | the module window plus its settings cell in the "Modules" tab |
| `settings_entry` only | no window at all: the module lives as a single settings cell, gets no button on the bar, and is marked "settings below" in the list (this is how `messengers` is built) |

**The `core` API:** `add_route(path, handler, methods)` → `/api/mod/<id>/<path>`;
`resolve_db(name)` — the module's own database in the protected folder; `new_id(prefix)`;
`printers()` and `printer_states()` — read the farm and AMS;
`add_hook(name, fn)` — subscribe to print hooks (all fail-open, a hook error does not affect printing):
`'pre_print_check'` fn(printer_id, fdata, ams_slot, fname) → `None` = allow, a dict with `status`
= a blocking response; `'after_dispatch'` fn(printer_id, ams_map, fdata, fname) — after a successful
send, the result is ignored.

**Feed plan (16.09.2026).** `pre_print_check` additionally receives a named `plan=` —
`{"slots": [a slot for each filament], "external": bool, "source", "confidence"}`: which slots the
print will actually use (when started from the queue or in a batch, `ams_slot` is not set at all). The plan is passed
**only** to hooks that declared this argument; a four-argument hook is called as before.
`slots: []` means "feed is undetermined" — there is nothing to check; `slots: None` — there is no plan, behave
as before; `confidence: "snapshot"` — the plan was captured when queued and may be stale by the time of the start.

**Window contract:** a default-export component, props `{ open, lang }`, event `'close'`;
inline styles based on the theme CSS variables; icons via the global `<svg-icon>`.

**Installation:** only via "Settings → Modules → Install a module from .zip"; activation happens
after a restart. Removal is with the trash icon in the same place (files are deleted, the module database is kept).

## 2. "Module → core" data: provider/aggregator only

The core **does not know** about specific modules: the core **must not** fetch `/api/mod/<id>/*`.
A module publishes data through a ModuleCore provider (`add_printer_badge_provider`,
`add_printer_filament_provider`), and the core polls the shared aggregator (`/api/printer-badges`,
`/api/printer-filament`). A provider exception is logged and swallowed — the core does not crash;
module not installed → empty response → the UI block is hidden. Register the provider under
`hasattr(core, "...")` so the module does not crash on an older core.

The opposite direction: `core.get_printer_filament_snapshot(printer_id)` — read-only, fail-open,
returns a **deep copy** of the bound filament snapshot. This is how the "Quality analytics" module
captures print materials without importing Inventory or opening its database.

## 3. Deployment: repository ≠ farm

The runtime loads modules **only** from `DATA_DIR/modules/`. Edits to `modules/<id>/*` reach the
farm only via: `python tools/build_<id>_zip.py` → reinstall the zip → restart the program.

**After any edit to `modules/<id>/*`:** bump `"version"` (patch) in `module.json`, write the same
number into `app/module_catalog.py`, rebuild the zip, and **explicitly tell the owner to reinstall the module**.
Lesson from Alpha 2.704: a provider "did not work" because the farm had an old zip installed.

**The module version no longer prevents loading (26.09.2026).** Any version is installed and run,
older or newer than the program. A route's permission is taken from the permission map by method and address. A version
mismatch with the map goes to the log as a note. A route that is not in the map is open only to the
administrator (`app/module_runtime_policy.py`). In "Settings → Modules", the version number and the
"newer: v…" or "newer than app" marks are shown under the name. A module fails to load in only three
cases: without a readable `module.json`, with an invalid id, or if its `backend.py` crashes at startup.
Checks — `tools/test_module_version_tolerance.py` and `tools/test_module_core_contract.py`.

## 4. Inventory SVG spools

- Runtime assets `modules/inventory/web/assets/spools/spool-{0,10,…,100}.svg` — **exactly 11**
  real vector SVGs (no raster/base64/`<image>`).
- The recoloring pipeline requires the filament fill `#00A0E3`, with no `url(#...)` references.
- `spool-states.generated.js` is an emergency codegen artifact: the runtime does **not import** it,
  and it is **not included** in the zip.
- Zip contents: `module.json`, `backend.py`, `web/InventoryPanel.js`, 11 SVGs — no backups,
  temp files or "New folder" folders.

## 5. UI invariants

- **Escape closes only the top layer** (the `escLayers` stack → the chain in `onKeydown`, `app.js`).
  New windows must join the stack; the recovery modal ignores Escape — do not change that.
- **Destructive actions** (deleting a printer/project/file/spool, stopping a print) — only
  through a confirm. They may be hidden in the right-click menu, but the functionality must not be removed.
- **The right-click menu does not break a normal click**: `@contextmenu.prevent` on the element, closing by clicking outside and by
  Escape, the menu is clamped at the screen edges, input/textarea keep the native menu.
  Dangerous items use `danger:true`.

## 6. Quality statistics policy (the `quality` module)

- A separately installable module; the program works fully without it.
- **The core provides only generic events**: `app/print_run_events.py` (no SQL) builds the `run_id`
  and the fail-open hooks `print_run_started` / `print_run_finished` (the payload is a copy; a subscriber
  error is swallowed). The core does not know about `/api/mod/quality/*`; there are no fallback endpoints.
- Quality data belongs to the module: `DATA_DIR\farm_quality.db`. Updating or removing the module code
  does not delete the database.
- **The log is immutable**: rows are only appended and receive a terminal outcome exactly once.
- **Print materials come only from the job's actual assignment** (the `material_assignments`
  of the start event, matched to the bound spool). A spool being present in the AMS is **not** usage
  in itself; never store "all non-empty slots". `confidence`:
  exact / probable / partial / unknown (nothing is written for unknown). Do not split the total weight across slots.
- Conclusions require a sample and confidence; correlation ≠ causation; "at fault" only after
  human confirmation. Non-quality outcomes are excluded from rankings while remaining
  in costs. `schema_version` is in every row; backfill is marked `origin='backfill'`.

## 7. Order calculation (the `cost` module, since 3.0)

On 12.09.2026 the owner removed "Print cost" and put "Order calculation"
(the owner's sources) in its place under the same id `cost`: the module kept the names, paths, methods and permissions
of the routes. Version 0.2.0 — so that the core does not load the old "Print cost" if it remained on the
farm: it will show as "needs an update", and installing the new zip is enough.

- Its own database `DATA_DIR\farm_cost.db`: `orders`, `order_files`, `order_config`, `order_model_rates`,
  `order_printer_rates`, `order_printer_models`, `order_sequence`. The module does not delete or rework the tables of the former
  "Print cost" (`cost_*`); before the first load it copies the previous database once
  to `farm_cost_before_order_module_<time>.db`.
- Copies of order files — `DATA_DIR\cost_order_files\<order>\`. Deleting an order removes only these
  copies; program projects created from the order are not touched.
- It does not hook into printing (no hooks): printing does not depend on the module.
- It takes jobs and projects from the program ITSELF via HTTP requests to `127.0.0.1:<server port>` with
  the user's session headers (Cookie, Authorization, X-CSRF-Token); it creates a project through the standard
  import `/api/projects/import` and uploads the order files into it. The Host from the request is not used,
  and the module does not access the external network. The module window takes material prices from Inventory.
- The core does not store the JOB file path (`staging_files.src_path` is empty): the module looks for the file by name in
  `DATA_DIR\temp_files`, then `DATA_DIR\slicer_uploads` — the same way the core itself does in `/api/staging`
  (fixed when it was included in release 3.0; without it, the job list in the module was always empty).
- Route effects in the permission map: FILESYSTEM and NETWORK for calculation, saving and `recalc`; the printer
  model cache (DATABASE, NETWORK) for the printer list and the printer rate. Proof —
  `tools/test_cost_module.py`, section I; the calculation is also checked there against independent arithmetic.
- **Backup (R-125):** the core provider `cost` is backup v2 based on the module's real schema:
  orders, model and printer rates, printer models, the number counter and settings
  (`order_config`). Model files attached to orders (`order_files`, `cost_order_files\`) are **not
  included** in the backup — this is stated in the backup window; attachments are the owner's decision (container v3). Old
  v1 backups ("Print cost") are readable: their data goes into extensions and is not applied. If you changed the module's
  tables, update `CostBackupProvider` (`app/config_backup/module_providers.py`): its contents are
  compared with the module DDL in `tools/test_cost_backup_provider.py`.
- Build: `python tools/build_cost_zip.py` → `modules/3diwell-module-order-calculation.zip`
  (backend, `order_calculator.py`, `order_parser.py`, window).

## 8. Appearance and themes (the `appearance` module, since 3.0)

- Interface only: `module.json` and ES modules in `web/`. There is no backend and no routes — the module is not in the core
  permission map, and the core does not check its version.
- The entry point `web/AppearancePanel.js` is imported by the core when the page loads, like any
  module with a window; its top level runs `bootstrapThemeRuntime`. The theme is applied to the whole
  program only if the module is enabled: the state is checked against `/api/modules` every 10 seconds and
  when returning to the window; if the module is disabled or no response arrives, the theme style is removed. Emergency
  exit — an address with `?appearance=off`.
- Themes are stored in the browser (`localStorage`, keys `fm_appearance_*`): they do not reach the server or the
  backup, and are moved to another computer with a theme file. In the backup the module is
  classified as "no user data" (`AppearanceBackupProvider`); without that, its
  installation would block a full export — fail-closed, `docs/MODULE_BACKUP_CONTRACT.md`.
- The author's documents (`README_RU.md`, `IPHONE_THEME_NOTES_RU.md`, `QA_*.json`) sit next to the
  sources but are not included in the zip.
- Build: `python tools/build_appearance_zip.py` → `modules/3diwell-module-appearance.zip`;
  the builder checks that every relative import resolves to a file in the archive. Checks —
  `tools/test_appearance_module.py`.

Which profile a particular edit needs — [profile-selection.md](profile-selection.en.md).
