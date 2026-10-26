// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
// Модуль «Аналитика качества» v0.2.1 — минимальное окно (Фаза 1: сбор истории + материалы).
// Контракт окна модуля: default-export компонент, props { open, lang }, событие 'close';
// стили инлайном на CSS-переменных темы; иконки — глобальный <svg-icon>.
// v0.2.1 — только UI-компоновка: компактная шапка (иконка в фикс-боксе, не раздувается),
// flex-геометрия с единственной прокруткой content. Логика/сбор истории/материалы НЕ менялись.
import { ref, watch } from 'vue';

const OUT_RU = { running: 'печатается', finished: 'завершена', failed: 'сбой', cancelled: 'отменена', interrupted: 'прервана', unknown: 'не определён' };
const OUT_COLOR = { finished: 'var(--fm-success)', failed: 'var(--fm-danger)', cancelled: '#f5a524', running: 'var(--fm-accent)' };

// Стиль модуля — один раз в <head>, СТРОГО через класс .quality-* (никаких глобальных селекторов,
// не влияет на другие модули). Ограничивает внутренний SVG иконки шапки, чтобы он не растягивался.
const STYLE_ID = 'quality-panel-styles';
const QUALITY_CSS = '.quality-ico svg{width:24px;height:24px;display:block}';
function ensureStyles() {
  try {
    if (typeof document === 'undefined' || document.getElementById(STYLE_ID)) return;
    const s = document.createElement('style');
    s.id = STYLE_ID;
    s.textContent = QUALITY_CSS;
    document.head.appendChild(s);
  } catch (e) { /* стиль не критичен для работы окна */ }
}

export default {
  name: 'QualityPanel',
  props: {
    open: { type: Boolean, default: false },
    lang: { type: String, default: 'ru' },
  },
  emits: ['close'],
  setup(props) {
    const L = (ru, en) => (props.lang === 'ru' ? ru : en);
    const loading = ref(false);
    const sum = ref({ active: false, total: 0, by_outcome: {}, recent: [] });
    const load = async () => {
      loading.value = true;
      try {
        const r = await fetch('/api/mod/quality/summary', { cache: 'no-store' });
        if (r.ok) sum.value = await r.json();
      } catch (e) { /* окно просто покажет нули */ }
      loading.value = false;
    };
    watch(() => props.open, (v) => { if (v) { ensureStyles(); load(); } }, { immediate: true });
    const outLabel = (o) => (props.lang === 'ru' ? (OUT_RU[o] || o || '—') : (o || '—'));
    const outColor = (o) => OUT_COLOR[o] || 'var(--fm-text-subtle)';
    const fmtTs = (s) => String(s || '').slice(0, 16);
    // Компактная подпись материалов запуска: «PLA, PETG +1 · Bambu · партия A12» или «Материал не определён».
    const matLabel = (r) => {
      const m = (r && r.materials) || [];
      if (!m.length) return L('Материал не определён', 'Material n/a');
      const names = [];
      for (const x of m) { const t = String((x && x.material) || '').trim() || '—'; if (!names.includes(t)) names.push(t); }
      let s = names.slice(0, 2).join(', ');
      if (names.length > 2) s += ' +' + (names.length - 2);
      const v = String((m[0].vendor_name) || '').trim();
      if (v) s += ' · ' + v;
      const lot = String((m[0].lot) || '').trim();
      if (lot) s += ' · ' + L('партия ', 'lot ') + lot;
      return s;
    };
    const matDot = (r) => {
      const m = (r && r.materials) || [];
      const c = m.length ? String(m[0].color_hex || '').trim() : '';
      return /^#?[0-9a-fA-F]{6}$/.test(c) ? (c[0] === '#' ? c : '#' + c) : '';
    };
    return { L, loading, sum, outLabel, outColor, fmtTs, matLabel, matDot };
  },
  template: `<teleport to="body"><transition name="fade"><div v-if="open" style="position:fixed;inset:0;z-index:100040;display:flex;align-items:center;justify-content:center;padding:20px">
    <div style="position:absolute;inset:0;background:rgba(0,0,0,0.55)" @click="$emit('close')"></div>
    <div style="position:relative;width:min(720px,calc(100vw - 40px));max-height:min(760px,calc(100vh - 40px));display:flex;flex-direction:column;background:var(--fm-surface-raised);border:1px solid var(--fm-border-strong);border-radius:16px;box-shadow:0 24px 60px rgba(var(--fm-black-rgb),0.5);overflow:hidden">

      <!-- ШАПКА (фиксирована) -->
      <div style="flex:0 0 auto;display:flex;align-items:center;gap:13px;padding:14px 20px;border-bottom:1px solid var(--fm-border-soft)">
        <span class="quality-ico" style="flex:0 0 auto;width:44px;height:44px;display:inline-flex;align-items:center;justify-content:center;border-radius:12px;background:rgba(var(--fm-accent-rgb),.12);color:var(--fm-accent)"><svg-icon name="activity" style="width:24px;height:24px;display:block"></svg-icon></span>
        <div style="display:flex;flex-direction:column;min-width:0;gap:1px">
          <span style="font-size:16px;font-weight:800;color:var(--fm-text-primary);line-height:1.2">{{ L('Аналитика качества','Quality analytics') }}</span>
          <span style="font-size:12px;color:var(--fm-text-subtle);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{ L('История печатей, материалов и результатов','Print, material and outcome history') }}</span>
        </div>
        <button style="flex:0 0 auto;margin-left:auto;border:1px solid var(--fm-border);background:transparent;color:var(--fm-text-secondary);border-radius:9px;padding:7px 15px;font-size:13px;font-weight:700;cursor:pointer" @click="$emit('close')">{{ L('Закрыть','Close') }}</button>
      </div>

      <!-- КОНТЕНТ (единственная прокручиваемая область) -->
      <div style="flex:1 1 auto;min-height:0;overflow-y:auto;overflow-x:hidden;padding:16px 20px">
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:12px">
          <span style="flex:0 0 auto;width:9px;height:9px;border-radius:50%;background:var(--fm-success);box-shadow:0 0 6px var(--fm-success)"></span>
          <span style="font-size:13.5px;font-weight:700;color:var(--fm-text-primary)">{{ L('Сбор истории активен','History collection is active') }}</span>
          <span style="font-size:13px;color:var(--fm-text-subtle)">· {{ sum.total }} {{ L('запусков сохранено','runs recorded') }}</span>
        </div>
        <template v-if="sum.recent && sum.recent.length">
          <div style="font-size:11px;font-weight:800;letter-spacing:.07em;text-transform:uppercase;color:var(--fm-text-subtle);margin:0 0 6px">{{ L('Последние запуски','Recent runs') }}</div>
          <div v-for="r in sum.recent" :key="r.run_id" style="display:flex;flex-direction:column;gap:2px;padding:6px 8px;border-radius:8px">
            <div style="display:flex;align-items:center;gap:10px;font-size:12.5px;color:var(--fm-text-secondary)">
              <span style="flex:0 0 auto;font-weight:700;color:var(--fm-text-primary);max-width:170px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{ r.printer_name || r.printer_id }}</span>
              <span style="flex:1 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{ r.filename || '—' }}</span>
              <span :style="{flex:'0 0 auto',fontWeight:'800',color:outColor(r.outcome_raw)}">{{ outLabel(r.outcome_raw) }}</span>
              <span style="flex:0 0 auto;font-size:11.5px;color:var(--fm-text-subtle);font-variant-numeric:tabular-nums">{{ fmtTs(r.started_at) }}</span>
            </div>
            <div style="display:flex;align-items:center;gap:6px;padding-left:1px;font-size:11.5px;color:var(--fm-text-subtle);min-width:0">
              <span v-if="matDot(r)" :style="{flex:'0 0 auto',width:'8px',height:'8px',borderRadius:'50%',border:'1px solid var(--fm-border)',background:matDot(r)}"></span>
              <span style="flex:1 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">{{ matLabel(r) }}</span>
            </div>
          </div>
        </template>
        <div v-else-if="!loading" style="padding:14px 8px;font-size:13px;color:var(--fm-text-subtle);font-style:italic">{{ L('Пока нет ни одного запуска — записи появятся после первой печати.','No runs yet — records will appear after the first print.') }}</div>
        <div style="margin-top:14px;padding:10px 12px;border:1px solid var(--fm-border-soft);border-radius:10px;background:rgba(var(--fm-accent-rgb),.05);font-size:12.5px;line-height:1.45;color:var(--fm-text-secondary)">
          {{ L('Модуль собирает историю всех запусков печати (принтер, файл, источник, профиль, исход) и снимок использованных материалов/катушек в собственную базу farm_quality.db. Снимок материала неизменяем: он не меняется, даже если позже катушку переименовать, переместить или удалить. Расширенная статистика — надёжность материалов и принтеров, причины брака, рекомендации — будет добавлена в следующих версиях.','The module records every print attempt (printer, file, source, profile, outcome) and a snapshot of the materials/spools used into its own farm_quality.db. The material snapshot is immutable — it stays unchanged even if the spool is later renamed, moved or deleted. Advanced statistics — material/printer reliability, failure causes, recommendations — will arrive in future versions.') }}
        </div>
      </div>
    </div>
  </div></transition></teleport>`,
}
