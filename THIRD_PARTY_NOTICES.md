THIRD_PARTY_NOTICES — сторонние компоненты 3DIWELL Farm Manager
==================================================================

Собственный код FM распространяется по Mozilla Public License 2.0 (файл LICENSE). Компоненты
ниже принадлежат их авторам и распространяются по своим лицензиям. Версии указаны на момент
подготовки этого файла (26.09.2026); точный состав конкретной сборки и полные тексты лицензий
пакетов Python внутри программы — в файле licenses\THIRD_PARTY_LICENSES.txt в папке программы.

Third-party components of 3DIWELL Farm Manager. First-party code is MPL-2.0 (LICENSE). The
components below belong to their authors and are licensed under their own terms. Full license
texts of the Python packages inside the program: licenses\THIRD_PARTY_LICENSES.txt.


1. Внутри исходников / Inside the source tree
---------------------------------------------

- Vue 3.5.35 — web/vendor/vue.esm-browser.js
  MIT License, (c) 2018-present Yuxi (Evan) You and Vue contributors.
- Tailwind CSS 3.4.19 (включает modern-normalize) — web/vendor/tailwind.css
  MIT License, (c) Tailwind Labs, Inc.; modern-normalize (c) Sindre Sorhus.
- Значки Feather / Feather icons (часть значков в web/design/icons.js)
  MIT License, (c) 2013-2017 Cole Bemis. Значки Lucide (если добавлены) — ISC License,
  (c) Lucide Contributors.
- pdf-lib 1.17.1 — modules/inventory/web/desktop-0.5.2/vendor/pdf-lib.esm.min.js
  MIT License, (c) 2019 Andrew Dillon. Внутри: tslib (Apache License 2.0, (c) Microsoft
  Corporation), pako (MIT, (c) 2014-2017 Vitaly Puzrin and Andrei Tuputcyn).
  Текст лицензии: modules/inventory/web/desktop-0.5.2/vendor/PDF-LIB-LICENSE.md.
- @pdf-lib/fontkit 1.1.1 — modules/inventory/web/desktop-0.5.2/vendor/fontkit.umd.min.js
  MIT License, (c) Andrew Dillon; основан на fontkit (c) Devon Govett.
- qrcode-generator 2.0.4 — modules/inventory/web/desktop-0.5.2/vendor/qrcode.js
  MIT License, (c) 2009 Kazuhiko Arase.
- DejaVu Sans 2.37 — modules/inventory/web/desktop-0.5.2/vendor/DejaVuSans.ttf
  Bitstream Vera Fonts License + Arev Fonts License; изменения DejaVu — общественное достояние.
  Текст: modules/inventory/web/desktop-0.5.2/vendor/DEJAVU-LICENSE.txt.
- Шрифт 3DIWELL Wide J — web/design/fonts/3diwell-wide-j*.woff2
  Изменённая версия Jura: (c) 2019 The Jura Project Authors (https://github.com/ossobuffo/jura).
  SIL Open Font License 1.1, текст: web/design/fonts/OFL-Jura.txt.
- Шрифт 3DIWELL Wide P — web/design/fonts/3diwell-wide-p-*.woff2
  Изменённая версия Play: (c) 2011 Jonas Hecksher, Playtypes, e-types AS, with Reserved Font
  Name 'Play', 'Playtype', 'Playtype Sans'. SIL Open Font License 1.1, текст:
  web/design/fonts/OFL-Play.txt.
  Оба шрифта подогнаны под метрики интерфейса, промежутки между буквами изменены, у Jura
  продлена насыщенность, подгонка под пиксели сделана заново программой ttfautohint, имена
  изменены по требованию OFL — подробно в web/design/fonts/README.md. В установленной
  программе тексты лицензий шрифтов — licenses\OFL-Jura.txt и licenses\OFL-Play.txt.
- Сведения о протоколе принтеров Bambu Lab (коды состояний и ошибок, таблицы совместимости в
  app/printer_health_policy.py, app/bambu_start_policy.py и server.py) сведены по открытым
  описаниям проектов ha-bambulab / pybambu (MIT License, (c) Greg Hesp и участники) и
  OpenBambuAPI. Код этих проектов не копировался.


2. Внутри собранной программы / Bundled into the executables
------------------------------------------------------------

В репозитории этих файлов нет: их добавляет сборка (PyInstaller).

- Python 3.14 — Python Software Foundation License 2.0.
- FastAPI 0.141 — MIT. Starlette 1.6 — BSD-3-Clause. uvicorn 0.52 — BSD-3-Clause.
- websockets 17.1 — BSD-3-Clause. httptools 0.8 — MIT. watchfiles 1.2 — MIT.
  python-dotenv 1.2 — BSD-3-Clause. PyYAML 6.0 — MIT.
- pydantic 2.13, pydantic-core 2.46, annotated-types 0.8, typing-inspection 0.4 — MIT.
- anyio 4.14 — MIT. h11 0.16 — MIT. idna 3.19 — BSD-3-Clause. click 8.5 — BSD-3-Clause.
- typing-extensions 4.16 — PSF License 2.0.
- python-multipart 0.0.32 — Apache License 2.0.
- paho-mqtt 2.1 — Eclipse Public License 2.0 или Eclipse Distribution License 1.0 (BSD-3-Clause),
  на выбор получателя.
- openpyxl 3.1 — MIT. et-xmlfile 2.0 — MIT.
- Pillow 12.3 — MIT-CMU (HPND).
- pystray 0.19 — GNU Lesser General Public License v3.0. Исходный код:
  https://github.com/moses-palmer/pystray.
- six 1.17 — MIT.
- cryptography 50 — Apache License 2.0 или BSD-3-Clause. cffi 2.1 — MIT-0.
  pycparser 3.0 — BSD-3-Clause.
- pywebview 6.2 — BSD-3-Clause; содержит Microsoft.Web.WebView2.*.dll (условия Microsoft
  WebView2 SDK).
- pythonnet 3.1, clr_loader 0.3 — MIT (.NET Foundation и участники). bottle 0.13 — MIT.
  proxy_tools 0.1 — MIT.
- Загрузчик PyInstaller 6.2x — GPL-2.0-or-later с исключением, разрешающим распространять
  собранные программы на любых условиях.


3. Внутри установщика / Inside the installer
--------------------------------------------

- Microsoft Edge WebView2 Runtime и .NET Framework 4.8 — распространяются на условиях
  Microsoft для распространяемых компонентов. Установщик ставит их, только если их нет.
- Установщик собран Inno Setup 6 — Inno Setup License, (c) Jordan Russell и Martijn Laan.


4. Не входят в этот репозиторий / Not included in this repository
------------------------------------------------------------------

Официальные сборки могут дополнительно содержать материалы, которых в открытом репозитории нет.
Тексты их лицензий и примечания — в папке licenses рядом с программой:

- FFmpeg 8.1.1, сборка «essentials» с сайта gyan.dev (программа ffmpeg.exe для камер Bambu Lab,
  запускается отдельной программой) — GNU General Public License v3.0. Текст лицензии —
  licenses\GPL-3.0.txt; версия, параметры сборки, ссылки на исходный код и предложение выдать
  исходный код по запросу — licenses\FFMPEG_NOTICE.txt.
- Изображения принтеров (207 файлов printer_covers) — из профилей принтеров слайсера OrcaSlicer
  (https://github.com/OrcaSlicer/OrcaSlicer), без изменений — GNU Affero General Public License
  v3.0. Текст лицензии — licenses\AGPL-3.0.txt, происхождение и авторы —
  licenses\PRINTER_IMAGES_NOTICE.txt. Названия и логотипы производителей на изображениях — их
  товарные знаки.

Сборка из открытого репозитория этих материалов не содержит и работает без них.

5. Тексты лицензий значков / Icon license texts
-----------------------------------------------

Часть значков web/design/icons.js нарисована по Feather, новые берутся с lucide.dev.

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
