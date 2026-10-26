// SPDX-License-Identifier: MPL-2.0
// SPDX-FileCopyrightText: 2025-2026 3DiWell Team
// This Source Code Form is subject to the terms of the Mozilla Public License, v. 2.0.
// If a copy of the MPL was not distributed with this file, You can obtain one at
// https://mozilla.org/MPL/2.0/.
export const MAX_TILES = 25;

const LAYOUTS = [
  [1, 1, 1],
  [2, 2, 1],
  [4, 2, 2],
  [6, 3, 2],
  [9, 3, 3],
  [12, 4, 3],
  [16, 4, 4],
  [20, 5, 4],
  [25, 5, 5],
];

export function layoutForCount(value) {
  const count = Math.max(1, Math.min(MAX_TILES, Number(value) || 1));
  const match = LAYOUTS.find(([capacity]) => count <= capacity) || LAYOUTS[LAYOUTS.length - 1];
  return Object.freeze({ count, columns: match[1], rows: match[2] });
}

export function gridStyleForCount(count) {
  const layout = layoutForCount(count);
  return {
    '--cw-columns': String(layout.columns),
    '--cw-rows': String(layout.rows),
  };
}
