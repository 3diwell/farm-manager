[Русский](UPDATE_0.15.1_RU.md) · **English**

# FM Android 0.15.1 — inventory and appearance

APK: `dist/FM-Client-0.15.1-debug.apk`. Android 8.0 or later.
The package and signature are unchanged; versionCode 19. Install it over 0.14 or 0.15
without uninstalling the app, to keep the settings, sign-in and operation logs.

## Why inventory disappeared

In 0.15 the client expected an array from `/api/modules`. Your core returns an object
containing a `modules` array. The parsing error turned into an empty list,
so the app hid inventory as missing. The inventory scenarios themselves
and the data were not deleted. The fix was made in the Android client.

Both formats are now supported. If the module check fails, the app
reports it and offers to refresh the data. Such an error is distinct from
a confirmed absence of inventory. The installed and loaded module,
user rights and the supported operations of the mobile protocol are taken into account.

## What has changed on the phone

- "Inventory" is back in the farm's bottom bar and in "More". The inventory bar has "Farm".
- Spools, receiving, installation/replacement, removal, QR/NFC, labels and PDF are kept.
  The buttons for the corresponding operations are available when the rights and server support are present.
- The bottom bars use familiar icons and highlight the active section.
- Printer cards are more compact: name, model, colored status, file and progress.
  Tapping opens an expanded card. Progress is hidden when fresh data is lost
  and for a free printer with a leftover value from the previous print.
- Refresh has been moved to a compact button next to the connection status.
- Theme and language are chosen the same way as in the previous app. They also apply
  when you go back to inventory. The NFC check is also available from the farm's "More".
- The camera has a compact panel for going back and reconnecting; more room for video.
- An empty submissions panel is hidden and comes back automatically when a submission appears.

The palette, logos and styling of the previous Android app are kept.
The FM core, server modules, databases and protocols have not changed. There are no new dependencies.
An unknown print result is not retried automatically; saved inventory
operations keep using the previous request number.

## Testing on your phone

1. After the update, sign in to the same FM on the local network; open "Inventory".
2. Check the list and the spool card, the usual QR/NFC and the labels section.
3. Look at the printers and the expanded card, then the camera of a supported printer.
4. Switch the theme and language in "More" and go back to inventory.
5. Check the layout of the text and the bottom bar at your font size.

Automated results: `VALIDATION_MOBILE_0.15.1.md`. A real phone,
camera and printing were not tested in this environment. If inventory is available only for
reading, check the rights and the support for mobile operations in the installed module.
