[Русский](UPDATE_0.16.0_RU.md) · **English**

# FM Client 0.16.0 — what has changed

24.10.2026. File: `FM-Client-0.16.0.apk` (Google Drive → Projects → 3DMF → Release_3.0; a copy is in `C:\3DIWELL\modules`).
Package `ru.threediwell.fm.mobile.prototype`, versionCode 35, signed with the same key as 0.15.15: it installs
OVER the previous app; sign-in, settings and unsent inventory operations are kept. There is no need to uninstall the old
app. This is a release build (not a debug build).

## New

- **License via the phone.** If the farm computer has no internet, the administrator's phone takes
  the license check-in to the website over its own internet (mobile data or Wi-Fi with internet) and returns the answer
  to the program — when the app is opened or with the "Module licenses: check in via this phone" button in
  the settings. The result is shown in words: "The license service answered via this phone — OK (time)" or the reason.
- **"Remember this device".** The sign-in is kept until you sign out or revoke the phone in FM
  (the "Users" window), instead of 8 hours. A saved sign-in is no longer erased on a connection failure or
  an FM restart — only when FM explicitly says that there is no sign-in.

## Fixed

- Bambu: the default material source is "Auto (as in file)", not the external spool.
- A new file can be sent to a printer that has finished printing — with the tick "The part is removed; the plate is clear".
- The "start not verified" mark is now per printer and is cleared automatically when FM has confirmed the start;
  if the submission has disappeared (FM was restarted), a gentle reminder remains and starts are not blocked.
- "Repeat last print" — only files that FM sent itself (not by a name match).
- While printing there is no "Turn off heating" button; if FM warns "the print will fail", the phone
  asks again and turns heating off only after "yes".
- Clear messages: "the command did not reach the printer", "Stop did not reach the printer — printing continues", wrong
  password, "wait N min", refusal codes for inventory and printing.
- Klipper: the preparation steps enabled in FM and the choice of a CFS slot also work from the phone.
- "Write off as empty" with more than 50 g (or 5 %) remaining asks again: "Write off N g?".
- After a print starts, inventory messages are shown (spool replaced, material running low).
- AMS slots are labeled as in FM: "AMS 2 · 1", "AMS HT · 1".
- Assemblers and Observers see in inventory: "View only: the Operator or Administrator role is required".
- The version number on the screens is taken from the build.

## What to check on the phone

1. Install over 0.15.15 — open it: the previous sign-in and settings are in place.
2. Sign in as an administrator with "Remember this device" ticked, close the app and restart FM
   on the farm — the sign-in remains.
3. License: with the farm computer offline, open the app as an administrator (a phone with mobile
   internet) — the message "The license service answered via this phone — OK" appears; in the website account,
   the last connection time has been updated.
4. Bambu: start a file with "Auto (as in file)" — printing uses the correct AMS slot.

Checked during development: the build and 546 automated app checks, a check of communication with the farm
program (20). Not checked: on a real phone, with real printers and the license service.
