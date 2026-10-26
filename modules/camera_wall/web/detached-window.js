// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
const WINDOW_NAME = '3diwell-camera-wall-detached';
const MESSAGE_TYPE = 'camera-wall-detached-closed';
export const THEME_REQUEST_TYPE = 'camera-wall-detached-theme-request';
export const THEME_UPDATE_TYPE = 'camera-wall-detached-theme-update';

export const THEME_VARIABLES = Object.freeze([
  '--fm-accent', '--fm-accent-rgb',
  '--fm-surface', '--fm-surface-deep', '--fm-surface-base', '--fm-surface-raised', '--fm-surface-card', '--fm-surface-control',
  '--fm-border-soft', '--fm-border', '--fm-border-strong',
  '--fm-text-primary', '--fm-text-secondary', '--fm-text-muted', '--fm-text-subtle',
  '--fm-success', '--fm-warn', '--fm-danger', '--fm-error',
  '--fm-theme-font', '--fm-theme-radius-sm', '--fm-theme-radius-md', '--fm-theme-radius-lg', '--fm-theme-radius-xl', '--fm-theme-radius-2xl',
  '--fm-theme-border-width', '--fm-theme-density', '--fm-theme-density-scale', '--fm-theme-control-height', '--fm-theme-spacing',
  '--fm-module-surface', '--fm-module-border', '--fm-module-text', '--fm-black-rgb',
]);

function token() {
  try { return globalThis.crypto.randomUUID(); } catch (_) { return `cw-${Date.now()}-${Math.random().toString(16).slice(2)}`; }
}

function scriptJson(value) {
  return JSON.stringify(value).replaceAll('<', '\\u003c').replaceAll('>', '\\u003e').replaceAll('&', '\\u0026');
}

export function captureFontFaceRules(documentRef = globalThis.document) {
  const found = [];
  const visit = (rules) => {
    for (const rule of Array.from(rules || [])) {
      const text = String(rule && rule.cssText || '');
      if ((rule && rule.type === 5) || /^@font-face\b/i.test(text.trim())) found.push(text);
      else if (rule && rule.cssRules) { try { visit(rule.cssRules); } catch (_) {} }
    }
  };
  for (const sheet of Array.from((documentRef && documentRef.styleSheets) || [])) {
    try { visit(sheet.cssRules); } catch (_) { /* Cross-origin sheets are intentionally ignored. */ }
  }
  return Array.from(new Set(found.filter(Boolean)));
}

export function captureThemeSnapshot(documentRef = globalThis.document, root = null) {
  const empty = { vars: {}, fontFamily: '', fontSize: '', colorScheme: '', fontFaces: [] };
  try {
    if (!documentRef) return empty;
    const target = root || (documentRef.querySelector && documentRef.querySelector('.cw-root')) || documentRef.documentElement;
    const view = documentRef.defaultView || globalThis;
    if (!target || !view || typeof view.getComputedStyle !== 'function') return { ...empty, fontFaces: captureFontFaceRules(documentRef) };
    const computed = view.getComputedStyle(target);
    const vars = {};
    for (const name of THEME_VARIABLES) {
      const value = String(computed.getPropertyValue(name) || '').trim();
      if (value) vars[name] = value;
    }
    const fontFamily = String(computed.fontFamily || computed.getPropertyValue('font-family') || '').trim();
    const fontSize = String(computed.fontSize || computed.getPropertyValue('font-size') || '').trim();
    const colorScheme = String(computed.colorScheme || computed.getPropertyValue('color-scheme') || '').trim();
    return {
      vars,
      fontFamily,
      fontSize,
      colorScheme: colorScheme && colorScheme !== 'normal' ? colorScheme : '',
      fontFaces: captureFontFaceRules(documentRef),
    };
  } catch (_) { return empty; }
}

export function detachedDocument(options = {}) {
  const lang = options.lang === 'en' ? 'en' : 'ru';
  const vueUrl = String(options.vueUrl || '/vendor/vue.esm-browser.js');
  const moduleUrl = String(options.moduleUrl || '/modules/camera_wall/CameraWallPanel.js');
  const cssUrl = String(options.cssUrl || '/modules/camera_wall/camera-wall.css?v=0.1.13-prototype1');
  const ownerToken = String(options.token || '');
  const themeSnapshot = options.themeSnapshot || { vars: {}, fontFaces: [] };
  return `<!doctype html><html lang="${lang}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>3DIWELL Camera Wall</title><link rel="stylesheet" href=${JSON.stringify(cssUrl)}><script type="importmap">${JSON.stringify({ imports: { vue: vueUrl } })}</script></head><body style="margin:0"><div id="camera-wall-detached"></div><script type="module">
import { createApp } from 'vue';
import CameraWallPanel from ${JSON.stringify(moduleUrl)};
const ownerToken = ${scriptJson(ownerToken)};
const allowedThemeVariables = new Set(${scriptJson(THEME_VARIABLES)});
const state = window.__cwDetached = { mounted:false, cleanup:false, ownerToken, themeApplyCount:0 };
let app;
let cleaned = false;
function applyTheme(snapshot){
  if(!snapshot || typeof snapshot!=='object') return;
  const vars = snapshot.vars && typeof snapshot.vars==='object' ? snapshot.vars : {};
  for(const [name,value] of Object.entries(vars)){
    if(allowedThemeVariables.has(name) && value!=null && String(value).trim()) document.documentElement.style.setProperty(name,String(value));
  }
  const fontFamily = String(snapshot.fontFamily||'').trim();
  if(fontFamily){ document.documentElement.style.fontFamily=fontFamily; document.body.style.fontFamily=fontFamily; document.documentElement.style.setProperty('--fm-theme-font',fontFamily); }
  const fontSize = String(snapshot.fontSize||'').trim();
  if(fontSize) document.documentElement.style.fontSize=fontSize;
  const colorScheme = String(snapshot.colorScheme||'').trim();
  if(colorScheme) document.documentElement.style.colorScheme=colorScheme;
  let fontStyle = document.getElementById('camera-wall-detached-font-faces');
  if(!fontStyle){ fontStyle=document.createElement('style'); fontStyle.id='camera-wall-detached-font-faces'; document.head.appendChild(fontStyle); }
  fontStyle.textContent = Array.isArray(snapshot.fontFaces) ? snapshot.fontFaces.join('\\n') : '';
  state.themeApplyCount += 1;
  state.theme = { vars:{...vars}, fontFamily, fontFaceCount:Array.isArray(snapshot.fontFaces)?snapshot.fontFaces.length:0 };
}
function cleanup(){
  if(cleaned) return;
  cleaned = true;
  try { if(app) app.unmount(); } catch(_) {}
  state.cleanup = document.querySelectorAll('.cw-media-host img,.cw-media-host video').length === 0;
  try { if(window.opener && !window.opener.closed) window.opener.postMessage({type:${JSON.stringify(MESSAGE_TYPE)},token:${JSON.stringify(ownerToken)},cleanup:state.cleanup}, location.origin); } catch(_) {}
}
function requestTheme(){ try { if(window.opener && !window.opener.closed) window.opener.postMessage({type:${scriptJson(THEME_REQUEST_TYPE)},token:ownerToken},location.origin); } catch(_) {} }
addEventListener('message',(event)=>{ if(event.source===window.opener && event.origin===location.origin && event.data && event.data.type===${scriptJson(THEME_UPDATE_TYPE)} && event.data.token===ownerToken) applyTheme(event.data.snapshot); });
addEventListener('focus',requestTheme);
applyTheme(${scriptJson(themeSnapshot)});
const root = { data:()=>({wallOpen:true}), methods:{ closeWall(){ this.wallOpen=false; queueMicrotask(()=>window.close()); } }, template:'<camera-wall-panel :open="wallOpen" :detached="true" lang="${lang}" @close="closeWall"></camera-wall-panel>' };
app = createApp(root);
app.component('svg-icon',{props:['name'],template:'<span :data-icon="name" aria-hidden="true">◉</span>'});
app.component('camera-wall-panel',CameraWallPanel);
app.mount('#camera-wall-detached');
state.mounted = true;
addEventListener('pagehide',cleanup,{once:true});
addEventListener('beforeunload',cleanup,{once:true});
</script></body></html>`;
}

export class DetachedWindowController {
  constructor(options = {}) {
    this.env = options.env || globalThis;
    this.onBeforeOpen = options.onBeforeOpen || (() => {});
    this.onBlocked = options.onBlocked || (() => {});
    this.onClosed = options.onClosed || (() => {});
    this.documentOptions = options.documentOptions || {};
    this.captureTheme = options.captureTheme || (() => captureThemeSnapshot(this.env.document));
    this.child = null;
    this.ownerToken = '';
    this.pollTimer = null;
    this.boundMessage = (event) => {
      if (!this.child || event.source !== this.child || event.origin !== this.env.location.origin) return;
      if (!event.data || event.data.token !== this.ownerToken) return;
      if (event.data.type === MESSAGE_TYPE) this.finish(!!event.data.cleanup);
      else if (event.data.type === THEME_REQUEST_TYPE) {
        try { this.child.postMessage({ type: THEME_UPDATE_TYPE, token: this.ownerToken, snapshot: this.captureTheme() }, this.env.location.origin); } catch (_) {}
      }
    };
  }

  open(lang = 'ru') {
    if (this.child && !this.child.closed) { try { this.child.focus(); } catch (_) {} return true; }
    const child = this.env.open('', WINDOW_NAME, 'popup=yes,width=1280,height=800,resizable=yes,scrollbars=yes');
    if (!child) { this.onBlocked(); return false; }
    this.child = child;
    this.ownerToken = token();
    try {
      this.onBeforeOpen();
      const themeSnapshot = this.captureTheme();
      this.env.addEventListener('message', this.boundMessage);
      child.document.open();
      child.document.write(detachedDocument({ ...this.documentOptions, lang, token: this.ownerToken, themeSnapshot }));
      child.document.close();
      this.pollTimer = this.env.setInterval(() => { if (!this.child || this.child.closed) this.finish(false); }, 500);
      return true;
    } catch (error) {
      try { child.close(); } catch (_) {}
      this.finish(false);
      this.onBlocked(error);
      return false;
    }
  }

  finish(cleanup) {
    if (this.pollTimer != null) { this.env.clearInterval(this.pollTimer); this.pollTimer = null; }
    this.env.removeEventListener('message', this.boundMessage);
    const hadChild = !!this.child;
    this.child = null;
    this.ownerToken = '';
    if (hadChild) this.onClosed(cleanup);
  }

  close() {
    const child = this.child;
    if (child && !child.closed) { try { child.close(); } catch (_) {} }
    this.finish(false);
  }
}
