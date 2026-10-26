// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
import DEFAULT_THEME from './default-theme.js';
import IPHONE_THEME from './iphone-theme.js';
import { cloneTheme, mergeWithDefaults } from './theme-validator.js';
import { separateProfiles, resolveProfile } from './theme-profiles.js';

// Stable starting points: never inherit the user's installed or exported theme.
function base(name,nameEn){
  const t=mergeWithDefaults(DEFAULT_THEME);
  Object.assign(t.meta,{name,nameEn,author:'3DIWELL',description:'',descriptionEn:''});
  t.typography.textScale=1.1;
  Object.assign(t.shape,{radiusScale:1.2,shadowIntensity:.22,surfaceOpacity:1});
  Object.assign(t.effects,{animatedBackground:'off',edgeLighting:'off',glowStrength:0,haloStrength:0,panelDepth:.08,panelAiriness:.08,glossStrength:0,matteStrength:.15,panelTopHighlight:false,hoverGlintPrinters:false,hoverGlintProjects:false,focusGlowStrength:.12,microAccentIntensity:.06});
  Object.assign(t.light,{headerSurface:'#ffffff',headerAction:'#edf0f4',headerBorder:'#d4d8de'});
  return t;
}
export function curatedThemes(){
  const calm=base('Тихая','Quiet');
  Object.assign(calm.dark,{accent:'#65bba7',surfaceDeep:'#101715',surfaceBase:'#17201d',surfaceCard:'#202b27',surfaceControl:'#28352f',borderSoft:'#2b3932',border:'#3d5046',headerSurface:'#1a2520',headerAction:'#26352d',headerBorder:'#34483d'});
  Object.assign(calm.light,{accent:'#247d67',surfaceDeep:'#eaf0eb',surfaceBase:'#f3f6f2',surfaceCard:'#fbfdf9',surfaceControl:'#f0f5ed',borderSoft:'#e0e8dc',border:'#c9d6c4',headerSurface:'#f7faf4',headerAction:'#e5eee1',headerBorder:'#c9d6c4'});
  calm.effects.secondaryAccent='#87b398';
  const glow=base('Сияние','Aurora');
  Object.assign(glow.dark,{accent:'#a294fa',surfaceDeep:'#10121d',surfaceBase:'#181b2b',surfaceCard:'#22263a',surfaceControl:'#2b3047',borderSoft:'#31374e',border:'#454d6c',headerSurface:'#1b2031',headerAction:'#29324b',headerBorder:'#3d4967'});
  Object.assign(glow.light,{accent:'#6954c7',surfaceDeep:'#e9eaf4',surfaceBase:'#f0f0f8',surfaceCard:'#fafaff',surfaceControl:'#ededf8',borderSoft:'#e0e0ee',border:'#cccde3',headerSurface:'#f6f5fc',headerAction:'#e8e5f5',headerBorder:'#cccde3'});
  Object.assign(glow.effects,{secondaryAccent:'#a78bdb',animatedBackground:'subtle',backgroundAnimationStyle:'aurora',backgroundFlowSpeed:.14,backgroundFlowOpacity:.1,backgroundFlowUseThemeColors:false,backgroundFlowPrimary:'#5c83cf',backgroundFlowSecondary:'#a582d4',backgroundFlowBlur:.85,backgroundFlowScale:.75,panelMaterial:'soft-glass',edgeLighting:'active',glowStrength:.12,haloStrength:.035,hoverGlintPrinters:true,hoverGlintProjects:true,hoverGlintIntensity:.28,hoverGlintDuration:10});
  glow.shape.surfaceOpacity=.93;separateProfiles(glow,true,'dark');glow.paletteEffects.lightBrightness=.045;glow.paletteEffects.lightOpacity=.98;glow.paletteEffects.lightGlow=.06;glow.paletteEffects.lightHalo=.02;
  const clear=base('Чёткая','Clarity');
  clear.interface.highContrast=true;clear.effects.cornerStyle='tech';clear.shape.borderWidth=1.25;clear.shape.shadowIntensity=0;
  Object.assign(clear.dark,{accent:'#69b9ff',surfaceDeep:'#090c11',surfaceBase:'#111722',surfaceCard:'#1b2432',surfaceControl:'#253244',border:'#61768f',textPrimary:'#f5f7fb',textSecondary:'#d2dbea',headerSurface:'#111722',headerAction:'#253244',headerBorder:'#61768f'});
  Object.assign(clear.light,{accent:'#155bbb',surfaceDeep:'#e7ecf3',surfaceBase:'#f1f4f8',surfaceCard:'#ffffff',surfaceControl:'#edf2f8',border:'#8697ad',textPrimary:'#152238',textSecondary:'#35445b',headerSurface:'#ffffff',headerAction:'#edf2f8',headerBorder:'#8697ad'});
  const glass=cloneTheme(IPHONE_THEME);
  Object.assign(glass.meta,{name:'Стекло',nameEn:'Glass'});glass.typography.textScale=1.1;
  Object.assign(glass.effects,{backgroundFlowSpeed:.12,hoverGlintIntensity:.3,hoverGlintDuration:10});
  const entries=[
    {id:'quiet',ru:'Тихая',en:'Quiet',hint:'Мягкие цвета · без анимации',hintEn:'Soft colors · no animation',theme:calm},
    {id:'aurora',ru:'Сияние',en:'Aurora',hint:'Плавный свет · деликатные акценты',hintEn:'Flowing light · subtle accents',theme:glow},
    {id:'clarity',ru:'Чёткая',en:'Clarity',hint:'Читаемый текст · ясные границы',hintEn:'Readable text · clear borders',theme:clear},
    {id:'glass',ru:'Стекло',en:'Glass',hint:'Воздушные панели · мягкое стекло',hintEn:'Airy surfaces · soft glass',theme:glass}
  ];
  for(const e of entries)Object.assign(e.theme.meta,{description:e.hint,descriptionEn:e.hintEn});
  return entries;
}
export function presetThumbnail(entry,mode){
  const t=resolveProfile(entry.theme,mode),p=t[mode],e=t.effects;
  return {'--tile-bg':p.surfaceDeep,'--tile-card':p.surfaceCard,'--tile-header':p.headerSurface,'--tile-border':p.border,'--tile-text':p.textPrimary,'--tile-muted':p.textSecondary,'--tile-accent':p.accent,'--tile-secondary':e.backgroundFlowSecondary,'--tile-radius':e.cornerStyle==='rounded'?'10px':'4px','--tile-shadow':`0 5px 12px rgba(0,0,0,${Math.min(.24,t.shape.shadowIntensity*.4)})`,'--tile-ambient':e.animatedBackground==='off'?'0':String(Math.min(.65,e.backgroundFlowOpacity*4))};
}
