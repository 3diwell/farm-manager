// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
// useI18n — доступ к переводам в компонентах. tr/lang приходят из app.js через provide().
//   import { useI18n } from '../../composables/useI18n.js'
//   const { tr } = useI18n()  // в шаблоне: {{ tr('Some key') }}
import { inject } from 'vue'

export function useI18n() {
  return {
    tr: inject('tr'),
    lang: inject('lang'),
  }
}
