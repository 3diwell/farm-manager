// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
// Настройки Dashboard хранятся в теме; прежние темы получают только недостающие поля.
export const DASHBOARD_DEFAULTS = {
  enabled:true, water:true, showModel:false, temperatureColors:true,
  showName:true, showPercent:true, showTime:true, showFile:true,
  showNozzle:true, showBed:true, showChamber:true, showStatus:true,
  showIndicators:true, showHint:true, showAddress:true, showProgressBar:true,
  percentSize:22, timeSize:22, waveHeight:3.5, wavePeriod:5, motion:true,
  blue:'#0058cc', green:'#00d684', idle:'#71839b', error:'#dc435a',
  pause:'#c69835', heating:'#f08b38', cooling:'#35b9e8'
};
const ranges = {percentSize:[13,30],timeSize:[16,32],waveHeight:[0,5],wavePeriod:[5,15]};
export function validateDashboard(value, errors) {
  for(const [key,base] of Object.entries(DASHBOARD_DEFAULTS)){
    const v=value[key];
    const ok=typeof base==='boolean'?typeof v==='boolean':
      typeof base==='string'?typeof v==='string'&&/^#[0-9a-f]{6}$/i.test(v):
      typeof v==='number'&&Number.isFinite(v)&&v>=ranges[key][0]&&v<=ranges[key][1];
    if(!ok)errors.push('dashboard.'+key);
  }
}
const field=(key,label,en,kind,extra={})=>({
  path:'dashboard.'+key,section:'dashboard',target:'dashboard',label,en,kind,
  help:'Оформление карточек в виде Dashboard.',helpEn:'Card appearance in Dashboard view.',
  ...extra
});
export const DASHBOARD_FIELDS = [
  field('enabled','Оформление Dashboard','Dashboard appearance','toggle'),
  field('showName','Показывать имя принтера','Show printer name','toggle',{group:'dash-content'}),
  field('showModel','Показывать модель принтера','Show printer model','toggle',{group:'dash-content'}),
  field('showPercent','Показывать процент печати','Show print percentage','toggle',{group:'dash-content'}),
  field('showTime','Показывать оставшееся время','Show remaining time','toggle',{group:'dash-content'}),
  field('showFile','Показывать имя файла печати','Show print file name','toggle',{group:'dash-content'}),
  field('showNozzle','Показывать температуру сопла','Show nozzle temperature','toggle',{group:'dash-content'}),
  field('showBed','Показывать температуру стола','Show bed temperature','toggle',{group:'dash-content'}),
  field('showChamber','Показывать температуру камеры','Show chamber temperature','toggle',{group:'dash-content'}),
  field('showStatus','Показывать текст состояния','Show status text','toggle',{group:'dash-content'}),
  field('showIndicators','Показывать значки состояния','Show status indicators','toggle',{group:'dash-content',help:'Точка состояния, предупреждения и значок очереди. Кнопки управления остаются доступны.',helpEn:'Status dot, warnings and queue indicator. Action buttons remain available.'}),
  field('showHint','Показывать подсказку после печати','Show post-print hint','toggle',{group:'dash-content',help:'Например, «Освободите стол». Кнопка подтверждения остаётся доступна.',helpEn:'For example, Clear the plate. The confirmation button remains available.'}),
  field('showAddress','Показывать IP-адрес','Show IP address','toggle',{group:'dash-content',help:'Адрес на карточке принтера без связи.',helpEn:'The address on an offline printer card.'}),
  field('showProgressBar','Показывать полосу прогресса','Show progress bar','toggle',{group:'dash-content',help:'Полоса видна при выключенном заполнении водой.',helpEn:'The bar is visible when water fill is off.'}),
  field('timeSize','Размер времени до завершения','Remaining time size','range',{min:16,max:32,step:1,unit:'px',help:'Увеличивает только время. Подпись «осталось» остаётся размером 14 px.',helpEn:'Enlarges the time only. The label stays at 14 px.'}),
  field('percentSize','Размер процента в углу','Corner percentage size','range',{min:13,max:30,step:1,unit:'px'}),
  field('water','Заполнение водой','Water progress fill','toggle',{group:'dash-water'}),
  field('blue','Вода в начале печати','Water at print start','color',{group:'dash-water'}),
  field('green','Вода в конце печати','Water at print end','color',{group:'dash-water'}),
  field('waveHeight','Высота волны','Wave height','range',{group:'dash-water',min:0,max:5,step:.5,unit:'px'}),
  field('wavePeriod','Период волны','Wave period','range',{group:'dash-water',min:5,max:15,step:1,unit:'s'}),
  field('motion','Движение воды','Water motion','toggle',{group:'dash-water'}),
  field('idle','Цвет простоя','Idle color','color',{group:'dash-status'}),
  field('error','Цвет ошибки','Error color','color',{group:'dash-status'}),
  field('pause','Цвет паузы','Pause color','color',{group:'dash-status'}),
  field('temperatureColors','Цвета изменения температуры','Temperature trend colors','toggle',{group:'dash-temp',help:'Стрелки ↑/↓ — нагрев и остывание по изменению показаний на 2° и больше. Включённый нагреватель подсвечен цветом нагрева, как без модуля.',helpEn:'Arrows ↑/↓ show heating and cooling by a change of 2° or more. A heater that is on keeps the heating colour, as without the module.'}),
  field('heating','Нагрев ↑','Heating ↑','color',{group:'dash-temp'}),
  field('cooling','Остывание ↓','Cooling ↓','color',{group:'dash-temp'})
];
