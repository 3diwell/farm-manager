# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Совместимость нарезанного 3mf с моделью принтера (семьи совместимости).

Вынесено из server.py без изменения поведения (шаг B3 реструктуризации).
Чистый разбор 3mf и сравнение моделей. Функции, завязанные на состояние принтеров
(p_states) — _printer_model_code, _check_file_compatible — остаются в server.py.
"""
import io
import re
import json
import zipfile
import logging

from app.utils import _normalize_model, _exc_brief

log = logging.getLogger("farm")  # тот же логгер, что и в server.py -> та же панель диагностики


# Семьи совместимости: файл, нарезанный под модель из набора, печатается на принтере из того же набора.
# Двусопельные H2D/P2S держим раздельно от односопельных и, по умолчанию, друг от друга.
# X1-серия и P1-серия РАЗДЕЛЕНЫ намеренно: при одинаковом столе 256³ у них разный стартовый g-code и
# прошивка сверяет модель из файла — файл под P1S на X1C (и наоборот) даёт отказ/неоптимальную печать
# (у X1 есть лидар-калибровка, которой нет у P1). Внутри серии нарезка взаимозаменяема.
_MODEL_FAMILIES = [
    {"X1C", "X1", "X1E"},                 # X1-серия: лидар, одно сопло, core-XY, стол 256³
    {"P1S", "P1P"},                       # P1-серия: без лидара, одно сопло, core-XY, стол 256³ (P1S = P1P + корпус/камера)
    {"A1", "A1M"},                        # A1-серия
    {"H2D"},                              # двухсопельный H2D
    {"P2S"},                              # двухсопельный P2S
    {"H2S"},                              # односопельный H2S (новое поколение)
]

# Известные коды моделей Bambu (контролируемый словарь). По несовпадению МОДЕЛИ жёстко
# блокируем печать только когда ОБЕ модели отсюда — иначе (Klipper/FlashForge/кастом, где
# названия профилей непоследовательны) рискуем ложно заблокировать корректный файл.
_BAMBU_CODES = {"X1C", "X1", "X1E", "P1S", "P1P", "A1", "A1M", "H2D", "P2S", "H2S"}

def _detect_3mf_target(data3mf):
    """Извлекает из 3mf модель принтера и число экструдеров, для которых нарезан файл.
    Возвращает dict {model: канонический код|None, extruders: int|None}."""
    info = {"model": None, "extruders": None, "model_raw": None}
    try:
        with zipfile.ZipFile(io.BytesIO(data3mf)) as z:
            names = z.namelist()
            if "Metadata/project_settings.config" in names:
                try:
                    cfg = json.loads(z.read("Metadata/project_settings.config").decode("utf-8", "ignore"))
                    pm = cfg.get("printer_model") or cfg.get("printer_settings_id")
                    if isinstance(pm, list): pm = pm[0] if pm else None
                    if pm:
                        info["model_raw"] = str(pm).strip()
                        info["model"] = _normalize_model(pm)
                    for key in ("nozzle_diameter", "nozzle_volume", "extruder_offset"):
                        v = cfg.get(key)
                        if isinstance(v, list) and len(v) > 0:
                            info["extruders"] = len(v)
                            break
                except Exception:
                    log.debug("[_detect_3mf_target] exception suppressed: %s", _exc_brief())
            if (info["model"] is None or info["extruders"] is None) and "Metadata/slice_info.config" in names:
                raw = z.read("Metadata/slice_info.config").decode("utf-8", "ignore")
                if info["model"] is None:
                    m = re.search(r'printer_model_id["\s=>:]+([A-Za-z0-9_\- ]+)', raw)
                    if m:
                        info["model_raw"] = m.group(1).strip()
                        info["model"] = _normalize_model(m.group(1))
                if info["extruders"] is None:
                    ex = re.findall(r'<extruder\b', raw)
                    if ex: info["extruders"] = len(ex)
    except Exception as e:
        log.warning(f"[BAMBU COMPAT] Failed to read target printer from 3mf: {e}")
    return info

def _models_compatible(file_model, printer_model):
    """Совместимы ли модель файла и модель принтера.
    True  — точное совпадение или одна семья;
    False — УВЕРЕННО несовместимы (обе — известные коды Bambu из разных семей);
    None  — неизвестно/не сравнить (не блокируем, только показываем)."""
    if not file_model or not printer_model:
        return None  # неизвестно
    if file_model == printer_model:
        return True
    for fam in _MODEL_FAMILIES:
        if file_model in fam and printer_model in fam:
            return True
    # Жёстко «несовместимо» — только в контролируемом словаре Bambu (без ложных блокировок у прочих).
    if file_model in _BAMBU_CODES and printer_model in _BAMBU_CODES:
        return False
    return None


def _clean_model_value(v):
    """Отбросить пустое/шаблонное/Unknown значение модели из gcode-комментария."""
    if not v:
        return None
    v = str(v).strip().strip('"').strip()
    if not v or "[" in v or "]" in v or v.lower() == "unknown":
        return None
    return v


def _detect_gcode_target(data):
    """Определить целевой принтер из ПЛОСКОГО .gcode (Bambu/Orca/PrusaSlicer/SuperSlicer/Cura).

    Слайсеры пишут модель прямым текстом в комментариях, причём в разных местах:
      ; printer_model = …       — Bambu/Orca (блок CONFIG_BLOCK вверху) и PrusaSlicer/SuperSlicer (config внизу)
      M862.3 P "…"              — PrusaSlicer/SuperSlicer: команда-проверка модели прошивкой (в теле, у старта)
      ;TARGET_MACHINE.NAME:…    — Cura (2-я строка), но для самодельных профилей бывает 'Unknown'
    Поэтому читаем и ГОЛОВУ, и ХВОСТ файла (файлы бывают в десятки МБ — целиком не тащим).
    Возвращает {model, extruders, nozzle, bed, slicer} (любое поле может быть None)."""
    info = {"model": None, "extruders": None, "nozzle": None, "bed": None, "slicer": None}
    try:
        if isinstance(data, (bytes, bytearray)):
            head = bytes(data[:262144]).decode("utf-8", "ignore")
            tail = bytes(data[-131072:]).decode("utf-8", "ignore") if len(data) > 262144 else ""
        else:
            s = str(data); head = s[:262144]; tail = s[-131072:] if len(s) > 262144 else ""
        text = head + "\n" + tail
    except Exception:
        return info
    # Подпись слайсера (для уверенности/диагностики)
    if "BambuStudio" in text or "Bambu Studio" in text: info["slicer"] = "BambuStudio"
    elif "OrcaSlicer" in text or "Orca-Flashforge" in text: info["slicer"] = "OrcaSlicer"
    elif "SuperSlicer" in text: info["slicer"] = "SuperSlicer"
    elif "PrusaSlicer" in text or "prusaslicer_config" in text: info["slicer"] = "PrusaSlicer"
    elif "Cura_SteamEngine" in text or "Cura_Steamengine" in text or "Generated with Cura" in text: info["slicer"] = "Cura"
    # 1) ; printer_model = …  (Bambu/Orca/Prusa/Super) — самый надёжный
    m = re.search(r'(?im)^;\s*printer_model\s*=\s*(.+?)\s*$', text)
    if m: info["model"] = _clean_model_value(m.group(1))
    # 2) M862.3 P "…"  (Prusa/Super — работает, даже если config-блок вырезан)
    if not info["model"]:
        m = re.search(r'M862\.3\s+P\s*"([^"]+)"', text)
        if m: info["model"] = _clean_model_value(m.group(1))
    # 3) ;TARGET_MACHINE.NAME:…  (Cura)
    if not info["model"]:
        m = re.search(r'(?im)^;\s*TARGET_MACHINE\.NAME\s*:\s*(.+?)\s*$', text)
        if m: info["model"] = _clean_model_value(m.group(1))
    # Сопло и число экструдеров: nozzle_diameter может быть списком (двухсопельные → "0.4,0.4")
    m = re.search(r'(?im)^;\s*nozzle_diameter\s*=\s*([0-9.,]+)', text)
    if m:
        parts = [x for x in m.group(1).strip().split(",") if x]
        if parts:
            try: info["nozzle"] = float(parts[0])
            except Exception: pass
            info["extruders"] = len(parts)
    # Размер стола (для эвристики/показа)
    m = re.search(r'(?im)^;\s*printable_area\s*=\s*(.+?)\s*$', text)
    if m: info["bed"] = m.group(1).strip()
    return info


def detect_target(data, filename=None):
    """Единая точка: определить целевой принтер из файла (.3mf или плоский .gcode).
    Диспетчер по содержимому (ZIP-сигнатура 'PK' = 3mf) с учётом расширения имени.
    Возвращает {model, extruders, ...}."""
    is_zip = False
    try:
        is_zip = isinstance(data, (bytes, bytearray)) and bytes(data[:2]) == b"PK"
    except Exception:
        is_zip = False
    if is_zip or (filename and str(filename).lower().endswith(".3mf")):
        t = _detect_3mf_target(data)
        # Доп. надёжность: если в 3mf модель не нашли (старые/нестандартные) — пробуем
        # CONFIG_BLOCK встроенного plate-gcode (тот же ; printer_model = …).
        if not t.get("model"):
            try:
                with zipfile.ZipFile(io.BytesIO(data)) as z:
                    gcs = [n for n in z.namelist() if n.lower().endswith(".gcode")]
                    pl = sorted([n for n in gcs if "plate_" in n.lower()]) or sorted(gcs)
                    if pl:
                        g = _detect_gcode_target(z.read(pl[0])[:262144])
                        if g.get("model"): t["model"] = g["model"]
                        if not t.get("extruders") and g.get("extruders"): t["extruders"] = g["extruders"]
            except Exception:
                log.debug("[detect_target] embedded gcode not read: %s", _exc_brief())
        return t
    return _detect_gcode_target(data)

