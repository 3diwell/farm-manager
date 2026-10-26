# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Общие чистые помощники без зависимостей от остального кода.

Вынесено из server.py без изменения поведения (шаг B1 реструктуризации).
Здесь могут жить только функции, которым не нужны глобальные объекты сервера
(состояние принтеров, БД, логгер и т.п.) — исключительно стандартная библиотека.
"""
import sys
import re


def _exc_brief(limit=240):
    """Краткое описание ТЕКУЩЕГО исключения (тип: текст), без трейсбэка — для журнала.
    Применяется там, где раньше ошибка молча проглатывалась (except: pass / continue):
    теперь сбой ВИДЕН в панели диагностики (уровень debug), но поведение НЕ меняется —
    поток исполнения прежний, лог лишь добавлен перед существовавшим pass/continue."""
    et, ev, _ = sys.exc_info()
    if et is None:
        return ""
    s = f"{et.__name__}: {ev}"
    return s if len(s) <= limit else s[:limit] + "…"


def _normalize_model(s):
    """Приводит название модели Bambu к каноническому виду: X1C, X1E, P1S, P1P, A1, A1M, H2D, P2S, ..."""
    if not s: return None
    t = str(s).upper().replace("BAMBU LAB", "").replace("BAMBULAB", "").replace("BAMBU", "").strip()
    t = t.replace("-", " ").replace("_", " ")
    # Сжатые коды моделей
    table = [
        ("X1 CARBON", "X1C"), ("X1C", "X1C"), ("X1E", "X1E"), ("X1", "X1"),
        ("P1S", "P1S"), ("P1P", "P1P"),
        ("A1 MINI", "A1M"), ("A1MINI", "A1M"), ("A1M", "A1M"), ("A1", "A1"),
        ("H2D", "H2D"), ("H2 D", "H2D"),
        ("H2S", "H2S"), ("H2 S", "H2S"),
        ("P2S", "P2S"), ("P2 S", "P2S"),
    ]
    compact = t.replace(" ", "")
    for needle, code in table:
        if needle.replace(" ", "") in compact:
            return code
    return compact or None


def _ver_tuple(s):
    """«Alpha 2.158» -> (2, 158). Любая версия раскладывается в кортеж целых для корректного сравнения."""
    return tuple(int(x) for x in re.findall(r"\d+", str(s or "")))
