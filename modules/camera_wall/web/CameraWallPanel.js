// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue';
import { applyServerIpChange, CameraStore, fetchServerIpSources, normalizeIpCamera, pushServerIpSources, reconcileIpSources } from './camera-store.js';
import { DetachedWindowController } from './detached-window.js';
import { gridStyleForCount, MAX_TILES } from './layout-engine.js';
import { isSupportedPrinter, printerToSource, sourceCostClass } from './camera-providers.js';
import { SessionRegistry } from './camera-session.js';
import { EventLoopLagClock, PerformanceGovernor } from './performance-governor.js';
import { PrinterStateBroker } from './printer-state-broker.js';
import { classifyPrinterState, filterSources, SmartWallHysteresis, SOURCE_FILTERS, sourceFilterCounts } from './source-discovery.js';
import { StableRefCallbacks } from './stable-ref-callbacks.js';
import { VisibilityManager } from './visibility-manager.js';

const LOG = '[CAMERA_WALL]';
const STYLE_ID = 'camera-wall-prototype1-styles';
const STYLE_URL = '/modules/camera_wall/camera-wall.css?v=0.1.13-prototype1';

function ensureStyles() {
  if (typeof document === 'undefined' || document.getElementById(STYLE_ID)) return;
  const link = document.createElement('link');
  link.id = STYLE_ID;
  link.rel = 'stylesheet';
  link.href = STYLE_URL;
  document.head.appendChild(link);
}

function isLocalWindow() {
  try { return ['localhost', '127.0.0.1', '::1'].includes(location.hostname); } catch (_) { return false; }
}

export default {
  name: 'CameraWallPanel',
  props: {
    open: { type: Boolean, default: false },
    lang: { type: String, default: 'ru' },
    detached: { type: Boolean, default: false },
  },
  emits: ['close'],
  setup(props, { emit }) {
    const L = (ru, en) => props.lang === 'ru' ? ru : en;
    //  23.09.2026: подпись способа потока приходит из camera-providers.js техническим названием на
    //  английском (как WebRTC · LAN, Core MJPEG · FFmpeg). По-русски у одного из них есть пояснение —
    //  его и возвращаем при RU; при EN раньше здесь оставалось «без перекодирования».
    const TRANSPORT_RU = { 'Core H.264 · no transcoding': 'Core H.264 · без перекодирования' };
    const transportText = (t) => (props.lang === 'ru' && TRANSPORT_RU[t]) || t || '';
    const store = new CameraStore();
    //  16.10.2026: IP-камеры живут в настройке фермы на сервере (camera-store.js) — видны на всех компьютерах.
    const fetchFn = (...args) => fetch(...args);
    //  Обращения к списку на сервере идут по очереди: две быстрые правки подряд не перетирают друг друга.
    let ipSync = Promise.resolve();
    function queueIpSync(task) { ipSync = ipSync.then(task).catch(() => {}); return ipSync; }
    function pushIpSources(list) {
      queueIpSync(() => pushServerIpSources(fetchFn, list).then((ok) => { if (ok) store.markIpSourcesSeeded(); }));
    }
    //  Добавить или удалить камеру — ОДНОЙ правкой поверх свежего списка сервера (camera-store.js,
    //  applyServerIpChange), а не всем списком, загруженным при открытии стены: стена, открытая весь день на
    //  одном компьютере, иначе затирала бы камеры, добавленные на другом. Принятый сервером список стена
    //  показывает и зеркалит; сервер правку не принял — остаётся список этого браузера.
    let ipPending = 0;
    function syncIpChange(change) {
      ipPending += 1;
      queueIpSync(async () => {
        let result = { ok: false, list: null };
        try { result = await applyServerIpChange(fetchFn, change, ipCameras.value.slice(), store.isIpSourcesSeeded()); }
        finally { ipPending -= 1; }
        if (result.ok) store.markIpSourcesSeeded();
        //  Список сервера берётся только после ПОСЛЕДНЕЙ правки из очереди: промежуточный ещё не знает о
        //  следующей камере, и стена на миг убрала бы её (и сняла с экрана).
        if (!result.ok || ipPending > 0) return;
        store.saveIpCameras(result.list);
        if (!shuttingDown) adoptIpCameras(result.list);
      });
    }
    const printers = ref([]);
    const ipCameras = ref([]);
    const selectedIds = ref([]);
    const sessionStates = ref({});
    const liveStates = ref({});
    const liveSnapshotAt = ref(0);
    const brokerStatus = ref('stopped');
    const loadState = ref('loading');
    const selectedAt = reactive({});
    const visible = reactive({});
    const fit = reactive({});
    const pinned = ref(new Set());
    const fullscreenId = ref('');
    const mode = ref('auto');
    const sourceFilter = ref('all');
    const sourceSearch = ref('');
    const smartMode = ref('manual');
    const smartOverflow = ref(0);
    const smartTelemetryReady = ref(false);
    const sidebarVisible = ref(true);
    const collapsed = ref(false);
    const ownershipSuspended = ref(false);
    const detachedActive = ref(false);
    const detachedCleanupConfirmed = ref(false);
    const popupError = ref('');
    const nowTick = ref(Date.now());
    const addForm = reactive({ name: '', url: '', mode: 'snapshot', fit: 'contain' });
    const addError = ref('');
    const tileElements = new Map();
    const mediaElements = new Map();
    let visibilityManager = null;
    let tickTimer = null;
    let lagTimer = null;
    let shuttingDown = false;
    let lifecycle = 0;
    let keyListenerBound = false;
    let applyingOperationalState = false;

    const governor = new PerformanceGovernor({
      localWindow: isLocalWindow(),
      hardwareConcurrency: (typeof navigator !== 'undefined' && navigator.hardwareConcurrency) || 1,
    });
    const lagClock = new EventLoopLagClock({ onSample: (lag) => governor.recordEventLoopLag(lag) });
    const smartHysteresis = new SmartWallHysteresis();
    const registry = new SessionRegistry({
      onChange: (snapshot) => { sessionStates.value = snapshot; },
      onReconnectStorm: () => nextTick(reconcile),
      onFailure: () => nextTick(reconcile),
      onRetryReady: () => nextTick(reconcile),
    });
    const statusBroker = typeof window === 'undefined' ? null : new PrinterStateBroker({
      env: window,
      onSnapshot: (snapshot) => {
        const now = Date.now();
        liveStates.value = snapshot;
        liveSnapshotAt.value = now;
        smartTelemetryReady.value = true;
        smartHysteresis.resume(now);
        syncPrinterAvailability();
        applySmartComposition(now);
        nextTick(reconcile);
      },
      onStatus: (status) => { brokerStatus.value = status; },
    });
    const detachedController = typeof window === 'undefined' ? null : new DetachedWindowController({
      env: window,
      onBeforeOpen: () => {
        persistOperationalState();
        pauseSmartComposition(Date.now());
        popupError.value = '';
        ownershipSuspended.value = true;
        detachedActive.value = true;
        detachedCleanupConfirmed.value = false;
        governor.setHidden(true);
        if (statusBroker) statusBroker.stop();
        registry.suspendVisibility();
        clearLiveTelemetry();
        sessionStates.value = registry.snapshot();
      },
      onBlocked: () => {
        popupError.value = L('Браузер заблокировал отдельное окно. Разрешите всплывающие окна для Farm Manager.', 'The browser blocked the separate window. Allow popups for Farm Manager.');
        detachedActive.value = false;
        ownershipSuspended.value = false;
        resumeFromUi();
      },
      onClosed: (cleanup) => {
        detachedActive.value = false;
        detachedCleanupConfirmed.value = !!cleanup;
        // Stay suspended until the operator explicitly returns ownership to the
        // embedded wall or opens another detached window.
        ownershipSuspended.value = true;
        if (!shuttingDown) applyOperationalState(store.loadOperationalState(), true);
      },
    });
    const tileRefCallbacks = new StableRefCallbacks(bindTile);
    const mediaRefCallbacks = new StableRefCallbacks(bindMedia);

    const printerSources = computed(() => printers.value.map(printerToSource).filter(isSupportedPrinter));
    const allSources = computed(() => printerSources.value.concat(ipCameras.value));
    const sourceMap = computed(() => new Map(allSources.value.map((source) => [source.id, source])));
    const selectedSources = computed(() => selectedIds.value.map((id) => sourceMap.value.get(id)).filter(Boolean).slice(0, MAX_TILES));
    const selectedSet = computed(() => new Set(selectedIds.value));
    const effectiveLiveStates = computed(() => {
      nowTick.value;
      const elapsed = liveSnapshotAt.value ? Math.max(0, (Date.now() - liveSnapshotAt.value) / 1000) : 0;
      const out = {};
      for (const [id, state] of Object.entries(liveStates.value || {})) {
        const seen = state && state.seen_ago;
        out[id] = seen != null && Number.isFinite(Number(seen)) ? { ...state, seen_ago: Number(seen) + elapsed } : state;
      }
      return out;
    });
    const filterCounts = computed(() => sourceFilterCounts(allSources.value, effectiveLiveStates.value, selectedSet.value));
    const filteredSources = computed(() => filterSources(allSources.value, effectiveLiveStates.value, sourceFilter.value, sourceSearch.value, selectedSet.value));
    const filteredPrinterSources = computed(() => filteredSources.value.filter((source) => source.sourceKind === 'printer'));
    const filteredIpCameras = computed(() => filteredSources.value.filter((source) => source.sourceKind === 'ip'));
    const stateFor = (id) => sessionStates.value[id] || { state: 'idle', transport: '', fallback: false, lastFrame: '', frameAt: '', snapshotAt: '', freshness: '', error: '', reconnectAt: 0, retryReady: false, activeTransport: false };
    const tileModels = computed(() => { nowTick.value; return selectedSources.value.map((source) => {
      const state = stateFor(source.id);
      const printerState = source.sourceKind === 'printer' ? classifyPrinterState(effectiveLiveStates.value[source.id]) : null;
      return {
        ...source,
        costClass: sourceCostClass(source),
        state,
        fullscreen: fullscreenId.value === source.id,
        pinned: pinned.value.has(source.id),
        visible: visible[source.id] !== false,
        recentlySelected: Date.now() - (selectedAt[source.id] || 0) < 60000,
        selectedAt: selectedAt[source.id] || 0,
        attention: !!printerState?.attention,
        printerState,
        isSnapshot: source.sourceKind === 'ip' && source.mode === 'snapshot',
        eligible: (!fullscreenId.value || fullscreenId.value === source.id) &&
          !(state.reconnectAt && !state.retryReady) && (source.sourceKind !== 'printer' || printerState.online),
      };
    }); });
    const displayedTiles = computed(() => fullscreenId.value ? tileModels.value.filter((tile) => tile.id === fullscreenId.value) : tileModels.value);
    const gridStyle = computed(() => gridStyleForCount(displayedTiles.value.length || 1));
    const activeCount = computed(() => Object.values(sessionStates.value).filter((state) => state.activeTransport).length);
    const expensiveCount = computed(() => tileModels.value.filter((tile) => tile.costClass === 'expensive-server' && tile.state.activeTransport).length);
    const limits = computed(() => { nowTick.value; return governor.limits(); });
    const governorReason = computed(() => { nowTick.value; return governor.reason(); });

    function isActiveVisibleOwner() {
      return props.open && !shuttingDown && !collapsed.value && !ownershipSuspended.value &&
        !(typeof document !== 'undefined' && document.hidden);
    }

    function pauseSmartComposition(now = Date.now()) {
      smartTelemetryReady.value = false;
      smartHysteresis.pause(now);
    }

    function operationalSnapshot() {
      return {
        mode: mode.value,
        smartMode: smartMode.value,
        selectedIds: selectedIds.value.slice(),
        pinnedIds: Array.from(pinned.value),
        ipCameras: ipCameras.value.slice(),
      };
    }

    function persistOperationalState() {
      if (applyingOperationalState || ownershipSuspended.value) return false;
      return store.saveOperationalState(operationalSnapshot());
    }

    function applyOperationalState(state, sync = false) {
      if (!state) return false;
      applyingOperationalState = true;
      ipCameras.value = state.ipCameras.slice();
      mode.value = state.mode;
      smartMode.value = state.smartMode;
      const valid = new Set(allSources.value.map((source) => source.id));
      selectedIds.value = state.selectedIds.filter((id) => valid.has(id)).slice(0, MAX_TILES);
      pinned.value = new Set(state.pinnedIds.filter((id) => valid.has(id)).slice(0, MAX_TILES));
      const stamp = Date.now();
      selectedIds.value.forEach((id, index) => {
        selectedAt[id] = stamp - index;
        if (visible[id] == null) visible[id] = true;
      });
      smartOverflow.value = 0;
      smartHysteresis.reset();
      pauseSmartComposition(stamp);
      governor.setMode(mode.value);
      applyingOperationalState = false;
      if (sync) syncRegistry();
      return true;
    }

    function syncPrinterAvailability() {
      // An intentionally absent snapshot during hidden/collapse/detached
      // suspension is not printer evidence. Keep CameraSession availability
      // and its bounded visibility-resume bookkeeping until fresh /ws data.
      if (!liveSnapshotAt.value) {
        sessionStates.value = registry.snapshot();
        return false;
      }
      for (const source of selectedSources.value) {
        if (source.sourceKind !== 'printer') continue;
        const live = classifyPrinterState(effectiveLiveStates.value[source.id]);
        registry.setPrinterAvailability(source.id, live.kind);
      }
      sessionStates.value = registry.snapshot();
      return true;
    }

    function clearLiveTelemetry() {
      liveStates.value = {};
      liveSnapshotAt.value = 0;
      smartTelemetryReady.value = false;
      // Deliberate broker suspension must not rewrite live CameraSession
      // availability to unknown. Tile eligibility is already fail-closed by
      // the empty UI snapshot; a fresh /ws snapshot performs the next sync.
    }

    function syncRegistry() {
      const wanted = new Set(selectedSources.value.map((source) => source.id));
      for (const source of selectedSources.value) registry.add(source);
      for (const id of Array.from(registry.sessions.keys())) if (!wanted.has(id)) {
        clearRefState(id);
        registry.remove(id);
      }
      syncPrinterAvailability();
      sessionStates.value = registry.snapshot();
    }

    function setSelection(ids, persist = true) {
      const valid = new Set(allSources.value.map((source) => source.id));
      const next = Array.from(new Set(ids || [])).filter((id) => valid.has(id)).slice(0, MAX_TILES);
      const previous = new Set(selectedIds.value);
      for (const id of previous) if (!next.includes(id)) clearRefState(id);
      selectedIds.value = next;
      const stamp = Date.now();
      next.forEach((id, index) => {
        if (!previous.has(id)) selectedAt[id] = stamp - index;
        if (visible[id] == null) visible[id] = true;
      });
      if (persist) persistSelection();
      syncRegistry();
      nextTick(reconcile);
    }

    function applySmartComposition(now = Date.now()) {
      if (smartMode.value === 'manual') { smartOverflow.value = 0; return; }
      if (!isActiveVisibleOwner() || !smartTelemetryReady.value) return;
      const manualIpIds = selectedIds.value.filter((id) => sourceMap.value.get(id)?.sourceKind === 'ip');
      const result = smartHysteresis.update({
        now,
        mode: smartMode.value,
        sources: printerSources.value,
        statesById: effectiveLiveStates.value,
        pinnedIds: pinned.value,
        selectedAt,
        maxTiles: Math.max(0, MAX_TILES - manualIpIds.length),
      });
      smartOverflow.value = result.overflow;
      const next = result.ids.concat(manualIpIds).slice(0, MAX_TILES);
      if (next.length !== selectedIds.value.length || next.some((id, index) => selectedIds.value[index] !== id)) setSelection(next);
    }

    function selectVisible() {
      smartMode.value = 'manual';
      const next = selectedIds.value.slice();
      const selected = new Set(next);
      for (const source of filteredSources.value) {
        if (selected.size >= MAX_TILES) break;
        if (!selected.has(source.id)) { selected.add(source.id); next.push(source.id); }
      }
      setSelection(next);
    }

    function clearVisible() {
      smartMode.value = 'manual';
      const visibleIds = new Set(filteredSources.value.map((source) => source.id));
      setSelection(selectedIds.value.filter((id) => !visibleIds.has(id)));
    }

    function reconcile() {
      if (!props.open || shuttingDown || collapsed.value || ownershipSuspended.value) return;
      governor.setMode(mode.value);
      governor.reconcile(tileModels.value, registry);
      sessionStates.value = registry.snapshot();
    }

    function bindMedia(id, element) {
      const next = element || null;
      const previous = mediaElements.get(id) || null;
      const currentHost = registry.sessions.get(id)?.host || null;
      if (previous === next && currentHost === next) return;
      if (!element) {
        mediaElements.delete(id);
        registry.setHost(id, null);
        return;
      }
      mediaElements.set(id, element);
      registry.setHost(id, element);
      nextTick(reconcile);
    }

    function mediaRef(id) { return mediaRefCallbacks.get(id); }
    function tileRef(id) { return tileRefCallbacks.get(id); }

    function bindTile(id, element) {
      if (!element) {
        const stale = tileElements.get(id);
        if (stale && visibilityManager) visibilityManager.unobserve(stale);
        tileElements.delete(id);
        return;
      }
      if (tileElements.get(id) === element) return;
      const old = tileElements.get(id);
      if (old && visibilityManager) visibilityManager.unobserve(old);
      tileElements.set(id, element);
      if (visibilityManager) visibilityManager.observe(element);
    }

    function clearRefState(id) {
      const tile = tileElements.get(id);
      if (tile && visibilityManager) visibilityManager.unobserve(tile);
      registry.setHost(id, null);
      tileElements.delete(id);
      mediaElements.delete(id);
      tileRefCallbacks.delete(id);
      mediaRefCallbacks.delete(id);
    }

    function persistSelection() { return persistOperationalState(); }

    function toggleSource(source) {
      if (!isSupportedPrinter(source) && source.sourceKind !== 'ip') return;
      if (smartMode.value !== 'manual') smartMode.value = 'manual';
      const set = new Set(selectedIds.value);
      if (set.has(source.id)) {
        set.delete(source.id);
        clearRefState(source.id);
        registry.remove(source.id);
        if (fullscreenId.value === source.id) fullscreenId.value = '';
      } else {
        if (set.size >= MAX_TILES) return;
        set.add(source.id);
        selectedAt[source.id] = Date.now();
      }
      selectedIds.value = Array.from(set);
      persistSelection();
      syncRegistry();
      nextTick(reconcile);
    }

    function removeTile(id) {
      const source = sourceMap.value.get(id);
      if (source) toggleSource(source);
    }

    function togglePinned(id) {
      const next = new Set(pinned.value);
      if (next.has(id)) next.delete(id); else next.add(id);
      pinned.value = next;
      applySmartComposition(Date.now());
      persistOperationalState();
      reconcile();
    }

    function toggleFit(id) { fit[id] = (fit[id] || sourceMap.value.get(id)?.fit || 'contain') === 'contain' ? 'cover' : 'contain'; }
    function tileFit(id) { return fit[id] || sourceMap.value.get(id)?.fit || 'contain'; }
    function toggleFullscreen(id) { fullscreenId.value = fullscreenId.value === id ? '' : id; nextTick(reconcile); }
    function reconnectTile(id) {
      const source = sourceMap.value.get(id);
      if (source?.sourceKind === 'printer' && !classifyPrinterState(effectiveLiveStates.value[id]).online) return;
      selectedAt[id] = Date.now();
      if (!registry.manualReconnect(id)) return;
      governor.requestImmediate(id);
      nextTick(reconcile);
    }

    function suspendForUi() {
      governor.setHidden(true);
      pauseSmartComposition(Date.now());
      if (statusBroker) statusBroker.stop();
      registry.suspendVisibility();
      clearLiveTelemetry();
      sessionStates.value = registry.snapshot();
    }

    function resumeFromUi() {
      if (collapsed.value || ownershipSuspended.value || (typeof document !== 'undefined' && document.hidden)) return;
      if (statusBroker) statusBroker.start();
      registry.prepareVisibilityResume();
      lagClock.reset();
      governor.setHidden(false);
      nextTick(reconcile);
    }

    function collapsePanel() {
      if (props.detached || collapsed.value) return;
      collapsed.value = true;
      suspendForUi();
    }

    function restorePanel() {
      collapsed.value = false;
      resumeFromUi();
    }

    function openDetachedWindow() {
      if (props.detached || !detachedController) return false;
      return detachedController.open(props.lang);
    }

    function restoreEmbedded() {
      if (detachedController) detachedController.close();
      detachedActive.value = false;
      applyOperationalState(store.loadOperationalState(), true);
      ownershipSuspended.value = false;
      popupError.value = '';
      collapsed.value = false;
      resumeFromUi();
    }

    function governorReasonLabel() {
      const code = governorReason.value;
      if (code === 'economy') return L('Экономия', 'Economy');
      if (code === 'protection-ui-lag') return L('Защита · задержка интерфейса', 'Protection · UI lag');
      if (code === 'stable') return L('Auto · стабильно', 'Auto · stable');
      return L('Auto · разгон', 'Auto · warming up');
    }

    function onKeyDown(event) {
      if (!props.open || event.key !== 'Escape') return;
      event.preventDefault();
      event.stopPropagation();
      if (event.stopImmediatePropagation) event.stopImmediatePropagation();
      if (fullscreenId.value) toggleFullscreen(fullscreenId.value);
      else shutdown(true);
    }

    function errorText(reason) {
      const map = {
        invalid_url: L('Введите корректный URL.', 'Enter a valid URL.'),
        unsupported_scheme: L('Разрешены только http:// и https://.', 'Only http:// and https:// are allowed.'),
        embedded_credentials: L('URL со встроенным логином или паролем не сохраняется.', 'URLs with embedded credentials are not saved.'),
        name_required: L('Введите название камеры.', 'Enter a camera name.'),
      };
      return map[reason] || L('Не удалось добавить камеру.', 'Could not add camera.');
    }

    function addIpCamera() {
      const normalized = normalizeIpCamera(addForm);
      if (!normalized.ok) { addError.value = errorText(normalized.reason); return; }
      ipCameras.value = ipCameras.value.concat([normalized.camera]).slice(0, MAX_TILES);
      store.saveIpCameras(ipCameras.value);
      syncIpChange({ add: normalized.camera });
      addForm.name = ''; addForm.url = ''; addError.value = '';
      if (selectedIds.value.length < MAX_TILES) toggleSource(normalized.camera);
      else persistOperationalState();
    }

    function deleteIpCamera(id) {
      if (selectedIds.value.includes(id)) removeTile(id);
      ipCameras.value = ipCameras.value.filter((source) => source.id !== id);
      store.saveIpCameras(ipCameras.value);
      syncIpChange({ remove: id });
      persistOperationalState();
    }

    //  Список, принятый сервером: камеры, удалённые на другом компьютере, снимаются и с экрана этой стены.
    function adoptIpCameras(list) {
      const keep = new Set(list.map((source) => source.id));
      ipCameras.value.filter((source) => !keep.has(source.id) && selectedIds.value.includes(source.id)).forEach((source) => removeTile(source.id));
      ipCameras.value = list.slice();
      persistOperationalState();
    }

    function statusLabel(tile) {
      if (tile.sourceKind === 'printer' && tile.printerState?.offline) return L('ПРИНТЕР НЕ В СЕТИ', 'PRINTER OFFLINE');
      if (tile.sourceKind === 'printer' && tile.printerState?.kind === 'unknown') return L('НЕТ ДАННЫХ', 'NO DATA');
      const state = tile.state.state;
      if (state === 'camera-unavailable') return L('КАМЕРА НЕДОСТУПНА', 'CAMERA UNAVAILABLE');
      if ((state === 'live' || state === 'frozen') && tile.sourceKind === 'ip' && tile.mode === 'snapshot') return L('СНИМОК', 'SNAPSHOT');
      const ru = { idle: 'ОЖИДАНИЕ', connecting: 'ПОДКЛЮЧЕНИЕ', live: 'LIVE', frozen: 'ЗАМОРОЖЕНО', reconnecting: 'ПЕРЕПОДКЛЮЧЕНИЕ', offline: 'ОФЛАЙН', 'printer-offline': 'ПРИНТЕР НЕ В СЕТИ', 'printer-unknown': 'НЕТ ДАННЫХ', 'paused-performance': 'ПАУЗА ПО НАГРУЗКЕ' };
      const en = { idle: 'IDLE', connecting: 'CONNECTING', live: 'LIVE', frozen: 'FROZEN', reconnecting: 'RECONNECTING', offline: 'OFFLINE', 'printer-offline': 'PRINTER OFFLINE', 'printer-unknown': 'NO DATA', 'paused-performance': 'PAUSED BY PERFORMANCE' };
      return (props.lang === 'ru' ? ru[state] : en[state]) || state.toUpperCase();
    }

    function stateClass(tile) {
      if (tile.sourceKind === 'printer' && tile.printerState?.offline) return 'offline';
      if (tile.sourceKind === 'printer' && tile.printerState?.kind === 'unknown') return 'idle';
      if (tile.state.state === 'camera-unavailable') return 'reconnecting';
      return tile.state.state === 'live' && tile.sourceKind === 'ip' && tile.mode === 'snapshot' ? 'snapshot' : tile.state.state;
    }
    function sourceStatusLabel(source) {
      if (source.sourceKind === 'ip') return source.mode === 'snapshot' ? 'Snapshot' : 'MJPEG';
      const live = classifyPrinterState(effectiveLiveStates.value[source.id]);
      if (live.attention) return L('Внимание', 'Attention');
      if (live.printing) return L('Печатает', 'Printing');
      if (live.online) return L('Онлайн', 'Online');
      if (live.offline) return L('Офлайн', 'Offline');
      return L('Нет данных', 'No data');
    }
    function sourceStateClass(source) { return source.sourceKind === 'ip' ? 'ip' : classifyPrinterState(effectiveLiveStates.value[source.id]).kind; }
    function reconnectHint(tile) {
      if (!tile.state.reconnectAt) return '';
      const seconds = Math.max(0, Math.ceil((tile.state.reconnectAt - nowTick.value) / 1000));
      return L(`Переподключение через ${seconds} с`, `Reconnect in ${seconds}s`);
    }
    function filterLabel(filter) {
      const ru = { all: 'Все', online: 'Онлайн', printing: 'Печатают', attention: 'Внимание', offline: 'Офлайн', selected: 'Выбранные' };
      const en = { all: 'All', online: 'Online', printing: 'Printing', attention: 'Attention', offline: 'Offline', selected: 'Selected' };
      return (props.lang === 'ru' ? ru : en)[filter] || filter;
    }
    // Alpha 2.875: причины отказа по-человечески. Код вида first_frame_timeout ничего не говорит
    // владельцу, а именно он смотрит на стену. Неизвестный код показываем как есть — врать не о чем.
    const FAIL_REASONS = {
      first_frame_timeout: ['камера не прислала кадр за 15 секунд', 'no frame within 15 seconds'],
      fmp4_stream_failed: ['поток не открылся', 'stream did not open'],
      fmp4_player_unavailable: ['проигрыватель недоступен: нужна программа 2.870 и новее',
                                'player unavailable: requires app 2.870 or newer'],
      mse_unsupported: ['браузер не умеет показывать этот поток', 'browser cannot play this stream'],
      codec_unsupported: ['браузер не понимает кодек камеры', 'browser does not support the codec'],
      append_backlog: ['браузер не успевает за потоком', 'browser cannot keep up with the stream'],
      mjpeg_stream_failed: ['поток MJPEG не открылся', 'MJPEG stream did not open'],
      camera_failed: ['камера не ответила', 'camera did not respond'],
      no_camera_provider: ['для этого источника нет способа показа', 'no provider for this source'],
      snapshot_provider_failed: ['снимок не получен', 'snapshot failed'],
    };
    function reasonText(tile) {
      const raw = String((tile.state && tile.state.error) || '').trim();
      if (!raw) return '';
      const known = FAIL_REASONS[raw];
      const human = known ? L(known[0], known[1]) : raw;
      // Код оставляем рядом: владельцу — понятный текст, разработчику — точная причина.
      return known ? human + ' (' + raw + ')' : human;
    }

    function freshnessHint(tile) {
      // Alpha 2.873: измеренная частота кадров. Считает её браузер по декодированным кадрам —
      // это факт, а не ощущение, и он сразу отвечает на вопрос «тормозит камера или программа».
      if (String(tile.state.freshness || '').startsWith('fps:')) {
        return L('Измеренная частота: столько кадров в секунду браузер декодировал за последние две секунды.',
                 'Measured rate: frames per second the browser decoded over the last two seconds.');
      }
      if (tile.state.freshness !== 'first-frame-only') return '';
      return L('Подтверждён первый кадр; браузер не даёт надёжного сигнала свежести каждого следующего MJPEG-кадра.', 'First frame verified; the browser exposes no reliable freshness signal for every later MJPEG frame.');
    }
    function freshnessShort(tile) {
      const f = String(tile.state.freshness || '');
      if (f.startsWith('fps:')) {
        // Alpha 2.877: строка вида fps:18;g:3;s:1 — к/с, перерывы приёма, застревания показа.
        const parts = f.split(';');
        let out = parts[0].slice(4) + L(' к/с', ' fps');
        for (let i = 1; i < parts.length; i++) {
          const p = parts[i];
          if (p.startsWith('g:')) out += L(' · связь: ', ' · network: ') + p.slice(2);
          else if (p.startsWith('s:')) out += L(' · показ: ', ' · playback: ') + p.slice(2);
        }
        return out;
      }
      return f === 'first-frame-only' ? L('первый кадр','first frame') : '';
    }
    function frameAge(tile) {
      const stamp = tile.state.frameAt || tile.state.snapshotAt;
      if (!stamp) return '';
      const seconds = Math.max(0, Math.floor((nowTick.value - new Date(stamp).getTime()) / 1000));
      return L(`${seconds} с назад`, `${seconds}s ago`);
    }

    async function loadPrinters() {
      loadState.value = 'loading';
      try {
        const response = await fetch('/api/printers', { credentials: 'same-origin', cache: 'no-store' });
        if (response.status === 401 || response.status === 403) { loadState.value = 'unauthorized'; return; }
        if (!response.ok) throw new Error('HTTP ' + response.status);
        const value = await response.json();
        printers.value = Array.isArray(value) ? value : [];
        loadState.value = 'ready';
      } catch (error) {
        console.warn(LOG, 'printer list unavailable', error && error.message ? error.message : 'network');
        loadState.value = 'unavailable';
      }
    }

    async function initialize() {
      const generation = ++lifecycle;
      ensureStyles();
      shuttingDown = false;
      if (!keyListenerBound && typeof window !== 'undefined') { window.addEventListener('keydown', onKeyDown, true); keyListenerBound = true; }
      let operational = store.loadOperationalState();
      ipCameras.value = operational ? operational.ipCameras.slice() : store.loadIpCameras();
      const localIps = ipCameras.value.slice();
      const server = (await Promise.all([loadPrinters(), fetchServerIpSources(fetchFn)]))[1];
      if (generation !== lifecycle || !props.open || shuttingDown) return;
      //  Список с сервера — главный; этот браузер его зеркалит. Сервер пуст, а здесь камеры есть — переносим их
      //  на сервер один раз. Сервер о списке не знает (старая программа) — молча остаётся список этого браузера.
      const plan = reconcileIpSources(server, localIps, store.isIpSourcesSeeded());
      if (plan.mirror) {
        store.saveIpCameras(plan.list);
        if (operational) operational = { ...operational, ipCameras: plan.list.slice() };
      }
      //  Перенос — пометка «перенесено» ставится, только когда сервер его принял. Если переносить нечего, а
      //  сервер список знает, пометка ставится сразу: удалённая на другом компьютере камера не вернётся.
      if (plan.seed) pushIpSources(plan.list);
      else if (server && server.supported) store.markIpSourcesSeeded();
      ipCameras.value = plan.list.slice();
      if (operational) applyOperationalState(operational, false);
      else {
        const valid = new Set(allSources.value.filter((source) => isSupportedPrinter(source) || source.sourceKind === 'ip').map((source) => source.id));
        let restored = store.loadSelection().filter((id) => valid.has(id)).slice(0, MAX_TILES);
        if (!restored.length) restored = allSources.value.filter((source) => isSupportedPrinter(source) || source.sourceKind === 'ip').slice(0, MAX_TILES).map((source) => source.id);
        selectedIds.value = restored;
        const stamp = Date.now();
        restored.forEach((id, index) => { selectedAt[id] = stamp - index; visible[id] = true; });
      }
      syncRegistry();
      if (!operational) persistOperationalState();
      visibilityManager = new VisibilityManager({
        onHidden: () => suspendForUi(),
        onVisible: () => resumeFromUi(),
        onTileVisibility: (id, value) => { visible[id] = value; reconcile(); },
      });
      visibilityManager.start();
      tileElements.forEach((element) => visibilityManager.observe(element));
      tickTimer = setInterval(() => {
        nowTick.value = Date.now();
        if (!isActiveVisibleOwner()) return;
        syncPrinterAvailability();
        applySmartComposition(nowTick.value);
        reconcile();
      }, 1000);
      lagClock.reset();
      lagTimer = setInterval(() => {
        lagClock.sample();
      }, 1000);
      await nextTick();
      reconcile();
    }

    function shutdown(notify = true) {
      if (shuttingDown) return;
      persistOperationalState();
      shuttingDown = true;
      lifecycle += 1;
      if (tickTimer != null) { clearInterval(tickTimer); tickTimer = null; }
      if (lagTimer != null) { clearInterval(lagTimer); lagTimer = null; }
      if (visibilityManager) { visibilityManager.stop(); visibilityManager = null; }
      if (statusBroker) statusBroker.stop();
      if (keyListenerBound && typeof window !== 'undefined') { window.removeEventListener('keydown', onKeyDown, true); keyListenerBound = false; }
      if (detachedController) detachedController.close();
      registry.closeAll();
      for (const id of mediaElements.keys()) registry.setHost(id, null);
      tileElements.clear();
      mediaElements.clear();
      tileRefCallbacks.clear();
      mediaRefCallbacks.clear();
      fullscreenId.value = '';
      const remaining = registry.activeCount();
      if (remaining) console.warn(LOG, 'cleanup incomplete', remaining);
      else console.info(LOG, 'all camera sessions released');
      if (notify) emit('close');
    }

    watch(() => props.open, (value) => { if (value) initialize(); else shutdown(false); }, { immediate: true });
    watch(mode, () => {
      governor.setMode(mode.value);
      if (!applyingOperationalState) persistOperationalState();
      reconcile();
    }, { flush: 'sync' });
    watch(smartMode, () => {
      if (applyingOperationalState) return;
      smartHysteresis.reset();
      if (!isActiveVisibleOwner() || !smartTelemetryReady.value) smartHysteresis.pause(Date.now());
      persistOperationalState();
      applySmartComposition(Date.now());
    }, { flush: 'sync' });
    onMounted(() => { if (props.open) nextTick(reconcile); });
    onBeforeUnmount(() => shutdown(false));

    return {
      L, MAX_TILES, SOURCE_FILTERS, printerSources, ipCameras, selectedIds, selectedSources, displayedTiles, gridStyle,
      sourceFilter, sourceSearch, smartMode, smartOverflow, filterCounts, filteredPrinterSources, filteredIpCameras,
      activeCount, expensiveCount, limits, loadState, mode, sidebarVisible, fullscreenId,
      governorReason, governorReasonLabel, brokerStatus, collapsed, ownershipSuspended, detachedActive, detachedCleanupConfirmed, popupError,
      addForm, addError, toggleSource, deleteIpCamera, addIpCamera, removeTile, togglePinned,
      toggleFit, tileFit, toggleFullscreen, mediaRef, tileRef, stateFor, statusLabel, stateClass, transportText,
      frameAge, freshnessHint, freshnessShort, reasonText, reconnectHint, sourceStatusLabel, sourceStateClass, filterLabel,
      reconnectTile, sourceCostClass, isSupportedPrinter, selectVisible, clearVisible, shutdown,
      collapsePanel, restorePanel, openDetachedWindow, restoreEmbedded,
    };
  },
  template: `<teleport to="body"><transition name="fade"><section v-if="open" class="cw-root fm-module fm-module-camera-wall" :class="{collapsed:collapsed}" aria-modal="true" role="dialog" :aria-label="L('Видеостена','Camera Wall')">
    <button v-if="collapsed" class="cw-restore-panel" @click="restorePanel">{{ L('Развернуть панель','Expand panel') }}</button>
    <template v-else>
    <header class="cw-header">
      <div class="cw-brand">
        <span class="cw-brand-icon"><svg-icon name="camera"></svg-icon></span>
        <div><div class="cw-title">{{ L('Видеостена','Camera Wall') }}</div><div class="cw-subtitle">Prototype 1 · {{ selectedSources.length }}/25 {{ L('плиток','tiles') }}</div></div>
      </div>
      <div class="cw-header-stats">
        <span class="cw-chip"><span class="cw-dot"></span>{{ activeCount }} {{ L('активно','active') }}</span>
        <span class="cw-chip optional">FFmpeg: {{ expensiveCount }}/{{ limits.expensiveServerLiveBudget }}</span>
        <span class="cw-chip optional">{{ L('Лимит live','Live budget') }}: {{ limits.totalLiveBudget }}</span>
        <span class="cw-chip optional" :class="{'cw-protection':governorReason==='protection-ui-lag'}" :title="governorReason">{{ governorReasonLabel() }}</span>
      </div>
      <div class="cw-actions">
        <span v-if="popupError" class="cw-popup-error" role="alert">{{ popupError }}</span>
        <div class="cw-mode" :aria-label="L('Режим производительности','Performance mode')">
          <button :class="{active:mode==='auto'}" @click="mode='auto'">Auto</button>
          <button :class="{active:mode==='economy'}" @click="mode='economy'">{{ L('Экономия','Economy') }}</button>
        </div>
        <button v-if="!detached" class="cw-btn cw-detach" @click="openDetachedWindow">{{ L('Открыть в отдельном окне','Open in separate window') }}</button>
        <button v-if="!detached" class="cw-btn cw-collapse" @click="collapsePanel">{{ L('Свернуть панель','Collapse panel') }}</button>
        <button class="cw-btn cw-close" :title="L('Закрыть всё','Close all')" @click="shutdown(true)">×</button>
      </div>
    </header>
    <div v-if="ownershipSuspended" class="cw-detached-notice" :data-cleanup="detachedCleanupConfirmed ? 'true' : 'false'">
      <strong>{{ detachedActive ? L('Видеостена работает в отдельном окне','Camera Wall is running in a separate window') : L('Отдельное окно закрыто','The separate window is closed') }}</strong>
      <span>{{ L('Встроенная панель не держит camera sessions.','The embedded panel owns no camera sessions.') }}</span>
      <span v-if="popupError" class="cw-form-error">{{ popupError }}</span>
      <div class="cw-detached-actions"><button class="cw-btn primary cw-return-embedded" @click="restoreEmbedded">{{ L('Вернуть в панель','Return to embedded panel') }}</button><button class="cw-btn cw-detach-reopen" @click="openDetachedWindow">{{ L('Открыть отдельное окно','Open separate window') }}</button></div>
    </div>
    <div v-else class="cw-body" :class="{'sidebar-hidden':!sidebarVisible || !!fullscreenId}">
      <aside class="cw-sidebar">
        <div class="cw-side-head"><span class="cw-side-title">{{ L('Источники','Sources') }}</span><span class="cw-chip">{{ selectedIds.length }}/25</span></div>
        <div v-if="loadState==='unauthorized'" class="cw-load-error">{{ L('Нет права на просмотр списка принтеров.','No permission to view printers.') }}</div>
        <div v-else-if="loadState==='unavailable'" class="cw-load-error">{{ L('Список принтеров недоступен.','Printer list is unavailable.') }}</div>
        <div class="cw-source-controls">
          <label class="cw-control-label"><span>{{ L('Состав стены','Wall composition') }}</span><select v-model="smartMode" class="cw-select cw-smart-mode"><option value="manual">{{ L('Вручную','Manual') }}</option><option value="online">{{ L('Все онлайн','All online') }}</option><option value="printing">{{ L('Все печатающие','All printing') }}</option><option value="printing-attention">{{ L('Печатающие + внимание','Printing + attention') }}</option></select></label>
          <div v-if="smartMode!=='manual'" class="cw-smart-summary"><span>{{ selectedSources.length }} {{ L('на стене','on wall') }}</span><span v-if="smartOverflow">{{ smartOverflow }} {{ L('ещё не помещаются','more do not fit') }}</span></div>
          <input v-model="sourceSearch" class="cw-input cw-source-search" type="search" :placeholder="L('Поиск источника','Search sources')">
          <div class="cw-source-filters" :aria-label="L('Фильтры источников','Source filters')"><button v-for="filter in SOURCE_FILTERS" :key="filter" class="cw-filter" :class="{active:sourceFilter===filter}" @click="sourceFilter=filter">{{ filterLabel(filter) }} <span>{{ filterCounts[filter] }}</span></button></div>
          <div class="cw-visible-actions"><button class="cw-btn" @click="selectVisible">{{ L('Выбрать видимые','Select visible') }}</button><button class="cw-btn" @click="clearVisible">{{ L('Снять видимые','Clear visible') }}</button></div>
        </div>
        <div class="cw-source-list">
          <button v-for="source in filteredPrinterSources" :key="source.id" class="cw-source" :class="[{selected:selectedIds.includes(source.id)},sourceStateClass(source)]" @click="toggleSource(source)">
            <span class="cw-check">{{ selectedIds.includes(source.id) ? '✓' : '' }}</span>
            <span class="cw-source-copy"><span class="cw-source-name">{{ source.name }}</span><span class="cw-source-meta">{{ source.model || source.type }} · {{ sourceStatusLabel(source) }}</span></span>
            <span v-if="sourceCostClass(source)==='expensive-server'" class="cw-expensive">FFmpeg</span>
          </button>
          <div v-if="filteredIpCameras.length" class="cw-side-title cw-ip-heading">IP</div>
          <div v-for="source in filteredIpCameras" :key="source.id" class="cw-source" :class="{selected:selectedIds.includes(source.id)}">
            <button class="cw-check" style="background:transparent;color:inherit" @click="toggleSource(source)">{{ selectedIds.includes(source.id) ? '✓' : '' }}</button>
            <button class="cw-source-copy" style="border:0;background:transparent;color:inherit;text-align:left;cursor:pointer" @click="toggleSource(source)"><span class="cw-source-name">{{ source.name }}</span><span class="cw-source-meta">{{ source.mode==='snapshot' ? 'Snapshot' : 'MJPEG' }}</span></button>
            <button class="cw-source-delete" :title="L('Удалить источник','Delete source')" @click="deleteIpCamera(source.id)">×</button>
          </div>
        </div>
        <form class="cw-add" @submit.prevent="addIpCamera">
          <div class="cw-add-grid">
            <input v-model="addForm.name" class="cw-input" maxlength="80" :placeholder="L('Название IP-камеры','IP camera name')">
            <input v-model="addForm.url" class="cw-input" maxlength="2048" inputmode="url" placeholder="http://camera/...">
            <div class="cw-add-row"><select v-model="addForm.mode" class="cw-select"><option value="snapshot">Snapshot</option><option value="mjpeg">MJPEG</option></select><select v-model="addForm.fit" class="cw-select"><option value="contain">Contain</option><option value="cover">Cover</option></select></div>
            <div v-if="addError" class="cw-form-error">{{ addError }}</div>
            <div class="cw-form-note">{{ L('Только browser-direct HTTP(S), без встроенных логинов и паролей. RTSP не поддерживается.','Browser-direct HTTP(S) only, without embedded usernames or passwords. RTSP is not supported.') }}</div>
            <button class="cw-btn primary" type="submit">{{ L('Добавить источник','Add source') }}</button>
          </div>
        </form>
      </aside>
      <main class="cw-stage">
        <div v-if="!displayedTiles.length" class="cw-empty"><svg-icon name="camera"></svg-icon><strong>{{ L('Выберите камеры','Select cameras') }}</strong><span>{{ L('Можно разместить до 25 плиток. Governor открывает только безопасное число live-потоков.','You can place up to 25 tiles. The Governor opens only a safe number of live streams.') }}</span></div>
        <div v-else class="cw-grid" :style="gridStyle">
          <article v-for="tile in displayedTiles" :key="tile.id" class="cw-tile" :class="{pinned:tile.pinned}" :data-camera-id="tile.id" :ref="tileRef(tile.id)" :style="{'--cw-fit':tileFit(tile.id)}" @dblclick="toggleFullscreen(tile.id)">
            <div class="cw-placeholder"><svg-icon name="camera"></svg-icon></div>
            <div class="cw-media-host" :ref="mediaRef(tile.id)"></div>
            <img v-if="tile.state.lastFrame && tile.state.state!=='live'" class="cw-frozen" :src="tile.state.lastFrame" alt="">
            <div class="cw-tile-top"><span class="cw-tile-name">{{ tile.name }}</span><div class="cw-tile-tools" @dblclick.stop>
              <button class="cw-icon-btn" :class="{active:tile.pinned}" :title="L('Закрепить','Pin')" @click="togglePinned(tile.id)">◆</button>
              <button class="cw-icon-btn" :title="tileFit(tile.id)==='contain' ? 'Contain' : 'Cover'" @click="toggleFit(tile.id)">▣</button>
              <button class="cw-icon-btn" :class="{active:tile.fullscreen}" :title="L('Во весь экран','Fullscreen')" @click="toggleFullscreen(tile.id)">⛶</button>
              <button class="cw-icon-btn" :disabled="tile.sourceKind==='printer' && !tile.printerState.online" :title="L('Переподключить','Reconnect')" @click="reconnectTile(tile.id)">↻</button>
              <button class="cw-icon-btn danger" :title="L('Убрать плитку','Remove tile')" @click="removeTile(tile.id)">×</button>
            </div></div>
            <div v-if="tile.sourceKind==='printer' && !tile.printerState.online" class="cw-banner"><strong>{{ statusLabel(tile) }}</strong>{{ frameAge(tile) || (tile.printerState.offline ? L('Камера закрыта, ожидание статуса /ws','Camera closed, waiting for /ws status') : L('Телеметрия ещё не получена','Telemetry has not arrived yet')) }}</div>
            <div v-else-if="tile.state.state==='paused-performance' || tile.state.state==='frozen'" class="cw-banner"><strong>{{ statusLabel(tile) }}</strong>{{ frameAge(tile) || L('Поток физически закрыт','Transport is physically closed') }}</div>
            <div v-else-if="tile.state.state==='camera-unavailable' || tile.state.state==='offline'" class="cw-banner"><strong>{{ statusLabel(tile) }}</strong>{{ reconnectHint(tile) || tile.state.error || L('Источник недоступен','Source unavailable') }}</div>
            <!-- Alpha 2.875: причина видна и во время переподключения. Прежде текст ошибки
                 существовал в состоянии, но показать его было негде: полоса рисовалась только
                 у camera-unavailable и offline, а плитка висела в «переподключении». -->
            <div v-else-if="tile.state.state==='reconnecting' && tile.state.error" class="cw-banner"><strong>{{ statusLabel(tile) }}</strong>{{ tile.state.error }}</div>
            <div class="cw-tile-bottom"><span class="cw-state" :class="stateClass(tile)" :title="reasonText(tile)"><span class="cw-state-dot"></span>{{ statusLabel(tile) }}<template v-if="reasonText(tile)"> · {{ reasonText(tile) }}</template></span><span class="cw-transport" :title="freshnessHint(tile)">{{ transportText(tile.state.transport) }}<template v-if="tile.state.fallback"> · fallback</template><template v-if="freshnessShort(tile)"> · {{ freshnessShort(tile) }}</template></span></div>
          </article>
        </div>
        <button v-if="fullscreenId" class="cw-btn cw-fullscreen-exit" @click="toggleFullscreen(fullscreenId)">{{ L('Выйти из полного экрана','Exit fullscreen') }}</button>
      </main>
    </div>
    </template>
  </section></transition></teleport>`,
};
