# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
#  Alpha 2.837 — ДОКАЗАТЕЛЬНЫЙ аудит состава рабочей папки (ТОЛЬКО ЧТЕНИЕ).
#
#  ЗАЧЕМ. Рабочая папка выросла до сотен мегабайт, и «на глаз» уже не видно, что в
#  ней исходник, что сборочный мусор, а что — неизвестный файл, который трогать
#  нельзя. Этот инструмент отвечает на вопрос «что это за файл» ДОКАЗАТЕЛЬСТВОМ, а
#  не догадкой: размер, git-статус, возраст, SHA-256, и — главное — КТО НА НЕГО
#  ССЫЛАЕТСЯ (исходники, .spec PyInstaller, .iss установщика, build-скрипты, тесты,
#  сборщики module-zip, статические ассеты).
#
#  ГЛАВНОЕ ПРАВИЛО. Отсутствие текстовой ссылки НЕ является доказательством
#  ненужности: бывают динамические импорты, datas из .spec, обнаружение модулей и
#  рантайм-пути. Поэтому «нет ссылки» переводит файл в UNKNOWN — категорию, которую
#  УДАЛЯТЬ ЗАПРЕЩЕНО, а не в «удалить».
#
#  БЕЗОПАСНОСТЬ: инструмент ничего не удаляет, не перемещает и не меняет. Он не
#  открывает БД, не читает DATA_DIR, не ходит в сеть и не запускает подпроцессов,
#  кроме git-запросов только-чтение (ls-files / check-ignore).
#
#  Запуск:
#     python tools/repository_audit.py                  — отчёт на экран (сводка)
#     python tools/repository_audit.py --out <файл.md>  — полный отчёт в файл
#     python tools/repository_audit.py --json <файл>    — машинный слепок
# ============================================================================
import argparse
import hashlib
import io
import json
import os
import subprocess
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ── Категории (порядок = приоритет вывода) ──────────────────────────────────
C_PRODUCT = "1 PRODUCT SOURCE"
C_BUILD = "2 BUILD SOURCE"
C_TEST = "3 TEST SOURCE"
C_DOCS = "4 DOCUMENTATION / HANDOFF"
C_ASSET = "5 REQUIRED STATIC ASSET"
C_MODULE = "6 MODULE SOURCE / ZIP"
C_GENERATED = "7 GENERATED BUILD OUTPUT"
C_CACHE = "8 CACHE"
C_TEMP = "9 TEMPORARY TEST ARTIFACT"
C_USERDATA = "10 USER DATA (не должно быть в repo)"
C_UNKNOWN = "11 UNKNOWN (НЕ УДАЛЯТЬ)"
C_OBSOLETE = "12 OBSOLETE (доказанно не используется)"

# Каталоги, которые НИКОГДА не считаются мусором и не трогаются аудитом.
PROTECTED_TOP = ("_incoming", ".claude", ".git")

# Расширения/имена, однозначно указывающие на кэш или байт-код.
CACHE_NAMES = ("__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache")
CACHE_EXT = (".pyc", ".pyo", ".pyd")

TEXT_EXT = (".py", ".js", ".mjs", ".css", ".html", ".json", ".md", ".txt", ".spec",
            ".iss", ".bat", ".ps1", ".cfg", ".ini", ".yml", ".yaml", ".pyw",
            ".gitignore", ".gitattributes")


def sh(args):
    """git только-чтение; при любой беде — пусто (аудит не обязан падать)."""
    try:
        r = subprocess.run(args, cwd=REPO, capture_output=True, timeout=180)
        return r.stdout.decode("utf-8", "replace") if r.returncode == 0 else ""
    except Exception:
        return ""


def human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return ("%.1f %s" % (n, unit)) if unit != "B" else ("%d B" % n)
        n /= 1024.0
    return "%d B" % n


def sha256(path, limit=None):
    h = hashlib.sha256()
    try:
        with io.open(path, "rb") as fh:
            while True:
                b = fh.read(1024 * 1024)
                if not b:
                    break
                h.update(b)
    except Exception:
        return ""
    return h.hexdigest()


# ════════════════════════════════════════════════════════════════════════════
def collect_tracked():
    """Множество tracked-путей (относительных, через '/')."""
    tracked = set()
    for p in sh(["git", "ls-files", "-z"]).split("\0"):
        if p:
            tracked.add(p)
    return tracked


def collect_ignored(paths):
    """Множество игнорируемых путей — спрашиваем САМ git по каждому файлу.

    `git status --ignored` схлопывает целиком игнорируемый каталог в ОДНУ строку
    («build/»), поэтому состав внутри остался бы неизвестным и файлы выглядели бы
    untracked. check-ignore отвечает по каждому пути и ошибиться не может.
    """
    out = set()
    data = ("\0".join(paths) + "\0").encode("utf-8", "surrogateescape")
    try:
        r = subprocess.run(["git", "check-ignore", "--stdin", "-z"], cwd=REPO,
                           input=data, capture_output=True, timeout=300)
        for p in r.stdout.decode("utf-8", "replace").split("\0"):
            if p:
                out.add(p.replace("\\", "/"))
    except Exception:
        pass
    return out


def walk_files():
    """Все файлы рабочей папки (кроме внутренностей .git) с размером и возрастом."""
    rows = []
    now = time.time()
    for root, dirs, files in os.walk(REPO):
        rel_root = os.path.relpath(root, REPO).replace("\\", "/")
        if rel_root == ".":
            rel_root = ""
        if rel_root == ".git" or rel_root.startswith(".git/"):
            dirs[:] = []
            continue
        for f in files:
            fp = os.path.join(root, f)
            rel = (rel_root + "/" + f) if rel_root else f
            try:
                st = os.stat(fp)
            except Exception:
                continue
            rows.append({"path": rel, "abs": fp, "size": st.st_size,
                         "age_days": round((now - st.st_mtime) / 86400.0, 1),
                         "ext": os.path.splitext(f)[1].lower(), "name": f})
    return rows


def dir_sizes(rows):
    """Суммарный размер каждого каталога (включая вложенные)."""
    acc = {}
    for r in rows:
        parts = r["path"].split("/")[:-1]
        cur = ""
        acc[""] = acc.get("", 0) + r["size"]
        for p in parts:
            cur = (cur + "/" + p) if cur else p
            acc[cur] = acc.get(cur, 0) + r["size"]
    return acc


def build_reference_corpus():
    """Тексты, в которых ищутся ссылки: исходники, spec, iss, build, тесты, документация."""
    corpus = {}
    roots = [("server.py", None), ("build.bat", None), ("3diwell.spec", None),
             ("desktop_shell.spec", None), ("3diwell-setup.iss", None),
             ("3diwell-client-setup.iss", None), ("requirements.txt", None),
             ("AGENTS.md", None), ("CLAUDE.md", None), (".gitignore", None),
             ("desktop_launcher.pyw", None), ("client_launcher.pyw", None)]
    for name, _ in roots:
        fp = os.path.join(REPO, name)
        if os.path.isfile(fp):
            corpus[name] = io.open(fp, encoding="utf-8", errors="surrogateescape").read()
    for sub in ("app", "web", "tools", "modules", "docs", ".ai", "one_shot_print"):
        base = os.path.join(REPO, sub)
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d not in CACHE_NAMES]
            for f in files:
                if os.path.splitext(f)[1].lower() not in TEXT_EXT:
                    continue
                fp = os.path.join(root, f)
                rel = os.path.relpath(fp, REPO).replace("\\", "/")
                try:
                    corpus[rel] = io.open(fp, encoding="utf-8", errors="surrogateescape").read()
                except Exception:
                    pass
    return corpus


def referrers(corpus, row):
    """Кто ссылается на файл: по basename и по относительному пути. Себя не считаем."""
    name = row["name"]
    rel = row["path"]
    stem = os.path.splitext(name)[0]
    out = []
    for src, text in corpus.items():
        if src == rel:
            continue
        if name in text or rel in text or (len(stem) > 6 and stem in text):
            out.append(src)
    return out


def classify(row, tracked, ignored, refs):
    p = row["path"]
    top = p.split("/")[0]
    name = row["name"]
    ext = row["ext"]

    if top in PROTECTED_TOP:
        return C_UNKNOWN if top != ".claude" else C_DOCS

    if any(seg in CACHE_NAMES for seg in p.split("/")) or ext in CACHE_EXT:
        return C_CACHE
    if top == "thumb_cache":
        return C_CACHE
    if top in ("build",):
        return C_GENERATED
    if top in ("dist", "installer"):
        return C_GENERATED
    if top == "logs" or ext == ".log":
        return C_TEMP
    if ext in (".db", ".sqlite", ".sqlite3", ".db-wal", ".db-shm"):
        return C_USERDATA
    if name == "_e2e_payload.json":
        return C_TEMP

    if p.startswith("modules/"):
        return C_MODULE
    if p.startswith("tools/fixtures/"):
        return C_TEST
    if p.startswith("tools/"):
        return C_TEST
    if p.startswith("docs/") or p.startswith(".ai/") or ext == ".md" \
            or name in ("LICENSE.txt", "license-ru.txt", "license-en.txt", "README_FIRST_RU.txt"):
        return C_DOCS
    if p.startswith("printer_covers/") \
            or p.startswith("web/vendor/") or p.startswith("web/assets/") \
            or p.startswith("web/design/") or name == "ffmpeg.exe":
        return C_ASSET
    if ext in (".spec", ".iss", ".bat", ".ps1") or name == "requirements.txt" \
            or name.startswith("desktop_shell_version") or ext == ".pyw":
        return C_BUILD
    if p == "server.py" or p.startswith("app/") or p.startswith("web/") \
            or p.startswith("one_shot_print/"):
        return C_PRODUCT
    if p in (".gitignore", ".gitattributes"):
        return C_BUILD
    if p in tracked:
        # Отслеживаемый файл без опознанной роли — НЕ мусор. Он попал в историю
        # осознанно; доказательство ненужности должен предъявить человек.
        return C_UNKNOWN if not refs else C_PRODUCT
    return C_UNKNOWN


def main():
    ap = argparse.ArgumentParser(description="Read-only аудит состава рабочей папки")
    ap.add_argument("--out", default="", help="файл полного отчёта (Markdown)")
    ap.add_argument("--json", default="", help="файл машинного слепка")
    ap.add_argument("--hash-limit", type=int, default=512 * 1024 * 1024,
                    help="не считать SHA-256 для файлов больше этого размера")
    args = ap.parse_args()

    t0 = time.time()
    tracked = collect_tracked()
    rows = walk_files()
    ignored = collect_ignored([r["path"] for r in rows])
    corpus = build_reference_corpus()
    dsz = dir_sizes(rows)

    by_hash = {}
    for r in rows:
        r["tracked"] = r["path"] in tracked
        r["ignored"] = (r["path"] in ignored) and not r["tracked"]
        r["untracked"] = (not r["tracked"]) and (not r["ignored"])
        r["refs"] = referrers(corpus, r) if r["size"] < 8 * 1024 * 1024 or r["tracked"] else []
        r["cat"] = classify(r, tracked, ignored, r["refs"])
        r["sha"] = sha256(r["abs"]) if r["size"] <= args.hash_limit else ""
        if r["sha"]:
            by_hash.setdefault(r["sha"], []).append(r["path"])

    # .git считаем отдельно: это история, а не состав рабочего дерева.
    git_size = 0
    for root, _d, files in os.walk(os.path.join(REPO, ".git")):
        for f in files:
            try:
                git_size += os.path.getsize(os.path.join(root, f))
            except Exception:
                pass

    total = sum(r["size"] for r in rows)
    L = []

    def w(s=""):
        L.append(s)

    w("# Аудит рабочей папки — 3DIWELL Farm Manager")
    w()
    w("Инструмент: `tools/repository_audit.py` (только чтение).")
    w("Корень: `%s`" % REPO)
    w("Файлов вне `.git`: **%d**; каталогов: **%d**." % (len(rows), len(dsz) - 1))
    w("Размер рабочего дерева без `.git`: **%s**; `.git`: **%s**; всего: **%s**."
      % (human(total), human(git_size), human(total + git_size)))
    w("Аудит выполнен за %.1f с." % (time.time() - t0))
    w()

    # ── Сводка по категориям ────────────────────────────────────────────────
    w("## 1. Сводка по категориям")
    w()
    w("| Категория | Файлов | Размер |")
    w("|---|---:|---:|")
    cats = {}
    for r in rows:
        c = cats.setdefault(r["cat"], [0, 0])
        c[0] += 1
        c[1] += r["size"]
    for c in sorted(cats):
        w("| %s | %d | %s |" % (c, cats[c][0], human(cats[c][1])))
    w("| **ИТОГО (без .git)** | **%d** | **%s** |" % (len(rows), human(total)))
    w()

    # ── Общий размер по группам ─────────────────────────────────────────────
    w("## 2. Общий размер по группам")
    w()
    groups = [
        ("Git-tracked source", sum(r["size"] for r in rows if r["tracked"])),
        ("tests (tools/)", dsz.get("tools", 0)),
        ("docs/handoff (docs/ + .ai/)", dsz.get("docs", 0) + dsz.get(".ai", 0)),
        ("module source (modules/)", dsz.get("modules", 0)),
        ("dist/", dsz.get("dist", 0)),
        ("build/ (PyInstaller work)", dsz.get("build", 0)),
        ("installer/", dsz.get("installer", 0)),
        ("caches (__pycache__/thumb_cache)", sum(r["size"] for r in rows if r["cat"] == C_CACHE)),
        ("generated artifacts", sum(r["size"] for r in rows if r["cat"] == C_GENERATED)),
        (".claude/", dsz.get(".claude", 0)),
        ("_incoming/", dsz.get("_incoming", 0)),
        (".git/ (история)", git_size),
        ("ВСЯ ПАПКА", total + git_size),
    ]
    w("| Группа | Размер |")
    w("|---|---:|")
    for n, s in groups:
        w("| %s | %s |" % (n, human(s)))
    w()

    # ── Каталоги больше 10 MB ───────────────────────────────────────────────
    w("## 3. Каталоги больше 10 MB")
    w()
    w("| Каталог | Размер |")
    w("|---|---:|")
    for d, s in sorted(dsz.items(), key=lambda kv: -kv[1]):
        if d and s > 10 * 1024 * 1024:
            w("| `%s/` | %s |" % (d, human(s)))
    w("| `.git/` | %s |" % human(git_size))
    w()

    # ── 100 крупнейших файлов ───────────────────────────────────────────────
    big = sorted(rows, key=lambda r: -r["size"])
    w("## 4. Сто крупнейших файлов")
    w()
    w("| # | Файл | Размер | Git | Возраст, дн. | Категория | Ссылок |")
    w("|---:|---|---:|---|---:|---|---:|")
    for i, r in enumerate(big[:100], 1):
        g = "tracked" if r["tracked"] else ("ignored" if r["ignored"] else "untracked")
        w("| %d | `%s` | %s | %s | %.1f | %s | %d |"
          % (i, r["path"], human(r["size"]), g, r["age_days"], r["cat"], len(r["refs"])))
    w()

    # ── Все файлы больше 1 MB ───────────────────────────────────────────────
    over1 = [r for r in big if r["size"] > 1024 * 1024]
    w("## 5. Все файлы больше 1 MB (%d шт.)" % len(over1))
    w()
    w("| Файл | Размер | Git | Категория | SHA-256 |")
    w("|---|---:|---|---|---|")
    for r in over1:
        g = "tracked" if r["tracked"] else ("ignored" if r["ignored"] else "untracked")
        w("| `%s` | %s | %s | %s | `%s` |"
          % (r["path"], human(r["size"]), g, r["cat"], r["sha"] or "—"))
    w()

    # ── Untracked (кроме .claude/ и _incoming/) ─────────────────────────────
    unt = [r for r in rows if r["untracked"]
           and r["path"].split("/")[0] not in ("_incoming", ".claude")]
    w("## 6. Untracked-файлы вне `.claude/` и `_incoming/` (%d шт.)" % len(unt))
    w()
    if unt:
        w("| Файл | Размер | Категория |")
        w("|---|---:|---|")
        for r in sorted(unt, key=lambda r: -r["size"]):
            w("| `%s` | %s | %s |" % (r["path"], human(r["size"]), r["cat"]))
    else:
        w("Таких файлов нет — рабочее дерево чистое.")
    w()

    # ── Игнорируемые генерируемые каталоги ──────────────────────────────────
    w("## 7. Игнорируемые генерируемые каталоги")
    w()
    w("| Каталог | Файлов | Размер | Что это |")
    w("|---|---:|---:|---|")
    known = {
        "build": "рабочий каталог PyInstaller (пересоздаётся сборкой)",
        "dist": "собранные EXE (рабочие копии программы)",
        "installer": "готовые установщики Inno Setup",
        "logs": "журналы рантайма",
        "thumb_cache": "кэш эскизов",
        "__pycache__": "байт-код Python",
    }
    seen = set()
    for r in rows:
        top = r["path"].split("/")[0]
        if top in known and top not in seen:
            seen.add(top)
            n = len([x for x in rows if x["path"].split("/")[0] == top])
            w("| `%s/` | %d | %s | %s |" % (top, n, human(dsz.get(top, 0)), known[top]))
    pyc = [r for r in rows if r["cat"] == C_CACHE and "__pycache__" in r["path"]]
    w("| `**/__pycache__/` (все) | %d | %s | %s |"
      % (len(pyc), human(sum(r["size"] for r in pyc)), known["__pycache__"]))
    w()

    # ── Дубликаты по SHA-256 ────────────────────────────────────────────────
    dups = {h: ps for h, ps in by_hash.items() if len(ps) > 1}
    w("## 8. Дубликаты с одинаковым SHA-256 (%d групп)" % len(dups))
    w()
    if dups:
        w("| SHA-256 (12) | Файлов | Пути |")
        w("|---|---:|---|")
        for h, ps in sorted(dups.items(), key=lambda kv: -len(kv[1]))[:60]:
            w("| `%s` | %d | %s |" % (h[:12], len(ps), ", ".join("`%s`" % x for x in ps[:6])))
    else:
        w("Дубликатов не найдено.")
    w()

    # ── Кандидаты без доказанной ссылки ─────────────────────────────────────
    noref = [r for r in rows if r["tracked"] and not r["refs"]
             and r["cat"] not in (C_DOCS,)]
    w("## 9. Tracked-файлы без НАЙДЕННОЙ текстовой ссылки (%d шт.)" % len(noref))
    w()
    w("> ВАЖНО: отсутствие текстовой ссылки НЕ доказывает ненужность. Возможны")
    w("> динамические импорты, `datas` из .spec, обнаружение модулей и рантайм-пути.")
    w("> Такие файлы остаются на месте до отдельного доказательства.")
    w()
    if noref:
        w("| Файл | Размер | Категория |")
        w("|---|---:|---|")
        for r in sorted(noref, key=lambda r: -r["size"])[:120]:
            w("| `%s` | %s | %s |" % (r["path"], human(r["size"]), r["cat"]))
    else:
        w("Таких файлов нет.")
    w()

    text = "\n".join(L)
    if args.out:
        d = os.path.dirname(os.path.abspath(args.out))
        if d and not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)
        io.open(args.out, "w", encoding="utf-8", newline="\n").write(text)
        print("Отчёт записан: %s (%d строк)" % (args.out, len(L)))
    if args.json:
        d = os.path.dirname(os.path.abspath(args.json))
        if d and not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)
        io.open(args.json, "w", encoding="utf-8", newline="\n").write(json.dumps(
            {"root": REPO, "files": [{k: v for k, v in r.items() if k != "abs"} for r in rows],
             "dirs": dsz, "git_size": git_size}, ensure_ascii=False, indent=1))
        print("Слепок записан: %s" % args.json)
    if not args.out and not args.json:
        print(text)
    else:
        # Короткая сводка на экран всегда — чтобы вызов был полезен без открытия файла.
        print("\n".join(L[:L.index("## 3. Каталоги больше 10 MB")]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
