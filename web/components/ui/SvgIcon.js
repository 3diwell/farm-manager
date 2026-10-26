// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
// ============================================================================
// SvgIcon — универсальная иконка интерфейса.
// Рисунок берётся из каталога web/design/icons.js по имени:
//   <svg-icon name="add"></svg-icon>
// Размер и цвет задаются классом снаружи (иконка наследует currentColor).
// Толщину линии можно задать через :sw (по умолчанию 2).
// ============================================================================
import { inject, computed } from 'vue';

export default {
  name: 'SvgIcon',
  props: {
    name: { type: String, required: true },        // имя иконки из каталога
    sw: { type: [Number, String], default: 2 },    // толщина линии (stroke-width)
  },
  setup(props) {
    const icons = inject('icons', {});
    const inner = computed(() => icons[props.name] || '');
    return { inner };
  },
  template: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" :stroke-width="sw" stroke-linecap="round" stroke-linejoin="round" v-html="inner"></svg>`,
};
