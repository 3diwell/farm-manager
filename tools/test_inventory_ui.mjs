// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
// Инварианты структуры и компоновки модуля «Складской учёт» (inventory 1.7.8).
// Регрессия A (1.6.10): второй launcher «Стоимость запасов» показывался ОТДЕЛЬНОЙ карточкой в
// менеджере модулей — «Стоимость запасов» должна быть только внутренней вкладкой InventoryPanel.
// «Склад → В работе» (1.7.7 → 1.7.8): ЕДИНАЯ компактная таблица всех принтеров (.fm-inv-ptable,
// строка = принтер, v-for="r in workRows") получила UI-polish: миниатюра принтера 52px
// (<img /covers/<model>_cover.png> по модели из публичного /api/printers; fallback — глобальный
// svg-icon printer в той же плашке) + имя + статус «точка+текст» второй строкой; внешняя катушка =
// полноценная slot-cell (SVG 50px, материал/цвет/остаток/% + progress-bar; пустая = вся
// ячейка-кнопка «+ Привязать»); AMS = вертикальные slot-cells с номером слота (занятый: мини-катушка
// + материал + %; пустой: «+»); честные состояния «Нет AMS» / «Нет внешней подачи» вместо «—»;
// sticky-заголовок; строки ~76-88px. Тумблер скрывает ТОЛЬКО полностью пустые принтеры.
// Проверки W1–W15 ниже; runtime-двойник — tools/test_inventory_workmode_runtime.mjs (R1–R15).
// Запуск: node tools/test_inventory_ui.mjs   (0 = все инварианты выполнены)
import { readFileSync } from 'fs';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const REPO = dirname(dirname(fileURLToPath(import.meta.url)));
const mj = JSON.parse(readFileSync(join(REPO, 'modules', 'inventory', 'module.json'), 'utf8'));
const panel = readFileSync(join(REPO, 'modules', 'inventory', 'web', 'InventoryPanel.js'), 'utf8');
const backend = readFileSync(join(REPO, 'modules', 'inventory', 'backend.py'), 'utf8');
const launchers = mj.launchers || [];
const names = launchers.map((l) => String(l.ru || '').trim());
const tmpl = (panel.match(/template:\s*`([\s\S]*)`/) || [null, ''])[1];   // только Vue-шаблон (без CARD_CSS)

let fail = 0;
const check = (name, cond) => { console.log((cond ? 'PASS' : 'FAIL') + ' — ' + name); if (!cond) fail++; };

// 1. Нет отдельного launcher «Стоимость запасов»
check('1. в module.json НЕТ launcher «Стоимость запасов» (и нет startTab:"cost" в launchers)',
  !names.includes('Стоимость запасов') && !launchers.some((l) => (l.props || {}).startTab === 'cost'));

// 2. Основной launcher «Складской учёт» — ровно один
check('2. launcher «Складской учёт» присутствует ровно один раз',
  names.filter((n) => n === 'Складской учёт').length === 1 && launchers.length === 1);

// 3. Вкладка «Стоимость запасов» ОСТАЁТСЯ внутри InventoryPanel
check('3. в InventoryPanel сохранена вкладка стоимости (tab==="cost", подпись «Стоимость запасов»)',
  /tab==='cost'|tab === 'cost'|:class=.*cost/.test(panel) && panel.includes("tab==='cost'")
  && panel.includes("'Стоимость запасов','Stock value'"));

// 4. API /api/mod/inventory/cost не удалён (роут "cost" в backend)
check('4. роут стоимости не удалён (core.add_route("cost", ...) в backend)',
  /core\.add_route\(\s*["']cost["']/.test(backend));

// 5. Остальные вкладки inventory сохранены
check('5. остальные вкладки сохранены (Склад/Запчасти/Локации + Стоимость запасов)',
  ["tab==='warehouse'", "tab==='parts'", "tab==='locations'", "tab==='cost'"].every((t) => panel.includes(t)));

// 6. Версия поднята до 1.7.9 (фикс просвета над sticky-шапкой «В работе»)
// Alpha 2.795: semver-порог вместо хрупкого точного пина (точный пин краснел после каждого патча).
const verGE = (a, b) => { const pa = String(a).split('.').map(Number), pb = b.split('.').map(Number); for (let i = 0; i < 3; i++) { if ((pa[i] || 0) !== (pb[i] || 0)) return (pa[i] || 0) > (pb[i] || 0); } return true; };
check('6. версия inventory валидна (semver) и не ниже 1.7.24', /^\d+\.\d+\.\d+$/.test(mj.version) && verGE(mj.version, '1.7.24'));

// ── Компоновка «Склад → В работе» (1.7.8): отполированная ЕДИНАЯ таблица всех принтеров ──
const cssRule = (sel) => {
  const m = panel.match(new RegExp("'" + sel.replace(/[.]/g, '\\.') + '\\{([^}]*)\\}'));
  return m ? m[1] : '';
};
const prow = cssRule('.fm-inv-prow');
const prowH = cssRule('.fm-inv-prow-h');

// W1. «В работе» = ОДНА таблица .fm-inv-ptable по workRows (строка = принтер)
check('W1. таблица .fm-inv-ptable = сгруппированные СЕКЦИИ (1.7.10): v-for="sec in workSections" + заголовок .fm-inv-psec-h + строки v-for="r in sec.rows"',
  tmpl.includes('class="fm-inv-ptable"')
  && tmpl.includes('<div v-for="sec in workSections" :key="sec.key" class="fm-inv-psec">')
  && tmpl.includes('<div class="fm-inv-psec-h"><span class="fm-inv-psec-t">{{ sec.title }}</span><span class="fm-inv-psec-c">{{ sec.count }}</span></div>')
  // строка-принтер: v-for/:key/класс проверяем по СОСТАВУ тега, а не дословной строкой — иначе любой
  // аддитивный атрибут (1.7.22: :data-recpid + подсветка наведённого принтера) ломает тест на ровном месте
  && /<div v-for="r in sec\.rows"[^>]*:key="r\.p\.printer_id"[^>]*class="fm-inv-prow"/.test(tmpl));
// W2. Старой карточной сетки, секции пустых и generic-иконки принтера НЕТ в разметке
check('W2. в шаблоне нет карточной сетки (workSlots/fm-inv-workgrid), секции пустых (amsEmpty/fm-inv-empties) и generic-иконки (svg-icon printer w-4 h-4)',
  !tmpl.includes('v-for="c in workSlots"') && !tmpl.includes('fm-inv-workgrid')
  && !tmpl.includes('v-for="p in amsEmpty"') && !tmpl.includes('fm-inv-empties')
  && !tmpl.includes('<svg-icon name="printer" class="w-4 h-4">') && !tmpl.includes('fm-inv-pdash'));
// W3. Колонка принтера: миниатюра 52px (img по модели / fallback svg-icon) + имя + статус второй строкой
check('W3. .fm-inv-pimg 52px: приоритет <img :src="r.cover"> → klipper-силуэт → generic svg-icon; URL из model не строим; имя .fm-inv-pname2 + статус .fm-inv-pst в .fm-inv-pcol-t',
  /\.fm-inv-pimg\{[^}]*width:52px;height:52px/.test(panel)
  && tmpl.includes('<img v-if="r.cover && !coverBroken[r.cover]" :src="r.cover"')
  && tmpl.includes('@error="coverBroken[r.cover] = true"')
  && tmpl.includes('<span v-else-if="r.kl && klipperSvg" class="fm-inv-pimg-kl" v-html="klipperSvg"></span>')
  && tmpl.includes('<svg-icon v-else name="printer"></svg-icon>')
  && !tmpl.includes('coverUrl(r.model)')
  && tmpl.includes('class="fm-inv-pcol-t"><span class="fm-inv-pname2"')
  && tmpl.includes('<span class="fm-inv-pst" :class="r.st.k"><i></i><span>{{ r.st.t }}</span></span>'));
// W4. Подсказки позиций (workSlotTitle): внешняя / «AMS · слот N» (+офлайн) и подсказка привязки
//  16.10.2026 (склад, R-137): подпись внешней позиции — extName (левая/правая у H2D, иначе «Внешняя катушка»).
check('W4. workSlotTitle: «Внешняя катушка» (левая/правая у H2D) / «AMS · слот N» (+офлайн) и подсказка привязки для пустых',
  panel.includes("sl.external ? extName(sl) : ('AMS · ' + L('слот', 'slot') + ' ' + (sl.index + 1))")
  && panel.includes("L('Внешняя катушка', 'External spool')") && panel.includes("L('Левая внешняя катушка', 'Left external spool')")
  && panel.includes("L('нажмите, чтобы привязать катушку со склада', 'click to bind a spool from stock')"));
// W5. workRows из workPrinters (ВСЕ принтеры); тумблер фильтрует ТОЛЬКО полностью пустые; экспорт
check('W5. workPrinters: _amsSearched + filter(printerOcc); workEmptyCount = полностью пустые; workRows/coverBroken экспортированы (coverUrl удалён)',
  /const workPrinters = computed\(\(\) => \{[\s\S]*?_amsSearched\.value/.test(panel)
  && panel.includes('arr = arr.filter(printerOcc)')
  && panel.includes('const workEmptyCount = computed(() => _amsSearched.value.filter((p) => !printerOcc(p)).length)')
  && /return \{[\s\S]*?workRows, workSections, unitLabel, slotLocalN, klipperSvg, printerTypeById, workSlotTitle, matCheckView, matCheckTip, workEmptyCount, coverBroken[,}]/.test(panel)
  && !/coverUrl/.test(panel));
// W6. Занятая внешняя = полноценная slot-cell: SVG 50px + материал/цвет/остаток/% + progress-bar
check('W6. занятая внешняя: .fm-inv-pext-svg 50px + .fm-inv-pext-m (материал) + .fm-inv-pext-c (цвет·vendor) + .fm-inv-pext-g (г·%) + .fm-inv-pext-bar',
  /\.fm-inv-pext-svg\{[^}]*width:50px/.test(panel)
  && tmpl.includes('class="fm-inv-pext-svg" v-html="spoolSvg(slotFull(r.ext) || r.ext.spool)"')
  && tmpl.includes('class="fm-inv-pext-m"') && tmpl.includes('class="fm-inv-pext-c"')
  && tmpl.includes('pct(r.ext.spool)')
  && tmpl.includes('<span class="fm-inv-pext-bar"><span :style="{width: pct(r.ext.spool) + \'%\''));
// W7. Пустые позиции: НАСТОЯЩАЯ external = ВСЯ ячейка-кнопка «+ Привязать» с подписью «Внешняя»
//     (пунктир) -> ПРЯМОЙ bind её index; пустой AMS-слот = «+» -> bind этого слота
check('W7. пустая external: .fm-inv-pfree «+ Привязать внешняя» + подпись «Внешняя подача» -> openBindFor(r.p, r.ext.index); пустой AMS: .fm-inv-pslot.add «+» -> openBindFor(r.p, sl.index)',
  tmpl.includes('<button v-else-if="r.ext" class="fm-inv-pfree"')
  && tmpl.includes("<b>+</b><span>{{ L('Привязать внешняя','Bind external') }}</span></span><span class=\"fm-inv-pfree-s\">{{ r.extL ? L('Правая внешняя','Right external') : L('Внешняя подача','External feed') }}</span>")
  && tmpl.includes('openBindFor(r.p, r.ext.index)')
  && /\.fm-inv-pfree\{[^}]*border:1px dashed/.test(panel) && /\.fm-inv-pfree\{[^}]*width:100%/.test(panel)
  && tmpl.includes('sl.spool ? onSlotClick(sl) : openBindFor(r.p, sl.index)')
  && tmpl.includes('<span v-else class="fm-inv-pslot-plus">+</span>'));
// W8. Обработчики позиций живы (клик/ПКМ); «Отвязать»/«Заменить»(bound+low) — в spoolMenu (ПКМ),
//     кнопки строки «⋯» нет. Alpha 2.795: с 2.793 пункты меню гейтятся правом project (cProj) —
//     «Заменить» теперь `bound && cProj && isLowSpool(s)`, что тест и проверяет (контракт не ослаблен).
check('W8. onSlotClick(r.ext)/onSlotMenu; spoolMenu: Отвязать + Заменить(bound && cProj && isLowSpool -> replaceSpool); строки «⋯»/workRowMenu нет',
  tmpl.includes('@click="onSlotClick(r.ext)"') && tmpl.includes('onSlotMenu($event, r.ext)')
  && tmpl.includes('sl.spool ? onSlotMenu($event, sl) : null')
  && /const spoolMenu = \(e, s\) =>[\s\S]*?openUnbind\(s\)[\s\S]*?bound && cProj && isLowSpool\(s\)[\s\S]*?replaceSpool\(s\)/.test(panel)
  && !tmpl.includes('workRowMenu($event, r)') && !panel.includes('const workRowMenu'));
// W9. Пропорции/адаптив: grid по ТЗ (принтер 190-220, внешняя 232-282, AMS 1fr) помещается в панель
//     1180px (полезная ширина body = 1180 - 2*20 padding = 1140): сумма минимумов + gaps ≤ 1140;
//     чипы AMS переносятся (flex-wrap); media 980/700 прячут только второстепенное (прогноз, остаток)
{
  const gridM = prow.match(/grid-template-columns:([^;]+)/);
  let minSum = 0, ok = false;
  if (gridM) {
    const mins = [...gridM[1].matchAll(/minmax\((\d+)px,[^)]+\)|(\d+)px/g)].map((m) => +(m[1] || m[2] || 0));
    const gap = +(prow.match(/gap:(\d+)px/) || [0, 0])[1];
    minSum = mins.reduce((a, b) => a + b, 0) + gap * Math.max(0, mins.length - 1);
    ok = mins.length === 5 && minSum > 0 && minSum <= 1140;
  }
  check('W9. grid 5 колонок (без «⋯»-колонки), сумма минимумов+gaps = ' + minSum + 'px ≤ 1140; .fm-inv-pams flex-wrap; media 980/700',
    ok && /minmax\(190px,220px\) minmax\(232px,282px\) minmax\(210px,1fr\)/.test(prow)
    && /\.fm-inv-pams\{[^}]*flex-wrap:wrap/.test(panel)
    && /@media \(max-width:980px\)\{\.fm-inv-prow\{grid-template-columns/.test(panel)
    && /@media \(max-width:700px\)\{\.fm-inv-prow\{grid-template-columns/.test(panel)
    && /\.fm-inv-pfc\{display:none\}/.test(panel) && /\.fm-inv-prem\{display:none\}/.test(panel));
}
// W10. 1.7.18: KPI разделены (навигация-кнопки + инфо-сводка plain); toolbar «В работе» без «Добавить катушку»/«Скрыть пустые»/счётчика; «На складе» цел
check('W10. KPI = навигация (.fm-inv-nav, кнопки wmode) + инфо-сводка (.fm-inv-sum: 3 plain div, cursor:default, без button/@click); «В работе» toolbar только поиск; «Добавить катушку» РОВНО одна (в «На складе»); тумблер пустых удалён; счётчика «катушек в работе» нет',
  panel.includes("wmode==='work'") && panel.includes("wmode==='stock'")
  && tmpl.includes('class="fm-inv-nav"') && (tmpl.match(/class="fm-inv-sum-i"><b>/g) || []).length === 3
  && cssRule('.fm-inv-sum') && /\.fm-inv-sum\{[^}]*cursor:default/.test(panel)
  && !panel.includes('showEmptyPrinters=!showEmptyPrinters') && !panel.includes('v-if="workEmptyCount"')
  && !tmpl.includes("L('катушек в работе','spools in use')")
  && tmpl.includes('<div class="fm-inv-toolbar"><input v-model="q" class="fm-inv-search" style="margin-left:auto" :placeholder="L(\'Поиск: материал, цвет, принтер…')
  && (tmpl.match(/@click="openAdd\(\)"/g) || []).length === 1);
// W11. Сводные колонки: остаток всего (printerBoundG/N), прогноз (мин. days_left); статусы Пусто/Мало/Готов
check('W11. сводные: remainG/boundN + workDaysLeft (fcMap, days_left) + workStatus (Пусто/Мало остатка/Готов)',
  panel.includes('remainG: printerBoundG(p), boundN: printerBoundN(p)')
  && /const workDaysLeft = \(p\) =>[\s\S]*?days_left/.test(panel)
  && panel.includes("L('Мало остатка', 'Low filament')") && panel.includes("L('Готов', 'Ready')"));
// W12. AMS slot-cells: номер слота + мини-катушка + материал + %; группировка по AMS unit без хардкода
check('W12. slot-cell AMS: ЛОКАЛЬНЫЙ номер slotLocalN (не глобальный index) + мини-катушка + материал + pct; unit-группы .fm-inv-punit2 с заголовком unitLabel (A1/A2/AMS HT)',
  tmpl.includes('<span class="fm-inv-pslot-n">{{ slotLocalN(sl) }}</span>')
  && !tmpl.includes('{{ sl.index + 1 }}')
  && tmpl.includes('class="fm-inv-pslot-svg" v-html="spoolSvg(slotFull(sl) || sl.spool)"')
  && tmpl.includes('{{ sl.spool.material || \'—\' }}') && tmpl.includes('pct(sl.spool)')
  && panel.includes('const workAmsUnits = (p) => slotUnits({ slots: (p.slots || []).filter((sl) => !sl.external && !sl.unconfirmed) })')
  && tmpl.includes('class="fm-inv-punit2-l">{{ unitLabel(u) }}')
  && panel.includes("? 'AMS HT' : ('A' + u.n)"));
// W12b. 1.7.20 safety: неоднозначная позиция слота 0 (offline/stale) — НЕЙТРАЛЬНЫЙ read-only чип .fm-inv-punc
//       («Не подтверждено»), БЕЗ действий (нет @click/@contextmenu); исключена из external и из AMS-юнитов.
{
  const punc = (tmpl.match(/<span v-for="sl in r\.unconfirmed"[\s\S]*?<\/span><span v-if="!r\.units\.length/) || [''])[0];
  check('W12b. unconfirmed-позиция: .fm-inv-punc read-only (нет @click/@contextmenu/openBindFor/onSlotMenu), «Не подтверждено»; workUnconfirmed определён; external и AMS-юниты её исключают',
    /<span v-for="sl in r\.unconfirmed" :key="'unc'\+sl\.index" class="fm-inv-punc"/.test(tmpl)
    && punc.includes("{{ L('Не подтверждено','Unconfirmed') }}")
    && !/r\.unconfirmed[\s\S]*?(@click|@contextmenu|openBindFor|onSlotMenu|onSlotClick)/.test(punc)
    && panel.includes('const workUnconfirmed = (p) => (p.slots || []).filter((sl) => sl.unconfirmed && sl.spool)')
    && /const workExternal = \(p\) => \{ for \(const sl of \(p\.slots \|\| \[\]\)\) if \(sl\.external && sl\.ext_side !== 'left'\) return sl;/.test(panel)
    && /\.fm-inv-punc\{[^}]*cursor:default/.test(panel));
}
// W13. 1.7.20: все принтеры видны по умолчанию; кнопка строки «⋯» УДАЛЕНА (действия — ПКМ по катушке/«+» ячейки)
check('W13. showEmptyPrinters = ref(true) по умолчанию; кнопки «⋯» строки нет (.fm-inv-gmore в work-строке отсутствует)',
  /const showEmptyPrinters = ref\(true\)/.test(panel)
  && !tmpl.includes('@click.stop="workRowMenu($event, r)"'));
// W14. 1.7.20: колонка «Катушка» = ВСЕГДА external-позиция (backend отдаёт её всем принтерам, index=-1).
//      A) занятая external — подпись «Внешняя»; B) пустая external — «+ Привязать внешняя» -> ПРЯМОЙ
//      openBindFor(r.p, r.ext.index) (external=-1). Универсал «Выбрать позицию»/openBindFor(p,null) и
//      «Все позиции заняты» УБРАНЫ. «Нет внешней подачи» отсутствует; «Нет AMS» есть; hover/sticky.
check('W14. колонка «Катушка»: A(занятая «Внешняя»)/B(«+ Привязать внешняя» -> openBindFor(r.p, r.ext.index)); универсал (Выбрать позицию/openBindFor(p,null)/«Все позиции заняты») убран; «Нет подачи» есть; border/hover/sticky',
  tmpl.includes("<span>{{ L('Катушка','Spool') }}</span>")
  && tmpl.includes('class="fm-inv-pext-k">{{ r.extL ? L(\'Внешняя · правая\',\'External · right\') : L(\'Внешняя\',\'External\') }}</span>')
  && tmpl.includes('<button v-else-if="r.ext" class="fm-inv-pfree"') && tmpl.includes('openBindFor(r.p, r.ext.index)')
  && tmpl.includes("{{ L('Привязать внешняя','Bind external') }}")
  && !tmpl.includes('r.hasFree') && !tmpl.includes('openBindFor(r.p, null)')
  && !tmpl.includes("{{ L('Выбрать позицию','Pick a position') }}")
  && !tmpl.includes("{{ L('Все позиции заняты','All positions occupied') }}")
  && tmpl.includes("L('Нет подачи','No feeder')") && !tmpl.includes('Нет внешней подачи')   // 1.7.26: подпись нейтральна к AMS/CFS
  && /\.fm-inv-pnone\{/.test(panel)
  && /border-bottom:1px solid var\(--fm-border-soft\)/.test(prow)
  && /\.fm-inv-prow:hover\{background:rgba\(var\(--fm-accent-rgb\),\.04\)\}/.test(panel)
  && /position:sticky/.test(prowH) && /background:var\(--fm-surface-raised\)/.test(prowH));
// W15. Источник миниатюр безопасный: публичный /api/printers + /covers/<model>_cover.png (как modelCover
//      ядра), fallback coverBroken; БЕЗ интернета и БЕЗ base64
check('W15. модели/обложки из публичного /api/printers (fail-open load); cover_url приходит готовым из ядра (URL из model НЕ строим); без http(s)-URL и base64-картинок',
  panel.includes("_loadSection('/api/printers'")
  && panel.includes("cu[p.id] = p.cover_url || ''")
  && !panel.includes("const coverUrl = (model) =>")
  && panel.includes('const coverBroken = reactive({})')
  && !tmpl.includes('coverUrl(r.model)') && !tmpl.includes('data:image'));

console.log('\n' + (fail ? ('FAIL: ' + fail + ' инвариантов провалено') : 'PASS: структура и компоновка модуля склада — все инварианты выполнены'));
process.exit(fail ? 1 : 0);
