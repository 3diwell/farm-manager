// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
// DiagRow — одна строка журнала диагностики (время · уровень · сообщение).

export default {
  name: 'DiagRow',
  props: {
    time: { type: String, default: '' },
    level: { type: String, default: '' },
    levelClass: { type: String, default: '' },
    msg: { type: String, default: '' },
  },
  template: `  <div class="diag-row">
    <span class="diag-ts">{{ time }}</span>
    <span class="diag-lvl" :class="levelClass">{{ level }}</span>
    <span class="diag-msg">{{ msg }}</span>
  </div>`,
}
