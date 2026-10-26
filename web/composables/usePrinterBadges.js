// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
// Бейджи модулей на карточках принтеров (например, «катушки со склада» у модуля
// складского учёта). Отдельный блок-файл по правилу модульности проекта: ядро app.js
// лишь подключает его парой строк. Лёгкий опрос /api/printer-badges раз в 8 секунд;
// любые сбои сети тихо игнорируются — бейджи не критичны для работы фермы.
import { ref } from 'vue';

export function usePrinterBadges() {
    const printerBadges = ref({});   // pid -> [ { module_id, icon, text, warn, title } ]
    let timer = null;
    const poll = async () => {
        try {
            const r = await fetch('/api/printer-badges');
            if (r.ok) { const d = await r.json(); printerBadges.value = (d && d.badges) || {}; }
        } catch (e) { /* тихо */ }
    };
    const startPrinterBadges = () => { if (timer) return; poll(); timer = setInterval(poll, 8000); };
    return { printerBadges, startPrinterBadges, refreshPrinterBadges: poll };
}
