# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
# ============================================================================
#  17.10.2026 — приёмка H09: итог отметки лицензий через браузер виден и на телефоне.
#
#  Было: администратор открыл программу с телефона — страница сразу относит отметку службе
#  лицензий (licLoad при открытии главной страницы), но на телефоне ничего не видно: вкладки
#  «Настройки → Модули» в узкой раскладке нет, результат владелец мог проверить только позже,
#  на компьютере. Стало: итог отметки — одно сообщение (на телефоне — в углу экрана .fm-toasts,
#  на компьютере — в панели «Подсказки»).
#
#  ЧТО ПРОВЕРЯЕТСЯ на настоящей странице (стенд tools/_fm_ui_stage.py: настоящие web/index.html и
#  app.js, ответы /api синтетические, сервер программы не запускается) с ПОДДЕЛЬНОЙ службой
#  лицензий — маленьким сервером этого набора на 127.0.0.1 (с CORS, как у настоящей службы).
#  Настоящая служба, принтеры и данные фермы не трогаются.
#    A. телефон 390×844: служба ответила «работает» — сообщение в углу, с временем, влезает в экран;
#       служба получила ровно одну отметку с пометкой via: browser;
#    B. телефон 360×740: «остановлена: ключ на другом компьютере» — предупреждение со словами причины,
#       влезает в экран;
#    C. служба отказала (HTTP 403) — предупреждение «служба отказала (HTTP 403) … попробует ещё раз»;
#    D. программа не приняла ответ службы — предупреждение «ответ … не принят»;
#    E. служба просит подождать (429) — молчим, вторую отметку не шлём;
#    F. администратор не вошёл (оператор): программа не отдаёт отметки — службе ничего, сообщения нет;
#    G. служба недоступна с этого устройства — молчим;
#    H. отметок, которые пора отправить, нет — службе ничего, сообщения нет;
#    I. адрес службы не задан — службе ничего, сообщения нет;
#    J. английский интерфейс — сообщение по-английски;
#    K. компьютер 1600×1000, «Настройки → Модули», две лицензии (работает + остановлена) — ОДНО
#       сообщение в панели «Подсказки», худшее состояние со счётом; строки лицензий — с теми же словами;
#    L. телефон 390×844: служба аннулировала лицензию — предупреждение «АННУЛИРОВАНА — платные функции
#       закрыты», влезает в экран;
#    M. телефон 390×844, две отметки: первую служба приняла, на вторую отказала (HTTP 403) — два
#       сообщения (итог ответа и отказ), оба влезают в экран;
#    N. компьютер, три лицензии (работает + аннулирована + остановлена) — одно сообщение, худшее
#       состояние «АННУЛИРОВАНА (1 из 3)».
#    O. 17.10.2026 (ответ службы 043): что страница сообщает программе, когда служба ответа не дала, и
#       какую паузу по этому сообщению ставит программа (та же функция LicenseService.note_relay, что
#       в /api/licenses/import): 429 с Retry-After 3600, 3 суток и датой HTTP — если служба открыла
#       заголовок (Access-Control-Expose-Headers), пауза ровно такая; не открыла — страница его не
#       видит, пауза 15 минут (это требование к службе); ответ 429 без заголовков CORS и служба
#       недоступна — «нет связи», следующая попытка через 15 минут.
#  Консоль страницы чистая. В вариантах, где служба отвечает ошибкой или недоступна, браузер сам
#  пишет строку о неудачном запросе к адресу службы — это не ошибка страницы, такие строки
#  отделяются по адресу поддельной службы.
#
#  Запуск:  python tools/test_license_relay_status_ui.py   (0 = пройдено)
# ============================================================================
import datetime
import email.utils
import html
import json
import os
import re
import shutil
import socket
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "tools"))
import _fm_ui_stage as stage  # noqa: E402
from app.licensing import service as SV  # noqa: E402

FAILED = []
PASSED = [0]


def check(name, ok, extra=""):
    if ok:
        PASSED[0] += 1
        print("PASS — %s" % name)
    else:
        FAILED.append(name)
        print("FAIL — %s%s" % (name, ("  :: %s" % (extra,))[:900] if extra != "" else ""))


# ── поддельная служба лицензий (только 127.0.0.1) ──────────────────────────────────
#  seq — коды ответа по очереди, отметка за отметкой (17.10.2026: «первую принять, на вторую отказать»);
#  очередь кончилась — отвечает status. 17.10.2026 (O): ra — Retry-After ответа 429/503; expose — служба
#  открывает его браузеру (Access-Control-Expose-Headers); bare_errors — ошибка без заголовков CORS (так
#  отвечает ограничитель запросов или прокси перед службой, если их не настроить).
SVC_DEFAULTS = {"ra": "120", "expose": False, "bare_errors": False}
SVC = dict({"status": 200, "seq": [], "body": "", "log": []}, **SVC_DEFAULTS)


class _Svc(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "600")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        raw = self.rfile.read(n) if n > 0 else b""
        try:
            SVC["log"].append(json.loads(raw.decode("utf-8")))
        except Exception:
            SVC["log"].append({"__raw": raw[:200].decode("utf-8", "replace")})
        body = str(SVC["body"]).encode("utf-8")
        code = int(SVC["seq"].pop(0)) if SVC["seq"] else int(SVC["status"])
        self.send_response(code)
        if not (SVC["bare_errors"] and code >= 400):
            self._cors()
            if SVC["expose"]:
                self.send_header("Access-Control-Expose-Headers", "Retry-After")
        if code in (429, 503) and SVC["ra"] is not None:
            self.send_header("Retry-After", str(SVC["ra"]))
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


_svc = ThreadingHTTPServer(("127.0.0.1", 0), _Svc)
threading.Thread(target=_svc.serve_forever, daemon=True).start()
SVC_URL = "http://127.0.0.1:%d/v1/mark" % _svc.server_address[1]

# Адрес, по которому никто не слушает: «у этого устройства нет связи со службой».
_s = socket.socket()
_s.bind(("127.0.0.1", 0))
DEAD_URL = "http://127.0.0.1:%d/v1/mark" % _s.getsockname()[1]
_s.close()

# Подписанный ответ службы здесь не нужен: принимает его не страница, а программа (/api/licenses/import),
# ответ которой задаёт стенд.
FAKE_VERDICT = '{"format":"fm-verdict","fixture":true}'

ADMIN = {"enabled": True, "authenticated": True, "user": {"username": "fixture_admin", "role": "admin"},
         "roles": ["admin", "operator", "assembler", "observer"], "remember_device": 1}
OPERATOR = {"enabled": True, "authenticated": True, "user": {"username": "fixture_operator", "role": "operator"},
            "roles": ["admin", "operator", "assembler", "observer"], "remember_device": 1}


def mark(n):
    return {"license_id": "FIXTURE-LIC-%d" % n, "machine": "FIXTURE_MACHINE", "nonce": "%032x" % n,
            "proof": "FIXTURE_PROOF_%d" % n, "module_id": "demo_paid", "module_version": "1.0.0"}


def lic_row(n, state="ok", reason="", last=""):
    return {"file": "FIXTURE-LIC-%d.fmlic" % n, "ok": True, "code": "", "license_id": "FIXTURE-LIC-%d" % n,
            "use_type": "perpetual", "updates_before": "2027-10-01", "use_valid_until": "", "issued_at": "",
            "channel": "stable", "bound": False, "bound_here": True,
            "grants": [{"module_id": "demo_paid", "edition": "", "features": []}],
            "service_state": state, "service_reason": reason, "last_answer_at": last}


def lic_list(marks, url=SVC_URL, configured=True, licenses=None):
    return {"status": "ok", "install_id": "FIXTURE-INSTALL", "licenses": licenses or [], "modules": [],
            "test_keys": False, "production_keys": 0, "activation_request": None, "machine": "FIXTURE",
            "consent": True, "service": {"configured": configured, "url": url if configured else ""},
            "terms_url": "", "privacy_url": "", "mark_requests": marks,
            "transmitted": {"requests": [], "answers": {}}}


def verdict(state="ok", reason="", n=1):
    return {"status": "ok", "kind": "verdict", "license_id": "FIXTURE-LIC-%d" % n,
            "service_state": state, "service_reason": reason}


def page_problems_except(R, url):
    """Ошибки страницы без строк самого браузера о неудачном запросе к адресу службы."""
    d = dict((R or {}).get("__diag") or {})
    allowed = []
    if url:
        for k in ("consoleErrors", "consoleWarnings"):
            keep = []
            for s in (d.get(k) or []):
                (allowed if url in str(s) else keep).append(s)
            d[k] = keep
    return stage.page_problems({"__diag": d}), allowed


def unescape_texts(R):
    """Результат сценария стенд забирает из outerHTML страницы, а там неразрывный пробел
    становится «&nbsp;» (и & — «&amp;»). Тексты сообщений возвращаем к тому, что видно на экране."""
    for key in ("toasts", "panel"):
        for b in (R.get(key) or []):
            if isinstance(b, dict) and isinstance(b.get("text"), str):
                b["text"] = html.unescape(b["text"])
    if isinstance(R.get("rows"), list):
        R["rows"] = [html.unescape(x) if isinstance(x, str) else x for x in R["rows"]]
    return R


if not stage.engine_ready():
    check("0. браузерный движок для стенда доступен", False, stage.last_diag())
    print("FAIL: стенд не поднят")
    sys.exit(1)

# ── сценарий для отметки при открытии страницы ──────────────────────────────────────
#  Отметка уходит сама при открытии (licLoad в onMounted) — сценарий ничего не нажимает, только
#  ждёт сообщение и снимает его размеры. Ждём «до появления» (expect) или полный срок (молчание).
JS_MOUNT = r"""
return new Promise(function(res){
  var C = window.__LIC_CFG || {};
  function qa(s){ return [].slice.call(document.querySelectorAll(s)); }
  var RX = /Лицензии модулей|Module licenses/;
  function lic(sel){ return qa(sel).filter(function(e){ return RX.test(e.textContent || ''); }); }
  function box(e){
    var b = e.getBoundingClientRect(), cs = getComputedStyle(e);
    var m = e.querySelector('.fm-toast-msg') || e.querySelector('.sg-msg-t') || e;
    return {text: (m.textContent || '').trim(), cls: String(e.className || ''), sw: e.scrollWidth, cw: e.clientWidth,
            msw: m.scrollWidth, mcw: m.clientWidth, left: b.left, right: b.right, top: b.top, bottom: b.bottom,
            w: b.width, h: b.height, vis: cs.visibility, op: cs.opacity, disp: cs.display,
            bc: cs.borderTopColor, col: cs.color, ic: !!e.querySelector('svg.fm-toast-ic'),
            warn: getComputedStyle(document.documentElement).getPropertyValue('--fm-warn-rgb').trim()};
  }
  function measure(){
    var de = document.documentElement;
    res(dump({ vw: window.innerWidth, vh: window.innerHeight, cw: de.clientWidth,
               corner: !!document.querySelector('.fm-toasts'),
               toasts: lic('.fm-toasts .fm-toast').map(box), panel: lic('.sg-msg').map(box),
               hscroll: de.scrollWidth > de.clientWidth + 1, waited: Date.now() - t0, log: FM_LOG }));
  }
  var t0 = Date.now();
  (function wait(){
    var found = lic('.fm-toasts .fm-toast').length + lic('.sg-msg').length;
    if ((C.expect && found) || Date.now() - t0 > (C.waitMs || 4000)) {
      //  Окно headless-браузера не бывает уже ~500 px: ширину телефона ставит мост (настоящая
      //  смена вьюпорта), размеры снимаются после перерисовки.
      if (C.vw) setViewport(C.vw, C.vh, 1, function(){ setTimeout(measure, 500); });
      else setTimeout(measure, C.expect ? 800 : 0);
      return;
    }
    setTimeout(wait, 150);
  })();
});
"""


def run_mount(size, lang, auth, licenses, imp, svc_status=200, expect=True, wait_ms=4000, shot=None, svc_seq=()):
    SVC["status"], SVC["seq"], SVC["body"], SVC["log"] = svc_status, list(svc_seq), FAKE_VERDICT, []
    stage.set_api({"/api/auth/status": auth, "/api/licenses": licenses, "/api/licenses/import": imp})
    cfg = {"expect": expect, "waitMs": wait_ms, "vw": size[0], "vh": size[1]}
    _shots = os.environ.get("FM_UI_SHOTS")
    R = stage.run("window.__LIC_CFG = %s;\n%s" % (json.dumps(cfg), JS_MOUNT), window_size=size, settle_ms=2400,
                  path="/?ls=farm_lang:" + lang,
                  shot_path=(os.path.join(_shots, shot) if (_shots and shot) else None)) or {}
    stage.set_api(None)
    return unescape_texts(R), list(SVC["log"])


def fits(b, cw):
    """Сообщение целиком на экране и без горизонтального переполнения."""
    return (b.get("w", 0) > 0 and b.get("h", 0) > 0 and b.get("vis") == "visible" and b.get("disp") != "none"
            and float(b.get("op") or 0) > 0.5 and b.get("left", -1) >= 0 and b.get("right", 1e9) <= cw + 0.5
            and b.get("top", -1) >= 0 and b.get("sw", 1e9) <= b.get("cw", 0) + 1
            and b.get("msw", 1e9) <= b.get("mcw", 0) + 1)


# ── A. телефон 390×844: служба ответила «работает» ──────────────────────────────────
R, log = run_mount((390, 844), "ru", ADMIN, lic_list([mark(1)]), verdict("ok"), shot="A_ok_390.png")
T = R.get("toasts") or []
check("A1. узкий экран: включена телефонная раскладка (угол сообщений .fm-toasts)",
      R.get("corner") is True and R.get("vw") == 390, (R.get("corner"), R.get("vw")))
check("A2. служба получила ровно одну отметку, отнесённую браузером (via: browser)",
      len(log) == 1 and log[0].get("via") == "browser" and log[0].get("license_id") == "FIXTURE-LIC-1", log)
check("A3. в углу ОДНО сообщение «служба лицензий ответила через этот браузер — работает (чч:мм)», с галочкой",
      len(T) == 1 and re.fullmatch(r"Лицензии модулей: служба лицензий ответила через этот браузер — работает \(\d\d:\d\d\)",
                                   T[0]["text"]) is not None and "fm-toast--success" in T[0]["cls"], T)
check("A4. сообщение видно и влезает в экран 390 px (без горизонтального переполнения)",
      len(T) == 1 and fits(T[0], R.get("cw") or 390) and R.get("hscroll") is False, (T, R.get("cw"), R.get("hscroll")))
check("A5. консоль страницы чистая", not stage.page_problems(R), stage.page_problems(R))
check("A6. «работает» — не предупреждение: без знака «внимание» и без жёлтой рамки",
      len(T) == 1 and not T[0].get("ic") and T[0].get("warn")
      and not T[0].get("bc", "").startswith("rgba(%s" % T[0]["warn"].replace(" ", "")), T)

# ── B. телефон 360×740: служба остановила ключ (ключ на другом компьютере) ───────────────
R, log = run_mount((360, 740), "ru", ADMIN, lic_list([mark(1)]), verdict("stop", "seat_taken"), shot="B_stop_360.png")
T = R.get("toasts") or []
check("B1. «ОСТАНОВЛЕНА» со словами причины — предупреждение, одно",
      len(T) == 1 and T[0]["text"] == ("Лицензии модулей: служба лицензий ответила через этот браузер — ОСТАНОВЛЕНА: "
                                       "ключ уже работает на другом компьютере — подтвердите перенос в личном кабинете "
                                       "на сайте 3diwell.com") and "fm-toast--warn" in T[0]["cls"], T)
check("B2. длинное предупреждение влезает в экран 360 px", R.get("vw") == 360 and len(T) == 1
      and fits(T[0], R.get("cw") or 360) and R.get("hscroll") is False, (T, R.get("vw"), R.get("cw")))
check("B3. консоль страницы чистая", not stage.page_problems(R), stage.page_problems(R))


def _rgb(s):
    return [x.strip() for x in s.split(",")[:3]]


def _warn_look(b):
    """17.10.2026: предупреждение на телефоне — знак «внимание», рамка и текст цветом предупреждения темы (--fm-warn)."""
    w = _rgb(b.get("warn", ""))
    bc = re.findall(r"[\d.]+", b.get("bc", ""))
    col = re.findall(r"[\d.]+", b.get("col", ""))
    return bool(b.get("ic")) and len(w) == 3 and bc[:3] == w and col[:3] == w


check("B4. предупреждение выглядит предупреждением: знак «внимание», жёлтая рамка и жёлтый текст (как в панели "
      "«Подсказки» на компьютере)", len(T) == 1 and _warn_look(T[0]), T)

# ── C. служба отказала (HTTP 403) ───────────────────────────────────────────────────
R, log = run_mount((390, 844), "ru", ADMIN, lic_list([mark(1)]), verdict("ok"), svc_status=403, shot="C_403_390.png")
T = R.get("toasts") or []
_pp, _allowed = page_problems_except(R, SVC_URL)
check("C1. отказ службы — предупреждение «служба лицензий отказала (HTTP 403)», лицензии как прежде, попробует позже",
      len(log) == 1 and len(T) == 1 and T[0]["text"] == ("Лицензии модулей: служба лицензий отказала (HTTP\u00a0403) — лицензии "
                                                         "работают как прежде, программа попробует ещё раз позже.")
      and "fm-toast--warn" in T[0]["cls"] and fits(T[0], R.get("cw") or 390), (log, T))
check("C2. консоль: кроме строки браузера о запросе к службе — чисто", not _pp, (_pp, _allowed))

# ── D. программа не приняла ответ службы ─────────────────────────────────────────────
R, log = run_mount((390, 844), "ru", ADMIN, lic_list([mark(1)]),
                   {"status": "error", "reason": "license_rejected", "code": "verdict_foreign"})
T = R.get("toasts") or []
check("D1. ответ не принят программой — предупреждение «ответ службы лицензий не принят»",
      len(log) == 1 and len(T) == 1 and T[0]["text"].startswith("Лицензии модулей: ответ службы лицензий не принят — ")
      and "fm-toast--warn" in T[0]["cls"] and fits(T[0], R.get("cw") or 390), (log, T))
check("D2. консоль страницы чистая", not stage.page_problems(R), stage.page_problems(R))

# ── E. служба просит подождать (429): молчим, следующую отметку не шлём ──────────────────
R, log = run_mount((390, 844), "ru", ADMIN, lic_list([mark(1), mark(2)]), verdict("ok"), svc_status=429,
                   expect=False, wait_ms=3000)
_pp, _allowed = page_problems_except(R, SVC_URL)
check("E1. 429: сообщения нет, вторая отметка не отправлена", len(log) == 1 and not (R.get("toasts") or [])
      and not (R.get("panel") or []) and R.get("corner") is True, (log, R.get("toasts"), R.get("panel")))
check("E2. консоль: кроме строки браузера о запросе к службе — чисто", not _pp, (_pp, _allowed))

# ── F. не администратор: программа отказывает в списке лицензий (как настоящий сервер — 403) ──
R, log = run_mount((390, 844), "ru", OPERATOR, {"error": "forbidden"}, verdict("ok"), expect=False, wait_ms=3000)
check("F1. оператор: службе ничего не ушло, сообщения нет", not log and not (R.get("toasts") or [])
      and not (R.get("panel") or []) and R.get("corner") is True, (log, R.get("toasts"), R.get("panel")))
check("F2. консоль страницы чистая", not stage.page_problems(R), stage.page_problems(R))

# ── G. служба недоступна с этого устройства ─────────────────────────────────────────
R, log = run_mount((390, 844), "ru", ADMIN, lic_list([mark(1)], url=DEAD_URL), verdict("ok"),
                   expect=False, wait_ms=4500)
_pp, _allowed = page_problems_except(R, DEAD_URL)
#  Строка браузера о недоступном адресе — доказательство, что отметку пытались отнести и попытка
#  уже закончилась к моменту замера (иначе «сообщения нет» могло бы значить «ещё не успели»).
check("G1. нет связи со службой — попытка была, сообщения нет (лицензии работают как прежде)",
      bool(_allowed) and not (R.get("toasts") or []) and not (R.get("panel") or []) and R.get("corner") is True,
      (_allowed, R.get("toasts"), R.get("panel")))
check("G2. консоль: кроме строки браузера о недоступном адресе службы — чисто", not _pp, (_pp, _allowed))

# ── H. отметок, которые пора отправить, нет ─────────────────────────────────────────
R, log = run_mount((390, 844), "ru", ADMIN, lic_list([]), verdict("ok"), expect=False, wait_ms=2500)
check("H1. отметок нет — службе ничего, сообщения нет", not log and not (R.get("toasts") or [])
      and not (R.get("panel") or []), (log, R.get("toasts")))
check("H2. консоль страницы чистая", not stage.page_problems(R), stage.page_problems(R))

# ── I. адрес службы не задан ────────────────────────────────────────────────────────
R, log = run_mount((390, 844), "ru", ADMIN, lic_list([mark(1)], configured=False), verdict("ok"),
                   expect=False, wait_ms=2500)
check("I1. адрес службы не задан — службе ничего, сообщения нет", not log and not (R.get("toasts") or [])
      and not (R.get("panel") or []), (log, R.get("toasts")))
check("I2. консоль страницы чистая", not stage.page_problems(R), stage.page_problems(R))

# ── J. английский интерфейс ─────────────────────────────────────────────────────────
R, log = run_mount((390, 844), "en", ADMIN, lic_list([mark(1)]), verdict("ok"), shot="J_en_390.png")
T = R.get("toasts") or []
check("J1. английский: «Module licenses: the license service answered via this browser — OK (hh:mm)»",
      len(log) == 1 and len(T) == 1 and re.fullmatch(
          r"Module licenses: the license service answered via this browser — OK \(\d\d:\d\d\)", T[0]["text"]) is not None
      and fits(T[0], R.get("cw") or 390), (log, T))
check("J2. консоль страницы чистая", not stage.page_problems(R), stage.page_problems(R))

# ── K. компьютер: «Настройки → Модули», две лицензии — одно сообщение в панели «Подсказки» ──
#  Отметка при открытии страницы здесь не нужна (отметок нет), её запускает вкладка «Модули».
#  Ответы программы для этого шага подменяются в самой странице: стенд отдаёт на один адрес
#  всегда одно и то же, а здесь две отметки с разными ответами службы.
JS_DESK = r"""
return new Promise(function(res){
  var C = window.__LIC_CFG;
  function qa(s){ return [].slice.call(document.querySelectorAll(s)); }
  var RX = /Лицензии модулей|Module licenses/;
  function lic(sel){ return qa(sel).filter(function(e){ return RX.test(e.textContent || ''); }); }
  var out = { before: lic('.sg-msg').length + lic('.fm-toasts .fm-toast').length };
  var _f = window.fetch, imports = 0, notes = 0, svc = 0;
  function J(o){ return Promise.resolve(new Response(JSON.stringify(o), {status: 200, headers: {'Content-Type': 'application/json'}})); }
  window.fetch = function(u, o){
    var s = String(u);
    if (s.indexOf('/api/licenses/import') >= 0) {
      var note = false; try { note = !!(o && o.body && o.body.get && o.body.get('relay_status') != null); } catch (e) {}
      if (note) { notes++; return J({status: 'ok', kind: 'relay_noted'}); }
      return J(C.imports[Math.min(imports++, C.imports.length - 1)]);
    }
    if (/\/api\/licenses(\?|$)/.test(s)) return J(C.list);
    if (s === C.svc) svc++;
    return _f.apply(this, arguments);
  };
  openStage('modules', function(){
    var t0 = Date.now();
    (function wait(){
      if (lic('.sg-msg').length || Date.now() - t0 > 8000) {
        setTimeout(function(){
          out.panel = lic('.sg-msg').map(function(e){ var m = e.querySelector('.sg-msg-t') || e;
            return {text: (m.textContent || '').trim(), cls: String(e.className || '')}; });
          out.corner = !!document.querySelector('.fm-toasts');
          out.rows = qa('.fm-lic-meta').map(function(e){ return (e.textContent || '').trim(); });
          out.tab = activeTabText(); out.imports = imports; out.notes = notes; out.svc = svc; out.log = FM_LOG;
          res(dump(out));
        }, 800);
        return;
      }
      setTimeout(wait, 150);
    })();
  }, 'ru');
});
"""
def run_desk(marks, rows, imports):
    cfg = {"svc": SVC_URL, "list": lic_list(marks, licenses=rows), "imports": imports}
    SVC["status"], SVC["seq"], SVC["body"], SVC["log"] = 200, [], FAKE_VERDICT, []
    stage.set_api({"/api/auth/status": ADMIN, "/api/licenses": lic_list([])})
    R = stage.run("window.__LIC_CFG = %s;\n%s" % (json.dumps(cfg), JS_DESK), window_size=(1600, 1000),
                  settle_ms=2400, path="/?ls=farm_lang:ru") or {}
    stage.set_api(None)
    return unescape_texts(R), list(SVC["log"])


_rows = [lic_row(1, "ok", "", "2026-10-17T10:05:00"), lic_row(2, "stop", "seat_taken"),
         lic_row(3, "stop", "constructor"), lic_row(4, "revoked", "refund")]
R, log = run_desk([mark(1), mark(2)], _rows, [verdict("ok", "", 1), verdict("stop", "seat_taken", 2)])
P = R.get("panel") or []
check("K1. компьютер: до вкладки «Модули» сообщения о лицензиях нет (отметок не было)",
      R.get("before") == 0 and R.get("corner") is False, (R.get("before"), R.get("corner")))
check("K2. вкладка «Модули» отнесла обе отметки службе, обе приняты программой",
      len(log) == 2 and R.get("svc") == 2 and R.get("imports") == 2 and R.get("notes") == 0
      and [x.get("license_id") for x in log] == ["FIXTURE-LIC-1", "FIXTURE-LIC-2"], (log, R.get("svc"), R.get("imports"), R.get("tab"), R.get("log")))
check("K3. ОДНО сообщение в панели: худшее состояние со счётом и словами причины, как предупреждение",
      len(P) == 1 and P[0]["text"] == ("Лицензии модулей (2): служба лицензий ответила через этот браузер — "
                                       "ОСТАНОВЛЕНА (1 из 2): ключ уже работает на другом компьютере — подтвердите "
                                       "перенос в личном кабинете на сайте 3diwell.com") and "k-warn" in P[0]["cls"], P)
_r = R.get("rows") or []
check("K4. строки лицензий: «работает (время)», остановлена со словами причины, незнакомая причина — общими словами, аннулирована",
      len(_r) == 4 and re.search(r"служба лицензий: работает \(17\.10\.2026 \d\d:\d\d\)$", _r[0]) is not None
      and _r[1].endswith("ОСТАНОВЛЕНА: ключ уже работает на другом компьютере — подтвердите перенос в личном кабинете на сайте 3diwell.com")
      and _r[2].endswith("ОСТАНОВЛЕНА: служба лицензий остановила ключ на этом компьютере")
      and _r[3].endswith("АННУЛИРОВАНА — платные функции закрыты"), _r)
check("K5. консоль страницы чистая", not stage.page_problems(R), stage.page_problems(R))

# ── L. телефон 390×844: служба аннулировала лицензию ────────────────────────────────
R, log = run_mount((390, 844), "ru", ADMIN, lic_list([mark(1)]), verdict("revoked", "refund"), shot="L_revoked_390.png")
T = R.get("toasts") or []
check("L1. «АННУЛИРОВАНА — платные функции закрыты» — предупреждение, одно",
      len(log) == 1 and len(T) == 1 and T[0]["text"] == ("Лицензии модулей: служба лицензий ответила через этот браузер — "
                                                         "АННУЛИРОВАНА — платные функции закрыты")
      and "fm-toast--warn" in T[0]["cls"], (log, T))
check("L2. предупреждение влезает в экран 390 px", len(T) == 1 and fits(T[0], R.get("cw") or 390)
      and R.get("hscroll") is False, (T, R.get("cw"), R.get("hscroll")))
check("L3. консоль страницы чистая", not stage.page_problems(R), stage.page_problems(R))
check("L4. аннулирование — тоже со знаком «внимание» и цветом предупреждения", len(T) == 1 and _warn_look(T[0]), T)

# ── M. телефон: первую отметку служба приняла, на вторую отказала (HTTP 403) ─────────────
R, log = run_mount((390, 844), "ru", ADMIN, lic_list([mark(1), mark(2)]), verdict("ok"), svc_seq=(200, 403),
                   shot="M_mixed_390.png")
T = R.get("toasts") or []
_ok = [b for b in T if re.fullmatch(r"Лицензии модулей: служба лицензий ответила через этот браузер — работает \(\d\d:\d\d\)",
                                    b["text"]) and "fm-toast--success" in b["cls"]]
_no = [b for b in T if b["text"] == ("Лицензии модулей: служба лицензий отказала (HTTP\u00a0403) — лицензии работают "
                                     "как прежде, программа попробует ещё раз позже.") and "fm-toast--warn" in b["cls"]]
_pp, _allowed = page_problems_except(R, SVC_URL)
check("M1. обе отметки отнесены службе; два сообщения: «работает» и «служба отказала (HTTP 403)»",
      [x.get("license_id") for x in log] == ["FIXTURE-LIC-1", "FIXTURE-LIC-2"] and len(T) == 2
      and len(_ok) == 1 and len(_no) == 1, (log, T))
check("M2. оба сообщения влезают в экран 390 px", len(T) == 2 and all(fits(b, R.get("cw") or 390) for b in T)
      and R.get("hscroll") is False, (T, R.get("cw"), R.get("hscroll")))
check("M3. консоль: кроме строки браузера о запросе к службе — чисто", not _pp, (_pp, _allowed))

# ── N. компьютер: три лицензии, одна аннулирована — она и попадает в сообщение ──────────
R, log = run_desk([mark(1), mark(2), mark(3)], _rows,
                  [verdict("ok", "", 1), verdict("revoked", "refund", 2), verdict("stop", "seat_taken", 3)])
P = R.get("panel") or []
check("N1. вкладка «Модули» отнесла три отметки, все приняты программой",
      len(log) == 3 and R.get("svc") == 3 and R.get("imports") == 3 and R.get("notes") == 0, (log, R.get("svc"), R.get("imports")))
check("N2. ОДНО сообщение: худшее — «АННУЛИРОВАНА (1 из 3) — платные функции закрыты», как предупреждение",
      len(P) == 1 and P[0]["text"] == ("Лицензии модулей (3): служба лицензий ответила через этот браузер — "
                                       "АННУЛИРОВАНА (1 из 3) — платные функции закрыты") and "k-warn" in P[0]["cls"], P)
check("N3. консоль страницы чистая", not stage.page_problems(R), stage.page_problems(R))

# ── O. 17.10.2026: что страница сообщает программе, когда служба ответа не дала ──────────
#  Сообщение страницы (поля relay_* запроса к /api/licenses/import) перехватывается в самой странице, а
#  паузу по нему считает та же функция программы, что и /api/licenses/import (LicenseService.note_relay) —
#  на временной папке этого набора.
JS_NOTE = r"""
return new Promise(function(res){
  var C = window.__LIC_CFG;
  var _f = window.fetch, notes = [], svc = 0;
  function J(o){ return Promise.resolve(new Response(JSON.stringify(o), {status: 200, headers: {'Content-Type': 'application/json'}})); }
  window.fetch = function(u, o){
    var s = String(u);
    if (s.indexOf('/api/licenses/import') >= 0) {
      var b = o && o.body, n = null;
      try { if (b && b.get && b.get('relay_status') != null) n = {license_id: b.get('relay_license_id'),
            status: b.get('relay_status'), retry_after: b.get('relay_retry_after')}; } catch (e) {}
      if (n) { notes.push(n); return J({status: 'ok', kind: 'relay_noted'}); }
      return J(C.imp);
    }
    if (/\/api\/licenses(\?|$)/.test(s)) return J(C.list);
    if (s === C.svc) svc++;
    return _f.apply(this, arguments);
  };
  openStage('modules', function(){
    var t0 = Date.now();
    (function wait(){
      if (notes.length || Date.now() - t0 > 30000) {
        setTimeout(function(){
          var msgs = [].slice.call(document.querySelectorAll('.sg-msg, .fm-toasts .fm-toast')).filter(function(e){
            return /Лицензии модулей|Module licenses/.test(e.textContent || ''); }).length;
          res(dump({notes: notes, svc: svc, msgs: msgs, log: FM_LOG}));
        }, 800);
        return;
      }
      setTimeout(wait, 150);
    })();
  }, 'ru');
});
"""


def run_note(status=429, url=SVC_URL, **svc_cfg):
    SVC.update(dict(SVC_DEFAULTS, status=status, seq=[], body=FAKE_VERDICT, log=[]))
    SVC.update(svc_cfg)
    cfg = {"svc": url, "list": lic_list([mark(1)], url=url), "imp": verdict("ok")}
    stage.set_api({"/api/auth/status": ADMIN, "/api/licenses": lic_list([])})
    R = stage.run("window.__LIC_CFG = %s;\n%s" % (json.dumps(cfg), JS_NOTE), window_size=(1600, 1000),
                  settle_ms=2400, path="/?ls=farm_lang:ru") or {}
    stage.set_api(None)
    SVC.update(SVC_DEFAULTS)
    return R, list(SVC["log"])


def program_wait(R):
    """Сообщение страницы -> (исход, пауза для всех отметок в секундах, следующая отметка этой лицензии в
    секундах) — так, как его разберёт программа (LicenseService.note_relay, как в /api/licenses/import)."""
    notes = R.get("notes") or []
    if len(notes) != 1:
        return None
    n = notes[0]
    t = tempfile.mkdtemp(prefix="fm_relay_ui_")
    try:
        s = SV.LicenseService(t, trusted={})
        now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
        out = s.note_relay(n.get("license_id"), n.get("status"), n.get("retry_after"), now=now)
        m = s.store.marks()

        def secs(v):
            return int((datetime.datetime.strptime(v, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
                        - now).total_seconds()) if v else None
        return out, secs(m["backoff_until"]), secs(m["next"].get(str(n.get("license_id")), ""))
    finally:
        shutil.rmtree(t, ignore_errors=True)


R, log = run_note(429, ra="3600", expose=True)
W = program_wait(R)
_pp, _allowed = page_problems_except(R, SVC_URL)
check("O1. 429, Retry-After 3600, служба открыла заголовок: страница передала программе 429 и «3600» — пауза для "
      "всех отметок ровно час; сообщения нет", len(log) == 1 and R.get("notes") == [
          {"license_id": "FIXTURE-LIC-1", "status": "429", "retry_after": "3600"}]
      and W == (429, 3600, 3600) and R.get("msgs") == 0 and not _pp, (log, R.get("notes"), W, R.get("msgs"), _pp))
R, log = run_note(429, ra=str(3 * 86400), expose=True)
W = program_wait(R)
check("O2. КРИТИЧНО: 429, Retry-After 3 суток — пауза 3 суток, НЕ сокращается до суток",
      len(log) == 1 and W == (429, 3 * 86400, 3 * 86400), (log, R.get("notes"), W))
_hd = email.utils.formatdate(time.time() + 7200, usegmt=True)
R, log = run_note(503, ra=_hd, expose=True)
W = program_wait(R)
check("O3. 503, Retry-After датой HTTP через 2 часа: страница передала дату как есть, программа поставила паузу "
      "2 часа", len(log) == 1 and (R.get("notes") or [{}])[0].get("retry_after") == _hd and W is not None
      and W[0] == 503 and 7200 - 120 <= (W[1] or 0) <= 7200, (log, R.get("notes"), W))
R, log = run_note(429, ra="3600", expose=False)
W = program_wait(R)
_pp, _allowed = page_problems_except(R, SVC_URL)
check("O4. служба НЕ открыла Retry-After браузеру (нет Access-Control-Expose-Headers): страница его не видит — "
      "программа ставит паузу по умолчанию, 15 минут (поэтому служба обязана открыть заголовок)",
      len(log) == 1 and R.get("notes") == [{"license_id": "FIXTURE-LIC-1", "status": "429", "retry_after": None}]
      and W == (429, 900, 900) and not _pp, (log, R.get("notes"), W, _pp))
R, log = run_note(429, ra="3600", bare_errors=True)
W = program_wait(R)
_pp, _allowed = page_problems_except(R, SVC_URL)
check("O5. ответ 429 без заголовков CORS (ограничитель перед службой): браузер ответ странице не показал — она "
      "сообщила «нет связи», следующая попытка через 15 минут, сообщения нет",
      len(log) == 1 and R.get("notes") == [{"license_id": "FIXTURE-LIC-1", "status": "network", "retry_after": None}]
      and W == ("network", None, 900) and R.get("msgs") == 0 and not _pp, (log, R.get("notes"), W, _pp, _allowed))
R, log = run_note(200, url=DEAD_URL)
W = program_wait(R)
_pp, _allowed = page_problems_except(R, DEAD_URL)
check("O6. служба недоступна с этого устройства: страница сообщила программе «нет связи» — следующая попытка через "
      "15 минут (раньше — ничего, и отметку отдавали снова через 10 минут); сообщения нет",
      R.get("notes") == [{"license_id": "FIXTURE-LIC-1", "status": "network", "retry_after": None}]
      and W == ("network", None, 900) and R.get("msgs") == 0 and bool(_allowed) and not _pp,
      (R.get("notes"), W, _pp, _allowed))

stage.stop()
_svc.shutdown()

print("\n" + "=" * 76)
if FAILED:
    print("FAIL: провалено %d из %d" % (len(FAILED), len(FAILED) + PASSED[0]))
    for f in FAILED:
        print("   - %s" % f)
    sys.exit(1)
print("PASS: все %d проверок пройдены" % PASSED[0])
sys.exit(0)
