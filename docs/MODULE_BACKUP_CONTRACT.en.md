[Русский](MODULE_BACKUP_CONTRACT.md) · **English**

# Module backup contract — PERMANENT RULES

**Introduced in Alpha 2.829. Mandatory for all current and future modules.**

A `.3diwell-backup` backup includes the settings and **all user data** of installed modules (the
`module_data` section of payload schema v2). Projects, jobs, project files, managed storage and
print history are **not** part of the backup, and restore does **not** change them (immutability
guard — fingerprint before/after with a full rollback on mismatch).

## Classification (fail-closed)

Every installed module must be registered (`app/config_backup/module_providers.py`) as exactly
one of:

| class | meaning |
|---|---|
| `persistent_data_with_backup_provider` | has user data AND has a provider |
| `no_persistent_user_data` | proven (forensic) to have no user data |
| `backup_temporarily_unsupported` | has data, no provider yet — **full export is blocked** |

- A module with data and no provider **cannot be skipped silently**: export fails with the error
  `manual_resolution_required` naming the exact module ("A full backup is not possible: the
  module does not support saving its data"). A file called a full backup is not created if part of
  the data would be lost.
- A new persistent module without a classification = a red test (`test_module_backup_contract.py`).
- **AGENTS rule:** *A module with persistent user data must provide a permanent versioned
  backup provider before release.*

## Provider (ModuleBackupProvider)

Contract: `module_id` (stable identity, NOT the display name; the module version is metadata, not
the schema), `backup_schema_version` (independent), `data_class`, `export_snapshot(store)`,
`validate_snapshot`, `migrate_snapshot` (the module's append-only chain; a schema newer than the
reader → safe refusal), `build_restore_plan` (read-only), `apply_restore` (only under the
multistore journal), `verify_restore`, `describe_scope`. A provider must: produce a logical
canonical JSON model (NOT a raw SQL dump, NOT ORM rows, NOT a pickle), be deterministic, not
access printers/the network/the locale, not include runtime cache, change nothing during
inspect/plan, and have a frozen fixture and a completeness test.

Providers of the current modules live **in the core** (module ZIPs are not changed). A future
module may register its own provider under the same contract.

**Which modules go into the backup (R-125, data-safety-01).** All installed ones: loaded,
**disabled by the user**, and found on disk but **failed to load** (the latter must have a
readable manifest with a valid id). A module's storage does not depend on its load state; a
disabled module has `enabled=false` in the backup. A database that does not exist yet (the module
has never run) is read as empty by export and plan, and is not created. A removed module (its
folder is gone) is not included in the backup, and restoring its data still requires the module
to be installed.

**Optional parts of the contract (R-125).** `TableSpec.unique` — sets of columns with a UNIQUE
constraint in the module schema (other than the key); `restore_conflicts(store, snapshot)` finds
backup rows whose unique value on the target is taken by a different record. A store with
`has_table(name)` (`SqliteModuleStore`) makes it possible to find backup tables that the module
on the target does not have.

## Forensic composition of the current modules (Alpha 2.829, updated by R-125)

- **inventory** (`farm_inventory.db`), **backup v2**: includes `inv_vendors/inv_filaments/
  inv_locations/inv_items/inv_spools/inv_ledger` + the `inv_settings` settings, and since v2 —
  mobile receiving: `inv_mobile_codes` (QR/barcode codes, including `nfc:bambu:<uid>`),
  `inv_mobile_nfc` (spool NFC tags), `inv_mobile_label_batches` and `inv_mobile_labels`
  (prepared labels; the label number is unique within a batch). The code on a label carries
  `inv_settings.mobile_server_id` — it is restored with the settings. Excluded:
  `inv_pending_prints` (runtime print tracking) and `inv_mobile_ops` (receipts for repeated phone
  requests). Migration v1→v2 adds the mobile tables empty: an old backup does not touch them.
  Spool assignments are by stable printer ID; a missing printer does NOT delete the spool (a
  warning in the plan, the assignment is kept in the data).
- **cost** (`farm_cost.db`). **backup v1** described the former "Print cost" module:
  `cost_config` (settings), `cost_printer_settings`, `cost_calculations`; `cost_run_durations`
  (print history) is excluded. Since 3.0 the same id is used by Order calculation (owner's decision
  of 12.09.2026), and **backup v2** describes its actual schema (`modules/cost/backend.py`, DDL):
  `order_config` (settings in the `global` row; an ordinary table — it has `updated_at NOT NULL`),
  `order_model_rates`, `order_printer_rates`, `order_printer_models`, `order_sequence`, `orders`.
  **`order_files` is not included**: its rows describe copies of model files in `cost_order_files\`
  by absolute path, and the backup does not carry files (attachments are container format v3,
  owner's decision); an order is restored without files, and the backup window says so. Special
  rules: an order number (`orders.order_number`, UNIQUE) that is taken on the target by a
  DIFFERENT order blocks restoring the module at the plan stage; the `order_sequence` counter is
  applied as MAX(current, from backup) and verified as "not less", so that numbers do not repeat.
  Migration v1→v2 carries the data of the former "Print cost" module as is into
  `extensions["x-legacy_cost_v1"]` and does NOT apply it (the 3.0 module does not create those
  tables): an old 2.x backup no longer rolls back the whole restore, and the plan says "Data of the
  former Print cost module in this backup is not restored".
- **quality** (`farm_quality.db`): **no_persistent_user_data** — proven: 0 write routes
  (all 4 are GET), all columns of `print_runs/print_run_materials/print_run_event_aliases` are
  captured automatically from print events = the PRINT HISTORY log, which restore is forbidden to
  change. There are no attachments ⇒ container v3 is not required (decision A of STAGE 5).
- **messengers** (`farm_messengers.db`): `msg_settings` settings without bot keys
  (`msg_secrets` is not included); on another computer the channels are connected again.
- **appearance** (Appearance and themes, 3.0): **no_persistent_user_data** — an interface-only
  module: no backend, database or routes; themes are stored in the browser (`localStorage`, keys
  `fm_appearance_*`). Without a classification, installing it would block a full export
  (fail-closed) — this was caught by a check on a real server on 12.09.2026.
- **camera_wall** (Camera Wall, R-125): **no_persistent_user_data** — there is no `backend.py`,
  so there is neither a database nor routes; camera sources, selection and layout are stored in the
  browser (`localStorage`, keys `3diwell.camera_wall.*`). Before it was classified, an installed
  Camera Wall blocked a full export (409 `manual_resolution_required`). Registry completeness is
  checked against the real modules: `modules/*/module.json` and
  `app/module_catalog.KNOWN_MODULE_RELEASES` (`tools/test_module_backup_contract.py`).

## Referential integrity (Alpha 2.830)

- **Structural integrity is fatal**: row is an object, non-empty key, key uniqueness, types,
  string length. A violation = real snapshot corruption → `validation_failed`.
- **Internal references (`refs`) are ADVISORY, NOT fatal**: a non-empty reference to a MISSING
  record (the user deleted a location/filament, while an item/spool still refers to it) is a
  LEGITIMATE state of a live database, not corruption. Such a record **is kept as is** (the value
  is NOT nulled and NOT replaced with a default), the link is considered inactive; the plan
  reports `dangling_internal_ref` (a count, without values). The same principle as for external
  references to printers (`missing_printer_ref`). This is the root cause of the Alpha 2.829 defect
  (`validation_failed: broken ref inv_items.location_id -> inv_locations` on a real user backup):
  the strict check rejected valid data and made the backup unrestorable.

## Export self-check — a PERMANENT invariant (Alpha 2.830)

**`export_success => same-version inspect/validate/plan_success`.** Before handing out the file,
export MUST perform a full reverse pass over the actual bytes of the backup with the same code as
restore (`app/config_backup/self_check.py`): decode → migrate → validate → `build_full_plan`
against the current state → the plan does not require manual_resolution for its own state. If the
check fails — **the file is not created**, the user sees a clear message, `audit` records
`validation_failed` (NEVER `result=ok` on an invalid backup). Farm Manager has no right to hand out
a backup that it cannot read itself.

## Safe validation errors (Alpha 2.830)

`BackupError` NEVER escapes as an unhandled 500. Only a structured safe response goes out:
`reason` (code) + `stage` (parse/migrate/plan/apply/self_validation) + `section`
(core|printers|modules) + `module_id` + `field_path` (schema path "table.column"). NEVER values,
secrets, file system paths, traceback, raw SQL or payload fragments. The UI shows a clear text
with the module name (for example "…failed data validation for module "Inventory". Nothing was
applied"), and the "Retry check" button repeats ONLY inspect/plan, not apply.

## Restore semantics

- **UPSERT by stable keys**; records that exist "only on the current machine" are NOT deleted.
- **Old backups (payload v1, 2.827–2.828) do NOT contain module_data**: the section is migrated as
  **ABSENT (None)**, not empty — module data on the target is **not cleared and not replaced**;
  the plan states explicitly: "Module data is absent in this backup version and will not be
  changed". A "replace with empty" migration is forbidden forever.
- **Missing module**: if the backup has data for a module that is not installed — the plan shows
  "Restoring the data requires the module <id>", full restore is blocked
  (`manual_resolution_required`); the user installs the module or explicitly excludes the section.
- **Module data does not fit this installation (R-125)** — the same refusal, but BEFORE any
  changes, not as a rollback of everything in the middle of applying: `module_not_initialized`
  (the module's database file does not exist on the target — the module has never run: enable it
  and restart), `module_tables_missing` (the backup has rows of a table that the module on the
  target does not have — the module is older than the backup) and `module_restore_conflict` (a
  unique value is taken by another record). The plan shows the reason, the apply response carries
  `module_id` and `field_path` (table/column name, without values).
- **Way out of a block**: the plan carries `module_data.blocked_modules` (modules that block the
  restore) and `module_data.excluded` (excluded by the `exclude_modules` request). The backup
  window offers "Restore without the "…" module": the plan is rebuilt with
  `exclude_modules=[id]`, and apply runs with the same list — the excluded module's data on the
  target does not change.
- **Rollback from a journal of a previous build**: `SqliteModuleStore.restore_full` does not touch
  tables (or settings) that are not in the pre-image. A journal left by a build with a different
  set of tables does not wipe tables that appeared in the new specification (orders, QR/NFC codes).
- **Pre-image — all columns** (16.10.2026, R-151): `SqliteModuleStore.full_snapshot` reads rows of
  the spec tables with `SELECT *` (bytes — `{"$b64": …}`), `restore_full` inserts the intersection
  of the row's columns with `PRAGMA table_info`. Rolling back a failed restore no longer drops
  columns that a newer module version added and the core provider does not know about yet. Export
  still reads only the specification columns; a journal in the previous format is restored as before.
- **Module schema newer than the reader** → safe refusal of the section/atomic set, no guessing.

## Sign-in protection during restore (R-128, arch-auth-07)

Users are not part of the backup. Therefore a backup with sign-in protection enabled, restored on
a computer without an active administrator, does NOT enable protection: the plan marks the
`security_enabled` key as `held` and says "The backup has sign-in protection enabled, but this
computer has no administrator. Protection stays off…" (`security_held_no_admin`), and apply does
not write this key. A failure of the administrator check counts as "no". The rule is the same for
plan and apply (`restore_plan.security_hold_keys`); a store without `enabled_admin_state` (test
store) behaves as before. If restore actually changes the protection flag (in either direction),
both the plan and the apply result require a restart — the process reads the flag only at
startup, and without a restart the change would take effect silently later.

## Multi-store atomicity

The core and modules are different files; one SQLite transaction does not cover them. Before
applying, the restore journal stores a **pre-image of every store + SHA-256**. The apply order is
documented: `core → modules (by module_id)`; rollback is strictly **reversed**, **all** selected
stores are rolled back (including the one that failed in the middle of apply); every rollback is
verified against the pre-image SHA. States:
`prepared → staging_modules → applying_core → applying_module:<id> → committed_pending_verify →
verifying_core → verifying_module:<id> → complete` (failure → `rolling_back_module:<id> →
rolling_back_core → complete|rollback_required`). It is impossible to end up with "core restored +
Inventory old" or vice versa. Pre-images are wiped only after the overall verification. A
physical database snapshot is allowed ONLY as an internal rollback mechanism; the canonical user
backup is logical. An archive of the whole DATA_DIR is **not** a user backup.

## Frozen fixtures

`tools/fixtures/config_backup/module_data/` — a frozen payload v2 fixture with module_data
(synthetic, SHA-256). Immutable after release; auto-enumerated by
`test_config_backup_compatibility_forever.py` together with v1/v2.
