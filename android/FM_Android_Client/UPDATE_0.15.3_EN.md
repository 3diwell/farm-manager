[Русский](UPDATE_0.15.3_RU.md) · **English**

# FM Android 0.15.3 — printer QR and repeating the last print

Install FM-Client-0.15.3-debug.apk over the previous app, without uninstalling it.
The application ID, signature and saved data stay the same.

## Operator scenario

1. Open the "Printers" tab and tap "Find printer by QR".
2. Point the phone camera at an existing sticker of an AMS/CFS slot or an external
   holder of this printer. After a stable read, its card opens.
   If there are several tags in the frame, choose the printer by name.
3. Remove the finished part, prepare the bed and the material.
4. In the card, tap "Repeat last print". FM finds the file of the last
   successful start and shows the file name, the printer and the accounting location: a project or a task.
5. Check the material source and the parameters. Tick "The part is removed; the plate is clear and ready for a new print",
   then tap "Start print".
6. Watch the submission and the live state. An accepted request does not prove that
   the printer has already started printing. After successful completion, the FM counter increases
   under the usual project/task rules; the count is not limited by the planned quantity.

## Availability

- The QR code uses the existing fm1:slot:<farm>:<printer>:<slot> format. The stickers do not need
  to be changed. Any slot of one printer opens the same card; a spool QR code,
  a QR code from another farm, an arbitrary URL and a missing printer are rejected.
- Checking which farm a sticker belongs to requires a loaded, enabled inventory module
  with mobile protocol 1 and server_id. Without it, the QR button is hidden. A spool does not need to be present in
  the slot or the slot occupied: scanning only opens the card, inventory does not change.
- A view-only user can scan a printer. Repeating requires the operate right.
- Repeating works independently of inventory. When quality is available, the last
  start of this printer is read; after an unsuccessful/unknown start, an older successful
  file is not selected automatically. On a free printer, repeating is available based on this history.
- Without quality, repeating is possible after a fresh, proven successful completion with a reported
  file name. The name is searched among all available projects and tasks. There must be exactly one
  unambiguous match. A name without an extension from the firmware is handled with caution.
- The exact link of the history to the project/file is kept; another project or task with the same
  name does not replace it. An archived/deleted project, a changed hash, a missing,
  incompatible or unprepared file block repeating. A missing project file
  on disk is additionally checked by the standard FM handler before the job is created.
- The FINISH state is acceptable only together with a successful raw status of the specific brand
  and an explicit confirmation that the bed is clear. Printing, pause, error, cancellation, an unknown
  state, stale data and an active submission block repeating.

## Accounting and preserving previous behavior

The phone sends a new regular job via /api/projects2/.../print or
/api/part/print with source=quick. FM creates a new submission, a new project job,
and start and completion events for the installed modules. The phone does not edit counters;
inventory checks and the project/task synchronization chosen by the owner are kept.
The previous slot/holder from the QR code does not automatically become the material source for the print.
The parameters and the material are checked in the regular dialog before the new start.

Before sending, the rights, the printer fleet, the history/file name,
compatibility, the hash/available file mark, the state and submissions are checked again. A changed start
or file cancels the old confirmation. The server does not provide an atomic
"repeat this start" route: a race after the last read cannot be fully eliminated without changing
the core. With several operators, the final reservation/hold protection is performed by FM.
Without history/hash, the firmware reports a name, not an immutable copy of the file: this is a repeat of
the current, unambiguously found FM file; the phone does not restore an old deleted revision.

If the result is uncertain, the previous waiting log is kept; there is no automatic
POST retry. The reprint button is blocked until the submission is checked.
The clear-bed confirmation is local to this start: no global plate-clear token,
which could allow the queue to auto-start, is created. Real printing starts only
after an explicit "Start print".

The core, installed modules, databases, stickers, dependencies, signature, themes and logos have not changed.
Inventory, NFC, pause/resume/stop, preheating and the printer camera are kept.
The build has been checked automatically against stubs and isolated data. Tests on the phone,
a real FM and physical printers are performed by the owner.
