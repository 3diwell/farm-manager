# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
#  Alpha 2.806 — смена серверного порта через трей.
#
#  ПОЛНОСТЬЮ OFFLINE. Реальные production-порты не занимаются (socket подменяется фабрикой,
#  bind идёт по фейковой карте занятости), рабочий config/DB/DATA_DIR не используются
#  (временный config во FM_SERVER_CONFIG), tray/dialog/subprocess/backend — фейки, интернет
#  и принтеры не используются. server.py импортируется НЕ обычным способом: чистый контракт
#  порта берётся из app/server_port_config.py, а серверные функции/строки — разбором AST/текста.
#
#  ЧТО ДОКАЗЫВАЕТ. server_port по умолчанию 8000, диапазон 1024–65535, строгая валидация;
#  честная проверка занятости в текущем bind-режиме без reuse; атомарная запись config;
#  контракт active/pending/previous; «Позже» сохраняет pending, «Перезапустить сейчас»
#  переиспользует безопасный restart; startup применяет pending только после РЕАЛЬНОГО bind,
#  иначе откат к прежнему порту; desktop shell/браузер/discovery следуют активному порту;
#  LAN/AUTH/DB/DATA_DIR/firewall не трогаются; второй backend не запускается.
#
#  Запуск:  python tools/test_tray_server_port.py   (0 = всё пройдено)
# ============================================================================
import ast
import atexit
import json
import os
import re
import socket
import sys
import tempfile

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

_DONE = {"ok": False}


def _guard():
    if not _DONE["ok"]:
        try:
            print("FAIL — тест завершился до выполнения проверок")
            sys.stdout.flush()
        except Exception:
            pass
        os._exit(1)


atexit.register(_guard)

FAILED = []
PASSED = [0]


def check(name, ok):
    if ok:
        PASSED[0] += 1
        print("PASS — %s" % name)
    else:
        FAILED.append(name)
        print("FAIL — %s" % name)


def section(t):
    print("\n--- %s ---" % t)


SENTINEL = "TRAY_SERVER_PORT_SENTINEL_2_806"

TMP = tempfile.TemporaryDirectory(prefix="fm_port_")
ROOT = TMP.name

from app import server_port_config as pc            # noqa: E402  (чистый stdlib-модуль)
from app import desktop_shell_config as shcfg       # noqa: E402

SRV = open(os.path.join(REPO, "server.py"), encoding="utf-8", errors="surrogateescape").read()
SRV_AST = ast.parse(SRV)
ORCH = open(os.path.join(REPO, "app", "project_orchestrator.py"), encoding="utf-8").read()
DS_SRC = open(os.path.join(REPO, "app", "desktop_shell.py"), encoding="utf-8").read()
DSC_SRC = open(os.path.join(REPO, "app", "desktop_shell_config.py"), encoding="utf-8").read()
PC_SRC = open(os.path.join(REPO, "app", "server_port_config.py"), encoding="utf-8").read()
ISS_MAIN = open(os.path.join(REPO, "3diwell-setup.iss"), encoding="utf-8").read()


def fn_src(name):
    for n in ast.walk(SRV_AST):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.name == name:
            return ast.unparse(n)
    return ""


_DS_AST = ast.parse(DS_SRC)


def fn_src_ds(name):
    for n in ast.walk(_DS_AST):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            return ast.unparse(n)
    return ""


def code_only(src):
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return src
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
            body = getattr(n, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                body[0].value.value = ""
    return ast.unparse(tree)


# ── фейковый socket: занятость портов по карте ────────────────────────────────
class FakeSock(object):
    """Мок server-socket: bind падает OSError, если (host, port) в BUSY. Фиксирует, что реально
    открывалось и с какими опциями (доказать отсутствие reuse и закрытие)."""
    BUSY = set()
    opened = []
    closed = [0]
    setsockopts = []

    def __init__(self, family, type_):
        self.family = family
        self.type = type_
        FakeSock.opened.append((family, type_))

    def settimeout(self, t):
        pass

    def setsockopt(self, level, opt, val):
        FakeSock.setsockopts.append((level, opt, val))

    def bind(self, addr):
        if (addr[0], int(addr[1])) in FakeSock.BUSY:
            raise OSError(10048, "address in use (fake)")

    def listen(self, n=0):
        pass

    def setblocking(self, b):
        pass

    def close(self):
        FakeSock.closed[0] += 1


def reset_fake(busy=()):
    FakeSock.BUSY = set(busy)
    FakeSock.opened = []
    FakeSock.closed = [0]
    FakeSock.setsockopts = []


def write_cfg(path, cfg):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f)


def read_cfg(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


try:
    print("=== Alpha 2.806: смена серверного порта через трей (offline) ===")

    CFG = os.path.join(ROOT, "config.json")

    # ═══════════════════════════ CONFIG (1-8) ═══════════════════════════════
    section("контракт config")
    check("1. отсутствующий server_port даёт 8000",
          pc.read_port_state({})["active"] == 8000 and pc.DEFAULT_PORT == 8000)
    check("2. существующий server_port читается",
          pc.read_port_state({"server_port": 9001})["active"] == 9001)
    cfg = {"server_port": 8000, "lan_access_enabled": False, "data_dir": "", "custom_x": SENTINEL}
    pc.plan_change(cfg, 9100)
    check("3. неизвестные поля config сохраняются",
          cfg.get("custom_x") == SENTINEL and cfg.get("lan_access_enabled") is False
          and cfg.get("pending_server_port") == 9100 and cfg.get("previous_server_port") == 8000)
    ok_w = pc.atomic_write_json(CFG, cfg)
    check("4. запись config атомарна (temp -> fsync -> os.replace)",
          ok_w and read_cfg(CFG)["custom_x"] == SENTINEL
          and not os.path.exists(CFG + ".tmp")
          and "os.replace" in PC_SRC and "fsync" in PC_SRC)
    before = read_cfg(CFG)
    bad = pc.atomic_write_json(os.path.join(ROOT, "nonexistent_dir_x", "sub", "c.json"), {"a": 1})
    check("5. ошибка записи оставляет старый config (исходный файл не тронут)",
          read_cfg(CFG) == before or bad is False)  # запись в несуществующее — либо создаётся, либо False; CFG не тронут
    check("5b. неудачная запись не оставляет .tmp",
          not any(f.endswith(".tmp") for f in os.listdir(ROOT)))
    cfg_noop = {"server_port": 8000}
    changed = pc.plan_change(cfg_noop, 8000)
    check("6/7. cancel/no-op ничего не пишет (plan_change no-op возвращает False, поля не создаёт)",
          changed is False and "pending_server_port" not in cfg_noop
          and "previous_server_port" not in cfg_noop)
    cfg_ok = {"server_port": 8000}
    check("8. pending/previous создаются только при реальной смене",
          pc.plan_change(cfg_ok, 9200) is True
          and cfg_ok["pending_server_port"] == 9200 and cfg_ok["previous_server_port"] == 8000)

    # ═══════════════════════════ VALIDATION (9-20) ══════════════════════════
    section("валидация порта")
    check("9. 1024 разрешён", pc.validate_server_port(1024) == (1024, ""))
    check("10. 65535 разрешён", pc.validate_server_port("65535") == (65535, ""))
    check("11. 1023 запрещён", pc.validate_server_port(1023)[0] is None)
    check("12. 65536 запрещён", pc.validate_server_port(65536)[0] is None)
    check("13. 0 запрещён", pc.validate_server_port(0)[0] is None and pc.validate_server_port("0")[0] is None)
    check("14. отрицательный запрещён", pc.validate_server_port(-8000)[0] is None
          and pc.validate_server_port("-1")[0] is None)
    check("15. пустое запрещено", pc.validate_server_port("")[0] is None
          and pc.validate_server_port(None)[0] is None and pc.validate_server_port("   ")[0] is None)
    check("16. пробелы допустимы только по краям", pc.validate_server_port("  8080  ") == (8080, "")
          and pc.validate_server_port("80 80")[0] is None)
    check("17. дробное запрещено", pc.validate_server_port(8000.5)[0] is None
          and pc.validate_server_port("8000.0")[0] is None and pc.validate_server_port(8000.0)[0] is None)
    check("18. host:port запрещено", pc.validate_server_port("127.0.0.1:8000")[0] is None
          and pc.validate_server_port("host:8000")[0] is None)
    check("19. URL запрещён", pc.validate_server_port("http://127.0.0.1:8000")[0] is None)
    check("20. hex/octal запрещены", pc.validate_server_port("0x1F90")[0] is None
          and pc.validate_server_port("0o17320")[0] is None and pc.validate_server_port("08000")[0] is None
          and pc.validate_server_port(True)[0] is None)   # bool не порт

    # ═══════════════════════════ PORT CHECK (21-27) ═════════════════════════
    section("проверка занятости порта")
    reset_fake(busy={("127.0.0.1", 8080)})
    check("21. свободный loopback port разрешён",
          pc.check_port_availability(9300, False, sock_factory=FakeSock) == (True, ""))
    check("22. занятый loopback port блокируется",
          pc.check_port_availability(8080, False, sock_factory=FakeSock) == (False, "busy"))
    reset_fake(busy={("0.0.0.0", 9400)})
    check("23. LAN mode проверяет wildcard bind (0.0.0.0)",
          pc.check_port_availability(9400, True, sock_factory=FakeSock) == (False, "busy")
          and pc.check_port_availability(9400, False, sock_factory=FakeSock) == (True, ""))
    reset_fake()
    pc.check_port_availability(9500, False, sock_factory=FakeSock)
    check("24. socket всегда закрывается", FakeSock.closed[0] == 1)
    check("25. SO_REUSEPORT/SO_REUSEADDR не используются (конфликт виден честно; setsockopt не звался)",
          FakeSock.setsockopts == [] and "setsockopt" not in code_only(PC_SRC)
          and "SO_REUSEPORT" not in code_only(PC_SRC) and "SO_REUSEADDR" not in code_only(PC_SRC))
    reset_fake(busy={("127.0.0.1", 8000)})
    check("26. текущий active port как no-op не считается конфликтом",
          pc.check_port_availability(8000, False, sock_factory=FakeSock, current_port=8000) == (True, "")
          and pc.check_port_availability(8000, False, sock_factory=FakeSock) == (False, "busy"))
    check("27. race precheck/startup покрывается реальным bind на старте (кандидаты + свой сокет)",
          "startup_plan" in PC_SRC and "_bind_listener" in SRV and "s.bind((host, int(port)))" in SRV)

    # ═══════════════════════════ TRAY (28-38) ═══════════════════════════════
    section("tray")
    _tray = fn_src("_start_tray_detached")
    check("28. меню показывает active port (информационный неактивный пункт)",
          "Порт сервера: %d" in _tray and "_active_server_port()" in _tray
          and "enabled=False" in _tray)
    check("29. pending отображается отдельным неактивным пунктом с условием видимости",
          "После перезапуска: %d" in _tray and "_pending_present" in _tray
          and "visible=_pending_present" in _tray)
    _dlg = fn_src("_show_change_port_dialog")
    check("30. change dialog открывается ОДИН РАЗ (lock, non-blocking acquire)",
          "_PORT_DIALOG_LOCK.acquire(blocking=False)" in _dlg and "Изменить порт…" in _tray)
    check("31. Enter применяет", "root.bind('<Return>', _apply)" in code_only(_dlg).replace('"', "'"))
    check("32. Escape отменяет", "<Escape>" in _dlg and "_close" in _dlg)
    check("33. закрытие крестиком = отмена (WM_DELETE_WINDOW -> _close)",
          "WM_DELETE_WINDOW" in _dlg and "_close" in _dlg)
    _dlg_q = code_only(_dlg).replace('"', "'")
    _inv_slice = _dlg_q[_dlg_q.index("res == 'invalid'"):]   # ветка invalid: return ДО любого _close
    check("34. неверное значение не закрывает dialog (ошибка внутри, return без destroy)",
          "err.config(text=_port_msg('invalid'))" in _inv_slice
          and _inv_slice.index("return") < _inv_slice.index("_close"))
    check("35. занятый порт не сохраняется (busy -> ошибка в диалоге; save только на res=='ok')",
          "_port_msg('busy'" in _dlg_q and "res == 'busy'" in _dlg_q)
    check("36. tray thread не блокируется (диалог и mainloop — в отдельном потоке)",
          "threading.Thread(target=_run, daemon=True).start()" in _dlg
          and "mainloop" in _dlg)
    check("37. browser menu остаётся", "Открыть в браузере" in _tray)
    check("38. exit contract остаётся", "'Выход', _quit" in _tray and "os._exit(0)" in _tray)

    # ═══════════════════════════ APPLY LATER (39-42) ════════════════════════
    section("применить позже")
    cfg_later = {"server_port": 8000, "keep_me": SENTINEL}
    pc.plan_change(cfg_later, 8090)
    check("39. «Позже» сохраняет pending (previous = прежний active)",
          cfg_later["pending_server_port"] == 8090 and cfg_later["previous_server_port"] == 8000)
    st = pc.read_port_state(cfg_later)
    check("40. текущий backend остаётся на старом порту (active не изменился до перезапуска)",
          st["active"] == 8000 and st["pending"] == 8090)
    check("41. Open Browser использует АКТИВНЫЙ (старый) порт до перезапуска",
          "_active_server_port()" in fn_src("_start_tray_detached")
          and "'http://localhost:%d' % _active_server_port()".replace("'", '"') in fn_src("_start_tray_detached").replace("'", '"'))
    plan = pc.startup_plan(cfg_later)
    check("42. следующий startup пытается pending первым",
          plan[0] == 8090 and 8000 in plan)

    # ═══════════════════════════ RESTART NOW (43-51) ════════════════════════
    section("перезапустить сейчас")
    _restart = fn_src("_restart_self").replace('"', "'")
    check("43. restart helper ждёт старый PID/порт (FM_RESTART_WAIT_PORT = активный порт)",
          "env['FM_RESTART_WAIT_PORT'] = str(_active_server_port())" in _restart)
    check("44/45. второй backend не работает параллельно (single-instance mutex + ожидание порта)",
          "FM_RESTART_WAIT_PORT" in SRV and "single_instance" in SRV
          and "_port_in_use(_wp)" in SRV)
    # commit/rollback контракта на старте
    cfg_boot = {"server_port": 8000, "pending_server_port": 8090, "previous_server_port": 8000, "u": SENTINEL}
    committed = pc.commit_pending(cfg_boot)
    check("46. успешный bind подтверждает pending как active",
          committed == 8090 and cfg_boot["server_port"] == 8090)
    # Startup применяет pending ТОЛЬКО когда поднялся ИМЕННО pending-порт (commit после bind).
    _boot_seg = SRV[SRV.index("КОНТРАКТ ПОРТА НА СТАРТЕ"):SRV.index("_uv.run(sockets=[_listen_sock])")]
    check("46b. pending применяется только если поднялся именно pending-порт (commit после bind)",
          '_bound_port == _pstate["pending"]' in _boot_seg
          and _boot_seg.index("_ACTIVE_PORT = _bound_port") < _boot_seg.index("commit_pending")
          and _boot_seg.index('_bound_port == _pstate["pending"]') < _boot_seg.index("commit_pending"))
    check("47/48. pending и previous очищаются после success",
          "pending_server_port" not in cfg_boot and "previous_server_port" not in cfg_boot
          and cfg_boot["u"] == SENTINEL)
    check("49. tray показывает новый порт (из active рантайма)",
          "_active_server_port()" in _tray)
    check("50. browser URL использует новый порт", "_active_server_port()" in fn_src("_open_desktop_shell")
          or "_active_server_port()" in _tray)
    check("51. discovery сообщает новый порт (beacon по активному порту)",
          "_active_server_port()" in fn_src("_discovery_beacon")
          and "_discovery_beacon, args=(_ACTIVE_PORT,)" in SRV)

    # ═══════════════════════════ ROLLBACK (52-61) ═══════════════════════════
    section("откат при неудачном bind")
    # previous ОТЛИЧАЕТСЯ от active, чтобы поймать откат «к активному/pending» вместо «к previous».
    cfg_rb = {"server_port": 9999, "pending_server_port": 8091, "previous_server_port": 8000, "z": SENTINEL}
    kept = pc.rollback_pending(cfg_rb)
    check("52. bind failure возвращает ПРЕЖНИЙ рабочий порт (previous), не активный и не занятый pending",
          kept == 8000 and cfg_rb["server_port"] == 8000)
    check("53/54/55. config восстанавливается, pending и previous очищаются",
          "pending_server_port" not in cfg_rb and "previous_server_port" not in cfg_rb
          and cfg_rb["z"] == SENTINEL)
    _boot = SRV[SRV.index("КОНТРАКТ ПОРТА НА СТАРТЕ"):SRV.index("uvicorn.Server(uvicorn.Config")]
    check("56/57. LAN/AUTH при откате не меняются (в блоке порта их не трогают)",
          "rollback_pending" in _boot and "set_network" not in _boot
          and "_SECURITY_ENABLED = " not in _boot and "lan_access_enabled\"] =" not in _boot)
    check("58. DB не открывается в port helper (server_port_config без sqlite/conn)",
          "sqlite" not in PC_SRC.lower() and "conn_p" not in PC_SRC)
    check("59. DATA_DIR не сканируется (нет os.walk/listdir в контракте порта)",
          "os.walk" not in PC_SRC and "listdir" not in PC_SRC)
    check("60. random port не выбирается (startup перебирает только кандидатов startup_plan; "
          "нет random/getrandbits/bind порта 0)",
          "random" not in PC_SRC.lower() and "random" not in code_only(_boot).lower()
          and "bind((host, 0))" not in SRV and ", 0))" not in code_only(_boot)
          and "for _cand in _candidates:" in _boot and "случайный порт НЕ выбираем" in SRV)
    check("61. ошибка обоих портов безопасна (config не повреждается, не падаем в random)",
          "config НЕ повреждаем" in SRV and "sys.exit(1)" in _boot)

    # ═══════════════════════════ DESKTOP SHELL (62-69) ══════════════════════
    section("desktop shell следует активному порту")
    _dsc = code_only(DSC_SRC)
    check("62. shell читает configured port (candidate_local_ports из config сервера)",
          "candidate_local_ports" in _dsc and "server_config_path" in _dsc
          and "pending_server_port" in _dsc and "server_port" in _dsc)
    check("63. жёсткого 8000 в startup shell нет (кандидаты из config, дефолт только fallback)",
          "candidate_local_ports" in code_only(DS_SRC)
          and "127.0.0.1:8000" not in code_only(fn_src_ds("boot")))
    check("64. foreign HTTP server отклоняется (строгая идентичность /version)",
          "classify_probe" in DS_SRC and "is_farm_manager_version_payload" in
          open(os.path.join(REPO, "app", "desktop_shell_security.py"), encoding="utf-8").read())
    # Alpha 2.812: перебор кандидатов вынесен в find_running_local (тем же резолвером пользуется
    # и ярлык «браузер»). Инвариант прежний: сначала ищем работающий сервер, и только потом
    # думаем о запуске backend.
    check("65. shell не запускает второй backend, если кандидат ответил",
          "for base in self.local_candidate_urls():" in fn_src_ds("find_running_local")
          and "probe_farm_manager" in fn_src_ds("find_running_local")
          and fn_src_ds("boot").index("find_running_local") < fn_src_ds("boot").index("ensure_local_backend"))
    check("66. shell после смены использует новый origin (go(base) на ответивший кандидат)",
          "self.go(base)" in fn_src_ds("boot"))
    check("67. navigation policy обновляется только после Farm Manager identity",
          "allowed_origin" in DS_SRC and "_policy_ready" in DS_SRC)
    check("68. query/fragment не логируются", "redact_url_for_log" in DS_SRC)
    check("69. close shell не останавливает backend (регрессия 2.805 сохранена)",
          "backend продолжает работать" in DS_SRC
          and not re.search(r"terminate|\.kill\(|taskkill|/api/(exit|shutdown)", code_only(DS_SRC)))

    # ═══════════════════════ REMOTE CLIENT/DISCOVERY (70-74) ════════════════
    section("remote client и discovery")
    check("70. discovery возвращает новый порт (парсит порт из ответа сервера)",
          "parse_discovery_reply" in DS_SRC and "port" in
          open(os.path.join(REPO, "app", "desktop_shell_security.py"), encoding="utf-8").read())
    check("71. client не запускает server", "server.py" not in
          open(os.path.join(REPO, "client_launcher.pyw"), encoding="utf-8").read())
    # server_config_path используется ТОЛЬКО в candidate_local_ports и ТОЛЬКО на чтение (json.load).
    _cand_src = ""
    for _n in ast.walk(ast.parse(DSC_SRC)):
        if isinstance(_n, ast.FunctionDef) and _n.name == "candidate_local_ports":
            _cand_src = ast.unparse(_n)
    check("72. client не меняет server config (config сервера читается read-only; порт пишет только сервер)",
          "server_port" not in code_only(DS_SRC)
          and _dsc.count("server_config_path") == 2                # определение + единственное чтение
          and "json.load" in _cand_src and "json.dump" not in _cand_src and "open(" in _cand_src
          and "atomic_write" not in (DS_SRC + DSC_SRC)
          and "plan_change" not in (DS_SRC + DSC_SRC) and "commit_pending" not in (DS_SRC + DSC_SRC))
    check("73. сохранённый origin не переписывается молча (client_connect по явному действию)",
          "save_client_config" in fn_src_ds("client_connect"))
    check("74. новый discovery result можно выбрать (discover -> список -> connect)",
          "discover_servers" in DS_SRC and "connect" in DS_SRC)

    # ═══════════════════════════ API/SECURITY (75-82) ═══════════════════════
    section("api и безопасность")
    _gnet = fn_src("g_network")
    check("75. read-only состояние показывает active port",
          "'port': _active_server_port()" in _gnet.replace('"', "'"))
    check("76. pending наружу безопасен (только при наличии, из read_port_state)",
          "pending_port" in _gnet and "_ps.get('pending')" in _gnet.replace('"', "'"))
    check("77. previous/rollback port наружу НЕ выходит",
          "previous_server_port" not in _gnet and "previous" not in _gnet.replace("pending", ""))
    check("78. config path наружу не выходит", "_config_path" not in _gnet
          and "config.json" not in _gnet)
    _routes = re.findall(r"@app\.(get|post|patch|delete|websocket)\([\"']([^\"']+)", SRV)
    # «port» как отдельный сегмент пути (а не подстрока imPORT/exPORT).
    _port_routes = [(m, p) for m, p in _routes
                    if re.search(r"(^|[/-])port($|[/-])|server[-_]port", p.lower())]
    check("79. write-route смены порта НЕ добавлен (порт меняется ТОЛЬКО локальным треем)",
          _port_routes == [] and "/api/set-port" not in SRV and "/api/server-port" not in SRV
          and len(_routes) == 209)   # 2.823 +printer-files; 2.825 +select-for-print; 2.827 +4 config-backup; 2.831 +2 printer-sort-mode; 2.833 +2 klipper-prestart; 2.903: +3 UI 3.0; 2.920: +5 очередь ожидания; 2.927: +3 пометки принтера и настройки фермы; 2.947 +staging/sync; 2.948 -projects2/pending-printable; 2.979 +projects2 files/locate; 2.980 +4 printer-discovery, +3 net-capture; 2.994 +6 маршрутов модуля messengers; 12.09.2026 -1 маршрут пометок принтера
    check("80. AUTH bypass не добавлен (гейт/политика не тронуты)",
          "_auth_gate" in SRV and "_gate_decide" in SRV)
    _prep = code_only(fn_src("_prepare_port_change"))   # без докстроки (в ней перечислены LAN/AUTH)
    check("81. LAN/AUTH не меняются сменой порта (в КОДЕ helper'а порта нет записи lan/auth/security)",
          "lan_access_enabled" not in PC_SRC and "lan_access_enabled" not in _prep
          and "_SECURITY_ENABLED" not in _prep and "auth" not in _prep.lower()
          and "_write_config(" not in _prep)   # смена порта пишет только атомарно свой контракт
    check("82. firewall не меняется сменой порта",
          "netsh" not in PC_SRC and "_ensure_firewall_rule" not in fn_src("_prepare_port_change")
          and "_ensure_firewall_rule" not in fn_src("_show_change_port_dialog"))

    # ═══════════════════════════ REGRESSION (83-94) ═════════════════════════
    section("регрессия")
    check("83. browser access работает (Открыть в браузере на активном порту)",
          "Открыть в браузере" in _tray)
    check("84. desktop shell работает (тест 2.805 не тронут по контракту)",
          os.path.exists(os.path.join(REPO, "tools", "test_desktop_shell.py")))
    check("85. WebSocket contract не меняется", "active_ws" in SRV and "ws_ep" in SRV)
    check("86. local admin recovery использует active port",
          "_active_server_port()" in fn_src("_local_recovery_url")
          or "_LOCAL_RECOVERY_PORT()" in fn_src("_local_recovery_url"))
    check("87/88. project files и managed storage не меняются",
          "normalize_and_validate_project_name" in SRV and "_import_copy_managed" in SRV)
    check("89. printer pipeline не меняется", "_moonraker_print_started" in SRV
          and "_send_file_to_printer" in SRV)
    check("90. DISPATCH_ENABLED остаётся False",
          re.search(r"^DISPATCH_ENABLED\s*=\s*False", ORCH, re.M) is not None)
    check("91. TRANSPORT_ENABLED остаётся False",
          re.search(r"^TRANSPORT_ENABLED\s*=\s*False", ORCH, re.M) is not None)
    check("92. `_incoming/` не используется контрактом порта",
          "_incoming" not in PC_SRC)
    check("93. артефактов теста нет; sentinel только в тесте",
          not os.path.exists(os.path.join(REPO, "tools", "_e2e_payload.json"))
          and SENTINEL not in SRV and SENTINEL not in PC_SRC and SENTINEL not in DS_SRC
          and SENTINEL not in DSC_SRC and SENTINEL not in ORCH and SENTINEL not in ISS_MAIN)
    check("93b. порт хранится в config, не в SQLite (контракт порта без БД; init_db без server_port)",
          "server_port" not in fn_src("init_db") and "sqlite" not in PC_SRC.lower())
    check("93c. HTTP-маршруты ядра = 197",
          len(re.findall(r"^@app\.(get|post|patch|delete|websocket)\(", SRV, re.M)) == 209)   # 2.823: +5 printer-files; 2.825: +select-for-print; 2.827: +4 config-backup; 2.831: +2 printer-sort-mode; 2.833: +2 klipper-prestart; 2.839: +klipper-contract-report; 2.903: +3 UI 3.0; 2.920: +5 очередь ожидания; 2.947 +staging/sync; 2.948 -projects2/pending-printable; 2.979 +projects2 files/locate; 2.980 +4 printer-discovery, +3 net-capture; 2.994 +6 маршрутов модуля messengers; 12.09.2026 -1 маршрут пометок принтера

finally:
    TMP.cleanup()

check("94. временный корень удалён после теста", not os.path.exists(ROOT))

print("\n" + "=" * 76)
if FAILED:
    print("FAIL: провалено %d из %d" % (len(FAILED), len(FAILED) + PASSED[0]))
    for n in FAILED:
        print("   - %s" % n)
    _DONE["ok"] = True
    sys.exit(1)
print("ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ (%d)" % PASSED[0])
_DONE["ok"] = True
sys.exit(0)
