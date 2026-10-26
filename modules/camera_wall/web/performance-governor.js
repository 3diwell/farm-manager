// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
export const GOVERNOR_MODES = Object.freeze(['auto', 'economy']);

// Alpha 2.871. Потолок «4 плитки, из них 2 камеры Bambu» стоял здесь не от осторожности:
// каждая камера Bambu перекодировалась сервером и стоила около 0,4 ядра. С путём без
// перекодирования (ядро 2.870+) сервер тратит в 250 раз меньше, и ограничивать надо уже не
// сервер, а браузер — сколько потоков он успевает декодировать. Поэтому потолок поднят, а
// решает по-прежнему ИЗМЕРЕНИЕ: лестница растёт только при спокойном интерфейсе и
// откатывается при задержках. Числа ниже — верхняя граница, а не обещание.
export const GOVERNOR_LIMITS = Object.freeze({
  startTotalLiveBudget: 4,      // столько показываем сразу: серверу это ничего не стоит
  maxTotalLiveBudget: 16,       // выше не поднимаемся даже на мощной машине
  growStep: 2,                  // +2 плитки за шаг
  growEveryMs: 8000,            // не чаще раза в 8 секунд спокойной работы
  maxExpensiveLiveBudget: 2,    // для путей с перекодированием (запасной MJPEG) — как было
});

export const GOVERNOR_TIMING = Object.freeze({
  streamStartSpacingMs: 250,
  snapshotRefreshSpacingMs: 1000,
  maxConcurrentSnapshotRefreshes: 1,
  minimumStabilitySamples: 15,
  stableP95LagMs: 80,
  overloadLagMs: 250,
  overloadSamples: 5,
  protectionStepSpacingMs: 5000,
  recoverySamples: 15,
  recoveryStepSpacingMs: 20000,
});

const ACTIVE_STATES = new Set(['connecting', 'live', 'reconnecting']);

export function priorityOf(tile) {
  return (tile.fullscreen ? 1000 : 0) +
    (tile.pinned ? 500 : 0) +
    (tile.printing ? 200 : 0) +
    (tile.visible ? 100 : 0) +
    (tile.recentlySelected ? 50 : 0);
}

function canAdd(tile, chosen, expensive, limits) {
  if (chosen.length >= limits.totalLiveBudget) return false;
  return tile.costClass !== 'expensive-server' || expensive < limits.expensiveServerLiveBudget;
}

function stableOrder(a, b) {
  const score = priorityOf(b) - priorityOf(a);
  if (score) return score;
  return (b.selectedAt || 0) - (a.selectedAt || 0) || String(a.id).localeCompare(String(b.id));
}

export function chooseStableLiveSet(tiles, limits) {
  const eligible = (tiles || []).filter((tile) => tile.eligible !== false && !tile.isSnapshot);
  const ordered = eligible.slice().sort(stableOrder);
  const chosen = [];
  let expensive = 0;
  const add = (tile) => {
    if (!canAdd(tile, chosen, expensive, limits)) return false;
    chosen.push(tile.id);
    if (tile.costClass === 'expensive-server') expensive += 1;
    return true;
  };
  ordered.forEach(add);
  return { chosen, expensive };
}

// Backward-compatible pure helper used by the original contract tests.
export function chooseLiveSet(tiles, limits) { return chooseStableLiveSet(tiles, limits).chosen; }

export class EventLoopLagClock {
  constructor(options = {}) {
    this.now = options.now || (() => Date.now());
    this.onSample = options.onSample || (() => {});
    this.intervalMs = Math.max(1, Number(options.intervalMs) || 1000);
    this.expectedAt = 0;
  }

  reset() { this.expectedAt = this.now() + this.intervalMs; }

  sample() {
    const current = this.now();
    if (!this.expectedAt) this.reset();
    const lag = Math.max(0, current - this.expectedAt);
    this.expectedAt = current + this.intervalMs;
    this.onSample(lag);
    return lag;
  }
}

export class PerformanceGovernor {
  constructor(options = {}) {
    this.now = options.now || (() => Date.now());
    this.localWindow = options.localWindow !== false;
    this.hardwareConcurrency = Number(options.hardwareConcurrency || 1);
    this.timing = { ...GOVERNOR_TIMING, ...(options.timing || {}) };
    this.mode = 'auto';
    this.startedAt = this.now();
    this.hidden = false;
    this.lastStartAt = 0;
    this.starts = 0;
    this.lagSamples = [];
    this.budgets = { ...GOVERNOR_LIMITS, ...(options.limits || {}) };
    this.earnedTotalLiveBudget = this.budgets.startTotalLiveBudget;
    this.earnedExpensiveLiveBudget = 1;
    this.lastGrowthAt = this.startedAt;
    this.protectionPenalty = 0;
    this.overloadStreak = 0;
    this.recoveryStreak = 0;
    this.lastProtectionChangeAt = 0;
    this.liveOwners = [];
    this.replacementCredits = 0;
    this.snapshotCursor = 0;
    this.snapshotSignature = '';
    this.lastSnapshotAt = 0;
    this.snapshotOpportunities = 0;
    this.requestedId = '';
  }

  setMode(mode) {
    const next = mode === 'economy' ? 'economy' : 'auto';
    if (next === this.mode) return;
    this.mode = next;
    this.replacementCredits = 0;
  }

  setHidden(hidden) {
    const next = !!hidden;
    if (next === this.hidden) return;
    this.hidden = next;
    this.overloadStreak = 0;
    this.recoveryStreak = 0;
    this.lagSamples = [];
    if (!next) {
      this.lastStartAt = 0;
      this.starts = 0;
      this.snapshotSignature = '';
      this.replacementCredits = 0;
    }
  }

  requestImmediate(id) { this.requestedId = String(id || ''); }
  // Per-source protocol/network failures own their retry policy and are not a
  // signal of global browser performance. Retained as compatibility no-ops.
  noteCameraFailure() {}
  noteReconnectStorm() {}

  recordEventLoopLag(value) {
    if (this.hidden) return;
    const lag = Math.max(0, Number(value) || 0);
    this.lagSamples.push(lag);
    if (this.lagSamples.length > 30) this.lagSamples.shift();
    if (lag > this.timing.overloadLagMs) {
      this.overloadStreak += 1;
      this.recoveryStreak = 0;
      if (this.overloadStreak >= this.timing.overloadSamples &&
          this.now() - this.lastProtectionChangeAt >= this.timing.protectionStepSpacingMs) {
        this.protectionPenalty = Math.min(3, this.protectionPenalty + 1);
        this.lastProtectionChangeAt = this.now();
        this.overloadStreak = 0;
      }
    } else if (lag <= this.timing.stableP95LagMs) {
      this.overloadStreak = 0;
      this.recoveryStreak += 1;
      if (this.protectionPenalty > 0 && this.recoveryStreak >= this.timing.recoverySamples &&
          this.now() - this.lastProtectionChangeAt >= this.timing.recoveryStepSpacingMs) {
        this.protectionPenalty -= 1;
        this.lastProtectionChangeAt = this.now();
        this.recoveryStreak = 0;
      }
    } else {
      // Moderate jitter neither earns an upgrade nor revokes earned capacity.
      this.overloadStreak = 0;
      this.recoveryStreak = 0;
    }
  }

  lagP95() {
    const sorted = this.lagSamples.slice().sort((a, b) => a - b);
    return sorted.length ? sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * 0.95))] : Infinity;
  }

  stabilitySatisfied() {
    return this.lagSamples.length >= this.timing.minimumStabilitySamples &&
      this.lagP95() <= this.timing.stableP95LagMs;
  }

  limits() {
    if (this.mode === 'economy') return { expensiveServerLiveBudget: 1, totalLiveBudget: 2 };
    const cfg = this.budgets;
    const now = this.now();
    // Растём ТОЛЬКО по измерению: интерфейс спокоен (p95 задержки цикла в норме) и с прошлого
    // шага прошло достаточно времени. Никаких «через 20 секунд точно можно» вслепую.
    if (this.stabilitySatisfied() && now - this.lastGrowthAt >= cfg.growEveryMs) {
      if (this.earnedTotalLiveBudget < cfg.maxTotalLiveBudget) {
        this.earnedTotalLiveBudget = Math.min(cfg.maxTotalLiveBudget,
                                              this.earnedTotalLiveBudget + cfg.growStep);
        this.lastGrowthAt = now;
      }
      if (this.earnedExpensiveLiveBudget < cfg.maxExpensiveLiveBudget
          && this.localWindow && this.hardwareConcurrency >= 5) {
        this.earnedExpensiveLiveBudget = cfg.maxExpensiveLiveBudget;
      }
    }
    let total = this.earnedTotalLiveBudget;
    let expensive = this.earnedExpensiveLiveBudget;
    // Откат при задержках — заметный, а не по одной плитке: на шестнадцати потоках шаг в
    // единицу не спасёт слабую машину, и человек будет смотреть на рывки минутами.
    let penalty = this.protectionPenalty;
    while (penalty > 0) {
      if (total > 2) total = Math.max(2, Math.round(total * 0.6));
      else if (expensive > 1) expensive -= 1;
      penalty -= 1;
    }
    return { expensiveServerLiveBudget: Math.min(cfg.maxExpensiveLiveBudget, expensive),
             totalLiveBudget: Math.min(cfg.maxTotalLiveBudget, total) };
  }

  reason() {
    if (this.mode === 'economy') return 'economy';
    this.limits();
    if (this.protectionPenalty > 0) return 'protection-ui-lag';
    const platformExpensiveMax = this.localWindow && this.hardwareConcurrency >= 5
      ? this.budgets.maxExpensiveLiveBudget : 1;
    return this.earnedTotalLiveBudget >= this.budgets.maxTotalLiveBudget
      && this.earnedExpensiveLiveBudget >= platformExpensiveMax ? 'stable' : 'warming-up';
  }

  planStreams(streamTiles, limits) {
    const eligible = (streamTiles || []).filter((tile) => tile.eligible !== false && !tile.isSnapshot);
    const byId = new Map(eligible.map((tile) => [tile.id, tile]));
    const previousOwners = this.liveOwners.filter((id) => byId.has(id));
    const chosen = [];
    let expensive = 0;
    const add = (tile) => {
      if (!tile || chosen.includes(tile.id) || !canAdd(tile, chosen, expensive, limits)) return false;
      chosen.push(tile.id);
      if (tile.costClass === 'expensive-server') expensive += 1;
      return true;
    };
    const remove = (tile) => {
      const index = chosen.indexOf(tile.id);
      if (index < 0) return;
      chosen.splice(index, 1);
      if (tile.costClass === 'expensive-server') expensive -= 1;
    };

    // Fullscreen/pinned sources are mandatory where the hard caps permit it.
    eligible.filter((tile) => tile.fullscreen || tile.pinned).sort(stableOrder).forEach(add);
    // Existing healthy owners are considered before any unowned source. Sorting
    // only matters when a reduced budget requires the lowest-priority eviction.
    previousOwners.map((id) => byId.get(id)).filter(Boolean).sort(stableOrder).forEach(add);

    const requested = this.requestedId ? byId.get(this.requestedId) : null;
    if (requested && !chosen.includes(requested.id)) {
      while (!canAdd(requested, chosen, expensive, limits)) {
        const needsExpensiveSlot = requested.costClass === 'expensive-server' && expensive >= limits.expensiveServerLiveBudget;
        const candidates = chosen.map((id) => byId.get(id)).filter((tile) =>
          tile && !tile.fullscreen && !tile.pinned && (!needsExpensiveSlot || tile.costClass === 'expensive-server'));
        candidates.sort((a, b) => priorityOf(a) - priorityOf(b) || (a.selectedAt || 0) - (b.selectedAt || 0) || String(b.id).localeCompare(String(a.id)));
        if (!candidates.length) break;
        remove(candidates[0]);
      }
      if (!add(requested)) this.requestedId = '';
    } else if (this.requestedId && streamTiles.some((tile) => tile.id === this.requestedId) && !requested) {
      // An ineligible/offline stream cannot retain a pending one-shot request.
      this.requestedId = '';
    }

    eligible.slice().sort(stableOrder).forEach(add);
    const released = this.liveOwners.filter((id) => !chosen.includes(id)).length;
    this.liveOwners = chosen.slice();
    return { chosen, expensive, released };
  }

  reconcileSnapshots(snapshotTiles, registry) {
    const eligible = snapshotTiles.filter((tile) => tile.eligible !== false);
    const signature = eligible.map((tile) => tile.id).sort().join('|');
    if (signature !== this.snapshotSignature) {
      this.snapshotSignature = signature;
      this.snapshotCursor = 0;
    }
    if (!eligible.length || registry.snapshotRefreshActiveCount() >= this.timing.maxConcurrentSnapshotRefreshes) return '';
    const requestedIndex = this.requestedId ? eligible.findIndex((tile) => tile.id === this.requestedId) : -1;
    const due = requestedIndex >= 0 || this.snapshotOpportunities === 0 || this.now() - this.lastSnapshotAt >= this.timing.snapshotRefreshSpacingMs;
    if (!due) return '';
    const start = requestedIndex >= 0 ? requestedIndex : (this.snapshotCursor % eligible.length);
    for (let offset = 0; offset < eligible.length; offset += 1) {
      const tile = eligible[(start + offset) % eligible.length];
      if (registry.refreshSnapshot(tile.id)) {
        this.snapshotCursor = (start + offset + 1) % eligible.length;
        this.lastSnapshotAt = this.now();
        this.snapshotOpportunities += 1;
        if (this.requestedId === tile.id) this.requestedId = '';
        return tile.id;
      }
    }
    return '';
  }

  canStartSequentially() { return this.starts === 0 || this.now() - this.lastStartAt >= this.timing.streamStartSpacingMs; }

  reconcile(tiles, registry) {
    // The owner (visibility/collapse lifecycle) performs the physical teardown
    // once and preserves its suspension metadata. Hidden reconciliations are inert.
    if (this.hidden) return [];
    const models = tiles || [];
    // Eligibility is also a teardown boundary. In fullscreen this closes any
    // already-running background Snapshot request before the refresh queue runs.
    let current = registry.snapshot();
    for (const tile of models) {
      const view = current[tile.id] || {};
      if (tile.eligible === false && (view.activeTransport || (ACTIVE_STATES.has(view.state) && !view.reconnectAt))) registry.pause(tile.id);
    }
    const snapshots = models.filter((tile) => tile.isSnapshot);
    this.reconcileSnapshots(snapshots, registry);

    const streams = models.filter((tile) => !tile.isSnapshot);
    const planned = this.planStreams(streams, this.limits());
    const chosen = planned.chosen;
    const wanted = new Set(chosen);
    let snapshot = registry.snapshot();
    let releasedActive = 0;
    for (const tile of streams) {
      const view = snapshot[tile.id] || {};
      if (!wanted.has(tile.id) && (view.activeTransport || (ACTIVE_STATES.has(view.state) && !view.reconnectAt))) {
        registry.pause(tile.id);
        releasedActive += 1;
      }
    }
    this.replacementCredits += Math.max(releasedActive, planned.released || 0);
    snapshot = registry.snapshot();
    const next = chosen.find((id) => {
      const view = snapshot[id] || {};
      return !view.activeTransport && !ACTIVE_STATES.has(view.state) && !(view.reconnectAt && !view.retryReady);
    });
    if (next == null) {
      if (this.requestedId && chosen.includes(this.requestedId)) this.requestedId = '';
      return chosen;
    }
    const fullscreenNext = streams.some((tile) => tile.id === next && tile.fullscreen);
    const requestedNext = this.requestedId === next;
    const replacement = this.replacementCredits > 0;
    if (!fullscreenNext && !requestedNext && !this.canStartSequentially()) return chosen;
    const started = registry.start(next);
    if (started) {
      this.lastStartAt = this.now();
      this.starts += 1;
      if (replacement) this.replacementCredits = Math.max(0, this.replacementCredits - 1);
    }
    // Manual reconnect is a one-shot attempt.
    if (requestedNext) this.requestedId = '';
    return chosen;
  }
}
