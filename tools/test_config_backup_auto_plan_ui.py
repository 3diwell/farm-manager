# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.829 — авто-план UI: выбор файла сам ведёт к плану; пароль только когда нужен;
stale-план не применяется; старой кнопки нет; scope-описание модулей; RU/EN."""
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

_n = {"pass": 0, "fail": 0}


def check(label, cond):
    ok = bool(cond)
    print(("PASS" if ok else "FAIL") + " — " + label)
    _n["pass" if ok else "fail"] += 1
    return ok


JS = open(os.path.join(ROOT, "web", "app.js"), encoding="utf-8").read()
IDX = open(os.path.join(ROOT, "web", "index.html"), encoding="utf-8").read()

print("--- авто-план ---")
pick = JS[JS.find("const cbPickImport"):JS.find("const cbApply")]
check("56. passwordless: выбор файла АВТОМАТИЧЕСКИ строит план (await cbInspect в cbPickImport)",
      "await cbInspect(token)" in pick)
check("57. protected: показывается пароль (phase='password'), план не строится без него",
      "cbPhase.value = 'password'" in pick and "cbImportRequiresPw.value = !!j.info.requires_password" in pick)
check("58. после ввода пароля план строится Enter-ом/Продолжить (без отдельной кнопки плана)",
      '@keydown.enter.prevent="cbInspect()"' in IDX and "Продолжить" in IDX)
check("59. старой кнопки «Показать план восстановления» нет в normal flow",
      "Показать план восстановления" not in IDX and "Show restore plan" not in IDX)
check("60. выбор нового файла очищает старый план/пароль",
      "cbPlan.value = null" in pick and "cbImportPw.value = ''" in pick)
check("61. stale-план нельзя применить (file token guard в pick и inspect)",
      "_cbFileToken" in pick and "token !== _cbFileToken" in pick
      and "tok !== _cbFileToken" in JS)
check("62. при ошибке есть «Повторить проверку»", "Повторить проверку" in IDX
      and "cbPhase==='error'" in IDX)
check("состояния: Проверка/Требуется пароль/Подготовка плана",
      "Проверка резервной копии" in IDX and "Требуется пароль" in IDX
      and "Подготовка плана" in IDX)

print("--- scope UI (модули) ---")
check("91. описание scope упоминает модули и честно называет, что в копию не входит (16.10.2026, аудит data-safety-17)",
      "данные модулей из списка ниже" in IDX and "хранятся в браузере — в копию они не входят" in IDX)
check("92. описание говорит, что проекты/задачи не входят и не изменяются",
      "Проекты и задачи в копию не входят и при восстановлении не изменяются" in IDX)
check("93. секции экспорта показаны (настройки/принтеры/склад/расчёт заказа/качество/видеостена); "
      "R-125: заказы в копии, а файлы моделей к ним — нет, и это сказано прямо",
      "Настройки Farm Manager" in IDX and "Принтеры и данные подключения" in IDX
      and "Складской учёт" in IDX
      and "Расчёт заказа — заказы, ставки и настройки; файлы моделей к заказам в копию не входят" in IDX
      and "Расчёт заказа — сохранённые заказы в копию пока не входят" not in IDX
      and "Видеостена — камеры хранятся в браузере этого компьютера и в копию не входят" in IDX
      and "Аналитика качества" in IDX)
check("no-data модуль показан честно («нет пользовательских данных»)",
      "нет пользовательских данных для сохранения" in IDX)
check("94. план показывает счётчики модулей (add/update/current-only)",
      "cbPlan.module_data" in IDX and "cbModLabel(m.module_id)" in IDX
      and "останется своих" in IDX)
check("95. absent-текст для старых копий в плане",
      "Данные модулей отсутствуют в этой версии резервной копии и не будут изменены" in IDX)
check("96-97. RU и EN присутствуют в новых текстах",
      "Module data is absent in this backup version" in IDX and "Checking the backup" in IDX)

print("\n" + "=" * 60)
print("Итого: PASS=%d FAIL=%d" % (_n["pass"], _n["fail"]))
sys.exit(1 if _n["fail"] else 0)
