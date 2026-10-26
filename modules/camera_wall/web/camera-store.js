// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
const STORAGE_KEY = '3diwell.camera_wall.ip_sources.v1';
const SELECTION_KEY = '3diwell.camera_wall.selected.v1';
const OPERATIONAL_KEY = '3diwell.camera_wall.operational.v1';
const MODES = new Set(['snapshot', 'mjpeg']);
const PERFORMANCE_MODES = new Set(['auto', 'economy']);
const SMART_MODES = new Set(['manual', 'online', 'printing', 'printing-attention']);

function storageOrNull(storage) {
  if (storage) return storage;
  try { return globalThis.localStorage || null; } catch (_) { return null; }
}

export function validateIpCameraUrl(raw) {
  const value = String(raw || '').trim();
  if (!value || value.length > 2048) return { ok: false, reason: 'invalid_url' };
  let parsed;
  try { parsed = new URL(value); } catch (_) { return { ok: false, reason: 'invalid_url' }; }
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') return { ok: false, reason: 'unsupported_scheme' };
  if (parsed.username || parsed.password) return { ok: false, reason: 'embedded_credentials' };
  if (!parsed.hostname) return { ok: false, reason: 'invalid_url' };
  return { ok: true, url: parsed.href };
}

export function normalizeIpCamera(input) {
  const checked = validateIpCameraUrl(input && input.url);
  if (!checked.ok) return checked;
  const name = String((input && input.name) || '').trim().slice(0, 80);
  const mode = MODES.has(input && input.mode) ? input.mode : 'snapshot';
  const fit = input && input.fit === 'cover' ? 'cover' : 'contain';
  if (!name) return { ok: false, reason: 'name_required' };
  const rawId = String((input && input.id) || '').replace(/[^a-zA-Z0-9_-]/g, '').slice(0, 64);
  const id = rawId || ('ip_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2, 8));
  return { ok: true, camera: { id, sourceKind: 'ip', name, url: checked.url, mode, fit } };
}

export function normalizeOperationalState(input) {
  if (!input || typeof input !== 'object') return null;
  const selectedIds = Array.from(new Set((Array.isArray(input.selectedIds) ? input.selectedIds : []).map(String))).slice(0, 25);
  const pinnedIds = Array.from(new Set((Array.isArray(input.pinnedIds) ? input.pinnedIds : []).map(String))).slice(0, 25);
  const ipCameras = (Array.isArray(input.ipCameras) ? input.ipCameras : []).map(normalizeIpCamera).filter((item) => item.ok).map((item) => item.camera).slice(0, 25);
  return {
    mode: PERFORMANCE_MODES.has(input.mode) ? input.mode : 'auto',
    smartMode: SMART_MODES.has(input.smartMode) ? input.smartMode : 'manual',
    selectedIds,
    pinnedIds,
    ipCameras,
  };
}

// 16.10.2026: список IP-камер хранится на сервере, в настройке фермы module_ui.camera_wall.ip_sources:
// добавили камеру на одном компьютере — она видна на всех. localStorage остаётся зеркалом и запасным путём:
// старая программа module_ui не знает, а у кого нет права менять настройки фермы, запись не пройдёт.
const MODULE_ID = 'camera_wall';
const SEEDED_KEY = '3diwell.camera_wall.ip_sources.seeded.v1';
const SETTINGS_URL = '/api/farm-settings';

function cleanList(list) {
  return (Array.isArray(list) ? list : []).map(normalizeIpCamera).filter((x) => x.ok).map((x) => x.camera).slice(0, 25);
}

// Ответ GET /api/farm-settings -> { supported, present, list }. supported — программа вернула module_ui;
// present — для видеостены там уже лежит список (возможно, пустой: камеры удалили на другом компьютере).
export function serverIpSourcesFrom(response) {
  const root = response && typeof response === 'object' ? response : {};
  const settings = root.settings && typeof root.settings === 'object' ? root.settings : root;
  const ui = settings.module_ui && typeof settings.module_ui === 'object' ? settings.module_ui
    : (root.module_ui && typeof root.module_ui === 'object' ? root.module_ui : null);
  if (!ui) return { supported: false, present: false, list: [] };
  const mine = ui[MODULE_ID];
  const raw = mine && typeof mine === 'object' && Array.isArray(mine.ip_sources) ? mine.ip_sources : null;
  return { supported: true, present: raw !== null, list: cleanList(raw) };
}

// Чей список показывать при открытии стены. -> { list, seed, mirror, source }
//  * на сервере есть камеры — они и показываются, а localStorage их зеркалит; при ПЕРВОЙ встрече этого
//    браузера с сервером его собственные камеры, которых на сервере нет, добавляются к списку (merge) —
//    иначе камеры, заведённые на втором компьютере до 16.10.2026, пропали бы;
//  * на сервере пусто, а в этом браузере камеры есть и сюда их ещё не переносили — переносим один раз (seed);
//  * на сервере список есть, но пустой (удалили на другом компьютере) — пусто и здесь;
//  * сервер о списке ничего не знает — остаётся то, что в этом браузере. 16.10.2026: и ничего не переносится —
//    «не знает» бывает и при сбое чтения у новой программы, и перенос тогда затёр бы камеры других компьютеров.
export function reconcileIpSources(server, localList, seeded) {
  const local = cleanList(localList);
  const srv = server && typeof server === 'object' ? server : { supported: false, present: false, list: [] };
  const srvList = cleanList(srv.list);
  if (srv.supported && srvList.length) {
    if (local.length && !seeded) {
      const known = new Set(srvList.map((c) => c.url));
      const ids = new Set(srvList.map((c) => c.id));
      const extra = local.filter((c) => !known.has(c.url) && !ids.has(c.id));
      if (extra.length) return { list: srvList.concat(extra).slice(0, 25), seed: true, mirror: true, source: 'merge' };
    }
    return { list: srvList, seed: false, mirror: true, source: 'server' };
  }
  if (srv.supported && local.length && !seeded) return { list: local, seed: true, mirror: false, source: 'local-seed' };
  if (srv.supported && srv.present) return { list: srvList, seed: false, mirror: true, source: 'server' };
  return { list: local, seed: false, mirror: false, source: 'local' };
}

// Одна правка списка: { add: камера } или { remove: id }. Повторное добавление той же камеры (тот же id)
// ничего не меняет, удаление отсутствующей — тоже. Две камеры с одним адресом, но разными id, допустимы —
// как и при добавлении в самой стене.
export function applyIpChange(list, change) {
  const cur = cleanList(list);
  const ch = change && typeof change === 'object' ? change : {};
  if (ch.add) {
    const cam = cleanList([ch.add])[0];
    if (!cam || cur.some((c) => c.id === cam.id)) return cur;
    return cur.concat([cam]).slice(0, 25);
  }
  if (ch.remove) return cur.filter((c) => c.id !== ch.remove);
  return cur;
}

// 16.10.2026: правка уходит на сервер поверх СВЕЖЕГО списка сервера, а не всем списком, который этот браузер
// загрузил при открытии стены: стена, открытая весь день на одном компьютере, иначе затирала бы камеры,
// добавленные на другом. Браузер, который со списком сервера ещё не сверялся, добавляет и свои камеры
// (как при открытии стены). -> { ok, list }: ok=false — сервер списка не знает (старая программа, сбой
// чтения) или запись не прошла; тогда список этого браузера остаётся как есть.
export async function applyServerIpChange(fetchFn, change, localList, seeded) {
  const srv = await fetchServerIpSources(fetchFn);
  if (!srv.supported) return { ok: false, list: null };
  const base = seeded ? srv.list : reconcileIpSources(srv, localList, false).list;
  const list = applyIpChange(base, change);
  const ok = await pushServerIpSources(fetchFn, list);
  return { ok, list: ok ? list : null };
}

export function serverPayload(list) {
  const ipSources = cleanList(list).map((c) => ({ id: c.id, name: c.name, url: c.url, mode: c.mode, fit: c.fit }));
  return { module_ui: { [MODULE_ID]: { ip_sources: ipSources } } };
}

export async function fetchServerIpSources(fetchFn) {
  try {
    const response = await fetchFn(SETTINGS_URL, { credentials: 'same-origin', cache: 'no-store' });
    if (!response || !response.ok) return { supported: false, present: false, list: [] };
    return serverIpSourcesFrom(await response.json());
  } catch (_) { return { supported: false, present: false, list: [] }; }
}

// -> true, только если сервер принял список (ok). Отказ — не ошибка: список остаётся в этом браузере.
export async function pushServerIpSources(fetchFn, list) {
  try {
    const response = await fetchFn(SETTINGS_URL, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(serverPayload(list)),
    });
    if (!response || !response.ok) return false;
    const answer = await response.json();
    return !!(answer && answer.ok);
  } catch (_) { return false; }
}

export class CameraStore {
  constructor(storage) { this.storage = storageOrNull(storage); }

  isIpSourcesSeeded() {
    if (!this.storage) return false;
    try { return this.storage.getItem(SEEDED_KEY) === '1'; } catch (_) { return false; }
  }

  markIpSourcesSeeded() {
    if (!this.storage) return false;
    try { this.storage.setItem(SEEDED_KEY, '1'); return true; } catch (_) { return false; }
  }

  loadIpCameras() {
    if (!this.storage) return [];
    try {
      const value = JSON.parse(this.storage.getItem(STORAGE_KEY) || '[]');
      if (!Array.isArray(value)) return [];
      return value.map(normalizeIpCamera).filter((x) => x.ok).map((x) => x.camera).slice(0, 25);
    } catch (_) { return []; }
  }

  saveIpCameras(cameras) {
    if (!this.storage) return false;
    const safe = (Array.isArray(cameras) ? cameras : []).map(normalizeIpCamera).filter((x) => x.ok).map((x) => x.camera).slice(0, 25);
    try { this.storage.setItem(STORAGE_KEY, JSON.stringify(safe)); return true; } catch (_) { return false; }
  }

  loadSelection() {
    if (!this.storage) return [];
    try {
      const value = JSON.parse(this.storage.getItem(SELECTION_KEY) || '[]');
      return Array.isArray(value) ? value.map(String).slice(0, 25) : [];
    } catch (_) { return []; }
  }

  saveSelection(ids) {
    if (!this.storage) return false;
    try { this.storage.setItem(SELECTION_KEY, JSON.stringify(Array.from(ids || []).map(String).slice(0, 25))); return true; } catch (_) { return false; }
  }

  loadOperationalState() {
    if (!this.storage) return null;
    try { return normalizeOperationalState(JSON.parse(this.storage.getItem(OPERATIONAL_KEY) || 'null')); }
    catch (_) { return null; }
  }

  saveOperationalState(state) {
    if (!this.storage) return false;
    const safe = normalizeOperationalState(state);
    if (!safe) return false;
    try {
      this.storage.setItem(OPERATIONAL_KEY, JSON.stringify(safe));
      this.storage.setItem(SELECTION_KEY, JSON.stringify(safe.selectedIds));
      this.storage.setItem(STORAGE_KEY, JSON.stringify(safe.ipCameras));
      return true;
    } catch (_) { return false; }
  }
}
