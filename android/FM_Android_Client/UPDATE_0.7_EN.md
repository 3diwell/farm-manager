[Русский](UPDATE_0.7_RU.md) · **English**

# FM Client 0.7 — NFC in inventory operations

## What to install

1. Finish pending operations on the phone. Do not receive spools from other devices during the update.
2. Back up the FM data in the standard way. Do not delete the module, its data or the app from the phone.
3. In FM, update inventory via "Install and update" with the file `dist/inventory-1.7.29-desktop-nfc-0.7.0.zip`.
4. If FM asks for a restart, perform it. The module deliberately keeps version 1.7.29: this is a core compatibility requirement. The new extension revision is 0.7.0-nfc.
5. Install `dist/FM-Client-0.7.0-debug.apk` over the previous client. Do not clear the app data.
6. Open the client and connect to your usual FM address. NFC must be enabled on the phone.

The FM core does not need to be changed; HTTPS and the demo server are not required.
The new module includes the previous label printing on the PC (A4 / thermal label sizes)
and the centered 0.5.2 templates. The previous QR operations, receiving, removal/replacement and batches are preserved.
If only the APK is updated, NFC operations will ask you to update the module; regular QR codes remain available.

## 1. A new full spool — receiving by NFC

1. "Receive into inventory" → the shelf you need.
2. "Read Bambu NFC" → "Read Bambu data".
3. Hold the phone against the factory tag of one spool and keep it there until the result appears.
4. Tap "Use scanned tag".
5. In the form, choose an existing material from the catalog **or** check the fields of a new one.
   For a new one, Bambu Lab, the variant read, the RGB color code, the diameter and the factory weight are filled in.
   The name Orange is not guessed: if needed, enter the color name you are used to.
   The separate "Primary HEX color" field saves the color swatch in FM even if you renamed the color.
   Choosing an existing material does not change its name, color or other parameters.
6. Make sure the spool is new and full, then tap "Receive 1 spool".
7. After FM confirms, you can print the spool's own QR code or receive the next one.
   NFC receipts go into the regular current batch: "QR codes for entire batch" saves one combined PDF.

Until you tap "Receive", reading adds nothing. Reading an NFC tag that is already linked again
opens the existing card without a receipt. The server additionally protects against repeats
on connection loss and when several operators work at the same time.

**If the spool has already been entered by QR or manually, use scenario 3, not a new receipt.**
Without an established NFC link, the system cannot tell it apart from a new identical spool.
For a partly used spool, first use the correct card and the FM remaining weight; the factory weight
on the tag does not mean the current remaining weight and is not transferred to an existing card.

## 2. Installation / replacement in AMS, CFS or an external holder

1. "Install / replace" → scan the QR code of the position you need.
2. Check the printer name, the position and the spool currently installed.
3. "Read spool NFC" → "Read Bambu data" → hold the phone against the tag → "Use scanned tag".
4. Check the selected card and confirm the installation or replacement.

For an occupied position, the existing atomic replacement is used. Until confirmation, the old spool
is not removed; its remaining weight is preserved on replacement. The restrictions on printing/unconfirmed
positions and on spools installed elsewhere stay the same.
If the NFC tag is not linked to inventory, first do the receiving or scenario 3, then repeat the installation.

## 3. An already received spool — link NFC without a receipt

1. "Link NFC to spool" → the spool's own FM QR code → its card.
   Another route: "Spools" → find and open the card you need.
2. "Link NFC" → "Read Bambu data" → hold the phone against the tag → "Use scanned tag".
3. Compare the FM card with the tag data. If they do not match, cancel and check the card selection.
4. Tap "Same spool — link NFC".

Only the NFC link changes. The number of spools, the material, remaining weight, shelf, QR code, history and installation
on a printer do not change. The NFC link of another card is not transferred automatically. Linking again
to the same card is safe. If the card that owned the tag has been deleted, it still blocks repeated receiving of that tag.

## Where to start testing

It is best to start with scenario 3 on one known spool: write down its ID and remaining weight, link NFC,
and check that the number of spools and the remaining weight are unchanged. Then install it into a free slot
with scenario 2 and make sure the same card was used. Test scenario 1 receiving
only on a genuinely new spool that has not been entered yet. Read it again: there must be no second receipt.

## Limitations

- Working reading is currently designed for the tested format of Bambu factory MIFARE Classic 1K tags with a 4-byte UID.
  Other manufacturers/formats, generic NFC/NDEF and tag writing have not been added; the QR/manual route is preserved.
- If reading fails, no data is filled in. Read again or use QR.
- The current remaining weight, additional colors and the authenticity signature are not read. The UID is an identifier in FM, not a guarantee of authenticity/global uniqueness.
- After a rotation/restart, if the operation screen is lost, sign in and read again. A request that was already sent stays in the log and is retried safely.
- If the result of sending is unknown, use "Check / retry pending operation".
  Do not receive the spool again in another way until the result is known.
- Full testing of the new version on a real phone and printer is still needed: automated tests do not replace it.
