# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.835/2.840 — MUTATION PROOF браузерного release gate (нулевые пропуски).

ЗАЧЕМ. Семь старых .mjs-харнессов перевели со сломанного `--dump-dom` на общий CDP-мост, а
браузерные проверки перестали быть пропусками. Само по себе «стало зелено» ничего не доказывает:
зелёным можно быть и потому, что проверки декоративны. Здесь по одной ломается КАЖДАЯ несущая
деталь механизма и защищаемого поведения, проверяется, что нужный тест КРАСНЕЕТ, и правка
откатывается ПОБАЙТОВО (сверка SHA-256 до и после).

ЧТО ИСПРАВЛЕНО В Alpha 2.840 (набор был непригоден для release gate)

1. ТАЙМАУТ СЧИТАЛСЯ УСПЕХОМ. Вердикт брался как `rc != 0`, а таймаут возвращал -9 — то есть
   зависшая проверка засчитывалась как «поломка поймана». Теперь таймаут, падение оснастки и
   несостоявшийся откат — это КРАСНЫЙ РЕЗУЛЬТАТ САМОГО НАБОРА, а не пойманная мутация.

2. ОКНО ОЖИДАНИЯ БЫЛО 2400 c НА ПРОВЕРКУ при том, что самый долгий здоровый браузерный тест
   идёт 161 c. Такое окно не ограничивает ничего: одна проверка могла съесть сорок минут.
   Теперь 420 c (2.6× самого долгого здорового) плюс общий потолок на весь набор.

3. ТРИ ПОЛОМКИ СТОИЛИ ~22 МИНУТ ИЗ 32. Замеры: поломка с `--dump-dom` НЕ зависает — мост честно
   отказывает («page-target не найден за 30000ms»), но отказ стоит 63 c на сценарий (30 c ожидания
   + вторая попытка), а сценариев шесть → 380 c на одну поломку, и таких было две; третья
   (проглоченный таймаут CDP) стоила ещё ~540 c. Это доказывало свойства САМОГО МОСТА через
   далёкое следствие. Теперь те же свойства пинаются напрямую в
   `tools/test_browser_bridge_contract.mjs` — за секунды и без потери смысла.

4. ПОЛОМКИ 1 и 3 БОЛЬШЕ НЕ ТРОГАЮТ ФАЙЛЫ РЕПОЗИТОРИЯ. Они применяются к КОПИИ оснастки во
   временной папке (overlay), и рабочее дерево при них не меняется вообще.

5. ОТКАТ ПЕРЕЖИВАЕТ ПРИНУДИТЕЛЬНОЕ ЗАВЕРШЕНИЕ. Кроме `finally` теперь есть журнал нетронутых
   копий, обработчики сигналов и atexit, а SHA-256 сверяется ПОСЛЕ КАЖДОЙ поломки, а не только
   в конце. Не удалось восстановить — набор краснеет и называет точный путь.

ЧТО ЛОМАЕТСЯ (12 поломок, ровно по списку release gate):
  1  харнесс снова передаёт `--dump-dom`                     [overlay, файлы репозитория не тронуты]
  2  отказ браузера снова превращается в пропуск вместо красного
  3  таймаут CDP молча отдаёт пустой ответ                   [overlay, файлы репозитория не тронуты]
  4  страница печатает ошибку в консоль;
  5  страница печатает предупреждение Vue;
  6  один из браузерных сценариев не исполняется;
  7  корню интерфейса снова разрешена прокрутка (уезжает верхний бар);
  8  настройки снова получают четыре колонки на 3440;
  9  `.fm-chk` снова получает flex-basis 240px;
 10  фикс кадра `#app` снимается;
 11  нижнее содержимое области настроек становится недоступным;
 12  появляется горизонтальная прокрутка.

БЕЗОПАСНОСТЬ. Правятся только web/app.css и файлы оснастки в tools/ — и всегда откатываются.
Рабочая БД, DATA_DIR, config и production-рантайм не затрагиваются; принтерам ничего не
отправляется; печати не запускаются; временные профили и процессы движка убираются по своему
профилю (пользовательский браузер не трогается НИКОГДА — глобального kill по имени процесса нет).

Запуск:  python tools/test_browser_gate_mutation_proof.py     (0 = все поломки пойманы)
"""
import atexit
import hashlib
import io
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Alpha 2.841: наборы mutation proof портят ОДНИ И ТЕ ЖЕ файлы репозитория.
# Параллельный запуск двух наборов уже приводил к тому, что откат одного затирал
# откат другого и в дереве оставалась чужая мутация. Замок сериализует прогоны;
# не дождались — mutation_lock_busy и КРАСНЫЙ выход, а не тихая правка файлов.
sys.path.insert(0, os.path.join(REPO, "tools"))
from _mutation_lock import acquire_or_die  # noqa: E402
# Alpha 2.841: машиночитаемый итог набора — гейт считает нули напрямую, а не разбирает прозу.
from _mutation_report import build as _mut_build, emit as _mut_emit  # noqa: E402
acquire_or_die('test_browser_gate_mutation_proof')

SENTINEL = "BROWSER_GATE_MUTATION_SENTINEL_2_835"

CSS = os.path.join(REPO, "web", "app.css")
LIB = os.path.join(REPO, "tools", "_edge_cdp_lib.mjs")
SLF = os.path.join(REPO, "tools", "test_inventory_search_layout.mjs")
HLF = os.path.join(REPO, "tools", "test_inventory_header_line.mjs")

LAYOUT = "tools/test_settings_layout_system.py"
TOPBAR = "tools/test_topbar_stays_fixed.py"
FRAME = "tools/test_app_frame_surfaces.py"
SL = "tools/test_inventory_search_layout.mjs"
HL = "tools/test_inventory_header_line.mjs"
BRIDGE = "tools/test_browser_bridge_contract.mjs"

# Окна ожидания. Самый долгий ЗДОРОВЫЙ браузерный тест набора — 161 c (topbar), поэтому 420 c
# заведомо достаточно и при этом реально ограничивает. Общий потолок ловит деградацию машины.
T_STATIC = 240
T_BROWSER = 420
T_TOTAL = 1500

# Якоря — ДОСЛОВНЫЕ куски настоящих файлов. app.css хранится с CRLF, файлы оснастки — с LF;
# переводы строк в якорях обязаны это учитывать, иначе замена молча не сработает.
FRAME_RULE = ("html.m-ui #app{                          /* только НАСТОЯЩЕЕ приложение: класс m-ui вешает app.js. */\r\n"
              "  position:fixed; inset:0;              /* ровно вьюпорт: корню нечего прокручивать */\r\n"
              "  overflow:hidden !important;           /* лишнее обрезается здесь, а не выносится в корень */\r\n"
              "  overscroll-behavior:none;             /* нет цепного «протягивания» прокрутки наружу */\r\n"
              "}")

# (номер, описание, [(файл, старое, новое), ...], тест, режим)
#   режим "static"  — тест запускается без браузера (быстро);
#   режим "browser" — тест запускается целиком: поломку обязано поймать измерение в браузере;
#   режим "overlay" — поломка применяется к КОПИИ tools/*.mjs во временной папке; файлы
#                     репозитория не изменяются вообще, тест запускается из копии.
MUTATIONS = [
    # Историческая поломка «вернули --dump-dom» доказывается ТАМ, где живёт правило, — в контракте
    # моста, статической проверкой за миллисекунды. Прежний вариант ждал 380 c, пока далёкий
    # харнесс геометрии не покраснеет по таймауту, и это же делало набор непригодным для gate.
    (1, "харнесс снова передаёт --dump-dom (Edge 150 отдаёт пустой документ)",
     [(SLF, "engine: ENGINE });", "engine: ENGINE, extraArgs: ['--dump-dom'] });")],
     BRIDGE, "overlay"),
    # Отказ браузера обязан оставаться КРАСНЫМ, даже если харнесс превратит его в SKIP: страховкой
    # служит финальная проверка «все 6 сценариев реально исполнены». Отказ сделан мгновенным
    # (несуществующая страница, 3 c) — прежде тот же смысл стоил 380 c.
    (2, "отказ браузера снова превращается в пропуск вместо красной проверки",
     # Ломать надо ТОЛЬКО чтение: стенд пишется и читается по одной переменной, поэтому
     # переименование пути ничего не ломает — файл просто создаётся под новым именем.
     [(SLF, "out = await measure({ url: pathToFileURL(pg).href,",
       "out = await measure({ url: pathToFileURL(pg + '.НЕТ').href,"),
      (SLF, "if (!out) { check(`SL. ${theme}/${w}: стенд выполнен в реальном браузере`, false); console.log('   причина: ' + err); continue; }",
       "if (!out) { console.log('SKIP — SL. ' + theme + '/' + w + ' [headless не вернул результат]'); continue; }")],
     SL, "browser"),
    # Прежний мост (до 2.835) на таймауте команды CDP молча отдавал пустой ответ — и харнесс
    # получал «результат», которого не было. Возвращаем ровно это поведение и проверяем прямо
    # в контракте моста (B2), а не через шесть сценариев чужого харнесса.
    (3, "таймаут команды CDP молча игнорируется (пустой ответ вместо ошибки)",
     [(LIB, "        reject(new Error('CDP timeout ' + timeoutMs + 'ms: ' + method));",
       "        resolve({});")],
     BRIDGE, "overlay"),
    (4, "страница печатает ошибку в консоль",
     [(SLF, "try {\n  const w = document.querySelector",
       "try {\n  console.error('FM_MUTATION_CONSOLE_ERROR');\n  const w = document.querySelector")],
     SL, "browser"),
    (5, "страница печатает предупреждение Vue",
     [(SLF, "try {\n  const w = document.querySelector",
       "try {\n  console.warn('[Vue warn] FM_MUTATION_VUE_WARNING');\n  const w = document.querySelector")],
     SL, "browser"),
    (6, "один из браузерных сценариев не исполняется (выпал из набора)",
     [(HLF, "for (const first of ['ext', 'empty']) for (const theme of ['dark', 'light']) for (const w of [1366, 1920]) CASES.push([theme, first, w, 0]);",
       "for (const first of ['ext']) for (const theme of ['dark', 'light']) for (const w of [1366, 1920]) CASES.push([theme, first, w, 0]);")],
     HL, "browser"),
    (7, "корню интерфейса снова разрешена прокрутка — верхний бар уезжает",
     [(CSS, "  overflow:hidden !important;           /* лишнее обрезается здесь, а не выносится в корень */",
       "  overflow:auto !important;             /* лишнее обрезается здесь, а не выносится в корень */")],
     TOPBAR, "browser"),
    (8, "настройки снова получают четыре колонки на 3440",
     [(CSS, "repeat(auto-fit,minmax(min(360px,100%),1fr))", "repeat(4,1fr)")],
     LAYOUT, "browser"),
    (9, ".fm-chk снова получает flex-basis 240px (строки-флажки раздуваются)",
     [(CSS, ".fm-chk{display:flex;align-items:flex-start;gap:10px;min-width:0;flex:0 0 auto;",
       ".fm-chk{display:flex;align-items:flex-start;gap:10px;min-width:0;flex:1 1 240px;")],
     LAYOUT, "browser"),
    (10, "фикс кадра #app снимается (корень снова в потоке)",
     [(CSS, FRAME_RULE, "html.m-ui #app{ position:static; }")],
     FRAME, "browser"),
    (11, "нижнее содержимое области настроек становится недоступным",
     [(CSS, ".fm-set-scroll{flex:1 1 auto;min-height:0;overflow-y:auto;overscroll-behavior:contain}",
       ".fm-set-scroll{flex:1 1 auto;min-height:0;overflow-y:hidden;overscroll-behavior:contain}")],
     FRAME, "browser"),
    (12, "появляется горизонтальная прокрутка области настроек",
     [(CSS, "@@APPEND@@", "\r\nhtml.m-ui .fm-set-scroll .fm-set-grid{min-width:2400px}\r\n")],
     FRAME, "browser"),
]


def sha(path):
    return hashlib.sha256(io.open(path, "rb").read()).hexdigest()


def read(path):
    return io.open(path, encoding="utf-8", errors="surrogateescape", newline="").read()


def write(path, text):
    io.open(path, "w", encoding="utf-8", errors="surrogateescape", newline="").write(text)


NODE = next((p for p in (r"C:\Program Files\nodejs\node.exe",
                         r"C:\Program Files (x86)\nodejs\node.exe")
             if os.path.isfile(p)), None) or shutil.which("node")


def run_test(rel, mode, cwd=None, env_extra=None):
    """Один прогон целевого теста. → (rc, хвост, секунды).

    rc = -9 означает ТАЙМАУТ и трактуется вызывающей стороной как отказ САМОГО НАБОРА:
    зависшая проверка ничего не доказывает и «пойманной поломкой» быть не может.
    """
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.pop("FM_LAYOUT_NO_BROWSER", None)
    env.pop("FM_TOPBAR_NO_BROWSER", None)
    if mode == "static":
        env["FM_LAYOUT_NO_BROWSER"] = "1"
        env["FM_TOPBAR_NO_BROWSER"] = "1"
    env.update(env_extra or {})
    target = rel if not cwd else os.path.join(cwd, os.path.basename(rel))
    cmd = [NODE, target] if rel.endswith(".mjs") else [sys.executable, target]
    t0 = time.monotonic()
    try:
        pr = subprocess.run(cmd, cwd=(cwd or REPO), env=env, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL,
                            timeout=(T_STATIC if mode == "static" else T_BROWSER))
        out = (pr.stdout or "")
        tail = [ln for ln in out.splitlines() if ln.startswith("ИТОГО") or ln.startswith("FAIL")]
        return pr.returncode, (tail[-1] if tail else (pr.stderr or out)[-140:].replace("\n", " ")), \
            time.monotonic() - t0
    except subprocess.TimeoutExpired:
        return -9, "ТАЙМАУТ %d c" % (T_STATIC if mode == "static" else T_BROWSER), \
            time.monotonic() - t0


# Поломки намеренно ломают сам мост, поэтому часть headless-движков переживает прогон. Убираем их
# ПОСЛЕ КАЖДОЙ поломки: иначе процессы копятся сотнями, машина захлёбывается и следующие измерения
# начинают плавать. Снимаются ТОЛЬКО процессы с нашими временными профилями — пользовательский
# браузер не затрагивается: глобального kill по имени процесса здесь нет и быть не должно.
def _sweep_engines():
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='msedge.exe' OR Name='chrome.exe'\" | "
          "Where-Object { $_.CommandLine -and ($_.CommandLine -match 'fm-cdp-' -or "
          "$_.CommandLine -match 'fm_cdp_' -or $_.CommandLine -match 'fm_stage835_' -or "
          "$_.CommandLine -match 'fm-bridge-' -or $_.CommandLine -match 'fm-inv-') } | "
          "ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop } catch {} }")
    try:
        subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps],
                       capture_output=True, timeout=60, stdin=subprocess.DEVNULL)
    except Exception:
        pass


print("Alpha 2.835/2.840 — mutation proof браузерного release gate")
print("Метка: %s" % SENTINEL)
print("Окна: static %d c, browser %d c, весь набор %d c" % (T_STATIC, T_BROWSER, T_TOTAL))
print("=" * 100)

FILES = sorted({f for _n, _d, edits, _t, m in MUTATIONS if m != "overlay"
                for f, _o, _x in edits})

# ЖУРНАЛ ЦЕЛОСТНОСТИ. Поломки правят настоящие файлы репозитория, и если процесс убьют извне
# (таймаут внешнего прогона, снятие задачи), `finally` не выполнится и файл останется испорченным —
# это однажды уже случилось. Поэтому перед первой правкой пристойные копии кладутся рядом, а КАЖДЫЙ
# запуск начинается с проверки: остался ли журнал от прерванного прогона.
_JOURNAL = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".mutation_pristine")


def _journal_save(files):
    os.makedirs(_JOURNAL, exist_ok=True)
    for f in files:
        with io.open(os.path.join(_JOURNAL, os.path.basename(f)), "wb") as fh:
            fh.write(io.open(f, "rb").read())


def _journal_restore_if_any(files):
    if not os.path.isdir(_JOURNAL):
        return []
    restored = []
    for f in files:
        src = os.path.join(_JOURNAL, os.path.basename(f))
        if os.path.isfile(src):
            data = io.open(src, "rb").read()
            if data != io.open(f, "rb").read():
                io.open(f, "wb").write(data)
                restored.append(os.path.basename(f))
    return restored


def _journal_clear():
    try:
        shutil.rmtree(_JOURNAL)
    except Exception:
        pass


_recovered = _journal_restore_if_any(FILES)
if _recovered:
    print("ВОССТАНОВЛЕНО после прерванного прогона: %s" % ", ".join(_recovered))
_journal_clear()

base = {p: (read(p), sha(p)) for p in FILES}
_journal_save(FILES)

_restore_done = {"v": False}


def _restore_all():
    """Вернуть все тронутые файлы к исходному состоянию. Идемпотентна и безопасна для повтора."""
    if _restore_done["v"]:
        return
    for p in FILES:
        try:
            if sha(p) != base[p][1]:
                write(p, base[p][0])
        except Exception:
            pass
    _journal_clear()


# Откат обязан произойти и при Ctrl+C, и при внешнем сигнале завершения, а не только в `finally`.
def _on_signal(signum, _frame):
    _restore_all()
    print("\nПРЕРВАНО сигналом %s — файлы восстановлены" % signum)
    sys.exit(1)


for _sig in ("SIGINT", "SIGTERM", "SIGBREAK"):
    _s = getattr(signal, _sig, None)
    if _s is not None:
        try:
            signal.signal(_s, _on_signal)
        except Exception:
            pass
atexit.register(_restore_all)

MJS_TOOLS = [n for n in os.listdir(os.path.join(REPO, "tools")) if n.endswith(".mjs")]


def _overlay_dir():
    """Копия всей .mjs-оснастки во временной папке: поломка не касается рабочего дерева."""
    d = tempfile.mkdtemp(prefix="fm-mutoverlay-")
    for n in MJS_TOOLS:
        shutil.copy2(os.path.join(REPO, "tools", n), os.path.join(d, n))
    return d


caught, missed, harness_errors = 0, [], []
planned = [0]          # сколько поломок реально взято в работу (FM_MUT_ONLY сужает набор)
t_start = time.monotonic()
try:
    _only = {int(x) for x in (os.environ.get("FM_MUT_ONLY") or "").replace(" ", "").split(",") if x}
    for num, why, edits, rel, mode in MUTATIONS:
        if _only and num not in _only:
            continue
        planned[0] += 1
        if time.monotonic() - t_start > T_TOTAL:
            harness_errors.append((num, why, "превышен общий потолок %d c" % T_TOTAL))
            break
        overlay = _overlay_dir() if mode == "overlay" else None
        touched, ok_applied = [], True
        try:
            for path, old, new in edits:
                target = os.path.join(overlay, os.path.basename(path)) if overlay else path
                src = read(target)
                if old == "@@APPEND@@":      # дописать в конец: каскад побеждает, статика молчит
                    write(target, src + new)
                    if not overlay:
                        touched.append(path)
                    continue
                if src.count(old) != 1:
                    print("%2d. ПОЛОМКА НЕ ПРИМЕНЕНА (якорь встречается %d раз): %s"
                          % (num, src.count(old), why))
                    ok_applied = False
                    break
                write(target, src.replace(old, new, 1))
                if not overlay:
                    touched.append(path)
            if not ok_applied:
                harness_errors.append((num, why, "якорь не найден или не уникален"))
                for p in touched:
                    write(p, base[p][0])
                continue
            rc, tail, secs = run_test(rel, "browser" if mode == "overlay" else mode, cwd=overlay)
        finally:
            for p in touched:              # откат ДО оценки: файлы не должны остаться битыми
                write(p, base[p][0])
            if overlay:
                shutil.rmtree(overlay, ignore_errors=True)
        _sweep_engines()                   # и сразу убрать движки, переживших сломанный мост
        # Побайтовая сверка ПОСЛЕ КАЖДОЙ поломки, а не только в конце: испорченный файл не должен
        # дожить до следующей проверки и отравить её результат.
        broken = [os.path.basename(p) for p in FILES if sha(p) != base[p][1]]
        if broken:
            harness_errors.append((num, why, "файлы не восстановлены: %s" % ", ".join(broken)))
        if rc == -9:
            harness_errors.append((num, why, tail))
            verdict = "ТАЙМАУТ"
        elif rc != 0:
            caught += 1
            verdict = "ПОЙМАНА"
        else:
            missed.append((num, why, tail))
            verdict = "ПРОПУЩЕНА"
        print("%2d. %-9s %-40s -> rc=%-3s %6.1f c  %s"
              % (num, verdict, os.path.basename(rel), rc, secs, tail[:60]))
        print("      %s" % why)
finally:
    _restore_all()
    _restore_done["v"] = True

elapsed = time.monotonic() - t_start
print("=" * 100)
bad_sha = [p for p in FILES if sha(p) != base[p][1]]
print("Побайтовое восстановление (SHA-256):")
for p in FILES:
    print("   %-34s %s  %s" % (os.path.basename(p), sha(p),
                               "OK" if sha(p) == base[p][1] else "РАСХОЖДЕНИЕ"))
print("МЕТКА: %s" % SENTINEL)
print("ИТОГО: ПОЙМАНО %d из %d за %.0f c" % (caught, planned[0], elapsed))
if missed:
    print("НЕ ПОЙМАНЫ (мутация не покраснела):")
    for num, why, tail in missed:
        print("   %2d. %s :: %s" % (num, why, tail))
if harness_errors:
    print("ОТКАЗ САМОГО НАБОРА (таймаут / якорь / откат):")
    for num, why, tail in harness_errors:
        print("   %2d. %s :: %s" % (num, why, tail))
if bad_sha:
    print("ФАЙЛЫ НЕ ВОССТАНОВЛЕНЫ: %s" % bad_sha)
# Alpha 2.841: FM_MUT_ONLY — отладочное СУЖЕНИЕ набора, и раньше оно молча делало прогон
# вакуумным: `planned[0]` считался ПОСЛЕ фильтра, поэтому запуск с FM_MUT_ONLY=1 исполнял одну
# поломку из 12, печатал «ПОЙМАНО 1 из 1» и выходил НУЛЁМ. Релизный gate, читающий только код
# возврата, видел полный успех. Теперь число исполненных сверяется с ОБЪЯВЛЕННЫМ len(MUTATIONS).
if planned[0] != len(MUTATIONS):
    print("ЧИСЛО ИСПОЛНЕННЫХ ПОЛОМОК %d != объявленных %d — набор недоказателен"
          "%s." % (planned[0], len(MUTATIONS),
                   " (FM_MUT_ONLY — отладочный режим)" if _only else ""))
# Прежнее условие выхода сохранено дословно; ниже к нему добавляется process_rc из сводки.
_rc_prev = 0 if (planned[0] == len(MUTATIONS) and caught == planned[0] and not bad_sha
                 and not missed and not harness_errors) else 1
# declared — объявлено поломок (len(MUTATIONS)); executed — реально исполнено (planned[0], сужается
# FM_MUT_ONLY); caught — покрасневшие целевые тесты; timeouts — отказы САМОГО набора (таймаут /
# якорь / несостоявшийся откат) из harness_errors; restore_failures — файлы, не вернувшиеся к
# исходным байтам (bad_sha). Отдельного счётчика уборки в наборе нет → cleanup_failures=0.
_summary = _mut_build(declared=len(MUTATIONS),
                      executed=planned[0],
                      caught=caught,
                      timeouts=len(harness_errors),
                      restore_failures=len(bad_sha),
                      cleanup_failures=0)
_rc = _mut_emit(_summary)
sys.exit(_rc_prev or _rc)
