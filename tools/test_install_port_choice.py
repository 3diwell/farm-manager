# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""17.09.2026 — порт и папка установки выбираются при установке.

ЗАЧЕМ. Слово владельца: «в процессе установки нужно добавить опцию выбора порта вручную, а также
автоматическую опцию, при которой установщик проверит, занят ли 8000-й порт, и если да — подберёт
свободный, чтобы программа после установки заработала. Также нужно добавить опцию возможности
изменения места установки программы».

ПОЧЕМУ ПАПКА НЕ ПОКАЗЫВАЛАСЬ. У Inno Setup DisableDirPage по умолчанию = auto: страницу выбора
папки он ПРЯЧЕТ, если программа уже установлена. Владелец ставит поверх прежней версии — и папку
сменить было нельзя. Лечится одной строкой DisableDirPage=no.

ПОЧЕМУ ПОРТ ПИШЕТ ПРОГРАММА, А НЕ УСТАНОВЩИК. config.json лежит в папке данных ПОЛЬЗОВАТЕЛЯ,
установщик работает от администратора, и в файле уже могут быть чужие настройки. Установщик
запускает программу одной командой от имени пользователя (--fm-apply-port), она честно проверяет
занятость пробным bind, атомарно пишет порт и возвращает выбранное значение файлом — для правила
брандмауэра.

ЧТО ДОКАЗЫВАЕТСЯ: разбор аргументов и запись порта (на ВРЕМЕННОЙ папке — рабочий config.json НЕ
трогается), автоподбор свободного порта, отказ на мусоре, сохранность чужих ключей, ранняя ветка
в server.py ДО замка одиночного экземпляра, и сам установщик — страница, её тексты на двух языках
и порядок действий после установки.

Запуск: python tools/test_install_port_choice.py   (0 = все проверки пройдены)
"""
import io
import json
import os
import shutil
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app import install_port_cli as C      # noqa: E402

SENTINEL = "INSTALL_PORT_CHOICE_SENTINEL_1709"
fail = 0
total = 0


def check(name, cond, extra=""):
    global fail, total
    total += 1
    print(("PASS" if cond else "FAIL") + " — " + name
          + ((" :: " + str(extra)) if (not cond and extra != "") else ""))
    if not cond:
        fail += 1


CLI_SRC = io.open(os.path.join(REPO, "app", "install_port_cli.py"), encoding="utf-8").read()

print("=== 17.09.2026: порт и папка при установке ===")
print()
print("--- 1. Автоподбор свободного порта ---")
check("1. порт 8000 свободен — берём его", C.pick_port(8000, lambda p: True) == (8000, ""))
check("2. 8000 занят — берётся следующий свободный",
      C.pick_port(8000, lambda p: p == 8003) == (8003, ""))
check("3. всё занято — честный отказ, а не случайный порт",
      C.pick_port(8000, lambda p: False, scan_limit=5) == (None, C.REASON_NO_FREE))
check("4. выше 65535 не поднимаемся",
      C.pick_port(65534, lambda p: False, scan_limit=50) == (None, C.REASON_NO_FREE))
check("5. занятость проверяется настоящим bind из server_port_config, а не выдумкой",
      "check_port_availability" in CLI_SRC)

print()
print("--- 2. Запись порта в настройки (во ВРЕМЕННОЙ папке) ---")
tmp = tempfile.mkdtemp(prefix="fm_port_cli_")
ENV = {"LOCALAPPDATA": tmp, "APPDATA": tmp}
cfgp = C.config_path(ENV)
check("6. путь настроек — тот же, что у программы (папка данных, а не папка установки)",
      cfgp == os.path.join(tmp, "3DIWELL", "config.json"), cfgp)

port, reason = C.apply_choice("auto", env=ENV, is_free=lambda p: p >= 8002)
check("7. авто: записан первый свободный порт", (port, reason) == (8002, ""), (port, reason))
saved = json.load(io.open(cfgp, encoding="utf-8"))
check("8. в настройках рабочий порт и никаких незавершённых переходов",
      saved.get("server_port") == 8002 and saved.get("pending_server_port") is None
      and saved.get("previous_server_port") is None, saved)

#  Чужие ключи (своя папка данных, доступ по сети) обязаны пережить запись порта.
saved["data_dir"] = "D:/ferma"
saved["lan_access_enabled"] = True
io.open(cfgp, "w", encoding="utf-8").write(json.dumps(saved, ensure_ascii=False))
port, reason = C.apply_choice("8123", env=ENV, is_free=lambda p: True)
after = json.load(io.open(cfgp, encoding="utf-8"))
check("9. вручную: записан ровно заданный порт", (port, reason) == (8123, ""), (port, reason))
check("10. КЛЮЧЕВОЕ: чужие настройки в config.json сохранены",
      after.get("data_dir") == "D:/ferma" and after.get("lan_access_enabled") is True
      and after.get("server_port") == 8123, after)

for bad, why in ((" ", "пусто"), ("80", "ниже 1024"), ("70000", "выше 65535"),
                 ("abc", "не число"), ("0x1F90", "hex"), ("8000 8001", "два числа")):
    p_, r_ = C.apply_choice(bad, env=ENV, is_free=lambda p: True)
    check("11. мусор отклонён (%s)" % why, p_ is None and r_ != "", (p_, r_))
still = json.load(io.open(cfgp, encoding="utf-8"))
check("12. после отказа настройки не тронуты", still.get("server_port") == 8123, still)

io.open(cfgp, "w", encoding="utf-8").write("{это не json")
p_, r_ = C.apply_choice("8200", env=ENV, is_free=lambda p: True)
check("13. битый config.json НЕ перезаписывается — чужие настройки дороже нашего порта",
      (p_, r_) == (None, C.REASON_CONFIG)
      and io.open(cfgp, encoding="utf-8").read().startswith("{это"), (p_, r_))
shutil.rmtree(tmp, ignore_errors=True)

print()
print("--- 3. Команда установщика ---")
check("14. разбор аргументов: обе формы записи",
      C.parse_args(["x", "--fm-apply-port", "auto", "--fm-port-out", "f.txt"]) == ("auto", "f.txt")
      and C.parse_args(["--fm-apply-port=8123", "--fm-port-out=o.txt"]) == ("8123", "o.txt"))
check("15. признак команды виден серверу при любом виде аргумента",
      C.requested(["--fm-apply-port", "auto"]) and C.requested(["--fm-apply-port=8000"])
      and not C.requested(["--no-browser"]))

tmp2 = tempfile.mkdtemp(prefix="fm_port_cli2_")
out = os.path.join(tmp2, "chosen.txt")
rc = C.main(["srv", "--fm-apply-port", "auto", "--fm-port-out", out],
            env={"LOCALAPPDATA": tmp2, "APPDATA": tmp2}, is_free=lambda p: p == 8007)
check("16. команда сообщает установщику ВЫБРАННЫЙ порт файлом",
      rc == 0 and io.open(out, encoding="ascii").read().strip() == "8007", rc)
check("17. без значения — код 2 (установщик увидит отказ)",
      C.main(["srv", "--fm-port-out", out], env={"LOCALAPPDATA": tmp2, "APPDATA": tmp2}) == 2)
shutil.rmtree(tmp2, ignore_errors=True)

print()
print("--- 4. Ранняя ветка в server.py ---")
SRV = io.open(os.path.join(REPO, "server.py"), encoding="utf-8").read()
i_branch = SRV.find("--fm-apply-port")
i_lock = SRV.find("_single_instance.acquire(")
check("18. ветка есть и стоит ДО замка одиночного экземпляра",
      i_branch > 0 and i_lock > 0 and i_branch < i_lock, (i_branch, i_lock))
check("19. команда уходит в отдельный чистый модуль, а не живёт в теле сервера",
      "install_port_cli" in SRV and "sys.exit(_install_port_cli.main(sys.argv))" in SRV)
check("20. воркеры пула разбора файлов в эту ветку не заходят",
      "--multiprocessing-fork" in SRV[max(0, i_branch - 800):i_branch + 400])

print()
print("--- 5. Установщик ---")
ISS = io.open(os.path.join(REPO, "3diwell-setup.iss"), encoding="utf-8").read()
PAGE = io.open(os.path.join(REPO, "tools", "installer", "portpage.iss"), encoding="utf-8").read()
check("21. ПАПКА УСТАНОВКИ: страница показывается ВСЕГДА (у Inno по умолчанию она прячется, "
      "когда программа уже установлена)", "DisableDirPage=no" in ISS)
check("22. страница порта подключена последней строкой файла (иначе Inno не компилируется)",
      ISS.rstrip().endswith('#include "tools\\installer\\portpage.iss"'))
check("23. после установки порт задаёт САМА ПРОГРАММА и от имени пользователя",
      "--fm-apply-port {code:FmGetPortArg}" in ISS and "runasoriginaluser" in ISS
      and "waituntilterminated" in ISS)
check("24. брандмауэр открывает ВЫБРАННЫЙ порт, а прежнее правило снимается",
      "localport={code:FmGetFinalPort}" in ISS and "firewall delete rule" in ISS
      and "localport=8000" not in ISS)
check("25. на странице два варианта, по умолчанию — автоматический",
      "{cm:PortAuto}" in PAGE and "{cm:PortManual}" in PAGE
      and "SelectedValueIndex := 0" in PAGE)
check("26. занятость 8000 проверяется и говорится словами",
      "FmPortIsBusy(8000)" in PAGE and "netstat" in PAGE and "{cm:PortBusy}" in PAGE
      and "{cm:PortFree}" in PAGE)
check("27. ручной ввод проверяется: диапазон и только цифры",
      "1024" in PAGE and "65535" in PAGE and "{cm:PortBadValue}" in PAGE
      and "IntToStr(Port) <> Value" in PAGE)
check("28. занятый порт вручную — спрашиваем, а не молча ставим",
      "{cm:PortBusyAsk}" in PAGE and "MB_YESNO" in PAGE)
check("29. список вариантов не занимает всю страницу (иначе поле ввода уезжает за край)",
      "CheckListBox.Height :=" in PAGE)
keys = [ln.split("=", 1)[0].split(".", 1)[1] for ln in PAGE.splitlines()
        if ln.startswith("russian.") and "=" in ln]
missing = [k for k in keys if ("english." + k + "=") not in PAGE]
check("30. каждый текст страницы есть на обоих языках", not missing, missing)
check("31. команда меняет в настройках только порт (ключи взяты из общего контракта)",
      "KEY_ACTIVE" in CLI_SRC and "KEY_PENDING" in CLI_SRC and "KEY_PREVIOUS" in CLI_SRC)

print()
print("=" * 78)
print("МЕТКА: %s" % SENTINEL)
print("ИТОГО: PASS=%d FAIL=%d" % (total - fail, fail))
sys.exit(1 if fail else 0)
