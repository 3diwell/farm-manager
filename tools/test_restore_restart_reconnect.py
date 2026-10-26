# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.829 — перезапуск после restore: root cause зафиксирован, reconnect по boot_id,
один hard reload, timeout снимает блокировку, pending-маркер, границы Client.

РЕАЛЬНЫЙ production-код restartWaitReady/restartProbe/hardReloadOnce извлекается из web/app.js
и ИСПОЛНЯЕТСЯ в Node со стабами (fetch-сценарии). Никакого запуска сервера/принтеров.
"""
import json
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

_n = {"pass": 0, "fail": 0}


def check(label, cond):
    ok = bool(cond)
    print(("PASS" if ok else "FAIL") + " — " + label)
    _n["pass" if ok else "fail"] += 1
    return ok


JS = open(os.path.join(ROOT, "web", "app.js"), encoding="utf-8").read()
SRV = open(os.path.join(ROOT, "server.py"), encoding="utf-8").read()

print("--- root cause (характеризация по коду) ---")
check("63a. root cause задокументирован в коде (ранний bind + backlog делают down-окно невидимым)",
      "окно недоступности невидимо" in JS and "backlog" in JS)
check("63b. новый контракт: определение нового процесса по СМЕНЕ boot_id, не по гонке",
      "probe.bootId !== oldBoot" in JS and "hardReloadOnce(probe.bootId)" in JS)
check("65-66. /version отдаёт boot_id (время+pid) — старый исчезает, новый обнаруживается",
      '"boot_id": _BOOT_ID' in SRV and '_BOOT_ID = "%s-%s" % (_BOOT, os.getpid())' in SRV)
check("76. restore journal complete ДО restart (панель после apply; журнал complete в движке)",
      "journal.complete()" in open(os.path.join(ROOT, "app", "config_backup", "multistore.py"),
                                   encoding="utf-8").read())

print("--- исполнение production-логики в Node ---")
seg_start = JS.find("    const serverBootId = ref('')")
seg_end = JS.find("    const doRestart = async ()")
assert seg_start > 0 and seg_end > seg_start
seg = JS[seg_start:seg_end]
# restartWaitReady стоит ПОСЛЕ restartMessage/restartReasonCode — вырежем только нужные const
m = re.search(r"(    const restartMessage[\s\S]*?    const restartProbe)", seg)
if m:
    seg = seg.replace(m.group(1), "    const restartProbe")

harness = r"""
'use strict';
const results = {};
function ref(v) { return { value: v }; }
const restartPhase = ref('idle');
const lang = ref('ru');
const calls = { reload: 0, assign: '' };
const location = { reload() { calls.reload++; }, assign(u) { calls.assign = u; } };
const _ss = {};
const sessionStorage = { getItem: (k) => (k in _ss ? _ss[k] : null), setItem: (k, v) => { _ss[k] = String(v); }, removeItem: (k) => { delete _ss[k]; } };
class AbortController { constructor() { this.signal = {}; } abort() {} }
const setTimeout = (fn, ms) => { fn(); return 0; };
const clearTimeout = () => {};
let fetchQueue = [];
let fetchDefault = null;
const fetch = async () => {
    const next = fetchQueue.length ? fetchQueue.shift() : fetchDefault;
    if (!next) throw new Error('no fetch');
    if (next.throw) throw new Error('refused');
    return { ok: true, json: async () => next.body };
};
SEGMENT
async function main() {
    // С1: boot сменился БЕЗ видимого down-окна (все probe alive) -> ровно один reload
    serverBootId.value = 'OLD'; restartOldBootId.value = 'OLD';
    fetchQueue = [ { body: { version: 'x', boot_id: 'OLD' } }, { body: { version: 'x', boot_id: 'OLD' } },
                   { body: { version: 'x', boot_id: 'NEW' } } ];
    fetchDefault = { body: { version: 'x', boot_id: 'NEW' } };
    calls.reload = 0; for (const k in _ss) delete _ss[k];
    await restartWaitReady('');
    results.s1_reload = calls.reload; results.s1_guard = _ss['fm_restart_reload_done'] || '';

    // С2: guard от петли — повторный вызов с тем же новым boot_id НЕ перезагружает
    calls.reload = 0;
    hardReloadOnce('NEW');
    results.s2_reload = calls.reload;

    // С3: timeout — boot не меняется 90 циклов -> phase='timeout' (без reload)
    serverBootId.value = 'OLD'; restartOldBootId.value = 'OLD';
    fetchQueue = []; fetchDefault = { body: { version: 'x', boot_id: 'OLD' } };
    calls.reload = 0; restartPhase.value = 'waiting'; for (const k in _ss) delete _ss[k];
    await restartWaitReady('');
    results.s3_phase = restartPhase.value; results.s3_reload = calls.reload;

    // С4: запасной путь для сервера БЕЗ boot_id: down -> up -> reload
    serverBootId.value = ''; restartOldBootId.value = '';
    fetchQueue = [ { body: { version: 'x' } }, { throw: true }, { throw: true },
                   { body: { version: 'x' } } ];
    fetchDefault = { body: { version: 'x' } };
    calls.reload = 0; for (const k in _ss) delete _ss[k];
    await restartWaitReady('');
    results.s4_reload = calls.reload;
    console.log(JSON.stringify(results));
}
main().catch(e => { console.error('HARNESS_ERR', e && e.message); process.exit(2); });
""".replace("SEGMENT", seg)

tmp = tempfile.mkdtemp()
hp = os.path.join(tmp, "h.mjs")
open(hp, "w", encoding="utf-8").write(harness)
node = "node"
r = subprocess.run([node, hp], capture_output=True, timeout=60)
out = r.stdout.decode("utf-8", "replace").strip().splitlines()
data = {}
for ln in reversed(out):
    try:
        data = json.loads(ln); break
    except Exception:
        continue
check("64+67. ROOT CAUSE FIX: смена boot_id БЕЗ down-окна -> ровно ОДИН hard reload",
      data.get("s1_reload") == 1)
check("68-69. reload = возврат UI (overlay исчезает перезагрузкой страницы); guard записан",
      data.get("s1_guard") == "NEW")
check("70. reload-петли нет (повторный вызов с тем же boot_id не перезагружает)",
      data.get("s2_reload") == 0)
check("71. timeout снимает ожидание: phase='timeout', без reload",
      data.get("s3_phase") == "timeout" and data.get("s3_reload") == 0)
check("запасной путь down->up без boot_id сохранён", data.get("s4_reload") == 1)

print("--- timeout UX / retry / маркер / границы ---")
IDX = open(os.path.join(ROOT, "web", "index.html"), encoding="utf-8").read()
check("71b. timeout-состояние НЕ безвыходно: «Повторить подключение» + «Закрыть»",
      "retryRestartConnection()" in IDX and "dismissRestartState()" in IDX)
check("72. retry connection: boot-aware повторная проверка",
      "const probe = await restartProbe();" in JS.split("const retryRestartConnection")[1][:400])
check("71c. текст timeout содержит инструкцию про трей",
      "через значок в трее" in JS)
check("73-74. Desktop/Browser: один и тот же page-level reload контракт (hardReloadOnce)",
      JS.count("hardReloadOnce(") >= 2)
check("75. Client НЕ может restore/restart production server (SYSTEM_ADMIN guard на маршрутах)",
      "_require_system_admin(req)" in SRV.split("async def cfgbackup_restore")[1][:900]
      and "_require_system_admin(req)" in SRV.split("async def restart_app")[1][:900])
check("77. pending-маркер снимается ТОЛЬКО после НОВОГО процесса (сравнение boot_id при старте)",
      "fm_pending_restart_boot" in JS and "marker !== serverBootId.value" in JS)
check("78. «Позже» сохраняет маркер (закрытие панели не чистит localStorage)",
      "cbRestartLater = () => { cbDone.value = null; }" in JS)
check("57(restart). double-click guard сохранён", "if (restartInProgress.value) return;" in JS)
check("64b. старый процесс фиксируется ДО перезапуска (restartOldBootId в doRestart)",
      "restartOldBootId.value = serverBootId.value || ''" in JS)

import shutil; shutil.rmtree(tmp, ignore_errors=True)
print("\n" + "=" * 60)
print("Итого: PASS=%d FAIL=%d" % (_n["pass"], _n["fail"]))
sys.exit(1 if _n["fail"] else 0)
