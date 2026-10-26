# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.835 — MUTATION PROOF для тестов раскладки настроек и верхнего бара.

ЗАЧЕМ. Зелёный тест сам по себе ничего не доказывает: он мог бы быть зелёным всегда. Здесь по
одной ломается КАЖДАЯ защищаемая деталь настоящего кода (web/app.css, web/index.html, web/app.js),
проверяется, что соответствующий тест краснеет, и правка ОТКАТЫВАЕТСЯ побайтово (сверка SHA-256).

ОСОБО ВАЖНО. Часть поломок сделана намеренно НЕВИДИМОЙ для статических проверок: они дописывают
переопределяющее правило в КОНЕЦ файла (статика читает первое правило и остаётся зелёной) либо
меняют только поведение, сохраняя контракт. Их ловит исключительно измерение в НАСТОЯЩЕМ браузере —
это и есть доказательство, что браузерная часть тестов не декоративная. Отдельно проверяется, что
снятие блока исправления целиком возвращает дефект (превышение корня 194px и уезд бара).

БЕЗОПАСНОСТЬ. Правятся только web/app.css, web/index.html, web/app.js — и всегда откатываются.
Рабочая БД, DATA_DIR, config и production-рантайм не затрагиваются; принтерам ничего не
отправляется; печати не запускаются. Прерывание процесса восстанавливает файлы в finally.

Запуск:  python tools/test_layout_topbar_mutation_proof.py    (0 = все поломки поймали)
"""
import hashlib
import io
import os
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
# Alpha 2.841: машиночитаемый итог набора — релизный гейт обязан считать нули напрямую,
# а не разбирать человекочитаемую прозу («ПОЙМАНО N из M»). Проза остаётся как была.
from _mutation_report import build as _mut_build, emit as _mut_emit  # noqa: E402
acquire_or_die('test_layout_topbar_mutation_proof')

SENTINEL = "LAYOUT_TOPBAR_MUTATION_SENTINEL_2_835"

CSS = os.path.join(REPO, "web", "app.css")
HTML = os.path.join(REPO, "web", "index.html")
APPJS = os.path.join(REPO, "web", "app.js")

LAYOUT = "tools/test_settings_layout_system.py"
TOPBAR = "tools/test_topbar_stays_fixed.py"

# (файл, что заменить, на что, тест, режим, описание)
#   режим "static"  — тест запускается без браузера (быстро), поломку обязана поймать статика;
#   режим "browser" — тест запускается целиком, поломку обязано поймать измерение в браузере.
MUTATIONS = [
    # ── раскладка: мера страницы ────────────────────────────────────────────────────────────────
    (CSS, "max-width:var(--fm-set-measure);", "max-width:none;", LAYOUT, "static",
     "убрать ограничение меры — на 3440 карточки снова растянутся полосой"),
    (CSS, "{width:100%;max-width:var(", "{max-width:var(", LAYOUT, "static",
     "убрать width:100% — flex-колонка начнёт мерить по содержимому (горизонтальная прокрутка)"),
    (CSS, "margin-right:auto;box-sizing:border-box}", "margin-right:auto}", LAYOUT, "static",
     "убрать box-sizing — padding начнёт добавляться к ширине"),
    (CSS, "margin-left:auto;margin-right:auto;box-sizing", "box-sizing", LAYOUT, "static",
     "убрать центрирование меры"),
    (CSS, "--fm-set-measure:1040px;", "--fm-set-measure:2000px;", LAYOUT, "static",
     "растянуть меру до 2000px — страница снова разъедется"),
    (CSS, ".fm-set-scroll > .fm-set-head,", ".fm-set-scroll > .fm-set-nonexistent,", LAYOUT, "static",
     "исключить заголовок раздела из меры — заголовок уедет от сетки"),
    # ── раскладка: колонки и ритм ──────────────────────────────────────────────────────────────
    (CSS, "repeat(auto-fit,minmax(min(360px,100%),1fr))", "repeat(4,1fr)", LAYOUT, "static",
     "жёсткие четыре колонки вместо адаптивных двух"),
    (CSS, "minmax(min(360px,100%),1fr));gap:12px", "minmax(min(300px,100%),1fr));gap:12px",
     LAYOUT, "static",
     "снизить минимум колонки до 300px — при мере 1040 появится третья колонка"),
    (CSS, "gap:12px;align-items:stretch;min-width:0}", "gap:12px;min-width:0}", LAYOUT, "static",
     "убрать выравнивание рядов — вернутся «ступеньки»"),
    (CSS, ".fm-set-grid > .fm-set-group{height:100%}", ".fm-set-grid > .fm-set-group{min-width:0}",
     LAYOUT, "static", "карточка перестанет занимать высоту ряда"),
    (CSS, ".fm-set-sec-wide{grid-column:1/-1}", ".fm-set-sec-wide{min-width:0}", LAYOUT, "static",
     "широкая секция перестанет занимать всю строку"),
    (CSS, "min-width:0;flex:0 0 auto;", "min-width:0;flex:1 1 240px;", LAYOUT, "static",
     "вернуть дефект 2.834: строка-флажок получит базовую ВЫСОТУ 240px"),
    # ── раскладка: порядок и группировка ───────────────────────────────────────────────────────
    (HTML, 'id="fm-sec-net"', 'id="fm-sec-network"', LAYOUT, "static",
     "переименовать id секции «Сеть» — мини-навигация потеряет цель"),
    (HTML, "setSecGo('fm-sec-net')", "setSecGo('fm-sec-nets')", LAYOUT, "static",
     "чип мини-навигации ведёт в никуда"),
    (HTML, 'id="fm-sec-storage"', 'id="fm-sec-zstorage"', LAYOUT, "static",
     "нарушить состав id (порядок секций больше не сверить)"),
    (HTML, 'id="fm-sec-modules" class="fm-set-group fm-set-sec-wide"',
     'id="fm-sec-modules" class="fm-set-group"', LAYOUT, "static",
     "снять полосу у «Модулей» — большая секция окажется в узкой колонке"),
    (HTML, 'id="fm-sec-backup" class="fm-set-group fm-set-sec-wide"',
     'id="fm-sec-backup" class="fm-set-group"', LAYOUT, "static",
     "снять полосу у «Резервной копии» — крупная секция сожмётся в колонку"),
    # ── верхний бар: каркас ────────────────────────────────────────────────────────────────────
    (CSS, "position:fixed; inset:0;", "position:relative;", TOPBAR, "static",
     "снять фиксированный кадр #app — корень снова сможет прокручиваться"),
    (CSS, "  overflow:hidden !important;           /* лишнее обрезается здесь, а не выносится в корень */",
     "  overflow:auto !important;", TOPBAR, "static",
     "разрешить прокрутку внутри #app"),
    (CSS, "  overscroll-behavior:none;", "  overscroll-behavior:auto;", TOPBAR, "static",
     "разрешить прокрутке «пробивать» кадр наружу"),
    (CSS, ".app-header{ position:sticky !important; top:0; }",
     ".app-header{ position:relative !important; }", TOPBAR, "static",
     "снять sticky у верхнего бара — вторая линия защиты исчезнет"),
    (CSS, ".app-header{ overflow:visible !important; }", ".app-header{ overflow:hidden !important; }",
     TOPBAR, "static", "бар начнёт обрезать своё содержимое"),
    (CSS, ".app-header{ overflow:visible !important; }",
     ".app-header{ overflow:visible !important; }\r\nhtml, html.m-ui{ height:100% !important; }",
     TOPBAR, "static",
     "вернуть в блок исправления навязанную высоту html — черновик 2.835 так ломал прокрутку "
     "списка файлов принтера"),
    (CSS, ".fm-set-scroll{flex:1 1 auto;min-height:0;overflow-y:auto;overscroll-behavior:contain}",
     ".fm-set-scroll{flex:1 1 auto;overflow-y:visible;overscroll-behavior:contain}",
     TOPBAR, "static",
     "лишить область настроек собственной прокрутки — прокрутка полезет к предкам"),
    # Alpha 2.836: setSecGo переписан (вычитает замеренную высоту закреплённой полосы вместо
    # фиксированных 6px и переводит визуальные px в px прокрутки), поэтому якорь переведён на
    # новую строку. СМЫСЛ порчи прежний: вернуть scrollIntoView в мини-навигацию.
    (APPJS, "m.box.scrollTo({ top: Math.max(0, m.box.scrollTop + deltaVis * m.k), behavior: 'smooth' });",
     "el.scrollIntoView({ block: 'start', behavior: 'smooth' });", TOPBAR, "static",
     "вернуть scrollIntoView в мини-навигацию — ровно то, что уносило бар"),
    # ── НЕВИДИМЫЕ для статики: ловит только настоящий браузер ──────────────────────────────────
    (CSS, "@@APPEND@@", ".fm-set-scroll > .fm-set-grid{max-width:none !important}", LAYOUT, "browser",
     "дописать переопределение меры в конец файла (статика читает первое правило и молчит)"),
    (CSS, "@@APPEND@@", ".fm-chk{min-height:240px}", LAYOUT, "browser",
     "раздуть строку-флажок через min-height (flex остаётся правильным — статика молчит)"),
    (CSS, "@@BLOCK_TOPBAR@@", "", TOPBAR, "browser",
     "снять ВЕСЬ блок исправления 2.835 — замерено, что дефект возвращается точь-в-точь "
     "(htmlOver 194px и уезд бара на -194px при 1920x1080)"),
    # Alpha 2.836: якорь переведён на новую строку setSecGo, смысл порчи прежний.
    (APPJS, "top: Math.max(0, m.box.scrollTop + deltaVis * m.k), behavior: 'smooth' });",
     "top: 0, behavior: 'smooth' });", TOPBAR, "browser",
     "мини-навигация всегда уезжает в начало (контракт .fm-set-scroll/scrollTo цел — статика молчит)"),
    (CSS, "html.m-ui{ height:auto !important; }\r\nhtml.m-ui body{ height:auto !important; min-height:0 !important; }",
     "", TOPBAR, "browser",
     "снять отпускание высот корня — замерено, что корню возвращается прокручиваемое превышение "
     "194px (1920x1080) и 256px (3440x1400), хотя бар пока держит sticky"),
    (CSS, "html.m-ui #app{", "#app, html.m-ui #app{", TOPBAR, "static",
     "вернуть голый селектор #app — он перехватывал бы точки монтирования сторонних страниц"),
    (CSS, "html.m-ui .app-header{ position:sticky", ".app-header{ position:sticky", TOPBAR, "static",
     "снять ограничение области у sticky-бара"),
    (CSS, "html.m-ui{ height:auto !important; }", "html{ height:auto !important; }", TOPBAR, "static",
     "снять ограничение области действия высот — так черновик 2.835 ломал прокрутку списка файлов "
     "принтера на сторонних страницах с app.css"),
]


def sha(path):
    return hashlib.sha256(io.open(path, "rb").read()).hexdigest()


def read(path):
    return io.open(path, encoding="utf-8", newline="").read()


def write(path, text):
    io.open(path, "w", encoding="utf-8", newline="").write(text)


def _sweep_engines():
    """Снять headless-движки, оставшиеся от прогонов с поломанным кодом.

    Alpha 2.835: без этого за 33 поломки накапливались сотни процессов, машина захлёбывалась и
    следующие браузерные измерения начинали плавать. Фильтр — только наши временные профили.
    """
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='msedge.exe' OR Name='chrome.exe'\" | "
          "Where-Object { $_.CommandLine -and ($_.CommandLine -match 'fm-cdp-' -or "
          "$_.CommandLine -match 'fm_cdp_' -or $_.CommandLine -match 'fm_stage835_') } | "
          "ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop } catch {} }")
    try:
        subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps],
                       capture_output=True, timeout=60)
    except Exception:
        pass


def run_test(rel, mode):
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    if mode == "static":
        env["FM_LAYOUT_NO_BROWSER"] = "1"
        env["FM_TOPBAR_NO_BROWSER"] = "1"
    else:
        env.pop("FM_LAYOUT_NO_BROWSER", None)
        env.pop("FM_TOPBAR_NO_BROWSER", None)
    try:
        pr = subprocess.run([sys.executable, rel], cwd=REPO, env=env, capture_output=True,
                            text=True, encoding="utf-8", errors="replace",
                            timeout=180 if mode == "static" else 1200)
        tail = [l for l in (pr.stdout or "").splitlines() if l.startswith("ИТОГО")]
        return pr.returncode, (tail[-1] if tail else (pr.stderr or "")[-120:])
    except subprocess.TimeoutExpired:
        return -9, "таймаут"


print("Alpha 2.835 — mutation proof раскладки и верхнего бара")
print("Метка: %s" % SENTINEL)
print("=" * 96)

base = {p: (read(p), sha(p)) for p in (CSS, HTML, APPJS)}
# Alpha 2.841: finally НЕ отрабатывает при убийстве процесса извне (лимит раннера, kill).
# Именно так здесь однажды осталась мутация web/app.js в рабочем дереве. guard_files даёт
# восстановление через atexit и обработчики сигналов — поверх существующего finally.
guard_files(CSS, HTML, APPJS)

# Контроль: до поломок оба теста обязаны быть зелёными (иначе доказательство бессмысленно).
caught, missed, harness_errors = 0, [], []
ok = False                      # побайтовый откат: подтверждается в finally, входит в вердикт
for rel, mode in ((LAYOUT, "static"), (TOPBAR, "static")):
    rc, tail = run_test(rel, mode)
    print("КОНТРОЛЬ  %-44s rc=%s  %s" % (os.path.basename(rel), rc, tail))
    if rc != 0:
        print("\nОСТАНОВ: тест краснеет ещё до поломок — доказательство невозможно.")
        sys.exit(2)

try:
    for n, (path, old, new, rel, mode, why) in enumerate(MUTATIONS, 1):
        src = base[path][0]
        if old == "@@BLOCK_TOPBAR@@":
            # Блок ищется по своим якорям: встраивать 2.6 КБ текста в таблицу поломок незачем.
            b0 = src.rfind("/*", 0, src.index("Alpha 2.835 — ВЕРХНИЙ БАР"))
            b1 = src.index("\r\n", src.index(
                "html.m-ui body{ height:auto !important; min-height:0 !important; }")) + 2
            mutated = src[:b0] + src[b1:]
        elif old == "@@APPEND@@":
            mutated = src + ("\r\n" if src.endswith("\n") is False else "") + new + "\r\n"
        else:
            cnt = src.count(old)
            if cnt != 1:
                missed.append("%02d. фрагмент встречается %d раз: %s" % (n, cnt, old[:60]))
                print("ПРОПУСК %02d — фрагмент найден %d раз (ожидалась 1): %s" % (n, cnt, old[:60]))
                continue
            mutated = src.replace(old, new, 1)
        write(path, mutated)
        rc, tail = run_test(rel, mode)
        write(path, src)
        _sweep_engines()                      # движки сломанного прогона не должны копиться
        ok_revert = sha(path) == base[path][1]
        # ── Alpha 2.841: ТАЙМАУТ — НЕ «поймана» ────────────────────────────────────────────
        # run_test отдаёт rc=-9 при subprocess.TimeoutExpired. Прежний вердикт `rc != 0`
        # засчитывал зависшую проверку как успешно пойманную поломку: набор рапортовал
        # «ПОЙМАНО N из N» и выходил нулём, ничего не доказав. Зависание — это отказ САМОЙ
        # оснастки, и он обязан краснить набор, а не украшать статистику.
        if rc == -9:
            status = "ТАЙМАУТ"
            harness_errors.append("%02d. %s :: таймаут проверки" % (n, why))
        elif rc != 0:
            status = "ПОЙМАНА"
            caught += 1
        else:
            status = "НЕ ПОЙМАНА"
            missed.append("%02d. %s" % (n, why))
        print("%02d [%-7s] %-11s %-62s | откат %s | %s"
              % (n, mode, status, why[:62], "OK" if ok_revert else "СБОЙ", tail[:40]))
        if not ok_revert:
            print("\nКРИТИЧНО: файл не восстановился побайтово — остановка.")
            sys.exit(3)
finally:
    for p, (src, digest) in base.items():
        if sha(p) != digest:
            write(p, src)
    ok = all(sha(p) == d for p, (s, d) in base.items())
    print("\nФайлы восстановлены побайтово: %s" % ("ДА" if ok else "НЕТ"))

print("=" * 96)
print("ИТОГО: ПОЙМАНО %d из %d" % (caught, len(MUTATIONS)))
if missed:
    print("НЕ ПОЙМАНЫ:")
    for m in missed:
        print("   - %s" % m)
if harness_errors:
    print("ОТКАЗ САМОГО НАБОРА (таймаут):")
    for m in harness_errors:
        print("   - %s" % m)
if not ok:
    print("ФАЙЛЫ НЕ ВОССТАНОВЛЕНЫ ПОБАЙТОВО — рабочее дерево испорчено.")
print("МЕТКА: %s" % SENTINEL)
# Alpha 2.841: в вердикт входят ВСЕ три условия. Прежде `ok` (побайтовый откат) считался и
# печатался, но в код возврата не попадал: набор с испорченным рабочим деревом мог выйти нулём.
# Прежнее условие выхода сохранено дословно; ниже к нему добавляется process_rc из сводки.
_rc_prev = 0 if (caught == len(MUTATIONS) and not harness_errors and ok) else 1
# ОТКУДА ЧИСЛА (все счётчики уже существовали в наборе):
#   declared  — len(MUTATIONS), длина таблицы поломок;
#   executed  — объявленное МИНУС записи ветки «ПРОПУСК» (неоднозначный якорь: там continue
#               срабатывает ДО write/run_test, то есть поломка объявлена, но не исполнена).
#               Отдельного счётчика исполненных в наборе нет, а ветка «ПРОПУСК» — единственная,
#               кладущая в missed запись со словами «фрагмент встречается»;
#   caught    — caught, поломки, покрасневшие целевой тест;
#   timeouts  — len(harness_errors): здесь harness_errors наполняется ТОЛЬКО таймаутами (rc == -9);
#   restore_failures — вердикт побайтового отката `ok` из finally (0 — файлы вернулись, 1 — нет);
#   cleanup_failures — отдельного счётчика уборки в наборе нет → 0.
_summary = _mut_build(declared=len(MUTATIONS),
                      executed=len(MUTATIONS) - sum(1 for _m in missed
                                                    if "фрагмент встречается" in _m),
                      caught=caught,
                      timeouts=len(harness_errors),
                      restore_failures=0 if ok else 1,
                      cleanup_failures=0)
_rc = _mut_emit(_summary)
sys.exit(_rc_prev or _rc)
