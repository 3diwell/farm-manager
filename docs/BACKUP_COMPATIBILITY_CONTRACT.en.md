[Русский](BACKUP_COMPATIBILITY_CONTRACT.md) · **English**

# Backup compatibility contract — IMMUTABLE RULES

**Introduced in Alpha 2.827. Mandatory in all future versions.**

A configuration backup is a promise to the user: *a backup taken today will be restored by the
application years from now, and after a major version change.* The farm runs in production — the
price of breaking the contract is lost user settings and lost printer access. The rules below
protect that promise. They take precedence over code convenience.

Specification of the first format: [BACKUP_FORMAT_V1.en.md](BACKUP_FORMAT_V1.en.md).

## Rule 1. A published format is immutable

Once a format version (`container_format_version`, `payload_schema_version`, a section or adapter
schema) is released, the meaning of its bytes is **frozen forever**. Fields must not be redefined,
units must not change, names must not be reused for a new meaning, and parsing of an old version
must not be made stricter.

## Rule 2. Changes only by bumping the version + a migration

Incompatible structure → **increment** the corresponding version and **ADD** a migration
`vN → vN+1` in `app/config_backup/migrations/`. Section/adapter versions grow independently and
are **never** equal to `APP_VERSION`.

## Rule 3. Migrations are append-only, pure, deterministic

- Migrations are only **appended**: `v1→v2`, `v2→v3`, … A published migration must **never** be
  rewritten or deleted.
- A migration is a pure `dict → dict` function: no time, network, randomness, database or `server.py`.
- New fields get default values; the meaning of old fields does not change.
- This way a v1 backup is brought to the current schema by the chain `v1→…→current` **without
  any old code**.
- A missing migration in the chain → an explicit `migration_missing` error, not silent corruption.

## Rule 4. Frozen fixtures are untouchable

`tools/fixtures/config_backup/vN/` holds reference backups taken once. Their SHA-256 is pinned.
**Never change or regenerate a published fixture.** For every released format version the fixture
must exist forever, and `test_config_backup_compatibility_forever.py` must restore it forever. A
red compatibility test is fixed **by adding a migration to the CODE**, not by editing the fixture.

When releasing a new format version: add a NEW fixture in a new `vN+1/` folder, keeping all the
previous ones.

## Rule 5. Every persistent setting is in the registry

Any new persistent user setting of the core is registered in
`app/config_backup/settings_registry.py` with a classification (portable / machine_bound /
operational / secret_derived and the restore behavior). Otherwise
`test_config_backup_contract.py` turns red: the backup would silently lose the setting.

## Rule 6. Security over convenience

- **Credentials are never stored in cleartext.** Secrets (printer tokens/checkcode/API keys) —
  only inside AES-256-GCM.
- **The backup password** is never stored, logged or sent in requests to printers.
- **A lost password cannot be recovered** — the UI must warn about this honestly.
- **No oracle:** a wrong password and corruption are indistinguishable (a single code).
- **New destructive/network features are imported as OFF** (for example,
  `printer_files_delete_enabled`).
- Data from a backup is **data, not commands**: it is never executed; the container is parsed strictly.
- Export/restore — only system-admin and only locally; restore is forbidden during an active
  print; it is applied atomically with a rollback journal.

## Rule 7. The crypto contract uses only proven primitives

scrypt + AES-256-GCM from the `cryptography` library. No home-made cipher, XOR, Fernet,
ZIP password or "HMAC only". If AES-GCM cannot be safely embedded in a future environment, backup
**stops** (no cleartext "backups").

## Rule 8. Container versions v1 and v2 are permanent (Alpha 2.828)

- **container v1 (payload.enc, always encrypted) is NOT changed** — not the format bytes, entry
  names, crypto, KDF parameters, header structure, payload semantics, reader v1, frozen fixture v1,
  its SHA-256, the test passphrase, published migrations or the meaning of the v1 document.
  **v1 is readable forever.**
- **container v2 (payload.bin) was added as the new primary container.** After the Alpha 2.828
  release it is also **frozen**: reader v2 stays forever, specification —
  [BACKUP_FORMAT_V2.en.md](BACKUP_FORMAT_V2.en.md).
- **Both readers (v1 and v2) are permanent.** A reader must exist for every released container
  version; removing any reader turns the compatibility test red.
- **An incompatible change — only as a NEW container version** (v3 …), not by editing v1/v2.
- **Mode `none` (no password) contains sensitive connection data** — this is a deliberate
  contract; the UI must warn honestly, and the importer must re-validate (SHA/CRC only protect
  against accidental corruption, not against tampering).
- **No silent conversion** between protected and unprotected modes: the user chooses the mode.
- **Historical fixtures of all versions never change** and are **auto-enumerated** by the
  compatibility test (`vN/` folders are picked up automatically; a changed file/hash turns the
  test red).

## Rule 9. Module data and immutability of projects/jobs (Alpha 2.829)

- **Payload schema v2** added the `module_data` section (module settings + user data). Containers
  v1/v2 were NOT changed; the payload version lives in the manifest and is migrated by an
  append-only chain.
- **Old backups without module_data** (payload v1, 2.827–2.828) are migrated with the section
  **ABSENT (None)** — module data on the target is NOT cleared and NOT replaced with empty;
  "replace with empty" semantics are forbidden forever.
- **Every persistent module must have a permanent versioned provider**
  ([MODULE_BACKUP_CONTRACT.en.md](MODULE_BACKUP_CONTRACT.en.md)); silently skipping a module is
  forbidden — a full export without a provider is blocked, naming the module.
- **Module-backup schemas are permanent**, module migrations are append-only, module fixtures are
  immutable.
- **Projects/jobs/project files/managed storage/print history** are not part of the backup and
  restore does not change them: fingerprint before/after, any mismatch → full rollback.
- **Multi-store restore is one operation**: a pre-image of every store, order core→modules,
  rollback of all stores in reverse order, verify of every rollback.
- **A physical archive of DATA_DIR is not a user backup** (it bypasses migrations, carries
  machine-bound paths/runtime; allowed only as an internal rollback pre-image).

## Checks guarding the contract

| test | what it guarantees |
|------|-----------------|
| `test_config_backup_contract.py` | crypto (round-trip, no-oracle, no-leak, KDF bounds), strict container, registry completeness, serializer types/exceptions |
| `test_config_backup_v1.py` | frozen v1 format constants, validator (rejects future versions, duplicates), append-only migrations |
| `test_config_backup_v2.py` | v1 regression, v2 structure, passwordless + protected modes, import by header, UI labels, restart, sentinel |
| `test_config_backup_restore_atomicity.py` | plan only reads; apply is atomic; failure → full rollback; journal complete after success; recovery at startup |
| `test_config_backup_compatibility_forever.py` | AUTO-enumeration of v1 and v2: every frozen fixture always restores (SHA-256 + end-to-end restore) |
| `test_config_backup_mutation_proof.py` / `_v2_mutation_proof.py` | breaking any invariant turns a test red (the tests are not vacuous) |
