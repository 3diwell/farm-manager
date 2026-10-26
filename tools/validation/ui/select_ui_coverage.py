# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.841 / этап 3D — покрытие изменённого интерфейса квалифицированными сценариями.

ЗАЧЕМ. Один сценарий настроек не превращает весь `web/app.js` в проверенный код. Решение
о покрытии принимается по СОДЕРЖИМОМУ изменённых участков diff: какие строки изменились и
что вокруг них стоит. Определять покрытие по имени файла нельзя — в одном `app.js` живут и
настройки, и очередь печати.

ПРАВИЛО. Недоказанное считается непокрытым. Каждый изменённый UI-участок обязан быть покрыт;
один покрытый участок не прячет соседний непокрытый; неизвестный маркер даёт UNCOVERED.

ЧЕГО НЕ ДЕЛАЕТ. Ничего не запускает и не изменяет. Список файлов у Git запрашивает только
при явном режиме.

    python tools/validation/ui/select_ui_coverage.py --working-tree --json
    python tools/validation/ui/select_ui_coverage.py --base HEAD~1

Статусы: COVERED · PARTIALLY_COVERED · UNCOVERED · NO_UI_CHANGES · UNKNOWN · INVALID_DIFF.
"""
import argparse
import fnmatch
import io
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
MAP_PATH = os.path.join(HERE, "ui_coverage_map.json")
SCHEMA = "3diwell-ui-coverage-v1"

COVERED, PARTIAL, UNCOVERED = "COVERED", "PARTIALLY_COVERED", "UNCOVERED"
NO_UI, UNKNOWN, INVALID = "NO_UI_CHANGES", "UNKNOWN", "INVALID_DIFF"

_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$")


class CoverageError(Exception):
    """Нечитаемая карта или неразбираемый diff."""


def load_map(path=None):
    p = path or MAP_PATH
    if not os.path.isfile(p):
        raise CoverageError("карта покрытия не найдена: %s" % p)
    try:
        data = json.load(io.open(p, encoding="utf-8"))
    except Exception as e:
        raise CoverageError("карта покрытия не читается: %s" % e)
    if data.get("schema_version") != SCHEMA:
        raise CoverageError("несовместимая схема карты покрытия")
    for u in data.get("coverage_units", []):
        for k in ("id", "paths", "required_scenarios", "allowed_hunk_markers",
                  "forbidden_hunk_markers", "required_hunk_context"):
            if k not in u:
                raise CoverageError("единица покрытия %r без поля %r" % (u.get("id"), k))
    if not data.get("coverage_units"):
        raise CoverageError("карта покрытия пуста")
    return data


def _match(path, patterns):
    p = (path or "").replace("\\", "/")
    for pat in patterns:
        pat = pat.replace("\\", "/")
        if fnmatch.fnmatchcase(p, pat):
            return True
        if pat.endswith("/**") and (p == pat[:-3] or p.startswith(pat[:-2])):
            return True
    return False


# ── Разбор unified diff ──────────────────────────────────────────────────────
def parse_diff(text):
    """Unified diff -> список участков. Переименование учитывается по обоим путям."""
    files, cur = [], None
    lines = (text or "").splitlines()
    i = 0
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("diff --git "):
            m = re.match(r'diff --git "?a/(.+?)"? "?b/(.+?)"?$', ln)
            cur = {"old_path": m.group(1) if m else None,
                   "new_path": m.group(2) if m else None, "hunks": [],
                   "renamed": False, "deleted": False, "added": False}
            files.append(cur)
        elif cur is not None and ln.startswith("rename from "):
            cur["old_path"] = ln[len("rename from "):].strip()
            cur["renamed"] = True
        elif cur is not None and ln.startswith("rename to "):
            cur["new_path"] = ln[len("rename to "):].strip()
            cur["renamed"] = True
        elif cur is not None and ln.startswith("deleted file mode"):
            cur["deleted"] = True
        elif cur is not None and ln.startswith("new file mode"):
            cur["added"] = True
        elif ln.startswith("--- ") and cur is not None:
            p = ln[4:].strip()
            if p != "/dev/null":
                cur["old_path"] = re.sub(r'^"?a/', "", p).rstrip('"')
        elif ln.startswith("+++ ") and cur is not None:
            p = ln[4:].strip()
            if p != "/dev/null":
                cur["new_path"] = re.sub(r'^"?b/', "", p).rstrip('"')
        elif ln.startswith("@@"):
            m = _HUNK.match(ln)
            if not m or cur is None:
                raise CoverageError("не разобран заголовок участка: %s" % ln[:80])
            hunk = {"old_start": int(m.group(1)), "old_count": int(m.group(2) or 1),
                    "new_start": int(m.group(3)), "new_count": int(m.group(4) or 1),
                    "section": (m.group(5) or "").strip(),
                    "changed_lines": [], "context_lines": []}
            i += 1
            while i < len(lines):
                b = lines[i]
                if b.startswith("@@") or b.startswith("diff --git "):
                    break
                if b.startswith("+") and not b.startswith("+++"):
                    hunk["changed_lines"].append(b[1:])
                elif b.startswith("-") and not b.startswith("---"):
                    hunk["changed_lines"].append(b[1:])
                elif b.startswith(" "):
                    hunk["context_lines"].append(b[1:])
                elif b.startswith("\\"):
                    pass
                i += 1
            cur["hunks"].append(hunk)
            continue
        i += 1
    return files


# ── Решение о покрытии одного участка ────────────────────────────────────────
def classify_hunk(fileinfo, hunk, units):
    """-> (список покрывших единиц, причина непокрытия, найденный запретный маркер)."""
    paths = [p for p in (fileinfo.get("old_path"), fileinfo.get("new_path")) if p]
    changed = [l for l in hunk["changed_lines"] if l.strip()]
    ctx = hunk["context_lines"] + [hunk.get("section") or ""]
    whole = changed + ctx
    matched, reasons, forbidden_seen = [], [], None

    for u in units:
        if not any(_match(p, u["paths"]) for p in paths):
            continue
        bad = next((m for m in u["forbidden_hunk_markers"]
                    if any(m in l for l in whole)), None)
        if bad:
            forbidden_seen = forbidden_seen or bad
            reasons.append("%s: запретный маркер %r" % (u["id"], bad))
            continue
        if not changed:
            reasons.append("%s: изменённых строк нет" % u["id"])
            continue

        allowed = u["allowed_hunk_markers"]
        each_line_explained = all(any(m in l for m in allowed) for l in changed)
        if each_line_explained:
            matched.append(u)
            continue

        # Якорный режим: сам участок стоит внутри оболочки настроек. Тогда изменение
        # соседних строк допустимо, но НЕ появление нового интерактивного элемента —
        # его сценарий не нажимает и покрытым считать нельзя.
        anchored = any(a in l for a in u["required_hunk_context"] for l in ctx)
        new_control = [l for l in changed
                       if any(c in l for c in (u.get("new_control_markers") or []))
                       and not any(m in l for m in allowed)]
        if anchored and not new_control:
            matched.append(u)
        elif anchored and new_control:
            reasons.append("%s: новый интерактивный элемент, который сценарий не проверяет"
                           % u["id"])
        else:
            reasons.append("%s: изменённые строки не объяснены разрешёнными маркерами и "
                           "участок не стоит внутри оболочки настроек" % u["id"])
    return matched, reasons, forbidden_seen


def analyse(diff_text, cmap):
    units = cmap["coverage_units"]
    ui_paths = cmap.get("ui_paths") or []
    files = parse_diff(diff_text)
    hunks_out, ui_hunks = [], 0
    for f in files:
        paths = [p for p in (f.get("old_path"), f.get("new_path")) if p]
        if not any(_match(p, ui_paths) for p in paths):
            continue
        for h in f["hunks"]:
            ui_hunks += 1
            matched, reasons, forbidden = classify_hunk(f, h, units)
            hunks_out.append({
                "file": f.get("new_path") or f.get("old_path"),
                "old_path": f.get("old_path"), "new_path": f.get("new_path"),
                "renamed": f["renamed"], "deleted": f["deleted"], "added": f["added"],
                "old_range": [h["old_start"], h["old_count"]],
                "new_range": [h["new_start"], h["new_count"]],
                "changed_lines": [l[:200] for l in h["changed_lines"][:40]],
                "context_lines": [l[:200] for l in h["context_lines"][:20]],
                "matched_coverage_units": [u["id"] for u in matched],
                "unmatched_reason": None if matched else ("; ".join(reasons)
                                                          or "нет подходящей единицы "
                                                             "покрытия"),
                "forbidden_marker": forbidden,
                "required_scenarios": sorted(set(s for u in matched
                                                 for s in u["required_scenarios"])),
            })
    covered = [h for h in hunks_out if h["matched_coverage_units"]]
    uncovered = [h for h in hunks_out if not h["matched_coverage_units"]]
    if not ui_hunks:
        status = NO_UI
    elif not uncovered:
        status = COVERED
    elif not covered:
        status = UNCOVERED
    else:
        status = PARTIAL
    return {
        "schema_version": SCHEMA, "status": status, "ui_hunks": ui_hunks,
        "covered_hunks": len(covered), "uncovered_hunks": len(uncovered),
        "hunks": hunks_out,
        "coverage_units": sorted(set(u for h in covered
                                     for u in h["matched_coverage_units"])),
        # Сценарии требуются ТОЛЬКО когда покрыто всё: частичное покрытие не даёт права
        # запускать UI и объявлять требование закрытым.
        "required_scenarios": sorted(set(s for h in covered
                                         for s in h["required_scenarios"]))
        if status == COVERED else [],
        "uncovered": [{"file": h["file"], "new_range": h["new_range"],
                       "reason": h["unmatched_reason"],
                       "forbidden_marker": h["forbidden_marker"]} for h in uncovered],
    }


# ── Источники diff ───────────────────────────────────────────────────────────
def _git_diff(args):
    try:
        pr = subprocess.run(["git", "diff", "-U5", "--no-color", "--find-renames"] + args,
                            cwd=REPO, capture_output=True, text=True, encoding="utf-8",
                            errors="replace", shell=False, timeout=90)
    except Exception as e:
        raise CoverageError("git diff не выполнен: %s" % e)
    if pr.returncode not in (0, 1):
        raise CoverageError("git diff -> код %d" % pr.returncode)
    return pr.stdout or ""


def collect_diff(ns):
    modes = [ns.working_tree, ns.staged, bool(ns.base), bool(ns.diff_file)]
    if sum(1 for m in modes if m) != 1:
        raise CoverageError("укажите ровно один источник: --working-tree, --staged, "
                            "--base или --diff-file")
    if ns.diff_file:
        if not os.path.isfile(ns.diff_file):
            raise CoverageError("файл diff не найден: %s" % ns.diff_file)
        return io.open(ns.diff_file, encoding="utf-8", errors="replace").read()
    if ns.working_tree:
        return _git_diff(["HEAD"])
    if ns.staged:
        return _git_diff(["--cached"])
    return _git_diff(["%s...HEAD" % ns.base]) or _git_diff([ns.base])


def unknown_result(reason):
    """Путь без diff доказательством покрытия быть не может."""
    return {"schema_version": SCHEMA, "status": UNKNOWN, "ui_hunks": None,
            "covered_hunks": 0, "uncovered_hunks": None, "hunks": [],
            "coverage_units": [], "required_scenarios": [], "uncovered": [],
            "reason": reason}


def render(res):
    L = ["=" * 78, "ПОКРЫТИЕ ИЗМЕНЁННОГО ИНТЕРФЕЙСА", "=" * 78,
         "СТАТУС: %s" % res["status"]]
    if res["status"] == UNKNOWN:
        L.append(res.get("reason", ""))
        L.append("Покрытие по одному пути файла не доказывается: нужен настоящий diff.")
        return "\n".join(L)
    L.append("участков UI: %s, покрыто %s, не покрыто %s"
             % (res["ui_hunks"], res["covered_hunks"], res["uncovered_hunks"]))
    if res["coverage_units"]:
        L.append("единицы покрытия: %s" % ", ".join(res["coverage_units"]))
    if res["required_scenarios"]:
        L.append("обязательные сценарии: %s" % ", ".join(res["required_scenarios"]))
    for h in res["uncovered"]:
        L.append("   ! %s @%s: %s" % (h["file"], h["new_range"][0],
                                      (h["reason"] or "")[:110]))
    if res["status"] in (PARTIAL, UNCOVERED):
        L.append("")
        L.append("Непокрытый участок не закрывается чужим покрытым: требование UI остаётся.")
    return "\n".join(L)


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="Покрытие изменённого интерфейса (только анализ).")
    ap.add_argument("--working-tree", action="store_true")
    ap.add_argument("--staged", action="store_true")
    ap.add_argument("--base")
    ap.add_argument("--diff-file", help="служебное: готовый diff для unit-тестов")
    ap.add_argument("--map")
    ap.add_argument("--json", action="store_true")
    ns = ap.parse_args(argv)
    try:
        cmap = load_map(ns.map)
        res = analyse(collect_diff(ns), cmap)
    except CoverageError as e:
        payload = {"schema_version": SCHEMA, "status": INVALID, "error": str(e)}
        sys.stderr.write((json.dumps(payload, ensure_ascii=False) if ns.json
                          else "ОШИБКА: %s" % e) + "\n")
        return 2
    sys.stdout.write((json.dumps(res, ensure_ascii=False, indent=1, sort_keys=True)
                      if ns.json else render(res)) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
