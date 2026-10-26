// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
import { createDashboardCards, dashboardCss } from './dashboard-cards.js';
import { createGlassLayer } from './glass-layer.js';
import { createPrinterProgress, printerProgressCss } from './printer-progress.js';
import { detailCss } from './detail-style.js';
import { ambientOptions, createAmbientRenderer } from './ambient-renderer.js';
import { resolveProfile } from './theme-profiles.js';
import { firstStored, APPLIED_STORAGE_KEYS, AMBIENT_LAYER_ID, APPLIED_STORAGE_KEY, LEGACY_APPLIED_STORAGE_KEY, OLDER_APPLIED_STORAGE_KEY, FONT_OPTIONS, HOVER_GLINT_CLASS, MODULE_ID, ROOT_ACTIVE_ATTR, ROOT_PREVIEW_ATTR, STYLE_ID } from './theme-schema.js';
import { validateTheme, themeHiddenReason } from './theme-validator.js';
import { buildCompatibilityCss } from './compatibility.js';

const state = {
  installedTheme: null,
  appliedTheme: null,
  previewTheme: null,
  enabled: false,
  emergencyOff: false,
  timer: null,
  listenersReady: false,
  lastError: '',
  appliedHidden: '',
  refreshGeneration: 0,
  refreshController: null,
  glintObserver: null,
  glintListenersReady: false,
  glintAnimationFrame: null,
  glintActiveCards: new Map(),
  streamSignature: '',
  renderedTheme: null,
  motionListenersReady: false,
  forcedPause: false,
  streamSeed: Math.floor(Math.random() * 2147483646) + 1,
  randomSeed: 1,
  streamCursor: 0
};

function hexRgb(hex) {
  const h = String(hex || '').replace('#', '');
  return `${parseInt(h.slice(0, 2), 16)}, ${parseInt(h.slice(2, 4), 16)}, ${parseInt(h.slice(4, 6), 16)}`;
}
function rgbaHex(hex, opacity) {
  const h = String(hex || '').replace('#', '');
  const r = parseInt(h.slice(0, 2), 16), g = parseInt(h.slice(2, 4), 16), b = parseInt(h.slice(4, 6), 16);
  return `rgba(${r},${g},${b},${Number(opacity).toFixed(3)})`;
}
function mixHex(hex, target, amount) {
  const parse = (value) => {
    const h = String(value || '').replace('#', '');
    return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
  };
  const a = parse(hex), b = parse(target);
  const t = Math.max(0, Math.min(1, Number(amount)));
  const out = a.map((value, i) => Math.round(value + (b[i] - value) * t));
  return `#${out.map((value) => value.toString(16).padStart(2, '0')).join('')}`;
}
function headerStateColors(hex) {
  const h = String(hex || '').replace('#', '');
  const r = parseInt(h.slice(0, 2), 16) / 255;
  const g = parseInt(h.slice(2, 4), 16) / 255;
  const b = parseInt(h.slice(4, 6), 16) / 255;
  const luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b;
  const target = luminance > 0.62 ? '#000000' : '#ffffff';
  return { hover: mixHex(hex, target, 0.08), active: mixHex(hex, target, 0.15) };
}
function fontCss(typography) {
  const id = typography && typography.font;
  return (FONT_OPTIONS.find((x) => x.id === id) || FONT_OPTIONS[0]).css;
}
function customFontFaceCss(typography) {
  if (!typography || typography.font !== 'custom' || !typography.customFontDataUrl) return '';
  const format = String(typography.customFontFormat || '');
  const data = String(typography.customFontDataUrl || '').replace(/"/g, '%22');
  return `@font-face{font-family:"FMThemeCustom";src:url("${data}") format("${format}");font-style:normal;font-weight:normal;font-display:swap;}`;
}
function varsForPalette(p, opacity, effects) {
  const surface = (value) => opacity < 0.999 ? rgbaHex(value, opacity) : value;
  const headerStates = headerStateColors(p.headerSurface);
  const flowPrimary = effects.backgroundFlowUseThemeColors ? p.accent : effects.backgroundFlowPrimary;
  const flowSecondary = effects.backgroundFlowUseThemeColors ? effects.secondaryAccent : effects.backgroundFlowSecondary;
  return [
    `--fm-accent:${p.accent}`,
    `--fm-accent-rgb:${hexRgb(p.accent)}`,
    `--fm-background-flow-primary-rgb:${hexRgb(flowPrimary)}`,
    `--fm-background-flow-secondary-rgb:${hexRgb(flowSecondary)}`,
    `--fm-surface-deep:${surface(p.surfaceDeep)}`,
    `--fm-surface-deep-rgb:${hexRgb(p.surfaceDeep)}`,
    `--fm-surface-base-rgb:${hexRgb(p.surfaceBase)}`,
    `--fm-surface-raised-rgb:${hexRgb(p.surfaceRaised)}`,
    `--fm-surface-card-rgb:${hexRgb(p.surfaceCard)}`,
    `--fm-surface-control-rgb:${hexRgb(p.surfaceControl)}`,
    `--fm-surface-base:${surface(p.surfaceBase)}`,
    `--fm-surface-raised:${surface(p.surfaceRaised)}`,
    `--fm-surface-card:${surface(p.surfaceCard)}`,
    `--fm-surface-control:${surface(p.surfaceControl)}`,
    `--fm-border-soft:${p.borderSoft}`,
    `--fm-border-dark:${p.borderSoft}`,
    `--fm-border:${p.border}`,
    `--fm-border-strong:${p.borderStrong}`,
    `--fm-text-primary:${p.textPrimary}`,
    `--fm-text-bright:${p.textPrimary}`,
    `--fm-text-secondary:${p.textSecondary}`,
    `--fm-text-cool:${p.textSecondary}`,
    `--fm-text-muted:${p.textMuted}`,
    `--fm-text-muted-cool:${p.textMuted}`,
    `--fm-text-subtle:${p.textSubtle}`,
    `--fm-success:${p.success}`,
    `--fm-danger:${p.danger}`,
    `--fm-error:${p.danger}`,
    `--fm-warn:${p.warning}`,
    `--fm-amber-56:${p.warning}`,
    `--fm-header-surface:${p.headerSurface}`,
    `--fm-header-hover:${headerStates.hover}`,
    `--fm-header-active:${headerStates.active}`,
    `--fm-header-action:${p.headerAction}`,
    `--fm-header-border:${p.headerBorder}`,
    `--fm-print-glow:${p.accent}`,
    `--fm-print-glow-rgb:${hexRgb(p.accent)}`
  ].join(';');
}
function radiusCss(scale) {
  const px = (n) => `${Math.round(n * scale * 100) / 100}px`;
  return [
    `--fm-theme-radius-sm:${px(4)}`,
    `--fm-theme-radius-md:${px(6)}`,
    `--fm-theme-radius-lg:${px(8)}`,
    `--fm-theme-radius-xl:${px(12)}`,
    `--fm-theme-radius-2xl:${px(16)}`
  ].join(';');
}
function backgroundCss(theme) {
  const bg = theme.background;
  const shell = 'html[data-fm-appearance-active="1"]{background:var(--fm-surface-deep)!important;}html[data-fm-appearance-active="1"] body{position:relative;isolation:isolate;background:linear-gradient(145deg,var(--fm-surface-deep) 0%,rgba(var(--fm-surface-base-rgb),.96) 55%,var(--fm-surface-deep) 100%) fixed!important;}html[data-fm-appearance-active="1"] #app{background-color:transparent!important;background-image:none!important;}';
  if (bg.mode === 'default' || bg.mode === 'solid') return shell;
  const overlay = rgbaHex(bg.overlay, bg.overlayOpacity);
  const image = String(bg.imageDataUrl || '').replace(/"/g, '%22');
  const blur = Math.max(0, Math.min(24, Number(bg.blurPx) || 0));
  return shell + `html[data-fm-appearance-active="1"] #${AMBIENT_LAYER_ID} .fm-appearance-ambient-image{background-color:var(--fm-surface-deep);background-image:linear-gradient(${overlay},${overlay}),url("${image}");background-position:center;background-size:cover;background-repeat:no-repeat;filter:blur(${blur}px);}`;
}
function densityCss(density) {
  if (density === 'compact') return 'html[data-fm-appearance-active="1"]{--fm-theme-density-scale:.88;--fm-theme-control-height:28px;--fm-theme-spacing:8px;}';
  if (density === 'comfortable') return 'html[data-fm-appearance-active="1"]{--fm-theme-density-scale:1.12;--fm-theme-control-height:38px;--fm-theme-spacing:14px;}';
  return 'html[data-fm-appearance-active="1"]{--fm-theme-density-scale:1;--fm-theme-control-height:32px;--fm-theme-spacing:10px;}';
}
function motionCss(reduce) {
  if (!reduce) return '';
  return `html[data-fm-appearance-active="1"] #${AMBIENT_LAYER_ID},html[data-fm-appearance-active="1"] #${AMBIENT_LAYER_ID}::before,html[data-fm-appearance-active="1"] #${AMBIENT_LAYER_ID}::after{animation:none!important;}`;
}

function buildCss(theme) {
  const opacity = Number(theme.shape.surfaceOpacity);
  const radius = Number(theme.shape.radiusScale);
  const effects = theme.effects || {};
  const rootVars = `${radiusCss(radius)};--text-scale:${Number(theme.typography.textScale)};--fm-theme-font:${fontCss(theme.typography)};--fm-secondary-accent:${effects.secondaryAccent};--fm-secondary-accent-rgb:${hexRgb(effects.secondaryAccent)};--fm-theme-glow-strength:${Number(effects.glowStrength)};--fm-theme-halo-strength:${Number(effects.haloStrength)}`;
  return [
    customFontFaceCss(theme.typography),
    `:root[data-fm-appearance-active="1"][data-theme="dark"]{${varsForPalette(theme.dark, opacity, effects)};${rootVars}}`,
    `:root[data-fm-appearance-active="1"][data-theme="light"]{${varsForPalette(theme.light, opacity, effects)};${rootVars}}`,
    'html[data-fm-appearance-active="1"] body,html[data-fm-appearance-active="1"] #app,html[data-fm-appearance-active="1"] button,html[data-fm-appearance-active="1"] input,html[data-fm-appearance-active="1"] select,html[data-fm-appearance-active="1"] textarea{font-family:var(--fm-theme-font)!important;}',
    'html[data-fm-appearance-active="1"] .rounded{border-radius:var(--fm-theme-radius-sm)!important;}html[data-fm-appearance-active="1"] .rounded-md{border-radius:var(--fm-theme-radius-md)!important;}html[data-fm-appearance-active="1"] .rounded-lg{border-radius:var(--fm-theme-radius-lg)!important;}html[data-fm-appearance-active="1"] .rounded-xl{border-radius:var(--fm-theme-radius-xl)!important;}html[data-fm-appearance-active="1"] .rounded-2xl{border-radius:var(--fm-theme-radius-2xl)!important;}',
    densityCss(theme.interface.density),
    motionCss(theme.interface.reduceMotion),
    backgroundCss(theme),
    buildCompatibilityCss(theme), detailCss(theme), printerProgressCss, dashboardCss(theme)
  ].filter(Boolean).join('\n');
}
let glassLayer=null;
let printerProgress=null;
let dashboardCards=null;
function clearGlass(){glassLayer?.dispose();glassLayer=null;}
let ambientRenderer=null,ambientContainer=null,ambientError='';
function clearProcedural(){ambientRenderer?.dispose();ambientRenderer=null;ambientContainer=null;ambientError='';}
function removeStyle() {
  dashboardCards?.dispose(); dashboardCards=null;
  printerProgress?.dispose(); printerProgress=null;
  clearGlass();
  clearProcedural();
  const node = typeof document !== 'undefined' ? document.getElementById(STYLE_ID) : null;
  if (node) node.remove();
  if (typeof document !== 'undefined') {
    const ambient = document.getElementById(AMBIENT_LAYER_ID);
    if (ambient) ambient.remove();
    state.streamSignature = '';
    removeGlintLayers();
    const root = document.documentElement;
    root.removeAttribute(ROOT_ACTIVE_ATTR);
    root.removeAttribute(ROOT_PREVIEW_ATTR);
    root.removeAttribute('data-fm-density');
  }
}
function createGlintLayer() {
  const light = document.createElement('span');
  light.classList.add(HOVER_GLINT_CLASS);
  light.setAttribute('aria-hidden', 'true');
  return light;
}
function attachGlintLayer(card) {
  const exists = Array.from(card.children || []).some((child) => child.classList && child.classList.contains(HOVER_GLINT_CLASS));
  if (!exists && glintAllowed(card)) card.appendChild(createGlintLayer());
}
function glintAllowed(card) {
  const t = state.renderedTheme;
  if (!t || t.interface.reduceMotion || state.forcedPause || document.hidden || window.matchMedia('(prefers-reduced-motion: reduce)').matches || t.effects.hoverGlintIntensity <= 0) return false;
  return card.matches('.printer-card') ? t.effects.hoverGlintPrinters : t.effects.hoverGlintProjects;
}
function attachGlintsWithin(root) {
  if (!root || root.nodeType !== 1) return;
  if (root.matches && root.matches('.printer-card,.plan-cell')) attachGlintLayer(root);
  if (root.querySelectorAll) root.querySelectorAll('.printer-card,.plan-cell').forEach(attachGlintLayer);
}
function pointOnRoundedRect(width, height, radius, distance) {
  const lineX = width - radius * 2;
  const lineY = height - radius * 2;
  const arc = Math.PI * radius / 2;
  const lengths = [lineX, arc, lineY, arc, lineX, arc, lineY, arc];
  let d = distance;
  let segment = 0;
  while (segment < lengths.length - 1 && d > lengths[segment]) { d -= lengths[segment]; segment += 1; }
  if (segment === 0) return { x: radius + d, y: 0, angle: 0 };
  if (segment === 1) { const a = -Math.PI / 2 + d / radius; return { x: width - radius + Math.cos(a) * radius, y: radius + Math.sin(a) * radius, angle: a + Math.PI / 2 }; }
  if (segment === 2) return { x: width, y: radius + d, angle: Math.PI / 2 };
  if (segment === 3) { const a = d / radius; return { x: width - radius + Math.cos(a) * radius, y: height - radius + Math.sin(a) * radius, angle: a + Math.PI / 2 }; }
  if (segment === 4) return { x: width - radius - d, y: height, angle: Math.PI };
  if (segment === 5) { const a = Math.PI / 2 + d / radius; return { x: radius + Math.cos(a) * radius, y: height - radius + Math.sin(a) * radius, angle: a + Math.PI / 2 }; }
  if (segment === 6) return { x: 0, y: height - radius - d, angle: -Math.PI / 2 };
  const a = Math.PI + d / radius;
  return { x: radius + Math.cos(a) * radius, y: radius + Math.sin(a) * radius, angle: a + Math.PI / 2 };
}
function positionGlint(card, startedAt, now) {
  const light = Array.from(card.children || []).find((child) => child.classList && child.classList.contains(HOVER_GLINT_CLASS));
  if (!light) return;
  const width = card.clientWidth;
  const height = card.clientHeight;
  if (width < 8 || height < 8) return;
  const cssRadius = typeof getComputedStyle === 'function' ? parseFloat(getComputedStyle(card).borderTopLeftRadius) : 0;
  const radius = Math.max(1, Math.min(Number.isFinite(cssRadius) ? cssRadius : 12, width / 4, height / 4));
  const perimeter = 2 * (width + height - radius * 4) + Math.PI * radius * 2;
  const distance = ((now - startedAt) / ((state.renderedTheme?.effects.hoverGlintDuration || 6.2) * 1000 / isolatedSpeed) * perimeter) % perimeter;
  const point = pointOnRoundedRect(width, height, radius, distance);
  light.style.left = `${point.x}px`;
  light.style.top = `${point.y}px`;
  light.style.transform = `translate(-50%, -50%) rotate(${point.angle}rad)`;
}
function animateGlints(now) {
  state.glintAnimationFrame = null;
  state.glintActiveCards.forEach((startedAt, card) => {
    if (!card.isConnected || !glintAllowed(card)) state.glintActiveCards.delete(card);
    else positionGlint(card, startedAt, now);
  });
  if (state.glintActiveCards.size && typeof window !== 'undefined') state.glintAnimationFrame = window.requestAnimationFrame(animateGlints);
}
function startGlint(card) {
  if (!glintAllowed(card)) return;
  attachGlintLayer(card);
  const startedAt = typeof performance !== 'undefined' ? performance.now() : 0;
  state.glintActiveCards.set(card, startedAt);
  positionGlint(card, startedAt, startedAt);
  if (!state.glintAnimationFrame && typeof window !== 'undefined') state.glintAnimationFrame = window.requestAnimationFrame(animateGlints);
}
function stopGlint(card) {
  state.glintActiveCards.delete(card);
  if (!state.glintActiveCards.size && state.glintAnimationFrame && typeof window !== 'undefined') {
    window.cancelAnimationFrame(state.glintAnimationFrame);
    state.glintAnimationFrame = null;
  }
}
function glintCardFromEvent(event) {
  const target = event && event.target;
  return target && target.closest ? target.closest('.printer-card,.plan-cell') : null;
}
function onGlintPointerOver(event) {
  if (typeof window !== 'undefined' && window.matchMedia && !window.matchMedia('(hover:hover) and (pointer:fine)').matches) return;
  const card = glintCardFromEvent(event);
  if (!card || (event.relatedTarget && card.contains(event.relatedTarget))) return;
  startGlint(card);
}
function onGlintPointerOut(event) {
  const card = glintCardFromEvent(event);
  if (!card || (event.relatedTarget && card.contains(event.relatedTarget))) return;
  stopGlint(card);
}
function ensureGlintLayers() {
  if (typeof document === 'undefined' || !document.body) return;
  attachGlintsWithin(document.body);
  if (!state.glintObserver && typeof MutationObserver !== 'undefined') {
    state.glintObserver = new MutationObserver((mutations) => {
      mutations.forEach((mutation) => {
        mutation.addedNodes.forEach(attachGlintsWithin);
        const card = mutation.target && mutation.target.closest ? mutation.target.closest('.printer-card,.plan-cell') : null;
        if (card) attachGlintLayer(card);
      });
    });
    state.glintObserver.observe(document.body, { childList: true, subtree: true });
  }
  if (!state.glintListenersReady) {
    document.body.addEventListener('pointerover', onGlintPointerOver);
    document.body.addEventListener('pointerout', onGlintPointerOut);
    document.body.addEventListener('pointercancel', onGlintPointerOut);
    state.glintListenersReady = true;
  }
}
function removeGlintLayers() {
  if (state.glintObserver) {
    state.glintObserver.disconnect();
    state.glintObserver = null;
  }
  if (state.glintAnimationFrame && typeof window !== 'undefined') window.cancelAnimationFrame(state.glintAnimationFrame);
  state.glintAnimationFrame = null;
  state.glintActiveCards.clear();
  if (state.glintListenersReady && typeof document !== 'undefined' && document.body) {
    document.body.removeEventListener('pointerover', onGlintPointerOver);
    document.body.removeEventListener('pointerout', onGlintPointerOut);
    document.body.removeEventListener('pointercancel', onGlintPointerOut);
    state.glintListenersReady = false;
  }
  if (typeof document !== 'undefined') document.querySelectorAll(`.${HOVER_GLINT_CLASS}`).forEach((node) => node.remove());
}
function ensureAmbientLayer() {
  if (typeof document === 'undefined' || !document.body) return null;
  let layer = document.getElementById(AMBIENT_LAYER_ID);
  if (!layer) {
    layer = document.createElement('div');
    layer.id = AMBIENT_LAYER_ID;
    layer.setAttribute('aria-hidden', 'true');
    document.body.prepend(layer);
  }
  ['image', 'flow-a', 'flow-b', 'procedural', 'streams', 'pattern'].forEach((name) => {
    const className = `fm-appearance-ambient-${name}`;
    const exists = Array.from(layer.children).some((child) => child.classList && child.classList.contains(className));
    if (!exists) {
      const part = document.createElement('span');
      part.className = className;
      const pattern = Array.from(layer.children).find((child) => child.classList && child.classList.contains('fm-appearance-ambient-pattern'));
      const before=name==='procedural'?Array.from(layer.children).find(c=>c.classList?.contains('fm-appearance-ambient-streams'))||pattern:pattern;
      if ((name === 'streams'||name==='procedural') && before) layer.insertBefore(part, before); else layer.appendChild(part);
    }
  });
  return layer;
}
function randomBetween(min, max) {
  state.randomSeed = (state.randomSeed * 16807) % 2147483647;
  return min + ((state.randomSeed - 1) / 2147483646) * (max - min);
}
function appendAmbientStream(container, options) {
  const ray = container.children[state.streamCursor++] || document.createElement('i');
  ray.className = `fm-appearance-stream-ray${options.anchor ? ' fm-appearance-stream-anchor' : ''}`;
  ray.dataset.direction = options.direction;
  ray.style.setProperty('--fm-stream-y', `${options.y.toFixed(2)}%`);
  ray.style.setProperty('--fm-stream-width', options.width);
  ray.style.setProperty('--fm-stream-height', `${options.height.toFixed(1)}px`);
  ray.style.setProperty('--fm-stream-duration', `${options.duration.toFixed(2)}s`);
  ray.style.setProperty('--fm-stream-delay', `${options.delay.toFixed(2)}s`);
  ray.style.setProperty('--fm-stream-opacity', options.opacity.toFixed(3));
  ray.style.setProperty('--fm-stream-low-opacity', (options.opacity * .72).toFixed(3));
  ray.style.setProperty('--fm-stream-blur', `${options.blur.toFixed(1)}px`);
  ray.style.setProperty('--fm-stream-rgb', options.secondary ? 'var(--fm-background-flow-secondary-rgb)' : 'var(--fm-background-flow-primary-rgb)');
  if (!ray.parentNode) container.appendChild(ray);
}
function syncAmbientStreams(theme, ambientLayer) {
  if (!ambientLayer) return;
  const container = Array.from(ambientLayer.children).find((child) => child.classList && child.classList.contains('fm-appearance-ambient-streams'));
  if (!container) return;
  const effects = theme.effects || {};
  const style = String(effects.backgroundAnimationStyle || 'flow');
  const intensity = String(effects.animatedBackground || 'off');
  const enabled = !theme.interface.reduceMotion && !window.matchMedia('(prefers-reduced-motion: reduce)').matches && intensity !== 'off' && effects.backgroundFlowOpacity > 0 && (style === 'streams' || style === 'mixed') && (style !== 'mixed' || effects.backgroundStreamsMix > 0);
  if (!enabled) {
    if (container.childNodes.length) container.replaceChildren();
    state.streamSignature = '';
    return;
  }
  const speed = Math.max(0, Math.min(1, Number(effects.backgroundFlowSpeed || 0)));
  const opacity = Math.max(0, Math.min(1, Number(effects.backgroundFlowOpacity || 0)));
  const softness = Math.max(0, Math.min(1, Number(effects.backgroundFlowBlur || 0)));
  const scale = Math.max(0, Math.min(1, Number(effects.backgroundFlowScale || 0)));
  const signature = [style, intensity, speed, opacity, softness, scale, effects.backgroundStreamCount, effects.backgroundStreamsMix, theme.interface.performanceMode].join('|');
  if (state.streamSignature === signature && container.childNodes.length) return;
  state.randomSeed = state.streamSeed;
  state.streamCursor = 0;
  state.streamSignature = signature;

  const intensityBoost = (intensity === 'medium' ? 1.28 : 1) * (style === 'mixed' ? .78 * effects.backgroundStreamsMix : 1);
  const baseOpacity = Math.min(.28, opacity * intensityBoost);
  const minWidth = 500 + scale * 344;
  const maxWidth = 1150 + scale * 860;
  const minHeight = 10 + softness * 10;
  const maxHeight = 20 + softness * 18;
  const minBlur = 10 + softness * 13;
  const maxBlur = 22 + softness * 21;
  const minDuration = 62 - speed * 30;
  const maxDuration = 98 - speed * 40;

  ['right', 'left'].forEach((direction, index) => {
    const duration = randomBetween(94 - speed * 30, 126 - speed * 40);
    appendAmbientStream(container, {
      anchor: true,
      direction,
      y: index === 0 ? randomBetween(18, 38) : randomBetween(64, 84),
      width: `${randomBetween(130 + scale * 19, 148 + scale * 47).toFixed(1)}vw`,
      height: randomBetween(minHeight + 4, maxHeight + 3),
      duration,
      delay: -duration * index / 2,
      opacity: Math.max(.025, Math.min(.16, baseOpacity * randomBetween(.54, .88))),
      blur: randomBetween(minBlur + 2, maxBlur + 4),
      secondary: index === 1
    });
  });

  const count = Math.min(effects.backgroundStreamCount, theme.interface.performanceMode === 'economy' ? 6 : 20);
  for (let index = 0; index < count; index += 1) {
    const direction = index === 0 ? 'right' : index === 1 ? 'left' : (randomBetween(0, 1) < .5 ? 'right' : 'left');
    const duration = randomBetween(minDuration, maxDuration);
    appendAmbientStream(container, {
      anchor: false,
      direction,
      y: randomBetween(5, 96),
      width: `${Math.round(randomBetween(minWidth, maxWidth))}px`,
      height: randomBetween(minHeight, maxHeight),
      duration,
      delay: -randomBetween(0, duration),
      opacity: Math.max(.02, Math.min(.26, baseOpacity * randomBetween(.65, 1.38))),
      blur: randomBetween(minBlur, maxBlur),
      secondary: randomBetween(0, 1) >= .58
    });
  }
  while (container.children.length > state.streamCursor) container.lastElementChild.remove();
}
function syncProcedural(theme,paused){
  const options=ambientOptions(theme,document.documentElement.dataset.theme);
  if(!options){clearProcedural();return;}
  const root=document.getElementById(AMBIENT_LAYER_ID),container=root?.querySelector('.fm-appearance-ambient-procedural');
  if(!container)return;
  if(ambientContainer!==container){clearProcedural();ambientContainer=container;ambientRenderer=createAmbientRenderer(container);if(!ambientRenderer)ambientError='canvas.unavailable';}
  ambientRenderer?.update(options,paused,isolatedSpeed);
}
function syncMotion() {
  const t = state.renderedTheme;
  if (!t || !state.enabled || state.emergencyOff) { clearProcedural(); removeGlintLayers(); return; }
  const paused = document.hidden || state.forcedPause;
  dashboardCards?.update(t, paused);
  document.documentElement.toggleAttribute('data-fm-appearance-paused', paused);
  const reduced = t.interface.reduceMotion || window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  syncProcedural(t,paused||reduced);
  if(t.effects.panelMaterial==='optical-glass'&&!paused&&t.shape.surfaceOpacity<1){
    if(!glassLayer)glassLayer=createGlassLayer(ensureAmbientLayer());
    glassLayer?.update(t);
  }else clearGlass();
  if (paused || reduced || !(t.effects.hoverGlintPrinters || t.effects.hoverGlintProjects) || t.effects.hoverGlintIntensity <= 0) removeGlintLayers();
  else {
    document.querySelectorAll(`.${HOVER_GLINT_CLASS}`).forEach(node => { if (!glintAllowed(node.parentElement)) node.remove(); });
    ensureGlintLayers();
  }
}
function ensureMotionListeners() {
  if (state.motionListenersReady) return;
  state.motionListenersReady = true;
  document.addEventListener('visibilitychange', syncMotion);
  const query = window.matchMedia('(prefers-reduced-motion: reduce)');
  const changed = () => { if (state.renderedTheme && state.enabled) { syncAmbientStreams(state.renderedTheme, ensureAmbientLayer()); syncMotion(); } };
  if (query.addEventListener) query.addEventListener('change', changed); else query.addListener(changed);
}
let profileSource, profilePreview, profileObserver, isolatedSpeed=1;
function apply(theme, preview) {
  if (state.emergencyOff || typeof document === 'undefined') { removeStyle(); return false; }
  const result = validateTheme(theme);
  if (!result.ok) { state.lastError = result.errors.join(', '); removeStyle(); return false; }
  let node = document.getElementById(STYLE_ID);
  if (!node) { node = document.createElement('style'); node.id = STYLE_ID; document.head.appendChild(node); }
  profileSource = result.theme; profilePreview=preview;
  if(!profileObserver && typeof MutationObserver!=='undefined') {
    profileObserver=new MutationObserver(()=>{if(state.enabled&&profileSource)apply(profileSource,profilePreview);});
    profileObserver.observe(document.documentElement,{attributes:true,attributeFilter:['data-theme']});
  }
  result.theme=resolveProfile(result.theme,document.documentElement.dataset.theme);
  const ambientLayer = ensureAmbientLayer();
  state.renderedTheme = result.theme;
  ensureMotionListeners();
  const css = buildCss(result.theme);
  if (node.textContent !== css) node.textContent = css;
  syncAmbientStreams(result.theme, ambientLayer);
  const root = document.documentElement;
  root.setAttribute(ROOT_ACTIVE_ATTR, '1');
  if(!printerProgress)printerProgress=createPrinterProgress();
  printerProgress.update();
  if(result.theme.dashboard.enabled){
    if(!dashboardCards)dashboardCards=createDashboardCards();
    dashboardCards.update(result.theme,state.forcedPause);
  }else{dashboardCards?.dispose();dashboardCards=null;}
  root.setAttribute('data-fm-density', result.theme.interface.density);
  syncMotion();
  if (preview) root.setAttribute(ROOT_PREVIEW_ATTR, '1'); else root.removeAttribute(ROOT_PREVIEW_ATTR);
  state.lastError = '';
  return true;
}
function renderCurrent() {
  if (!state.enabled || state.emergencyOff) { removeStyle(); return; }
  apply(state.previewTheme || state.appliedTheme || state.installedTheme, !!state.previewTheme);
}

export function loadAppliedTheme() {
  state.appliedTheme = null;
  state.appliedHidden = '';
  if (typeof localStorage === 'undefined') return null;
  try {
    const raw = firstStored(APPLIED_STORAGE_KEYS);
    if (!raw || raw === 'null') return null;
    const stored = JSON.parse(raw);
    const checked = validateTheme(stored);
    if (!checked.ok) {
      state.lastError = 'stored_theme.invalid';
      // 0.17.5: редактор говорит, почему применённая тема не показана: её сохранила более новая
      // версия модуля или она повреждена. Прежде вместо неё молча показывалась стартовая тема.
      state.appliedHidden = themeHiddenReason(stored);
      return null;
    }
    state.appliedTheme = checked.theme;
    return checked.theme;
  } catch (_) {
    state.lastError = 'stored_theme.unreadable';
    state.appliedTheme = null;
    state.appliedHidden = 'invalid';
    return null;
  }
}

export function getAppliedTheme() {
  return state.appliedTheme ? JSON.parse(JSON.stringify(state.appliedTheme)) : null;
}

export function setAppliedTheme(theme) {
  const checked = validateTheme(theme);
  if (!checked.ok) return { ok: false, errors: checked.errors, error: 'validation' };
  if (typeof localStorage === 'undefined') return { ok: false, errors: ['storage.unavailable'], error: 'storage' };
  try {
    localStorage.setItem(APPLIED_STORAGE_KEY, JSON.stringify(checked.theme));
  } catch (_) {
    return { ok: false, errors: ['storage.write'], error: 'storage' };
  }
  state.appliedTheme = checked.theme;
  state.appliedHidden = '';
  renderCurrent();
  return { ok: true, theme: checked.theme };
}

export function clearAppliedTheme() {
  if (typeof localStorage !== 'undefined') {
    try { localStorage.setItem(APPLIED_STORAGE_KEY, 'null'); }
    catch (_) { return false; }
  }
  state.appliedTheme = null;
  state.appliedHidden = '';
  renderCurrent();
  return true;
}

async function refreshModuleState() {
  const generation = ++state.refreshGeneration;
  if (state.refreshController) {
    try { state.refreshController.abort(); } catch (_) {}
  }
  const controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
  state.refreshController = controller;
  let timeout = null;
  try {
    if (controller && typeof window !== 'undefined' && window.setTimeout) {
      timeout = window.setTimeout(() => controller.abort(), 4000);
    }
    const response = await fetch('/api/modules', { cache: 'no-store', ...(controller ? { signal: controller.signal } : {}) });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    if (generation !== state.refreshGeneration) return false;
    const own = Array.isArray(data.modules) ? data.modules.find((m) => m.id === MODULE_ID) : null;
    state.enabled = !!(own && !own.disabled && (!own.state || own.state === 'loaded'));
    renderCurrent();
    return state.enabled;
  } catch (error) {
    if (generation !== state.refreshGeneration) return false;
    state.enabled = false;
    state.lastError = String(error && error.message || error);
    removeStyle();
    return false;
  } finally {
    if (timeout !== null && typeof window !== 'undefined' && window.clearTimeout) window.clearTimeout(timeout);
    if (generation === state.refreshGeneration) state.refreshController = null;
  }
}
export function bootstrapThemeRuntime(installedTheme) {
  state.installedTheme = installedTheme;
  state.appliedTheme = null;
  if (typeof window === 'undefined') return;
  try { state.emergencyOff = new URLSearchParams(window.location.search).get('appearance') === 'off'; } catch (_) {}
  if (state.emergencyOff) { removeStyle(); return; }
  loadAppliedTheme();
  refreshModuleState();
  if (!state.timer) state.timer = window.setInterval(() => { if (!document.hidden) refreshModuleState(); }, 10000);
  if (!state.listenersReady) {
    state.listenersReady = true;
    window.addEventListener('focus', refreshModuleState);
    document.addEventListener('visibilitychange', () => { if (!document.hidden) refreshModuleState(); });
  }
}
export function setPreviewTheme(theme) { state.previewTheme = theme; renderCurrent(); }
export function clearPreviewTheme() { state.previewTheme = null; renderCurrent(); }
export function getRuntimeState() { return { enabled: state.enabled, emergencyOff: state.emergencyOff, preview: !!state.previewTheme, applied: !!state.appliedTheme, appliedHidden: state.appliedHidden, lastError: state.lastError, ambientError };  }
export function forceRuntimeRefresh() { return refreshModuleState(); }

// This entry point is used only inside the editor's independent preview frame.
// It neither reads personal storage nor polls the Farm Manager API.
export function renderIsolatedTheme(theme, mode = 'dark', paused = false, speed = 1) {
  isolatedSpeed=speed===3?3:1;
  state.enabled = true;
  state.forcedPause = paused;
  document.documentElement.dataset.theme = mode === 'light' ? 'light' : 'dark';
  return apply(theme, true);
}
