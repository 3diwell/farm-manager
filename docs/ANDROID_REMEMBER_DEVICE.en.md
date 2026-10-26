[Русский](ANDROID_REMEMBER_DEVICE.md) · **English**

# "Remember this device": the contract between FM and the Android app

Contract version: **1** (FM Alpha 3.0, 26.09.2026). For the developer of the FM Client app.

## Why

Owner's request: enter the login and password on the phone once. After that the phone signs in by itself until
the permission is revoked: by signing out on the phone or with the "Revoke" button in FM. The password is not
stored on the phone.

## What FM provides (contract 1)

1. **Support flag.** `GET /api/auth/status` returns `"remember_device": 1`.
   Earlier FM versions do not return this field: with them the app behaves as before
   (8 hours).
2. **Request to remember the device.** The following fields are added to the login body:
   ```json
   {"username": "...", "password": "...", "remember_device": true, "device_name": "Pixel 7"}
   ```
   `device_name` is optional. Without it FM takes the phone model from the User-Agent
   (`… Android 14; SM-S918B Build/…`) and shows it in the device list. No longer than 64 characters.
3. **Response on success:**
   ```json
   {"ok": true, "user": {"username": "...", "role": "..."},
    "device": {"id": "dev_…", "name": "Pixel 7", "persistent": true}}
   ```
   The `fm_session` cookie is then a **device token**: it starts with `fmd_`, alphabet
   `[A-Za-z0-9_-]`, length 47. `Max-Age` = 315 360 000 (10 years). The lifetime is set not by the clock but by revocation.
   All other app requests use the same cookie; nothing changes in them.
4. **If FM could not save the permission** (disk failure), it issues a regular 8-hour session
   and responds with `"device": null, "remember_device_error": "store_failed"`. The app should
   tell the user about it ("signed in only until the app is closed") rather than treat the
   device as remembered.
5. **Check on startup:** `GET /api/auth/status` with the device token returns
   `authenticated: true` and `"device": {"id", "name", "persistent": true}`.
   - Idle time is unlimited.
   - Restarting FM does not remove the permission.
   - The role is the current one, taken from the FM database.
   - A temporary FM database failure returns **503** (`{"error": "temporarily_unavailable"}`, `Retry-After: 5`),
     not `authenticated: false`. On 503 the saved sign-in must not be erased: retry later.
6. **When the permission is removed** (after that any request with this token gets 401, and
   `status` returns `authenticated: false`):
   - signing out on the phone: `POST /api/auth/logout` with this token;
   - the "Revoke" button in FM: Settings → System → Access & audit → Users → "Remembered
     devices" (the section is visible in any interface mode);
   - in FM the user's password or role was changed, or the user was disabled or deleted. The permission is bound
     to the fingerprint of the password used to sign in: if the password changed, the permission no longer works, even if
     the revocation did not make it to disk;
   - in FM access protection was turned off ("Access & audit" → "Disable mode") or turned on again;
     while protection is off, device tokens are not accepted and new ones are not issued;
   - signing in again from the same phone: the previous permission is replaced with a new one.

   FM stores only the SHA-256 of the token. A copy of the FM database does not allow signing in.

## What is expected from the app

1. Before signing in, read `GET /api/auth/status`. If `remember_device >= 1`, offer
   "Remember this device" with an explanation: the sign-in will be kept until the user signs out or
   access is revoked in FM. If the field is missing, behave as with earlier FM versions.
2. With the checkbox on, send `remember_device: true` and `device_name` in the login request.
3. Store a sign-in with `device.persistent == true` without an expiry based on the phone's clock, and verify it with
   `GET /api/auth/status` on startup.
4. Erase the saved sign-in only on `authenticated: false`. On 503 and on network errors keep it
   and retry the check later; on 401 from other requests ask `status` first.
   The same applies to the live `/ws` connection: FM rejects the connection (HTTP 401/403 instead of `101`) or
   closes it with code 1008 both on a temporary failure of its database and on revocation. So here too
   call `GET /api/auth/status` first, and erase the sign-in only on `authenticated: false`.
5. "Sign out" — `POST /api/auth/logout`: with this FM removes the permission for good.
6. Encrypt the saved sign-in with a key available only on an unlocked phone
   (`setUnlockedDeviceRequired(true)` from API 28; StrongBox if available, otherwise the regular
   keystore). Otherwise a sign-in without expiry on a stolen phone keeps working until it is revoked in FM.
7. A `402` response with `reason: "license_required"` (a paid inventory build without a valid license)
   is not a rejection of the operation: do not delete an unsent inventory operation, show "read only"
   and retry later. Otherwise an expired license would silently erase a scanned spool.

An analysis of the current app build and specific changes to its code are in FM's internal development
notes (not included in the open repository).

## What has and has not been verified on the FM side

- Verified by the `tools/test_remembered_devices.py` suite: issuing, verification, surviving
  a "restart" (the store is re-read), all revocation paths, binding to the password, a disk write failure
  and its retry in the background, the 503 response on a database failure, turning protection off and on, the device
  list in FM.
- **Not verified:** a real phone with a new app. Such an app version does not exist yet:
  both 0.13.0 and 0.15.15 (analysis of 10.10.2026) still limit the sign-in to 8 hours themselves and do not send
  the `remember_device`/`device_name` fields.
