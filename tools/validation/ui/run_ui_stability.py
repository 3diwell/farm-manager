# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.841 / этап 3C — квалификация стабильности UI-проверки.

ЗАЧЕМ. Один зелёный прогон ничего не говорит о том, можно ли на проверку опереться.
Хрупкий браузерный шаг, подключённый к автоматике, начнёт красить безобидные правки —
и доверие к проверкам умрёт быстрее, чем принесёт пользу. Здесь измеряется именно это:
десять последовательных циклов без единого повтора, без остаточных процессов, без внешней
сети и с предсказуемым временем.

ЧТО ДЕЛАЕТ. Управляет серией СУЩЕСТВУЮЩИХ сценариев: вызывает `run_ui_verification.py`
подпроцессом и разбирает его артефакты. Своей интерпретации интерфейса здесь нет и быть
не должно — иначе квалификация мерила бы саму себя.

ГЛАВНОЕ ПРАВИЛО. Индивидуальный повтор запрещён. Любой красный прогон обрывает серию,
и счётчик начинается с нуля, а не продолжается. «Почти квалифицирован» не существует.

    python tools/validation/ui/run_ui_stability.py            # план
    python tools/validation/ui/run_ui_stability.py --execute  # настоящая серия

Коды: 0 QUALIFIED или DRY_RUN · 2 NOT_QUALIFIED · 5 CONFIG_ERROR · 6 внутренний сбой.
"""
import argparse
import datetime
import hashlib
import io
import json
import math
import os
import re
import socket
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
VERIFIER = os.path.join(HERE, "run_ui_verification.py")
SERIES_DIR = os.path.join(REPO, "logs", "ui_stability")
RUNS_DIR = os.path.join(REPO, "logs", "ui_runs")

SCHEMA = "3diwell-ui-stability-v1"
QUALIFIED, NOT_QUALIFIED, CONFIG_ERROR, DRY_RUN = (
    "QUALIFIED", "NOT_QUALIFIED", "CONFIG_ERROR", "DRY_RUN")
EXIT = {QUALIFIED: 0, DRY_RUN: 0, NOT_QUALIFIED: 2, CONFIG_ERROR: 5}
EXIT_INTERNAL = 6

REQUIRED_CYCLES = 10
STATIC_ID = "settings_panel_open_close"
ISOLATED_ID = "settings_panel_open_close_isolated"

MAX_ISOLATED_SECONDS = 60.0
MAX_STATIC_SECONDS = 30.0
DEVIATION = 0.30                     # допустимое отклонение от медианы, доли

# Файлы кандидата. Меняться во время серии они не имеют права: иначе неизвестно,
# стабильность ЧЕГО измерена.
CANDIDATE_FILES = (
    "server.py", "app/e2e_isolation.py", "web/index.html", "web/app.js", "web/app.css",
    "tools/validation/ui/run_ui_verification.py", "tools/validation/ui/_ui_driver.mjs",
    "tools/validation/ui/_stage_server.py",
    "tools/validation/ui/network_guard/sitecustomize.py",
    "tools/validation/ui/scenarios.json", "tools/validation/ui/run_ui_stability.py",
)
PRODUCT_PATHS = ("server.py", "app", "web", "modules", "tools/release_gate.py")
UPDATE_HOST_HINT = "3diwell"


class ConfigError(Exception):
    """Неверная конфигурация: серия не начинается."""


# ── Статистика на стандартной библиотеке ─────────────────────────────────────
def _median(xs):
    s = sorted(xs)
    n = len(s)
    if not n:
        return None
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def _percentile(xs, q):
    """Метод ближайшего ранга: p90 из десяти значений — девятое по возрастанию."""
    s = sorted(xs)
    if not s:
        return None
    k = max(1, int(math.ceil(q / 100.0 * len(s))))
    return s[min(k, len(s)) - 1]


def _stdev(xs):
    n = len(xs)
    if n < 2:
        return 0.0
    m = sum(xs) / float(n)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / float(n - 1))


def metrics(rows):
    d = [r["duration_seconds"] for r in rows if r.get("duration_seconds") is not None]
    out = {"count": len(rows), "pass_count": sum(1 for r in rows if r["status"] == "PASS"),
           "fail_count": sum(1 for r in rows if r["status"] != "PASS"),
           "min": None, "max": None, "mean": None, "median": None, "p90": None,
           "p95": None, "stdev": None, "coefficient_of_variation": None,
           "max_to_median": None}
    if not d:
        return out
    mean = sum(d) / float(len(d))
    med = _median(d)
    sd = _stdev(d)
    out.update(min=round(min(d), 3), max=round(max(d), 3), mean=round(mean, 3),
               median=round(med, 3), p90=round(_percentile(d, 90), 3),
               p95=round(_percentile(d, 95), 3), stdev=round(sd, 4),
               coefficient_of_variation=round(sd / mean, 4) if mean else None,
               max_to_median=round(max(d) / med, 3) if med else None)
    return out


# ── Отпечатки ────────────────────────────────────────────────────────────────
def _sha(path):
    return hashlib.sha256(io.open(path, "rb").read()).hexdigest()


def candidate_fingerprint():
    files = {}
    for rel in CANDIDATE_FILES:
        p = os.path.join(REPO, rel)
        files[rel] = _sha(p) if os.path.isfile(p) else None
    return files


def product_fingerprint():
    h = hashlib.sha256()
    n = 0
    for rel in PRODUCT_PATHS:
        full = os.path.join(REPO, rel)
        if os.path.isfile(full):
            st = os.stat(full)
            h.update(("%s|%d|%d\n" % (rel, st.st_size, int(st.st_mtime))).encode("utf-8"))
            n += 1
            continue
        for base, dirs, names in os.walk(full):
            dirs[:] = sorted(x for x in dirs if x != "__pycache__")
            for f in sorted(names):
                p = os.path.join(base, f)
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                r = os.path.relpath(p, REPO).replace("\\", "/")
                h.update(("%s|%d|%d\n" % (r, st.st_size, int(st.st_mtime))).encode("utf-8"))
                n += 1
    return {"entries": n, "sha256": h.hexdigest()}


def _ps(command):
    """Read-only запрос к системе. Ничего не завершает."""
    try:
        p = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                            command], capture_output=True, text=True, shell=False,
                           timeout=40,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return (p.stdout or "").strip()
    except Exception:
        return ""


def environment_snapshot():
    node = ""
    for c in (r"C:\Program Files\nodejs\node.exe",):
        if os.path.isfile(c):
            try:
                node = subprocess.run([c, "--version"], capture_output=True, text=True,
                                      shell=False, timeout=20).stdout.strip()
            except Exception:
                node = ""
    engine = next((p for p in (
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe") if os.path.isfile(p)),
        None)
    ver = ""
    if engine:
        ver = _ps("(Get-Item %s).VersionInfo.ProductVersion" % json.dumps(engine))
    commit = ""
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True,
                                text=True, shell=False, timeout=30).stdout.strip()
    except Exception:
        commit = ""
    app_version = ""
    try:
        m = re.search(r'APP_VERSION\s*=\s*"([^"]+)"',
                      io.open(os.path.join(REPO, "server.py"), encoding="utf-8",
                              errors="replace").read())
        app_version = m.group(1) if m else ""
    except Exception:
        app_version = ""
    return {
        "git_commit": commit, "app_version": app_version,
        "python": sys.version.split()[0], "node": node, "os": sys.platform,
        "os_release": _ps("(Get-CimInstance Win32_OperatingSystem).Version"),
        # Путь к движку сохраняется отпечатком: сам путь в отчёт не пишется.
        "engine_path_sha256": hashlib.sha256((engine or "").encode()).hexdigest()
        if engine else None,
        "engine_version": ver or None,
    }


def owned_e2e_processes():
    """Есть ли в системе выжившие изолированные экземпляры. Только чтение."""
    out = _ps("@(Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
              "Where-Object { $_.CommandLine -and $_.CommandLine -like "
              "'*fm-packaged-e2e*' }).Count")
    try:
        return int((out or "0").splitlines()[-1].strip())
    except Exception:
        return -1


def port_is_free(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.settimeout(1.0)
        return s.connect_ex(("127.0.0.1", int(port))) != 0
    finally:
        s.close()


def pid_alive(pid):
    if not pid:
        return False
    try:
        r = subprocess.run(["tasklist", "/FI", "PID eq %d" % int(pid), "/NH"],
                           capture_output=True, text=True, shell=False, timeout=25)
        return str(pid) in (r.stdout or "")
    except Exception:
        return False


# ── Один прогон существующего верификатора ───────────────────────────────────
def invoke_verifier(scenario_id, timeout_s=600):
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    t0 = time.time()
    p = subprocess.run([sys.executable, VERIFIER, "--scenario", scenario_id, "--execute",
                        "--json"], cwd=REPO, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", shell=False, env=env,
                       timeout=timeout_s)
    wall = round(time.time() - t0, 3)
    try:
        summary = json.loads(p.stdout)
    except Exception:
        return None, wall, p.returncode, (p.stdout or "")[:400] + (p.stderr or "")[:400]
    return summary, wall, p.returncode, ""


def _run_dir(summary):
    ap = summary.get("artifacts_path")
    return os.path.join(REPO, ap) if ap else None


def _read_json(path, default=None):
    try:
        return json.load(io.open(path, encoding="utf-8"))
    except Exception:
        return default


def check_run(summary, wall, rc, mode):
    """Требования шагов 6 и 7 к ОДНОМУ прогону. -> список нарушений."""
    bad = []
    rd = _run_dir(summary)

    def need(cond, why):
        if not cond:
            bad.append(why)

    need(summary.get("status") == "PASS", "статус %s вместо PASS" % summary.get("status"))
    need(rc == 0, "код возврата %s" % rc)
    need(summary.get("application_mode") == mode,
         "режим %s вместо %s" % (summary.get("application_mode"), mode))
    need(summary.get("assertions_total") and
         summary.get("assertions_passed") == summary.get("assertions_total"),
         "проверки DOM %s/%s" % (summary.get("assertions_passed"),
                                 summary.get("assertions_total")))
    need(summary.get("console_error_count") == 0,
         "ошибок консоли %s" % summary.get("console_error_count"))
    need(summary.get("external_network_attempt_count") == 0,
         "внешних обращений браузера %s" % summary.get("external_network_attempt_count"))
    need(summary.get("cleanup_status") == "clean",
         "уборка %s" % summary.get("cleanup_status"))
    need(summary.get("port_released") is True, "порт не освобождён")
    need(not summary.get("remaining_owned_processes"), "остались свои процессы")

    console = _read_json(os.path.join(rd, "console.json"), {}) if rd else {}
    need(len(console.get("warnings") or []) == 0,
         "предупреждений консоли %d" % len(console.get("warnings") or []))

    shots = summary.get("screenshots") or []
    for n in ("01_before.png", "02_settings_open.png", "03_restored.png"):
        need(n in shots, "нет снимка %s" % n)
    if rd and all(n in shots for n in ("01_before.png", "02_settings_open.png",
                                       "03_restored.png")):
        art = os.path.join(rd, "artifacts")
        try:
            h1 = _sha(os.path.join(art, "01_before.png"))
            h2 = _sha(os.path.join(art, "02_settings_open.png"))
            h3 = _sha(os.path.join(art, "03_restored.png"))
            # Побайтовое равенство «до» и «восстановлено» требуется ТОЛЬКО от статического
            # стенда: там ответы /api синтетические и картинка детерминирована. С живым
            # backend страница продолжает жить между снимками, и байтовое равенство
            # доказывало бы не восстановление состояния, а отсутствие жизни. Восстановление
            # в изолированном режиме доказывает проверка DOM assert_hidden, а не пиксели.
            if mode == "static_harness":
                need(h1 == h3, "снимок «до» и «восстановлено» различаются")
            need(h2 != h1, "снимок открытой панели совпал с исходным")
        except Exception as e:
            bad.append("снимки не прочитаны: %s" % str(e)[:60])

    if mode == "isolated_farm_manager":
        need(summary.get("readiness_verified") is True, "готовность не подтверждена")
        need(summary.get("e2e_contract_verified") is True, "контракт E2E не подтверждён")
        need(summary.get("network_guard_active") is True, "сторож сети неактивен")
        need(summary.get("network_guard_sentinel") is True, "нет удостоверения сторожа")
        need(summary.get("backend_assertions_total") and
             summary.get("backend_assertions_passed") ==
             summary.get("backend_assertions_total"),
             "проверки backend %s/%s" % (summary.get("backend_assertions_passed"),
                                         summary.get("backend_assertions_total")))
        need(summary.get("blocked_network_attempts") == 0,
             "заблокированных попыток %s" % summary.get("blocked_network_attempts"))
        need(summary.get("production_data_unchanged") is True,
             "рабочая папка владельца изменилась")
        need(summary.get("repository_product_files_unchanged") is True,
             "продуктовые файлы изменились")
        ba = _read_json(os.path.join(rd, "backend_assertions.json"), []) if rd else []
        ids = set(x.get("id") for x in ba)
        need("update_check_suppressed" in ids and
             next((x["passed"] for x in ba if x["id"] == "update_check_suppressed"), False),
             "подавление проверки обновлений не доказано")
        need("update_suppression_declared_by_contract" in ids,
             "нет подтверждения подавления самим контрактом")
        guard = []
        if rd:
            gp = os.path.join(rd, "network_guard", "guard.jsonl")
            if os.path.isfile(gp):
                for line in io.open(gp, encoding="utf-8", errors="replace"):
                    if line.strip():
                        try:
                            guard.append(json.loads(line))
                        except Exception:
                            pass
        need(not [g for g in guard if UPDATE_HOST_HINT in str(g.get("host", "")).lower()],
             "в журнале сторожа есть обращение к узлу обновлений")
        need(not [g for g in guard if not g.get("allowed")],
             "сторож зафиксировал заблокированную попытку")
        need(summary.get("test_database_created") is True, "тестовая БД не создана")
    return bad


def collect_row(cycle, pos, scenario_id, summary, wall, rc, mode, violations):
    rd = _run_dir(summary) if summary else None
    console = _read_json(os.path.join(rd, "console.json"), {}) if rd else {}
    ph = (summary or {}).get("phase_seconds") or {}
    url = (summary or {}).get("local_url") or ""
    m = re.search(r":(\d+)/", url)
    return {
        "cycle": cycle, "sequence_position": pos, "scenario_id": scenario_id,
        "mode": mode, "run_id": (summary or {}).get("run_id"),
        "status": (summary or {}).get("status", "NO_RESULT"),
        "exit_code": rc, "duration_seconds": (summary or {}).get("duration_seconds"),
        "wall_seconds": wall,
        "startup_seconds": ph.get("startup"), "readiness_seconds": ph.get("readiness"),
        "browser_action_seconds": ph.get("browser"), "cleanup_seconds": ph.get("cleanup"),
        "server_pid": (summary or {}).get("server_pid"),
        "browser_pid": (summary or {}).get("browser_pid"),
        "port": int(m.group(1)) if m else None,
        "dom_assertions_passed": (summary or {}).get("assertions_passed"),
        "dom_assertions_total": (summary or {}).get("assertions_total"),
        "backend_assertions_passed": (summary or {}).get("backend_assertions_passed"),
        "backend_assertions_total": (summary or {}).get("backend_assertions_total"),
        "console_errors": (summary or {}).get("console_error_count"),
        "console_warnings": len(console.get("warnings") or []),
        "browser_requests": (summary or {}).get("browser_network_attempts")
        or len((summary or {}).get("network") or []),
        "browser_external_requests": (summary or {}).get("external_network_attempt_count"),
        "backend_requests": (summary or {}).get("backend_network_attempts"),
        "backend_external_requests": (summary or {}).get("blocked_network_attempts"),
        "blocked_requests": (summary or {}).get("blocked_network_attempts"),
        "screenshots": (summary or {}).get("screenshots") or [],
        "cleanup_status": (summary or {}).get("cleanup_status"),
        "remaining_processes": (summary or {}).get("remaining_owned_processes") or [],
        "browser_profile_path": (summary or {}).get("browser_profile_path"),
        "test_data_path": (summary or {}).get("test_data_path"),
        "artifacts_path": (summary or {}).get("artifacts_path"),
        "violations": violations,
    }


def between_runs_check(row, prev_rows, prod_before, product_before):
    """Требования шага 8. Следующий прогон не начинается, пока это не сошлось."""
    bad = []
    if pid_alive(row.get("browser_pid")):
        bad.append("PID браузера %s жив" % row["browser_pid"])
    if pid_alive(row.get("server_pid")):
        bad.append("PID сервера %s жив" % row["server_pid"])
    if row.get("port") and not port_is_free(row["port"]):
        bad.append("порт %s занят" % row["port"])
    if row.get("browser_profile_path") in [r.get("browser_profile_path")
                                           for r in prev_rows]:
        bad.append("профиль браузера повторно использован")
    if row["mode"] == "isolated_farm_manager" and row.get("test_data_path") in [
            r.get("test_data_path") for r in prev_rows
            if r["mode"] == "isolated_farm_manager"]:
        bad.append("тестовая папка данных повторно использована")
    if row.get("run_id") in [r.get("run_id") for r in prev_rows]:
        bad.append("run-id повторно использован")
    alive = owned_e2e_processes()
    if alive > 0:
        bad.append("в системе остались изолированные экземпляры: %d" % alive)
    if prod_before:
        now = _production_fp()
        if now.get("sha256") != prod_before.get("sha256"):
            bad.append("рабочая папка владельца изменилась после прогона")
    if product_before:
        nowp = product_fingerprint()
        if nowp.get("sha256") != product_before.get("sha256"):
            bad.append("продуктовые файлы репозитория изменились после прогона")
    # Журнал сторожа обязан быть дочитан целиком: оборванная строка означает, что
    # изолированный процесс не завершился штатно.
    rd = os.path.join(REPO, row["artifacts_path"]) if row.get("artifacts_path") else None
    if row["mode"] == "isolated_farm_manager" and rd:
        gp = os.path.join(rd, "network_guard", "guard.jsonl")
        if not os.path.isfile(gp):
            bad.append("журнала сторожа сети нет")
        else:
            for line in io.open(gp, encoding="utf-8", errors="replace"):
                if not line.strip():
                    continue
                try:
                    json.loads(line)
                except Exception:
                    bad.append("журнал сторожа оборван на незавершённой записи")
                    break
        if not os.path.isfile(os.path.join(rd, "network_guard", "sentinel.json")):
            bad.append("удостоверение сторожа не найдено после прогона")
    return bad


# ── Серия ────────────────────────────────────────────────────────────────────
def plan(cycles):
    """Порядок сценариев чередуется: так видно проблемы уборки в обе стороны."""
    out = []
    for c in range(1, cycles + 1):
        order = (STATIC_ID, ISOLATED_ID) if c % 2 else (ISOLATED_ID, STATIC_ID)
        for pos, sid in enumerate(order, start=1):
            out.append({"cycle": c, "sequence_position": pos, "scenario_id": sid,
                        "mode": ("static_harness" if sid == STATIC_ID
                                 else "isolated_farm_manager")})
    return out


def evaluate(rows, cand_before, cand_after, prod_before, prod_after, product_before,
             product_after, cycles, test_mode, restarted, aborted_reason):
    """Критерии шага 10. Никаких «почти»: не сошлось — NOT_QUALIFIED."""
    static = [r for r in rows if r["mode"] == "static_harness"]
    iso = [r for r in rows if r["mode"] == "isolated_farm_manager"]
    ms, mi = metrics(static), metrics(iso)
    failed = []

    def crit(cid, ok, detail=""):
        if not ok:
            failed.append({"id": cid, "detail": str(detail)[:200]})
        return ok

    crit("cycles_required_10", cycles >= REQUIRED_CYCLES and not test_mode,
         "циклов %d, test_mode=%s" % (cycles, test_mode))
    crit("static_all_pass", ms["pass_count"] == cycles and ms["count"] == cycles,
         "%s/%s" % (ms["pass_count"], cycles))
    crit("isolated_all_pass", mi["pass_count"] == cycles and mi["count"] == cycles,
         "%s/%s" % (mi["pass_count"], cycles))
    crit("no_individual_retries", True, "повторов не предусмотрено конструкцией")
    crit("no_timeout", all(r["status"] != "TIMEOUT" for r in rows))
    crit("no_console_errors", all((r["console_errors"] or 0) == 0 for r in rows))
    crit("no_console_warnings", all((r["console_warnings"] or 0) == 0 for r in rows))
    crit("no_browser_external", all((r["browser_external_requests"] or 0) == 0
                                    for r in rows))
    crit("no_backend_external", all((r["blocked_requests"] or 0) == 0 for r in iso))
    crit("no_blocked_attempts", all((r["blocked_requests"] or 0) == 0 for r in iso))
    crit("no_remaining_processes", all(not r["remaining_processes"] for r in rows))
    crit("all_ports_released", all(r.get("port") and port_is_free(r["port"])
                                   for r in rows),
         "портов проверено %d" % len(rows))
    profiles = [r["browser_profile_path"] for r in rows]
    crit("unique_browser_profiles", len(set(profiles)) == len(profiles))
    datadirs = [r["test_data_path"] for r in iso]
    crit("unique_isolated_data_dirs", len(set(datadirs)) == len(datadirs))
    crit("production_data_unchanged",
         prod_before.get("sha256") == prod_after.get("sha256"),
         "%s -> %s" % (prod_before.get("entries"), prod_after.get("entries")))
    crit("product_files_unchanged",
         product_before.get("sha256") == product_after.get("sha256"))
    diff = [k for k in cand_before if cand_before[k] != cand_after.get(k)]
    crit("candidate_fingerprint_stable", not diff, diff)
    dom = set((r["dom_assertions_total"] for r in rows if r["dom_assertions_total"]))
    crit("dom_assertion_set_stable", len(dom) <= 2, sorted(dom))
    ba = set(r["backend_assertions_total"] for r in iso if r["backend_assertions_total"])
    crit("backend_assertion_set_stable", len(ba) == 1, sorted(ba))
    crit("isolated_under_60s", (mi["max"] or 0) < MAX_ISOLATED_SECONDS, mi["max"])
    crit("static_under_30s", (ms["max"] or 0) < MAX_STATIC_SECONDS, ms["max"])
    for name, m, rs in (("static", ms, static), ("isolated", mi, iso)):
        med = m["median"]
        out = [r["duration_seconds"] for r in rs
               if med and r.get("duration_seconds") is not None
               and (r["duration_seconds"] < med * (1 - DEVIATION)
                    or r["duration_seconds"] > med * (1 + DEVIATION))]
        crit("%s_within_30pct_of_median" % name, not out,
             "медиана %s, вне коридора: %s" % (med, out))
    crit("series_not_aborted", not aborted_reason, aborted_reason or "")
    crit("at_most_one_restart", restarted <= 1, restarted)

    status = QUALIFIED if not failed else NOT_QUALIFIED
    if test_mode or cycles < REQUIRED_CYCLES:
        status = NOT_QUALIFIED     # заявить квалификацию сокращённой серией нельзя
        if not any(f["id"] == "cycles_required_10" for f in failed):
            failed.append({"id": "cycles_required_10",
                           "detail": "серия короче десяти циклов или test-mode"})
    return status, failed, ms, mi


def run_series(cycles=REQUIRED_CYCLES, execute=False, test_mode=False, restarted=0,
               previous_series_id=None):
    if not os.path.isfile(VERIFIER):
        raise ConfigError("верификатор не найден: %s" % VERIFIER)
    if cycles < REQUIRED_CYCLES and not test_mode:
        raise ConfigError("для квалификации требуется %d циклов; сокращённая серия "
                          "допустима только с --test-mode и квалификацией не считается"
                          % REQUIRED_CYCLES)
    started = datetime.datetime.now()
    series_id = started.strftime("%Y%m%d-%H%M%S") + "-" + os.urandom(3).hex()
    steps = plan(cycles)
    res = {
        "schema_version": SCHEMA, "series_id": series_id,
        "started_at": started.isoformat(timespec="seconds"), "finished_at": None,
        "duration_seconds": 0.0, "cycles_required": REQUIRED_CYCLES,
        "cycles_requested": cycles, "cycles_completed": 0, "total_runs_planned": len(steps),
        "total_runs": 0, "test_mode": bool(test_mode), "restarted_series": restarted,
        "previous_series_id": previous_series_id, "status": None, "exit_code": None,
        "static_passes": 0, "isolated_passes": 0, "failed_criteria": [],
        "aborted_reason": None, "artifacts_path": None,
        "limitations": [
            "квалификация относится ТОЛЬКО к двум проверенным сценариям и одному экрану",
            "печать, оборудование и остальные экраны не проверяются",
            "статический стенд отдаёт синтетические /api: backend им не проверяется",
            "изолированный экземпляр всегда свежий: поведение на данных владельца не измеряется",
            "QUALIFIED не означает автоматического подключения к исполнителю",
        ],
    }
    if not execute:
        res.update(status=DRY_RUN, exit_code=EXIT[DRY_RUN],
                   finished_at=datetime.datetime.now().isoformat(timespec="seconds"))
        res["plan"] = steps
        return res, [], None

    out_dir = os.path.join(SERIES_DIR, series_id)
    os.makedirs(out_dir, exist_ok=True)
    res["artifacts_path"] = os.path.relpath(out_dir, REPO).replace("\\", "/")

    cand_before = candidate_fingerprint()
    prod_before = _production_fp()
    product_before = product_fingerprint()
    env_snap = environment_snapshot()
    _write(out_dir, "candidate_fingerprint_before.json",
           {"files": cand_before, "environment": env_snap,
            "started_at": res["started_at"]})

    rows, aborted = [], None
    t0 = time.time()
    runs_path = os.path.join(out_dir, "runs.jsonl")
    for step in steps:
        summary, wall, rc, err = invoke_verifier(step["scenario_id"])
        if summary is None:
            aborted = "прогон не вернул разбираемого результата: %s" % err[:160]
            rows.append(collect_row(step["cycle"], step["sequence_position"],
                                    step["scenario_id"], {}, wall, rc, step["mode"],
                                    [aborted]))
            break
        violations = check_run(summary, wall, rc, step["mode"])
        row = collect_row(step["cycle"], step["sequence_position"], step["scenario_id"],
                          summary, wall, rc, step["mode"], violations)
        between = between_runs_check(row, rows, prod_before, product_before)
        row["between_runs_violations"] = between
        rows.append(row)
        with io.open(runs_path, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        if violations or between:
            aborted = ("цикл %d, %s: %s" % (step["cycle"], step["scenario_id"],
                                            "; ".join(violations + between)[:220]))
            break     # серия обрывается немедленно; индивидуального повтора не будет

    res["total_runs"] = len(rows)
    res["cycles_completed"] = len(set(r["cycle"] for r in rows
                                      if not r["violations"]
                                      and not r.get("between_runs_violations"))) \
        if not aborted else max(0, min(r["cycle"] for r in rows if r["violations"]
                                       or r.get("between_runs_violations")) - 1)
    res["static_passes"] = sum(1 for r in rows if r["mode"] == "static_harness"
                               and r["status"] == "PASS" and not r["violations"])
    res["isolated_passes"] = sum(1 for r in rows if r["mode"] == "isolated_farm_manager"
                                 and r["status"] == "PASS" and not r["violations"])
    res["aborted_reason"] = aborted

    cand_after = candidate_fingerprint()
    prod_after = _production_fp()
    product_after = product_fingerprint()
    _write(out_dir, "candidate_fingerprint_after.json",
           {"files": cand_after, "finished_at":
            datetime.datetime.now().isoformat(timespec="seconds")})

    status, failed, ms, mi = evaluate(rows, cand_before, cand_after, prod_before,
                                      prod_after, product_before, product_after,
                                      cycles, test_mode, restarted, aborted)
    res.update(status=status, failed_criteria=failed, exit_code=EXIT[status],
               duration_seconds=round(time.time() - t0, 3),
               finished_at=datetime.datetime.now().isoformat(timespec="seconds"))
    _write_series_artifacts(out_dir, res, rows, ms, mi, cand_before, cand_after,
                            prod_before, prod_after, product_before, product_after,
                            env_snap)
    return res, rows, out_dir


def _production_fp():
    """Отпечаток рабочей папки владельца берётся у самого верификатора: одна реализация."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("fm_rv_fp", VERIFIER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.production_fingerprint()


def _write(d, name, obj):
    io.open(os.path.join(d, name), "w", encoding="utf-8", newline="\n").write(
        json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=True) + "\n")


def _write_series_artifacts(d, res, rows, ms, mi, cb, ca, pb, pa, prb, pra, env_snap):
    _write(d, "metrics_static.json", ms)
    _write(d, "metrics_isolated.json", mi)
    _write(d, "failures.json", {"aborted_reason": res["aborted_reason"],
                                "failed_criteria": res["failed_criteria"],
                                "runs_with_violations":
                                [{"run_id": r["run_id"], "cycle": r["cycle"],
                                  "scenario_id": r["scenario_id"],
                                  "violations": r["violations"],
                                  "between_runs_violations":
                                  r.get("between_runs_violations", [])}
                                 for r in rows if r["violations"]
                                 or r.get("between_runs_violations")]})
    _write(d, "process_audit.json", {
        "runs": [{"run_id": r["run_id"], "server_pid": r["server_pid"],
                  "browser_pid": r["browser_pid"],
                  "server_alive_after": pid_alive(r["server_pid"]),
                  "browser_alive_after": pid_alive(r["browser_pid"]),
                  "remaining": r["remaining_processes"]} for r in rows],
        "isolated_instances_left_in_system": owned_e2e_processes(),
        "note": "чужие процессы не проверялись и не завершались; смотрели только свои PID"})
    _write(d, "port_audit.json", {
        "ports": [{"run_id": r["run_id"], "port": r["port"],
                   "released": port_is_free(r["port"]) if r["port"] else None}
                  for r in rows],
        "unique_ports": len(set(r["port"] for r in rows if r["port"])),
        "total": len(rows)})
    _write(d, "network_audit.json", {
        "runs": [{"run_id": r["run_id"], "mode": r["mode"],
                  "browser_requests": r["browser_requests"],
                  "browser_external": r["browser_external_requests"],
                  "backend_requests": r["backend_requests"],
                  "blocked": r["blocked_requests"]} for r in rows],
        "external_total": sum((r["browser_external_requests"] or 0) for r in rows),
        "blocked_total": sum((r["blocked_requests"] or 0) for r in rows)})
    _write(d, "data_isolation_audit.json", {
        "browser_profiles": [r["browser_profile_path"] for r in rows],
        "isolated_data_dirs": [r["test_data_path"] for r in rows
                               if r["mode"] == "isolated_farm_manager"],
        "unique_profiles": len(set(r["browser_profile_path"] for r in rows)),
        "unique_data_dirs": len(set(r["test_data_path"] for r in rows
                                    if r["mode"] == "isolated_farm_manager")),
        "production_before": pb, "production_after": pa,
        "product_files_before": prb, "product_files_after": pra,
        "note": "абсолютный путь рабочей папки владельца не сохраняется"})
    _write(d, "qualification_decision.json", {
        "series_id": res["series_id"], "candidate_commit": env_snap.get("git_commit"),
        "cycles_required": res["cycles_required"],
        "cycles_completed": res["cycles_completed"],
        "static_passes": res["static_passes"], "isolated_passes": res["isolated_passes"],
        "total_runs": res["total_runs"], "status": res["status"],
        "criteria": {"required_cycles": REQUIRED_CYCLES,
                     "max_isolated_seconds": MAX_ISOLATED_SECONDS,
                     "max_static_seconds": MAX_STATIC_SECONDS,
                     "median_deviation": DEVIATION},
        "failed_criteria": res["failed_criteria"],
        "restarted_series": res["restarted_series"],
        "previous_series_id": res["previous_series_id"],
        "started_at": res["started_at"], "finished_at": res["finished_at"],
        "duration_seconds": res["duration_seconds"],
        "limitations": res["limitations"]})
    _write(d, "series_summary.json", dict(res, run_artifacts=[r["artifacts_path"]
                                                              for r in rows]))
    io.open(os.path.join(d, "series_summary.txt"), "w", encoding="utf-8",
            newline="\n").write(render(res, ms, mi, rows) + "\n")


def render(res, ms=None, mi=None, rows=None):
    L = ["=" * 78, "КВАЛИФИКАЦИЯ СТАБИЛЬНОСТИ UI-ПРОВЕРКИ", "=" * 78,
         "серия:   %s" % res["series_id"],
         "СТАТУС:  %s (код %s)" % (res["status"], res["exit_code"])]
    if res["status"] == DRY_RUN:
        L.append("НИЧЕГО НЕ ЗАПУЩЕНО: это план. Для серии добавьте --execute.")
        L.append("запланировано прогонов: %d (%d циклов по два сценария)"
                 % (res["total_runs_planned"], res["cycles_requested"]))
        for s in (res.get("plan") or [])[:6]:
            L.append("   цикл %d, шаг %d: %s" % (s["cycle"], s["sequence_position"],
                                                 s["scenario_id"]))
        if len(res.get("plan") or []) > 6:
            L.append("   … ещё %d" % (len(res["plan"]) - 6))
        return "\n".join(L)
    L.append("циклов пройдено: %d из %d" % (res["cycles_completed"],
                                            res["cycles_requested"]))
    L.append("static PASS: %d   isolated PASS: %d   всего прогонов: %d"
             % (res["static_passes"], res["isolated_passes"], res["total_runs"]))
    if res["aborted_reason"]:
        L.append("")
        L.append("СЕРИЯ ОБОРВАНА: %s" % res["aborted_reason"])
    for name, m in (("static", ms), ("isolated", mi)):
        if not m or not m["count"]:
            continue
        L.append("")
        L.append("%s: min %.2f  median %.2f  mean %.2f  p90 %.2f  p95 %.2f  max %.2f"
                 % (name, m["min"], m["median"], m["mean"], m["p90"], m["p95"], m["max"]))
        L.append("        отклонение %.3f  коэф. вариации %.3f  max/median %.2f"
                 % (m["stdev"], m["coefficient_of_variation"], m["max_to_median"]))
    if res["failed_criteria"]:
        L.append("")
        L.append("НЕ ВЫПОЛНЕННЫЕ КРИТЕРИИ:")
        for f in res["failed_criteria"]:
            L.append("   ! %-34s %s" % (f["id"], f["detail"]))
    L.append("")
    if res["status"] == QUALIFIED:
        L.append("QUALIFIED относится ТОЛЬКО к двум проверенным сценариям. Это не проверка")
        L.append("печати, оборудования и остальных экранов, и не основание подключать")
        L.append("UI-шаг к исполнителю автоматически.")
    else:
        L.append("NOT_QUALIFIED. Индивидуальный повтор запрещён: серия начинается заново.")
    if res.get("artifacts_path"):
        L.append("артефакты: %s" % res["artifacts_path"])
    return "\n".join(L)


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(
        description="Квалификация стабильности UI-проверки (по умолчанию — только план).")
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--cycles", type=int, default=REQUIRED_CYCLES)
    ap.add_argument("--test-mode", action="store_true",
                    help="служебное: короткая серия, квалификацией не считается")
    ap.add_argument("--restarted", type=int, default=0)
    ap.add_argument("--previous-series")
    ns = ap.parse_args(argv)

    try:
        res, rows, out = run_series(cycles=ns.cycles, execute=ns.execute,
                                    test_mode=ns.test_mode, restarted=ns.restarted,
                                    previous_series_id=ns.previous_series)
    except ConfigError as e:
        payload = {"schema_version": SCHEMA, "status": CONFIG_ERROR, "error": str(e)}
        sys.stderr.write((json.dumps(payload, ensure_ascii=False) if ns.json
                          else "ОШИБКА КОНФИГУРАЦИИ: %s" % e) + "\n")
        return EXIT[CONFIG_ERROR]
    except Exception as e:
        sys.stderr.write("ВНУТРЕННИЙ СБОЙ КВАЛИФИКАТОРА: %s\n" % str(e)[:300])
        return EXIT_INTERNAL

    static = [r for r in rows if r["mode"] == "static_harness"]
    iso = [r for r in rows if r["mode"] == "isolated_farm_manager"]
    sys.stdout.write((json.dumps(res, ensure_ascii=False, indent=1, sort_keys=True)
                      if ns.json else render(res, metrics(static), metrics(iso), rows))
                     + "\n")
    return res["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
