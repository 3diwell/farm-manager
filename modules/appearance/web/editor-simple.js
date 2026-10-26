// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
import { resolveProfile } from './theme-profiles.js';
import DEFAULT_THEME from './default-theme.js';
import IPHONE_THEME from './iphone-theme.js';
import { cloneTheme, mergeWithDefaults } from './theme-validator.js';
import { fieldValue, setFieldValue } from './editor-fields.js';
export const SIMPLE_ACCENTS=['#508cf0','#9e7aef','#40b79b','#ed9a54'];
export const SIMPLE_TEXT_SIZES=[{value:1,ru:'Обычный',en:'Normal'},{value:1.28,ru:'Крупный',en:'Large'},{value:1.45,ru:'Очень крупный',en:'Extra large'}];
export const SIMPLE_COLOR_PAIRS=[{id:'blue',ru:'Синий и фиолетовый',en:'Blue and purple',colors:['#508cf0','#9858df']},{id:'sea',ru:'Бирюзовый и синий',en:'Teal and blue',colors:['#40b79b','#508cf0']},{id:'warm',ru:'Янтарный и розовый',en:'Amber and rose',colors:['#ed9a54','#d76f9c']}];
export function builtinThemes(installed){
 const ambient=mergeWithDefaults(installed);Object.assign(ambient.effects,{animatedBackground:'subtle',backgroundAnimationStyle:'fluid'});
 const calm=cloneTheme(ambient);calm.meta.name='Спокойная';calm.meta.nameEn='Calm';Object.assign(calm.effects,{animatedBackground:'off',glowStrength:.12,haloStrength:.08,hoverGlintPrinters:false,hoverGlintProjects:false});
 const contrast=cloneTheme(DEFAULT_THEME);contrast.meta.name='Контрастная';contrast.meta.nameEn='Contrast';contrast.interface.highContrast=true;contrast.effects.panelMaterial='solid';contrast.effects.animatedBackground='off';
 return [{id:'ambient',ru:'С живым фоном',en:'Ambient',theme:ambient},{id:'calm',ru:'Спокойная',en:'Calm',theme:calm},{id:'contrast',ru:'Контрастная',en:'Contrast',theme:contrast},{id:'iphone',ru:'Ясная',en:'Clear',theme:cloneTheme(IPHONE_THEME)}];
}
export function simpleValues(theme,mode){
 const e=resolveProfile(theme,mode).effects;
 const pair=e.backgroundFlowUseThemeColors?'auto':SIMPLE_COLOR_PAIRS.find(p=>p.colors[0].toLowerCase()===e.backgroundFlowPrimary.toLowerCase()&&p.colors[1].toLowerCase()===e.backgroundFlowSecondary.toLowerCase())?.id||'custom';
 return {accent:theme[mode].accent,background:e.animatedBackground==='off'?'off':e.backgroundAnimationStyle,pair,brightness:fieldValue(theme,'effects.backgroundFlowOpacity',mode),textSize:SIMPLE_TEXT_SIZES.some(s=>s.value===theme.typography.textScale)?String(theme.typography.textScale):'custom',glint:e.hoverGlintPrinters&&e.hoverGlintProjects,glintMixed:e.hoverGlintPrinters!==e.hoverGlintProjects};
}
// All setters touch only the chosen setting. Hidden advanced values are preserved.
export function setSimpleValue(theme,key,value,mode){
 const e=theme.effects;
 if(key==='accent'&&/^#[a-f0-9]{6}$/i.test(value)){theme[mode].accent=value;return true;}
 if(key==='background'&&['off','flow','fluid','aurora','mist','streams','mixed'].includes(value)){
  if(value==='off')e.animatedBackground='off';else {if(e.animatedBackground==='off')e.animatedBackground='subtle';e.backgroundAnimationStyle=value;}return true;
 }
 if(key==='pair'){
  if(value==='auto'){setFieldValue(theme,'effects.backgroundFlowUseThemeColors',mode,true);return true;}
  const p=SIMPLE_COLOR_PAIRS.find(p=>p.id===value);if(!p)return false;
  for(const [key,v] of Object.entries({backgroundFlowUseThemeColors:false,backgroundFlowPrimary:p.colors[0],backgroundFlowSecondary:p.colors[1]}))setFieldValue(theme,'effects.'+key,mode,v);return true;
 }
 if(key==='brightness'&&Number.isFinite(value)&&value>=0&&value<=1){setFieldValue(theme,'effects.backgroundFlowOpacity',mode,value);return true;}
 if(key==='textSize'&&SIMPLE_TEXT_SIZES.some(s=>s.value===Number(value))){theme.typography.textScale=Number(value);return true;}
 if(key==='glint'&&typeof value==='boolean'){e.hoverGlintPrinters=value;e.hoverGlintProjects=value;return true;}
 return false;
}
