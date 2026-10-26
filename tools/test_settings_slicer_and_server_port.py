# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Настройки: слайсер во вкладке «Печать» и серверный порт в «Сеть и доступ» — Alpha 2.814.
=================================================================================================
ЗАЧЕМ ЭТОТ ТЕСТ СУЩЕСТВУЕТ.

Два пользовательских замечания. (1) Карточка «Интеграция со слайсером» жила в системных
настройках, хотя относится к печати. (2) Серверный порт можно было сменить ТОЛЬКО через меню
значка в трее — в самих настройках его не было видно вовсе.

ГЛАВНЫЙ АРХИТЕКТУРНЫЙ РИСК ЭТОЙ ЗАДАЧИ — вторая реализация смены порта. Если бы настройки
проверяли и записывали порт по-своему, появились бы два расходящихся источника истины: тихо
разъехавшиеся правила проверки, конкурирующая запись config и перезапуск в обход supervisor,
который в 2.809–2.811 научили не терять работающий сервер. Поэтому здесь проверяется не только
поведение, но и ЕДИНСТВЕННОСТЬ реализации: и трей, и настройки обязаны звать одни и те же
функции ядра.

ПОЛНОСТЬЮ OFFLINE: временная папка и временный config, поддельные сокеты и перезапуск; рабочие
config/БД/DATA_DIR не читаются и не пишутся, рабочие порты не занимаются, принтеры и сеть не
участвуют, интерфейс не открывается.

Запуск: PYTHONIOENCODING=utf-8 python tools/test_settings_slicer_and_server_port.py   (0 = пройдено)
"""
import ast
import atexit
import json
import os
import re
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

SENTINEL = "SETTINGS_SLICER_PORT_SENTINEL_2_814"

# ── Ловушки: сеть и запуск процессов запрещены ────────────────────────────────────────────────
import socket as _socket_mod
import subprocess as _subprocess_mod

_VIOLATIONS = []


class _NoSocket(object):
    def __init__(self, *a, **k):
        _VIOLATIONS.append("socket")
        raise RuntimeError("сеть в offline-тесте запрещена")


_socket_mod.create_connection = lambda *a, **k: _NoSocket()


class _NoPopen(object):
    def __init__(self, *a, **k):
        _VIOLATIONS.append("subprocess")
        raise RuntimeError("запуск процессов в offline-тесте запрещён")


_subprocess_mod.Popen = _NoPopen

_TMP = tempfile.TemporaryDirectory(prefix="fm_settings_port_2814_")
TMP_ROOT = os.path.realpath(_TMP.name)
CFG_PATH = os.path.join(TMP_ROOT, "config.json")

from app import server_port_config as PC

_SRV = open(os.path.join(REPO, "server.py"), encoding="utf-8").read()
_APP = open(os.path.join(REPO, "web", "app.js"), encoding="utf-8").read()
_HTML = open(os.path.join(REPO, "web", "index.html"), encoding="utf-8").read()
_SRV_AST = ast.parse(_SRV)

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


def fn_src(name):
    for n in ast.walk(_SRV_AST):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            return ast.get_source_segment(_SRV, n) or ""
    return ""


def calls_in(src_text):
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


def code_strings(src_text):
    """Строковые литералы КОДА без докстрок — иначе проверка ловит собственные пояснения."""
    tree = ast.parse(src_text)
    doc = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if n.body and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant):
                doc.add(id(n.body[0].value))
    return [n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in doc]


def set_group_tabs():
    """Вкладка каждой карточки настроек в порядке их следования в разметке."""
    # Alpha 2.834: у карточек появились id (мини-навигация) и дополнительный класс широкой секции —
    # сопоставляем открывающий тег шире, а не дословной строкой '<div class="fm-set-group"'.
    return [(m.group(1), m.start()) for m in
            re.finditer(r'<div [^>]*class="fm-set-group[^"]*"[^>]*?curSetTab===\'(\w+)\'', _HTML)]


SLICER_ANCHOR = "'Интеграция со слайсером':'Slicer integration'"


def slicer_card():
    """Разметка карточки интеграции со слайсером целиком."""
    i = _HTML.index(SLICER_ANCHOR)
    _op = [m.start() for m in re.finditer(r'<div [^>]*class="fm-set-group', _HTML[:i])]
    s = _op[-1]
    depth, end = 0, s
    for m in re.finditer(r'<div\b|</div>', _HTML[s:]):
        depth += 1 if m.group(0) == "<div" else -1
        if depth == 0:
            end = s + m.end()
            break
    return _HTML[s:end], s


print("=" * 95)
print("A. КАРТОЧКА ИНТЕГРАЦИИ СО СЛАЙСЕРОМ ПЕРЕЕХАЛА В «ПЕЧАТЬ»")
print("=" * 95)

card, card_pos = slicer_card()
check("A1. КРИТИЧНО: карточка существует РОВНО одна (копии не создано)",
      _HTML.count(SLICER_ANCHOR) == 1)
check("A2. КРИТИЧНО: карточка показывается во вкладке «Печать»",
      "curSetTab==='print'" in card)
check("A3. КРИТИЧНО: во вкладке «Система» её больше нет",
      "curSetTab==='system'" not in card)
_tabs = [t for t, _p in set_group_tabs()]
check("A4. карточка стоит ПОСЛЕ остальных параметров печати",
      [t for t, p in set_group_tabs() if p == card_pos] == ["print"]
      and _tabs.index("system") > max(i for i, t in enumerate(_tabs) if t == "print"))
check("A5. КРИТИЧНО: статус интеграции сохранён (настроено/отключено/не настроено + дата)",
      "sliCb.configured" in card and "sliCb.enabled" in card and "sliCb.created_at" in card)
check("A6. КРИТИЧНО: кнопка замены/создания ключа сохранена",
      "sliCbGenerate()" in card and "Заменить ключ" in card and "Replace key" in card)
check("A7. КРИТИЧНО: кнопка отключения сохранена",
      "sliCbRevoke()" in card and "Отключить" in card and "Disable" in card)
check("A8. показ и копирование одноразового ключа сохранены",
      "sliCbToken" in card and "sliCbCopy()" in card and "sliCbHide()" in card)
check("A9. права карточки не ослаблены (только администратор)", "can('admin')" in card)
check("A10. RU/EN тексты сохранены",
      "Сохраните ключ сейчас" in card and "Save the key now" in card)
check("A11. КРИТИЧНО: перенос не трогает ни ключ, ни его API — обработчики те же",
      all(s in _APP for s in ("const sliCbGenerate", "const sliCbRevoke", "const sliCbLoad"))
      and "/api/slicer-callback" in _APP)
check("A12. КРИТИЧНО: перенос не создаёт ключ и не отключает интеграцию сам по себе — в карточке "
      "нет вызовов, срабатывающих без нажатия",
      "@click=\"sliCbGenerate()\"" in card and "@click=\"sliCbRevoke()\"" in card
      and "created(" not in card and "mounted" not in card)

print()
print("=" * 95)
print("B. ПОРТ В НАСТРОЙКАХ: ОТОБРАЖЕНИЕ")
print("=" * 95)

# Alpha 2.834: у секций настроек появились id (мини-навигация) и доп. классы (широкая секция),
# поэтому границу карточки ищем по РЕГУЛЯРНОМУ выражению, а не по дословному '<div class="fm-set-group"'.
_net_i = _HTML.find("'Сеть и доступ':'Network & access'")
_net_s = [m.start() for m in re.finditer(r'<div [^>]*class="fm-set-group', _HTML[:_net_i])][-1]
_net_rest = _HTML[_net_s:]
_net_nx = [m.start() for m in re.finditer(r'<div [^>]*class="fm-set-group', _net_rest[10:])]
_net_card = _net_rest[:(_net_nx[0] + 10) if _net_nx else len(_net_rest)]
check("B1. КРИТИЧНО: активный порт показан в карточке «Сеть и доступ»",
      "'Порт сервера':'Server port'" in _net_card and "netPort" in _net_card)
check("B2. КРИТИЧНО: значение берётся ИЗ ОТВЕТА СЕРВЕРА, а не придумывается интерфейсом",
      "netPort.value = Number(j.port)" in _APP)
check("B3. КРИТИЧНО: текущий порт фермы (8123) нигде не зашит в интерфейсе",
      "8123" not in _APP and "8123" not in _HTML)
check("B4. КРИТИЧНО: 8000 не становится значением по умолчанию в интерфейсе",
      "8000" not in _APP.split("const netPort")[1][:4000])
# Alpha 2.834: ожидающий порт показан в machine-строке значением + бейджем «Требуется перезапуск».
check("B5. ожидающий порт показан отдельной строкой (значение + бейдж перезапуска)",
      "netPendingPort" in _net_card and "fm-bdg-rst" in _net_card
      and ("после перезапуска" in _net_card or "after restart" in _net_card))
check("B6. КРИТИЧНО: прежний порт (для отката) наружу не показывается",
      "previous_server_port" not in _APP and "previous" not in _net_card.lower())
# Alpha 2.834: пояснение сокращено до одной строки-подсказки (экран не должен быть полотном текста).
check("B7. пояснение назначения порта присутствует (краткая подсказка RU/EN)",
      "Через него подключаются браузер" in _net_card and "The browser, the app window and clients" in _net_card)
check("B8. КРИТИЧНО: состояние берётся из общего ответа /api/network — общего у трея и настроек",
      "const loadNetworkInfo" in _APP and "fetch('/api/network')" in _APP)

print()
print("=" * 95)
print("C. ДИАЛОГ ИЗМЕНЕНИЯ ПОРТА")
print("=" * 95)

_dlg = _HTML[_HTML.find('v-if="showPortDialog"'):]
_dlg = _dlg[:_dlg.find("restartPhase==='arming'")]
check("C1. диалог показывает текущий порт и поле ввода",
      "'Текущий порт':'Current port'" in _dlg and 'v-model="portInput"' in _dlg)
check("C2. диапазон 1024–65535 указан пользователю",
      'min="1024"' in _dlg and 'max="65535"' in _dlg and "от 1024 до 65535" in _dlg)
check("C3. КРИТИЧНО: предупреждение о перезапуске показано ДО действия",
      "требуется перезапуск Farm Manager" in _dlg and "must restart to apply" in _dlg)
check("C4. три действия: отмена, применить позже, применить и перезапустить",
      "'Отмена':'Cancel'" in _dlg and "'Применить позже':'Apply later'" in _dlg
      and "'Применить и перезапустить':'Apply and restart'" in _dlg)
check("C5. КРИТИЧНО: Enter не выполняет перезапуск сам по себе",
      "@keydown.enter.prevent" in _dlg)
# Alpha 2.815: граница СМЕЩЕНА намеренно. До 2.815 Escape ловил локальный @keydown.escape на самой
# панели — он срабатывал, только если фокус уже был внутри диалога, а фокус туда никто не переводил.
# Теперь диалог заявляет себя слоем общего стека, и Escape закрывает ВЕРХНИЙ слой централизованно.
check("C6. Escape и клик мимо закрывают диалог (через единый стек, а не локальный обработчик)",
      "v-modal-layer=" in _dlg and "close: closePortDialog" in _dlg
      and 'class="fm-ov-back" @click="closePortDialog()"' in _dlg
      and "fmModalTopNested" in _APP)
check("C7. КРИТИЧНО: двойная отправка блокируется",
      "if (portBusy.value) return;" in _APP.split("const applyPort")[1][:200])
check("C8. во время проверки показывается ожидание", "'Проверка…':'Checking…'" in _dlg)
check("C9. КРИТИЧНО: ошибка НЕ закрывает диалог и введённое значение сохраняется",
      re.search(r"portError\.value = portReasonText[^;]*;\s*await loadNetworkInfo\(\);\s*return;",
                _APP.split("const applyPort")[1][:1200]) is not None
      and "portInput.value = ''" not in _APP)
check("C10. закрытие во время проверки запрещено (иначе операция осталась бы без ответа)",
      "if (!portBusy.value) showPortDialog.value = false;" in _APP)
check("C11. КРИТИЧНО: наружу не показываются ни пути, ни команды, ни traceback",
      not re.search(r"config\.json|Traceback|\.exe|sys\.argv", _dlg)
      and not re.search(r"config\.json|Traceback|\.exe", _APP.split("const PORT_REASONS")[1][:1400]))
check("C12. тексты причин общие с перезапуском из трея (нет второго словаря ошибок)",
      "return restartReasonText(code);" in _APP)

print()
print("=" * 95)
print("D. ЕДИНЫЙ BACKEND-СЕРВИС (главный инвариант задачи)")
print("=" * 95)

_net_post = fn_src("set_network")
_tray_dialog = fn_src("_show_change_port_dialog")
check("D1. КРИТИЧНО: настройки зовут ТОТ ЖЕ подготовительный сервис, что и трей",
      "_prepare_port_change" in calls_in(_net_post) and "_prepare_port_change" in _tray_dialog)
check("D2. КРИТИЧНО: настройки зовут ТОТ ЖЕ перезапуск, что и трей",
      "_restart_for_port" in calls_in(_net_post) and "_restart_for_port" in _tray_dialog)
check("D3. КРИТИЧНО: второй реализации проверки/записи порта в маршруте нет",
      not (calls_in(_net_post) & {"validate_server_port", "check_port_availability",
                                  "plan_change", "commit_pending", "rollback_pending"}))
check("D4. КРИТИЧНО: маршрут сам не пишет config — это делает общий сервис",
      "_write_config_atomic" not in calls_in(_net_post))
check("D5. КРИТИЧНО: перезапуск идёт через supervisor (отдельной реализации нет)",
      "perform_restart_async" in fn_src("_restart_for_port"))
check("D6. КРИТИЧНО: интерфейс не присылает ни прежний порт, ни адрес привязки, ни путь, "
      "ни команду перезапуска",
      not re.search(r"previous_port|old_port|bind_host|config_path|executable",
                    _APP.split("const applyPort")[1][:1500]))
check("D7. смена порта НЕ добавила своих HTTP-маршрутов (ядро 183) — расширен существующий /api/network",
      len(re.findall(r'@app\.(get|post|patch|delete|websocket)\(', _SRV)) == 209)   # Alpha 2.823: +5 printer-files; 2.825: +select-for-print; 2.827: +4 config-backup; 2.831: +2 printer-sort-mode; 2.833: +2 klipper-prestart; 2.839: +klipper-contract-report; 2.903: +3 UI 3.0; 2.920: +5 очередь ожидания; 2.927: +3 пометки принтера и настройки фермы; 2.947 +staging/sync; 2.948 -projects2/pending-printable; 2.979 +projects2 files/locate; 2.980 +4 printer-discovery, +3 net-capture; 2.994 +6 маршрутов модуля messengers; 12.09.2026 -1 маршрут пометок принтера
check("D8. ответ маршрута безопасен: только состояние и машинный код причины",
      all(k in _net_post for k in ("active_port", "pending_port", "restart_required",
                                   "restart_armed", "target_origin")))
check("D9. КРИТИЧНО: адрес перехода строит СЕРВЕР, а не браузер",
      'target_origin"] = "http://localhost:%d"' in _net_post
      and "j.target_origin" in _APP)

print()
print("=" * 95)
print("E. ПРОВЕРКА ЗНАЧЕНИЯ (общий валидатор ядра)")
print("=" * 95)

check("E1. 1024 разрешён", PC.validate_server_port(1024) == (1024, ""))
check("E2. 65535 разрешён", PC.validate_server_port(65535) == (65535, ""))
check("E3. КРИТИЧНО: 1023 запрещён", PC.validate_server_port(1023)[1] != "")
check("E4. КРИТИЧНО: 65536 запрещён", PC.validate_server_port(65536)[1] != "")
check("E5. пустое значение запрещено", PC.validate_server_port("")[1] != "")
check("E6. дробное значение запрещено", PC.validate_server_port("8080.5")[1] != "")
check("E7. КРИТИЧНО: адрес вместо порта запрещён",
      PC.validate_server_port("http://127.0.0.1:8080")[1] != ""
      and PC.validate_server_port("127.0.0.1:8080")[1] != "")
def js_code_only(src):
    """JS без строковых литералов — иначе проверка ловит текст подсказки «от 1024 до 65535»,
    который пользователю как раз показать НАДО, а валидатором не является."""
    out, i, n = [], 0, len(src)
    while i < n:
        ch = src[i]
        if ch in "'\"`":
            q, i = ch, i + 1
            while i < n and src[i] != q:
                i += 2 if src[i] == "\\" else 1
            i += 1
            out.append(" ")
            continue
        out.append(ch)
        i += 1
    return "".join(out)


# Смотрим ИМЕННО портовый участок кода: число 1024 встречается в файле и по другому поводу
# (форматирование размера файлов в килобайтах), а текст подсказки диапазона показать пользователю
# как раз нужно — валидатором он не является.
_PORT_JS = js_code_only(_APP[_APP.index("const netPort"):_APP.index("const _applyNet")])
check("E8. КРИТИЧНО: в портовом коде интерфейса нет собственной проверки диапазона — решение "
      "принимает сервер (подсказка диапазона и размеры файлов не в счёт)",
      "1024" not in _PORT_JS and "65535" not in _PORT_JS
      and not re.search(r"(<=|>=|<|>)\s*\d{4,5}", _PORT_JS))
check("E9. проверка занятости выполняется ядром в текущем режиме привязки",
      "check_port_availability" in fn_src("_prepare_port_change"))
check("E10. текущий порт как новое значение — no-op, config не трогается",
      "return (\"noop\", \"noop\", active)" in fn_src("_prepare_port_change"))

print()
print("=" * 95)
print("F. «ПРИМЕНИТЬ ПОЗЖЕ» И ОТКАТ (контракт 2.806 не тронут)")
print("=" * 95)

cfg = {"server_port": 8123, "unknown_field": SENTINEL}
assert PC.plan_change(cfg, 8000)
check("F1. КРИТИЧНО: сохранены ожидающий и прежний порт",
      cfg[PC.KEY_PENDING] == 8000 and cfg[PC.KEY_PREVIOUS] == 8123)
check("F2. КРИТИЧНО: активный порт при этом НЕ меняется", cfg[PC.KEY_ACTIVE] == 8123)
check("F3. неизвестные поля настройки сохраняются", cfg["unknown_field"] == SENTINEL)
st = PC.read_port_state(cfg)
check("F4. состояние отдаёт ожидающий порт отдельно",
      st["active"] == 8123 and st["pending"] == 8000)
cfg2 = dict(cfg)
PC.commit_pending(cfg2)
check("F5. КРИТИЧНО: ожидающий становится активным ТОЛЬКО при подтверждении (после bind)",
      cfg2[PC.KEY_ACTIVE] == 8000 and not cfg2.get(PC.KEY_PENDING))
cfg3 = dict(cfg)
back = PC.rollback_pending(cfg3)
check("F6. КРИТИЧНО: откат возвращает прежний порт и очищает ожидающий",
      back == 8123 and cfg3[PC.KEY_ACTIVE] == 8123 and not cfg3.get(PC.KEY_PENDING))
check("F7. КРИТИЧНО: случайный порт не выбирается никогда",
      "random" not in _SRV.split("def _prepare_port_change")[1][:1500].lower())
check("F8. КРИТИЧНО: смена порта не трогает LAN и авторизацию",
      not (calls_in(fn_src("_prepare_port_change")) & {"can_enable", "_set_security_enabled"})
      and "lan_access_enabled" not in fn_src("_prepare_port_change"))
check("F9. стартовый контракт применения ожидающего порта не изменён",
      "startup_plan" in _SRV and "commit_pending" in _SRV and "rollback_pending" in _SRV)
check("F10. запись настройки атомарна", "_write_config_atomic" in fn_src("_prepare_port_change"))
check("F11. КРИТИЧНО: подготовка смены НЕ объявляет новый порт активным — это делает только "
      "успешный bind на старте (иначе интерфейс и трей показывали бы порт, который ещё никто "
      "не занял)",
      not (calls_in(fn_src("_prepare_port_change")) & {"commit_pending", "rollback_pending"}))
_cfg_rb = {"server_port": 8000, PC.KEY_PENDING: 8123, PC.KEY_PREVIOUS: 8000}
check("F12. КРИТИЧНО: откат ВОЗВРАЩАЕТ прежний порт (а не оставляет несостоявшийся новый)",
      PC.rollback_pending(dict(_cfg_rb)) == 8000
      and PC.rollback_pending({"server_port": 8123, PC.KEY_PENDING: 9000,
                               PC.KEY_PREVIOUS: 8123}) == 8123)

print()
print("=" * 95)
print("G. ПРАВА: ЭТО МАШИННАЯ НАСТРОЙКА")
print("=" * 95)

check("G1. КРИТИЧНО: маршрут закрыт административной границей ДО любых действий",
      "_require_system_admin(req)" in _net_post
      and _net_post.index("_require_system_admin") < _net_post.index("server_port"))
check("G2. КРИТИЧНО: менять порт можно только с компьютера-сервера — даже администратору из сети",
      "_require_server_machine(req)" in _net_post)
check("G3. КРИТИЧНО: машинная граница определяется по транспорту, а не по заголовкам",
      "_peer_of(req)" in fn_src("_require_server_machine")
      and "is_loopback_client" in fn_src("_require_server_machine"))
check("G4. КРИТИЧНО: признак «я Desktop/оболочка» из интерфейса доверенным не считается",
      not re.search(r"desktop|shell|user-agent", fn_src("_require_server_machine"), re.I)
      or "is_loopback_client" in fn_src("_require_server_machine"))
check("G5. удалённый клиент видит порт, но кнопки не получает",
      "Порт меняется только на компьютере-сервере." in _HTML
      and 'v-if="portCanChange"' in _net_card)
check("G6. КРИТИЧНО: подсказка интерфейса не является границей — решение принимает сервер",
      "portCanChange" in _APP and "location.hostname" in _APP
      and "server_machine_only" in _SRV)
check("G7. публичного маршрута записи порта нет",
      _SRV.count('@app.post("/api/network")') == 1)
check("G8. отказ отдаёт машинный код причины без подробностей",
      '"reason": "server_machine_only"' in _SRV)

print()
print("=" * 95)
print("H. ОДНОВРЕМЕННОСТЬ И СИНХРОНИЗАЦИЯ С ТРЕЕМ")
print("=" * 95)

check("H1. КРИТИЧНО: одновременный перезапуск сериализован общим замком",
      "_restart_lock.acquire(blocking=False)" in _SRV and '"restart_in_progress"' in _SRV)
check("H2. диалог трея по-прежнему открывается строго один",
      "_PORT_DIALOG_LOCK.acquire(blocking=False)" in _SRV)
check("H3. КРИТИЧНО: настройки и трей читают одно состояние портов",
      "_read_port_state()" in _net_post and "_read_port_state" in _SRV)
check("H4. КРИТИЧНО: интерфейс не хранит собственный «активный порт» как истину — после действия "
      "состояние перечитывается у сервера",
      "await loadNetworkInfo();" in _APP.split("const applyPort")[1][:1500])
check("H5. неудачная попытка оставляет прежнюю настройку нетронутой",
      "save_fail" in _net_post and "return (\"save_fail\"" in fn_src("_prepare_port_change"))

print()
print("=" * 95)
print("I. ПЕРЕЗАПУСК И ПОВЕДЕНИЕ БРАУЗЕРА")
print("=" * 95)

check("I1. КРИТИЧНО: сервер завершается только после подтверждения готовности",
      "restart_armed" in _net_post and "verify_armed" in _SRV)
check("I2. КРИТИЧНО: браузер переходит на новый адрес только после того, как старый замолчал",
      "downSince" in _APP and "location.assign(target" in _APP)
# Alpha 2.829: определение нового процесса — по boot_id; запасной down/up-путь сохранён для
# сервера без boot_id. Откат порта: старый адрес ожил (новый boot) -> reload ТЕКУЩЕЙ страницы
# (hardReloadOnce) = остаёмся на прежнем адресе; поведение прежнее, определение честнее.
check("I3. КРИТИЧНО: если старый адрес ожил — это откат, остаёмся на нём (boot-aware 2.829)",
      "if (!probe.bootId && downSince) { location.reload(); return; }" in _APP
      and "hardReloadOnce(probe.bootId); return;" in _APP)
check("I4. ожидание ограничено, бесконечного экрана нет",
      re.search(r"for \(let i = 0; i < \d+; i\+\+\)", _APP) is not None
      and "restartPhase.value = 'timeout'" in _APP)
check("I5. есть кнопка повторного подключения", "retryRestartConnection" in _APP)
check("I6. КРИТИЧНО: политика origin ради перехода не ослабляется (сверяем ВЫЗОВЫ, а не "
      "пояснение о том, что CORS был убран в 2.775)",
      "CORSMiddleware" not in calls_in(_SRV)
      and "allow_origins" not in [kw.arg for n in ast.walk(_SRV_AST)
                                  if isinstance(n, ast.Call) for kw in n.keywords]
      and "_origin_guard" in _SRV)
check("I7. собственное окно само найдёт новый порт (резолвер 2.812 сохранён)",
      "def find_running_local" in open(os.path.join(REPO, "app", "desktop_shell.py"),
                                       encoding="utf-8").read())

print()
print("=" * 95)
print("J. ГРАНИЦЫ И РЕГРЕССИИ")
print("=" * 95)

check("J1. схема БД не менялась",
      "ALTER TABLE printer_job_sessions" not in _SRV and "DROP TABLE" not in _SRV)
check("J2. порт в базе данных не хранится", "server_port" not in _SRV.split("def init_db")[1][:6000])
check("J3. встроенный журнал 2.813 сохранён",
      os.path.isfile(os.path.join(REPO, "app", "runtime_log_buffer.py"))
      and "Открыть журнал Farm Manager" in _SRV)
check("J4. packaged restart E2E 2.811 сохранён",
      os.path.isfile(os.path.join(REPO, "tools", "test_packaged_restart_end_to_end.py")))
check("J5. управление модулями 2.808 сохранено", "_failed_modules" in _SRV)
check("J6. наблюдение внешней печати 2.807 сохранено", "observe_printer_job(" in _SRV)
check("J7. автоматическая отправка выключена",
      re.search(r"^DISPATCH_ENABLED = False",
                open(os.path.join(REPO, "app", "project_orchestrator.py"), encoding="utf-8").read(), re.M) is not None)
check("J8. транспорт выключен",
      re.search(r"^TRANSPORT_ENABLED = False",
                open(os.path.join(REPO, "app", "project_orchestrator.py"), encoding="utf-8").read(), re.M) is not None)
check("J9. КРИТИЧНО: смена порта принтерам ничего не отправляет",
      not (calls_in(_net_post) & {"_send_file_to_printer", "printer_cmd", "publish"}))
check("J10. КРИТИЧНО: firewall смена порта не трогает",
      "_ensure_firewall_rule" not in _net_post)
check("J11. sentinel живёт только в оснастке теста",
      all(SENTINEL not in s for s in (_SRV, _APP, _HTML)))
check("J12. КРИТИЧНО: тест не открывал сеть и не запускал процессов", not _VIOLATIONS)
check("J13. работа шла во временной папке; рабочий config не трогался",
      os.path.realpath(TMP_ROOT).startswith(os.path.realpath(tempfile.gettempdir()))
      and not os.path.exists(CFG_PATH))
check("J14. артефактов e2e нет", not os.path.exists(os.path.join(REPO, "tools", "_e2e_payload.json")))
check("J15. `_incoming` не используется", "_incoming" not in _net_post)

print()
print("=" * 95)
_verdict[0] = True
print("Проверок выполнено: %d, провалено: %d" % (_checked, fail))
if fail:
    print("FAIL: %d проверок провалено" % fail)
else:
    print("PASS: интеграция со слайсером живёт во вкладке «Печать» ровно одной карточкой и с теми "
          "же ключом, кнопками и правами; порт виден и меняется из настроек, но проверка, запись, "
          "перезапуск и откат выполняются ТЕМИ ЖЕ функциями ядра, что и у пункта трея.")
raise SystemExit(1 if fail else 0)
