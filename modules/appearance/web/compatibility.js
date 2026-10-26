// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
import { AMBIENT_LAYER_ID, HOVER_GLINT_CLASS } from './theme-schema.js';

// Адресный слой совместимости. Он не меняет разметку и поведение Farm Manager.
// Новые модули должны использовать THEME_CONTRACT.md и переменные --fm-* напрямую.

const HEADER_LEFT_PATHS = [
  'M580.19 3867.89l47188.12 0c153.97,-0.1 301.6,-61.36 410.4,-170.3 108.8,-108.95 169.88,-255.92 169.78,-409.89l0 -1450.46c-0.05,-76.98 -30.68,-150.79 -85.15,-205.2 -54.47,-54.4 -127.96,-84.94 -204.94,-84.89l-3337.46 0c-153.84,0.02 -301.47,-61.17 -410.26,-169.93l-1207.29 -1207.29c-108.85,-108.82 -256.34,-169.95 -410.25,-169.93l-23827.09 0c-153.92,0.01 -301.43,61.08 -410.26,169.93l-433.71 433.71c-108.76,108.79 -256.42,169.91 -410.25,169.93l-10796.12 0c-153.84,0.02 -301.47,-61.16 -410.26,-169.93l-433.71 -433.71c-108.85,-108.82 -256.34,-169.95 -410.26,-169.93l-4981.31 0c-153.97,0.09 -301.6,61.35 -410.4,170.3 -108.81,108.94 -169.88,255.91 -169.78,409.88l0 2707.52c0.1,153.97 61.36,301.6 170.3,410.4 108.95,108.81 255.92,169.88 409.89,169.78z',
  'M45003.18 56.66c-36.28,-36.28 -85.44,-56.65 -136.75,-56.64l-1137.87 0c-78.33,0.28 -148.79,47.73 -178.51,120.22 -29.71,72.48 -13.84,154.73 41.76,209.93l882.98 882.97c65.3,65.3 153.8,101.97 246.15,101.96l1073.78 0c78.34,-0.28 148.79,-47.74 178.51,-120.22 29.72,-72.49 13.84,-154.73 -41.76,-209.93l-928.29 -928.29z',
  'M47016.26 56.66c-36.29,-36.28 -85.45,-56.65 -136.75,-56.64l-1137.87 0c-78.34,0.28 -148.79,47.73 -178.51,120.22 -29.72,72.48 -13.84,154.73 41.76,209.93l928.29 928.29c36.29,36.27 85.45,56.65 136.75,56.64l1137.87 0c78.34,-0.28 148.79,-47.74 178.51,-120.22 29.71,-72.49 13.84,-154.73 -41.76,-209.93l-928.29 -928.29z'
];

function safeColor(value) {
  const text = String(value || '').trim();
  return /^#[0-9a-f]{6}$/i.test(text) ? text : '#26282a';
}

function headerLeftDataUrl(color) {
  const fill = safeColor(color);
  const paths = HEADER_LEFT_PATHS.map((d) => `<path d="${d}" fill="${fill}"/>`).join('');
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 18866 3867.9" preserveAspectRatio="none">${paths}</svg>`;
  return `data:image/svg+xml,${encodeURIComponent(svg)}`;
}

function addHeaderCompatibility(lines, theme) {
  const darkUrl = headerLeftDataUrl(theme.dark && theme.dark.headerSurface);
  const lightUrl = headerLeftDataUrl(theme.light && theme.light.headerSurface);
  lines.push(`:root[data-theme="dark"][data-fm-appearance-active="1"] .fm-header-left-v270{background-image:url("${darkUrl}")!important;background-repeat:no-repeat!important;background-size:100% 100%!important;}`);
  lines.push(`:root[data-theme="light"][data-fm-appearance-active="1"] .fm-header-left-v270{background-image:url("${lightUrl}")!important;background-repeat:no-repeat!important;background-size:100% 100%!important;}`);
  lines.push('html[data-fm-appearance-active="1"] .fm-header-lang-svg-v270>path{fill:var(--fm-header-surface)!important;}');
  lines.push('html[data-fm-appearance-active="1"] .fm-header-lang-svg-v270 .ltb{fill:var(--fm-header-surface)!important;}');
  lines.push('html[data-fm-appearance-active="1"] .fm-header-lang-svg-v270 .ltab:hover .ltb{fill:var(--fm-header-hover)!important;}');
  lines.push('html[data-fm-appearance-active="1"] .fm-header-lang-svg-v270 .ltab:active .ltb{fill:var(--fm-header-active)!important;}');
}

function addPrintingGlowCompatibility(lines) {
  lines.push('@keyframes fmAppearanceRunPulse{0%,100%{box-shadow:0 0 4px 0 rgba(var(--fm-accent-rgb),.25)}50%{box-shadow:0 0 16px 3px rgba(var(--fm-accent-rgb),.7)}}');
  lines.push('html[data-fm-appearance-active="1"] .run-glow{animation-name:fmAppearanceRunPulse!important;border-color:rgba(var(--fm-accent-rgb),.4)!important;}');
}


function addFileManagerCompatibility(lines) {
  lines.push('html[data-fm-appearance-active="1"] .ex-win{background:var(--fm-surface-base)!important;border-color:var(--fm-border-strong)!important;color:var(--fm-text-primary)!important;font-family:var(--fm-theme-font)!important;box-shadow:0 24px 70px rgba(var(--fm-black-rgb),calc(.58 * var(--fm-theme-shadow-intensity,1)))!important;}');
  lines.push('html[data-fm-appearance-active="1"] .ex-win *{scrollbar-color:var(--fm-border-strong) var(--fm-surface-deep);}');
  lines.push('html[data-fm-appearance-active="1"] .ex-win ::-webkit-scrollbar-track{background:var(--fm-surface-deep)!important;}html[data-fm-appearance-active="1"] .ex-win ::-webkit-scrollbar-thumb{background:var(--fm-border-strong)!important;border:2px solid var(--fm-surface-deep)!important;}html[data-fm-appearance-active="1"] .ex-win ::-webkit-scrollbar-thumb:hover{background:var(--fm-accent)!important;}');
  lines.push('html[data-fm-appearance-active="1"] .ex-title{background:var(--fm-surface-raised)!important;border-color:var(--fm-border)!important;color:var(--fm-text-primary)!important;}');
  lines.push('html[data-fm-appearance-active="1"] .ex-x{color:var(--fm-text-secondary)!important;}html[data-fm-appearance-active="1"] .ex-x:hover{background:var(--fm-danger)!important;color:#fff!important;}');
  lines.push('html[data-fm-appearance-active="1"] .ex-bar{background:var(--fm-surface-base)!important;border-color:var(--fm-border-soft)!important;}');
  lines.push('html[data-fm-appearance-active="1"] .ex-nav,html[data-fm-appearance-active="1"] .ex-addr{background:var(--fm-surface-control)!important;border-color:var(--fm-border)!important;color:var(--fm-text-primary)!important;}');
  lines.push('html[data-fm-appearance-active="1"] .ex-nav:hover{background:var(--fm-surface-raised)!important;border-color:var(--fm-accent)!important;}');
  lines.push('html[data-fm-appearance-active="1"] .ex-zoom-val,html[data-fm-appearance-active="1"] .ex-crumb{color:var(--fm-text-secondary)!important;}html[data-fm-appearance-active="1"] .ex-zoom-val:hover,html[data-fm-appearance-active="1"] .ex-crumb:hover{background:var(--fm-surface-raised)!important;color:var(--fm-text-primary)!important;}html[data-fm-appearance-active="1"] .ex-crsep{color:var(--fm-text-subtle)!important;}');
  lines.push('html[data-fm-appearance-active="1"] .ex-side{background:var(--fm-surface-card)!important;border-color:var(--fm-border-soft)!important;}html[data-fm-appearance-active="1"] .ex-sdiv:hover{background:var(--fm-border)!important;}');
  lines.push('html[data-fm-appearance-active="1"] .ex-side-h{color:var(--fm-text-muted)!important;}html[data-fm-appearance-active="1"] .ex-side-i{color:var(--fm-text-secondary)!important;}html[data-fm-appearance-active="1"] .ex-side-i:hover{background:rgba(var(--fm-accent-rgb),.12)!important;color:var(--fm-text-primary)!important;}');
  lines.push('html[data-fm-appearance-active="1"] .ex-main{background:var(--fm-surface-base)!important;}html[data-fm-appearance-active="1"] .ex-head{background:var(--fm-surface-raised)!important;border-color:var(--fm-border-soft)!important;color:var(--fm-text-muted)!important;}');
  lines.push('html[data-fm-appearance-active="1"] .ex-list{background:var(--fm-surface-base)!important;}html[data-fm-appearance-active="1"] .ex-row{color:var(--fm-text-secondary)!important;}html[data-fm-appearance-active="1"] .ex-row:hover{background:var(--fm-surface-raised)!important;}html[data-fm-appearance-active="1"] .ex-row.sel{background:rgba(var(--fm-accent-rgb),.18)!important;border-color:rgba(var(--fm-accent-rgb),.72)!important;color:var(--fm-text-primary)!important;}');
  lines.push('html[data-fm-appearance-active="1"] .ex-meta,html[data-fm-appearance-active="1"] .ex-prev-meta{color:var(--fm-text-muted)!important;font-family:var(--fm-theme-font)!important;}');
  lines.push('html[data-fm-appearance-active="1"] .ex-foot{background:var(--fm-surface-raised)!important;border-color:var(--fm-border-soft)!important;}html[data-fm-appearance-active="1"] .ex-foot-info{color:var(--fm-text-muted)!important;}');
  lines.push('html[data-fm-appearance-active="1"] .ex-btn{background:var(--fm-surface-control)!important;border-color:var(--fm-border)!important;color:var(--fm-text-primary)!important;}html[data-fm-appearance-active="1"] .ex-btn:hover{background:var(--fm-surface-raised)!important;border-color:var(--fm-border-strong)!important;}html[data-fm-appearance-active="1"] .ex-btn.pri{background:var(--fm-accent)!important;border-color:var(--fm-accent)!important;color:#071018!important;}html[data-fm-appearance-active="1"] .ex-btn.pri:hover{background:rgba(var(--fm-accent-rgb),.88)!important;box-shadow:0 0 12px rgba(var(--fm-accent-rgb),.18)!important;}');
  lines.push('html[data-fm-appearance-active="1"] .ex-empty,html[data-fm-appearance-active="1"] .ex-prev-empty{color:var(--fm-text-subtle)!important;}html[data-fm-appearance-active="1"] .ex-err{color:var(--fm-danger)!important;}');
  lines.push('html[data-fm-appearance-active="1"] .ex-prev{background:var(--fm-surface-card)!important;border-color:var(--fm-border-soft)!important;}html[data-fm-appearance-active="1"] .ex-prev-img{background:var(--fm-surface-deep)!important;border-color:var(--fm-border)!important;}html[data-fm-appearance-active="1"] .ex-prev-ph{background:var(--fm-surface-deep)!important;border-color:var(--fm-border)!important;color:var(--fm-text-muted)!important;}html[data-fm-appearance-active="1"] .ex-prev-nm{color:var(--fm-text-primary)!important;}');
}

function addPremiumEffectsCompatibility(lines, theme) {
  // WORKFLOW SAFETY: never create filter/backdrop-filter/z-index/opacity/transform stacking behavior on core FM workflow elements.
  const e = theme.effects || {};
  const glow = Math.max(0, Math.min(1, Number(e.glowStrength || 0)));
  const halo = Math.max(0, Math.min(1, Number(e.haloStrength || 0)));
  const pattern = Math.max(0, Math.min(.18, Number(e.patternOpacity || 0)));
  const ambient = Math.max(0, Math.min(.6, Number(e.ambientStrength || 0)));
  const desat = Math.max(0, Math.min(.5, Number(e.inactiveDesaturation || 0)));
  const depth = Math.max(0, Math.min(1, Number(e.panelDepth || 0)));
  const focusGlow = Math.max(0, Math.min(1, Number(e.focusGlowStrength || 0)));
  const matte = Math.max(0, Math.min(1, Number(e.matteStrength || 0)));
  const gloss = Math.max(0, Math.min(1, Number(e.glossStrength || 0)));
  const air = Math.max(0, Math.min(1, Number(e.panelAiriness || 0)));
  const micro = Math.max(0, Math.min(1, Number(e.microAccentIntensity || 0)));
  const animBg = String(e.animatedBackground || 'off');
  const backgroundAnimationStyle = String(e.backgroundAnimationStyle || 'flow');
  const flowSpeed = Math.max(0, Math.min(1, Number(e.backgroundFlowSpeed || 0)));
  const flowOpacity = Math.max(0, Math.min(1, Number(e.backgroundFlowOpacity || 0)));
  const flowBlur = Math.max(0, Math.min(1, Number(e.backgroundFlowBlur || 0)));
  const flowScale = Math.max(0, Math.min(1, Number(e.backgroundFlowScale || 0)));

  // Surface material: controlled transparency and blur without changing DOM structure.
  if (e.panelMaterial === 'soft-glass') {
    lines.push(`html[data-fm-appearance-active="1"] .glass-panel,html[data-fm-appearance-active="1"] .fm-module{background-color:rgba(var(--fm-surface-card-rgb),${(0.82 - matte*0.10).toFixed(3)})!important;background-image:linear-gradient(180deg,rgba(255,255,255,${(0.06 + gloss*0.10).toFixed(3)}) 0%,rgba(255,255,255,${(0.015 + gloss*0.03).toFixed(3)}) 12%,rgba(0,0,0,0) 42%,rgba(0,0,0,${(0.03 + matte*0.04).toFixed(3)}) 100%)!important;}`);
    lines.push('html[data-fm-appearance-active="1"] .printer-card,html[data-fm-appearance-active="1"] .plan-cell{background-color:rgba(var(--fm-surface-raised-rgb),.76)!important;}');
  } else if (e.panelMaterial === 'deep-glass') {
    lines.push(`html[data-fm-appearance-active="1"] .glass-panel,html[data-fm-appearance-active="1"] .fm-module{background-color:rgba(var(--fm-surface-card-rgb),${(0.74 - matte*0.10).toFixed(3)})!important;background-image:radial-gradient(circle at 18% 10%,rgba(255,255,255,${(0.03 + gloss*0.12).toFixed(3)}),transparent 26%),linear-gradient(180deg,rgba(255,255,255,${(0.045 + gloss*0.08).toFixed(3)}) 0%,rgba(255,255,255,${(0.012 + gloss*0.03).toFixed(3)}) 16%,rgba(0,0,0,0) 50%,rgba(0,0,0,${(0.04 + matte*0.06).toFixed(3)}) 100%)!important;}`);
    lines.push(`html[data-fm-appearance-active="1"] .printer-card,html[data-fm-appearance-active="1"] .plan-cell{background-color:rgba(var(--fm-surface-raised-rgb),${(0.68 - matte*0.08).toFixed(3)})!important;background-image:radial-gradient(circle at 18% 8%,rgba(255,255,255,${(0.02 + gloss*0.08).toFixed(3)}),transparent 26%),linear-gradient(180deg,rgba(255,255,255,${(0.03 + gloss*0.06).toFixed(3)}) 0%,rgba(255,255,255,0) 24%,rgba(0,0,0,${(0.04 + matte*0.05).toFixed(3)}) 100%)!important;}`);
  } else if (e.panelMaterial === 'hud') {
    lines.push('html[data-fm-appearance-active="1"] .glass-panel,html[data-fm-appearance-active="1"] .fm-module,html[data-fm-appearance-active="1"] .printer-card,html[data-fm-appearance-active="1"] .plan-cell{background-color:rgba(var(--fm-surface-deep-rgb),.84)!important;border-color:rgba(var(--fm-accent-rgb),.34)!important;}');
  }

  if (e.panelTopHighlight) {
    lines.push(`html[data-fm-appearance-active="1"] .glass-panel,html[data-fm-appearance-active="1"] .printer-card,html[data-fm-appearance-active="1"] .plan-cell,html[data-fm-appearance-active="1"] .fm-module{background-image:radial-gradient(circle at 18% 10%,rgba(255,255,255,${(0.02 + gloss*0.08).toFixed(3)}),transparent 24%),linear-gradient(180deg,rgba(255,255,255,${(0.028 + gloss*0.05).toFixed(3)}),rgba(255,255,255,0) 22%)!important;}`);
  }

  const shadowTargets=['.glass-panel','.fm-module','.printer-card','.plan-cell'].map(s=>'html[data-fm-appearance-active="1"] '+s).join(',');
  const zero='0 0 0 transparent';
  lines.push(`${shadowTargets}{--fm-ap-depth:${zero};--fm-ap-air:${zero};--fm-ap-glow:${zero};--fm-ap-hover:${zero};--fm-ap-base:0 8px 30px rgba(var(--fm-black-rgb),${(.16*theme.shape.shadowIntensity).toFixed(3)});box-shadow:var(--fm-ap-depth),var(--fm-ap-air),var(--fm-ap-glow),var(--fm-ap-hover),var(--fm-ap-base)!important;}`);
  if (depth > .001) {
    const innerTop = (.025 + depth * .055).toFixed(3);
    const innerBottom = (.08 + depth * .14).toFixed(3);
    const outerAlpha = (.10 + depth * .16).toFixed(3);
    const outerBlur = Math.round(12 + depth * 24);
    lines.push(`html[data-fm-appearance-active="1"] .glass-panel,html[data-fm-appearance-active="1"] .fm-module{--fm-ap-depth:inset 0 1px 0 rgba(255,255,255,${innerTop}),inset 0 -16px 28px rgba(var(--fm-black-rgb),${innerBottom}),0 10px ${outerBlur}px rgba(var(--fm-black-rgb),${outerAlpha})!important;}`);
    lines.push(`html[data-fm-appearance-active="1"] .printer-card,html[data-fm-appearance-active="1"] .plan-cell{--fm-ap-depth:inset 0 1px 0 rgba(255,255,255,${innerTop}),inset 0 -12px 22px rgba(var(--fm-black-rgb),${innerBottom})!important;}`);
  }

  // Corner character: no clip-path, so shadows and click targets remain intact.
  if (e.cornerStyle === 'tech') {
    lines.push('html[data-fm-appearance-active="1"] .printer-card,html[data-fm-appearance-active="1"] .plan-cell,html[data-fm-appearance-active="1"] .glass-panel{border-radius:5px 14px 5px 14px!important;}');
  } else if (e.cornerStyle === 'squared') {
    lines.push('html[data-fm-appearance-active="1"] .printer-card,html[data-fm-appearance-active="1"] .plan-cell,html[data-fm-appearance-active="1"] .glass-panel{border-radius:3px!important;}');
  }

  if (air > .001) {
    const panelShadowA = (0.14 + air * 0.12).toFixed(3);
    const panelLift = Math.round(14 + air * 18);
    const panelBlur = Math.round(30 + air * 26);
    lines.push(`html[data-fm-appearance-active="1"] .glass-panel,html[data-fm-appearance-active="1"] .fm-module,html[data-fm-appearance-active="1"] .printer-card,html[data-fm-appearance-active="1"] .plan-cell{--fm-ap-air:0 ${panelLift}px ${panelBlur}px rgba(0,0,0,${panelShadowA}),inset 0 1px 0 rgba(255,255,255,${(0.035 + gloss*0.04).toFixed(3)})!important;}`);
  }

  const glowA = (.18 + glow * .42).toFixed(3);
  const haloA = (.08 + halo * .28).toFixed(3);
  const blur1 = Math.round(6 + glow * 12);
  const blur2 = Math.round(12 + halo * 24);
  const directionalShadow = (active) => {
    const accentA = active ? (glow * .52).toFixed(3) : (glowA * .42).toFixed(3);
    const secondA = active ? (halo * .30).toFixed(3) : (haloA * .34).toFixed(3);
    if (e.edgeDirection === 'lower') return `inset 0 -2px 0 rgba(var(--fm-accent-rgb),${active ? glowA : (.18 + glow*.18).toFixed(3)}),0 8px ${blur1}px rgba(var(--fm-accent-rgb),${accentA}),0 12px ${blur2}px rgba(var(--fm-secondary-accent-rgb),${secondA})`;
    if (e.edgeDirection === 'lower-left') return `inset 2px 0 0 rgba(var(--fm-secondary-accent-rgb),${active ? haloA : (.10 + halo*.12).toFixed(3)}),inset 0 -2px 0 rgba(var(--fm-accent-rgb),${active ? glowA : (.18 + glow*.18).toFixed(3)}),-4px 5px ${blur1}px rgba(var(--fm-accent-rgb),${accentA}),0 10px ${blur2}px rgba(var(--fm-secondary-accent-rgb),${secondA})`;
    return `0 0 ${blur1}px rgba(var(--fm-accent-rgb),${accentA}),0 0 ${blur2}px rgba(var(--fm-secondary-accent-rgb),${secondA})`;
  };
  if (e.edgeLighting === 'all') {
    lines.push(`html[data-fm-appearance-active="1"] .printer-card,html[data-fm-appearance-active="1"] .plan-cell{border-color:rgba(var(--fm-accent-rgb),${(.18 + glow*.18).toFixed(3)})!important;--fm-ap-glow:${directionalShadow(false)}!important;}`);
  } else if (e.edgeLighting === 'active') {
    lines.push(`html[data-fm-appearance-active="1"] .printer-card.card-active,html[data-fm-appearance-active="1"] .printer-card.run-glow,html[data-fm-appearance-active="1"] .plan-cell:hover{border-color:rgba(var(--fm-accent-rgb),${glowA})!important;--fm-ap-glow:${directionalShadow(true)}!important;}`);
  }

  if (e.hoverLift && !theme.interface.reduceMotion) {
    lines.push('@media (hover:hover) and (pointer:fine){html[data-fm-appearance-active="1"] .printer-card:hover,html[data-fm-appearance-active="1"] .plan-cell:hover{--fm-ap-hover:inset 0 1px 0 rgba(255,255,255,.045),0 10px 26px rgba(var(--fm-black-rgb),.16)!important;}}');
  }

  if (e.shimmerProgress && !theme.interface.reduceMotion) {
    lines.push('@keyframes fmAppearanceShimmer{0%{transform:translateX(-140%)}100%{transform:translateX(220%)}}');
    lines.push('html[data-fm-appearance-active="1"] .card-progress-fill,html[data-fm-appearance-active="1"] .plan-cell-fill,html[data-fm-appearance-active="1"] .wpx-prog i,html[data-fm-appearance-active="1"] .fm-send-fill{position:relative;overflow:hidden;}');
    lines.push('html[data-fm-appearance-active="1"] .card-progress-fill::after,html[data-fm-appearance-active="1"] .plan-cell-fill::after,html[data-fm-appearance-active="1"] .wpx-prog i::after,html[data-fm-appearance-active="1"] .fm-send-fill::after{content:"";position:absolute;inset:0 auto 0 0;width:38%;background:linear-gradient(90deg,transparent,rgba(255,255,255,.42),transparent);animation:fmAppearanceShimmer 2.8s ease-in-out infinite;pointer-events:none;}');
  }

  const progressTargets = 'html[data-fm-appearance-active="1"] .card-progress-fill,html[data-fm-appearance-active="1"] .plan-cell-fill,html[data-fm-appearance-active="1"] .wpx-prog i,html[data-fm-appearance-active="1"] .fm-send-fill';
  if (e.progressStyle === 'glow') {
    lines.push(`${progressTargets}{background:var(--fm-accent)!important;box-shadow:0 0 7px rgba(var(--fm-accent-rgb),.42)!important;}`);
  } else if (e.progressStyle === 'dual') {
    lines.push(`${progressTargets}{background:linear-gradient(90deg,var(--fm-accent),var(--fm-secondary-accent))!important;box-shadow:0 0 8px rgba(var(--fm-accent-rgb),.34)!important;}`);
  }

  if (e.controlStyle === 'glass') {
    lines.push(`html[data-fm-appearance-active="1"] button,html[data-fm-appearance-active="1"] input,html[data-fm-appearance-active="1"] select,html[data-fm-appearance-active="1"] textarea{background-color:rgba(var(--fm-surface-control-rgb),${(0.70 - matte*0.08).toFixed(3)})!important;background-image:linear-gradient(180deg,rgba(255,255,255,${(0.05 + gloss*0.16).toFixed(3)}) 0%,rgba(255,255,255,${(0.015 + gloss*0.04).toFixed(3)}) 18%,rgba(0,0,0,0) 52%,rgba(0,0,0,${(0.035 + matte*0.05).toFixed(3)}) 100%)!important;border-color:rgba(var(--fm-accent-rgb),.22)!important;box-shadow:0 ${Math.round(6 + air*6)}px ${Math.round(16 + air*10)}px rgba(0,0,0,${(0.10 + air*0.08).toFixed(3)}),inset 0 1px 0 rgba(255,255,255,${(0.06 + gloss*0.18).toFixed(3)}),inset 0 -1px 0 rgba(0,0,0,${(0.06 + matte*0.05).toFixed(3)})!important;}`);
    lines.push(`html[data-fm-appearance-active="1"] button:hover{box-shadow:0 ${Math.round(8 + air*8)}px ${Math.round(18 + air*12)}px rgba(0,0,0,${(0.12 + air*0.10).toFixed(3)}),inset 0 1px 0 rgba(255,255,255,${(0.08 + gloss*0.24).toFixed(3)}),inset 0 -1px 0 rgba(0,0,0,${(0.07 + matte*0.05).toFixed(3)})!important;}`);
  } else if (e.controlStyle === 'command') {
    lines.push('html[data-fm-appearance-active="1"] button,html[data-fm-appearance-active="1"] input,html[data-fm-appearance-active="1"] select,html[data-fm-appearance-active="1"] textarea{border-color:rgba(var(--fm-accent-rgb),.24)!important;box-shadow:inset 0 1px 0 rgba(255,255,255,.025),inset 0 -1px 0 rgba(var(--fm-accent-rgb),.07);}');
    lines.push('html[data-fm-appearance-active="1"] button:hover{border-color:rgba(var(--fm-accent-rgb),.50)!important;}');
    if (micro > .001) {
      lines.push(`html[data-fm-appearance-active="1"] button,html[data-fm-appearance-active="1"] input,html[data-fm-appearance-active="1"] select,html[data-fm-appearance-active="1"] textarea{box-shadow:0 ${Math.round(6 + air*8)}px ${Math.round(16 + air*12)}px rgba(0,0,0,${(0.11 + air*0.10).toFixed(3)}),inset 0 1px 0 rgba(255,255,255,${(0.05 + gloss*0.16).toFixed(3)}),inset 0 -1px 0 rgba(0,0,0,${(0.08 + matte*0.08).toFixed(3)}),0 0 ${Math.round(3 + micro*8)}px rgba(var(--fm-accent-rgb),${(0.04 + micro*0.10).toFixed(3)})!important;}`);
      lines.push(`html[data-fm-appearance-active="1"] .status-dot{box-shadow:0 0 ${Math.round(3 + micro*8)}px rgba(var(--fm-accent-rgb),${(0.10 + micro*0.20).toFixed(3)})!important;}`);
    }
  }
  if (focusGlow > .001) {
    const focusA = (.16 + focusGlow * .42).toFixed(3);
    const focusBlur = Math.round(4 + focusGlow * 12);
    lines.push(`html[data-fm-appearance-active="1"] button:focus-visible,html[data-fm-appearance-active="1"] input:focus-visible,html[data-fm-appearance-active="1"] select:focus-visible,html[data-fm-appearance-active="1"] textarea:focus-visible{outline:1px solid rgba(var(--fm-accent-rgb),${focusA})!important;outline-offset:2px!important;box-shadow:0 0 ${focusBlur}px rgba(var(--fm-accent-rgb),${(focusGlow*.30).toFixed(3)})!important;}`);
  }

  // The animated background lives in a module-owned, pointer-transparent layer.
  // Core FM nodes never receive filter, backdrop-filter, z-index, opacity or transform.
  {
    const ambientRoot = `html[data-fm-appearance-active="1"] #${AMBIENT_LAYER_ID}`;
    const flowA = `${ambientRoot} .fm-appearance-ambient-flow-a`;
    const flowB = `${ambientRoot} .fm-appearance-ambient-flow-b`;
    const streams = `${ambientRoot} .fm-appearance-ambient-streams`;
    const streamRay = `${streams} .fm-appearance-stream-ray`;
    const patternLayer = `${ambientRoot} .fm-appearance-ambient-pattern`;
    const flowVisible = animBg !== 'off' && flowOpacity > 0 && (backgroundAnimationStyle === 'flow' || backgroundAnimationStyle === 'mixed' && e.backgroundMixedStyle === 'flow') && (backgroundAnimationStyle !== 'mixed' || e.backgroundFlowMix > 0);
    const streamsVisible = animBg !== 'off' && (backgroundAnimationStyle === 'streams' || backgroundAnimationStyle === 'mixed');
    const flowEnabled = flowVisible && !theme.interface?.reduceMotion;
    const flowBoost = animBg === 'medium' ? 1.34 : 1;
    const mixedScale = backgroundAnimationStyle === 'mixed' ? .76 * e.backgroundFlowMix : 1;
    const flowAlpha = Math.min(.34, flowOpacity * flowBoost * mixedScale);
    const a1 = (flowAlpha * .70).toFixed(3);
    const a2 = (flowAlpha * .52).toFixed(3);
    const a3 = (flowAlpha * .34).toFixed(3);
    const ambientA = (ambient * .18).toFixed(3);
    const ambientB = (ambient * .13).toFixed(3);
    const blurPx = Math.round(42 + flowBlur * (theme.interface.performanceMode === 'economy' ? 32 : 82));
    const scale = (1.04 + flowScale * .34).toFixed(3);
    const durationA = Math.round(126 - flowSpeed * 54);
    const durationB = Math.round(durationA * 1.27);

    lines.push(`${ambientRoot}{position:fixed;inset:-12vmax;z-index:-1;overflow:hidden;pointer-events:none;contain:strict;}`);
    lines.push(`${ambientRoot} .fm-appearance-ambient-procedural{inset:12vmax;overflow:hidden;} ${ambientRoot} .fm-appearance-ambient-canvas{display:block;position:absolute;inset:0;width:100%;height:100%;pointer-events:none;}`);
    lines.push(`${ambientRoot}>span{position:absolute;inset:0;display:block;pointer-events:none;}`);
    lines.push(`html[data-fm-appearance-paused] #${AMBIENT_LAYER_ID} *,html[data-fm-appearance-paused] #${AMBIENT_LAYER_ID} *::after{animation-play-state:paused!important;}`);
    lines.push('html[data-fm-appearance-paused] .card-progress-fill::after,html[data-fm-appearance-paused] .plan-cell-fill::after,html[data-fm-appearance-paused] .wpx-prog i::after,html[data-fm-appearance-paused] .fm-send-fill::after{animation-play-state:paused!important;}');
    if (flowVisible) {
      lines.push(`${flowA},${flowB}{inset:-18%;will-change:transform;transform-origin:center;filter:blur(${blurPx}px) saturate(.82);}`);
      lines.push(`${flowA}{background:conic-gradient(from 214deg at 42% 52%,transparent 0deg,rgba(var(--fm-background-flow-primary-rgb),${a1}) 54deg,rgba(var(--fm-background-flow-secondary-rgb),${a2}) 106deg,transparent 172deg 360deg),radial-gradient(ellipse at 24% 28%,rgba(var(--fm-background-flow-primary-rgb),${ambientA}),transparent 57%);transform:scale(${scale}) rotate(-10deg);}`);
      lines.push(`${flowB}{background:conic-gradient(from 34deg at 64% 46%,transparent 0deg,rgba(var(--fm-background-flow-secondary-rgb),${a2}) 48deg,rgba(var(--fm-background-flow-primary-rgb),${a3}) 118deg,transparent 184deg 360deg),radial-gradient(ellipse at 78% 76%,rgba(var(--fm-background-flow-secondary-rgb),${ambientB}),transparent 55%);transform:scale(${(Number(scale) * 1.08).toFixed(3)}) rotate(12deg);}`);
    } else {
      lines.push(`${flowA},${flowB}{display:none!important;}`);
    }

    if (e.backgroundPattern === 'grid') {
      lines.push(`${patternLayer}{background-image:linear-gradient(rgba(var(--fm-accent-rgb),${pattern.toFixed(3)}) 1px,transparent 1px),linear-gradient(90deg,rgba(var(--fm-accent-rgb),${pattern.toFixed(3)}) 1px,transparent 1px);background-size:32px 32px;}`);
    } else if (e.backgroundPattern === 'micro-lines') {
      lines.push(`${patternLayer}{background-image:repeating-linear-gradient(180deg,rgba(var(--fm-accent-rgb),${(pattern*.65).toFixed(3)}) 0 1px,transparent 1px 7px);}`);
    }

    if (flowEnabled) {
      lines.push('@keyframes fmAppearanceAmbientA{0%{transform:translate3d(-5%,-3%,0) scale(var(--fm-ambient-scale-a,1.2)) rotate(-13deg)}33%{transform:translate3d(4%,-1%,0) scale(var(--fm-ambient-scale-a,1.2)) rotate(2deg)}67%{transform:translate3d(1%,5%,0) scale(var(--fm-ambient-scale-a,1.2)) rotate(14deg)}100%{transform:translate3d(-5%,-3%,0) scale(var(--fm-ambient-scale-a,1.2)) rotate(-13deg)}}');
      lines.push('@keyframes fmAppearanceAmbientB{0%{transform:translate3d(5%,4%,0) scale(var(--fm-ambient-scale-b,1.3)) rotate(15deg)}38%{transform:translate3d(-3%,1%,0) scale(var(--fm-ambient-scale-b,1.3)) rotate(-4deg)}72%{transform:translate3d(2%,-5%,0) scale(var(--fm-ambient-scale-b,1.3)) rotate(-17deg)}100%{transform:translate3d(5%,4%,0) scale(var(--fm-ambient-scale-b,1.3)) rotate(15deg)}}');
      lines.push(`${ambientRoot}{--fm-ambient-scale-a:${scale};--fm-ambient-scale-b:${(Number(scale) * 1.08).toFixed(3)};}`);
      lines.push(`${flowA}{animation:fmAppearanceAmbientA ${durationA}s ease-in-out infinite;}`);
      lines.push(`${flowB}{animation:fmAppearanceAmbientB ${durationB}s ease-in-out infinite;}`);
      lines.push(`@media (prefers-reduced-motion:reduce){${flowA},${flowB}{animation:none!important;}}`);
    }

    if (streamsVisible && !theme.interface?.reduceMotion) {
      lines.push(`${streams}{inset:12vmax;display:block;overflow:hidden;}`);
      lines.push(`${streamRay}{position:absolute;top:var(--fm-stream-y);width:var(--fm-stream-width);height:var(--fm-stream-height);display:block;opacity:0;border-radius:999px;font-style:normal;background:radial-gradient(ellipse at 68% 50%,rgba(255,255,255,.42) 0%,rgba(var(--fm-stream-rgb),.25) 18%,rgba(var(--fm-stream-rgb),.10) 46%,rgba(var(--fm-stream-rgb),0) 76%);box-shadow:0 0 var(--fm-stream-blur) 2px rgba(var(--fm-stream-rgb),.18);mix-blend-mode:screen;will-change:transform,opacity;animation-duration:var(--fm-stream-duration);animation-delay:var(--fm-stream-delay);animation-timing-function:linear;animation-iteration-count:infinite;}`);
      lines.push(`${streamRay}::after{content:"";position:absolute;left:8%;right:8%;top:50%;height:1px;transform:translateY(-50%);border-radius:999px;background:linear-gradient(90deg,transparent,rgba(var(--fm-stream-rgb),.10) 18%,rgba(var(--fm-stream-rgb),.32) 60%,rgba(255,255,255,.46) 76%,transparent);filter:blur(.7px);}`);
      lines.push(`${streamRay}[data-direction="right"]{left:0;animation-name:fmAppearanceStreamToRight;}`);
      lines.push(`${streamRay}[data-direction="left"]{right:0;background:radial-gradient(ellipse at 32% 50%,rgba(255,255,255,.42) 0%,rgba(var(--fm-stream-rgb),.25) 18%,rgba(var(--fm-stream-rgb),.10) 46%,rgba(var(--fm-stream-rgb),0) 76%);animation-name:fmAppearanceStreamToLeft;}`);
      lines.push(`${streamRay}[data-direction="left"]::after{background:linear-gradient(90deg,transparent,rgba(255,255,255,.46) 24%,rgba(var(--fm-stream-rgb),.32) 40%,rgba(var(--fm-stream-rgb),.10) 82%,transparent);}`);
      lines.push(`${streamRay}.fm-appearance-stream-anchor{opacity:var(--fm-stream-opacity);animation-timing-function:ease-in-out;animation-direction:alternate;}`);
      lines.push(`${streamRay}.fm-appearance-stream-anchor[data-direction="right"]{animation-name:fmAppearanceStreamAnchorRight;}`);
      lines.push(`${streamRay}.fm-appearance-stream-anchor[data-direction="left"]{animation-name:fmAppearanceStreamAnchorLeft;}`);
      lines.push('@keyframes fmAppearanceStreamToRight{0%{transform:translate3d(-135%,0,0) scaleX(.82);opacity:0}9%{opacity:var(--fm-stream-opacity)}88%{opacity:var(--fm-stream-opacity)}100%{transform:translate3d(calc(100vw + 135%),0,0) scaleX(1.08);opacity:0}}');
      lines.push('@keyframes fmAppearanceStreamToLeft{0%{transform:translate3d(135%,0,0) scaleX(.82);opacity:0}9%{opacity:var(--fm-stream-opacity)}88%{opacity:var(--fm-stream-opacity)}100%{transform:translate3d(calc(-100vw - 135%),0,0) scaleX(1.08);opacity:0}}');
      lines.push('@keyframes fmAppearanceStreamAnchorRight{from{transform:translate3d(-34vw,0,0) scaleX(.96);opacity:var(--fm-stream-low-opacity)}to{transform:translate3d(5vw,0,0) scaleX(1.04);opacity:var(--fm-stream-opacity)}}');
      lines.push('@keyframes fmAppearanceStreamAnchorLeft{from{transform:translate3d(34vw,0,0) scaleX(.96);opacity:var(--fm-stream-low-opacity)}to{transform:translate3d(-5vw,0,0) scaleX(1.04);opacity:var(--fm-stream-opacity)}}');
      lines.push(`@media (prefers-reduced-motion:reduce){${streams}{display:none!important;}}`);
    } else {
      lines.push(`${streams}{display:none!important;}`);
    }
  }

  // One module-owned neutral light spot follows the rounded perimeter under the pointer.
  // It does not use SVG dashes: screen blending lightens the real blue, orange, green or gray outline below it.
  {
    const glint = `html[data-fm-appearance-active="1"] .${HOVER_GLINT_CLASS}`;
    const cards = 'html[data-fm-appearance-active="1"] .printer-card,html[data-fm-appearance-active="1"] .plan-cell';
    const hover = `html[data-fm-appearance-active="1"] .printer-card:hover>.${HOVER_GLINT_CLASS},html[data-fm-appearance-active="1"] .plan-cell:hover>.${HOVER_GLINT_CLASS}`;
    lines.push(`${cards}{position:relative;}`);
    lines.push(`${glint}{position:absolute;left:0;top:0;width:clamp(52px,32%,92px);height:18px;display:block;pointer-events:none;z-index:2;opacity:0;mix-blend-mode:screen;will-change:left,top,transform,opacity;transition:opacity .16s ease;}`);
    lines.push(`${glint}::before{content:"";position:absolute;inset:0;border-radius:50%;background:radial-gradient(ellipse at center,rgba(255,255,255,.56) 0%,rgba(255,255,255,.22) 28%,rgba(255,255,255,0) 74%);filter:blur(2.2px);}`);
    lines.push(`${glint}::after{content:"";position:absolute;left:15%;right:15%;top:50%;height:1.5px;transform:translateY(-50%);border-radius:999px;background:linear-gradient(90deg,transparent,rgba(255,255,255,.36) 18%,rgba(255,255,255,.94) 50%,rgba(255,255,255,.36) 82%,transparent);box-shadow:0 0 5px rgba(255,255,255,.48);}`);
    if (theme.interface.reduceMotion) {
      lines.push(`${glint}{display:none!important;}`);
    } else {
      lines.push(`@media (hover:hover) and (pointer:fine){${hover}{opacity:${e.hoverGlintIntensity};}}`);
      lines.push(`@media (prefers-reduced-motion:reduce){${glint}{display:none!important;}}`);
    }
  }

  if (e.tableStyle === 'soft-neon') {
    lines.push('html[data-fm-appearance-active="1"] .ex-head,html[data-fm-appearance-active="1"] table thead{box-shadow:inset 0 -1px 0 rgba(var(--fm-accent-rgb),.20);}');
    lines.push('html[data-fm-appearance-active="1"] .ex-row:hover,html[data-fm-appearance-active="1"] table tbody tr:hover{box-shadow:inset 2px 0 0 rgba(var(--fm-accent-rgb),.7);background-color:rgba(var(--fm-accent-rgb),.055)!important;}');
  } else if (e.tableStyle === 'hud') {
    lines.push('html[data-fm-appearance-active="1"] .ex-head,html[data-fm-appearance-active="1"] table thead{background-color:rgba(var(--fm-surface-deep-rgb),.92)!important;box-shadow:inset 0 -1px 0 rgba(var(--fm-accent-rgb),.38);}');
    lines.push('html[data-fm-appearance-active="1"] .ex-row,html[data-fm-appearance-active="1"] table tbody tr{border-bottom-color:rgba(var(--fm-accent-rgb),.10)!important;}html[data-fm-appearance-active="1"] .ex-row:hover,html[data-fm-appearance-active="1"] table tbody tr:hover{background-color:rgba(var(--fm-accent-rgb),.075)!important;box-shadow:inset 2px 0 0 var(--fm-accent);}');
  }

  if (e.statusStyle === 'chip') {
    lines.push('html[data-fm-appearance-active="1"] .status-badge{border:1px solid currentColor!important;border-radius:999px!important;padding:2px 7px!important;background-color:rgba(var(--fm-surface-deep-rgb),.36)!important;}');
  } else if (e.statusStyle === 'underline') {
    lines.push('html[data-fm-appearance-active="1"] .status-badge{border-radius:3px!important;border:0!important;box-shadow:inset 0 -2px 0 currentColor!important;background:transparent!important;padding-left:4px!important;padding-right:4px!important;}');
  }

  if (desat > .001) {
    lines.push(`html[data-fm-appearance-active="1"] .printer-card:not(.run-glow):not(.card-active){--fm-appearance-inactive-desat:${desat.toFixed(3)};}`);
  }
}

export function buildCompatibilityCss(theme) {
  const shadow = Math.max(0, Math.min(1.5, Number(theme.shape.shadowIntensity || 0)));
  const borderWidth = Math.max(1, Math.min(2, Number(theme.shape.borderWidth || 1)));
  const high = !!theme.interface.highContrast;
  const lines = [];

  lines.push(`html[data-fm-appearance-active="1"]{--fm-theme-border-width:${borderWidth}px;--fm-theme-shadow-intensity:${shadow};}`);
  lines.push('html[data-fm-appearance-active="1"] .glass-panel{border-width:var(--fm-theme-border-width);}');
  lines.push('html[data-fm-appearance-active="1"] .printer-card{border-width:var(--fm-theme-border-width);}');
  lines.push('html[data-fm-appearance-active="1"] .fm-module,html[data-fm-appearance-active="1"] [class*="-panel"]{--fm-module-surface:var(--fm-surface-card);--fm-module-border:var(--fm-border);--fm-module-text:var(--fm-text-primary);}');

  addHeaderCompatibility(lines, theme);
  addPrintingGlowCompatibility(lines);
  addFileManagerCompatibility(lines);
  addPremiumEffectsCompatibility(lines, theme);

  if (high) {
    lines.push('html[data-fm-appearance-active="1"]{--fm-border-soft:var(--fm-border);--fm-text-subtle:var(--fm-text-muted);}');
    lines.push('html[data-fm-appearance-active="1"] button:focus-visible,html[data-fm-appearance-active="1"] input:focus-visible,html[data-fm-appearance-active="1"] select:focus-visible,html[data-fm-appearance-active="1"] textarea:focus-visible{outline:2px solid var(--fm-accent)!important;outline-offset:2px!important;}');
  }
  return lines.join('\n');
}
