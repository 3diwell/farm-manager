[Русский](UPDATE_0.3_RU.md) · **English**

# FM Client 0.3 — new look and a combined QR PDF

## Installation

Install `dist/FM-Client-0.3.0-debug.apk` over the previous client. Do not uninstall the app
and do not clear its data. The new APK also contains the removal/replacement functions from 0.2.

The new design and PDF do not require changes to the FM core. If the `mobile-prototype-0.2` module is already installed,
there is no need to install it again. If you still have 0.1, receiving and PDF work;
removal/replacement needs the 0.2 module, as described in `UPDATE_0.2_EN.md`.
Before any update, finish any saved pending operation.

## Appearance

- The main FM palette: graphite panels, light-blue accent, line icons.
- "Inventory": receiving, installation/replacement, removal; spool counters.
- "Spools": search by material, color, label or ID, the spool's own QR codes.
- "Batches": the current receiving batch and previous batches, a combined PDF.
- "More": position QR codes, dark/light theme switch and sign-out.
- Camera: operation context, a guide frame, tap to focus, flashlight if available.
- When an existing material is selected, the fields for creating a new one are hidden.

## Receiving several spools and one PDF

1. Open "Batches" → "Start new batch" and confirm.
2. Choose the storage location, scan the spool, check the fields and confirm the receipt.
3. Tap "Next spool". The location stays the same; scan and receive the next ones.
4. Open "Batches", select the current batch → "Download all QR codes as one PDF".
5. In the system dialog, choose "Downloads" or another location and tap "Save".
6. Open the file and print it on A4 at 100% scale. Each page has eight labels with a QR code,
   a caption and an individual ID. Stick each label on its own spool.

If you start a regular receipt without creating a batch, the first batch is created automatically;
further receipts go into it until you explicitly start a new one. Previous batches
are not deleted. One batch can contain different materials and different storage locations.

Each spool is confirmed separately: this is a batch of labels, not a single bulk stock
addition by quantity. The list shows only spools that were received successfully. An error on the next
scan does not cancel the previous receipts. After a connection loss, retry the saved request:
the receipt and the label are not duplicated.

## QR codes for existing spools

"Spools" → "Download multiple QR codes" → tick the spools you need → "Download PDF".
There is search, a selected counter and "Select all / clear selection". The selection is kept while filtering;
the "Select all" button also includes spools hidden by the search. Export changes nothing in inventory.

## Limitations and testing

- Up to 500 spools in one PDF. The format is A4, not thermal label rolls.
- Batches are stored only on this phone. If the app or its data is deleted,
  the local history is lost; the spools themselves stay in FM and their QR codes can be selected again.
- The history contains the captions as of the time of receipt. Later editing/deletion in FM
  does not rewrite an old batch; check the spools before reprinting old history.
- A long caption on a label may be shortened; the individual ID is printed separately.
- Cancelling the PDF save does not cancel the inventory receipt. The PDF can always be saved again.
- Removal/replacement from 0.2 still awaits your real-world testing. The new interface, saving the PDF
  and reading paper labels also need to be tested on the phone; automated tests do not replace this.

For a first try, receive two test spools, save the combined PDF, check that there are two different
IDs and that both QR codes scan. Then test nine spools: there should be two pages with no duplicates.
