# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""16.10.2026 (R-143) — каждая причина в журнале склада переводится в английском интерфейсе.

ЗАЧЕМ. Склад пишет в журнал (inv_ledger.reason) русские служебные фразы: «печать (авто)»,
«возврат: печать остановлена на ~42%», «списание пустой катушки · мобильный клиент» и другие.
Хранятся они по-русски навсегда: по ним считается расход. В английском интерфейсе окно истории
переводит их функцией systemText (modules/inventory/web/InventoryI18n.js) — по точному словарю и
по шаблонам с числами. Новая причина без перевода тихо показалась бы англоязычному пользователю
по-русски, и узнали бы об этом на ферме. Этот набор собирает причины из САМОГО кода модуля и
прогоняет их через настоящий переводчик.

Что проверяется исполнением:
  1. Из backend.py и mobile_api.py разбором кода (AST) собираются все русские причины журнала:
     аргументы записи INSERT INTO inv_ledger (в том числе через переменную и через параметр
     функции — по всем местам вызова), значения ключей "reason"/"notes" в готовых шагах ответа,
     причины закрытия печати (_pending_finalize). Шаблоны «… ~%d г», «… ~%s%%» заполняются
     пробными числами — так, как их заполнит программа.
  2. Каждая причина через systemText(…, 'en') (node, настоящий модуль) даёт текст без русских
     букв; в русском интерфейсе — без изменений.
  3. Непустота: набор находит заведомо известные причины (автосписание, возвраты, телефон), а
     выдуманная новая причина без перевода признаётся дефектом.

БЕЗОПАСНОСТЬ: только чтение исходников; ни сервера, ни базы, ни принтеров.

Запуск:  python tools/test_inventory_i18n_reasons.py      (0 = всё в порядке)
"""
import ast
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MOD = os.path.join(ROOT, "modules", "inventory")
I18N = os.path.join(MOD, "web", "InventoryI18n.js")
CYR = re.compile(u"[\u0400-\u04FF]")

PASS, FAILS = [0], []


def check(name, cond, detail=""):
    if cond:
        PASS[0] += 1
        print("PASS — %s" % name)
    else:
        FAILS.append(name)
        print("FAIL — %s%s" % (name, ("  :: %s" % (detail,))[:900] if detail != "" else ""))


#  Пробные значения для шаблонов: целое — граммы и номер слота, строка — процент (pct_txt).
SAMPLES = {"d": "7", "i": "7", "s": "42", "f": "12.5"}


def fill(fmt):
    """«…~%d г» -> «…~7 г»; «%%» -> «%»; «%.1f» -> «12.5». Как оператор % Python с пробными числами."""
    def rep(m):
        if m.group(0) == "%%":
            return "%"
        conv = m.group(0)[-1]
        return SAMPLES.get(conv, "7")
    return re.sub(r"%%|%[-+ #0]*\d*(?:\.\d+)?[disf]", rep, fmt)


class Collector:
    """Сбор причин журнала из одного модуля Python (без исполнения)."""

    def __init__(self, path):
        self.path = path
        self.tree = ast.parse(io.open(path, encoding="utf-8").read(), path)
        self.funcs = {n.name: n for n in ast.walk(self.tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        self.parent = {}
        for node in ast.walk(self.tree):
            for ch in ast.iter_child_nodes(node):
                self.parent[ch] = node
        self.found = {}   # текст -> откуда

    def func_of(self, node):
        while node in self.parent:
            node = self.parent[node]
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return node
        return None

    def expand(self, expr, scope, depth=0):
        """Выражение -> список возможных строк."""
        if depth > 6 or expr is None:
            return []
        if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
            return [expr.value]
        if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Mod) and isinstance(expr.left, ast.Constant) \
                and isinstance(expr.left.value, str):
            return [fill(expr.left.value)]
        if isinstance(expr, ast.JoinedStr):
            return ["".join(v.value if isinstance(v, ast.Constant) else SAMPLES["d"] for v in expr.values)]
        if isinstance(expr, ast.IfExp):
            return self.expand(expr.body, scope, depth + 1) + self.expand(expr.orelse, scope, depth + 1)
        if isinstance(expr, ast.BoolOp):
            return [s for v in expr.values for s in self.expand(v, scope, depth + 1)]
        if isinstance(expr, ast.Name) and scope is not None:
            out = []
            for n in ast.walk(scope):
                if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == expr.id for t in n.targets):
                    out += self.expand(n.value, scope, depth + 1)
            params = [a.arg for a in scope.args.args + scope.args.kwonlyargs]
            if expr.id in params:
                out += self.call_args(scope.name, expr.id, params.index(expr.id), depth + 1)
            return out
        return []

    def call_args(self, fname, pname, pos, depth):
        """Значения параметра pname функции fname по всем местам её вызова в модуле."""
        out = []
        for n in ast.walk(self.tree):
            if isinstance(n, ast.Call) and ((isinstance(n.func, ast.Name) and n.func.id == fname)
                                            or (isinstance(n.func, ast.Attribute) and n.func.attr == fname)):
                arg = None
                if pos < len(n.args):
                    arg = n.args[pos]
                for kw in n.keywords:
                    if kw.arg == pname:
                        arg = kw.value
                if arg is not None:
                    out += self.expand(arg, self.func_of(n), depth)
        return out

    def add(self, texts, where):
        for t in texts:
            if isinstance(t, str) and CYR.search(t):
                self.found.setdefault(t, where)

    def run(self):
        for n in ast.walk(self.tree):
            #  1) запись в журнал: execute("INSERT INTO inv_ledger …", (…))
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "execute" \
                    and n.args and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str) \
                    and "inv_ledger" in n.args[0].value and "INSERT" in n.args[0].value.upper() and len(n.args) > 1:
                params = n.args[1]
                elts = params.elts if isinstance(params, (ast.Tuple, ast.List)) else [params]
                scope = self.func_of(n)
                for e in elts:
                    self.add(self.expand(e, scope), "%s:%d журнал" % (os.path.basename(self.path), n.lineno))
            #  2) готовые шаги ответа: {"reason": "…"} / {"notes": "…"}
            if isinstance(n, ast.Dict):
                for k, v in zip(n.keys, n.values):
                    if isinstance(k, ast.Constant) and k.value in ("reason", "notes"):
                        self.add(self.expand(v, self.func_of(n)), "%s:%d %s" % (os.path.basename(self.path), n.lineno, k.value))
        #  3) причины закрытия печати: _pending_finalize(row, доля, причина)
        if "_pending_finalize" in self.funcs:
            self.add(self.call_args("_pending_finalize", "why", 2, 0), "%s _pending_finalize" % os.path.basename(self.path))
        return self.found


def translate(texts):
    """-> {текст: {"en": …, "ru": …}} через настоящий systemText модуля (node)."""
    node = shutil.which("node") or r"C:\Program Files\nodejs\node.exe"
    td = tempfile.mkdtemp(prefix="fm_inv_i18n_")
    try:
        mjs = os.path.join(td, "run.mjs")
        url = "file:///" + I18N.replace("\\", "/").lstrip("/")
        io.open(mjs, "w", encoding="utf-8").write(
            "import { systemText } from %s;\n" % json.dumps(url)
            + "const T = %s;\n" % json.dumps(texts, ensure_ascii=False)
            + "const out = {};\n"
            + "for (const t of T) out[t] = { en: systemText(t, 'en'), ru: systemText(t, 'ru') };\n"
            + "console.log(JSON.stringify(out));\n")
        p = subprocess.run([node, mjs], capture_output=True, text=True, encoding="utf-8", timeout=60)
        try:
            return json.loads(p.stdout.strip().splitlines()[-1]), ""
        except Exception:
            return None, (p.stdout[-200:] + p.stderr[-500:])
    finally:
        shutil.rmtree(td, ignore_errors=True)


print("--- 1. причины журнала собраны из кода модуля ---")
FOUND = {}
for f in ("backend.py", "mobile_api.py"):
    FOUND.update(Collector(os.path.join(MOD, f)).run())
for t in sorted(FOUND):
    print("      %s  ← %s" % (t, FOUND[t]))
MUST = ["печать (авто)", "возврат: печать не началась", "возврат: сменила новая печать (было ~42%)",
        "возврат: печать остановлена на ~42%", "замена катушки: снята с принтера (остаток ~7 г)",
        "замена катушки: установлена в слот 7", "списание пустой катушки · мобильный клиент",
        "снятие катушки · мобильный клиент", "приход", "расход", "печать завершена"]
check("1. найдены %d причин, среди них заведомо известные (автосписание, возвраты, замена, телефон)" % len(FOUND),
      len(FOUND) >= 15 and all(m in FOUND for m in MUST), [m for m in MUST if m not in FOUND])

print("--- 2. каждая переводится в английском интерфейсе ---")
PROBE = "новая причина без перевода: проверка набора"
TR, ERR = translate(sorted(FOUND) + [PROBE])
check("2. переводчик модуля исполнился в node", isinstance(TR, dict), ERR)
TR = TR or {}
untranslated = [t for t in sorted(FOUND) if not TR.get(t) or CYR.search(TR[t].get("en") or "") or not (TR[t].get("en") or "").strip()]
check("3. ни одна причина не осталась русской в английском интерфейсе", not untranslated,
      ["%s → %s" % (t, (TR.get(t) or {}).get("en")) for t in untranslated[:10]])
changed_ru = [t for t in sorted(FOUND) if (TR.get(t) or {}).get("ru") != t]
check("4. в русском интерфейсе причины показываются как записаны", not changed_ru, changed_ru[:5])
#  Числа из шаблона доходят до перевода, а не теряются.
check("5. числа шаблонов сохраняются в переводе (~42%, ~7 г, слот 7)",
      "42" in ((TR.get("возврат: печать остановлена на ~42%") or {}).get("en") or "")
      and "7" in ((TR.get("замена катушки: снята с принтера (остаток ~7 г)") or {}).get("en") or "")
      and "7" in ((TR.get("замена катушки: установлена в слот 7") or {}).get("en") or ""),
      {k: (TR.get(k) or {}).get("en") for k in ("возврат: печать остановлена на ~42%",
                                                 "замена катушки: снята с принтера (остаток ~7 г)")})

print("--- 3. непустота ---")
check("6. выдуманная причина без перевода признаётся дефектом",
      bool(CYR.search(((TR.get(PROBE) or {}).get("en")) or PROBE)), TR.get(PROBE))
_src = "def f(conn, x):\n    conn.execute('INSERT INTO inv_ledger (reason) VALUES (?)', (x,))\n\nf(c, 'тестовая причина %d' % 5)\n"
_td = tempfile.mkdtemp(prefix="fm_inv_i18n_c_")
try:
    _p = os.path.join(_td, "m.py")
    io.open(_p, "w", encoding="utf-8").write(_src)
    _f = Collector(_p).run()
finally:
    shutil.rmtree(_td, ignore_errors=True)
check("7. сборщик доходит до причины через параметр функции и шаблон", "тестовая причина 7" in _f, _f)

print("\n" + "=" * 78)
print("ИТОГО: PASS=%d FAIL=%d" % (PASS[0], len(FAILS)))
for f in FAILS:
    print("  ПРОВАЛ: %s" % f)
sys.exit(1 if FAILS else 0)
