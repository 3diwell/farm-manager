# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# Корреляция project_print_job с телеметрией — core Alpha 2.741 (этап 5A1).
# ЗАЧЕМ. До 2.741 ядро брало «самое СВЕЖЕЕ задание по printer_id» вообще без сверки имени файла:
# внешняя/экранная печать засчитывала чужое задание (printed_qty рос не у той детали), а два
# dispatched-задания на одном принтере оставляли старое висеть навсегда. Здесь доказываем, что
# сверка идёт по имени, а при неоднозначности НЕ засчитывается НИЧЕГО (fail-safe).
# Функции _match_project_job/_pjob_candidates/_pjob_name_match берутся ДОСЛОВНО из server.py
# (exec нужных блоков), поэтому тест падает, если реализация уедет.
# Запуск: PYTHONIOENCODING=utf-8 python tools/test_project_job_correlation.py   (0 = пройдено)
import os, re, sqlite3, tempfile, threading

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRV = open(os.path.join(REPO, 'server.py'), encoding='utf-8').read()

fail = 0


def check(name, cond):
    global fail
    print(('PASS' if cond else 'FAIL') + ' — ' + name)
    if not cond:
        fail += 1


def _ddl(t):
    return re.search(r'"(CREATE TABLE IF NOT EXISTS %s \(.*?\))"' % t, _SRV, re.S).group(1)


def _fn_src(name):
    """Исходник функции ядра ДОСЛОВНО: от 'def name(' до следующего определения верхнего уровня."""
    i = _SRV.index('\ndef %s(' % name) + 1
    m = re.search(r'\n(?=def |class |@app\.)', _SRV[i:])
    return _SRV[i:i + (m.start() if m else len(_SRV))]


# ── песочница ядра: только то, от чего зависят проверяемые функции ─────────────────────────────
db = os.path.join(tempfile.mkdtemp(), 'farm_parts.db')
conn_p = sqlite3.connect(db, check_same_thread=False)
conn_p.row_factory = sqlite3.Row
conn_p.execute(_ddl('project_print_jobs'))
conn_p.commit()

NS = {'conn_p': conn_p, 'lock_p': threading.Lock(), 'os': os, 're': re}
# Каноническая нормализация имени — ДОСЛОВНО из server.py (та же, что у склада/Quick/экранной печати).
exec(re.search(r'^NORM_RE = .*$', _SRV, re.M).group(0), NS)
exec(re.search(r'^norm = lambda .*$', _SRV, re.M).group(0), NS)
exec('_PRINT_EXTS = ' + re.search(r'_PRINT_EXTS = (\([^)]*\))', _SRV).group(1), NS)
exec(_fn_src('_name_stem'), NS)
exec(_fn_src('_pjob_candidates'), NS)
exec(_fn_src('_pjob_name_match'), NS)
exec(_fn_src('_match_project_job'), NS)
match = NS['_match_project_job']
norm = NS['norm']

_seq = [0]


def mk_job(jid, pid, filename, ts):
    """Задание с ЯВНЫМ started_at: порядок «старейшее первым» обязан быть детерминированным."""
    conn_p.execute("INSERT INTO project_print_jobs (id, project_id, file_id, printer_id, filename, "
                   "file_norm, snapshot_json, status, started_at, counted_at) "
                   "VALUES (?,?,?,?,?,?,?,'dispatched',?,'')",
                   (jid, 'prj', 'F1', pid, filename, norm(filename), '[]', ts))
    conn_p.commit()


def reset():
    conn_p.execute("DELETE FROM project_print_jobs")
    conn_p.commit()


# ── 1. Один job, имя совпало ───────────────────────────────────────────────────────────────────
reset(); mk_job('j1', 'pr1', 'plate.3mf', '2024-01-01 10:00:00')
check('C1. один job + совпавшее имя -> он, decision=matched_unique',
      match('pr1', norm('plate.3mf'), 'plate.3mf') == ('j1', 'matched_unique'))

# ── 2. Два jobs, совпало одно ──────────────────────────────────────────────────────────────────
reset()
mk_job('j1', 'pr1', 'plate.3mf', '2024-01-01 10:00:00')
mk_job('j2', 'pr1', 'other.3mf', '2024-01-01 11:00:00')
check('C2. два jobs, совпало одно -> именно оно (а НЕ самое свежее)',
      match('pr1', norm('plate.3mf'), 'plate.3mf') == ('j1', 'matched_unique'))
check('C3. и наоборот: свежее совпавшее выбирается тоже по имени',
      match('pr1', norm('other.3mf'), 'other.3mf') == ('j2', 'matched_unique'))

# ── 3. Два одинаковых имени -> СТАРЕЙШЕЕ ───────────────────────────────────────────────────────
reset()
mk_job('jB', 'pr1', 'plate.3mf', '2024-01-01 12:00:00')      # вставлен ПЕРВЫМ, но он новее
mk_job('jA', 'pr1', 'plate.3mf', '2024-01-01 09:00:00')      # старейший
check('C4. два jobs с одним именем -> детерминированно СТАРЕЙШИЙ, decision=matched_oldest',
      match('pr1', norm('plate.3mf'), 'plate.3mf') == ('jA', 'matched_oldest'))
check('C5. выбор устойчив (повтор даёт тот же ответ)',
      match('pr1', norm('plate.3mf'), 'plate.3mf') == match('pr1', norm('plate.3mf'), 'plate.3mf'))

# ── 4. Внешняя печать другого файла -> НИ ОДИН ─────────────────────────────────────────────────
reset(); mk_job('j1', 'pr1', 'plate.3mf', '2024-01-01 10:00:00')
check('C6. external/manual печать ДРУГОГО файла -> ничего не выбрано (no_match)',
      match('pr1', norm('чужое.gcode'), 'чужое.gcode') == (None, 'no_match'))
check('C7. ГЛАВНОЕ: чужая печать НЕ завершает наше задание (регресс «самое свежее» закрыт)',
      match('pr1', norm('чужое.gcode'), 'чужое.gcode')[0] is None)

# ── 5. Имя отсутствует ─────────────────────────────────────────────────────────────────────────
reset(); mk_job('j1', 'pr1', 'plate.3mf', '2024-01-01 10:00:00')
check('C8. имени нет + ровно один активный -> legacy fallback допустим',
      match('pr1', '', '') == ('j1', 'legacy_single'))
mk_job('j2', 'pr1', 'other.3mf', '2024-01-01 11:00:00')
check('C9. имени нет + несколько -> ambiguity, «последний» НЕ выбирается',
      match('pr1', '', '') == (None, 'ambiguous_multi'))

# ── 6. Unicode и составные расширения ──────────────────────────────────────────────────────────
reset(); mk_job('ju', 'pr1', 'Деталь Ф-1.gcode.3mf', '2024-01-01 10:00:00')
check('C10. Unicode-имя совпадает по norm', match('pr1', norm('Деталь Ф-1.gcode.3mf'), 'Деталь Ф-1.gcode.3mf')[0] == 'ju')
check('C11. .gcode.3mf: принтер сообщил имя БЕЗ расширения (subtask_name) -> совпадение по stem',
      match('pr1', norm('Деталь Ф-1'), 'Деталь Ф-1')[0] == 'ju')
check('C12. другое расширение того же имени -> совпадение по stem',
      match('pr1', norm('Деталь Ф-1.gcode'), 'Деталь Ф-1.gcode')[0] == 'ju')
check('C13. похожее, но ДРУГОЕ имя -> не совпадает',
      match('pr1', norm('Деталь Ф-2'), 'Деталь Ф-2') == (None, 'no_match'))

# ── 7. Изоляция по принтеру ────────────────────────────────────────────────────────────────────
reset()
mk_job('j1', 'pr1', 'plate.3mf', '2024-01-01 10:00:00')
mk_job('j2', 'pr2', 'plate.3mf', '2024-01-01 10:00:00')
check('C14. одинаковое имя на РАЗНЫХ принтерах не путается',
      match('pr1', norm('plate.3mf'), 'plate.3mf')[0] == 'j1'
      and match('pr2', norm('plate.3mf'), 'plate.3mf')[0] == 'j2')

# ── 8. Засчитанные/терминальные кандидатами не являются ────────────────────────────────────────
reset(); mk_job('j1', 'pr1', 'plate.3mf', '2024-01-01 10:00:00')
conn_p.execute("UPDATE project_print_jobs SET counted_at='2024-01-01 12:00:00' WHERE id='j1'"); conn_p.commit()
check('C15. уже засчитанное задание в кандидаты не попадает (повторный FINISH не удвоит)',
      match('pr1', norm('plate.3mf'), 'plate.3mf') == (None, 'none'))
reset(); mk_job('j1', 'pr1', 'plate.3mf', '2024-01-01 10:00:00')
conn_p.execute("UPDATE project_print_jobs SET status='failed' WHERE id='j1'"); conn_p.commit()
check('C16. failed-задание в кандидаты не попадает', match('pr1', norm('plate.3mf'), 'plate.3mf') == (None, 'none'))
check('C17. заданий нет вовсе -> (None, none)', (reset(), match('pr1', norm('x.3mf'), 'x.3mf'))[1] == (None, 'none'))

# ── 9. Повторные кадры Bambu (JOB start приходит многократно) ──────────────────────────────────
reset(); mk_job('j1', 'pr1', 'plate.3mf', '2024-01-01 10:00:00')
_r = [match('pr1', norm('plate.3mf'), 'plate.3mf') for _ in range(5)]
check('C18. повторные JOB start -> тот же job, дублей не создаётся', _r == [('j1', 'matched_unique')] * 5)
check('C19. сопоставление НИЧЕГО не пишет в БД (чистое чтение)',
      conn_p.execute("SELECT COUNT(*) n FROM project_print_jobs").fetchone()["n"] == 1)

# ── 10. FINISH exactly-once поверх сопоставления ───────────────────────────────────────────────
# finish_project_print_job гардирован counted_at='' + rowcount: моделируем ровно этот гард.
reset(); mk_job('j1', 'pr1', 'plate.3mf', '2024-01-01 10:00:00')


def finish_once(jid):
    cur = conn_p.execute("UPDATE project_print_jobs SET status='finished', counted_at='X' "
                         "WHERE id=? AND counted_at=''", (jid,))
    conn_p.commit()
    return cur.rowcount == 1


_j, _d = match('pr1', norm('plate.3mf'), 'plate.3mf')
check('C20. FINISH засчитывается РОВНО один раз (повтор -> False)',
      finish_once(_j) is True and finish_once(_j) is False)
check('C21. после учёта то же задание кандидатом больше не является',
      match('pr1', norm('plate.3mf'), 'plate.3mf') == (None, 'none'))

# ── 11. Статика: опасный выбор «самое свежее» удалён из учётного пути ──────────────────────────
_hs = _fn_src('handle_state')
check('C22. handle_state сверяет имя: вызывает _match_project_job(pid, fn, raw_fn)',
      '_match_project_job(pid, fn, raw_fn)' in _hs)
check('C23. handle_state больше НЕ берёт задание вслепую по printer_id',
      '_active_project_job_for_printer(pid)' not in _hs)
check('C24. в кандидатах нет ORDER BY started_at DESC (это и был баг «последний выигрывает»)',
      'DESC' not in _fn_src('_pjob_candidates'))
check('C25. legacy-обёртка обезврежена: делегирует канонической сверке',
      '_match_project_job(printer_id)' in _fn_src('_active_project_job_for_printer'))
check('C26. correlation id в протокол НЕ вводился (5A1: только имя файла)',
      'correlation_id' not in _SRV)

print('\n' + ('FAIL: %d проверок провалено' % fail if fail else
              'PASS: задание сопоставляется по ИМЕНИ файла (norm + stem), при нескольких совпадениях '
              'берётся детерминированно старейшее, при отсутствии совпадений и при неоднозначности не '
              'засчитывается ничего; чужая печать не завершает проектное задание, повторные кадры '
              'идемпотентны, FINISH учитывается ровно один раз'))
raise SystemExit(1 if fail else 0)
