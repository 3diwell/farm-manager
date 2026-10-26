[Русский](UPDATE_0.13.0_RU.md) · **English**

# Farm Manager Android 0.13.0 — theme and language

Install `dist/FM-Client-0.13.0-debug.apk` over 0.12.0. Do not uninstall the app or delete its data.
Settings, the saved sign-in and pending operations are kept during the update.

## Where to switch

Before sign-in: **App settings**. After sign-in: **More**.

- **Appearance** → **Dark** or **Light**.
- **App language** → **Русский** (Russian) or **English**.

In the English interface: **App settings** / **More** → **Appearance** / **App language**.
The language names are always shown as "Русский" and "English", so that you can always switch back.
The choice takes effect immediately, is kept between launches and does not require a new sign-in.
Theme and language are independent: all four combinations are available.
On update, the previously selected theme is kept; the initial language is Russian.

The light theme applies to the connection screen, settings, inventory, spools, labels, dialogs,
the camera, NFC and the welcome screen. The camera area itself shows the camera image;
QR codes and printed sheets keep a black-and-white look suitable for scanning and printing.
The brand logo stays orange and white. In the header of the light interface, the
contrasting background of the approved logo is kept; in the intro, a thin shadow has been added under the white facets.

629 source phrases have been translated, including error messages, instructions, scanning,
NFC diagnostics, PDF headings and the four time-of-day greetings.
System elements inside the app receive the selected locale. External Android settings,
OS permissions and the system file picker may follow the language of the phone itself.

Data from FM is not translated: the names of printers, materials, colors, storage locations,
batch names and user-entered captions stay as they are. Label captions that have already been saved
and historical reports are not rewritten when the language changes. New service headings
and reports are generated in the selected language. OCR recognition, as before, supports Latin script.

## Preserved features

Sign-in for up to 8 hours, connection retry without a password during a temporary network loss, deletion of the saved
sign-in on sign-out and the welcome screen switch remain available.
Changing the appearance/language does not extend the session and does not send inventory operations.
The FM core, the server module, the QR protocol, the NFC algorithms and the geometry/timing of the intro have not changed.

## Testing on the phone

1. Before sign-in, open the settings: switch to Light / English, return to the connection screen.
2. Sign in, open More, check both languages and both themes. Changing the settings must not sign you out.
3. Check lists, selection dialogs, the receiving form, the QR scanner and NFC in both appearances.
4. Close the process and open the app again: the settings should be kept; a valid
   eight-hour sign-in should be restored under the same rules as before.
5. Check the intro and the greeting in the selected language, then turn off the welcome screen.
6. Generate a test PDF in English: the headings should be in English, while user-entered
   names and the QR contents stay the same.

There is no connected Android device/emulator in the build environment. The checks are automated;
the reference images of the intro were produced by a desktop renderer of the shared vector data;
they are not Android screenshots. The native interface, language switching and the Keystore need to be tested on the phone.
On Android 8.0 the bottom system bar stays dark so that the system buttons remain readable.
The short Android 12+ system screen before the app starts stays neutral dark;
the enlarged app icon on it is still hidden.

Previous APKs and a backup of the sources are kept. Release materials:
`F:/Codex/Intro/Android_Localization_v06/`.
