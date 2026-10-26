[Русский](THIRD_PARTY_NOTICES.md) · **English**

THIRD_PARTY_NOTICES — third-party components of 3DIWELL Farm Manager
=====================================================================

First-party FM code is distributed under the Mozilla Public License 2.0 (the LICENSE file). The
components below belong to their authors and are distributed under their own licenses. Versions are
as of the preparation of this file (26.09.2026); the exact contents of a specific build and the full
license texts of the Python packages inside the program are in the file
licenses\THIRD_PARTY_LICENSES.txt in the program folder.


1. Inside the source tree
-------------------------

- Vue 3.5.35 — web/vendor/vue.esm-browser.js
  MIT License, (c) 2018-present Yuxi (Evan) You and Vue contributors.
- Tailwind CSS 3.4.19 (includes modern-normalize) — web/vendor/tailwind.css
  MIT License, (c) Tailwind Labs, Inc.; modern-normalize (c) Sindre Sorhus.
- Feather icons (some of the icons in web/design/icons.js)
  MIT License, (c) 2013-2017 Cole Bemis. Lucide icons (if added) — ISC License,
  (c) Lucide Contributors.
- pdf-lib 1.17.1 — modules/inventory/web/desktop-0.5.2/vendor/pdf-lib.esm.min.js
  MIT License, (c) 2019 Andrew Dillon. Includes: tslib (Apache License 2.0, (c) Microsoft
  Corporation), pako (MIT, (c) 2014-2017 Vitaly Puzrin and Andrei Tuputcyn).
  License text: modules/inventory/web/desktop-0.5.2/vendor/PDF-LIB-LICENSE.md.
- @pdf-lib/fontkit 1.1.1 — modules/inventory/web/desktop-0.5.2/vendor/fontkit.umd.min.js
  MIT License, (c) Andrew Dillon; based on fontkit (c) Devon Govett.
- qrcode-generator 2.0.4 — modules/inventory/web/desktop-0.5.2/vendor/qrcode.js
  MIT License, (c) 2009 Kazuhiko Arase.
- DejaVu Sans 2.37 — modules/inventory/web/desktop-0.5.2/vendor/DejaVuSans.ttf
  Bitstream Vera Fonts License + Arev Fonts License; DejaVu changes are in the public domain.
  Text: modules/inventory/web/desktop-0.5.2/vendor/DEJAVU-LICENSE.txt.
- 3DIWELL Wide J font — web/design/fonts/3diwell-wide-j*.woff2
  A modified version of Jura: (c) 2019 The Jura Project Authors (https://github.com/ossobuffo/jura).
  SIL Open Font License 1.1, text: web/design/fonts/OFL-Jura.txt.
- 3DIWELL Wide P font — web/design/fonts/3diwell-wide-p-*.woff2
  A modified version of Play: (c) 2011 Jonas Hecksher, Playtypes, e-types AS, with Reserved Font
  Name 'Play', 'Playtype', 'Playtype Sans'. SIL Open Font License 1.1, text:
  web/design/fonts/OFL-Play.txt.
  Both fonts are adjusted to the interface metrics, the letter spacing is changed, the weight axis
  of Jura is extended, the hinting is redone with ttfautohint, and the names are
  changed as the OFL requires — details in web/design/fonts/README.md. In the installed
  program the font license texts are licenses\OFL-Jura.txt and licenses\OFL-Play.txt.
- Information about the Bambu Lab printer protocol (state and error codes, compatibility tables in
  app/printer_health_policy.py, app/bambu_start_policy.py and server.py) was compiled from the public
  descriptions of the ha-bambulab / pybambu projects (MIT License, (c) Greg Hesp and contributors) and
  OpenBambuAPI. No code from these projects was copied.


2. Bundled into the executables
-------------------------------

These files are not in the repository: the build (PyInstaller) adds them.

- Python 3.14 — Python Software Foundation License 2.0.
- FastAPI 0.141 — MIT. Starlette 1.6 — BSD-3-Clause. uvicorn 0.52 — BSD-3-Clause.
- websockets 17.1 — BSD-3-Clause. httptools 0.8 — MIT. watchfiles 1.2 — MIT.
  python-dotenv 1.2 — BSD-3-Clause. PyYAML 6.0 — MIT.
- pydantic 2.13, pydantic-core 2.46, annotated-types 0.8, typing-inspection 0.4 — MIT.
- anyio 4.14 — MIT. h11 0.16 — MIT. idna 3.19 — BSD-3-Clause. click 8.5 — BSD-3-Clause.
- typing-extensions 4.16 — PSF License 2.0.
- python-multipart 0.0.32 — Apache License 2.0.
- paho-mqtt 2.1 — Eclipse Public License 2.0 or Eclipse Distribution License 1.0 (BSD-3-Clause),
  at the recipient's choice.
- openpyxl 3.1 — MIT. et-xmlfile 2.0 — MIT.
- Pillow 12.3 — MIT-CMU (HPND).
- pystray 0.19 — GNU Lesser General Public License v3.0. Source code:
  https://github.com/moses-palmer/pystray.
- six 1.17 — MIT.
- cryptography 50 — Apache License 2.0 or BSD-3-Clause. cffi 2.1 — MIT-0.
  pycparser 3.0 — BSD-3-Clause.
- pywebview 6.2 — BSD-3-Clause; contains Microsoft.Web.WebView2.*.dll (Microsoft
  WebView2 SDK terms).
- pythonnet 3.1, clr_loader 0.3 — MIT (.NET Foundation and contributors). bottle 0.13 — MIT.
  proxy_tools 0.1 — MIT.
- PyInstaller bootloader 6.2x — GPL-2.0-or-later with an exception that allows distributing
  the built programs under any terms.


3. Inside the installer
-----------------------

- Microsoft Edge WebView2 Runtime and .NET Framework 4.8 — distributed under Microsoft's
  terms for redistributable components. The installer installs them only if they are missing.
- The installer is built with Inno Setup 6 — Inno Setup License, (c) Jordan Russell and Martijn Laan.


4. Not included in this repository
----------------------------------

Official builds may additionally contain materials that are not in the open repository.
Their license texts and notes are in the licenses folder next to the program:

- FFmpeg 8.1.1, the "essentials" build from gyan.dev (the ffmpeg.exe program for Bambu Lab cameras,
  run as a separate program) — GNU General Public License v3.0. License text —
  licenses\GPL-3.0.txt; the version, build options, links to the source code and the offer to provide
  the source code on request — licenses\FFMPEG_NOTICE.txt.
- Printer images (207 printer_covers files) — from the printer profiles of the OrcaSlicer slicer
  (https://github.com/OrcaSlicer/OrcaSlicer), unmodified — GNU Affero General Public License
  v3.0. License text — licenses\AGPL-3.0.txt, origin and authors —
  licenses\PRINTER_IMAGES_NOTICE.txt. Manufacturer names and logos on the images are their
  trademarks.

A build from the open repository does not contain these materials and works without them.

5. Icon license texts
---------------------

Some of the icons in web/design/icons.js are drawn after Feather; new ones are taken from lucide.dev.

Feather — The MIT License (MIT)

Copyright (c) 2013-2017 Cole Bemis

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

Lucide — ISC License

Copyright (c) for portions of Lucide are held by Cole Bemis 2013-2022 as part
of Feather (MIT). All other copyright (c) for Lucide are held by Lucide
Contributors 2022.

Permission to use, copy, modify, and/or distribute this software for any
purpose with or without fee is hereby granted, provided that the above
copyright notice and this permission notice appear in all copies.

THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.
