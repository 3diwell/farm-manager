[Русский](UPDATE_0.2_RU.md) · **English**

# Updating your FM to 0.2

The demo server is not needed. Spool removal and replacement require updates to the inventory module and the Android client.
No changes to the FM core are required. We did not install the update into your production FM automatically.

## Update procedure

1. Finish any pending operation in the app if it offers to check/retry it.
   Do not clear the app data. Update during a pause with no active printing and no inventory operations.
2. Make a standard FM backup, including the inventory data.
3. Install `dist/inventory-1.7.29-mobile-prototype-0.2.zip` through module management.
   The internal compatibility version remains 1.7.29; go by the 0.2 in the file name.
   If FM refuses to install the same version, stop and send us the error text:
   do not delete the module/database and do not bypass the version check.
4. Perform the FM restart that is required, then check that inventory opens and the spools are intact.
5. On the phone, install `dist/FM-Client-0.2.0-debug.apk` over the previous app.
   The signature and application ID are the same, and the version is higher. There is no need to uninstall the app.
6. Open the app and sign in to the same FM. QR codes that are already printed keep working.

## How to remove a spool

On the home screen, tap "Remove spool from printer". Scan the QR code of the position,
the spool code, or pick the spool from the list of installed spools. Check the spool and the position,
then confirm the removal. The spool stays in inventory with the same remaining weight and its saved storage location.
No new shelf is chosen automatically on removal. The operator removes the spool physically:
the app only changes the link in inventory and does not send the printer a filament unload command.

## How to replace a spool

Open the regular spool installation → scan the QR code of the occupied position → scan the new
spool → check the old and new spools → confirm the replacement.
The old spool is removed and the new one is installed in a single operation. Scanning a slot QR code on its own
unlinks nothing; cancelling before confirmation leaves inventory unchanged.

If another operator has already changed the slot, the app will not silently overwrite it:
refresh the data and check the position again. You cannot replace spools on a printer that is printing/
unavailable or while print accounting is incomplete. Do not start jobs at the same time
as a removal/replacement: the core does not yet have a shared lock with print start.

After a connection loss, use "Check / retry pending operation".
Do not repeat it as a new receipt and do not clear the app data.

## First check

On an idle printer with two known spools, A and B:

1. Write down their remaining weights. Scan the occupied slot and cancel — A must stay in place.
2. Replace A with B — A is free, B is linked, both remaining weights are unchanged.
3. Remove B with the separate button — the slot is free, B is still in inventory.
4. Check the regular FM interface and the log: no consumption/repeated receipt has appeared.
5. If needed, repeat for the external holder and verify that AMS/CFS have not changed.

The full list is in `ACCEPTANCE.md`. The new functions have not yet been tested on your phone;
the automated checks are described in `VALIDATION_0.2.md`.
