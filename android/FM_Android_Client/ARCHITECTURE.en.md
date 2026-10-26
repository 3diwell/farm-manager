[Русский](ARCHITECTURE.md) · **English**

# FM Android Client — design and further development

## Android 0.15.3: printer QR and repeat of the last job

PrinterQr uses the unchanged Labels and server_id from the mobile inventory metadata.
ScanPolicy.PRINTER checks that the code belongs to the farm and to the ID of the current fleet, and accepts
any printer slot for opening the card. ScannerActivity keeps CameraX,
the real crop, stability, the choice among several tags and the camera lifecycle.
PRINTER turns off OCR and URL opening; ActivityResult returns only the code.
FarmActivity keeps the pending QR when recreated and re-checks FM after the camera.
Scanning makes no changes to inventory or links, does not contact printers and does not start printing.

RepeatPrint allows a fresh IDLE, or FINISH + a successful raw value of the specific transport.
FINISH is not declared safe_idle: a manual repeat additionally requires confirmation
that the plate is clear. The shared PrinterState.ready and the regular printer choice are not extended.
When quality is loaded/enabled, GET /api/mod/quality/print-runs?printer_id=...&limit=2 is read
without an outcome filter, so as not to skip over the last unsuccessful run. The exact
project reference is kept, and the hash is compared with the tree. Without history, only
proven FINISH telemetry and a single match among projects and tasks are used.
Collisions, deleted/archived owners and incompatibility are not resolved by heuristics.
Repeating the current file by name without a hash does not guarantee that the old revision is preserved.

FarmRepository.repeat repeats the read-only check before saving PrintJournal,
verifies the prepared Target, state, reservation and role. It sends one regular
PrintRequest, without cmd/start, force, skip_filament, counter edits or a global plate-clear.
The journal keeps an undetermined result; accepted is tracked by the existing send-jobs.
For a project the server creates a new pjob with its contents; a task keeps source=quick.
The phone does not interfere with FINISH deduplication, task synchronization or module events.
Separate read + POST do not remove the final race between several operators: the final
reservation/hold stays the standard one in FM. Core changes for a new atomic API were not made.

New JVM tests check QR, the choice of the last job, roles, changes/collisions,
a lost response and the journal. An additional Python test runs the extracted standard
handlers on temporary files, in-memory SQLite and transport stubs, and checks
new IDs and counter growth after completion. Neither server.py nor the working FM is started.


## Android 0.15.2: printer control and presets

`PrinterCommand` builds only logical pause/resume/stop and bounded
integer temperatures nozzle/nozzle_l/nozzle_r/bed/chamber. The phone does not build G-code,
does not contact the printer directly and does not use this path to start files.
`FarmRepository` sends commands via POST `/api/printer/{pid}/cmd` with the shared
session. Before sending, the operate permission, the printer and the freshness of the state are re-checked.
Pause/resume/stop are available in the corresponding print phase. A status=ok response
means FM processed the command; the new state is shown only from real telemetry.
There are no POST retries and no optimistic switching of the printer to "Paused" or "Idle".

`PreheatPresets` reads GET `/api/farm-settings`: {ok:true, settings:{preheat_presets:[...]}}.
A missing field uses exactly the built-in PLA/PETG/ABS of the main FM; an explicit
empty array stays empty, and a read error is not replaced with defaults.
The editor works with a draft. On saving, the server presets are read again:
a detected change rejects the write. The POST contains only preheat_presets;
other farm settings are not changed. The server does not provide an atomic
check of the preset version; comparing before the POST does not remove the race between read
and write. The phone does not change this core contract.

Preheating re-checks the selected server preset, then sends the
targets one after another through the same cmd. On a dual-nozzle Bambu, nozzle_l/nozzle_r are used;
the chamber — only with a declared heater and a supported type.
On a refusal/disconnect the remaining commands are not sent; a partial result is reported.
Before each step, permissions and freshness are checked again. Presets are refreshed together
with the card and periodically while it is being viewed. Heating and turning it off are confirmed
with the targets shown; during an active print it is shown explicitly that its temperatures will change.

These core features are independent of inventory. Its rules and the earlier inventory scenarios
are kept. Java requests are additionally checked against a pure command policy and the extracted
preset handlers of the shipped core on a temporary database, without starting FM.

## Android 0.15.1: module contract and the earlier inventory

The actual response of the core's GET `/api/modules` as of 30.09.2026 is an object
`{"modules": [...], "restart_needed": false}`. In 0.15 the client wrongly expected an array,
then treated the failed read as the absence of modules. This hid the entry to inventory and
the material on printers. `FmApi.callArray(path, member)` now reads the declared
array from the object and keeps support for a plain array from older servers.
An unexpected format is not treated as an empty array: `Capabilities.modulesKnown`
shows whether the check completed. On failure, dependent features are hidden with an explanation;
after a successful refresh they are available again. An explicitly missing, disabled or
not loaded module stays unavailable. Independent core screens are kept.

MainActivity keeps the earlier inventory scenarios and the journal of idempotent operations.
When coming from FarmActivity, language and theme are applied again, then
the module, permissions and inventory data are checked. The bottom navigation of both screens uses the shared
`FmStyle.navigationItem`; printer cards use `PrinterTile` on the earlier palette.
`PrinterState.progress` excludes stale progress and leftover values
of a finished file on an idle printer. Sending to print and the camera use the
earlier routes; no new commands, protocols or dependencies were added.


## Android 0.15: standalone core screens

The owner's mandatory requirements are kept in DEVELOPMENT_RULES_RU.md.
MainActivity keeps the connection, intro screen, automatic sign-in and the earlier inventory; after sign-in
it opens FarmActivity. SessionRegistry passes the shared FmApi in process memory, without cookies
in the Intent. After the process is recreated, a missing session returns to the regular sign-in.

FarmRepository reads /api/printers, /api/projects2, /api/staging, the project tree,
/api/modules, /api/auth/status, /api/send-jobs and the standard card extensions.
Capabilities allows only loaded and enabled modules and takes the role into account.
The inventory screen additionally takes into account the declared capabilities of the mobile protocol;
before an inventory POST the module and the operation permission are re-checked, and the journal body is kept.

TelemetryClient reads /ws with the shared session, checks the handshake, parses fragments
and ping/pong, reconnects after a network failure, and closes when the screen is left.
PrinterState allows a choice only with fresh data and an explicit safe idle state.
Print commands go through /api/projects2/{project}/files/{file}/print or /api/part/print
with source=quick. The accepted job_id is tracked via /api/send-jobs. PrintJournal saves
an unknown result before the POST and forbids a new send until it is checked; there are no POST retries.

CameraActivity shows its own minimal CameraPage document. The session is passed only as
an HTTP-only cookie of the same FM; external pages, resources, file access and the JavaScript bridge
are closed. Bambu uses the standard MJPEG, Klipper — WebRTC with MJPEG as a fallback.
Viewing stops on close, when going to the background or when the session expires/is revoked.
There are no new Android dependencies, server routes or changes to printer protocols.

## Android 0.10: brand look without changing working operations

BrandHeader replaces the repeated FM / FARM MANAGER and the drawn FM icon in MainActivity.
Header A — Farm Manager on the left and an ImageView with the original vector 3diwell logo on the right.
All 11 contours, #FFFFFF and #EA5E20 are kept. The intrinsic ratio of the vector matches the viewport,
ImageView uses FIT_CENTER, no tint is applied. In the light theme a dark backing is used.
When width is short with a large system font, the header wraps onto two lines, without ellipsis.

Icon 3 "Glass" is stored as an SVG with the original favicon.svg geometry and a highlight
clipped to the silhouette. Transparent PNGs in five densities are produced from it. It is a regular icon without our
adaptive/round/monochrome backing; a user theme/launcher may apply its own mask.
Origin, limitations and the reproducible render are described in branding/README.md.

applicationId, the debug signing key, SharedPreferences and rotation flags do not change.
Inventory operations, ScannerActivity and the server module were not changed. In the NFC screens only
the name/version number in the diagnostic report changed. The large slogan is replaced with the sign-in title;
the HTTP warning is kept. FM core sections can still be added in the future.

## Android 0.9: bounded crop, position choice and native look

Camera: PreviewView COMPATIBLE/FILL_CENTER, a 240 dp portrait window, landscape with separate
scrolling of the controls. Preview and ImageAnalysis are bound by one UseCaseGroup/ViewPort.
ImageProxyTransformFactory (rotation=true, crop=false) + CoordinateTransform link the coordinates
of the full rotated bitmap and PreviewView. The inverse transform maps AimWindow into the bitmap;
borders are rounded inward. The bitmap is actually cropped BEFORE InputImage.fromBitmap, for both ML Kit
recognizers. There is no fallback to the full frame. Results are mapped back onto the aiming frame and checked
to lie fully inside it. The TransformExperimental opt-in applies to the pinned CameraX 1.4.2.

StableCode requires the same code in consecutive observations for at least 700 ms, at least 3 observations,
an interval of up to 500 ms and bounding box overlap >= .55. A different code, a shift, a miss or a reset clear
the accumulation. This is a UX filter, not proof that a product EAN is unique. ScanPolicy with an explicit
slot/spool/any mode discards foreign/unsuitable FM codes. For a position, a bounded snapshot of
available AMS positions without offline/unconfirmed ones is passed to the private Activity. Full inventory data,
passwords and cookies are not passed in the Intent. Before installation MainActivity refreshes the FM data again.

A stable position QR freezes a preview copy in memory; analysis is paused, and the selected code stays unchanged
until the user explicitly chooses/resets. Confirming with the button returns the code and sends no requests.
Several candidates also freeze the frame; the choice is made by tapping or with an accessible labeled button,
followed by confirmation. The current remaining amount/occupancy are checked again by the earlier business process.
A single spool, after stabilization, returns to the earlier unified receiving. OCR stays an explicit
Latin-text mode with editing/confirmation. Scanning outside the frame is not performed.

A generation token + paused/finished/choosing discard stale asynchronous results. OnPause,
a size/mode change and re-aiming clear the transient choice, frame and hold. A regular rotation
recreates ScannerActivity, but not MainActivity/the session. Rotating the display by 180 degrees updates
targetRotation of both use cases and resets the choice. OnDestroy unbinds only its own use cases:
an old scanner must not turn off the camera of the next scanner through a global unbindAll.

The look is extended inside FmStyle: native action cards, icons on a backing, a distinct hierarchy
of title/description, accessible button semantics, colors of both standard themes, amber for errors.
MainActivity does not change storage schemas, the pending journal, the API contract or transactions. NFC changed only
in the version number header. Support for future FM sections and existing data are kept.

## Android 0.8: single scanning entry, no change to the server contract

MainActivity/BambuReadActivity/NfcCheckActivity explicitly handle orientation/screenSize/
smallestScreenSize/screenLayout without recreation. The existing flexible native View layouts
are re-laid out; MainActivity requests layout/insets. This keeps the current fields, the in-memory
session, the request and the scanner callback on a regular rotation, rather than locking the phone orientation.
ScannerActivity is still recreated, and CameraX is bound again with the new rotation;
in landscape the preview is on the left and the scrollable buttons on the right. The OCR mode is restored from the Bundle.
Process death/other configuration changes are not treated as rotation:
the password is not saved; since 0.12, with the option enabled, the session is restored after an FM check,
no later than 8 hours from sign-in. Without the option, sign-in is required after the process is lost; the pending journal remains.

BambuReader.readReliable repeats the full read exactly once and only after an IOException,
if there is no cancellation. A refusal authenticate=false, an incomplete block and a wrong format are not retried.
Each attempt closes the port and zeroes its keys/blocks; the second one reconnects,
reads all five blocks and checks the UID again. The overall Activity timeout of 15 seconds is kept.
The report contains both attempts; this does not guarantee recovery of a lost radio contact.
A completed flag excludes a delayed extra close of an already successfully closed connection.
The warehouse read starts on entry with an explicit flag and returns only a full result.
Diagnostics separately remain manual, without network/inventory writes.

InventoryRepository.receiptTarget determines prepared/existing/factory. A prepared UUID from a QR
is found in the prepared_labels metadata, then batch_id is passed to the earlier claimRequest (v3).
A foreign farm/slot QR/cancelled/unknown internal label does not become a new product.
A received ticket gets the earlier server-side idempotent no-op; a regular existing QR shows
the card without a receipt request. A factory shared code/text goes to the earlier check form.
The UI states in advance that scanning a prepared QR immediately creates a receipt into the selected shelf.
The local pending.ui_flow=receipt_scan is kept until sending, is not sent to the API and makes it possible
to return to the single scanner even after an incomplete request is restored.
In the next scan the batch is not fixed. The data and payload of old QR codes do not change.
In installation, after a position QR the spool camera opens immediately; a single found instance
leads directly to the earlier confirmation, several candidates require an explicit choice.
In a matching allowed scenario, the scanner lets you switch to NFC as a separate result,
without presenting it as a QR. The final installation/replacement is still checked by protocol 2.

Grounds: the local lifecycle code and the user's report (access to sectors 0/1 obtained,
Transceive failed after block 4), [Android configuration changes](https://developer.android.com/guide/topics/resources/runtime-changes)
and [MifareClassic read/close](https://developer.android.com/reference/android/nfc/tech/MifareClassic).
The exact physical cause of the NFC loss cannot be determined from a single text report.

## Android and module 0.7: NFC as an additional identifier

`BambuReadActivity` stays free of network/inventory dependencies and does not write to the tag.
When called with `warehouse_read`, after a full successful read an explicit button appears
that returns `NfcReading` to MainActivity. An error/unsupported tag gives no result;
switching to a new read clears the previous result. A MainActivity callback lost after recreation
is not restored by guessing: a new sign-in/scan is required, without writing.
The read fields are filled only into the form of a NEW full spool. The user chooses the catalog material
themselves; the color defaults to RGB HEX, not an invented shade name.

The module publishes `nfc_spools_v4`. Protocol 4 over the existing protected spool POST
accepts only `nfc_receipt` / `nfc_attach`; an old module rejects them before writing.
The standard versions 1/2/3 and all 31 routes/policies/print hooks stay the same.
`inv_mobile_nfc(uid PRIMARY KEY, spool_id, created_at)` stores additional links;
the canonical code `nfc:bambu:UID` is also reserved in `inv_mobile_codes` as unique.
On receiving, the earlier `_receipt` is called inside the same transaction with alias + operation journal.
On linking, NOT A SINGLE inv_spools field changes and no ledger entry is written; the old
QR/codes, nfc_uid, remaining amount, location and installed position are kept. Before writing, all
owners of the UID are checked, including deleted cards/old UIDs with separators and different case.
Ambiguity, a shared product code, a foreign owner or a deleted card forbid the write.
Several explicitly confirmed tags may refer to one card, but not the other way round.
A UID is not cryptographically unique and does not prove authenticity. There is no automatic merging by material.

NFC installation resolves the card ID and calls the earlier confirmation/protocol 2:
the checks of the occupied slot, the expected spool, printing/telemetry freshness and the atomic replacement are unchanged.
The shared durable pending journal works for both NFC writes; NFC receipts go into
the existing batch journal for the shared QR PDF. Core files and the installed database are not affected.
The new ZIP is built from the pinned SHA256 of Desktop Labels 0.5.2; only
mobile_api.py and an additional manifest revision change, and its version is strictly 1.7.29.
The sections below are the historical description of earlier stages.

## Android 0.6: separate read-only test of Bambu data

`BambuReadActivity` is opened by an explicit button from the earlier diagnostics screen and is not exported.
`NfcCheckActivity` still does not read protected blocks: the basic test is kept separately.
`BambuKeys` independently implements HKDF-SHA256 per RFC 5869 with the public protocol parameters.
`AndroidBambuPort` allows only Key A for sectors 0/1 and reading blocks 0/1/2/4/5.
`BambuReader` makes one attempt per sector in the background, checks for cancellation between operations,
closes the connection in finally and zeroes the keys/buffers of the read blocks after parsing.
Neither trailers, nor the RSA signature, nor additional colors are read. There are no writing methods.
`BambuData` checks block lengths, the UID match, the text format, the material ID, the weight
and a finite float32 diameter. There is no partial success/substitution of parameters expected by the user.

Reader Mode stays on during NFC I/O. After a result/error/leaving the screen
it is turned off. A separate executor calls close to cancel blocked I/O without waiting
in the UI. Detection gets 45 seconds, reading after detection — 15 seconds;
the transport timeout is 2000 ms. Late callbacks are matched against the current Probe; an old result does not
replace a new one. On pause the attempt is cancelled and is not resumed automatically.
The report and color can be restored after the screen is recreated; keys and the full dump are not saved.
The API, FM databases, QR, inventory operations, printer apps and server ZIPs do not change.

## Android 0.5: isolated NFC diagnostics

`NfcCheckActivity` is a separate non-exported screen opened from the sign-in screen and from "More".
It does not depend on the inventory API/repository; the NFC permission is normal, the hardware is optional.
Reader Mode is turned on only by a button in the active Activity. NFC-A/B/F/V, SKIP_NDEF_CHECK:
no reading of NDEF memory, sector authentication, connect/transceive, keys or writing to the tag.
Only the detection properties cached by Android are used: UID, techList, ATQA/SAK,
MifareClassic availability and its memory geometry. This is not a Bambu decoder.
`ScanGate` accepts one result and blocks late/repeated callbacks. On minimizing,
exiting, opening settings, a result or a 45-second timeout, Reader Mode is turned off.
On return, scanning is not resumed automatically. The report is kept in the screen state
when it is recreated; copying the UID/report to the clipboard happens only by an explicit user button.
`NfcReport` does not determine the manufacturer from the UID and does not declare the phone incompatible only
because one tag lacks MifareClassic. An available interface does not mean a successful read of
protected data. QR formats, server protocols, inventory data and the module ZIP were not changed.

## Desktop Labels 0.5.2: centered templates

Compatibility is still 1.7.29, revision `0.5.2-centered-labels`.
Resources are moved to a separate `desktop-0.5.2` path to refresh the browser cache.
`LabelPrint.labelGeometry` sets common text and QR coordinates for PDF, SVG and printing.
`LabelCore` separates the printed fields from the full catalog caption: a spool has the manufacturer,
material, color and short ID; a prepared label also has the original batch ordinal.
A position has only the printer name and the slot/external holder. The QR payload does not change.
The batch caption is parsed from an immutable snapshot; the diameter is removed only from the printed
caption. The server-side snapshot check and the whole backend are kept unchanged.
Existing print profiles are kept; the "Use example dimensions" button explicitly applies
the new recommended sizes. Sizes: spool 60×75 mm, position 60×60 mm.

## Desktop Labels 0.5 add-on (20.09.2026)

`desktop/` is a separate lazily loaded Vue section of inventory for printing from a PC.
`server/build_desktop_module.py` creates a 1.7.29 ZIP with a separate Desktop 0.5.1 revision,
without changing Android 0.4 and its old build. The initial 1.7.30 ZIP was a packaging error:
the core requires an exact match of the version with the permission registry, not a higher number.
The `version` field stays 1.7.29; the improvement is recorded in `desktop_labels_revision`.
Backend/mobile_api match ZIP 0.4 byte for byte: the earlier routes, checks, transactions, QR and tables.
Only the integration points in InventoryPanel and the module.json metadata changed; print resources were added.
The statements below about the unchanged UI refer to the earlier mobile packages 0.1–0.4, not to Desktop 0.5.
PDF and printing use one vector layout; dependencies and the font are included in the ZIP, without a CDN.
Incomplete prepare/cancel requests are saved before the POST and retried with the same request_id.
Print profiles and incomplete requests are local to the browser origin. Confirmed batches are shared in FM.

Recorded at the owner's request on 19.09.2026: the app is NOT limited to inventory forever.
Later it will be necessary to add the main FM features (printers, jobs, projects, etc.).
This is a planned direction of development, not a promise that these screens are already implemented.

## Boundaries

- `core/FmApi`: the shared connection to FM, session, errors. No knowledge of inventory tables.
- `inventory/InventoryRepository`: the current inventory module, code resolution and data.
- `inventory/Labels`, `LabelPrinter`: QR format version, generation, printing/PDF.
- `ScannerActivity`: the native camera and local recognition, without inventory writes.
- `MainActivity`: the shell and the first user scenarios. When the next section is added,
  the inventory screens are moved into standalone Fragment/ViewModel; the transport is kept.
- `server/mobile_api.py`: an additional safe write path INSIDE the inventory module.
  The phone does not read SQLite directly; the standard tables, statuses, journal and links are kept.

## What we keep unchanged

The original 1.7.29 ZIP, the working FM installation, working databases, LAN settings and users.
The package is built separately. The list of HTTP routes, policy_id, handler names and print hooks
do not change. Old requests without the `mobile` field run the original handlers.
The module UI is the original byte for byte. The prototype does not replace the FIFO function, does not zero remaining amounts,
does not start printing and does not close incomplete jobs.

In the test ZIP the manifest keeps the compatible version 1.7.29. This is NOT an official release of the same
version: the ZIP name contains `mobile-prototype-0.4`. The metadata keeps `mobile.protocol=1`
for the old client and declares `slot_exchange_v2` / `prepared_labels_v3` for new operations.
A public release must get a new version and pass the policy registry check of the current
FM 3.0 core; passing the prototype off as a standard package is not allowed.

## Mobile protocol 1

Prepared labels protocol 3 / client 0.4 are described in `PREPARED_LABELS_PROTOCOL.en.md`.
It is a separate registry in FM, not the creation of zero/virtual spools in the main inventory.

GET `/api/mod/inventory/filament` additionally returns `mobile`:
`protocol`, `server_id`, `codes[]` with `code`, `kind`, `filament_id`, `spool_id`.
`server_id` is stored in inv_settings; our own QR codes are tied to this FM database, not to an IP.

The POST of the existing `/spool` accepts the regular fields of a new spool and `mobile`:
`protocol`, `server_id`, `request_id`, `code`, `code_kind` (product/unique).
For a new product, `filament` (vendor_name, material, color_name, diameter) is allowed.
Receiving requires an existing location and a positive finite weight. Partly used spools — through FM.

The POST of the existing `/spool/{sid}/bind` additionally accepts the same envelope.
Checked are the real printer_id/index, freshness, an allowed idle state, active
pending records, the presence and remaining amount of the spool, slot occupancy, and a link elsewhere.
In protocol 1, moving and replacing in an occupied slot are still forbidden.
External feed is always -1; slot 0 is never turned into external feed automatically.

`inv_mobile_ops`: operation number, hash of the full request, confirmed result.
`inv_mobile_codes`: a shared product code OR an individual spool code. Re-learning an existing
link is forbidden. Deleting a spool does not free its factory individual code for reuse.
Writing the spool, the journal, the code and the idempotency result is one transaction under lock_inv.
All new operations require the standard permissions of the existing route; there are no own authorization bypasses.

On the phone the request is saved before sending. After a failure/restart, exactly that request is retried.
401/403, a dropped connection and 5xx do not mean cancellation. There is no automatic retry with a new number.
Changing the server address does not carry an incomplete operation over to another farm.

## Removal and replacement — protocol 2 (client 0.2)

The same POST `/spool/{sid}/bind` is used, with the existing permissions and access checks.
Envelope: `mobile: {protocol: 2, operation: "bind" | "replace" | "unbind", server_id, request_id}`.
The body must contain `printer_id`, `ams_slot`, `external`, `expected_spool_id` — the exact spool
shown in the confirmation; for a free position an empty string is expected.
Receiving stays on protocol 1. The QR format and the farm identity do not change.

The old `/unbind` is deliberately NOT used: the original handler ignores the request body
and would not be able to reject the new protocol on an old installation. The bind route with the 0.1 mobile
wrapper rejects protocol=2; this is checked by a test against the saved 0.1 archive.
The client additionally checks the feature before showing the new operation.

Scanning a position is read-only. Confirmation records the expected old spool.
Under lock_inv and BEGIN IMMEDIATE, the position, printer freshness/idle state,
the absence of pending prints for the printer and both spools, and the match of the expected link are checked.
Two records on one position are treated as an error, not chosen at random.
A new spool installed elsewhere is not moved silently.
On replacement, the standard `_inv_unbind_spool_sql` removes the old spool without an intermediate commit,
then the new one is installed; an error rolls back the whole operation. On removal the same
standard helper is called. Weight, price, material and location_id do not change; loaded becomes in_stock.
Zero `move` records supplement the journal without creating consumption or a repeated receipt.
The result and the request ID are saved in the same transaction. A retry returns
the saved result, even if the spool was later installed in another position again.

## QR

- Spool: `fm1:spool:<server_id>:<spool_id>`.
- Position: `fm1:slot:<server_id>:<printer_id>:<index>`.
- No IP, password, session cookie or weight. The content is not executed, links are not opened.
- An unknown version, another farm or a wrong tag type are blocked.
- Factory strings are kept literally (with leading zeros, case and URLs).
- EAN/UPC/SKU identify a product, not automatically a specific spool.
- A manufacturer QR is not considered unique without explicit operator confirmation.

## Client 0.3: look and batch QR codes

The server extension stays at 0.2, without new routes/tables and without core changes.
`ui/FmStyle` uses the standard FM palette: #18181B / #27272A / #4DA6FF; the light variant
has the same shape language and a darker accent for readability. Icons are vector, without new
libraries; the main screen is adapted for a phone rather than repeating the desktop grid.
The native camera keeps the old recognition mechanism; a scenario hint and a flashlight are added.

`ReceiptBook` is only a local journal of confirmed receipts in SharedPreferences.
A batch is identified by server_id + UUID; the history of another farm is not shown. Creating a batch
does not create a receipt. Before the POST, the batch context/caption are saved together with the pending request.
After confirmation, writing the batch and deleting pending are done in one commit. A retry
is deduplicated by spool_id within the farm. A shared JOURNAL_LOCK protects read-modify-write
when the Activity is recreated; a late response of an old screen does not delete a newer pending.
An old pending from 0.2 goes into a restored batch; request_id/body do not change.
This is not background synchronization and not a shared journal for several phones.

`LabelSheet` checks a set of 1–500 unique spools of one inventory and sets a 2×4 grid.
`LabelPrinter.writeSheet` creates one PDF with the native PdfDocument; the QR is drawn with vector
modules with a 4-module quiet zone, without keeping hundreds of Bitmaps. The PDF is black and white regardless
of the app theme; lines are truncated only by the space available for the caption, the ID stays separate.
Export uses CreateDocument (the system file picker), without broad storage access.
A snapshot of the selected labels is saved before opening the file picker, outside the Bundle, so that a large
batch does not overflow the Activity state limit. Export does not call inventory POSTs.
The batch history keeps data as of receiving, not the current spool status/remaining amount.

## Plan of the next stages

1. Check on a real Android device and a test copy of FM 3.0: sign-in, camera, receiving, AMS/CFS/external.
2. Cyrillic OCR, additional manufacturer parsers, label profiles based on real samples.
   Currently QR codes/barcodes are read locally; OCR is Latin only, and the operator confirms the text.
3. A faster receiving flow for known products, batch marking, label size templates.
4. Separate sections for printers/jobs/projects, server-side capability checks for every action.
5. A shared navigation layer, full screen restoration, a safe long-term
   server-side device authorization for sign-in after an FM restart, a signed production APK.
   Since 0.12 a regular session is kept encrypted for up to 8 hours, the key is in Android Keystore.
6. If needed, HTTPS with a trusted/pinned certificate — without turning off TLS verification.

## Look and language of Android 0.13

`ui/FmActivity` sets the app locale for all four Activities. Russian and English are chosen
in the app settings independently of the phone language. When the setting changes, the resources
and theme of the current Activity are updated, then the settings screen is rebuilt; the Activity, FmApi and the operations journal
are not recreated. Subsequent screens get the same saved setting.

`i18n/I18n` serves the strings of the interface, exceptions, NFC reports and PDF. The shared catalog
`app/src/main/resources/i18n/en.json` is packaged into the APK and is also available to JVM tests. The key is the original
Russian phrase, which keeps compatibility with the existing checks. The translation is applied
only by an explicit call for app strings: server data, the QR payload, user-defined names,
network fields and identifiers do not go through the translator. Android resources (the intro screen and system
widgets) use the Context locale and `values-en`. New text requires an entry in the catalog;
a translation completeness check is included in the build.

`FmStyle` is the shared palette for screens and system bars. The base themes are set up for native
dialogs, lists and switches. On API 26 the navigation bar stays dark for readability of
the light system buttons; dark navigation icons are applied from API 27.
The light intro uses the app background, dark greetings and a thin shadow under the white parts
of the logo. The original fills #FFFFFF/#EA5E20, paths and timing are kept. The Android 12+ system splash screen
before the Activity is drawn stays a neutral dark one without a large icon: the OS draws it
before the user settings are read.

## Android 0.15.4: view and personal sorting

FarmSort performs a pure sort of a copy of the list, with natural number order
and a stable comparison of identifiers. Printer statuses take PrinterState.fresh into account;
file readiness separately takes into account whether a prepared file exists and whether the plan is fulfilled.
projectFiles gathers the displayed parts from children/extra_files in separate copies of
the JSON: the original tree and the PrintRequest bodies do not change. "Parts in progress" refers
to the overall parts plan, "Printing" — to status=printing of the file itself.

CompactFileRow splits opening the details and the print action into two accessible
elements. Only the thumbnail/icon has a fixed size; the text height is determined by the content.
FarmActivity saves farm_sort_* and farm_sort_reverse_* separately for printers,
project files and tasks in the earlier SharedPreferences, without new server requests
or queue changes. When sorting by status, the existing Views are rearranged;
the visible printer is kept, and rearranging is postponed after touches and while TalkBack is on.
All commands use the earlier FarmRepository, PrintRequest and PrintJournal.

## Known security and compatibility limitations

HTTP is explicitly allowed for the sake of a trusted LAN and does not encrypt the password/session.
HTTPS uses the standard certificate check; there is no trust-all/ignoring of errors.
The app does not save the password; backup of app data is disabled.
There is no offline inventory writing, no background queue of new operations, no cloud lookup of labels.
Scanning does not guarantee that a code recognized from the manufacturer contains composition/color/weight.
Restoring/cloning the database carries the server_id over: before using two independent
clones as different farms, a procedure to change the identity and reissue labels will be needed.
Status freshness does not provide atomicity with starting a print from another core client:
general cross-module arbitration of print starts is a separate core task. Do not change spools in parallel
with starting jobs. The prototype does not promise to remove this existing core race.
# Android 0.11: standalone native intro screen

MainActivity first prepares the earlier connection screen, then on a new launch overlays
LogoIntroView. The vector IntroRenderer uses curves and computed transforms from Blender 06;
ValueAnimator interpolates frames over time. The background and greeting belong to separate Views.
No video decoders, WebView, PNG sequences or new dependencies were added to the APK.
Gradients/thin edges adapt the 3D sample for Canvas; the exact Cycles lighting is not reproduced.

The playback state is kept on recreation; onPause/onResume pause/resume
the animator, onDestroy removes callbacks. After completion or "Continue", the already prepared
screen is shown. With system animations turned off, the intro is skipped. No automatic sign-in,
server waiting or fake loading progress were added. On Android 12+ the system splash uses
the earlier app icon and a matching dark background, then control passes to the View.


## Android 0.15.5: nullable JSON and card presentation

FarmValues.text checks JSONObject.isNull before optString: Android libcore
JSON.toString(JSONObject.NULL) returns the string "null". RepeatPrint applies
it to all nullable history fields, exact links and the confirmation signature;
real non-empty hashes are not ignored. FarmActivity also normalizes file_id
before creating a PrintRequest. The API schema, the server and accounting were not changed.
Android source: https://android.googlesource.com/platform/libcore/+/refs/heads/main/json/src/main/java/org/json/JSONObject.java

NotificationBook is stored in farm_notifications_v1, separately from PrintJournal.
The scope key is origin + accountKey from /api/auth/status (username; for auth-off
a shared scope "shared"). send-jobs statuses update one record; periodic
progress does not create new unread ones. HMS is saved only from a fresh snapshot;
when an error disappears and appears again, the unread mark is restored.
While capabilities/data are being refreshed, records are not saved under an intermediate
account. The center keeps the earlier manual check of an unknown run;
readAll has no access to PrintJournal. A short message lives for 6 seconds.

MaterialSlots is a pure model over ams_trays/cfs_trays/ext_tray/ext_trays and
the optional GET /api/printer-filament. When stale, there is no active position and no
percentage; an undetermined legacy index0 does not become external. AMS HT indexes
512+ do not create regular blocks of 4 slots. For two external spools, the inventory weight at
index=-1 belongs only to the main 255; the left 254 is separate. MaterialSlotsView
draws the palette/frame and wraps cells; tapping only shows details.
An RRGGBBAA color is normalized to RGB, without reordering channels as Android ARGB.

ProjectProgress uses done_count / parts_count, like
web/components/projects/ProjectCell.js. ProjectTile draws progress along the length of
the rounded perimeter. Projects are re-read only in the open project list
in the regular 10-second cycle. The video icon repeats the geometry of pp-cam from
web/design/icons.js and opens the earlier CameraActivity. The camera buttons and cards
have separate accessible actions. No new libraries/protocols were added.
