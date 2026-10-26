// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
// РЕАЛЬНЫЙ runtime-тест индикатора сверки материала «Склад → В работе» — inventory 1.7.14.
// Часть S — НАСТОЯЩИЙ вендорный Vue на самодельном DOM монтирует ДОСЛОВНЫЙ блок таблицы (извлечён из
// shipped InventoryPanel.js) с фикстурами material_check во ВСЕХ пяти состояниях (match / material_mismatch /
// color_mismatch / slot_empty / unknown) на AMS-слотах и внешних катушках. Проверяется: индикатор рендерится
// в нужной ячейке, mismatch виден (класс .mm + янтарный dot .mck-warn), тексты состояний, tooltip несёт
// «Сверка: ожидается X · на принтере Y», привязка пустого AMS-слота и внешней катушки продолжают работать,
// multi-AMS (два unit) не сломан. Плюс статическая сверка shipped matCheckView (5 статусов) и разметки.
// Часть L — РЕАЛЬНЫЙ layout-движок (Edge/Chromium headless) dark/light 1366/1750: индикаторы не вызывают
// горизонтального overflow, dot не выходит за slot-cell и не накладывается на номер слота, плашка внешней
// катушки не выходит за свою ячейку; PNG-скриншоты во временной папке прогона.
// Alpha 2.835: L* переведены со сломанного `--dump-dom` на общий CDP-мост (_edge_cdp_lib.mjs) —
// стенд, четыре сценария и все пороги сохранены дословно; недоступный браузер или не вернувшийся
// результат теперь КРАСНЫЕ, а не пропуск.
// Запуск: node tools/test_material_check_ui.mjs   (0 = пройдено)
import { readFileSync, writeFileSync, mkdirSync } from 'fs';
import { tmpdir } from 'os';
import { fileURLToPath, pathToFileURL } from 'url';
import { dirname, join } from 'path';
import { findEngine, measure, browserProblems } from './_edge_cdp_lib.mjs';

const REPO = dirname(dirname(fileURLToPath(import.meta.url)));
const PANEL = readFileSync(join(REPO, 'modules', 'inventory', 'web', 'InventoryPanel.js'), 'utf8');
const APP_CSS = readFileSync(join(REPO, 'web', 'app.css'), 'utf8');
let fail = 0;
const check = (name, cond) => { console.log((cond ? 'PASS' : 'FAIL') + ' — ' + name); if (!cond) fail++; };

// ─────────── минимальный DOM (как в других runtime-тестах модуля) ───────────
class DNode {
  constructor(t) { this.nodeType = t; this.childNodes = []; this.parentNode = null; }
  get nextSibling() { const p = this.parentNode; if (!p) return null; const i = p.childNodes.indexOf(this); return i >= 0 ? (p.childNodes[i + 1] || null) : null; }
  _link(c, a) { if (c.parentNode) c.parentNode.removeChild(c); c.parentNode = this; if (a && a.parentNode === this) this.childNodes.splice(this.childNodes.indexOf(a), 0, c); else this.childNodes.push(c); return c; }
  insertBefore(c, a) { return this._link(c, a); }
  appendChild(c) { return this._link(c, null); }
  removeChild(c) { const i = this.childNodes.indexOf(c); if (i >= 0) this.childNodes.splice(i, 1); c.parentNode = null; return c; }
  getRootNode() { return globalThis.document; }
  get ownerDocument() { return globalThis.document; }
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
  set disabled(v) { this._disabled = !!v; }
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
}
const doc = { createElement: (t) => new DElement(t), createElementNS: (ns, t) => new DElement(t), createTextNode: (t) => new DText(t), createComment: (t) => new DComment(t), querySelector: () => null, addEventListener: () => {}, removeEventListener: () => {}, activeElement: null };
doc.body = new DElement('body'); doc.head = new DElement('head'); doc.documentElement = new DElement('html');
if (!globalThis.document) globalThis.document = doc;
if (!globalThis.window) { try { globalThis.window = globalThis; } catch (e) {} }
for (const g of ['SVGElement', 'HTMLElement', 'Element', 'Node', 'ShadowRoot', 'Document', 'DocumentFragment']) { if (globalThis[g] === undefined) globalThis[g] = class {}; }

const Vue = await import(pathToFileURL(join(REPO, 'web', 'vendor', 'vue.esm-browser.js')).href);
const { createApp, ref, reactive, computed, nextTick } = Vue;

// ─────────── ДОСЛОВНЫЙ блок таблицы из shipped-панели ───────────
const extractTable = () => {
  const key = '<div v-else class="fm-inv-ptable">';
  const s = PANEL.indexOf(key);
  const openEnd = PANEL.indexOf('>', s) + 1;
  const re = /<div\b|<\/div>/g; re.lastIndex = openEnd;
  let m, d = 1, close = -1;
  while ((m = re.exec(PANEL))) { d += (m[0] === '</div>') ? -1 : 1; if (d === 0) { close = m.index; break; } }
  return PANEL.slice(s, close + 6).replace('v-else class="fm-inv-ptable"', 'class="fm-inv-ptable"');
};
const TABLE_BLOCK = extractTable();
check('S0. блок таблицы извлечён; содержит индикатор (fm-inv-mck / fm-inv-mck-dot) и matCheckView(sl)',
  TABLE_BLOCK.includes('fm-inv-mck') && TABLE_BLOCK.includes('fm-inv-mck-dot') && TABLE_BLOCK.includes('matCheckView('));
// shipped matCheckView отображает ВСЕ пять статусов
check('S0b. shipped matCheckView охватывает все 5 статусов + matCheckTip формирует «Сверка/ожидается/на принтере»',
  ['match:', 'material_mismatch:', 'color_mismatch:', 'slot_empty:', 'unknown:'].every((k) => PANEL.includes(k))
  && PANEL.includes('const matCheckView') && PANEL.includes('const matCheckTip')
  && PANEL.includes("L('Сверка', 'Check')") && PANEL.includes("L('ожидается', 'expected')"));

// ─────────── фикстуры material_check во всех пяти состояниях ───────────
const MC = (status, exp, rep, ecol, rcol) => ({ status, reason: '', expected_material: exp, reported_material: rep,
  expected_color: ecol || null, reported_color: rcol || null, checked_at: '2026-07-14 10:00:00' });
const SP = (id, mat) => ({ id, material: mat, color_name: '', color_hex: '00aa55', weight_remaining_g: 800, weight_total_g: 1000, vendor_name: 'V' });
const OVERVIEW = { printers: [
  // AMS с ДВУМЯ unit: все пять состояний (unit0 слоты 0-3, unit1 слот 4)
  { printer_id: 'AMS', printer_name: 'AMS', has_ams: true, slots: [
    { index: 0, unit: 0, tray: 0, spool: SP('a0', 'PETG'), material_check: MC('match', 'PETG', 'PETG') },
    { index: 1, unit: 0, tray: 1, spool: SP('a1', 'PETG'), material_check: MC('material_mismatch', 'PETG', 'ABS') },
    { index: 2, unit: 0, tray: 2, spool: SP('a2', 'PETG'), material_check: MC('color_mismatch', 'PETG', 'PETG', '#00FF00', '#FF0000') },
    { index: 3, unit: 0, tray: 3, spool: SP('a3', 'PETG'), material_check: MC('slot_empty', 'PETG', null) },
    { index: 4, unit: 1, tray: 0, spool: SP('a4', 'PLA'), material_check: MC('unknown', 'PLA', null) },
    { index: 5, unit: 1, tray: 1, spool: SP('a5', 'PETG'), material_check: MC('match', 'PETG', 'PETG') },
  ] },
  // AMS2: слот 0 занят (match), слот 1 пуст — для проверки привязки пустого AMS-слота
  { printer_id: 'AMS2', printer_name: 'AMS2', has_ams: true, slots: [
    { index: 0, unit: 0, tray: 0, spool: SP('b0', 'PETG'), material_check: MC('match', 'PETG', 'PETG') },
    { index: 1, unit: 0, tray: 1 },
  ] },
  // Внешняя катушка: mismatch (плашка-предупреждение)
  { printer_id: 'EXT', printer_name: 'EXT', has_ams: false, slots: [
    { index: 0, external: true, spool: SP('e0', 'PETG'), material_check: MC('material_mismatch', 'PETG', 'ABS') },
  ] },
  // Внешняя катушка: match (спокойная плашка)
  { printer_id: 'EXT2', printer_name: 'EXT2', has_ams: false, slots: [
    { index: 0, external: true, spool: SP('e1', 'PETG'), material_check: MC('match', 'PETG', 'PETG') },
  ] },
  // Внешняя ПУСТАЯ — для проверки привязки внешней катушки
  { printer_id: 'EXT3', printer_name: 'EXT3', has_ams: false, slots: [ { index: 0, external: true } ] },
] };
const MODELS = {}; const TYPES = { AMS: 'bambu', AMS2: 'bambu', EXT: 'bambu', EXT2: 'bambu', EXT3: 'bambu' };

// ─────────── фабрика: shipped-логика + ДОСЛОВНЫЕ matCheckView/matCheckTip/workSlotTitle 1.7.14 ───────────
const makeWork = (overview) => {
  const calls = { bind: [], click: [], menu: [] };
  const component = {
    setup() {
      const L = (ru) => ru;
      const loading = ref(false), ams = ref(overview), q = ref(''), showEmptyPrinters = ref(true);
      const fcMap = ref({}), printerModelById = ref(MODELS), printerTypeById = ref(TYPES), klipperSvg = ref('');
      const spoolById = computed(() => { const m = {}; for (const p of (ams.value.printers || [])) for (const sl of (p.slots || [])) if (sl.spool) m[sl.spool.id] = sl.spool; return m; });
      const slotFull = (sl) => (sl && sl.spool && spoolById.value[sl.spool.id]) || null;
      const slotLow = () => false;
      const pct = (s) => { const t = +s.weight_total_g || 0; return t <= 0 ? 0 : Math.max(0, Math.min(100, Math.round((+s.weight_remaining_g || 0) / t * 100))); };
      const barColor = () => 'var(--fm-success)';
      const printerBoundG = (p) => { let g = 0; for (const sl of (p.slots || [])) if (sl && sl.spool) g += (+sl.spool.weight_remaining_g || 0); return Math.round(g); };
      const printerBoundN = (p) => (p.slots || []).filter((sl) => sl && sl.spool).length;
      const slotUnits = (p) => { const order = []; const map = {}; for (const sl of (p.slots || [])) { const u = (sl.unit == null ? 0 : sl.unit); if (!(u in map)) { map[u] = []; order.push(u); } map[u].push(sl); } return order.map((u, i) => ({ unit: u, n: i + 1, slots: map[u] })); };
      const coverBroken = reactive({});
      const coverUrl = (m) => '/covers/' + encodeURIComponent(String(m) + '_cover.png');
      const printerOcc = (p) => (p.slots || []).some((sl) => sl && sl.spool);
      const _amsSearched = computed(() => (ams.value.printers || []).slice());
      const workPrinters = computed(() => { const rank = (p) => (printerOcc(p) ? 1 : 2); let arr = _amsSearched.value; if (!showEmptyPrinters.value) arr = arr.filter(printerOcc); return arr.map((p, i) => ({ p, i })).sort((a, b) => (rank(a.p) - rank(b.p)) || (a.i - b.i)).map((x) => x.p); });
      const workEmptyCount = computed(() => _amsSearched.value.filter((p) => !printerOcc(p)).length);
      const workExternal = (p) => { for (const sl of (p.slots || [])) if (sl.external) return sl; return null; };
      const workAmsUnits = (p) => slotUnits({ slots: (p.slots || []).filter((sl) => !sl.external) });
      const workStatus = (p) => (!printerOcc(p) ? { k: 'empty', t: 'Пусто' } : { k: 'ok', t: 'Готов' });
      const workRows = computed(() => workPrinters.value.map((p) => ({ p, ext: workExternal(p), units: workAmsUnits(p), unconfirmed: (p.slots||[]).filter((sl)=>sl.unconfirmed&&sl.spool), remainG: printerBoundG(p), boundN: printerBoundN(p), days: null, st: workStatus(p), model: printerModelById.value[p.printer_id] || '', kl: (printerTypeById.value[p.printer_id] || '') === 'klipper', hasFree: (p.slots || []).some((sl) => !sl.spool && !sl.offline) })));
      const workSections = computed(() => { const a = [], e = [], em = []; for (const r of workRows.value) { if (r.st.k === 'empty') { em.push(r); continue; } (r.units.length ? a : e).push(r); } const busy = a.reduce((n, r) => n + r.units.reduce((m, u) => m + u.slots.filter((s) => s.spool).length, 0), 0); const sp = e.reduce((n, r) => n + (r.boundN || 0), 0); return [{ key: 'ams', title: 'Системы AMS', count: a.length + ' принт. · ' + busy + ' занятых слотов', rows: a }, { key: 'ext', title: 'Внешняя подача', count: e.length + ' принт. · ' + sp + ' кат.', rows: e }, { key: 'empty', title: 'Без катушки', count: em.length + ' принт.', rows: em }].filter((s) => s.rows.length); });
      const unitLabel = (u) => ((u.slots.length === 1 && !u.slots[0].offline && u.slots[0].unit != null) ? 'AMS HT' : ('A' + u.n));
      const slotLocalN = (sl) => { if (!sl) return ''; if (sl.tray != null) return Number(sl.tray) + 1; const i = Number(sl.index) || 0; if (sl.unit != null) return i - Number(sl.unit) * 4 + 1; return (i % 4) + 1; };
      // ==== ДОСЛОВНО shipped 1.7.14 ====
      const matCheckTip = (mc) => {
        if (!mc || !mc.status) return '';
        const exp = mc.expected_material || '—';
        const rep = mc.status === 'slot_empty' ? 'пусто' : (mc.reported_material || (mc.status === 'unknown' ? 'нет данных' : '—'));
        return 'Сверка' + ': ' + 'ожидается' + ' ' + exp + ' · ' + 'на принтере' + ' ' + rep;
      };
      const workSlotTitle = (sl) => {
        const base = (sl.external ? 'Внешняя катушка' : ('AMS · ' + 'слот' + ' ' + (sl.index + 1))) + (sl.offline ? (' · офлайн') : '');
        if (!sl.spool) return base + ' — привязать';
        const s = sl.spool;
        const mck = sl.material_check ? ' · ' + matCheckTip(sl.material_check) : '';
        return base + ': ' + ([s.material, s.color_name, s.vendor_name].filter(Boolean).join(' · ') || s.label || '') + ' · ' + Math.round(s.weight_remaining_g || 0) + ' г · ' + pct(s) + '% — меню' + mck;
      };
      const matCheckView = (sl) => {
        const mc = sl && sl.material_check; if (!mc || !mc.status) return null;
        const rep = mc.reported_material || '';
        const M = {
          match: { k: 'ok', ic: '✓', t: 'Совпадает' },
          material_mismatch: { k: 'warn', ic: '!', t: 'На принтере' + ': ' + (rep || '—') },
          color_mismatch: { k: 'color', ic: '≈', t: 'Цвет отличается' },
          slot_empty: { k: 'empty', ic: '∅', t: 'На принтере пусто' },
          unknown: { k: 'unk', ic: '?', t: 'Нет свежих данных' },
        };
        return M[mc.status] || M.unknown;
      };
      const onSlotClick = (sl) => calls.click.push(sl);
      const onSlotMenu = (e, sl) => calls.menu.push(sl);
      const openBindFor = (p, idx) => calls.bind.push({ printer_id: p.printer_id, idx });
      const workRowMenu = () => {};
      const spoolSvg = () => '<svg viewBox="0 0 10 10" width="24" height="24"><circle cx="5" cy="5" r="4"/></svg>';
      return { L, loading, ams, q, showEmptyPrinters, fcMap, printerModelById, printerTypeById, klipperSvg, coverBroken, coverUrl, workRows, workSections, unitLabel, slotLocalN, workEmptyCount, workSlotTitle, matCheckView, matCheckTip, workRowMenu, slotFull, slotLow, onSlotClick, onSlotMenu, openBindFor, spoolSvg, barColor, pct };
    },
    template: '<div class="wrap">' + TABLE_BLOCK + '</div>',
    compilerOptions: { decodeEntities: (x) => x },
  };
  return { component, calls };
};
const mount = (component) => { const app = createApp(component); app.config.warnHandler = () => {}; app.component('svg-icon', { props: { name: { type: String, default: '' } }, template: '<i class="ico" :data-name="name"></i>' }); const root = new DElement('div'); const vm = app.mount(root); return { root, vm }; };
const byCls = (root, c) => root._findAll((e) => (' ' + e.className + ' ').includes(' ' + c + ' '));
const hasCls = (e, c) => (' ' + e.className + ' ').includes(' ' + c + ' ');
const fireEv = (el, type) => el._fire(type, { type, target: el, stopPropagation() {}, preventDefault() {} });
const clsOf = (e, prefix) => (e.className.split(/\s+/).find((c) => c.startsWith(prefix)) || '').slice(prefix.length);

const made = makeWork(OVERVIEW);
const { root } = mount(made.component);
await nextTick();

// ═══ S1: все пять состояний присутствуют (5 dot-статусов на AMS, 2 плашки на внешних) ═══
{
  const dots = byCls(root, 'fm-inv-mck-dot');
  const pills = byCls(root, 'fm-inv-mck');
  const dotStatuses = new Set(dots.map((d) => clsOf(d, 'mck-')));
  const pillStatuses = new Set(pills.map((p) => clsOf(p, 'mck-')));
  check('S1. AMS-точки покрывают все 5 статусов (ok/warn/color/empty/unk); внешние плашки — ok+warn',
    ['ok', 'warn', 'color', 'empty', 'unk'].every((k) => dotStatuses.has(k))
    && pillStatuses.has('ok') && pillStatuses.has('warn') && pills.length === 2);
}

// ═══ S2: material_mismatch ВИДЕН в AMS slot-cell — класс .mm + янтарный dot .mck-warn ═══
{
  const slots = byCls(root, 'fm-inv-pslot');
  const mm = slots.filter((s) => hasCls(s, 'mm'));
  const warnDotInside = mm.length === 1 && byCls(mm[0], 'fm-inv-mck-dot').some((d) => hasCls(d, 'mck-warn'));
  check('S2. AMS material_mismatch виден без меню: ячейка .fm-inv-pslot.mm + внутри dot .mck-warn («!»)',
    mm.length === 1 && warnDotInside && byCls(mm[0], 'fm-inv-mck-dot')[0].textContent.trim() === '!');
}

// ═══ S3: внешняя material_mismatch — плашка с текстом «На принтере: ABS» ═══
{
  const pill = byCls(root, 'fm-inv-mck').find((p) => hasCls(p, 'mck-warn'));
  check('S3. внешняя плашка material_mismatch содержит «На принтере: ABS»',
    !!pill && pill.textContent.includes('На принтере') && pill.textContent.includes('ABS'));
}

// ═══ S4: внешняя match — плашка «Совпадает» ═══
{
  const pill = byCls(root, 'fm-inv-mck').find((p) => hasCls(p, 'mck-ok'));
  check('S4. внешняя плашка match содержит «Совпадает»', !!pill && pill.textContent.includes('Совпадает'));
}

// ═══ S5/S6: slot_empty («∅») и unknown («?») — компактные точки нужных классов ═══
{
  const dots = byCls(root, 'fm-inv-mck-dot');
  const emp = dots.find((d) => hasCls(d, 'mck-empty'));
  const unk = dots.find((d) => hasCls(d, 'mck-unk'));
  check('S5. slot_empty → dot .mck-empty с иконкой «∅»', !!emp && emp.textContent.trim() === '∅');
  check('S6. unknown → dot .mck-unk с иконкой «?» (компактно, не доминирует)', !!unk && unk.textContent.trim() === '?');
}

// ═══ S7: tooltip ячейки несёт полную сверку «Сверка: ожидается X · на принтере Y» ═══
{
  const mmSlot = byCls(root, 'fm-inv-pslot').find((s) => hasCls(s, 'mm'));
  const extMatch = byCls(root, 'fm-inv-pext').find((c) => (c.getAttribute('title') || '').includes('Совпадает') === false && (c.getAttribute('title') || '').includes('PETG'));
  const amsTip = mmSlot ? (mmSlot.getAttribute('title') || '') : '';
  check('S7. tooltip AMS-mismatch: «Сверка … ожидается PETG … на принтере ABS»',
    amsTip.includes('Сверка') && amsTip.includes('ожидается') && amsTip.includes('PETG') && amsTip.includes('ABS'));
  check('S7b. tooltip внешней match: «Сверка … PETG» (полный текст expected/reported в title)',
    !!extMatch && (extMatch.getAttribute('title') || '').includes('Сверка') && (extMatch.getAttribute('title') || '').includes('PETG'));
}

// ═══ S8: привязка пустого AMS-слота продолжает работать (клик add-кнопки → openBindFor с верным индексом) ═══
// ═══ S9: привязка внешней катушки продолжает работать (клик .fm-inv-pfree) ═══
{
  made.calls.bind.length = 0;
  byCls(root, 'fm-inv-pslot').filter((s) => hasCls(s, 'add')).forEach((b) => fireEv(b, 'click'));
  byCls(root, 'fm-inv-pfree').forEach((b) => fireEv(b, 'click'));
  const binds = made.calls.bind;
  check('S8. пустой AMS-слот: клик add-кнопки → openBindFor(AMS2, 1) (bind не сломан индикатором)',
    binds.some((b) => b.printer_id === 'AMS2' && b.idx === 1));
  check('S9. внешняя катушка: клик «+ Привязать» → openBindFor(EXT3, 0) (external bind жив)',
    binds.some((b) => b.printer_id === 'EXT3' && b.idx === 0));
}

// ═══ S10: multi-AMS не сломан (два unit у AMS-принтера; локальные номера лотков) ═══
{
  const amsRow = byCls(root, 'fm-inv-prow').find((r) => (byCls(r, 'fm-inv-pname2')[0] || { textContent: '' }).textContent.trim() === 'AMS');
  const units = amsRow ? byCls(amsRow, 'fm-inv-punit2') : [];
  const labels = units.map((u) => (byCls(u, 'fm-inv-punit2-l')[0] || { textContent: '' }).textContent.trim());
  const nums = amsRow ? byCls(amsRow, 'fm-inv-pslot-n').map((n) => n.textContent.trim()) : [];
  check('S10. multi-AMS цел: два unit (A1 + A2), локальные номера лотков 1..4 и 1..2 (индикатор не сломал структуру)',
    units.length === 2 && labels.join('|') === 'A1|A2' && nums.join(',') === '1,2,3,4,1,2');
}

// ═══ S11: клик по ЗАНЯТОМУ слоту с индикатором → история (onSlotClick), а не bind (dot не крадёт клик) ═══
{
  made.calls.click.length = 0;
  const occ = byCls(root, 'fm-inv-pslot').find((s) => !hasCls(s, 'add') && byCls(s, 'fm-inv-mck-dot').length);
  if (occ) fireEv(occ, 'click');
  check('S11. клик по занятому AMS-слоту с индикатором → onSlotClick (история), индикатор не перехватывает клик',
    made.calls.click.length === 1);
}

// ═══════════════ L*: реальный layout-движок (Edge/Chromium headless) dark/light ═══════════════
const ENGINE = findEngine();

const cssVar = (block, name) => { const m = new RegExp(name.replace(/[-]/g, '[-]') + ':\\s*([^;}]+)[;}]').exec(block); return m ? m[1].trim() : ''; };
const _blockAround = (idx) => APP_CSS.slice(APP_CSS.lastIndexOf('{', idx) + 1, APP_CSS.indexOf('}', idx));
const _dIdx = APP_CSS.indexOf('--fm-surface-raised:');
const _lIdx = APP_CSS.indexOf('--fm-surface-raised:', _dIdx + 10);
const darkRoot = _blockAround(_dIdx), lightRoot = _blockAround(_lIdx);
const VARS = (block, fallback) => ['--fm-surface-raised', '--fm-surface-card', '--fm-border-soft', '--fm-border-strong', '--fm-border', '--fm-text-primary', '--fm-text-secondary', '--fm-text-subtle', '--fm-accent-rgb', '--fm-black-rgb', '--fm-accent', '--fm-success', '--fm-danger']
  .map((v) => v + ':' + (cssVar(block, v) || cssVar(fallback, v) || '#888')).join(';');
const coreRule = (sel) => (new RegExp(sel.replace(/[.]/g, '\\.') + '\\{[^}]*\\}')).exec(APP_CSS)[0];
const CARD_CSS_TEXT = (() => { const i = PANEL.indexOf('const CARD_CSS = ['); const j = PANEL.indexOf("].join('\\n');", i); const arr = new Function('return ' + PANEL.slice(i + 'const CARD_CSS ='.length, j + 1))(); return arr.join('\n'); })();

check('L0. движок рендера для браузерных измерений найден (без него L-проверки невозможны)', !!ENGINE);
if (ENGINE) {
  const tmp = join(tmpdir(), 'fm-inv-mck-' + process.pid);
  mkdirSync(tmp, { recursive: true });
  // Снимки — во временную папку прогона (раньше _incoming/): рабочие каталоги проекта не трогаем.
  const shotsDir = join(tmp, 'shots');
  try { mkdirSync(shotsDir, { recursive: true }); } catch (e) {}
  const vueUrl = pathToFileURL(join(REPO, 'web', 'vendor', 'vue.esm-browser.js')).href;
  const setupSrc = `
const L = (ru) => ru;
const loading = ref(false); const ams = ref(OVERVIEW); const q = ref(''); const showEmptyPrinters = ref(true);
const fcMap = ref({}); const printerModelById = ref({}); const printerTypeById = ref(TYPES); const klipperSvg = ref('');
const spoolById = computed(() => { const m = {}; for (const p of (ams.value.printers||[])) for (const sl of (p.slots||[])) if (sl.spool) m[sl.spool.id]=sl.spool; return m; });
const slotFull = (sl) => (sl && sl.spool && spoolById.value[sl.spool.id]) || null;
const slotLow = () => false;
const pct = (s) => { const t=+s.weight_total_g||0; return t<=0?0:Math.max(0,Math.min(100,Math.round((+s.weight_remaining_g||0)/t*100))); };
const barColor = () => 'var(--fm-success)';
const printerBoundG = (p) => { let g=0; for (const sl of (p.slots||[])) if (sl&&sl.spool) g+=(+sl.spool.weight_remaining_g||0); return Math.round(g); };
const printerBoundN = (p) => (p.slots||[]).filter((sl)=>sl&&sl.spool).length;
const slotUnits = (p) => { const order=[]; const map={}; for (const sl of (p.slots||[])) { const u=(sl.unit==null?0:sl.unit); if(!(u in map)){map[u]=[];order.push(u);} map[u].push(sl);} return order.map((u,i)=>({unit:u,n:i+1,slots:map[u]})); };
const coverBroken = reactive({});
const coverUrl = () => 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="52" height="52"><rect width="52" height="52" fill="#456"/></svg>');
const printerOcc = (p) => (p.slots||[]).some((sl)=>sl&&sl.spool);
const _amsSearched = computed(() => (ams.value.printers||[]).slice());
const workPrinters = computed(() => { const rank=(p)=>(printerOcc(p)?1:2); let arr=_amsSearched.value; if(!showEmptyPrinters.value) arr=arr.filter(printerOcc); return arr.map((p,i)=>({p,i})).sort((a,b)=>(rank(a.p)-rank(b.p))||(a.i-b.i)).map((x)=>x.p); });
const workEmptyCount = computed(() => _amsSearched.value.filter((p)=>!printerOcc(p)).length);
const workExternal = (p) => { for (const sl of (p.slots||[])) if (sl.external) return sl; return null; };
const workAmsUnits = (p) => slotUnits({ slots: (p.slots||[]).filter((sl)=>!sl.external) });
const workStatus = (p) => (!printerOcc(p) ? {k:'empty',t:'Пусто'} : {k:'ok',t:'Готов'});
const workRows = computed(() => workPrinters.value.map((p) => ({ p, ext: workExternal(p), units: workAmsUnits(p), unconfirmed: (p.slots||[]).filter((sl)=>sl.unconfirmed&&sl.spool), remainG: printerBoundG(p), boundN: printerBoundN(p), days: null, st: workStatus(p), model: '', kl: false, hasFree: (p.slots||[]).some((sl)=>!sl.spool&&!sl.offline) })));
const workSections = computed(() => { const a=[],e=[],em=[]; for (const r of workRows.value){ if(r.st.k==='empty'){em.push(r);continue;} (r.units.length?a:e).push(r);} const busy=a.reduce((n,r)=>n+r.units.reduce((m,u)=>m+u.slots.filter((s)=>s.spool).length,0),0); const sp=e.reduce((n,r)=>n+(r.boundN||0),0); return [ {key:'ams',title:'Системы AMS',count:a.length+' принт. · '+busy+' занятых слотов',rows:a}, {key:'ext',title:'Внешняя подача',count:e.length+' принт. · '+sp+' кат.',rows:e}, {key:'empty',title:'Без катушки',count:em.length+' принт.',rows:em} ].filter((s)=>s.rows.length); });
const unitLabel = (u) => ((u.slots.length === 1 && !u.slots[0].offline && u.slots[0].unit != null) ? 'AMS HT' : ('A' + u.n));
const slotLocalN = (sl) => { if(!sl) return ''; if (sl.tray != null) return Number(sl.tray)+1; const i=Number(sl.index)||0; if (sl.unit != null) return i - Number(sl.unit)*4 + 1; return (i%4)+1; };
const matCheckTip = (mc) => { if(!mc||!mc.status) return ''; const exp=mc.expected_material||'—'; const rep=mc.status==='slot_empty'?'пусто':(mc.reported_material||(mc.status==='unknown'?'нет данных':'—')); return 'Сверка: ожидается '+exp+' · на принтере '+rep; };
const workSlotTitle = (sl) => { const base=(sl.external?'Внешняя катушка':('AMS · слот '+(sl.index+1)))+(sl.offline?' · офлайн':''); if(!sl.spool) return base+' — привязать'; const s=sl.spool; const mck=sl.material_check?' · '+matCheckTip(sl.material_check):''; return base+': '+([s.material,s.color_name,s.vendor_name].filter(Boolean).join(' · ')||'')+' · '+Math.round(s.weight_remaining_g||0)+' г · '+pct(s)+'% — меню'+mck; };
const matCheckView = (sl) => { const mc=sl&&sl.material_check; if(!mc||!mc.status) return null; const rep=mc.reported_material||''; const M={ match:{k:'ok',ic:'✓',t:'Совпадает'}, material_mismatch:{k:'warn',ic:'!',t:'На принтере: '+(rep||'—')}, color_mismatch:{k:'color',ic:'≈',t:'Цвет отличается'}, slot_empty:{k:'empty',ic:'∅',t:'На принтере пусто'}, unknown:{k:'unk',ic:'?',t:'Нет свежих данных'} }; return M[mc.status]||M.unknown; };
const onSlotClick = () => {}; const onSlotMenu = () => {}; const openBindFor = () => {}; const workRowMenu = () => {};
const spoolSvg = () => '<svg viewBox="0 0 10 10" width="24" height="24"><circle cx="5" cy="5" r="4" fill="var(--fm-accent)"/></svg>';
return { L, loading, ams, q, showEmptyPrinters, fcMap, printerModelById, printerTypeById, klipperSvg, coverBroken, coverUrl, workRows, workSections, unitLabel, slotLocalN, workEmptyCount, workSlotTitle, matCheckView, matCheckTip, workRowMenu, slotFull, slotLow, onSlotClick, onSlotMenu, openBindFor, spoolSvg, barColor, pct };`;
  const buildPage = (theme) => `<!doctype html><html><head><meta charset="utf-8"><style>
:root{${theme === 'dark' ? VARS(darkRoot, darkRoot) : VARS(lightRoot, darkRoot)}}
html,body{margin:0;background:${theme === 'dark' ? '#141416' : '#eef1f4'};font:13px system-ui}
${coreRule('.fm-inv-panel')}
${coreRule('.fm-inv-body')}
${coreRule('.fm-inv-toolbar')}
${CARD_CSS_TEXT}
.fm-inv-panel{margin:10px auto;height:calc(100vh - 20px)}
</style></head><body>
<div class="fm-inv-panel"><div class="fm-inv-body" id="sc"><div class="fm-inv-tabpane"><div id="app"></div></div></div></div>
<pre id="__res" style="position:fixed;left:0;bottom:0;font:11px monospace;background:rgba(0,0,0,.85);color:#0f0;z-index:99;white-space:pre;max-width:100vw;overflow:hidden"></pre>
<script type="module">
import { createApp, ref, reactive, computed } from '${vueUrl}';
const OVERVIEW = ${JSON.stringify(OVERVIEW)};
const TYPES = ${JSON.stringify(TYPES)};
const app = createApp({ setup() { ${setupSrc} }, template: ${JSON.stringify('<div>' + TABLE_BLOCK + '</div>')} });
app.component('svg-icon', { props: { name: String }, template: '<i style="display:inline-block;width:26px;height:26px;background:currentColor;opacity:.4;border-radius:4px"></i>' });
app.mount('#app');
requestAnimationFrame(() => requestAnimationFrame(() => {
  const sc = document.getElementById('sc');
  const dots = [...document.querySelectorAll('.fm-inv-mck-dot')];
  const pills = [...document.querySelectorAll('.fm-inv-mck')];
  const overflowX = sc.scrollWidth - sc.clientWidth;
  const dotIn = dots.every((d) => { const r = d.getBoundingClientRect(), c = d.closest('.fm-inv-pslot').getBoundingClientRect(); return r.right <= c.right + 1 && r.top >= c.top - 1 && r.left >= c.left - 1; });
  const pillIn = pills.every((p) => { const r = p.getBoundingClientRect(), c = p.closest('.fm-inv-pext').getBoundingClientRect(); return r.right <= c.right + 1 && r.left >= c.left - 1; });
  const noNumOverlap = dots.every((d) => { const dn = d.closest('.fm-inv-pslot').querySelector('.fm-inv-pslot-n'); if (!dn) return true; const a = d.getBoundingClientRect(), b = dn.getBoundingClientRect(); return a.left >= b.right - 0.5 || a.right <= b.left + 0.5 || a.top >= b.bottom - 0.5 || a.bottom <= b.top + 0.5; });
  const res = { theme: ${JSON.stringify(theme)}, w: innerWidth, dots: dots.length, pills: pills.length, overflowX, dotIn, pillIn, noNumOverlap };
  document.getElementById('__res').textContent = '@@RES@@' + JSON.stringify(res) + '@@END@@';
  document.title = 'ready';
}));
</scr` + `ipt></body></html>`;
  const CASES = [['dark', 1366, 768], ['dark', 1750, 880], ['light', 1366, 768], ['light', 1750, 880]];
  let ran = 0;
  for (const [theme, w, h] of CASES) {
    const pg = join(tmp, 'mck-' + theme + '-' + w + '.html');
    writeFileSync(pg, buildPage(theme), 'utf8');
    const shot = join(shotsDir, `inv_1714_mck_${theme}_${w}x${h}.png`);
    let out = null, why = '';
    try { out = await measure({ url: pathToFileURL(pg).href, width: w, height: h, engine: ENGINE, shot }); }
    catch (e) { why = String((e && e.message) || e); }
    if (!out) { check(`L. ${theme} ${w}x${h}: стенд выполнен в реальном браузере`, false); console.log('   причина: ' + why); continue; }
    const probs = browserProblems(out);
    check(`L. ${theme} ${w}x${h}: страница без ошибок JS/консоли/Vue`, probs.length === 0);
    if (probs.length) console.log('   ' + probs.join('\n   '));
    const r = out.res;
    ran++;
    const ok = r.dots >= 5 && r.pills === 2 && r.overflowX <= 0 && r.dotIn && r.pillIn && r.noNumOverlap;
    check(`L. ${theme} ${w}x${h}: ${r.dots} точек / ${r.pills} плашки, overflowX=${r.overflowX} (≤0), dot в slot-cell=${r.dotIn}, плашка в ячейке=${r.pillIn}, нет наложения на № слота=${r.noNumOverlap} — скриншот ${shot}`, ok);
  }
  check('L. все 4 сценария (dark/light × 1366x768 / 1750x880) реально исполнены в браузере', ran === CASES.length);
}

console.log('\n' + (fail ? ('FAIL: ' + fail + ' проверок провалено') : 'PASS: индикатор сверки материала — 5 состояний, mismatch виден, tooltip, bind цел, multi-AMS, layout dark/light (реальный Edge через CDP, 0 пропусков)'));
process.exit(fail ? 1 : 0);
