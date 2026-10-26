# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
#  26.09.2026 — платные модули на НАСТОЯЩЕМ процессе программы, полностью офлайн.
#
#  Программа поднимается по-настоящему (python server.py в изолированном режиме app/e2e_isolation:
#  своя временная папка данных, свой config, свободный порт, свой замок, без трея, браузера,
#  обнаружения и принтеров) с одноразовыми ТЕСТОВЫМИ ключами (FM_LICENSE_TEST_KEYS — из исходников
#  они принимаются, собранной программой — никогда). Проверяется путь покупателя:
#    установка подписанных пакетов -> бесплатное работает, платное закрыто (402) -> импорт лицензии
#    -> платное открылось без перезапуска -> перезапуск: лицензия на месте -> подменённый пакет не
#    ставится и рабочая версия цела -> неоплаченное обновление отклонено -> ручное копирование нового
#    выпуска в папку модулей платное не открывает -> удаление лицензии закрывает платное.
#  11.10.2026 (стенд службы лицензий 043): «подождите» от службы (503 + Retry-After) — программа не
#  повторяет отметку раньше срока и не отдаёт её браузеру; отданная браузеру отметка не повторяется;
#  НАСТОЯЩИЕ «Складской учёт» и «Расчёт заказа» в платной сборке сами проверяют лицензию: без неё
#  просмотр работает, изменения — 402; лицензия склада не открывает расчёт; «остановить» от службы
#  закрывает изменения и после перезапуска.
#  Сеть наружу не нужна: всё, что делает программа, — на этом компьютере.
#
#  БЕЗОПАСНОСТЬ ПРОГОНА: рабочие DATA_DIR/config/БД/порт/замок не используются; принтерам ничего не
#  отправляется; временная папка удаляется в конце.
#
#  Запуск:  PYTHONIOENCODING=utf-8 python tools/test_licensing_process.py   (0 = пройдено)
# ============================================================================
import hashlib, io, json, os, re, secrets, shutil, socket, subprocess, sys, tempfile, time, urllib.error, urllib.request, zipfile
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tools"))
sys.dont_write_bytecode = True
from app import e2e_isolation as ISO  # noqa: E402
from app.licensing import fm_license_sdk as S  # noqa: E402
import module_package as MP  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402
from cryptography.hazmat.primitives import serialization  # noqa: E402

SRC = open(os.path.join(REPO, "server.py"), encoding="utf-8").read()
APP_VERSION = re.search(r'^APP_VERSION\s*=\s*"([^"]+)"', SRC, re.M).group(1)
PROD = os.path.join(os.environ.get("LOCALAPPDATA", ""), "3DIWELL")
fails, names = [], []


def check(name, ok, extra=""):
    names.append(name)
    print(("PASS" if ok else "FAIL") + " — " + name + (("  :: %s" % (extra,))[:600] if (not ok and extra != "") else ""), flush=True)
    if not ok:
        fails.append(name)


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


def listening(port):
    out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True, creationflags=0x08000000).stdout
    return any(len(l.split()) >= 5 and l.split()[3] == "LISTENING" and l.split()[1] == "127.0.0.1:%d" % port for l in out.splitlines())


def wait(fn, t):
    end = time.monotonic() + t
    while time.monotonic() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.5)
    return None


def call(method, path, body=None, raw=None, ctype=None):
    data = json.dumps(body).encode("utf-8") if body is not None else (raw if raw is not None else (b"" if method != "GET" else None))
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), data=data, method=method)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    if ctype:
        req.add_header("Content-Type", ctype)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8") or "{}")
        except Exception:
            return e.code, {}


def upload(path, filename, data, fields=None):
    b = "----fmlic" + secrets.token_hex(8)
    body = b""
    for k, v in (fields or {}).items():   # 10.10.2026: поля формы (согласие, ключ текстом)
        body += ("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n" % (b, k, v)).encode("utf-8")
    if filename is not None:
        body += (("--%s\r\nContent-Disposition: form-data; name=\"file\"; filename=\"%s\"\r\n"
                  "Content-Type: application/octet-stream\r\n\r\n") % (b, filename)).encode("utf-8") + data + b"\r\n"
    body += ("--%s--\r\n" % b).encode()
    return call("POST", path, raw=body, ctype="multipart/form-data; boundary=" + b)


# ── 10.10.2026, вариант 3: подставная служба лицензий на этом компьютере (127.0.0.1). Отвечает
#    подписанным fm-verdict тестовым ключом лицензий; режим ответа задаёт проверка.
import http.server  # noqa: E402
import threading  # noqa: E402
SVC = {"mode": ("ok", ""), "got": []}


class _Svc(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        req = json.loads(self.rfile.read(n).decode("utf-8"))
        SVC["got"].append(req)
        st, why = SVC["mode"]
        if st == "busy":                       # служба перегружена: неподписанная ошибка и Retry-After
            out = b'{"error":"service_unavailable"}'
            self.send_response(503)
            self.send_header("Content-Type", "application/json")
            self.send_header("Retry-After", "1")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)
            return
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        pl = {"schema_version": 1, "product_id": S.PRODUCT_ID, "license_id": req["license_id"], "machine": req["machine"],
              "nonce": req["nonce"], "status": st, "reason": why, "checked_at": now}
        out = json.dumps(S.sign_document(S.FORMAT_VERDICT, pl, LK, "e2e-lic")).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)


def pub(key):
    return S.b64u_encode(key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw))


def tree_hash(d):
    h = hashlib.sha256()
    for base, dirs, files in sorted(os.walk(d)):
        dirs[:] = sorted(x for x in dirs if x != "__pycache__")
        for n in sorted(files):
            p = os.path.join(base, n)
            h.update(os.path.relpath(p, d).encode("utf-8"))
            h.update(open(p, "rb").read())
    return h.hexdigest()


root = tempfile.mkdtemp(prefix="fm_e2e_lic_")
assert not os.path.normcase(root).startswith(os.path.normcase(PROD)), "временная папка внутри рабочей!"
work = os.path.join(root, "_work")
os.makedirs(work)
LK, PK, OK = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
TRUST = [{"key_id": "e2e-lic", "purpose": "license", "public_key": pub(LK), "label": "e2e", "test": True},
         {"key_id": "e2e-pkg", "purpose": "package", "public_key": pub(PK), "label": "e2e", "test": True}]
trust_file = os.path.join(work, "trust.json")
# 16.10.2026 (R-150): второй доверенный ключ пакетов — «подписан другим ключом». Только в списке
# программы; в пакеты встраивается прежний TRUST.
QK = Ed25519PrivateKey.generate()
json.dump(TRUST + [{"key_id": "e2e-pkg2", "purpose": "package", "public_key": pub(QK), "label": "e2e2", "test": True}],
          open(trust_file, "w", encoding="utf-8"))
DEMO_FREE = os.path.join(REPO, "examples", "modules", "demo_free")
DEMO_PAID = os.path.join(REPO, "examples", "modules", "demo_paid")
PAID_ARGS = dict(licensing="freemium", paid_features=["pro_report"], edition="pro", embed_sdk=True, embed_trust=TRUST)


def write(name, data):
    p = os.path.join(work, name)
    open(p, "wb").write(data)
    return p


zfree, _ = MP.build_package(DEMO_FREE, PK, "e2e-pkg", "2026-09-26T00:00:00Z", "free")
zpaid, _ = MP.build_package(DEMO_PAID, PK, "e2e-pkg", "2027-09-20T00:00:00Z", **PAID_ARGS)
newsrc = os.path.join(work, "demo_paid_110")
shutil.copytree(DEMO_PAID, newsrc)
_mj = json.load(open(os.path.join(newsrc, "module.json"), encoding="utf-8"))
_mj["version"] = "1.1.0"
json.dump(_mj, open(os.path.join(newsrc, "module.json"), "w", encoding="utf-8"), ensure_ascii=False)
znew, _ = MP.build_package(newsrc, PK, "e2e-pkg", "2027-10-10T00:00:00Z", **PAID_ARGS)
# подменённый пакет: подпись настоящая, но в backend.py дописана строка
_zin = zipfile.ZipFile(io.BytesIO(zpaid))
_buf = io.BytesIO()
with zipfile.ZipFile(_buf, "w") as _zo:
    for _n in _zin.namelist():
        _d = _zin.read(_n)
        if _n.endswith("/backend.py"):
            _d += b"\n# tampered\n"
        _zo.writestr(_n, _d)
ztamper = _buf.getvalue()
p_free, p_paid, p_new, p_tamper = (write("free.zip", zfree), write("paid.zip", zpaid), write("paid_110.zip", znew),
                                   write("tamper.zip", ztamper))
# 11.10.2026: настоящие «Складской учёт» и «Расчёт заказа» в платной сборке (подпись тестовым ключом пакетов)
PAID_REAL = dict(licensing="paid", edition="standard", embed_sdk=True, embed_trust=TRUST)
zinv, _ = MP.build_package(os.path.join(REPO, "modules", "inventory"), PK, "e2e-pkg", "2026-10-11T12:00:00Z", **PAID_REAL)
zcost, _ = MP.build_package(os.path.join(REPO, "modules", "cost"), PK, "e2e-pkg", "2026-10-11T12:00:00Z", **PAID_REAL)
p_inv, p_cost = write("inventory_paid.zip", zinv), write("cost_paid.zip", zcost)
# 16.10.2026 (R-150): тот же demo_free без подписи и подписанный другим доверенным ключом.
_ubuf = io.BytesIO()
with zipfile.ZipFile(_ubuf, "w") as _zo:
    for _b, _ds, _fs in os.walk(DEMO_FREE):
        _ds[:] = [x for x in _ds if x != "__pycache__"]
        for _n in _fs:
            _p = os.path.join(_b, _n)
            _zo.write(_p, "demo_free/" + os.path.relpath(_p, DEMO_FREE).replace(os.sep, "/"))
zfree_q, _ = MP.build_package(DEMO_FREE, QK, "e2e-pkg2", "2026-09-26T00:00:00Z", "free")
p_free_unsigned, p_free_q = write("free_unsigned.zip", _ubuf.getvalue()), write("free_q.zip", zfree_q)


def audit_rows(action):
    import sqlite3
    try:
        c = sqlite3.connect("file:%s?mode=ro" % os.path.join(root, "farm_parts.db").replace(os.sep, "/"), uri=True)
        try:
            return [tuple(r) for r in c.execute("SELECT username, action, target, result FROM audit_log WHERE action=?", (action,))]
        finally:
            c.close()
    except Exception as e:
        return [("error", repr(e))]


def license_doc(key=LK, key_id="e2e-lic", **over):
    body = {"schema_version": 1, "product_id": S.PRODUCT_ID, "license_id": "L-E2E-1",
            "grants": [{"module_id": "demo_paid", "edition": "pro", "features": ["pro_report"]}],
            "use_type": "perpetual", "updates_before": "2027-10-01T00:00:00Z", "issued_at": "2026-09-26T00:00:00Z"}
    body.update(over)
    return S.dump_document(S.sign_document(S.FORMAT_LICENSE, body, key, key_id))


port = free_port()
token = "LIC_E2E_" + secrets.token_hex(8)
with open(os.path.join(root, ISO.MARKER_NAME), "w", encoding="utf-8") as f:
    json.dump({"token": token, "sentinel": "LIC_E2E_0926"}, f)
cfgp = os.path.join(root, "config.json")
json.dump({"server_port": port}, open(cfgp, "w", encoding="utf-8"))
env = dict(os.environ)
env.update({ISO.ENV_SENTINEL: token, ISO.ENV_INSTANCE: "e2e", ISO.ENV_DATA_DIR: root, ISO.ENV_CONFIG: cfgp,
            ISO.ENV_MUTEX: "Local\\3DIWELL_FM_E2E_LIC_" + secrets.token_hex(6), ISO.ENV_PORT: str(port),
            ISO.ENV_NO_TRAY: "1", ISO.ENV_NO_BROWSER: "1", ISO.ENV_NO_DISCOVERY: "1", ISO.ENV_NO_PRINTERS: "1",
            ISO.ENV_NO_MODULES: "0", "FM_LICENSE_TEST_KEYS": trust_file, "PYTHONDONTWRITEBYTECODE": "1"})
svc_port = free_port()
_svc = http.server.ThreadingHTTPServer(("127.0.0.1", svc_port), _Svc)
threading.Thread(target=_svc.serve_forever, daemon=True).start()
env["FM_LICENSE_TEST_SERVICE"] = "http://127.0.0.1:%d/mark" % svc_port
proc = None


def start():
    p = subprocess.Popen([sys.executable, os.path.join(REPO, "server.py"), ISO.FLAG, "--desktop-start", "--no-browser"],
                         cwd=REPO, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, creationflags=(0x00000008 | 0x00000200))
    ok = wait(lambda: call("GET", "/version")[1].get("version") == APP_VERSION if listening(port) else None, 150)
    return p, bool(ok)


def stop():
    with open(os.path.join(root, "stop.request"), "w", encoding="utf-8") as f:
        f.write(token)
    gone = wait(lambda: not listening(port), 60)
    if not gone and proc is not None and proc.poll() is None:
        proc.terminate()   # только СВОЙ процесс; рабочую программу не трогаем
        gone = wait(lambda: not listening(port), 20)
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


def mod(mid):
    return next((m for m in call("GET", "/api/modules")[1].get("modules", []) if m["id"] == mid), {})


print("изолированный экземпляр: порт %d, папка %s" % (port, root))
proc, ok = start()
check("A1. изолированный экземпляр поднялся (своя папка, порт, замок; тестовые ключи из переменной)", ok)
try:
    st, js = call("POST", "/api/modules/install-path", {"path": p_free})
    check("A2. подписанный бесплатный пакет установлен", st == 200 and js.get("status") == "ok" and js.get("package") == "verified", js)
    st, js = call("POST", "/api/modules/install-path", {"path": p_paid})
    check("A3. подписанный платный пакет 1.0.0 установлен", st == 200 and js.get("status") == "ok" and js.get("package") == "verified", js)
    # P. 16.10.2026 (R-150, аудит paid-boundary-17): подписанный модуль не заменяется молча файлом
    #    без подписи или подписанным другим ключом — только после явного подтверждения.
    live_free = os.path.join(root, "modules", "demo_free")
    before_free = tree_hash(live_free)
    st, js = call("POST", "/api/modules/install-path", {"path": p_free_unsigned})
    _stg = os.path.join(root, "modules_staging")
    check("P1. неподписанный файл поверх подписанного модуля: «нужно подтверждение», файлы модуля не тронуты",
          st == 200 and js.get("status") == "confirm_required" and js.get("reason") == "signed_replaced"
          and js.get("id") == "demo_free" and js.get("new_signed") is False
          and tree_hash(live_free) == before_free
          and not [x for x in (os.listdir(_stg) if os.path.isdir(_stg) else []) if x.startswith("demo_free-")], js)
    st, js = upload("/api/modules/install?confirm_provenance=1", "demo_free.zip", open(p_free_unsigned, "rb").read())
    check("P2. с подтверждением (загрузка из браузера) неподписанный заменил подписанный, ответ говорит об этом",
          st == 200 and js.get("status") == "ok" and js.get("package") == "unsigned"
          and js.get("replaced_signed") is True and tree_hash(live_free) != before_free, js)
    check("P3. замена подписанного модуля записана в журнал аудита",
          any(r[1] == "module.replace_signed" and "demo_free" in r[2] and r[3] == "confirmed"
              for r in audit_rows("module.replace_signed")), audit_rows("module.replace_signed"))
    st, js = call("POST", "/api/modules/install-path", {"path": p_free})
    check("P4. подписанный поверх неподписанного ставится без вопроса",
          js.get("status") == "ok" and js.get("package") == "verified" and js.get("replaced_signed") is False, js)
    before_free = tree_hash(live_free)
    st, js = call("POST", "/api/modules/install-path", {"path": p_free_q})
    check("P5. подписанный ДРУГИМ ключом поверх подписанного: «нужно подтверждение», файлы не тронуты",
          js.get("status") == "confirm_required" and js.get("reason") == "signed_replaced"
          and js.get("new_signed") is True and tree_hash(live_free) == before_free, js)
    st, js = call("POST", "/api/modules/install-path", {"path": p_free_q, "confirm_provenance": True})
    check("P6. с подтверждением (установка по пути) заменён", js.get("status") == "ok" and js.get("package") == "verified"
          and js.get("replaced_signed") is True, js)
    st, js = call("POST", "/api/modules/install-path", {"path": p_free_q})
    check("P7. повторная установка тем же ключом — без вопроса", js.get("status") == "ok" and js.get("replaced_signed") is False, js)
    st, js = call("POST", "/api/modules/install-path", {"path": p_free, "confirm_provenance": "1"})
    check("P8. подтверждение принимается только как true: строка «1» в установке по пути — снова вопрос",
          js.get("status") == "confirm_required", js)
    st, js = call("POST", "/api/modules/install-path", {"path": p_free, "confirm_provenance": True})
    check("P9. исходный подписанный demo_free возвращён на место", js.get("status") == "ok" and js.get("package") == "verified", js)
    restart("A4")
    fm, pm = mod("demo_free"), mod("demo_paid")
    check("B1. оба модуля загружены: бесплатный «лицензия не нужна», платный «нет лицензии»",
          fm.get("state") == "loaded" and (fm.get("licensing") or {}).get("license") == "not_required"
          and pm.get("state") == "loaded" and (pm.get("licensing") or {}).get("license") == "missing", (fm, pm))
    st, js = call("GET", "/api/mod/demo_free/hello")
    check("B2. бесплатный модуль работает без всякой лицензии", st == 200 and js.get("ok") is True, (st, js))
    st, js = call("GET", "/api/mod/demo_paid/status")
    check("B3. бесплатная часть платного модуля работает без лицензии", st == 200 and js.get("free_part") is True
          and js.get("pro_report_available") is False, (st, js))
    st, js = call("GET", "/api/mod/demo_paid/report")
    check("B4. КРИТИЧНО: платная функция без лицензии закрыта (402), обработчик не вызван",
          st == 402 and js.get("reason") == "license_required" and "checked_by" not in js, (st, js))
    st, js = call("GET", "/api/licenses")
    check("B5. окно лицензий: номер установки, запрос активации, тестовые ключи отмечены",
          st == 200 and js.get("install_id", "").startswith("fm-") and js.get("test_keys") is True
          and js.get("activation_request", {}).get("install_id") == js.get("install_id")
          and any(m["module_id"] == "demo_paid" for m in js.get("modules", [])), js)
    st, js = upload("/api/licenses/import", "L-E2E-1.fmlic", license_doc())
    check("C0. без согласия на передачу номера лицензии и номера компьютера лицензия не принимается",
          js.get("status") == "error" and js.get("reason") == "consent_required"
          and not os.path.exists(os.path.join(root, "licenses", "L-E2E-1.fmlic")), js)
    st, js = upload("/api/licenses/import", "forged.fmlic", license_doc(OK, "e2e-lic"), {"consent": "1"})
    check("C1. поддельная лицензия отклонена", js.get("status") == "error" and js.get("code") == S.R_BAD_SIGNATURE, js)
    check("C1б. согласие вместе с отклонённой лицензией не записалось", call("GET", "/api/licenses")[1].get("consent") is False)
    st, js = upload("/api/licenses/import", None, None, {"text": S.encode_key(license_doc()), "consent": "1"})
    check("C2. настоящая лицензия принята КЛЮЧОМ ТЕКСТОМ (FMK1.…) с согласием",
          js.get("status") == "ok" and js.get("kind") == "license" and js.get("license_id") == "L-E2E-1", js)
    st, js = call("GET", "/api/mod/demo_paid/report")
    check("C3. платная функция открылась без перезапуска; компонент проверил лицензию сам",
          st == 200 and js.get("checked_by") == "component" and js.get("license_id") == "L-E2E-1", (st, js))
    restart("C4")
    st, js = call("GET", "/api/mod/demo_paid/report")
    check("C5. после перезапуска лицензия на месте, платное работает (офлайн, без сервера поставщика)",
          st == 200 and js.get("checked_by") == "component", (st, js))
    # V. Вариант 3: программа сама отмечается у службы лицензий; ответ «остановить» закрывает платное,
    #    «работает» — открывает; ответ через браузер принимается только на свою последнюю отметку.
    first = wait(lambda: SVC["got"][:1], 30)
    keys = set((first or [{}])[0].keys())
    check("V1. после ввода ключа программа сама отметилась у службы — ровно эти поля, без имён, адресов и данных фермы",
          bool(first) and keys == {"schema_version", "product_id", "license_id", "proof", "machine", "module_id",
                                   "module_version", "fm_version", "nonce", "via"}
          and first[0]["via"] == "direct" and first[0]["license_id"] == "L-E2E-1"
          and first[0]["proof"] == S.license_proof(license_doc()) and re.fullmatch(r"[0-9a-f]{64}", first[0]["machine"]), first)
    st, js = call("GET", "/api/licenses")
    row = next((l for l in js.get("licenses", []) if l.get("license_id") == "L-E2E-1"), {})
    check("V2. окно лицензий: номер компьютера XXXX-XXXX, согласие дано, служба задана, «Что передаётся» показывает отметку",
          re.fullmatch(r"[0-9A-F]{4}-[0-9A-F]{4}", js.get("machine", "")) and js.get("consent") is True
          and (js.get("service") or {}).get("configured") is True and row.get("service_state") == "ok"
          and any(r.get("license_id") == "L-E2E-1" for r in (js.get("transmitted") or {}).get("requests", [])), (js.get("machine"), row))
    SVC["mode"] = ("stop", "seat_taken")
    n0 = len(SVC["got"])
    upload("/api/licenses/import", "L-E2E-1.fmlic", license_doc())     # повторный ввод — отметиться снова
    wait(lambda: len(SVC["got"]) > n0, 30)
    stopped = wait(lambda: call("GET", "/api/mod/demo_paid/report")[0] == 402, 20)
    st, js = call("GET", "/api/mod/demo_paid/report")
    pm = mod("demo_paid")
    check("V3. КРИТИЧНО: служба ответила «ключ уже на другом компьютере» — платное закрыто (402), модуль помечен «остановлена»",
          bool(stopped) and st == 402 and js.get("code") == "license_stopped"
          and (pm.get("licensing") or {}).get("license") == "license_stopped", (st, js, pm.get("licensing")))
    st, js = call("GET", "/api/mod/demo_paid/status")
    check("V4. бесплатная часть модуля при остановленной лицензии работает", st == 200 and js.get("free_part") is True, (st, js))
    #  Служба перегружена: 503 + Retry-After. Программа не повторяет отметку и не отдаёт её браузеру,
    #  пока не пройдёт пауза (не короче 30 секунд).
    SVC["mode"] = ("busy", "")
    n1 = len(SVC["got"])
    upload("/api/licenses/import", "L-E2E-1.fmlic", license_doc())     # новый ввод — отметиться сразу
    wait(lambda: len(SVC["got"]) > n1, 30)
    time.sleep(3)
    st, js = call("GET", "/api/licenses?relay=1")
    check("V5а. служба ответила «подождите» (503): программа отметилась один раз, браузеру отметку не отдала, пауза записана",
          len(SVC["got"]) == n1 + 1 and js.get("mark_requests") == [] and bool((js.get("transmitted") or {}).get("backoff_until")),
          (len(SVC["got"]) - n1, js.get("mark_requests"), (js.get("transmitted") or {}).get("backoff_until")))
    check("V5б. «подождите» — не «остановить»: прежнее состояние лицензии (остановлена) не изменилось",
          call("GET", "/api/mod/demo_paid/report")[0] == 402)
    time.sleep(31)
    st, js = call("GET", "/api/licenses?relay=1")
    req = next((r for r in js.get("mark_requests", []) if r.get("license_id") == "L-E2E-1"), None)
    check("V5. после паузы отметка отдана браузеру — со свежим случайным числом и via=browser",
          bool(req) and req.get("nonce") and req.get("via") == "browser" and len(SVC["got"]) == n1 + 1, js.get("mark_requests"))
    st, js2 = call("GET", "/api/licenses?relay=1")
    check("V5в. отданная браузеру отметка повторно не отдаётся (оба канала ждут его ответа)",
          not any(r.get("license_id") == "L-E2E-1" for r in js2.get("mark_requests", [])) and len(SVC["got"]) == n1 + 1,
          js2.get("mark_requests"))
    SVC["mode"] = ("ok", "")
    if req:
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 2))
        good = S.sign_document(S.FORMAT_VERDICT, {"schema_version": 1, "product_id": S.PRODUCT_ID, "license_id": "L-E2E-1",
                                                  "machine": req["machine"], "nonce": req["nonce"], "status": "ok", "reason": "",
                                                  "checked_at": now}, LK, "e2e-lic")
        foreign = S.sign_document(S.FORMAT_VERDICT, dict(good["payload"], machine="0" * 64), LK, "e2e-lic")
        st, js = upload("/api/licenses/import", None, None, {"text": json.dumps(foreign)})
        check("V6. ответ службы для ДРУГОГО компьютера не принят", js.get("status") == "error" and js.get("code") == "verdict_foreign", js)
        st, js = upload("/api/licenses/import", None, None, {"text": json.dumps(good)})
        check("V7. ответ «работает», принесённый браузером (перенос подтверждён), принят — платное открылось",
              js.get("status") == "ok" and js.get("kind") == "verdict" and js.get("service_state") == "ok"
              and call("GET", "/api/mod/demo_paid/report")[0] == 200, js)
        st, js = upload("/api/licenses/import", None, None, {"text": json.dumps(good)})
        check("V8. тот же ответ повторно не принимается (ответ только на последнюю отметку)",
              js.get("status") == "error" and js.get("code") == "verdict_stale", js)
    st, js = upload("/api/licenses/import", None, None, {"relay_license_id": "L-E2E-1", "relay_status": "429",
                                                         "relay_retry_after": "120"})
    bu = (call("GET", "/api/licenses")[1].get("transmitted") or {}).get("backoff_until", "")
    check("V9. браузер передал «слишком часто» (429, Retry-After 120 с): программа поставила паузу для всех отметок ~2 минуты",
          js.get("kind") == "relay_noted" and bu >= time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 100)), (js, bu))
    _mf = os.path.join(root, "licenses", "marks.json")

    def _clear_pause():
        """Паузу снимает проверка, чтобы идти дальше (вместе с записью, когда и на сколько её поставили)."""
        _m = json.load(open(_mf, encoding="utf-8"))
        for _k in ("backoff_until", "backoff_set_at", "backoff_s"):
            _m.pop(_k, None)
        json.dump(_m, open(_mf, "w", encoding="utf-8"))

    def _iso(sec):
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + sec))

    def _pause():
        return (call("GET", "/api/licenses")[1].get("transmitted") or {}).get("backoff_until", "")

    #  17.10.2026 (ответ службы 043): Retry-After датой HTTP и дольше суток — через настоящий /api/licenses/import.
    import email.utils as _eu
    _clear_pause()
    st, js = upload("/api/licenses/import", None, None, {"relay_license_id": "L-E2E-1", "relay_status": "503",
                                                         "relay_retry_after": _eu.formatdate(time.time() + 7200, usegmt=True)})
    bu = _pause()
    check("V9б. браузер передал 503 и Retry-After датой HTTP через 2 часа — пауза для всех отметок 2 часа",
          js.get("kind") == "relay_noted" and _iso(7200 - 100) <= bu <= _iso(7200 + 100), (js, bu))
    _clear_pause()
    n9 = len(SVC["got"])
    st, js = upload("/api/licenses/import", None, None, {"relay_license_id": "L-E2E-1", "relay_status": "429",
                                                         "relay_retry_after": str(3 * 86400)})
    bu = _pause()
    check("V9в. браузер передал 429 и Retry-After 3 суток — пауза 3 суток (не сокращена до суток)",
          js.get("kind") == "relay_noted" and _iso(3 * 86400 - 100) <= bu <= _iso(3 * 86400 + 100), (js, bu))
    upload("/api/licenses/import", "L-E2E-1.fmlic", license_doc())     # повторный ввод ключа во время паузы
    upload("/api/licenses/import", None, None, {"text": S.encode_key(license_doc())})
    time.sleep(3)
    _r1 = call("GET", "/api/licenses?relay=1")[1].get("mark_requests")
    _r2 = call("GET", "/api/licenses?relay=1")[1].get("mark_requests")
    check("V9г. КРИТИЧНО: во время паузы 3 суток повторный ввод ключа (файлом и текстом) и окно лицензий не отправляют "
          "отметок ни напрямую, ни через браузер; пауза та же",
          len(SVC["got"]) == n9 and _r1 == [] and _r2 == [] and _pause() == bu, (len(SVC["got"]) - n9, _r1, _r2, _pause(), bu))
    _clear_pause()
    st, js = upload("/api/licenses/import", None, None, {"relay_license_id": "L-E2E-1", "relay_status": "network"})
    _nx = (json.load(open(_mf, encoding="utf-8")).get("next") or {}).get("L-E2E-1", "")
    check("V9д. браузер сообщил «нет связи со службой» — следующая отметка через 15 минут (не 6 часов, как при отказе), "
          "общей паузы нет", js.get("kind") == "relay_noted" and _iso(15 * 60 - 100) <= _nx <= _iso(15 * 60 + 100)
          and _pause() == "", (js, _nx, _pause()))
    _clear_pause()
    SVC["mode"] = ("ok", "")
    live = os.path.join(root, "modules", "demo_paid")
    before = tree_hash(live)
    st, js = call("POST", "/api/modules/install-path", {"path": p_tamper})
    check("D1. КРИТИЧНО: подменённый пакет не установлен (подпись не сходится с файлами)",
          js.get("status") == "error" and js.get("reason") == "package_integrity", js)
    check("D2. рабочая версия после отказа не тронута ни одним байтом", tree_hash(live) == before)
    st, js = call("POST", "/api/modules/install-path", {"path": p_new})
    check("D3. КРИТИЧНО: выпуск 1.1.0 вне оплаченных обновлений не заменил рабочую 1.0.0",
          js.get("status") == "error" and js.get("reason") == "update_not_covered" and tree_hash(live) == before, js)
    st, js = call("POST", "/api/modules/install-path", {"path": p_paid})
    check("D4. повторная установка купленного выпуска разрешена; прежняя копия сохранена",
          js.get("status") == "ok" and js.get("previous_kept") is True
          and os.path.isdir(os.path.join(root, "modules_previous", "demo_paid")), js)
    # ручное копирование нового выпуска в папку модулей (мимо установщика)
    stop()
    shutil.rmtree(live)
    with zipfile.ZipFile(io.BytesIO(znew)) as z:
        z.extractall(os.path.join(root, "modules"))
    proc, ok = start()
    check("E1. экземпляр поднялся после ручного копирования нового выпуска", ok)
    pm = mod("demo_paid")
    st, js = call("GET", "/api/mod/demo_paid/report")
    check("E2. КРИТИЧНО: ручное копирование не открыло неоплаченный выпуск (ядро: «не покрыт», 402)",
          pm.get("version") == "1.1.0" and (pm.get("licensing") or {}).get("license") == S.R_UPDATE_NOT_COVERED
          and st == 402 and js.get("code") == S.R_UPDATE_NOT_COVERED, (pm.get("licensing"), st, js))
    with open(os.path.join(root, "modules", "demo_paid", "backend.py"), "a", encoding="utf-8") as f:
        f.write("\n# правка после установки\n")
    restart("E3")
    pm = mod("demo_paid")
    st, js = call("GET", "/api/mod/demo_paid/status")
    check("E4. КРИТИЧНО: изменённый после установки подписанный модуль не запущен, отмечен «повреждён»",
          pm.get("state") == "integrity_failed" and st == 404, (pm, st))
    st, js = call("POST", "/api/modules/install-path", {"path": p_paid})
    restart("E5")
    st, js = call("DELETE", "/api/licenses/L-E2E-1")
    check("F1. лицензия удалена", js.get("status") == "ok", js)
    st, js = call("GET", "/api/mod/demo_paid/report")
    check("F2. после удаления платное закрыто сразу, бесплатное работает",
          st == 402 and call("GET", "/api/mod/demo_paid/status")[0] == 200, (st, js))
    check("F3. данные модулей и программы на месте: папка данных цела",
          os.path.isfile(os.path.join(root, "farm_parts.db")) or os.path.isdir(os.path.join(root, "modules")))
    # G. Замена модуля оборвалась посреди (сбой питания между двумя переименованиями): рабочая
    #    версия уже в modules_previous, новой на месте нет. При запуске она должна вернуться сама.
    stop()
    live = os.path.join(root, "modules", "demo_paid")
    prev = os.path.join(root, "modules_previous", "demo_paid")
    if os.path.isdir(prev):
        shutil.rmtree(prev)
    os.makedirs(os.path.dirname(prev), exist_ok=True)
    os.replace(live, prev)
    stg = os.path.join(root, "modules_staging")
    os.makedirs(os.path.join(stg, "demo_paid-deadbeef"), exist_ok=True)   # остаток распаковки
    json.dump({"id": "demo_paid", "restore_from": prev}, open(os.path.join(stg, "demo_paid.swap.json"), "w", encoding="utf-8"))
    proc, ok = start()
    st, js = call("GET", "/api/mod/demo_paid/status")
    check("G1. КРИТИЧНО: после оборванной замены прежняя версия вернулась сама и работает",
          ok and st == 200 and os.path.isdir(live) and not os.path.exists(prev), (ok, st))
    check("G2. журнал замены и остатки распаковки убраны",
          not os.path.exists(os.path.join(stg, "demo_paid.swap.json")) and not os.path.exists(os.path.join(stg, "demo_paid-deadbeef")))
    # M. Настоящие «Складской учёт» и «Расчёт заказа» в ПЛАТНОЙ сборке: лицензию проверяет сам модуль.
    st, js = call("POST", "/api/modules/install-path", {"path": p_inv})
    check("M1. платная сборка склада установлена (подписана, со своей копией SDK, ключей и самопроверки)",
          js.get("status") == "ok" and js.get("package") == "verified", js)
    st, js = call("POST", "/api/modules/install-path", {"path": p_cost})
    check("M2. платная сборка расчёта заказа установлена", js.get("status") == "ok" and js.get("package") == "verified", js)
    restart("M3")
    im, cm = mod("inventory"), mod("cost")
    check("M4. оба модуля загружены; ядро видит «нужна лицензия»",
          im.get("state") == "loaded" and cm.get("state") == "loaded"
          and (im.get("licensing") or {}).get("license") == "missing" and (cm.get("licensing") or {}).get("license") == "missing",
          (im.get("state"), im.get("licensing"), cm.get("state"), cm.get("licensing")))
    st, js = call("GET", "/api/mod/inventory/locations")
    check("M5. без лицензии склад виден (просмотр открыт)", st == 200 and isinstance(js.get("locations"), list), (st, js))
    st, js = call("POST", "/api/mod/inventory/location", {"name": "E2E shelf"})
    check("M6. КРИТИЧНО: без лицензии изменение склада закрыто — 402 от САМОГО модуля",
          st == 402 and js.get("checked_by") == "module" and js.get("reason") == "license_required", (st, js))
    st, js = call("GET", "/api/mod/inventory/settings")
    check("M7. склад сообщает своему окну «только просмотр»", (js.get("license") or {}).get("paid") is True
          and (js.get("license") or {}).get("ok") is False, js.get("license"))
    st, js = call("POST", "/api/mod/cost/calculate", {"order": {}})
    st2, js2 = call("GET", "/api/mod/cost/calculations")
    check("M8. без лицензии расчёт закрыт (402 от модуля), сохранённые заказы видны",
          st == 402 and js.get("checked_by") == "module" and st2 == 200, (st, js, st2))
    inv_lic = license_doc(license_id="L-E2E-INV", grants=[{"module_id": "inventory", "edition": "standard", "features": ["*"]}],
                          updates_before="2027-10-12T00:00:00Z")
    st, js = upload("/api/licenses/import", None, None, {"text": S.encode_key(inv_lic)})
    check("M9. ключ склада принят", js.get("status") == "ok" and js.get("license_id") == "L-E2E-INV", js)
    st, js = call("POST", "/api/mod/inventory/location", {"name": "E2E shelf"})
    check("M10. с ключом склада изменение склада работает (модуль проверил лицензию сам)", st == 200, (st, js))
    st, js = call("POST", "/api/mod/cost/calculate", {"order": {}})
    check("M11. КРИТИЧНО: лицензия склада не открывает расчёт заказа", st == 402, (st, js))
    first_inv = wait(lambda: [r for r in SVC["got"] if r.get("license_id") == "L-E2E-INV"][:1], 30)
    _inv_rel = __import__("app.module_catalog", fromlist=["KNOWN_MODULE_RELEASES"]).KNOWN_MODULE_RELEASES.get("inventory")
    check("M12. отметка по ключу склада ушла с module_id=inventory и версией модуля, как в каталоге программы (%s)" % _inv_rel,
          bool(first_inv) and first_inv[0].get("module_id") == "inventory" and first_inv[0].get("module_version") == _inv_rel,
          first_inv)
    SVC["mode"] = ("stop", "seat_taken")
    n2 = len(SVC["got"])
    upload("/api/licenses/import", "L-E2E-INV.fmlic", inv_lic)          # повторный ввод — отметиться снова
    wait(lambda: len(SVC["got"]) > n2, 30)
    closed = wait(lambda: call("POST", "/api/mod/inventory/location", {"name": "E2E shelf 2"})[0] == 402, 30)
    st, js = call("POST", "/api/mod/inventory/location", {"name": "E2E shelf 2"})
    check("M13. КРИТИЧНО: служба ответила «ключ на другом компьютере» — модуль сам закрыл изменения (license_stopped)",
          bool(closed) and st == 402 and js.get("code") == "license_stopped" and js.get("checked_by") == "module", (st, js))
    check("M14. данные склада при этом видны", call("GET", "/api/mod/inventory/locations")[0] == 200)
    SVC["mode"] = ("ok", "")
    restart("M15")
    st, js = call("POST", "/api/mod/inventory/location", {"name": "E2E shelf 3"})
    check("M16. после перезапуска остановка сохранилась (ответ службы хранится на диске, новой отметки до срока нет)", st == 402 and js.get("code") == "license_stopped", (st, js))
finally:
    check("Z1. изолированный экземпляр остановлен", stop())
    shutil.rmtree(root, ignore_errors=True)

print("\n" + "=" * 76)
if fails:
    print("FAIL: провалено %d из %d" % (len(fails), len(names)))
    for f in fails:
        print("   - " + f)
    sys.exit(1)
print("PASS: все %d проверок пройдены" % len(names))
sys.exit(0)
