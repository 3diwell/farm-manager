// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
// ProjectCell — плитка проекта (иконка, имя, счётчик, %). Клик -> 'toggle'.
// • Размеры контента — в фиксированных px (как у карточек принтера): масштабируются зумом
//   интерфейса одинаково со всем остальным. cqw НЕ используем намеренно: его видимый размер
//   не зависит от зума (зум в формуле «%×ширина» сокращается), из-за чего текст ячейки проекта
//   переставал масштабироваться при браузерном/CSS-зуме. При правке размеров — только px/rem.
// • Контент прижат к ВЕРХНЕМУ контуру; внизу — ряд превью деталей (partThumbs).
// • Прогресс — линией ПО КОНТУРУ карточки (как у принтеров grid), без полосы внутри.
// • Имя — в одну строку с обрезкой; полное имя — в тултипе (:title).
// pcsLabel ('шт') приходит готовой строкой.

export default {
  name: 'ProjectCell',
  props: {
    project: { type: Object, required: true },   // { id, name, done_count, parts_count }
    expanded: { type: Boolean, default: false },
    pcsLabel: { type: String, default: '' },
    partThumbs: { type: Array, default: () => [] },
    dueDate: { type: String, default: '' },
    createdAt: { type: String, default: '' },
    showCreated: { type: Boolean, default: true },
    yellowDays: { type: [Number, String], default: 3 },
    lang: { type: String, default: 'ru' },
    needsRework: { type: Boolean, default: false },
    reworkPending: { type: [Number, String], default: 0 },
    tint: { type: String, default: '' },
    selectMode: { type: Boolean, default: false },
    selected: { type: Boolean, default: false },
    canEdit: { type: Boolean, default: true },
  },
  emits: ['toggle', 'due-set', 'due-clear', 'menu'],
  computed: {
    pct() { return this.project.parts_count ? Math.round(this.project.done_count / this.project.parts_count * 100) : 0; },
    hasThumbs() { return Array.isArray(this.partThumbs) && this.partThumbs.length > 0; },
  },
  template: `  <div
    @click="$emit('toggle', $event)"
    @contextmenu.prevent="$emit('menu', $event)"
    class="plan-cell relative fm-bg-raised rounded-xl border p-2 cursor-pointer shadow-md text-center transition-colors overflow-hidden flex flex-col items-center justify-between"
    :class="[expanded ? 'border-neon' : 'fm-border hover:border-gray-400', (selectMode && selected) ? 'pc-sel-on' : '']"
    :style="tint"
  >
    <span v-if="selectMode" class="pc-check" :class="{ 'pc-check-on': selected }">{{ selected ? '✓' : '' }}</span>
    <svg v-if="project.parts_count > 0" class="plan-ring text-neon"><rect pathLength="100" :style="{ strokeDasharray: pct + ' 100' }"></rect></svg>
    <div class="pc-body flex flex-col items-center w-full">
      <span class="pc-name font-bold text-gray-200 w-full px-1" :title="project.name">{{ project.name }}</span>
      <span class="pc-metarow"><span class="pc-meta text-gray-500 font-mono">{{ project.done_count }}/{{ project.parts_count }} {{ pcsLabel }}</span><span class="pc-meta text-neon font-mono">{{ pct }}%</span><span v-if="needsRework" class="pc-rework" :title="lang==='ru'?'Нужна перепечатка':'Needs rework'">⟳{{ reworkPending }}</span></span>
      <due-chip :due-date="dueDate" :created-at="createdAt" :show-created="showCreated" :yellow-days="yellowDays" :lang="lang" :can-edit="canEdit" @set="$emit('due-set', $event)" @clear="$emit('due-clear')"></due-chip>
    </div>
    <div v-if="hasThumbs" class="pc-thumbs">
      <img v-for="(u,i) in partThumbs" :key="i" :src="u" @error="$event.target.style.display='none'" class="pvprev-img" loading="lazy" alt="">
    </div>
  </div>`,
}
