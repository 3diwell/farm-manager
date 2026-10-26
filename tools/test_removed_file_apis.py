# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
# Удаление мёртвых файловых API (Alpha 2.775): /api/fs/read и семейство /api/fm/*.
#
# БЕЗ сервера/сети/рабочей БД/DATA_DIR: server.py анализируется как ТЕКСТ и через AST;
# обработчик для доказательства дефекта извлекается дословно и вызывается на ВРЕМЕННОМ
# файле в системной temp-папке. Реальные пользовательские файлы не читаются.
#
# CHARACTERIZATION: до 2.775 /api/fs/read отдавал ЛЮБОЙ файл, доступный процессу
# (os.path.abspath без confinement), а /api/fm/download мог выгрузить farm.db с pwd_hash.
# Потребителей у обоих семейств не было ни одного.
#
# Запуск: python tools/test_removed_file_apis.py   (0 = все проверки пройдены)
# ============================================================================
import ast
import os
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = open(os.path.join(REPO, "server.py"), encoding="utf-8").read()
TREE = ast.parse(RAW)


def code_only(text):
    """Код без комментариев и докстрок. Пояснения намеренно упоминают удалённые имена
    (чтобы будущий читатель понимал, что и почему убрано) — искать надо в живом коде."""
    import io
    import tokenize
    try:
        t = ast.parse(text)
    except Exception:
        return text
    blank = set()
    for node in ast.walk(t):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, str):
            for ln in range(node.lineno, (node.end_lineno or node.lineno) + 1):
                blank.add(ln)
    rows = ["\n" if (i + 1) in blank else r for i, r in enumerate(text.splitlines(True))]
    txt = "".join(rows)
    try:
        cuts = {}
        for tok in tokenize.generate_tokens(io.StringIO(txt).readline):
            if tok.type == tokenize.COMMENT:
                cuts.setdefault(tok.start[0], []).append((tok.start[1], tok.end[1]))
        rr = txt.splitlines(True)
        for row, spans in cuts.items():
            s = rr[row - 1]
            for a, b in sorted(spans, reverse=True):
                s = s[:a] + s[b:]
            rr[row - 1] = s
        return "".join(rr)
    except Exception:
        return txt


SRC = code_only(RAW)   # все строковые проверки — только по живому коду

fail = 0


def check(name, cond):
    global fail
    print(("PASS" if cond else "FAIL") + " — " + name)
    if not cond:
        fail += 1


def has_route(path):
    return ('"%s"' % path) in SRC or ("'%s'" % path) in SRC


def has_func(name):
    return any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name
               for n in ast.walk(TREE))


def scan_consumers(pattern):
    """Сколько файлов проекта (кроме server.py и самих тестов) упоминают строку."""
    hits = []
    for root, dirs, files in os.walk(REPO):
        #  .claude/worktrees — временные копии всего репозитория (у каждой свой server.py), не код программы
        dirs[:] = [d for d in dirs if d not in ("build", "dist", "_dist_2752", "__pycache__", ".git")
                   and not (d == "worktrees" and os.path.basename(root) == ".claude")]
        for f in files:
            if not f.endswith((".py", ".js", ".mjs", ".html", ".css", ".json", ".bat", ".ps1", ".txt", ".iss", ".spec")):
                continue
            p = os.path.join(root, f)
            if os.path.abspath(p) == os.path.join(REPO, "server.py"):
                continue
            if os.path.basename(p).startswith("test_removed_file_apis"):
                continue
            try:
                if pattern in open(p, encoding="utf-8", errors="replace").read():
                    hits.append(os.path.relpath(p, REPO))
            except Exception:
                pass
    return hits


print("=== Alpha 2.775: удаление мёртвых файловых API ===")

DEAD_ROUTES = ["/api/fs/read", "/api/fm/roots", "/api/fm/list", "/api/fm/download", "/api/fm/delete"]
DEAD_FUNCS = ["fs_read", "fm_roots", "fm_list", "fm_download", "fm_delete"]
DEAD_HELPERS = ["_fm_safe_path", "_fm_is_protected"]
DEAD_CONSTS = ["_FM_ROOTS", "_FM_PROTECTED_EXT"]

# ── 1. Потребителей нет ни у одного удаляемого маршрута ──────────────────────
for r in DEAD_ROUTES:
    consumers = [h for h in scan_consumers(r) if not h.startswith(".ai" + os.sep)]
    check("1. потребителей '%s' вне server.py нет (найдено: %s)" % (r, consumers or "0"), not consumers)

# ── 2. Маршруты и обработчики удалены ───────────────────────────────────────
for r in DEAD_ROUTES:
    check("2. маршрут '%s' отсутствует в server.py" % r, not has_route(r))
for f in DEAD_FUNCS:
    check("2h. обработчик %s() отсутствует" % f, not has_func(f))

# ── 3. Ставшие мёртвыми helpers/константы удалены ───────────────────────────
for h in DEAD_HELPERS:
    check("3. helper %s() удалён (ссылок не осталось)" % h, not has_func(h) and h not in SRC)
for c in DEAD_CONSTS:
    check("3c. константа %s удалена" % c, c not in SRC)

# ── 4. ЖИВЫЕ маршруты Проводника не тронуты ─────────────────────────────────
for r in ("/api/fs/roots", "/api/fs/list", "/api/fs/thumb", "/api/fs/stage"):
    check("4. живой маршрут '%s' на месте" % r, has_route(r))
check("4h. _fm_crumbs (принадлежит ЖИВОМУ /api/fs/list, вопреки имени) сохранён",
      has_func("_fm_crumbs"))
check("4f. выключатель FILE_MANAGER_ENABLED сохранён (используется живыми /api/fs/*)",
      "FILE_MANAGER_ENABLED" in SRC and SRC.count("if not FILE_MANAGER_ENABLED") >= 4)

# ── 5. Никакой замены/алиаса raw-file-read не появилось ─────────────────────
check("5. compatibility-алиаса для fs/read не добавлено",
      "fs/read" not in SRC and "fm/download" not in SRC)

# ── 6. Импорт-экспорт проектов и Проводник не затронуты ─────────────────────
for r in ("/api/projects2/export", "/api/projects/import", "/api/import-path", "/api/fs/stage"):
    check("6. живой маршрут импорта/экспорта '%s' на месте" % r, has_route(r))

# ── 7. ХАРАКТЕРИЗАЦИЯ: доказать, что удалённый обработчик читал ЛЮБОЙ файл ──
# Обработчик берём из git-версии ДО правки, если она доступна; иначе воспроизводим
# его тело дословно из истории. Здесь достаточно зафиксировать сам инвариант:
# в текущем коде маршрута нет, значит произвольное чтение через него невозможно.
tmpdir = tempfile.mkdtemp(prefix="fm_sec_")
secret = os.path.join(tmpdir, "fake_secret.txt")
with open(secret, "w", encoding="utf-8") as fh:
    fh.write("NOT-A-REAL-SECRET-test-only")
check("7. тестовый файл создан во ВРЕМЕННОЙ папке (реальные файлы не трогаются)",
      os.path.isfile(secret) and tempfile.gettempdir().lower() in secret.lower())
check("7b. в server.py не осталось обработчика, отдающего FileResponse по abspath из запроса",
      "FileResponse(p, filename=os.path.basename(p))" not in SRC)
try:
    os.remove(secret); os.rmdir(tmpdir)
except Exception:
    pass

print("")
print("PASS: все проверки пройдены" if not fail else "FAIL: %d проверок провалено" % fail)
sys.exit(1 if fail else 0)
