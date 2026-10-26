// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
import { DASHBOARD_DEFAULTS, validateDashboard } from './dashboard-settings.js';
import { EXTRA_DEFAULTS, EXTRA_RANGES, EXTRA_PROFILE_PATHS, MATERIALS, CONTROL_STYLES as NEW_CONTROLS } from './theme-extensions.js';
import DEFAULT_THEME, { THEME_SCHEMA_VERSION } from './default-theme.js';
import { FONT_OPTIONS, PALETTE_FIELDS } from './theme-schema.js';

const HEX_RE = /^#[0-9a-fA-F]{6}$/;
const DENSITIES = new Set(['compact', 'normal', 'comfortable']);
const BG_MODES = new Set(['default', 'solid', 'image']);
const PANEL_MATERIALS = new Set(MATERIALS);
const EDGE_LIGHTING = new Set(['off', 'active', 'all']);
const BACKGROUND_PATTERNS = new Set(['none', 'grid', 'micro-lines']);
const TABLE_STYLES = new Set(['clean', 'soft-neon', 'hud']);
const STATUS_STYLES = new Set(['text-dot', 'chip', 'underline']);
const CORNER_STYLES = new Set(['rounded', 'tech', 'squared']);
const EDGE_DIRECTIONS = new Set(['full', 'lower', 'lower-left']);
const PROGRESS_STYLES = new Set(['flat', 'glow', 'dual']);
const CONTROL_STYLES = new Set(['clean', 'glass', 'command']);
const FONT_FORMATS = new Set(['woff2', 'woff', 'truetype', 'opentype']);
const FONT_DATA_RE = /^data:(?:font\/(?:woff2?|ttf|otf)|application\/(?:font-woff2?|font-sfnt|x-font-ttf|x-font-opentype|vnd\.ms-opentype|octet-stream));base64,(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/i;
const MAX_FONT_DATA_URL = 2_850_000; // примерно 2 МБ исходного файла после Base64.
const BACKGROUND_IMAGE_RE = /^data:image\/(png|jpeg|webp);base64,(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/i;
const UNSAFE_KEYS = new Set(['__proto__', 'prototype', 'constructor']);
const ANIMATED_BACKGROUNDS = new Set(['off', 'subtle', 'medium']);
const BACKGROUND_ANIMATION_STYLES = new Set(['flow', 'fluid', 'aurora', 'mist', 'streams', 'mixed']);

const SECTION_KEYS = {
  dashboard: Object.keys(DASHBOARD_DEFAULTS),
  meta: ['name', 'nameEn', 'author', 'description', 'descriptionEn'],
  dark: PALETTE_FIELDS.map(([key]) => key),
  light: PALETTE_FIELDS.map(([key]) => key),
  typography: ['font', 'textScale', 'customFontName', 'customFontFormat', 'customFontDataUrl'],
  shape: ['radiusScale', 'borderWidth', 'shadowIntensity', 'surfaceOpacity'],
  interface: ['density', 'reduceMotion', 'highContrast', 'performanceMode'],
  effects: ['secondaryAccent', 'glowStrength', 'haloStrength', 'panelMaterial', 'edgeLighting', 'panelTopHighlight', 'hoverLift', 'shimmerProgress', 'backgroundPattern', 'patternOpacity', 'ambientStrength', 'tableStyle', 'statusStyle', 'cornerStyle', 'inactiveDesaturation', 'edgeDirection', 'panelDepth', 'progressStyle', 'controlStyle', 'focusGlowStrength', 'matteStrength', 'glossStrength', 'panelAiriness', 'animatedBackground', 'backgroundAnimationStyle', 'backgroundMixedStyle', 'backgroundFlowUseThemeColors', 'backgroundFlowPrimary', 'backgroundFlowSecondary', 'backgroundFlowSpeed', 'backgroundFlowOpacity', 'backgroundFlowBlur', 'backgroundFlowScale', 'microAccentIntensity'],
  paletteEffects: ['separate','darkBrightness','lightBrightness','darkOpacity','lightOpacity','darkGlow','lightGlow','darkHalo','lightHalo'],
  background: ['mode', 'imageDataUrl', 'overlay', 'overlayOpacity', 'blurPx']
};
for(const [section,values] of Object.entries(EXTRA_DEFAULTS))SECTION_KEYS[section].push(...Object.keys(values));
for(const mode of ['dark','light'])SECTION_KEYS.paletteEffects.push(...Object.values(EXTRA_PROFILE_PATHS).map(s=>mode+s));
const TOP_LEVEL_KEYS = new Set(['schemaVersion', ...Object.keys(SECTION_KEYS)]);
SECTION_KEYS.effects.push('backgroundStreamCount', 'backgroundFlowMix', 'backgroundStreamsMix', 'hoverGlintPrinters', 'hoverGlintProjects', 'hoverGlintIntensity', 'hoverGlintDuration');

export const cloneTheme = (theme) => JSON.parse(JSON.stringify(theme));
const isRecord = (value) => !!value && typeof value === 'object' && !Array.isArray(value);
const owns = (value, key) => Object.prototype.hasOwnProperty.call(value, key);

export function mergeWithDefaults(input) {
  const base = cloneTheme(DEFAULT_THEME);
  if (!isRecord(input)) return base;
  if (owns(input, 'schemaVersion')) {
    const incomingVersion = Number(input.schemaVersion);
    base.schemaVersion = (incomingVersion >= 2 && incomingVersion < THEME_SCHEMA_VERSION) ? THEME_SCHEMA_VERSION : input.schemaVersion;
  }
  for (const [section, keys] of Object.entries(SECTION_KEYS)) {
    const source = input[section];
    if (!isRecord(source)) continue;
    for (const key of keys) if (owns(source, key)) base[section][key] = source[key];
  }
  if (Number(input.schemaVersion || 8) < 9 && !owns(input.effects || {}, 'backgroundStreamCount')) {
    base.effects.backgroundStreamCount = input.effects?.animatedBackground === 'medium' ? 16 : 12;
  }
  if (!input.paletteEffects) for (const mode of ['dark','light']) {
    base.paletteEffects[mode+'Brightness']=base.effects.backgroundFlowOpacity;
    base.paletteEffects[mode+'Opacity']=base.shape.surfaceOpacity;
    base.paletteEffects[mode+'Glow']=base.effects.glowStrength;
    base.paletteEffects[mode+'Halo']=base.effects.haloStrength;
  }
  // Missing per-palette additions inherit the imported common value, including
  // themes that already separated the four older effects. Never use preset colors.
  for(const mode of ['dark','light'])for(const [path,suffix] of Object.entries(EXTRA_PROFILE_PATHS)) {
    const [section,key]=path.split('.');
    if(!owns(input.paletteEffects||{},mode+suffix))base.paletteEffects[mode+suffix]=base[section][key];
  }
  return base;
}

function collectStructureErrors(input, errors) {
  if (input == null) return;
  if (!isRecord(input)) { errors.push('theme'); return; }
  for (const key of Object.keys(input)) {
    if (UNSAFE_KEYS.has(key) || !TOP_LEVEL_KEYS.has(key)) errors.push(`unknown.${key}`);
  }
  for (const [section, keys] of Object.entries(SECTION_KEYS)) {
    if (!owns(input, section)) continue;
    if (!isRecord(input[section])) { errors.push(section); continue; }
    const allowed = new Set(keys);
    for (const key of Object.keys(input[section])) {
      if (UNSAFE_KEYS.has(key) || !allowed.has(key)) errors.push(`${section}.unknown.${key}`);
    }
  }
}

function channel(hex, start) { return parseInt(hex.slice(start, start + 2), 16) / 255; }
function linear(v) { return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }
export function contrastRatio(a, b) {
  if (!HEX_RE.test(a || '') || !HEX_RE.test(b || '')) return 0;
  const lum = (hex) => 0.2126 * linear(channel(hex, 1)) + 0.7152 * linear(channel(hex, 3)) + 0.0722 * linear(channel(hex, 5));
  const l1 = lum(a), l2 = lum(b);
  return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
}

export function validateTheme(input) {
  const errors = [];
  const warnings = [];
  collectStructureErrors(input, errors);
  const theme = mergeWithDefaults(input);
  validateDashboard(theme.dashboard, errors);
  for(const path of ['typography.customMetrics','shape.independentRadii']){
    const [s,k]=path.split('.');if(typeof theme[s][k]!=='boolean')errors.push(path);
  }
  const checkRange=(v,min,max,step)=>typeof v==='number'&&Number.isFinite(v)&&v>=min&&v<=max&&(!step||v%step===0);
  for(const [path,[min,max,step]] of Object.entries(EXTRA_RANGES)){
    const [s,k]=path.split('.');if(!checkRange(theme[s][k],min,max,step))errors.push(path);
  }
  for(const mode of ['dark','light'])for(const suffix of Object.values(EXTRA_PROFILE_PATHS)){
    const v=theme.paletteEffects[mode+suffix];
    const ok=suffix==='UseThemeColors'?typeof v==='boolean':
      ['Primary','Secondary'].includes(suffix)?typeof v==='string'&&HEX_RE.test(v):
      suffix==='Material'?MATERIALS.includes(v):suffix==='Controls'?NEW_CONTROLS.includes(v):
      checkRange(v,0,suffix==='Shadow'?1.5:suffix==='GlassBlur'?16:1,0);
    if(!ok)errors.push('paletteEffects.'+mode+suffix);
  }
  if (typeof theme.paletteEffects.separate !== 'boolean') errors.push('paletteEffects.separate');
  for(const mode of ['dark','light']) for(const suffix of ['Brightness','Opacity','Glow','Halo']) {
    const v=theme.paletteEffects[mode+suffix],max=1,min=suffix==='Opacity'?.72:0;
    if(typeof v!=='number'||!Number.isFinite(v)||v<min||v>max) errors.push('paletteEffects.'+mode+suffix);
  }
  if (!Number.isInteger(theme.schemaVersion) || theme.schemaVersion !== THEME_SCHEMA_VERSION) errors.push('schemaVersion');

  for (const mode of ['dark', 'light']) {
    for (const [key] of PALETTE_FIELDS) {
      if (!HEX_RE.test(String(theme[mode][key] || ''))) errors.push(`${mode}.${key}`);
    }
    const cardContrast = contrastRatio(theme[mode].textPrimary, theme[mode].surfaceCard);
    const baseContrast = contrastRatio(theme[mode].textPrimary, theme[mode].surfaceBase);
    if (cardContrast < 4.5) errors.push(`${mode}.contrast.card`);
    if (baseContrast < 4.5) errors.push(`${mode}.contrast.base`);
    const secondaryContrast = contrastRatio(theme[mode].textSecondary, theme[mode].surfaceCard);
    if (secondaryContrast < 3) warnings.push(`${mode}.contrast.secondary`);
  }

  const fontIds = new Set(FONT_OPTIONS.map((x) => x.id));
  if (!fontIds.has(theme.typography.font)) errors.push('typography.font');
  const customName = String(theme.typography.customFontName || '');
  const customFormat = String(theme.typography.customFontFormat || '');
  const customData = String(theme.typography.customFontDataUrl || '');
  if (typeof theme.typography.customFontName !== 'string' || customName.length > 180 || /[<>]/.test(customName)) errors.push('typography.customFontName');
  if (typeof theme.typography.customFontFormat !== 'string') errors.push('typography.customFontFormat'); if (typeof theme.typography.customFontDataUrl !== 'string') errors.push('typography.customFontDataUrl'); if (customData.length > MAX_FONT_DATA_URL) errors.push('typography.customFontSize');
  if (customData && (!FONT_FORMATS.has(customFormat) || !FONT_DATA_RE.test(customData))) errors.push('typography.customFontData');
  if (theme.typography.font === 'custom') {
    if (!customData) errors.push('typography.customFontMissing');
    if (!FONT_FORMATS.has(customFormat)) errors.push('typography.customFontFormat');
  }
  const textScale = Number(theme.typography.textScale);
  if (typeof theme.typography.textScale !== 'number' || !Number.isFinite(textScale) || textScale < 0.85 || textScale > 1.6) errors.push('typography.textScale');

  const radiusScale = Number(theme.shape.radiusScale);
  if (typeof theme.shape.radiusScale !== 'number' || !Number.isFinite(radiusScale) || radiusScale < 0.5 || radiusScale > 1.8) errors.push('shape.radiusScale');
  const borderWidth = Number(theme.shape.borderWidth);
  if (typeof theme.shape.borderWidth !== 'number' || !Number.isFinite(borderWidth) || borderWidth < 1 || borderWidth > 2) errors.push('shape.borderWidth');
  const shadowIntensity = Number(theme.shape.shadowIntensity);
  if (typeof theme.shape.shadowIntensity !== 'number' || !Number.isFinite(shadowIntensity) || shadowIntensity < 0 || shadowIntensity > 1.5) errors.push('shape.shadowIntensity');
  const surfaceOpacity = Number(theme.shape.surfaceOpacity);
  if (typeof theme.shape.surfaceOpacity !== 'number' || !Number.isFinite(surfaceOpacity) || surfaceOpacity < 0.72 || surfaceOpacity > 1) errors.push('shape.surfaceOpacity');

  if (!DENSITIES.has(theme.interface.density)) errors.push('interface.density');
  if (typeof theme.interface.reduceMotion !== 'boolean') errors.push('interface.reduceMotion');
  if (typeof theme.interface.highContrast !== 'boolean') errors.push('interface.highContrast');
  if (!['balanced', 'economy'].includes(theme.interface.performanceMode)) errors.push('interface.performanceMode');
  for (const key of ['hoverGlintPrinters', 'hoverGlintProjects']) {
    if (typeof theme.effects[key] !== 'boolean') errors.push(`effects.${key}`);
  }
  for (const [key, min, max] of [['backgroundStreamCount', 2, 20], ['backgroundFlowMix', 0, 1], ['backgroundStreamsMix', 0, 1], ['hoverGlintIntensity', 0, 1], ['hoverGlintDuration', 2, 15]]) {
    const n = theme.effects[key];
    if (typeof n !== 'number' || !Number.isFinite(n) || n < min || n > max || (key === 'backgroundStreamCount' && !Number.isInteger(n))) errors.push(`effects.${key}`);
  }

  if (!HEX_RE.test(String(theme.effects.secondaryAccent || ''))) errors.push('effects.secondaryAccent');
  const glowStrength = Number(theme.effects.glowStrength);
  if (typeof theme.effects.glowStrength !== 'number' || !Number.isFinite(glowStrength) || glowStrength < 0 || glowStrength > 1) errors.push('effects.glowStrength');
  const haloStrength = Number(theme.effects.haloStrength);
  if (typeof theme.effects.haloStrength !== 'number' || !Number.isFinite(haloStrength) || haloStrength < 0 || haloStrength > 1) errors.push('effects.haloStrength');
  if (!PANEL_MATERIALS.has(theme.effects.panelMaterial)) errors.push('effects.panelMaterial');
  if (!EDGE_LIGHTING.has(theme.effects.edgeLighting)) errors.push('effects.edgeLighting');
  if (typeof theme.effects.panelTopHighlight !== 'boolean') errors.push('effects.panelTopHighlight');
  if (typeof theme.effects.hoverLift !== 'boolean') errors.push('effects.hoverLift');
  if (typeof theme.effects.shimmerProgress !== 'boolean') errors.push('effects.shimmerProgress');
  if (!BACKGROUND_PATTERNS.has(theme.effects.backgroundPattern)) errors.push('effects.backgroundPattern');
  const patternOpacity = Number(theme.effects.patternOpacity);
  if (typeof theme.effects.patternOpacity !== 'number' || !Number.isFinite(patternOpacity) || patternOpacity < 0 || patternOpacity > 0.18) errors.push('effects.patternOpacity');
  const ambientStrength = Number(theme.effects.ambientStrength);
  if (typeof theme.effects.ambientStrength !== 'number' || !Number.isFinite(ambientStrength) || ambientStrength < 0 || ambientStrength > 0.6) errors.push('effects.ambientStrength');
  if (!TABLE_STYLES.has(theme.effects.tableStyle)) errors.push('effects.tableStyle');
  if (!STATUS_STYLES.has(theme.effects.statusStyle)) errors.push('effects.statusStyle');
  if (!CORNER_STYLES.has(theme.effects.cornerStyle)) errors.push('effects.cornerStyle');
  const inactiveDesaturation = Number(theme.effects.inactiveDesaturation);
  if (typeof theme.effects.inactiveDesaturation !== 'number' || !Number.isFinite(inactiveDesaturation) || inactiveDesaturation < 0 || inactiveDesaturation > 0.5) errors.push('effects.inactiveDesaturation');
  if (!EDGE_DIRECTIONS.has(theme.effects.edgeDirection)) errors.push('effects.edgeDirection');
  const panelDepth = Number(theme.effects.panelDepth);
  if (typeof theme.effects.panelDepth !== 'number' || !Number.isFinite(panelDepth) || panelDepth < 0 || panelDepth > 1) errors.push('effects.panelDepth');
  if (!PROGRESS_STYLES.has(theme.effects.progressStyle)) errors.push('effects.progressStyle');
  if (!CONTROL_STYLES.has(theme.effects.controlStyle)) errors.push('effects.controlStyle');
  const focusGlowStrength = Number(theme.effects.focusGlowStrength);
  if (typeof theme.effects.focusGlowStrength !== 'number' || !Number.isFinite(focusGlowStrength) || focusGlowStrength < 0 || focusGlowStrength > 1) errors.push('effects.focusGlowStrength');
  const matteStrength = Number(theme.effects.matteStrength);
  if (typeof theme.effects.matteStrength !== 'number' || !Number.isFinite(matteStrength) || matteStrength < 0 || matteStrength > 1) errors.push('effects.matteStrength');
  const glossStrength = Number(theme.effects.glossStrength);
  if (typeof theme.effects.glossStrength !== 'number' || !Number.isFinite(glossStrength) || glossStrength < 0 || glossStrength > 1) errors.push('effects.glossStrength');
  const panelAiriness = Number(theme.effects.panelAiriness);
  if (typeof theme.effects.panelAiriness !== 'number' || !Number.isFinite(panelAiriness) || panelAiriness < 0 || panelAiriness > 1) errors.push('effects.panelAiriness');
  if (!ANIMATED_BACKGROUNDS.has(theme.effects.animatedBackground)) errors.push('effects.animatedBackground');
  if (!['flow','fluid','aurora','mist'].includes(theme.effects.backgroundMixedStyle)) errors.push('effects.backgroundMixedStyle');
  if (!BACKGROUND_ANIMATION_STYLES.has(theme.effects.backgroundAnimationStyle)) errors.push('effects.backgroundAnimationStyle');
  if (typeof theme.effects.backgroundFlowUseThemeColors !== 'boolean') errors.push('effects.backgroundFlowUseThemeColors');
  if (!HEX_RE.test(String(theme.effects.backgroundFlowPrimary || ''))) errors.push('effects.backgroundFlowPrimary');
  if (!HEX_RE.test(String(theme.effects.backgroundFlowSecondary || ''))) errors.push('effects.backgroundFlowSecondary');
  const backgroundFlowSpeed = Number(theme.effects.backgroundFlowSpeed);
  if (typeof theme.effects.backgroundFlowSpeed !== 'number' || !Number.isFinite(backgroundFlowSpeed) || backgroundFlowSpeed < 0 || backgroundFlowSpeed > 1) errors.push('effects.backgroundFlowSpeed');
  const backgroundFlowOpacity = Number(theme.effects.backgroundFlowOpacity);
  if (typeof theme.effects.backgroundFlowOpacity !== 'number' || !Number.isFinite(backgroundFlowOpacity) || backgroundFlowOpacity < 0 || backgroundFlowOpacity > 1) errors.push('effects.backgroundFlowOpacity');
  const backgroundFlowBlur = Number(theme.effects.backgroundFlowBlur);
  if (typeof theme.effects.backgroundFlowBlur !== 'number' || !Number.isFinite(backgroundFlowBlur) || backgroundFlowBlur < 0 || backgroundFlowBlur > 1) errors.push('effects.backgroundFlowBlur');
  const backgroundFlowScale = Number(theme.effects.backgroundFlowScale);
  if (typeof theme.effects.backgroundFlowScale !== 'number' || !Number.isFinite(backgroundFlowScale) || backgroundFlowScale < 0 || backgroundFlowScale > 1) errors.push('effects.backgroundFlowScale');
  const microAccentIntensity = Number(theme.effects.microAccentIntensity);
  if (typeof theme.effects.microAccentIntensity !== 'number' || !Number.isFinite(microAccentIntensity) || microAccentIntensity < 0 || microAccentIntensity > 1) errors.push('effects.microAccentIntensity');

  if (!BG_MODES.has(theme.background.mode)) errors.push('background.mode');
  if (!HEX_RE.test(String(theme.background.overlay || ''))) errors.push('background.overlay');
  const overlayOpacity = Number(theme.background.overlayOpacity);
  if (typeof theme.background.overlayOpacity !== 'number' || !Number.isFinite(overlayOpacity) || overlayOpacity < 0 || overlayOpacity > 0.85) errors.push('background.overlayOpacity');
  const blurPx = Number(theme.background.blurPx);
  if (typeof theme.background.blurPx !== 'number' || !Number.isFinite(blurPx) || blurPx < 0 || blurPx > 20) errors.push('background.blurPx');
  if (typeof theme.background.imageDataUrl !== 'string') errors.push('background.imageDataUrl');
  const dataUrl = typeof theme.background.imageDataUrl === 'string' ? theme.background.imageDataUrl : '';
  if (dataUrl && !BACKGROUND_IMAGE_RE.test(dataUrl)) errors.push('background.imageDataUrl');
  if (dataUrl.length > 2_050_000) errors.push('background.imageSize');
  if (theme.background.mode === 'image' && !dataUrl) errors.push('background.imageDataUrl');

  for (const field of ['name', 'nameEn', 'author', 'description', 'descriptionEn']) {
    const value = String(theme.meta[field] || '');
    if (typeof theme.meta[field] !== 'string') errors.push('meta.' + field); if (value.length > (field.startsWith('description') ? 500 : 100)) errors.push(`meta.${field}`);
    if (/[<>]/.test(value)) errors.push(`meta.${field}.markup`);
  }
  if (!String(theme.meta.name || '').trim()) errors.push('meta.name');

  return { ok: errors.length === 0, errors: [...new Set(errors)], warnings: [...new Set(warnings)], theme };
}

// 0.17.5: почему тему не удалось показать — 'newer' (сохранена более новой версией модуля, у неё номер
// схемы больше нашего) или 'invalid' (повреждена). Редактор говорит об этом словами, а не молчит.
export function themeHiddenReason(input) {
  const version = isRecord(input) ? Number(input.schemaVersion) : NaN;
  return Number.isFinite(version) && version > THEME_SCHEMA_VERSION ? 'newer' : 'invalid';
}

export function safeFileName(value) {
  const clean = String(value || 'theme').trim().replace(/[\\/:*?"<>|\x00-\x1f]+/g, '_').replace(/\s+/g, '_').slice(0, 80);
  return clean || 'theme';
}
