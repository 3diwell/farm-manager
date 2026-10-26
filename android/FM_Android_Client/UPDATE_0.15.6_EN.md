[Русский](UPDATE_0.15.6_RU.md) · **English**

# FM Android 0.15.6 — layout following the owner's example

Install dist/FM-Client-0.15.6-debug.apk over the current app.
The connection, notifications, theme, language and sort order are kept.

- The bell has moved to the top row between Farm Manager and the 3diwell logo.
  The large frame around the icon has been removed; the counter and the unknown-start mark are kept.
- Refresh is placed directly next to the short caption "Connected"
  or "Connection lost". The server address is available in the settings, in the row tooltip and
  in its TalkBack description; the row no longer takes up space with a long address.
- The QR button has been enlarged to 96dp and moved to the right of the connection block,
  the heading and sorting. It is still available only with a working
  inventory module and a received farm identity. The phone camera and printer search
  use the previous scenario.
- "Farm printers" is placed closer to the connection row: the top margin
  of the heading and its alignment to the height of the former buttons on the right have been removed.
- Sorting is placed next to the caption of the current order. The visible button background is
  32dp, the touch area is 48dp. The same layout is used in projects and tasks.
- The printer camera stays on the right of its card header.

The logo is not recolored. With large fonts, the brand and the right block may
wrap to the next line. Long connection/sorting captions
wrap within the available width without taking up the area of the neighboring button.
The touch areas of the bell and refresh remain 48dp, despite the absence of
a large visible background. No new server requests or actions have been added.

The core, modules, inventory, print repeat, accounting and command restrictions have not changed.
Automated results: VALIDATION_MOBILE_0.15.6.md.
The look of the new layout still needs to be checked on the phone: normal and
large font, light/dark theme, QR, the bell, refresh and sorting.
The FM server and real printers were not used during development.
