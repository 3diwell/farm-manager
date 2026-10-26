# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
#  Alpha 2.838/2.839 — READ-ONLY разведка контракта подготовки печати Klipper.
#
#  Alpha 2.839: это ТОНКАЯ ОБЁРТКА. Вся логика — сбор, разбор макросов, редакция и
#  самопроверка — живёт в production-модуле `app/klipper_contract_probe.py`, тем же
#  ядром пользуется встроенная кнопка «Собрать диагностический отчёт» в Farm Manager.
#  Второй реализации протокола в проекте нет: разойтись им негде.
#
#  КОГДА НУЖЕН ЭТОТ CLI. Только разработчику, у которого есть терминал. Владельцу
#  принтера он не нужен вовсе — тот нажимает кнопку в программе и сохраняет файл.
#
#  ГАРАНТИИ БЕЗОПАСНОСТИ (проверяются тестами и mutation proof):
#   * только HTTP GET по неизменяемому allowlist ядра — ни одного POST;
#   * `/printer/gcode/script` не вызывается никогда, команды принтеру не отправляются;
#   * печать не запускается и не останавливается, конфигурация не меняется;
#   * отчёт обезличен: ни адресов, ни токенов, ни серийников, ни путей, ни полного
#     printer.cfg — и это проверяется самопроверкой перед выдачей.
#
#  Запуск:
#     python tools/klipper_probe.py <host> [--port 7125] [--json out.json] [--gcode файл]
# ============================================================================
import argparse
import io
import json
import os
import sys
import time
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app import klipper_contract_probe as K  # noqa: E402

READ_ONLY_PATHS = K.ALLOWED_PATHS      # единственный источник истины — ядро


def make_getter(host, port, timeout=8.0):
    """Колбэк чтения для ядра. ТОЛЬКО GET, без тела запроса, только allowlist."""
    def _get(path):
        if not K.is_allowed(path):
            return (None, "not_allowed")
        req = urllib.request.Request("http://%s:%s%s" % (host, port, path), method="GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return (json.loads(r.read().decode("utf-8", "replace")), "")
        except Exception as e:
            return (None, type(e).__name__)
    return _get


def main():
    ap = argparse.ArgumentParser(description="Read-only слепок контракта подготовки Klipper")
    ap.add_argument("host", help="адрес принтера (в отчёт не попадает)")
    ap.add_argument("--port", type=int, default=7125)
    ap.add_argument("--json", default="", help="файл обезличенного слепка")
    ap.add_argument("--gcode", default="", help="локальный G-code: разобрать ТОЛЬКО начало")
    args = ap.parse_args()

    print("=== READ-ONLY разведка Klipper (команд принтеру НЕ отправляется) ===")
    print("Разрешённых эндпоинтов: %d. Адрес в отчёт не попадает." % len(READ_ONLY_PATHS))
    print()

    raw = K.collect(make_getter(args.host, args.port))
    for path in READ_ONLY_PATHS:
        st = raw.get(path) or {}
        print("  GET %-56s %s" % (path, "ok" if st.get("ok") else ("ОШИБКА: " + st.get("error", "?"))))
    print()

    head = ""
    if args.gcode and os.path.isfile(args.gcode):
        head = io.open(args.gcode, "rb").read(65536).decode("utf-8", "replace")

    secrets = [args.host, str(args.port), os.path.expanduser("~")]
    report = K.build_report(raw, app_version="cli", model_label="klipper",
                            generated_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
                            secrets=secrets, gcode_head=head)
    leaks = K.find_leaks(json.dumps(report, ensure_ascii=False), secrets)
    if leaks:
        print("ОТЧЁТ НЕ ВЫДАН: самопроверка нашла следы %s" % ", ".join(leaks))
        return 2

    s = K.summarize(report)
    print("Moonraker: %s | Klipper: %s" % (s["moonraker_version"] or "?", s["klipper_version"] or "?"))
    print("Стартовый макрос:            %s" % (s["start_macro"] or "не найден"))
    print("  его параметры:             %s" % (", ".join(s["start_macro_params"]) or "—"))
    print("  делает bed mesh сам:       %s" % ("ДА" if s["start_macro_does_bed_mesh"] else "нет"))
    print("  паркует оси сам:           %s" % ("ДА" if s["start_macro_homes"] else "нет"))
    print("BED_MESH_CALIBRATE есть:     %s" % ("ДА" if s["bed_mesh_command_exists"] else "нет"))
    print("  переопределена макросом:   %s" % ("ДА" if s["bed_mesh_overridden"] else "нет"))
    print("Секций собрано/недоступно:   %d / %d" % (len(s["sections_complete"]), len(s["sections_unavailable"])))
    print()
    print("Открытые вопросы:")
    for q in report.get("unresolved_questions") or ["—"]:
        print("  · %s" % q)
    print()

    if args.json:
        io.open(args.json, "w", encoding="utf-8", newline="\n").write(
            json.dumps(report, ensure_ascii=False, indent=1))
        print("Обезличенный слепок записан: %s" % args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
