# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.836 — MUTATION PROOF каркаса и верха настроек.

ЗАЧЕМ. Alpha 2.835 имела зелёный release gate и при этом провалила приёмку по скриншоту
владельца: тесты мерили КОРОБКУ верхнего бара, а рисовал он ниже коробки. Значит зелёный сам по
себе ничего не значит — надо доказать, что новые проверки РЕАЛЬНО ловят возврат каждого дефекта.

КАК. Двадцать одна намеренная порча продуктовых файлов и самого набора. После каждой порчи
целевой тест ОБЯЗАН покраснеть, причём покраснеть ИМЕННО ожидаемой проверкой (проверяется имя —
иначе «покраснел хоть чем-то» скрыл бы, что нужная проверка не работает). Затем файл
восстанавливается ПОБАЙТОВО и сверяется по SHA-256.

БЕЗОПАСНОСТЬ. Правятся только web/app.css, web/app.js, app/project_orchestrator.py и файлы
набора в tools/. Рабочая БД, DATA_DIR, config и production-рантайм не трогаются; принтерам
ничего не отправляется. Порчи откатываются даже при аварии (finally).

Запуск:  python tools/test_shell_header_mutation_proof.py
Переменные: FM_MUT_ONLY=1,5,9 — прогнать только выбранные номера (отладка).
"""
import hashlib
import io
import os
import re
import shutil
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Alpha 2.841: наборы mutation proof портят ОДНИ И ТЕ ЖЕ файлы репозитория.
# Параллельный запуск двух наборов уже приводил к тому, что откат одного затирал
# откат другого и в дереве оставалась чужая мутация. Замок сериализует прогоны;
# не дождались — mutation_lock_busy и КРАСНЫЙ выход, а не тихая правка файлов.
sys.path.insert(0, os.path.join(REPO, "tools"))
from _mutation_lock import acquire_or_die, guard_files  # noqa: E402
# Alpha 2.841: машиночитаемый итог набора — гейт считает нули напрямую, а не разбирает прозу.
from _mutation_report import build as _mut_build, emit as _mut_emit  # noqa: E402
acquire_or_die('test_shell_header_mutation_proof')

CSS = "web/app.css"
JS = "web/app.js"
ORCH = "app/project_orchestrator.py"
TEST = "tools/test_app_shell_and_settings_header.py"
DIAG = "tools/test_diagnostics_toolbar_responsive.py"

SENTINEL = "SHELL_HEADER_MUTATION_SENTINEL_2_836"

# (номер, описание, [(файл, что, на что)], какой тест гонять, режим, ожидаемая проверка)
MUTATIONS = [
    (1, "строка бара снова короче того, что бар рисует (возврат корня дефекта 2.835)",
     [(CSS, "body .fm-style-migrated.fm-header-shell-v270{ height:var(--fm-header-h); }",
       "body .fm-style-migrated.fm-header-shell-v270{ height:2.695rem; }")],
     TEST, "shell", "22."),
    (2, "нарисованный бар выше своей строки на 12px — наложение на колонку принтеров",
     [(CSS, "body .fm-style-migrated.fm-header-desktop-v270{ height:var(--fm-header-h); }",
       "body .fm-style-migrated.fm-header-desktop-v270{ height:calc(var(--fm-header-h) + 12px); }")],
     TEST, "shell", "23."),
    (3, "нарисованный бар выше своей строки на 30px — наложение на рабочий экран",
     [(CSS, "body .fm-style-migrated.fm-header-desktop-v270{ height:var(--fm-header-h); }",
       "body .fm-style-migrated.fm-header-desktop-v270{ height:calc(var(--fm-header-h) + 30px); }")],
     TEST, "shell", "24."),
    (4, "зазор между баром и основной областью убран",
     [(CSS, "@@APPEND@@", "\r\nhtml.m-ui .app-header{ margin-bottom:0 !important; }\r\n")],
     TEST, "shell", "26."),
    (5, "кадр приложения снят — корню снова есть что прокручивать",
     [(CSS, "@@APPEND@@", "\r\nhtml.m-ui #app{ position:static !important; }\r\n")],
     TEST, "shell", "6."),
    (6, "корень снова прокручивается: высота body больше вьюпорта",
     [(CSS, "@@APPEND@@", "\r\nhtml.m-ui{ height:100% !important; overflow:auto !important; }\r\n"
                          "html.m-ui body{ height:300vh !important; }\r\n")],
     TEST, "shell", "28."),
    (7, "рабочий экран настроек получает собственный сдвиг вверх и лезет под бар",
     [(CSS, "@@APPEND@@", "\r\n.fm-settings-workspace{ margin-top:-40px; }\r\n")],
     TEST, "shell", "24."),
    (8, "закреплённая навигация становится прозрачной",
     [(CSS, "@@APPEND@@", "\r\n.fm-set-mini{ background:transparent !important; }\r\n")],
     TEST, "shell", "37."),
    (9, "верхний отступ возвращён области прокрутки — щель над навигацией открывается снова",
     [(CSS, "@@APPEND@@", "\r\n.fm-settings-workspace .fm-set-scroll{ padding-top:16px; }\r\n")],
     TEST, "shell", "41."),
    (10, "первый ряд карточек уезжает под навигацию",
     [(CSS, "@@APPEND@@", "\r\n.fm-set-mini{ margin-bottom:-60px; }\r\n")],
     TEST, "shell", "39."),
    (11, "scroll-padding-top у области прокрутки обнулён",
     [(CSS, "@@APPEND@@", "\r\n.fm-settings-workspace .fm-set-scroll{ scroll-padding-top:0; }\r\n")],
     TEST, "shell", "12."),
    (12, "scroll-margin-top у секций обнулён",
     [(CSS, "@@APPEND@@",
       "\r\n.fm-settings-workspace .fm-set-scroll [id^=\"fm-sec-\"]{ scroll-margin-top:0; }\r\n")],
     TEST, "shell", "13."),
    # Порча ДВОЙНАЯ намеренно. Одного «setSecGo прокручивает корень» мало: пока жив кадр
    # html.m-ui #app{position:fixed;inset:0;overflow:hidden}, у корня scrollHeight == clientHeight
    # и присвоение scrollTop не даёт НИЧЕГО — прокрутить нечего. Это и есть суть защиты 2.835.
    # Поэтому воспроизводим ровно тот дефект: снимаем кадр И заставляем чипы двигать корень.
    (13, "кадр снят И setSecGo прокручивает КОРЕНЬ (возврат дефекта 2.835: чипы утаскивают бар)",
     [(CSS, "@@APPEND@@", "\r\nhtml.m-ui #app{ position:static !important; overflow:visible !important; }"
                          "\r\nhtml.m-ui body{ height:300vh !important; }\r\n"),
      (JS, "                const deltaVis = el.getBoundingClientRect().top - m.rect.top - m.bandVis;",
       "                document.documentElement.scrollTop = 200;\n"
       "                const deltaVis = el.getBoundingClientRect().top - m.rect.top - m.bandVis;")],
     TEST, "chips", "50."),
    (14, "setSecGo снова использует scrollIntoView",
     [(JS, "                m.box.scrollTo({ top: Math.max(0, m.box.scrollTop + deltaVis * m.k), behavior: 'smooth' });",
       "                el.scrollIntoView(true);")],
     TEST, "chips", "14."),
    (15, "setSecGo снова игнорирует высоту закреплённой полосы",
     [(JS, "const deltaVis = el.getBoundingClientRect().top - m.rect.top - m.bandVis;",
       "const deltaVis = el.getBoundingClientRect().top - m.rect.top - 6;")],
     TEST, "chips", "48."),
    (16, "обязательный сценарий скриншота владельца убран из набора",
     [(TEST, '    ((1365, 1024), 1.0, "ru", "СКРИНШОТ ВЛАДЕЛЬЦА 1365x1024 RU"),\n', "")],
     TEST, "shell", "17b."),
    (17, "увеличение 200 % убрано из набора",
     [(TEST, '    ((1920, 1080), 2.0, "ru", "увеличение 200 %"),\n', "")],
     TEST, "shell", "17c."),
    (18, "в приложении появляется ошибка консоли",
     [(JS, "    const setSecGo = (id) => {",
       "    console.error('FM_MUTATION_CONSOLE_ERROR');\n    const setSecGo = (id) => {")],
     TEST, "shell", "45."),
    (19, "проверка пересечения бара и колонки ослаблена до «касание допустимо»",
     [(TEST, 'all(v["r"]["left"]["top"] > v["r"]["paint"]["bottom"] + 0.5 for v in ok.values())',
       'all(v["r"]["left"]["top"] >= v["r"]["paint"]["bottom"] - 99 for v in ok.values())'),
      (CSS, "body .fm-style-migrated.fm-header-desktop-v270{ height:var(--fm-header-h); }",
       "body .fm-style-migrated.fm-header-desktop-v270{ height:calc(var(--fm-header-h) + 12px); }")],
     TEST, "shell", "22."),
    # Якорь с переводом строки обязателен: в начале файла те же слова стоят в ДОКСТРОКЕ
    # («Предохранитель: DISPATCH_ENABLED = False.»), и порча без \n меняла бы прозу, а не код —
    # набор оставался бы зелёным, и проверка была бы ложно-успешной.
    (20, "DISPATCH включается (предохранитель печати снят)",
     [(ORCH, "\nDISPATCH_ENABLED = False", "\nDISPATCH_ENABLED = True")],
     DIAG, "static", ""),
    (21, "TRANSPORT включается (предохранитель отправки снят)",
     [(ORCH, "\nTRANSPORT_ENABLED = False", "\nTRANSPORT_ENABLED = True")],
     DIAG, "static", ""),
]


def sha(rel):
    return hashlib.sha256(io.open(os.path.join(REPO, rel), "rb").read()).hexdigest()


def read(rel):
    return io.open(os.path.join(REPO, rel), encoding="utf-8", errors="surrogateescape",
                   newline="").read()


def write(rel, text):
    io.open(os.path.join(REPO, rel), "w", encoding="utf-8", errors="surrogateescape",
            newline="").write(text)


def run_test(rel, mode):
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if mode in ("shell", "chips", "ws"):
        env["FM_SHELL_ONLY"] = mode
    else:
        env.pop("FM_SHELL_ONLY", None)
    try:
        pr = subprocess.run([sys.executable, rel], cwd=REPO, env=env, capture_output=True,
                            text=True, encoding="utf-8", errors="replace", timeout=1800)
        out = pr.stdout or ""
        reds = [ln[len("  RED: "):] if ln.startswith("  RED: ") else ln
                for ln in out.splitlines() if ln.startswith("  RED: ") or ln.startswith("FAIL — ")]
        reds = [re.sub(r"^FAIL — ", "", r) for r in reds]
        tail = [ln for ln in out.splitlines() if ln.startswith("ИТОГО")]
        return pr.returncode, reds, (tail[-1] if tail else (pr.stderr or out)[-160:].replace("\n", " "))
    except subprocess.TimeoutExpired:
        return -9, [], "таймаут"


def sweep_engines():
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='msedge.exe'\" | "
          "Where-Object { $_.CommandLine -and ($_.CommandLine -match 'fm-cdp-' -or "
          "$_.CommandLine -match 'fm_cdp_' -or $_.CommandLine -match 'fm_stage835_' -or "
          "$_.CommandLine -match 'fm_probe_') } | "
          "ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop } catch {} }")
    try:
        subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps],
                       capture_output=True, timeout=60)
    except Exception:
        pass


ONLY = {int(x) for x in (os.environ.get("FM_MUT_ONLY") or "").replace(" ", "").split(",") if x}

FILES = sorted({f for m in MUTATIONS for (f, _, _) in m[2]})
BASE_SHA = {f: sha(f) for f in FILES}
BASE_TXT = {f: read(f) for f in FILES}
# Alpha 2.841: восстановление, переживающее убийство процесса (см. _mutation_lock.guard_files).
guard_files(*[os.path.join(REPO, f) if not os.path.isabs(f) else f for f in FILES])

print("=" * 96)
print("MUTATION PROOF Alpha 2.836 — каркас приложения и верх настроек")
print("=" * 96)
print("Исходные SHA-256:")
for f in FILES:
    print("   %-42s %s" % (f, BASE_SHA[f]))

# ── базовая линия: без порчи каждый режим ЗЕЛЁНЫЙ (иначе «покраснел» ничего не доказывает) ────
print("\nБазовая линия (без порчи):")
base_ok = True
for mode in ("shell", "chips"):
    rc, reds, tail = run_test(TEST, mode)
    print("   режим %-6s rc=%d  %s" % (mode, rc, tail))
    if rc != 0:
        base_ok = False
    sweep_engines()
rc, reds, tail = run_test(DIAG, "static")
print("   %-13s rc=%d  %s" % (DIAG.split("/")[-1], rc, tail))
if rc != 0:
    base_ok = False
sweep_engines()
if not base_ok:
    print("\nБАЗОВАЯ ЛИНИЯ НЕ ЗЕЛЁНАЯ — порчи проверять бессмысленно.")
    raise SystemExit(1)

caught, missed, harness_errors = [], [], []
try:
    for num, desc, edits, test_rel, mode, expect in MUTATIONS:
        if ONLY and num not in ONLY:
            continue
        applied = True
        for rel, old, new in edits:
            src = read(rel)
            if old == "@@APPEND@@":
                write(rel, src + new)
                continue
            if src.count(old) < 1:
                print("MISS  — [%2d] %-70s ЯКОРЬ НЕ НАЙДЕН в %s" % (num, desc[:70], rel))
                applied = False
                break
            write(rel, src.replace(old, new, 1))
        if not applied:
            for rel in FILES:
                write(rel, BASE_TXT[rel])
            missed.append((num, desc, "якорь не найден"))
            continue

        rc, reds, tail = run_test(test_rel, mode)
        for rel in FILES:
            write(rel, BASE_TXT[rel])
        sweep_engines()

        # Пустое ожидание = «любая краснота»: у части тестов другой формат вывода (ok/Итого),
        # имена проверок оттуда не вытащить. Для остальных сверяем ИМЕННО ожидаемую проверку —
        # иначе «покраснел хоть чем-то» скрыл бы, что нужная проверка не работает.
        # Alpha 2.841: ТАЙМАУТ — отказ САМОЙ оснастки, а не пойманная поломка. run_test отдаёт
        # rc=-9 при subprocess.TimeoutExpired; при пустом `expect` прежняя формула `rc != 0`
        # засчитывала зависшую проверку как улов и позволяла набору выйти нулём.
        if rc == -9:
            harness_errors.append((num, desc, "таймаут проверки"))
            print("HARNESS — [%2d] %-64s ТАЙМАУТ" % (num, desc[:64]))
            continue
        hit = rc != 0 and (not expect or any(expect in r for r in reds))
        restored = all(sha(f) == BASE_SHA[f] for f in FILES)
        mark = "CAUGHT" if (hit and restored) else "MISS  "
        print("%s — [%2d] %-64s rc=%d ожидалась «%s» %s откат=%s"
              % (mark, num, desc[:64], rc, expect or "любая",
                 "ЕСТЬ" if (not expect or any(expect in r for r in reds)) else "НЕТ",
                 "OK" if restored else "СЛОМАН"))
        if not (hit and restored):
            print("          красные проверки: %s" % ([r[:70] for r in reds][:6] or tail))
            missed.append((num, desc, "rc=%d" % rc))
        else:
            caught.append(num)
finally:
    for rel in FILES:
        write(rel, BASE_TXT[rel])
    sweep_engines()

ok_sha = {f: (sha(f) == BASE_SHA[f]) for f in FILES}
print("\nПобайтовое восстановление:")
for f in FILES:
    print("   %-42s %s  %s" % (f, sha(f), "OK" if ok_sha[f] else "СЛОМАН"))

total = len([m for m in MUTATIONS if not ONLY or m[0] in ONLY])
print("\n" + "=" * 96)
print("МЕТКА: %s" % SENTINEL)
print("ИТОГО: ПОЙМАНО %d из %d (объявлено поломок: %d)" % (len(caught), total, len(MUTATIONS)))
if missed:
    for n, d, why in missed:
        print("  ПРОПУЩЕНА [%d] %s (%s)" % (n, d, why))
if harness_errors:
    print("ОТКАЗ САМОГО НАБОРА (таймаут):")
    for n, d, why in harness_errors:
        print("  [%d] %s (%s)" % (n, d, why))
print("Файлы восстановлены побайтово: %s" % ("ДА" if all(ok_sha.values()) else "НЕТ"))
# Alpha 2.841: FM_MUT_ONLY — отладочное СУЖЕНИЕ набора. Прежде `total` считался уже ПОСЛЕ
# фильтра, поэтому запуск с FM_MUT_ONLY=1 печатал «ПОЙМАНО 1 из 1» и выходил НУЛЁМ: релизный
# gate, читающий только код возврата, видел полный успех при одной исполненной поломке.
# Теперь сужение набора само по себе делает результат КРАСНЫМ.
if ONLY:
    print("ВНИМАНИЕ: FM_MUT_ONLY сузил набор до %d из %d — это отладочный режим, "
          "доказательством он не является." % (total, len(MUTATIONS)))
# Прежнее условие выхода сохранено дословно; ниже к нему добавляется process_rc из сводки.
_rc_prev = 0 if (len(caught) == total and total == len(MUTATIONS)
                 and not harness_errors and all(ok_sha.values())) else 1
# declared — объявлено поломок (len(MUTATIONS)); executed — реально исполнено (total, то есть
# число итераций цикла; сужается FM_MUT_ONLY); caught — поломки, покрасневшие ожидаемой
# проверкой (len(caught)); timeouts — проверки, убитые по времени (harness_errors пополняется
# только при rc == -9); restore_failures — файлы, не вернувшиеся к исходным байтам (ok_sha).
# Отдельного счётчика уборки в наборе нет → cleanup_failures=0.
_summary = _mut_build(declared=len(MUTATIONS),
                      executed=total,
                      caught=len(caught),
                      timeouts=len(harness_errors),
                      restore_failures=len([_f for _f in FILES if not ok_sha[_f]]),
                      cleanup_failures=0)
_rc = _mut_emit(_summary)
raise SystemExit(_rc_prev or _rc)
