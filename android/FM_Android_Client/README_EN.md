[Русский](README_RU.md) · **English**

## Working baseline returned to 0.15.5 — October 2, 2026

To install over 0.15.9: **`dist/FM-Client-0.15.5-rollback-debug.apk`**.
Code and resources are taken from the working 0.15.5 APK. The internal install number is 28.
The app sources are restored to 0.15.5; the next release needs a number higher than 28.
Details and checks: `ROLLBACK_TO_0.15.5_RU.md`.
Below is the original description of version 0.15.5.

## Current version 0.15.5: repeat, notifications and cards

APK: **`dist/FM-Client-0.15.5-debug.apk`**. Installs over the current app.
Handling of an empty file fingerprint in print repeat is fixed. Messages have moved
to notifications under the bell; short notices disappear after 6 seconds.
The video camera is in the card header, materials are shown as slots with
percentages, and projects show a percentage and a progress frame based on the main FM calculation.
Inventory, module restrictions, accounting and launch checks are unchanged.
Details: `UPDATE_0.15.5_EN.md`, `VALIDATION_MOBILE_0.15.5.md`.
The sections below describe the history of earlier versions.

## Current version 0.15.4: compact lists and sorting

APK: **`dist/FM-Client-0.15.4-debug.apk`**. Installs over the current app.
Project and task files are shown as short rows with a separate print icon;
tapping a row opens the full details. Printers are sorted by status,
model and name; files by name and readiness. The direction and the chosen order
are stored only on the phone. Inventory and the earlier launch checks are unchanged.
More: `UPDATE_0.15.4_EN.md`, `UI_RESEARCH_0.15.4_RU.md`,
`VALIDATION_MOBILE_0.15.4.md`. The sections below are the history of earlier versions.

## Update 0.15.3: printer QR and print repeat

An existing slot/holder sticker opens the printer card from the
"Printers" tab. The repeat button finds the last FM file that printed successfully,
requires confirmation that the plate is clear and creates a new regular job.
Module rules, FM accounting, inventory, control commands and preheating are unchanged.
Details and the check procedure: UPDATE_0.15.3_EN.md; VALIDATION_MOBILE_0.15.3.md.

# Farm Manager for Android — prototype 0.15.2

## Android 0.15.2: pause, stop and preheat presets

Current APK: **`dist/FM-Client-0.15.2-debug.apk`**. Installs over the current
version without removing the app. The expanded printer card now has
"Pause / Resume", a full stop with confirmation, shared preheat presets,
preset editing and turning heating off. Presets are read from and saved to FM;
it is one set for the phone and all computers of the farm.

The commands are available with the control permission, a supported printer type and fresh
data. Bambu dual nozzles and chamber heating are taken into account from FM data. These features
are built into the core and do not require the inventory module. The core and server modules were not changed.
Details: `UPDATE_0.15.2_EN.md`; checks: `VALIDATION_MOBILE_0.15.2.md`.

## Android 0.15.1: inventory restored and a unified look

Previous APK: **`dist/FM-Client-0.15.1-debug.apk`**. Installs over 0.14 or 0.15
keeping the data. Reading the module list of your FM core is fixed: inventory is
available again from the bottom bar and "More" when the module is installed, enabled and loaded.
The earlier operations, QR/NFC, spools and labels are kept; their availability depends
on the user's permissions and on the capabilities of the mobile inventory protocol.

Navigation of the new screens follows the earlier look: icons, cards, both themes,
language and settings. Tapping opens the printer card; progress is shown
for the current print with fresh data. The camera buttons are more compact.
The core, server modules and their protocols were not changed.
Details: `UPDATE_0.15.1_EN.md`; checks: `VALIDATION_MOBILE_0.15.1.md`.


## Android 0.15: printers, projects, tasks and printing

Previous APK: **`dist/FM-Client-0.15.0-debug.apk`**. Installs over 0.14 without removing data.
After sign-in you get printers with live status, the expanded card and camera,
project and quick-task files, choice of a compatible idle printer and sending to print.
The feature set depends on the modules of the current FM and the user's permissions. Without inventory, sign-in and
the core screens work on their own; dependent features are hidden. If the result is unknown,
the print is not resent automatically. The core and modules were not changed.
Mandatory rules: `DEVELOPMENT_RULES_RU.md`. Installation and limitations:
`UPDATE_0.15.0_EN.md`. Check results: `VALIDATION_MOBILE_0.15.md`.

## Android 0.14: visual hints for operations

Previous APK: **`dist/FM-Client-0.14.0-debug.apk`**. Installs over 0.13.0 without removing data.
Receiving, installation/replacement and removal now include the approved 3D icons:
printer No. 3, inventory rack, a full black spool and an almost empty spool.
Hints appear in the camera, manual entry, NFC and confirmations; the brand check mark appears
after a successful FM response. Both themes and both languages are supported. The core and server module were not changed.
The almost empty spool is a symbol for removal; the actual remaining amount is shown in the card.
Details: `UPDATE_0.14.0_EN.md`; checks: `VALIDATION_MOBILE_0.14.md`.

## Android 0.13: light theme and English

Previous APK: **`dist/FM-Client-0.13.0-debug.apk`**. Installs over 0.12.0 without removing data.
"App settings" before sign-in or "More" after sign-in → "Appearance" / "App language".
Dark and light themes, Russian and English are available. The choice is saved, applied immediately
and does not end the current session. The existing theme and Russian remain the defaults.
Screens, dialogs, error messages, camera, NFC reports, PDF captions and greetings are translated.
Printer names, materials and other user data are not translated automatically.
Remembering sign-in for 8 hours and turning off the intro screen work as in 0.12.
Details: `UPDATE_0.13.0_EN.md`; checks: `VALIDATION_MOBILE_0.13.md`.

## Android 0.12: remember sign-in for up to 8 hours

Previous APK: **`dist/FM-Client-0.12.0-debug.apk`**, kept separately.
On the connection screen, turn on "Remember sign-in for 8 hours" and sign in as usual.
On later launches the saved session is checked with FM and inventory opens without a password.
The period counts from sign-in, is not extended on launch and may end earlier after
an FM restart or revoked access. If the connection is temporarily lost, you can retry connecting.
"Sign out" deletes the saved sign-in, including without a network. The password is not saved.
The session is encrypted with AES-GCM; the key is in Android Keystore, and the file is excluded from backups.
No changes to the core or server module are needed. The welcome screen is turned off with the same
switch in the app settings; the sign-in check runs in parallel with the intro screen.
Installation, checks and limitations: `UPDATE_0.12.0_EN.md`.

## Android 0.11: 3diwell intro screen on launch

Previous APK: **`dist/FM-Client-0.11.3-debug.apk`**, kept separately.
In 0.11.3 the welcome screen can be turned off in "More" or in the settings on the connection screen.
The switch is kept between launches; it is on by default. Details: `UPDATE_0.11.3_EN.md`.
A proposal for future long-term sign-in is in `AUTH_PERSISTENCE_PLAN_RU.md`; 0.11.3 has no automatic sign-in yet.
0.11.2 added four approved greetings for the time of day: `UPDATE_0.11.2_EN.md`.
0.11.1 removed the large icon before the animation: the Android system splash screen
uses a transparent icon on the same #18181B background. The app icon on the home screen is kept.
Details of the fix and the on-phone check: `UPDATE_0.11.1_EN.md`.
Native phone intro: an engineering reveal, shrinking to the strike and a quick fly-in of
the remaining logo elements. Solid #18181B background, a separate greeting based on local time.
Full playback takes 7 seconds; the "Continue" button immediately opens the prepared connection screen.
When returning from the background, a finished intro is not replayed; disabled system animations are respected.
Camera, NFC, QR and the inventory protocol are unchanged. The server module does not need an update for the intro.
Installation and on-phone check: `UPDATE_0.11_EN.md`; results: `VALIDATION_MOBILE_0.11.md`.
Earlier APKs are kept. The description of the 0.10 look below refers to the previous release.

## Current PC module: inventory 1.7.31 — Claude version + batch prices

Inventory update file: `dist/3diwell-module-inventory-1.7.31.zip`.
Based on the Claude module 1.7.30 that was sent over. Its fix for write-off
from the AD5M external spool, English units and the separate compatibility contract are kept.
In "Labels & QR → Before receipt → New batch" you can enter the purchase cost
of the whole batch or of one spool. The other value is calculated automatically.
The price is fixed to each label and carried over into the card when receiving by QR.
Partial receiving, scan order and cancellation do not redistribute the cost.
Without a price everything works as before; old batches and received spools are not repriced.

The inventory 1.7.31 release did not require an Android 0.10 update; the new **0.11** client is also compatible. The price is set on the PC,
and receiving on the phone uses the earlier protocol. QR codes and print templates are unchanged.
The FM core was not changed. The Claude server backend is kept byte for byte.
The release version is now **1.7.31**, the contract version stays **1.7.29**,
revisions: mobile `0.8.0-pricing`,
desktop labels `0.6.0-prepared-prices`. This is not the Android version number.
An updated Claude core with `core_contract` support is required: its installer,
loader, all 31 routes and the version display were checked in isolation.
The module was not installed automatically into the working FM.

Installation and scenario: `UPDATE_INVENTORY_1.7.31_RU.md`.
Checks and limitations: `VALIDATION_INVENTORY_1.7.31.md`.
Build only this package: `python server/build_merged_module.py`.
Do not use the historical builders of earlier releases for the current package.
The previous `inventory-1.7.29-desktop-prices-0.8.0.zip` is kept for history:
it lacks Claude's later fixes; choose 1.7.31 for the current update.

## Android 0.10: approved header and icon

Previous APK: `dist/FM-Client-0.10.0-debug.apk`; the current 0.11 client is listed above.
The name on the phone is **Farm Manager**. Header A: Farm Manager on the left, the original 3diwell on the right.
The trademark keeps white #FFFFFF and orange #EA5E20, its geometry and proportions.
In the light theme there is a small dark backing under the logo — the mark itself is not recolored.
The icon is the approved variant 3 "Glass" from the actual icon pack, in its regular shape,
without a round mask added by us. The phone's home screen style may affect how it is shown.
The slogan is removed, sign-in is titled "Connect to FM"; the version is at the bottom of the screen.
The Android 0.10 release itself did not change inventory, camera, the NFC protocol or existing QR codes.
For the new prepared-batch price feature, install the module from the section above.
Installation procedure: `UPDATE_0.10_EN.md`. Checks: `VALIDATION_MOBILE_0.10.md`.

Below is the history of earlier versions, not the current files to install.

## Android 0.9: targeted camera and the FM look in one update

Current APK: `dist/FM-Client-0.9.0-debug.apk`. Install over 0.8 without removing the app/data.
The module stays `dist/inventory-1.7.29-desktop-nfc-0.7.0.zip`; it does not need an update.
Only the actual cropped fragment inside the aiming frame is passed to QR/barcode/OCR recognition.
In portrait orientation the camera window is compact (240 dp); a narrow square frame is used for a position.
After a stable read, a slot is frozen on the image with its name from FM; a select button is required.
With several tags, you can choose by tapping the frozen image or by caption.
Choosing a position does not remove a spool or change inventory; the final check/confirmation of the replacement is kept.
Action cards, compact buttons, shelf/position context, "Labels" navigation, spool cards
with a color swatch (if known) and an installation filter use the earlier dark/light FM palette.
QR, the server protocol, NFC reading and inventory operations are unchanged. Labels do not need reprinting.
Installation/check procedure: `UPDATE_0.9_EN.md`. Scope of checks: `VALIDATION_MOBILE_0.9.md`.

The history of earlier releases is kept below.

## Android 0.8: unified receiving, screen rotation and NFC retry

Current APK: `dist/FM-Client-0.8.0-debug.apk`, over 0.7 without removing data.
The module stays the same: `dist/inventory-1.7.29-desktop-nfc-0.7.0.zip` — no need to reinstall.
Prepared QR codes are now received via "Receive into inventory → Shelf → Scan":
the batch is identified by the ID from the existing label, no reprinting is needed.
The main screen and NFC are not recreated on rotation; forms, sign-in and callbacks stay in memory.
The camera rearranges its interface for a landscape screen with scrollable buttons.
On an NFC transport error there is one retry of the FULL read; incomplete data is discarded.
Inventory NFC starts immediately and returns the full result without an intermediate button.
Check procedure: `UPDATE_0.8_EN.md`. Scope and tests: `VALIDATION_MOBILE_0.8.md`.
The sections below are the history of earlier versions.

## Android + inventory 0.7: NFC in three working scenarios

Current files: `dist/FM-Client-0.7.0-debug.apk` and
`dist/inventory-1.7.29-desktop-nfc-0.7.0.zip`. Both updates are required.
Bambu receiving by NFC with field checks; installation via position QR + NFC;
linking NFC to an already received spool without changing its data. Reading itself writes nothing.
The Desktop Labels 0.5.2 print templates are kept byte for byte, the FM core is not changed.
The module contract version stays 1.7.29, the new extension revision is 0.7.0-nfc.
Step-by-step installation and check: `UPDATE_0.7_EN.md`. Checks: `VALIDATION_NFC_0.7.md`.
APK build: `build.ps1 -Offline`; packaging the new module: `python server/build_nfc_module.py`.
Do not run the old builders `build_module.py` / `build_desktop_module.py` for the 0.7 release:
they are meant for earlier stages and may overwrite old artifacts.
Below is the history, not instructions for choosing the current version.

## Android 0.6: trial reading of Bambu protected data

`dist/FM-Client-0.6.0-debug.apk` — an update over 0.5. "NFC check" gets a separate
"Read Bambu data" screen. It reads only material, variant, primary RGBA color,
factory weight and diameter; there is no writing to the tag and no inventory operations.
Instructions: `UPDATE_0.6_EN.md`; checks: `VALIDATION_BAMBU_0.6.md`; sources: `NFC_SOURCES.en.md`.
The FM module is not updated. The sections below describe earlier versions.

## Android 0.5: NFC check

`dist/FM-Client-0.5.0-debug.apk` — a client update with separate NFC diagnostics.
It opens without signing in to FM or via "More" → "NFC check". Only the properties of the detected
tag and MIFARE Classic availability; Bambu protected fields are not read yet.
Instructions: `UPDATE_0.5_EN.md`, checks: `VALIDATION_NFC_0.5.md`.
The inventory module does not need an update for this. `build.ps1 -Offline` builds the 0.5 APK and runs
the checks without rebuilding/overwriting the module ZIP. The Android 0.4 description below is historical.

## Previous PC package: Desktop Labels 0.5.2

`dist/inventory-1.7.29-desktop-labels-0.5.2.zip` — centered labels following the samples:
name at the top, QR in the center, caption at the bottom. Weight and diameter are not printed on labels.
Instructions and checks: `UPDATE_DESKTOP_0.5.2_RU.md`. Android 0.4 is unchanged.
The sections below describe earlier development stages.

## PC add-on: Desktop Labels 0.5.1 — compatibility fix

Use `dist/inventory-1.7.29-desktop-labels-0.5.1-compat.zip`.
The previous ZIP numbered 1.7.30 is incompatible with an FM that expects 1.7.29; do not install it.
Fix procedure: `UPDATE_DESKTOP_0.5.1_RU.md`; checks: `VALIDATION_DESKTOP_0.5.1.md`.
The fixed package keeps the "Labels & QR" tab
in the inventory module: AMS/CFS/external feed positions, prepared batches and existing spools.
A combined PDF, A4, any supported thermal label size, reprinting and cancelling labels.
Android stays at version 0.4 and does not need reinstalling. Details: `UPDATE_DESKTOP_0.5_RU.md`;
checks: `VALIDATION_DESKTOP_0.5.md`. Build only this package: `python server/build_desktop_module.py`.
The description of Android 0.4 and its original 1.7.29 package is kept below.

The first version of a separate Android FM client. The main FM features can be added later;
this is explicitly recorded in `ARCHITECTURE.en.md`. The current scope is inventory.

## Where the result is

- `dist/FM-Client-0.4.0-debug.apk` — the built test Android app.
- `dist/inventory-1.7.29-mobile-prototype-0.4.zip` — experimental inventory with mobile
  operations; do NOT replace the working module with it without checking on a copy and making a backup.
- `app/src/main/java/ru/threediwell/fm/` — client sources.
- `server/mobile_api.py`, `server/build_module.py` — the extension and reproducible packaging.
- `tests/test_mobile_api.py` — checks only on separate in-memory databases.

The working FM program, its network settings, user accounts and databases are not changed by this development.
Inside the test ZIP the compatibility version is left at 1.7.29 because of the core contract; this is not
an update for publication. The original archive next to the project is kept unchanged.

## Prototype features

1. Sign-in to a local FM over HTTP/HTTPS with an existing user.
2. Native Android camera: QR codes and barcodes, choice when there are several codes in the frame.
3. Manual code entry; OCR of Latin text with mandatory text check.
4. Choice of storage location, receiving one new full spool, linking to an existing
   material or creating a new one. The operator links an unknown code to a product once.
5. Separate shared product codes and unique codes of individual spools.
6. Scanning a printer position and a spool, confirmed safe linking.
7. Own QR codes for spools and positions; printing via Android or saving a PDF.
8. Retrying one request after a dropped connection without a duplicate inventory receipt.
9. Removing a spool: by position QR, spool code or by choosing from the list of installed spools.
10. Confirmed replacement in an occupied position: the old spool is unlinked and the new one linked
    in one operation. Remaining amounts, the previous storage location and existing history are kept.
    Zero-consumption moves are added to the log. Scanning itself changes nothing.
11. Look in the FM palette: dark/light theme, large buttons with line icons,
    bottom navigation, spool search, a shortened form for an existing material.
12. Receiving batches stored on the phone. QR codes of all confirmed spools of a batch —
    in one PDF; a repeated request does not add a second label.
13. Selecting several previously received spools for a combined PDF. A4, 8 labels per page,
    up to 500 spools per file; vector QR, caption and individual ID.
14. Prepared labels: material, weight and quantity → PDF with unique QR codes,
    with no spools/receipt yet. Then receiving by QR into the selected shelf.
15. Prepared batches are stored in FM and available to several phones. Partial receiving,
    reprinting, cancelling one or all pending labels; a repeated scan does not duplicate the receipt.

With the standard module without the mobile extension, only reading is allowed. The client does not send
unsafe old-format requests bypassing the compatibility check.

## How to check

Prepared labels need both the client AND module 0.4: `UPDATE_0.4_EN.md`.
The core does not need changes. The previously added design and the PDF of regular batches are described in `UPDATE_0.3_EN.md`.
Updating the server module from version 0.1 is described in `UPDATE_0.2_EN.md`.
The user confirmed receiving, field filling, QR creation and linking in version 0.1.
Removal and replacement in 0.2 need a separate check on a phone; the demo server is optional.

For an isolated trial there is a built-in demo server, WITHOUT installing the module
into the working FM. From the project folder run `python server/demo_server.py --host COMPUTER_IP`.
In the client enter `http://COMPUTER_IP:8011`, login/password `demo` / `demo`.
These are only made-up shelves, a P2S and a K2 Plus; the database is in memory and disappears when the server stops.
Do not expose the port to the internet. Without `--host` the server listens only on the computer itself.
On the first run, allow Python access to private networks in Windows settings
if the firewall blocks it. The working FM on port 8000 is not affected.
`fastapi` and `uvicorn` are enough for the demo and the HTTP test.

First installation on a separate test FM:

1. Android 8.0 or newer is required. Transfer the APK to the phone and allow installation for that
   specific source only for the duration of the installation. This is a debug build for testing, not a store release.
2. First use a separate test FM 3.0 installation with a copy of the data/empty inventory.
   Copying or switching the DATA_DIR of the running program on your own is not allowed.
3. On the test installation make a standard backup, then install the test ZIP
   via module management. After a restart, check that the regular inventory opens.
   If the installer does not accept a package with the same version, do NOT bypass the check by deleting data:
   a matching module version and core registry are needed before installation.
4. Enable FM access over the local network with the standard settings and set up a user
   with the inventory operations permission. Do not turn off protection to connect; do not expose the port to the internet.
5. Connect the phone to the same trusted network. Enter the computer's address, for example
   `http://192.168.1.10:8000` (this is an example, not the address of your installation). `localhost` on the phone is the phone itself.
6. Go through the scenarios in `ACCEPTANCE.md`. Write to the real inventory only after they pass.

## Honest limitations of the first version

- OCR of Russian text is not implemented yet: Russian text is entered manually. The camera recognizes
  codes regardless of the caption language. Material/color/weight are not guessed from an arbitrary QR.
- Regular receiving/installation requires confirmation. For a prepared batch the operator
  checks material/weight in advance, chooses a shelf and explicitly enables QR receiving.
  After that, each scan immediately records a receipt without a separate confirmation.
  The camera reads one tag at a time: after the FM response, tap "Scan next".
- An occupied slot is replaced only after scanning the new spool and confirming.
  Moving a spool directly from another printer is not allowed: remove it explicitly first.
  If another operator changed the link after the confirmation was opened, the request is rejected.
  New operations need both module 0.2 and client 0.2; old QR codes do not need changes.
- Linking requires fresh printer data and an idle state. Unconfirmed positions
  are not guessed. Some models may need clarification of state names after testing.
- A shared EAN does not distinguish identical spools — a choice or an own QR is required.
- A single label — via Android printing/PDF; a batch — directly into one A4 PDF, 8 labels per page.
  Thermal roll label formats are not implemented yet. The history of regular receipts is stored on the phone,
  is not synchronized with other operators and is lost when the app data is cleared.
  Prepared batches of 0.4, in contrast, are stored in the FM inventory database.
  Previously received spools are available for export through manual selection.
- No printing of jobs/printer control from the client, no background inventory operations and no cloud code database.
- A dropped connection after sending does not mean cancellation. Connect to the same server and tap
  "Check / retry pending operation"; do not clear the app data to repeat receiving.
- When the screen is recreated (for example, when the phone is rotated), you may need to sign in/
  scan again; the sent operation stays saved. The password and cookies are not stored on disk.
- HTTP does not encrypt the password, cookies or inventory data. Trusted LAN only; HTTPS is supported
  with a certificate trusted in the standard way. Certificate errors are not disabled.

## Build

JDK 17, Gradle 8.11.1, Android SDK platform 35 and build-tools 35.0.0.
Android Gradle Plugin 8.9.2; CameraX 1.4.2; bundled ML Kit barcode 17.3.0,
Latin text 16.0.1; ZXing 3.5.3 for QR generation.
The tools are kept locally in `toolchain/` and do not change the system PATH.

In PowerShell: `./build.ps1`; after the first dependency download you can use `./build.ps1 -Offline`.
The Python checks need `fastapi`, `uvicorn` (installed on the current machine).
In Android Studio you can open the root as a Gradle project and choose the installed SDK/JDK.
Tools and caches are not part of the source distribution and are not committed; build.ps1 sets the paths.

Official references:
- https://developer.android.com/privacy-and-security/security-config
- https://developers.google.com/ml-kit/vision/barcode-scanning/android
- https://developers.google.com/ml-kit/vision/text-recognition/v2

## Check status

Results of the current build — `VALIDATION_0.4.md`, historical checks — `VALIDATION_0.3.md`, `VALIDATION_0.2.md` and `VALIDATION.md`.
A camera check on a real phone, a physical label check and integration with specific
AMS/CFS units are mandatory; automated tests do not replace them.
