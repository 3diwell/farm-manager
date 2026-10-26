// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
// Модуль «Уведомления в мессенджеры» — ЕДИНСТВЕННОЕ лицо модуля: ячейка в «Настройки → Модули».
// Своего окна у модуля нет (в module.json нет entry): настройки — это всё, что он показывает,
// и отдельному всплывающему окну взяться неоткуда.
// Контракт: модуль объявляет этот файл полем settings_entry; ядро грузит его и рисует
// <component :is="…" :lang :access :embedded="true"> внутри вкладки настроек. Права — только
// через props.access.can('admin'), своей таблицы прав у модуля нет.
import { useMessengers, MESSENGERS_BODY, MESSENGERS_PROPS } from './MessengersPanel.js';

export default {
  name: 'MessengersSettings',
  props: Object.assign({ embedded: { type: Boolean, default: true } }, MESSENGERS_PROPS),
  emits: ['close'],
  setup(props) { return useMessengers(props); },
  template: `<div class="msg-body msg-body-embed">${MESSENGERS_BODY}</div>`,
};
