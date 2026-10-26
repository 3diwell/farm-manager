[Русский](UPDATE_0.15.0_RU.md) · **English**

# FM Android 0.15.0 — printers, projects and tasks

APK: `dist/FM-Client-0.15.0-debug.apk`. Android 8.0 or later. The package and debug signature are unchanged and the version number has been raised from 17 to 18: the APK can be installed over 0.14 while keeping the app data.

After sign-in, the farm opens. The "Printers" tab shows the models, state, file, print progress and remaining time. The printer card shows temperatures, multiple nozzles, printer messages, AMS and linked inventory spools when the inventory module is present.

The camera button is available for the Bambu and Klipper types supported by the core. Bambu uses the standard FM MJPEG, including the shared stream for X1/H2; Klipper first tries WebRTC on the local network, then MJPEG. If the camera is missing or not configured in FM, the screen reports that it is unavailable. Closing the screen stops viewing. The fMP4 stream has not been added in this version.

"Projects" opens project files and parts; "Tasks" shows FM quick task files. A ready file can be sent to a compatible free printer with fresh data. For Bambu, you choose the external spool or AMS and the main start parameters. Before sending, you need to confirm that the bed is clear and the material is loaded. FM performs its own checks and accounting.

The submissions panel distinguishes acceptance of a request from a confirmed start. If the response is lost, resubmission is blocked. You need to check the result in the main FM and on the printer; "I checked the result in FM" only clears the waiting mark on the phone.

Without an available inventory module, its tab and the inventory spool information are hidden; sign-in and core functions work on their own. Inventory NFC, removal/replacement and prepared labels also depend on the capabilities declared by the module. Printing is available to administrators and operators; view-only roles do not get the start button. Capabilities are re-read on opening, about every 10 seconds and before sending.

The previous inventory protocols, QR/NFC, themes, Russian and English, the intro setting and sign-in saving for up to 8 hours are kept. The FM core and modules have not changed and do not need an update for these new screens.

## Checking after installation

1. The phone and the FM server must be on the same local network. Use the same FM address and port as before.
2. Check the printer list and the live state; open the card and the camera of a printer that has one.
3. Open a project and a quick task. First check that the file and a compatible printer are selected correctly. Start a real print only after checking the bed and the material.
4. Check the connection to FM with and without the inventory module, and a user with view rights.
5. When Wi-Fi is turned off, the state should become stale and starting a print unavailable until the connection is restored.

The build has been checked automatically. No phone or real cameras are connected to this working environment: video display, screen usability and actual printing need to be tested on your devices.

For development: `DEVELOPMENT_RULES_RU.md`, `ARCHITECTURE.md`, `VALIDATION_MOBILE_0.15.md`. The build uses the same local JDK 17 / Android SDK 35 / Gradle 8.11.1 as before, plus Node.js to check the camera document; no new Android dependencies have been added.
