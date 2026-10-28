// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
import { FIELDS as ORIGINAL_FIELDS } from './editor-fields.js';

// UI-only organization. Theme paths, defaults and storage formats remain unchanged.
export const SECTIONS = [
  {id:'dashboard',ru:'Dashboard',en:'Dashboard',help:'Вода, процент в углу, время и температуры принтеров.',helpEn:'Water, corner percentage, remaining time and printer temperatures.'},
  {id:'themes',ru:'Темы',en:'Themes',help:'Выберите основу или сохраните собственный вариант.',helpEn:'Choose a starting point or save your own variation.'},
  {id:'colors',ru:'Цвета и текст',en:'Colors and text',help:'Главный цвет, удобный размер текста и расстояния.',helpEn:'Your accent color, comfortable text size and spacing.'},
  {id:'background',ru:'Фон',en:'Background',help:'Цвет или изображение. Живой фон можно добавить поверх.',helpEn:'A color or image. Animated effects can be layered on top.'},
  {id:'panels',ru:'Карточки и эффекты',en:'Cards and effects',help:'Материал, форма и аккуратные световые акценты.',helpEn:'Materials, shapes and subtle light accents.'}
];
export const GROUPS = [
  {id:'dash-content',section:'dashboard',ru:'Содержимое карточки',en:'Card contents'},
  {id:'dash-water',section:'dashboard',ru:'Вода и движение',en:'Water and motion'},
  {id:'dash-status',section:'dashboard',ru:'Цвета состояний',en:'State colors'},
  {id:'dash-temp',section:'dashboard',ru:'Температуры',en:'Temperatures'},
  {id:'surfaces',section:'colors',ru:'Цвета поверхностей и текста',en:'Surface and text colors'},
  {id:'accents',section:'colors',ru:'Статусы, рамки и верхняя панель',en:'Status, borders and header'},
  {id:'fonts',section:'colors',ru:'Шрифт и точная типографика',en:'Font and precise typography'},
  {id:'image',section:'background',ru:'Настройки изображения',en:'Image settings'},
  {id:'live-colors',section:'background',ru:'Цвета живого фона',en:'Animated background colors'},
  {id:'live-shape',section:'background',ru:'Форма и смешивание эффектов',en:'Shape and effect mixing'},
  {id:'pattern',section:'background',ru:'Статичный узор',en:'Static pattern'},
  {id:'motion',section:'background',ru:'Движение и нагрузка',en:'Motion and workload'},
  {id:'material',section:'panels',ru:'Материал и стекло',en:'Material and glass'},
  {id:'shape',section:'panels',ru:'Форма и границы',en:'Shape and borders'},
  {id:'shadows',section:'panels',ru:'Тени и глубина',en:'Shadows and depth'},
  {id:'glow',section:'panels',ru:'Свечение и подсветка',en:'Glow and lighting'},
  {id:'hover',section:'panels',ru:'Блики при наведении',en:'Hover glints'},
  {id:'controls',section:'panels',ru:'Кнопки, таблицы и прогресс',en:'Buttons, tables and progress'}
];
const primary = new Set(['palette.accent','typography.textScale','interface.density','interface.highContrast','background.mode','live','effects.backgroundFlowOpacity','effects.backgroundFlowSpeed','effects.panelMaterial','effects.cornerStyle','effects.edgeLighting']);
const groups = {
  image:['background.overlay','background.overlayOpacity','background.blurPx'],
  'live-colors':['effects.backgroundFlowUseThemeColors','effects.backgroundFlowPrimary','effects.backgroundFlowSecondary'],
  'live-shape':['effects.backgroundFlowScale','effects.backgroundFlowBlur','effects.backgroundStreamCount','effects.backgroundMixedStyle','effects.backgroundFlowMix','effects.backgroundStreamsMix','effects.ambientStrength'],
  pattern:['effects.backgroundPattern','effects.patternOpacity'],
  motion:['interface.reduceMotion','interface.performanceMode'],
  material:['shape.surfaceOpacity','effects.matteStrength','effects.glossStrength','effects.glassRefraction','effects.glassBlur','effects.glassEdge'],
  shape:['shape.radiusScale','shape.borderWidth','shape.independentRadii','shape.buttonRadius','shape.inputRadius','shape.cardRadius'],
  shadows:['shape.shadowIntensity','effects.panelDepth','effects.panelAiriness'],
  glow:['effects.glowStrength','effects.haloStrength','effects.edgeDirection','effects.panelTopHighlight'],
  hover:['effects.hoverGlintPrinters','effects.hoverGlintProjects','effects.hoverGlintIntensity','effects.hoverGlintDuration','effects.hoverLift'],
  controls:['effects.tableStyle','effects.statusStyle','effects.progressStyle','effects.controlStyle','effects.focusGlowStrength','effects.microAccentIntensity','effects.shimmerProgress']
};
export const FIELDS = ORIGINAL_FIELDS.map(f=>{
  if(f.section==='dashboard')return {...f,group:f.group||'',advanced:!!f.group};
  let section=f.section==='text'?'colors':f.section,group='';
  if(!primary.has(f.path)){
    group=Object.keys(groups).find(id=>groups[id].includes(f.path));
    if(!group&&f.path.startsWith('typography.'))group='fonts';
    if(!group&&f.section==='colors')group=/^palette\.(surface|text)/.test(f.path)?'surfaces':'accents';
    if(!group)throw new Error('Unmapped appearance field: '+f.path);
    section=GROUPS.find(g=>g.id===group).section;
  }
  return {...f,section,group,advanced:!!group};
});

export function fieldSummary(f,value,lang='ru'){
  const L=(ru,en)=>lang==='ru'?ru:en;
  if(f.kind==='toggle')return value?L('вкл.','on'):L('выкл.','off');
  if(f.kind==='select'){const o=f.options.find(o=>o.value===value);return o?L(o.ru,o.en):String(value);}
  if(f.kind==='range')return f.unit==='px'?`${value} px`:f.unit==='s'?`${value} ${L('с','s')}`:f.unit==='count'?String(value):`${Math.round(Number(value)*100)}%`;
  return String(value);
}
