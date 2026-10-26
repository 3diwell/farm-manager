[Русский](BACKUP_FORMAT_V2.md) · **English**

# Configuration backup format `.3diwell-backup` — version 2

**Status: FROZEN after the Alpha 2.828 release. A permanent public contract.**
The extension is the same — `.3diwell-backup`. The container version is distinguished by the
`container_format_version` field in `header.json`, NOT by the extension or the payload content.

- **v1 ([BACKUP_FORMAT_V1.en.md](BACKUP_FORMAT_V1.en.md)) is NOT changed** and is readable forever.
- **v2 is the new primary container for new exports.** It changes only the packaging and the
  protection mode; the LOGICAL payload model is the same (the same `serializer`, the same `payload_schema_version`).
Compatibility rules — [BACKUP_COMPATIBILITY_CONTRACT.en.md](BACKUP_COMPATIBILITY_CONTRACT.en.md).

## Why v2

The mandatory password of v1 is excessive for the owner's local scenario. v2 makes creating a
backup **without a password** the primary simple mode, and password protection an additional
option. The v1 format (always encrypted) remains fully compatible.

## Outer container (`container_format_version = 2`)

A ZIP with exactly two entries with fixed names:

| entry         | content                                                           |
|---------------|-------------------------------------------------------------------|
| `header.json` | NON-secret metadata + protection mode (+ encryption parameters for password) |
| `payload.bin` | canonical JSON (mode=none) OR ciphertext (mode=password)           |

Strict parsing (`app/config_backup/container_v2.py`, reuses the safe v1 primitives): exactly two
entries, strict names, no extra/repeated entries, path traversal, symlinks, nested archives or
password-protected ZIP; the same size limits and anti-bomb protection as v1. Data from a backup is
**never executed**.

### `header.json` (non-secret, both modes)

```json
{
  "format_id": "com.3diwell.farm-manager.configuration-backup",
  "container_format_version": 2,
  "backup_id": "<random non-secret id>",
  "created_at": "2026-07-24 12:00:00 UTC",
  "created_by_app": "3DIWELL Farm Manager Alpha 2.828",
  "payload_schema_version": 1,
  "sections": ["core", "printers", "modules"],
  "printer_count": 3,
  "module_count": 0,
  "protection_mode": "none",
  "payload_encoding": "canonical-json-utf8",
  "payload_length": 1234,
  "payload_sha256": "<hex, over the CLEARTEXT payload>",
  "required_reader_capabilities": ["cleartext-json-v2"]
}
```

For `password_aes256gcm`, additionally:

```json
  "required_reader_capabilities": ["aes256gcm-scrypt-v1"],
  "encryption": {"kdf": "scrypt", "n": 32768, "r": 8, "p": 1,
                 "salt": "<b64>", "cipher": "AES-256-GCM", "nonce": "<b64>"}
```

`header.json` (in BOTH modes) **contains no** user data: no printer names/IPs/credentials and no
setting values. `payload_length`/`payload_sha256` are computed over the CLEARTEXT canonical
payload (in password mode they are bound via the AAD).

## Protection modes

### `none` (default, no password)

- `payload.bin` — canonical UTF-8 JSON of the logical model (cleartext inside the ZIP).
- **No password is requested.** Using an empty password to derive an AES key is **forbidden**.
- `payload_sha256` and the ZIP CRC protect against **accidental** corruption — but **NOT** against
  deliberate tampering (anyone can change the cleartext and recompute the SHA).
- The importer **must re-run** full schema/value/security validation (data from a backup is data,
  not commands; claims are not trusted).
- **User warning (always visible in the UI):** a backup without a password contains printer
  connection settings; the file must be kept in a secure place.

### `password_aes256gcm` (optional)

- `payload.bin` — ciphertext. The same proven stack as v1: scrypt (n=2^15, r=8, p=1) → AES-256-GCM,
  random salt/nonce, **AAD = canonical header bytes** (GCM provides authenticated integrity).
- The password is entered and **confirmed twice**; export is blocked if they do not match.
- A wrong password and corruption produce **one** safe code (no oracle).
- The password is never stored/logged/sent to a printer; a lost password cannot be recovered.

Forbidden: an empty password as a key, a fixed application password, a shared secret in the EXE, an
auto-generated key next to the backup, DPAPI as the only method (the backup moves to another
computer), passing off an unencrypted payload as protected, XOR/ZIP-password/Fernet/home-made crypto.

## Import (v1 and v2)

The mode is determined from the **safe header**, not from the extension or whether the payload
contains text:

- **v1** → always asks for a password (`requires_password=true`).
- **v2 `none`** → no password is shown or required.
- **v2 `password_aes256gcm`** → asks for a password.

The first step reads ONLY the header (`inspect`). A container from a future version
(`container_format_version` > supported) and an unknown `protection_mode` → safe refusal
**without partial application**. Restore stays atomic (plan → confirmation → apply with a
rollback journal → verify), only for system-admin and locally (loopback); forbidden during an
active print; the rate limit on decryption attempts applies only to password mode.

## Frozen v2 fixtures

`tools/fixtures/config_backup/v2/`: `passwordless_v2.3diwell-backup` + `protected_v2.3diwell-backup`
+ `fixture_manifest.json` + `.sha256`. After publication **do not change or regenerate**.
`test_config_backup_compatibility_forever.py` **auto-enumerates** v1 and v2 and requires each to
restore forever; changing any file/hash turns the test red.
