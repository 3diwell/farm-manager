[Русский](android.md) · **English**

# Phone: the FM Client app

The Android app connects to Farm Manager on the local network. Build 0.15.15 can do the following:

- **Farm:** printers with live data (state, temperatures, material in the slots), camera,
  pausing, resuming and stopping a print, heating and preheat presets, notifications.
- **Printing:** projects and tasks, launching a print of a file on the selected printer, "repeat the last
  print".
- **Inventory** (requires the Inventory module): receiving spools, labels, scanning QR and NFC,
  loading a spool into a printer, replacing, unloading and writing off an empty spool.

The app file is `FM-Client-<version>-debug.apk` in the project's modules folder. This is a developer's
test build: before handing phones out to workers, a final (release) build is needed.

## Which phone you need

- **Android 8 or newer** with the FM Client app. All farm control from the phone — pause,
  stop, heating, print launch, inventory — goes through the app.
- **The phone's browser** opens the program at the same address as on the computer, in a simplified
  view (the "Printers" and "Projects" tabs). This option is for viewing: some of the computer's buttons are
  hidden in it; the full control panel is in the app or on the computer.
- **There is no iPhone app.** On an iPhone the program can be opened only in the browser — for
  viewing.

The phone is a tool for monitoring and quick intervention; full control of the farm stays on the
computer: there is no separate full version of the program for phones.

## Connecting

1. Turn on sign-in protection: *Settings → System → Access & audit*, and create a user for the
   phone (*Users*). The section is visible in any interface mode.
2. Open the program to the network (*Settings → System → Network & access*).
3. In the app, enter the farm computer's address and port, and sign in with your user.

## Which role is needed

The phone follows the same roles as the program on the computer:

| Role | What can be done from the phone |
|---|---|
| Administrator, Operator | everything: printer control (stop, pause, heating, presets), print launch, inventory operations |
| Assembler, Observer | view only |

There is no separate "inventory only" role: a warehouse worker with a phone needs the Operator role, and then they
can also stop and start prints.

## Good to know

- **Stopping, heating and launching a print** ask for confirmation; pausing does not. Launching a print
  requires ticking "the part is removed, the plate is clear".
- **Preheat presets are shared by the whole farm:** a change made from a phone is seen by everyone.
- **Bambu X1, H2, P2S camera:** the program keeps one video stream per printer. While the camera is open on
  a phone (just as in the camera window on the computer), this printer's tile on the Camera Wall
  switches to a slower picture until it reconnects.
- **Klipper printers** print from the phone without the preparation steps enabled in the program
  (for example, bed calibration) and without CFS slot selection. Use the computer for such launches.
- **A command did not reach the printer** (no connection, the printer did not respond) — the program refuses
  a pause, resume and heating the same way it already did for "Stop". The app shows this as
  an error; the print continues as before. Check the connection to the printer and try again.
- **Turning off nozzle or bed heating during a print from the phone is not possible:** the program refuses,
  so as not to ruin the print. You can cool down while paused or after the print; on the computer the program
  asks for confirmation.
- **The audit log**, when protection is on, records printer commands and print launches: who,
  from which phone, to which printer and with what result (*Settings → System → Access & audit*).
- **Before restoring a settings backup**, wait until the phones have sent all
  inventory operations (the app's log of unsent operations is empty): unfinished phone operations are not
  included in the backup.

## "Remember this device"

On the program side the feature is ready: a phone with "Remember this device" ticked would sign in
by itself, including after the program restarts, until access is revoked (signing out in the app, the
*Users → Remembered devices → Revoke* button, a password change, disabling or deleting
the user).

App 0.15.15 cannot do this yet: its checkbox is called "Remember sign-in for 8 hours", and
after 8 hours or after the program restarts you have to sign in again.

## Moving to a new app build

The final (release) build is signed with a different key than the test build, so it cannot be installed
over it: the test build has to be uninstalled, and everything the app stores is deleted with it —
including scanned but not yet sent inventory operations. The order is:

1. Wait until the phone has sent all inventory operations (the log of unsent operations is empty).
2. Only then uninstall the old app and install the new one.

## Connection to Google

QR code and text recognition in the app is built on the Google ML Kit libraries. If the
phone has internet access, these libraries may send Google information about how they work (according to
Google's description — the phone model and version, recognition speed). We have not intercepted the exact
contents. The connection between the phone and the farm program itself goes only over the local network.

## Security

The connection between the phone and the program goes over the local network without encryption, and the phone can now
control printers. Connect phones only on your own farm network, and give the Operator role
only to those who are allowed to stop and start prints.
