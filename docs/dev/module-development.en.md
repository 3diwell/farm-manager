[Русский](module-development.md) · **English**

# Module development

A module is a folder with `module.json`, an optional `backend.py` and an optional interface in `web/`.
It is installed as a `.zip` archive into `DATA_DIR/modules/<id>/`. Ready-made examples —
[examples/modules/demo_free](../../examples/modules/demo_free) and
[examples/modules/demo_paid](../../examples/modules/demo_paid).

## module.json

```json
{"id": "my_module", "ru": "Мой модуль", "en": "My module", "version": "1.0.0",
 "icon": "module", "entry": "web/Panel.js", "settings_entry": "web/Settings.js",
 "core_contract": "1.0.0"}
```

- `id` — Latin letters, digits, `_` and `-` only.
- `version` — the release number, changes freely. `core_contract` — the version number of the module's routes in
  the core permission map; it changes only when the routes change.
- `entry` — the module window component (Vue, ES module), `settings_entry` — a tile in "Settings → Modules".

## backend.py

```python
def register(core):
    core.add_route("hello", api_hello, ["GET"], policy_id="my_module.hello")
```

What `core` provides (`ModuleCore` in `server.py`):

- routes `add_route(path, handler, methods, policy_id)` → `/api/mod/<id>/<path>`; paid ones —
  `add_paid_route(path, handler, feature, methods, policy_id)`;
- its own database `resolve_db("farm_<id>.db")` in the data folder;
- its own folder for files `data_dir()` → `<data folder>/module_data/<id>` (created on first
  access, 16.10.2026): cache, exports, copies of documents. It moves together with the data folder and
  is NOT deleted when the module is removed or reinstalled. The module's program folder (`module_dir`) is
  read-only: it is replaced entirely by every reinstall, signed package replacement and
  rollback to the previous version. The daily backup covers only the `farm_*.db` databases — the module
  adds its important files to its own backup provider;
- printers and their state, read-only: `printers()`, `printer_states()`,
  `get_printer_filament_snapshot()`, `get_printer_reported_filament()`;
- print hooks `add_hook(name, fn)`: `pre_print_check`, `after_dispatch`, `print_run_started`,
  `print_run_finished`;
- badges and filament on printer cards: `add_printer_badge_provider`,
  `add_printer_filament_provider`;
- licenses and the signed package: `license_documents()`, `license_revision()`, `install_id()`,
  `package_document()`, `import_module_file()` — see
  [MODULE_LICENSING_FOUNDATION.en.md](../licensing/MODULE_LICENSING_FOUNDATION.en.md).

Route permissions are defined only in `app/route_policy_registry.py` by `policy_id`. A route that is
not listed there is available only to the administrator when login protection is on.

## Data and backups

A module with user data must have a backup provider in
`app/config_backup/module_providers.py` (or a declaration that it has no data). Without it a full settings
backup will fail while the module is installed — even if it is disabled: disabled modules and modules that
failed to load are included in the backup too. If you changed the module's tables, update the provider and bump
its `backup_schema_version` with a migration from the old schema; declare UNIQUE constraints in
`TableSpec(unique=...)` so that a conflict is found in the plan rather than by a restore rollback.
Rules — [MODULE_BACKUP_CONTRACT.en.md](../MODULE_BACKUP_CONTRACT.en.md).

## Packaging

```bash
python tools/module_package.py --module-dir path/to/my_module --out my_module-1.0.0.zip
```

With a signature and embedded keys for a paid component — section 9 of the licensing foundation document.

## Rules

- A module does not import `server.py` and does not reach into core internals — only through `core`.
- Neighbouring files — via `core.import_module_file("helper.py")`: for a signed package this way they
  are loaded from verified bytes.
- A module does not send commands to printers bypassing the core.
- A license refusal must not stop printing or hide user data. The core itself
  turns a `pre_print_check` refusal with `reason_class: "license"` into a notification.
- Timeouts (16.10.2026): `register()` — 30 s (otherwise the module is not loaded, state `load_error`,
  reason `timeout`, late `add_route`/`add_hook` calls are rejected); `pre_print_check` hooks — 20 s,
  `after_dispatch` — 30 s, `print_run_*` — 10 s. A hook that does not answer in time is skipped, printing
  goes on; while it hangs, subsequent `pre_print_check` and `print_run_*` calls are skipped immediately.
  `after_dispatch` is not skipped: each call runs in its own thread, the timeout limits only
  waiting for the dispatch, and a late deduction is carried out later (no more than 8 simultaneously hung calls
  of one hook). Hooks are called in a separate thread.
- The left external spool of the H2D is internal slot `-2`. A hook that understands it declares
  a keyword parameter `ext_left`; for the others the core does not expose `-2` (a plan with empty slots,
  `after_dispatch` is skipped).
