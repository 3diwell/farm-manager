[Русский](UPDATE_0.8_RU.md) · **English**

# FM Client 0.8 — fixes and simplified scanning

## Installation

Install `dist/FM-Client-0.8.0-debug.apk` over 0.7. Do not uninstall the app and do not clear
its data. It is best to finish any saved unconfirmed operation first.
The 0.7 inventory module, the FM core and printed labels do not need to be changed.

## 1. Rotating the phone

A normal portrait ↔ landscape rotation no longer recreates the home screen or the NFC screen.
Sign-in, filled-in fields, the selected shelf and the operation should be preserved. Orientation is not locked.
In landscape, the camera shows the image on the left and scrollable buttons on the right.
This is a rotation fix, not automatic sign-in after the system has fully terminated the app:
the password and session are still not written to storage.

Check: sign in, choose a shelf, rotate the phone; then fill in part of a form and rotate it
back. Also check rotation with the camera open, while reading NFC and in the replacement confirmation
dialog. After a normal rotation, the username/password must not be requested.

## 2. NFC

"Read Bambu NFC" immediately starts waiting for a tag — during a successful inventory operation you no longer need to tap
"Read Bambu data" and "Use scanned tag" in addition.
Reading on its own still does not change inventory: after it, the receiving form opens,
or the existing installation/linking confirmation.

If data exchange is interrupted during reading, the whole read is retried automatically once
with a new connection. Fields from the two attempts are not mixed. If both attempts fail,
the app does not fill in the material/weight and lets you retry or use QR.
A sector access refusal or a wrong format does not trigger key guessing or endless retries.

Your 0.7 report shows access to both sectors, but a communication failure before block 5 was received.
It does not prove that the keys are wrong and does not let us pinpoint the physical cause.
Keep the phone still against the tag until reading is finished. If it fails again, send the full
0.8 report: it now shows what happened in both attempts.

## 3. One receiving flow for all codes

1. On the home screen, tap "Receive into inventory".
2. Choose the storage location, for example "Shelf 1".
3. Tap "Scan" and point the camera at the spool code.

The app then works out the code by itself:

- **Prepared FM QR code:** immediately receives one spool onto the selected shelf. The material and weight
  are taken from the prepared label. There is no need to look for or select a batch.
- **QR code already received:** shows that the spool is already recorded; there is no new receipt and no move to another shelf.
- **Factory QR code or barcode:** opens the existing form with the product found or the fields for a new material.
  The confirmation remains, because a shared product code does not distinguish one physical spool from another.
- **Text only:** in the same camera window, tap "Label has text only (Latin script)", check
  the recognized SKU/ID, then fill in the missing fields. Arbitrary text does not guarantee that
  the manufacturer/material/color is identified. Cyrillic is entered manually for now.
- **Bambu NFC:** available on the receiving screen and as a separate button inside the camera.

After a result, "Scan next" opens the camera again immediately. The shelf stays the same,
and the next label may be from a different batch or be a factory code.
Cancelled, foreign and unknown internal QR codes are not accepted as new products.
Batch data is already stored in FM and is found by the ID in the QR code: old labels do not need to be reprinted.

The previous batch screens are kept for preparing, downloading, printing and cancelling labels,
but are no longer required for everyday receiving. On the home screen they are combined into "Labels and QR codes".

## 4. Installation / replacement

1. "Install / replace" → "Open camera" → the position QR code.
2. The camera opens automatically to scan the spool. The hint shows the selected position.
3. Scan its QR code/barcode. For NFC, use the NFC button inside the camera.
4. If exactly one item is found, the final installation/replacement confirmation opens immediately.
   If a shared product code matches several spools, you need to pick a specific one.

One confirmation before writing is kept on purpose: it shows what is being removed and what
is being installed. Before it, scanning the position QR code removes nothing. Protection against an occupied/changed
position, printing, and a spool installed elsewhere is preserved. A new spool must first be in inventory.

## Quick check

- Check rotation on the sign-in form and after sign-in, in receiving, camera, NFC and the confirmation.
- Receive one pending QR label the usual way; scan it again: there is no second receipt.
- On the same shelf, scan a label from another batch without going back to batch selection.
- Read NFC several times; if it fails, send the full report.
- Check the chain position QR → spool QR → confirmation on a free slot, then on an occupied one.

The automated checks have passed, but physical NFC and the behavior of the Redmi in particular require this check.
