// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
// StatusBadge — бейдж статуса (цветная плашка). Цвет и подпись приходят пропсами;
// по клику испускает 'click' — что делать, решает родитель. Стили из .status-badge в app.css.

export default {
  name: 'StatusBadge',
  props: {
    styleClass: { type: String, default: '' }, // классы цвета (результат getStatusStyles())
    label: { type: String, default: '' },       // готовая подпись статуса
    clickable: { type: Boolean, default: false },// кликабелен ли бейдж
    title: { type: String, default: '' },        // подсказка
    count: { type: Number, default: 0 },         // 2.951: число печатающихся внутри бейджа (0 — не показывать)
  },
  emits: ['click'],
  template: `  <span
    class="status-badge"
    :class="[styleClass, clickable ? 'cursor-pointer' : '']"
    :title="title"
    @click.stop="clickable ? $emit('click') : null"
  >{{ label }}<i v-if="count > 0" class="sb-n">{{ count }}</i></span>`,
}
