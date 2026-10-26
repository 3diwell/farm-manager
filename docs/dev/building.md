**Русский** · [English](building.en.md)

# Сборка

Состояние на 16.10.2026. Программа — сервер на Python (FastAPI + uvicorn) и интерфейс на Vue без
сборщика: файлы `web/` отдаются как есть.

## Из исходников

Нужен **Python 3.14** (часть проверок не работает на 3.13).

```bash
py -3.14 -m pip install -r requirements.txt
py -3.14 server.py
```

Версии в `requirements.txt` закреплены точно (`имя==версия`) — см. «Закреплённые версии» ниже.

Интерфейс — http://127.0.0.1:8000. Данные — `%LOCALAPPDATA%\3DIWELL`. Для камер Bambu Lab нужен
`ffmpeg.exe` рядом с `server.py` (в репозитории его нет — см. ниже).

## Серверный EXE

```bash
build.bat
```

`build.bat` ставит зависимости и PyInstaller закреплённых версий (`requirements-build.txt`) и
собирает EXE по `3diwell.spec`. Внимание: он удаляет папки `build\` и `dist\` перед сборкой.

Номер версии в свойствах EXE (Свойства → Подробно) `3diwell.spec` берёт при сборке из
`APP_VERSION` в `server.py` через `tools/build_version_info.py` (с 16.10.2026, R-149): «Alpha 3.0»
→ 3.0.0.0, «Beta 3.71» → 3.71.0.0. Отдельного файла с номером у сервера нет — мест версии не прибавилось. У окна и клиента
номер по-прежнему в `desktop_shell_version_*.txt`, у установщиков — `VersionInfoVersion={#AppVersion}`.

Необязательные входы сборки — их нет в открытом репозитории, и сборка без них проходит:

| Файл | Без него | Где взять |
|---|---|---|
| `ffmpeg.exe` | не работает трансляция камер Bambu Lab | сборка FFmpeg с подходящей лицензией; её лицензию и ссылку на исходники приложить к своей сборке (официальная сборка — `packaging/installer/licenses/FFMPEG_NOTICE.txt`, проверка — `tools/test_license_files.py`) |
| `printer_covers/` | карточки принтеров показывают значки-заглушки | свои изображения с правом на распространение (официальные — из OrcaSlicer, AGPL-3.0: `packaging/installer/licenses/PRINTER_IMAGES_NOTICE.txt`) |

## Окно программы и клиент

`desktop_shell.spec` собирает оболочки окна (pywebview + WebView2). Нужны pywebview 6.2,
pythonnet 3.1, clr_loader, bottle, proxy_tools — их нет в `requirements.txt` (сервер без них
работает); они живут в отдельном окружении `buildenv` и закреплены в
`requirements-desktop-shell.txt` (см. «Закреплённые версии»).
`tools/build_desktop_shell.ps1` собирает обе оболочки.

## Установщики

Inno Setup 6: `3diwell-setup.iss` (программа) и `3diwell-client-setup.iss` (клиент).
Предварительные условия (.NET Framework 4.8, WebView2 Runtime) — `tools/installer/prereqs.iss`;
их установщики берутся из папки `/DVendorDir=...` и в репозиторий не кладутся.

Проверка установщика на чистой Windows без сети (R-109, 16.10.2026; инструмент разработки, в
выпуск не входит): `tools/installer/sandbox/fm-install-test.wsb` открывает Windows Sandbox без
сети, папка выпуска подключается только для чтения, `run_install_test.ps1` ставит программу тихо
и пишет `result.json` в `C:\3DIWELL_Builds\sandbox_out` — суммы, что стояло до установки (WebView2,
.NET) и что поставил установщик, файлы, правила брандмауэра, порт, ответ сервера и окно. Как
запустить — в шапке скрипта. Вне песочницы скрипт отказывается работать. Компонент «Песочница
Windows» включает владелец; пока набор ни разу не запускался.

## Официальный выпуск

`tools/build_release.py` — вся цепочка официального выпуска: три EXE, проверки содержимого,
сверка текстов лицензий, оба установщика, папка выпуска с модулями. Рассчитан на сборочный
корень вне репозитория (по умолчанию `C:\3DIWELL_Builds`) и отдельное окружение оболочек; из
чистой копии без них не пройдёт. В папку выпуска кладётся `BUILD_ENVIRONMENT.txt` — версии Python
и пакетов обоих окружений, Inno Setup, суммы SHA-256 компонентов Windows и `ffmpeg.exe` (без путей
компьютера); его сумма входит в `SHA256SUMS.txt`.

До PyInstaller (шаг 2, и с `--skip-exe` тоже) сборщик сверяет пакеты обоих Python с закреплёнными
версиями и при расхождении останавливается, напечатав точную команду `pip install -r …`. Только
эта сверка, без сборки: `python tools/build_release.py --env-only`. После сборки он же проверяет
номер в свойствах всех трёх EXE и обоих установщиков.

Пути задаются переменными окружения (без них — значения по умолчанию):

| Переменная | Что | По умолчанию |
|---|---|---|
| `FM_BUILD_ROOT` | сборочный корень: staging, рабочие папки, папка выпуска | `C:\3DIWELL_Builds` |
| `FM_VENDOR_DIR` | установщики компонентов Windows | `<FM_BUILD_ROOT>\vendor` |
| `FM_SHELL_PYTHON` | Python окружения оболочек | `<FM_BUILD_ROOT>\buildenv\Scripts\python.exe` |

### Тексты лицензий сторонних пакетов

`packaging/installer/licenses/THIRD_PARTY_LICENSES.txt` — тексты лицензий всех пакетов Python,
вшитых в три EXE. Установщик программы ставит его в папку `licenses` рядом с программой (как и
остальные `*.txt` этой папки). Файл отслеживается в git и собирается
`tools/collect_third_party_licenses.py` по составу **самих EXE**: внутри каждого читается список
модулей, модули сопоставляются с пакетами окружения, которым EXE собран. Поэтому каждую часть
запускают своим интерпретатором:

```bash
python tools/collect_third_party_licenses.py --from-exe "<dist>\3DIWELL Farm Manager.exe" --part-out server.json
"<buildenv>\Scripts\python.exe" tools/collect_third_party_licenses.py ^
    --from-exe "<dist>\3DIWELL Farm Manager Desktop.exe" "<dist>\3DIWELL Farm Manager Client.exe" --part-out shell.json
python tools/collect_third_party_licenses.py --assemble server.json shell.json ^
    --out packaging/installer/licenses/THIRD_PARTY_LICENSES.txt
```

`build_release.py` делает то же самое после проверки содержимого EXE, но с `--check`: если файл
не совпадает со сборкой (обновили пакет), выпуск останавливается и печатает точную команду
обновления. Сама сборка в репозиторий ничего не пишет.

Свои имена проекта сборщик отличает от пакетов так: модули `*.py` корня, папки-пакеты Python и
папки данных. Папка данных, чьё имя совпадает с установленным пакетом, своей не считается — иначе
пакет `packaging` (он вшит во все EXE) терялся из-за папки `packaging/` проекта.

### Описание выпуска на сайте (latest.json)

Программа раз в несколько часов читает `https://3diwell.com/farm/latest.json` (выключается в
Настройках → Общие → Программа). Пока в `app/licensing/trust.py` список `RELEASE_KEYS` пуст,
годится прежний простой файл `{"version", "url", "notes"}`.

Переход на подписанный файл: создать ключ выпуска (`tools/fm_license_tool.py keygen --purpose
package`, закрытая часть — вне проекта), вписать ОТКРЫТУЮ часть в `RELEASE_KEYS`, собрать выпуск,
подписать его описание `tools/fm_license_tool.py sign-release ...` и положить результат по тому же
адресу. Подписанный файл несёт сверху копию `version`, `url`, `notes` — её читают выпуски, которые
уже у пользователей (Alpha 3.0 и раньше), поэтому они продолжают видеть новую версию. Новые выпуски
проверяют подпись и отклоняют файл, где верхние поля расходятся с подписанными; править их руками
нельзя. Ссылка в файле — только `https://3diwell.com/...` или `https://www.3diwell.com/...`
(`ALLOWED_HOSTS` в `app/update_manifest.py`); переадресация сайта на другой хост тоже не проходит.

## Закреплённые версии (с 16.10.2026, R-149)

Три файла задают ровно состав выпуска Alpha 3.0 (его `BUILD_ENVIRONMENT.txt`), со всеми
зависимостями зависимостей, без хешей:

| Файл | Что | Куда ставить |
|---|---|---|
| `requirements.txt` | пакеты программы (сервер), 28 штук | системный Python 3.14 |
| `requirements-build.txt` | `-r requirements.txt` + PyInstaller и его зависимости | тот же Python, им собирается сервер-EXE |
| `requirements-desktop-shell.txt` | окно и клиент, 16 пакетов (свои версии cryptography, cffi, PyInstaller) | `buildenv` |

`tools/build_release.py` сверяет оба окружения с этими файлами до сборки и останавливается при
расхождении. Лишние пакеты (например numpy в системном Python — сборка его исключает) не мешают.
Сменить версию — осознанно: поправить строку, поставить, собрать и обновить
`packaging/installer/licenses/THIRD_PARTY_LICENSES.txt` (сборка подскажет команду);
`tools/test_dependency_pins.py` следит, чтобы каждый пакет из этого файла был закреплён той же
версией.

## Проверенное окружение (снимок 29.09.2026)

Точный состав конкретного выпуска — в его `BUILD_ENVIRONMENT.txt`; для Alpha 3.0 он совпадает с
закреплёнными версиями выше.

**Сервер** — системный Python **3.14.7**, PyInstaller 6.22.2. Пакеты внутри EXE: annotated-doc
0.0.5, annotated-types 0.8.0, anyio 4.14.2, cffi 2.1.1, click 8.5.0, cryptography 50.0.1,
et_xmlfile 2.0.0, fastapi 0.141.1, h11 0.16.0, httptools 0.8.0, idna 3.19, openpyxl 3.1.5,
packaging 26.3, paho-mqtt 2.1.0, pillow 12.3.0, pydantic 2.13.5, pydantic_core 2.46.5, pystray 0.19.5,
python-dotenv 1.2.3, python-multipart 0.0.32, PyYAML 6.0.3, setuptools 84.0.0, six 1.17.0,
starlette 1.6.0, typing_extensions 4.16.0, typing-inspection 0.4.4, uvicorn 0.52.4, watchfiles
1.2.0, websockets 17.1.

**Окно и клиент** — отдельное окружение `buildenv` (venv), Python **3.14.7**: pywebview 6.2.1,
pythonnet 3.1.0, clr_loader 0.3.1, bottle 0.13.4, proxy_tools 0.1.0, cryptography 49.0.0,
cffi 2.1.0, pycparser 3.0, typing_extensions 4.16.0, pyinstaller 6.21.0 (с altgraph 0.17.5,
pefile 2024.8.26, pywin32-ctypes 0.2.3, pyinstaller-hooks-contrib 2026.6), packaging 26.2,
setuptools 83.0.0.

Как пересоздать `buildenv` (он не переносится между компьютерами: в `pyvenv.cfg` остаются пути):

```bash
py -3.14 -m venv C:\3DIWELL_Builds\buildenv
C:\3DIWELL_Builds\buildenv\Scripts\python.exe -m pip install -r requirements-desktop-shell.txt
```

**Inno Setup 6.7.3** — ищется в `%LOCALAPPDATA%\Programs\Inno Setup 6`, затем в Program Files.

**Компоненты Windows** (`<FM_VENDOR_DIR>`): `MicrosoftEdgeWebView2RuntimeInstallerX64.exe` и
`ndp48-x86-x64-allos-enu.exe` — где взять и как проверить подпись Microsoft, написано в шапке
`tools/installer/prereqs.iss`.

## Что ещё не закрыто

Сделано: сборочный корень и Python оболочек задаются переменными; окружение оболочек описано
выше; выпуск описывает своё окружение (`BUILD_ENVIRONMENT.txt`); тексты лицензий сторонних
пакетов ставятся с программой и сверяются со сборкой; версии всех пакетов закреплены точно
(R-149); у сервер-EXE и установщиков есть номер версии в свойствах файла.

Ждёт решения владельца: хеши пакетов — позже, для открытой сборки (режим хешей pip требует хеш
каждого пакета под каждую платформу); тексты лицензий и `THIRD_PARTY_NOTICES` в установщике клиента
(`3diwell-client-setup.iss`: сейчас кладёт только `LICENSE`); условие LGPL для pystray внутри
однофайлового EXE; исходный код FFmpeg для выпусков.
