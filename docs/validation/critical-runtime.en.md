[Русский](critical-runtime.md) · **English**

# Critical areas: printing, data, backup

**Mandatory reading** if the task involves print start, the queue, recovery,
the database, migrations, shared/core, or the server runtime.

**These areas are subject to the full current validation cycle with no relaxations** — targeted
checks are not enough. See CLAUDE.md §3 and [release.md](release.en.md).

## 1. High-risk zone: printing

`PrintStartDialog` / `printStart`, the `sendJobs` indicator, the staged start queue
(`printQueue`), recovery after restart, `_send_file_to_printer` 🔒 —
change them **only under a direct task**, after rereading the 🔒 markers. Incidental edits are forbidden.

`_send_file_to_printer` is the **single** point that sends a file to a printer. Bypassing this point
is forbidden.

## 2. Data

- SQLite databases live in the protected `DATA_DIR` (outside the program folder): `farm_parts.db`,
  `farm_printers.db`, `farm_inventory.db`, `farm_quality.db`, `farm_cost.db`.
  The daily automatic backup goes to `DATA_DIR/backups`.
- Obtain database paths **only** through `_resolve_db` / `core.resolve_db` (migration and protection live there).
- New modules get their own database; do not touch other modules' tables.
- Do not change `DATA_DIR` by hand; database schema changes require explicit permission in the task text
  (see the permission policy).

## 3. Safety switches

`DISPATCH_ENABLED`, `TRANSPORT_ENABLED` (`app/project_orchestrator.py`),
`PRINTER_FILE_DELETE_ENABLED_DEFAULT` (`app/printer_files/security.py`) are `False` in the source.

**Check the effective state, not the source**: the owner's settings
(`config.json`, the `app_settings` table) raise these values at server start. Proof of "off"
is made by executing the decision function against the real config, not by reading the constant.

Turning the safety switches on yourself is forbidden.

## 4. Configuration backup contract

The `.3diwell-backup` format is a **permanent public contract**. Full rules:
[BACKUP_COMPATIBILITY_CONTRACT.md](../BACKUP_COMPATIBILITY_CONTRACT.en.md); specifications —
[BACKUP_FORMAT_V1.md](../BACKUP_FORMAT_V1.en.md), [BACKUP_FORMAT_V2.md](../BACKUP_FORMAT_V2.en.md),
[MODULE_BACKUP_CONTRACT.md](../MODULE_BACKUP_CONTRACT.en.md).
The pure core is `app/config_backup/` (crypto, containers and migrations do **not** import `server.py`).

- **Containers v1 and v2 are permanent.** v1 (payload.enc, always encrypted) never changes;
  v2 (payload.bin, modes none / password_aes256gcm) is frozen after release. A reader must exist
  for every container version. Incompatibility → a **new** version (v3…), not an edit of
  v1/v2. The version is determined by the header, not by the extension.
- **The `none` mode contains sensitive connection data** — a deliberate contract: the UI
  warns, the importer validates again. No silent conversion between protected and
  unprotected modes.
- **Historical fixtures of all versions never change** and are auto-enumerated by
  `test_config_backup_compatibility_forever.py`.
- **Self-check:** the invariant *export_success ⇒ same-version inspect/validate/plan_success* —
  export performs a full round trip (`app/config_backup/self_check.py`) **before** handing out the file;
  if it fails, there is no file, `audit=validation_failed`, never `result=ok`.
- A dangling **internal** reference is not corruption: the record is kept as is, the plan reports
  `dangling_internal_ref`. Only structural corruption is fatal. Only a structured
  safe response goes out; `BackupError` is never an unhandled 500.
- **Module data:** a module with user data must have a permanent
  versioned backup provider before release; silently skipping a module during export is forbidden
  (fail-closed with the module name). Module-backup schemas are permanent, migrations are append-only.
  An old backup without `module_data` **does not clear** module data.
- Projects, jobs, files and print history are not included in the backup; restore does not change them
  (fingerprint guard, mismatch → full rollback). A multi-store restore rolls back as a single
  operation. A physical archive of `DATA_DIR` is **not** a user backup.
- **The format is frozen.** Incompatibility → bump the version and **add** a migration
  (append-only, pure, deterministic). Do not rewrite a published migration.
- **Frozen fixtures are untouchable** (`tools/fixtures/config_backup/vN/`, SHA-256
  pinned). A red `test_config_backup_compatibility_forever.py` is fixed with a migration **in code**,
  not by editing the fixture.
- **Every new persistent core setting** is registered in
  `app/config_backup/settings_registry.py`, otherwise `test_config_backup_contract.py` turns red.
- **Security:** credentials only inside AES-256-GCM; the backup password is not stored, not
  logged and never sent to a printer; a lost password cannot be recovered; a wrong password and corruption
  are indistinguishable (a single code); destructive and network functions are imported as OFF; backup data is
  data, not commands. Crypto is only scrypt + AES-GCM from `cryptography`.
- **Boundaries:** export / inspect / restore — system-admin only and local only (loopback); restore
  is forbidden during an active print, one at a time, atomic with a rollback journal.
- **Validation:** the five `test_config_backup_*` tests must be green; when editing the core,
  run the corresponding mutation proof.

## 5. Klipper: recalibration and idle state

- The basis for "the operation is controlled by the file" is **only a command visible in the file**. The name of the start
  macro in the G-code header is not proof (root cause of Alpha 2.841).
- An unprovable start macro shifts calibration to Farm Manager rather than disabling it.
- Idle states before start: `standby`, `complete`, `cancelled`. `printing`, `paused` and an empty string
  are **not** considered idle.
- A read timeout after sending the start request = PENDING, not a failure. **Automatic retry
  is forbidden** — the operation goes into waiting for confirmation.

Which profile a particular edit needs — [profile-selection.md](profile-selection.en.md).
