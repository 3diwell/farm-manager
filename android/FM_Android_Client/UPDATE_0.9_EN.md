[Русский](UPDATE_0.9_RU.md) · **English**

# FM Client 0.9 — camera and appearance

## Installation

1. Finish the current inventory operation in the app.
2. Copy `dist/FM-Client-0.9.0-debug.apk` to the phone and open it.
3. Choose to update the existing app. Do not uninstall it and do not clear its data.
4. After the update, sign in to FM the usual way if needed.

The core and the inventory module are not updated. The previous module with the 0.7 NFC extension stays.
Existing QR codes keep working; there is no need to print new ones. PDFs/labels have not changed.

## How to pick the right QR code on an AMS

1. "Install / replace" → "Open camera".
2. Place the QR code you need entirely inside the central square. Keep the other codes outside the frame.
3. Hold the phone still for about a second. After a stable read, the image freezes.
4. Check the printer and slot shown, then tap "Select this slot".
5. Scan the spool or tap Bambu NFC. Then confirm the installation/replacement.

If the wrong QR code was captured, tap "Aim at another tag". No installation/removal has happened yet.
If several codes are recognized inside the frame, the frame freezes without automatic selection:
tap the QR code you need or its caption below the camera, then confirm the selected tag.
In this mode the flashlight/OCR buttons are hidden until you aim again, so that they do not get in the way of the confirmation.
The information about the occupied position is a snapshot of FM taken before the camera opened; it is checked again before the operation.

An important difference: it is not only the preview window that is smaller. Only the cropped area inside the sight
is passed to QR/barcode/OCR recognition. The camera optics do not physically change; this is a software
restriction of the processing area, not a promise of hardware zoom. The darkened area is not recognized.
When the phone is rotated or the app goes to the background, an unconfirmed selection is reset: aim again.

## Receiving

"Receive into inventory" → shelf → "Scan". For barcodes, the sight is wider than for slots.
Your own prepared QR code goes straight onto the selected shelf after a stable read of a single code,
under the same rules as before. Several QR codes in the frame require a choice. Repeated receiving is protected by the server.
A factory code and OCR open the existing card check. A shared product code does not identify a specific
physical spool. Text reading is still turned on separately; Cyrillic is entered manually.
NFC receiving, linking NFC to an existing spool and NFC installation work as in 0.8.

## Appearance

- The FM dark and light themes, the graphite/light background and the blue accent are kept.
- Action cards: an icon on a background, a heading and a calmer caption.
- On the home screen, receiving and installation are highlighted; additional operations are set apart.
- Secondary buttons are more compact; the selected bottom navigation section is highlighted.
- "Batches" in the navigation is renamed to "Labels"; the batches themselves and the history were not deleted.
- The receiving/installation screens show the shelf and the position, and a selection is distinguished from a completed operation.
- Spools: material, color, remaining weight, location, a color swatch when HEX is available; search is kept,
  and an "All / Not installed / On printers" filter has been added. Full details are inside the card.

## What to test on the Redmi

1. With four QR codes in view, aim at each slot in turn, especially the middle ones, 2 and 3.
2. Keep a neighboring QR code outside the frame: it must not be selected.
3. With a frozen result, move the phone: the name must not change by itself.
4. "Aim at another tag" → a different position. Also try several QR codes inside the frame.
5. Aim at a printer/spool QR code in slot selection mode: there must be no transition to installation.
6. Check the external holder, cancel, flashlight, tap to focus, QR codes from old labels.
7. Rotate the phone before/after recognition, minimize the app and return: the selected tag is reset,
   inventory does not change by itself, and a normal rotation does not reset the sign-in to the main screen.
8. Receive a prepared QR code and a factory barcode, try text and NFC using the existing scenarios.
9. Check the appearance in both themes, with an enlarged system font and in landscape.

Without a connected phone, real focusing, CameraX coordinate transformation on Xiaomi,
glare on the AMS, ML Kit speed and visual convenience cannot be fully confirmed.
The automated tests check individual rules/boundaries and the inventory logic, but do not replace these items.
