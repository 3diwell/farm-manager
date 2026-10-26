[Русский](UPDATE_0.15.2_RU.md) · **English**

# FM Android 0.15.2 — print control and preheating

APK: `dist/FM-Client-0.15.2-debug.apk`. Android 8.0 or later.
The package and signature are unchanged; versionCode 20. Install it over the current version
without uninstalling the app, to keep the sign-in, settings and operation logs.

## Printer card

- **Pause** — while printing, preparing or slicing.
- **Resume** — appears instead of "Pause" when FM reports that the printer is paused.
- **Stop** — a confirmation for fully stopping the current print. After it,
  this print cannot be resumed. The command is the same as the stop button in the main FM.
- **Preheat presets** — a shared server-side set; the built-in PLA/PETG/ABS are used
  until the owner saves their own presets. Preheating shows the targets before confirmation.
- **Edit presets** — name, nozzle, bed and an optional heated chamber; up to 24 presets.
  Saving changes the shared set for the whole farm, as in the main application.
- **Cool down — turn off heating** — the targets of the nozzle, the bed and a supported chamber are set
  to zero. If a print is running, the app warns before confirmation that the temperatures
  of the current print will change.

For a dual-nozzle Bambu, both nozzle targets are set. The chamber temperature is applied
only with a supported heater; a chamber sensor on its own does not mean heating.
An empty chamber value in a preset leaves its current target unchanged.

The limits follow the FM policy: nozzle 0–350 °C, bed 0–120 °C, chamber 0–65 °C.
The actual capabilities of a particular printer are determined by its firmware and the main FM.
Invalid, fractional and out-of-range values are not sent.

## Availability and confirmation

Control is available with the corresponding rights, a supported printer type
and a fresh state. In view mode the control sections are hidden; when the connection
is lost, commands are unavailable. These functions do not require the inventory module.

The app does not show a printer as stopped or paused based only
on the response to a command: the state comes from live FM data.
After a connection loss or partial preheating, check the state and targets in the card;
there will be no automatic repeated commands. A selected preset that has changed on the server
cannot be applied from an old window. A detected change of the shared set also
stops an old draft from being saved.

Commands go only through the standard FM on the local network. The core, modules, databases,
printer adapters and the previous inventory/file printing scenarios have not changed.
The styling, themes, languages, logos and app signature are kept.

## Testing on the phone

1. Sign in with control rights and open the card of a printer that is printing.
   Pause it, wait for the corresponding state and resume.
2. On a print that can be interrupted, check "Stop" and the confirmation.
3. On a free printer, apply a suitable preset and check the temperature targets.
4. Change a preset and check the same set in the main FM. Then check "Cool down".
5. Check both themes, the language, the text size and access to the previous inventory sections.

Summary of automated checks: `VALIDATION_MOBILE_0.15.2.md`.
No real phone or printers are connected in this environment; hardware execution
of the new commands and the native interface need to be tested by the owner.
