// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
export const SOURCE_FILTERS = Object.freeze(['all', 'online', 'printing', 'attention', 'offline', 'selected']);
export const SMART_WALL_MODES = Object.freeze(['manual', 'online', 'printing', 'printing-attention']);
export const TELEMETRY_STALE_SECONDS = 60;

function normalized(value) {
  return String(value || '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
}

export function resolveCameraCapability(printer) {
  const type = normalized(printer && printer.type);
  if (type === 'bambu') return 'confirmed';
  // 12.10.2026: FlashForge — у Adventurer 5M Pro камера штатная, у 5M покупается отдельно.
  if (type === 'flashforge') {
    const ffIdentity = normalized(`${printer && printer.model || ''} ${printer && printer.model_key || ''}`);
    return /\b5m pro\b/.test(ffIdentity) ? 'confirmed' : 'unknown';
  }
  // 16.10.2026 (R-146): Creality на заводской прошивке — камера через ядро, как у Klipper (WebRTC, затем
  // MJPEG). Камера подтверждена у K1, K1C, K1 Max и семейства K2; у остальных (KE, Ender-5 Max) — неизвестно.
  if (type === 'creality') {
    const crIdentity = normalized(`${printer && printer.model || ''} ${printer && printer.model_key || ''}`);
    if (/\bk1(?:c|\s*max)?\b(?!\s*se\b)/.test(crIdentity) || /\bk2(?:\s*(?:plus|pro|max))?\b/.test(crIdentity)) return 'confirmed';
    return 'unknown';
  }
  if (type !== 'klipper') return 'none';
  // Capability is inferred only from public model identity, never the display name.
  const modelIdentity = normalized(`${printer && printer.model || ''} ${printer && printer.model_key || ''}`);
  if (/\bk2(?:\s*(?:plus|pro|max))?\b/.test(modelIdentity)) return 'confirmed';
  return 'unknown';
}

function nonEmptyError(value) {
  if (value == null || value === false || value === 0) return false;
  if (typeof value === 'string') return value.trim() !== '' && value.trim() !== '0';
  if (Array.isArray(value)) return value.length > 0;
  if (typeof value === 'object') return Object.keys(value).length > 0;
  return true;
}

export function classifyPrinterState(state) {
  if (!state || typeof state !== 'object') {
    return { kind: 'unknown', fresh: false, online: false, offline: false, printing: false, attention: false, status: '' };
  }
  const status = String(state.status || '').trim().toUpperCase();
  const age = state.seen_ago == null || state.seen_ago === '' ? null : Number(state.seen_ago);
  const stale = Number.isFinite(age) && age >= TELEMETRY_STALE_SECONDS;
  const offline = status === 'OFFLINE' || stale;
  const fresh = !offline;
  return {
    kind: offline ? 'offline' : 'online',
    fresh,
    online: fresh,
    offline,
    printing: fresh && (status === 'RUNNING' || status === 'PREPARE'),
    attention: fresh && nonEmptyError(state.device_error),
    status,
  };
}

function matchesSearch(source, search) {
  const needle = String(search || '').trim().toLocaleLowerCase();
  return !needle || String(source && source.name || '').toLocaleLowerCase().includes(needle);
}

export function sourceMatchesFilter(source, state, filter, selectedIds) {
  const selected = selectedIds instanceof Set ? selectedIds : new Set(selectedIds || []);
  if (filter === 'selected') return selected.has(source.id);
  if (filter === 'all' || !SOURCE_FILTERS.includes(filter)) return true;
  if (source.sourceKind === 'ip') return false;
  const live = classifyPrinterState(state);
  if (filter === 'online') return live.online;
  if (filter === 'printing') return live.printing;
  if (filter === 'attention') return live.attention;
  if (filter === 'offline') return live.offline;
  return true;
}

export function filterSources(sources, statesById, filter = 'all', search = '', selectedIds = []) {
  const selected = selectedIds instanceof Set ? selectedIds : new Set(selectedIds || []);
  return Array.from(sources || []).filter((source) => matchesSearch(source, search) &&
    sourceMatchesFilter(source, statesById && statesById[source.id], filter, selected));
}

export function sourceFilterCounts(sources, statesById, selectedIds = []) {
  const selected = selectedIds instanceof Set ? selectedIds : new Set(selectedIds || []);
  const counts = {};
  for (const filter of SOURCE_FILTERS) counts[filter] = 0;
  for (const source of sources || []) {
    for (const filter of SOURCE_FILTERS) {
      if (sourceMatchesFilter(source, statesById && statesById[source.id], filter, selected)) counts[filter] += 1;
    }
  }
  return counts;
}

export function smartModeMatches(mode, live) {
  if (mode === 'online') return live.online;
  if (mode === 'printing') return live.printing;
  if (mode === 'printing-attention') return live.printing || live.attention;
  return false;
}

function orderNumber(source) {
  const value = Number(source && source.orderIdx);
  return Number.isFinite(value) ? value : Number.MAX_SAFE_INTEGER;
}

export function rankSmartSources(sources, statesById, pinnedIds = [], selectedAt = {}) {
  const pinned = pinnedIds instanceof Set ? pinnedIds : new Set(pinnedIds || []);
  return Array.from(sources || []).slice().sort((a, b) => {
    const aa = classifyPrinterState(statesById && statesById[a.id]);
    const bb = classifyPrinterState(statesById && statesById[b.id]);
    return Number(bb.attention) - Number(aa.attention) ||
      Number(bb.printing) - Number(aa.printing) ||
      Number(pinned.has(b.id)) - Number(pinned.has(a.id)) ||
      Number(bb.online) - Number(aa.online) ||
      Number(selectedAt[b.id] || 0) - Number(selectedAt[a.id] || 0) ||
      orderNumber(a) - orderNumber(b) ||
      String(a.name || '').localeCompare(String(b.name || '')) ||
      String(a.id).localeCompare(String(b.id));
  });
}

export class SmartWallHysteresis {
  constructor(options = {}) {
    this.addDelayMs = options.addDelayMs == null ? 3000 : Math.max(0, Number(options.addDelayMs));
    this.removeDelayMs = options.removeDelayMs == null ? 12000 : Math.max(0, Number(options.removeDelayMs));
    this.entries = new Map();
    this.pausedAt = null;
    this.lastResult = { ids: [], overflow: 0, eligible: 0 };
  }

  reset() {
    this.entries.clear();
    this.pausedAt = null;
    this.lastResult = { ids: [], overflow: 0, eligible: 0 };
  }

  pause(now = Date.now()) {
    if (this.pausedAt != null) return false;
    this.pausedAt = Number(now);
    return true;
  }

  resume(now = Date.now()) {
    if (this.pausedAt == null) return false;
    const delta = Math.max(0, Number(now) - this.pausedAt);
    for (const entry of this.entries.values()) {
      if (entry.desiredSince) entry.desiredSince += delta;
      if (entry.absentSince) entry.absentSince += delta;
    }
    this.pausedAt = null;
    return true;
  }

  snapshot() { return { ids: this.lastResult.ids.slice(), overflow: this.lastResult.overflow, eligible: this.lastResult.eligible }; }

  update(options = {}) {
    if (this.pausedAt != null) return this.snapshot();
    const now = Number(options.now == null ? Date.now() : options.now);
    const mode = options.mode || 'manual';
    const sources = Array.from(options.sources || []).filter((source) => source.sourceKind === 'printer');
    const states = options.statesById || {};
    const sourceIds = new Set(sources.map((source) => source.id));
    for (const id of Array.from(this.entries.keys())) if (!sourceIds.has(id)) this.entries.delete(id);
    if (mode === 'manual') {
      this.lastResult = { ids: [], overflow: 0, eligible: 0 };
      return this.snapshot();
    }

    for (const source of sources) {
      const live = classifyPrinterState(states[source.id]);
      const desired = smartModeMatches(mode, live);
      const entry = this.entries.get(source.id) || { included: false, desiredSince: 0, absentSince: 0 };
      if (desired) {
        entry.absentSince = 0;
        if (!entry.desiredSince) entry.desiredSince = now;
        if (live.attention || now - entry.desiredSince >= this.addDelayMs) entry.included = true;
      } else {
        entry.desiredSince = 0;
        if (entry.included) {
          if (!entry.absentSince) entry.absentSince = now;
          if (now - entry.absentSince >= this.removeDelayMs) entry.included = false;
        } else entry.absentSince = 0;
      }
      this.entries.set(source.id, entry);
    }

    const included = sources.filter((source) => this.entries.get(source.id)?.included);
    const ranked = rankSmartSources(included, states, options.pinnedIds, options.selectedAt);
    const maxTiles = Math.max(0, Number(options.maxTiles == null ? 25 : options.maxTiles));
    this.lastResult = { ids: ranked.slice(0, maxTiles).map((source) => source.id), overflow: Math.max(0, ranked.length - maxTiles), eligible: ranked.length };
    return this.snapshot();
  }
}
