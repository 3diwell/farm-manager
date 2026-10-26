# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Запись того, что принтеры рассказывают о себе в сеть (пункт карты R-092).

ЗАЧЕМ ЭТО ВАМ. Программа умеет находить принтеры по их собственным объявлениям, но проверить
её на настоящих принтерах разработка не может — принтеров у неё нет. Этот инструмент садится
слушать сеть и записывает КАЖДЫЙ пакет, который принтеры прислали, вместе со временем, портом
и адресом отправителя. По такому дампу видно, что именно объявляют ВАШИ принтеры, и опознание
можно доделать точно, а не по догадкам.

ЧТО ОН ДЕЛАЕТ И ЧЕГО НЕ ДЕЛАЕТ:
  * по умолчанию НЕ ОТПРАВЛЯЕТ В СЕТЬ НИ ОДНОГО БАЙТА — только слушает;
  * ничего не запускает и не меняет на принтерах;
  * сеть не перебирает и порты не сканирует;
  * с ключом --say-hello один раз посылает обычный вопрос «представься» — ровно те же
    стандартные запросы, что постоянно шлёт сам Windows. Ничего вендорского.

КАК ЗАПУСТИТЬ (проще всего — двойным щелчком по printer_net_capture.bat рядом):

    python tools/printer_net_capture.py                 слушать 10 минут
    python tools/printer_net_capture.py --seconds 120   слушать 2 минуты
    python tools/printer_net_capture.py --say-hello     плюс один вопрос «представься»
    python tools/printer_net_capture.py --summarize <папка>/printer_net_20260908_141500.jsonl

ЧТО ПОЛУЧИТСЯ. Два файла во временной папке Windows, подпапка 3DIWELL_capture (путь печатается
при запуске): сам дамп (.jsonl, по строке на пакет, с сырыми байтами)
и человеческая сводка (.txt). Пришлите оба — по ним видно, чего программе не хватает.
"""
import argparse
import io
import json
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from app import printer_discovery as pd   # noqa: E402


def human(dump_path):
    """Человеческая сводка по уже снятому дампу: кто, сколько, на каких портах и что похоже
    на принтер. Ничего не слушает — только читает файл."""
    by_src, by_port, guesses, total = {}, {}, {}, 0
    first_ts = last_ts = ""
    for line in io.open(dump_path, encoding="utf-8", errors="replace"):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue
        total += 1
        first_ts = first_ts or rec.get("ts", "")
        last_ts = rec.get("ts", "") or last_ts
        src = rec.get("src_ip") or "?"
        by_src[src] = by_src.get(src, 0) + 1
        pt = str(rec.get("listen_port"))
        by_port[pt] = by_port.get(pt, 0) + 1
        raw = bytes.fromhex(rec.get("hex") or "")
        who = ""
        d = pd.parse_bambu_notify(raw, src)
        if d:
            who = "Bambu %s (%s), серийный %s" % (d.get("model") or d.get("model_code") or "?",
                                                  d.get("name") or "", d.get("serial") or "?")
        if not who:
            f = pd.parse_flashforge_packet(raw, src)
            if f:
                who = "FlashForge %s (%s), серийный %s" % (f.get("model") or f.get("model_code") or "?",
                                                           f.get("name") or "", f.get("serial") or "нет в пакете")
        if not who and str(rec.get("listen_port")) == "5353":
            devs = pd.devices_from_mdns(pd.parse_mdns_message(raw), src)
            if devs:
                who = "mDNS: " + ", ".join(sorted({x.get("service") or x.get("family") for x in devs}))
        if who:
            guesses.setdefault(src, set()).add(who)

    out = []
    out.append("СВОДКА ПО ЗАПИСИ СЕТЕВЫХ ОБЪЯВЛЕНИЙ")
    out.append("файл: %s" % dump_path)
    out.append("пакетов: %d, с %s по %s" % (total, first_ts or "?", last_ts or "?"))
    out.append("")
    out.append("Кто присылал (адрес: число пакетов)")
    for src, n in sorted(by_src.items(), key=lambda kv: -kv[1]):
        out.append("  %-16s %5d" % (src, n))
    out.append("")
    out.append("На какие порты приходило")
    for pt, n in sorted(by_port.items(), key=lambda kv: -kv[1]):
        out.append("  порт %-6s %5d" % (pt, n))
    out.append("")
    if guesses:
        out.append("Что удалось опознать")
        for src, whos in sorted(guesses.items()):
            for w in sorted(whos):
                out.append("  %-16s %s" % (src, w))
    else:
        out.append("Опознать не удалось ничего. Это и есть самое ценное: значит, ваши принтеры")
        out.append("объявляются иначе, чем программа ожидает, и дамп нужен разработке целиком.")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description="Запись сетевых объявлений принтеров (R-092)")
    ap.add_argument("--seconds", type=int, default=600, help="сколько слушать, секунд (0 — до Ctrl+C)")
    ap.add_argument("--out", default="", help="папка для файлов (по умолчанию %%TEMP%%\\3DIWELL_capture; в дампах серийные номера и MAC-адреса принтеров — не кладите их в проект и в облако)")
    ap.add_argument("--say-hello", action="store_true",
                    help="один раз послать стандартный вопрос «представься» (по умолчанию НЕ шлём)")
    ap.add_argument("--summarize", default="", help="только пересказать уже снятый дамп")
    a = ap.parse_args()

    if a.summarize:
        if not os.path.isfile(a.summarize):
            print("Файла нет:", a.summarize)
            return 2
        print(human(a.summarize))
        return 0

    #  16.10.2026 (аудит secrets-history-12): по умолчанию — временная папка Windows, а не logs проекта:
    #  в дампах серийные номера и MAC-адреса принтеров фермы.
    out_dir = a.out or os.path.join(os.environ.get("TEMP") or os.environ.get("TMP") or ROOT, "3DIWELL_capture")
    os.makedirs(out_dir, exist_ok=True)
    print("Слушаю сеть. Ничего в неё не отправляю." if not a.say_hello
          else "Слушаю сеть и один раз спрашиваю «представься».")
    print("Порты:", ", ".join(str(p) for p in pd.CAPTURE_PORTS))
    print("Папка:", out_dir)
    print("Остановить можно в любой момент — Ctrl+C.")
    print()

    sess = pd.NetCaptureSession()
    ok, why = sess.start(out_dir, a.seconds, (), a.say_hello)
    if not ok:
        print("Начать не удалось:", why)
        return 1
    t0 = time.monotonic()
    try:
        while True:
            snap = sess.snapshot()
            if not snap.get("active"):
                break
            el = int(time.monotonic() - t0)
            print("\r  %3d с · пакетов: %-6d · адресов: %-3d" %
                  (el, snap.get("packets", 0), len(snap.get("sources") or {})), end="", flush=True)
            time.sleep(1.0)
    except KeyboardInterrupt:
        sess.stop()
        time.sleep(1.0)
    print()
    snap = sess.snapshot()
    path = snap.get("path") or ""
    if snap.get("error"):
        print("Во время записи случилась ошибка:", snap["error"])
    if not path or not os.path.isfile(path):
        print("Файл записи не создан.")
        return 1
    txt = human(path)
    spath = path.replace(".jsonl", "_summary.txt")
    io.open(spath, "w", encoding="utf-8", newline="\n").write(txt + "\n")
    print()
    print(txt)
    print()
    print("Готово. Пришлите разработке эти два файла:")
    print("  ", path)
    print("  ", spath)
    if not snap.get("packets"):
        print()
        print("Ноль пакетов — это тоже результат. Обычно причина одна из трёх: принтеры выключены,")
        print("компьютер и принтеры в разных сетях, либо брандмауэр Windows не пропускает входящие")
        print("объявления к python.exe. Проверять программу по этому дампу нельзя.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
