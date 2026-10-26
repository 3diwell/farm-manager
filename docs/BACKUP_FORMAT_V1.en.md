[Русский](BACKUP_FORMAT_V1.md) · **English**

# Configuration backup format `.3diwell-backup` — version 1

**Status: FROZEN (Alpha 2.827). This document describes a PERMANENT public contract.**
Version values and the meaning of the bytes under them are immutable forever. Incompatible changes
are made ONLY by bumping the version and adding a migration — see
[BACKUP_COMPATIBILITY_CONTRACT.en.md](BACKUP_COMPATIBILITY_CONTRACT.en.md).

> V1 remains supported forever; new exports use V2 (see [BACKUP_FORMAT_V2.en.md](BACKUP_FORMAT_V2.en.md)). The meaning of v1 below does not change.

Pure implementation: `app/config_backup/` (crypto/container/migrations do not import `server.py`).
The storage adapter and routes are in `server.py`.

## Purpose

A logical, versioned, encrypted snapshot of the farm's USER CONFIGURATION: core settings and the
printer fleet (with identity and access). It is **not** a copy of SQLite, **not** a copy of
`config.json`, **not** a ZIP of the data folder and **not** a pickle. The backup is meant to
survive years and major application version changes.

## Outer container (`container_format_version = 1`)

A `.3diwell-backup` file is a ZIP with exactly two entries with strictly fixed names:

| entry         | content                                                           |
|---------------|-------------------------------------------------------------------|
| `header.json` | NON-secret metadata + encryption parameters (salt/nonce/KDF)       |
| `payload.enc` | ciphertext of the logical payload (AES-256-GCM)                    |

Strict parsing (`app/config_backup/container_v1.py`): exactly two entries, no extra/repeated
names, paths with `/`, `\`, `..`, symlinks, nested archives or password-protected ZIP; hard size
limits and anti-ZIP-bomb protection (compression ratio threshold). Data from a backup is **never
executed**.

### `header.json` (non-secret)

```json
{
  "format_id": "com.3diwell.farm-manager.configuration-backup",
  "container_format_version": 1,
  "payload_schema_version": 1,
  "created_by_app": "3DIWELL Farm Manager Alpha 2.827",
  "created_at": "2026-07-24 12:00:00",
  "printer_count": 3,
  "module_count": 0,
  "required_reader_capabilities": ["aes256gcm-scrypt-v1"],
  "encryption": {
    "kdf": "scrypt", "n": 32768, "r": 8, "p": 1,
    "salt": "<base64>", "cipher": "AES-256-GCM", "nonce": "<base64>"
  }
}
```

`required_reader_capabilities` — the list of capabilities WITHOUT which the backup must not be
read. An unknown required capability → safe refusal (unknown must not be treated as known).

## Encryption (frozen)

- **KDF:** scrypt (`cryptography.hazmat`), 256-bit output. v1 release: `n=2^15 (32768), r=8, p=1`.
  Bounds forever: `n ∈ [2^14, 2^20]` (floor against weakness, ceiling against DoS), `r ∈ [8,32]`,
  `p ∈ [1,16]`, `n` is a power of two.
- **Cipher:** AES-256-GCM.
- **AAD:** the canonical bytes of `header.json`. Tampering with any header field breaks decryption.
- **Salt and nonce** are random for EVERY backup.
- **Password:** UTF-8, **without** trimming and **without** Unicode normalization (the rule is
  fixed). An empty password is forbidden.
- **No oracle:** a wrong password and corruption produce ONE and the same code
  `backup_corrupted_or_wrong_password` — the error does not tell one from the other.
- **A lost password cannot be recovered.** The UI must warn about this honestly.

No home-made cipher, XOR, Fernet, ZIP password or "HMAC only".

## Logical payload (`payload_schema_version = 1`)

Inside `payload.enc` — canonical JSON (sort_keys, compact, UTF-8):

```json
{
  "manifest": {"payload_schema_version": 1, "created_by": "...",
               "include_secrets": true, "sections": ["core", "printers", "modules"]},
  "core": {"schema_version": 1, "values": {...}, "machine_bound": {...}, "extensions": {}},
  "printers": [{"stable_id": "...", "adapter": "bambu", "adapter_schema_version": 1,
                "display_name": "...", "model": "...", "enabled": true,
                "connection": {"ip": "...", "port": 8883, "gen": "auto", "serial": "..."},
                "options": {"order_idx": 0},
                "credentials": {"token": "<secret — only inside the cipher>"},
                "extensions": {}}],
  "modules": [],
  "extensions": {}
}
```

Section versions (`core`/`printers`/`module`) and adapter schema versions grow **independently** of
`payload_schema_version` and are **never** equal to `APP_VERSION` (that one is only metadata).

### What is carried over and what is not (registry `settings_registry.py`)

Every persistent core setting is classified (the test `test_config_backup_contract.py` turns red
if an unregistered key appears in `server.py`):

- **portable** → carried over (`core.values`): `lan_access_enabled` (with a network warning),
  `project_print_enabled`, `modules_disabled`, `net_monitor`, `security_enabled` (with a warning),
  `slicer_callback_enabled`, `printer_files_read_enabled`, `printer_files_delete_enabled`
  (**destructive → imported as OFF**).
- **machine_bound** → into `core.machine_bound`, **not applied** by default (paths/port of this
  machine): `data_dir`, `server_port`, `archive_dir`, `slicer_path`.
- **operational / secret_derived** → **excluded** from the snapshot: `pending_server_port`,
  `previous_server_port`, `migrate_from`, `slicer_callback_token_hash`,
  `slicer_callback_token_created_at`.

Secrets (printer `token`/checkcode/API key) are stored **only** inside AES-GCM — they exist
nowhere in cleartext. The `last_parts` cache (operational) is not carried over.

## Restore (state machine)

`READ → DECRYPT → VALIDATE → MIGRATE(in memory) → PLAN → CONFIRM → PRE-SNAPSHOT(journal) →
APPLY(atomic) → VERIFY → COMMIT | ROLLBACK`.

- **PLAN** — read-only: what will be added/changed per section, warnings (network/security/
  destructive), whether a restart is needed.
- **APPLY** — `config.json` atomically (temp+fsync+os.replace); `app_settings`/`printers` in
  SQLite transactions. A failure at any step → compensating rollback to the pre-image.
- **Restore journal** (`recovery.py`) lives in `DATA_DIR` and survives a process crash:
  `prepared → applying → committed_pending_verify → complete`; on failure `→ rollback_required →
  complete`. After completion the pre-image is **wiped** (secrets do not linger on disk).
- Printer identity (`stable_id`) is preserved; printers that exist "only on the current machine"
  are not deleted.

## Access boundaries

Export/inspect/restore — **only system-admin and only locally** (loopback). Restore is forbidden
during an active print and runs one at a time. The backup password is not logged, not stored and
not sent in requests to printers.

## Frozen fixture

`tools/fixtures/config_backup/v1/sample.3diwell-backup` — the v1 format reference (taken once).
`test_config_backup_compatibility_forever.py` requires every future version to restore it.
**The fixture must never be changed or regenerated** (it is checked against SHA-256).
