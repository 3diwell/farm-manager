[Русский](backend.md) · **English**

# Backend validation

Read this **only when you are editing** `server.py` or `app/**`.
What to run and when — CLAUDE.md §3.

## Required minimum after an edit

```bash
python -c "import py_compile; py_compile.compile('server.py', doraise=True)"
python -m py_compile app/*.py            # if they changed
```

Then run the existing tests directly related to the changed function
(find them with `grep -l "<function_name>" tools/test_*.py`).

## Landmarks in `server.py`

| What | Anchor |
|---|---|
| Version | `APP_VERSION = ` |
| "What's new" changelog | `CHANGELOG = ` (new entries go on TOP) |
| SQLite schemas | `def init_db` |
| Database placement in DATA_DIR | `_resolve_db(` |
| 🔒 the **single** point that sends a file to a printer | `_send_file_to_printer` |
| Print start (project / part) | `_do_project2_file_print`, `"/api/part/print"` |
| Plugin module system | `class ModuleCore`, `_load_modules`, `"/api/modules` |
| Klipper idle state before start | `_KLIPPER_IDLE_STATES` |

`app/` holds the modules extracted from the core (`utils.py`, `diagnostics.py`, `import_worker.py`,
`model_compat.py`, `part_contours.py`, `part_counter.py`, `klipper_*.py`,
`project_orchestrator.py`, `printer_files/`, `config_backup/`). New "cold" blocks
are extracted there as well.

## Pitfalls confirmed in practice

- **False-green offline tests.** A test that imports `server.py` calls `sys.exit(0)` on the named
  mutex BEFORE any checks when the program is running. `exit 0` ≠ PASS. Encoding: set
  `PYTHONIOENCODING=utf-8`, otherwise cp1252 produces a false `exit 1`.
- **The running process lags behind the disk.** An edit to `server.py` takes effect only after a manual
  restart; compare `/version` with `APP_VERSION` before relying on "release confirmed".
- **A "substring in the source" check catches its own prose** — docstrings and comments produce
  false matches. Count calls or parse the AST; a mutation run is mandatory.
- **Line endings are NOT normalized and NOT guaranteed.** `.gitattributes` stores files
  byte for byte (`* -text`), so whatever endings were committed are what you get. Checked on
  22.08.2026: `server.py` used to be entirely CRLF, and since Alpha 2.863 it is LF (it flipped during an
  edit of the "What's new" changelog). Measured the same day: everything is LF except two files;
  `app/project_orchestrator.py` and `web/app.css` remained CRLF.
  **Assuming line endings is forbidden — determine them from the file itself.** A multi-line anchor
  written with `\n` is NEVER found in a CRLF file, and the corruption silently turns into a "harness
  failure": that is how two suites lost 3 of 34 and 7 of 22 corruptions, staying red and proving
  nothing. The right way is to fit the anchor to the EOL of the specific file (`_fit_eol`,
  counting `\r\n` in the source, or the fallback "not found — try CRLF");
  check D3 in `tools/test_mutation_proof_exit_contract.py` enforces this.
- **Installer PowerShell scripts are ASCII only** (Cyrillic breaks PS 5.1).

## Printer protocols (🔒, verified on hardware)

- **Bambu FTPS** — `storbinary` WITHOUT `conn.unwrap()` (Bambu does not send TLS close_notify);
  P1 path `file:///mnt/sdcard/`; H2D/H2S/P2S use the `ftp:///` scheme.
- **FlashForge AD5M** — `POST /uploadGcode`, all metadata in HTTP headers, multipart
  with a single field `gcodeFile`, `Expect: 100-continue`.
- **Klipper/Moonraker** — upload and start in one POST; a read timeout after sending means
  PENDING, not a failure; automatic retry is forbidden.

Changing any of these paths is a critical area,
see [critical-runtime.md](critical-runtime.en.md).

Which profile a particular edit needs — [profile-selection.md](profile-selection.en.md).
