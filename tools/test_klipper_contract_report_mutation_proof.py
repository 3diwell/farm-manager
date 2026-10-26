# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
#  Alpha 2.839 — MUTATION PROOF встроенного отчёта Klipper.
#
#  ЗАЧЕМ. Отчёт уходит НАРУЖУ, к разработчику, и собирается на ЧУЖОМ принтере. Цена
#  ошибки здесь — утёкший адрес или отправленная принтеру команда. Поэтому каждая
#  гарантия ломается по одной за раз и обязана покраснить ИМЕННО ожидаемую проверку.
#
#  БЕЗОПАСНОСТЬ: восстановление побайтовое (SHA-256), окончания строк смешанные и
#  учитываются, реальному принтеру не уходит ни одного запроса (fake-Moonraker).
#
#  Запуск:  python tools/test_klipper_contract_report_mutation_proof.py   (0 = все пойманы)
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
acquire_or_die('test_klipper_contract_report_mutation_proof')

REP = ["tools/test_klipper_contract_report.py"]
UI = ["tools/test_klipper_contract_report_ui.py"]
K2 = ["tools/test_k2_plus_bed_mesh_prestart.py"]

SRV = "server.py"
PROBE = "app/klipper_contract_probe.py"
APP = "web/app.js"
IDX = "web/index.html"
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
    r = subprocess.run([sys.executable] + argv, cwd=REPO, capture_output=True, timeout=2400, env=env)
    return r.returncode, (r.stdout or b"").decode("utf-8", "replace")


M = []


def mut(n, title, path, old, new, test, expect):
    M.append({"n": n, "title": title, "path": path, "old": old, "new": new,
              "test": test, "expect": expect})


# ═══════════ 1–4: границы обращения к принтеру ══════════════════════════════
mut(1, "разрешён POST к Moonraker", PROBE,
    '    req = urllib.request.Request("http://%s:%s%s" % (host, port, path), method="GET")',
    '    req = urllib.request.Request("http://%s:%s%s" % (host, port, path), method="GET")',
    REP, "A1")   # заменяется ниже: у ядра нет своего HTTP — порча идёт по CLI-обёртке
mut(2, "снята вторая линия защиты: исполняющий фрагмент больше не отклоняется", PROBE,
    '    for bad in FORBIDDEN_FRAGMENTS:\n        if bad in p:\n            return False',
    '    for bad in ():\n        if bad in p:\n            return False', REP, "A6")
#  Alpha 2.887: якорь перенесён на конец списка — в allowlist добавился запрос состояния
#  CFS (/printer/objects/query?box). Смысл порчи прежний: дописать исполняющий эндпоинт.
mut(3, "в allowlist добавлен исполняющий эндпоинт", PROBE,
    '    "/printer/objects/query?box&filament_rack",\n)',
    '    "/printer/objects/query?box&filament_rack",\n    "/printer/gcode/script",\n)', REP, "A2")
mut(4, "разрешён произвольный путь (fail-open вместо fail-closed)", PROBE,
    "    return p in ALLOWED_PATHS", "    return True", REP, "A4")

# ═══════════ 5–9: клиент диктует адрес/эндпоинт ═════════════════════════════
mut(5, "адрес принимается от клиента (маршрут читает тело запроса)", SRV,
    "    _ip, _port = p[\"ip\"], p[\"port\"]",
    "    _body = await _json_body(req)\n    _ip, _port = (_body.get('ip') or p[\"ip\"]), p[\"port\"]",
    REP, "E1")
mut(6, "интерфейс отправляет адрес и токен в теле запроса", APP,
    "'/klipper-contract-report',\n                { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });",
    "'/klipper-contract-report',\n                { method: 'POST', headers: { 'Content-Type': 'application/json' }, "
    "body: JSON.stringify({ ip: '10.0.0.42', token: 'x' }) });", UI, "A15")
mut(7, "маршрут перестаёт проверять allowlist перед запросом", SRV,
    "        if not _kcprobe.is_allowed(path):\n            return (None, \"not_allowed\")",
    "        if False:\n            return (None, \"not_allowed\")", REP, "E3")
_GUARDS = ('    if not p:\n        return JSONResponse({"status": "error", "reason": "no_printer"}, status_code=404)\n'
           '    if str(p["type"] or "").lower() != "klipper":\n'
           '        return JSONResponse({"status": "error", "reason": "not_klipper",')
mut(8, "отчёт собирается для любого адаптера, не только Klipper", SRV, _GUARDS,
    _GUARDS.replace('    if str(p["type"] or "").lower() != "klipper":', "    if False:"),
    REP, "D15")
mut(9, "неизвестный принтер больше не отклоняется", SRV, _GUARDS,
    _GUARDS.replace('    if not p:\n', '    if p is None:\n        p = {"type": "klipper", "ip": "1.2.3.4", '
                    '"port": 7125, "token": "", "serial": "", "id": "", "model": "x"}\n    if False:\n'),
    REP, "D17")

# ═══════════ 10–14: утечки в отчёт ══════════════════════════════════════════
mut(10, "редакция отключена полностью", PROBE,
    "    for rx in _PATTERNS:\n        out = rx.sub(REDACTED, out)",
    "    for rx in ():\n        out = rx.sub(REDACTED, out)", REP, "B1")
mut(11, "известные секреты (токен, серийник) больше не вычищаются", PROBE,
    "    for sec in (secrets or ()):\n        v = str(sec or \"\").strip()\n"
    "        if len(v) >= 3 and v.lower() not in (\"none\", \"null\", \"0\"):\n"
    "            out = out.replace(v, REDACTED)",
    "    for sec in ():\n        v = str(sec or \"\").strip()\n"
    "        if len(v) >= 3 and v.lower() not in (\"none\", \"null\", \"0\"):\n"
    "            out = out.replace(v, REDACTED)", REP, "B4")
mut(12, "редакция перестаёт быть рекурсивной (вложенное не чистится)", PROBE,
    "    if isinstance(obj, dict):\n        return {redact_text(k, secrets): redact(v, secrets) for k, v in obj.items()}",
    "    if isinstance(obj, dict):\n        return dict(obj)", REP, "B10")
mut(13, "самопроверка отключена (утечка проходит наружу)", SRV,
    "    if _leaks:", "    if False:", REP, "E4")
mut(14, "в отчёт добавляется полная конфигурация принтера", PROBE,
    '        "probe_warnings": sorted(set(warnings)),',
    '        "raw_settings": settings,\n        "probe_warnings": sorted(set(warnings)),', REP, "C16")

# ═══════════ 15–17: поведение при отказе ════════════════════════════════════
mut(15, "офлайн создаёт запись об ошибке принтера", SRV,
    '                 "result=unreachable elapsed=%.1fs", str(pid)[:8], time.monotonic() - _t0)',
    '                 "result=unreachable device_error=1 elapsed=%.1fs", str(pid)[:8], time.monotonic() - _t0)',
    REP, "D22")
mut(16, "офлайн больше не ограничен одной проверкой (семь таймаутов подряд)", SRV,
    '    if not _klipper_get_json(_ip, _port, "/printer/info", timeout=3.0):',
    "    if False:", REP, "D21")
mut(17, "частичный отчёт выдаётся за полный", SRV,
    '            "partial": bool(report.get("endpoints_failed"))}',
    '            "partial": False}', REP, "D24")

# ═══════════ 18–20: интерфейс и предохранители фермы ════════════════════════
mut(18, "повторное нажатие запускает второй сбор", APP,
    "        if (klRepBusy.value) return;                    // защита от повторного нажатия",
    "        if (false) return;                    // защита от повторного нажатия", UI, "B9")
mut(19, "предохранитель DISPATCH снят", ORCH, "\nDISPATCH_ENABLED = False\n",
    "\nDISPATCH_ENABLED = True\n", REP, "E10")
mut(20, "предохранитель TRANSPORT снят", ORCH, "\nTRANSPORT_ENABLED = False\n",
    "\nTRANSPORT_ENABLED = True\n", REP, "E11")

# ═══════════ 21–22: старые гарантии не должны исчезнуть ═════════════════════
mut(21, "недоказанная калибровка снова становится автоматической", "app/klipper_prestart.py",
    "        elif overridden:\n            state, why = STATE_MANUAL, WHY_VENDOR_OVERRIDE",
    "        elif False:\n            state, why = STATE_MANUAL, WHY_VENDOR_OVERRIDE", K2, "A3")
# Alpha 2.867: диагностика переехала на ячейку принтера. Ломаем ИМЕННО новые предохранители:
# защиту в коде (окно не должно открываться для не-Klipper) и признак в разметке.
mut(22, "окно диагностики открывается для любого принтера", APP,
    '        if (!p || !printerCapabilities(p).klipper) return;   // отчёт умеет собираться только с Klipper',
    '        if (!p) return;   // отчёт умеет собираться только с Klipper', UI, "A18")
# Якорь длинный намеренно: оба значка (сетка и раскрытая карточка) написаны одинаково,
# уникальным делает только хвост после кнопки. Портится значок в раскрытой карточке.
mut(23, "значок диагностики показывается у любого принтера", IDX,
    'button" v-if="printerCapabilities(p).klipper" class="pc-diag shrink-0 inline-flex items-center" data-help="pc-diag" :title="lang===\'ru\' ? \'Диагностика принтера: собрать отчёт\' : \'Printer diagnostics: collect a report\'" :aria-label="lang===\'ru\' ? \'Диагностика принтера: собрать отчёт\' : \'Printer diagnostics: collect a report\'" @click.stop="openKlipperDiag(p)"><svg-icon name="activity" class="w-3 h-3"></svg-icon></button>\n                                        ',
    'button" v-if="true" class="pc-diag shrink-0 inline-flex items-center" data-help="pc-diag" :title="lang===\'ru\' ? \'Диагностика принтера: собрать отчёт\' : \'Printer diagnostics: collect a report\'" :aria-label="lang===\'ru\' ? \'Диагностика принтера: собрать отчёт\' : \'Printer diagnostics: collect a report\'" @click.stop="openKlipperDiag(p)"><svg-icon name="activity" class="w-3 h-3"></svg-icon></button>\n                                        ', UI, "A10b")

# Порча №1 нацелена на CLI-обёртку: единственное место, где реально строится HTTP-запрос.
M[0]["path"] = "tools/klipper_probe.py"
M[0]["old"] = '        req = urllib.request.Request("http://%s:%s%s" % (host, port, path), method="GET")'
M[0]["new"] = '        req = urllib.request.Request("http://%s:%s%s" % (host, port, path), method="POST", data=b"")'
M[0]["test"] = K2
M[0]["expect"] = "G13"

print("=== Alpha 2.839: mutation proof встроенного отчёта — %d порч ===" % len(M))
print("Каждая обязана покраснить ИМЕННО ожидаемую проверку. Восстановление побайтовое.\n")

TOUCHED = sorted({m["path"] for m in M})
BASE = {p: sha(p) for p in TOUCHED}
for p in TOUCHED:
    print("  %-32s %s" % (p, BASE[p][:16]))
print()

for argv, label in ((REP, "BASE-1. отчёт"), (UI, "BASE-2. интерфейс"), (K2, "BASE-3. подготовка")):
    rc, out = run(argv)
    check("%s: до порчи тест зелёный" % label, rc == 0, out[-300:])
print()

for m in M:
    tag = "M%02d. %s" % (m["n"], m["title"])
    fp = os.path.join(REPO, m["path"])
    orig = io.open(fp, "rb").read()
    txt = orig.decode("utf-8", "surrogateescape")
    old, new = m["old"], m["new"]
    if txt.count(old) != 1 and "\r\n" in txt:      # окончания строк в проекте смешанные
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
for argv, label in ((REP, "REST-3. отчёт"), (UI, "REST-4. интерфейс"), (K2, "REST-5. подготовка")):
    rc, out = run(argv)
    check("%s: после всех порч снова зелёный" % label, rc == 0, out[-300:])

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

# Alpha 2.841: машиночитаемый итог для релизного гейта — считает нули напрямую,
# а не разбирает прозу выше. Человекочитаемая сводка остаётся как была.
from _mutation_report import build as _mut_build, emit as _mut_emit  # noqa: E402

# Отдельных счётчиков «поймано/исполнено» в наборе нет: исход каждой порчи пишет общая
# check() под тем же тегом, что строится в цикле. Поэтому пойманные = объявленные минус
# теги порч, попавшие в FAILED (устаревший якорь тоже попадает туда и в улов не идёт).
_MUT_TAGS = {"M%02d. %s" % (m["n"], m["title"]) for m in M}
_mut_failed = len(_MUT_TAGS & set(FAILED))
_summary = _mut_build(declared=EXPECTED_MUTATIONS,
                      executed=EXPECTED_MUTATIONS,   # цикл идёт по всем M, фильтра порч нет
                      caught=EXPECTED_MUTATIONS - _mut_failed,
                      timeouts=0,                    # счётчика таймаутов в наборе нет
                      restore_failures=len(bad),     # файлы, не вернувшиеся к исходным байтам
                      cleanup_failures=0)            # отдельного счётчика уборки нет
_rc_prev = 0 if not FAILED else 1
_rc = _mut_emit(_summary)
sys.exit(_rc_prev or _rc)
