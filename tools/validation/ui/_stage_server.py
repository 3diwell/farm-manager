# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""Alpha 2.841 / этап 3A — отдельный процесс статического стенда UI.

ЗАЧЕМ ОТДЕЛЬНЫЙ ПРОЦЕСС. Общий стенд `tools/_fm_ui_stage.py` поднимает сервер в потоке того же
процесса, что и тест. Верификатору нужен настоящий PID: без него нельзя ни записать процесс в
манифест, ни завершить именно его, ни доказать, что после уборки не осталось своих процессов.
Поэтому стенд запускается здесь, а сам обработчик берётся у существующей оснастки — вторая
реализация статического сервера проекту не нужна.

ЧЕГО НЕ ДЕЛАЕТ. Не запускает server.py, не открывает БД, не читает DATA_DIR, не ходит в сеть,
не обращается к принтерам. Слушает только 127.0.0.1 на случайном порту.

    python tools/validation/ui/_stage_server.py <файл-для-порта>
"""
import io
import os
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(REPO, "tools"))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def main(argv):
    if len(argv) != 1:
        sys.stderr.write("нужен ровно один аргумент: путь к файлу для записи порта\n")
        return 2
    port_file = argv[0]

    import _fm_ui_stage                                     # существующая общая сцена
    port = _fm_ui_stage.start()                             # ThreadingHTTPServer на 127.0.0.1:0
    io.open(port_file, "w", encoding="utf-8", newline="\n").write(str(port))
    print("STAGE_PORT=%d" % port)
    sys.stdout.flush()

    # Живём, пока верификатор не завершит нас по сохранённому PID.
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        _fm_ui_stage.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
