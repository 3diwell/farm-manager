[Русский](UPDATE_0.15.5_RU.md) · **English**

# FM Android 0.15.5 — fixes from phone testing

Install dist/FM-Client-0.15.5-debug.apk over the current version, without uninstalling
the app. The connection data, theme, language and sorting settings are kept.

## Repeating a print

Fixed a false message about a changed file when the FM history contains
file_hash: null. Android turned this value into the text "null"; now an empty
value is treated as the absence of a fingerprint. Nullable
identifiers, names, staging_file and the file snapshot before confirmation have also been fixed.
A real non-empty fingerprint is still strictly compared with the current file.
The checks of the source/project, a successful last start, freshness, compatibility,
reservation and a clear bed are kept. Repeating creates a regular new
job through FM; the phone does not change counters and does not send commands to the printer directly.

## Notifications

The bell next to refresh opens "Notifications". The number shows how many
unread messages there are; reading them when the screen is opened is remembered after a restart.
Submissions, errors and printer messages no longer take up space above the printer
list. Short operation messages disappear after 6 seconds and stay
in notifications. Confirmations of start, stop and other actions are kept.
The submission status is updated in a single entry; progress does not increase the counter.
A printer error that appears again is marked as unread again.
The history is stored only on the phone and is separated by server and account,
up to 100 entries per account and up to 500 in total. Old submission errors
are kept even after the job disappears from the FM list.

If the result of a start is unknown, the bell keeps a "!" mark and
the notifications offer a result check. Reading a notification does not remove the block on
resubmission. The mark is cleared by a confirmed FM result or
after the existing explicit operator confirmation "I checked the result in FM".

## Cards

The video camera icon matches pp-cam in the main application. It is on the right
of the printer card header, next to the name and the image, both in the list and
in the detailed card. The phone camera for QR remains a separate action.
Support for Bambu/Klipper streams uses the previous API and the previous limitations.

In the detailed card, material is shown by slot: color, material, the active
slot with a blue frame and a dot. AMS, AMS HT, CFS and external spools are separated;
slots wrap to the next line on a narrow screen. The remaining amount is shown under each one.
Tapping opens the details without changing the link or the feed source.
For a confirmed inventory spool, remaining = remaining weight / initial weight;
if this data is missing, the printer's percentage is used. If there is no reliable remaining amount,
"—" is shown, without assuming a full spool. An explicit zero remaining amount is shown as 0%.
An empty slot is not replaced by an old inventory link. With stale data,
activity and the current percentage are not shown; ambiguous inventory positions
are displayed separately. The left external spool does not inherit the weight of the right one.
Slot telemetry is available independently of inventory; links and weights only when
the inventory module is available. The new functions do not require changes to the core or modules.

Projects show a percentage and a blue frame around the perimeter, like ProjectCell in FM.
The calculation is the same: done_count / parts_count, rounded to a whole percent.
This is the share of completed part rows in the project; printed_total / required_total
is not used in place of this figure. The list is refreshed every 10 seconds
while the projects tab is open; an empty plan shows 0%.

## Testing on the phone

1. Repeat a finished FlashForge print from a task and from a project with an unchanged
   file. Check the new start in FM and the accounting after successful completion.
2. A changed file, an unsuccessful last start and a busy printer must block repeating.
3. Check a submission with an error, the bell, reading, a restart and returning to the previous
   screen. An unknown result must keep blocking a new start.
4. Check the camera, QR, real AMS/CFS/AMS HT and external spools: full,
   partial, zero and unknown remaining amounts, no connection and inventory disabled.
5. Compare the project percentages with FM, including 1/10, 12/13 and 6/6.
6. Check the light/dark theme, a large font, a narrow screen and TalkBack.

The automated checks were run in isolation. The APK has not yet been tested on a phone;
the real FM server and printers were not started or controlled during development.
Build and test results: VALIDATION_MOBILE_0.15.5.md.
