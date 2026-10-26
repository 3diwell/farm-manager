# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Файловый менеджер принтеров (Alpha 2.823) — адаптер Klipper/Moonraker.

Доказанная база: проект уже читает `GET /server/files/list?root=gcodes` (server.py
g_files) и грузит файлы Moonraker'у; удаление `DELETE /server/files/{root}/{path}`
и корни `GET /server/files/roots` — официальный документированный Moonraker API.

Транспорт ВНЕДРЯЕТСЯ: http_get_json(path)->dict и http_delete_json(path)->dict —
их даёт server.py (реальный urllib с таймаутом) или тест (фейк). Сам модуль в сеть
не ходит. Все ошибки наружу — ТОЛЬКО безопасные reason-коды.
"""
from urllib.parse import quote

from app.printer_files import models as M
from app.printer_files import security as S
from app.printer_files.base import PrinterFileProvider, PrinterFileError

# Корни, в которых удаление разрешено политикой (пользовательские данные).
_WRITABLE_ROOTS = frozenset(("gcodes", "timelapse"))
# Понятные подписи известных корней; неизвестный корень показывается своим именем.
_ROOT_LABELS = {
    "gcodes": ("Файлы G-code", M.STORAGE_INTERNAL),
    "timelapse": ("Таймлапсы", M.STORAGE_INTERNAL),
    "config": ("Конфигурация", M.STORAGE_INTERNAL),
    "logs": ("Журналы", M.STORAGE_INTERNAL),
    "config_examples": ("Примеры конфигурации", M.STORAGE_INTERNAL),
    "docs": ("Документация", M.STORAGE_INTERNAL),
}


class MoonrakerFileProvider(PrinterFileProvider):
    adapter = "klipper"
    # Удаление ДРУГОГО файла — операция файловой системы хоста Klipper (не printer-команда);
    # официальный API выполняет её и во время печати. Текущий файл всегда защищён отдельно.
    delete_safe_during_print = True
    timelapse_dirs = ("timelapse",)
    # Alpha 2.825: печать существующего файла доказана C1-flow карточки (start_print
    # 2.728 -> POST /printer/print/start?filename=); фильтр расширений тот же, что у
    # доказанной выпадашки g_files. Старый flow берёт filename ОТНОСИТЕЛЬНО root
    # gcodes -> печать только из накопителя gcodes (из timelapse/config старт невозможен).
    printable_extensions = (".gcode", ".3mf")
    printable_storages = ("gcodes",)

    def __init__(self, http_get_json, http_delete_json, http_get_bytes=None):
        # все транспорты принимают (printer_id, path): адрес принтера резолвит server.py
        self._get = http_get_json
        self._delete = http_delete_json
        #  2.989: сырые байты нужны только предпросмотру. Не внедрили — предпросмотр
        #  честно объявляется недоступным, остальное работает как раньше.
        self._get_bytes = http_get_bytes

    @staticmethod
    def _pid(printer):
        return str((printer or {}).get("id") or "")

    def probe_capabilities(self, printer):
        return M.PrinterFileCapabilities(
            supported=True, list_files=True, browse_directories=True, delete_files=True,
            print_existing_files=True,     # доказанный C1-flow: /printer/print/start
            read_sizes=True, read_mtime=True, read_storage_usage=True,
            read_previews=bool(self._get_bytes),
            storage_types=(M.STORAGE_INTERNAL,), adapter=self.adapter)

    # ── storages = корни Moonraker ────────────────────────────────────────────
    def list_storages(self, printer):
        pid = self._pid(printer)
        roots = []
        try:
            j = self._get(pid, "/server/files/roots")
            raw = (j or {}).get("result") or []
            for r in raw:
                nm = str((r or {}).get("name") or "").strip().lower()
                if S.storage_id_ok(nm):
                    roots.append(nm)
        except PrinterFileError:
            raise
        except Exception:
            # roots может отсутствовать у старого Moonraker — честный минимум: gcodes
            roots = []
        if not roots:
            roots = ["gcodes"]
        out = []
        for nm in roots:
            label, stype = _ROOT_LABELS.get(nm, (nm, M.STORAGE_INTERNAL))
            total, free = self._disk_usage(pid, nm)
            out.append(M.PrinterStorage(
                storage_id=nm, display_name=label, type=stype,
                writable=(nm in _WRITABLE_ROOTS), total_bytes=total, free_bytes=free,
                online=True))
        return out

    def storage_writable(self, printer, storage_id):
        return str(storage_id) in _WRITABLE_ROOTS

    def _disk_usage(self, pid, root):
        """Best-effort: официальный GET /server/files/directory отдаёт disk_usage.
        Любая неудача -> (None, None) — цифры не выдумываются."""
        try:
            j = self._get(pid, "/server/files/directory?path=" + quote(str(root)))
            du = ((j or {}).get("result") or {}).get("disk_usage") or {}
            t, f = du.get("total"), du.get("free")
            return (int(t) if isinstance(t, (int, float)) else None,
                    int(f) if isinstance(f, (int, float)) else None)
        except Exception:
            return (None, None)

    # ── листинг: доказанный flat-ответ list?root=; папки синтезируются из путей ──
    def list_directory(self, printer, storage_id, rel_path):
        if not S.storage_id_ok(storage_id):
            raise PrinterFileError(M.REASON_BAD_REQUEST)
        try:
            j = self._get(self._pid(printer), "/server/files/list?root=" + quote(str(storage_id)))
        except PrinterFileError:
            raise
        except Exception:
            raise PrinterFileError(M.REASON_CONNECTION_LOST)
        rows = (j or {}).get("result")
        if not isinstance(rows, list):
            raise PrinterFileError(M.REASON_MALFORMED)   # мусорный ответ ≠ пустой storage
        prefix = (rel_path + "/") if rel_path else ""
        files, dirs = [], {}
        for r in rows:
            p = str((r or {}).get("path") or "").replace("\\", "/").strip("/")
            if not p or S.normalize_rel_path(p) is None:
                continue                                  # подозрительный путь — пропуск
            if prefix and not p.startswith(prefix):
                continue
            rest = p[len(prefix):]
            if "/" in rest:
                d = rest.split("/", 1)[0]
                if d:
                    dirs[d] = True
                continue
            sz = (r or {}).get("size")
            mt = (r or {}).get("modified")
            files.append({
                "name": rest, "is_dir": False,
                "size": int(sz) if isinstance(sz, (int, float)) else None,
                "mtime": int(mt) if isinstance(mt, (int, float)) else None,
            })
        out = [{"name": d, "is_dir": True, "size": None, "mtime": None} for d in sorted(dirs)]
        return out + files

    # ── Alpha 2.989: предпросмотр ────────────────────────────────────────────────
    #  Официальный API Moonraker (документация file_manager): GET /server/files/thumbnails
    #  ?filename=<путь от корня gcodes> отдаёт список картинок, у каждой width/height/size
    #  и thumbnail_path — путь ОТ КОРНЯ gcodes. Сами байты берутся обычной загрузкой файла:
    #  GET /server/files/gcodes/<thumbnail_path>. Ничего скачивать целиком не нужно —
    #  картинку слайсер положил рядом заранее.
    PREVIEW_MAX_BYTES = 8 * 1024 * 1024        # картинка размером с файл — это уже не картинка

    def get_preview(self, printer, storage_id, rel_path):
        """-> (bytes PNG, "image/png"). Ошибки — только безопасными кодами."""
        if self._get_bytes is None:
            raise PrinterFileError(M.REASON_UNSUPPORTED)
        #  Предпросмотр умеет только накопитель gcodes: у прочих корней (config, logs)
        #  картинок нет и быть не может.
        if str(storage_id) not in self.printable_storages:
            raise PrinterFileError(M.REASON_NO_PREVIEW)
        norm = S.normalize_rel_path(rel_path)
        if not norm:
            raise PrinterFileError(M.REASON_BAD_REQUEST)
        try:
            j = self._get(self._pid(printer), "/server/files/thumbnails?filename=" + quote(norm))
        except PrinterFileError:
            raise
        except Exception:
            raise PrinterFileError(M.REASON_CONNECTION_LOST)
        rows = (j or {}).get("result") if isinstance(j, dict) else None
        if not isinstance(rows, list) or not rows:
            raise PrinterFileError(M.REASON_NO_PREVIEW)
        #  Берём САМУЮ КРУПНУЮ из тех, что влезают в потолок: мелкая часто 32x32 и в окне
        #  выглядит мылом. Записи без пути пропускаем молча — это не ошибка принтера.
        best, best_px = None, -1
        for r in rows:
            if not isinstance(r, dict):
                continue
            tp = str(r.get("thumbnail_path") or "").strip()
            if not tp:
                continue
            try:
                size = int(r.get("size") or 0)
            except Exception:
                size = 0
            if size and size > self.PREVIEW_MAX_BYTES:
                continue
            try:
                px = int(r.get("width") or 0) * int(r.get("height") or 0)
            except Exception:
                px = 0
            if px > best_px:
                best, best_px = tp, px
        if not best:
            raise PrinterFileError(M.REASON_NO_PREVIEW)
        try:
            blob = self._get_bytes(self._pid(printer), "/server/files/gcodes/" + quote(best))
        except PrinterFileError:
            raise
        except Exception:
            raise PrinterFileError(M.REASON_CONNECTION_LOST)
        if not blob or len(blob) > self.PREVIEW_MAX_BYTES:
            raise PrinterFileError(M.REASON_NO_PREVIEW)
        if bytes(blob[:8]) != b"\x89PNG\r\n\x1a\n":
            #  Пришло не изображение (например страница ошибки) — не показываем мусор.
            raise PrinterFileError(M.REASON_NO_PREVIEW)
        return (bytes(blob), "image/png")

    # ── удаление: официальный DELETE /server/files/{root}/{path} ──────────────
    def delete_file(self, printer, storage_id, rel_path):
        if not S.storage_id_ok(storage_id) or storage_id not in _WRITABLE_ROOTS:
            raise PrinterFileError(M.REASON_READ_ONLY)
        norm = S.normalize_rel_path(rel_path)
        if not norm:
            raise PrinterFileError(M.REASON_BAD_REQUEST)
        try:
            j = self._delete(self._pid(printer),
                             "/server/files/%s/%s" % (quote(str(storage_id)), quote(norm)))
        except PrinterFileError:
            raise
        except Exception:
            raise PrinterFileError(M.REASON_CONNECTION_LOST)
        # Подтверждение: Moonraker возвращает result с item/action. 404 транспорт
        # обязан поднять PrinterFileError(not_found) сам.
        if not isinstance(j, dict) or "result" not in j:
            raise PrinterFileError(M.REASON_DELETE_UNCONFIRMED)
        return True
