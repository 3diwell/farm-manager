# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Встроенный журнал вместо CMD — Alpha 2.813.
=================================================================================================
ЗАЧЕМ ЭТОТ ТЕСТ СУЩЕСТВУЕТ.

Единственным «просмотрщиком логов» для пользователя было окно CMD, которое открывал пункт трея
«Показать консоль (логи)». Это окно — НАСТОЯЩАЯ консоль процесса сервера (сборка идёт с
console=True, программа лишь прячет окно через ShowWindow). Крестик у такого окна Windows
трактует как завершение процесса-владельца, поэтому пользователь, закрывая «просмотр логов»,
завершал Farm Manager вместе с идущими печатями. Категория причины: **A** — консоль является
консолью самого backend, отдельного процесса-просмотрщика не существовало.

ЧТО ПРОВЕРЯЕТСЯ ЗДЕСЬ: центральный буфер журнала и вычищение секретов (записи, вытеснение,
номера), ограниченный контракт чтения, административная граница маршрута, поведение окна журнала
(пауза, поиск, фильтр, копирование, сохранение, «очистить экран»), пункт трея и отсутствие
консольных вызовов в пользовательском пути, режим разработчика и сохранность прежних контрактов.

ПОЛНОСТЬЮ OFFLINE: временная папка, поддельные записи, ловушки на сокеты и подпроцессы; рабочие
БД, DATA_DIR и файлы журналов не читаются, окно не открывается, сеть и принтеры не участвуют.

Запуск: PYTHONIOENCODING=utf-8 python tools/test_in_app_log_viewer.py   (0 = пройдено)
"""
import ast
import atexit
import os
import re
import sys
import tempfile
import threading

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

SENTINEL = "IN_APP_LOG_VIEWER_SENTINEL_2_813"

# ── Ловушки: сеть и запуск процессов в offline-тесте запрещены ────────────────────────────────
import socket as _socket_mod
import subprocess as _subprocess_mod

_VIOLATIONS = []


class _NoSocket(object):
    def __init__(self, *a, **k):
        _VIOLATIONS.append("socket")
        raise RuntimeError("сеть в offline-тесте запрещена")


_socket_mod.socket = _NoSocket
_socket_mod.create_connection = lambda *a, **k: _NoSocket()


class _NoPopen(object):
    def __init__(self, *a, **k):
        _VIOLATIONS.append("subprocess")
        raise RuntimeError("запуск процессов в offline-тесте запрещён")


_subprocess_mod.Popen = _NoPopen

_TMP = tempfile.TemporaryDirectory(prefix="fm_log_viewer_2813_")
TMP_ROOT = os.path.realpath(_TMP.name)

from app import runtime_log_buffer as B

_SRV = open(os.path.join(REPO, "server.py"), encoding="utf-8").read()
_APP = open(os.path.join(REPO, "web", "app.js"), encoding="utf-8").read()
_HTML = open(os.path.join(REPO, "web", "index.html"), encoding="utf-8").read()
_BUF_SRC = open(os.path.join(REPO, "app", "runtime_log_buffer.py"), encoding="utf-8").read()
_SHELL_SRC = open(os.path.join(REPO, "app", "desktop_shell.py"), encoding="utf-8").read()
_SHCFG_SRC = open(os.path.join(REPO, "app", "desktop_shell_config.py"), encoding="utf-8").read()

fail = 0
_checked = 0
_verdict = [False]


def check(name, cond):
    global fail, _checked
    _checked += 1
    print(("PASS" if cond else "FAIL") + " — " + name)
    if not cond:
        fail += 1


@atexit.register
def _guard_exit():
    if not _verdict[0]:
        print("FAIL — тест завершился БЕЗ финального вердикта (преждевременный выход)")
        os._exit(1)


def fn_src(name, src=None):
    """Тело функции/метода по имени — для проверок ПО КОДУ, а не по тексту файла."""
    tree = ast.parse(src or _SRV)
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            return ast.get_source_segment(src or _SRV, n) or ""
    return ""


def calls_in(src_text):
    """Имена вызываемых функций внутри фрагмента кода."""
    out = set()
    try:
        tree = ast.parse(src_text)
    except SyntaxError:
        return out
    for n in ast.walk(tree):
        if isinstance(n, ast.Call):
            f = n.func
            out.add(getattr(f, "id", None) or getattr(f, "attr", None) or "")
    return out


print("=" * 95)
print("A. ЦЕНТРАЛЬНЫЙ БУФЕР ЖУРНАЛА")
print("=" * 95)

buf = B.LogBuffer(capacity=5)
s1 = buf.append("INFO", "[PORT] первая запись")
s2 = buf.append("warning", "вторая запись")
check("A1. запись получает номер", isinstance(s1, int) and s1 >= 1)
check("A2. КРИТИЧНО: номера строго возрастают (просмотр не получит дублей и пропусков)", s2 == s1 + 1)
recs, latest, has_more = buf.snapshot(0, 10)
check("A3. у записи есть время", all(isinstance(r["ts"], float) and r["ts"] > 0 for r in recs))
check("A4. уровень нормализован к четырём значениям",
      all(r["level"] in B.LEVELS for r in recs) and B.normalize_level("CRITICAL") == "error"
      and B.normalize_level("WARN") == "warning" and B.normalize_level("что-то") == "info")
check("A5. источник берётся из метки сообщения и безопасен",
      recs[0]["source"] == "port" and recs[1]["source"] == "general")
check("A6. latest_seq и has_more возвращаются", latest == s2 and has_more is False)

for i in range(20):
    buf.append("info", "запись %d" % i)
st = buf.stats()
check("A7. КРИТИЧНО: буфер ограничен — память не растёт вместе со временем работы",
      st["count"] == 5 and st["capacity"] == 5)
check("A8. старые записи вытеснены и это ЧЕСТНО посчитано", st["dropped_count"] == 17)
check("A9. номера после вытеснения продолжают расти", st["latest_seq"] == 22)

par = B.LogBuffer(capacity=5000)
_errs = []


def _writer(n):
    try:
        for i in range(200):
            par.append("info", "поток %d запись %d" % (n, i))
    except Exception as e:      # noqa: BLE001 — важен сам факт исключения
        _errs.append(repr(e))


ths = [threading.Thread(target=_writer, args=(k,)) for k in range(8)]
for t in ths:
    t.start()
for t in ths:
    t.join()
_all, _latest, _ = par.snapshot(0, 1000)
check("A10. КРИТИЧНО: одновременная запись из нескольких потоков не ломает нумерацию",
      not _errs and _latest == 1600 and len(set(r["seq"] for r in _all)) == len(_all))
check("A11. сбой файла журнала не ломает буфер (буфер не трогает диск вовсе)",
      "open(" not in _BUF_SRC and "os.makedirs" not in _BUF_SRC)
buf.clear()
check("A12. очистка буфера не сбрасывает нумерацию", buf.stats()["latest_seq"] == 22)

print()
print("=" * 95)
print("B. ВЫЧИЩЕНИЕ СЕКРЕТОВ")
print("=" * 95)

R = B.redact
check("B1. КРИТИЧНО: Authorization скрывается ЦЕЛИКОМ (вместе со схемой и значением) — проверяем "
      "и Basic: его правило для Bearer не покрывает, поэтому одной страховки мало",
      "eyJ" not in R("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.body.sig")
      and B.REDACTED in R("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.body.sig")
      and "dXNlcjpwYXNz" not in R("Authorization: Basic dXNlcjpwYXNz")
      and B.REDACTED in R("Authorization: Basic dXNlcjpwYXNz"))
check("B2. КРИТИЧНО: cookie скрывается целиком",
      "abc123" not in R("Cookie: fm_session=abc123; theme=dark")
      and "zzz" not in R("Set-Cookie: fm_session=zzz; HttpOnly"))
check("B3. bearer-токен без заголовка тоже скрывается", "qwerty" not in R("bearer qwerty123456"))
check("B4. КРИТИЧНО: пароль скрывается", "hunter2" not in R("password=hunter2"))
check("B5. КРИТИЧНО: код доступа принтера скрывается",
      "12345678" not in R("access_code=12345678") and "9999" not in R("lan-code: 9999"))
check("B6. КРИТИЧНО: recovery-токен скрывается", "9f8e7d" not in R("recovery_token=9f8e7d6c"))
check("B7. КРИТИЧНО: секрет в адресе скрывается",
      "abcdef" not in R("открыт http://127.0.0.1:8123/#recover?token=abcdef123")
      and "secret" not in R("http://user:secret@192.168.1.50:8000/api"))
check("B8. КРИТИЧНО: абсолютные пути наружу не выходят",
      "3DIWELL" not in R(r"файл C:\Users\Someone\AppData\Local\3DIWELL\farm_parts.db")
      and B.REDACTED in R(r"C:\Users\Someone\AppData\Local\3DIWELL\config.json"))
check("B9. КРИТИЧНО: G-code не выходит",
      B.REDACTED == R("G1 X10 Y10 E5 F1500").strip() and B.REDACTED == R("M104 S210").strip())
check("B10. серийный номер принтера скрывается", "01P00A" not in R("serial=01P00A1234567"))
check("B11. обычное безопасное сообщение НЕ портится",
      R("[BAMBU] принтер подключён, температура 210") == "[BAMBU] принтер подключён, температура 210")
check("B12. слишком длинная строка обрезается (сырой дамп в журнал не попадает)",
      len(R("x" * 9000)) < 2100)
check("B13. КРИТИЧНО: вычищение выполняется ПРИ ЗАПИСИ — просмотр, копирование и сохранение "
      "получают один и тот же безопасный текст",
      "redact(message)" in _BUF_SRC
      and (lambda b: (b.append("info", "password=zzz"),
                      "zzz" not in b.snapshot(0, 5)[0][0]["message"])[1])(B.LogBuffer()))

print()
print("=" * 95)
print("C. ОГРАНИЧЕННОЕ ЧТЕНИЕ И ГРАНИЦА ДОСТУПА")
print("=" * 95)

big = B.LogBuffer(capacity=3000)
for i in range(1500):
    big.append("info" if i % 3 else "error", "строка %d" % i)
recs, latest, more = big.snapshot(0, 250)
check("C1. КРИТИЧНО: по умолчанию ответ ограничен", len(recs) == 250 and more is True)
recs2, _l, _m = big.snapshot(0, 99999)
check("C2. КРИТИЧНО: запрошенный лимит зажимается сверху", len(recs2) == 1000)
recs3, _l, _m = big.snapshot(after_seq=1400, limit=250)
check("C3. КРИТИЧНО: after_seq отдаёт ТОЛЬКО новые записи",
      recs3 and all(r["seq"] > 1400 for r in recs3))
recs4, _l, _m = big.snapshot(0, 50, min_level="error")
check("C4. фильтр по уровню работает на сервере", all(r["level"] == "error" for r in recs4))
check("C5. мусорные значения параметров не роняют чтение",
      len(big.snapshot(after_seq="нет", limit="много")[0]) == 250)

_diag = fn_src("diagnostics")
check("C6. КРИТИЧНО: маршрут журнала закрыт административной границей",
      "_require_system_admin(req)" in _diag)
check("C7. КРИТИЧНО: права проверяются ДО чтения буфера",
      _diag.index("_require_system_admin") < _diag.index("_ring_handler"))
check("C8. КРИТИЧНО: путь к файлу журнала наружу не отдаётся и от клиента не принимается",
      "LOG_FILE" not in _diag and "path" not in _diag.lower().split("def diagnostics")[-1][:400])
check("C9. ответ несёт служебные счётчики просмотра",
      all(k in _diag for k in ("latest_seq", "has_more", "dropped_count", "viewer_available")))
check("C10. КРИТИЧНО: пользовательский шаблон поиска на сервере НЕ исполняется",
      "re.compile" not in _diag and "eval(" not in _diag)
check("C11. в реестре маршрутов журнал помечен административной границей",
      "('GET', '/api/diagnostics', 'diagnostics', 'diagnostics', 'browser', 'SENSITIVE', "
      "('NONE',), 'SYSTEM_ADMIN', None)" in
      open(os.path.join(REPO, "app", "route_policy_registry.py"), encoding="utf-8").read())
check("C12. КРИТИЧНО: нового публичного маршрута журнала не добавлено (@app.* = 197)",
      len(re.findall(r'@app\.(get|post|patch|delete|websocket)\(', _SRV)) == 209)   # Alpha 2.823: +5 printer-files; 2.825: +select-for-print; 2.831: +2 printer-sort-mode; 2.833: +2 klipper-prestart; 2.839: +klipper-contract-report; 2.903: +3 UI 3.0; 2.920: +5 очередь ожидания; 2.927: +3 пометки принтера и настройки фермы; 2.947 +staging/sync; 2.948 -projects2/pending-printable; 2.979 +projects2 files/locate; 2.980 +4 printer-discovery, +3 net-capture; 2.994 +6 маршрутов модуля messengers; 12.09.2026 -1 маршрут пометок принтера

print()
print("=" * 95)
print("D. ОКНО ЖУРНАЛА")
print("=" * 95)

check("D1. КРИТИЧНО: окно журнала открывается из настроек и из якоря «#logs» (пункт трея)",
      "openDiagnostics()" in _HTML and "'#logs'" in _APP and "openDiagnostics()" in
      _APP[_APP.index("#logs") - 400:_APP.index("#logs") + 400])
check("D2. КРИТИЧНО: «Очистить экран» очищает ТОЛЬКО показанное — ни файла, ни серверного буфера",
      "diagnostics/clear" not in _APP.split("const clearDiag")[1][:300]
      and "diagEntries.value = []" in _APP.split("const clearDiag")[1][:300])
_close = _APP.split("const closeDiagnostics")[1][:400]
check("D3. КРИТИЧНО: закрытие окна журнала не завершает сервер — оно только гасит опрос",
      "if (diagTimer) { clearInterval(diagTimer); diagTimer = null; }" in _close
      and "fetch(" not in _close and "restart" not in _close)
check("D4. КРИТИЧНО: пауза прекращает обновление экрана",
      "if (diagPaused.value) return;" in _APP.split("const fetchDiag")[1][:200])
check("D5. после продолжения записи дочитываются по номеру (ничего не теряется)",
      "if (!diagPaused.value) fetchDiag();" in _APP)
check("D6. поиск идёт по уже полученным безопасным строкам и НЕ уходит на сервер",
      "diagSearch" in _APP and "search=" not in _APP.split("const fetchDiag")[1][:400])
check("D7. фильтр уровней сохранён", "diagFilter" in _APP and "'ERROR'" in _APP)
check("D8. КРИТИЧНО: копирование и сохранение берут ТОЛЬКО видимые записи",
      "diagFiltered.value" in _APP.split("const diagVisibleText")[1][:200]
      and "diagVisibleText()" in _APP.split("const copyDiag")[1][:200]
      and "diagVisibleText()" in _APP.split("const exportDiag")[1][:300])
check("D9. сохранение отдаёт обычный текстовый файл", "text/plain" in _APP and ".txt" in _APP)
_DIAGROW = open(os.path.join(REPO, "web", "components", "diagnostics", "DiagRow.js"),
                encoding="utf-8").read()
check("D10. КРИТИЧНО: запись журнала не рендерится как HTML — иначе строка из журнала могла бы "
      "внести в интерфейс чужую разметку",
      "v-html" not in _HTML.split('id="diagBody"')[1][:900]
      and "v-html" not in _DIAGROW and "innerHTML" not in _DIAGROW
      and "innerHTML" not in _APP and "diagInnerHtml" not in _APP)
check("D11. КРИТИЧНО: список в окне ограничен — бесконечного DOM нет",
      "diagEntries.value.length - 1200" in _APP)
check("D12. показан счётчик видимых записей и состояние соединения",
      "diagFiltered.length" in _HTML and "diagStateText" in _HTML)
check("D13. КРИТИЧНО: потеря связи показывается честно (сервер мог перезапуститься или сменить "
      "порт) — окно не молчит и не зависает",
      re.search(r"catch \(e\) \{[^}]*diagLostConnection\.value = true",
                _APP.split("const fetchDiag")[1][:1200], re.S) is not None
      and "Соединение потеряно" in _APP)
check("D14. новые состояния экспортированы в шаблон",
      "diagSearch, diagPaused, diagLostConnection, diagStateText, toggleDiagPause, copyDiag, exportDiag," in _APP)

print()
print("=" * 95)
print("E. ТРЕЙ И КОНСОЛЬ")
print("=" * 95)

_tray = fn_src("_start_tray_detached")


def code_strings(src_text):
    """Строковые литералы КОДА, без докстрок.

    Текстовый поиск здесь обманывает: в пояснении к этой же функции честно написано, что пункта
    «Показать консоль (логи)» больше нет, и наивная проверка нашла бы собственную прозу."""
    tree = ast.parse(src_text)
    doc_ids = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if n.body and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant):
                doc_ids.add(id(n.body[0].value))
    return [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in doc_ids]


check("E1. КРИТИЧНО: пункта «Показать консоль (логи)» больше нет (сверяем строки КОДА меню, "
      "а не пояснения к нему)",
      not [s for s in code_strings(_tray) if "Показать консоль" in s])
check("E2. КРИТИЧНО: появился пункт «Открыть журнал Farm Manager»",
      'MenuItem("Открыть журнал Farm Manager"' in _tray)
check("E3. КРИТИЧНО: пункт журнала НЕ показывает консоль",
      "_show_console_window" not in fn_src("_open_log_viewer", _tray))
check("E4. КРИТИЧНО: в пользовательском пути нет создания консоли",
      not re.search(r"AllocConsole|AttachConsole", _SRV))
check("E5. КРИТИЧНО: журнал открывается собственным окном, а при его недоступности — браузером",
      "_open_desktop_shell(LOG_VIEW_FRAGMENT)" in _tray
      and "_open_local_url" in fn_src("_open_desktop_shell"))
check("E6. КРИТИЧНО: второй backend при открытии журнала не запускается "
      "(оболочка сама ищет работающий сервер)",
      "find_running_local" in _SHELL_SRC and "ensure_local_backend" not in fn_src("_open_desktop_shell"))
check("E7. КРИТИЧНО: якорь раздела не содержит и не может содержать секрет",
      'LOG_VIEW_FRAGMENT = "#logs"' in _SRV and "token" not in fn_src("_open_log_viewer", _tray).lower())
from app import desktop_shell_config as shcfg
check("E8. якорь проверяется по белому списку символов (ни схемы, ни хоста, ни параметров)",
      shcfg.normalize_fragment("logs") == "#logs"
      and shcfg.normalize_fragment("#logs") == "#logs"
      and shcfg.normalize_fragment("http://evil/x") == ""
      and shcfg.normalize_fragment("#a?token=1") == ""
      and shcfg.normalize_fragment("") == "")
check("E9. КРИТИЧНО: «Выход» из трея по-прежнему завершает программу штатно",
      'MenuItem("Выход"' in _tray)
check("E10. КРИТИЧНО: консоль прячется всегда, кроме явного режима разработчика",
      "if not _DEBUG_CONSOLE:" in _tray and "_hide_console_window()" in _tray)
check("E11. КРИТИЧНО: режим разработчика включается ТОЛЬКО аргументом командной строки",
      '_DEBUG_CONSOLE = ("--debug-console" in sys.argv)' in _SRV
      and "--debug-console" not in _APP and "--debug-console" not in _HTML)
_dbg_assigns = [n for n in ast.walk(ast.parse(_SRV)) if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "_DEBUG_CONSOLE" for t in n.targets)]
check("E12. КРИТИЧНО: включить консоль через HTTP невозможно — признак задаётся РОВНО ОДИН РАЗ "
      "из аргументов запуска и больше нигде не переприсваивается",
      len(_dbg_assigns) == 1 and "sys.argv" in (ast.unparse(_dbg_assigns[0].value)))

print()
print("=" * 95)
print("F. ГРАНИЦЫ И РЕГРЕССИИ")
print("=" * 95)

check("F1. файловый журнал сохранён: ротация ограничена по размеру и числу файлов",
      "RotatingFileHandler" in _SRV and "maxBytes=2_000_000" in _SRV and "backupCount=5" in _SRV)
check("F2. КРИТИЧНО: окно журнала файл не открывает и не удаляет",
      "LOG_FILE" not in _APP and "unlink" not in _APP.split("const clearDiag")[1][:300])
check("F3. КРИТИЧНО: буфер и вычищение живут отдельным чистым модулем",
      all(s not in _BUF_SRC for s in ("import server", "sqlite3", "import socket", "urllib", "subprocess")))
check("F4. буфер не хранится в базе данных", "sqlite" not in _BUF_SRC.lower())
check("F5. Alpha 2.812 сохранена: окно следует активному порту",
      "def find_running_local" in _SHELL_SRC and "candidate_local_ports" in _SHCFG_SRC)
check("F6. Alpha 2.811 сохранена: изоляция packaged E2E на месте",
      os.path.isfile(os.path.join(REPO, "app", "e2e_isolation.py"))
      and os.path.isfile(os.path.join(REPO, "tools", "test_packaged_restart_end_to_end.py")))
check("F7. Alpha 2.810/2.809 сохранены: подтверждение перезапуска до остановки",
      "verify_armed" in _SRV and '"restart_armed": True' in _SRV)
check("F8. Alpha 2.808 сохранена: управление модулями",
      "_failed_modules" in _SRV and "MODULE_STATE_VERSION_MISMATCH" in _SRV)
check("F9. Alpha 2.807 сохранена: наблюдение внешней печати",
      "observe_printer_job(" in _SRV)
check("F10. закрытие собственного окна не завершает сервер (инвариант 2.805)",
      "backend продолжает работать" in _SHELL_SRC)
check("F11. клиент backend не запускает",
      "ensure_local_backend" not in _SHELL_SRC.split("def client_boot")[1].split("def client_connect")[0])
check("F12. схема БД не менялась", "ALTER TABLE printer_job_sessions" not in _SRV and "DROP TABLE" not in _SRV)
check("F13. автоматическая отправка выключена",
      re.search(r"^DISPATCH_ENABLED = False",
                open(os.path.join(REPO, "app", "project_orchestrator.py"), encoding="utf-8").read(), re.M) is not None)
check("F14. транспорт выключен",
      re.search(r"^TRANSPORT_ENABLED = False",
                open(os.path.join(REPO, "app", "project_orchestrator.py"), encoding="utf-8").read(), re.M) is not None)
check("F15. журнал принтерам ничего не отправляет",
      not re.search(r"mqtt|ftplib|8883|8898", _BUF_SRC, re.I))
check("F16. LAN/firewall встроенным журналом не меняются",
      not re.search(r"netsh|firewall", _BUF_SRC, re.I))
check("F17. `_incoming` не используется", "_incoming" not in _BUF_SRC)
check("F18. КРИТИЧНО: тест не открывал сокетов и не запускал процессов", not _VIOLATIONS)
check("F19. sentinel живёт только в оснастке теста",
      all(SENTINEL not in s for s in (_SRV, _APP, _HTML, _BUF_SRC, _SHELL_SRC, _SHCFG_SRC)))
check("F20. работа шла только во временной папке", os.path.realpath(TMP_ROOT).startswith(
    os.path.realpath(tempfile.gettempdir())))
check("F21. артефактов e2e нет", not os.path.exists(os.path.join(REPO, "tools", "_e2e_payload.json")))

print()
print("=" * 95)
_verdict[0] = True
print("Проверок выполнено: %d, провалено: %d" % (_checked, fail))
if fail:
    print("FAIL: %d проверок провалено" % fail)
else:
    print("PASS: журнал показывается внутри программы, секреты вычищаются при записи, чтение "
          "ограничено и закрыто административной границей; пункт трея открывает встроенный "
          "журнал вместо консоли, а закрытие журнала не влияет ни на сервер, ни на печати.")
raise SystemExit(1 if fail else 0)
