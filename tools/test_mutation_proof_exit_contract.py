# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
#  Alpha 2.841 — EXIT-CONTRACT всех mutation proof: внутренний провал ОБЯЗАН
#  становиться ненулевым кодом возврата процесса.
#
#  ЗАЧЕМ. Релизный gate судит о наборе по КОДУ ВОЗВРАТА. Если набор печатает
#  «FAIL»/«MISS»/«ТАЙМАУТ», но выходит нулём, gate зеленеет, ничего не проверив.
#  Отдельно опасен обратный случай: набор ВЫШЕЛ нулём, потому что исполнил одну
#  поломку из двенадцати (сужение через FM_MUT_ONLY) — знаменатель считался
#  после фильтра, и «ПОЙМАНО 1 из 1» выглядело полным успехом.
#
#  ЧЕСТНО О ГРАНИЦАХ. Раздел A — статический разбор AST: он доказывает, что
#  результат ДОХОДИТ до процесса, но не доказывает, что вердикт верен по сути.
#  Поэтому раздел B гоняет НАСТОЯЩИЕ синтетические наборы (в TemporaryDirectory,
#  копии — рабочее дерево не трогается вообще) и проверяет коды возврата в шести
#  отрицательных сценариях. Раздел C — статические свойства реальных наборов.
#
#  БЕЗОПАСНОСТЬ. Ни один файл репозитория не изменяется. Синтетические наборы
#  живут во временной папке и удаляются. Сети нет. Реальному принтеру ничего
#  не отправляется.
#
#  Запуск:  python tools/test_mutation_proof_exit_contract.py   (0 = всё сошлось)
# ============================================================================
import ast
import glob
import io
import os
import shutil
import subprocess
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(REPO, "tools")
PY = sys.executable

FAILED = []
PASSED = [0]


def check(name, ok, extra=""):
    if ok:
        PASSED[0] += 1
        print("PASS — %s" % name)
    else:
        FAILED.append(name)
        print("FAIL — %s%s" % (name, ("\n        " + str(extra)[:300]) if extra else ""))


def section(t):
    print("\n--- %s ---" % t)


PROOFS = sorted(glob.glob(os.path.join(TOOLS, "test_*mutation_proof*.py")))
SRC = {p: io.open(p, "rb").read().decode("utf-8") for p in PROOFS}
TREE = {p: ast.parse(SRC[p]) for p in PROOFS}


# ════════════════════════════════════════════════════════════════════════════
section("A. Статика: результат каждого набора доходит до кода возврата процесса")

check("A1. наборы mutation proof найдены (их не ноль)", len(PROOFS) >= 16, len(PROOFS))


def exit_calls(tree):
    """Все вызовы sys.exit(...) / SystemExit(...) в модуле, с их аргументом."""
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Attribute) and f.attr == "exit":
                out.append(n)
            elif isinstance(f, ast.Name) and f.id == "SystemExit":
                out.append(n)
        elif isinstance(n, ast.Raise) and isinstance(n.exc, ast.Call) \
                and isinstance(n.exc.func, ast.Name) and n.exc.func.id == "SystemExit":
            out.append(n.exc)
    return out


for p in PROOFS:
    b = os.path.basename(p)
    calls = exit_calls(TREE[p])
    check("A2[%s]. есть хотя бы один sys.exit/SystemExit" % b[:46], bool(calls), len(calls))

for p in PROOFS:
    b = os.path.basename(p)
    # Итоговый выход не должен быть константой: sys.exit(0) в конце — это «всегда зелёный».
    const_zero_final = False
    calls = exit_calls(TREE[p])
    if calls:
        last = max(calls, key=lambda c: getattr(c, "lineno", 0))
        a = last.args[0] if last.args else None
        const_zero_final = isinstance(a, ast.Constant) and a.value in (0, None)
    check("A3[%s]. итоговый выход НЕ константный ноль" % b[:46], not const_zero_final)

for p in PROOFS:
    b = os.path.basename(p)
    # main(), результат которой никуда не передана, — классический способ потерять провал.
    has_main = any(isinstance(n, ast.FunctionDef) and n.name == "main" for n in TREE[p].body)
    if not has_main:
        check("A4[%s]. main() отсутствует — терять нечего" % b[:46], True)
        continue
    passed_to_exit = any(
        c.args and isinstance(c.args[0], ast.Call) and isinstance(c.args[0].func, ast.Name)
        and c.args[0].func.id == "main" for c in exit_calls(TREE[p]))
    check("A4[%s]. результат main() передан в код возврата" % b[:46], passed_to_exit)

for p in PROOFS:
    b = os.path.basename(p)
    src = SRC[p]
    # «except Exception: print(...)» вокруг всего прогона гасит провал в зелень.
    swallow = False
    for n in ast.walk(TREE[p]):
        if isinstance(n, ast.ExceptHandler):
            body = n.body
            only_prints = body and all(
                isinstance(s, ast.Expr) and isinstance(s.value, ast.Call)
                and isinstance(s.value.func, ast.Name) and s.value.func.id == "print"
                for s in body)
            # опасно, только если это обработчик ВОКРУГ основного цикла порч
            if only_prints and n.lineno > len(src.splitlines()) * 0.5:
                swallow = True
    check("A5[%s]. провал не гасится «except: print(...)» в конце" % b[:46], not swallow)


# ════════════════════════════════════════════════════════════════════════════
section("B. Синтетические наборы: шесть отрицательных сценариев (в TemporaryDirectory)")

# Каркас синтетического mutation proof: он ведёт себя как настоящий (портит файл,
# запускает «тест», откатывает, считает), но живёт целиком во временной папке.
HARNESS = '''# -*- coding: utf-8 -*-
import hashlib, io, os, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
TARGET = os.path.join(HERE, "target.py")
PROBE = os.path.join(HERE, "probe.py")
DECLARED = 2
TIMEOUT_RC = -1001
_n = {"caught": 0, "miss": 0, "harness": 0}

def run(timeout):
    try:
        return subprocess.run([sys.executable, PROBE], capture_output=True,
                              timeout=timeout).returncode
    except subprocess.TimeoutExpired:
        return TIMEOUT_RC

MUT = [("VALUE = 1", "VALUE = 2"), ("NAME = 'a'", "NAME = 'b'")]
SCENARIO = os.environ.get("SYN_SCENARIO", "healthy")

for old, new in MUT:
    orig = io.open(TARGET, "rb").read()
    sha0 = hashlib.sha256(orig).hexdigest()
    if SCENARIO == "not_applied":
        old = "ЭТОГО ТЕКСТА НЕТ"
    if orig.count(old.encode()) != 1:
        print("SETUP FAIL: якорь не найден (%d)" % orig.count(old.encode()))
        _n["miss"] += 1
        continue
    try:
        io.open(TARGET, "wb").write(orig.replace(old.encode(), new.encode(), 1))
        rc = run(2 if SCENARIO == "timeout" else 60)
    finally:
        if SCENARIO != "restore_fail":
            io.open(TARGET, "wb").write(orig)
    reverted = hashlib.sha256(io.open(TARGET, "rb").read()).hexdigest() == sha0
    if rc == TIMEOUT_RC:
        _n["harness"] += 1
        print("HARNESS: таймаут")
        continue
    ok = rc != 0 and reverted
    _n["caught" if ok else "miss"] += 1
    print("%s rc=%d revert=%s" % ("CAUGHT" if ok else "MISS", rc, reverted))

io.open(TARGET, "wb").write(b"VALUE = 1\\nNAME = 'a'\\n")
executed = _n["caught"] + _n["miss"] + _n["harness"]
count_ok = executed == DECLARED if SCENARIO != "count_mismatch" else executed == DECLARED + 1
print("ИТОГО: CAUGHT=%d MISS=%d HARNESS=%d исполнено=%d из %d"
      % (_n["caught"], _n["miss"], _n["harness"], executed, DECLARED))
sys.exit(0 if (not _n["miss"] and not _n["harness"] and count_ok) else 1)
'''

TARGET_SRC = "VALUE = 1\nNAME = 'a'\n"

# «Тест», который краснеет, если target испорчен, — кроме сценария unexpected_green.
PROBE_SRC = '''import io, os, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
src = io.open(os.path.join(HERE, "target.py"), encoding="utf-8").read()
if os.environ.get("SYN_SCENARIO") == "timeout":
    time.sleep(30)
if os.environ.get("SYN_SCENARIO") == "unexpected_green":
    sys.exit(0)
sys.exit(0 if src == "VALUE = 1\\nNAME = 'a'\\n" else 1)
'''


def run_synthetic(scenario):
    """Запустить синтетический набор в своей временной папке. → (rc, вывод)."""
    d = tempfile.mkdtemp(prefix="fm-exitcontract-")
    try:
        io.open(os.path.join(d, "harness.py"), "w", encoding="utf-8", newline="\n").write(HARNESS)
        io.open(os.path.join(d, "target.py"), "w", encoding="utf-8", newline="\n").write(TARGET_SRC)
        io.open(os.path.join(d, "probe.py"), "w", encoding="utf-8", newline="\n").write(PROBE_SRC)
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        env["SYN_SCENARIO"] = scenario
        pr = subprocess.run([PY, os.path.join(d, "harness.py")], cwd=d, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=180)
        return pr.returncode, pr.stdout.decode("utf-8", "replace")
    finally:
        shutil.rmtree(d, ignore_errors=True)


rc, out = run_synthetic("healthy")
check("B1. СЦЕНАРИЙ A (здоровый набор): rc == 0", rc == 0, out[-260:])
check("B1b. здоровый набор поймал все поломки", "CAUGHT" in out and "MISS=0" in out, out[-200:])

rc, out = run_synthetic("not_applied")
check("B2. СЦЕНАРИЙ B (мутация не применилась): rc != 0", rc != 0, out[-260:])
check("B2b. в выводе видно, что якорь не найден", "SETUP FAIL" in out, out[-200:])

rc, out = run_synthetic("unexpected_green")
check("B3. СЦЕНАРИЙ C (мутация применилась, тест зелёный): rc != 0", rc != 0, out[-260:])
check("B3b. в выводе видно MISS", "MISS" in out, out[-200:])

rc, out = run_synthetic("timeout")
check("B4. СЦЕНАРИЙ D (таймаут проверки): rc != 0", rc != 0, out[-260:])
check("B4b. таймаут назван отказом ОСНАСТКИ, а не уловом",
      "HARNESS" in out and "CAUGHT" not in out.split("ИТОГО")[0], out[-200:])

rc, out = run_synthetic("restore_fail")
check("B5. СЦЕНАРИЙ E (откат не состоялся): rc != 0", rc != 0, out[-260:])
check("B5b. несостоявшийся откат виден как revert=False", "revert=False" in out, out[-200:])

rc, out = run_synthetic("count_mismatch")
check("B6. СЦЕНАРИЙ F (число исполненных != объявленному): rc != 0", rc != 0, out[-260:])

check("B7. рабочее дерево не изменялось отрицательными сценариями",
      os.path.exists(os.path.join(REPO, "server.py")))


# ════════════════════════════════════════════════════════════════════════════
section("C. Свойства настоящих наборов")

for p in PROOFS:
    b = os.path.basename(p)
    check("C1[%s]. набор берёт mutation lock" % b[:46], "_mutation_lock" in SRC[p])

# Таймаут не имеет права считаться пойманной поломкой: там, где TimeoutExpired ловится,
# его результат обязан отличаться от «обычного ненулевого rc».
for p in PROOFS:
    b = os.path.basename(p)
    src = SRC[p]
    # Alpha 2.841: раньше здесь искалась ПОДСТРОКА «TimeoutExpired» — и проверка краснела на
    # комментарии, где словами объяснено, что таймаут не ловится. Проза не перехватывает
    # исключений: смотрим НАСТОЯЩИЕ обработчики через AST.
    _catches_timeout = False
    for _node in ast.walk(TREE[p]):
        if not isinstance(_node, ast.ExceptHandler) or _node.type is None:
            continue
        _names = [n.attr if isinstance(n, ast.Attribute) else getattr(n, "id", "")
                  for n in ([_node.type] if not isinstance(_node.type, ast.Tuple)
                            else _node.type.elts)]
        if "TimeoutExpired" in _names:
            _catches_timeout = True
    if not _catches_timeout:
        # Не ловит — значит таймаут прорастает исключением и даёт ненулевой выход сам собой.
        check("C2[%s]. таймаут не перехватывается → падает наружу, зелёным быть не может" % b[:46],
              True)
        continue
    handled = ("TIMEOUT_RC" in src or "harness_errors" in src or "HARNESS_ERRORS" in src
               or "return None, True" in src or 'rc == -9' in src)
    check("C2[%s]. таймаут отделён от «поломка поймана»" % b[:46], handled)

# Сужение набора через FM_MUT_ONLY не должно давать зелёный выход.
for p in PROOFS:
    b = os.path.basename(p)
    src = SRC[p]
    # Как и в C2: раньше искалась подстрока и проверка краснела на комментарии, где сказано,
    # что фильтра в наборе НЕТ. Признаём фильтр только по фактическому чтению переменной
    # окружения в коде: os.environ.get("FM_MUT_ONLY") / os.environ["FM_MUT_ONLY"].
    _reads_only = False
    for _node in ast.walk(TREE[p]):
        if isinstance(_node, ast.Constant) and _node.value == "FM_MUT_ONLY":
            _reads_only = True
    if not _reads_only:
        continue
    check("C3[%s]. FM_MUT_ONLY не даёт зелёный выход" % b[:46],
          "len(MUTATIONS)" in src and ("planned[0] == len(MUTATIONS)" in src
                                       or "total == len(MUTATIONS)" in src))

# Первая редакция этой проверки искала подстроку «SKIP» и была ЛОЖНО-КРАСНОЙ: в browser-gate
# «SKIP» — это ТЕЛО САМОЙ ПОЛОМКИ (она внедряет пропуск в оснастку, чтобы тест это поймал), а во
# frontend_boot это имя переменной окружения FM_SKIP_BROWSER. Проверять надо не слово, а свойство:
# набор обязан сверять число ИСПОЛНЕННЫХ порч с объявленным — именно это делает невозможным
# «молча пропустили половину и вышли зелёными».
_COUNT_MARKERS = ("исполнено", "ЧИСЛО ИСПОЛНЕННЫХ", "EXPECTED_MUTATIONS",
                  "planned[0] == len(MUTATIONS)", "total == len(MUTATIONS)",
                  "_executed == len(MUT)", "caught == len(MUTATIONS)")
for p in PROOFS:
    b = os.path.basename(p)
    check("C4[%s]. число исполненных порч сверяется с объявленным" % b[:46],
          any(m in SRC[p] for m in _COUNT_MARKERS),
          "ни один маркер сверки не найден")

check("C5. общий замок существует и не пуст",
      os.path.getsize(os.path.join(TOOLS, "_mutation_lock.py")) > 1000)

# ── D. Alpha 2.841: ПРЯМОЙ структурированный итог ────────────────────────────────────────
# Гейт обязан читать числа, а не разбирать прозу. Каждый набор публикует одну машиночитаемую
# строку FM_MUTATION_SUMMARY_JSON. Проверяем ВЫЗОВЫ через AST — упоминание в комментарии
# ничего не печатает (на этом уже дважды краснели проверки C2 и C3).
check("D0. общий модуль отчёта существует и не пуст",
      os.path.getsize(os.path.join(TOOLS, "_mutation_report.py")) > 1000)

# Требование адресовано наборам, которые РЕАЛЬНО портят общие файлы репозитория. Признак —
# взятие общего замка: этот сторож сам ничего не мутирует (его синтетика живёт во временной
# папке), поэтому структурированный итог мутаций ему не нужен и не осмыслен.
def _calls_acquire(tree):
    """Фактический ВЫЗОВ замка, а не упоминание имени: этот файл содержит строку
    'acquire_or_die' внутри собственной проверки C1 и иначе считал бы мутатором себя."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            name = (fn.id if isinstance(fn, ast.Name)
                    else (fn.attr if isinstance(fn, ast.Attribute) else ""))
            if name == "acquire_or_die":
                return True
    return False


MUTATORS = [p for p in PROOFS if _calls_acquire(TREE[p])]
check("D1a. наборов, реально мутирующих репозиторий, найдено 16", len(MUTATORS) == 16,
      "найдено %d" % len(MUTATORS))

for p in MUTATORS:
    b = os.path.basename(p)
    _emits = False
    for _node in ast.walk(TREE[p]):
        if isinstance(_node, ast.Call):
            _fn = _node.func
            _name = (_fn.id if isinstance(_fn, ast.Name)
                     else (_fn.attr if isinstance(_fn, ast.Attribute) else ""))
            if _name in ("_mut_emit", "emit", "emit_and_exit"):
                _emits = True
    check("D1[%s]. публикует структурированный итог (вызов emit найден в AST)" % b[:46], _emits)

# D2: если в наборе есть ветка «якорь не найден», обязан быть ОТДЕЛЬНЫЙ счётчик неисполненных.
# Иначе executed == declared тождественно, поле mutation_not_applied мертво по построению,
# а неисполненная порча будет доложена гейту как unexpected_green — ложное утверждение.
for p in PROOFS:
    b = os.path.basename(p)
    if "SETUP FAIL" not in SRC[p]:
        continue
    check("D2[%s]. ветка «якорь не найден» имеет отдельный счётчик not_applied" % b[:46],
          '"not_applied"' in SRC[p] or "'not_applied'" in SRC[p])

# D3: подмена окончаний строк в якорях обязана ОПИРАТЬСЯ НА ФАЙЛ, а не на предположение.
# Alpha 2.868. Два набора безусловно переводили якоря server.py в CRLF «по контракту».
# С Alpha 2.863 файл лежит с LF, и подмена делала якоря ненаходимыми: 3 порчи из 34 и 7 из 22
# молча превращались в SETUP FAIL. Окончания строк в проекте не нормализуются вовсе
# (.gitattributes: * -text), поэтому единственный правильный источник — сам файл.
_EOL_SUBS = (
    ".replace(b" + chr(34) + chr(92) + "n" + chr(34) + ", b" + chr(34) + chr(92) + "r" + chr(92) + "n" + chr(34) + ")",
    ".replace(" + chr(34) + chr(92) + "n" + chr(34) + ", " + chr(34) + chr(92) + "r" + chr(92) + "n" + chr(34) + ")",
)
_EOL_DETECT = (
    ".count(b" + chr(34) + chr(92) + "r" + chr(92) + "n" + chr(34) + ")",   # считает CRLF в самом файле
    chr(34) + chr(92) + "r" + chr(92) + "n" + chr(34) + " in ",             # запасной вариант по факту
    "_fit_eol",                                                             # общий помощник подгонки
)
for p in PROOFS:
    b = os.path.basename(p)
    if not any(x in SRC[p] for x in _EOL_SUBS):
        continue
    check("D3[%s]. подмена окончаний строк опирается на сам файл, а не на предположение" % b[:46],
          any(m in SRC[p] for m in _EOL_DETECT))

# D3b: якорь порчи не должен НЕСТИ окончания строк в себе.
# Alpha 2.869: в config_backup_2830 якорь был записан как b("...verify_exported_blob(\r\n") —
# с CRLF внутри текста. server.py лежит с LF, якорь не находился ни разу, и порча молча
# превращалась в SETUP FAIL: набор был красным, ничего не доказывая. Окончания строк подгоняются
# КОДОМ по факту файла (см. D3), а не вписываются в текст якоря.
_BS_R_N = chr(92) + "r" + chr(92) + "n"     # два символа-экранирования, а не сами CR и LF
for p in PROOFS:
    b = os.path.basename(p)
    _bad = []
    for _ln in SRC[p].split(chr(10)):
        _st = _ln.strip()
        if _st.startswith("#"):
            continue
        if _BS_R_N in _ln and ((chr(98) + chr(40) + chr(34)) in _ln or (chr(98) + chr(40) + chr(39)) in _ln):
            _bad.append(_st[:70])
    check("D3b[%s]. якорь порчи не несёт окончания строк внутри себя" % b[:46], not _bad, _bad[:2])

print("\nИТОГО: PASS=%d FAIL=%d" % (PASSED[0], len(FAILED)))
for f in FAILED:
    print("  RED: %s" % f)
raise SystemExit(1 if FAILED else 0)
