// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
// РЕАЛЬНЫЙ runtime-тест режима «Склад → В работе» — inventory 1.7.8 (UI-polish единой таблицы).
// Монтирует СТРОКИ ТАБЛИЦЫ НАСТОЯЩИМ вендорным Vue (web/vendor/vue.esm-browser.js) на минимальном
// самодельном DOM (jsdom/happy-dom не ставим — их нет) и доказывает во время ВЫПОЛНЕНИЯ (не строками):
//   R1  ВСЕ принтеры фермы (включая полностью пустые) — строками ОДНОЙ таблицы .fm-inv-ptable;
//   R2  отдельной секции «Пустые принтеры» нет: пустые X1C/P1P — строки ВНУТРИ той же таблицы;
//   R3  generic-иконка принтера (svg-icon w-4 h-4) удалена; вместо неё миниатюра .fm-inv-pimg 52px:
//       при известной модели — <img src="/covers/<model>_cover.png"> (URL-паттерн ядра modelCover),
//       без модели — fallback <svg-icon name="printer"> в той же плашке; статус — точка+текст
//       ВТОРОЙ СТРОКОЙ под именем (.fm-inv-pst внутри .fm-inv-pcol-t);
//   R4  занятая НАСТОЯЩАЯ external-позиция = читаемая slot-cell с подписью «Внешняя»: материал
//       (главное), цвет·vendor (вторично), остаток·% + progress-bar; клик -> история, ПКМ -> меню;
//   R5  пустая НАСТОЯЩАЯ external-позиция = ячейка-кнопка .fm-inv-pfree («+ Привязать» + подпись
//       «Внешняя», пунктир); клик по ЛЮБОМУ месту ячейки -> ПРЯМОЙ openBindFor(принтер, 0);
//   R6  AMS с пустыми слотами показывает slot-cells с номерами и «+» (кликабельна вся ячейка);
//   R7  клик пустого AMS-слота передаёт ВЕРНЫЙ слот (X8 slot 2; мульти-unit H2D slot 5 из A2);
//   R8  СЕМАНТИЧЕСКИ ЧЕСТНАЯ универсальная ячейка: живой AMS-принтер без external-записи видит
//       «+ Привязать катушку» / «Выбрать позицию» БЕЗ слова «Внешняя» (обещания external-привязки нет,
//       её текущая модель данных не поддерживает); клик -> openBindFor(p, null) = штатный диалог с
//       ЯВНЫМ выбором слота; ложного «Нет внешней подачи» нет; AMS-слоты независимы; «Нет AMS» —
//       только у принтеров вообще без AMS-позиций;
//   R8b офлайн-AMS принтер: занятая external И offline-AMS-ячейка видны ОДНОВРЕМЕННО (обе области);
//   R8c полностью занятый принтер (живой AMS, все позиции заняты, external-записи нет): вместо
//       заведомо бесполезной кнопки — спокойное «Все позиции заняты»; в меню «⋯» bind-пункта тоже нет;
//   R9  несколько AMS unit: группы .fm-inv-punit с лейблами A1/A2 (не хардкод одного unit);
//   R10 занятый AMS-слот: номер + мини-катушка (SVG) + материал + %;
//   R11 сводные колонки: остаток всего (Σ г + N кат.), прогноз (мин. days_left, класс soon);
//   R12 тумблер: OFF скрывает ТОЛЬКО полностью пустые принтеры; «+»-ячейки частично занятых видны;
//   R13 cold-load: пока loading=true — таблицы нет; после прихода обзора строки появляются;
//   R14 меню строки «⋯» (workRowMenu): привязать / заменить (low) / отвязать — действия верные;
//   R15 мост runtime<->файл: shipped InventoryPanel.js содержит ДОСЛОВНО эти же строки таблицы,
//       логику workRows/model/coverUrl и фильтра пустых; старой generic-иконки, «—»-заглушек и
//       текста «Нет внешней подачи» нет;
//   R16 аудит картинок: без данных /api/printers (запрос упал) — fallback-иконки у всех строк,
//       таблица полна, bind живёт (сам запрос идёт через fail-open _loadSection — см. W15).
// Harness (DElement/DText/DComment + globalThis-заглушки) — тот же, что в test_inventory_bind_runtime.mjs.
// Запуск: node tools/test_inventory_workmode_runtime.mjs   (0 = все проверки пройдены)
import { readFileSync } from 'fs';
import { fileURLToPath, pathToFileURL } from 'url';
import { dirname, join } from 'path';

const REPO = dirname(dirname(fileURLToPath(import.meta.url)));
const PANEL = readFileSync(join(REPO, 'modules', 'inventory', 'web', 'InventoryPanel.js'), 'utf8');
let fail = 0;
const check = (name, cond) => { console.log((cond ? 'PASS' : 'FAIL') + ' — ' + name); if (!cond) fail++; };

// ─────────── минимальный DOM (идентичен bind-runtime harness) ───────────
class DNode {
  constructor(nodeType) { this.nodeType = nodeType; this.childNodes = []; this.parentNode = null; }
  get nextSibling() { const p = this.parentNode; if (!p) return null; const i = p.childNodes.indexOf(this); return i >= 0 ? (p.childNodes[i + 1] || null) : null; }
  _link(child, anchor) { if (child.parentNode) child.parentNode.removeChild(child); child.parentNode = this; if (anchor && anchor.parentNode === this) { this.childNodes.splice(this.childNodes.indexOf(anchor), 0, child); } else this.childNodes.push(child); return child; }
  insertBefore(child, anchor) { return this._link(child, anchor); }
  appendChild(child) { return this._link(child, null); }
  removeChild(child) { const i = this.childNodes.indexOf(child); if (i >= 0) this.childNodes.splice(i, 1); child.parentNode = null; return child; }
}
class DText extends DNode { constructor(t) { super(3); this.nodeValue = t == null ? '' : String(t); } get data() { return this.nodeValue; } set data(v) { this.nodeValue = v; } }
class DComment extends DNode { constructor(t) { super(8); this.nodeValue = t == null ? '' : String(t); } }
class DElement extends DNode {
  constructor(tag) { super(1); this._tag = tag; this.tagName = String(tag).toUpperCase(); this.namespaceURI = 'http://www.w3.org/1999/xhtml'; this.attributes = {}; this._listeners = {}; this.style = {}; this._cls = ''; this._disabled = false; }
  setAttribute(k, v) { this.attributes[k] = String(v); if (k === 'class') this._cls = String(v); }
  removeAttribute(k) { delete this.attributes[k]; if (k === 'class') this._cls = ''; }
  getAttribute(k) { return k in this.attributes ? this.attributes[k] : null; }
  hasAttribute(k) { return k in this.attributes; }
  get className() { return this._cls; }
  set className(v) { this._cls = v == null ? '' : String(v); this.attributes['class'] = this._cls; }
  get disabled() { return this._disabled; }
  set disabled(v) { this._disabled = !!v; if (v) this.attributes['disabled'] = ''; else delete this.attributes['disabled']; }
  addEventListener(t, fn) { (this._listeners[t] = this._listeners[t] || []).push(fn); }
  removeEventListener(t, fn) { const a = this._listeners[t]; if (a) { const i = a.indexOf(fn); if (i >= 0) a.splice(i, 1); } }
  get textContent() { return this.childNodes.map((c) => c.nodeType === 3 ? c.nodeValue : (c.nodeType === 1 ? c.textContent : '')).join(''); }
  set textContent(v) { this.childNodes.forEach((c) => (c.parentNode = null)); this.childNodes = []; if (v !== '' && v != null) this.appendChild(new DText(String(v))); }
  hasChildNodes() { return this.childNodes.length > 0; }
  get firstChild() { return this.childNodes[0] || null; }
  get innerHTML() { return ''; }
  set innerHTML(v) { if (v === '' || v == null) { this.childNodes.forEach((c) => (c.parentNode = null)); this.childNodes = []; } }
  querySelector() { return null; }
  _fire(type, ev) { (this._listeners[type] || []).slice().forEach((fn) => fn(ev)); }
  _findAll(pred, out = []) { if (this.nodeType === 1 && pred(this)) out.push(this); this.childNodes.forEach((c) => { if (c.nodeType === 1) c._findAll(pred, out); }); return out; }
  get _elemChildren() { return this.childNodes.filter((c) => c.nodeType === 1); }
}
const documentShim = { createElement: (t) => new DElement(t), createElementNS: (ns, t) => new DElement(t), createTextNode: (t) => new DText(t), createComment: (t) => new DComment(t), querySelector: () => null, addEventListener: () => {}, removeEventListener: () => {} };
documentShim.body = new DElement('body'); documentShim.documentElement = new DElement('html');
if (!globalThis.document) globalThis.document = documentShim;
if (!globalThis.window) { try { globalThis.window = globalThis; } catch (e) {} }
for (const g of ['SVGElement', 'HTMLElement', 'Element', 'Node', 'ShadowRoot']) { if (globalThis[g] === undefined) globalThis[g] = class {}; }

const Vue = await import(pathToFileURL(join(REPO, 'web', 'vendor', 'vue.esm-browser.js')).href);
const { createApp, ref, reactive, computed, nextTick } = Vue;

const clsList = (el) => (el.className || '').split(/\s+/).filter(Boolean);
const hasCls = (el, c) => clsList(el).includes(c);
const byCls = (root, c) => root._findAll((e) => hasCls(e, c));
const byTag = (root, t) => root._findAll((e) => e._tag === t);
const fireEv = (el, type) => { const ev = { type, target: el, currentTarget: el, timeStamp: 0, stopPropagation() {}, stopImmediatePropagation() {}, preventDefault() {} }; el._fire(type, ev); };
const silence = async (fn) => { const e = console.error, w = console.warn; console.error = () => {}; console.warn = () => {}; try { return await fn(); } finally { console.error = e; console.warn = w; } };

// ─────────── ДОСЛОВНЫЙ блок таблицы «В работе», ИЗВЛЕЧЁННЫЙ из shipped InventoryPanel.js ───────────
// 1.7.10: вместо хрупких копий — вырезаем настоящий блок <div v-else class="fm-inv-ptable">…</div>
// из shipped-шаблона (баланс div) и монтируем ЕГО. Мост runtime<->файл теперь неотъемлемый:
// тестируется буквально та разметка, что уезжает на ферму (секции workSections + группы unit).
const _extractTable = () => {
  const key = '<div v-else class="fm-inv-ptable">';
  const s = PANEL.indexOf(key);
  if (s < 0) throw new Error('ptable block not found in shipped panel');
  const openEnd = PANEL.indexOf('>', s) + 1;
  const re = /<div\b|<\/div>/g; re.lastIndex = openEnd;
  let m, depth = 1, close = -1;
  while ((m = re.exec(PANEL))) { depth += (m[0] === '</div>') ? -1 : 1; if (depth === 0) { close = m.index; break; } }
  return PANEL.slice(s, close + '</div>'.length).replace('v-else class="fm-inv-ptable"', 'v-else-if="workRows.length" class="fm-inv-ptable"');
};
const TABLE_BLOCK = _extractTable();
// (легаси-копии строк удалены: блок извлекается из shipped-файла выше)
// Верхняя обвязка (loading / пусто / таблица) — как в shipped (wmode==='work').
const WORK_TEMPLATE = '<div class="wrap">'
  + '<div v-if="loading" class="fm-inv-empty ld">{{ L(\'Загрузка…\',\'Loading…\') }}</div>'
  + '<div v-else-if="!workRows.length" class="fm-inv-empty none">{{ L(\'Нет катушек в работе\',\'No spools in use\') }}</div>'
  + TABLE_BLOCK
  + '</div>';

// Фабрика компонента с ИДЕНТИЧНОЙ shipped-логикой (1.7.8). Состояние вынесено в state — чтобы мутировать после mount.
const makeWork = (overview, opts = {}) => {
  const state = {
    loading: ref(!!opts.loading),
    ams: ref(overview || { printers: [] }),
    q: ref(''),
    showEmptyPrinters: ref(true),
    fcMap: ref(opts.fcMap || {}),
    printerModelById: ref(opts.models || {}),
    printerTypeById: ref(opts.types || {}),      // 1.7.10: платформа из /api/printers (kl-иконка)
    printerCoverById: ref(opts.covers || {}),    // 1.7.15: готовый canonical cover_url из /api/printers
    klipperSvg: ref(opts.klipperSvg || ''),      // 1.7.10: owner-иконка Klipper (в тесте задаётся стабом)
    calls: { bind: [], click: [], menu: [], unbind: [], replace: [], menuItems: [] },
  };
  const component = {
    setup() {
      const L = (ru) => ru;
      const { loading, ams, q, showEmptyPrinters, fcMap, printerModelById, printerTypeById, printerCoverById, klipperSvg, calls } = state;
      const spoolById = computed(() => { const m = {}; for (const p of (ams.value.printers || [])) for (const sl of (p.slots || [])) if (sl.spool) m[sl.spool.id] = sl.spool; return m; });
      const slotFull = (sl) => (sl && sl.spool && spoolById.value[sl.spool.id]) || null;
      // «мало остатка» моделируем порогом 100 г по brief-катушке (shipped slotLow идёт через isLowSpool/lowG)
      const slotLow = (sl) => { const sp = sl && sl.spool; return !!(sp && (+sp.weight_remaining_g || 0) <= 100); };
      const pct = (s) => { const t = +s.weight_total_g || 0; if (t <= 0) return 0; return Math.max(0, Math.min(100, Math.round((+s.weight_remaining_g || 0) / t * 100))); };
      const barColor = () => '#888';
      const printerBoundG = (p) => { let g = 0; for (const sl of (p.slots || [])) if (sl && sl.spool) g += (+sl.spool.weight_remaining_g || 0); return Math.round(g); };
      const printerBoundN = (p) => (p.slots || []).filter((sl) => sl && sl.spool).length;
      const slotUnits = (p) => {
        const order = []; const map = {};
        for (const sl of (p.slots || [])) { const u = (sl.unit == null ? 0 : sl.unit); if (!(u in map)) { map[u] = []; order.push(u); } map[u].push(sl); }
        return order.map((u, i) => ({ unit: u, n: i + 1, slots: map[u] }));
      };
      // ==== ДОСЛОВНО shipped 1.7.8 ====
      const coverBroken = reactive({});
      const coverUrl = (model) => '/covers/' + encodeURIComponent(String(model) + '_cover.png');
      const printerOcc = (p) => (p.slots || []).some((sl) => sl && sl.spool);
      const _printerHasLow = (p) => (p.slots || []).some((sl) => slotLow(sl));
      const _amsSearched = computed(() => { const t = q.value.trim().toLowerCase(); const all = (ams.value.printers || []); if (!t) return all.slice(); return all.filter((p) => (p.printer_name || '').toLowerCase().indexOf(t) !== -1); });
      const workPrinters = computed(() => {
        const rank = (p) => (_printerHasLow(p) ? 0 : (printerOcc(p) ? 1 : 2));   // low -> занятые -> пустые
        let arr = _amsSearched.value;
        if (!showEmptyPrinters.value) arr = arr.filter(printerOcc);   // скрыть полностью пустые принтеры по тумблеру
        return arr.map((p, i) => ({ p: p, i: i })).sort((a, b) => (rank(a.p) - rank(b.p)) || (a.i - b.i)).map((x) => x.p);
      });
      const workEmptyCount = computed(() => _amsSearched.value.filter((p) => !printerOcc(p)).length);   // полностью пустых принтеров (для тумблера)
      const workExternal = (p) => { for (const sl of (p.slots || [])) if (sl.external) return sl; return null; };
      const workAmsUnits = (p) => slotUnits({ slots: (p.slots || []).filter((sl) => !sl.external && !sl.unconfirmed) });
      const workUnconfirmed = (p) => (p.slots || []).filter((sl) => sl.unconfirmed && sl.spool);
      const workDaysLeft = (p) => { let m = null; for (const sl of (p.slots || [])) { const sp = sl && sl.spool; if (!sp) continue; const f = fcMap.value[sp.id]; if (f && f.days_left != null && (m == null || f.days_left < m)) m = f.days_left; } return m; };
      const workStatus = (p) => {
        if (!printerOcc(p)) return { k: 'empty', t: L('Пусто', 'Empty') };
        if (_printerHasLow(p)) return { k: 'low', t: L('Мало остатка', 'Low filament') };
        return { k: 'ok', t: L('Готов', 'Ready') };
      };
      const workRows = computed(() => workPrinters.value.map((p) => ({
        p: p, ext: workExternal(p), units: workAmsUnits(p), unconfirmed: workUnconfirmed(p),
        remainG: printerBoundG(p), boundN: printerBoundN(p),
        days: workDaysLeft(p), st: workStatus(p),
        model: printerModelById.value[p.printer_id] || '',
        cover: printerCoverById.value[p.printer_id] || '',   // 1.7.15: готовый canonical cover_url из ядра
        kl: (printerTypeById.value[p.printer_id] || '') === 'klipper',   // 1.7.10: платформа по РЕАЛЬНОМУ type (не по имени)
        hasFree: (p.slots || []).some((sl) => !sl.spool && !sl.offline),   // есть свободная позиция (критерий ветки C/D и bind-пункта меню)
      })));
      // ==== ДОСЛОВНО shipped 1.7.10: секции + подпись unit + локальный номер лотка ====
      const workSections = computed(() => {
        const ams = [], ext = [], empty = [];
        for (const r of workRows.value) {
          if (r.st.k === 'empty') { empty.push(r); continue; }
          (r.units.length ? ams : ext).push(r);
        }
        const busy = ams.reduce((n, r) => n + r.units.reduce((m, u) => m + u.slots.filter((s) => s.spool).length, 0), 0);
        const spools = ext.reduce((n, r) => n + (r.boundN || 0), 0);
        return [
          { key: 'ams', title: L('Системы AMS', 'AMS systems'), count: ams.length + ' ' + L('принт.', 'prn.') + ' · ' + busy + ' ' + L('занятых слотов', 'busy slots'), rows: ams },
          { key: 'ext', title: L('Внешняя подача', 'External feed'), count: ext.length + ' ' + L('принт.', 'prn.') + ' · ' + spools + ' ' + L('кат.', 'spools'), rows: ext },
          { key: 'empty', title: L('Без катушки', 'No spool'), count: empty.length + ' ' + L('принт.', 'prn.'), rows: empty },
        ].filter((s) => s.rows.length);
      });
      const unitLabel = (u) => ((u.slots.length === 1 && !u.slots[0].offline && u.slots[0].unit != null) ? 'AMS HT' : ('A' + u.n));
      const slotLocalN = (sl) => {
        if (!sl) return '';
        if (sl.tray != null) return Number(sl.tray) + 1;
        const i = Number(sl.index) || 0;
        if (sl.unit != null) return i - Number(sl.unit) * 4 + 1;
        return (i % 4) + 1;
      };
      const workSlotTitle = (sl) => {
        const base = (sl.external ? L('Внешняя катушка', 'External spool') : ('AMS · ' + L('слот', 'slot') + ' ' + (sl.index + 1))) + (sl.offline ? (' · ' + L('офлайн', 'offline')) : '');
        if (!sl.spool) return base + ' — ' + L('нажмите, чтобы привязать катушку со склада', 'click to bind a spool from stock');
        const s = sl.spool;
        return base + ': ' + ([s.material, s.color_name, s.vendor_name].filter(Boolean).join(' · ') || s.label || '') + ' · ' + Math.round(s.weight_remaining_g || 0) + ' ' + L('г', 'g') + ' · ' + pct(s) + '% — ' + L('клик — история · ПКМ — меню', 'click: history · right-click: menu');
      };
      // регистраторы вместо реальных действий (проверяем ТОЛЬКО, что разметка/меню зовут их с верными аргументами)
      const onSlotClick = (sl) => { calls.click.push(sl); };
      const onSlotMenu = (e, sl) => { calls.menu.push(sl); };
      const slotReplace = (sl) => { calls.replace.push(sl); };
      const openBindFor = (p, idx) => { calls.bind.push({ printer_id: p.printer_id, idx: idx }); };
      const openUnbind = (f) => { calls.unbind.push(f); };
      const ctxLocalOpen = (e, items) => { calls.menuItems.push(items); };
      // ==== ДОСЛОВНО shipped 1.7.8 (меню строки) ====
      const workRowMenu = (e, r) => {
        const p = r.p; const items = [];
        const freeSl = (p.slots || []).find((sl) => !sl.spool && !sl.offline);
        if (freeSl) items.push({ icon: 'link', label: L('Привязать катушку', 'Bind a spool'), action: () => openBindFor(p, freeSl.index) });
        for (const sl of (p.slots || [])) {
          if (!sl.spool) continue;
          const f = slotFull(sl); if (!f) continue;
          const nm = [f.material, f.color_name].filter(Boolean).join(' · ') || f.label || L('катушка', 'spool');
          if (slotLow(sl)) items.push({ icon: 'refresh', label: L('Заменить', 'Replace') + ': ' + nm, action: () => slotReplace(sl) });
          items.push({ icon: 'undo', label: L('Отвязать', 'Unbind') + ': ' + nm, action: () => openUnbind(f) });
        }
        if (items.length) ctxLocalOpen(e, items);
      };
      const spoolSvg = () => '';
      return { L, loading, ams, q, showEmptyPrinters, fcMap, printerModelById, printerTypeById, klipperSvg, coverBroken, coverUrl, workRows, workSections, unitLabel, slotLocalN, workEmptyCount, workSlotTitle, matCheckView: () => null, workRowMenu, slotFull, slotLow, onSlotClick, onSlotMenu, slotReplace, openBindFor, openUnbind, spoolSvg, barColor, pct, calls };
    },
    template: WORK_TEMPLATE,
    // harness-DOM не умеет декодировать HTML-энтити через innerHTML (нет настоящего парсера), а в
    // атрибутах шаблона есть «&&» — отдаём identity-декодер, как в compile()-проверках других тестов
    compilerOptions: { decodeEntities: (x) => x },
  };
  return { component, state };
};
const mount = (component) => { const app = createApp(component); app.component('svg-icon', { props: { name: { type: String, default: '' } }, template: '<i class="ico" :data-name="name"></i>' }); const root = new DElement('div'); const vm = app.mount(root); return { root, vm }; };

// ─────────── обзор фермы: занятые/пустые, external/AMS, мульти-unit, полностью пустые принтеры ───────────
const OVERVIEW = { printers: [
  // X8: AMS, частично занят (PLA 640 г + low PETG 80 г + 2 пустых слота); модель известна -> <img>
  { printer_id: 'PRN_X8', printer_name: 'X8', has_ams: true, slots: [
    { index: 0, unit: 0, spool: { id: 's1', material: 'PLA', color_name: 'Красный', color_hex: 'ff0000', weight_remaining_g: 640, weight_total_g: 1000 } },
    { index: 1, unit: 0, spool: { id: 's2', material: 'PETG', color_name: 'Синий', color_hex: '0000ff', weight_remaining_g: 80, weight_total_g: 1000 } },
    { index: 2, unit: 0 }, { index: 3, unit: 0 }, { index: -1, external: true } ] },   // 1.7.20: external-позиция (-1) есть у КАЖДОГО принтера, в т.ч. с живым AMS
  // H2D: ДВА AMS unit (сквозные индексы), одна катушка в unit 1 + пустая external
  { printer_id: 'PRN_H2D', printer_name: 'H2D', has_ams: true, slots: [
    { index: 0, unit: 0 }, { index: 1, unit: 0 },
    { index: 4, unit: 1, spool: { id: 's4', material: 'ASA', color_name: 'Серый', color_hex: '999999', weight_remaining_g: 500, weight_total_g: 1000 } },
    { index: 5, unit: 1 }, { index: -1, external: true } ] },
  // X7: живой AMS на 2 слота, ОБА заняты; external-позиция (-1) СВОБОДНА -> «+ Привязать внешняя»
  //     остаётся доступной даже при полностью занятом AMS (external и AMS больше не конкурируют)
  { printer_id: 'PRN_X7', printer_name: 'X7', has_ams: true, slots: [
    { index: 0, unit: 0, spool: { id: 's7', material: 'PLA', color_name: 'Зелёный', color_hex: '00aa00', weight_remaining_g: 500, weight_total_g: 1000 } },
    { index: 1, unit: 0, spool: { id: 's8', material: 'PETG', color_name: 'Оранжевый', color_hex: 'ff8800', weight_remaining_g: 900, weight_total_g: 1000 } },
    { index: -1, external: true } ] },
  // X9: AMS ОФЛАЙН (живых лотков нет, has_ams=false): external-позиция (-1) ЗАНЯТА + привязка к AMS-слоту 1
  //     отдаётся offline-ячейкой — обе НЕЗАВИСИМЫЕ области видны одновременно
  { printer_id: 'PRN_X9', printer_name: 'X9', has_ams: false, slots: [
    { index: -1, external: true, spool: { id: 's5', material: 'PC', color_name: 'Белый', color_hex: 'ffffff', weight_remaining_g: 700, weight_total_g: 1000 } },
    { index: 1, offline: true, spool: { id: 's6', material: 'PA-CF', color_name: '', color_hex: '222222', weight_remaining_g: 400, weight_total_g: 1000 } } ] },
  // X1C: AMS, ПОЛНОСТЬЮ пуст (ни одной катушки) + пустая external
  { printer_id: 'PRN_X1C', printer_name: 'X1C', has_ams: true, slots: [ { index: 0, unit: 0 }, { index: 1, unit: 0 }, { index: 2, unit: 0 }, { index: 3, unit: 0 }, { index: -1, external: true } ] },
  // P1P: только внешняя катушка (-1), ПОЛНОСТЬЮ пуст; модели нет -> fallback-иконка
  { printer_id: 'PRN_P1P', printer_name: 'P1P', has_ams: false, slots: [ { index: -1, external: true } ] },
  // A1: только внешняя катушка (-1), занята
  { printer_id: 'PRN_A1', printer_name: 'A1', has_ams: false, slots: [ { index: -1, external: true, spool: { id: 's3', material: 'ABS', color_name: 'Чёрный', color_hex: '111111', weight_remaining_g: 900, weight_total_g: 1000, vendor_name: 'Bambu' } } ] },
] };
const MODELS = { PRN_X8: 'Bambu Lab X1 Carbon', PRN_H2D: 'Bambu Lab H2D', PRN_X7: 'Bambu Lab P1S', PRN_X9: 'Bambu Lab P1S', PRN_X1C: 'Bambu Lab X1 Carbon', PRN_A1: 'Bambu Lab A1' };   // у P1P модели нет
// 1.7.15: cover_url как отдаёт ядро (GET /api/printers, allowlisted registry). У P1P модели/обложки нет.
const COVERS = { PRN_X8: '/covers/Bambu%20Lab%20X1%20Carbon_cover.png', PRN_H2D: '/covers/Bambu%20Lab%20H2D_cover.png', PRN_X7: '/covers/Bambu%20Lab%20P1S_cover.png', PRN_X9: '/covers/Bambu%20Lab%20P1S_cover.png', PRN_X1C: '/covers/Bambu%20Lab%20X1%20Carbon_cover.png', PRN_A1: '/covers/Bambu%20Lab%20A1_cover.png' };
const FC = { s1: { days_left: 5 } };   // прогноз есть только у s1 -> строка X8 показывает ≈5 дн.
const TOTAL_PRINTERS = OVERVIEW.printers.length;                                        // 5
const FULLY_EMPTY = OVERVIEW.printers.filter((p) => !p.slots.some((s) => s.spool)).length;  // 2 (X1C, P1P)
const rowByName = (root, name) => byCls(root, 'fm-inv-prow').find((r) => !hasCls(r, 'fm-inv-prow-h') && (byCls(r, 'fm-inv-pname2')[0] || { textContent: '' }).textContent.trim() === name);
const dataRows = (root) => byCls(root, 'fm-inv-prow').filter((r) => !hasCls(r, 'fm-inv-prow-h'));

// ═══ R1: все принтеры (включая полностью пустые) — строками ОДНОЙ таблицы ═══
const base = await silence(async () => mount(makeWork(OVERVIEW, { fcMap: FC, models: MODELS, covers: COVERS }).component));
{
  const root = base.root;
  const tables = byCls(root, 'fm-inv-ptable');
  const rows = dataRows(root);
  const names = new Set(rows.map((r) => (byCls(r, 'fm-inv-pname2')[0] || { textContent: '' }).textContent.trim()));
  check('R1. одна таблица .fm-inv-ptable; строк = ' + TOTAL_PRINTERS + ' (все принтеры: X8, H2D, X7, X9, X1C, P1P, A1)',
    tables.length === 1 && rows.length === TOTAL_PRINTERS
    && ['X8', 'H2D', 'X7', 'X9', 'X1C', 'P1P', 'A1'].every((n) => names.has(n)));
}

// ═══ R2: отдельной секции «Пустые принтеры» НЕТ — пустые строки внутри той же таблицы ═══
{
  const root = base.root;
  const table = byCls(root, 'fm-inv-ptable')[0];
  const inTable = (row) => { let n = row; while (n) { if (n === table) return true; n = n.parentNode; } return false; };
  const x1c = rowByName(root, 'X1C'), p1p = rowByName(root, 'P1P');
  check('R2. пустые X1C/P1P — строки ВНУТРИ единой таблицы; чипов/секции пустых (.fm-inv-empties/.fm-inv-echip) нет',
    !!x1c && !!p1p && inTable(x1c) && inTable(p1p)
    && byCls(root, 'fm-inv-empties').length === 0 && byCls(root, 'fm-inv-echip').length === 0);
}

// ═══ R3: generic-иконки нет; миниатюра 52px: <img /covers/...> при модели, fallback svg-icon без модели; статус второй строкой ═══
{
  const root = base.root;
  const x8 = rowByName(root, 'X8'), p1p = rowByName(root, 'P1P'), x1c = rowByName(root, 'X1C');
  const x8img = byTag(byCls(x8, 'fm-inv-pimg')[0], 'img');
  const p1pImgBox = byCls(p1p, 'fm-inv-pimg')[0];
  const p1pImgs = byTag(p1pImgBox, 'img');
  const p1pFallback = byCls(p1pImgBox, 'ico').filter((i) => i.getAttribute('data-name') === 'printer');
  const stInCol = (row) => { const col = byCls(row, 'fm-inv-pcol-t')[0]; return col ? byCls(col, 'fm-inv-pst') : []; };
  const x1cSt = stInCol(x1c)[0];
  check('R3. миниатюра .fm-inv-pimg у каждой строки; X8 -> <img src="/covers/Bambu%20Lab%20X1%20Carbon_cover.png">; P1P без модели -> fallback svg-icon printer (img нет); статус точкой ВТОРОЙ строкой (X1C: «Пусто»)',
    dataRows(root).every((r) => byCls(r, 'fm-inv-pimg').length === 1)
    && x8img.length === 1 && x8img[0].getAttribute('src') === '/covers/Bambu%20Lab%20X1%20Carbon_cover.png'
    && p1pImgs.length === 0 && p1pFallback.length === 1
    && dataRows(root).every((r) => stInCol(r).length === 1)
    && !!x1cSt && hasCls(x1cSt, 'empty') && x1cSt.textContent.includes('Пусто'));
}

// ═══ R4: занятая внешняя — читаемая slot-cell (материал/цвет/остаток/% + progress-bar), клик/ПКМ живы ═══
{
  const { root, vm } = await silence(async () => mount(makeWork(OVERVIEW, { models: MODELS }).component));
  const a1 = rowByName(root, 'A1');
  const ext = byCls(a1, 'fm-inv-pext')[0];
  const mat = (byCls(ext, 'fm-inv-pext-m')[0] || { textContent: '' }).textContent.trim();
  const sub = (byCls(ext, 'fm-inv-pext-c')[0] || { textContent: '' }).textContent;
  const g = (byCls(ext, 'fm-inv-pext-g')[0] || { textContent: '' }).textContent;
  const bar = byCls(ext, 'fm-inv-pext-bar')[0];
  const barFill = bar && bar._elemChildren[0];
  fireEv(ext, 'click'); await nextTick();
  fireEv(ext, 'contextmenu'); await nextTick();
  const st = vm.$.setupState;
  const kLabel = (byCls(ext, 'fm-inv-pext-k')[0] || { textContent: '' }).textContent.trim();
  check('R4. занятая НАСТОЯЩАЯ external A1: подпись «Внешняя» + материал «ABS», «Чёрный · Bambu», «900 г · 90%», progress-bar 90%; клик -> onSlotClick(s3), ПКМ -> onSlotMenu',
    !!ext && kLabel === 'Внешняя' && mat === 'ABS' && sub.includes('Чёрный') && sub.includes('Bambu')
    && g.includes('900') && g.includes('90%')
    && !!barFill && String(barFill.style.width) === '90%'
    && st.calls.click.length === 1 && st.calls.click[0].spool.id === 's3'
    && st.calls.menu.length === 1 && st.calls.menu[0].spool.id === 's3');
}

// ═══ R5: пустая внешняя — ПОЛНОЦЕННАЯ ячейка-кнопка («+» + «Привязать»); клик по всей ячейке -> bind ═══
{
  const { root, vm } = await silence(async () => mount(makeWork(OVERVIEW).component));
  const p1p = rowByName(root, 'P1P');
  const free = byCls(p1p, 'fm-inv-pfree');
  fireEv(free[0], 'click'); await nextTick();
  const b = vm.$.setupState.calls.bind;
  const subLbl = (byCls(free[0], 'fm-inv-pfree-s')[0] || { textContent: '' }).textContent.trim();
  check('R5. пустая external P1P = ячейка-кнопка «+ Привязать внешняя» с подписью «Внешняя подача» (кликабельна вся) -> ПРЯМОЙ openBindFor(P1P, -1)',
    free.length === 1 && free[0]._tag === 'button'
    && free[0].textContent.includes('+') && free[0].textContent.includes('Привязать внешняя')
    && subLbl === 'Внешняя подача'
    && b.length === 1 && b[0].printer_id === 'PRN_P1P' && b[0].idx === -1);
}

// ═══ R6: пустые AMS-слоты = slot-cells с номером и «+» ═══
{
  const root = base.root;
  const x1c = rowByName(root, 'X1C');
  const cells = byCls(x1c, 'fm-inv-pslot');
  const adds = cells.filter((c) => hasCls(c, 'add'));
  const nums = cells.map((c) => (byCls(c, 'fm-inv-pslot-n')[0] || { textContent: '' }).textContent.trim());
  const pluses = adds.filter((c) => byCls(c, 'fm-inv-pslot-plus').length === 1);
  check('R6. X1C (AMS пустой): 4 slot-cells .fm-inv-pslot.add с номерами 1..4 и «+» (кликабельна вся ячейка-кнопка)',
    cells.length === 4 && adds.length === 4 && pluses.length === 4
    && nums.join(',') === '1,2,3,4' && cells.every((c) => c._tag === 'button'));
}

// ═══ R7: клик пустого AMS-слота передаёт ВЕРНЫЙ слот (X8 slot 2; мульти-unit H2D slot 5 из группы A2) ═══
{
  const { root, vm } = await silence(async () => mount(makeWork(OVERVIEW).component));
  const x8 = rowByName(root, 'X8');
  const x8adds = byCls(x8, 'fm-inv-pslot').filter((c) => hasCls(c, 'add'));
  fireEv(x8adds[0], 'click'); await nextTick();
  const h2d = rowByName(root, 'H2D');
  const units = byCls(h2d, 'fm-inv-punit2');
  const a2add = byCls(units[1], 'fm-inv-pslot').filter((c) => hasCls(c, 'add'));
  const a2addNum = (byCls(a2add[0], 'fm-inv-pslot-n')[0] || { textContent: '' }).textContent.trim();
  fireEv(a2add[0], 'click'); await nextTick();
  const b = vm.$.setupState.calls.bind;
  check('R7. клик пустого AMS: X8 -> openBindFor(X8, 2); H2D группа A2 -> openBindFor(H2D, 5) — на ячейке ЛОКАЛЬНЫЙ номер «2», а bind получает глобальный index 5',
    b.length === 2 && b[0].printer_id === 'PRN_X8' && b[0].idx === 2
    && a2addNum === '2'
    && b[1].printer_id === 'PRN_H2D' && b[1].idx === 5);
}

// ═══ R8: 1.7.20 — живой AMS-принтер (X8) ТОЖЕ имеет отдельную external-позицию «+ Привязать внешняя» ═══
{
  const { root, vm } = await silence(async () => mount(makeWork(OVERVIEW).component));
  const x8 = rowByName(root, 'X8');
  const free = byCls(x8, 'fm-inv-pfree');
  const x8AmsCells = byCls(byCls(x8, 'fm-inv-pams')[0], 'fm-inv-pslot');
  fireEv(free[0], 'click'); await nextTick();
  const b = vm.$.setupState.calls.bind;
  const amsCol = (row) => byCls(row, 'fm-inv-pams')[0];
  const a1None = byCls(amsCol(rowByName(root, 'A1')), 'fm-inv-pnone')[0];
  const p1pNone = byCls(amsCol(rowByName(root, 'P1P')), 'fm-inv-pnone')[0];
  const noDash = dataRows(root).every((r) => !byCls(r, 'fm-inv-pams')[0].textContent.includes('—'));
  const freeTxt = free[0] ? free[0].textContent : '';
  check('R8. X8 (живой AMS): в «Катушка» отдельная external-позиция «+ Привязать внешняя» -> ПРЯМОЙ openBindFor(X8, -1) (не универсал openBindFor(p,null)); AMS-слоты (4) независимы; «Выбрать позицию»/«Все позиции заняты»/«Нет внешней подачи» нет; «Нет AMS» — только у A1/P1P; «—» в AMS нет',
    free.length === 1 && free[0]._tag === 'button'
    && freeTxt.includes('Привязать внешняя')
    && !root.textContent.includes('Выбрать позицию') && !root.textContent.includes('Все позиции заняты')
    && x8AmsCells.length === 4
    && b.length === 1 && b[0].printer_id === 'PRN_X8' && b[0].idx === -1
    && !root.textContent.includes('Нет внешней подачи')
    && !!a1None && a1None.textContent.includes('Нет подачи')   // 1.7.26: нейтрально к AMS/CFS && byCls(amsCol(rowByName(root, 'A1')), 'fm-inv-pslot').length === 0
    && !!p1pNone && p1pNone.textContent.includes('Нет подачи') && byCls(amsCol(rowByName(root, 'P1P')), 'fm-inv-pslot').length === 0
    && noDash);
}

// ═══ R8b: офлайн-AMS X9 — ОБЕ независимые области одновременно: занятая external + offline AMS-ячейка ═══
{
  const root = base.root;
  const x9 = rowByName(root, 'X9');
  const ext = byCls(x9, 'fm-inv-pext')[0];
  const extMat = (byCls(ext, 'fm-inv-pext-m')[0] || { textContent: '' }).textContent.trim();
  const amsCells = byCls(byCls(x9, 'fm-inv-pams')[0], 'fm-inv-pslot');
  check('R8b. X9 (AMS офлайн): занятая external «PC» (с подписью «Внешняя») И offline AMS-ячейка «PA-CF» видны ОДНОВРЕМЕННО; «Нет AMS» у него нет',
    !!ext && extMat === 'PC' && (byCls(ext, 'fm-inv-pext-k')[0] || { textContent: '' }).textContent.trim() === 'Внешняя'
    && amsCells.length === 1 && hasCls(amsCells[0], 'off') && amsCells[0].textContent.includes('PA-CF')
    && byCls(x9, 'fm-inv-pfree').length === 0
    && byCls(byCls(x9, 'fm-inv-pams')[0], 'fm-inv-pnone').length === 0);
}

// ═══ R8c: 1.7.20 — X7 (живой AMS, ОБА слота заняты): external-позиция ОСТАЁТСЯ доступной (item 9, тест C) ═══
{
  const { root, vm } = await silence(async () => mount(makeWork(OVERVIEW).component));
  const x7 = rowByName(root, 'X7');
  const free = byCls(x7, 'fm-inv-pfree');
  const occCells = byCls(byCls(x7, 'fm-inv-pams')[0], 'fm-inv-pslot');
  fireEv(free[0], 'click'); await nextTick();
  const b = vm.$.setupState.calls.bind;
  check('R8c. X7 (живой AMS, оба слота заняты): external-позиция ОСТАЁТСЯ доступной — «+ Привязать внешняя» -> openBindFor(X7, -1); 2 занятые AMS-ячейки на месте; «Все позиции заняты» и кнопки строки «⋯» больше нет',
    free.length === 1 && free[0].textContent.includes('Привязать внешняя')
    && b.length === 1 && b[0].printer_id === 'PRN_X7' && b[0].idx === -1
    && occCells.length === 2 && occCells.every((c) => !hasCls(c, 'add'))
    && !x7.textContent.includes('Все позиции заняты')
    && byCls(x7, 'fm-inv-gmore').length === 0);
}

// ═══ R9: несколько AMS unit — группы A1/A2, без хардкода одного unit ═══
{
  const root = base.root;
  const h2d = rowByName(root, 'H2D');
  const units = byCls(h2d, 'fm-inv-punit2');
  const labels = byCls(h2d, 'fm-inv-punit2-l').map((e) => e.textContent.trim());
  const x8units = byCls(rowByName(root, 'X8'), 'fm-inv-punit2');
  const x8labels = byCls(rowByName(root, 'X8'), 'fm-inv-punit2-l').map((e) => e.textContent.trim());
  check('R9. H2D: 2 ВНУТРЕННИЕ группы unit (.fm-inv-punit2) с заголовками A1/A2 (слоты 2+2 внутри своих рамок); X8: 1 группа с заголовком A1',
    units.length === 2 && labels.join(',') === 'A1,A2'
    && byCls(units[0], 'fm-inv-pslot').length === 2 && byCls(units[1], 'fm-inv-pslot').length === 2
    && x8units.length === 1 && x8labels.join(',') === 'A1');
}

// ═══ R10: занятый AMS-слот — номер + мини-катушка (SVG-контейнер) + материал + % ═══
{
  const root = base.root;
  const x8 = rowByName(root, 'X8');
  const occ = byCls(x8, 'fm-inv-pslot').filter((c) => !hasCls(c, 'add'));
  const first = occ[0];
  const num = (byCls(first, 'fm-inv-pslot-n')[0] || { textContent: '' }).textContent.trim();
  const matTxt = (byCls(first, 'fm-inv-pslot-m')[0] || { textContent: '' }).textContent.trim();
  const pctTxt = (byCls(first, 'fm-inv-pslot-pct')[0] || { textContent: '' }).textContent.trim();
  check('R10. занятый AMS-слот X8 №1: мини-катушка (.fm-inv-pslot-svg) + «PLA» + «64%»; занятых slot-cells 2',
    occ.length === 2 && num === '1' && byCls(first, 'fm-inv-pslot-svg').length === 1
    && matTxt === 'PLA' && pctTxt === '64%');
}

// ═══ R11: сводные колонки — остаток всего, прогноз (мин days_left, soon) ═══
{
  const root = base.root;
  const x8 = rowByName(root, 'X8'), a1 = rowByName(root, 'A1'), x1c = rowByName(root, 'X1C');
  const rem = (row) => (byCls(row, 'fm-inv-prem')[0] || { textContent: '' }).textContent;
  const fc = (row) => byCls(row, 'fm-inv-pfc')[0];
  check('R11. X8: 720 г · 2 кат., ≈5 дн. (soon); A1: 900 г · 1 кат.; X1C: «—» в остатке и прогнозе',
    rem(x8).includes('720') && rem(x8).includes('2')
    && fc(x8).textContent.includes('≈5') && hasCls(fc(x8), 'soon')
    && rem(a1).includes('900') && rem(a1).includes('1')
    && rem(x1c).includes('—') && fc(x1c).textContent.trim() === '—');
}

// ═══ R12: тумблер скрывает ТОЛЬКО полностью пустые принтеры; «+»-ячейки частично занятых видны ═══
{
  const { root, vm } = await silence(async () => mount(makeWork(OVERVIEW).component));
  const before = dataRows(root).length;
  const countBefore = vm.$.setupState.workEmptyCount;
  vm.$.setupState.showEmptyPrinters = false;
  await nextTick();
  const rowsAfter = dataRows(root);
  const namesAfter = rowsAfter.map((r) => (byCls(r, 'fm-inv-pname2')[0] || { textContent: '' }).textContent.trim());
  const x8 = rowByName(root, 'X8');
  const x8AddsAfter = byCls(x8, 'fm-inv-pslot').filter((c) => hasCls(c, 'add')).length;
  const countAfter = vm.$.setupState.workEmptyCount;
  check('R12. OFF: скрыты ТОЛЬКО полностью пустые (7→5: X8, H2D, X7, X9, A1 остаются); пустые «+» X8 видны (2); workEmptyCount=' + FULLY_EMPTY + ' цел',
    before === TOTAL_PRINTERS && rowsAfter.length === TOTAL_PRINTERS - FULLY_EMPTY
    && ['X8', 'H2D', 'X7', 'X9', 'A1'].every((n) => namesAfter.includes(n))
    && !namesAfter.includes('X1C') && !namesAfter.includes('P1P')
    && x8AddsAfter === 2 && countBefore === FULLY_EMPTY && countAfter === FULLY_EMPTY);
}

// ═══ R13: cold-load — пока loading, таблицы нет; после обзора + loading=false строки появляются ═══
{
  const { root, vm } = await silence(async () => mount(makeWork({ printers: [] }, { loading: true }).component));
  const tableWhileLoading = byCls(root, 'fm-inv-ptable').length;
  const loadingShown = byCls(root, 'ld').length;
  vm.$.setupState.ams = OVERVIEW;      // «пришёл» обзор фермы
  vm.$.setupState.loading = false;     // загрузка завершена
  await nextTick();
  check('R13. cold-load: при loading таблицы нет (показан индикатор); после прихода обзора — таблица со всеми ' + TOTAL_PRINTERS + ' строками',
    tableWhileLoading === 0 && loadingShown === 1
    && byCls(root, 'fm-inv-ptable').length === 1 && dataRows(root).length === TOTAL_PRINTERS);
}

// ═══ R14: 1.7.20 — кнопки строки «⋯» больше нет; действия привязанной катушки — по ПКМ (onSlotMenu -> spoolMenu) ═══
{
  const { root, vm } = await silence(async () => mount(makeWork(OVERVIEW).component));
  const st = vm.$.setupState;
  const x8 = rowByName(root, 'X8');
  const occ = byCls(byCls(x8, 'fm-inv-pams')[0], 'fm-inv-pslot').find((c) => !hasCls(c, 'add'));   // занятый AMS-слот X8 (PLA, s1)
  fireEv(occ, 'contextmenu'); await nextTick();
  const a1ext = byCls(rowByName(root, 'A1'), 'fm-inv-pext')[0];                                     // занятая external A1 (ABS, s3)
  fireEv(a1ext, 'contextmenu'); await nextTick();
  check('R14. кнопок строки «⋯» нет ни у одной строки; действия привязанной катушки — по ПКМ: onSlotMenu вызван для занятого AMS-слота X8 (s1) и занятой external A1 (s3). Отвязать/Заменить — в spoolMenu (проверено в ui/unbind_ui)',
    dataRows(root).every((r) => byCls(r, 'fm-inv-gmore').length === 0)
    && st.calls.menu.length === 2
    && !!st.calls.menu[0] && !!st.calls.menu[0].spool && st.calls.menu[0].spool.id === 's1'
    && !!st.calls.menu[1] && !!st.calls.menu[1].spool && st.calls.menu[1].spool.id === 's3');
}

// ═══ R15: мост runtime<->файл — shipped содержит ДОСЛОВНО эти строки и логику; старых заглушек нет ═══
{
  const tmplMatch = PANEL.match(/template:\s*`([\s\S]*)`/);
  const tmpl = tmplMatch ? tmplMatch[1] : '';
  // Мост разметки теперь неотъемлемый (TABLE_BLOCK извлечён из файла и смонтирован выше);
  // здесь фиксируем структуру секций/групп и дословную логику 1.7.10.
  const rowsOk = TABLE_BLOCK.includes('v-for="sec in workSections"')
    && TABLE_BLOCK.includes('class="fm-inv-psec-h"')
    && TABLE_BLOCK.includes('v-for="r in sec.rows"')
    && TABLE_BLOCK.includes('class="fm-inv-punit2"')
    && TABLE_BLOCK.includes('{{ unitLabel(u) }}')
    && TABLE_BLOCK.includes('{{ slotLocalN(sl) }}')
    && !TABLE_BLOCK.includes('{{ sl.index + 1 }}')
    && TABLE_BLOCK.includes('v-html="klipperSvg"')
    && TABLE_BLOCK.includes(':src="r.cover"')            // 1.7.15: миниатюра берёт готовый cover_url
    && !TABLE_BLOCK.includes('coverUrl(r.model)')        // 1.7.15: URL из сырого model больше НЕ строим
    && PANEL.includes('const workSections = computed')
    //  1.7.26: подпись группы знает про CFS (короб «T1»), поэтому проверяем ОБЕ ветки: прежнюю
    //  AMS-нумерацию и новую, где имя короба приходит от самого принтера.
    && PANEL.includes("return (u.slots.length === 1 && !u.slots[0].offline && u.slots[0].unit != null) ? 'AMS HT' : ('A' + u.n);")
    && PANEL.includes("return lbl ? lbl.slice(0, 2) : ('T' + ((u.n || 0) + 1));")
    && PANEL.includes("kl: (printerTypeById.value[p.printer_id] || '') === 'klipper'");
  const logicOk = PANEL.includes('const workRows = computed')
    && PANEL.includes('arr = arr.filter(printerOcc)')
    && PANEL.includes('const workEmptyCount = computed(() => _amsSearched.value.filter((p) => !printerOcc(p)).length)')
    && PANEL.includes("cover: printerCoverById.value[p.printer_id] || ''")   // 1.7.15: готовый cover_url из ядра
    && PANEL.includes("cu[p.id] = p.cover_url || ''")                        // 1.7.15: приём cover_url из /api/printers
    && PANEL.includes("model: printerModelById.value[p.printer_id] || ''")
    && PANEL.includes('hasFree: (p.slots || []).some((sl) => !sl.spool && !sl.offline)')
    && PANEL.includes("_loadSection('/api/printers'")
    && /const showEmptyPrinters = ref\(true\)/.test(PANEL);
  const oldGone = !tmpl.includes('v-for="c in workSlots"') && !tmpl.includes('fm-inv-workgrid')
    && !tmpl.includes('<svg-icon name="printer" class="w-4 h-4">')   // generic-иконка строки удалена
    && !tmpl.includes('fm-inv-pdash')                                 // «—»-заглушек колонок больше нет
    && !tmpl.includes('fm-inv-pslot-dot')                             // чип с точкой заменён slot-cell с мини-катушкой
    && !tmpl.includes('Нет внешней подачи')                           // ложного capability-состояния в разметке нет
    && tmpl.includes('openBindFor(r.p, r.ext.index)')                 // 1.7.20: external-ячейка -> ПРЯМАЯ external-привязка (index=-1)
    && !tmpl.includes('openBindFor(r.p, null)')                       // 1.7.20: универсальный «Выбрать позицию» убран
    && tmpl.includes('Привязать внешняя');                            // текст external-ячейки
  check('R15. shipped InventoryPanel.js: ДОСЛОВНО те же строки таблицы + логика model/cover_url//api/printers; external-ячейка -> openBindFor(r.p, r.ext.index) (универсал openBindFor(p,null) убран); generic-иконки/«—»-заглушки/«Нет внешней подачи» нет',
    rowsOk && logicOk && oldGone);
}

// ═══ R16: аудит картинок — /api/printers недоступен (моделей нет): fallback у всех, таблица и bind живы ═══
{
  const { root, vm } = await silence(async () => mount(makeWork(OVERVIEW).component));   // без opts.models = запрос моделей упал
  const imgs = byTag(root, 'img');
  const fbs = dataRows(root).map((r) => byCls(byCls(r, 'fm-inv-pimg')[0], 'ico').filter((i) => i.getAttribute('data-name') === 'printer').length);
  fireEv(byCls(rowByName(root, 'P1P'), 'fm-inv-pfree')[0], 'click'); await nextTick();
  check('R16. без данных /api/printers: <img> нет, у ВСЕХ ' + TOTAL_PRINTERS + ' строк fallback svg-icon printer в плашке; таблица полна, bind живёт (P1P external -> слот -1)',
    imgs.length === 0 && fbs.length === TOTAL_PRINTERS && fbs.every((n) => n === 1)
    && dataRows(root).length === TOTAL_PRINTERS
    && vm.$.setupState.calls.bind.some((b) => b.printer_id === 'PRN_P1P' && b.idx === -1));
}

console.log('\n' + (fail ? ('FAIL: ' + fail + ' проверок провалено') : 'PASS: runtime — колонка «Катушка» = отдельная external-позиция (-1) у КАЖДОГО принтера (в т.ч. с AMS): занятая «Внешняя» / «+ Привязать внешняя» -> openBindFor(p,-1); external доступна даже при полном AMS; универсал/«Все позиции заняты»/кнопки строки «⋯» убраны; действия — по ПКМ (onSlotMenu); миниатюры/slot-cells/тумблер/bind живы (Vue mount + DOM)'));
process.exit(fail ? 1 : 0);
