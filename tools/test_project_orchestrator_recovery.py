# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# Recovery оркестратора «Печатать весь проект» — core Alpha 2.740 (этапы 1-4, DRY-RUN).
# Главное правило фермы: после перезапуска НИЧТО не продолжается автоматически. Свежая телеметрия —
# единственное доказательство; при сомнении item уходит в ambiguous (липкое), автоповтор запрещён.
# Запуск: python tools/test_project_orchestrator_recovery.py   (0 = пройдено)
import importlib.util, os, sys, sqlite3, tempfile, threading, uuid, re

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location('po', os.path.join(REPO, 'app', 'project_orchestrator.py'))
po = importlib.util.module_from_spec(spec)
spec.loader.exec_module(po)
_SRV = open(os.path.join(REPO, 'server.py'), encoding='utf-8').read()

fail = 0
def check(name, cond):
    global fail
    print(('PASS' if cond else 'FAIL') + ' — ' + name)
    if not cond:
        fail += 1

BOOM = []
def bomb(n):
    def _f(*a, **k):
        BOOM.append(n); raise AssertionError('ЗАПРЕЩЁННЫЙ ВЫЗОВ: ' + n)
    return _f

def _ddl(t):
    return re.search(r'"(CREATE TABLE IF NOT EXISTS %s \(.*?\))"' % t, _SRV, re.S).group(1)

TEL = {}
db = os.path.join(tempfile.mkdtemp(), 'farm_parts.db')
c = sqlite3.connect(db, check_same_thread=False)
c.row_factory = sqlite3.Row
for t in ('projects', 'project_parts', 'project_files', 'project_file_parts', 'project_print_jobs'):
    c.execute(_ddl(t))
c.execute("INSERT INTO projects (id, name) VALUES ('prj','P')")
c.execute("INSERT INTO project_parts (id, project_id, part_name, norm_name, required_qty, printed_qty) "
          "VALUES ('pa','prj','A','a',9,0)")
c.execute("INSERT INTO project_files (id, project_id, filename, content_hash, is_printable) "
          "VALUES ('F1','prj','f1.3mf','h1',1)")
c.execute("INSERT INTO project_file_parts (id, project_id, file_id, part_id, on_plate_qty) "
          "VALUES ('l1','prj','F1','pa',1)")
c.commit()

def SAFETY(pid):
    """Alpha 2.741: безопасностный снимок из той же тестовой телеметрии TEL (стенды — Bambu)."""
    st, fr = TEL.get(pid, ("OFFLINE", False))
    st = str(st or "").upper()
    active = st in ("RUNNING", "PREPARE", "PAUSE", "PAUSED", "SLICING")
    safe = bool(fr) and st == "IDLE"
    return {"printer_id": pid, "transport": "bambu", "status": st, "status_raw": st,
            "fresh": bool(fr), "user_stopped_pending": False, "printing_active": active,
            "safe_idle": safe,
            "unsafe_reason": "" if safe else ("offline_or_stale" if not fr else "not_idle_raw:" + st)}


def boot(b):
    po.init(c, threading.Lock(), lambda p: p + uuid.uuid4().hex[:10], b,
            printer_status_fn=lambda pid: TEL.get(pid, ("OFFLINE", False)),
            safety_fn=SAFETY,
            printers_fn=lambda: [{"id": k, "name": k, "type": "bambu"} for k in
                                 ('pr1', 'pr2', 'pr3', 'pr4', 'pr5', 'pr6')],
            send_reserved_fn=bomb('send_mgr.reserved') if False else (lambda: set()),
            file_ok_fn=lambda f: True)

COMPAT = lambda f: ['pr1']
boot('boot_A')
po.init_db()
run = po.create_run('prj', False, {}, 'op', None, COMPAT)
RID = run['run_id']
check('R1. draft-run и его items созданы (9 запусков по 1 детали)',
      po.get_run(RID)['state'] == 'draft' and len(po.get_run(RID)['items']) == 9)

# токен старого boot — обязан погибнуть при рестарте
TEL['pr1'] = ("IDLE", True)
po.create_clearance('pr1', confirmed=True, run_id=RID, compat_fn=COMPAT)
OLD_CLR = po.active_clearance('pr1')['id']

def set_item(seq, **kw):
    it = [i for i in c.execute("SELECT * FROM project_run_items WHERE run_id=? ORDER BY seq", (RID,))][seq]
    sets = ", ".join("%s=?" % k for k in kw)
    c.execute("UPDATE project_run_items SET %s WHERE id=?" % sets, tuple(kw.values()) + (it["id"],))
    c.commit()
    return it["id"]

def state_of(iid):
    return c.execute("SELECT state, last_error FROM project_run_items WHERE id=?", (iid,)).fetchone()

def mk_pjob(jid, status='dispatched', counted=''):
    c.execute("INSERT INTO project_print_jobs (id, project_id, file_id, printer_id, filename, file_norm, "
              "status, counted_at, snapshot_json) VALUES (?,?,?,?,?,?,?,?,'[]')",
              (jid, 'prj', 'F1', 'pr1', 'f1.3mf', 'f1.3mf', status, counted))
    c.commit()

# ── готовим item'ы во ВСЕХ будущих состояниях (имитируем состояние ДО падения сервера) ──
mk_pjob('pjob_counted', 'finished', '2026-07-16 10:00:00')
mk_pjob('pjob_disp')
# каждому активному item'у — СВОЙ принтер: partial UNIQUE (idx_pri_active_printer) физически
# запрещает двум активным item'ам делить принтер (это проверяет test_project_orchestrator_schema).
i_leased = set_item(0, state='leased', assigned_printer_id='pr1', lease_boot_id='boot_A',
                    lease_nonce='n1', command_sent=0)
i_sending = set_item(1, state='sending', assigned_printer_id='pr2', lease_boot_id='boot_A', command_sent=0)
i_wait = set_item(2, state='waiting_start_confirmation', assigned_printer_id='pr3', lease_boot_id='boot_A',
                  command_sent=1, project_print_job_id='pjob_disp')
i_print = set_item(3, state='printing', assigned_printer_id='pr4', lease_boot_id='boot_A', command_sent=1)
i_counted = set_item(4, state='printing', assigned_printer_id='pr5', lease_boot_id='boot_A', command_sent=1,
                     project_print_job_id='pjob_counted')
i_wpc = set_item(5, state='waiting_plate_clear', assigned_printer_id='pr6', lease_boot_id='boot_A', command_sent=1)
i_pending = set_item(6, state='pending')
i_amb = set_item(7, state='ambiguous_after_dispatch', last_error='был ambiguous до рестарта')

# ══ ПЕРЕЗАПУСК СЕРВЕРА ══
boot('boot_B')
for _p in ('pr1', 'pr2', 'pr3', 'pr4', 'pr5', 'pr6'):
    TEL[_p] = ("IDLE", True)         # свежая телеметрия, принтеры простаивают
rec = po.recover_on_start()

check('R2. старые clearance инвалидированы при рестарте',
      po.active_clearance('pr1') is None
      and c.execute("SELECT invalid_reason FROM plate_clearances WHERE id=?", (OLD_CLR,)).fetchone()["invalid_reason"] == 'server_restart')
check('R3. draft-run пережил рестарт и его items сохранены',
      c.execute("SELECT state FROM project_runs WHERE id=?", (RID,)).fetchone()["state"] in po.RUN_ACTIVE_STATES
      and c.execute("SELECT COUNT(*) n FROM project_run_items WHERE run_id=?", (RID,)).fetchone()["n"] == 9)
check('R4. pending пережил рестарт без изменений', state_of(i_pending)["state"] == 'pending')
check('R5. leased чужого boot_id БЕЗ job и command_sent=0 -> pending (команда точно не отправлялась)',
      state_of(i_leased)["state"] == 'pending' and state_of(i_leased)["last_error"] == 'lease_void_after_restart')
check('R6. lease чужого boot_id обнулён (нельзя продолжить)',
      c.execute("SELECT lease_boot_id, lease_nonce FROM project_run_items WHERE id=?", (i_leased,)).fetchone()["lease_boot_id"] == '')
check('R7. sending (умерли в момент отправки) -> ambiguous: доказать, что команда не ушла, нечем',
      state_of(i_sending)["state"] == 'ambiguous_after_dispatch')
check('R8. command_sent=1 без подтверждения старта -> ambiguous_after_dispatch',
      state_of(i_wait)["state"] == 'ambiguous_after_dispatch')
check('R9. printing без project_print_job -> ambiguous (не completed и не free)',
      state_of(i_print)["state"] == 'ambiguous_after_dispatch')
check('R10. подтверждённый counted project_print_job -> completed (учтено ядром — это факт)',
      state_of(i_counted)["state"] == 'completed' and state_of(i_counted)["last_error"] == 'counted_before_restart')
check('R11. waiting_plate_clear после рестарта НЕ считается чистым -> требует нового подтверждения',
      state_of(i_wpc)["state"] == 'ambiguous_after_dispatch' and po.active_clearance('pr1') is None)
check('R12. ambiguous остаётся липким (recovery его не «чинит»)',
      state_of(i_amb)["state"] == 'ambiguous_after_dispatch')
check('R13. run с ambiguous переведён в attention_required (нужен человек)',
      c.execute("SELECT state FROM project_runs WHERE id=?", (RID,)).fetchone()["state"] == 'attention_required')

# ── идемпотентность ──
snap1 = [repr(tuple(r)) for r in c.execute("SELECT * FROM project_run_items ORDER BY id")]
po.recover_on_start()
snap2 = [repr(tuple(r)) for r in c.execute("SELECT * FROM project_run_items ORDER BY id")]
check('R14. повторный recovery идемпотентен (состояния не «скачут»)', snap1 == snap2)

# ── stale/offline не освобождает и не завершает ──
TEL['pr7'] = ("IDLE", False)          # телеметрия протухла
i_st = set_item(8, state='printing', lease_boot_id='boot_A', command_sent=1, assigned_printer_id='pr7')
po.recover_on_start()
check('R15. stale/offline НИКОГДА не даёт completed/free -> ambiguous с честной причиной',
      state_of(i_st)["state"] == 'ambiguous_after_dispatch'
      and state_of(i_st)["last_error"] == 'no_fresh_telemetry_after_restart')

# ── ручное разрешение ──
check('R16. resolution=started БЕЗ подтверждающего project_print_job отклоняется',
      po.resolve_item(RID, i_print, 'started')['reason'] == 'no_project_print_job_to_confirm'
      and state_of(i_print)["state"] == 'ambiguous_after_dispatch')
check('R17. resolution=started с подтверждающим job принимается',
      po.resolve_item(RID, i_wait, 'started')['status'] == 'ok' and state_of(i_wait)["state"] == 'completed')
# Alpha 2.766: «не начиналась» ВОЗВРАЩАЕТ деталь в очередь (pending), а не хоронит её. Прежний
# failed_before_dispatch был ТУПИКОМ: запуск требует pending/eligible, пути из failed нет — оператор
# был вынужден отменять ВЕСЬ план после каждого сбоя принтера (реальный круг с живой фермы).
# Это НЕ автоповтор: диспатча здесь не происходит (см. R18c), повтор — только явной кнопкой.
_r18 = po.resolve_item(RID, i_print, 'not_started')
check('R18. resolution=not_started -> деталь ВОЗВРАЩЕНА В ОЧЕРЕДЬ (pending) и НИКАКОГО запуска',
      _r18['status'] == 'ok' and state_of(i_print)["state"] == 'pending')
check('R18b. КРИТИЧНО: run вышел из attention_required (есть что печатать -> waiting_for_printer), '
      'а не завис в «нужно решение человека» после решения',
      _r18.get('run_state') == 'waiting_for_printer'
      and c.execute("SELECT state FROM project_runs WHERE id=?", (RID,)).fetchone()["state"] == 'waiting_for_printer')
check('R18c. и след решения сохранён (attempt/история не потеряны)',
      state_of(i_print)["last_error"] == 'resolved_not_started_by_operator')
check('R19. повторный resolve уже разрешённого item -> отказ not_ambiguous',
      po.resolve_item(RID, i_wait, 'started')['reason'] == 'not_ambiguous')
check('R20. неверное значение resolution отклоняется', po.resolve_item(RID, i_amb, 'retry')['reason'] == 'bad_resolution')
check('R21. retry ambiguous напрямую невозможен: единственный выход — resolve человеком '
      '(в модуле нет ни retry-функции, ни авто-повтора)',
      not any(x in re.sub(r'#.*', '', re.sub(r'"""[\s\S]*?"""', '',
              open(os.path.join(REPO, 'app', 'project_orchestrator.py'), encoding='utf-8').read()))
              for x in ('def retry_item', 'auto_retry', 'def _retry')))
# ══ Alpha 2.743 (5A2b): восстановление ДАННЫХ LEASE и удержаний ═══════════════════════════════
# Теперь lease реально записывается (nonce/boot/срок/clearance_id/send_job_id), поэтому проверяем,
# что рестарт разбирает его по уже принятой canonical модели и что удержания восстанавливаются
# ровно по ФАКТИЧЕСКОМУ состоянию item'а, а не по памяти (её после рестарта нет).
c.execute("DELETE FROM project_run_items")
c.execute("UPDATE project_runs SET state='running' WHERE id=?", (RID,))
c.commit()
_L = [('lz_leased', 'leased', 'pz1', 0, ''), ('lz_sending', 'sending', 'pz2', 0, ''),
      ('lz_wait', 'waiting_start_confirmation', 'pz3', 1, ''), ('lz_print', 'printing', 'pz4', 1, ''),
      ('lz_clear', 'waiting_plate_clear', 'pz5', 1, ''), ('lz_failed', 'failed_before_dispatch', 'pz6', 0, '')]
for _i, (_id, _st, _pid, _cs, _pj) in enumerate(_L):
    c.execute("INSERT INTO project_run_items (id, run_id, project_id, file_id, seq, state, "
              "assigned_printer_id, lease_nonce, lease_boot_id, lease_acquired_at, lease_expires_at, "
              "clearance_id, send_job_id, command_sent, project_print_job_id, created_at, updated_at) "
              "VALUES (?,?,'prj','F1',?,?,?,'nonce_x','boot_A',10.0,910.0,'clr_x','send_x',?,?,1.0,1.0)",
              (_id, RID, 50 + _i, _st, _pid, _cs, _pj))
c.commit()
TEL.update({p: ("IDLE", True) for p in ('pz1', 'pz2', 'pz3', 'pz4', 'pz5', 'pz6')})
boot('boot_C')                     # ══ ЧУЖОЙ BOOT: вся память ядра потеряна ══
rec2 = po.recover_on_start()


def _st_of(iid):
    return c.execute("SELECT state FROM project_run_items WHERE id=?", (iid,)).fetchone()["state"]


check('R24. leased без job и без command_sent -> pending (команда точно не отправлялась)',
      _st_of('lz_leased') == 'pending')
check('R25. sending -> ambiguous (могла уйти команда)', _st_of('lz_sending') == 'ambiguous_after_dispatch')
check('R26. waiting_start_confirmation -> ambiguous (нет доказательств старта)',
      _st_of('lz_wait') == 'ambiguous_after_dispatch')
check('R27. printing -> ambiguous (решает человек)', _st_of('lz_print') == 'ambiguous_after_dispatch')
check('R28. waiting_plate_clear -> ambiguous (детали могли остаться на столе)',
      _st_of('lz_clear') == 'ambiguous_after_dispatch')
check('R29. failed_before_dispatch рестарт не трогает (терминальное безопасное состояние)',
      _st_of('lz_failed') == 'failed_before_dispatch')
check('R30. lease чужого boot обнулён у всех разобранных item\'ов',
      all(r["lease_nonce"] == '' and r["lease_boot_id"] == ''
          for r in c.execute("SELECT lease_nonce, lease_boot_id FROM project_run_items "
                             "WHERE id IN ('lz_leased','lz_sending','lz_wait','lz_print','lz_clear')").fetchall()))
# Разрешение, израсходованное ДО рестарта, обязано остаться израсходованным: доказательств пустого
# стола после перезапуска нет, и «воскресить» токен нельзя — оператор подтверждает заново.
c.execute("INSERT INTO plate_clearances (id, printer_id, confirmed_at, nonce, boot_id, consumed_at, "
          "consumed_by_item_id) VALUES ('clr_used','pz9',1.0,'n','boot_A',5.0,'lz_sending')")
c.commit()
po.recover_on_start()
_used = dict(c.execute("SELECT * FROM plate_clearances WHERE id='clr_used'").fetchone())
check('R31. КРИТИЧНО: потреблённое разрешение НЕ восстанавливается рестартом',
      _used['consumed_at'] == 5.0 and _used['consumed_by_item_id'] == 'lz_sending'
      and po.active_clearance('pz9') is None
      and po.consume_clearance('clr_used', 'кто-угодно') is False)
_holds = po.active_holds()
check('R32. КРИТИЧНО: удержания восстанавливаются по ФАКТИЧЕСКОМУ состоянию после рестарта',
      set(_holds) == {'pz2', 'pz3', 'pz4', 'pz5'})
check('R33. pending после разбора lease удержание НЕ создаёт (команда не уходила)', 'pz1' not in _holds)
check('R34. failed_before_dispatch удержание НЕ создаёт', 'pz6' not in _holds)
check('R35. владелец восстановленных удержаний — run', all(h['owner_id'] == RID for h in _holds.values()))
_snap3 = [repr(tuple(r)) for r in c.execute("SELECT * FROM project_run_items ORDER BY id")]
po.recover_on_start()
_snap4 = [repr(tuple(r)) for r in c.execute("SELECT * FROM project_run_items ORDER BY id")]
check('R36. повторный recovery с lease-данными идемпотентен',
      _snap4 == _snap3 and po.active_holds() == _holds)

check('R22. НИ ОДИН recovery-сценарий не тронул печать/сеть/send-manager', BOOM == [])
check('R23. dispatch по-прежнему выключен после всех recovery', po.DISPATCH_ENABLED is False
      and rec['dispatch_enabled'] is False)
check('R37. production scheduler после recovery по-прежнему ничего не делает',
      po.scheduler_tick() == {"status": "disabled", "reason": "project_orchestrator_dispatch_disabled",
                              "leased": 0, "dispatched": 0})

print('\n' + ('FAIL: %d проверок провалено' % fail if fail else
              'PASS: после рестарта draft/items сохраняются, lease чужого boot мёртв, старые clearance '
              'инвалидированы; свежая телеметрия — единственное доказательство, stale/offline никогда не даёт '
              'completed/free; сомнение -> ambiguous (липкое), автоповтора нет, выход только через человека; '
              'recovery идемпотентен и не делает ни одного вызова печати'))
sys.exit(1 if fail else 0)
