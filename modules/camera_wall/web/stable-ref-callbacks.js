// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
export class StableRefCallbacks {
  constructor(bind) {
    this.bind = bind;
    this.callbacks = new Map();
  }

  get(id) {
    const key = String(id);
    let callback = this.callbacks.get(key);
    if (!callback) {
      callback = (element) => this.bind(key, element);
      this.callbacks.set(key, callback);
    }
    return callback;
  }

  delete(id) { this.callbacks.delete(String(id)); }
  clear() { this.callbacks.clear(); }
  get size() { return this.callbacks.size; }
}
