# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Шаблоны сообщений: как событие фермы превращается в текст, который человек читает на телефоне.

Заказ владельца 12.09.2026: принтер — в заголовке, имя файла печати — отдельной строкой и
выделено, статус — в конце со своим значком; и чтобы текст можно было настроить самому.

УСТРОЙСТВО. Шаблон — обычный текст с подстановками в фигурных скобках. Программа подставляет
данные события, а строку, в которой ВСЕ подстановки оказались пустыми, выбрасывает целиком:
так «📄 «{file}»» исчезает у событий без файла, а «{icon} {status} · {duration}» не оставляет
висящей точки, когда длительности нет. Неизвестная подстановка остаётся как есть — человек
увидит опечатку в предпросмотре, а не пустоту в сообщении.

Разметки (жирный, курсив) нет намеренно: у каждой площадки свои правила экранирования, а
сообщение должно дойти, а не упасть. Выделение — значками и кавычками, они работают везде.

Подстановки: {printer} имя принтера · {file} файл печати · {status} что случилось ·
{icon} значок события · {duration} длительность · {percent} выполнено · {code} код ·
{detail} расшифровка уведомления · {where} узел и серьёзность · {minutes} минут без связи ·
{time} время события.
"""
import re
import time as _time

from . import models as M

TEMPLATE_MAX = 600
OFFLINE_AFTER_S = M.OFFLINE_AFTER_S

VARS = ("printer", "file", "status", "icon", "duration", "percent", "code", "detail", "where", "minutes", "time")

VAR_HINT = {
    "printer": {"ru": "имя принтера", "en": "printer name"},
    "file": {"ru": "файл печати (g-code)", "en": "print file (g-code)"},
    "status": {"ru": "что случилось, словами", "en": "what happened, in words"},
    "icon": {"ru": "значок события", "en": "event icon"},
    "duration": {"ru": "длительность печати", "en": "print duration"},
    "percent": {"ru": "сколько выполнено", "en": "how much was done"},
    "code": {"ru": "код ошибки или уведомления", "en": "error or notice code"},
    "detail": {"ru": "расшифровка уведомления", "en": "notice text"},
    "where": {"ru": "узел принтера и серьёзность", "en": "printer module and severity"},
    "minutes": {"ru": "минут без связи", "en": "minutes offline"},
    "time": {"ru": "время события", "en": "event time"},
}

#  Значки событий: одинаковые на всех площадках (простые эмодзи, а не разметка).
ICONS = {
    M.EVENT_PRINT_FINISHED: "✅", M.EVENT_PRINT_FAILED: "❌", M.EVENT_PRINT_CANCELLED: "⏹",
    M.EVENT_PRINTER_ERROR: "⚠️", M.EVENT_PRINTER_NOTICE: "🔔", M.EVENT_PRINTER_OFFLINE: "📴",
}
ICON_ONLINE = "📶"

STATUS = {
    M.EVENT_PRINT_FINISHED: {"ru": "Печать завершена", "en": "Print finished"},
    M.EVENT_PRINT_FAILED: {"ru": "Печать прервана сбоем", "en": "Print failed"},
    M.EVENT_PRINT_CANCELLED: {"ru": "Печать остановлена", "en": "Print cancelled"},
    M.EVENT_PRINTER_ERROR: {"ru": "Ошибка принтера", "en": "Printer error"},
    M.EVENT_PRINTER_NOTICE: {"ru": "Уведомление на экране принтера", "en": "Notice on the printer screen"},
}
STATUS_OFFLINE = {"ru": "Нет связи уже {minutes} мин", "en": "No connection for {minutes} min"}
STATUS_ONLINE = {"ru": "Связь восстановлена", "en": "Back online"}
NOTICE_ON_SCREEN = {"ru": "Текст — на экране принтера", "en": "The text is on the printer screen"}

#  Шаблоны по умолчанию — ровно то, что просил владелец: принтер сверху, файл отдельной
#  строкой в кавычках со значком, статус последним со своим значком.
DEFAULTS = {
    M.EVENT_PRINT_FINISHED: "🖨 {printer}\n📄 «{file}»\n{icon} {status} · {duration}",
    M.EVENT_PRINT_FAILED: "🖨 {printer}\n📄 «{file}»\n{icon} {status} · {percent}",
    M.EVENT_PRINT_CANCELLED: "🖨 {printer}\n📄 «{file}»\n{icon} {status} · {percent}",
    M.EVENT_PRINTER_ERROR: "🖨 {printer}\n{icon} {status}\n⚙ {code}",
    M.EVENT_PRINTER_NOTICE: "🖨 {printer}\n{icon} {status}\n{detail}\n{where}",
    M.EVENT_PRINTER_OFFLINE: "🖨 {printer}\n{icon} {status}",
}

SEV = {"fatal": {"ru": "критично", "en": "fatal"}, "serious": {"ru": "серьёзно", "en": "serious"},
       "common": {"ru": "обычное", "en": "common"}, "info": {"ru": "к сведению", "en": "info"}}
MOD = {"mc": {"ru": "плата движения", "en": "motion board"},
       "mainboard": {"ru": "материнская плата", "en": "mainboard"},
       "ams": {"ru": "AMS", "en": "AMS"}, "toolhead": {"ru": "печатающая голова", "en": "toolhead"},
       "xcam": {"ru": "камера и лидар", "en": "camera and lidar"}}

_PH = re.compile(r"\{([a-z_]+)\}")
_SEP = " · "


def fmt_duration(sec, ru=True):
    try:
        s = int(sec)
    except Exception:
        return ""
    if s < 0:
        return ""
    h, m = s // 3600, (s % 3600) // 60
    if ru:
        return ("%d ч %d мин" % (h, m)) if h else ("%d мин" % m)
    return ("%dh %dm" % (h, m)) if h else ("%dm" % m)


def template_for(kind, templates=None):
    """Шаблон события: свой из настроек, если задан, иначе — по умолчанию."""
    custom = (templates or {}).get(kind) if isinstance(templates, dict) else None
    custom = str(custom or "").strip()
    return custom or DEFAULTS.get(kind, "🖨 {printer}\n{icon} {status}")


def _tidy(line):
    parts = [p.strip() for p in line.split(_SEP)]
    line = _SEP.join(p for p in parts if p)
    line = line.replace("«»", "").replace("()", "").replace("[]", "")
    return re.sub(r"[ \t]{2,}", " ", line).strip()


def render(template, ctx):
    """Подставить данные в шаблон. Строка, где все подстановки пусты, выбрасывается;
    неизвестная подстановка остаётся как есть."""
    ctx = ctx or {}
    out = []
    for raw in str(template or "").splitlines():
        names = _PH.findall(raw)
        known = [str(ctx.get(n) or "") for n in names if n in ctx]
        if known and all(v == "" for v in known):
            continue
        line = _PH.sub(lambda m: str(ctx.get(m.group(1)) or "") if m.group(1) in ctx else m.group(0), raw)
        line = _tidy(line)
        if line:
            out.append(line)
    return "\n".join(out).strip()


def build_context(ev, lang, hms_text=None, now=None):
    """Событие фермы -> значения подстановок."""
    ru = lang != "en"
    L = "ru" if ru else "en"
    ev = ev or {}
    kind = ev.get("kind")
    ctx = {v: "" for v in VARS}
    ctx["printer"] = str(ev.get("printer_name") or ev.get("printer_id") or "?")
    ctx["file"] = str(ev.get("file") or "")
    ctx["time"] = _time.strftime("%H:%M", _time.localtime(now)) if now is not None else _time.strftime("%H:%M")
    pct = ev.get("percent")
    try:
        ctx["percent"] = ("%d%%" % int(round(float(pct)))) if pct is not None else ""
    except Exception:
        ctx["percent"] = ""
    ctx["duration"] = fmt_duration(ev.get("elapsed_s"), ru) if kind == M.EVENT_PRINT_FINISHED else ""
    code = str(ev.get("code") or "")
    ctx["code"] = code
    ctx["icon"] = ICONS.get(kind, "🔔")
    ctx["status"] = (STATUS.get(kind) or {}).get(L, "")
    if kind == M.EVENT_PRINTER_NOTICE:
        known = (hms_text or {}).get(code) if code else None
        ctx["detail"] = (known.get(L) or known.get("en") or code) if isinstance(known, dict) else NOTICE_ON_SCREEN[L]
        parts = []
        mod = MOD.get(str(ev.get("module") or ""))
        sev = SEV.get(str(ev.get("severity") or ""))
        if mod:
            parts.append(mod[L])
        if sev:
            parts.append(sev[L])
        if code:
            parts.append(code)
        ctx["where"] = _SEP.join(parts)
    elif kind == M.EVENT_PRINTER_OFFLINE:
        if ev.get("online"):
            ctx["icon"] = ICON_ONLINE
            ctx["status"] = STATUS_ONLINE[L]
        else:
            mins = ev.get("minutes")
            try:
                mins = int(mins)
            except Exception:
                mins = OFFLINE_AFTER_S // 60
            ctx["minutes"] = str(mins)
            ctx["status"] = STATUS_OFFLINE[L].replace("{minutes}", str(mins))
    elif kind not in STATUS:
        ctx["status"] = str(kind or "")
    return ctx


def render_event(ev, lang, hms_text=None, templates=None, now=None):
    ev = ev or {}
    return render(template_for(ev.get("kind"), templates), build_context(ev, lang, hms_text, now))


def sample_event(kind, lang):
    """Событие-образец для предпросмотра в настройках."""
    ru = lang != "en"
    base = {"kind": kind, "printer_name": "H2D_01", "file": "bracket_v3.gcode"}
    if kind == M.EVENT_PRINT_FINISHED:
        base["elapsed_s"] = 2 * 3600 + 15 * 60
    elif kind in (M.EVENT_PRINT_FAILED, M.EVENT_PRINT_CANCELLED):
        base["percent"] = 43
    elif kind == M.EVENT_PRINTER_ERROR:
        base.update({"code": "0300-8100-0001-0002", "file": ""})
    elif kind == M.EVENT_PRINTER_NOTICE:
        base.update({"code": "0700-2000-0002-0001", "severity": "serious", "module": "ams", "file": ""})
    elif kind == M.EVENT_PRINTER_OFFLINE:
        base.update({"minutes": 3, "file": ""})
    return base


def sample_context(kind, lang):
    ctx = build_context(sample_event(kind, lang), lang, hms_text={
        "0700-2000-0002-0001": {"ru": "Филамент в AMS закончился — вставьте новую катушку",
                                "en": "AMS filament ran out — load a new spool"}})
    ctx["time"] = "14:05"
    return ctx


def bundle(lang, templates=None):
    """Для окна настроек: шаблоны по умолчанию, список подстановок с подсказками, образцы
    данных для живого предпросмотра и готовый предпросмотр с текущими шаблонами."""
    L = "ru" if lang != "en" else "en"
    out = {"defaults": dict(DEFAULTS), "vars": list(VARS),
           "hints": {v: VAR_HINT[v][L] for v in VARS}, "sample": {}, "preview": {}}
    for k in M.EVENT_KEYS:
        ctx = sample_context(k, L)
        out["sample"][k] = ctx
        out["preview"][k] = render(template_for(k, templates), ctx)
    return out
