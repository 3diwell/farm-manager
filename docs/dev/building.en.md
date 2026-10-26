[Русский](building.md) · **English**

# Building

Status as of 16.10.2026. The program is a Python server (FastAPI + uvicorn) and a Vue interface without
a bundler: the files in `web/` are served as is.

## From source

**Python 3.14** is required (some checks do not work on 3.13).

```bash
py -3.14 -m pip install -r requirements.txt
py -3.14 server.py
```

Versions in `requirements.txt` are pinned exactly (`name==version`) — see "Pinned versions" below.

Interface — http://127.0.0.1:8000. Data — `%LOCALAPPDATA%\3DIWELL`. Bambu Lab cameras need
`ffmpeg.exe` next to `server.py` (it is not in the repository — see below).

## Server EXE

```bash
build.bat
```

`build.bat` installs the dependencies and PyInstaller at pinned versions (`requirements-build.txt`) and
builds the EXE from `3diwell.spec`. Note: it deletes the `build\` and `dist\` folders before building.

The version number in the EXE properties (Properties → Details) is taken by `3diwell.spec` at build time from
`APP_VERSION` in `server.py` via `tools/build_version_info.py` (since 16.10.2026, R-149): "Alpha 3.0"
→ 3.0.0.0, "Beta 3.71" → 3.71.0.0. The server has no separate version file — no new version locations were added. The window and the client
still keep their number in `desktop_shell_version_*.txt`, the installers in `VersionInfoVersion={#AppVersion}`.

Optional build inputs — they are not in the open repository, and the build succeeds without them:

| File | Without it | Where to get it |
|---|---|---|
| `ffmpeg.exe` | Bambu Lab camera streaming does not work | an FFmpeg build with a suitable license; include its license and a link to its source code with your build (official build — `packaging/installer/licenses/FFMPEG_NOTICE.txt`, check — `tools/test_license_files.py`) |
| `printer_covers/` | printer cards show placeholder icons | your own images with redistribution rights (the official ones come from OrcaSlicer, AGPL-3.0: `packaging/installer/licenses/PRINTER_IMAGES_NOTICE.txt`) |

## Program window and client

`desktop_shell.spec` builds the window shells (pywebview + WebView2). They need pywebview 6.2,
pythonnet 3.1, clr_loader, bottle, proxy_tools — these are not in `requirements.txt` (the server works
without them); they live in a separate `buildenv` environment and are pinned in
`requirements-desktop-shell.txt` (see "Pinned versions").
`tools/build_desktop_shell.ps1` builds both shells.

## Installers

Inno Setup 6: `3diwell-setup.iss` (the program) and `3diwell-client-setup.iss` (the client).
Prerequisites (.NET Framework 4.8, WebView2 Runtime) — `tools/installer/prereqs.iss`;
their installers are taken from the `/DVendorDir=...` folder and are not committed to the repository.

Testing the installer on a clean Windows without network access (R-109, 16.10.2026; a development tool, not
part of the release): `tools/installer/sandbox/fm-install-test.wsb` opens Windows Sandbox without
network access, the release folder is mapped read-only, `run_install_test.ps1` installs the program silently
and writes `result.json` to `C:\3DIWELL_Builds\sandbox_out` — checksums, what was present before installation (WebView2,
.NET) and what the installer added, files, firewall rules, port, server response and window. How to
run it is described in the script header. Outside the sandbox the script refuses to run. The "Windows
Sandbox" feature is enabled by the owner; the suite has not been run yet.

## Official release

`tools/build_release.py` — the whole official release chain: three EXEs, content checks,
license text verification, both installers, a release folder with modules. It expects a build
root outside the repository (`C:\3DIWELL_Builds` by default) and a separate shell environment; from
a clean checkout without them it will not pass. The release folder gets `BUILD_ENVIRONMENT.txt` — the Python
and package versions of both environments, Inno Setup, SHA-256 checksums of the Windows components and `ffmpeg.exe` (without
computer paths); its checksum is included in `SHA256SUMS.txt`.

Before PyInstaller (step 2, also with `--skip-exe`) the builder compares the packages of both Pythons with the pinned
versions and stops on any mismatch, printing the exact `pip install -r …` command. Only
this check, without building: `python tools/build_release.py --env-only`. After the build it also checks
the number in the properties of all three EXEs and both installers.

Paths are set with environment variables (without them, defaults are used):

| Variable | What | Default |
|---|---|---|
| `FM_BUILD_ROOT` | build root: staging, working folders, release folder | `C:\3DIWELL_Builds` |
| `FM_VENDOR_DIR` | installers of Windows components | `<FM_BUILD_ROOT>\vendor` |
| `FM_SHELL_PYTHON` | Python of the shell environment | `<FM_BUILD_ROOT>\buildenv\Scripts\python.exe` |

### Third-party license texts

`packaging/installer/licenses/THIRD_PARTY_LICENSES.txt` — the license texts of all Python packages
bundled into the three EXEs. The program installer places it in the `licenses` folder next to the program (like
the other `*.txt` files of that folder). The file is tracked in git and is assembled by
`tools/collect_third_party_licenses.py` from the contents of **the EXEs themselves**: the module list is read
from inside each EXE, and the modules are matched to the packages of the environment the EXE was built with. That is why each part
is run with its own interpreter:

```bash
python tools/collect_third_party_licenses.py --from-exe "<dist>\3DIWELL Farm Manager.exe" --part-out server.json
"<buildenv>\Scripts\python.exe" tools/collect_third_party_licenses.py ^
    --from-exe "<dist>\3DIWELL Farm Manager Desktop.exe" "<dist>\3DIWELL Farm Manager Client.exe" --part-out shell.json
python tools/collect_third_party_licenses.py --assemble server.json shell.json ^
    --out packaging/installer/licenses/THIRD_PARTY_LICENSES.txt
```

`build_release.py` does the same after checking the EXE contents, but with `--check`: if the file
does not match the build (a package was updated), the release stops and prints the exact update
command. The build itself writes nothing to the repository.

The collector tells the project's own names apart from packages as follows: root `*.py` modules, Python package folders and
data folders. A data folder whose name matches an installed package is not treated as the project's own — otherwise
the `packaging` package (bundled into all EXEs) would be lost because of the project's `packaging/` folder.

### Release description on the website (latest.json)

Every few hours the program reads `https://3diwell.com/farm/latest.json` (this is turned off in
Settings → General → Program). While the `RELEASE_KEYS` list in `app/licensing/trust.py` is empty,
the old plain file `{"version", "url", "notes"}` is accepted.

Switching to a signed file: create a release key (`tools/fm_license_tool.py keygen --purpose
package`, the private part kept outside the project), put the PUBLIC part into `RELEASE_KEYS`, build the release,
sign its description with `tools/fm_license_tool.py sign-release ...` and publish the result at the same
address. The signed file carries a top-level copy of `version`, `url`, `notes` — it is read by releases that
users already have (Alpha 3.0 and earlier), so they keep seeing the new version. New releases
verify the signature and reject a file whose top-level fields differ from the signed ones; they must not be edited
by hand. The link in the file may only be `https://3diwell.com/...` or `https://www.3diwell.com/...`
(`ALLOWED_HOSTS` in `app/update_manifest.py`); a website redirect to another host is rejected as well.

## Pinned versions (since 16.10.2026, R-149)

Three files define exactly the contents of the Alpha 3.0 release (its `BUILD_ENVIRONMENT.txt`), with all
transitive dependencies, without hashes:

| File | What | Where to install |
|---|---|---|
| `requirements.txt` | program (server) packages, 28 of them | system Python 3.14 |
| `requirements-build.txt` | `-r requirements.txt` + PyInstaller and its dependencies | the same Python, used to build the server EXE |
| `requirements-desktop-shell.txt` | window and client, 16 packages (their own versions of cryptography, cffi, PyInstaller) | `buildenv` |

`tools/build_release.py` compares both environments with these files before building and stops on
a mismatch. Extra packages (for example numpy in the system Python — the build excludes it) do no harm.
Changing a version is a deliberate step: edit the line, install, build and update
`packaging/installer/licenses/THIRD_PARTY_LICENSES.txt` (the build will suggest the command);
`tools/test_dependency_pins.py` makes sure every package from that file is pinned at the same
version.

## Verified environment (snapshot of 29.09.2026)

The exact contents of a specific release are in its `BUILD_ENVIRONMENT.txt`; for Alpha 3.0 it matches
the pinned versions above.

**Server** — system Python **3.14.7**, PyInstaller 6.22.2. Packages inside the EXE: annotated-doc
0.0.5, annotated-types 0.8.0, anyio 4.14.2, cffi 2.1.1, click 8.5.0, cryptography 50.0.1,
et_xmlfile 2.0.0, fastapi 0.141.1, h11 0.16.0, httptools 0.8.0, idna 3.19, openpyxl 3.1.5,
packaging 26.3, paho-mqtt 2.1.0, pillow 12.3.0, pydantic 2.13.5, pydantic_core 2.46.5, pystray 0.19.5,
python-dotenv 1.2.3, python-multipart 0.0.32, PyYAML 6.0.3, setuptools 84.0.0, six 1.17.0,
starlette 1.6.0, typing_extensions 4.16.0, typing-inspection 0.4.4, uvicorn 0.52.4, watchfiles
1.2.0, websockets 17.1.

**Window and client** — a separate `buildenv` environment (venv), Python **3.14.7**: pywebview 6.2.1,
pythonnet 3.1.0, clr_loader 0.3.1, bottle 0.13.4, proxy_tools 0.1.0, cryptography 49.0.0,
cffi 2.1.0, pycparser 3.0, typing_extensions 4.16.0, pyinstaller 6.21.0 (with altgraph 0.17.5,
pefile 2024.8.26, pywin32-ctypes 0.2.3, pyinstaller-hooks-contrib 2026.6), packaging 26.2,
setuptools 83.0.0.

How to recreate `buildenv` (it cannot be moved between computers: `pyvenv.cfg` keeps paths):

```bash
py -3.14 -m venv C:\3DIWELL_Builds\buildenv
C:\3DIWELL_Builds\buildenv\Scripts\python.exe -m pip install -r requirements-desktop-shell.txt
```

**Inno Setup 6.7.3** — looked up in `%LOCALAPPDATA%\Programs\Inno Setup 6`, then in Program Files.

**Windows components** (`<FM_VENDOR_DIR>`): `MicrosoftEdgeWebView2RuntimeInstallerX64.exe` and
`ndp48-x86-x64-allos-enu.exe` — where to get them and how to verify the Microsoft signature is described in the header of
`tools/installer/prereqs.iss`.

## What is still open

Done: the build root and the shell Python are set with variables; the shell environment is described
above; a release describes its own environment (`BUILD_ENVIRONMENT.txt`); third-party
license texts are installed with the program and checked against the build; all package versions are pinned exactly
(R-149); the server EXE and the installers carry a version number in their file properties.

Awaiting the owner's decision: package hashes — later, for the open build (pip hash mode requires a hash
for every package on every platform); license texts and `THIRD_PARTY_NOTICES` in the client installer
(`3diwell-client-setup.iss`: currently it ships only `LICENSE`); the LGPL condition for pystray inside
a single-file EXE; FFmpeg source code for releases.
