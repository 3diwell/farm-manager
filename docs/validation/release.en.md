[Русский](release.md) · **English**

# Release: full gate, version, build

Read this **only when the task really requires a release** — that is, when the result
is handed to the owner for installation or a critical area is affected
([critical-runtime.md](critical-runtime.en.md)).

A routine change does **not** require a release. What to run and when — CLAUDE.md §3.

## 1. Full release gate

**It is run at the owner's word** (his decision of 04.09.2026). Before a build that he will
install himself or hand to a beta tester, I offer a run and wait for the answer — there the cost of an error is his.

```bash
python tools/release_gate.py          # the whole suite; --list prints the manifest without running anything
```

The runner **is not changed and not relaxed**. It does the following by itself:

- builds a manifest with no exclusions (all `tools/test_*.py` and `tools/test_*.mjs`);
- saves separate `stdout` and `stderr` for every file, `manifest.json`, `results.json`
  (written after every file), `summary.json`, `runner.log` in
  `C:\3DIWELL_Builds\logs\release_gate_2.841\<run-id>\` — **outside the repository**;
- counts the result strictly: machine-readable line → mutation summary → exact summary form →
  line-by-line protocol. **An unrecognized format = `unknown` = red**, it never becomes zero;
- gives the suites a temporary folder **on the repository's drive** (`gate_tmp_dir`) when the system
  `TEMP` is on a different drive. Otherwise some suites fail in `os.path.relpath`
  ("path is on mount 'C:', start on mount 'D:'") before their own checks: they do not run
  at all, and the gate shows them red — a real breakage inside would go unnoticed.
  The directory is created next to the project folder (`_3diwell_gate_tmp`), and its name does NOT start
  with the repository path: sandbox suites check themselves with the conditions "REPO not in ROOT" and
  "not ROOT.startswith(REPO)", so a name like `<repository>.gate_tmp` breaks seven previously
  green suites. Temporary files must even less be placed inside the repository — the hygiene check
  will catch them. If the system `TEMP` is already on the right drive, no substitution happens.
  The rule is pinned by the suite `tools/test_release_gate_tmp_isolation.py`.

`rc = 0` is allowed only when all of these are zero: red, unknown, error, timeout, excluded, fail_checks,
skip_checks, unknown_skip_files, internal_mutation_failures, mutation_not_applied,
unexpected_green, restore_failures, cleanup_failures.

Reference figures: **304 files, about 1 h 25 min** (13.10.2026); most of the time is taken by mutation proofs.

**Mutation proofs modify repository files.** The shared lock `tools/_mutation_lock.py` serializes
runs; a parallel launch has already led to one run's rollback overwriting another's.
During a run `git status` shows other runs' mutations — do not trust it and do not edit anything.

## 2. Version

`APP_VERSION` in `server.py` is **the single source**, format `"Alpha <major>.<minor>"` or
`"Beta <major>.<minor>"` (since 12.09.2026 — `"Alpha 3.0"`, since 25.10.2026 — `"Beta 3.71"`;
parsers read the number as a pair of integers and accept both prefixes). Always read the number
from the file, not from memory.

**When to bump it — per CLAUDE.md §8** (on every code change;
the version freeze via the `.ai/VERSION_FREEZE` file is described there too).
Only WHAT to update in sync is described here:

- `3diwell-setup.iss` and `3diwell-client-setup.iss` — `#define AppVersion`
- `desktop_shell_version_local.txt` and `desktop_shell_version_client.txt` — `filevers`,
  `prodvers`, `FileVersion`, `ProductVersion`

Five places in total. There is no separate `CHANGELOG.md` file in the repository; the "What's new" log
lives as the `CHANGELOG` constant inside `server.py` (new entries on top).

## 3. Build

**The whole release — with one command (since 3.0):**

```bash
python tools/build_release.py
```

It does, in order: three EXEs (the server — with the system Python from `3diwell.spec`, the shells —
with the `buildenv` interpreter from `desktop_shell.spec`), the `e2e-supported.txt` attestation,
packaged proof (§4), reconciliation of license texts (below), the "folder without write permission" stand (§4), both
Inno Setup installers with the bundled Windows components, a rebuild of all module ZIPs and the release
folder `C:\3DIWELL_Builds\Release_<version>\` with the installer, modules, `ПРОЧТИ МЕНЯ.txt` (the user README),
`BUILD_ENVIRONMENT.txt` (what it was built with, without computer paths) and `SHA256SUMS.txt`. A red step
stops everything. Options: `--skip-exe` (EXEs are already in staging), `--no-stand` (no stand — the build
is not considered verified). It does not start the full run (§1). Paths can be overridden with the
variables `FM_BUILD_ROOT`, `FM_VENDOR_DIR`, `FM_SHELL_PYTHON` (docs/dev/building.md).

**License texts of third-party packages (R-130, 29.09.2026).** The installer puts every `*.txt` from
`packaging/installer/licenses` into the `licenses` folder next to the program, including
`THIRD_PARTY_LICENSES.txt` — the license texts of all Python packages inside the three EXEs. The file
is tracked in git; the build does NOT write it but reconciles it: `tools/collect_third_party_licenses.py`
reads the contents of every EXE (the server — with the system Python, the shells — with `buildenv`) and compares them with the
file. If they do not match (a package was updated), the release stops and prints the update command;
update, commit and repeat `python tools/build_release.py --skip-exe`.

**Windows components for the installer** live outside the repository in `C:\3DIWELL_Builds\vendor`:
`MicrosoftEdgeWebView2RuntimeInstallerX64.exe` (~210 MB) and `ndp48-x86-x64-allos-enu.exe`
(~120 MB). Where to get them and how to verify the Microsoft signature — in the header of
`tools/installer/prereqs.iss`. Without them the release build stops (`/DReleaseBuild`);
an ordinary `.iss` compilation does not break without them — it just skips the components step.

**Do not run `build.bat` from the agent** — it contains `pause` and deletes the working `dist\`.
To build manually step by step, staging goes outside:

```bash
python -m PyInstaller --noconfirm --clean \
  --distpath "C:/3DIWELL_Builds/Beta_<version>/dist" \
  --workpath "C:/3DIWELL_Builds/work/<version>/server" 3diwell.spec

"C:/3DIWELL_Builds/buildenv/Scripts/python.exe" -m PyInstaller --noconfirm --clean \
  --distpath "C:/3DIWELL_Builds/Beta_<version>/dist" \
  --workpath "C:/3DIWELL_Builds/work/<version>/shell" desktop_shell.spec

ISCC.exe /DDistDir="C:\3DIWELL_Builds\Beta_<version>\dist" /DReleaseBuild /O"<output folder>" 3diwell-setup.iss
```

The server is built with **the system Python**, the shells — with the `buildenv` interpreter.
**Do not overwrite the working `dist\*.exe`** — the owner replaces them manually.

`buildenv` does not move between computers: after a transfer over USB, `pyvenv.cfg` keeps
foreign paths, and they are fixed manually.

## 4. Packaged proof

After the build — prove that the new code is **inside** the EXE: unpack the archive, extract the code objects
and check function names and constants. A check against the outer TOC is false in both directions: `fastapi`,
`uvicorn` and the `app/*` modules live in the PYZ.

**Do not run the server EXE WITH ARGUMENTS** — it has no version flag, and any unrecognized
argument will start the whole program.

### Launch from a folder without write permission — MANDATORY

The "code is inside the EXE" proof alone is NOT ENOUGH. On 02.09.2026 build 2.939 passed packaged
proof 25 out of 25 and was handed to the owner — and did not start for him at all: the server crashed at
`server.py:769` with `PermissionError [WinError 5]` while trying to create `thumb_cache` inside
`C:\Program Files\3DIWELL Farm Manager`. On the development machine the build lives in an ordinary folder,
so no static analysis saw this.

The condition is reproduced like this (a stand that changes nothing in the system):

1. a temporary folder, and in it `icacls <folder> /deny "%USERNAME%":(WD,AD)` — the right to create files
   and subfolders is removed; make sure that `os.makedirs` inside it really fails;
2. put the built `3DIWELL Farm Manager.exe` there and run it **without arguments**, pointing
   `LOCALAPPDATA` and `APPDATA` at the temporary folder — the owner's real databases are not involved;
3. after 20 seconds stop the process by its PID and remove the deny rule.

Only this counts as green: the process survived to the end of the countdown, the log contains the line
`lifespan: YIELD`, and there is no `PermissionError` in the output. A good habit is to run the PREVIOUS
build through the same stand: it must behave the same way, otherwise the stand proves nothing.

The static guard on the same topic is `tools/test_program_folder_not_written.py` (in the full
run). It catches a code change, the stand catches an environment change; both are needed.

Separately, take the SHA-256 of the three EXEs and confirm that the working `dist\*.exe` have not changed.

## 5. Modules

`modules/<id>/*` changed → bump `"version"` in `module.json`, rebuild the zip
(`tools/build_<id>_zip.py`) and tell the owner to reinstall the module.
Details — [modules.md](modules.en.md).

## 6. What is recorded on completion

- One line in `.ai/action_log.jsonl`.
- One commit per task; a separate handoff commit — only if the task explicitly requires it.
- `.ai/CURRENT_STATE.md` is updated **only if the state described there has changed**.

Which profile a specific change needs — [profile-selection.md](profile-selection.en.md).
