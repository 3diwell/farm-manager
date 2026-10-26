[Русский](UPDATE_0.15.7_RU.md) · **English**

# FM Android 0.15.7 — compact top row

Install dist/FM-Client-0.15.7-debug.apk over the current app.
The connection, notifications, theme, language and sorting are kept.

- The Farm Manager text has been removed from the app's common header. The app name
  in Android and the original 3diwell logo are kept.
- On the farm screens, the "Connected" / "Connection lost" status and the refresh button
  have moved up into the top row. The bell and the logo are next to them.
- The separate status row that is no longer needed has been removed. The "Farm printers" heading
  and the previous QR/sorting block are placed directly under the common header.
- With a large font or a long translation, the right block wraps below.
  The full status text is not cut off; the buttons keep a 48dp area.
- On the inventory/sign-in screens, the common header also no longer contains the
  Farm Manager caption; their own statuses and actions stay where they were.

The icons in this build are unchanged. Five new sets are presented separately for selection:
FM-icon-sets/index.html and FM-Icon-Sets-2026-10-02.zip. Each contains all 25
existing symbols plus 5 separate symbols for actions that previously
used the same icon: projects, inventory, "More", printing, PDF download.
A new set has not been adopted automatically. The mockups are not APK screenshots.

The core, modules, the Android server, inventory, print repeat, accounting and command restrictions
have not changed. Results: VALIDATION_MOBILE_0.15.7.md.
On the phone, check the top row, the light/dark theme and a large font.
The real FM server and printers were not used during development.
