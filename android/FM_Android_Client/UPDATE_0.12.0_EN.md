[Русский](UPDATE_0.12.0_RU.md) · **English**

# Android 0.12.0 — sign-in for up to 8 hours without changing the core

Install `dist/FM-Client-0.12.0-debug.apk` over the installed Farm Manager.
Do not uninstall the app or delete its data: this keeps the settings and the log of pending operations.
On the connection screen, tick **"Remember sign-in for 8 hours"**, enter your usual username and password
and connect. The option is off by default; the selected value is remembered for future sign-ins.

On a new launch, the app checks the session with the same FM and loads inventory.
The check runs at the same time as the intro. If the intro is turned off in the settings, only
the actual connection time remains; there is no extra delay for the animation.

## Behavior

- The term is at most 8 hours from sign-in. If FM issues a shorter term, that term applies.
  Repeated launches and network requests do not extend the saved term.
- Restarting FM, revoking access or expiry of the term will require a new sign-in. Core sessions
  are kept in the server's memory; the client cannot preserve them across an FM restart.
- When there is no connection, the saved sign-in stays on the phone. The screen offers to retry
  the connection or to delete the saved sign-in and sign in with another account/address.
- "Sign out" first deletes the local saved session, then tries to end the session on FM.
  Without a network, the local sign-out is still performed; the remote session will end according to FM rules.
- A session for a different address, port or HTTP/HTTPS scheme is not used. The saved file on its own
  does not grant access to inventory: a successful `/api/auth/status` check and data load are required.
- A 401 response or an explicit `authenticated:false` deletes the saved sign-in. A 403 response, a server error,
  an unavailable network and a malformed response are not treated as a wrong password.
- The app handles a read/decryption error by returning to the regular sign-in. If the new
  sign-in could not be saved, the app reports it; the current sign-in keeps working in memory.
- Without a saved sign-in, the password will be required again after the process is lost. The setting that turns off
  the welcome screen works independently of authorization.
- When authorization is disabled on the server, there is nothing to save: no protected session is created.

The password is not written to storage. Only the current `fm_session` cookie, the FM address,
the original sign-in time, the fixed term and the HTTPS flag are saved. The data is encrypted with AES-256-GCM with a new
random IV on every write; the key is created in the Android Keystore. The file is located in `noBackupFilesDir`;
backup and transfer of app data remain disabled.
Encryption at rest does not change the properties of HTTP: HTTP still requires a trusted farm network.
System validation of HTTPS certificates is kept.

The FM core, the server module, the animation, the greeting texts, QR/NFC and the inventory protocol have not changed.
Saving the sign-in does not trigger a retry of pending inventory operations: the log stays as it was,
and a retry is performed only by user action.

## How it is implemented

- `SavedSession`: validated fields, the 8-hour limit and an absolute expiry, rejection when the clock is earlier than the sign-in.
- `SessionCipher`: versioned encryption with an integrity check of all saved fields.
- `EncryptedSessionStore`: Android Keystore, a limited file size, atomic writes,
  deletion of a corrupted record; key operations run off the main thread.
- `RememberedLogin`: a mandatory server-side session check, separate handling of revocation and connection failure.
- `FmApi`: exports only cookies with a known expiry, imports only for the same address,
  checks the expiry before requests and has a separate authorization-expired error.
- `MainActivity`: the sign-in option, the check during the intro, connection retry, local deletion
  before sign-out. The connection result is shown after the intro closes and does not cut it short.

The client-side term uses the phone's system time; the server remains the authority that decides
whether the session is valid. There is no long-lived device token and no background session refresh.

## Checks and testing on the phone

Automated check results and checksums: `VALIDATION_MOBILE_0.12.md`.
There is no connected Android device or emulator in this environment. The Android Keystore,
a cold start, the transition after the intro and recovery after a phone reboot
require testing on a real device; JVM tests do not substitute for this.

1. Install the APK over the previous one, turn on sign-in saving, sign in, close the app's process
   and open it again. Inventory should open without entering the username and password.
2. Repeat with the welcome screen turned off: there should be no animation.
3. Close the app, temporarily turn off Wi-Fi, open it: a connection retry should appear.
   Restore the network and retry — the password is not required until the term expires.
4. Tap "Sign out", including with the network off, close the process and open the app again:
   the sign-in form should appear.
5. Restarting FM and waiting more than 8 hours after sign-in should both lead to re-authorization.
6. Sign in without ticking the save option and close the process: the next launch shows the form again.
7. Check recovery after a phone reboot within the term while FM is running.

Previous APKs are kept. A backup of the sources before the changes:
`F:/Codex/Intro/Android_Session_v05/before_0.11.3.zip`.
