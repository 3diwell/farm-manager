# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.841 / этап 2A: детерминированный выбор профиля проверки по изменённым файлам.

ЧТО ДЕЛАЕТ. Читает список изменённых путей, сопоставляет их с `tools/validation/risk_map.json`,
определяет уровень риска R0..R4 и минимально достаточный профиль
FAST / TARGETED / SUBSYSTEM / RELEASE / HARDWARE, объясняет причину и печатает ПЛАН команд.

ЧЕГО НЕ ДЕЛАЕТ. Не изменяет ни одного файла. **Не выполняет ни одной проверки** — только
планирует; в каждой команде плана стоит `executes: false`. Единственный subprocess —
безопасное получение списка файлов у Git, и только когда об этом попросили явно
(`--working-tree`, `--staged`, `--base`).

ПРИНЦИП. Совпавшие правила НЕ конкурируют по принципу «первое победило»: берётся
МАКСИМАЛЬНЫЙ риск, САМЫЙ СТРОГИЙ профиль и объединение всех обязательных признаков.
Файл, не совпавший ни с одним правилом, зелёным не считается: обычный продуктовый путь
эскалируется до RELEASE, неизвестный путь внутри критической области ставит `blocked = true`.

    python tools/validation/select_profile.py --files web/app.css
    python tools/validation/select_profile.py --working-tree --json
    python tools/validation/select_profile.py --files-from changed.txt

Код возврата: 0 — план построен; 2 — ошибка ввода или схемы; 3 — результат заблокирован
(blocked), решение принимает владелец.
"""
import argparse
import fnmatch
import glob
import io
import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MAP_PATH = os.path.join(REPO, "tools", "validation", "risk_map.json")
SCHEMA = "3diwell-risk-map-v1"

EXIT_OK, EXIT_USAGE, EXIT_BLOCKED = 0, 2, 3


class SelectorError(Exception):
    """Ошибка ввода или схемы: приводит к ненулевому коду возврата, а не к догадке."""


class OutOfRepoError(SelectorError):
    """Путь вне репозитория. Не ошибка вызова, а результат `blocked`: назвать файл важнее,
    чем просто выйти с ненулевым кодом."""


# ── Карта риска ───────────────────────────────────────────────────────────────────────────
def load_map(path=None):
    p = path or MAP_PATH
    if not os.path.isfile(p):
        raise SelectorError("карта риска не найдена: %s" % p)
    try:
        data = json.load(io.open(p, encoding="utf-8"))
    except Exception as e:
        raise SelectorError("карта риска не читается как JSON (%s): %s" % (p, e))
    if not isinstance(data, dict):
        raise SelectorError("карта риска должна быть объектом JSON")
    if data.get("schema_version") != SCHEMA:
        raise SelectorError("несовместимая схема карты: ожидалась %r, получена %r"
                            % (SCHEMA, data.get("schema_version")))
    for key in ("risk_order", "profile_order", "profile_min_by_risk", "fallback", "rules"):
        if key not in data:
            raise SelectorError("в карте риска нет обязательного раздела %r" % key)
    if not isinstance(data["rules"], list) or not data["rules"]:
        raise SelectorError("в карте риска пустой или неверный список правил")
    for r in data["rules"]:
        for key in ("id", "component", "globs", "risk", "profile", "reason"):
            if key not in r:
                raise SelectorError("правило %r без обязательного поля %r" % (r.get("id"), key))
        if r["risk"] not in data["risk_order"]:
            raise SelectorError("правило %r: неизвестный риск %r" % (r["id"], r["risk"]))
        if r["profile"] not in data["profile_order"]:
            raise SelectorError("правило %r: неизвестный профиль %r" % (r["id"], r["profile"]))
    return data


# ── Нормализация путей ────────────────────────────────────────────────────────────────────
def normalize(raw, repo=REPO):
    """Привести путь к POSIX-виду относительно корня репозитория.

    Windows и POSIX-разделители дают ОДИН результат. Выход за пределы репозитория
    (`..`, абсолютный путь наружу) — ошибка, а не молчаливое усечение.
    """
    if raw is None:
        raise SelectorError("пустой путь")
    s = str(raw).strip().strip('"').strip("'")
    if not s:
        raise SelectorError("пустой путь")
    s = s.replace("\\", "/")
    if os.path.isabs(s) or (len(s) > 1 and s[1] == ":"):
        full = os.path.normpath(s)
        try:
            rel = os.path.relpath(full, repo)
        except ValueError:
            raise OutOfRepoError("путь на другом диске, вне репозитория: %s" % raw)
        rel = rel.replace("\\", "/")
        if rel.startswith("../") or rel == "..":
            raise OutOfRepoError("путь вне репозитория: %s" % raw)
        return rel
    parts, out = s.split("/"), []
    for p in parts:
        if p in ("", "."):
            continue
        if p == "..":
            if not out:
                raise OutOfRepoError("путь выходит за пределы репозитория: %s" % raw)
            out.pop()
            continue
        out.append(p)
    if not out:
        raise SelectorError("пустой путь после нормализации: %s" % raw)
    return "/".join(out)


def _match_glob(path, pattern):
    """Сопоставление с glob. `**` покрывает любую глубину, `*` — один сегмент."""
    pat = pattern.replace("\\", "/")
    if fnmatch.fnmatchcase(path, pat):
        return True
    # `dir/**` должен покрывать и сам `dir/...` любой глубины
    if pat.endswith("/**") and (path == pat[:-3] or path.startswith(pat[:-2])):
        return True
    # `**/*x*` должен ловить и файл в корне
    if pat.startswith("**/") and fnmatch.fnmatchcase(path, pat[3:]):
        return True
    if pat.startswith("**/") and fnmatch.fnmatchcase(os.path.basename(path), pat[3:]):
        return True
    # `*.md` в любом каталоге
    if "/" not in pat and fnmatch.fnmatchcase(os.path.basename(path), pat):
        return True
    return False


def rule_matches(path, rule):
    for ex in rule.get("exclude_globs", []) or []:
        if _match_glob(path, ex):
            return False
    for g in rule["globs"]:
        if _match_glob(path, g):
            return True
    return False


def in_critical_area(path, data):
    for g in data["fallback"].get("critical_area_globs", []) or []:
        if _match_glob(path, g):
            return True
    return False


def _max_by(order, values, default):
    best = default
    for v in values:
        if order.index(v) > order.index(best):
            best = v
    return best


# ── Ядро выбора ───────────────────────────────────────────────────────────────────────────
def select(paths, data):
    """→ dict результата. Ничего не выполняет и не пишет на диск."""
    risk_order, prof_order = data["risk_order"], data["profile_order"]
    matched, unmatched, comps = [], [], []
    risk, profile = risk_order[0], prof_order[0]
    ui = build = hardware = False
    targeted, subsystem, reasons, warnings = [], [], [], []
    blocked, blocked_reason = False, None

    seen, changed = set(), []
    for p in paths:                       # дубликаты убираем, порядок сохраняем
        try:
            n = normalize(p)
        except OutOfRepoError as e:
            # Не выходим с ошибкой: важнее назвать файл и не выдать зелёный результат.
            blocked, blocked_reason = True, str(e)
            risk = _max_by(risk_order, ["R4"], risk)
            profile = _max_by(prof_order, ["RELEASE"], profile)
            reasons.append(str(e))
            warnings.append("Путь вне репозитория классифицировать нельзя: %s" % p)
            continue
        if n not in seen:
            seen.add(n)
            changed.append(n)

    if blocked:
        res = {
            "schema_version": SCHEMA, "changed_files": changed, "matched_rules": [],
            "unmatched_files": [], "components": ["out-of-repo"], "risk": risk,
            "profile": profile, "ui_required": False, "build_required": False,
            "hardware_required": False, "targeted_tests": [], "subsystem_tests": [],
            "reasons": reasons, "warnings": warnings,
            "blocked": True, "blocked_reason": blocked_reason,
        }
        res["plan"] = build_plan(res)
        return res

    if not changed:
        return {
            "schema_version": SCHEMA, "changed_files": [], "matched_rules": [],
            "unmatched_files": [], "components": [], "risk": "R0", "profile": "FAST",
            "ui_required": False, "build_required": False, "hardware_required": False,
            "targeted_tests": [], "subsystem_tests": [],
            "reasons": ["изменений нет — проверять нечего"],
            "warnings": [], "blocked": False, "blocked_reason": None,
            "plan": [], "note": "Пустой список изменений: ни одна проверка не нужна и не запланирована.",
        }

    for path in changed:
        hits = [r for r in data["rules"] if rule_matches(path, r)]
        if not hits:
            unmatched.append(path)
            fb_key = "unknown_in_critical_area" if in_critical_area(path, data) else "unknown_product_file"
            fb = data["fallback"][fb_key]
            risk = _max_by(risk_order, [fb["risk"]], risk)
            profile = _max_by(prof_order, [fb["profile"]], profile)
            comps.append(fb["component"])
            reasons.append("%s: %s" % (path, fb["reason"]))
            warnings.append("%s: %s" % (path, fb["warning"]))
            if fb.get("blocked"):
                blocked = True
                blocked_reason = fb["reason"]
            continue
        for r in hits:
            matched.append({"file": path, "rule": r["id"], "component": r["component"],
                            "risk": r["risk"], "profile": r["profile"]})
            comps.append(r["component"])
            risk = _max_by(risk_order, [r["risk"]], risk)
            profile = _max_by(prof_order, [r["profile"]], profile)
            ui = ui or bool(r.get("ui_required"))
            build = build or bool(r.get("build_required"))
            hardware = hardware or bool(r.get("hardware_required"))
            for t in r.get("targeted_tests", []) or []:
                if t not in targeted:
                    targeted.append(t)
            for t in r.get("subsystem_tests", []) or []:
                if t not in subsystem:
                    subsystem.append(t)
            # self_test: изменённый файл сам является тестом — он и есть связанная проверка.
            if r.get("self_test") and path not in targeted:
                targeted.append(path)
            reasons.append("%s -> %s (%s, %s): %s" % (path, r["id"], r["risk"], r["profile"], r["reason"]))

    # Профиль не может быть слабее минимума для итогового риска.
    profile = _max_by(prof_order, [data["profile_min_by_risk"][risk]], profile)
    # Требуется железо -> HARDWARE как верхняя ступень поверх RELEASE.
    if hardware:
        profile = _max_by(prof_order, ["HARDWARE"], profile)

    # Тест, которого нет на диске, в план не попадает: имена не выдумываем.
    def existing(lst, kind):
        out = []
        for t in lst:
            if os.path.isfile(os.path.join(REPO, t)):
                out.append(t)
            else:
                warnings.append("в карте указан несуществующий %s-тест %s — исключён из плана"
                                % (kind, t))
        return out

    targeted, subsystem = existing(targeted, "targeted"), existing(subsystem, "subsystem")

    if profile in ("TARGETED",) and not targeted:
        warnings.append("для профиля TARGETED не нашлось ни одного существующего связанного "
                        "теста — профиль повышен до SUBSYSTEM")
        profile = _max_by(prof_order, ["SUBSYSTEM"], profile)
    if profile == "SUBSYSTEM" and not subsystem and not targeted:
        warnings.append("для профиля SUBSYSTEM не нашлось ни одного существующего теста "
                        "подсистемы — профиль повышен до RELEASE")
        profile = _max_by(prof_order, ["RELEASE"], profile)

    res = {
        "schema_version": SCHEMA,
        "changed_files": changed,
        "matched_rules": matched,
        "unmatched_files": unmatched,
        "components": sorted(set(comps)),
        "risk": risk,
        "profile": profile,
        "ui_required": ui,
        "build_required": build,
        "hardware_required": hardware,
        "targeted_tests": targeted,
        "subsystem_tests": subsystem,
        "reasons": reasons,
        "warnings": warnings,
        "blocked": blocked,
        "blocked_reason": blocked_reason,
    }
    res["plan"] = build_plan(res)
    return res


# ── План (только план: executes всегда false) ─────────────────────────────────────────────
def build_plan(res):
    prof, plan = res["profile"], []
    py = [f for f in res["changed_files"] if f.endswith(".py")]
    js = [f for f in res["changed_files"] if f.endswith((".js", ".mjs"))]
    css = [f for f in res["changed_files"] if f.endswith(".css")]
    html = [f for f in res["changed_files"] if f.endswith(".html")]

    def add(pid, profile, command, reason, scope):
        plan.append({"id": pid, "profile": profile, "command": command,
                     "reason": reason, "estimated_scope": scope, "executes": False})

    if res["blocked"]:
        add("blocked", prof, None,
            "Неизвестный путь в критической области: автоматический план не строится, "
            "решение принимает владелец", "нет")
        return plan

    # FAST входит в любой профиль.
    for f in py:
        add("fast:py:%s" % f, "FAST",
            'python -c "import py_compile; py_compile.compile(r\'%s\', doraise=True)"' % f,
            "синтаксис изменённого Python-файла", "1 файл, <1 c")
    for f in js:
        add("fast:js:%s" % f, "FAST", "node --check %s" % f,
            "синтаксис изменённого JS-файла", "1 файл, <1 c")
    for _ in css:
        add("fast:css-balance", "FAST",
            "python - (баланс { } в web/app.css через errors='surrogateescape')",
            "непарная скобка ломает всю тему; файл читается только так", "1 файл, <1 c")
    for _ in html:
        add("fast:html-balance", "FAST",
            "python - (баланс div/span в web/index.html)",
            "шаблон — одна гигантская строка, дисбаланс ломает разметку", "1 файл, <1 c")
    if not plan:
        add("fast:none", "FAST", None,
            "среди изменённых файлов нет исходников с синтаксисом — синтаксическая "
            "проверка не нужна", "нет")

    def runner(t):
        return ("node %s" if t.endswith(".mjs") else "python %s") % t

    if prof in ("TARGETED", "SUBSYSTEM", "RELEASE", "HARDWARE"):
        for t in res["targeted_tests"]:
            add("targeted:%s" % os.path.basename(t), "TARGETED",
                runner(t), "тест, прямо связанный с изменённой областью", "1 набор")
    if prof in ("SUBSYSTEM", "RELEASE", "HARDWARE"):
        for t in res["subsystem_tests"]:
            if t in res["targeted_tests"]:
                continue
            add("subsystem:%s" % os.path.basename(t), "SUBSYSTEM",
                runner(t), "тест затронутой подсистемы", "1 набор")
    if res["ui_required"] and prof != "FAST":
        add("ui:visual", "TARGETED", None,
            "Затронут интерфейс: результат виден только глазами или на стенде headless-Edge "
            "(tools/_fm_ui_stage.py). Порядок — docs/validation/frontend.md", "вручную")

    if prof in ("RELEASE", "HARDWARE"):
        # Объём считается по диску, а не фиксированным числом: набор растёт.
        n = len(glob.glob(os.path.join(REPO, "tools", "test_*.py"))) + \
            len(glob.glob(os.path.join(REPO, "tools", "test_*.mjs")))
        add("release:gate", "RELEASE", "python tools/release_gate.py",
            "полный набор без исключений, включая mutation proof; раннер не изменяется "
            "и не ослабляется", "%d файлов, ~1 час" % n)
        if res["build_required"]:
            add("release:build", "RELEASE",
                "PyInstaller --distpath C:/3DIWELL_Builds/... (см. docs/validation/release.md)",
                "затронуты сборка или установщик — нужен собранный EXE", "~2 мин")
            add("release:packaged-proof", "RELEASE",
                "packaged proof по объектам кода внутри EXE",
                "доказать, что новый код действительно внутри сборки", "~10 c")
    if prof == "HARDWARE":
        add("hardware:manual", "HARDWARE", None,
            "Ручной сценарий на реальном принтере. Автоматическое прохождение запрещено: "
            "результат подтверждает только владелец на ферме", "вручную")
    return plan


# ── Покрытие изменённого интерфейса ──────────────────────────────────────────
# Селектор сам UI не запускает. Он только сообщает, ДОКАЗУЕМО ли покрыто изменение
# квалифицированными сценариями. Путь без diff доказательством покрытия не является:
# в одном web/app.js живут и настройки, и очередь печати.
UI_DIR = os.path.join(REPO, "tools", "validation", "ui")


def _load_ui(name):
    import importlib.util
    path = os.path.join(UI_DIR, name)
    if not os.path.isfile(path):
        return None
    spec = importlib.util.spec_from_file_location("fm_ui_" + name.split(".")[0], path)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except Exception:
        return None
    return mod


def augment_ui(res, diff_mode=None, base=None, diff_file=None):
    """Дополнить результат сведениями о покрытии UI. Профиль при этом НЕ понижается."""
    res.setdefault("ui_coverage_status", "NOT_REQUIRED")
    res.setdefault("ui_coverage_units", [])
    res.setdefault("required_ui_scenarios", [])
    res.setdefault("uncovered_ui_hunks", [])
    res.setdefault("ui_qualification_status", "UNKNOWN")

    vq = _load_ui("verify_qualification.py")
    res["ui_qualification_status"] = vq.verify()["status"] if vq else "MISSING"

    if not res.get("ui_required"):
        res["ui_coverage_status"] = "NOT_REQUIRED"
        return res
    if not diff_mode:
        # Path-only: doказать покрытие нечем, требование UI остаётся открытым.
        res["ui_coverage_status"] = "UNKNOWN"
        res["warnings"].append("покрытие интерфейса по одному пути файла не доказывается: "
                               "нужен режим с настоящим diff")
        return res

    cov = _load_ui("select_ui_coverage.py")
    if cov is None:
        res["ui_coverage_status"] = "UNKNOWN"
        res["warnings"].append("анализатор покрытия интерфейса недоступен")
        return res
    try:
        ns = argparse.Namespace(working_tree=(diff_mode == "working-tree"),
                                staged=(diff_mode == "staged"),
                                base=base if diff_mode == "base" else None,
                                diff_file=diff_file if diff_mode == "diff-file" else None)
        out = cov.analyse(cov.collect_diff(ns), cov.load_map())
    except Exception as e:
        res["ui_coverage_status"] = "UNKNOWN"
        res["warnings"].append("покрытие интерфейса не определено: %s" % str(e)[:120])
        return res

    res["ui_coverage_status"] = out["status"]
    res["ui_coverage_units"] = out["coverage_units"]
    res["uncovered_ui_hunks"] = out["uncovered"]
    # Сценарии выдаются, только когда покрыто ВСЁ и оснастка квалифицирована.
    if out["status"] == "COVERED" and res["ui_qualification_status"] == "VALID":
        res["required_ui_scenarios"] = out["required_scenarios"]
    else:
        res["required_ui_scenarios"] = []
        if out["status"] != "COVERED":
            res["warnings"].append("интерфейс покрыт не полностью (%s): непокрытых "
                                   "участков %d" % (out["status"], out["uncovered_hunks"]))
        elif res["ui_qualification_status"] != "VALID":
            res["warnings"].append("квалификация UI-оснастки недействительна: %s"
                                   % res["ui_qualification_status"])
    return res


# ── Ввод ──────────────────────────────────────────────────────────────────────────────────
def _git(args):
    try:
        pr = subprocess.run(["git"] + args, cwd=REPO, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=60)
    except Exception as e:
        raise SelectorError("не удалось запросить список файлов у Git: %s" % e)
    if pr.returncode != 0:
        raise SelectorError("git %s → код %d: %s" % (" ".join(args), pr.returncode,
                                                     (pr.stderr or "").strip()[:200]))
    return [l.strip() for l in pr.stdout.splitlines() if l.strip()]


def collect(ns):
    modes = [bool(ns.files), bool(ns.files_from), ns.working_tree, ns.staged, bool(ns.base)]
    if sum(1 for m in modes if m) == 0:
        raise SelectorError("не задан источник изменений: --files / --files-from / "
                            "--working-tree / --staged / --base")
    if sum(1 for m in modes if m) > 1:
        raise SelectorError("режимы ввода несовместимы: укажите ровно один из "
                            "--files, --files-from, --working-tree, --staged, --base")
    if ns.files:
        return list(ns.files)
    if ns.files_from:
        p = ns.files_from
        if not os.path.isfile(p):
            raise SelectorError("файл со списком не найден: %s" % p)
        return [l.strip() for l in io.open(p, encoding="utf-8").read().splitlines() if l.strip()]
    if ns.working_tree:
        # Изменённые и неотслеживаемые. Удалённые файлы классифицируются по СТАРОМУ пути.
        return _git(["diff", "--name-only", "--diff-filter=ACMRD", "HEAD"]) + \
               _git(["ls-files", "--others", "--exclude-standard"])
    if ns.staged:
        return _git(["diff", "--cached", "--name-only", "--diff-filter=ACMRD"])
    return _git(["diff", "--name-only", "--diff-filter=ACMRD", "%s...HEAD" % ns.base]) or \
           _git(["diff", "--name-only", "--diff-filter=ACMRD", ns.base])


# ── Печать ────────────────────────────────────────────────────────────────────────────────
def render(res):
    L = []
    L.append("=" * 78)
    L.append("ВЫБОР ПРОФИЛЯ ПРОВЕРКИ — ЭТО ПЛАН, А НЕ ВЫПОЛНЕНИЕ")
    L.append("=" * 78)
    L.append("изменённых файлов: %d" % len(res["changed_files"]))
    for f in res["changed_files"][:40]:
        L.append("   %s" % f)
    if len(res["changed_files"]) > 40:
        L.append("   … ещё %d" % (len(res["changed_files"]) - 40))
    L.append("")
    L.append("области:  %s" % (", ".join(res["components"]) or "—"))
    L.append("РИСК:     %s" % res["risk"])
    L.append("ПРОФИЛЬ:  %s" % res["profile"])
    L.append("признаки: UI=%s  сборка=%s  железо=%s"
             % (res["ui_required"], res["build_required"], res["hardware_required"]))
    if res["blocked"]:
        L.append("")
        L.append("!!! ЗАБЛОКИРОВАНО: %s" % res["blocked_reason"])
    if res["unmatched_files"]:
        L.append("")
        L.append("не совпали с картой (%d): %s" % (len(res["unmatched_files"]),
                                                   ", ".join(res["unmatched_files"][:8])))
    if res.get("ui_required"):
        L.append("UI:       покрытие %s, квалификация %s%s"
                 % (res.get("ui_coverage_status"), res.get("ui_qualification_status"),
                    (", сценарии: " + ", ".join(res["required_ui_scenarios"]))
                    if res.get("required_ui_scenarios") else ""))
    L.append("")
    L.append("почему:")
    for r in res["reasons"][:25]:
        L.append("   • %s" % r)
    if res["warnings"]:
        L.append("")
        L.append("предупреждения:")
        for w in res["warnings"]:
            L.append("   ! %s" % w)
    L.append("")
    L.append("ПЛАН (ни одна команда не выполнена — executes=false у всех):")
    for s in res["plan"]:
        L.append("   [%-9s] %s   (%s)" % (s["profile"], s["command"] or "(ручное действие)",
                                          s["estimated_scope"]))
        L.append("               %s" % s["reason"])
    L.append("")
    L.append("Dry-run НЕ является выполненной проверкой. Команды запускает человек "
             "или будущий executor.")
    return "\n".join(L)


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(
        description="Детерминированный выбор профиля проверки по изменённым файлам (только план).")
    ap.add_argument("--files", nargs="+", help="явный список путей")
    ap.add_argument("--files-from", help="файл со списком путей, по одному в строке")
    ap.add_argument("--working-tree", action="store_true", help="изменения рабочего дерева")
    ap.add_argument("--staged", action="store_true", help="проиндексированные изменения")
    ap.add_argument("--base", help="сравнить с базовым коммитом")
    ap.add_argument("--map", help="путь к карте риска (по умолчанию tools/validation/risk_map.json)")
    ap.add_argument("--json", action="store_true", help="вывод в JSON")
    ns = ap.parse_args(argv)

    try:
        data = load_map(ns.map)
        res = select(collect(ns), data)
        mode = ("working-tree" if ns.working_tree else "staged" if ns.staged
                else "base" if ns.base else None)
        res = augment_ui(res, diff_mode=mode, base=ns.base)
    except SelectorError as e:
        msg = {"error": str(e), "schema_version": SCHEMA}
        sys.stderr.write((json.dumps(msg, ensure_ascii=False) if ns.json
                          else "ОШИБКА: %s" % e) + "\n")
        return EXIT_USAGE

    sys.stdout.write((json.dumps(res, ensure_ascii=False, indent=1, sort_keys=True)
                      if ns.json else render(res)) + "\n")
    return EXIT_BLOCKED if res["blocked"] else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
