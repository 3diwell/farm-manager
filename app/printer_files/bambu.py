# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Файловый менеджер принтеров (Alpha 2.823) — адаптер Bambu Lab.

Доказанная база (🔒 рабочий путь печати + g_files): implicit FTPS :990, логин
bblp/access-code, nlst по каталогам "/", "/cache", "/model", "/timelapse".
Единственный носитель — корень FTP: у X1/P1 это SD-карта (file:///mnt/sdcard/),
у H2-серии — встроенная память (схема ftp:///). USB как отдельный накопитель этим
протоколом НЕ подтверждён — и потому НЕ заявляется.

Листинг с метаданными: команда LIST (обязательная в FTP) парсится best-effort;
неразобранное честно отдаёт size/mtime = None (UI покажет «Дата неизвестна»),
fallback — доказанный nlst. Удаление: стандартная команда DELE того же доказанного
FTPS-канала; выполняется ТОЛЬКО за предохранителем и ТОЛЬКО когда принтер не
печатает (безопасность файловых операций во время печати прошивкой не доказана ->
fail-safe запрет, см. base.delete_safe_during_print=False).

Транспорт ВНЕДРЯЕТСЯ: ftp_factory(printer_id) -> подключённый ftp-объект
(nlst/retrlines/delete/quit). Сам модуль в сеть не ходит; наружу — только
безопасные reason-коды.
"""
import io
import re
import time
import calendar
import zipfile

from app.printer_files import models as M
from app.printer_files import security as S
from app.printer_files.base import PrinterFileProvider, PrinterFileError

# Доказанные каталоги корня (g_files). Навигация разрешена по каталогам,
# ПОКАЗАННЫМ самим устройством в листинге, глубина ограничена нормализацией.
KNOWN_ROOT_DIRS = ("cache", "model", "timelapse")

_MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_abbr) if m}
# unix-стиль LIST: "-rw-r--r--   1 user group  12345 Jan 01 12:34 name.ext"
_LIST_RE = re.compile(
    r"^([\-dl])[rwxsStT\-]{9}\s+\d+\s+\S+\s+\S+\s+(\d+)\s+"
    r"([A-Za-z]{3})\s+(\d{1,2})\s+((\d{4})|(\d{1,2}:\d{2}))\s+(.+)$")


def parse_list_line(line, now_ts=None):
    """Одна строка LIST -> {name, is_dir, size|None, mtime|None} | None (не разобрана).
    Только чтение текста; ничего не выдумывается — сомнение = None."""
    m = _LIST_RE.match(str(line or "").rstrip())
    if not m:
        return None
    kind, size_s, mon_s, day_s, _, year_s, hm_s, name = m.groups()
    name = name.strip()
    if not name or name in (".", ".."):
        return None
    is_dir = (kind == "d")
    try:
        size = None if is_dir else int(size_s)
    except Exception:
        size = None
    mtime = None
    try:
        mon = _MONTHS.get(mon_s.lower())
        day = int(day_s)
        now = time.time() if now_ts is None else now_ts
        now_tm = time.gmtime(now)
        if mon:
            if year_s:
                tm = (int(year_s), mon, day, 0, 0, 0, 0, 0, 0)
                mtime = int(calendar.timegm(tm))
            elif hm_s:
                hh, mm = hm_s.split(":")
                year = now_tm.tm_year
                tm = (year, mon, day, int(hh), int(mm), 0, 0, 0, 0)
                cand = int(calendar.timegm(tm))
                if cand > now + 2 * 86400:      # «будущее» = прошлый год (правило FTP)
                    cand = int(calendar.timegm((year - 1, mon, day, int(hh), int(mm), 0, 0, 0, 0)))
                mtime = cand
    except Exception:
        mtime = None
    return {"name": name, "is_dir": is_dir, "size": size, "mtime": mtime}


def _model_storage(printer):
    """Единственный носитель по модели: H2-серия — встроенная память (emmc),
    остальные (X1/P1 и по умолчанию) — SD-карта. USB не заявляется."""
    model = str((printer or {}).get("model") or "").lower()
    if "h2" in model:
        return ("emmc", "Встроенная память", M.STORAGE_INTERNAL)
    return ("sd", "SD-карта", M.STORAGE_SD)


def extract_preview_png(data):
    """PNG-картинка плиты из содержимого .3mf. Чистая функция: ни сети, ни файлов.

    Нет картинки внутри, файл не ZIP или картинка пустая — честное no_preview, а не
    выдуманная заглушка: пустой предпросмотр хуже отсутствия, он выглядит как поломка."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except Exception:
        raise PrinterFileError(M.REASON_NO_PREVIEW)
    try:
        names = z.namelist()
        for rx in BambuFileProvider._PREVIEW_RE:
            for nm in names:
                if rx.match(str(nm).replace("\\", "/")):
                    try:
                        png = z.read(nm)
                    except Exception:
                        continue
                    if png[:8] == b"\x89PNG\r\n\x1a\n" and len(png) > 64:
                        return png
        raise PrinterFileError(M.REASON_NO_PREVIEW)
    finally:
        try:
            z.close()
        except Exception:
            pass


class BambuFileProvider(PrinterFileProvider):
    adapter = "bambu"
    delete_safe_during_print = False       # прошивкой не доказано -> во время печати запрет
    # Alpha 2.825: печать существующего файла доказана C1-flow карточки (start_print
    # 2.728 -> _bambu_start_print по MQTT); фильтр расширений тот же, что у доказанной
    # выпадашки g_files (endswith .gcode/.3mf).
    printable_extensions = (".gcode", ".3mf")
    # хинт категоризации строится как "<storage_id>/<rel_path>" (см. server.py)
    timelapse_dirs = ("sd/timelapse", "emmc/timelapse")

    def __init__(self, ftp_factory):
        self._ftp_factory = ftp_factory

    def probe_capabilities(self, printer):
        if not (printer or {}).get("has_credentials"):
            return M.PrinterFileCapabilities(
                supported=False, reason=M.REASON_NO_CREDENTIALS, adapter=self.adapter)
        _, _, stype = _model_storage(printer)
        return M.PrinterFileCapabilities(
            supported=True, list_files=True, browse_directories=True, delete_files=True,
            print_existing_files=True,     # доказанный C1-flow: _bambu_start_print (MQTT)
            read_sizes=True, read_mtime=True, read_storage_usage=False, read_previews=True,
            storage_types=(stype,), adapter=self.adapter)

    def list_storages(self, printer):
        if not (printer or {}).get("has_credentials"):
            raise PrinterFileError(M.REASON_NO_CREDENTIALS)
        sid, label, stype = _model_storage(printer)
        return [M.PrinterStorage(storage_id=sid, display_name=label, type=stype,
                                 writable=True, total_bytes=None, free_bytes=None, online=True)]

    def storage_writable(self, printer, storage_id):
        sid, _, _ = _model_storage(printer)
        return str(storage_id) == sid

    def _session(self, printer):
        try:
            return self._ftp_factory(str((printer or {}).get("id") or ""))
        except PrinterFileError:
            raise
        except (TimeoutError,):
            raise PrinterFileError(M.REASON_TIMEOUT)
        except Exception:
            raise PrinterFileError(M.REASON_CONNECTION_LOST)

    def list_directory(self, printer, storage_id, rel_path):
        sid, _, _ = _model_storage(printer)
        if str(storage_id) != sid:
            raise PrinterFileError(M.REASON_BAD_REQUEST)
        path = "/" + (rel_path or "")
        ftp = self._session(printer)
        try:
            lines = []
            parsed_ok = True
            try:
                ftp.retrlines("LIST " + path, lines.append)
            except Exception:
                parsed_ok = False
            out = []
            if parsed_ok and lines:
                for ln in lines:
                    row = parse_list_line(ln)
                    if row is not None:
                        out.append(row)
            if not out:
                # fallback на ДОКАЗАННЫЙ nlst: имена без метаданных (честные None)
                try:
                    names = ftp.nlst(path)
                except Exception:
                    raise PrinterFileError(M.REASON_CONNECTION_LOST)
                for e in names:
                    nm = str(e or "").replace("\\", "/").split("/")[-1].strip()
                    if not nm or nm in (".", ".."):
                        continue
                    # nlst не различает каталоги; известные корневые папки помечаем сами
                    is_dir = (not rel_path) and (nm.lower() in KNOWN_ROOT_DIRS)
                    out.append({"name": nm, "is_dir": is_dir, "size": None, "mtime": None})
            return out
        finally:
            try:
                ftp.quit()
            except Exception:
                pass

    # ── Alpha 2.989: предпросмотр ────────────────────────────────────────────────
    #  Bambu не отдаёт картинку отдельным запросом: она лежит ВНУТРИ файла. Слайсер
    #  кладёт в .3mf (это ZIP) картинки плит — Metadata/plate_1.png, рядом уменьшенная
    #  plate_1_small.png и вид сверху top_1.png. Проверено на файлах владельца и описано
    #  в разборах формата (3mf = zip, папка Metadata).
    #
    #  Цена операции честная: чтобы показать картинку, файл надо СКАЧАТЬ целиком — у
    #  протокола нет частичного чтения. Поэтому есть предел: слишком большой файл честно
    #  отвечает too_large, а не тянет десятки мегабайт молча. Скачивание идёт в буфер с
    #  жёстким потолком, а не «сколько пришлёт принтер».
    PREVIEW_MAX_BYTES = 64 * 1024 * 1024      # потолок скачивания ради картинки
    #  Порядок предпочтения: сначала маленькая (её и показываем), потом обычная, потом вид
    #  сверху. Имя плиты не угадываем — берём первую подходящую по шаблону.
    _PREVIEW_RE = (re.compile(r"^Metadata/plate_\d+_small\.png$", re.I),
                   re.compile(r"^Metadata/plate_\d+\.png$", re.I),
                   re.compile(r"^Metadata/top_\d+\.png$", re.I),
                   re.compile(r"^Metadata/plate_no_light_\d+\.png$", re.I))

    def get_preview(self, printer, storage_id, rel_path):
        """-> (bytes PNG, "image/png"). Ошибки — только безопасными кодами."""
        sid, _, _ = _model_storage(printer)
        if str(storage_id) != sid:
            raise PrinterFileError(M.REASON_BAD_REQUEST)
        norm = S.normalize_rel_path(rel_path)
        if not norm:
            raise PrinterFileError(M.REASON_BAD_REQUEST)
        if not norm.lower().endswith(".3mf"):
            #  У голого .gcode на Bambu картинки внутри нет — честное «нет предпросмотра».
            raise PrinterFileError(M.REASON_NO_PREVIEW)
        ftp = self._session(printer)
        try:
            buf = io.BytesIO()
            over = [False]

            def _sink(chunk):
                if over[0]:
                    return
                if buf.tell() + len(chunk) > self.PREVIEW_MAX_BYTES:
                    over[0] = True
                    return
                buf.write(chunk)

            try:
                ftp.retrbinary("RETR /" + norm, _sink)
            except PrinterFileError:
                raise
            except (TimeoutError,):
                raise PrinterFileError(M.REASON_TIMEOUT)
            except Exception:
                raise PrinterFileError(M.REASON_NOT_FOUND)
            if over[0]:
                raise PrinterFileError(M.REASON_TOO_LARGE)
            data = buf.getvalue()
            if not data:
                raise PrinterFileError(M.REASON_NOT_FOUND)
            return (extract_preview_png(data), "image/png")
        finally:
            try:
                ftp.quit()
            except Exception:
                pass

    def delete_file(self, printer, storage_id, rel_path):
        sid, _, _ = _model_storage(printer)
        if str(storage_id) != sid:
            raise PrinterFileError(M.REASON_BAD_REQUEST)
        norm = S.normalize_rel_path(rel_path)
        if not norm:
            raise PrinterFileError(M.REASON_BAD_REQUEST)
        ftp = self._session(printer)
        try:
            try:
                ftp.delete("/" + norm)      # стандартная команда DELE доказанного канала
            except PrinterFileError:
                raise
            except (TimeoutError,):
                raise PrinterFileError(M.REASON_TIMEOUT)
            except Exception:
                # ftplib поднимает error_perm с текстом «550 ...» — наружу только код
                raise PrinterFileError(M.REASON_DELETE_UNCONFIRMED)
            return True
        finally:
            try:
                ftp.quit()
            except Exception:
                pass
