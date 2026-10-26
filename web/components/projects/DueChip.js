// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
// ============================================================================
// DueChip — компактный чип «срок сдачи» + дата создания + цвет приоритета.
//   • Дата создания (created_at) показывается относительно: «создан 3 дня назад».
//   • Срок сдачи задаётся пресетами (+3 дня / +1 нед / +2 нед) или нативным
//     календарём <input type="date"> (локализуется браузером, без библиотек).
//   • Приоритет считается из срока и красит чип: 🔴 просрочено/сегодня-завтра,
//     🟡 до срока ≤ yellowDays, иначе нейтрально.
//   Компонент презентационный: наружу эмитит 'set' (YYYY-MM-DD) и 'clear';
//   сам ничего не сохраняет — запись делает родитель через свой API.
// ============================================================================
import { ref, computed } from 'vue';

// --- утилиты дат (экспортируются, чтобы родитель мог считать приоритет так же) ---
const _parseDue = (s) => {
  if (!s) return null;
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(s).trim());
  if (!m) return null;
  return new Date(+m[1], +m[2] - 1, +m[3]);   // локальная полночь
};
const _todayMidnight = () => { const t = new Date(); return new Date(t.getFullYear(), t.getMonth(), t.getDate()); };
const _addDaysISO = (n) => {
  const d = new Date(); d.setDate(d.getDate() + n);
  const p = (x) => String(x).padStart(2, '0');
  return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate());
};

// 'red' | 'yellow' | 'none' — единый источник истины для приоритета по сроку
export const duePriority = (due, yellowDays) => {
  const d = _parseDue(due);
  if (!d) return 'none';
  const days = Math.round((d - _todayMidnight()) / 86400000);
  if (days <= 1) return 'red';                 // просрочено, сегодня или завтра
  if (days <= (Number(yellowDays) || 3)) return 'yellow';
  return 'none';
};

// «30 июня» / «June 30» — локализация через Intl, без своих таблиц месяцев
export const formatDue = (due, lang) => {
  const d = _parseDue(due);
  if (!d) return '';
  try { return new Intl.DateTimeFormat(lang === 'ru' ? 'ru-RU' : 'en-US', { day: 'numeric', month: 'long' }).format(d); }
  catch (e) { return String(due); }
};

// «сегодня» / «вчера» / «3 дня назад» — Intl.RelativeTimeFormat сам склоняет и для ru, и для en
export const relativeCreated = (iso, lang) => {
  if (!iso) return '';
  let s = String(iso).trim().replace(' ', 'T');
  if (!/[zZ]|[+-]\d\d:?\d\d$/.test(s)) s += 'Z';     // CURRENT_TIMESTAMP в SQLite — это UTC
  const dt = new Date(s);
  if (isNaN(dt.getTime())) return '';
  const created = new Date(dt.getFullYear(), dt.getMonth(), dt.getDate());
  const days = Math.round((_todayMidnight() - created) / 86400000);
  const word = lang === 'ru' ? 'создан ' : 'created ';
  if (days > 60) {                                   // очень старое — показываем дату
    try { return word + new Intl.DateTimeFormat(lang === 'ru' ? 'ru-RU' : 'en-US', { day: '2-digit', month: '2-digit', year: 'numeric' }).format(created); }
    catch (e) { return ''; }
  }
  try { return word + new Intl.RelativeTimeFormat(lang === 'ru' ? 'ru' : 'en', { numeric: 'auto' }).format(-Math.max(0, days), 'day'); }
  catch (e) { return ''; }
};

export default {
  name: 'DueChip',
  props: {
    dueDate: { type: String, default: '' },        // 'YYYY-MM-DD' или ''
    createdAt: { type: String, default: '' },      // ISO/CURRENT_TIMESTAMP
    showCreated: { type: Boolean, default: true },
    yellowDays: { type: [Number, String], default: 3 },
    lang: { type: String, default: 'ru' },
    canEdit: { type: Boolean, default: true },     // без права — чип только показывает срок, без поповера
  },
  emits: ['set', 'clear'],
  setup(props, { emit }) {
    const open = ref(false);
    const pos = ref({ top: 0, left: 0 });
    const prio = computed(() => duePriority(props.dueDate, props.yellowDays));
    const dueLabel = computed(() => formatDue(props.dueDate, props.lang));
    const createdLabel = computed(() => relativeCreated(props.createdAt, props.lang));
    const chipText = computed(() => {
      if (props.dueDate) return (props.lang === 'ru' ? 'до ' : '') + dueLabel.value;
      return props.lang === 'ru' ? '+ срок' : '+ due';
    });
    const openPop = (ev) => {
      if (!props.canEdit) return;             // нет права правки — поповер не открываем
      try {
        const r = ev.currentTarget.getBoundingClientRect();
        // .dc-pop — position:fixed под html{zoom}: getBoundingClientRect/innerWidth дают ВИЗУАЛЬНЫЕ px,
        // а инлайновые top/left ещё раз домножаются на zoom. Переводим в логические координаты (делим на zoom) —
        // как ядро в openContextMenu. Плюс flip вверх, если снизу не хватает места, и clamp в вьюпорт с отступом 8px.
        const z = parseFloat(getComputedStyle(document.documentElement).zoom) || 1;
        const vw = window.innerWidth / z, vh = window.innerHeight / z;
        const rl = r.left / z, rt = r.top / z, rb = r.bottom / z;
        const popW = 184, popH = 160, pad = 8;   // 184 = ширина .dc-pop; popH — оценка высоты поповера
        let left = Math.max(pad, Math.min(rl, vw - popW - pad));                 // не вылезать за правый/левый край
        let top = (rb + popH > vh - pad) ? (rt - popH - 6) : (rb + 6);           // снизу не влезает → открыть сверху
        top = Math.max(pad, Math.min(top, vh - popH - pad));                     // финальный clamp по вертикали
        pos.value = { top: Math.round(top), left: Math.round(left) };
      } catch (e) { pos.value = { top: 120, left: 120 }; }
      open.value = true;
    };
    const closePop = () => { open.value = false; };
    const applyPreset = (n) => { emit('set', _addDaysISO(n)); open.value = false; };
    const applyPick = (ev) => { const v = ev && ev.target ? ev.target.value : ''; if (v) emit('set', v); open.value = false; };
    const clearDue = () => { emit('clear'); open.value = false; };
    return { open, pos, prio, dueLabel, createdLabel, chipText, openPop, closePop, applyPreset, applyPick, clearDue };
  },
  template: `<div class="due-chip-wrap">
  <div v-if="showCreated && createdLabel" class="dc-created">{{ createdLabel }}</div>
  <button data-help="due-chip" v-if="canEdit || dueDate" class="dc-chip" :class="'dc-'+prio" :style="canEdit ? '' : 'cursor:default'" @click.stop="openPop($event)" :title="dueDate ? (lang==='ru'?'Срок сдачи клиенту':'Due date') : (lang==='ru'?'Задать срок сдачи':'Set due date')">
    <span v-if="dueDate" class="dc-dot" :class="'dot-'+prio"></span>
    <span class="dc-txt">{{ chipText }}</span>
  </button>
  <teleport to="body">
    <transition name="fade">
      <div v-if="open">
        <div class="dc-backdrop" @click.stop="closePop"></div>
        <div class="dc-pop" :style="{top: pos.top+'px', left: pos.left+'px'}" @click.stop>
          <div class="dc-pop-label">{{ lang==='ru'?'Срок сдачи':'Due date' }}</div>
          <div class="dc-presets">
            <button class="dc-preset" @click.stop="applyPreset(3)">+3 {{ lang==='ru'?'дня':'d' }}</button>
            <button class="dc-preset" @click.stop="applyPreset(7)">+1 {{ lang==='ru'?'нед':'wk' }}</button>
            <button class="dc-preset" @click.stop="applyPreset(14)">+2 {{ lang==='ru'?'нед':'wk' }}</button>
          </div>
          <input type="date" class="dc-date" :value="dueDate" @change="applyPick($event)" @click.stop>
          <button v-if="dueDate" class="dc-clear" @click.stop="clearDue">{{ lang==='ru'?'Убрать срок':'Clear due date' }}</button>
        </div>
      </div>
    </transition>
  </teleport>
</div>`,
};
