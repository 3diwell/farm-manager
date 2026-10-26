// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
// Привязанный филамент/катушки на карточках принтеров (read-only, из модуля складского
// учёта). Отдельный блок-файл по правилу модульности проекта: ядро app.js лишь подключает
// его парой строк. Лёгкий опрос /api/printer-filament раз в 10 секунд; любые сбои сети или
// отсутствие модуля (404/пусто) тихо игнорируются — блок филамента не критичен для фермы.
import { ref } from 'vue';

export function usePrinterFilament() {
    const printerFilament = ref({});   // pid -> { has_ams, slots: [ { index, unit, tray, external, offline, spool:{...} } ] }
    let timer = null;
    const poll = async () => {
        try {
            const r = await fetch('/api/printer-filament');
            if (r.ok) { const d = await r.json(); printerFilament.value = (d && d.printers) || {}; }
        } catch (e) { /* тихо: модуль склада может быть не установлен */ }
    };
    // Generic-сигнал обновления: ЛЮБОЙ модуль, изменивший привязку филамента, шлёт нейтральное событие окна
    // 'fm:printer-filament-changed', и ядро просто ПЕРЕСПРАШИВАЕТ свой же /api/printer-filament (тот же poll,
    // никакого нового канала данных и никакой связи ядро->склад). Модуль не установлен — событие никто не шлёт,
    // работает штатный 10-секундный опрос. Так значок появляется/гаснет сразу после bind/unbind, без перезагрузки.
    const startPrinterFilament = () => {
        if (timer) return;
        poll();
        timer = setInterval(poll, 10000);
        try { window.addEventListener('fm:printer-filament-changed', poll); } catch (e) { /* нет window — не критично */ }
    };
    return { printerFilament, startPrinterFilament, refreshPrinterFilament: poll };
}
