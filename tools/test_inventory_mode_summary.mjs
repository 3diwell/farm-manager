// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
// Тест MODE-специфичной сводки «кг / типов / катушек» — inventory 1.7.20 (item 7).
// Извлекает РЕАЛЬНЫЕ _gtxt/_matKey/isBound/_kpiAgg и computed kpi из InventoryPanel.js и ВЫПОЛНЯЕТ их на
// фикстуре spools. Проверяет: work = привязанные (external -1 + AMS >=0), stock = живые непривязанные без
// pending; каждый spool id — ОДИН раз (нет двойного счёта, даже если катушка фигурирует в нескольких
// представлениях UI); типы = уникальный нормализованный material; сумма = Σ weight_remaining_g; сводка НЕ
// зависит от поиска/фильтров (kpi читает только spools.value); nav-счётчики bound/stock = те же множества.
// Запуск: node tools/test_inventory_mode_summary.mjs   (0 = пройдено)
import { readFileSync } from 'fs';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const REPO = dirname(dirname(fileURLToPath(import.meta.url)));
const PANEL = readFileSync(join(REPO, 'modules', 'inventory', 'web', 'InventoryPanel.js'), 'utf8');
let fail = 0;
const check = (name, cond) => { console.log((cond ? 'PASS' : 'FAIL') + ' — ' + name); if (!cond) fail++; };

const grab = (re, what) => { const m = re.exec(PANEL); if (!m) throw new Error('не найдено: ' + what); return m[0]; };
const SRC_GTXT = grab(/const _gtxt = \(v\) => [^\n]+?;/, '_gtxt');
const SRC_MATKEY = grab(/const _matKey = \(s\) => [^\n]+?;/, '_matKey');
const SRC_ISBOUND = grab(/const isBound = \(s\) => [^\n]+?;/, 'isBound');
const SRC_KPIAGG = grab(/const _kpiAgg = \(list\) => \{.*\};/, '_kpiAgg');   // однострочный: жадный .* до последнего };
const SRC_KPI = grab(/const kpi = computed\(\(\) => \{[\s\S]*?total: cur\.count \};[\s\S]*?\}\);/, 'kpi');

// harness: computed-стаб пересчитывает при каждом обращении к .value
const build = new Function('spools', 'wmode', 'computed',
  SRC_GTXT + '\n' + SRC_MATKEY + '\n' + SRC_ISBOUND + '\n' + SRC_KPIAGG + '\n' + SRC_KPI + '\n return kpi;');
const mkKpi = (fixture, mode) => {
  const spools = { value: fixture };
  const wmode = { value: mode };
  const computed = (fn) => ({ get value() { return fn(); } });
  return build(spools, wmode, computed).value;
};

// ── фикстура: bound external(-1) + bound AMS(0) на ОДНОМ принтере (P1) — риск двойного счёта в per-printer
//    представлении; сток с повтором материала; pending-сток (исключается); пустой сток (включается) ──
const S = (o) => Object.assign({ ams_printer_id: '', ams_slot: -1, material: 'PLA', weight_remaining_g: 100, status: 'in_stock', pending: false }, o);
const FIX = [
  S({ id: 'be', ams_printer_id: 'P1', ams_slot: -1, material: 'PLA', weight_remaining_g: 500, status: 'loaded' }),   // external bound
  S({ id: 'ba', ams_printer_id: 'P1', ams_slot: 0,  material: 'PETG', weight_remaining_g: 300, status: 'loaded' }),  // AMS0 bound (тот же принтер!)
  S({ id: 'ba2', ams_printer_id: 'P2', ams_slot: 5, material: 'pla', weight_remaining_g: 200, status: 'loaded' }),   // AMS bound, материал «pla» == «PLA» после нормализации
  S({ id: 's1', material: 'ABS', weight_remaining_g: 1000 }),   // сток
  S({ id: 's2', material: 'ABS', weight_remaining_g: 800 }),    // сток, тот же материал ABS
  S({ id: 'sp', material: 'TPU', weight_remaining_g: 400, pending: true }),   // сток pending -> ИСКЛЮЧАЕТСЯ
  S({ id: 'se', material: 'PLA', weight_remaining_g: 0, status: 'empty' }),   // сток пустой -> ВКЛЮЧАЕТСЯ (не bound, не pending)
];

// work-режим
{
  const k = mkKpi(FIX, 'work');
  // WORK set = {be, ba, ba2}; kg=(500+300+200)/1000=1.0; типы={pla,petg}=2; count=3 (каждый spool один раз)
  check('W1. work: сводка по привязанным (external -1 + AMS >=0), каждый spool id один раз: катушек=3, кг=1.0, типов=2',
    k.total === 3 && k.kg === '1.0' && k.types === 2);
  // nav-счётчики: bound=3, stock=3 (те же множества)
  check('W2. nav-счётчики: kpi.bound=3 (привязанные), kpi.stock=3 (живые непривязанные без pending)',
    k.bound === 3 && k.stock === 3);
}
// stock-режим
{
  const k = mkKpi(FIX, 'stock');
  // STOCK set = {s1, s2, se} (sp pending исключён; se пустой включён); kg=(1000+800+0)/1000=1.8; типы={abs,pla}=2; count=3
  check('S1. stock: сводка по живым непривязанным без pending (пустые включены): катушек=3, кг=1.8, типов=2',
    k.total === 3 && k.kg === '1.8' && k.types === 2);
  check('S2. stock: pending-катушка исключена (иначе было бы 4); bound/stock те же (3/3)',
    k.total === 3 && k.bound === 3 && k.stock === 3);
}
// двойной счёт: be(external) и ba(AMS) — ОБА на P1; в per-printer представлении P1 = 2 катушки, но сводка
// считает из плоского spools.value -> ровно 3 привязанных (не 4+). Уберём ba2 -> P1 остаётся с 2 катушками.
{
  const twoOnP1 = FIX.filter((s) => s.ams_printer_id === 'P1');
  const k = mkKpi(twoOnP1, 'work');
  check('D1. двойного счёта нет: be(external -1) и ba(AMS0) на одном принтере P1 считаются как 2 РАЗНЫЕ катушки (не 1 и не 4): total=2',
    k.total === 2 && k.bound === 2 && twoOnP1.length === 2);
}
// filter-independence: kpi читает ТОЛЬКО spools.value (нет ссылок на q/fMat/fVendor/fLoc/fLow)
{
  const refsFilters = /kpi = computed[\s\S]*?\}\);/.exec(PANEL)[0];
  check('F1. сводка НЕ зависит от поиска/фильтров: тело kpi не ссылается на q/fMat/fVendor/fLoc/fLow',
    !/\b(q\.value|fMat\.value|fVendor\.value|fLoc\.value|fLow\.value)\b/.test(refsFilters));
}

console.log('\n' + (fail ? ('FAIL: ' + fail + ' проверок провалено') :
  'PASS: mode-специфичная сводка — work=привязанные (external -1 + AMS), stock=живые непривязанные без pending; каждый spool id один раз (нет двойного счёта); нормализованные типы; filter-independent; nav-счётчики = те же множества'));
process.exit(fail ? 1 : 0);
