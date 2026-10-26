# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""3DIWELL Farm Manager Client — окно подключения к ферме на ДРУГОМ компьютере (Alpha 2.805).

Клиент содержит ТОЛЬКО оболочку: ни backend, ни рабочей БД, ни DATA_DIR, ни связи с
принтерами здесь нет и не появляется. Авторизацию выполняет сервер; пароль клиент не
сохраняет; cookies живут только в отдельном WebView2-профиле клиента.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.desktop_shell import main

if __name__ == "__main__":
    sys.exit(main(default_mode="client"))
