# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# Планировщик покрытия проекта «Печатать весь проект» — core Alpha 2.740 (этапы 1-4, dry-run).
# Проверяет РЕАЛЬНЫЙ app/project_orchestrator.py на временной БД со СХЕМОЙ ЯДРА (project_parts /
# project_files / project_file_parts берутся дословно из server.py init_db — иначе тест проверял бы
# выдуманную модель). Печать не участвует: планировщик — чистая функция над снимком.
# Запуск: python tools/test_project_whole_planner.py   (0 = пройдено)
import importlib.util, os, sys, sqlite3, tempfile, threading, uuid, re

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location('po', os.path.join(REPO, 'app', 'project_orchestrator.py'))
po = importlib.util.module_from_spec(spec)
spec.loader.exec_module(po)

# ── схема проектных таблиц берётся ИЗ server.py (дословно), чтобы модель не разошлась с ядром ──
_SRV = open(os.path.join(REPO, 'server.py'), encoding='utf-8').read()
def _ddl(table):
    m = re.search(r'"(CREATE TABLE IF NOT EXISTS %s \(.*?\))"' % table, _SRV, re.S)
    assert m, 'не найден DDL ядра для ' + table
    return m.group(1)

fail = 0
def check(name, cond):
    global fail
    print(('PASS' if cond else 'FAIL') + ' — ' + name)
    if not cond:
        fail += 1


def fresh_db():
    db = os.path.join(tempfile.mkdtemp(), 'farm_parts.db')
    c = sqlite3.connect(db, check_same_thread=False)
    c.row_factory = sqlite3.Row
    for t in ('projects', 'project_parts', 'project_files', 'project_file_parts', 'project_print_jobs'):
        c.execute(_ddl(t))
    c.commit()
    po.init(c, threading.Lock(), lambda p: p + uuid.uuid4().hex[:10], 'boot_test')
    po.init_db()
    return c


def mk(c, parts, files, links):
    """parts: {name: (required, printed, rework_qty, rework_done)}; files: {fid: printable};
    links: {(fid, part_name): on_plate_qty}. -> project_id, {name: part_id}"""
    c.execute("INSERT INTO projects (id, name) VALUES ('prj','P')")
    ids = {}
    for i, (n, v) in enumerate(parts.items()):
        pid = 'part_' + n
        ids[n] = pid
        c.execute("INSERT INTO project_parts (id, project_id, part_name, norm_name, required_qty, printed_qty, "
                  "rework_qty, rework_done, order_idx) VALUES (?,?,?,?,?,?,?,?,?)",
                  (pid, 'prj', n, n.lower(), v[0], v[1], v[2], v[3], i))
    for i, (f, printable) in enumerate(files.items()):
        c.execute("INSERT INTO project_files (id, project_id, filename, content_hash, is_printable, order_idx) "
                  "VALUES (?,?,?,?,?,?)", (f, 'prj', f + '.3mf', 'h_' + f, 1 if printable else 0, i))
    for (f, pn), q in links.items():
        c.execute("INSERT INTO project_file_parts (id, project_id, file_id, part_id, on_plate_qty) VALUES (?,?,?,?,?)",
                  ('l_' + f + '_' + pn, 'prj', f, ids[pn], q))
    c.commit()
    return 'prj', ids


ALL_OK = lambda f: ['pr1']          # совместимость: всё совместимо
NONE_OK = lambda f: []              # совместимых принтеров нет


def plan(c, allow=False, compat=ALL_OK):
    return po.plan_project(po.project_snapshot('prj'), allow, compat)


# ── 1. один файл / одна деталь: осталось 4, плита даёт 4 -> ровно 1 запуск, 0 лишних ──
c = fresh_db(); mk(c, {'A': (4, 0, 0, 0)}, {'F1': 1}, {('F1', 'A'): 4})
p = plan(c)
check('P1. осталось 4, плита даёт 4 -> 1 запуск, перепроизводства нет, покрыто полностью',
      p['chosen_files'] == {'F1': 1} and len(p['items']) == 1 and p['overproduction_count'] == 0
      and not p['uncovered'] and p['plan_quality'] == 'exact')

# ── 2. один файл печатает НЕСКОЛЬКО деталей ──
c = fresh_db(); mk(c, {'A': (2, 0, 0, 0), 'B': (2, 0, 0, 0)}, {'F1': 1}, {('F1', 'A'): 1, ('F1', 'B'): 1})
p = plan(c)
check('P2. плита несёт две детали по 1 шт, нужно по 2 -> 2 запуска, 0 лишних',
      p['chosen_files'] == {'F1': 2} and p['overproduction_count'] == 0 and not p['uncovered'])

# ── 3. неизбежное перепроизводство: осталось 1, плита даёт 4 ──
c = fresh_db(); mk(c, {'A': (1, 0, 0, 0)}, {'F1': 1}, {('F1', 'A'): 4})
p_no = plan(c, allow=False)
check('P3a. allow_overproduction=false -> НИЧЕГО не планируем скрыто, остаток честно uncovered',
      p_no['items'] == [] and p_no['uncovered'] == {'part_A': 1}
      and p_no['requires_overproduction_approval'] is True
      and p_no['blocked'][0]['reason'] == 'overproduction_not_allowed')
p_yes = plan(c, allow=True)
check('P3b. allow_overproduction=true -> 1 запуск, ровно 3 лишних, остатка нет',
      p_yes['chosen_files'] == {'F1': 1} and p_yes['overproduction_count'] == 3
      and p_yes['overproduction_total'] == {'part_A': 3} and not p_yes['uncovered']
      and p_yes['items'][0]['planned_parts'] == {'part_A': 1}
      and p_yes['items'][0]['planned_overproduction'] == {'part_A': 3})

# ── 4. одна деталь на НЕСКОЛЬКИХ плитах + связанный компонент ──
# A нужно 3, B нужно 1. FA: A×3; FB: A×1,B×1; FC: B×1. Точное покрытие: FA+FC (0 лишних).
c = fresh_db()
mk(c, {'A': (3, 0, 0, 0), 'B': (1, 0, 0, 0)}, {'FA': 1, 'FB': 1, 'FC': 1},
   {('FA', 'A'): 3, ('FB', 'A'): 1, ('FB', 'B'): 1, ('FC', 'B'): 1})
p = plan(c)
check('P4. связанный компонент (A на FA и FB, B на FB и FC) -> точное покрытие FA+FC, 0 лишних',
      p['chosen_files'] == {'FA': 1, 'FC': 1} and p['overproduction_count'] == 0
      and not p['uncovered'] and p['plan_quality'] == 'exact')

# ── 5. greedy-ловушка: «плита-образец» против одиночных плит ──
# По приоритетам перепроизводство важнее числа запусков -> FB+FC+FD (3 запуска, 0 лишних),
# а НЕ FA (1 запуск, 12 лишних). Это и есть доказательство, что greedy не выдаётся за оптимум.
c = fresh_db()
mk(c, {'A': (1, 0, 0, 0), 'B': (1, 0, 0, 0), 'C': (1, 0, 0, 0)},
   {'FA': 1, 'FB': 1, 'FC': 1, 'FD': 1},
   {('FA', 'A'): 5, ('FA', 'B'): 5, ('FA', 'C'): 5, ('FB', 'A'): 1, ('FC', 'B'): 1, ('FD', 'C'): 1})
p = plan(c)
check('P5. плита-образец (5×5×5) НЕ выбрана: 3 одиночных запуска с 0 лишних вместо 1 запуска с 12 лишними',
      p['chosen_files'] == {'FB': 1, 'FC': 1, 'FD': 1} and p['overproduction_count'] == 0)

# ── 6. ручная печать уменьшила остаток (printed_qty ведёт ядро) ──
c = fresh_db(); mk(c, {'A': (4, 3, 0, 0)}, {'F1': 1}, {('F1', 'A'): 1})
p = plan(c)
check('P6. распознанная ручная/экранная печать уже в printed_qty -> остаток 1, план 1 запуск',
      p['deficits'] == {'part_A': 1} and p['chosen_files'] == {'F1': 1} and p['overproduction_count'] == 0)

# ── 7. rework входит в остаток по СУЩЕСТВУЮЩЕЙ семантике ядра ──
c = fresh_db(); mk(c, {'A': (2, 2, 3, 1)}, {'F1': 1}, {('F1', 'A'): 1})
p = plan(c)
check('P7. остаток = max(0,required-printed) + max(0,rework_qty-rework_done) = 0 + 2',
      p['deficits'] == {'part_A': 2} and p['chosen_files'] == {'F1': 2})

# ── 8. частично несовместимый проект: печатаем что можем, остальное blocked ──
c = fresh_db()
mk(c, {'A': (1, 0, 0, 0), 'B': (1, 0, 0, 0)}, {'FA': 1, 'FB': 1}, {('FA', 'A'): 1, ('FB', 'B'): 1})
p = po.plan_project(po.project_snapshot('prj'), False, lambda f: ['pr1'] if f['id'] == 'FA' else [])
check('P8. одна плита без совместимого принтера -> вторая всё равно планируется, остаток blocked',
      p['chosen_files'] == {'FA': 1} and p['uncovered'] == {'part_B': 1}
      and p['blocked'][0]['reason'] == 'no_compatible_printer')
c2 = fresh_db(); mk(c2, {'A': (1, 0, 0, 0)}, {'F1': 0}, {('F1', 'A'): 1})   # is_printable=0
p2 = plan(c2)
check('P9. непечатаемый файл -> blocked=file_missing, ничего не планируем',
      p2['items'] == [] and p2['blocked'][0]['reason'] == 'file_missing')

# ── 9. детерминизм: тот же вход -> байт-в-байт тот же план ──
c = fresh_db()
mk(c, {'A': (3, 0, 0, 0), 'B': (2, 0, 0, 0)}, {'FA': 1, 'FB': 1},
   {('FA', 'A'): 2, ('FA', 'B'): 1, ('FB', 'A'): 1, ('FB', 'B'): 2})
import json as _j
r1, r2 = _j.dumps(plan(c), sort_keys=True, ensure_ascii=False), _j.dumps(plan(c), sort_keys=True, ensure_ascii=False)
check('P10. повторный одинаковый вход даёт БАЙТ-В-БАЙТ одинаковый план', r1 == r2)
check('P11. snapshot_version стабилен и меняется при изменении остатка',
      (lambda v1: (c.execute("UPDATE project_parts SET printed_qty=1 WHERE id='part_A'"), c.commit(),
                   po.project_snapshot('prj')['version'] != v1)[2])(po.project_snapshot('prj')['version']))

# ── 10. форсированный лимит -> честный approximate fallback ──
c = fresh_db()
mk(c, {'A': (7, 0, 0, 0), 'B': (7, 0, 0, 0), 'C': (7, 0, 0, 0)}, {'FA': 1, 'FB': 1, 'FC': 1},
   {('FA', 'A'): 2, ('FA', 'B'): 1, ('FB', 'B'): 2, ('FB', 'C'): 1, ('FC', 'C'): 2, ('FC', 'A'): 1})
p_lim = po.plan_project(po.project_snapshot('prj'), True, ALL_OK, node_limit=3, time_limit_ms=300)
check('P12. превышен лимит узлов -> plan_quality=approximate (fallback честно помечен, не выдаётся за точный)',
      p_lim['plan_quality'] == 'approximate')
p_full = plan(c, allow=True)
check('P13. без форсированного лимита тот же проект решается точно', p_full['plan_quality'] == 'exact')

# ── 11. пустой / уже завершённый проект ──
c = fresh_db(); mk(c, {'A': (2, 2, 0, 0)}, {'F1': 1}, {('F1', 'A'): 1})
p = plan(c)
check('P14. проект уже завершён -> план пуст, blocked пуст, согласия не требуется',
      p['items'] == [] and not p['uncovered'] and not p['blocked']
      and p['requires_overproduction_approval'] is False)
c = fresh_db(); c.execute("INSERT INTO projects (id, name) VALUES ('prj','P')"); c.commit()
p = plan(c)
check('P15. пустой проект (нет деталей и файлов) -> пустой план без падения', p['items'] == [] and p['deficits'] == {})

print('\n' + ('FAIL: %d проверок провалено' % fail if fail else
              'PASS: планировщик детерминирован, точен на тривиальных и связанных компонентах, не '
              'перепроизводит скрыто, честно помечает approximate при лимите, учитывает ручные печати '
              'через printed_qty и rework по существующей семантике ядра'))
sys.exit(1 if fail else 0)
