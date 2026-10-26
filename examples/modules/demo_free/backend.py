# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MPL-2.0
# SPDX-FileCopyrightText: 2025-2026 3DiWell Team
# This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
# If a copy of the MPL was not distributed with this file, You can obtain one at
# https://mozilla.org/MPL/2.0/.
"""ДЕМОНСТРАЦИОННЫЙ бесплатный модуль FM (26.09.2026). На рабочую ферму не ставится.

Показывает, что бесплатному модулю лицензия не нужна вовсе: он работает одинаково без подписи
(как любой старый или сторонний модуль) и в подписанном пакете с licensing.model = "free".
Ничего не пишет, в сеть не ходит, принтерам ничего не отправляет.

    GET /api/mod/demo_free/hello  ->  {"module": "demo_free", "ok": true, "package": "..."}
"""

core = None


def api_demo_free_hello():
    st = core.license_status() if hasattr(core, "license_status") else {}
    return {"module": "demo_free", "ok": True, "package": st.get("state", "unsigned"),
            "license": st.get("license", "")}


def register(_core):
    global core
    core = _core
    core.add_route("hello", api_demo_free_hello, ["GET"], policy_id="demo_free.hello")
