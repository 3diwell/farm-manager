[Русский](creality-stock.md) · **English**

# Creality printers on stock firmware

Ender-3 V3 KE, Ender-5 Max, K1 and other Creality printers run Klipper, but the stock firmware
has no Moonraker. The program connects to them through the same printer service that Creality Print uses. Root and
printer modifications are not needed. Support is experimental: it was built from the description of this service and
has not yet been tested on your printers.

## How to connect

1. *Printers → Add*. Choose the model, for example "Creality Ender-3 V3 KE" or "Creality Ender-5 Max".
2. In the **Creality** section, choose "How the printer is connected" → **Stock firmware (no root)**.
3. Enter the printer's IP address (it is in the network settings on the printer's screen). Leave the "Port" field
   empty.
4. "Add".

If you choose Moonraker but the printer responds only with its own service, the program offers to switch by itself.

## What should work

- The printer card: state ("Idle", "Printing", "Paused"), nozzle and bed temperatures, percentage and
  remaining time, file name.
- Sending a **.gcode** file sliced for this model (Creality Print, Orca, etc.) to print.
  The program uploads the file to the printer, checks that it appeared in the printer's file list, and starts
  the print. The send counts as successful when the printer itself reports that it is printing. A printer on
  stock firmware does not print .3mf files — the program will tell you so.
- Control panel: pause, resume, stop, nozzle and bed temperature.
- Camera, if one is connected to the printer (more details below).

The printer must be on the same network as the computer running the program. The printer ports 9999 (service) and 80
(file upload) are needed, and for the camera — 443, 8000 or 8080. You do not need to open them; the printer listens on them by itself.

## Camera

- On the K1C and K1 Max with firmware 1.3.5.22 or newer, and on the K2 family, the camera works over WebRTC. The program
  opens it the same way Creality Print does: it gets the camera key from the printer through the 9999 service and connects
  over HTTPS (port 443); the fallback paths are ports 8000 and 80. Video goes directly over the farm network; no internet
  is needed.
- On the Ender-3 V3 KE and older K1 printers the camera serves an MJPEG stream on port 8080. If the printer reports that it has no
  WebRTC, the camera window opens this stream right away.
- The Ender-5 Max connects through the same service as the KE.
- If the camera does not open, open the camera window, then press "Diagnostics" on the printer card. The "Camera"
  line shows which paths the program tried and the printer's firmware version.

## If something is wrong

*Settings → System → Diagnostics*, the "Download logs" button — send us this file. On the first connection the program writes to
the log what exactly the printer reports — without its name, address or serial numbers. We will use this record to fix
the connection.
