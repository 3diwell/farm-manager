// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
// ViewModeSwitch — ЕДИНАЯ кнопка вида принтеров. Клик циклически меняет режим (список ↔ сетка,
// при добавлении режимов — по кругу). Показывает иконку ТЕКУЩЕГО режима; tooltip поясняет переключение.
import { useI18n } from '../../composables/useI18n.js'

export default {
  name: 'ViewModeSwitch',
  props: {
    modes: { type: Array, required: true }, // [{ id, title, icon }]
    current: { type: String, default: '' },
    hint: { type: String, default: '' },    // готовый tooltip; пусто = прежний общий текст
  },
  emits: ['select'],
  setup(props, { emit }) {
    const { tr } = useI18n()
    const cycle = () => {
      const ids = props.modes.map(x => x.id)
      if (!ids.length) return
      const i = ids.indexOf(props.current)
      emit('select', ids[(i + 1) % ids.length])
    }
    return { tr, cycle }
  },
  template: `  <button @click="cycle()" :title="hint || tr('List or grid view')" class="w-7 flex items-center justify-center rounded-lg border fm-border bg-black/40 text-gray-400 hover:text-neon transition-colors shrink-0 fm-style-migrated fm-printers-flex-06">
    <svg-icon :name="(modes.find(m => m.id === current) || modes[0] || {}).icon" class="w-3.5 h-3.5"></svg-icon>
  </button>`,
}
