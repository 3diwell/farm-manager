# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.834 — mutation proof редизайна настроек: 20 порч обязаны краснить release gate.

Каждая мутация вносится в РАБОЧИЙ файл, целевой тест запускается, затем файл восстанавливается
БАЙТ-В-БАЙТ (сверка SHA-256). Production-данные не участвуют: правятся только web/* и app/*.

Чтобы прогон был обозримым, порчи разметки/CSS/логики проверяются быстрым статическим режимом
release gate (FM_SETPRO_NO_BROWSER=1) — он ловит их детерминированно; отдельная порча раскладки
(горизонтальная прокрутка) проверяется ПОЛНЫМ браузерным прогоном.
"""
import hashlib
import os
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# Alpha 2.841: наборы mutation proof портят ОДНИ И ТЕ ЖЕ файлы репозитория.
# Параллельный запуск двух наборов уже приводил к тому, что откат одного затирал
# откат другого и в дереве оставалась чужая мутация. Замок сериализует прогоны;
# не дождались — mutation_lock_busy и КРАСНЫЙ выход, а не тихая правка файлов.
sys.path.insert(0, os.path.join(ROOT, "tools"))
from _mutation_lock import acquire_or_die  # noqa: E402
from _mutation_report import build as _mut_build, emit as _mut_emit  # noqa: E402
acquire_or_die('test_settings_redesign_mutation_proof')
ENV = dict(os.environ)
ENV["PYTHONIOENCODING"] = "utf-8"
ENV["PYTHONDONTWRITEBYTECODE"] = "1"

IDX = os.path.join(ROOT, "web", "index.html")
CSS = os.path.join(ROOT, "web", "app.css")
APP = os.path.join(ROOT, "web", "app.js")
ORCH = os.path.join(ROOT, "app", "project_orchestrator.py")
REGP = os.path.join(ROOT, "app", "route_policy_registry.py")

GATE = "test_settings_professional_redesign"
BKP2 = "test_config_backup_v2"
MODS = "test_module_management_settings"
LAN = "test_lan_toggle_ui"


def b(x):
    return x.encode("utf-8")


# (файл, что_ищем, на_что_меняем, тест, только_статика, подпись)
MUT = [
    # 1. булево снова становится кнопкой «Включено»
    (IDX, b('<input type="checkbox" class="fm-chk-in" :checked="pfFlags.read_enabled"'),
     b('<button class="fm-set-toggle" :data-x="pfFlags.read_enabled"'),
     GATE, True, "boolean снова кнопка «Включено»"),
    # 2. checked без галочки
    (CSS, b(".fm-chk-in:checked::after{content:\"\";position:absolute"),
     b(".fm-chk-in-x:checked::after{content:\"\";position:absolute"),
     GATE, True, "checked-состояние рисуется без галочки"),
    # 3. OFF выглядит как ON (фон включённого у всех)
    (CSS, b(".fm-chk-in:checked{background:var(--fm-accent);border-color:var(--fm-accent)}"),
     b(".fm-chk-in{background:var(--fm-accent);border-color:var(--fm-accent)}"),
     GATE, True, "OFF выглядит как ON"),
    # 4. действие получает checkbox
    (IDX, b('<span class="fm-set-act-ic"><svg-icon name="bulb"'),
     b('<input type="checkbox" class="fm-chk-in"><span class="fm-set-act-ic"><svg-icon name="bulb"'),
     GATE, True, "action row получает checkbox"),
    # 5. подтверждение удаления обходится (флаг ставится мимо backend)
    (IDX, b("pfSetFlag('delete_enabled', !pfFlags.delete_enabled)"),
     b("pfFlags.delete_enabled = !pfFlags.delete_enabled"),
     GATE, True, "delete-флаг ставится мимо backend (обход подтверждения)"),
    # 6. ошибка backend не возвращает серверное состояние
    (IDX, b("$event.target.checked = pfFlags.read_enabled; pfSetFlag('read_enabled'"),
     b("pfSetFlag('read_enabled'"),
     GATE, True, "ошибка backend не возвращает состояние (DOM расходится)"),
    # 7. disabled-флажок снова изменяем
    (CSS, b(".fm-chk-in:disabled{cursor:default;opacity:.45}"),
     b(".fm-chk-in-off:disabled{cursor:default;opacity:.45}"),
     GATE, True, "disabled-состояние флажка не оформлено"),
    # 8. длинные описания вернулись в основные строки
    (IDX, b("'Другие компьютеры смогут открыть Farm Manager в этой сети.'"),
     b("'Разрешить другим компьютерам в локальной сети находить и открывать Farm Manager, "
       "не влияя на связь с принтерами, камеры и печать, а также на очередь запуска.'"),
     GATE, True, "длинное полотно текста вернулось в строку настройки"),
    # 9. предупреждение снова обычный текст
    (IDX, b('<div class="fm-pnl fm-pnl-dng" v-if="pfFlags.delete_enabled">'),
     b('<div v-if="pfFlags.delete_enabled">'),
     GATE, True, "danger-предупреждение стало обычным текстом"),
    # 10. пояснение «этот компьютер» удалено
    (IDX, b("<span class=\"fm-bdg fm-bdg-mch\">{{ lang==='ru'?'Этот компьютер':'This computer' }}</span>"),
     b(""), GATE, True, "пояснение «этот компьютер» удалено"),
    # 11. горизонтальная прокрутка в узкой области (ПОЛНЫЙ браузерный прогон)
    (CSS, b("grid-template-columns:repeat(auto-fit,minmax(min(360px,100%),1fr))"),
     b("grid-template-columns:repeat(auto-fit,minmax(560px,1fr))"),
     GATE, False, "сетка распирает узкую область -> горизонтальная прокрутка"),
    # 12. текст выходит за пределы кнопок (нет nowrap/овер-контроля у чипов)
    (CSS, b(".fm-set-mini-a{display:inline-flex;align-items:center;gap:5px;flex:0 0 auto;"),
     b(".fm-set-mini-a{display:inline-flex;align-items:center;gap:5px;flex:0 0 auto;width:12px;overflow:hidden;"),
     GATE, False, "текст выходит за пределы чипов навигации"),
    # 13. RU-подпись удалена
    (IDX, b("{{ lang==='ru'?'Чтение файлов с принтеров':'Read files from printers' }}"),
     b("{{ 'Read files from printers' }}"),
     GATE, True, "RU-подпись удалена"),
    # 14. EN-подпись удалена
    (IDX, b("{{ lang==='ru'?'Разрешить удаление файлов':'Allow deleting files' }}"),
     b("{{ lang==='ru'?'Разрешить удаление файлов':'' }}"),
     GATE, True, "EN-подпись удалена"),
    # 15. действие «Диагностика» ломается
    (IDX, b('@click="closeSettings(); openDiagnostics()"'),
     b('@click="closeSettings()"'),
     GATE, True, "переход в Диагностику сломан"),
    # 16. действие резервного копирования ломается
    (IDX, b('@click="cbExport()"'), b('@click="void 0"'),
     GATE, True, "создание резервной копии сломано"),
    # 17. действие модулей ломается
    (IDX, b('pickModuleZip()'), b('void 0'),
     GATE, True, "установка модуля сломана", True),
    # 18. route guard ослаблен
    (REGP, b("('POST', '/api/printer-files/settings', 'pf_settings_set', 'printers', 'browser', 'SENSITIVE', ('DATABASE', 'AUDIT'), 'SYSTEM_ADMIN', 'project')"),
     b("('POST', '/api/printer-files/settings', 'pf_settings_set', 'printers', 'browser', 'SENSITIVE', ('DATABASE', 'AUDIT'), 'NONE', 'project')"),
     GATE, True, "route guard printer-files/settings ослаблен"),
    # 19. DISPATCH включён
    (ORCH, b("\nDISPATCH_ENABLED = False"), b("\nDISPATCH_ENABLED = True"),
     GATE, True, "DISPATCH включён"),
    # 20. TRANSPORT включён
    (ORCH, b("\nTRANSPORT_ENABLED = False"), b("\nTRANSPORT_ENABLED = True"),
     GATE, True, "TRANSPORT включён"),
]

_n = {"caught": 0, "miss": 0, "not_applied": 0}


def run(test, static_only):
    env = dict(ENV)
    if static_only:
        env["FM_SETPRO_NO_BROWSER"] = "1"
    return subprocess.run([sys.executable, os.path.join(ROOT, "tools", test + ".py")],
                          env=env, capture_output=True, timeout=1800).returncode


def main():
    for test, so in sorted({(m[3], m[4]) for m in MUT}):
        if run(test, so) != 0:
            print("BASELINE FAIL: %s (static_only=%s)" % (test, so))
            return 1
    print("baseline: целевые тесты зелёные\n")
    for path, find, repl, test, static_only, label, *rest in MUT:
        all_hits = bool(rest[0]) if rest else False
        orig = open(path, "rb").read()
        sha0 = hashlib.sha256(orig).hexdigest()
        if orig.count(find) < 1:
            print("SETUP FAIL — якорь не найден: [%s]" % label)
            # Alpha 2.841: порча НЕ внесена (устаревший якорь). Считаем ОТДЕЛЬНО:
            # иначе executed == declared тождественно и mutation_not_applied мёртв.
            _n["miss"] += 1; _n["not_applied"] += 1
            continue
        try:
            open(path, "wb").write(orig.replace(find, repl) if all_hits
                                   else orig.replace(find, repl, 1))
            rc = run(test, static_only)
        finally:
            open(path, "wb").write(orig)
        reverted = hashlib.sha256(open(path, "rb").read()).hexdigest() == sha0
        ok = rc != 0 and reverted
        _n["caught" if ok else "miss"] += 1
        print("%s — [%-58s] %-38s rc=%d revert=%s"
              % ("CAUGHT" if ok else "MISS  ", label, test.replace("test_", ""), rc, reverted))
    print("\n" + "=" * 78)
    print("Mutation proof 2.834 (редизайн настроек): CAUGHT=%d MISS=%d (всего %d)"
          % (_n["caught"], _n["miss"], len(MUT)))
    # Alpha 2.841: сверка ЧИСЛА исполненных порч с объявленным. Прежний знаменатель
    # len(MUT) самоссылочен — он равен числу итераций по построению и не мог заметить,
    # что часть порч не исполнилась (например, из-за устаревшего якоря).
    _executed = _n["caught"] + _n["miss"]
    if _executed != len(MUT):
        print("ЧИСЛО ИСПОЛНЕННЫХ ПОРЧ %d != объявленных %d — набор недоказателен."
              % (_executed, len(MUT)))
    # Alpha 2.841: машиночитаемый итог для релизного гейта — печатается ПОСЛЕ
    # человекочитаемой сводки и не заменяет её. Прежнее условие выхода сохранено
    # как _rc_prev; ненулевым итог становится от любого из двух источников.
    _rc_prev = 0 if (not _n["miss"] and _executed == len(MUT)) else 1
    _summary = _mut_build(declared=len(MUT), executed=_executed - _n["not_applied"], caught=_n["caught"],
                          timeouts=0, restore_failures=0, cleanup_failures=0)
    _rc = _mut_emit(_summary)
    return _rc_prev or _rc


if __name__ == "__main__":
    sys.exit(main())
