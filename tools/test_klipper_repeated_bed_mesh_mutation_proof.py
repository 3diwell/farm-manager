# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
#  Alpha 2.841 — MUTATION PROOF повторной калибровки стола.
#
#  ЗАЧЕМ. Зелёный тест сам по себе не доказывает ничего: он мог бы оставаться
#  зелёным и после возврата дефекта. Здесь в исходники по одной вносятся
#  ПОЛОМКИ, ровно соответствующие тому, что чинила Alpha 2.841 (и тому, что она
#  чинить НЕ должна была), и проверяется, что каждую ловит конкретный тест.
#
#  ВЕРДИКТ (по образцу коммита 1cc681e). Таймаут проверки, сбой оснастки и
#  несостоявшийся откат — КРАСНЫЙ РЕЗУЛЬТАТ НАБОРА, а не «поломка поймана».
#  Прежняя формула `rc != 0` засчитывала зависшую проверку как улов.
#
#  БЕЗОПАСНОСТЬ. Каждая поломка вносится в файл репозитория и откатывается
#  побайтово; SHA-256 сверяется ПОСЛЕ КАЖДОЙ поломки, а не только в конце.
#  Откат защищён журналом нетронутых копий, обработчиками сигналов и atexit.
#  Реальному принтеру не отправляется ни одной команды.
#
#  Запуск:  python tools/test_klipper_repeated_bed_mesh_mutation_proof.py
# ============================================================================
import atexit
import hashlib
import io
import os
import signal
import subprocess
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Alpha 2.841: наборы mutation proof портят ОДНИ И ТЕ ЖЕ файлы репозитория.
# Параллельный запуск двух наборов уже приводил к тому, что откат одного затирал
# откат другого и в дереве оставалась чужая мутация. Замок сериализует прогоны;
# не дождались — mutation_lock_busy и КРАСНЫЙ выход, а не тихая правка файлов.
sys.path.insert(0, os.path.join(REPO, "tools"))
from _mutation_lock import acquire_or_die  # noqa: E402
acquire_or_die('test_klipper_repeated_bed_mesh_mutation_proof')
PY = sys.executable

TIMEOUT_CHECK = 240.0          # соизмеримо со здоровым временем набора (единицы секунд)
TIMEOUT_TOTAL = 900.0

SERVER = os.path.join(REPO, "server.py")
PRESTART = os.path.join(REPO, "app", "klipper_prestart.py")
PROBE = os.path.join(REPO, "app", "klipper_contract_probe.py")
ORCH = os.path.join(REPO, "app", "project_orchestrator.py")

T_REPEAT = "tools/test_klipper_repeated_bed_mesh.py"
T_EXEC = "tools/test_klipper_bed_mesh_execution.py"
T_CONTRACT = "tools/test_k2_plus_real_contract.py"
T_CAPS = "tools/test_klipper_prestart_capabilities.py"
T_PRESTART = "tools/test_k2_plus_bed_mesh_prestart.py"

_ORIG = {}                     # путь -> исходные БАЙТЫ (эталон для отката)
_SHA = {}                      # путь -> SHA-256 исходника


def _read(p):
    return io.open(p, "rb").read()


def _write(p, b):
    io.open(p, "wb").write(b)


def _sha(b):
    return hashlib.sha256(b).hexdigest()


for _p in (SERVER, PRESTART, PROBE, ORCH):
    _ORIG[_p] = _read(_p)
    _SHA[_p] = _sha(_ORIG[_p])


def restore_all():
    """Побайтовый откат ВСЕГО. Должен пережить и исключение, и принудительное завершение."""
    for p, b in _ORIG.items():
        try:
            if _read(p) != b:
                _write(p, b)
        except Exception:
            try:
                _write(p, b)
            except Exception:
                pass


atexit.register(restore_all)
for _sig in ("SIGINT", "SIGTERM", "SIGBREAK"):
    _s = getattr(signal, _sig, None)
    if _s is not None:
        try:
            signal.signal(_s, lambda *a: (restore_all(), sys.exit(1)))
        except Exception:
            pass

HARNESS_ERRORS = []
CAUGHT = []
MISSED = []


def run_test(rel):
    """→ (rc, вышло_ли_время). rc=None означает СБОЙ ОСНАСТКИ, а не результат теста."""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        pr = subprocess.run([PY, os.path.join(REPO, rel)], cwd=REPO, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            timeout=TIMEOUT_CHECK)
        return pr.returncode, False
    except subprocess.TimeoutExpired:
        return None, True
    except Exception:
        return None, False


def mutate(name, path, old, new, tests, note=""):
    """Внести ОДНУ поломку и убедиться, что её ловит хотя бы один из tests."""
    src = _read(path)
    # Концы строк в проекте не нормализуются и не гарантированы (.gitattributes: * -text):
    # с Alpha 2.863 server.py лежит с LF, CRLF остались у app/project_orchestrator.py и app.css. Многострочный
    # якорь с "\n" в CRLF-файле не находится никогда, и поломка тихо превращалась бы в «сбой
    # оснастки». Приводим якорь и замену к концам строк ЭТОГО файла и ничего в нём не флипаем.
    _eol = b"\r\n" if src.count(b"\r\n") > (src.count(b"\n") - src.count(b"\r\n")) else b"\n"
    ob = old.replace("\r\n", "\n").encode("utf-8").replace(b"\n", _eol)
    nb = new.replace("\r\n", "\n").encode("utf-8").replace(b"\n", _eol)
    if src.count(ob) != 1:
        HARNESS_ERRORS.append("%s: якорь не найден однозначно (%d)" % (name, src.count(ob)))
        print("HARNESS — %s: якорь встречается %d раз" % (name, src.count(ob)))
        return
    _write(path, src.replace(ob, nb, 1))
    t0 = time.monotonic()
    caught_by, timed_out = None, False
    try:
        for t in tests:
            rc, to = run_test(t)
            if to:
                timed_out = True
                HARNESS_ERRORS.append("%s: %s не уложился в %.0f c" % (name, t, TIMEOUT_CHECK))
                break
            if rc is None:
                HARNESS_ERRORS.append("%s: %s не запустился" % (name, t))
                break
            if rc != 0:
                caught_by = t
                break
    finally:
        _write(path, src)                       # откат ДО любых выводов
    after = _read(path)
    if _sha(after) != _SHA[path]:
        HARNESS_ERRORS.append("%s: откат не состоялся, SHA-256 расходится" % name)
        print("HARNESS — %s: ОТКАТ НЕ СОСТОЯЛСЯ" % name)
        return
    el = time.monotonic() - t0
    if timed_out or HARNESS_ERRORS and HARNESS_ERRORS[-1].startswith(name):
        print("HARNESS — %s (%.1f c)" % (name, el))
        return
    if caught_by:
        CAUGHT.append(name)
        print("ПОЙМАНА — %-58s %-46s %5.1f c" % (name[:58], caught_by.split("/")[-1][:46], el))
    else:
        MISSED.append(name)
        print("НЕ ПОЙМАНА — %s  %s %.1f c" % (name, note, el))


print("=" * 100)
print("MUTATION PROOF — Alpha 2.841, повторная калибровка стола")
print("=" * 100)
_t_all = time.monotonic()

mutate('1. вызов START_PRINT снова делает калибровку file_controlled', PRESTART,
       '    for op_id, markers in _FILE_MARKERS.items():',
       '    for sm in _START_MACROS:\n        if _calls(sm):\n            reasons.setdefault("bed_mesh_calibrate", WHY_FILE_MACRO)\n            break\n    for op_id, markers in _FILE_MARKERS.items():',
       [T_REPEAT, T_PRESTART, T_CAPS], 'это и есть корень реальной приёмки')

mutate('2. явная команда в файле перестаёт учитываться (двойная калибровка)', PRESTART,
       '                reasons[op_id] = WHY_FILE_EXPLICIT\n                break',
       '                if op_id != "bed_mesh_calibrate":\n                    reasons[op_id] = WHY_FILE_EXPLICIT\n                break',
       [T_REPEAT, T_PRESTART])

mutate('3. поиск подстрокой по всему тексту (регресс 2.838)', PRESTART,
       '        for ln in lines:\n            if ln == name or ln.startswith(name + " ") or ln.startswith(name + "="):\n                return True\n        return False',
       '        return str(name).upper() in str(sample_text or "").upper()',
       [T_REPEAT, T_PRESTART])

mutate('4. PRINT_START снова объявляет калибровку управляемой файлом', PRESTART,
       '    for op_id, markers in _FILE_MARKERS.items():',
       '    if any(l.startswith("PRINT_START") for l in lines):\n        reasons["bed_mesh_calibrate"] = WHY_FILE_EXPLICIT\n    for op_id, markers in _FILE_MARKERS.items():',
       [T_REPEAT])

mutate('5. недоказуемый стартовый макрос снова закрывает путь (не калибрует никто)', PROBE,
       '        return _out(MODE_STANDARD, "start_macro_unproven_self_calibrate",',
       '        return _out(MODE_UNSAFE, "start_macro_unproven_self_calibrate",',
       [T_REPEAT, T_EXEC, T_CONTRACT])

mutate('6. ДОКАЗАННАЯ очистка сетки перестаёт закрывать путь', PROBE,
       '    if risk in (RISK_CLEARS, RISK_REPLACES):',
       '    if risk in (RISK_REPLACES,):',
       [T_REPEAT, T_EXEC, T_CONTRACT])

mutate('7. ДОКАЗАННАЯ подмена сетки перестаёт закрывать путь', PROBE,
       '    if risk in (RISK_CLEARS, RISK_REPLACES):',
       '    if risk in (RISK_CLEARS,):',
       [T_REPEAT, T_EXEC, T_CONTRACT])

mutate('8. доказанно калибрующий стартовый макрос -> калибруем ВТОРОЙ раз', PROBE,
       '    if risk == RISK_RECALIBRATES:',
       '    if risk == "\\x00never":',
       [T_REPEAT, T_EXEC, T_CONTRACT])

mutate('9. покой снова только standby (вторая печать отказывает)', SERVER,
       '_KLIPPER_IDLE_STATES = ("standby", "complete", "cancelled")',
       '_KLIPPER_IDLE_STATES = ("standby",)',
       [T_REPEAT])

mutate('10. идущая печать объявляется покоем', SERVER,
       '_KLIPPER_IDLE_STATES = ("standby", "complete", "cancelled")',
       '_KLIPPER_IDLE_STATES = ("standby", "complete", "cancelled", "printing", "paused")',
       [T_REPEAT])

mutate('11. пустое состояние (нет данных) принимается за покой', SERVER,
       '_KLIPPER_IDLE_STATES = ("standby", "complete", "cancelled")',
       '_KLIPPER_IDLE_STATES = ("standby", "complete", "cancelled", "")',
       [T_REPEAT])

mutate('12. проверка ПОСЛЕ калибровки снова требует строго standby', SERVER,
       '    _bad = (_ps not in _KLIPPER_IDLE_STATES) or (_wh not in ("", "ready")) or (not fp_after.get("present"))',
       '    _bad = (_ps != "standby") or (_wh not in ("", "ready")) or (not fp_after.get("present"))',
       [T_REPEAT])

mutate('13. проверка после обычной операции снова требует строго standby', SERVER,
       '        if _ps not in _KLIPPER_IDLE_STATES or (_wh and _wh != "ready"):',
       '        if _ps != "standby" or (_wh and _wh != "ready"):',
       [T_REPEAT, T_CAPS])

mutate('14. активная сетка отменяет новую калибровку', SERVER,
       '    fp_before = _kcprobe.mesh_fingerprint(_mesh())',
       '    fp_before = _kcprobe.mesh_fingerprint(_mesh())\n    if fp_before.get("present"):\n        return (True, "", info)',
       [T_REPEAT])

mutate('15. запаркованные оси отменяют не только G28, но и калибровку', SERVER,
       '    cmd = (plan["commands"] or ["BED_MESH_CALIBRATE"])[0]',
       '    if all(a in homed_axes() for a in ("x", "y", "z")):\n        return (True, "", info)\n    cmd = (plan["commands"] or ["BED_MESH_CALIBRATE"])[0]',
       [T_REPEAT])

mutate('16. одинаковый отпечаток объявляется провалом калибровки', SERVER,
       '    _bad = (_ps not in _KLIPPER_IDLE_STATES) or (_wh not in ("", "ready")) or (not fp_after.get("present"))',
       '    _bad = (_ps not in _KLIPPER_IDLE_STATES) or (_wh not in ("", "ready")) or (not fp_after.get("present")) or (not changed)',
       [T_REPEAT])

mutate('17. G28 отправляется всегда, даже когда оси запаркованы', SERVER,
       '        if not all(a in _hx for a in ("x", "y", "z")):\n            _t0 = time.monotonic()',
       '        if True:\n            _t0 = time.monotonic()',
       [T_REPEAT])

mutate('18. парковка перестаёт выполняться вообще', SERVER,
       '    if plan["requires_homing"]:',
       '    if False:',
       [T_REPEAT])

mutate('19. таймаут калибровки автоматически повторяет команду', SERVER,
       '    r = _send(cmd, cls, 900.0)',
       '    r = _send(cmd, cls, 900.0)\n    if r == "timeout":\n        r = _send(cmd, cls, 900.0)',
       [T_REPEAT, T_EXEC])

mutate('20. проверка результата калибровки пропускается (HTTP-ответа хватает)', SERVER,
       '    pcb(stage="verifying", op=cls)',
       '    return (True, "", info)\n    pcb(stage="verifying", op=cls)',
       [T_REPEAT, T_EXEC])

mutate('21. неудача калибровки не мешает загрузке файла', SERVER,
       '        if not _ok_bm:\n            return (False, _why_bm)',
       '        if not _ok_bm:\n            _ok_bm = True',
       [T_REPEAT, T_EXEC, T_CAPS])

mutate('22. DISPATCH включается', ORCH,
       '\nDISPATCH_ENABLED = False',
       '\nDISPATCH_ENABLED = True',
       [T_REPEAT])

mutate('23. TRANSPORT включается', ORCH,
       '\nTRANSPORT_ENABLED = False',
       '\nTRANSPORT_ENABLED = True',
       [T_REPEAT])

mutate('24. выбор пользователя молча отбрасывается перед подготовкой', SERVER,
       '    _bm_selected = "bed_mesh_calibrate" in [str(x or "").strip() for x in (selected_ids or [])]',
       '    _bm_selected = False',
       [T_REPEAT, T_CAPS])

# ════════════════════════════════════════════════════════════════════════════
restore_all()
_bad_sha = [p for p in _ORIG if _sha(_read(p)) != _SHA[p]]
_el = time.monotonic() - _t_all
print("=" * 100)
print("ИТОГО: поймано %d, не поймано %d, сбоев оснастки %d, время %.1f c"
      % (len(CAUGHT), len(MISSED), len(HARNESS_ERRORS), _el))
for m in MISSED:
    print("  НЕ ПОЙМАНА: %s" % m)
for h in HARNESS_ERRORS:
    print("  СБОЙ ОСНАСТКИ: %s" % h)
for p in _bad_sha:
    print("  ФАЙЛ НЕ ВОССТАНОВЛЕН: %s" % p)
if _el > TIMEOUT_TOTAL:
    print("  НАБОР НЕ УЛОЖИЛСЯ В %.0f c" % TIMEOUT_TOTAL)
# Alpha 2.841: число ИСПОЛНЕННЫХ поломок сверяется с объявленным. Без этого набор, у которого
# часть поломок отвалилась бы «до счёта» (например, все якоря устарели разом), мог отчитаться
# «0 не поймано» и выйти нулём, не проверив ничего.
EXPECTED_MUTATIONS = 24
_executed = len(CAUGHT) + len(MISSED) + len(HARNESS_ERRORS)
if _executed != EXPECTED_MUTATIONS:
    print("  ЧИСЛО ИСПОЛНЕННЫХ ПОЛОМОК %d != объявленных %d — набор недоказателен."
          % (_executed, EXPECTED_MUTATIONS))
_ok = ((not MISSED) and (not HARNESS_ERRORS) and (not _bad_sha)
       and _el <= TIMEOUT_TOTAL and _executed == EXPECTED_MUTATIONS)
print("РЕЗУЛЬТАТ: %s" % ("ВСЕ ПОЛОМКИ ПОЙМАНЫ" if _ok else "ЕСТЬ ПРОБЛЕМЫ"))

# Alpha 2.841: машиночитаемый итог для релизного гейта — считает нули напрямую,
# а не разбирает прозу выше. Человекочитаемая сводка остаётся как была.
from _mutation_report import build as _mut_build, emit as _mut_emit  # noqa: E402

_summary = _mut_build(declared=EXPECTED_MUTATIONS,
                      executed=_executed,
                      caught=len(CAUGHT),
                      timeouts=len(HARNESS_ERRORS),
                      restore_failures=len(_bad_sha),
                      cleanup_failures=0)
_rc_prev = 0 if _ok else 1
_rc = _mut_emit(_summary)
sys.exit(_rc_prev or _rc)
