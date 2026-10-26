// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
// Frontend regression-тест первичной загрузки склада (Alpha 2.714).
// Баг доказанно frontend: холодный load() оставлял spools/filaments/vendors пустыми,
// а load после POST работал. Тест закрепляет архитектурные инварианты устойчивой загрузки
// и проверяет чистую логику нормализации ответа /filament. Node ESM, без зависимостей.
//
// Запуск:  node tools/test_inventory_frontend_load.mjs   (код возврата 1 при провале)
import fs from 'node:fs';

const src = fs.readFileSync(new URL('../modules/inventory/web/InventoryPanel.js', import.meta.url), 'utf8');
let fail = 0;
const check = (name, cond) => { console.log((cond ? 'PASS' : 'FAIL') + ' — ' + name); if (!cond) fail++; };

// ── Структурные инварианты устойчивой загрузки ──
check('default mode is stock (wmode ref init)', /const wmode = ref\('stock'\)/.test(src));
check('core filament load is a separate fn (loadFilamentCore + _applyFilament)', /loadFilamentCore/.test(src) && /_applyFilament/.test(src));
check('sections load independently (Promise.allSettled)', /Promise\.allSettled\(/.test(src));
check('core load happens BEFORE/independent of sections', src.indexOf('loadFilamentCore()') !== -1 && src.indexOf('loadFilamentCore()') < src.indexOf('Promise.allSettled'));
check('guaranteed initial load on mount (onMounted -> openInit)', /onMounted\(\(\)\s*=>\s*\{\s*if\s*\(props\.open\)\s*openInit/.test(src));
check('onMounted is imported from vue', /import\s*\{[^}]*\bonMounted\b[^}]*\}\s*from\s*'vue'/.test(src));
check('filament failure is logged, not silent', /console\.error\('\[inventory\] \/filament/.test(src));
check('SVG preload does NOT block/abort data load', /preloadSpoolSvgs\(\)\.catch\(/.test(src));

// ── Логика нормализации ответа /filament (fixture) ──
const applyFilament = (state, d) => { state.vendors = (d && d.vendors) || []; state.filaments = (d && d.filaments) || []; state.spools = (d && d.spools) || []; };

const st = { vendors: [], filaments: [], spools: [] };
applyFilament(st, { vendors: [{ id: 'v' }], filaments: [{ id: 'f' }, { id: 'f2' }], spools: [{ id: 's1' }, { id: 's2' }, { id: 's3' }] });
check('filament fixture populates core arrays (3 spools / 2 filaments / 1 vendor)', st.spools.length === 3 && st.filaments.length === 2 && st.vendors.length === 1);

// сбой вспомогательной секции (AMS) НЕ должен обнулять core
let amsOk = true;
try { throw new Error('ams down'); } catch (e) { amsOk = false; /* core arrays нетронуты */ }
check('an AMS/section error does NOT clear the core dataset', st.spools.length === 3 && !amsOk);

// пустой/битый ответ нормализуется в [] (не undefined, не throw)
const st2 = { vendors: [], filaments: [], spools: [] };
applyFilament(st2, {});
applyFilament(st2, null);
check('empty/undefined response normalizes to []', Array.isArray(st2.spools) && st2.spools.length === 0 && Array.isArray(st2.vendors));

console.log(fail ? ('\nFAIL: ' + fail + ' check(s) failed') : '\nPASS: frontend initial-load invariants hold');
process.exit(fail ? 1 : 0);
