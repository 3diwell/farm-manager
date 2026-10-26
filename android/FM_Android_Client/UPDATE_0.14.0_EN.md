[Русский](UPDATE_0.14.0_RU.md) · **English**

# FM Android 0.14.0 — visual operation hints

New package: `dist/FM-Client-0.14.0-debug.apk`. It installs over 0.13.0 with the same signature and application ID. Previous APKs are kept separately. There is no need to uninstall the installed app before updating.

## What has been added

The approved set of images is built into the scanning, manual entry, selection, confirmation and success screens:

| Operation | Hint |
| --- | --- |
| Receiving into inventory | Full black spool → 3D warehouse |
| Installation, choosing a position | Printer No. 3 "Open gantry" |
| Installation or replacement, choosing a spool | Full black spool → printer |
| Removal from a printer | Printer → almost empty spool → warehouse |

The object whose code the camera expects is highlighted with a frame and a caption. For removal, both existing methods are allowed: the position QR code and the code of the installed spool. NFC receiving and NFC installation use the same diagrams without the hint to aim the camera.

The icons have a transparent background; the captions and styling support the dark/light theme and Russian/English. The installation, replacement and removal confirmations scroll together with the images, so that the data and buttons stay accessible on small screens. The main camera keeps the previous sight, recognition inside the frame and manual position selection.

The brand orange check mark appears after a successful response from FM. Reading a code, choosing a position, NFC reading, cancellation or an error do not show a successful inventory change. A repeated submission keeps the explanation about the operation that was already performed.

## What the images mean

The full and almost empty spools indicate the type of action, not the real amount of plastic. The actual remaining weight is shown in the card and the confirmation. Removal frees the printer position and keeps the remaining weight, the history and the previous storage location; this operation does not assign a new shelf.

The code of the FM core and the server module has not changed. This version changes the Android interface and local resources. Sign-in saving for 8 hours, the intro and the theme/language choice are kept.

## Testing on the phone

Automated checks and build information: `VALIDATION_MOBILE_0.14.md`. No physical phone or emulator was connected while the package was prepared; camera/NFC operation and the final layout on the device need to be tested.

To test the interface, open receiving, then installation (position → spool) and removal. Check both themes and both languages, an enlarged font size and phone rotation. Before you tap the installation/replacement/removal confirmation, there must be no check mark. Test receiving by a prepared QR code on a test spool: its current scenario sends the receipt to FM immediately.

## Editable resources

The exact SVGs from the approved set are kept in `branding/operation-hints/`. For Android they have been converted to PNGs with an alpha channel, up to 384 px on the long side, without changing geometry or colors. The script `branding/render-operation-hints.cjs` and `raster-manifest.json` keep the process reproducible and record the hashes of sources/results. The set `F:\Codex\Intro\Android_Operation_Hints_v06_Approved` has not been overwritten.
