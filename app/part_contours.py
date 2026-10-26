# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# =============================================================================
# 3DIWELL Farm Manager — серверные ПЛОСКИЕ 2D-превью деталей из присланного файла.
#
# Источник — маска выбора объектов слайсера (Metadata/pick_*.png внутри .gcode.3mf):
# в ней каждый объект залит цветом, кодирующим его identify_id (R + G*256 + B*65536).
# Это footprint детали сверху, как его видит сам слайсер, СО СКВОЗНЫМИ ОТВЕРСТИЯМИ.
# Берём силуэт каждой детали, сглаживаем и рисуем плоской бирюзовой заливкой с чётким
# контуром. Имя детали — из slice_info (identify_id -> name), ключ = _pc_norm(name),
# как у детектора деталей (поэтому фронт находит превью по part_name).
#
# Плюсы против разбора траекторий: контуры/отверстия совпадают с платой, привязка имён
# берётся из самого слайсера, и НЕ нужно парсить десятки МБ g-code — отдаём мгновенно.
# Только Pillow (без numpy). При любой ошибке/отсутствии маски -> {}: эндпоинт откатится
# к вшитым превью / превью плиты.
# =============================================================================

import os, io, re, zipfile, threading
from PIL import Image, ImageDraw, ImageChops, ImageFilter

from app.part_counter import _pc_norm, _pc_match_key

# --- параметры отрисовки (цвет легко поменять) -------------------------------
PREVIEW_PX = 240          # размер итогового превью, px
_SS        = 4            # суперсэмплинг кромки
_FRAME     = 0.84         # доля кадра под деталь (поля вокруг)
C_FILL = (56, 176, 168)   # заливка (бирюза)
C_EDGE = (12, 28, 44)     # контур (тёмный)
_MIN_PART_PX = 30         # меньше — считаем мусором/незначимым
_LO, _HI = 90.0, 150.0    # мягкий порог сглаживания кромки

_CACHE = {}               # (path, mtime, size) -> {key: png}
_LOCK = threading.Lock()


def _render_flat_mask(sub):
    """Бинарная маска детали (L, 0/255) -> PNG плоского силуэта с гладкой кромкой."""
    S = PREVIEW_PX * _SS
    w, h = sub.size
    if w < 2 or h < 2:
        return None
    target = int(PREVIEW_PX * _FRAME)
    sc = target / float(max(w, h))
    big = sub.resize((max(1, int(w * sc * _SS)), max(1, int(h * sc * _SS))), Image.LANCZOS)
    big = big.filter(ImageFilter.GaussianBlur(_SS * 0.6))
    alpha = Image.new("L", (S, S), 0)
    alpha.paste(big, ((S - big.width) // 2, (S - big.height) // 2))
    # мягкий порог -> ровная сглаженная граница (вместо лесенки 512px-источника)
    alpha = alpha.point(lambda v: int(max(0.0, min(255.0, (v - _LO) * 255.0 / (_HI - _LO)))))
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    img.paste(C_FILL + (255,), (0, 0, S, S), alpha)
    hard = alpha.point(lambda v: 255 if v >= 128 else 0)
    border = ImageChops.subtract(hard, hard.filter(ImageFilter.MinFilter(2 * _SS + 1)))
    img = Image.composite(Image.new("RGBA", (S, S), C_EDGE + (255,)), img, border)
    img = img.resize((PREVIEW_PX, PREVIEW_PX), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def _part_mask(R, G, B, sid):
    """Маска пикселей детали по её identify_id (цвет = R + G*256 + B*65536)."""
    r, g, b = sid & 255, (sid >> 8) & 255, (sid >> 16) & 255
    mR = R.point(lambda v, t=r: 255 if v == t else 0)
    mG = G.point(lambda v, t=g: 255 if v == t else 0)
    mB = B.point(lambda v, t=b: 255 if v == t else 0)
    return ImageChops.multiply(ImageChops.multiply(mR, mG), mB)  # AND для 0/255


def _build_from_pick(path):
    """Прочитать pick-маску и slice_info из .gcode.3mf, отрисовать превью всех деталей.
    -> {_pc_norm(имя): png}."""
    out = {}
    if not zipfile.is_zipfile(path):
        return out
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        picks = [n for n in names if re.search(r"(^|/)pick_\d+\.png$", n.lower())]
        if not picks:
            return out
        picks.sort(key=lambda n: (0 if "pick_1." in n.lower() else 1, n))
        try:
            si = z.read("Metadata/slice_info.config").decode("utf-8", "ignore")
        except Exception:
            return out
        id2name = {}
        for m in re.finditer(r"<object\b([^>]*?)/?>", si):
            attrs = dict(re.findall(r'(\w+)="([^"]*)"', m.group(1)))
            if attrs.get("identify_id"):
                try:
                    id2name[int(attrs["identify_id"])] = attrs.get("name", "")
                except Exception:
                    pass
        if not id2name:
            return out
        # Многоплитный проект: нарезана может быть не первая плита (slice_info index=2
        # и т.п.), тогда цвет детали лежит в pick_2.png, а не pick_1.png. Грузим ВСЕ
        # pick_*.png и ищем каждую деталь там, где реально встречается её цвет-id.
        layers = []
        for pn in picks:
            try:
                im = Image.open(io.BytesIO(z.read(pn))).convert("RGB")
                layers.append((im.split(), im.size))
            except Exception:
                continue
        if not layers:
            return out
        for sid, raw in id2name.items():
            key = _pc_match_key(raw)
            if not key or key in out:                 # дубли-копии одной детали -> один силуэт
                continue
            for (R, G, B), (W, H) in layers:
                try:
                    mask = _part_mask(R, G, B, sid)
                    bbox = mask.getbbox()
                    if not bbox or mask.histogram()[-1] < _MIN_PART_PX:
                        continue
                    x0 = max(0, bbox[0] - 2); y0 = max(0, bbox[1] - 2)
                    x1 = min(W, bbox[2] + 2); y1 = min(H, bbox[3] + 2)
                    png = _render_flat_mask(mask.crop((x0, y0, x1, y1)))
                    if png:
                        out[key] = png
                        break                          # деталь найдена в этой плите
                except Exception:
                    continue
    return out


# --- обычный .gcode (не zip): силуэты из EXCLUDE_OBJECT_DEFINE-полигонов ------
# FlashForge / Klipper / Orca-gcode пишут контур каждого объекта строкой
#   EXCLUDE_OBJECT_DEFINE NAME=<имя> ... POLYGON=[[x,y],...]
# Это footprint детали сверху (внешний контур, без сквозных отверстий). Рисуем тем
# же плоским стилем. Имя (напр. Flash_Forge_5M_Head_B8.stl_id_0_copy_0) через
# _pc_match_key даёт тот же ключ, что и part_name, поэтому фронт находит превью.
_RE_OBJ_NAME = re.compile(r"EXCLUDE_OBJECT_DEFINE\s+NAME=(\S+)")
_RE_NUM = re.compile(r"-?\d+(?:\.\d+)?")


def _gcode_head_text(path, fileobj=None):
    """Заголовок g-code (до начала печати) — там лежат все EXCLUDE_OBJECT_DEFINE.
    Читаем построчно и выходим, как только пошла печать, чтобы НЕ грузить десятки МБ
    траекторий. Источник — путь (обычный .gcode) или открытый file-like (из .3mf)."""
    buf = []

    def _scan(fh):
        for i, line in enumerate(fh):
            if i > 200000:
                break
            if isinstance(line, (bytes, bytearray)):
                line = line.decode("utf-8", "ignore")
            buf.append(line)
            if line.startswith("EXCLUDE_OBJECT_START") or line.startswith("; printing object"):
                break

    try:
        if fileobj is not None:
            _scan(fileobj)
        else:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                _scan(f)
    except Exception:
        return ""
    return "".join(buf)


def _read_3mf_gcode_head(path):
    """Заголовок ВСТРОЕННОГО g-code из .3mf — запас для .3mf без pick-маски."""
    try:
        with zipfile.ZipFile(path) as z:
            cands = [n for n in z.namelist() if n.lower().endswith(".gcode")]
            if not cands:
                return ""
            cands.sort(key=lambda n: (0 if "plate_1." in n.lower() else 1, n))
            with z.open(cands[0]) as fh:
                return _gcode_head_text(None, fileobj=fh)
    except Exception:
        return ""


def _render_polygon(pts):
    """Залитый силуэт по списку точек контура (мм) -> PNG в общем стиле."""
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    minx, maxx = min(xs), max(xs)
    miny, maxy = min(ys), max(ys)
    w = maxx - minx
    h = maxy - miny
    if w <= 0 or h <= 0:
        return None
    sc = 512.0 / max(w, h)            # растеризуем длинной стороной ~512px
    pad = 4
    W = max(2, int(round(w * sc)) + pad * 2)
    H = max(2, int(round(h * sc)) + pad * 2)
    mask = Image.new("L", (W, H), 0)
    # ось Y в g-code направлена вверх -> переворачиваем для вида сверху
    poly = [((x - minx) * sc + pad, (maxy - y) * sc + pad) for (x, y) in pts]
    ImageDraw.Draw(mask).polygon(poly, fill=255)
    return _render_flat_mask(mask)


def _build_from_gcode_text(text):
    """{_pc_match_key(имя): png} из строк EXCLUDE_OBJECT_DEFINE заголовка g-code.
    {} если их нет (эндпоинт откатится к превью плиты)."""
    out = {}
    if not text or "EXCLUDE_OBJECT_DEFINE" not in text:
        return out
    for line in text.splitlines():
        if "EXCLUDE_OBJECT_DEFINE" not in line:
            continue
        nm = _RE_OBJ_NAME.search(line)
        pi = line.find("POLYGON=")
        if not nm or pi < 0:
            continue
        key = _pc_match_key(nm.group(1))
        if not key or key in out:
            continue                 # дубли-копии одной детали -> один силуэт
        nums = _RE_NUM.findall(line[pi + 8:])
        pts = [(float(nums[k]), float(nums[k + 1])) for k in range(0, len(nums) - 1, 2)]
        if len(pts) < 3:
            continue
        try:
            png = _render_polygon(pts)
            if png:
                out[key] = png
        except Exception:
            continue
    return out


def _build(path):
    """Диспетчер источника превью деталей:
    • .gcode.3mf с pick-маской -> силуэты из неё (со сквозными отверстиями);
    • обычный .gcode или .3mf без pick-маски -> силуэты из EXCLUDE_OBJECT_DEFINE."""
    # 🔒 ОТЛАЖЕНО — порядок источников превью деталей проверен на реальных файлах (одно- и многоплитные .3mf, обычный .gcode с EXCLUDE_OBJECT_DEFINE). Не менять без перепроверки.
    if zipfile.is_zipfile(path):
        out = _build_from_pick(path)
        if out:
            return out
        return _build_from_gcode_text(_read_3mf_gcode_head(path))
    return _build_from_gcode_text(_gcode_head_text(path))


def render_contour_previews(path):
    """{_pc_norm(имя_детали): png_bytes} для .gcode.3mf. Кэш по (path,mtime,size).
    {} при ошибке/отсутствии pick-маски -> эндпоинт откатится к превью плиты."""
    try:
        st = os.stat(path)
        ckey = (path, int(st.st_mtime), st.st_size)
    except Exception:
        return {}
    cached = _CACHE.get(ckey)
    if cached is not None:
        return cached
    with _LOCK:
        cached = _CACHE.get(ckey)
        if cached is not None:
            return cached
        try:
            res = _build(path)
        except Exception:
            res = {}
        if len(_CACHE) > 64:
            try:
                _CACHE.pop(next(iter(_CACHE)))
            except Exception:
                _CACHE.clear()
        _CACHE[ckey] = res
        return res
