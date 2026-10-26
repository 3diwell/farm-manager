// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
import { firstStored, APPLIED_STORAGE_KEYS, DRAFT_STORAGE_KEYS, DRAFT_STORAGE_KEY, APPLIED_STORAGE_KEY, LEGACY_DRAFT_STORAGE_KEY, LEGACY_APPLIED_STORAGE_KEY, OLDER_APPLIED_STORAGE_KEY, OLDER_DRAFT_STORAGE_KEY, SAVED_THEMES_KEY, EDITOR_STATE_KEY } from './theme-schema.js';
import { cloneTheme, validateTheme, themeHiddenReason } from './theme-validator.js';

export function signature(theme) {
  const text = JSON.stringify(theme);
  let hash = 2166136261;
  for (let i = 0; i < text.length; i++) hash = Math.imul(hash ^ text.charCodeAt(i), 16777619);
  return `${text.length}:${hash >>> 0}`;
}
export function readDraft(current) {
  try {
    let raw=null;
    for(let i=0;i<DRAFT_STORAGE_KEYS.length;i++){
      const value=localStorage.getItem(DRAFT_STORAGE_KEYS[i]);
      if(value!==null){raw=value;break;}
      if(localStorage.getItem(APPLIED_STORAGE_KEYS[i])!==null)break;
    }
    const parsed = JSON.parse(raw || 'null');
    if (!parsed) return null;
    if (parsed.draftVersion === 1) {
      let matchingBase=parsed.base===signature(current);
      if(!matchingBase&&localStorage.getItem(APPLIED_STORAGE_KEY)===null){
        const previous=JSON.parse(firstStored(APPLIED_STORAGE_KEYS.slice(1))??'null');
        const checked=previous&&validateTheme(previous);
        matchingBase=!!(checked?.ok&&signature(checked.theme)===signature(current)&&parsed.base===signature(previous));
      }
      if (!matchingBase) return { stale: true, theme: parsed.theme };
      return signature(parsed.theme) === signature(current) ? null : parsed;
    }
    const checked = validateTheme(parsed);
    return checked.ok && signature(checked.theme) !== signature(current) ? { theme: checked.theme } : null;
  } catch (_) { return null; }
}
export function writeDraft(theme, current) {
  try {
    // A null sentinel prevents a superseded legacy draft from being restored again.
    if (signature(theme) === signature(current)) {
      // 0.17.5: незаконченный черновик более новой версии модуля не затирается — он вернётся вместе с ней.
      let stored = null;
      try { stored = JSON.parse(localStorage.getItem(DRAFT_STORAGE_KEY) || 'null'); } catch (_) { /* битый черновик можно затереть */ }
      if (stored?.draftVersion === 1 && themeHiddenReason(stored.theme) === 'newer') return true;
      localStorage.setItem(DRAFT_STORAGE_KEY, 'null');
    }
    else localStorage.setItem(DRAFT_STORAGE_KEY, JSON.stringify({ draftVersion: 1, base: signature(current), savedAt: Date.now(), theme }));
    return true;
  } catch (_) { return false; }
}
const STORE_KEY='fm_appearance_library_v4';
const ASSET_PATHS=[['background','imageDataUrl'],['typography','customFontDataUrl']];
const own=(o,k)=>Object.prototype.hasOwnProperty.call(o,k);
// 0.17.5: kept — темы, которые эта версия показать не может (см. unpackCollection). Они пишутся обратно
// как были, вместе со своими вложениями (фон, шрифт): версия, которая их понимает, найдёт их на месте.
function assetRefs(nodes){
  const ids=new Set(),walk=v=>{
    if(!v||typeof v!=='object')return;
    if(!Array.isArray(v)&&typeof v.asset==='string'&&Object.keys(v).length===1)ids.add(v.asset);
    for(const k of Object.keys(v))walk(v[k]);
  };
  nodes.forEach(walk);return ids;
}
export function packCollection(entries,history=[],kept=null) {
  const assets=Object.create(null);
  if(kept)for(const id of assetRefs([...kept.entries,...kept.history]))if(own(kept.assets,id)&&typeof kept.assets[id]==='string')assets[id]=kept.assets[id];
  const pack=entry=>{
    const copy=cloneTheme(entry);
    for(const [section,key] of ASSET_PATHS) {
      const value=copy.theme[section][key];if(!value)continue;
      const base='a'+signature(value).replace(':','_');let id=base,n=0;
      while(own(assets,id)&&assets[id]!==value) id=base+'_'+(++n);
      assets[id]=value;copy.theme[section][key]={asset:id};
    }
    return copy;
  };
  return {format:'3diwell-appearance-collection',version:2,entries:[...entries.map(pack),...(kept?.entries||[])],history:[...history.map(pack),...(kept?.history||[])],assets};
}
export function unpackCollection(data,lenient=false) {
  if(lenient&&data?.format==='3diwell-appearance-collection'&&Number(data.version)>2)throw Error('newer');
  if(!data||data.format!=='3diwell-appearance-collection'||data.version!==2||!Array.isArray(data.entries)||data.entries.length>20||!Array.isArray(data.history)||data.history.length>5||!data.assets||typeof data.assets!=='object'||Array.isArray(data.assets))throw Error('collection');
  if(Object.keys(data.assets).length>50)throw Error('assets');
  const unpack=(entry,isHistory)=>{
    if(!entry||typeof entry.id!=='string'||entry.id.length>160||typeof entry.name!=='string'||!entry.name.trim()||entry.name.length>100||/[<>]/.test(entry.name))throw Error('entry');
    const theme=cloneTheme(entry.theme);
    for(const [section,key] of ASSET_PATHS) {
      const value=theme?.[section]?.[key];
      if(value&&typeof value==='object') {
        if(Object.keys(value).length!==1||typeof value.asset!=='string'||!/^a[0-9_]+$/.test(value.asset)||!own(data.assets,value.asset)||typeof data.assets[value.asset]!=='string')throw Error('asset');
        theme[section][key]=data.assets[value.asset];
      }
    }
    const checked=validateTheme(theme);if(!checked.ok)throw Error('theme');
    if(isHistory&&(!Number.isFinite(entry.appliedAt)||entry.appliedAt<0))throw Error('date');
    return {id:entry.id,name:entry.name,theme:checked.theme,...(isHistory?{appliedAt:entry.appliedAt}:{})};
  };
  if(!lenient){
    const entries=data.entries.map(e=>unpack(e,false)),history=data.history.map(e=>unpack(e,true));
    if(new Set(entries.map(e=>e.id)).size!==entries.length)throw Error('duplicate');
    return {entries,history};
  }
  // 0.17.5: хранилище читается по одной теме. Тема, которую эта версия показать не может (её сохранила
  // более новая версия модуля или она повреждена), не прячет остальные: она откладывается как есть,
  // при записи возвращается на место, а редактор говорит, сколько тем скрыто и почему.
  const entries=[],history=[],kept={entries:[],history:[],assets:data.assets},hidden={newer:0,invalid:0},ids=new Set();
  for(const raw of data.entries){
    try{const e=unpack(raw,false);if(ids.has(e.id))throw Error('duplicate');ids.add(e.id);entries.push(e);}
    catch(_){kept.entries.push(raw);hidden[themeHiddenReason(raw?.theme)]++;}
  }
  for(const raw of data.history){try{history.push(unpack(raw,true));}catch(_){kept.history.push(raw);}}
  return {entries,history,kept,hidden};
}
function readStore() {
  const raw=localStorage.getItem(STORE_KEY)??localStorage.getItem('fm_appearance_library_v3')??localStorage.getItem('fm_appearance_library_v2');
  if(raw!==null)return unpackCollection(JSON.parse(raw),true);
  const entries=JSON.parse(localStorage.getItem(SAVED_THEMES_KEY)||'[]');
  return {entries:Array.isArray(entries)?entries.slice(0,20).flatMap(entry=>{
    if(!entry||typeof entry.id!=='string'||typeof entry.name!=='string')return [];
    const checked=validateTheme(entry.theme);
    return checked.ok?[{id:entry.id,name:entry.name.slice(0,100),theme:checked.theme}]:[];
  }):[],history:[],kept:null,hidden:{newer:0,invalid:0}};
}
export function readCollection(){try{return readStore().entries;}catch(_){return [];}}
// 0.17.5: выгрузка «Мои темы» — полная копия списка: скрытые темы идут в файл как есть, со своими вложениями.
export function exportLibrary(entries){let kept=null;try{kept=readStore().kept;}catch(_){}return packCollection(entries,[],kept&&{...kept,history:[]});}
export function readAppliedHistory(){try{return readStore().history;}catch(_){return [];}}
// 0.17.5: что из «Мои темы» не показано и почему — для предупреждения в редакторе. unreadable — весь
// список не читается: 'newer' (формат более новой версии модуля) или 'invalid' (данные повреждены).
export function readLibraryState(){
  try{const store=readStore();return {newer:store.hidden.newer,invalid:store.hidden.invalid,unreadable:''};}
  catch(error){return {newer:0,invalid:0,unreadable:error?.message==='newer'?'newer':'invalid'};}
}
function writeStore(entries,history,kept=null){
  const packed=packCollection(entries,history,kept),check=unpackCollection(packed,true);
  if(check.entries.length!==entries.length||check.history.length!==history.length)throw Error('pack');
  // One atomic write: references and assets always commit together. Legacy data is retained.
  localStorage.setItem(STORE_KEY,JSON.stringify(packed));
}
export function writeCollection(entries){try{const store=readStore();writeStore(entries,store.history,store.kept);return true;}catch(_){return false;}}
export function recordAppliedTheme(theme){try{
  const store=readStore(),entry={...themeEntry(theme,theme.meta.name),appliedAt:Date.now()};
  // Скрытые записи истории остаются, пока они среди пяти последних применений.
  const keptHistory=store.kept?.history||[],when=e=>Number.isFinite(e?.appliedAt)?e.appliedAt:0;
  const latest=[entry,...(keptHistory.length?[...store.history,...keptHistory].sort((a,b)=>when(b)-when(a)):store.history)].slice(0,5);
  writeStore(store.entries,latest.filter(e=>!keptHistory.includes(e)),store.kept&&{...store.kept,history:latest.filter(e=>keptHistory.includes(e))});return true;
}catch(_){return false;}}
// 0.17.5: коллекция добавляется по одной теме; что не добавлено и почему — в skipped.
export function importCollection(data){
  const incoming=unpackCollection(data,true);let current;
  try{current=readStore();}catch(_){throw Error('store');}
  if(!incoming.entries.length&&(incoming.hidden.newer||incoming.hidden.invalid))throw Error(incoming.hidden.newer?'newer':'theme');
  if(current.entries.length+(current.kept?.entries.length||0)+incoming.entries.length>20)throw Error('limit');
  const next=[...current.entries,...incoming.entries.map(e=>themeEntry(e.theme,e.name))];
  writeStore(next,current.history,current.kept);return {entries:next,skipped:incoming.hidden};
}
export function appearanceSignature(theme){const copy=cloneTheme(theme);delete copy.meta;return signature(copy);}
export function themeEntry(theme, name) {
  const copy = cloneTheme(theme);
  copy.meta.name = name;
  return { id: typeof crypto.randomUUID === 'function' ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`, name, theme: copy };
}
export function readEditorState() {
  try { return JSON.parse(localStorage.getItem(EDITOR_STATE_KEY) || '{}') || {}; } catch (_) { return {}; }
}
export function writeEditorState(value) {
  try { localStorage.setItem(EDITOR_STATE_KEY, JSON.stringify(value)); } catch (_) { /* Optional navigation preference. */ }
}
