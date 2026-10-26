# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Сборка шрифтов интерфейса «3DIWELL Wide J» и «3DIWELL Wide P» из свободных Jura и Play.

ЗАЧЕМ. Фирменный Sony Sketch EF нельзя распространять (права Monotype, лицензии нет). Замена —
шрифты под SIL Open Font License 1.1, которую разрешено изменять и распространять. Интерфейс
программы выверен под Sony Sketch: рисунок букв занимает ~49 % кегля и широкий. Чтобы замена
заняла на экране то же место, буквы уменьшаются до высоты заглавной Sony Sketch, а строка
текста в среднем выходит той же длины, что у него. Коэффициенты считаются замером, а не на глаз.

ЧТО МЕНЯЕТСЯ В ШРИФТАХ (26.09.2026, вторая редакция — по замечаниям владельца «Jura размытый»,
«буквы слишком близко»):
  • Jura берётся насыщеннее её самого жирного начертания (wght 700): ось насыщенности у Jura одна
    и линейная (одна опорная точка), поэтому начертание продлевается по тем же приращениям
    автора. Тонкий штрих на экране выходил меньше пикселя и расплывался серым.
  • Между буквами — одинаковая прибавка (TRACK_EM), пробел между словами — как у Sony Sketch.
    Длина строки при этом прежняя: буквы расширяются меньше, промежутки — больше.
  • Контуры, ширины знаков, кернинг и привязки диакритики масштабируются.
  • Подгонка контуров под пиксели экрана (hinting) делается заново программой ttfautohint —
    прежняя после масштаба неверна, а без подгонки на Windows горизонтальные штрихи мылятся.
  • Шрифт получает новое имя. У Play имя «Play» зарезервировано автором (Reserved Font Name) —
    изменённая версия называться так не может, поэтому оба шрифта названы «3DIWELL Wide …».
    Уведомления об авторских правах авторов сохраняются, лицензия прежняя — OFL 1.1.

ИСТОЧНИКИ. Файлы Google Fonts (github.com/google/fonts) на закреплённых коммитах, сверка SHA-256.

    python tools/build_ui_fonts.py --src <папка с исходными файлами> [--out web/design/fonts]
    python tools/build_ui_fonts.py --download --src <пустая папка вне проекта>

Нужны fontTools с brotli и ttfautohint-py (pip install fonttools brotli ttfautohint-py==0.6.1) —
только для сборки; программе они не нужны: в программу попадают готовые .woff2.
Одинаковые исходники и те же версии библиотек дают побайтно те же файлы.
"""
import argparse
import hashlib
import io
import os
import sys
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_OUT = os.path.join(REPO, "web", "design", "fonts")
GF = "https://raw.githubusercontent.com/google/fonts/%s/%s"
SOURCES = {
    "Jura-VF.ttf": ("6e4b84c976cadb3c49a40fd9a1c203e4f7fcf2da", "ofl/jura/Jura%5Bwght%5D.ttf",
                    "188b415d44810d68b4d6b4a8c281f864184c2b8edc5e88e6357c89f7b44075bf"),
    "Jura-OFL.txt": ("6e4b84c976cadb3c49a40fd9a1c203e4f7fcf2da", "ofl/jura/OFL.txt",
                     "54d85ef76f1fcf89671e196a9bca6b02683c68277caa89d89ff1b63a5fe9c421"),
    "Play-Regular.ttf": ("51c6a423fbfbd78a5111241dfd07791644b4c5c6", "ofl/play/Play-Regular.ttf",
                         "eed0da79005cab35d6ed0eacab594ed67cc643be0b2632fa9e440b3bc5078dc4"),
    "Play-Bold.ttf": ("51c6a423fbfbd78a5111241dfd07791644b4c5c6", "ofl/play/Play-Bold.ttf",
                      "45c572eccda4cf335165b750345258e753035bf48ee2fdf37faa07c7db88bce0"),
    "Play-OFL.txt": ("51c6a423fbfbd78a5111241dfd07791644b4c5c6", "ofl/play/OFL.txt",
                     "6d216cec166b6e139adaa599053dd49720c053e1f2adb4845de3cc9c3704344d"),
}

#  Замер Sony Sketch EF 2.0.5: высота заглавной H, средняя ширина знака на русско-латинском образце
#  и ширина пробела — в долях кегля. Сам файл Sony Sketch сборке не нужен.
SONY_CAP = 0.4883
SONY_ADV = 0.5085
SONY_SPACE = 0.2949
SAMPLE = ("Принтеры Очередь Склад Настройки Печать идёт абвгдеёжзийклмнопрстуфхцчшщъыьэюя "
          "ABCDEFGHIJKLMNOPQRSTUVWXYZ abcdefghijklmnopqrstuvwxyz 0123456789")
SPACE_CODES = (0x20, 0xA0)                 # пробел и неразрывный пробел — ширина как у Sony Sketch

TRACK_EM = 0.022                            # прибавка между буквами, доля кегля (при size = 1)
#  Начертания. wght — насыщенность Jura (у источника ось 300..700, выше — продление, см. jura_at);
#  size — во сколько раз буквы и строка крупнее Sony Sketch при том же кегле (1 — ровно как он).
#  Wide J 1.200 (26.09.2026, третья редакция по замечаниям владельца «неточный, мелковат, буквы
#  сливаются»): своё жирное начертание (раньше жирный текст браузер раздувал сам — буквы слипались),
#  обычное 850 (чуть светлее прежних 900 — просветы в «в», «е», «з», «8» не заливаются), на 7 % крупнее,
#  подгонка под пиксели поднимает строчные до целого пикселя на мелком тексте (increase_x_height) и
#  ставит толщину штриха строго по пикселям (stem width mode = strong).
J_SIZE = 1.07
J_HINT = dict(increase_x_height=22, gray_stem_width_mode=1, gdi_cleartype_stem_width_mode=1,
              dw_cleartype_stem_width_mode=1)
FACES = [
    dict(src="Jura-VF.ttf", wght=850, family="3DIWELL Wide J", style="Regular", dst="3diwell-wide-j.woff2",
         notice="Jura-OFL.txt", size=J_SIZE, track=TRACK_EM * J_SIZE, hint=J_HINT, version="1.200"),
    dict(src="Jura-VF.ttf", wght=1000, family="3DIWELL Wide J", style="Bold", dst="3diwell-wide-j-bold.woff2",
         notice="Jura-OFL.txt", size=J_SIZE, track=TRACK_EM * J_SIZE, hint=J_HINT, version="1.200"),
    dict(src="Play-Regular.ttf", wght=None, family="3DIWELL Wide P", style="Regular", dst="3diwell-wide-p-regular.woff2",
         notice="Play-OFL.txt", size=1.0, track=TRACK_EM),
    dict(src="Play-Bold.ttf", wght=None, family="3DIWELL Wide P", style="Bold", dst="3diwell-wide-p-bold.woff2",
         notice="Play-OFL.txt", size=1.0, track=TRACK_EM),
]
VERSION = "1.100"
BUILD_STAMP = "Sat Sep 26 00:00:00 2026"
AUTOHINT = dict(no_info=True, hinting_range_min=8, hinting_range_max=50, hinting_limit=200,
                increase_x_height=0, windows_compatibility=True, default_script="latn",
                fallback_script="none")


def sha256(p):
    with open(p, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def download(src):
    os.makedirs(src, exist_ok=True)
    for name, (commit, path, _) in SOURCES.items():
        req = urllib.request.Request(GF % (commit, path), headers={"User-Agent": "3diwell-build"})
        with urllib.request.urlopen(req, timeout=60) as r, open(os.path.join(src, name), "wb") as f:
            f.write(r.read())


def check_sources(src):
    bad = []
    for name, (_, _, want) in SOURCES.items():
        p = os.path.join(src, name)
        if not os.path.isfile(p) or sha256(p) != want:
            bad.append(name)
    return bad


def glyph_stats(font):
    """-> (высота заглавной, средняя ширина знака на образце, ширина пробела) в долях кегля."""
    from fontTools.pens.boundsPen import BoundsPen
    upem = font["head"].unitsPerEm
    gs = font.getGlyphSet()
    cmap = font.getBestCmap()
    pen = BoundsPen(gs)
    gs[cmap[ord("H")]].draw(pen)
    cap = pen.bounds[3] / upem
    hmtx = font["hmtx"]
    adv = sum(hmtx[cmap[ord(c)]][0] for c in SAMPLE) / len(SAMPLE) / upem
    return cap, adv, hmtx[cmap[0x20]][0] / upem


def stem_width(font):
    """Толщина вертикального штриха заглавной I в долях кегля."""
    from fontTools.pens.boundsPen import BoundsPen
    gs = font.getGlyphSet()
    pen = BoundsPen(gs)
    gs[font.getBestCmap()[ord("I")]].draw(pen)
    return (pen.bounds[2] - pen.bounds[0]) / font["head"].unitsPerEm


def jura_at(path, wght):
    """Jura заданной насыщенности. До 700 — обычный срез переменного шрифта; выше — продление по
    приращениям автора: у Jura ось одна и линейная (одна опорная точка 300 -> 700), поэтому
    точка контура при wght = p300 + (wght-300)/400 * (p700 - p300) и при wght > 700 лежит на той
    же прямой. Кернинг берётся от 700."""
    from fontTools.ttLib import TTFont
    from fontTools.ttLib.tables._g_l_y_f import GlyphCoordinates
    from fontTools.varLib.instancer import instantiateVariableFont
    if wght <= 700:
        return instantiateVariableFont(TTFont(path), {"wght": wght}, updateFontNames=False)
    lo = instantiateVariableFont(TTFont(path), {"wght": 300}, updateFontNames=False)
    hi = instantiateVariableFont(TTFont(path), {"wght": 700}, updateFontNames=False)
    t = (wght - 700) / 400.0
    gh_, gl_ = hi["glyf"], lo["glyf"]
    for gn in hi.getGlyphOrder():
        gh, gl = gh_[gn], gl_[gn]
        if gh.isComposite():
            for ch, cl in zip(gh.components, gl.components):
                ch.x = int(round(ch.x + t * (ch.x - cl.x)))
                ch.y = int(round(ch.y + t * (ch.y - cl.y)))
        elif gh.numberOfContours > 0:
            ph, pl = gh.coordinates, gl.coordinates
            if len(ph) != len(pl):
                raise SystemExit("Jura: у глифа %s разное число точек в срезах" % gn)
            gh.coordinates = GlyphCoordinates([(int(round(xh + t * (xh - xl))), int(round(yh + t * (yh - yl))))
                                               for (xh, yh), (xl, yl) in zip(ph, pl)])
        advh, lsbh = hi["hmtx"][gn]
        advl = lo["hmtx"][gn][0]
        hi["hmtx"][gn] = (int(round(advh + t * (advh - advl))), lsbh)
    for _ in range(4):
        for gn in hi.getGlyphOrder():
            gh_[gn].recalcBounds(gh_)
    return hi


def _scale_layout(obj, sx, sy, seen):
    """Кернинг и привязки: X-величины умножаются на sx, Y — на sy."""
    from fontTools.ttLib.tables import otTables
    if id(obj) in seen:
        return
    seen.add(id(obj))
    if isinstance(obj, otTables.ValueRecord):
        for attr, k in (("XAdvance", sx), ("XPlacement", sx), ("YAdvance", sy), ("YPlacement", sy)):
            if hasattr(obj, attr):
                setattr(obj, attr, int(round(getattr(obj, attr) * k)))
        return
    if isinstance(obj, otTables.Anchor):
        obj.XCoordinate = int(round(obj.XCoordinate * sx))
        obj.YCoordinate = int(round(obj.YCoordinate * sy))
        return
    if isinstance(obj, otTables.CaretValue) and hasattr(obj, "Coordinate"):
        obj.Coordinate = int(round(obj.Coordinate * sx))
        return
    if isinstance(obj, (list, tuple)):
        for x in obj:
            _scale_layout(x, sx, sy, seen)
        return
    if isinstance(obj, dict):
        for x in obj.values():
            _scale_layout(x, sx, sy, seen)
        return
    if hasattr(obj, "__dict__") and type(obj).__module__.startswith("fontTools"):
        for x in vars(obj).values():
            _scale_layout(x, sx, sy, seen)


def _shift_anchors(gpos, spacing, half):
    """Прибавка между буквами сдвигает рисунок знака на half вправо — туда же сдвигаются привязки
    диакритики у букв (у самих знаков диакритики ширины нет, они не сдвигаются)."""
    done = set()

    def shift(anchor):
        if anchor is not None and id(anchor) not in done:
            done.add(id(anchor))
            anchor.XCoordinate += half

    for lk in gpos.LookupList.Lookup:
        for st in lk.SubTable:
            if lk.LookupType == 9:
                st = st.ExtSubTable
            t = st.LookupType if hasattr(st, "LookupType") else lk.LookupType
            if t == 4:
                for g, rec in zip(st.BaseCoverage.glyphs, st.BaseArray.BaseRecord):
                    if spacing.get(g):
                        for a in rec.BaseAnchor:
                            shift(a)
            elif t == 5:
                for g, att in zip(st.LigatureCoverage.glyphs, st.LigatureArray.LigatureAttach):
                    if spacing.get(g):
                        for cr in att.ComponentRecord:
                            for a in cr.LigatureAnchor:
                                shift(a)
            elif t == 3:
                for g, rec in zip(st.Coverage.glyphs, st.EntryExitRecord):
                    if spacing.get(g):
                        shift(rec.EntryAnchor)
                        shift(rec.ExitAnchor)
            if t in (4, 5):
                for g, rec in zip(st.MarkCoverage.glyphs, st.MarkArray.MarkRecord):
                    if spacing.get(g):
                        shift(rec.MarkAnchor)
            if t == 6:
                for g, rec in zip(st.Mark1Coverage.glyphs, st.Mark1Array.MarkRecord):
                    if spacing.get(g):
                        shift(rec.MarkAnchor)
                for g, rec in zip(st.Mark2Coverage.glyphs, st.Mark2Array.Mark2Record):
                    if spacing.get(g):
                        for a in rec.Mark2Anchor:
                            shift(a)


def solve_sx(font, sy, track_em, size=1.0):
    """Ширина рисунка буквы (sx) такая, чтобы с прибавкой между буквами и пробелом как у Sony
    Sketch средняя ширина знака на образце совпала с Sony Sketch (при size ≠ 1 — с ним же,
    увеличенным в size раз)."""
    upem = font["head"].unitsPerEm
    cmap = font.getBestCmap()
    hmtx = font["hmtx"]
    n = len(SAMPLE)
    n_sp = sum(1 for c in SAMPLE if ord(c) in SPACE_CODES)
    body = sum(hmtx[cmap[ord(c)]][0] for c in SAMPLE if ord(c) not in SPACE_CODES) / upem
    return (SONY_ADV * size * n - (n - n_sp) * track_em - n_sp * SONY_SPACE * size) / body


def transform(font, sx, sy, track_em, space_em=SONY_SPACE):
    from fontTools.ttLib.tables import ttProgram
    glyf, hmtx = font["glyf"], font["hmtx"]
    upem = font["head"].unitsPerEm
    order = font.getGlyphOrder()
    track = int(round(track_em * upem))
    half = track // 2
    spaces = {font.getBestCmap().get(u) for u in SPACE_CODES} - {None}
    spacing = {gn: (hmtx[gn][0] > 0 and gn not in spaces) for gn in order}
    for gn in order:
        g = glyf[gn]
        if g.isComposite():
            for c in g.components:
                #  составная буква: её буквенные части сдвинуты внутри себя, диакритика — нет
                extra = half if (spacing[gn] and not spacing.get(c.glyphName)) else 0
                c.x = int(round(c.x * sx)) + extra
                c.y = int(round(c.y * sy))
        elif g.numberOfContours > 0:
            g.coordinates.scale((sx, sy))
            if spacing[gn]:
                g.coordinates.translate((half, 0))
            g.coordinates.toInt()
        if hasattr(g, "program"):
            g.program = ttProgram.Program()
            g.program.fromBytecode(b"")
    for _ in range(4):                       # составные из составных — до устойчивости
        for gn in order:
            glyf[gn].recalcBounds(glyf)
    space_units = int(round(space_em * upem))
    for gn in order:
        adv, lsb = hmtx[gn]
        g = glyf[gn]
        if gn in spaces:
            new_adv = space_units
        else:
            new_adv = int(round(adv * sx)) + (track if spacing[gn] else 0)
        hmtx[gn] = (new_adv, g.xMin if getattr(g, "numberOfContours", 0) != 0 else int(round(lsb * sx)))
    if "kern" in font:
        for st in font["kern"].kernTables:
            st.kernTable = {k: int(round(v * sx)) for k, v in st.kernTable.items()}
    for tag in ("GPOS", "GDEF"):
        if tag in font:
            _scale_layout(font[tag].table, sx, sy, set())
    if "GPOS" in font and half:
        _shift_anchors(font["GPOS"].table, spacing, half)
    os2 = font["OS/2"]
    for attr in ("sxHeight", "sCapHeight", "yStrikeoutSize", "yStrikeoutPosition",
                 "ySubscriptYSize", "ySubscriptYOffset", "ySuperscriptYSize", "ySuperscriptYOffset"):
        if hasattr(os2, attr):
            setattr(os2, attr, int(round(getattr(os2, attr) * sy)))
    for attr in ("ySubscriptXSize", "ySubscriptXOffset", "ySuperscriptXSize", "ySuperscriptXOffset"):
        if hasattr(os2, attr):
            setattr(os2, attr, int(round(getattr(os2, attr) * sx)))
    post = font["post"]
    post.underlinePosition = int(round(post.underlinePosition * sy))
    post.underlineThickness = int(round(post.underlineThickness * sy))
    #  Настройка под пиксели после масштаба неверна — убирается; новую делает ttfautohint.
    for tag in ("fpgm", "prep", "cvt ", "cvar", "hdmx", "LTSH", "VDMX", "DSIG", "STAT", "gasp"):
        if tag in font:
            del font[tag]
    os2.recalcAvgCharWidth(font)


def rename(font, family, style, notice_first_line, version=None):
    version = version or VERSION
    name = font["name"]
    bold = style == "Bold"
    ps = family.replace(" ", "") + "-" + style
    full = family + ("" if style == "Regular" else " " + style)
    first = notice_first_line.strip()
    copyright_ = (first + ("" if first.endswith(".") else ".") + " Modified 2026 by 3DIWELL: rescaled, "
                  "widened, respaced, re-hinted with ttfautohint; renamed as required by the SIL Open Font License 1.1.")
    values = {0: copyright_, 1: family, 2: style, 3: "%s;%s;3DIWELL" % (version, ps), 4: full,
              5: "Version %s" % version, 6: ps,
              13: "This Font Software is licensed under the SIL Open Font License, Version 1.1. "
                  "This license is available with a FAQ at: https://openfontlicense.org",
              14: "https://openfontlicense.org"}
    name.names = [n for n in name.names if n.nameID not in values and n.nameID not in (16, 17, 21, 22, 25)
                  and n.nameID < 256]
    for nid, v in values.items():
        name.setName(v, nid, 3, 1, 0x409)
        name.setName(v, nid, 1, 0, 0)
    os2 = font["OS/2"]
    os2.usWeightClass = 700 if bold else 400
    os2.fsSelection = (os2.fsSelection & ~0b1100001) | (0b100000 if bold else 0b1000000)
    font["head"].macStyle = 1 if bold else 0


def autohint(font, options=None):
    """Подгонка под пиксели: сохранить TTF, прогнать ttfautohint, прочитать обратно."""
    import ttfautohint
    from fontTools.ttLib import TTFont
    buf = io.BytesIO()
    font.flavor = None
    font.save(buf)
    return TTFont(io.BytesIO(ttfautohint.ttfautohint(in_buffer=buf.getvalue(), **(options or AUTOHINT))))


def true_x_height(font):
    """Настоящая высота строчной x в единицах шрифта (по контуру, а не по записи в OS/2)."""
    from fontTools.pens.boundsPen import BoundsPen
    gs = font.getGlyphSet()
    pen = BoundsPen(gs)
    gs[font.getBestCmap()[ord("x")]].draw(pen)
    return pen.bounds[3]


def build(src, out, faces=None, hint=True, autohint_options=None):
    from fontTools.ttLib import TTFont
    from fontTools.misc.timeTools import timestampFromString
    os.makedirs(out, exist_ok=True)
    report = []
    family_xh = {}
    for f in (faces or FACES):
        path = os.path.join(src, f["src"])
        font = jura_at(path, f["wght"]) if f.get("wght") is not None else TTFont(path)
        size, track_em = f.get("size", 1.0), f.get("track", TRACK_EM)
        cap, _, _ = glyph_stats(font)
        sy = SONY_CAP * size / cap
        sx = solve_sx(font, sy, track_em, size)
        transform(font, sx, sy, track_em, SONY_SPACE * size)
        family, style, dst, notice = f["family"], f["style"], f["dst"], f["notice"]
        #  Запись высоты строчных (OS/2 sxHeight) — по настоящему контуру обычного начертания, одна на
        #  семью: по ней браузер пересчитывает «Размер текста» (font-size-adjust). У Jura запись шла от
        #  тонкого начертания и у жирного расходилась на 3 % — жирный текст увеличивался сильнее.
        family_xh.setdefault(family, true_x_height(font) / font["head"].unitsPerEm)
        font["OS/2"].sxHeight = int(round(family_xh[family] * font["head"].unitsPerEm))
        first = open(os.path.join(src, notice), encoding="utf-8").readline()
        rename(font, family, style, first, f.get("version"))
        if hint:
            opts = dict(autohint_options or AUTOHINT)
            opts.update(f.get("hint") or {})
            font = autohint(font, opts)
        #  Одинаковые исходники дают одинаковый файл: время сборки в шрифт не пишется.
        font.recalcTimestamp = False
        font["head"].created = font["head"].modified = timestampFromString(BUILD_STAMP)
        font.flavor = "woff2"
        p = os.path.join(out, dst)
        font.save(p)
        f2 = TTFont(p)
        cap2, adv2, sp2 = glyph_stats(f2)
        report.append((dst, round(sx / sy, 3), round(cap2, 4), round(adv2, 4), round(sp2, 4), round(stem_width(f2), 4),
                       "fpgm" in f2))
    report = [r for r in report]
    for notice, target in (("Jura-OFL.txt", "OFL-Jura.txt"), ("Play-OFL.txt", "OFL-Play.txt")):
        with open(os.path.join(src, notice), "rb") as f, open(os.path.join(out, target), "wb") as g:
            g.write(f.read())
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--src", required=True, help="папка исходных файлов (вне проекта)")
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--download", action="store_true", help="скачать исходники с Google Fonts по закреплённым коммитам")
    ap.add_argument("--no-hint", action="store_true", help="без подгонки под пиксели (только для сравнения)")
    a = ap.parse_args(argv)
    if a.download:
        download(a.src)
    bad = check_sources(a.src)
    if bad:
        print("ОШИБКА: исходники не совпадают с закреплёнными (SHA-256): %s" % ", ".join(bad))
        return 2
    for dst, widen, cap, adv, sp, stem, hinted in build(a.src, a.out, hint=not a.no_hint):
        print("%-30s расширение %.3f | заглавная %.4f (Sony %.4f) | ширина знака %.4f (Sony %.4f) | пробел %.4f "
              "(Sony %.4f) | штрих I %.4f (Sony 0.0972) | подгонка %s"
              % (dst, widen, cap, SONY_CAP, adv, SONY_ADV, sp, SONY_SPACE, stem, "да" if hinted else "нет"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
