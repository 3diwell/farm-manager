[Русский](UPDATE_0.5_RU.md) · **English**

# FM Client 0.5 — NFC check on Redmi Note 14S

File: `dist/FM-Client-0.5.0-debug.apk` (about 66 MiB).

## Installation

1. Finish the current operation in the client if one is in progress.
2. Copy the APK to the phone and open the file. Confirm the update of the installed FM Client.
   Do not uninstall the previous app and do not clear its data. The signature matches APK 0.4;
   the application ID stays the same, and versionCode is raised from 4 to 5.
3. If Android does not offer an update, do not uninstall the app — send us the error text.
4. The inventory module and the FM core do not need to be updated for this check.

## Checking a spool

1. Turn on NFC and unlock the phone.
2. Start FM Client. On the sign-in screen, tap "NFC check" — you do not need to connect to the farm.
   If you are already signed in to FM: "More" → "NFC check".
3. Tap "Start check". Hold the back of the phone against the tag of one Bambu spool.
   Slowly change the phone's position, keeping it close for a few seconds. Keep other tags
   well away; remove a metal case if necessary. Do not use bank cards.
4. Once a tag is detected, scanning stops and a report appears. Tap "Copy report"
   and paste it into the conversation. Alternatively, you can send a screenshot of the result.
5. You can check the other side of the same spool: first move the phone away, then tap
   "Check again". Copy each result separately, noting which side of the spool it was.

If no tag is found within 45 seconds, a hint appears. Try a different phone position.
No response on its own does not prove incompatibility.

## What the result shows

- Whether NFC is present on the phone and its state.
- The UID of the detected tag in HEX, without changing Android's byte order.
- The detected technologies; for NFC-A — ATQA and SAK.
- Whether MIFARE Classic is available for this phone/tag combination; if it is, the memory size.

IMPORTANT: this is detection diagnostics, not full reading of Bambu filament data.
Material and color are not extracted yet. Keys and reading of protected sectors are not tested.
The UID does not prove the manufacturer, authenticity or uniqueness of the spool.
The absence of MIFARE Classic may mean a different tag type or a phone limitation.
Automatic NDEF reading is deliberately disabled; the absence of Ndef in the list is expected here.

## Safety

The tag is not modified. The screen sends no requests to FM, does not create spools and does not change remaining weights
or links. Scanning stops after a result, when you tap the stop button, after 45 seconds
or when you leave the screen. When you return, you need to tap the button again.
The UID found is not sent automatically; the report is copied only when you tap the button.
The camera, QR, inventory operations and the client's previous printing functions are preserved.

Testing on a real Redmi with a factory tag remains with the user. The software checks
and build information are given in `VALIDATION_NFC_0.5.md`.
