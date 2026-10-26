# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""3DIWELL Farm Manager — запуск СОБСТВЕННОГО ОКНА (local desktop mode, Alpha 2.805).

Тонкая точка входа: вся логика — в app/desktop_shell.py. Backend НЕ импортируется;
он переиспользуется, если уже работает, либо запускается отдельным процессом.
Закрытие окна backend не останавливает (полное завершение — «Выход» в трее).

Аргументы: --local | --client | --server-url <origin> | --port N | --debug-shell |
           --open-browser | --reset-window-state
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.desktop_shell import main

if __name__ == "__main__":
    sys.exit(main(default_mode="local"))
