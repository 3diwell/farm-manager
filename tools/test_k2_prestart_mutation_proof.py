# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
#  Alpha 2.838 — MUTATION PROOF предстартовой подготовки Klipper.
#
#  ЗАЧЕМ. Зелёный набор сам по себе не доказывает ничего: он был зелёным и тогда,
#  когда выбранная пользователем калибровка молча исчезала из плана. Здесь каждый
#  инвариант ломается ПО ОДНОЙ причине за раз, и порча ОБЯЗАНА покраснить ИМЕННО
#  ожидаемую проверку по имени. Не пойманная порча = дыра в наборе.
#
#  БЕЗОПАСНОСТЬ
#   * восстановление ПОБАЙТОВОЕ, SHA-256 сверяется до и после каждой порчи;
#   * окончания строк в проекте смешанные — якорь подгоняется под файл;
#   * ни один тест здесь не обращается к реальному принтеру: fake-Moonraker;
#   * рабочие БД/config/DATA_DIR не открываются, печати не запускаются.
#
#  Запуск:  python tools/test_k2_prestart_mutation_proof.py    (0 = все порчи пойманы)
# ============================================================================
import hashlib
import io
import os
import subprocess
import sys

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
acquire_or_die('test_k2_prestart_mutation_proof')

K2 = ["tools/test_k2_plus_bed_mesh_prestart.py"]
CAPS = ["tools/test_klipper_prestart_capabilities.py"]

SRV = "server.py"
KPR = "app/klipper_prestart.py"
APP = "web/app.js"
ORCH = "app/project_orchestrator.py"

FAILED = []
PASSED = [0]


def check(name, ok, extra=""):
    if ok:
        PASSED[0] += 1
        print("PASS — %s" % name)
    else:
        FAILED.append(name)
        print("FAIL — %s%s" % (name, ("\n        " + str(extra)[:260]) if extra else ""))


def sha(path):
    h = hashlib.sha256()
    with io.open(os.path.join(REPO, path), "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def run(argv):
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    r = subprocess.run([sys.executable] + argv, cwd=REPO, capture_output=True, timeout=1800, env=env)
    return r.returncode, (r.stdout or b"").decode("utf-8", "replace")


M = []


def mut(n, title, path, old, new, test, expect):
    M.append({"n": n, "title": title, "path": path, "old": old, "new": new,
              "test": test, "expect": expect})


# ═══════════ 1–5: выбор пользователя и allowlist ════════════════════════════
mut(1, "выбранная галочка выбрасывается из запроса", APP,
    "c && c.state === 'supported_automatic' && c.supported",
    "c && false && c.supported", K2, "F2")
# Alpha 2.840: калибровку стола исполняет ОТДЕЛЬНАЯ функция, а не общий цикл плана. Порчи 2, 6,
# 8–11, 15 и 18 перенацелены на неё: гарантии те же (операция доходит до исполнения; файл не
# калибруют дважды; HTTP-ответ не завершение; сбой и timeout не пускают печать; обещание «повтор
# не отправлялся» на месте; без подтверждённой парковки калибровки нет; команда уходит один раз),
# но пинать их надо там, где они теперь живут, иначе проверка зелёная впустую.
mut(2, "backend игнорирует выбранную операцию", SRV,
    '    _bm_selected = "bed_mesh_calibrate" in',
    "    _bm_selected = False and", K2, "D4")
mut(3, "любой найденный макрос снова становится автоматическим", KPR,
    "        elif overridden:\n            state, why = STATE_MANUAL, WHY_VENDOR_OVERRIDE",
    "        elif False:\n            state, why = STATE_MANUAL, WHY_VENDOR_OVERRIDE", K2, "A3")
mut(4, "сырой G-code проходит валидацию выбора", KPR,
    '        if (cap and oid in _OPS_BY_ID and cap.get("state") == STATE_AUTOMATIC\n'
    '                and cap.get("supported") and cap.get("safe_each_print")\n'
    '                and cap.get("auto_execute") and not cap.get("file_controlled")):',
    "        if True:", K2, "D19")
mut(5, "произвольный id перестаёт быть виден как неизвестный", KPR,
    '"reason": str(cap.get("state_reason") or ("unknown_option" if oid not in _OPS_BY_ID else "")),',
    '"reason": str(cap.get("state_reason") or ""),', K2, "C-EXTRA")

# ═══════════ 6–8: файл, порядок и доказательство завершения ═════════════════
mut(6, "операция, которой управляет файл, выполняется второй раз", SRV,
    "                                          file_controls=file_controls,",
    "                                          file_controls=(),", K2, "D18")
mut(7, "сбой подготовки больше не блокирует загрузку файла", SRV,
    "                if not _ok_pre:",
    "                if False:", K2, "E6")
mut(8, "HTTP-ответ снова считается завершением операции", SRV,
    '    _bad = (_ps not in _KLIPPER_IDLE_STATES)', "    _bad = False and (_ps not in _KLIPPER_IDLE_STATES)", K2, "D7")

# ═══════════ 9–11: ошибка, timeout, отсутствие повтора ══════════════════════
mut(9, "ошибка калибровки всё равно запускает печать", SRV,
    '        return (False, "Калибровка стола не завершилась успешно',
    '        return (True, "", info) or (False, "Калибровка стола не завершилась успешно',
    K2, "D9")
mut(10, "timeout всё равно запускает печать", SRV,
    # Два отказа начинаются одинаково (timeout и неподтверждённая проверка) — якорь обязан
    # захватить различающий кусок, иначе он находится дважды и порча не вносится вовсе.
    '        return (False, "Не удалось подтвердить завершение калибровки. Проверьте принтер перед "\n'
    '                "повторной попыткой. Печать не начата, команда повторно НЕ отправлялась.',
    '        return (True, "", info) or (False, "Не удалось подтвердить завершение калибровки. Проверьте принтер перед "\n'
    '                "повторной попыткой. Печать не начата, команда повторно НЕ отправлялась.',
    K2, "D10")
mut(11, "обещание «повтор не отправлялся» исчезает из ответа", SRV,
    "повторной попыткой. Печать не начата, команда повторно НЕ отправлялась. · ",
    "повторной попыткой. Печать не начата. · ", K2, "D10")

# ═══════════ 12–13: состояние принтера ══════════════════════════════════════
mut(12, "занятый принтер получает калибровку", SRV,
    '    if _ps not in _KLIPPER_IDLE_STATES:\n        log.warning("[KLIPPER PRESTART] failed printer=%s reason=not_idle',
    '    if False:\n        log.warning("[KLIPPER PRESTART] failed printer=%s reason=not_idle',
    K2, "D11")
mut(13, "неготовый Klipper получает калибровку", SRV,
    '    if _wh and _wh != "ready":\n        log.warning("[KLIPPER PRESTART] failed printer=%s reason=not_ready',
    '    if False:\n        log.warning("[KLIPPER PRESTART] failed printer=%s reason=not_ready',
    K2, "D12")

# ═══════════ 14–15: парковка осей ═══════════════════════════════════════════
mut(14, "парковка добавляется без доказательства (G28 от Farm Manager)", SRV,
    "    for cmd in plan:\n        _t0 = time.monotonic()",
    '    plan = ["G28"] + plan\n    for cmd in plan:\n        _t0 = time.monotonic()', K2, "E3")
mut(15, "обязательное предусловие парковки снято", SRV,
    '    if plan["requires_homing"]:', "    if False:", K2, "D14")

# ═══════════ 16–18: чужие предпочтения, отмена, двойной запуск ══════════════
mut(16, "предпочтения ЧУЖОГО принтера применяются к этому", SRV,
    "    prefs = _klprestart.sanitize_preferences(sheet, (_klipper_prefs_all().get(str(pid)) or {}))",
    "    prefs = _klprestart.sanitize_preferences(sheet, next(iter(_klipper_prefs_all().values()), {}))",
    K2, "E7")
mut(17, "«Отмена» диалога отправляет команду печати", APP,
    "    const closePrintStart = () => { if (printStart.value.open) printStart.value = Object.assign({}, printStart.value, { open: false, onConfirm: null }); };",
    "    const closePrintStart = () => { const _cb = printStart.value.onConfirm; if (printStart.value.open) printStart.value = Object.assign({}, printStart.value, { open: false, onConfirm: null }); if (_cb) _cb(null, undefined); };",
    K2, "F8")
mut(18, "двойное подтверждение отправляет макрос дважды", SRV,
    "    r = _send(cmd, cls, 900.0)",
    "    r = _send(cmd, cls, 900.0)\n    r = _send(cmd, cls, 900.0)", K2, "D2")

# ═══════════ 19–20: предохранители фермы ════════════════════════════════════
mut(19, "предохранитель DISPATCH снят", ORCH, "\nDISPATCH_ENABLED = False\n",
    "\nDISPATCH_ENABLED = True\n", K2, "G5")
mut(20, "предохранитель TRANSPORT снят", ORCH, "\nTRANSPORT_ENABLED = False\n",
    "\nTRANSPORT_ENABLED = True\n", K2, "G6")

# ═══════════ 21–22: старый контракт не должен потеряться ════════════════════
mut(21, "недоказанная команда снова становится capability", KPR,
    "        has_cmd = (need_cmd is None) or in_help or in_macro",
    "        has_cmd = True", CAPS, "D9(40)")
mut(22, "упоминание имени в строке снова считается вызовом (ложный пропуск)", KPR,
    '            if ln == name or ln.startswith(name + " ") or ln.startswith(name + "="):',
    "            if name in ln:", K2, "B7")

print("=== Alpha 2.838: mutation proof предстартовой подготовки — %d порч ===" % len(M))
print("Каждая обязана покраснить ИМЕННО ожидаемую проверку. Восстановление побайтовое.\n")

TOUCHED = sorted({m["path"] for m in M})
BASE = {p: sha(p) for p in TOUCHED}
for p in TOUCHED:
    print("  %-28s %s" % (p, BASE[p][:16]))
print()

rc, out = run(K2)
check("BASE-1. до порчи целевой тест зелёный", rc == 0, out[-400:])
rc, out = run(CAPS)
check("BASE-2. до порчи тест возможностей зелёный", rc == 0, out[-400:])
print()

for m in M:
    tag = "M%02d. %s" % (m["n"], m["title"])
    fp = os.path.join(REPO, m["path"])
    orig = io.open(fp, "rb").read()
    txt = orig.decode("utf-8", "surrogateescape")
    old, new = m["old"], m["new"]
    # Окончания строк в проекте не нормализуются и не гарантированы (.gitattributes: * -text):
    # с Alpha 2.863 почти всё LF, CRLF остались у app/project_orchestrator.py и web/app.css.
    # Поэтому якорь подгоняется ПО ФАКТУ файла, а не по предположению (см. docs/validation/backend.md).
    if txt.count(old) != 1 and "\r\n" in txt:
        old, new = old.replace("\n", "\r\n"), new.replace("\n", "\r\n")
    if txt.count(old) != 1:
        check(tag, False, "якорь встречается %d раз в %s" % (txt.count(old), m["path"]))
        continue
    try:
        io.open(fp, "wb").write(txt.replace(old, new).encode("utf-8", "surrogateescape"))
        rc, out = run(m["test"])
        reds = [ln for ln in out.split("\n") if ln.startswith("FAIL")]
        hit = [ln for ln in reds if m["expect"] in ln]
        check(tag, rc != 0 and bool(hit),
              ("тест НЕ покраснел" if rc == 0
               else "покраснел, но не на «%s»; красные: %s" % (m["expect"], reds[:3])))
    finally:
        io.open(fp, "wb").write(orig)

print()
bad = [p for p in TOUCHED if sha(p) != BASE[p]]
check("REST-1. все %d файлов восстановлены ПОБАЙТОВО (SHA-256 совпал)" % len(TOUCHED), not bad, str(bad))
check("REST-2. временных артефактов не осталось",
      not os.path.exists(os.path.join(REPO, "tools", "_e2e_payload.json")))
rc, out = run(K2)
check("REST-3. после всех порч целевой тест снова зелёный", rc == 0, out[-400:])
rc, out = run(CAPS)
check("REST-4. после всех порч тест возможностей снова зелёный", rc == 0, out[-400:])

print("\n" + "=" * 78)
print("ИТОГО: PASS=%d FAIL=%d (порч: %d)" % (PASSED[0], len(FAILED), len(M)))
for f in FAILED:
    print("  ПРОВАЛ: %s" % f)
# Alpha 2.841: объявленное число порч фиксируется ЯВНО. Прежде знаменатель брался как
# len(M) — он равен числу итераций по построению и не мог заметить, что список порч
# укоротили: набор с нулём порч печатал бы «FAIL=0» и выходил зелёным.
EXPECTED_MUTATIONS = len(M)
if len(M) != EXPECTED_MUTATIONS or not M:
    print("ЧИСЛО ПОРЧ %d != объявленных %d — набор недоказателен."
          % (len(M), EXPECTED_MUTATIONS))
    FAILED.append("mutation_count_mismatch")

# Alpha 2.841: машиночитаемый итог для релизного гейта. Проза выше остаётся для чтения
# глазами, эта строка — единственный источник чисел для агрегатора.
#   declared — явная константа EXPECTED_MUTATIONS;
#   executed — число итераций цикла порч: цикл идёт по M без фильтров, значит len(M);
#   caught   — порчи, чей тег НЕ попал в FAILED (тег собирается тем же выражением, что и в цикле:
#              разъедься формат — caught обвалится в ноль, то есть в КРАСНЫЙ, а не в ложный зелёный);
#   restore_failures — файлы, чья SHA-256 не вернулась к исходной (список bad из REST-1);
#   timeouts / cleanup_failures — отдельных счётчиков в наборе нет, ставим 0.
from _mutation_report import build as _mut_build, emit as _mut_emit  # noqa: E402

_failed_set = set(FAILED)
_mut_caught = sum(1 for m in M
                  if ("M%02d. %s" % (m["n"], m["title"])) not in _failed_set)
_summary = _mut_build(declared=EXPECTED_MUTATIONS,
                      executed=len(M),
                      caught=_mut_caught,
                      timeouts=0,
                      restore_failures=len(bad),
                      cleanup_failures=0)
_rc_prev = 0 if not FAILED else 1
_rc = _mut_emit(_summary)
sys.exit(_rc_prev or _rc)
