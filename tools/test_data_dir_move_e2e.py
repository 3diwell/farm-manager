# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
#  29.09.2026 — смена папки данных на НАСТОЯЩЕМ процессе программы, полностью офлайн.
#
#  Программа поднимается по-настоящему (python server.py в изолированном режиме app/e2e_isolation:
#  своя временная папка данных, свой config, свободный порт, свой замок, без трея, браузера,
#  обнаружения и принтеров; модули включены). Путь владельца:
#    ставит модули (склад, качество, расчёт заказа) -> заводит катушку и заказ с файлом ->
#    «Хранение данных» отказывает в папку с чужими базами и внутрь служебной папки, принимает
#    пустую -> перезапуск: данные переехали (модули с теми же данными, лицензия и номер установки
#    на месте, файл заказа открывается — проект по заказу получает файл), в прежней папке осталось
#    только непереносимое, есть отчёт, ежедневные копии всех баз -> перенос в папку с конфликтом:
#    программа честно остаётся на прежней папке, данные целы, причина видна; отказ от переноса.
#
#  БЕЗОПАСНОСТЬ ПРОГОНА: рабочие DATA_DIR/config/БД/порт/замок не используются (все папки — внутри
#  временной папки теста, программа сама не выпускает изолированный экземпляр за её пределы);
#  принтерам ничего не отправляется; сеть наружу не нужна; временная папка удаляется в конце.
#
#  Запуск:  PYTHONIOENCODING=utf-8 python tools/test_data_dir_move_e2e.py   (0 = пройдено)
# ============================================================================
import hashlib, importlib.util, io, json, os, re, secrets, shutil, socket, subprocess, sys, tempfile, time
import urllib.error, urllib.request
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.dont_write_bytecode = True
from app import e2e_isolation as ISO  # noqa: E402
from app import data_dir_items as D  # noqa: E402

SRC = open(os.path.join(REPO, "server.py"), encoding="utf-8").read()
APP_VERSION = re.search(r'^APP_VERSION\s*=\s*"([^"]+)"', SRC, re.M).group(1)
PROD = os.path.join(os.environ.get("LOCALAPPDATA", ""), "3DIWELL")
fails, names = [], []


def check(name, ok, extra=""):
    names.append(name)
    print(("PASS" if ok else "FAIL") + " — " + name + (("  :: %s" % (extra,))[:700] if (not ok and extra != "") else ""),
          flush=True)
    if not ok:
        fails.append(name)


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


def listening(port):
    out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True, creationflags=0x08000000).stdout
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


def call(method, path, body=None, raw=None, ctype=None, timeout=60):
    data = json.dumps(body).encode("utf-8") if body is not None else (raw if raw is not None else (b"" if method != "GET" else None))
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), data=data, method=method)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    if ctype:
        req.add_header("Content-Type", ctype)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8") or "{}")
        except Exception:
            return e.code, {}
    except Exception as e:
        return 0, {"error": repr(e)}


def multipart(path, fields, files):
    b = "----fmmove" + secrets.token_hex(8)
    parts = []
    for k, v in fields.items():
        parts.append(("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n" % (b, k, v)).encode("utf-8"))
    for k, (fname, data) in files.items():
        parts.append(("--%s\r\nContent-Disposition: form-data; name=\"%s\"; filename=\"%s\"\r\n"
                      "Content-Type: application/octet-stream\r\n\r\n" % (b, k, fname)).encode("utf-8") + data + b"\r\n")
    body = b"".join(parts) + ("--%s--\r\n" % b).encode()
    return call("POST", path, raw=body, ctype="multipart/form-data; boundary=" + b)


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def files_under(root):
    out = set()
    for base, _d, fs in os.walk(root):
        for f in fs:
            out.add(os.path.relpath(os.path.join(base, f), root).replace("\\", "/"))
    return out


root = tempfile.mkdtemp(prefix="fm_e2e_datamove_")
work = tempfile.mkdtemp(prefix="fm_e2e_datamove_work_")
assert not os.path.normcase(root).startswith(os.path.normcase(PROD)), "временная папка внутри рабочей!"
assert not os.path.normcase(work).startswith(os.path.normcase(PROD)), "временная папка внутри рабочей!"
NEW = os.path.join(root, "moved")          # новая папка данных — внутри папки теста
BLOCKED = os.path.join(root, "blocked")    # папка с чужой базой: перенос туда должен честно не состояться


class _NoGenerator(object):
    """Сборщик склада перед упаковкой перегенерирует служебный файл В ПАПКЕ ПРОЕКТА (в zip он не
    входит). Набору писать в проект незачем — генератор подменён пустым успешным запуском."""

    class _R(object):
        returncode = 0

    @staticmethod
    def run(*a, **k):
        return _NoGenerator._R()


def build_zip(script, attr, out_name):
    """Сборка zip модуля из исходников во временную папку (не в modules/)."""
    spec = importlib.util.spec_from_file_location("fm_e2e_build_" + out_name, os.path.join(REPO, "tools", script))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    setattr(mod, attr, os.path.join(work, out_name))
    if hasattr(mod, "subprocess"):
        mod.subprocess = _NoGenerator
    old, sys.stdout = sys.stdout, io.StringIO()
    try:
        mod.main()
    finally:
        sys.stdout = old
    return os.path.join(work, out_name)


ZIPS = {"cost": build_zip("build_cost_zip.py", "OUT", "cost.zip"),
        "quality": build_zip("build_quality_zip.py", "OUT", "quality.zip"),
        "inventory": build_zip("build_inventory_zip.py", "OUT_ZIP", "inventory.zip")}

port = free_port()
token = "MOVE_E2E_" + secrets.token_hex(8)
with open(os.path.join(root, ISO.MARKER_NAME), "w", encoding="utf-8") as f:
    json.dump({"token": token, "sentinel": "DATA_MOVE_E2E_0929"}, f)
cfgp = os.path.join(root, "config.json")
json.dump({"server_port": port}, open(cfgp, "w", encoding="utf-8"))
env = dict(os.environ)
env.update({ISO.ENV_SENTINEL: token, ISO.ENV_INSTANCE: "e2e-move", ISO.ENV_DATA_DIR: root, ISO.ENV_CONFIG: cfgp,
            ISO.ENV_MUTEX: "Local\\3DIWELL_FM_E2E_MOVE_" + secrets.token_hex(6), ISO.ENV_PORT: str(port),
            ISO.ENV_NO_TRAY: "1", ISO.ENV_NO_BROWSER: "1", ISO.ENV_NO_DISCOVERY: "1", ISO.ENV_NO_PRINTERS: "1",
            ISO.ENV_NO_MODULES: "0", "PYTHONDONTWRITEBYTECODE": "1"})
env.pop("FM_LICENSE_TEST_KEYS", None)
proc = None


def start():
    p = subprocess.Popen([sys.executable, os.path.join(REPO, "server.py"), ISO.FLAG, "--desktop-start", "--no-browser"],
                         cwd=REPO, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, creationflags=(0x00000008 | 0x00000200))
    ok = wait(lambda: call("GET", "/version")[1].get("version") == APP_VERSION if listening(port) else None, 180)
    return p, bool(ok)


def stop():
    with open(os.path.join(root, "stop.request"), "w", encoding="utf-8") as f:
        f.write(token)
    gone = wait(lambda: not listening(port), 60)
    if not gone and proc is not None and proc.poll() is None:
        proc.terminate()   # только СВОЙ процесс; рабочую программу не трогаем
        gone = wait(lambda: not listening(port), 20)
    if proc is not None:
        try:
            proc.wait(timeout=20)       # процесс отпустил файлы — дальше их можно сверять и переносить
        except Exception:
            pass
    try:
        os.unlink(os.path.join(root, "stop.request"))
    except Exception:
        pass
    return bool(gone)


def restart(label):
    global proc
    check("%s. изолированный экземпляр остановлен штатно" % label, stop())
    proc, ok = start()
    check("%s. и поднялся снова" % label, ok)
    return ok


def mods():
    return {m["id"]: m for m in call("GET", "/api/modules")[1].get("modules", [])}


GCODE = ("; HEADER_BLOCK_START\n; generated by OrcaSlicer 2.3.0 on 2026-09-29 at 10:00:00\n"
         "; model printing time: 0h 10m 0s; total estimated time: 0h 11m 0s\n; HEADER_BLOCK_END\n"
         "G28\nG1 X10 Y10 E1\n; filament used [g] = 4.50\n; filament_type = PLA\n; filament_colour = #FF0000\n"
         "; printer_model = Bambu Lab X1 Carbon\n").encode("utf-8")

print("изолированный экземпляр: порт %d, папка %s" % (port, root))
proc, ok = start()
check("A1. изолированный экземпляр поднялся (своя папка, порт, замок; модули включены)", ok)
try:
    for mid, zp in sorted(ZIPS.items()):
        st, js = call("POST", "/api/modules/install-path", {"path": zp})
        check("A2. модуль %s установлен из zip" % mid, st == 200 and js.get("status") == "ok", js)
    restart("A3")
    M1 = mods()
    check("A4. склад, качество и расчёт заказа загружены",
          all((M1.get(m) or {}).get("state") == "loaded" for m in ZIPS), {k: v.get("state") for k, v in M1.items()})
    st, js = call("POST", "/api/mod/inventory/spool", {"filament": {"material": "PLA", "color_name": "Красный",
                                                                    "vendor_name": "E2E-перенос"},
                                                       "weight_total_g": 1000, "label": "E2E-катушка"})
    check("A5. на складе заведена катушка", st == 200 and js.get("ok") is True, (st, js))
    order = {"title": "E2E перенос папки", "items": [{"name": "Кронштейн", "duration_s": 600, "required_qty": 1,
                                                      "on_plate_qty": 1, "weight_g": 5, "material_price_per_kg": 1000,
                                                      "file_token": "tok1", "filename": "bracket.gcode"}]}
    st, js = multipart("/api/mod/cost/calculations", {"payload": json.dumps({"order": order}, ensure_ascii=False)},
                       {"file:tok1": ("bracket.gcode", GCODE)})
    OID = js.get("internal_id", "")
    check("A6. заказ с файлом сохранён (копия файла — в папке заказов модуля)",
          st == 200 and js.get("ok") is True and len(js.get("files") or []) == 1, (st, js))
    st, js = call("GET", "/api/licenses")
    IID = js.get("install_id", "")
    check("A7. номер установки создан", st == 200 and IID.startswith("fm-"), js)
    st, SUM1 = call("GET", "/api/mod/inventory/summary")
    check("A8. сводка склада: одна катушка", SUM1.get("spools") == 1, SUM1)

    # Б. «Хранение данных»: отказы и приём
    os.makedirs(os.path.join(root, "occupied"))
    with open(os.path.join(root, "occupied", "farm_parts.db"), "wb") as f:
        f.write(b"another farm")
    st, js = call("POST", "/api/storage/data", {"path": os.path.join(root, "occupied")})
    check("B1. папка, где уже есть базы Farm Manager, отклонена с понятной причиной (ru/en)",
          js.get("status") == "error" and js.get("reason") == "data_dir_not_empty" and js.get("message_en"), js)
    st, js = call("POST", "/api/storage/data", {"path": os.path.join(root, "modules", "x")})
    check("B2. папка внутри служебной папки программы отклонена, пустая папка в modules не появилась",
          js.get("reason") == "data_dir_inside_current" and not os.path.exists(os.path.join(root, "modules", "x")), js)
    st, js = call("POST", "/api/storage/data", {"path": NEW})
    check("B3. пустая папка принята: перенос при следующем запуске",
          js.get("status") == "ok" and js.get("changed") is True, js)
    st, js = call("GET", "/api/storage")
    check("B4. «Хранение данных» показывает ожидающую смену", D.same_path(js.get("data_dir_pending", ""), NEW), js)

    # Лицензия (файл) и снимок того, что должно переехать.
    stop()
    os.makedirs(os.path.join(root, "licenses"), exist_ok=True)
    with open(os.path.join(root, "licenses", "E2E-TEST.fmlic"), "w", encoding="utf-8") as f:
        f.write('{"format": "fm-license", "note": "e2e"}')
    with open(os.path.join(root, "notes-owner.txt"), "w", encoding="utf-8") as f:
        f.write("личный файл владельца — не данные программы")
    LIC_SHA = sha(os.path.join(root, "licenses", "E2E-TEST.fmlic"))
    ORDER_FILES = sorted(files_under(os.path.join(root, "cost_order_files")))
    ORDER_SHA = {r: sha(os.path.join(root, "cost_order_files", r)) for r in ORDER_FILES}
    MOD_FILES = files_under(os.path.join(root, "modules"))
    BEFORE_TOP = set(os.listdir(root))
    proc, ok = start()
    check("C1. программа поднялась после смены папки (перенос выполнен при запуске)", ok)

    # В. после переноса
    st, js = call("GET", "/api/storage")
    mv = js.get("data_move") or {}
    check("C2. программа работает из новой папки; итог переноса «выполнен» виден в «Хранении данных»",
          D.same_path(js.get("data_dir", ""), NEW) and not js.get("data_dir_pending") and mv.get("status") == "ok"
          and mv.get("active") is True and D.same_path(mv.get("from", ""), root), js)
    M2 = mods()
    check("C3. модули те же и загружены",
          set(M2) == set(M1) and all((M2.get(m) or {}).get("state") == "loaded" for m in ZIPS)
          and all(M2[m].get("version") == M1[m].get("version") for m in ZIPS), {k: v.get("state") for k, v in M2.items()})
    st, js = call("GET", "/api/mod/inventory/summary")
    st2, fil = call("GET", "/api/mod/inventory/filament")
    check("C4. склад с теми же данными: катушка на месте",
          js.get("spools") == 1 and "E2E-катушка" in json.dumps(fil, ensure_ascii=False), (js, st2))
    st, js = call("GET", "/api/mod/cost/calculations/%s" % OID)
    check("C5. заказ на месте, с файлом", js.get("internal_id") == OID and len(js.get("files") or []) == 1, js)
    st, js = call("GET", "/api/licenses")
    check("C6. номер установки тот же (лицензии с привязкой не теряются)", js.get("install_id") == IID, (IID, js.get("install_id")))
    check("C7. файл лицензии переехал побайтно",
          os.path.isfile(os.path.join(NEW, "licenses", "E2E-TEST.fmlic"))
          and sha(os.path.join(NEW, "licenses", "E2E-TEST.fmlic")) == LIC_SHA)
    check("C8. файлы заказа и модули переехали побайтно",
          files_under(os.path.join(NEW, "cost_order_files")) >= set(ORDER_FILES)
          and all(sha(os.path.join(NEW, "cost_order_files", r)) == h for r, h in ORDER_SHA.items())
          and files_under(os.path.join(NEW, "modules")) >= MOD_FILES and ORDER_FILES, ORDER_FILES)
    st, js = call("POST", "/api/mod/cost/calculations/%s/recalc" % OID, {"action": "create_project"}, timeout=120)
    check("C9. КРИТИЧНО: файл заказа открывается после переноса — проект по заказу получил файл",
          js.get("ok") is True and js.get("uploaded") == ["bracket.gcode"] and not js.get("file_failures"), js)
    _left = set(os.listdir(root)) - {"moved", "occupied"}
    _allowed = {"config.json", ISO.MARKER_NAME, D.REPORT_NAME, "notes-owner.txt", "thumb_cache", "modules_staging",
                "bambu_hms_texts.json", "restart-state.json", "restart-helper.log"}
    check("C10. в прежней папке осталось только непереносимое и чужое (config, кэш, отчёт, личный файл)",
          _left <= _allowed and "notes-owner.txt" in _left and "config.json" in _left
          and not any(D.classify(n, os.path.isdir(os.path.join(root, n))).action == D.MOVE for n in _left),
          sorted(_left))
    _rep = D.read_report(NEW) or {}
    check("C11. отчёт data-move-report.json в новой папке: выполнено, чужой файл владельца назван и оставлен",
          _rep.get("status") == "ok" and "notes-owner.txt" in [e.get("name") for e in _rep.get("unknown") or []]
          and (D.read_report(root) or {}).get("status") == "ok", {k: _rep.get(k) for k in ("status", "unknown", "left")})
    _day = time.strftime("%Y%m%d")
    _bk = set(os.listdir(os.path.join(NEW, "backups")))
    check("C12. ежедневные копии есть у всех баз, в том числе модулей (расчёт заказа, качество, склад)",
          {"%s_%s.db" % (t, _day) for t in ("cost", "quality", "inventory", "parts", "printers")} <= _bk, sorted(_bk))

    # Г. перенос в папку с конфликтом — программа остаётся на месте
    stop()
    os.makedirs(BLOCKED)
    with open(os.path.join(BLOCKED, "farm_parts.db"), "wb") as f:
        f.write(b"stale database of another farm")
    BLK_SHA = sha(os.path.join(BLOCKED, "farm_parts.db"))
    cfg = json.load(open(cfgp, encoding="utf-8"))
    cfg["data_dir"], cfg["migrate_from"] = BLOCKED, NEW     # как если бы папку заняли уже после выбора
    json.dump(cfg, open(cfgp, "w", encoding="utf-8"))
    NEW_FILES = files_under(NEW)
    proc, ok = start()
    check("D1. программа поднялась, хотя перенос не удался", ok)
    st, js = call("GET", "/api/storage")
    mv = js.get("data_move") or {}
    check("D2. КРИТИЧНО: программа осталась на прежней папке; причина видна; перенос ждёт повтора",
          D.same_path(js.get("data_dir", ""), NEW) and mv.get("status") == "failed" and mv.get("active") is True
          and mv.get("reason") == D.R_CONFLICT and D.same_path(js.get("data_dir_pending", ""), BLOCKED), js)
    st, js = call("GET", "/api/mod/cost/calculations/%s" % OID)
    check("D3. данные на месте: заказ, модули, катушка",
          js.get("internal_id") == OID and all((mods().get(m) or {}).get("state") == "loaded" for m in ZIPS)
          and call("GET", "/api/mod/inventory/summary")[1].get("spools") == 1, js)
    check("D4. КРИТИЧНО: чужая база в занятой папке не тронута, наших копий там нет",
          sha(os.path.join(BLOCKED, "farm_parts.db")) == BLK_SHA and set(os.listdir(BLOCKED)) == {"farm_parts.db"},
          sorted(os.listdir(BLOCKED)))
    #  -wal/-shm SQLite сам создаёт и убирает при открытии и закрытии баз; журнал и кэш превью пишет
    #  работающая программа — их из сравнения исключаем, всё остальное обязано остаться.
    _steady = {f for f in NEW_FILES if not f.startswith(("logs/", "thumb_cache/")) and not f.endswith(("-wal", "-shm"))}
    check("D5. КРИТИЧНО: ни один файл прежней папки не пропал",
          _steady <= files_under(NEW) and "farm_parts.db" in _steady and "install_id.txt" in _steady,
          sorted(_steady - files_under(NEW))[:10])
    check("D6. migrate_from сохранён: перенос повторится при следующем запуске",
          D.same_path(json.load(open(cfgp, encoding="utf-8")).get("migrate_from", ""), NEW))
    st, js = call("POST", "/api/storage/data", {"path": NEW})
    st2, js2 = call("GET", "/api/storage")
    check("D7. отказ от переноса: выбрать нынешнюю папку — ожидание снято, предупреждение больше не показывается",
          js.get("status") == "ok" and js.get("changed") is False and not js2.get("data_dir_pending")
          and (js2.get("data_move") or {}).get("active") is False
          and "migrate_from" not in json.load(open(cfgp, encoding="utf-8")), (js, js2))
finally:
    check("Z1. изолированный экземпляр остановлен", stop())
    shutil.rmtree(root, ignore_errors=True)
    shutil.rmtree(work, ignore_errors=True)

print("\n" + "=" * 76)
print("ИТОГО: PASS=%d FAIL=%d" % (len(names) - len(fails), len(fails)))
if fails:
    for f in fails:
        print("   - " + f)
    sys.exit(1)
sys.exit(0)
