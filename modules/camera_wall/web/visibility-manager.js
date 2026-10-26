// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
export class VisibilityManager {
  constructor(options = {}) {
    this.document = options.document || globalThis.document;
    this.IntersectionObserver = options.IntersectionObserver || globalThis.IntersectionObserver;
    this.onHidden = options.onHidden || (() => {});
    this.onVisible = options.onVisible || (() => {});
    this.onTileVisibility = options.onTileVisibility || (() => {});
    this.observer = null;
    this.bound = false;
    this.handleVisibility = () => {
      if (this.document.hidden) this.onHidden();
      else this.onVisible();
    };
  }

  start() {
    if (this.bound) return;
    this.bound = true;
    this.document.addEventListener('visibilitychange', this.handleVisibility);
    if (this.IntersectionObserver) {
      this.observer = new this.IntersectionObserver((entries) => {
        for (const entry of entries) {
          const id = entry.target && entry.target.dataset ? entry.target.dataset.cameraId : '';
          if (id) this.onTileVisibility(id, !!entry.isIntersecting);
        }
      }, { threshold: 0.05 });
    }
    this.handleVisibility();
  }

  observe(element) { if (this.observer && element) this.observer.observe(element); }
  unobserve(element) { if (this.observer && element) this.observer.unobserve(element); }

  stop() {
    if (!this.bound) return;
    this.bound = false;
    this.document.removeEventListener('visibilitychange', this.handleVisibility);
    if (this.observer) this.observer.disconnect();
    this.observer = null;
  }
}
