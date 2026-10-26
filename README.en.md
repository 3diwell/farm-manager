[Русский](README.md) · **English**

# 3DIWELL Farm Manager

A program that runs a 3D printer farm from one screen: projects and parts, the print queue and
print launch, monitoring of Bambu Lab, FlashForge, Klipper/Moonraker and other printers, users with
roles, backups. It runs on the farm computer, with no cloud and no mandatory internet connection.

## What this repository contains

- **The FM core** — the server (`server.py`, `app/`) and the interface in a browser or in its own
  window (`web/`). Free, open source, licensed under the [MPL 2.0](LICENSE).
- **Free modules** (`modules/`): Quality analytics, Messenger notifications, Appearance and themes,
  and Camera Wall. A module is installed in the program: *Settings → Modules → Install*.
- **The foundation for paid modules** (`app/licensing/`): verification of signed packages and
  licenses, fully offline after activation. Description —
  [docs/licensing/MODULE_LICENSING_FOUNDATION.en.md](docs/licensing/MODULE_LICENSING_FOUNDATION.en.md).
- **The phone app** (`android/FM_Android_Client/`) — FM Client for Android: printers, print
  launch, inventory by QR and NFC, licenses through the phone. Built with Gradle (JDK 17, Android SDK 35).
- **Demo modules** (`examples/modules/`) — a free and a paid example for module
  developers.

The paid modules (Inventory, Order calculation) are not in this repository: they are distributed
separately as signed builds; without a license they open in view-only mode.

## Installation

Ready-made installers for Windows 10/11 (64-bit) are published under Releases. The installer
installs the missing Windows components itself (.NET Framework, WebView2). Farm data is stored in
`%LOCALAPPDATA%\3DIWELL` and survives program updates.

User guides — [docs/user/](docs/user/README.en.md): installation, modules, licenses,
backups, phone.

## Running from source

Python 3.14 is required.

```bash
python -m pip install -r requirements.txt
python server.py
```

The interface opens at http://127.0.0.1:8000. Building the EXE and the installers —
[docs/dev/building.en.md](docs/dev/building.en.md), checks — [docs/dev/testing.en.md](docs/dev/testing.en.md).

Some files of the official build are intentionally missing here: the ffmpeg program for Bambu Lab
cameras and the printer model images (see [NOTICE.en.md](NOTICE.en.md)). The program works without them:
placeholder icons instead of printer pictures, and for Bambu cameras you need to put `ffmpeg.exe`
next to `server.py`.

## License and rights

- First-party code — [Mozilla Public License 2.0](LICENSE); details and exceptions —
  [NOTICE.en.md](NOTICE.en.md).
- Third-party components — [THIRD_PARTY_NOTICES.en.md](THIRD_PARTY_NOTICES.en.md).
- The 3DIWELL name and logos are trademarks, see [TRADEMARKS.en.md](TRADEMARKS.en.md).

## Contributing and security

How to report a bug and propose a change — [CONTRIBUTING.en.md](CONTRIBUTING.en.md).
Vulnerabilities are not reported in public issues but as described in [SECURITY.en.md](SECURITY.en.md).
