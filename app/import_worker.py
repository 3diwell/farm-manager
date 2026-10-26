# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Разбор ОДНОГО файла импорта — выполняется в отдельном процессе (многоядерность).

ВАЖНО про точность: здесь меняется только МЕСТО выполнения (рабочий процесс),
но НЕ алгоритмы. Используются ровно те же функции, что и на сервере:
  - detect_target      (app.model_compat)  — под какой принтер нарезан файл;
  - _count_plate_parts (app.part_counter)  — подсчёт деталей на плите;
  - count_gcode_copies (app.part_counter)  — число копий по геометрии (fallback);
  - is_3mf_printable   (app.part_counter)  — готов ли .3mf к печати.
Поэтому результат разбора идентичен серверному add_file_to_project.

Модуль ЧИСТЫЙ: не импортирует server.py, не открывает БД и не поднимает связь
с принтерами. Это позволяет безопасно запускать его в рабочих процессах
(в т.ч. на Windows со 'spawn').
"""
import os
import hashlib

from app.part_counter import _count_plate_parts, count_gcode_copies, is_3mf_printable
from app.model_compat import detect_target


def _file_hash(path):
    """sha256 файла (для возможной дедупликации). Идентичен серверному _file_hash."""
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


def _local_target(path):
    """Цель печати (model/model_raw/extruders). Та же стратегия чтения, что и в серверном
    _local_file_target: .3mf — целиком, .gcode — голова (256К) + хвост (128К); тот же detect_target.
    Кэш не нужен (в рабочем процессе он не переиспользуется)."""
    empty = {"model": None, "model_raw": None, "extruders": None}
    if not path:
        return empty
    try:
        st = os.stat(path)
        low = path.lower()
        if low.endswith(".3mf"):
            with open(path, "rb") as f:
                _t = detect_target(f.read(), path)
        elif low.endswith(".gcode"):
            with open(path, "rb") as f:
                head = f.read(262144)
                tail = b""
                if st.st_size > 262144:
                    f.seek(max(0, st.st_size - 131072)); tail = f.read(131072)
            _t = detect_target(head + b"\n" + tail, path)
        else:
            return empty
        return {"model": _t.get("model"), "model_raw": _t.get("model_raw"), "extruders": _t.get("extruders")}
    except Exception:
        return empty


def _analyze_manifest(path):
    """Манифест деталей плиты — идентично серверному analyze_project_plate
    (тот же _count_plate_parts, та же фильтрация/формат)."""
    try:
        r = _count_plate_parts(path) or {}
    except Exception:
        r = {}
    if r.get("status") != "counted":
        return []
    src, conf = (r.get("source") or ""), (r.get("confidence") or "")
    out = []
    for p in (r.get("parts") or []):
        nm = str(p.get("name") or "").strip()
        if not nm:
            continue
        out.append({"name": nm, "qty": max(1, int(p.get("count") or 1)), "ids": [], "source": src, "confidence": conf})
    return out


def _fallback_base(filename):
    """Базовое имя детали по имени файла (идентично серверной ветке fallback)."""
    base = os.path.splitext(os.path.basename(filename or ""))[0]
    if base.lower().endswith(".gcode"):
        base = os.path.splitext(base)[0]
    return base.strip() or (filename or "") or "file"


def parse_file(path, filename):
    """Полный разбор файла. Возвращает простой dict для последующей вставки в БД
    основным процессом:
        {ok, chash, is_print, tmodel, tnoz, analyzed, parts:[{name,qty,ids,confidence,source}]}
    parts — финальный список (детали с плиты ИЛИ одна деталь по имени файла)."""
    out = {"ok": False, "chash": "", "is_print": 0, "tmodel": "", "tnoz": 0, "analyzed": False, "parts": []}
    try:
        if not path:
            out["parts"] = [{"name": _fallback_base(filename), "qty": 1, "ids": [], "confidence": "filename", "source": "filename"}]
            out["ok"] = True
            return out
        tgt = _local_target(path)
        out["tmodel"] = (tgt.get("model_raw") or tgt.get("model") or "")
        out["tnoz"] = int(tgt.get("extruders") or 0)
        low = (filename or "").lower()
        if low.endswith(".gcode"):
            out["is_print"] = 1
        elif low.endswith(".3mf"):
            try:
                out["is_print"] = 1 if is_3mf_printable(path) else 0
            except Exception:
                out["is_print"] = 0
        out["chash"] = _file_hash(path)
        manifest = _analyze_manifest(path)
        out["analyzed"] = bool(manifest)
        if manifest:
            out["parts"] = manifest
        else:
            base = _fallback_base(filename)
            qty, src = 1, "filename"
            if low.endswith((".gcode", ".gco", ".g")):
                try:
                    n = count_gcode_copies(path)
                    if n > 1:
                        qty, src = n, "gcode_geometry"
                except Exception:
                    qty, src = 1, "filename"
            out["parts"] = [{"name": base, "qty": qty, "ids": [], "confidence": ("estimated" if qty > 1 else "filename"), "source": src}]
        out["ok"] = True
    except Exception:
        out["ok"] = False
    return out
