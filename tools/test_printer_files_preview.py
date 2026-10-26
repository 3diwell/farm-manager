# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.989 — предпросмотр файлов принтера.

ЗАЧЕМ. Владелец попросил показывать картинку модели прямо в проводнике файлов принтера:
по имени файла не понять, что там лежит, а на ферме файлов много. Картинку кладёт в файл
сам слайсер, программа её только достаёт.

ОТКУДА КАРТИНКА (контракты, не догадки):
  · Bambu: .3mf — это ZIP, и внутри в папке Metadata лежат картинки плит: plate_1.png,
    рядом уменьшенная plate_1_small.png и вид сверху top_1.png. Проверяется разбором
    настоящего ZIP, собранного здесь же.
  · Klipper: официальный API Moonraker (документация file_manager) — GET
    /server/files/thumbnails?filename=<путь> отдаёт список картинок с полем thumbnail_path
    (путь ОТ КОРНЯ gcodes), сами байты берутся как обычный файл: GET
    /server/files/gcodes/<thumbnail_path>. Скачивать g-code целиком не нужно.

ЧТО ДОКАЗЫВАЕТСЯ ЗДЕСЬ:
  · картинка достаётся из настоящего .3mf, предпочтение — уменьшенной;
  · нет картинки, файл не ZIP, пришёл не PNG — честный отказ, а не пустая рамка;
  · Moonraker берётся по ОФИЦИАЛЬНЫМ адресам и выбирает самую крупную картинку;
  · умение объявляется честно: нет транспорта — read_previews=False;
  · путь от клиента не принимается ВООБЩЕ — только непрозрачная ссылка, выданная сервером;
  · маршрут объявлен в карте прав с правом чтения файлов принтера и только для чтения;
  · кнопка в интерфейсе появляется лишь там, где картинка может быть.

Безопасность прогона: server.py НЕ импортируется, сеть не используется, принтеров нет —
транспорты подставные, разбор ZIP идёт в памяти.

Запуск: python tools/test_printer_files_preview.py   (0 = все проверки пройдены)
"""
import io
import os
import re
import sys
import zipfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.printer_files import models as M                       # noqa: E402
from app.printer_files.base import PrinterFileError             # noqa: E402
from app.printer_files.bambu import BambuFileProvider, extract_preview_png   # noqa: E402
from app.printer_files.moonraker import MoonrakerFileProvider   # noqa: E402
from app import route_policy_registry as reg                    # noqa: E402

SENTINEL = "PRINTER_FILES_PREVIEW_SENTINEL_2_989"
fail = 0
total = 0

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 300


def check(name, cond, extra=""):
    global fail, total
    total += 1
    print(("PASS" if cond else "FAIL") + " — " + name
          + ((" :: " + str(extra)) if (not cond and extra != "") else ""))
    if not cond:
        fail += 1


def reason_of(fn, *a, **k):
    """Причина отказа операции или '' — если отказа не было."""
    try:
        fn(*a, **k)
        return ""
    except PrinterFileError as e:
        return str(getattr(e, "reason", "") or "")


def make_3mf(names):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Metadata/plate_1.gcode", "; g\nG28\n")
        for n in names:
            z.writestr(n, PNG + n.encode("utf-8"))
    return buf.getvalue()


print("=== Alpha 2.989: предпросмотр файлов принтера ===")

# ── 1. Bambu: картинка внутри .3mf ────────────────────────────────────────────────────────
print("\n--- 1. Bambu: картинка лежит внутри файла ---")
data = make_3mf(["Metadata/plate_1.png", "Metadata/plate_1_small.png", "Metadata/top_1.png"])
got = extract_preview_png(data)
check("1. картинка достаётся из настоящего .3mf", got[:8] == PNG[:8] and len(got) > 64)
check("2. предпочтение — уменьшенной картинке плиты (её и показываем в окне)",
      got.endswith(b"Metadata/plate_1_small.png"))

check("3. нет уменьшенной — берётся обычная картинка плиты",
      extract_preview_png(make_3mf(["Metadata/plate_1.png"])).endswith(b"Metadata/plate_1.png"))
check("4. нет картинок плит — берётся вид сверху",
      extract_preview_png(make_3mf(["Metadata/top_1.png"])).endswith(b"Metadata/top_1.png"))
check("5. в файле нет картинок — честный отказ, а не пустая рамка",
      reason_of(extract_preview_png, make_3mf([])) == M.REASON_NO_PREVIEW)
check("6. файл не ZIP — тоже честный отказ",
      reason_of(extract_preview_png, b"this is not a zip archive at all") == M.REASON_NO_PREVIEW)

_broken = io.BytesIO()
with zipfile.ZipFile(_broken, "w") as z:
    z.writestr("Metadata/plate_1.png", b"not a png")
check("7. внутри лежит не PNG — не показываем мусор",
      reason_of(extract_preview_png, _broken.getvalue()) == M.REASON_NO_PREVIEW)

BSRC = io.open(os.path.join(REPO, "app", "printer_files", "bambu.py"), encoding="utf-8").read()
check("8. у скачивания ради картинки есть ПОТОЛОК (файл не тянется без предела)",
      "PREVIEW_MAX_BYTES" in BSRC and "REASON_TOO_LARGE" in BSRC)
check("9. голый .gcode на Bambu честно отвечает «картинки нет» (внутри её быть не может)",
      "REASON_NO_PREVIEW" in BSRC and '.endswith(".3mf")' in BSRC)


class _FtpStub:
    """FTP ровно в том объёме, какой трогает предпросмотр."""

    def __init__(self, blob, fail_with=None):
        self._blob = blob
        self._fail = fail_with
        self.retr = []
        self.quit_calls = 0

    def retrbinary(self, cmd, cb):
        self.retr.append(cmd)
        if self._fail:
            raise self._fail
        for i in range(0, len(self._blob), 8192):
            cb(self._blob[i:i + 8192])

    def quit(self):
        self.quit_calls += 1


PR_B = {"id": "b1", "type": "bambu", "model": "Bambu Lab H2D", "has_credentials": True}
ftp = _FtpStub(data)
prov_b = BambuFileProvider(lambda pid: ftp)
_sid = prov_b.list_storages(PR_B)[0].storage_id
blob, mime = prov_b.get_preview(PR_B, _sid, "cache/model.gcode.3mf")
check("10. Bambu: картинка получена через доказанный канал FTP", blob.endswith(b"_small.png") and mime == "image/png")
check("11. запрошен ИМЕННО тот файл, что выбрали", ftp.retr == ["RETR /cache/model.gcode.3mf"], ftp.retr)
check("12. соединение закрывается всегда", ftp.quit_calls == 1)

big = _FtpStub(b"\x00" * (BambuFileProvider.PREVIEW_MAX_BYTES + 4096))
check("13. слишком большой файл — отказ too_large, а не молчаливая закачка",
      reason_of(BambuFileProvider(lambda pid: big).get_preview, PR_B, _sid, "cache/big.3mf")
      == M.REASON_TOO_LARGE)
check("14. подъём каталогом вверх невозможен (путь нормализуется)",
      reason_of(prov_b.get_preview, PR_B, _sid, "../../etc/passwd") in (M.REASON_BAD_REQUEST, M.REASON_NO_PREVIEW))
check("15. чужой накопитель — отказ", reason_of(prov_b.get_preview, PR_B, "нет-такого", "a.3mf") == M.REASON_BAD_REQUEST)
check("16. умение объявлено", prov_b.probe_capabilities(PR_B).read_previews is True)

# ── 2. Klipper: картинку отдаёт Moonraker ─────────────────────────────────────────────────
print("\n--- 2. Klipper: картинку отдаёт сам Moonraker ---")
PR_K = {"id": "k1", "type": "klipper"}
asked = []


def _get_json(pid, path):
    asked.append(path)
    return {"result": [
        {"width": 32, "height": 32, "size": 900, "thumbnail_path": ".thumbs/m-32x32.png"},
        {"width": 400, "height": 400, "size": 70000, "thumbnail_path": ".thumbs/m-400x400.png"},
    ]}


def _get_bytes(pid, path):
    asked.append(path)
    return PNG + path.encode("utf-8")


prov_k = MoonrakerFileProvider(_get_json, lambda *a: None, _get_bytes)
blob_k, mime_k = prov_k.get_preview(PR_K, "gcodes", "sub/model.gcode")
check("17. Klipper: картинка получена", blob_k[:8] == PNG[:8] and mime_k == "image/png")
check("18. спрошен ОФИЦИАЛЬНЫЙ адрес списка картинок",
      asked[0].startswith("/server/files/thumbnails?filename="), asked[:1])
check("19. байты взяты обычной загрузкой файла от корня gcodes",
      asked[1] == "/server/files/gcodes/.thumbs/m-400x400.png", asked[1:2])
check("20. выбрана САМАЯ КРУПНАЯ картинка (мелкая в окне — мыло)", b"400x400" in blob_k)
check("21. g-code целиком не качается (в запросах его нет)",
      not any(a.endswith("model.gcode") and "thumbnails" not in a for a in asked), asked)

check("22. нет картинок — честный отказ",
      reason_of(MoonrakerFileProvider(lambda *a: {"result": []}, lambda *a: None, _get_bytes).get_preview,
                PR_K, "gcodes", "a.gcode") == M.REASON_NO_PREVIEW)
check("23. пришёл не PNG — мусор не показываем",
      reason_of(MoonrakerFileProvider(_get_json, lambda *a: None, lambda *a: b"<html>error</html>").get_preview,
                PR_K, "gcodes", "a.gcode") == M.REASON_NO_PREVIEW)
check("24. накопитель без картинок (config/logs) — честный отказ",
      reason_of(prov_k.get_preview, PR_K, "config", "printer.cfg") == M.REASON_NO_PREVIEW)
check("25. нет транспорта байтов — умение НЕ заявляется и операция отказывает",
      MoonrakerFileProvider(_get_json, lambda *a: None).probe_capabilities(PR_K).read_previews is False
      and reason_of(MoonrakerFileProvider(_get_json, lambda *a: None).get_preview, PR_K, "gcodes", "a.gcode")
      == M.REASON_UNSUPPORTED)
check("26. умение объявлено, когда транспорт есть", prov_k.probe_capabilities(PR_K).read_previews is True)

# ── 3. Сервер: права, ссылка вместо пути, кэш ─────────────────────────────────────────────
print("\n--- 3. Сервер: права и безопасность ---")
pol = reg.core_http_policy("GET", "/api/printer-files/preview")
check("27. маршрут объявлен в карте прав ядра", pol is not None)
check("28. право — то же, что у чтения файлов принтера (наблюдателю содержимое ни к чему)",
      pol is not None and pol.enforced_access.value == "CAPABILITY"
      and pol.required_capability == "printer_files_read",
      (pol.enforced_access.value, pol.required_capability) if pol else None)
check("29. маршрут объявлен ТОЛЬКО ЧИТАЮЩИМ", pol is not None and pol.read_only is True)

SRV = io.open(os.path.join(REPO, "server.py"), encoding="utf-8").read()
_impl = SRV[SRV.index("def _pf_preview_impl("):SRV.index("@app.get(\"/api/printer-files/preview\")")]
check("30. КЛЮЧЕВОЕ: путь от клиента не принимается — только непрозрачная ссылка сервера",
      "_PF_REFS.resolve(" in _impl and "rel_path" not in _impl and "file_ref" in _impl)
check("31. каталог предпросмотра не имеет", "REASON_DIRECTORY" in _impl)
#  Окно поиска берём с запасом: у обработчика длинное пояснение, и короткий срез
#  находил бы не тело функции, а её описание.
_pv_route = SRV.split('@app.get("/api/printer-files/preview")')[1][:1600]
check("32. выключённое чтение файлов принтера закрывает и предпросмотр",
      "if not _pf_read_enabled():" in _pv_route)
check("33. картинка не оседает в чужих кэшах (no-store)",
      '"Cache-Control": "no-store"' in SRV.split('@app.get("/api/printer-files/preview")')[1][:1200])
check("34. у кэша картинок есть предел и по числу, и по объёму",
      "_PF_PREVIEW_MAX_ENTRIES" in SRV and "_PF_PREVIEW_MAX_TOTAL" in SRV)
check("35. транспорт байтов ограничивает размер ответа",
      "max_bytes=" in SRV and "REASON_TOO_LARGE" in SRV.split("def _pf_http_get_bytes(")[1][:1200])

# ── 4. Интерфейс ──────────────────────────────────────────────────────────────────────────
print("\n--- 4. Интерфейс ---")
HTML = io.open(os.path.join(REPO, "web", "index.html"), encoding="utf-8").read()
APPJS = io.open(os.path.join(REPO, "web", "app.js"), encoding="utf-8").read()
check("36. кнопка предпросмотра есть в строке файла", 'class="pfw-eye"' in HTML and "pfPreviewOpen(e)" in HTML)
check("37. кнопка появляется только там, где картинка может быть (файл + умеющий принтер)",
      "const pfCanPreview = (e) => !!(e && !e.is_directory && pfCaps.value && pfCaps.value.read_previews)" in APPJS)
check("38. окно показывает картинку, а при отказе — причину словами",
      'class="pfw-pv-img"' in HTML and "pfReasonText(pfPreview.reason)" in HTML)
check("39. ответ на устаревший запрос не показывается (быстро щёлкали по строкам)",
      "_pfPreviewSeq" in APPJS and "my !== _pfPreviewSeq" in APPJS)
check("40. ссылка на картинку освобождается при закрытии (браузер не копит их)",
      "URL.revokeObjectURL" in APPJS)
check("41. причины переведены на оба языка",
      "no_preview: ru ?" in APPJS and "too_large: ru ?" in APPJS)
CSS = io.open(os.path.join(REPO, "web", "app.css"), encoding="utf-8").read()
check("42. картинка вписывается в окно, а не растягивается",
      ".pfw-pv-img{" in CSS and "object-fit:contain" in CSS)

print()
print("=" * 78)
print("МЕТКА: %s" % SENTINEL)
print("ИТОГО: PASS=%d FAIL=%d" % (total - fail, fail))
sys.exit(1 if fail else 0)
