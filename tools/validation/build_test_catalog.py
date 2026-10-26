# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.841 / этап 2B: каталог безопасности тестов — что можно запускать автоматически.

ЗАЧЕМ. Исполнителю профиля нужен ответ на вопрос «безопасно ли запустить этот тест без
присмотра». Ответ нельзя брать из названия файла: `test_network_access_settings.py` читает
исходник и в сеть не ходит, а безобидное имя может скрывать запуск браузера. Поэтому
классификация строится по СОДЕРЖИМОМУ: дерево кода для Python, текстовый разбор для .mjs.

ГЛАВНОЕ ПРАВИЛО. Недоказанная безопасность — это НЕ безопасность. Любой признак, который
не удалось разобрать, даёт `unknown capability` и закрывает тест для автоматического
запуска. Текстовый разбор умеет только ДОБАВЛЯТЬ ограничения, снять их он не может:
ложное срабатывание стоит покрытия, пропуск стоит доверия.

ЧЕГО НЕ ДЕЛАЕТ. **Ни один тест не запускается.** Ничего не пишет без `--write`.
Продуктовые файлы не изменяет никогда.

    python tools/validation/build_test_catalog.py --check    # актуален ли каталог
    python tools/validation/build_test_catalog.py --write    # перестроить

Код возврата: 0 — каталог актуален (или записан); 1 — устарел; 2 — ошибка ввода.
"""
import argparse
import ast
import glob
import hashlib
import io
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
VALDIR = os.path.join(REPO, "tools", "validation")
CATALOG = os.path.join(VALDIR, "test_catalog.json")
OVERRIDES = os.path.join(VALDIR, "test_catalog_overrides.json")
RISK_MAP = os.path.join(VALDIR, "risk_map.json")

SCHEMA = "3diwell-test-catalog-v1"
# Версия классификатора. Меняется при любой правке логики распознавания — иначе старый
# каталог выглядел бы актуальным при новых правилах.
CLASSIFIER = "2b.4"      # 2b.4: адрес в данных без способа выйти в сеть больше не помеха

# Способности, каждая из которых закрывает автоматический запуск.
BLOCKING = ("browser", "local_server", "network", "mutation", "writes_repository",
            "build", "installer", "real_printer", "database_write", "shell_usage",
            "spawns_unknown", "git_write", "imports_server", "unknown_capability")

# Импорт -> способность. Упоминание модуля в строке ничего не значит: считается только
# настоящий импорт, иначе тест, который просто НАЗЫВАЕТ sqlite3, объявляется работающим с БД.
IMPORT_CAPS = {
    "sqlite3": ("database_write", "импортирует sqlite3"),
    "socket": ("network", "импортирует socket"),
    "ssl": ("network", "импортирует ssl"),
    "ftplib": ("network", "импортирует ftplib"),
    "requests": ("network", "импортирует requests"),
    "paho": ("network", "импортирует paho (MQTT)"),
    "websockets": ("network", "импортирует websockets"),
    "socketserver": ("local_server", "импортирует socketserver"),
    "uvicorn": ("local_server", "поднимает uvicorn"),
    "wsgiref": ("local_server", "импортирует wsgiref"),
    "PyInstaller": ("build", "импортирует PyInstaller"),
    "_mutation_lock": ("mutation", "использует общий замок mutation proof"),
    "_mutation_report": ("mutation", "публикует отчёт mutation proof"),
    "_edge_cdp": ("browser", "управляет браузером через CDP"),
    "_edge_dom": ("browser", "снимает DOM из браузера"),
    "_fm_ui_stage": ("browser", "поднимает UI-стенд"),
    # Импорт server.py смертелен для автоматики: при запущенной программе тест уходит
    # в sys.exit(0) на именованном мьютексе ДО проверок — код 0 без единой проверки.
    "server": ("imports_server", "импортирует server.py: при запущенной программе "
                                 "завершится кодом 0 до проверок (ложный зелёный)"),
}
_DOTTED_CAPS = (("urllib.request", ("network", "импортирует urllib.request")),
                ("http.client", ("network", "импортирует http.client")),
                ("http.server", ("local_server", "импортирует http.server")))

TIMEOUT_BY_KIND = (("mutation", 900), ("browser", 300), ("local_server", 240),
                   ("network", 180), ("build", 600))
DEFAULT_TIMEOUT = 120
SPAWN_TIMEOUT = 600
# Модули, надзирающие за дочерним процессом со стеновыми пределами. Импорт любого из них
# означает, что тест ждёт срабатывания предела, а не просто запускает подпроцесс.
SUPERVISOR_MODULES = ("process_runner", "windows_job", "process_qualification")

GIT_READONLY = {"ls-files", "status", "diff", "show", "rev-parse", "check-ignore",
                "cat-file", "log", "config", "describe", "merge-base", "hash-object"}

_WRITE_FUNCS = {"remove", "unlink", "rename", "replace", "rmdir", "makedirs", "mkdir",
                "rmtree", "copy", "copy2", "copyfile", "copytree", "move", "chmod",
                "truncate", "write_text", "write_bytes", "touch"}

# Признаки, которые ищутся в СТРОКОВЫХ ЛИТЕРАЛАХ Python и в тексте .mjs. Сюда попадает
# только то, что не бывает случайной прозой: имя исполняемого файла браузера, флаг запуска,
# адрес железа. Расширения вроде `.iss` намеренно НЕ проверяются строкой — тест, который
# просто читает файл установщика, установщик не собирает.
LITERAL_SIGNS = (
    ("browser", (r"msedge", r"chrome\.exe", r"chromium", r"--headless", r"remote-debugging",
                 r"puppeteer", r"playwright", r"webdriver")),
    ("build", (r"pyinstaller", r"--distpath", r"build\.bat")),
    ("installer", (r"\bISCC\b", r"Inno[ ]?Setup")),
    ("real_printer", (r":7125\b", r"\bmqtts?://", r"\b8883\b")),
    ("shell_usage", (r"powershell", r"cmd\.exe")),
)
_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_LOCAL_IP = re.compile(r"^(?:127\.\d+\.\d+\.\d+|0\.0\.0\.0|255\.255\.255\.255)$")


def _sha(path):
    return hashlib.sha256(io.open(path, "rb").read()).hexdigest()


# ── Разбор Python по дереву ──────────────────────────────────────────────────
class _PyScan(object):
    """Только чтение дерева. Ничего не импортирует и не исполняет."""

    def __init__(self):
        self.caps = dict((k, False) for k in BLOCKING)
        self.reasons = []
        self.spawns_process = False
        self.temp_names = set()

    def note(self, cap, why):
        if cap in self.caps:
            self.caps[cap] = True
        if why not in self.reasons:
            self.reasons.append(why)

    def scan_literals(self, values, where):
        """Признаки, которые ищутся только в строках — и только те, что не бывают прозой."""
        for cap, pats in LITERAL_SIGNS:
            if self.caps.get(cap):
                continue
            for v in values:
                m = None
                for p in pats:
                    m = re.search(p, v, re.IGNORECASE)
                    if m:
                        break
                if m:
                    self.note(cap, "%s (%s): %s" % (cap, where, m.group(0)[:40]))
                    break
        if not self.caps.get("real_printer"):
            #  Alpha 2.884. Адрес В ДАННЫХ и работа С ПРИНТЕРОМ — разные вещи. Раньше любой
            #  адрес в тексте закрывал набору автозапуск, и 14 наборов (все проверки резервного
            #  копирования в их числе) не выполнялись никогда из-за выдуманных фикстур.
            #  Опасным адрес становится тогда, когда набору есть ЧЕМ по нему пойти: сокет,
            #  http-клиент, собственный сервер, оболочка, подпроцесс или импорт server.py.
            #  Каждый из этих признаков классификатор находит отдельно и каждый сам по себе
            #  закрывает автозапуск — значит защита не ослабляется, а становится точнее.
            can_reach = bool(self.caps.get("network") or self.caps.get("local_server")
                             or self.caps.get("shell_usage") or self.caps.get("imports_server")
                             or self.caps.get("spawns_unknown") or self.spawns_process)
            for v in values:
                for ip in _IPV4.findall(v):
                    if not _LOCAL_IP.match(ip):
                        if can_reach:
                            self.note("real_printer", "адрес устройства в строке: %s" % ip)
                        else:
                            why = ("адрес в данных: %s — выйти в сеть набору нечем"
                                   " (ни сокета, ни http-клиента, ни подпроцесса)" % ip)
                            if why not in self.reasons:
                                self.reasons.append(why)
                        return

    # Значение выражения выводится из временного каталога?
    def is_temp(self, node):
        if isinstance(node, ast.Name):
            return node.id in self.temp_names
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            v = node.value.replace("\\", "/").lower()
            return "/temp/" in v or v.startswith("/tmp") or "/appdata/local/temp" in v
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Attribute):
                if isinstance(f.value, ast.Name) and f.value.id == "tempfile":
                    return True
                if f.attr == "join" and node.args:
                    return self.is_temp(node.args[0])
        if isinstance(node, ast.BinOp):
            return self.is_temp(node.left) or self.is_temp(node.right)
        if isinstance(node, ast.JoinedStr):
            return any(self.is_temp(v.value) for v in node.values
                       if isinstance(v, ast.FormattedValue))
        if isinstance(node, ast.Attribute):
            return isinstance(node.value, ast.Name) and node.value.id in self.temp_names
        return False

    def visit_assign(self, node):
        val = node.value
        temp = self.is_temp(val)
        if isinstance(val, ast.Call) and isinstance(val.func, ast.Attribute) \
                and isinstance(val.func.value, ast.Name) and val.func.value.id == "tempfile":
            temp = True
        if temp:
            for t in node.targets if isinstance(node, ast.Assign) else [node.target]:
                if isinstance(t, ast.Name):
                    self.temp_names.add(t.id)

    def visit_call(self, node):
        f = node.func
        owner = f.value.id if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) \
            else ""
        name = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name)
                                                            else "")
        for kw in node.keywords:
            if kw.arg == "shell" and not (isinstance(kw.value, ast.Constant)
                                          and kw.value.value is False):
                self.note("shell_usage", "subprocess с shell=True")

        if owner == "os" and name == "system":
            self.note("shell_usage", "os.system")
        if owner == "subprocess":
            self.spawns_process = True
            self._argv(node)
        if owner in ("os", "shutil", "pathlib") and name in _WRITE_FUNCS:
            tgt = node.args[0] if node.args else None
            if not (tgt is not None and self.is_temp(tgt)):
                self.note("writes_repository", "%s.%s вне доказуемо временного пути"
                          % (owner, name))
        if name in ("write_text", "write_bytes", "touch", "unlink", "mkdir") \
                and isinstance(f, ast.Attribute) and owner not in ("os", "shutil", "pathlib"):
            self.note("writes_repository", "запись через объект пути: .%s" % name)
        if (name == "open" and (owner == "io" or isinstance(f, ast.Name))):
            mode = "r"
            if len(node.args) > 1 and isinstance(node.args[1], ast.Constant):
                mode = str(node.args[1].value)
            for kw in node.keywords:
                if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                    mode = str(kw.value.value)
            if any(c in mode for c in "wax+"):
                tgt = node.args[0] if node.args else None
                if not (tgt is not None and self.is_temp(tgt)):
                    self.note("writes_repository", "открытие на запись (mode=%s)" % mode)

    def _argv(self, node):
        """Первый аргумент subprocess: что именно запускается."""
        arg = node.args[0] if node.args else None
        while isinstance(arg, ast.BinOp):
            arg = arg.left
        if not isinstance(arg, ast.List) or not arg.elts:
            self.note("spawns_unknown", "subprocess с неразбираемым argv")
            return
        head = arg.elts[0]
        if isinstance(head, ast.Attribute) and head.attr == "executable":
            return                      # sys.executable — свой же интерпретатор
        if isinstance(head, ast.Name):
            return                      # переменная, разрешённая внутри теста
        if not isinstance(head, ast.Constant) or not isinstance(head.value, str):
            self.note("spawns_unknown", "subprocess с вычисляемой программой")
            return
        prog = head.value.lower()
        if prog == "git":
            sub = arg.elts[1].value if len(arg.elts) > 1 and isinstance(
                arg.elts[1], ast.Constant) else None
            if sub is None:
                self.note("spawns_unknown", "git с вычисляемой подкомандой")
            elif sub not in GIT_READONLY:
                self.note("git_write", "git %s — не только чтение" % sub)
            return
        if prog in ("node", "node.exe", "python", "py"):
            return
        if prog in ("cmd", "cmd.exe", "powershell", "powershell.exe", "pwsh"):
            self.note("shell_usage", "запуск оболочки: %s" % prog)
            return
        self.note("spawns_unknown", "запуск внешней программы: %s" % prog)


def _import_names(tree):
    """Импортированные модули: верхний уровень и полный путь."""
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                out.add(a.name)
                out.add(a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
            out.add(node.module.split(".")[0])
    return out


def _literals(tree):
    return [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def _supervises_processes(src):
    """Импортирует ли тест модуль, надзирающий за дочерним процессом.

    Разбор структурный: подстрока сработала бы на собственном комментарии файла.
    """
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return False
    names = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            names += [a.name for a in n.names]
        elif isinstance(n, ast.ImportFrom):
            names.append(n.module or "")
            names += [(n.module or "") + "." + a.name for a in n.names]
    return any(part == m for full in names for part in full.split(".")
               for m in SUPERVISOR_MODULES)


def classify_python(src):
    sc = _PyScan()
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        sc.note("unknown_capability", "исходник не разобран: %s" % e)
        return sc, "parse-error"

    mods = _import_names(tree)
    for m in sorted(mods):
        if m in IMPORT_CAPS:
            cap, why = IMPORT_CAPS[m]
            sc.note(cap, why)
    for dotted, (cap, why) in _DOTTED_CAPS:
        if dotted in mods:
            sc.note(cap, why)

    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            sc.visit_assign(node)
        elif isinstance(node, ast.Call):
            sc.visit_call(node)
        elif isinstance(node, ast.Name) and node.id == "DATA_DIR":
            sc.note("database_write", "обращается к DATA_DIR")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == "spec_from_file_location":
            if any(isinstance(c, ast.Constant) and isinstance(c.value, str)
                   and c.value.endswith("server.py") for c in ast.walk(node)):
                sc.note("imports_server", IMPORT_CAPS["server"][1])
        elif isinstance(node, ast.Attribute) and node.attr in ("serve_forever", "urlopen"):
            sc.note("local_server" if node.attr == "serve_forever" else "network",
                    "вызывает .%s" % node.attr)

    lits = _literals(tree)
    # Сценарий, который грузит server.py, может лежать внутри строки и уезжать в подпроцесс.
    for v in lits:
        if "spec_from_file_location" in v and "server.py" in v:
            sc.note("imports_server", IMPORT_CAPS["server"][1])
            break
    sc.scan_literals(lits, "строковый литерал")
    return sc, "ast"


def classify_mjs(src):
    """JS без разбора дерева. Доказать безопасность нечем — закрываем по умолчанию."""
    sc = _PyScan()
    sc.note("unknown_capability",
            "JS разбирается только текстом: безопасность не доказуема на этапе 2B")
    if re.search(r"child_process|\bspawn\(|\bexec\(", src):
        sc.note("spawns_unknown", "child_process в .mjs")
    sc.scan_literals([src], "текст файла")
    return sc, "text-scan"


# ── Сборка каталога ──────────────────────────────────────────────────────────
def components_for(path, risk_map):
    out = []
    for r in risk_map["rules"]:
        if path in (r.get("targeted_tests") or []) or path in (r.get("subsystem_tests") or []):
            if r["component"] not in out:
                out.append(r["component"])
    return out or ["unclassified"]


def load_overrides():
    if not os.path.isfile(OVERRIDES):
        return {}
    data = json.load(io.open(OVERRIDES, encoding="utf-8"))
    out = {}
    for o in data.get("overrides", []):
        if not o.get("reason"):
            raise SystemExit("ОШИБКА: исключение %r без поля reason" % o.get("path"))
        out[o["path"]] = o
    return out


def build():
    risk_map = json.load(io.open(RISK_MAP, encoding="utf-8"))
    over = load_overrides()
    paths = sorted([p.replace("\\", "/") for p in
                    glob.glob(os.path.join(REPO, "tools", "test_*.py")) +
                    glob.glob(os.path.join(REPO, "tools", "test_*.mjs"))])
    tests = []
    for full in paths:
        rel = os.path.relpath(full, REPO).replace("\\", "/")
        src = io.open(full, encoding="utf-8", errors="replace").read()
        lang = "python" if rel.endswith(".py") else "javascript"
        if lang == "python":
            sc, source = classify_python(src)
        else:
            sc, source = classify_mjs(src)
        # Mutation proof узнаётся и по имени: файл называет себя сам.
        if "mutation" in os.path.basename(rel).lower():
            sc.note("mutation", "имя файла содержит mutation")

        timeout = DEFAULT_TIMEOUT
        for cap, sec in TIMEOUT_BY_KIND:
            if sc.caps.get(cap):
                timeout = max(timeout, sec)
        # Тест, который сам надзирает за дочерним процессом, ждёт срабатывания стенового
        # предела по-настоящему: серия запусков со сценарием таймаута расходует минуты.
        # Бюджета по умолчанию не хватает, и урезанный прогон записывался бы как ТАЙМАУТ
        # вместо собственного вердикта теста. Признак структурный — импорт надзирающего
        # модуля, а не любое порождение процесса: иначе бюджет вырос бы у полусотни файлов.
        # Требовать вдобавок spawns_process нельзя: тест зовёт надзирающий модуль, а
        # подпроцесс порождает уже он, поэтому у самого теста признака нет.
        if lang == "python" and _supervises_processes(src):
            timeout = max(timeout, SPAWN_TIMEOUT)

        entry = {
            "id": os.path.splitext(os.path.basename(rel))[0],
            "path": rel,
            "exists": True,
            "language": lang,
            "components": components_for(rel, risk_map),
            "browser": sc.caps["browser"],
            "local_server": sc.caps["local_server"],
            "network": sc.caps["network"],
            "mutation": sc.caps["mutation"],
            "writes_repository": sc.caps["writes_repository"],
            "build": sc.caps["build"],
            "installer": sc.caps["installer"],
            "real_printer": sc.caps["real_printer"],
            "database_write": sc.caps["database_write"],
            "shell_usage": sc.caps["shell_usage"],
            "spawns_unknown": sc.caps["spawns_unknown"],
            "git_write": sc.caps["git_write"],
            "imports_server": sc.caps["imports_server"],
            "unknown_capability": sc.caps["unknown_capability"],
            "spawns_process": sc.spawns_process,
            "expected_max_seconds": timeout,
            "sha256": _sha(full),
            "reasons": sc.reasons,
            "classification_source": source,
        }
        blocking = [c for c in BLOCKING if entry[c]]
        if blocking and not entry["reasons"]:
            entry["reasons"] = ["unknown capability"]

        # Ручное исключение снимает ТОЛЬКО перечисленные способности. Любая другая
        # оставшаяся способность по-прежнему закрывает тест: исключение не может
        # объявить безопасным то, чего не разбирало.
        o = over.get(rel)
        if o:
            if o.get("force_unsafe"):
                blocking = list(set(blocking) | {"manual_hold"})
            else:
                waived = [c for c in (o.get("waives") or []) if c in BLOCKING]
                unknown = [c for c in (o.get("waives") or []) if c not in BLOCKING]
                if unknown:
                    raise SystemExit("ОШИБКА: исключение %s снимает несуществующую "
                                     "способность %s" % (rel, unknown))
                blocking = [c for c in blocking if c not in waived]
            entry["reasons"] = list(entry["reasons"]) + ["ручное исключение: " + o["reason"]]
            entry["classification_source"] = "override"

        entry["blocking_capabilities"] = sorted(blocking)
        entry["safe_for_targeted"] = not blocking
        entry["safe_for_subsystem"] = not blocking
        tests.append(entry)

    counts = {
        "total": len(tests),
        "python": sum(1 for t in tests if t["language"] == "python"),
        "javascript": sum(1 for t in tests if t["language"] == "javascript"),
        "safe_for_targeted": sum(1 for t in tests if t["safe_for_targeted"]),
        "safe_for_subsystem": sum(1 for t in tests if t["safe_for_subsystem"]),
    }
    for c in BLOCKING:
        counts["cap_" + c] = sum(1 for t in tests if t.get(c))
    return {
        "schema_version": SCHEMA,
        "classifier_version": CLASSIFIER,
        "note": ("Построено СТАТИЧЕСКИ; ни один тест не запускался. expected_max_seconds — "
                 "назначенный бюджет времени, а не измерение. Недоказанная безопасность "
                 "трактуется как небезопасность."),
        "counts": counts,
        "tests": tests,
    }


def dump(data):
    return json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


def freshness(catalog_path=None):
    """Расхождения между записанным каталогом и текущим состоянием репозитория.

    Возвращает (список расхождений, свежий каталог). Пустой список = каталог актуален.
    Ничего не записывает.
    """
    path = catalog_path or CATALOG
    fresh = build()
    if not os.path.isfile(path):
        return ["каталог отсутствует: %s" % path], fresh
    try:
        stored = json.load(io.open(path, encoding="utf-8"))
    except Exception as e:
        return ["каталог не читается: %s" % e], fresh
    if not isinstance(stored, dict):
        return ["каталог не является объектом JSON"], fresh

    diffs = []
    if stored.get("schema_version") != fresh["schema_version"]:
        diffs.append("схема: %s -> %s" % (stored.get("schema_version"), fresh["schema_version"]))
    if stored.get("classifier_version") != fresh["classifier_version"]:
        diffs.append("классификатор: %s -> %s"
                     % (stored.get("classifier_version"), fresh["classifier_version"]))
    a = dict((t["path"], t) for t in stored.get("tests", []) if isinstance(t, dict))
    b = dict((t["path"], t) for t in fresh["tests"])
    for p in sorted(set(b) - set(a)):
        diffs.append("новый тест: %s" % p)
    for p in sorted(set(a) - set(b)):
        diffs.append("тест исчез: %s" % p)
    for p in sorted(set(a) & set(b)):
        if a[p].get("sha256") != b[p].get("sha256"):
            diffs.append("изменился: %s" % p)
        elif a[p] != b[p]:
            diffs.append("классификация разошлась: %s" % p)
    return diffs, fresh


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="Каталог безопасности тестов (тесты не запускаются).")
    ap.add_argument("--check", action="store_true", help="проверить актуальность, не записывать")
    ap.add_argument("--write", action="store_true", help="перестроить и записать каталог")
    ap.add_argument("--json", action="store_true", help="машинный вывод для --check")
    ns = ap.parse_args(argv)
    if ns.write and ns.check:
        sys.stderr.write("ОШИБКА: --check и --write несовместимы\n")
        return 2

    if ns.write:
        fresh = build()
        io.open(CATALOG, "w", encoding="utf-8", newline="\n").write(dump(fresh))
        print("записано: %s" % os.path.relpath(CATALOG, REPO).replace("\\", "/"))
        print("тестов: %(total)d | безопасных TARGETED: %(safe_for_targeted)d | "
              "SUBSYSTEM: %(safe_for_subsystem)d" % fresh["counts"])
        return 0

    diffs, fresh = freshness()

    if ns.json:
        print(json.dumps({"stale": bool(diffs), "differences": diffs[:50],
                          "counts": fresh["counts"]}, ensure_ascii=False))
    elif diffs:
        print("УСТАРЕЛ (%d расхождений):" % len(diffs))
        for d in diffs[:20]:
            print("   %s" % d)
        if len(diffs) > 20:
            print("   … ещё %d" % (len(diffs) - 20))
        print("Перестроить: python tools/validation/build_test_catalog.py --write")
    else:
        print("АКТУАЛЕН: %(total)d тестов, безопасных TARGETED %(safe_for_targeted)d / "
              "SUBSYSTEM %(safe_for_subsystem)d" % fresh["counts"])
    return 1 if diffs else 0


if __name__ == "__main__":
    sys.exit(main())
