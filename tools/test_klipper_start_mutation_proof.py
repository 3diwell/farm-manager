# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.833 — mutation proof: ≥22 порч подтверждения запуска Klipper / prestart-возможностей
обязаны краснить тесты. Каждая мутация вносится, целевой тест запускается, файл восстанавливается
байт-в-байт (SHA-256). Production data не трогается; PYTHONDONTWRITEBYTECODE."""
import hashlib
import os
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# Alpha 2.841: наборы mutation proof портят ОДНИ И ТЕ ЖЕ файлы репозитория.
# Параллельный запуск двух наборов уже приводил к тому, что откат одного затирал
# откат другого и в дереве оставалась чужая мутация. Замок сериализует прогоны;
# не дождались — mutation_lock_busy и КРАСНЫЙ выход, а не тихая правка файлов.
sys.path.insert(0, os.path.join(ROOT, "tools"))
from _mutation_lock import acquire_or_die  # noqa: E402
acquire_or_die('test_klipper_start_mutation_proof')
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
BASE_ENV = dict(os.environ); BASE_ENV["PYTHONIOENCODING"] = "utf-8"; BASE_ENV["PYTHONDONTWRITEBYTECODE"] = "1"

SRV = os.path.join(ROOT, "server.py")
KST = os.path.join(ROOT, "app", "klipper_start.py")
KPR = os.path.join(ROOT, "app", "klipper_prestart.py")
APP = os.path.join(ROOT, "web", "app.js")
IDX = os.path.join(ROOT, "web", "index.html")
ORCH = os.path.join(ROOT, "app", "project_orchestrator.py")

CONF = ("py", "test_klipper_start_confirmation")
CAPS = ("py", "test_klipper_prestart_capabilities")
MOON = ("py", "test_moonraker_start_confirmation")
PSUI = ("node", "test_print_start_ui")


def b(x):
    return x.encode("utf-8")


# (file, find, replace, (runner, test), label)
MUT = [
    # 1. read-timeout снова мгновенная красная ошибка
    #  12.10.2026: образец уточнён соседней строкой — «except TimeoutError:» есть и в коде Creality.
    (SRV, b("            except TimeoutError:\n                # (socket.timeout == TimeoutError"),
     b("            except NameError:\n                # (socket.timeout == TimeoutError"),
     CONF, "1: read-timeout снова становится красной ошибкой"),
    # 2. timeout помечается как ошибка устройства (device_error в send-ветке)
    (SRV, b('log.warning(f"[KLIPPER] start response timed out (request delivered) for {fname}: awaiting telemetry confirmation (no auto-retry)")'),
     b('log.warning(f"[KLIPPER] start response timed out for {fname}"); locals().setdefault("device_error", True)'),
     CONF, "2: timeout создаёт device_error-маркер"),
    # 3. timeout снова уводит job в failed (job_failed-канал)
    (SRV, b('return {"status": "ok", "pending_confirmation": True,\n                        "reason": _klstart.user_message(_klstart.PENDING_CONFIRMATION)}'),
     b('return {"status": "error", "pending_confirmation": True,\n                        "reason": _klstart.user_message(_klstart.PENDING_CONFIRMATION)}'),
     CONF, "3: timeout создаёт job_failed (status=error)"),
    # 4. start автоматически повторяется после timeout
    (SRV, b('                _pcb(command_ok=True)                              # → waiting_confirmation (reconciliation по телеметрии)'),
     b('                _resp2 = urllib.request.urlopen(req, timeout=15.0)\n                _pcb(command_ok=True)                              # → waiting_confirmation (reconciliation по телеметрии)'),
     CONF, "4: start повторяется автоматически после timeout"),
    # 5. upload повторяется автоматически (двойной POST на успехе)
    (SRV, b('                _resp = urllib.request.urlopen(req, timeout=15.0)\n                _raw = _resp.read()'),
     b('                _resp = urllib.request.urlopen(req, timeout=15.0)\n                _resp = urllib.request.urlopen(req, timeout=15.0)\n                _raw = _resp.read()'),
     MOON, "5: upload/команда отправляется дважды"),
    # 6. другой filename подтверждает attempt
    (KST, b("    return a == b"),
     b("    return True"),
     CONF, "6: другой filename подтверждает attempt"),
    # 7. другой printer подтверждает attempt
    (KST, b('    if str(printer_id or "") != attempt.printer_id:\n        return PENDING_CONFIRMATION'),
     b('    if str(printer_id or "") != attempt.printer_id:\n        return CONFIRMED'),
     CONF, "7: другой принтер подтверждает attempt"),
    # 8. старая физическая сессия подтверждает новый attempt
    (KST, b("            if float(session_start) < attempt.started_at - 2.0:\n                return PENDING_CONFIRMATION"),
     b("            if float(session_start) < attempt.started_at - 2.0:\n                return CONFIRMED"),
     CONF, "8: старая сессия подтверждает новый attempt"),
    # 9. дедлайн трактуется как доказанный отказ
    (KST, b("    if now > attempt.confirmation_deadline:\n        return UNCERTAIN"),
     b("    if now > attempt.confirmation_deadline:\n        return REJECTED"),
     CONF, "9: deadline считается definite failure"),
    # 10. reservation снимается при pending (мгновенный ложный release)
    (SRV, b('                if j.pop("_saw_running", False):\n                    self._terminate_locked(j, "completed")\n                else:\n                    j["state"] = "waiting_confirmation"; j["updated_at"] = time.time()\n                return'),
     b('                self._terminate_locked(j, "completed")\n                return'),
     CONF, "10: reservation снимается при pending"),
    # 11. телеметрия ДО command_ok слепо завершает job
    (SRV, b('            if j.get("_command_sent"):\n                self._terminate_locked(j, "completed")        # команда отправлена → это НАШ старт → release'),
     b('            if True:\n                self._terminate_locked(j, "completed")        # команда отправлена → это НАШ старт → release'),
     CONF, "11: телеметрия без отправленной команды завершает job"),
    # 12. UI пишет «Печать не запущена» при uncertain
    (APP, b("? 'Не удалось подтвердить запуск. Проверьте состояние принтера перед повторной отправкой.'"),
     b("? 'Печать не запущена.'"),
     CONF, "12: UI пишет «Печать не запущена» при uncertain"),
    # 13. сырой G-code принимается валидацией
    (KPR, b('        if (cap and oid in _OPS_BY_ID and cap.get("state") == STATE_AUTOMATIC\n                and cap.get("supported") and cap.get("safe_each_print")\n                and cap.get("auto_execute") and not cap.get("file_controlled")):\n            if oid not in accepted:\n                accepted.append(oid)'),
     b('        if True:\n            if oid not in accepted:\n                accepted.append(oid)'),
     CAPS, "13: сырой G-code проходит валидацию"),
    # 14. произвольный macro попадает в план команд
    (KPR, b("    plan = []\n    for op in PRESTART_OPS:                   # детерминированный порядок реестра\n        if op[\"id\"] in acc:\n            plan.append(op[\"command\"])"),
     b("    plan = [str(x) for x in (selected_ids or [])]\n    for op in []:                   # детерминированный порядок реестра\n        if op[\"id\"] in acc:\n            plan.append(op[\"command\"])"),
     CAPS, "14: произвольный macro попадает в план"),
    # 15. Bambu-опции протекают в klipper-диалог
    (IDX, b('<div v-if="printStart.caps && printStart.caps.bambu" style="border-top:1px solid var(--fm-border);padding-top:12px;display:flex;flex-direction:column;gap:9px">'),
     b('<div v-if="printStart.caps" style="border-top:1px solid var(--fm-border);padding-top:12px;display:flex;flex-direction:column;gap:9px">'),
     PSUI, "15: Bambu-опции показываются у Klipper"),
    # 16. недоказанная команда считается доступной
    (KPR, b("        has_cmd = (need_cmd is None) or in_help or in_macro"),
     b("        has_cmd = True"),
     CAPS, "16: unknown macro становится capability"),
    # 17. калибровка запускается на занятом принтере
    (SRV, b('    if _ps not in _KLIPPER_IDLE_STATES:\n        log.warning("[KLIPPER PRESTART] failed printer=%s reason=not_idle'),
     b('    if False:\n        log.warning("[KLIPPER PRESTART] failed printer=%s reason=not_idle'),
     CAPS, "17: calibration запускается при busy"),
    # 18. HTTP ACK считается завершением калибровки (post-check снят)
    # Alpha 2.840: калибровка стола проверяется СВОИМ доказательством (состояние + отпечаток
    # сетки), поэтому порча целится в него — это и есть живой путь bed mesh.
    (SRV, b('    _bad = (_ps not in _KLIPPER_IDLE_STATES) or (_wh not in ("", "ready")) or (not fp_after.get("present"))'),
     b('    _bad = False'),
     CAPS, "18: HTTP ACK считается завершением calibration"),
    # 19. «Отмена» диалога отправляет команду печати
    (APP, b("    const closePrintStart = () => { if (printStart.value.open) printStart.value = Object.assign({}, printStart.value, { open: false, onConfirm: null }); };"),
     b("    const closePrintStart = () => { const _cb = printStart.value.onConfirm; if (printStart.value.open) printStart.value = Object.assign({}, printStart.value, { open: false, onConfirm: null }); if (_cb) _cb(null, undefined); };"),
     PSUI, "19: Cancel диалога отправляет команду"),
    # 20. double-click создаёт два attempt (busy-guard снят)
    (SRV, b('            ex = self._resv.get(pid)\n            if ex:\n                return (False, ex, "busy")'),
     b('            ex = self._resv.get(pid)\n            if False:\n                return (False, ex, "busy")'),
     CONF, "20: double-click отправляет два start"),
    # 21-22. DISPATCH/TRANSPORT включаются
    (ORCH, b("\nDISPATCH_ENABLED = False"),
     b("\nDISPATCH_ENABLED = True"),
     CAPS, "21: DISPATCH включён"),
    (ORCH, b("\nTRANSPORT_ENABLED = False"),
     b("\nTRANSPORT_ENABLED = True"),
     CAPS, "22: TRANSPORT включён"),
]

_n = {"caught": 0, "miss": 0, "not_applied": 0}


def run_test(runner, name):
    if runner == "node":
        cmd = ["node", os.path.join(ROOT, "tools", name + ".mjs")]
    else:
        cmd = [sys.executable, os.path.join(ROOT, "tools", name + ".py")]
    return subprocess.run(cmd, env=BASE_ENV, capture_output=True, timeout=300).returncode


def _fit_eol(src, find, repl):
    r"""Подогнать якорь под окончания строк КОНКРЕТНОГО файла, а не под предположение о них.

    Alpha 2.868. ЗДЕСЬ БЫЛ ДЕФЕКТ, и он молча съедал треть набора. Стояло безусловное
    преобразование для server.py (find.replace(b"\n", b"\r\n")) в расчёте на то, что файл
    целиком CRLF. С Alpha 2.863 он лежит с LF (измерено 22.08.2026: 0 CRLF, 18066 LF), и после
    подмены многострочные якоря не находились ни разу: 7 порч из 22 давали «SETUP FAIL».
    Окончания строк в проекте не нормализуются (.gitattributes: * -text), поэтому их нельзя
    предполагать ни в одну сторону — только определять по самому файлу.

    Ослабления нет: не нашлось однозначного совпадения ни как записано, ни в CRLF —
    возвращается исходный якорь, и вызывающий код краснеет на count != 1, как и раньше.
    """
    if src.count(find) == 1:
        return find, repl
    crlf_find = find.replace(b"\n", b"\r\n")
    if src.count(crlf_find) == 1:
        return crlf_find, repl.replace(b"\n", b"\r\n")
    return find, repl


def main():
    for runner, name in sorted({m[3] for m in MUT}):
        if run_test(runner, name) != 0:
            print("BASELINE FAIL:", name); return 1
    print("baseline: целевые тесты зелёные\n")
    for path, find, repl, (runner, test), label in MUT:
        orig = open(path, "rb").read(); sha0 = hashlib.sha256(orig).hexdigest()
        find, repl = _fit_eol(orig, find, repl)
        if orig.count(find) != 1:
            print("SETUP FAIL — якорь не найден/не уникален (%d): [%s]" % (orig.count(find), label))
            # Alpha 2.841: порча НЕ внесена (устаревший якорь). Считаем ОТДЕЛЬНО:
            # иначе executed == declared тождественно и mutation_not_applied мёртв.
            _n["miss"] += 1; _n["not_applied"] += 1; continue
        try:
            open(path, "wb").write(orig.replace(find, repl, 1))
            rc = run_test(runner, test)
        finally:
            open(path, "wb").write(orig)
        reverted = hashlib.sha256(open(path, "rb").read()).hexdigest() == sha0
        ok = rc != 0 and reverted
        _n["caught" if ok else "miss"] += 1
        print("%s — [%-52s] %-38s rc=%d revert=%s"
              % ("CAUGHT" if ok else "MISS  ", label, test.replace("test_", ""), rc, reverted))
    print("\n" + "=" * 80)
    print("Mutation proof 2833: CAUGHT=%d MISS=%d (всего %d)" % (_n["caught"], _n["miss"], len(MUT)))
    # Alpha 2.841: сверка ЧИСЛА исполненных порч с объявленным. Прежний знаменатель
    # len(MUT) самоссылочен — он равен числу итераций по построению и не мог заметить,
    # что часть порч не исполнилась (например, из-за устаревшего якоря).
    _executed = _n["caught"] + _n["miss"]
    if _executed != len(MUT):
        print("ЧИСЛО ИСПОЛНЕННЫХ ПОРЧ %d != объявленных %d — набор недоказателен."
              % (_executed, len(MUT)))

    # Alpha 2.841: машиночитаемый итог для релизного гейта — нули считаются напрямую,
    # а не вычитываются из прозы выше. Человекочитаемая сводка остаётся как была.
    # Отдельных счётчиков таймаута и несостоявшегося отката в этом наборе нет:
    # TimeoutExpired из run_test не перехватывается (падение прогона), а revert=False
    # уже учтён как MISS выше — поэтому здесь честные нули.
    from _mutation_report import build as _mut_build, emit as _mut_emit  # noqa: E402

    _summary = _mut_build(declared=len(MUT),
                          executed=_executed - _n["not_applied"],
                          caught=_n["caught"],
                          timeouts=0,
                          restore_failures=0,
                          cleanup_failures=0)
    # Прежнее условие выхода сохранено дословно; к нему добавляется process_rc из сводки.
    _rc_prev = 0 if (not _n["miss"] and _executed == len(MUT)) else 1
    _rc = _mut_emit(_summary)
    return _rc_prev or _rc


if __name__ == "__main__":
    sys.exit(main())
