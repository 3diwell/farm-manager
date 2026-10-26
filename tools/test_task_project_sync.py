# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.947 — синхронизация задачи с проектом и счёт печатей сверх плана.

ЧЕГО ПРОСИЛ ВЛАДЕЛЕЦ. Одна и та же модель лежит и в «Задачах», и в проекте. Нужен значок
синхронизации у задачи с двумя состояниями:
  выключен — печати считаются ТОЛЬКО в задаче;
  включён  — каждая печать считается и в задаче, и в проекте.
Правило обязано работать в полной мере при ПОВТОРНОЙ ПЕЧАТИ С ЭКРАНА ПРИНТЕРА. Итог в ячейке
должен расти при каждой удачной печати, в том числе когда план уже достигнут.

ЧТО БЫЛО. Связь задачи с проектом выводилась по совпадению имени файла и решала за владельца:
наблюдение привязывало печать к проекту, счёт шёл в проект, а итог задачи стоял на месте —
владелец видел «печатаю второй раз, а в задаче ноль движения».

ЧТО ЗДЕСЬ ДОКАЗЫВАЕТСЯ — исполнением настоящего кода ядра, а не чтением:
  A. хранение флага: по умолчанию выключен, включается и выключается, чужое имя отвергается,
     задача без проекта синхронизацию не получает (включать не с чем);
  B. гейт привязки к проекту: печать НЕ из проекта уходит в проект только при включённой
     синхронизации; файл, которого нет в задачах, ведёт себя как раньше; явная отправка из
     проекта (dispatch) не трогается вовсе;
  C. счёт задачи: +1 за каждую удачную печать, в том числе СВЕРХ ПЛАНА;
  D. ветки конца печати и старта в server.py устроены так, как описано (мост «текст ↔ поведение»);
  E. НЕ ВАКУУМ: возврат прежнего поведения красит проверки.

ПОЛНОСТЬЮ OFFLINE: временная папка, временная SQLite со схемой, извлечённой из server.py,
функции ядра исполняются ДОСЛОВНО. Ни сети, ни принтеров, ни рабочей базы, ни DATA_DIR.

Запуск:  python tools/test_task_project_sync.py      (0 = всё в порядке)
"""
import atexit
import contextlib
import io
import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import threading
import uuid

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
SENTINEL = "TASK_PROJECT_SYNC_SENTINEL_2_947"
_SRV = io.open(os.path.join(REPO, "server.py"), encoding="utf-8").read()
_HTML = io.open(os.path.join(REPO, "web", "index.html"), encoding="utf-8").read()
_APPJS = io.open(os.path.join(REPO, "web", "app.js"), encoding="utf-8").read()

_pass = [0]
_fail = []
_verdict = [False]


def check(name, cond, detail=""):
    if cond:
        _pass[0] += 1
        print("PASS — %s" % name)
    else:
        _fail.append(name)
        print("FAIL — %s%s" % (name, (" :: " + str(detail)[:300]) if detail else ""))


@atexit.register
def _guard_exit():
    if not _verdict[0]:
        print("FAIL — тест завершился без финального вердикта")
        os._exit(1)


TMP = tempfile.mkdtemp(prefix="fm_tasksync_")
atexit.register(lambda: shutil.rmtree(TMP, ignore_errors=True))


def _ddl(t):
    return re.search(r'"(CREATE TABLE IF NOT EXISTS %s \(.*?\))"' % t, _SRV, re.S).group(1)


def _fn_src(name):
    """Исходник функции ядра ДОСЛОВНО: от 'def name(' до следующего определения верхнего уровня."""
    i = _SRV.index("\ndef %s(" % name) + 1
    m = re.search(r"\n(?=def |class |@app\.|if not _IS_POOL_WORKER)", _SRV[i:])
    return _SRV[i:i + (m.start() if m else len(_SRV))]


# ── Песочница ядра ──────────────────────────────────────────────────────────────────────────
from app import printer_job_lifecycle as PJL          # noqa: E402

DB = os.path.join(TMP, "farm_parts.db")
conn_p = sqlite3.connect(DB, check_same_thread=False)
conn_p.row_factory = sqlite3.Row
for _t in ("app_settings", "staging_files", "projects", "project_files", "project_parts",
           "project_file_parts", "project_print_jobs", "printer_job_sessions"):
    conn_p.execute(_ddl(_t))
conn_p.commit()


class _Log(object):
    lines = []

    @classmethod
    def _rec(cls, msg, *a):
        try:
            cls.lines.append(str(msg) % a if a else str(msg))
        except Exception:
            cls.lines.append(str(msg))

    info = classmethod(lambda cls, m, *a, **k: cls._rec(m, *a))
    debug = classmethod(lambda cls, m, *a, **k: cls._rec(m, *a))
    warning = classmethod(lambda cls, m, *a, **k: cls._rec(m, *a))
    error = classmethod(lambda cls, m, *a, **k: cls._rec(m, *a))


staging_print = {}
NS = {
    "conn_p": conn_p, "lock_p": threading.RLock(), "os": os, "re": re, "json": json, "uuid": uuid,
    "log": _Log, "_pjl": PJL, "contextmanager": contextlib.contextmanager,
    "_exc_brief": lambda: "test-exc", "staging_print": staging_print, "threading": threading,
    "_IS_POOL_WORKER": True, "__builtins__": __builtins__,
    #  2.978: _print_name_eq сверяется с манифестом плиты на печати. В песочнице
    #  печатей нет — пустой словарь и есть честное «манифеста не знаем».
    "live_parts": {}, "last_job": {}, "print_start_ts": {}, "server_print": {}, "_server_print_ts": {}, "print_source": {}, "plan_part": {},
}
exec(re.search(r"^NORM_RE = .*$", _SRV, re.M).group(0), NS)
exec(re.search(r"^norm = lambda .*$", _SRV, re.M).group(0), NS)
#  2.978: сопоставление имени печати с именем файла вынесено в _print_name_eq —
#  без неё кусок «задача по печати» не исполняется.
for _f in ("_name_stem", "_print_name_eq", "_get_setting", "_set_setting", "_staging_sync_map", "_staging_sync_on",
           "_staging_sync_set", "_staging_task_for_print", "_staging_printers_for",
           "_staging_count_finish", "_staging_project_link", "staging_project_sync",
           "_rollback_sqlite_on_error", "_uid", "_get_project",
           "_recompute_project_part_status", "create_project_print_job",
           "_pjl_match_candidates", "_pjl_remote_sends", "_pjl_project_filename",
           "_pjl_resolve_match", "_pjl_link_project"):
    exec(_fn_src(_f), NS)
NS["_rollback_sqlite_on_error"] = contextlib.contextmanager(NS["_rollback_sqlite_on_error"])

sync_on = NS["_staging_sync_on"]
sync_set = NS["_staging_sync_set"]
task_for = NS["_staging_task_for_print"]
count_finish = NS["_staging_count_finish"]
route_sync = NS["staging_project_sync"]
link_project = NS["_pjl_link_project"]
norm = NS["norm"]

FILE_BOTH = "Cube_v3.gcode"          # лежит и в задачах, и в проекте
FILE_TASK_ONLY = "Bracket.gcode"     # только в задачах
FILE_PROJ_ONLY = "Gear.gcode"        # только в проекте


def _seed():
    conn_p.execute("DELETE FROM staging_files")
    conn_p.execute("DELETE FROM projects")
    conn_p.execute("DELETE FROM project_files")
    conn_p.execute("DELETE FROM project_parts")
    conn_p.execute("DELETE FROM project_file_parts")
    conn_p.execute("DELETE FROM project_print_jobs")
    conn_p.execute("DELETE FROM app_settings")
    for fn, req, prn in ((FILE_BOTH, 2, 0), (FILE_TASK_ONLY, 1, 0)):
        conn_p.execute("INSERT INTO staging_files (filename, status, printer_id, required_qty, printed_qty) "
                       "VALUES (?,'ready','',?,?)", (fn, req, prn))
    conn_p.execute("INSERT INTO projects (id, name, is_deleted) VALUES ('PRJ','Заказ 17',0)")
    for fid, fn in (("F1", FILE_BOTH), ("F2", FILE_PROJ_ONLY)):
        conn_p.execute("INSERT INTO project_files (id, project_id, filename) VALUES (?,?,?)", (fid, "PRJ", fn))
    conn_p.execute("INSERT INTO project_parts (id, project_id, part_name, norm_name, required_qty, printed_qty) "
                   "VALUES ('PP1','PRJ','Куб','куб',3,0)")
    conn_p.execute("INSERT INTO project_parts (id, project_id, part_name, norm_name, required_qty, printed_qty) "
                   "VALUES ('PP2','PRJ','Шестерня','шестерня',3,0)")
    conn_p.execute("INSERT INTO project_file_parts (id, project_id, file_id, part_id, on_plate_qty) "
                   "VALUES ('L1','PRJ','F1','PP1',1)")
    conn_p.execute("INSERT INTO project_file_parts (id, project_id, file_id, part_id, on_plate_qty) "
                   "VALUES ('L2','PRJ','F2','PP2',1)")
    conn_p.commit()
    staging_print.clear()


def _task(fn):
    r = conn_p.execute("SELECT required_qty, printed_qty, status FROM staging_files WHERE filename=?", (fn,)).fetchone()
    return dict(r) if r else None


def _jobs():
    return [dict(r) for r in conn_p.execute("SELECT id, project_id, file_id, status FROM project_print_jobs").fetchall()]


class _Obs(object):
    """Наблюдение ровно с теми полями, которые читает связывание с проектом."""

    def __init__(self, filename, printer_id="PRN1"):
        self.filename_raw = filename
        self.filename_normalized = PJL.normalize_filename(filename)
        self.printer_id = printer_id


print("=" * 78)
print("--- A. Хранение флага: по умолчанию выключен, включается по слову владельца ---")
_seed()
check("A1. по умолчанию синхронизация выключена", sync_on(FILE_BOTH) is False)
check("A2. задача с проектом синхронизацию принимает",
      route_sync({"filename": FILE_BOTH, "enabled": True}) == {"status": "ok", "filename": FILE_BOTH, "project_sync": True}
      and sync_on(FILE_BOTH) is True)
check("A3. выключение возвращает прежнее состояние",
      route_sync({"filename": FILE_BOTH, "enabled": False})["project_sync"] is False
      and sync_on(FILE_BOTH) is False)
check("A4. задача БЕЗ проекта синхронизацию не получает — включать не с чем",
      route_sync({"filename": FILE_TASK_ONLY, "enabled": True}) == {"status": "error", "reason": "no_project"}
      and sync_on(FILE_TASK_ONLY) is False)
check("A5. неизвестное имя задачи отвергается",
      route_sync({"filename": "нет-такого.gcode", "enabled": True})["reason"] == "unknown_task")
check("A6. пустое имя отвергается", route_sync({"filename": "", "enabled": True})["reason"] == "no_filename")
check("A7. флаг переживает перечитывание настройки (хранится, а не живёт в памяти)",
      sync_set(FILE_BOTH, True) and NS["_get_setting"]("staging_project_sync", "") != ""
      and json.loads(NS["_get_setting"]("staging_project_sync", "[]")) == [FILE_BOTH])
sync_set(FILE_BOTH, False)
#  Пустых проверок здесь быть не должно: связь с одним проектом сперва подтверждаем, а уже
#  потом ломаем её вторым проектом с тем же именем файла.
check("A8. пока имя лежит в одном проекте, связь есть и синхронизацию включить можно",
      NS["_staging_project_link"](FILE_BOTH) == ("PRJ", "Заказ 17"),
      NS["_staging_project_link"](FILE_BOTH))
conn_p.execute("INSERT INTO projects (id, name, is_deleted) VALUES ('PRJ2','Заказ 18',0)")
conn_p.execute("INSERT INTO project_files (id, project_id, filename) VALUES ('F3','PRJ2',?)", (FILE_BOTH,))
conn_p.commit()
check("A9. то же имя в двух проектах: связи нет, синхронизация не включается",
      NS["_staging_project_link"](FILE_BOTH) is None
      and route_sync({"filename": FILE_BOTH, "enabled": True})["reason"] == "no_project")
_seed()

print("--- B. Куда уходит печать, запущенная НЕ из проекта ---")
_seed()
_m, _job = link_project(_Obs(FILE_BOTH))
check("B1. КЛЮЧЕВОЕ: синхронизация выключена — печать в проект НЕ засчитывается",
      _job == "" and not _m.matched and _m.reason == "quick_task_not_synced" and _jobs() == [],
      (_job, _m.reason, _jobs()))
sync_set(FILE_BOTH, True)
_m2, _job2 = link_project(_Obs(FILE_BOTH))
check("B2. КЛЮЧЕВОЕ: синхронизация включена — та же печать засчитывается и проекту",
      bool(_job2) and _m2.matched and len(_jobs()) == 1 and _jobs()[0]["file_id"] == "F1",
      (_job2, _jobs()))
sync_set(FILE_BOTH, False)
conn_p.execute("DELETE FROM project_print_jobs")
conn_p.commit()
_m3, _job3 = link_project(_Obs(FILE_PROJ_ONLY))
check("B3. файла нет в задачах — поведение прежнее, печать уходит в проект",
      bool(_job3) and _m3.matched and _jobs()[0]["file_id"] == "F2", (_job3, _jobs()))
conn_p.execute("DELETE FROM project_print_jobs")
conn_p.commit()
_dispatch = NS["create_project_print_job"]("PRJ", "F1", "PRN1", FILE_BOTH)
_m4, _job4 = link_project(_Obs(FILE_BOTH), dispatch_job_id=_dispatch)
check("B4. отправку ИЗ проекта гейт не трогает: намерение уже выражено нажатием",
      _job4 == _dispatch and _m4.state == PJL.MATCH_DISPATCH, (_job4, _dispatch))

print("--- C. Итог задачи растёт при каждой печати, в том числе сверх плана ---")
_seed()
for _i in range(5):
    count_finish(FILE_BOTH)
_t = _task(FILE_BOTH)
check("C1. КЛЮЧЕВОЕ: при плане 2 пять печатей дают итог 5, а не 2", _t["printed_qty"] == 5, _t)
check("C2. задача помечена готовой, но продолжает считать", _t["status"] == "done", _t)
_seed()
count_finish(FILE_TASK_ONLY)
check("C3. первая печать закрывает план из одной штуки", _task(FILE_TASK_ONLY) == {"required_qty": 1, "printed_qty": 1, "status": "done"})
count_finish(FILE_TASK_ONLY)
check("C4. шестая, десятая, любая следующая печать тоже попадает в итог",
      _task(FILE_TASK_ONLY)["printed_qty"] == 2, _task(FILE_TASK_ONLY))
_seed()
staging_print["PRN2"] = FILE_BOTH          # тот же файл ещё печатает другой принтер
count_finish(FILE_BOTH)
check("C5. пока файл печатает другой принтер, задача остаётся «в печати»",
      _task(FILE_BOTH)["status"] == "printing" and _task(FILE_BOTH)["printed_qty"] == 1,
      _task(FILE_BOTH))
staging_print.clear()
check("C6. неизвестное имя не роняет счёт и ничего не создаёт",
      (count_finish("нет-такого.gcode") is None)
      and conn_p.execute("SELECT COUNT(*) c FROM staging_files").fetchone()["c"] == 2)

print("--- D. Ветки печати в server.py устроены так, как описано ---")
check("D1. конец печати: проектная ветка засчитывает и задаче, до выхода",
      "_staging_count_finish(_sfile_prev)" in _SRV
      and _SRV.index("_orch.on_printer_finished(pid, fn, _proj_job)")
      < _SRV.index("if _sfile_prev:\n                _staging_count_finish(_sfile_prev)")
      < _SRV.index("if _sfile_prev:\n                _staging_count_finish(_sfile_prev)") + 200)
check("D2. старт: условие «только если не проектная печать» снято",
      'if fn and src != "plan" and not _proj_job:' not in _SRV
      and 'if fn and src != "plan":' in _SRV)
check("D3. старт: отправку из проекта задача считает только при синхронизации",
      "if _dispatch_proj_job and not _staging_sync_on(_st_name):" in _SRV)
check("D4. признак «отправлено из проекта» снят ДО наблюдения, а не после",
      _SRV.index("_dispatch_proj_job = _proj_job or \"\"") < _SRV.index("_obs_job = observe_printer_job("))
check("D5. гейт стоит перед разбором кандидатов, а не после",
      _SRV.index('reason="quick_task_not_synced"') < _SRV.index("match = _pjl_resolve_match(obs)"))
check("D6. состояние переключателя уходит на экран в списке задач",
      'r["project_sync"] = bool(r["project_id"])' in _SRV)

print("--- D2. Интерфейс: значок есть, отдан шаблону и переведён ---")
check("D7. значок показывается только у задачи, связанной с проектом",
      'v-if="f.project_id" type="button" class="qtsync"' in _HTML)
check("D8. состояние значка видно классом, а не только цветом",
      ':class="{on: f.project_sync}"' in _HTML and ".qtsync.on{" in io.open(os.path.join(REPO, "web", "app.css"), encoding="utf-8").read())
check("D9. обе функции отданы шаблону из setup",
      "stagingSyncTip, toggleStagingSync," in _APPJS)
check("D10. подписи переведены на русский",
      '"Synced with project": "Синхронизировано с проектом"' in _APPJS
      and '"This model is in project": "Эта модель есть в проекте"' in _APPJS)
check("D11. без права 'project' переключатель недоступен",
      ':disabled="!can(\'project\')"' in _HTML and "!can('project')) return;" in _APPJS)

print("--- E. НЕ ВАКУУМ: прежнее поведение красит проверки ---")
_seed()
_orig_gate = NS["_staging_task_for_print"]
NS["_staging_task_for_print"] = lambda fn_norm, raw_fn="": ("", False)   # как было до 2.947
#  2.978: у настоящей функции появился второй довод raw_fn (сверка имени печати
#  с именем файла) — заглушка обязана принимать его же, иначе сцена не собирается.
try:
    _mb, _jb = link_project(_Obs(FILE_BOTH))
    check("E1. без гейта несинхронизированная задача снова уводит печать в проект",
          bool(_jb) and _mb.matched, (_jb, _mb.state))
finally:
    NS["_staging_task_for_print"] = _orig_gate
conn_p.execute("DELETE FROM project_print_jobs")
conn_p.commit()
check("E2. гейт возвращён — печать снова остаётся в задаче",
      link_project(_Obs(FILE_BOTH))[1] == "" and _jobs() == [])

_orig_count = NS["_staging_count_finish"]


def _capped(fname):
    """Прежняя ошибка: итог упирается в план."""
    with NS["lock_p"]:
        row = conn_p.execute("SELECT required_qty, printed_qty FROM staging_files WHERE filename=?", (fname,)).fetchone()
        if row and (row["printed_qty"] or 0) < (row["required_qty"] or 1):
            conn_p.execute("UPDATE staging_files SET printed_qty=? WHERE filename=?",
                           ((row["printed_qty"] or 0) + 1, fname))
        conn_p.commit()


_seed()
for _i in range(5):
    _capped(FILE_BOTH)
check("E3. на прежнем поведении итог упёрся бы в план (2 вместо 5)",
      _task(FILE_BOTH)["printed_qty"] == 2, _task(FILE_BOTH))
_seed()
for _i in range(5):
    NS["_staging_count_finish"](FILE_BOTH)
check("E4. с исправлением итог снова считает все пять",
      _task(FILE_BOTH)["printed_qty"] == 5, _task(FILE_BOTH))

check("E5. в журнале теста нет ни адресов, ни кодов доступа",
      not re.search(r"\d+\.\d+\.\d+\.\d+|token|password", " ".join(_Log.lines), re.I))

print("--- F. Значок в НАСТОЯЩЕМ браузере: виден, переключается, ничего не ломает ---")
sys.path.insert(0, os.path.join(REPO, "tools"))
import _fm_ui_stage as stage                            # noqa: E402

_ST_ROWS = [
    {"filename": FILE_BOTH, "status": "ready", "printer_id": "", "required_qty": 2,
     "printed_qty": 5, "target_nozzles": 0.4, "target_model": "", "is_printable": True,
     "notes": "", "src_path": "", "linked": False, "missing": False,
     "project_id": "PRJ", "project_name": "Заказ 17", "project_sync": False},
    {"filename": FILE_TASK_ONLY, "status": "ready", "printer_id": "", "required_qty": 1,
     "printed_qty": 0, "target_nozzles": 0.4, "target_model": "", "is_printable": True,
     "notes": "", "src_path": "", "linked": False, "missing": False,
     "project_id": "", "project_name": "", "project_sync": False},
]
_JS = r"""
return new Promise(function(res){
  setTimeout(function(){
    var out = {};
    var all = [].slice.call(document.querySelectorAll('button.qtsync'));
    out.count = all.length;
    var b = all[0];
    out.before = b ? { on: /(^|\s)on(\s|$)/.test(b.className), tip: (b.getAttribute('title') || '') } : null;
    //  Значок обязан жить внутри своей колонки и не расталкивать имя файла.
    if (b) {
      var r = b.getBoundingClientRect(), col = b.closest('.pvnamecol');
      var cr = col ? col.getBoundingClientRect() : null;
      out.inCol = cr ? (r.left >= cr.left - 0.6 && r.right <= cr.right + 0.6) : false;
      out.size = { w: Math.round(r.width), h: Math.round(r.height) };
      out.colClip = col ? (col.scrollWidth - col.clientWidth) : -1;
      b.click();
    }
    setTimeout(function(){
      var b2 = document.querySelector('button.qtsync');
      out.after = b2 ? { on: /(^|\s)on(\s|$)/.test(b2.className), tip: (b2.getAttribute('title') || '') } : null;
      var tbl = document.querySelector('.pvtbl.qtpv');
      out.hscroll = tbl ? (tbl.scrollWidth - tbl.clientWidth) : -1;
      out.docScroll = document.documentElement.scrollWidth - document.documentElement.clientWidth;
      out.prnt = (function(){
        var i = document.querySelector('.pvrow.qtpvrow.pvpart [data-help="qt-prnt"]');
        return i ? i.value : null;
      })();
      res(dump(out));
    }, 500);
  }, 900);
});
"""
if not stage.engine_ready():
    check("F1. браузерный движок доступен", False, str(stage.last_diag())[:200])
else:
    stage.set_api({"/api/staging": _ST_ROWS,
                   "/api/staging/sync": {"status": "ok", "filename": FILE_BOTH, "project_sync": True}})
    SHOT = os.path.join(TMP, "tasks_sync.png")
    _bad = []
    _first = None
    for _wnd in ((1600, 1000), (1440, 900), (1280, 800), (1024, 640)):
        #  Язык интерфейса берётся из браузера и в сцене по умолчанию английский (задать его
        #  для страницы "/" сцена не умеет — параметр ?ls= работает только у второй страницы).
        #  Поэтому подписи ниже сверяются на обоих языках, а русские строки закреплены D10.
        R = stage.run(_JS, window_size=_wnd, settle_ms=2500,
                      shot_path=(SHOT if _wnd == (1440, 900) else None))
        _d = (R or {}).get("__diag") or {}
        _errs = (_d.get("consoleErrors") or []) + (_d.get("pageErrors") or [])
        ok = (bool(R) and R.get("count") == 1 and R.get("inCol") and R.get("colClip") == 0
              and R.get("hscroll", 1) <= 0 and R.get("docScroll", 1) <= 0 and not _errs)
        if not ok:
            _bad.append("%dx%d: %s" % (_wnd[0], _wnd[1], json.dumps(R, ensure_ascii=False)[:200]))
        if _first is None:
            _first = R
    check("F1. на всех четырёх размерах окна: значок один, внутри колонки, без прокрутки и ошибок",
          not _bad, "; ".join(_bad)[:400])
    check("F2. значок есть только у задачи, связанной с проектом (вторая без него)",
          (_first or {}).get("count") == 1, (_first or {}).get("count"))
    #  Язык интерфейса в сцене — браузерный (по умолчанию английский), поэтому подпись
    #  сверяется на обоих языках: русские строки отдельно закреплены проверкой D10.
    _tip_off = ((_first or {}).get("before") or {}).get("tip", "")
    _tip_on = ((_first or {}).get("after") or {}).get("tip", "")
    check("F3. в выключенном состоянии подпись объясняет, что печати идут только в задачу",
          ("только в задаче" in _tip_off or "only in the task" in _tip_off)
          and ("Заказ 17" in _tip_off)
          and not ((_first or {}).get("before") or {}).get("on", True), _tip_off[:140])
    check("F4. нажатие включает синхронизацию — состояние видно классом",
          ((_first or {}).get("after") or {}).get("on") is True,
          (_first or {}).get("after"))
    check("F5. включённая подпись говорит про обе стороны учёта",
          ("и в задаче, и в проекте" in _tip_on
           or "in the task and in the project" in _tip_on) and _tip_on != _tip_off, _tip_on[:140])
    check("F6. итог показан как есть, даже когда он больше плана (5 при плане 2)",
          str((_first or {}).get("prnt")) == "5", (_first or {}).get("prnt"))
    stage.set_api(None)

print("")
print("=" * 78)
print("МЕТКА: %s" % SENTINEL)
print("ИТОГО: PASS=%d FAIL=%d" % (_pass[0], len(_fail)))
for n in _fail:
    print("  провалено: %s" % n)
_verdict[0] = True
sys.exit(1 if _fail else 0)
