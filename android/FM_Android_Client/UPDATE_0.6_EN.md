[Русский](UPDATE_0.6_RU.md) · **English**

# FM Client 0.6 — trial reading of a Bambu factory tag

File: `dist/FM-Client-0.6.0-debug.apk`.

## Installation and testing

1. Install the APK as an update over FM Client 0.5, without uninstalling the app or clearing its data.
2. Open "NFC check" from the sign-in screen or via "More". You do not need to connect to FM.
3. Tap "Read Bambu data" — a separate screen with a description of the test opens.
4. On that screen, tap "Read Bambu data", then hold the phone against the same
   factory spool tag that was previously detected with UID `F6B582CA`.
5. Keep the phone still until the result appears. Do not move it away right after the tag is detected:
   data is now read after detection. Reading is limited to 15 seconds.
6. Tap "Copy report" and send the result here, even if reading ended with an error.
   If needed, move the phone away, change its position and repeat with the button.

The inventory module and the FM core do not need to be updated. Writing to the tag, spool linking and receiving
are not performed from this screen. Use only your own Bambu factory filament tags;
do not hold payment cards, access passes or other unrelated tags against the phone.

## What we expect to see

For comparison, the user reported: Bambu Lab, presumably PETG Basic, Orange, 1.75 mm.
This information is NOT used for identification and is NOT filled in when reading fails.
The result may show the material, variant, material/variant codes, the RGBA of the main
color, the diameter and the factory weight. The name Orange is not shown as a fact that was read: the readable
fields contain a color code. For convenience, an on-screen swatch of that color is shown next to it.
The factory weight is not treated as the remaining weight. Additional colors and the authenticity of the RSA signature
are not checked at this stage.

## If an error occurs

- "Access to sector … was not obtained": reading with the known algorithm was not confirmed.
  The cause may be a different format/keys or a lost connection. Keys are not brute-forced.
- "UID … does not match": the result is rejected and the fields are not filled in.
- "Do not match the … format" / "outside the … range": the blocks are accessible, but parsing is not confirmed.
- "Timeout" / connection lost: move the phone away and try again, holding it against the tag.
- "Not supported": the current test is designed only for MIFARE Classic 1K with a 4-byte UID.

The report shows the reading stages but does not include keys or a full dump. It is not sent anywhere
automatically. After a result, a stop or minimizing the app, scanning stops.
There is no automatic resume — each test is started with the button.

This is an experimental reader based on a publicly researched format, not an official Bambu SDK.
Real compatibility will be confirmed by the result from your phone. Old APKs are kept.
