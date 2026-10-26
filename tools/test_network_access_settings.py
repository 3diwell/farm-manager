# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
#  Alpha 2.837 — «Настройки → Система → Сеть и доступ»: секция обязана РАБОТАТЬ.
#
#  ЧТО ЗАКРЫВАЕТ. Приёмка владельца: «изменение порта работает; остальное видно,
#  но не работает; флажок доступа из локальной сети недоступен либо не реагирует».
#  Доказанный корень — ДВА дефекта сразу:
#    1) g_network отдавал причину ТЕКУЩЕГО решения (blocked_reason), которая при
#       выключенном тумблере всегда 'lan_disabled'. Причина, по которой ВКЛЮЧЕНИЕ
#       недоступно, вычислялась тут же (can_enable) и ВЫБРАСЫВАЛАСЬ. Поэтому ветки
#       объяснений в интерфейсе не могли сработать никогда;
#    2) панель с объяснением стояла под v-if="lanAccess", то есть показывалась только
#       когда сеть УЖЕ включена — ровно наоборот тому, когда она нужна.
#  Итог для владельца: погашенный флажок без единого слова о причине.
#
#  БЕЗОПАСНОСТЬ ПРОГОНА
#   * server.py НЕ импортируется: реальные функции берутся разбором AST и исполняются
#     в изоляции (ложно-зелёного exit 0 на замке одиночного экземпляра быть не может).
#   * Рабочие config.json, БД и DATA_DIR не открываются и не пишутся — ловушка open
#     краснит тест при первой же попытке.
#   * Ни одного subprocess: netsh/брандмауэр не вызывается — ловушка subprocess краснит.
#   * Принтерам ничего не отправляется, печати не запускаются, порт не меняется,
#     LAN в рабочей конфигурации не переключается.
#   * Браузерная часть работает на СИНТЕТИЧЕСКОМ backend (tools/_fm_ui_stage.py).
#
#  Запуск:  python tools/test_network_access_settings.py     (0 = всё пройдено)
# ============================================================================
import ast
import asyncio
import builtins
import io
import json
import os
import re
import sqlite3
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tools"))

FAILED = []
PASSED = [0]


def check(name, ok, extra=""):
    if ok:
        PASSED[0] += 1
        print("PASS — %s" % name)
    else:
        FAILED.append(name)
        print("FAIL — %s%s" % (name, (" [%s]" % extra) if extra else ""))


def sec(t):
    print("\n--- %s ---" % t)


SRC = io.open(os.path.join(REPO, "server.py"), encoding="utf-8", errors="surrogateescape").read()
SRC_AST = ast.parse(SRC)
APP = io.open(os.path.join(REPO, "web", "app.js"), encoding="utf-8", errors="surrogateescape").read()
HTML = io.open(os.path.join(REPO, "web", "index.html"), encoding="utf-8").read()
REG = io.open(os.path.join(REPO, "app", "config_backup", "settings_registry.py"), encoding="utf-8").read()
RP = io.open(os.path.join(REPO, "app", "route_policy_registry.py"), encoding="utf-8").read()
ORCH = io.open(os.path.join(REPO, "app", "project_orchestrator.py"), encoding="utf-8").read()

from app import lan_access_policy as L        # noqa: E402
from app import security_policy as SP         # noqa: E402


def fn_src(name):
    for n in ast.walk(SRC_AST):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            return ast.unparse(n)
    return ""


def net_section():
    """Разметка ТОЛЬКО секции «Сеть и доступ» (от её id до следующей группы настроек)."""
    i = HTML.find('id="fm-sec-net"')
    if i < 0:
        return ""
    i = HTML.rfind("<div", 0, i)
    j = HTML.find('id="fm-sec-storage"', i)
    return HTML[i:j if j > 0 else i + 9000]


NET = net_section()

print("=== Alpha 2.837: секция «Сеть и доступ» работает по серверному контракту ===")

# ════════════════════════════════════════════════════════════════════════════
sec("A. КОРЕНЬ ДЕФЕКТА зафиксирован (регрессия не вернётся молча)")

_g = fn_src("g_network")
check("A1. причина недоступности ВКЛЮЧЕНИЯ отдаётся отдельным полем enable_blocked_reason",
      "'enable_blocked_reason'" in _g and "enable_blocked_reason" in APP)
check("A2. результат can_enable больше не выбрасывается: 'why' попадает в ответ",
      re.search(r"'enable_blocked_reason':\s*\(?'' if ok_enable else why\)?", _g) is not None,
      _g[_g.find("enable_blocked_reason") - 4:][:80])
check("A3. blocked_reason СОХРАНЁН (прежний контракт интерфейса не сломан)",
      "'blocked_reason'" in _g and "lanBlockedReason" in APP)
check("A4. объяснение больше не спрятано под v-if=\"lanAccess\": есть панель причины",
      'v-if="lanBlockedText"' in NET and "lanBlockedText" in APP)
check("A5. панель причины стоит ДО панели включённого состояния",
      NET.find('v-if="lanBlockedText"') >= 0
      and NET.find('v-if="lanBlockedText"') < NET.find('v-if="lanAccess"'))

# ════════════════════════════════════════════════════════════════════════════
sec("B. Backend-контракт на РЕАЛЬНОМ коде в изоляции (синтетический config)")

DB = sqlite3.connect(":memory:", check_same_thread=False)
DB.row_factory = sqlite3.Row
DB.execute("CREATE TABLE users (id TEXT PRIMARY KEY, username TEXT, role TEXT, is_active INTEGER)")
DB.commit()

CFG = {}
WRITES = []
OPENED = []
SPAWNED = []
FIREWALL = []


class _Lock:
    def __enter__(self): return self
    def __exit__(self, *a): return False


class _Log:
    def _r(self, *a, **k): pass
    info = warning = error = debug = _r


class _Resp:
    def __init__(self, content=None, status_code=200):
        self.content = content
        self.status_code = status_code


class _Req:
    """Синтетический запрос: адрес берётся ТОЛЬКО из транспорта, как в проде."""
    def __init__(self, host):
        self.client = type("C", (), {"host": host})()


NS = {
    "_lan_policy": L, "log": _Log(), "lock_p": _Lock(), "conn_p": DB,
    "_read_config": lambda: dict(CFG),
    "_write_config": lambda c: (WRITES.append(dict(c)), CFG.clear(), CFG.update(c), True)[-1],
    "_exc_brief": lambda: "err", "_SECURITY_ENABLED": True, "_LAN_ACCESS_APPLIED": False,
    "JSONResponse": _Resp,
    "app": type("A", (), {"get": lambda *a, **k: (lambda f: f),
                          "post": lambda *a, **k: (lambda f: f)})(),
    "_require_system_admin": lambda req: None,
    "_security_policy": SP, "_peer_of": lambda req: (getattr(getattr(req, "client", None), "host", "") or ""),
    "_json_body": None, "Request": object,
    "_active_server_port": lambda: 8000,
    "_read_port_state": lambda: {"active": 8000, "pending": None, "previous": None},
    "_lan_ip": lambda: "192.168.7.7",
    "_prepare_port_change": lambda v: ("invalid", "not_int", None),
    # Ловушка брандмауэра: обработчик сети НЕ ИМЕЕТ ПРАВА его трогать. Если однажды тронет —
    # вызов будет записан и проверка B16c покраснит именно на этом, а не упадёт по NameError.
    "_ensure_firewall_rule": lambda port: FIREWALL.append(port),
}
for _p in ("_lan_access_enabled", "_enabled_admin_check", "_lan_effective_decision",
           "_require_server_machine", "g_network", "set_network"):
    exec(compile(fn_src(_p), "<server>", "exec"), NS)
g_network, set_network = NS["g_network"], NS["set_network"]

ADMIN_OK = (("admin", 1),)


def setup(cfg_lan=None, auth=True, admins=ADMIN_OK, applied=False):
    CFG.clear()
    if cfg_lan is not None:
        CFG["lan_access_enabled"] = cfg_lan
    WRITES[:] = []
    DB.execute("DELETE FROM users")
    for i, (role, active) in enumerate(admins):
        DB.execute("INSERT INTO users (id,username,role,is_active) VALUES (?,?,?,?)",
                   ("u%d" % i, "n%d" % i, role, active))
    DB.commit()
    NS["_SECURITY_ENABLED"] = auth
    NS["_LAN_ACCESS_APPLIED"] = applied


async def _mk(x):
    return x


def post(body, peer="127.0.0.1", auth=True, admins=ADMIN_OK, cfg_lan=False, applied=False):
    setup(cfg_lan, auth, admins, applied)
    NS["_json_body"] = lambda req: _mk(dict(body))
    r = asyncio.run(set_network(_Req(peer)))
    if isinstance(r, _Resp):
        return (r.status_code, r.content if isinstance(r.content, dict) else {})
    return (200, r if isinstance(r, dict) else {})


# ── ловушки: рабочие данные, брандмауэр и подпроцессы недоступны ────────────────
_real_open, _real_run, _real_popen = builtins.open, subprocess.run, subprocess.Popen


def _trap_open(file, *a, **k):
    p = str(file)
    OPENED.append(p)
    low = p.replace("\\", "/").lower()
    if low.endswith("config.json") or "/farmdata" in low or low.endswith(".db"):
        raise AssertionError("тест попытался открыть рабочие данные: %s" % p)
    return _real_open(file, *a, **k)


def _trap_proc(*a, **k):
    SPAWNED.append(str(a[:1]))
    raise AssertionError("тест попытался запустить подпроцесс: %s" % str(a[:1]))


builtins.open, subprocess.run, subprocess.Popen = _trap_open, _trap_proc, _trap_proc
try:
    # 5. Разрешённый локальный пользователь МОЖЕТ изменить значение.
    _r_on = post({"lan_access_enabled": True}, peer="127.0.0.1")
    check("B5. локальный system-admin при выполненных предпосылках включает сеть",
          _r_on[0] == 200 and _r_on[1].get("lan_access_enabled") is True
          and CFG.get("lan_access_enabled") is True and len(WRITES) == 1, str(_r_on))
    _r_off = post({"lan_access_enabled": False}, peer="127.0.0.1", cfg_lan=True)
    check("B5b. он же выключает сеть обратно",
          _r_off[0] == 200 and _r_off[1].get("lan_access_enabled") is False
          and CFG.get("lan_access_enabled") is False)

    # 6. Удалённый Client НЕ может изменить — и не оставляет следа.
    _r_rem = post({"lan_access_enabled": True}, peer="192.168.1.50")
    check("B6. удалённый клиент получает 403 server_machine_only",
          _r_rem[0] == 403 and _r_rem[1].get("reason") == "server_machine_only", str(_r_rem))
    check("B6b. отказ произошёл ДО записи конфигурации (следа не осталось)",
          not WRITES and CFG.get("lan_access_enabled") is False)
    _r_rem_off = post({"lan_access_enabled": False}, peer="10.0.0.9", cfg_lan=True)
    check("B6c. удалённый клиент не может и ВЫКЛЮЧИТЬ сеть",
          _r_rem_off[0] == 403 and CFG.get("lan_access_enabled") is True and not WRITES)
    check("B6d. ::1 и 127.x — это тот же компьютер, доступ сохраняется",
          post({"lan_access_enabled": True}, peer="::1")[0] == 200
          and post({"lan_access_enabled": True}, peer="127.0.0.5")[0] == 200)

    # 12. LAN и порт — независимые операции.
    _r_port = post({"server_port": "99999"}, peer="127.0.0.1", cfg_lan=None)
    check("B12. запрос порта уходит в ветку порта и НЕ трогает lan_access_enabled",
          _r_port[0] == 400 and "lan_access_enabled" not in CFG and not WRITES, str(_r_port))
    check("B12b. запрос LAN не содержит и не меняет порт",
          "server_port" not in json.dumps(post({"lan_access_enabled": True})[1])
          and "server_port" not in CFG)

    # 13/14. Смысл OFF и ON.
    setup(False, True, ADMIN_OK, applied=False)
    _st_off = g_network(_Req("127.0.0.1"))
    check("B13. OFF -> loopback: сервер остаётся только на этом компьютере",
          _st_off["current_bind_scope"] == "loopback" and _st_off["requested_enabled"] is False
          and _st_off["restart_required"] is False and "lan_url" not in _st_off)
    _r14 = post({"lan_access_enabled": True}, peer="127.0.0.1", applied=False)
    check("B14. ON планирует сеть на ПЕРЕЗАПУСК: restart_required, applied не меняется",
          _r14[1].get("restart_required") is True and _r14[1].get("applied") is False
          and NS["_LAN_ACCESS_APPLIED"] is False)
    check("B14b. горячего rebind нет: обработчик не трогает сокеты, uvicorn и применённый режим",
          not ({"uvicorn", "socket", "_bind_listener", "_lan_bind_host"}
               & set(re.findall(r"[A-Za-z_][A-Za-z_0-9]*", fn_src("set_network"))))
          and not re.search(r"_LAN_ACCESS_APPLIED\s*=", fn_src("set_network")))

    # Новые поля состояния.
    setup(False, False, (), applied=False)
    _st_blk = g_network(_Req("127.0.0.1"))
    check("B-NEW1. при выключенной авторизации причина ВКЛЮЧЕНИЯ названа честно",
          _st_blk["enable_blocked_reason"] == L.REASON_AUTH_REQUIRED
          and _st_blk["can_enable"] is False and _st_blk["blocked_reason"] == L.REASON_LAN_DISABLED,
          str(_st_blk))
    setup(False, True, (), applied=False)
    check("B-NEW2. авторизация есть, активного администратора нет -> своя причина",
          g_network(_Req("127.0.0.1"))["enable_blocked_reason"] == L.REASON_ADMIN_REQUIRED)
    setup(False, True, ADMIN_OK, applied=False)
    check("B-NEW3. предпосылки выполнены -> причина пуста, включение разрешено",
          g_network(_Req("127.0.0.1"))["enable_blocked_reason"] == ""
          and g_network(_Req("127.0.0.1"))["can_enable"] is True)
    check("B-NEW4. change_allowed отражает машинную границу",
          g_network(_Req("127.0.0.1"))["change_allowed"] is True
          and g_network(_Req("192.168.1.50"))["change_allowed"] is False)
    setup(True, True, ADMIN_OK, applied=True)
    _st_on = g_network(_Req("127.0.0.1"))
    check("B-NEW5. адрес в сети отдаётся ТОЛЬКО когда сеть фактически слушается",
          _st_on.get("lan_url") == "http://192.168.7.7:8000")
    setup(True, True, ADMIN_OK, applied=False)
    check("B-NEW5b. пока сеть не применена — адреса в ответе нет (ложного успеха не бывает)",
          "lan_url" not in g_network(_Req("127.0.0.1")))
    check("B-NEW6. наружу не уходят ни логины, ни пароли, ни пути, ни детали БД",
          not re.search(r"(?i)(password|passwd|hash|session|sqlite|traceback|[A-Za-z]:\\\\)",
                        json.dumps(_st_on) + json.dumps(_st_blk)))

    # 15/16/17. Рабочий рантайм, брандмауэр и принтеры не затронуты.
    check("B15. рабочие config/БД/DATA_DIR не открывались ни разу",
          not [p for p in OPENED if p.replace("\\", "/").lower().endswith("config.json")])
    check("B16. ни одного подпроцесса (netsh/брандмауэр не вызывался)", not SPAWNED)
    check("B16c. правило брандмауэра не вызывалось НИ РАЗУ за всю работу с сетью",
          not FIREWALL, str(FIREWALL))
finally:
    builtins.open, subprocess.run, subprocess.Popen = _real_open, _real_run, _real_popen

_set_src = fn_src("set_network")
check("B16b. в обработчике сети нет ни netsh, ни правила брандмауэра",
      "netsh" not in _set_src and "_ensure_firewall_rule" not in _set_src
      and "_ensure_firewall_rule" not in fn_src("g_network"))
check("B17. связь с принтерами не затрагивается (ни отправки файла, ни команд, ни очереди)",
      not ({"_send_file_to_printer", "_printer_command", "_do_project2_file_print",
            "printQueue", "_send_jobs"} & set(re.findall(r"[A-Za-z_][A-Za-z_0-9]*", _set_src))))

# 26. Границы маршрута сохранены и усилены.
_reg_line = [ln for ln in RP.split("\n") if "'/api/network'" in ln and "'POST'" in ln]
check("B26. POST /api/network остаётся SYSTEM_ADMIN в реестре маршрутов",
      len(_reg_line) == 1 and "SYSTEM_ADMIN" in _reg_line[0], str(_reg_line))
check("B26b. обе границы стоят в коде: system-admin И машина сервера",
      "_require_system_admin" in _set_src and "_require_server_machine" in _set_src
      and _set_src.find("_require_system_admin") < _set_src.find("_require_server_machine"))
check("B26c. заголовки прокси в решении не участвуют (адрес только из транспорта)",
      "x-forwarded" not in _set_src.lower() and "headers" not in _set_src.lower())

# 27. Резервное копирование настройки — по существующему контракту.
check("B27. lan_access_enabled зарегистрирован в реестре настроек резервной копии",
      "lan_access_enabled" in REG and "RB_RESTORE_WITH_WARNING" in REG)

# 28/29/30. Предохранители не тронуты.
check("B28. DISPATCH_ENABLED = False", re.search(r"^DISPATCH_ENABLED = False$", ORCH, re.M) is not None)
check("B29. TRANSPORT_ENABLED = False", re.search(r"^TRANSPORT_ENABLED = False$", ORCH, re.M) is not None)
check("B30. удаление файлов принтера остаётся выключенным по умолчанию",
      re.search(r"PRINTER_FILE_DELETE_ENABLED_DEFAULT\s*=\s*False",
                io.open(os.path.join(REPO, "app", "printer_files", "security.py"),
                        encoding="utf-8").read()) is not None)

# ════════════════════════════════════════════════════════════════════════════
sec("C. Frontend-инварианты секции (статически)")

check("C3. OFF читается однозначно: бейдж «Только этот компьютер»",
      "'Только этот компьютер':'This computer only'" in NET)
check("C4. ON читается однозначно: бейдж «Доступен в локальной сети»",
      "'Доступен в локальной сети':'Available on the network'" in NET)
check("C10. статус «Требуется перезапуск» виден прямо в строке настройки",
      re.search(r'v-if="lanRestartRequired">\{\{ lang===\'ru\'\?\'Требуется перезапуск\'', NET) is not None)
check("C22. статус «Недоступно в удалённом клиенте» существует",
      "'Недоступно в удалённом клиенте':'Unavailable in a remote client'" in NET
      and 'v-if="!lanChangeAllowed"' in NET)
check("C7. save-запрос ровно один на действие (единственный POST /api/network в setLanAccess)",
      len(re.findall(r"fetch\('/api/network', \{ method: 'POST'", APP)) == 1)
check("C8. двойной клик не создаёт второй запрос (busy-guard первым оператором)",
      re.search(r"const setLanAccess = async \(v\) => \{\s*if \(lanBusy\.value\) return;", APP) is not None)
check("C9. ошибка backend возвращает серверное состояние И показывает текст ошибки",
      "catch (e) { lanAccess.value = prev; await loadNetworkInfo(); }" in APP
      and "lanError.value = saved ? '' : lanErrorText(why)" in APP
      and 'v-if="lanError"' in NET)
check("C11. строка порта осталась отдельной и рабочей",
      "openPortDialog()" in NET and "'Порт сервера':'Server port'" in NET
      and "server_port: portInput.value" in APP)
def _js_slice(name):
    """Тело функции app.js от объявления до следующего объявления того же уровня."""
    i = APP.find("const %s =" % name)
    if i < 0:
        return ""
    j = APP.find("\n    const ", i + 1)
    return APP[i:j if j > 0 else i + 2000]


check("C12. LAN и порт не смешиваются в одну операцию",
      "server_port" not in _js_slice("setLanAccess")
      and "lan_access_enabled" not in _js_slice("applyPort")
      and len(_js_slice("setLanAccess")) > 200 and len(_js_slice("applyPort")) > 200)
check("C-NEW1. флажок гаснет и в удалённом клиенте (машинная граница в составном :disabled)",
      ':disabled="lanBusy || !lanChangeAllowed || (!lanAccess && !lanCanEnable)"' in NET)
check("C-NEW2. setLanAccess не шлёт запрос без права менять машинную настройку",
      "if (!lanChangeAllowed.value) { await loadNetworkInfo(); return; }" in APP)
check("C-NEW3. причина берётся из enable_blocked_reason, а не из blocked_reason",
      "lanEnableBlocked.value = j.enable_blocked_reason || ''" in APP
      and "const r = lanEnableBlocked.value;" in APP)
check("C-NEW4. адрес в сети показывается только по данным сервера (не собирается в браузере)",
      "lanUrl.value = lanApplied.value ? String(j.lan_url || '') : ''" in APP
      and "location.host" not in APP[APP.index("const _applyNet"):APP.index("const _applyNet") + 1200])
check("C-NEW5. про брандмауэр сказано честно: автоматическая настройка не обещана",
      "разрешите входящий порт в брандмауэре Windows вручную" in NET
      and "программа этого не гарантирует" in NET)
check("C-NEW6. новые имена экспортированы из setup (иначе шаблон их не увидит)",
      "lanChangeAllowed, lanBlockedText, lanError, lanUrl" in APP)
check("C18. RU-подписи секции на месте",
      "'Доступ из локальной сети':'Local network access'" in NET
      and "'Сеть и доступ':'Network & access'" in NET)
check("C19. EN-подписи секции непустые (у каждой RU-строки есть перевод)",
      all(e.strip() for _r, e in re.findall(r"lang==='ru'\?'([^']*)':'([^']*)'", NET)))
check("C21. Desktop-оболочка открывает ТОЛЬКО loopback — значит право менять у неё есть",
      'return ["http://127.0.0.1:%d" % int(self.cfg["port"])]'
      in io.open(os.path.join(REPO, "app", "desktop_shell.py"), encoding="utf-8").read())
check("C20. Browser на компьютере-сервере тоже loopback (тот же список хостов, что у порта)",
      "['localhost', '127.0.0.1', '::1', '[::1]'].includes(location.hostname)" in APP
      and "lanChangeAllowedSrv.value && portCanChange.value" in APP)


# ════════════════════════════════════════════════════════════════════════════
sec("D. РЕАЛЬНЫЙ БРАУЗЕР: секция монтируется, читается и работает")

import _fm_ui_stage as stage  # noqa: E402

BASE_NET = {"lan_access_enabled": False, "requested_enabled": False, "applied": False,
            "restart_required": False, "port": 8000, "current_bind_scope": "loopback",
            "auth_enabled": False, "enabled_admin_present": False,
            "can_enable": False, "blocked_reason": "lan_disabled",
            "enable_blocked_reason": "auth_required", "change_allowed": True}


def net(**over):
    d = dict(BASE_NET)
    d.update(over)
    return d


PROBE = r"""
var NET='#fm-sec-net';
function q(s){ return document.querySelector(NET+' '+s); }
function txts(s){ return [].slice.call(document.querySelectorAll(NET+' '+s))
  .map(function(e){ return (e.textContent||'').replace(/\s+/g,' ').trim(); }).filter(function(t){return t;}); }
function spy(mode){
  window.__posts=[]; var of=window.fetch;
  window.fetch=function(u,o){
    var url=String((u&&u.url)||u||''), m=(o&&o.method)||'GET';
    if(url.indexOf('/api/network')>=0 && m==='POST'){
      var b={}; try{ b=JSON.parse((o&&o.body)||'{}'); }catch(e){}
      window.__posts.push(b);
      if(mode==='error') return Promise.resolve(new Response(
        JSON.stringify({status:'error',reason:'auth_required'}),
        {status:409,headers:{'Content-Type':'application/json'}}));
      //  13.10.2026: ответ НАСТОЯЩЕГО сервера на сохранение — ровно четыре поля (server.py, POST /api/network).
      //  Прежде окно ЗАМЕНЯЛО им состояние, и флажок блокировался до повторного открытия настроек.
      if(mode==='minimal') return Promise.resolve(new Response(JSON.stringify({status:'ok',
        lan_access_enabled:!!b.lan_access_enabled, applied:false, restart_required:!!b.lan_access_enabled, port:8000}),
        {status:200,headers:{'Content-Type':'application/json'}}));
      return Promise.resolve(new Response(JSON.stringify({status:'ok',
        lan_access_enabled:!!b.lan_access_enabled, applied:false,
        restart_required:!!b.lan_access_enabled, port:8000, requested_enabled:!!b.lan_access_enabled,
        current_bind_scope:'loopback', auth_enabled:true, enabled_admin_present:true,
        can_enable:true, blocked_reason:'', enable_blocked_reason:'', change_allowed:true}),
        {status:200,headers:{'Content-Type':'application/json'}}));
    }
    return of.apply(this,arguments); };
}
function snap(){
  var s=document.querySelector(NET), b=q('input.fm-chk-in'), r=s?s.getBoundingClientRect():null;
  var br=b?b.getBoundingClientRect():null;
  return { mounted: !!s, secH: r?Math.round(r.height):0, secW: r?Math.round(r.width):0,
           hasBox: !!b, boxVisible: !!(br && br.width>0 && br.height>0),
           checked: b?!!b.checked:null, disabled: b?!!b.disabled:null,
           badges: txts('.fm-bdg'), panels: txts('.fm-pnl'),
           labels: txts('.fm-set-lbl'), portBtn: !!q('.fm-set-ctl button'),
           posts: window.__posts||[], lang: uiLang() };
}
return new Promise(function(res){ openStage('system', function(){
  var mode='%MODE%';
  spy(mode==='error'?'error':(mode==='minimal'?'minimal':'ok'));
  setTimeout(function(){
    if(mode==='click' || mode==='double' || mode==='error' || mode==='blocked' || mode==='minimal'){
      var b=q('input.fm-chk-in');
      if(b){ b.click(); if(mode==='double'){ b.click(); } }
    }
    setTimeout(function(){ dump(snap()); res(true); }, %WAIT%);
  }, 260);
}, '%LANG%'); });
"""

ZOOM_PROBE = r"""
return new Promise(function(res){ openStage('system', function(){
  var out={steps:[]};
  function step(dsf, cb){
    setViewport(1440, 900, dsf, function(){
      var s=document.querySelector('#fm-sec-net'), b=document.querySelector('#fm-sec-net input.fm-chk-in');
      var r=s?s.getBoundingClientRect():null, br=b?b.getBoundingClientRect():null;
      out.steps.push({dsf:dsf, mounted:!!s, h:r?Math.round(r.height):0,
                      boxVisible: !!(br && br.width>0 && br.height>0),
                      inside: !!(r && br && br.top>=r.top-1 && br.bottom<=r.bottom+1),
                      overflow: !!(s && s.scrollWidth > s.clientWidth+1)});
      cb();
    });
  }
  step(1, function(){ step(1.5, function(){ step(2, function(){ dump(out); res(true); }); }); });
}); });
"""


def run_case(label, api, mode="read", lang="ru", wait=700, size=(1440, 900)):
    stage.set_api({"/api/network": api})
    js = PROBE.replace("%MODE%", mode).replace("%LANG%", lang).replace("%WAIT%", str(wait))
    res = stage.run(js, window_size=size, settle_ms=1500, timeout=420.0)
    if res is None:
        check("D[%s]. сценарий выполнен в браузере" % label, False, str(stage.last_diag())[:200])
        return None
    probs = stage.page_problems(res)
    check("D[%s]. 0 ошибок консоли и 0 предупреждений Vue" % label, not probs, "; ".join(probs[:2]))
    return res


STATIC_ONLY = "--static" in sys.argv
if STATIC_ONLY:
    # Режим ТОЛЬКО для tools/test_network_repo_mutation_proof.py: 18 порч × 9 запусков
    # браузера — это часы. Пропуск здесь ГРОМКИЙ и осознанный; в полном наборе флаг не
    # передаётся никогда, и раздел D обязателен.
    print("!!! РЕЖИМ MUTATION PROOF (--static): браузерная часть D НЕ выполняется.")
    print("!!! Полный прогон без этого флага обязателен и проверяет 25 браузерных пунктов.")
elif not stage.engine_ready():
    check("D0. движок браузера доступен (пропуск ЗАПРЕЩЁН — это красный)", False,
          "Edge/Node не найдены")
else:
    check("D0. движок браузера доступен", True)

    # ── 1. Реальная ситуация владельца: сеть выключена, авторизация выключена ──
    r = run_case("owner-off", net(), lang="ru")
    if r:
        check("D1. секция «Сеть и доступ» смонтирована и имеет реальную геометрию",
              r["mounted"] and r["secH"] > 40 and r["secW"] > 200, str(r)[:160])
        check("D2. флажок присутствует и виден", r["hasBox"] and r["boxVisible"])
        check("D3. OFF отображается ПУСТЫМ флажком + бейдж «Только этот компьютер»",
              r["checked"] is False and any("Только этот компьютер" in b for b in r["badges"]),
              str(r["badges"]))
        check("D3b. недоступность ОБЪЯСНЕНА прямо в секции (корень дефекта закрыт)",
              any("администратор" in p and "авторизаци" in p for p in r["panels"]),
              str(r["panels"])[:220])
        check("D3c. флажок при этом честно погашен, а не «просто не реагирует молча»",
              r["disabled"] is True)
        check("D18. интерфейс на русском", r["lang"] == "ru")

    # ── 2. Предпосылки выполнены: флажок активен, один клик = один запрос ──
    r = run_case("enable-click", net(auth_enabled=True, enabled_admin_present=True,
                                     can_enable=True, enable_blocked_reason=""),
                 mode="click")
    if r:
        check("D5. при выполненных предпосылках флажок активен", r["disabled"] is False)
        check("D7. одно действие = РОВНО один POST /api/network со строгим boolean",
              len(r["posts"]) == 1 and r["posts"][0] == {"lan_access_enabled": True}, str(r["posts"]))
        check("D5b. после успешного сохранения флажок стоит и объяснения-блокировки нет",
              r["checked"] is True
              and not any("недоступно" in p.lower() for p in r["panels"]), str(r["panels"])[:200])

    # ── 2б. 13.10.2026: настоящий (неполный) ответ сервера на сохранение — включение и выключение ──
    r = run_case("enable-real-post", net(auth_enabled=True, enabled_admin_present=True,
                                         can_enable=True, enable_blocked_reason=""), mode="minimal")
    if r:
        check("D5c. настоящий ответ сохранения: флажок включён, НЕ заблокирован, объяснения-блокировки нет",
              r["checked"] is True and r["disabled"] is False
              and not any("недоступно" in p.lower() for p in r["panels"]), str((r["checked"], r["disabled"], r["panels"]))[:200])
    r = run_case("disable-real-post", net(auth_enabled=True, enabled_admin_present=True, can_enable=True,
                                          enable_blocked_reason="", lan_access_enabled=True, requested_enabled=True),
                 mode="minimal")
    if r:
        check("D5d. ...и выключение: флажок снят и по-прежнему доступен (можно включить обратно)",
              r["checked"] is False and r["disabled"] is False, str((r["checked"], r["disabled"], r["panels"]))[:200])

    # ── 3. Двойной клик ──
    r = run_case("double-click", net(auth_enabled=True, enabled_admin_present=True,
                                     can_enable=True, enable_blocked_reason=""),
                 mode="double")
    if r:
        check("D8. двойной клик всё равно даёт один запрос (busy-guard)",
              len(r["posts"]) == 1, str(r["posts"]))

    # ── 4. Ошибка backend ──
    r = run_case("backend-error", net(auth_enabled=True, enabled_admin_present=True,
                                      can_enable=True, enable_blocked_reason=""),
                 mode="error", wait=1100)
    if r:
        check("D9. ошибка backend откатывает флажок к серверному состоянию",
              r["checked"] is False, str(r)[:160])
        check("D9b. ошибка ПОКАЗАНА пользователю (ложного успеха нет)",
              any(("не удалось" in p.lower()) or ("администратор" in p.lower()) for p in r["panels"]),
              str(r["panels"])[:220])

    # ── 5. Сеть включена и применена ──
    r = run_case("lan-on", net(lan_access_enabled=True, requested_enabled=True, applied=True,
                               current_bind_scope="network", auth_enabled=True,
                               enabled_admin_present=True, can_enable=True,
                               blocked_reason="", enable_blocked_reason="",
                               lan_url="http://192.168.7.7:8000"))
    if r:
        check("D4. ON отображается С ГАЛОЧКОЙ + бейдж «Доступен в локальной сети»",
              r["checked"] is True and any("Доступен в локальной сети" in b for b in r["badges"]),
              str(r["badges"]))
        check("D4b. адрес для других компьютеров показан из ответа сервера",
              any("192.168.7.7:8000" in p for p in r["panels"]), str(r["panels"])[:220])
        check("D16. про брандмауэр сказано, но автонастройка не обещана",
              any("брандмауэр" in p for p in r["panels"])
              and not any("автоматическ" in p and "брандмауэр" in p for p in r["panels"]))

    # ── 6. Требуется перезапуск ──
    r = run_case("restart-required", net(lan_access_enabled=True, requested_enabled=True,
                                         applied=False, restart_required=True,
                                         auth_enabled=True, enabled_admin_present=True,
                                         can_enable=True, blocked_reason="",
                                         enable_blocked_reason=""))
    if r:
        check("D10. «Требуется перезапуск» показано как статус и как панель с кнопкой",
              any("Требуется перезапуск" in b for b in r["badges"])
              and any("перезапуск" in p.lower() for p in r["panels"]), str(r["badges"]))

    # ── 7. Удалённый клиент ──
    r = run_case("remote-client", net(auth_enabled=True, enabled_admin_present=True,
                                      can_enable=True, enable_blocked_reason="",
                                      change_allowed=False), mode="blocked")
    if r:
        check("D22. в удалённом клиенте флажок недоступен и это НАПИСАНО",
              r["disabled"] is True
              and any("Недоступно в удалённом клиенте" in b for b in r["badges"]),
              str(r["badges"]))
        check("D22b. удалённый клиент не отправляет запрос вовсе", len(r["posts"]) == 0)
        check("D11. строка порта при этом на месте (порт и LAN независимы)",
              any("Порт сервера" in l for l in r["labels"]), str(r["labels"])[:200])

    # ── 8. Английский интерфейс ──
    r = run_case("en", net(), lang="en")
    if r:
        check("D19. EN: секция и статус переведены",
              r["lang"] == "en" and any("This computer only" in b for b in r["badges"]),
              str(r["badges"]))
        check("D19b. EN: причина недоступности тоже переведена",
              any("administrator" in p.lower() for p in r["panels"]), str(r["panels"])[:200])

    # ── 9. Увеличение 100–200 % ──
    stage.set_api({"/api/network": net()})
    rz = stage.run(ZOOM_PROBE, window_size=(1440, 900), settle_ms=1500, timeout=420.0)
    if rz is None:
        check("D23. увеличение 100–200 % проверено", False, str(stage.last_diag())[:200])
    else:
        st = rz.get("steps") or []
        check("D23. при 100/150/200 % секция цела, флажок виден и не выходит за карточку",
              len(st) == 3 and all(s["mounted"] and s["h"] > 40 and s["boxVisible"]
                                   and s["inside"] and not s["overflow"] for s in st), str(st))
        check("D24-25. при увеличении 0 ошибок консоли и 0 предупреждений Vue",
              not stage.page_problems(rz), "; ".join(stage.page_problems(rz)[:2]))

    stage.set_api(None)
    stage.stop()

# ════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 78)
print("ИТОГО: PASS=%d FAIL=%d" % (PASSED[0], len(FAILED)))
for f in FAILED:
    print("  ПРОВАЛ: %s" % f)
sys.exit(1 if FAILED else 0)
