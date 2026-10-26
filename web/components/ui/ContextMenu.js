// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
// ContextMenu — контекстное меню (правый клик). Пункты в menu.items; выбор -> 'run'.
// Видимостью/позицией управляет родитель (v-if + menu.x/menu.y).

export default {
  name: 'ContextMenu',
  props: {
    menu: { type: Object, required: true }, // { x, y, items: [{ icon, label, danger }] }
  },
  emits: ['run'],
  template: `  <div class="ctx-menu" :style="{ left: menu.x + 'px', top: menu.y + 'px' }">
    <button v-for="(it, i) in menu.items" :key="i" class="ctx-item" :class="{ danger: it.danger }" @click="$emit('run', it)">
      <svg-icon :name="it.icon" class="ctx-ico"></svg-icon>
      <span>{{ it.label }}</span>
    </button>
  </div>`,
}
