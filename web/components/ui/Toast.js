// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
// Toast — всплывающее уведомление: progress (полоса) / info (спиннер) / success (галочка) /
// warn и error (знак «внимание»). 17.10.2026: предупреждение на телефоне выглядело как обычное
// сообщение — без знака и без жёлтой рамки; теперь как в панели «Подсказки» на компьютере.

export default {
  name: 'Toast',
  props: {
    toast: { type: Object, required: true }, // { type, msg, pct }
  },
  template: `  <div class="fm-toast" :class="'fm-toast--' + toast.type">
    <div v-if="toast.type === 'progress'" class="fm-toast-prog">
      <div class="fm-toast-prog-top"><span class="fm-toast-msg">{{ toast.msg }}</span><span class="fm-toast-pct">{{ toast.pct || 0 }}%</span></div>
      <div class="fm-toast-track"><div class="fm-toast-bar" :style="'width:' + (toast.pct || 0) + '%'"></div></div>
    </div>
    <template v-else>
      <span v-if="toast.type === 'info'" class="fm-toast-spin" aria-hidden="true"></span>
      <svg-icon v-else-if="toast.type === 'success'" name="check" sw="2.5" class="w-4 h-4 shrink-0"></svg-icon>
      <svg-icon v-else-if="toast.type === 'warn' || toast.type === 'error'" name="alert" sw="2.4" class="fm-toast-ic w-4 h-4 shrink-0"></svg-icon>
      <span class="fm-toast-msg">{{ toast.msg }}</span>
    </template>
  </div>`,
}
