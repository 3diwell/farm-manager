# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
#  R-125 / R-128 — резервная копия ВСЕХ модулей на НАСТОЯЩЕМ процессе программы, полностью офлайн.
#
#  ЗАЧЕМ. Наборы на провайдерах работают без сервера, а блокировку полной копии модулем
#  («Оформление», 12.09.2026) поймал только настоящий сервер. Здесь программа поднимается
#  по-настоящему (python server.py в изолированном режиме app/e2e_isolation: своя временная папка
#  данных, свой config, свободный порт, свой замок одиночного экземпляра, без трея, браузера,
#  обнаружения и принтеров; модули ВКЛЮЧЕНЫ) — два экземпляра по очереди:
#    A: все модули проекта (как их ставит установщик — папками в DATA_DIR\modules), заказ
#       «Расчёта заказа», склад с кодом QR, меткой NFC и подготовленными наклейками; «Расчёт
#       заказа» отключён и экземпляр перезапущен. Экспорт = 200 (раньше «Видеостена» давала 409),
#       в копии заказ отключённого модуля (enabled=false), коды QR/NFC и наклейки. Затем
#       включается защита входом и делается вторая копия — с security_enabled=1.
#    B: чистая папка без пользователей. Первая копия восстанавливается целиком (заказ, коды,
#       метки, номер сервера склада — телефон узнаёт уже принятую метку). Вторая копия защиту НЕ
#       включает (план: security_held_no_admin), и после перезапуска вход по-прежнему открыт.
#    C: свой заказ с тем же номером, что в копии. План блокирует «Расчёт заказа» и называет его;
#       «Восстановить без этого модуля» (exclude_modules) восстанавливает остальное, свои заказы
#       C не трогаются.
#
#  БЕЗОПАСНОСТЬ ПРОГОНА: рабочие DATA_DIR/config/БД/порт/замок не используются (LOCALAPPDATA
#  дочерних процессов тоже подменён на временную папку); принтерам ничего не отправляется, наружу
#  программа не ходит; временная папка удаляется в конце.
#
#  Запуск:  PYTHONIOENCODING=utf-8 python tools/test_config_backup_all_modules_e2e.py   (0 = пройдено)
# ============================================================================
import base64
import json
import os
import re
import secrets
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.dont_write_bytecode = True
from app import e2e_isolation as ISO  # noqa: E402
from app.config_backup import serializer  # noqa: E402

SRC = open(os.path.join(REPO, "server.py"), encoding="utf-8").read()
APP_VERSION = re.search(r'^APP_VERSION\s*=\s*"([^"]+)"', SRC, re.M).group(1)
PROD = os.path.join(os.environ.get("LOCALAPPDATA", ""), "3DIWELL")
_n = {"pass": 0, "fail": 0}
fails = []


def check(name, ok, extra=""):
    ok = bool(ok)
    _n["pass" if ok else "fail"] += 1
    print(("PASS" if ok else "FAIL") + " — " + name + (("  :: %s" % (extra,))[:700] if (not ok and extra != "") else ""),
          flush=True)
    if not ok:
        fails.append(name)
    return ok


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def listening(port):
    out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True,
                         creationflags=0x08000000).stdout
    return any(len(l.split()) >= 5 and l.split()[3] == "LISTENING" and l.split()[1] == "127.0.0.1:%d" % port
               for l in out.splitlines())


def wait(fn, t):
    end = time.monotonic() + t
    while time.monotonic() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.5)
    return None


BASE = tempfile.mkdtemp(prefix="fm_e2e_bkpall_")
assert not os.path.normcase(BASE).startswith(os.path.normcase(PROD)), "временная папка внутри рабочей!"
LAD = os.path.join(BASE, "localappdata")          # подменённый LOCALAPPDATA дочерних процессов
os.makedirs(LAD)


def copy_modules(dst):
    """Все модули проекта — папками в DATA_DIR\\modules, как их раскладывает установщик zip.
    В открытой копии части модулей может не быть: берётся то, что лежит в modules/."""
    ids = []
    base = os.path.join(REPO, "modules")
    for name in sorted(os.listdir(base)):
        src = os.path.join(base, name)
        mj = os.path.join(src, "module.json")
        if not os.path.isfile(mj):
            continue
        mid = str(json.load(open(mj, encoding="utf-8"))["id"])
        shutil.copytree(src, os.path.join(dst, mid),
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.db", "*.db-wal", "*.db-shm", "*.zip"))
        ids.append(mid)
    return sorted(ids)


class Instance(object):
    def __init__(self, tag):
        self.tag = tag
        self.root = os.path.join(BASE, tag)
        os.makedirs(self.root)
        self.port = free_port()
        self.token = "BKP_E2E_%s_%s" % (tag, secrets.token_hex(8))
        with open(os.path.join(self.root, ISO.MARKER_NAME), "w", encoding="utf-8") as f:
            json.dump({"token": self.token, "sentinel": "BKP_E2E_R125"}, f)
        self.cfg = os.path.join(self.root, "config.json")
        with open(self.cfg, "w", encoding="utf-8") as f:
            json.dump({"server_port": self.port}, f)
        self.mods = copy_modules(os.path.join(self.root, "modules"))
        self.env = dict(os.environ)
        self.env.update({ISO.ENV_SENTINEL: self.token, ISO.ENV_INSTANCE: "bkp-" + tag, ISO.ENV_DATA_DIR: self.root,
                         ISO.ENV_CONFIG: self.cfg, ISO.ENV_MUTEX: "Local\\3DIWELL_FM_E2E_BKP_" + secrets.token_hex(6),
                         ISO.ENV_PORT: str(self.port), ISO.ENV_NO_TRAY: "1", ISO.ENV_NO_BROWSER: "1",
                         ISO.ENV_NO_DISCOVERY: "1", ISO.ENV_NO_PRINTERS: "1", ISO.ENV_NO_MODULES: "0",
                         "PYTHONDONTWRITEBYTECODE": "1", "LOCALAPPDATA": LAD})
        self.proc = None
        self.cookie = ""

    def http(self, method, path, body=None, raw=None):
        data = json.dumps(body).encode("utf-8") if body is not None else (raw if raw is not None
                                                                         else (b"" if method != "GET" else None))
        req = urllib.request.Request("http://127.0.0.1:%d%s" % (self.port, path), data=data, method=method)
        if body is not None:
            req.add_header("Content-Type", "application/json")
        if self.cookie:
            req.add_header("Cookie", self.cookie)
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                st, payload, hdrs = r.status, r.read(), r.headers
        except urllib.error.HTTPError as e:
            st, payload, hdrs = e.code, e.read(), e.headers
        except Exception as e:
            return 0, {"_error": type(e).__name__}, {}
        if "application/json" in str(hdrs.get("Content-Type") or ""):
            try:
                return st, json.loads(payload.decode("utf-8") or "{}"), hdrs
            except Exception:
                return st, {}, hdrs
        return st, payload, hdrs

    def js(self, method, path, body=None):
        st, payload, _h = self.http(method, path, body)
        return st, (payload if isinstance(payload, dict) else {})

    def start(self):
        self.proc = subprocess.Popen([sys.executable, os.path.join(REPO, "server.py"), ISO.FLAG, "--desktop-start",
                                      "--no-browser"], cwd=REPO, env=self.env, stdin=subprocess.DEVNULL,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     creationflags=(0x00000008 | 0x00000200))
        return bool(wait(lambda: (self.js("GET", "/version")[1].get("version") == APP_VERSION)
                         if listening(self.port) else None, 180))

    def stop(self):
        with open(os.path.join(self.root, "stop.request"), "w", encoding="utf-8") as f:
            f.write(self.token)
        gone = wait(lambda: not listening(self.port), 60)
        if not gone and self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()               # только СВОЙ процесс; рабочую программу не трогаем
            gone = wait(lambda: not listening(self.port), 20)
        try:
            os.unlink(os.path.join(self.root, "stop.request"))
        except Exception:
            pass
        return bool(gone)

    def modules(self):
        return {m["id"]: m for m in self.js("GET", "/api/modules")[1].get("modules", [])}

    def db(self, name, sql, args=()):
        c = sqlite3.connect("file:%s?mode=ro" % os.path.join(self.root, name).replace("\\", "/"), uri=True)
        c.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in c.execute(sql, args).fetchall()]
        finally:
            c.close()


def decode(blob):
    return serializer.decode_payload(blob).as_dict()


def mod_entry(payload, mid):
    return next((m for m in (payload.get("module_data") or {}).get("modules") or [] if m.get("module_id") == mid), {})


def restore(inst, blob, mode, exclude=None):
    body = {"mode": mode, "backup_b64": base64.b64encode(blob).decode("ascii")}
    if exclude is not None:
        body["exclude_modules"] = list(exclude)
    return inst.js("POST", "/api/config-backup/restore", body)


def mobile(sid, n, **extra):
    m = {"protocol": 1, "server_id": sid, "request_id": "bkp-e2e-request-%06d" % n}
    m.update(extra)
    return m


A = B = C = None
try:
    # ═════════════════════════════ ЭКЗЕМПЛЯР A ═════════════════════════════
    A = Instance("A")
    print("изолированный экземпляр A: порт %d, модули %s" % (A.port, A.mods))
    check("A1. экземпляр A поднялся (своя папка, порт, замок; модули включены)", A.start())
    mods = A.modules()
    check("A2. все модули проекта загружены", all(mods.get(m, {}).get("state") == "loaded" for m in A.mods)
          and {"inventory", "cost"} <= set(A.mods), {k: v.get("state") for k, v in mods.items()})

    st, filament = A.js("GET", "/api/mod/inventory/filament")
    srv_id = ((filament.get("mobile") or {}).get("server_id")) or ""
    st, loc = A.js("POST", "/api/mod/inventory/location", {"name": "Стеллаж E2E"})
    lid = loc.get("id", "")
    st, qr = A.js("POST", "/api/mod/inventory/spool", {
        "mobile": mobile(srv_id, 1, code="4601234567890", code_kind="product"), "location": lid,
        "weight_total_g": 1000, "label": "E2E",
        "filament": {"vendor_name": "E2E Vendor", "material": "PLA", "color_name": "Blue", "diameter": 1.75}})
    fid = qr.get("filament_id", "")
    check("A3. склад: катушка принята по коду QR с телефона (мобильный протокол)",
          bool(srv_id) and bool(lid) and qr.get("ok") is True and bool(fid), qr)
    st, nfc = A.js("POST", "/api/mod/inventory/spool", {
        "mobile": mobile(srv_id, 2, protocol=4, operation="nfc_receipt", nfc_uid="A1B2C3D4"), "location": lid,
        "weight_total_g": 1000, "filament_id": fid})
    check("A4. склад: катушка принята по метке NFC", nfc.get("ok") is True and nfc.get("nfc_uid") == "A1B2C3D4", nfc)
    st, lab = A.js("POST", "/api/mod/inventory/spool", {
        "mobile": mobile(srv_id, 3, protocol=3, operation="prepare_labels"), "quantity": 2,
        "weight_total_g": 1000, "name": "Партия E2E", "label": "E2E", "filament_id": fid})
    check("A5. склад: подготовлены 2 наклейки", lab.get("ok") is True and (lab.get("counts") or {}).get("total") == 2, lab)

    st, cset = A.js("POST", "/api/mod/cost/settings", {"tax_percent": 20})
    st, saved = A.js("POST", "/api/mod/cost/calculations", {"order": {"title": "Заказ E2E", "items": []}})
    order_no = saved.get("order_number", "")
    check("A6. «Расчёт заказа»: настройки и заказ сохранены", saved.get("ok") is True and bool(order_no), saved)

    st, dis = A.js("POST", "/api/modules/cost/disable")
    check("A7. «Расчёт заказа» отключён", st == 200 and dis.get("status") == "ok", (st, dis))
    check("A8. A остановлен штатно", A.stop())
    check("A9. A поднялся снова", A.start())
    check("A10. после перезапуска «Расчёт заказа» отключён (backend не загружен)",
          A.modules().get("cost", {}).get("state") == "disabled", A.modules().get("cost"))

    st, blob1, _h = A.http("POST", "/api/config-backup/export", {"protection_mode": "none"})
    check("A11. КРИТИЧНО: полный экспорт со ВСЕМИ модулями = 200 (раньше «Видеостена» давала 409)",
          st == 200 and isinstance(blob1, bytes) and len(blob1) > 0, (st, blob1 if not isinstance(blob1, bytes) else ""))
    p1 = decode(blob1) if st == 200 else {}
    ids1 = sorted(m.get("module_id") for m in (p1.get("module_data") or {}).get("modules") or [])
    check("A12. в копии все установленные модули; «Видеостена» — без пользовательских данных",
          ids1 == A.mods and (("camera_wall" not in A.mods)
                              or mod_entry(p1, "camera_wall").get("data_class") == "no_persistent_user_data"),
          ids1)
    ce = mod_entry(p1, "cost")
    orders1 = (((ce.get("domain_data") or {}).get("tables") or {}).get("orders") or [])
    check("A13. КРИТИЧНО: отключённый модуль в копии (enabled=false) вместе с заказом",
          ce.get("enabled") is False and ce.get("backup_schema_version") == 2
          and [o.get("order_number") for o in orders1] == [order_no], (ce.get("enabled"), orders1))
    ie = mod_entry(p1, "inventory")
    it = (ie.get("domain_data") or {}).get("tables") or {}
    check("A14. склад в копии: коды QR и NFC, метка NFC, наклейки, номер сервера",
          sorted(r["code"] for r in it.get("inv_mobile_codes") or []) == ["4601234567890", "nfc:bambu:A1B2C3D4"]
          and [r["uid"] for r in it.get("inv_mobile_nfc") or []] == ["A1B2C3D4"]
          and len(it.get("inv_mobile_labels") or []) == 2
          and (ie.get("settings") or {}).get("mobile_server_id") == srv_id, {k: len(v) for k, v in it.items()})

    st, setup, hdrs = A.http("POST", "/api/auth/setup", {"username": "e2eadmin", "password": "e2e-secret-1"})
    m = re.search(r"fm_session=([^;]+)", str(hdrs.get("Set-Cookie") or "")) if hdrs else None
    A.cookie = ("fm_session=" + m.group(1)) if m else ""
    check("A15. на A включена защита входом (создан администратор)",
          st == 200 and isinstance(setup, dict) and setup.get("ok") is True and bool(A.cookie), (st, setup))
    st, blob2, _h = A.http("POST", "/api/config-backup/export", {"protection_mode": "none"})
    p2 = decode(blob2) if st == 200 and isinstance(blob2, bytes) else {}
    check("A16. вторая копия (с входом администратора) — с включённой защитой",
          st == 200 and (p2.get("core") or {}).get("values", {}).get("security_enabled") is True, st)
    check("A17. A остановлен", A.stop())

    # ═════════════════════════════ ЭКЗЕМПЛЯР B ═════════════════════════════
    B = Instance("B")
    print("изолированный экземпляр B (чистая папка): порт %d" % B.port)
    check("B1. экземпляр B поднялся на чистой папке", B.start())
    check("B2. на B загружены все модули", all(B.modules().get(mm, {}).get("state") == "loaded" for mm in B.mods))
    st, plan = restore(B, blob1, "plan")
    pl = plan.get("plan") or {}
    pmods = {m.get("module_id"): m for m in (pl.get("module_data") or {}).get("modules") or []}
    check("B3. план первой копии: не заблокирован, заказ и склад добавляются",
          st == 200 and not (pl.get("module_data") or {}).get("blocked")
          and (pmods.get("cost") or {}).get("counts", {}).get("added", 0) >= 1
          and (pmods.get("inventory") or {}).get("counts", {}).get("added", 0) >= 5, (st, plan.get("reason"), pl.get("warnings")))
    st, res = restore(B, blob1, "apply")
    r = res.get("result") or {}
    check("B4. КРИТИЧНО: восстановление на чистую папку применено (склад и заказы)",
          st == 200 and res.get("status") == "ok" and {"cost", "inventory"} <= set(r.get("modules_applied") or []),
          (st, res))
    st, orders = B.js("GET", "/api/mod/cost/calculations")
    check("B5. заказ с A на месте на B (тот же номер)",
          [o.get("order_number") for o in orders.get("orders") or []] == [order_no], orders.get("orders"))
    st, fil_b = B.js("GET", "/api/mod/inventory/filament")
    mb = fil_b.get("mobile") or {}
    check("B6. склад B: номер сервера, коды QR/NFC, метка и наклейки — как на A",
          mb.get("server_id") == srv_id
          and sorted(c.get("code") for c in mb.get("codes") or []) == ["4601234567890", "nfc:bambu:A1B2C3D4"]
          and [t.get("uid") for t in mb.get("nfc_tags") or []] == ["A1B2C3D4"]
          and len(mb.get("prepared_labels") or []) == 2, mb)
    st, again = B.js("POST", "/api/mod/inventory/spool", {
        "mobile": mobile(srv_id, 9, protocol=4, operation="nfc_receipt", nfc_uid="A1B2C3D4"), "location": lid,
        "weight_total_g": 1000, "filament_id": fid})
    check("B7. телефон узнаёт уже принятую метку: повторная приёмка на B отклонена",
          st == 409 and again.get("error") == "spool_already_received", (st, again))

    st, plan2 = restore(B, blob2, "plan")
    w2 = (plan2.get("plan") or {}).get("warnings") or []
    check("B8. КРИТИЧНО (R-128): план копии с защитой на компьютере без пользователей — «защита останется выключенной»",
          st == 200 and any(w.get("code") == "security_held_no_admin" for w in w2), (st, [w.get("code") for w in w2]))
    st, res2 = restore(B, blob2, "apply")
    check("B9. применение не включает защиту (ключ удержан)",
          st == 200 and (res2.get("result") or {}).get("held_keys") == ["security_enabled"], (st, res2))
    check("B10. вход на B по-прежнему не требуется", B.js("GET", "/api/auth/status")[1].get("enabled") is False)
    check("B11. B остановлен штатно", B.stop())
    check("B12. B поднялся снова", B.start())
    st_status, _s = B.js("GET", "/api/config-backup/status")
    check("B13. КРИТИЧНО: после перезапуска вход не заперт — защита выключена, администрирование доступно",
          B.js("GET", "/api/auth/status")[1].get("enabled") is False and st_status == 200, st_status)
    check("B14. в базе B флаг защиты '0', заказ с A на месте после перезапуска",
          [x["value"] for x in B.db("farm_parts.db", "SELECT value FROM app_settings WHERE key='security_enabled'")] in (["0"], [])
          and [x["order_number"] for x in B.db("farm_cost.db", "SELECT order_number FROM orders")] == [order_no])
    check("B15. B остановлен", B.stop())

    # ═════════════════════════════ ЭКЗЕМПЛЯР C ═════════════════════════════
    # Замечание проверки: на втором компьютере свои заказы с теми же номерами (шаблон номера по
    # умолчанию одинаков). Модуль блокируется, но выход есть — «Восстановить без этого модуля»:
    # тот же запрос с exclude_modules, остальное восстанавливается, свои заказы C не трогаются.
    C = Instance("C")
    print("изолированный экземпляр C (свои заказы): порт %d" % C.port)
    check("C1. экземпляр C поднялся", C.start())
    st, own = C.js("POST", "/api/mod/cost/calculations", {"order": {"title": "Свой заказ C", "items": []}})
    own_rows = C.db("farm_cost.db", "SELECT internal_id, order_number, title FROM orders") if own.get("ok") else []
    check("C2. на C свой заказ с тем же номером, что у заказа из копии, но другой записью",
          own.get("ok") is True and len(own_rows) == 1 and own_rows[0]["order_number"] == order_no, (own, own_rows))
    st, pc = restore(C, blob1, "plan")
    mdc = (pc.get("plan") or {}).get("module_data") or {}
    check("C3. план: восстановление заблокировано «Расчётом заказа» (номер занят), модуль назван",
          st == 200 and mdc.get("blocked") is True and mdc.get("blocked_modules") == ["cost"]
          and any(w.get("code") == "module_restore_conflict" and w.get("module_id") == "cost"
                  for w in mdc.get("warnings") or []), (st, mdc.get("blocked_modules"), mdc.get("warnings")))
    st, rc = restore(C, blob1, "apply")
    check("C4. применение без исключения отказывает, ничего не меняя",
          st == 409 and rc.get("reason") == "manual_resolution_required" and rc.get("module_id") == "cost"
          and not C.js("GET", "/api/mod/inventory/filament")[1].get("mobile", {}).get("codes"), (st, rc))
    st, px = restore(C, blob1, "plan", exclude=["cost"])
    mdx = (px.get("plan") or {}).get("module_data") or {}
    check("C5. КРИТИЧНО: план «без модуля Расчёт заказа» не заблокирован, модуль назван исключённым",
          st == 200 and mdx.get("blocked") is False and mdx.get("excluded") == ["cost"]
          and mdx.get("blocked_modules") == [], (st, mdx))
    st, rx = restore(C, blob1, "apply", exclude=["cost"])
    rxr = rx.get("result") or {}
    check("C6. КРИТИЧНО: восстановление без этого модуля применено (склад восстановлен, заказы не тронуты)",
          st == 200 and rx.get("status") == "ok" and "inventory" in (rxr.get("modules_applied") or [])
          and "cost" not in (rxr.get("modules_applied") or []), (st, rx))
    st, fil_c = C.js("GET", "/api/mod/inventory/filament")
    check("C7. склад C — как на A (коды QR/NFC, номер сервера)",
          (fil_c.get("mobile") or {}).get("server_id") == srv_id
          and sorted(c.get("code") for c in (fil_c.get("mobile") or {}).get("codes") or [])
          == ["4601234567890", "nfc:bambu:A1B2C3D4"], fil_c.get("mobile"))
    check("C8. свой заказ C остался как был, заказ из копии не добавлен",
          C.db("farm_cost.db", "SELECT internal_id, order_number, title FROM orders") == own_rows)
    check("C9. C остановлен", C.stop())
finally:
    for inst in (A, B, C):
        if inst is not None and inst.proc is not None and listening(inst.port):
            check("Z. экземпляр %s остановлен" % inst.tag, inst.stop())
    shutil.rmtree(BASE, ignore_errors=True)

print("\n" + "=" * 76)
if fails:
    print("FAIL: провалено %d" % len(fails))
    for f in fails:
        print("   - " + f)
print("ИТОГО: PASS=%d FAIL=%d" % (_n["pass"], _n["fail"]))
sys.exit(1 if _n["fail"] else 0)
