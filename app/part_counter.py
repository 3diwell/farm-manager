# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Анализатор подсчёта деталей по метаданным слайсера.

Вынесено из server.py без изменения поведения (шаг B2 реструктуризации).
Чистая логика: путь к файлу -> {status,total,parts,...}. Не трогает БД, логгер и
состояние сервера. Запись результата в staging_part_counts выполняет _pc_for_staging
в server.py, который импортирует отсюда только итоговую _count_plate_parts.
"""
import os
import io
import json
import re
import time
import zipfile
import xml.etree.ElementTree as ET


PART_COUNT_ENABLED = True
PART_COUNT_MAX_ANALYSIS_MS = 1500
PART_COUNT_MAX_GCODE_SCAN_BYTES = 32 * 1024 * 1024
PART_COUNT_MAX_ZIP_ENTRY_BYTES = 64 * 1024 * 1024
PART_COUNT_MAX_TOTAL_UNCOMPRESSED_BYTES = 1024 * 1024 * 1024
PART_COUNT_MAX_COMPRESSION_RATIO = 200
PART_COUNT_MAX_OBJECTS = 5000
PART_COUNT_PARSER_VERSION = "pc_v1"
_PC_MODEL_EXTS = (".gcode.3mf", ".3mf", ".stl", ".obj", ".step", ".stp", ".gcode", ".ply")
_PC_RE_PRINTING_OBJECT = re.compile(r";\s*(?:start |stop )?printing object[,:\s]+(.+)", re.I)
_PC_RE_ID = re.compile(r"\bid[:=]\s*([^\s,]+)", re.I)
_PC_RE_COPY = re.compile(r"\bcopy[:=\s]+(\d+)", re.I)
_PC_RE_EXCLUDE_DEF = re.compile(r"EXCLUDE_OBJECT_DEFINE\s+NAME=([^\s,]+)", re.I)
_PC_RE_LAYER = re.compile(r"^\s*(?:;\s*LAYER_CHANGE|;\s*LAYER[:\s]|;\s*layer\s+num|; CHANGE_LAYER)", re.I | re.M)


def _pc_make(status, total=None, parts=None, source=None, confidence=None, reason=None, warnings=None):
    return {"status": status, "total": total, "parts": parts or [], "source": source,
            "confidence": confidence, "reason": reason,
            "parser": PART_COUNT_PARSER_VERSION if status == "counted" else None, "warnings": warnings or []}


def _pc_ignored(reason):
    return _pc_make("ignored", reason=reason)


def _pc_counted(counts, source, confidence="exact"):
    parts = sorted(({"name": k, "count": int(v)} for k, v in counts.items()),
                   key=lambda d: (-d["count"], d["name"].lower()))
    return _pc_make("counted", total=sum(int(v) for v in counts.values()), parts=parts, source=source, confidence=confidence)


def _pc_norm(raw):
    """Имя объекта -> каноническое имя детали. Без расширения модели. НЕ срезаем хвостовой
    '_NN' — 'Помидор' и 'Помидор_02' остаются РАЗНЫМИ деталями."""
    import unicodedata
    s = str(raw or "").strip()
    if len(s) >= 2 and s[0] in "\"'" and s[-1] == s[0]:
        s = s[1:-1].strip()
    s = s.replace("\\", "/").split("/")[-1]
    s = unicodedata.normalize("NFC", s).strip()
    low = s.lower()
    for ext in _PC_MODEL_EXTS:
        if low.endswith(ext):
            s = s[:-len(ext)]
            break
    return s.strip()


def _pc_over(deadline):
    return deadline is not None and time.monotonic() > deadline


_PC_RE_INST_FULL = re.compile(r"[._]id[._]\d+[._]copy[._]\d+$", re.I)


def _pc_strip_instance(name):
    """Снять хвостовой маркер экземпляра слайсера (Klipper и пр.), оставив базовое имя.
    Главный формат Klipper/Orca: '..._id_<n>_copy_<m>' (расширение модели в СЕРЕДИНЕ имени).
    Иначе — одиночные маркеры с явным ключом id/copy/instance/(N). БЕЗ ключа ничего не срезаем
    ('Помидор_02' и 'B10' не страдают)."""
    s = str(name)
    s2 = _PC_RE_INST_FULL.sub("", s)
    if s2 != s:
        return s2
    for _ in range(3):
        b = s
        s = re.sub(r"[._\s]+copy[._:=\s]*\d+$", "", s, flags=re.I)
        s = re.sub(r"[._\s]+id[._:=\s]*\d+$", "", s, flags=re.I)
        s = re.sub(r"[._\s]+instance[._:=\s]*\d+$", "", s, flags=re.I)
        s = re.sub(r"\s*\(\s*\d+\s*\)$", "", s)
        if s == b:
            break
    return s


def _pc_base_name(raw):
    """Базовое имя детали из метки объекта g-code: снять маркер экземпляра, затем нормализовать."""
    return _pc_norm(_pc_strip_instance(raw))


_PC_RE_PLATE_JSON = re.compile(r"Metadata/plate_\d+\.json$", re.I)


def _pc_match_key(name):
    """Устойчивый ключ детали, не зависящий от формата имени. slice_info заменяет пробелы на
    подчёркивания и добавляет хвост '_id_N_copy_M', а в plate_*.json имя оригинальное (с настоящими
    пробелами/подчёркиваниями). Снимаем маркер экземпляра и расширение модели, затем схлопываем к
    буквам/цифрам любого алфавита (убираем всё прочее и '_'): раньше схлопывали к [a-z0-9], и чисто кириллические
    имена ('Помидор', 'Огурец') давали ОДИН пустой ключ — разные детали путались между собой.
    Для латиницы ключ прежний: 'Flash_Forge_5M_Head_B8.stl_id_0_copy_0' и реальное
    'Flash Forge 5M Head B8.stl' дают ОДИН ключ 'flashforge5mheadb8'. Используется для матчинга
    превью к имени детали."""
    # NFC: без нормализации 'й' в NFC и NFD ('и'+знак) дали бы РАЗНЫЕ ключи (файлы с macOS пишут NFD).
    import unicodedata
    s = _pc_strip_instance(unicodedata.normalize("NFC", str(name or "")))
    low = s.lower()
    for ext in _PC_MODEL_EXTS:
        if low.endswith(ext):
            s = s[:-len(ext)]
            break
    return re.sub(r"[\W_]+", "", s.lower())


def _pc_apply_real_names(result, z, names):
    """Подменить имена деталей в result['parts'] на РЕАЛЬНЫЕ имена модели из Metadata/plate_*.json
    (поле bbox_objects.name) — там оригинал с настоящими пробелами/подчёркиваниями, тогда как
    slice_info заменяет пробелы на подчёркивания. Сопоставление по устойчивому ключу _pc_match_key.
    Тихо ничего не делает, если plate json нет или совпадение не найдено (имя остаётся как было)."""
    try:
        real = {}
        for n in names:
            if not _PC_RE_PLATE_JSON.search(n):
                continue
            try:
                data = json.loads(z.read(n).decode("utf-8", "ignore"))
            except Exception:
                continue
            for o in (data.get("bbox_objects") or []):
                nm = str((o or {}).get("name") or "").strip()
                if nm:
                    k = _pc_match_key(nm)
                    if k:   # имя без единой буквы/цифры даёт пустой ключ — не матчим, чтобы разные детали не слипались
                        real.setdefault(k, nm)
        if not real:
            return
        for p in (result.get("parts") or []):
            rn = real.get(_pc_match_key(p.get("name") or ""))
            if rn:
                p["name"] = rn
    except Exception:
        pass


def _pc_slice_info(raw_bytes):
    """slice_info.config: <plate>/<object identify_id name skipped>. result | None (неприменимо)."""
    if b"<!DOCTYPE" in raw_bytes or b"<!ENTITY" in raw_bytes:
        return _pc_ignored("malformed_metadata")
    try:
        root = ET.fromstring(raw_bytes)
    except Exception:
        return _pc_ignored("malformed_metadata")
    ids, noid, active = {}, [], 0
    for plate in root.iter("plate"):
        for obj in plate.iter("object"):
            if str(obj.get("skipped", "false")).strip().lower() in ("true", "1", "yes"):
                continue
            nm = obj.get("name")
            if nm is None or not str(nm).strip():
                return _pc_ignored("object_names_missing")
            norm = _pc_norm(nm)
            if not norm:
                return _pc_ignored("object_names_missing")
            active += 1
            if active > PART_COUNT_MAX_OBJECTS:
                return _pc_ignored("too_many_objects")
            iid = obj.get("identify_id")
            if iid is not None and str(iid).strip():
                iid = str(iid).strip()
                if iid in ids and ids[iid] != norm:
                    return _pc_ignored("object_identity_ambiguous")
                ids[iid] = norm
            else:
                noid.append(norm)
    if active == 0:
        return None
    if ids and noid:
        return _pc_ignored("object_identity_ambiguous")
    counts = {}
    for nm in (ids.values() if ids else noid):
        counts[nm] = counts.get(nm, 0) + 1
    return _pc_counted(counts, source="3mf_slice_info_config")


def _pc_model_settings(raw_bytes):
    """model_settings.config (запасной): <object id>+<metadata name>, экземпляры в assemble_item."""
    if b"<!DOCTYPE" in raw_bytes or b"<!ENTITY" in raw_bytes:
        return _pc_ignored("malformed_metadata")
    try:
        root = ET.fromstring(raw_bytes)
    except Exception:
        return _pc_ignored("malformed_metadata")
    id2name = {}
    for obj in root.iter("object"):
        oid, nm = obj.get("id"), None
        for md in obj.iter("metadata"):
            if md.get("key") == "name":
                nm = md.get("value")
                break
        if oid and nm:
            id2name[oid] = _pc_norm(nm)
    inst = [ai.get("object_id") for ai in root.iter("assemble_item") if ai.get("object_id")]
    names = [id2name[o] for o in inst if o in id2name] or list(id2name.values())
    names = [n for n in names if n]
    if not names:
        return None
    if len(names) > PART_COUNT_MAX_OBJECTS:
        return _pc_ignored("too_many_objects")
    counts = {}
    for nm in names:
        counts[nm] = counts.get(nm, 0) + 1
    return _pc_counted(counts, source="3mf_model_settings_config")


def _pc_first_layer(text):
    """Блоки 'printing object' между началом 1-го модельного слоя и началом 2-го."""
    starts = [m.start() for m in _PC_RE_PRINTING_OBJECT.finditer(text)]
    if not starts:
        return _pc_ignored("object_names_missing")
    layer_pos = [m.start() for m in _PC_RE_LAYER.finditer(text)]
    if len(layer_pos) < 2:
        return _pc_ignored("layer_boundaries_missing")
    after = [p for p in layer_pos if p > starts[0]]
    if not after:
        return _pc_ignored("layer_boundaries_missing")
    seg = text[starts[0]:after[0]]
    counts = {}
    for rem in _PC_RE_PRINTING_OBJECT.findall(seg):
        nm = _pc_base_name(re.split(r"\s+id[:=]", rem.strip(), flags=re.I)[0].strip().rstrip(","))
        if nm:
            counts[nm] = counts.get(nm, 0) + 1
    if not counts:
        return _pc_ignored("object_names_missing")
    return _pc_counted(counts, source="gcode_first_layer")


def _pc_gcode_comments(text):
    """Надёжные объектные комментарии. Ключ экземпляра = имя+id(+copy). result | None."""
    defs = _PC_RE_EXCLUDE_DEF.findall(text)
    if defs:
        counts = {}
        for nm in dict.fromkeys(defs):            # дедуп по полной метке (уникальна на экземпляр)
            b = _pc_base_name(nm)                 # снять _id_N_copy_M -> базовое имя -> сгруппировать копии
            if b:
                counts[b] = counts.get(b, 0) + 1
        if counts:
            return _pc_counted(counts, source="gcode_exclude_object_define")
    po = _PC_RE_PRINTING_OBJECT.findall(text)
    if po:
        keys, has_id = set(), True
        for rem in po:
            rem = rem.strip()
            mid = _PC_RE_ID.search(rem)
            mcp = _PC_RE_COPY.search(rem)
            name = _pc_base_name(re.split(r"\s+id[:=]", rem, flags=re.I)[0].strip().rstrip(","))
            if not name:
                continue
            if mid:
                keys.add((name, mid.group(1), mcp.group(1) if mcp else ""))
            else:
                has_id = False
                break
        if has_id and keys:
            counts = {}
            for (name, _i, _c) in keys:
                counts[name] = counts.get(name, 0) + 1
            return _pc_counted(counts, source="gcode_object_comments")
        return _pc_first_layer(text)
    return None


def _pc_zip_guard(z):
    """Защита от zip-бомбы/архивных атак. True если архив безопасен."""
    total = 0
    for zi in z.infolist():
        nm = zi.filename
        if nm.startswith("/") or ".." in nm.replace("\\", "/").split("/"):
            return False
        if getattr(zi, "flag_bits", 0) & 0x1:
            return False
        # G-code внутри 3mf читается с жёстким лимитом (PART_COUNT_MAX_GCODE_SCAN_BYTES),
        # поэтому его размер не опасен и не должен отклонять весь архив. Метаданные и
        # прочие записи по-прежнему ограничены пер-файловым лимитом. Защита от бомбы
        # (соотношение сжатия и общий объём) действует для всех записей, включая g-code.
        if not nm.lower().endswith(".gcode") and zi.file_size > PART_COUNT_MAX_ZIP_ENTRY_BYTES:
            return False
        if zi.compress_size > 0 and (zi.file_size / zi.compress_size) > PART_COUNT_MAX_COMPRESSION_RATIO and zi.file_size > 1024 * 1024:
            return False
        total += zi.file_size
        if total > PART_COUNT_MAX_TOTAL_UNCOMPRESSED_BYTES:
            return False
    return True


def _pc_zip_plate_gcode(z):
    gco = [n for n in z.namelist() if n.lower().endswith(".gcode")]
    if not gco:
        return ""
    gco.sort(key=lambda n: (0 if "plate" in n.lower() else 1, len(n)))
    if z.getinfo(gco[0]).file_size > PART_COUNT_MAX_ZIP_ENTRY_BYTES:
        return ""
    with z.open(gco[0]) as f:
        return f.read(PART_COUNT_MAX_GCODE_SCAN_BYTES).decode("utf-8", "ignore")


def _count_plate_parts(path):
    """Координатор: тип по сигнатуре -> стратегии по убыванию доверия. Никогда не бросает."""
    if not PART_COUNT_ENABLED:
        return _pc_ignored("disabled")
    if not path or not os.path.isfile(path):
        return _pc_ignored("unsupported_format")
    deadline = time.monotonic() + PART_COUNT_MAX_ANALYSIS_MS / 1000.0
    try:
        text = ""
        if zipfile.is_zipfile(path):
            try:
                with zipfile.ZipFile(path) as z:
                    if not _pc_zip_guard(z):
                        return _pc_ignored("archive_limit_exceeded")
                    names = set(z.namelist())
                    if "Metadata/slice_info.config" in names:
                        r = _pc_slice_info(z.read("Metadata/slice_info.config"))
                        if r is not None:
                            _pc_apply_real_names(r, z, names)   # подтянуть реальные имена моделей из plate_*.json
                            return r
                    if _pc_over(deadline):
                        return _pc_ignored("time_limit_exceeded")
                    if "Metadata/model_settings.config" in names:
                        r = _pc_model_settings(z.read("Metadata/model_settings.config"))
                        if r is not None:
                            return r
                    text = _pc_zip_plate_gcode(z)
            except zipfile.BadZipFile:
                return _pc_ignored("malformed_metadata")
        else:
            with open(path, "rb") as f:
                text = f.read(PART_COUNT_MAX_GCODE_SCAN_BYTES).decode("utf-8", "ignore")
        if _pc_over(deadline):
            return _pc_ignored("time_limit_exceeded")
        if not text:
            return _pc_ignored("object_names_missing")
        r = _pc_gcode_comments(text)
        return r if r is not None else _pc_ignored("object_names_missing")
    except Exception:
        return _pc_ignored("malformed_metadata")


# ============================================================================
# ЗАПАСНОЙ СЧЁТЧИК КОПИЙ ПО ГЕОМЕТРИИ (только для g-code БЕЗ объектных меток —
# «старые» выгрузки OrcaSlicer/Prusa с gcode_label_objects=0). Не анализирует
# именованные детали; даёт лишь число одинаковых копий на плите. Принцип:
# артефакты (перемычки/брим) могут только СОЕДИНИТЬ объекты (занизить счёт),
# но сплошной периметр никогда ложно не разделит одну деталь. Поэтому берём
# максимальное число ОДНОРОДНЫХ компонент, устойчиво встречающихся по слоям.
# Консервативно: если компоненты разнородны (не копии) — возвращаем 1 (как было).
# ============================================================================
_PC_COPY_CELL = 1.0          # размер ячейки растеризации, мм
_PC_COPY_MIN_CELLS = 8       # компонент меньше — мусор (артефакт/юбка)
_PC_COPY_RATIO = 1.7         # макс. отношение размеров компонент, чтобы считать их копиями
_PC_COPY_MAX = 64            # потолок числа копий
_PC_COPY_SAMPLE = 16         # сколько слоёв сэмплировать
_PC_COPY_BUDGET_MS = 1200    # бюджет времени

def _pc_layer_starts(lines):
    """Индексы строк начала слоёв (один тип маркера по приоритету; иначе Z-подъёмы)."""
    probes = (lambda l: ";AFTER_LAYER_CHANGE" in l,
              lambda l: l[:7] == ";LAYER:",
              lambda l: l[:11] == "; layer num" or l[:13] == ";LAYER_CHANGE" or l[:13] == "; CHANGE_LAYER",
              lambda l: (l[:5] == "G1 Z" or l[:5] == "G0 Z"))
    for probe in probes:
        idx = [i for i, l in enumerate(lines) if probe(l)]
        if len(idx) >= 6:
            return idx
    return []

def _pc_layer_components(lines, a, b, cell=_PC_COPY_CELL):
    """Размеры связных компонент экструзии на участке слоя [a:b) (растеризация отрезков)."""
    import collections
    x = y = None
    occ = set()
    for l in lines[a:b]:
        s = l.strip()
        if s[:2] in ("G1", "G0"):
            mx = re.search(r"X([-0-9.]+)", s)
            my = re.search(r"Y([-0-9.]+)", s)
            me = re.search(r"E([-0-9.]+)", s)
            nx = float(mx.group(1)) if mx else x
            ny = float(my.group(1)) if my else y
            if me and x is not None and nx is not None:
                try: ext = float(me.group(1)) > 0
                except Exception: ext = False
                if ext:
                    d = max(abs(nx - x), abs(ny - y))
                    steps = max(1, int(d / (cell * 0.6)))
                    for k in range(steps + 1):
                        t = k / steps
                        occ.add((int((x + (nx - x) * t) / cell), int((y + (ny - y) * t) / cell)))
            x, y = nx, ny
    seen = set()
    sizes = []
    for c in occ:
        if c in seen:
            continue
        sz = 0
        q = collections.deque([c]); seen.add(c)
        while q:
            cur = q.popleft(); sz += 1
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    n = (cur[0] + dx, cur[1] + dy)
                    if n in occ and n not in seen:
                        seen.add(n); q.append(n)
        sizes.append(sz)
    return sorted([s for s in sizes if s >= _PC_COPY_MIN_CELLS], reverse=True)

def count_gcode_copies(path, max_bytes=PART_COUNT_MAX_GCODE_SCAN_BYTES):
    """Число одинаковых копий на плите для g-code без объектных меток. >=1, при сомнении 1."""
    try:
        if not path or not os.path.isfile(path):
            return 1
        with open(path, "rb") as f:
            text = f.read(max_bytes).decode("utf-8", "ignore")
    except Exception:
        return 1
    try:
        lines = text.split("\n")
        idx = _pc_layer_starts(lines)
        if len(idx) < 6:
            return 1
        lo, hi = int(len(idx) * 0.15), int(len(idx) * 0.9)
        band = list(range(max(1, lo), max(2, hi)))
        if len(band) < 6:
            band = list(range(1, len(idx) - 1))
        step = max(1, len(band) // _PC_COPY_SAMPLE)
        sample = band[::step][:_PC_COPY_SAMPLE]
        deadline = time.monotonic() + _PC_COPY_BUDGET_MS / 1000.0
        import collections
        uniform = collections.Counter()
        n_used = 0
        for L in sample:
            if time.monotonic() > deadline:
                break
            a = idx[L]
            b = idx[L + 1] if L + 1 < len(idx) else len(lines)
            cs = _pc_layer_components(lines, a, b)
            n_used += 1
            if len(cs) >= 2 and cs[0] <= cs[-1] * _PC_COPY_RATIO:   # однородные = копии
                uniform[len(cs)] += 1
        if not uniform or n_used == 0:
            return 1
        thr = max(2, int(n_used * 0.33))
        cand = [k for k, c in uniform.items() if c >= thr]
        return max(1, min(max(cand) if cand else 1, _PC_COPY_MAX))
    except Exception:
        return 1


def is_3mf_printable(data_or_path):
    """True, если 3MF — нарезанный (sliced), т.е. готов к печати.
    Признак: внутри ZIP есть G-code (Metadata/plate_N.gcode или любой .gcode).
    Перенесено из server.py без изменения поведения (чистый модуль для рабочих процессов)."""
    try:
        zf = zipfile.ZipFile(data_or_path if isinstance(data_or_path, str) else io.BytesIO(data_or_path))
        with zf as z:
            for n in z.namelist():
                low = n.lower()
                if low.endswith(".gcode") or low.endswith(".gcode.md5"):
                    return True
        return False
    except Exception:
        return False
