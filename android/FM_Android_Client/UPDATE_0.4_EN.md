[Русский](UPDATE_0.4_RU.md) · **English**

# FM Client 0.4 — labels first, then receiving

## Update

You need BOTH files:

- `dist/inventory-1.7.29-mobile-prototype-0.4.zip` — the inventory module update;
- `dist/FM-Client-0.4.0-debug.apk` — the Android client update.

The FM core does not change. With the old module, label preparation will be blocked.

1. Finish saved unconfirmed operations on the phones. Choose a pause in the farm's work.
2. Make a standard FM backup including the inventory database.
3. Install the 0.4 ZIP through module management and perform the FM restart that is required.
   Inside the ZIP the compatibility version is still 1.7.29; tell the packages apart by file name.
   If FM refuses because the version is the same, do not delete the module/database and do not bypass the protection:
   send us the error text so that we can agree on a solution.
4. Check regular inventory: existing spools and remaining weights must be preserved.
5. Install the 0.4 APK over the previous app, without uninstalling it or clearing its data.
6. Sign in to the same FM. Old QR codes and regular operations remain available.

The update was not installed into your FM automatically. This is a test build, not an official
inventory 1.7.29 release for publication.

## Your example: 10 identical PETG spools without factory codes

### Preparation and printing

1. On the home screen, tap "Labels before receiving" → "Prepare new labels".
2. Enter a batch name, for example "PETG grey — 10 spools".
3. Choose a material from the catalog or fill in the manufacturer, PETG, color and diameter once.
   No factory barcode or made-up article number is needed for this scenario.
4. Enter the filament weight in ONE spool (for example, 1000 g excluding the empty spool)
   and the quantity 10. Optionally set a common caption.
5. Tap "Create labels", check the parameters and confirm.
6. Open the batch → "Download QR codes as one PDF". For 10 spools there will be two A4 pages.
7. Print at 100% and stick one different label on each physical spool.

At this stage FM stores ten pending labels, but ZERO new spools and ZERO receipts.
If the material was new, its card appears in the catalog — with no stock.

### Receiving onto a shelf

8. In this batch, tap "Receive using these QR codes" and choose a shelf.
9. Check the batch, material, weight and location, then tap "Enable".
10. Tap "Scan spool" and point the camera at the label STUCK ON the spool.
    Once the QR code is read, the receipt is made immediately, without another confirmation.
11. Wait for the "Spool received" response, then check the shelf and the counter.
12. Tap "Scan next" and repeat for the remaining spools.

The camera reads one label at a time and closes until FM responds. This is not continuous background
scanning. Do not scan labels that are not yet stuck on spools directly from the printed sheet:
the program cannot check that the spool physically exists.

If you received 7 out of 10, stock increases by 7 spools only; three labels stay pending.
You can stop, continue later from another phone, or choose a different shelf for the rest.

## Reprinting, cancelling, rescanning

- Lost a label: open the batch, select its number → "Show QR code", or download
  the combined PDF again. The number does not change and there is no new receipt. A copy of a single label is meant
  for THE SAME spool: do not stick it on a second physical spool.
- Wrong parameters before receiving: cancel the pending labels and prepare a new batch.
  Editing labels that are already printed is not supported.
- Cancelling one label: tap its number → "Cancel label" and confirm.
- Cancelling the rest of a batch: "Cancel all pending labels". Received spools are not affected,
  including those that another operator received after the cancellation confirmation was opened.
- A cancelled label cannot be restored, is not printed from the common list and cannot be received.
- Rescanning a received label reports "Spool already received" and does not make a receipt,
  does not move the spool to another shelf and does not restore it after deletion/write-off.
- After receiving, the same QR code is used to install the spool in a printer. There is no need to relabel.

## Important limitations

- All spools in a batch are of one material and one initial weight; quantity 1–500.
- The mode is designed for new full spools. Partly used spools need separate tracking of the remaining weight.
- Prepared batches are shared and stored in FM; the former section of regular receiving batches
  is still the phone's local history.
- If the shelf/material has been deleted or the manufacturer name, material, color or diameter
  has been changed after the labels were prepared, the receipt is blocked. Check the catalog/choose a shelf;
  cancel incorrect pending labels and prepare them again.
- There is no offline receiving. After a connection loss, use "Check / retry pending operation".
  While the response is unknown, do not create a replacement request and do not clear the app data.
- Retrying a saved request returns the earlier result. Check the current shared counters
  by opening/refreshing the batch, especially when several operators are working.
- Cloning or restoring an old database changes the available operation history. Do not use
  two independent copies of the same farm at the same time and do not receive old labels blindly after a restore.

## First check

First prepare one label and make sure in the main FM that stock has not increased.
Print it, stick it on, receive it — one spool should appear. Check its QR code during installation.
Then test partial receiving and rescanning in a batch of several labels.
The full list is in `ACCEPTANCE.md`. The APK, camera and PDF in this version have not yet been tested on your phone.
