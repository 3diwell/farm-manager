# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""29.09.2026 — помощник исторического эталона tools/_history_baseline.py.

Часть наборов сверяет текущий код с прошлым коммитом закрытой истории. В открытой копии
(tools/public_export.py) этой истории нет, и такие сверки там честно пропускаются (SKIP
с причиной). Этот набор закрепляет, что пропуск включается ТОЛЬКО в открытой копии:

  1. эталонный коммит есть — режим present, исторические проверки выполняются;
  2. эталона нет, метки открытой копии нет — режим missing: проверки выполняются и краснеют;
  3. эталона нет, метка есть, первого коммита закрытой истории нет — режим public (SKIP);
  4. метка есть, но первый коммит «закрытой истории» в репозитории лежит — НЕ public:
     метка, случайно попавшая в закрытое дерево, пропуска не включает;
  5. hcheck: в public печатает SKIP и не вычисляет условие; в missing исключение внутри
     условия — FAIL, а не обрыв набора; сводка ИТОГО согласована с построчным протоколом.

Безопасность: только временные git-репозитории во временной папке ОС, с пустыми настройками
git (без глобальных хуков и шаблонов владельца). Сеть, программа и рабочие данные не трогаются.

Запуск:  python tools/test_history_baseline.py   (0 = пройдено)
"""
import contextlib
import io
import os
import shutil
import stat
import subprocess
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))
sys.dont_write_bytecode = True
import _history_baseline as HB   # noqa: E402
from _gate_parse import parse_test_output   # noqa: E402

FAILED = []
PASSED = [0]


def check(name, ok):
    if ok:
        PASSED[0] += 1
        print("PASS — %s" % name)
    else:
        FAILED.append(name)
        print("FAIL — %s" % name)


def section(t):
    print("\n--- %s ---" % t)


TMP = tempfile.mkdtemp(prefix="fm_history_baseline_")
EMPTY_CFG = os.path.join(TMP, "empty.gitconfig")
io.open(EMPTY_CFG, "w").close()
#  Настройки git владельца (хуки, подпись, шаблоны) во временные репозитории не попадают;
#  переменные действуют и на вызовы git внутри помощника.
for _k in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
           "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_CEILING_DIRECTORIES"):
    os.environ.pop(_k, None)
#  Для раздела «настоящий репозиторий» настройки владельца нужны обратно: в них safe.directory,
#  без которого git отказывается читать папку проекта, созданную другой учётной записью Windows.
_OWNER_GIT_ENV = {_k: os.environ.get(_k) for _k in ("GIT_CONFIG_NOSYSTEM", "GIT_CONFIG_GLOBAL", "GIT_CEILING_DIRECTORIES")}
os.environ.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": EMPTY_CFG,
                   "GIT_TEMPLATE_DIR": "", "GIT_CEILING_DIRECTORIES": TMP,
                   "GIT_AUTHOR_NAME": "fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
                   "GIT_COMMITTER_NAME": "fixture", "GIT_COMMITTER_EMAIL": "fixture@example.invalid"})


def git(repo, *args):
    r = subprocess.run(["git", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=",
                        "-c", "core.autocrlf=false"] + list(args),
                       cwd=repo, capture_output=True)
    if r.returncode != 0:
        raise RuntimeError("git %s: %s" % (args[0], r.stderr.decode("utf-8", "replace")))
    return r.stdout.decode("utf-8", "replace").strip()


def make_repo(name, files, marker=False):
    """Временный репозиторий с одним коммитом. -> (путь, хеш коммита)."""
    d = os.path.join(TMP, name)
    os.makedirs(d)
    for rel, text in files.items():
        p = os.path.join(d, *rel.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        io.open(p, "w", encoding="utf-8", newline="\n").write(text)
    git(d, "init", "-q")
    git(d, "add", "-A")
    git(d, "commit", "-q", "-m", "fixture")
    if marker:   # метка кладётся после коммита, как её кладёт выгрузка — рядом с файлами
        p = os.path.join(d, *HB.PUBLIC_MARKER.split("/"))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        io.open(p, "w", encoding="utf-8").write("# public\n")
    return d, git(d, "rev-parse", "HEAD")


def run_quiet(fn):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        res = fn()
    return res, buf.getvalue()


ABSENT = "0123456789abcdef0123456789abcdef01234567"   # такого коммита нет ни в одном репозитории

try:
    print("=== помощник исторического эталона (tools/_history_baseline.py) ===")
    #  Выгрузка (tools/public_export.py) есть только в закрытом репозитории; в открытой копии
    #  сверяется лишь форма констант.
    _pe = os.path.join(REPO, "tools", "public_export.py")
    _pe_src = io.open(_pe, encoding="utf-8").read() if os.path.isfile(_pe) else None
    check("C0. метка и первый коммит закрытой истории — те же, что у выгрузки public_export.py",
          HB.PUBLIC_MARKER == "packaging/PUBLIC_TREE.md" and len(HB.PRIVATE_ROOT_COMMIT) >= 7
          and (_pe_src is None
               or (('ROOT_COMMIT = "%s"' % HB.PRIVATE_ROOT_COMMIT) in _pe_src
                   and ('PUBLIC_MARKER = "%s"' % HB.PUBLIC_MARKER) in _pe_src)))

    section("режимы")
    closed, c_head = make_repo("closed", {"server.py": "x = 1\n", "app/reg.py": "y = 2\n"})
    check("M1. эталонный коммит есть — present",
          HB.mode(closed, c_head, ["server.py", "app/reg.py"]) == HB.PRESENT)
    check("M1b. файл эталона читается как текст",
          HB.show(closed, c_head, "server.py") == "x = 1\n")
    check("M2. эталона нет, метки нет — missing (проверки выполняются и краснеют)",
          HB.mode(closed, ABSENT, ["server.py"]) == HB.MISSING)
    check("M2b. коммит есть, но файла в нём нет — не present",
          HB.mode(closed, c_head, ["server.py", "нет/такого.py"]) == HB.MISSING)
    check("M2c. нечитаемый эталон — None, без исключения",
          HB.show(closed, ABSENT, "server.py") is None
          and HB.show(os.path.join(TMP, "нет-такой-папки"), c_head, "server.py") is None)

    public, p_head = make_repo("public", {"server.py": "x = 1\n"}, marker=True)
    check("M3. эталона нет, метка есть, закрытого корня нет — public",
          HB.mode(public, ABSENT, ["server.py"]) == HB.PUBLIC)
    check("M3b. метка есть, но эталон читается — present (метка сама ничего не пропускает)",
          HB.mode(public, p_head, ["server.py"]) == HB.PRESENT)
    check("M4. метка есть и «первый коммит закрытой истории» в репозитории лежит — НЕ public",
          HB.mode(public, ABSENT, ["server.py"], root_commit=p_head) == HB.MISSING
          and not HB.is_public_tree(public, root_commit=p_head))
    check("M4b. то же по короткому хешу корня (как в константе)",
          HB.mode(public, ABSENT, ["server.py"], root_commit=p_head[:10]) == HB.MISSING)
    nogit = os.path.join(TMP, "nogit")
    os.makedirs(os.path.join(nogit, "packaging"))
    io.open(os.path.join(nogit, *HB.PUBLIC_MARKER.split("/")), "w").close()
    check("M5. выгрузка без истории git, но с меткой — public",
          HB.mode(nogit, ABSENT, ["server.py"]) == HB.PUBLIC)
    check("M5b. без истории git и без метки — missing",
          HB.mode(os.path.join(TMP, "closed", "app"), ABSENT, ["server.py"]) == HB.MISSING)

    section("исторические проверки: hcheck и сводка")
    got = []

    def fake_check(name, ok):
        got.append((name, bool(ok)))

    calls = []

    def thunk_true():
        calls.append(1)
        return True

    b_pub = HB.Baseline(public, ABSENT, ["server.py"], fake_check)
    res, out = run_quiet(lambda: b_pub.check("H1. проба", thunk_true))
    check("K1. public: SKIP с причиной, условие НЕ вычисляется, check набора не вызывается",
          res is None and not calls and not got and b_pub.skipped == ["H1. проба"]
          and out.startswith("SKIP — H1. проба: эталон %s" % ABSENT)
          and "открытой копии" in out)
    check("K1b. public: show() не обращается к git и отдаёт None", b_pub.show("server.py") is None)

    b_mis = HB.Baseline(closed, ABSENT, ["server.py"], fake_check)
    res, out = run_quiet(lambda: b_mis.check("H2. падает", lambda: None.split()))
    check("K2. missing: исключение в условии — FAIL с именем исключения, без обрыва",
          res is False and got[-1][1] is False and "AttributeError" in got[-1][0]
          and not b_mis.skipped and out == "")
    res, _ = run_quiet(lambda: b_mis.check("H3. пустой список", lambda: None == []))
    check("K3. missing: список расхождений None (эталона нет) — FAIL, а не ложная зелень",
          res is False and got[-1] == ("H3. пустой список", False))

    b_pre = HB.Baseline(closed, c_head, ["server.py"], fake_check)
    run_quiet(lambda: b_pre.check("H4. верно", lambda: HB.show(closed, c_head, "server.py") == "x = 1\n"))
    run_quiet(lambda: b_pre.check("H5. неверно", lambda: False))
    check("K4. present: условие вычисляется, верное — PASS, неверное — FAIL",
          got[-2] == ("H4. верно", True) and got[-1] == ("H5. неверно", False))

    #  Сводка: код выхода и согласие гейта с построчным протоколом.
    b_sum = HB.Baseline(public, ABSENT, ["server.py"], fake_check)
    run_quiet(lambda: b_sum.check("H6", thunk_true))
    rc_pub, out_pub = run_quiet(lambda: b_sum.summary(5, 0))
    proto_pub = "PASS — a\n" * 5 + "SKIP — H6: x\n" + out_pub
    g_pub = parse_test_output("t.py", proto_pub, "", rc_pub, False, 0.1)
    check("K5. открытая копия: rc 0, ИТОГО PASS=5 FAIL=0 SKIP=1, гейт видит 1 пропуск без расхождений",
          rc_pub == 0 and "ИТОГО: PASS=5 FAIL=0 SKIP=1" in out_pub
          and "пропущено 1" in out_pub and "все 5" not in out_pub
          and g_pub["counts_source"] == "summary" and g_pub["skip_count"] == 1
          and g_pub["fail_count"] == 0)
    rc_bad, out_bad = run_quiet(lambda: b_mis.summary(3, ["H2", "H3"]))
    proto_bad = "PASS — a\n" * 3 + "FAIL — H2\nFAIL — H3\n" + out_bad
    g_bad = parse_test_output("t.py", proto_bad, "", rc_bad, False, 0.1)
    check("K6. провал: rc 1, строка о провале не считается лишним FAIL, гейт — красный без расхождения",
          rc_bad == 1 and "ИТОГО: PASS=3 FAIL=2 SKIP=0" in out_bad and "   - H2" in out_bad
          and g_bad["counts_source"] == "summary" and g_bad["fail_count"] == 2
          and g_bad["status"] == "red")
    b_ok = HB.Baseline(closed, c_head, ["server.py"], fake_check)
    rc_ok, out_ok = run_quiet(lambda: b_ok.summary(7, 0))
    g_ok = parse_test_output("t.py", "PASS — a\n" * 7 + out_ok, "", rc_ok, False, 0.1)
    check("K7. закрытый репозиторий без пропусков: прежняя фраза «все N» и зелёный гейт",
          rc_ok == 0 and "PASS: все 7 проверок пройдены" in out_ok
          and "ИТОГО: PASS=7 FAIL=0 SKIP=0" in out_ok and g_ok["status"] == "green")

    section("настоящий репозиторий")
    #  Здесь эталоны наборов обязаны читаться. В открытой копии этот пункт сам уходит в SKIP.
    for _k, _v in _OWNER_GIT_ENV.items():
        if _v is None:
            os.environ.pop(_k, None)
        else:
            os.environ[_k] = _v
    b_real = HB.Baseline(REPO, "8fe9e70", ["server.py"], check)
    b_real.check("R1. в этом дереве эталон наборов (8fe9e70:server.py) читается",
                 lambda: b_real.present)
    if not b_real.public:
        check("R2. закрытое дерево не считается открытой копией", not HB.is_public_tree(REPO))
    else:
        check("R2. открытая копия: метка есть, закрытого корня нет",
              os.path.isfile(os.path.join(REPO, *HB.PUBLIC_MARKER.split("/")))
              and not HB.has_commit(REPO, HB.PRIVATE_ROOT_COMMIT))
    SKIPPED = b_real.skipped
finally:
    #  Объекты git в Windows только для чтения: снимаем атрибут и удаляем.
    def _rm_readonly(func, path, _exc):
        os.chmod(path, stat.S_IWRITE)
        func(path)
    if sys.version_info >= (3, 12):
        shutil.rmtree(TMP, onexc=_rm_readonly)
    else:
        shutil.rmtree(TMP, onerror=_rm_readonly)

check("Z1. временная папка набора убрана", not os.path.exists(TMP))

print("\n" + "=" * 76)
if FAILED:
    print("Провалено %d из %d:" % (len(FAILED), len(FAILED) + PASSED[0]))
    for f in FAILED:
        print("   - %s" % f)
elif SKIPPED:
    print("PASS: пройдено %d, пропущено %d" % (PASSED[0], len(SKIPPED)))
else:
    print("PASS: все %d проверок пройдены" % PASSED[0])
print("ИТОГО: PASS=%d FAIL=%d SKIP=%d" % (PASSED[0], len(FAILED), len(SKIPPED)))
sys.exit(1 if FAILED else 0)
